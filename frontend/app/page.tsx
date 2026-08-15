"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Source = {
  title: string;
  url: string;
  product?: string | null;
  section?: string | null;
  relevance: number;
};

type ChatResponse = {
  answer: string;
  sources: Source[];
  grounded: boolean;
  retrieval: { chunks_used: number; latency_ms: number };
};

const EXAMPLES = [
  "Why is my Cloud Run service returning 503 errors after a new revision?",
  "How do I connect a Cloud Run service to Cloud SQL for PostgreSQL?",
  "How do I resolve an IAM permission-denied error?",
];

export default function Home() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ChatResponse | null>(null);

  async function ask(q: string) {
    const query = q.trim();
    if (query.length < 3 || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: query }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Request failed (${res.status})`);
      }
      setResult((await res.json()) as ChatResponse);
    } catch (e: any) {
      setError(e.message || "Something went wrong. Is the API running?");
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    ask(question);
  }

  const noEvidence = result && (!result.grounded || result.sources.length === 0);

  return (
    <main className="page">
      <header className="header">
        <div className="logo">
          <span className="dot" />
          CloudOps Copilot
        </div>
        <p className="tagline">
          Troubleshoot Google Cloud with answers grounded in the official
          documentation — every claim cited.
        </p>
      </header>

      <div className="card">
        <form className="ask" onSubmit={onSubmit}>
          <textarea
            placeholder="e.g. My Cloud Run service returns 503 after deploying a new revision. What should I check?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") onSubmit(e);
            }}
          />
          <div className="row">
            <span className="hint">Grounded in Google Cloud docs · ⌘/Ctrl + Enter to send</span>
            <button className="primary" type="submit" disabled={loading || question.trim().length < 3}>
              {loading ? <><span className="spinner" />Thinking…</> : "Ask"}
            </button>
          </div>
        </form>

        {!result && !loading && (
          <div className="examples">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                className="chip"
                onClick={() => {
                  setQuestion(ex);
                  ask(ex);
                }}
              >
                {ex}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <div className="error">⚠ {error}</div>}

      {result && (
        <section className="answer card">
          <span className={`badge ${noEvidence ? "insufficient" : "grounded"}`}>
            {noEvidence ? "⚠ Insufficient evidence" : "✓ Grounded"}
            {!noEvidence &&
              ` · ${result.retrieval.chunks_used} sources · ${result.retrieval.latency_ms} ms retrieval`}
          </span>

          <div className="answer-body">
            <ReactMarkdown>{result.answer}</ReactMarkdown>
          </div>

          {result.sources.length > 0 && (
            <div className="sources">
              <h3>Sources</h3>
              {result.sources.map((s) => (
                <a
                  key={s.url}
                  className="source"
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <span>
                    <div className="source-title">{s.title}</div>
                    <div className="source-meta">
                      {s.product ? `${s.product} · ` : ""}
                      {s.section || s.url.replace(/^https?:\/\//, "")}
                    </div>
                  </span>
                  <span className="relevance">
                    {Math.round(s.relevance * 100)}%
                  </span>
                </a>
              ))}
            </div>
          )}
        </section>
      )}

      <footer className="footer">
        RAG · PostgreSQL + pgvector · Gemini ·{" "}
        <a href={`${API_URL}/docs`} target="_blank" rel="noopener noreferrer">
          API docs
        </a>
      </footer>
    </main>
  );
}
