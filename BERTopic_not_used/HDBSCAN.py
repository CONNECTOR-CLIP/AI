# -*- coding: utf-8 -*-
"""
HDBSCAN 클러스터링 스크립트
- result/UMAP/umap_embeddings.npy를 읽어서 HDBSCAN으로 클러스터링
- 결과를 result/HDBSCAN에 저장
"""
import os
import time
import json
import numpy as np
import hdbscan

print("=" * 60)
print("HDBSCAN Clustering")
print("=" * 60)

# UMAP 결과 로드
print("\nLoading UMAP embeddings from result/UMAP/umap_embeddings.npy ...")
umap_embeddings = np.load("result/UMAP/umap_embeddings.npy")
print(f"Loaded UMAP embeddings shape: {umap_embeddings.shape}")

# 문서 로드
with open("result/embedding/documents.json", "r", encoding="utf-8") as f:
    documents = json.load(f)

# HDBSCAN 설정 (BERTopic 기본값 기반)
min_cluster_size = 2
min_samples = None
cluster_selection_method = "leaf"
metric = "euclidean"

print(f"\nHDBSCAN parameters:")
print(f"  min_cluster_size:         {min_cluster_size}")
print(f"  min_samples:              {min_samples}")
print(f"  cluster_selection_method: {cluster_selection_method}")
print(f"  metric:                   {metric}")

# HDBSCAN 실행
print("\n" + "-" * 60)
print("Running HDBSCAN...")

hdbscan_start = time.time()

hdbscan_model = hdbscan.HDBSCAN(
    min_cluster_size=min_cluster_size,
    min_samples=min_samples,
    metric=metric,
    cluster_selection_method=cluster_selection_method,
    prediction_data=True,
)
hdbscan_model.fit(umap_embeddings)
labels = hdbscan_model.labels_
probabilities = hdbscan_model.probabilities_

hdbscan_end = time.time()
hdbscan_time = hdbscan_end - hdbscan_start

# 클러스터 분석
n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
n_noise = list(labels).count(-1)

# 클러스터별 문서 매핑
cluster_docs = {}
for i, label in enumerate(labels):
    label_str = str(label)
    if label_str not in cluster_docs:
        cluster_docs[label_str] = []
    cluster_docs[label_str].append({
        "index": i,
        "document": documents[i][:100] + "..." if len(documents[i]) > 100 else documents[i]
    })

# 결과 출력
print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)
print(f"\n[HDBSCAN Clustering]")
print(f"  Total documents: {len(labels)}")
print(f"  Clusters found:  {n_clusters}")
print(f"  Noise points:    {n_noise} (label = -1)")
print(f"  Total time:      {hdbscan_time:.4f} sec")

print(f"\n[Cluster distribution]")
for cluster_id in sorted(set(labels)):
    count = list(labels).count(cluster_id)
    name = "Noise" if cluster_id == -1 else f"Cluster {cluster_id}"
    print(f"  {name}: {count} documents")

# 결과 저장
os.makedirs("result/HDBSCAN", exist_ok=True)

np.save("result/HDBSCAN/labels.npy", labels)
np.save("result/HDBSCAN/probabilities.npy", probabilities)

result_summary = {
    "input_shape": list(umap_embeddings.shape),
    "min_cluster_size": min_cluster_size,
    "min_samples": min_samples,
    "cluster_selection_method": cluster_selection_method,
    "metric": metric,
    "n_clusters": n_clusters,
    "n_noise": n_noise,
    "hdbscan_time_sec": round(hdbscan_time, 4),
    "cluster_distribution": {str(k): list(labels).count(k) for k in sorted(set(labels))},
    "cluster_documents": cluster_docs,
}
with open("result/HDBSCAN/result.json", "w", encoding="utf-8") as f:
    json.dump(result_summary, f, ensure_ascii=False, indent=2)

print(f"\nResults saved to result/HDBSCAN/")
print(f"  - labels.npy ({labels.shape})")
print(f"  - probabilities.npy ({probabilities.shape})")
print(f"  - result.json")

print("\n" + "=" * 60)
print("Done!")
print("=" * 60)
