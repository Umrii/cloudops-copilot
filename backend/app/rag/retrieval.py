"""Vector retrieval over pgvector.

Cosine distance via the `<=>` operator. We also apply a distance ceiling so that
when nothing is genuinely relevant, retrieval returns an empty list and the
generator can honestly decline instead of grounding on noise.
"""
from __future__ import annotations

import logging
import time

import numpy as np

from app.config import settings
from app.db.database import get_conn
from app.db.models import RetrievedChunk
from app.rag.embeddings import embed_query

logger = logging.getLogger(__name__)


def retrieve(
    question: str,
    *,
    top_k: int | None = None,
    product: str | None = None,
    max_distance: float | None = None,
) -> tuple[list[RetrievedChunk], float]:
    """Return (chunks, latency_ms). Chunks are ordered nearest-first."""
    top_k = top_k or settings.top_k
    max_distance = settings.max_distance if max_distance is None else max_distance

    q_vec = np.asarray(embed_query(question), dtype=np.float32)

    where = ""
    params: list[object] = [q_vec]
    if product:
        where = "WHERE c.metadata->>'product' = %s"
        params.append(product)
    params.append(q_vec)  # for ORDER BY
    params.append(top_k)

    sql = f"""
        SELECT c.id, c.document_id, d.title, d.source_url, d.product,
               c.section, c.content,
               (c.embedding <=> %s) AS distance
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        {where}
        ORDER BY c.embedding <=> %s
        LIMIT %s
    """

    start = time.perf_counter()
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    results: list[RetrievedChunk] = []
    for r in rows:
        distance = float(r[7])
        if distance > max_distance:
            continue  # below the relevance threshold — discard
        results.append(
            RetrievedChunk(
                chunk_id=r[0],
                document_id=r[1],
                title=r[2],
                source_url=r[3],
                product=r[4],
                section=r[5],
                content=r[6],
                distance=distance,
            )
        )

    logger.info(
        "retrieved %d/%d chunks (threshold=%.2f) in %.1fms",
        len(results), len(rows), max_distance, latency_ms,
    )
    return results, latency_ms
