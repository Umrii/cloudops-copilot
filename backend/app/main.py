"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.db.database import close_pool, init_db

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("cloudops")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as exc:  # noqa: BLE001 - don't crash if DB is briefly unready
        logger.warning("init_db skipped: %s", exc)
    yield
    close_pool()


app = FastAPI(
    title="CloudOps Copilot",
    description="An evaluated RAG system for Google Cloud troubleshooting.",
    version="0.1.0",
    lifespan=lifespan,
)

# Frontend runs on a separate origin in dev; allow it to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", tags=["ops"])
def root() -> dict:
    return {"service": "cloudops-copilot", "docs": "/docs", "health": "/health"}
