# Deploying CloudOps Copilot (Render + Vercel)

Live topology:

```text
  Browser ──▶ Vercel (Next.js UI) ──HTTPS──▶ Render (FastAPI API) ──▶ Render Postgres + pgvector
                                                     │
                                                     └──▶ Gemini API
```

- **Render** hosts the FastAPI backend (from `backend/Dockerfile`) and a managed
  Postgres with the `vector` extension.
- **Vercel** hosts the Next.js UI and points `NEXT_PUBLIC_API_URL` at the Render API.

You need: the GitHub repo pushed, a **Render** account, a **Vercel** account, and
your **Gemini API key**.

---

## 0. Push the deployment files

These must be on GitHub before Render/Vercel can read them:
`render.yaml`, the CORS changes in `app/config.py` + `app/main.py`,
`.github/workflows/keepalive.yml`.

```bash
git add render.yaml .github backend/app/config.py backend/app/main.py .env.example DEPLOYMENT.md
git commit -m "Add Render + Vercel deployment config and CORS allowlist"
git push
```

---

## 1. Backend + database on Render (Blueprint)

1. Render dashboard → **New → Blueprint** → connect this GitHub repo → **Apply**.
   Render reads `render.yaml` and creates two resources: `cloudops-db` (Postgres)
   and `cloudops-copilot-api` (the Docker web service).
2. When prompted (or on the API service → **Environment**), set the two
   hand-managed vars:
   - `GEMINI_API_KEY` → your Google AI Studio key.
   - `CORS_ALLOW_ORIGINS` → leave blank for now; you'll fill it in step 4 once you
     have the Vercel URL. (`CORS_ALLOW_ORIGIN_REGEX` is pre-set to allow
     `*.vercel.app` preview URLs.)
3. Let it build and deploy (~3–5 min). On first boot the app runs `init_db()`,
   which creates the `vector` extension, tables, and indexes automatically.
4. **Verify** (replace with your service URL):
   ```bash
   curl https://cloudops-copilot-api.onrender.com/health
   ```
   Expect `{"status":"ok","database":true,"gemini_configured":true}`.
   Interactive docs: `https://cloudops-copilot-api.onrender.com/docs`.

> The database is empty at this point — that's expected. Load it next.

---

## 2. Load the corpus into the Render database (one-time)

The API is live but has no documents yet. Ingest from your laptop straight into
the Render Postgres, using its **external** connection string.

1. Render → `cloudops-db` → copy the **External Database URL**.
2. Locally, in `backend/` with the venv active and `GEMINI_API_KEY` in `prod.env`:
   ```powershell
   $env:DATABASE_URL = "postgresql://...EXTERNAL_URL...?sslmode=require"
   python -m scripts.ingest --reset
   ```
   (macOS/Linux: `export DATABASE_URL="..."`). If you get an SSL error, make sure
   the URL ends with `?sslmode=require`.
3. **Verify** the live API now sees the corpus:
   ```bash
   curl https://cloudops-copilot-api.onrender.com/api/stats
   ```
   Expect `{"documents":20,"chunks":403}` (or your current corpus size).

Re-run this step only when `data/urls.csv` changes.

---

## 3. Frontend on Vercel

1. Vercel → **Add New → Project** → import the GitHub repo.
2. **Root Directory** → set to **`frontend`** (this is a monorepo — without this the
   build fails). Framework preset auto-detects **Next.js**.
3. **Environment Variables** → add
   `NEXT_PUBLIC_API_URL = https://cloudops-copilot-api.onrender.com`
   (your Render API URL, **no trailing slash**).
4. **Deploy.** Note the production URL, e.g. `https://cloudops-copilot.vercel.app`
   (or your custom domain).

---

## 4. Close the CORS loop

Now that you have the Vercel URL, allowlist it on the API:

1. Render → `cloudops-copilot-api` → **Environment** → set
   `CORS_ALLOW_ORIGINS = https://cloudops-copilot.vercel.app`
   (comma-separate extra origins, e.g. a custom domain
   `https://cloudops-copilot.vercel.app,https://www.anasatiq.com`).
   Use the exact scheme + host, **no path, no trailing slash**.
2. Save — Render redeploys automatically.
3. **Test end-to-end:** open the Vercel URL, ask a question, and confirm an answer
   with sources appears. Open browser DevTools → Network: no CORS errors.

---

## 5. Keep it warm (kill the cold start)

Render's free web service spins down after ~15 min idle; the next request waits
~30–60s. For a job-application link that must feel instant, pick one:

- **A — In-repo GitHub Action** (`.github/workflows/keepalive.yml`): pings `/health`
  every 10 min. Set repo **variable** `API_URL` to your Render URL
  (repo → Settings → Secrets and variables → Actions → **Variables**), and make sure
  Actions are enabled. (Free/unlimited minutes on public repos.)
- **B — cron-job.org** (most reliable timing): create a free cron hitting
  `https://cloudops-copilot-api.onrender.com/health` every 10 minutes.
- **C — Render Starter ($7/mo):** disables spin-down entirely. The most robust
  option for a live demo link.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| CORS error in browser console | `CORS_ALLOW_ORIGINS` doesn't exactly match the Vercel origin — check scheme, host, no trailing slash/path. Redeploy after changing. |
| `/health` shows `database:false` | DB still provisioning, or `DATABASE_URL` not wired. Give it a minute; confirm the Blueprint linked the DB. |
| `/api/chat` returns 503 | `GEMINI_API_KEY` not set on the Render API service. |
| Answers all say "insufficient documentation" | Corpus not ingested into the Render DB — do step 2. |
| Very slow first request | Cold start — set up a keep-alive (step 5). |
| Vercel build fails | Root Directory not set to `frontend`. |
| Deploy log: `could not create extension "vector"` | The DB plan/version lacks pgvector; confirm Postgres 16 on Render and that pgvector is available for your plan. |

---

## Updating after deploy

- **Backend:** push to `main` → Render `autoDeploy` rebuilds the Docker image.
- **Frontend:** push to `main` → Vercel auto-deploys.
- **Corpus:** re-run step 2 whenever `data/urls.csv` changes.
