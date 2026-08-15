"""API smoke tests using FastAPI's TestClient (no live DB/Gemini needed).

These verify wiring and validation, not retrieval quality. The health endpoint
degrades gracefully when the database is unreachable, so it returns 200 with
database=false rather than erroring.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_ok():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "cloudops-copilot"


def test_health_shape():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body) == {"status", "database", "gemini_configured"}
    assert isinstance(body["database"], bool)


def test_chat_rejects_too_short_question():
    r = client.post("/api/chat", json={"question": "hi"})
    assert r.status_code == 422  # fails min_length validation


def test_chat_requires_question_field():
    r = client.post("/api/chat", json={})
    assert r.status_code == 422
