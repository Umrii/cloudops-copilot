"""Evaluate the RAG pipeline on two independent axes.

Layer 1 (retrieval, all questions): Recall@5 — did an expected source appear in
the top-5 retrieved chunks? Also reports latency and retrieval-failure rate.

Layer 2 (generation faithfulness, judged subset): run the full pipeline and use
Gemini as a judge to classify each answer as grounded / partial / unsupported
against the retrieved context.

Run from the backend/ directory so `app` is importable:

    python -m evaluation.evaluate      # (path: ../evaluation/evaluate.py)

or from repo root:

    PYTHONPATH=backend python evaluation/evaluate.py
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from google.genai import types

from app.config import settings
from app.rag.embeddings import get_client
from app.rag.generation import answer_question
from app.rag.retrieval import retrieve

QUESTIONS_FILE = Path(__file__).parent / "questions.json"
RESULTS_FILE = Path(__file__).parent / "results.json"

JUDGE_PROMPT = """You are evaluating whether an answer is grounded in the provided context.

Given the QUESTION, the CONTEXT that was retrieved, and the ANSWER produced,
classify the answer as exactly one of:
- "grounded": every substantive claim is supported by the context.
- "partial": mostly supported, but contains at least one claim not in the context.
- "unsupported": key claims are not supported by the context, or the answer
  fabricates specifics.

If the answer correctly states that the documentation is insufficient AND the
context indeed lacks the information, classify it "grounded".

Respond with a single JSON object: {{"verdict": "...", "reason": "..."}}.

QUESTION:
{question}

CONTEXT:
{context}

ANSWER:
{answer}
"""


def _source_hit(expected: list[str], retrieved) -> bool:
    """True if any expected keyword appears in a retrieved title/section/url."""
    hay = " ".join(
        f"{c.title} {c.section or ''} {c.source_url}".lower() for c in retrieved
    )
    return any(kw.lower() in hay for kw in expected)


def evaluate_retrieval(questions: list[dict]) -> dict:
    hits = 0
    latencies: list[float] = []
    failures: list[str] = []
    per_q = []

    for q in questions:
        chunks, latency_ms = retrieve(q["question"], product=q.get("product"))
        latencies.append(latency_ms)
        if not chunks:
            failures.append(q["question"])
        hit = _source_hit(q.get("expected_sources", []), chunks)
        hits += int(hit)
        per_q.append(
            {
                "question": q["question"],
                "hit": hit,
                "chunks": len(chunks),
                "latency_ms": latency_ms,
                "top": chunks[0].title if chunks else None,
            }
        )

    n = len(questions)
    return {
        "n": n,
        "recall_at_5": round(hits / n, 3) if n else 0.0,
        "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
        "failure_rate": round(len(failures) / n, 3) if n else 0.0,
        "failures": failures,
        "per_question": per_q,
    }


def _judge(question: str, context: str, answer: str) -> dict:
    client = get_client()
    resp = client.models.generate_content(
        model=settings.generation_model,
        contents=JUDGE_PROMPT.format(question=question, context=context, answer=answer),
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )
    try:
        return json.loads(resp.text)
    except Exception:  # noqa: BLE001
        return {"verdict": "unparseable", "reason": resp.text[:200]}


def evaluate_faithfulness(questions: list[dict]) -> dict:
    judged = [q for q in questions if q.get("judge")]
    results = []
    counts = {"grounded": 0, "partial": 0, "unsupported": 0, "unparseable": 0}

    for q in judged:
        chunks, _ = retrieve(q["question"], product=q.get("product"))
        context = "\n\n---\n\n".join(
            f"{c.title} — {c.section}\n{c.content}" for c in chunks
        ) or "(no context retrieved)"
        result = answer_question(q["question"], product=q.get("product"))
        verdict = _judge(q["question"], context, result["answer"])
        v = verdict.get("verdict", "unparseable")
        counts[v] = counts.get(v, 0) + 1
        results.append(
            {"question": q["question"], "verdict": v, "reason": verdict.get("reason")}
        )

    n = len(judged)
    return {
        "n": n,
        "grounded_rate": round(counts["grounded"] / n, 3) if n else 0.0,
        "counts": counts,
        "per_question": results,
    }


def main() -> None:
    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))

    print("=== Layer 1: Retrieval (Recall@5) ===")
    retrieval = evaluate_retrieval(questions)
    print(json.dumps({k: v for k, v in retrieval.items() if k != "per_question"}, indent=2))

    print("\n=== Layer 2: Generation faithfulness (Gemini-as-judge) ===")
    faithfulness = evaluate_faithfulness(questions)
    print(json.dumps({k: v for k, v in faithfulness.items() if k != "per_question"}, indent=2))

    out = {"retrieval": retrieval, "faithfulness": faithfulness}
    RESULTS_FILE.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nFull results written to {RESULTS_FILE}")

    print("\n--- README table ---")
    print("| Metric | Value |")
    print("|---|---|")
    print(f"| Retrieval Recall@5 | {retrieval['recall_at_5']:.0%} ({retrieval['n']} questions) |")
    print(f"| Avg retrieval latency | {retrieval['avg_latency_ms']} ms |")
    print(f"| Retrieval failure rate | {retrieval['failure_rate']:.0%} |")
    print(f"| Generation faithfulness (grounded) | {faithfulness['grounded_rate']:.0%} ({faithfulness['n']} judged) |")


if __name__ == "__main__":
    main()
