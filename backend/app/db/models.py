"""Data-access helpers for documents and chunks.

Thin functions over SQL — no ORM. Kept here so ingestion and retrieval share
one definition of how rows are written and read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from psycopg.types.json import Jsonb

from app.db.database import get_conn


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    title: str
    source_url: str
    product: str | None
    section: str | None
    content: str
    distance: float

    @property
    def similarity(self) -> float:
        """Cosine similarity in [0, 1] derived from cosine distance."""
        return round(1.0 - self.distance, 4)


def upsert_document(
    title: str,
    source_url: str,
    product: str | None,
    document_type: str = "documentation",
) -> int:
    """Insert a document (or return the existing id for this source_url)."""
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO documents (title, source_url, product, document_type)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_url)
            DO UPDATE SET title = EXCLUDED.title,
                          product = EXCLUDED.product,
                          document_type = EXCLUDED.document_type
            RETURNING id
            """,
            (title, source_url, product, document_type),
        ).fetchone()
        return int(row[0])


def delete_chunks_for_document(document_id: int) -> None:
    """Remove existing chunks so re-ingesting a doc doesn't duplicate them."""
    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))


def insert_chunks(document_id: int, chunks: Sequence[dict[str, Any]]) -> int:
    """Bulk-insert chunk rows. Each dict carries content/section/embedding/etc."""
    if not chunks:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO chunks
                    (document_id, content, section, chunk_index, token_count,
                     embedding, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        document_id,
                        c["content"],
                        c.get("section"),
                        c.get("chunk_index", 0),
                        c.get("token_count"),
                        np.asarray(c["embedding"], dtype=np.float32),
                        Jsonb(c.get("metadata", {})),
                    )
                    for c in chunks
                ],
            )
    return len(chunks)


def reset_corpus() -> None:
    """Wipe all documents and chunks (chunks cascade). Use before a full re-ingest."""
    with get_conn() as conn:
        conn.execute("TRUNCATE chunks, documents RESTART IDENTITY CASCADE")


def corpus_stats() -> dict[str, int]:
    with get_conn() as conn:
        docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return {"documents": int(docs), "chunks": int(chunks)}
