"""Unit tests for pure pipeline logic (no DB or network required)."""
from __future__ import annotations

import math

from app.rag.embeddings import _l2_normalize
from app.rag.ingestion import Block, chunk_blocks, clean_html


def test_l2_normalize_produces_unit_vector():
    out = _l2_normalize([3.0, 4.0])  # norm 5
    assert math.isclose(out[0], 0.6, abs_tol=1e-6)
    assert math.isclose(out[1], 0.8, abs_tol=1e-6)
    norm = math.sqrt(sum(x * x for x in out))
    assert math.isclose(norm, 1.0, abs_tol=1e-6)


def test_l2_normalize_handles_zero_vector():
    assert _l2_normalize([0.0, 0.0]) == [0.0, 0.0]


def test_clean_html_extracts_text_and_strips_noise():
    html = """
    <html><head><title>Cloud Run troubleshooting | Google Cloud</title></head>
    <body>
      <nav>SHOULD BE STRIPPED</nav>
      <main>
        <h1>Cloud Run troubleshooting</h1>
        <h2>Container failed to start</h2>
        <p>Ensure your container listens on the PORT environment variable.</p>
        <script>console.log('nope')</script>
      </main>
    </body></html>
    """
    title, blocks = clean_html(html)
    assert "Cloud Run troubleshooting" in title
    joined = " ".join(b.text for b in blocks)
    assert "PORT environment variable" in joined
    assert "SHOULD BE STRIPPED" not in joined
    assert "nope" not in joined
    # section should come from the h2 heading
    assert any(b.section == "Container failed to start" for b in blocks)


def test_chunk_blocks_respects_size_and_overlaps():
    # Two large blocks that must split into multiple chunks.
    big = "word " * 800  # ~4000 chars -> above one target window
    blocks = [Block(section="A", text=big), Block(section="B", text=big)]
    chunks = chunk_blocks(
        blocks, title="Doc", product="cloud_run", source_url="http://x"
    )
    assert len(chunks) >= 2
    # Each chunk carries the enriched embedding header but clean stored content.
    assert all("Product: cloud_run" in c.embed_input for c in chunks)
    assert all("Product: cloud_run" not in c.content for c in chunks)
    assert all(c.metadata["source_url"] == "http://x" for c in chunks)
    # chunk_index is sequential
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunk_blocks_drops_trivial_fragments():
    chunks = chunk_blocks(
        [Block(section="A", text="tiny")],
        title="Doc",
        product="p",
        source_url="http://x",
    )
    assert chunks == []
