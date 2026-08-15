-- CloudOps Copilot schema.
-- Idempotent: safe to run on every startup and as a Docker init script.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id            SERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    source_url    TEXT NOT NULL UNIQUE,
    product       TEXT,
    document_type TEXT DEFAULT 'documentation',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id          SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    section     TEXT,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    token_count INTEGER,
    embedding   VECTOR(768),
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Approximate-nearest-neighbour index for cosine distance (<=>).
-- HNSW gives good recall/latency for a small-to-medium corpus.
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);

-- Support metadata filtering (e.g. by product) without scanning every row.
CREATE INDEX IF NOT EXISTS chunks_metadata_gin
    ON chunks USING gin (metadata);

CREATE INDEX IF NOT EXISTS chunks_document_id_idx
    ON chunks (document_id);
