"""CLI: build the corpus. Run from the backend/ directory:

    python -m scripts.ingest                    # fetch (cached) + embed + load
    python -m scripts.ingest --no-cache         # force re-download of every page
    python -m scripts.ingest --reset            # wipe corpus first (clean rebuild)
    python -m scripts.ingest --sources PATH      # use an alternate CSV source list

The corpus is defined by data/urls.csv (columns: url, product, question).
Requires GEMINI_API_KEY in prod.env and a reachable database (DATABASE_URL).
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from app.db.database import init_db
from app.db.models import reset_corpus
from app.rag.ingestion import ingest_all

logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest the Google Cloud doc corpus.")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cached HTML in data/raw and re-fetch every URL.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Truncate documents and chunks before ingesting (clean rebuild).",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=None,
        help="Path to an alternate CSV source list (defaults to data/urls.csv).",
    )
    args = parser.parse_args()

    init_db()
    if args.reset:
        reset_corpus()
        print("Corpus reset (documents + chunks truncated).")
    result = ingest_all(use_cache=not args.no_cache, sources_path=args.sources)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
