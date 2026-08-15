"""Grounded answer generation with Gemini.

Ties the pipeline together: retrieve -> build prompt -> generate -> attach the
sources actually shown to the model as citations.
"""
from __future__ import annotations

import logging

from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.db.models import RetrievedChunk
from app.rag.embeddings import get_client
from app.rag.prompts import SYSTEM_PROMPT, build_user_prompt
from app.rag.retrieval import retrieve

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True,
)
def _generate(system_prompt: str, user_prompt: str) -> str:
    client = get_client()
    resp = client.models.generate_content(
        model=settings.generation_model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2,
            max_output_tokens=2048,
            # gemini-2.5-flash "thinks" by default, and those thinking tokens are
            # drawn from max_output_tokens — long thinking silently truncates the
            # visible answer. Grounded extraction from retrieved docs doesn't need
            # it, so we disable thinking for stable, complete, cheaper answers.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return (resp.text or "").strip()


def _sources_payload(chunks: list[RetrievedChunk]) -> list[dict]:
    """De-duplicate by document, keeping the best (nearest) similarity."""
    seen: dict[str, dict] = {}
    for c in chunks:
        key = c.source_url
        if key not in seen or c.similarity > seen[key]["relevance"]:
            seen[key] = {
                "title": c.title,
                "url": c.source_url,
                "product": c.product,
                "section": c.section,
                "relevance": c.similarity,
            }
    return sorted(seen.values(), key=lambda s: s["relevance"], reverse=True)


def answer_question(
    question: str,
    *,
    product: str | None = None,
) -> dict:
    """Full RAG turn. Returns answer, sources, and retrieval diagnostics."""
    chunks, latency_ms = retrieve(question, product=product)

    user_prompt = build_user_prompt(question, chunks)
    answer = _generate(SYSTEM_PROMPT, user_prompt)

    return {
        "answer": answer,
        "sources": _sources_payload(chunks),
        "grounded": bool(chunks),
        "retrieval": {
            "chunks_used": len(chunks),
            "latency_ms": latency_ms,
        },
    }
