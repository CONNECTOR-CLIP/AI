"""SPECTER2 document embeddings backed by Hugging Face weights."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any, Dict, List


_BASE_MODEL = os.getenv("SPECTER2_BASE_MODEL", "allenai/specter2_base")
_ADAPTER_MODEL = os.getenv("SPECTER2_ADAPTER_MODEL", "allenai/specter2")
_BATCH_SIZE = int(os.getenv("SPECTER2_BATCH_SIZE", "16"))
_MAX_LENGTH = int(os.getenv("SPECTER2_MAX_LENGTH", "512"))

_tokenizer = None
_model = None
_device = None
_load_lock = threading.Lock()
_inference_lock = threading.Lock()


def _load_model():
    """Load the official base model and retrieval/proximity adapter once."""
    global _tokenizer, _model, _device
    if _model is not None:
        return _tokenizer, _model, _device
    with _load_lock:
        if _model is not None:
            return _tokenizer, _model, _device
        try:
            import torch
            from adapters import AutoAdapterModel
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "SPECTER2 requires torch, transformers, and adapters. "
                "Install the project dependencies before running CoT5."
            ) from exc

        tokenizer = AutoTokenizer.from_pretrained(_BASE_MODEL)
        model = AutoAdapterModel.from_pretrained(_BASE_MODEL)
        model.load_adapter(
            _ADAPTER_MODEL, source="hf", load_as="specter2", set_active=True
        )
        model.set_active_adapters("specter2")
        requested = os.getenv("SPECTER2_DEVICE", "auto").lower()
        if requested == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device = requested
        model.to(device)
        model.eval()
        _tokenizer, _model, _device = tokenizer, model, device
        return _tokenizer, _model, _device


def _encode_papers(papers: List[Dict[str, Any]]) -> List[List[float]]:
    tokenizer, model, device = _load_model()
    import torch
    texts = [
        f"{paper.get('title') or ''}{tokenizer.sep_token}{paper.get('abstract') or ''}"
        for paper in papers
    ]
    embeddings: List[List[float]] = []
    # A single model instance is shared process-wide. Serialize forward passes so
    # concurrent retrieval branches cannot race on device memory.
    with _inference_lock, torch.inference_mode():
        for start in range(0, len(texts), max(1, _BATCH_SIZE)):
            batch = texts[start:start + max(1, _BATCH_SIZE)]
            inputs = tokenizer(
                batch,
                padding=True,
                truncation=True,
                return_tensors="pt",
                return_token_type_ids=False,
                max_length=_MAX_LENGTH,
            )
            inputs = {key: value.to(device) for key, value in inputs.items()}
            output = model(**inputs)
            # Official SPECTER2 usage takes the first-token representation.
            cls_embeddings = output.last_hidden_state[:, 0, :].detach().cpu()
            embeddings.extend(cls_embeddings.tolist())
    return embeddings


async def get_embeddings_ideapapers(
    idea_papers: List[Dict[str, Any]] | Dict[str, Dict[str, Any]], reformat: bool = True
) -> Dict[str, Any]:
    if not idea_papers:
        return {}
    if reformat and isinstance(idea_papers, list):
        idea_papers = {
            str(paper["corpusId"]): dict(paper)
            for paper in idea_papers
            if paper.get("corpusId") is not None
        }
    elif isinstance(idea_papers, dict):
        idea_papers = {str(key): value for key, value in idea_papers.items()}

    keys = list(idea_papers)
    papers = [idea_papers[key] for key in keys]
    vectors = await asyncio.to_thread(_encode_papers, papers)
    for key, vector in zip(keys, vectors):
        idea_papers[key]["embedding"] = vector
    return idea_papers
