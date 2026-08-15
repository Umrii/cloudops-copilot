# CloudOps Copilot

An evaluated **Retrieval-Augmented Generation (RAG)** system that helps developers
troubleshoot Google Cloud problems using grounded Google Cloud documentation.

Ask a real operational question — *"My Cloud Run service returns 503 after deploying
a new revision, what should I check?"* — and the system retrieves the most relevant
documentation, passes it to Gemini for a grounded answer, and returns citations back
to the source docs. When the retrieved evidence is insufficient, it says so instead
of hallucinating.

> **Not** "a chatbot built with LangChain." This is a retrieval system with an
> evaluation harness: PostgreSQL + pgvector for semantic retrieval, Gemini for
> grounded generation, and measured retrieval **and** generation quality.

---

## Architecture

```text
        User ──▶ Next.js UI ──HTTP──▶ FastAPI
                                        │
                                  query embedding (Gemini, RETRIEVAL_QUERY)
                                        │
                                        ▼
                        PostgreSQL + pgvector  (cosine <=>, top-K)
                                        │
                                  top-K chunks (+ distance threshold)
                                        │
                                  context builder  ──▶  Gemini (grounded prompt)
                                        │
                                        ▼
                          Answer + Citations + retrieval diagnostics
```

**Key idea:** the LLM does not search the docs. Retrieval finds the evidence first;
the LLM only reasons over what was retrieved.

---

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI (Python 3.11) |
| Vector store | PostgreSQL + `pgvector` (HNSW, cosine) |
| Embeddings | Gemini `gemini-embedding-001` @ 768 dims (L2-normalized) |
| Generation | Gemini `gemini-2.5-flash` |
| Frontend | Next.js + TypeScript |
| Containers | Docker + docker-compose |
| Target cloud | Cloud Run + Cloud SQL |
| Tests | pytest |

---

## Quickstart (local)

**Prerequisites:** Docker + Docker Compose, a Google AI Studio API key.

1. **Configure secrets.** Copy the example env and add your key:
   ```bash
   cp .env.example prod.env
   # edit prod.env: set GEMINI_API_KEY=...
   ```

2. **Start Postgres + the API:**
   ```bash
   docker compose up -d --build
   ```
   The API is now on `http://localhost:8000` (`/health`, `/docs`).

3. **Build the corpus.** The document set is defined in `data/urls.csv`
   (columns: `url, product, question`). Ingest it:
   ```bash
   docker compose exec backend python -m scripts.ingest --reset
   ```

4. **Ask a question:**
   ```bash
   curl -s localhost:8000/api/chat \
     -H 'content-type: application/json' \
     -d '{"question":"Why is my Cloud Run service returning 503?"}' | jq
   ```

5. **Inspect retrieval directly** (great for tuning):
   ```bash
   curl -s "localhost:8000/api/debug/retrieve?q=cloud%20run%20503&k=5" | jq
   ```

6. **Run the web UI** (Next.js, separate terminal):
   ```bash
   cd frontend
   cp .env.local.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
   npm install && npm run dev
   ```
   Open `http://localhost:3000`, ask a question, and read the grounded answer with
   its cited sources.

### Corpus source list

The corpus is defined by a single file, `data/urls.csv` (columns:
`url, product, question`); the `question` column also seeds the evaluation set.
Edit that file to change the corpus, then re-ingest:
```bash
docker compose exec backend python -m scripts.ingest --reset
```

---

## API

### `POST /api/chat`
```json
// request
{ "question": "Why is my Cloud Run service returning 503?", "product": "cloud_run" }
```
```json
// response
{
  "answer": "…grounded answer with inline [n] citations…",
  "sources": [
    { "title": "Cloud Run troubleshooting", "url": "https://…", "relevance": 0.87 }
  ],
  "grounded": true,
  "retrieval": { "chunks_used": 5, "latency_ms": 42.1 }
}
```

- `GET /health` — liveness + DB + key-configured flags.
- `GET /api/stats` — document / chunk counts.
- `GET /api/debug/retrieve?q=…&k=5&product=…` — raw retrieval inspection.

---

## Evaluation

A RAG pipeline fails in two independent places, so both are measured separately.

```bash
# from the repo root:
PYTHONPATH=backend python evaluation/evaluate.py
```

- **Layer 1 — Retrieval (all questions):** `Recall@5` — did an expected source
  appear in the top-5? Plus latency and retrieval-failure rate.
- **Layer 2 — Generation faithfulness (judged subset):** the full pipeline runs,
  then **Gemini-as-judge** classifies each answer `grounded` / `partial` /
  `unsupported` against the retrieved context.

### Results

Measured on a 20-document corpus (Cloud Run, Cloud SQL, IAM; 403 chunks).

| Metric | Value |
|---|---|
| Retrieval Recall@5 | **95%** (19/20 questions) |
| Avg retrieval latency | **~5 ms** |
| Retrieval failure rate | **0%** |
| Generation faithfulness — grounded | **90%** (9/10 judged) |
| Generation faithfulness — unsupported / hallucinated | **0%** (0/10) |

