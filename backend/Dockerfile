# syntax=docker/dockerfile:1
FROM python:3.11-slim

# System deps kept minimal; psycopg[binary] ships its own libpq.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy application code.
COPY app ./app
COPY scripts ./scripts

# Cloud Run provides $PORT; default to 8080 for parity with Cloud Run.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
