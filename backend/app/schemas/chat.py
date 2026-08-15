"""Pydantic request/response models for the API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    product: str | None = Field(
        default=None,
        description="Optional product filter, e.g. 'cloud_run', to scope retrieval.",
    )


class Source(BaseModel):
    title: str
    url: str
    product: str | None = None
    section: str | None = None
    relevance: float


class RetrievalInfo(BaseModel):
    chunks_used: int
    latency_ms: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    grounded: bool
    retrieval: RetrievalInfo


class HealthResponse(BaseModel):
    status: str
    database: bool
    gemini_configured: bool
