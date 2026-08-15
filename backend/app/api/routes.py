"""API routes: the chat endpoint plus health and a retrieval debug endpoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.db.database import healthcheck
from app.db.models import corpus_stats
from app.rag.generation import answer_question
from app.rag.retrieval import retrieve
from app.schemas.chat import ChatRequest, ChatResponse, HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        database=healthcheck(),
        gemini_configured=settings.has_gemini,
    )


@router.post("/api/chat", response_model=ChatResponse, tags=["rag"])
def chat(req: ChatRequest) -> ChatResponse:
    if not settings.has_gemini:
        raise HTTPException(status_code=503, detail="Gemini API key is not configured.")
    try:
        result = answer_question(req.question, product=req.product)
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat pipeline failed")
        raise HTTPException(status_code=502, detail=f"Generation failed: {exc}") from exc
    return ChatResponse(**result)


@router.get("/api/stats", tags=["ops"])
def stats() -> dict:
    return corpus_stats()


@router.get("/api/debug/retrieve", tags=["rag"])
def debug_retrieve(q: str, k: int = 5, product: str | None = None) -> dict:
    """Inspect raw retrieval — invaluable while tuning the corpus and threshold."""
    chunks, latency_ms = retrieve(q, top_k=k, product=product)
    return {
        "query": q,
        "latency_ms": latency_ms,
        "results": [
            {
                "rank": i + 1,
                "title": c.title,
                "section": c.section,
                "product": c.product,
                "similarity": c.similarity,
                "distance": round(c.distance, 4),
                "url": c.source_url,
                "preview": c.content[:280] + ("…" if len(c.content) > 280 else ""),
            }
            for i, c in enumerate(chunks)
        ],
    }
