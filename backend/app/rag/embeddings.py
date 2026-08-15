"""Embeddings via Gemini (gemini-embedding-001).

Two important details this module gets right:

1. task_type — Gemini embeddings are asymmetric. Documents are embedded with
   RETRIEVAL_DOCUMENT and queries with RETRIEVAL_QUERY, which measurably improves
   retrieval over embedding both the same way.

2. Normalization — gemini-embedding-001 only returns unit-normalized vectors at
   its native 3072 dimensions. At output_dimensionality=768 the vectors are NOT
   normalized, so we L2-normalize ourselves. Cosine distance assumes unit norm,
   so skipping this quietly degrades ranking.
"""
from __future__ import annotations

import logging
from typing import Literal

import numpy as np
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.has_gemini:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to prod.env before embedding."
            )
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _l2_normalize(vec: list[float]) -> list[float]:
    arr = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm == 0.0:
        return arr.tolist()
    return (arr / norm).tolist()


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
def _embed_batch(texts: list[str], task_type: TaskType) -> list[list[float]]:
    client = get_client()
    resp = client.models.embed_content(
        model=settings.embedding_model,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=settings.embedding_dim,
        ),
    )
    return [_l2_normalize(e.values) for e in resp.embeddings]


def embed_documents(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Embed a list of document chunks. Batched to limit request count."""
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        out.extend(_embed_batch(batch, "RETRIEVAL_DOCUMENT"))
        logger.info("Embedded %d/%d chunks", min(i + batch_size, len(texts)), len(texts))
    return out


def embed_query(text: str) -> list[float]:
    """Embed a single user query."""
    return _embed_batch([text], "RETRIEVAL_QUERY")[0]
