# Running CloudOps Copilot locally

A step-by-step guide to run the whole stack on your laptop. Commands are shown for
**Windows PowerShell** (your setup); macOS/Linux notes are called out where they differ.

You'll end up with three things running:

| Component | URL | Started by |
|---|---|---|
| Postgres + pgvector | `localhost:5432` | Docker |
| FastAPI backend | `localhost:8000` | Python |
| Next.js web UI | `localhost:3000` | Node |

---

## 0. Prerequisites (install once)

- **Docker Desktop** — must be **running** before you start (whale icon in the tray).
- **Python 3.11+** — `python --version`
- **Node.js 18+** — `node --version`
- **A Google AI Studio API key** — https://aistudio.google.com/app/apikey

All commands below are run from the project root:

```powershell
cd "C:\Users\HP\Downloads\CloudOps Copilot\cloudops-copilot"
```

---

## 1. Add your Gemini API key

The key lives in `prod.env` at the project root (this file is gitignored — never commit it).
It should contain exactly one line:

```
GEMINI_API_KEY=your-key-here
```

> If `prod.env` doesn't exist yet: `Copy-Item .env.example prod.env` then edit it.

---

## 2. Start the database (Docker)

```powershell
docker compose up -d db
```

This launches Postgres with `pgvector` and auto-creates the tables and indexes on
first boot. Check it's healthy:

```powershell
docker compose ps
```

You want `db` showing `(healthy)`. (First run pulls the image — give it a minute.)

---

## 3. Backend (FastAPI)

Open a terminal in the project root.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> **If PowerShell blocks the activate script** ("running scripts is disabled"), either
> run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, or skip
> activation and prefix python with the venv path: `.\.venv\Scripts\python.exe` instead
> of `python` in the commands below.
>
> **macOS/Linux:** `python3 -m venv .venv && source .venv/bin/activate`

### 3a. Build the document corpus (one time, ~1–2 min)

This fetches the pages in `data/urls.csv`, chunks them, creates embeddings with
Gemini, and loads them into Postgres. Needs your API key and internet.

```powershell
python -m scripts.ingest --reset
```

You should see it finish with something like `"chunks": 403, "failures": []`.

### 3b. Run the API

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Leave this running. Verify in another terminal (or a browser):

```powershell
curl http://localhost:8000/health
```

Expected: `{"status":"ok","database":true,"gemini_configured":true}`.
Interactive API docs are at http://localhost:8000/docs.

---

## 4. Frontend (Next.js)

Open a **second** terminal in the project root.

```powershell
cd frontend
Copy-Item .env.local.example .env.local
npm install
npm run dev
```

Then open **http://localhost:3000**, type a question (or click a sample), and you'll
get a grounded answer with cited sources.

Try:
> *"My Cloud Run service returns 503 after deploying a new revision. What should I check?"*

---

## Everyday use (after first-time setup)

You don't repeat the installs. Each session, just start the three pieces:

```powershell
# 1. database
docker compose up -d db

# 2. backend  (in backend/, venv active)
uvicorn app.main:app --port 8000

# 3. frontend (in frontend/)
npm run dev
```

Re-run ingestion only when you change `data/urls.csv`:

```powershell
# in backend/, venv active
python -m scripts.ingest --reset
```

---

## Stopping / cleanup

```powershell
# Stop backend / frontend: press Ctrl+C in their terminals.

# Stop the database (keeps your ingested data):
docker compose stop db

# Remove the database AND wipe all ingested data:
docker compose down -v
```

---

## Handy checks

```powershell
# How many docs/chunks are loaded?
curl http://localhost:8000/api/stats

# Inspect raw retrieval for a query (no LLM call):
curl "http://localhost:8000/api/debug/retrieve?q=cloud%20run%20503&k=5"

# Run the test suite (in backend/, venv active):
pytest

# Run the evaluation (from project root):
$env:PYTHONPATH="backend"; python evaluation/evaluate.py
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker: ... dockerDesktopLinuxEngine ... cannot find the file` | Docker Desktop isn't running. Start it, wait for the whale icon to go steady, retry. |
| `/health` shows `"database":false` | The db container isn't up/healthy yet. `docker compose ps`; give it a few seconds after `up`. |
| `/health` shows `"gemini_configured":false` | `GEMINI_API_KEY` missing/empty in `prod.env`. Fix it and restart the backend. |
| `/api/chat` returns 503 | Same as above — no API key configured. |
| Answers say "insufficient documentation" for everything | Corpus not ingested. Run `python -m scripts.ingest --reset`. |
| `Port 8000 (or 3000) already in use` | An old server is still running. Close it, or run on another port (`--port 8001`, `npm run dev -- -p 3001`, and set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` to match). |
| `Activate.ps1 cannot be loaded` | See the PowerShell note in step 3 (execution policy). |
| UI can't reach the API | Make sure the backend is running and `frontend/.env.local` has `NEXT_PUBLIC_API_URL=http://localhost:8000`. |

---

## Alternative: run the backend in Docker too

If you'd rather not manage a Python venv, run both the DB and the API in Docker and
only run the frontend on the host:

```powershell
docker compose up -d --build           # starts db + backend
docker compose exec backend python -m scripts.ingest --reset   # build corpus
# then run the frontend as in step 4
```

The API is still on `localhost:8000`. Logs: `docker compose logs -f backend`.
