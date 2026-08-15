"""Ingestion pipeline: sources.yaml -> fetch -> clean -> chunk -> embed -> pgvector.

Design notes
------------
* Fetching is polite (single-threaded, timeout, real UA) and caches raw HTML in
  data/raw so re-runs don't re-download.
* Cleaning targets Google's devsite article body and strips nav/aside/code-copy
  chrome, keeping headings so chunks can carry a section label.
* Chunking is intentionally simple — fixed-size token windows with overlap — per
  the build plan. The embedding *input* is enriched with a small structural
  header (product / section / source); the stored `content` stays clean text.
"""
from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml
from bs4 import BeautifulSoup

from app.rag.embeddings import embed_documents
from app.db.models import (
    corpus_stats,
    delete_chunks_for_document,
    insert_chunks,
    upsert_document,
)

logger = logging.getLogger(__name__)

# --- Paths ---
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
RAW_DIR = DATA_DIR / "raw"
CSV_SOURCES = DATA_DIR / "urls.csv"
YAML_SOURCES = DATA_DIR / "sources.yaml"


def default_sources_path() -> Path:
    """Prefer the curated CSV if present, else fall back to the YAML template."""
    return CSV_SOURCES if CSV_SOURCES.exists() else YAML_SOURCES

# --- Chunking parameters (approximate; ~4 chars/token heuristic) ---
CHARS_PER_TOKEN = 4
TARGET_TOKENS = 600
OVERLAP_TOKENS = 80
MIN_CHUNK_CHARS = 120  # drop trivially small trailing fragments

FETCH_TIMEOUT = 30.0
USER_AGENT = "CloudOps-Copilot-Ingestion/1.0 (portfolio project; respects CC-BY docs)"

# Selectors we try, in order, to find the real article body on Google docs.
CONTENT_SELECTORS = [
    "div.devsite-article-body",
    "main article",
    "article",
    "main",
    '[role="main"]',
]

# Chrome/noise to strip before extracting text.
NOISE_SELECTORS = [
    "script", "style", "nav", "header", "footer", "aside",
    "devsite-toc", ".devsite-article-meta", ".devsite-page-rating",
    ".devsite-feedback", "button", "form", "svg",
]


@dataclass
class Source:
    url: str
    product: str
    title: str | None = None
    document_type: str = "documentation"


@dataclass
class Block:
    section: str
    text: str


@dataclass
class Chunk:
    content: str          # clean text, stored + displayed
    embed_input: str      # header-enriched text, sent to the embedder
    section: str
    chunk_index: int
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Load sources
# --------------------------------------------------------------------------- #
def load_sources(path: Path | None = None) -> list[Source]:
    """Load the corpus URL list from CSV (url,product[,question,title,...]) or YAML."""
    path = path or default_sources_path()
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Add your curated URL list (data/urls.csv or sources.yaml)."
        )
    if path.suffix.lower() == ".csv":
        return _load_csv(path)
    return _load_yaml(path)


def _load_csv(path: Path) -> list[Source]:
    sources: list[Source] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            sources.append(
                Source(
                    url=url,
                    product=(row.get("product") or "unknown").strip(),
                    title=(row.get("title") or None),
                    document_type=(row.get("document_type") or "documentation").strip(),
                )
            )
    return sources


def _load_yaml(path: Path) -> list[Source]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("sources", raw if isinstance(raw, list) else [])
    sources: list[Source] = []
    for e in entries:
        if not e or not e.get("url"):
            continue
        sources.append(
            Source(
                url=e["url"].strip(),
                product=e.get("product", "unknown"),
                title=e.get("title"),
                document_type=e.get("document_type", "documentation"),
            )
        )
    return sources


