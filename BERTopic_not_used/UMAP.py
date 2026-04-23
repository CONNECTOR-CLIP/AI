# -*- coding: utf-8 -*-
"""
UMAP 차원 축소 스크립트
- result/embedding/embeddings.npy를 읽어서 UMAP으로 차원 축소
- 결과를 result/UMAP에 저장
"""
import os
import time
import json
import numpy as np
import umap

print("=" * 60)
print("UMAP Dimensionality Reduction")
print("=" * 60)

# 임베딩 로드
print("\nLoading embeddings from result/embedding/embeddings.npy ...")
embeddings = np.load("result/embedding/embeddings.npy")
print(f"Loaded embeddings shape: {embeddings.shape}")

# UMAP 설정 (BERTopic 기본값 기반)
n_neighbors = 15
n_components = 5
min_dist = 0.0
metric = "cosine"

print(f"\nUMAP parameters:")
print(f"  n_neighbors:  {n_neighbors}")
print(f"  n_components: {n_components}")
print(f"  min_dist:     {min_dist}")
print(f"  metric:       {metric}")

# UMAP 실행
print("\n" + "-" * 60)
print("Running UMAP...")

umap_start = time.time()

umap_model = umap.UMAP(
    n_neighbors=n_neighbors,
    n_components=n_components,
    min_dist=min_dist,
    metric=metric,
    random_state=42,
)
umap_embeddings = umap_model.fit_transform(embeddings)

umap_end = time.time()
umap_time = umap_end - umap_start

# 결과 출력
print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)
print(f"\n[UMAP Reduction]")
print(f"  Input shape:  {embeddings.shape}")
print(f"  Output shape: {umap_embeddings.shape}")
print(f"  Total time:   {umap_time:.4f} sec")

# 결과 저장
os.makedirs("result/UMAP", exist_ok=True)

np.save("result/UMAP/umap_embeddings.npy", umap_embeddings)

result_summary = {
    "input_shape": list(embeddings.shape),
    "output_shape": list(umap_embeddings.shape),
    "n_neighbors": n_neighbors,
    "n_components": n_components,
    "min_dist": min_dist,
    "metric": metric,
    "umap_time_sec": round(umap_time, 4),
}
with open("result/UMAP/result.json", "w", encoding="utf-8") as f:
    json.dump(result_summary, f, ensure_ascii=False, indent=2)

print(f"\nResults saved to result/UMAP/")
print(f"  - umap_embeddings.npy ({umap_embeddings.shape})")
print(f"  - result.json")

print("\n" + "=" * 60)
print("Done!")
print("=" * 60)
