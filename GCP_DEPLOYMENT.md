# Deploying to Google Cloud (Cloud Run + Cloud SQL)

The GCP-native deployment: FastAPI on **Cloud Run**, Postgres/pgvector on **Cloud
SQL**, UI on **Vercel**. No application code changes are required — the Dockerfile
already honors Cloud Run's `$PORT`, the DB is driven by `DATABASE_URL` (over the
Cloud SQL socket), and CORS is env-driven.

> **Cost heads-up:** Cloud Run scales to zero (effectively free for a demo), but
> **Cloud SQL has no free tier** — the smallest shared-core instance runs roughly
> **$8–12/month**, always on. That's the price of the "deployed on Cloud SQL" story.

**Prerequisites:** the `gcloud` CLI installed and authenticated, a GCP project with
**billing enabled**, and the `cloud-sql-proxy` binary (for one-time ingestion).

Throughout, replace `PROJECT_ID`, `YOUR_DB_PASSWORD`, and `YOUR_GEMINI_KEY`.

---

## 0. Project + APIs

```bash
gcloud auth login
gcloud config set project PROJECT_ID
gcloud services enable \
  run.googleapis.com sqladmin.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com

# pick a region and reuse it everywhere
export REGION=us-central1
```

---

## 1. Cloud SQL (Postgres 16 + pgvector)

```bash
gcloud sql instances create cloudops-db \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=$REGION \
  --storage-size=10GB

gcloud sql databases create cloudops --instance=cloudops-db
gcloud sql users set-password postgres --instance=cloudops-db --password=YOUR_DB_PASSWORD

# grab the connection name (looks like PROJECT_ID:REGION:cloudops-db)
export CONN=$(gcloud sql instances describe cloudops-db --format='value(connectionName)')
echo "$CONN"
```

pgvector is available on Cloud SQL; the app's `init_db()` runs `CREATE EXTENSION IF
NOT EXISTS vector` on first connect (the `postgres` user has the privilege).

---

## 2. Store the Gemini key as a secret

```bash
printf '%s' 'YOUR_GEMINI_KEY' | gcloud secrets create gemini-api-key --data-file=-
```

---

## 3. Deploy the backend to Cloud Run

Builds `backend/Dockerfile` via Cloud Build and wires it to Cloud SQL. The `^##^`
prefix just sets `##` as the delimiter so the regex/URL values are passed intact.

```bash
gcloud run deploy cloudops-copilot-api \
  --source backend \
  --region $REGION \
  --allow-unauthenticated \
  --add-cloudsql-instances $CONN \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
  --set-env-vars "^##^DATABASE_URL=postgresql://postgres:YOUR_DB_PASSWORD@/cloudops?host=/cloudsql/$CONN##CORS_ALLOW_ORIGINS=https://cloudops-copilot.vercel.app##CORS_ALLOW_ORIGIN_REGEX=https://.*\.vercel\.app"

# the public URL:
export API_URL=$(gcloud run services describe cloudops-copilot-api --region $REGION --format='value(status.url)')
echo "$API_URL"
curl "$API_URL/health"     # expect database:true, gemini_configured:true
```

> Optional hardening: store the full `DATABASE_URL` as a Secret Manager secret too
> (it contains the DB password) and pass it via `--set-secrets` instead of
> `--set-env-vars`.

---

## 4. Load the corpus (one-time, via Cloud SQL Auth Proxy)

In one terminal, start the proxy (exposes the instance on localhost):

```bash
cloud-sql-proxy $CONN        # listens on 127.0.0.1:5432
```

In another, from `backend/` with the venv active (`GEMINI_API_KEY` in `prod.env`):

```powershell
$env:DATABASE_URL = "postgresql://postgres:YOUR_DB_PASSWORD@127.0.0.1:5432/cloudops"
python -m scripts.ingest --reset
```

Verify: `curl $API_URL/api/stats` → `{"documents":20,"chunks":403}`.

---

## 5. Point Vercel at Cloud Run

- Vercel → project → **Settings → Environment Variables** → set
  `NEXT_PUBLIC_API_URL` to the Cloud Run URL from step 3 → **Redeploy**.
- If your Vercel origin differs from what you set in step 3, update
  `CORS_ALLOW_ORIGINS` (re-run the `gcloud run deploy`/`services update` with the
  right value).

Test the live Vercel page end-to-end (DevTools open → no CORS errors).

---

## 6. Cold starts

Cloud Run also scales to zero, so the first request after idle cold-starts (usually
faster than Render — a few seconds). Options:

```bash
# keep one instance warm (small always-on cost):
gcloud run services update cloudops-copilot-api --region $REGION --min-instances=1
```

or keep the existing cron-job.org `/health` ping pointed at the new Cloud Run URL.

---

## After it's live

Update the README to the now-accurate claim: **Cloud Run + Cloud SQL** in the tech
stack table, the Live demo / Deployment sections, and remove it from the roadmap.

## Teardown (stop the meter)

```bash
gcloud run services delete cloudops-copilot-api --region $REGION
gcloud sql instances delete cloudops-db
```