# --------------------------------------------------------------------------- #
# Fetch (with on-disk cache)
# --------------------------------------------------------------------------- #
def _slug(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", url).strip("_")[:150]


def fetch_html(url: str, use_cache: bool = True) -> str:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / f"{_slug(url)}.html"
    if use_cache and cache_path.exists():
        logger.info("cache hit: %s", url)
        return cache_path.read_text(encoding="utf-8", errors="ignore")

    logger.info("fetching: %s", url)
    resp = httpx.get(
        url,
        timeout=FETCH_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    cache_path.write_text(resp.text, encoding="utf-8")
    return resp.text


# --------------------------------------------------------------------------- #
# Clean
# --------------------------------------------------------------------------- #
def _clean_title(text: str) -> str:
    """Strip devsite boilerplate that Google injects into headings/titles."""
    t = re.sub(r"\s+", " ", text or "").strip()
    t = t.split("|")[0].strip()  # drop "| Google Cloud" suffix
    # Remove the "Stay organized with collections / Save and categorize…" widget text.
    t = re.sub(r"Stay organized with collections.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Save and categorize content.*$", "", t, flags=re.IGNORECASE)
    return t.strip()


def clean_html(html: str) -> tuple[str, list[Block]]:
    """Return (page_title, blocks). Each block is a heading-scoped text unit."""
    soup = BeautifulSoup(html, "lxml")

    page_title = ""
    if soup.title and soup.title.string:
        page_title = _clean_title(soup.title.string)
    if not page_title:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            page_title = _clean_title(h1.get_text(" ", strip=True))

    container = None
    for sel in CONTENT_SELECTORS:
        container = soup.select_one(sel)
        if container:
            break
    if container is None:
        container = soup.body or soup

    for sel in NOISE_SELECTORS:
        for tag in container.select(sel):
            tag.decompose()

    blocks: list[Block] = []
    current_section = page_title or "Overview"
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(t for t in buffer if t.strip())
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            blocks.append(Block(section=current_section, text=text))
        buffer.clear()

    for el in container.find_all(
        ["h1", "h2", "h3", "h4", "p", "li", "pre", "td", "th"]
    ):
        name = el.name
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if name in ("h1", "h2", "h3", "h4"):
            flush()
            current_section = _clean_title(txt) or txt
        elif name == "pre":
            buffer.append(f"\n{txt}\n")
        elif name in ("li", "td", "th"):
            buffer.append(f"- {txt}")
        else:
            buffer.append(txt)
    flush()

    return page_title or "Untitled", blocks


# --------------------------------------------------------------------------- #
# Chunk
# --------------------------------------------------------------------------- #
def _est_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def chunk_blocks(
    blocks: list[Block],
    *,
    title: str,
    product: str,
    source_url: str,
) -> list[Chunk]:
    """Fixed-size token windows with overlap, walking across blocks.

    The section recorded for a chunk is the section active where the chunk starts.
    """
    target_chars = TARGET_TOKENS * CHARS_PER_TOKEN
    overlap_chars = OVERLAP_TOKENS * CHARS_PER_TOKEN

    chunks: list[Chunk] = []
    buf = ""
    buf_section = blocks[0].section if blocks else (title or "Overview")

    def emit(text: str, section: str) -> None:
        text = text.strip()
        if len(text) < MIN_CHUNK_CHARS:
            return
        idx = len(chunks)
        header = (
            f"Product: {product}\n"
            f"Section: {section}\n"
            f"Source: {source_url}\n\n"
        )
        chunks.append(
            Chunk(
                content=text,
                embed_input=header + text,
                section=section,
                chunk_index=idx,
                token_count=_est_tokens(text),
                metadata={
                    "product": product,
                    "section": section,
                    "title": title,
                    "source_url": source_url,
                    "document_type": "documentation",
                },
            )
        )

    for block in blocks:
        if not buf:
            buf_section = block.section
        candidate = f"{buf}\n\n{block.text}" if buf else block.text
        if len(candidate) <= target_chars:
            buf = candidate
            continue

        # Flush current buffer, then start a new one with an overlap tail.
        if buf:
            emit(buf, buf_section)
            tail = buf[-overlap_chars:]
            buf = f"{tail}\n\n{block.text}"
            buf_section = block.section
        else:
            buf = block.text
            buf_section = block.section

        # A single oversized block: hard-split it into windows.
        while len(buf) > target_chars:
            emit(buf[:target_chars], buf_section)
            buf = buf[target_chars - overlap_chars :]

    if buf:
        emit(buf, buf_section)
    return chunks


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def ingest_source(source: Source, *, use_cache: bool = True) -> int:
    html = fetch_html(source.url, use_cache=use_cache)
    page_title, blocks = clean_html(html)
    title = source.title or page_title
    if not blocks:
        logger.warning("no content extracted from %s", source.url)
        return 0

    chunks = chunk_blocks(
        blocks, title=title, product=source.product, source_url=source.url
    )
    if not chunks:
        logger.warning("no chunks produced from %s", source.url)
        return 0

    embeddings = embed_documents([c.embed_input for c in chunks])

    doc_id = upsert_document(
        title=title,
        source_url=source.url,
        product=source.product,
        document_type=source.document_type,
    )
    delete_chunks_for_document(doc_id)  # idempotent re-ingest

    rows = [
        {
            "content": c.content,
            "section": c.section,
            "chunk_index": c.chunk_index,
            "token_count": c.token_count,
            "embedding": emb,
            "metadata": c.metadata,
        }
        for c, emb in zip(chunks, embeddings)
    ]
    n = insert_chunks(doc_id, rows)
    logger.info("ingested %s -> %d chunks", source.url, n)
    return n


def ingest_all(*, use_cache: bool = True, sources_path: Path | None = None) -> dict[str, Any]:
    sources = load_sources(sources_path)
    if not sources:
        logger.warning("sources.yaml has no entries yet.")
        return {"sources": 0, "chunks": 0, **corpus_stats()}

    total_chunks = 0
    failures: list[str] = []
    for src in sources:
        try:
            total_chunks += ingest_source(src, use_cache=use_cache)
        except Exception as exc:  # noqa: BLE001 - keep going, report at the end
            logger.error("failed to ingest %s: %s", src.url, exc)
            failures.append(src.url)

    stats = corpus_stats()
    result = {
        "sources_processed": len(sources),
        "chunks_added_this_run": total_chunks,
        "failures": failures,
        **stats,
    }
    logger.info("ingestion complete: %s", result)
    return result
