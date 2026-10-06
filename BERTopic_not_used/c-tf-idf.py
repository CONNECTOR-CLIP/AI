# -*- coding: utf-8 -*-
"""
c-TF-IDF 토픽 추출 스크립트
- result/HDBSCAN/labels.npy와 result/embedding/documents.json을 읽어서
- 클러스터별 c-TF-IDF를 계산하여 토픽 키워드 추출
- 결과를 result/c-tf-idf에 저장
"""
import os
import time
import json
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.preprocessing import normalize
from sklearn.utils import check_array
import scipy.sparse as sp


class ClassTfidfTransformer:
    """BERTopic의 c-TF-IDF 구현.

    클래스(클러스터)별 문서를 합친 뒤, 클래스 단위 TF-IDF를 계산.
    TF = L1 정규화된 단어 빈도
    IDF = log(클래스당 평균 단어 수 / 전체 클래스에서의 단어 빈도 + 1)
    """

    def fit(self, X):
        X = check_array(X, accept_sparse=("csr", "csc"))
        if not sp.issparse(X):
            X = sp.csr_matrix(X)

        # 전체 클래스에서 각 단어의 빈도 합
        df = np.squeeze(np.asarray(X.sum(axis=0)))
        # 클래스당 평균 단어 수
        avg_nr_samples = int(X.sum(axis=1).mean())
        # IDF 계산
        idf = np.log((avg_nr_samples / df) + 1)

        self._idf_diag = sp.diags(
            idf, offsets=0,
            shape=(X.shape[1], X.shape[1]),
            format="csr", dtype=np.float64,
        )
        return self

    def transform(self, X):
        X = normalize(X, axis=1, norm="l1", copy=True)
        X = X * self._idf_diag
        return X

    def fit_transform(self, X):
        self.fit(X)
        return self.transform(X)

print("=" * 60)
print("c-TF-IDF Topic Extraction")
print("=" * 60)

# 데이터 로드
print("\nLoading data...")
labels = np.load("result/HDBSCAN/labels.npy")
with open("result/embedding/documents.json", "r", encoding="utf-8") as f:
    documents = json.load(f)

print(f"Documents: {len(documents)}")
print(f"Labels:    {len(labels)}")

n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
print(f"Clusters:  {n_clusters}")

# 클러스터별 문서 합치기 (노이즈 제외)
print("\n" + "-" * 60)
print("Building per-cluster documents...")

cluster_ids = sorted(set(labels))
docs_per_cluster = []
valid_cluster_ids = []

for cluster_id in cluster_ids:
    indices = [i for i, l in enumerate(labels) if l == cluster_id]
    joined = " ".join([documents[i] for i in indices])
    docs_per_cluster.append(joined)
    valid_cluster_ids.append(cluster_id)

print(f"Clusters (including noise): {len(docs_per_cluster)}")

# c-TF-IDF 실행
print("\n" + "-" * 60)
print("Running c-TF-IDF...")

ctfidf_start = time.time()

# Step 1: CountVectorizer로 단어 빈도 행렬 생성
vectorizer = CountVectorizer(stop_words="english")
X = vectorizer.fit_transform(docs_per_cluster)
words = vectorizer.get_feature_names_out()

# Step 2: ClassTfidfTransformer 적용
ctfidf_model = ClassTfidfTransformer()
ctfidf_matrix = ctfidf_model.fit_transform(X)

ctfidf_end = time.time()
ctfidf_time = ctfidf_end - ctfidf_start

# 토픽별 상위 키워드 추출
top_n = 10
topics = {}

for idx, cluster_id in enumerate(valid_cluster_ids):
    row = ctfidf_matrix[idx].toarray().flatten()
    top_indices = row.argsort()[-top_n:][::-1]
    top_words = [(words[i], round(float(row[i]), 4)) for i in top_indices if row[i] > 0]

    cluster_name = "Noise (-1)" if cluster_id == -1 else f"Topic {cluster_id}"
    topics[str(cluster_id)] = {
        "name": cluster_name,
        "keywords": [{"word": w, "score": s} for w, s in top_words],
        "n_documents": list(labels).count(cluster_id),
    }

# 결과 출력
print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)
print(f"\n[c-TF-IDF]")
print(f"  Vocabulary size: {len(words)}")
print(f"  Matrix shape:    {ctfidf_matrix.shape}")
print(f"  Total time:      {ctfidf_time:.4f} sec")

print(f"\n[Topics]")
for cluster_id_str, topic in topics.items():
    keywords_str = ", ".join([f"{kw['word']}({kw['score']:.3f})" for kw in topic["keywords"][:5]])
    print(f"  {topic['name']} ({topic['n_documents']} docs): {keywords_str}")

# 결과 저장
os.makedirs("result/c-tf-idf", exist_ok=True)

# c-TF-IDF 행렬 저장
sp.save_npz("result/c-tf-idf/ctfidf_matrix.npz", ctfidf_matrix)

# 단어 목록 저장
with open("result/c-tf-idf/vocabulary.json", "w", encoding="utf-8") as f:
    json.dump(words.tolist(), f, ensure_ascii=False, indent=2)

# 토픽 결과 저장
result_summary = {
    "vocabulary_size": len(words),
    "ctfidf_shape": list(ctfidf_matrix.shape),
    "ctfidf_time_sec": round(ctfidf_time, 4),
    "top_n_keywords": top_n,
    "topics": topics,
}
with open("result/c-tf-idf/result.json", "w", encoding="utf-8") as f:
    json.dump(result_summary, f, ensure_ascii=False, indent=2)

print(f"\nResults saved to result/c-tf-idf/")
print(f"  - ctfidf_matrix.npz ({ctfidf_matrix.shape})")
print(f"  - vocabulary.json ({len(words)} words)")
print(f"  - result.json")

print("\n" + "=" * 60)
print("Done!")
print("=" * 60)
