# -*- coding: utf-8 -*-
"""
SentenceTransformer 임베딩 시간 측정 스크립트
GPU: RTX 3080 사용
- 입력: fetch_arxiv.py가 저장한 result/embedding/documents.json (제목+초록)
"""
import os
import time
import json
import numpy as np
import torch
from sentence_transformers import SentenceTransformer

# arXiv 논문 제목+초록 로드 (fetch_arxiv.py 먼저 실행 필요)
documents_path = "result/embedding/documents.json"
if not os.path.exists(documents_path):
    raise FileNotFoundError(
        f"{documents_path} 파일이 없습니다. 먼저 fetch_arxiv.py를 실행하세요."
    )

with open(documents_path, "r", encoding="utf-8") as f:
    documents = json.load(f)

print(f"Loaded {len(documents)} documents from {documents_path}")

print("=" * 60)
print("SentenceTransformer Embedding Time Measurement")
print("=" * 60)

# GPU 확인
print(f"\nPyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU device: {torch.cuda.get_device_name(0)}")
    print(f"CUDA version: {torch.version.cuda}")
    device = 'cuda'
else:
    print("Using CPU")
    device = 'cpu'

# 모델 로딩 시간 측정
print("\n" + "-" * 60)
print("Loading model...")
model_load_start = time.time()

model = SentenceTransformer('all-mpnet-base-v2', device=device)

model_load_end = time.time()
model_load_time = model_load_end - model_load_start
print(f"Model load time: {model_load_time:.4f} sec")

# 단어 수 출력
print(f"\nTotal documents: {len(documents)}")

# 워밍업
print("\n" + "-" * 60)
print("GPU warmup...")
_ = model.encode(["warmup test"])
print("Warmup done")

# 임베딩 시간 측정
print("\n" + "-" * 60)
print("Starting embedding...")

# 배치 임베딩 시간 측정
batch_start = time.time()
batch_embeddings = model.encode(documents)
batch_end = time.time()
batch_time = batch_end - batch_start

# 결과 출력
print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)

print(f"\n[Batch Embedding]")
print(f"  Total time: {batch_time:.4f} sec")
print(f"  Per document avg: {batch_time/len(documents)*1000:.4f} ms")

print(f"\n[Embedding dimension]")
print(f"  Vector shape: {batch_embeddings.shape}")

# 샘플 출력
print(f"\n[Sample - first document embedding]")
print(f"  First 10 values: {batch_embeddings[0][:10]}")

# 결과 저장
os.makedirs("result/embedding", exist_ok=True)

# 임베딩 벡터 저장
np.save("result/embedding/embeddings.npy", batch_embeddings)

# documents.json은 fetch_arxiv.py가 이미 저장했으므로 덮어쓰지 않음

# 결과 요약 저장
result_summary = {
    "model": "all-mpnet-base-v2",
    "device": device,
    "total_documents": len(documents),
    "embedding_shape": list(batch_embeddings.shape),
    "model_load_time_sec": round(model_load_time, 4),
    "embedding_time_sec": round(batch_time, 4),
    "per_document_avg_ms": round(batch_time / len(documents) * 1000, 4),
}
with open("result/embedding/result.json", "w", encoding="utf-8") as f:
    json.dump(result_summary, f, ensure_ascii=False, indent=2)

print(f"\nResults saved to result/embedding/")
print(f"  - embeddings.npy ({batch_embeddings.shape})")
print(f"  - documents.json ({len(documents)} docs)")
print(f"  - result.json")

print("\n" + "=" * 60)
print("Done!")
print("=" * 60)
