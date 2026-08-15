"""Prompt construction for grounded generation.

The system prompt enforces grounding: answer only from the supplied context, and
say so plainly when the context is insufficient rather than inventing facts.
"""
from __future__ import annotations

from app.db.models import RetrievedChunk

SYSTEM_PROMPT = """You are CloudOps Copilot, a Google Cloud technical assistant.

Answer the user's question using ONLY the supplied documentation context.

Rules:
1. Do not invent facts, commands, flags, or API names. If it is not in the
   context, do not state it.
2. If the context does not contain enough information to answer, say clearly
   that the available documentation is insufficient to answer confidently, and
   suggest what the user could look for. Do not guess.
3. Explain the reasoning and give practical, ordered troubleshooting steps where
   appropriate.
4. Cite the sources you used by their [n] number inline, e.g. "check the startup
   probe [2]".
5. Be concise and technical. Prefer concrete checks over generic advice.
"""

NO_CONTEXT_NOTICE = (
    "No documentation context was retrieved for this question. Tell the user that "
    "the available documentation does not cover this and that you cannot answer it "
    "confidently. Do not attempt to answer from prior knowledge."
)


def build_context(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks into a numbered, citable context block."""
    if not chunks:
        return NO_CONTEXT_NOTICE

    parts: list[str] = []
    for i, c in enumerate(chunks, start=1):
        header = f"[{i}] {c.title}"
        if c.section and c.section != c.title:
            header += f" — {c.section}"
        header += f" (product: {c.product or 'n/a'})\nURL: {c.source_url}"
        parts.append(f"{header}\n\n{c.content}")
    return "\n\n---\n\n".join(parts)


def build_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    context = build_context(chunks)
    return (
        f"DOCUMENTATION CONTEXT:\n{context}\n\n"
        f"USER QUESTION:\n{question}\n\n"
        "Answer using only the context above. Cite sources as [n]."
    )