The single non-grounded answer was judged **partial**, not unsupported: for the
IAP question the model gave a `gcloud run deploy --iap` command for a *new* service
while the retrieved docs only covered adding `--iap` to an *existing* one — mild
over-generalization, not a fabricated fact. **No answer contained an unsupported
claim** — the key property for a grounded assistant.

**What evaluation caught (and fixed):** the first run scored only 50% grounded.
The judge's reasons showed answers were being *truncated mid-sentence*, not
hallucinating. Root cause: `gemini-2.5-flash` "thinks" by default, and those
thinking tokens are drawn from `max_output_tokens`, silently cutting the visible
answer. Disabling thinking for this grounded-extraction task freed the output
budget and moved faithfulness **50% → 80% → 90%**, while cutting latency and cost.
This is exactly what the two-layer eval is for: Recall@5 alone (already 95%) would
have hidden a real generation bug.

> A small **curated** evaluation validating the pipeline end-to-end — not a
> large-scale benchmark. Questions are derived from the corpus (`data/urls.csv`),
> so the gold source for each is known and Recall@5 is naturally favourable. Stated
> honestly, that is the point: it demonstrates the retrieval and grounding pipeline
> works. Reproduce with `PYTHONPATH=backend python evaluation/evaluate.py`.

---

## Deployment

```text
Browser ──▶ Vercel (Next.js UI) ──▶ Render (FastAPI API) ──▶ Render Postgres + pgvector ──▶ Gemini
```

- **Render** — FastAPI backend (Docker) + managed Postgres with `pgvector`,
  provisioned as code via [`render.yaml`](render.yaml).
- **Vercel** — the Next.js UI, with `NEXT_PUBLIC_API_URL` pointed at the Render API.
- CORS is a strict env-driven allowlist (not `*`), and a keep-alive pings `/health`
  to avoid free-tier cold starts.

Full step-by-step in **[DEPLOYMENT.md](DEPLOYMENT.md)**.

---

## Project structure

```text
cloudops-copilot/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app + lifespan
│   │   ├── config.py          # env-driven settings
│   │   ├── api/routes.py      # /api/chat, /health, debug
│   │   ├── rag/
│   │   │   ├── embeddings.py   # Gemini embeddings (+ L2 normalize, task_type)
│   │   │   ├── ingestion.py    # fetch → clean → chunk → embed → load
│   │   │   ├── retrieval.py    # pgvector cosine search + threshold
│   │   │   ├── prompts.py      # grounded prompt + context builder
│   │   │   └── generation.py   # retrieve → prompt → Gemini → citations
│   │   ├── db/                 # schema.sql, pool, data-access
│   │   └── schemas/chat.py     # pydantic request/response
│   ├── scripts/ingest.py       # CLI ingestion
│   └── tests/                  # pytest (pure-logic + API smoke)
├── data/urls.csv               # ← the corpus: url, product, question
├── evaluation/                 # questions.json + evaluate.py
├── frontend/                   # Next.js UI
├── docker-compose.yml
└── prod.env                    # secrets (gitignored)
```

---

## Design decisions (interview notes)

- **pgvector, not a separate vector DB** — real semantic search while keeping one
  datastore for documents, chunks, metadata, and embeddings. Less infrastructure
  to justify; Postgres already stores the relational side.
- **768-dim embeddings, explicitly normalized** — `gemini-embedding-001` only
  returns unit vectors at its native 3072 dims; at 768 it does not, so we
  L2-normalize before storing. Cosine distance assumes unit norm.
- **Asymmetric embeddings** — documents use `RETRIEVAL_DOCUMENT`, queries use
  `RETRIEVAL_QUERY`, which improves retrieval over embedding both identically.
- **Distance threshold → honest refusal** — retrieval discards chunks beyond a
  cosine-distance ceiling, so "no relevant evidence" produces a decline, not a
  confident hallucination.
- **Enriched embedding input, clean stored content** — each chunk is embedded with
  a small `Product / Section / Source` header for better matching, but the stored
  and displayed content stays clean.
- **Raw SQL for retrieval** — the `<=>` cosine query is the core of the system and
  is kept visible rather than hidden behind an ORM.

---

## Limitations

- Fixed-size token-window chunking (no semantic chunking yet).
- Dense retrieval only — no hybrid (BM25) or reranking (see roadmap).
- Corpus is a curated snapshot; it can go stale as docs change.
- Retrieved content is trusted context — production use would need prompt-injection
  hardening.
- Evaluation is a small curated set, not a benchmark.

## Roadmap (v2)

Hybrid retrieval (vector + BM25) → cross-encoder reranking → deeper eval
(MRR, context precision/recall, citation-correctness) → Cloud Run + Cloud SQL deploy.

---

## License & attribution

Code: MIT (see [LICENSE](LICENSE)). Ingested Google Cloud documentation is licensed
by Google under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); the app
attributes every answer via citations to the source documentation URLs.
