# Vithana Accounting Automation — POC Summary & Deployment Strategy

> **Status:** POC complete as of 2026-05-06. This document captures what was built, what needs to change before going to production, and the full deployment strategy.

---

## Table of Contents

1. [What Was Built (POC Summary)](#1-what-was-built-poc-summary)
2. [Tech Stack](#2-tech-stack)
3. [System Architecture](#3-system-architecture)
4. [What Works Today](#4-what-works-today)
5. [Deployment Decision: Why GCP + Vercel](#5-deployment-decision-why-gcp--vercel)
6. [Cost Comparison](#6-cost-comparison)
7. [Target Production Architecture](#7-target-production-architecture)
8. [Pre-Deployment Blockers (Must Fix First)](#8-pre-deployment-blockers-must-fix-first)
9. [Deployment Playbook](#9-deployment-playbook)
10. [CI/CD Strategy](#10-cicd-strategy)
11. [Secrets Management](#11-secrets-management)
12. [Scaling Roadmap](#12-scaling-roadmap)
13. [Known Limitations](#13-known-limitations)
14. [Verification Checklist](#14-verification-checklist)

---

## 1. What Was Built (POC Summary)

The Vithana Accounting Automation POC is a **multi-tenant SaaS platform** that automates the full invoice-to-bill workflow:

```
Ingest (Gmail / Stripe / Chargebee / Upload)
    ↓
Parse (GPT-4o Vision / Tesseract / LlamaParse)
    ↓
Rules Engine (route to billing platform)
    ↓
Vendor Mapping (enforce canonical vendor names)
    ↓
Review (AG Grid — Excel-like UI)
    ↓
Push (Zoho Books / QuickBooks Online / Tally Prime)
```

### What the POC proved

- End-to-end invoice ingestion from **4 sources** (Gmail, Stripe, Chargebee, manual upload)
- AI parsing via **GPT-4o vision** with pluggable fallback (Tesseract, LlamaParse)
- GST/IGST/CGST routing logic for Zoho Books (India-specific)
- Multi-tenant isolation: multiple companies can run simultaneously with zero data bleed
- Rule engine with nested AND/OR conditions routing invoices to the right platform
- Vendor mapping enforcement — no invoice reaches any billing platform without an explicit mapping
- Full audit trail (immutable `audit_logs` + `extraction_logs`) meeting CGST S.36 Act requirements
- GSTIN validation pipeline

### POC Constraints (by design)

| Constraint | Why it was OK for POC | What needs to change |
|---|---|---|
| `docker-compose` local only | Fast iteration | Move to cloud |
| Files stored on local disk | No S3 setup needed | Migrate to Cloud Storage |
| `runtime_config.json` on disk | Simple overrides | Migrate to DB |
| MySQL password `accounting` | Local dev only | Strong password + Secret Manager |
| Tally LAN-only | Dev machine only | Relay agent needed |
| No background jobs | Small volume | Add async worker for Gmail polling |
| `create_all()` for schema | Quick iteration | Proper Alembic migrations |
| Secrets in `.env` | Local only | Rotate + move to Secret Manager |

---

## 2. Tech Stack

| Layer | Technology | Version |
|---|---|---|
| **Frontend** | Next.js (App Router) | 14.2.15 |
| **Frontend UI** | React + TypeScript + Tailwind CSS | 18.3.1 / 5.5.0 / 3.4.4 |
| **Frontend Tables** | AG Grid Community | 32.0.0 |
| **Frontend Charts** | Recharts | 2.12.0 |
| **Frontend Data** | TanStack React Query | 5.50.0 |
| **Backend** | FastAPI + Uvicorn (ASGI) | 0.110.0+ |
| **Backend Language** | Python | 3.11 |
| **ORM** | SQLAlchemy 2.0 + Alembic | 2.0+ |
| **Validation** | Pydantic Settings | 2.0+ |
| **Database** | MySQL | 8.0 |
| **PDF Parsing** | pdfplumber + pdf2image + Pillow | latest |
| **OCR** | Tesseract (system binary) + pytesseract | 5.x |
| **AI Parsing** | OpenAI GPT-4o Vision (default) | gpt-4o |
| **Alt AI** | Anthropic Claude / Google Gemini / Ollama | pluggable |
| **Cloud Parsing** | LlamaParse API | optional |
| **Auth** | Google OAuth2 (authlib) + JWT (pyjwt) | latest |
| **HTTP Client** | httpx | 0.27+ |
| **Containers** | Docker + Docker Compose | 3.8 |
| **Tests** | pytest + pytest-asyncio | 33 e2e + 26 unit |

### Dependencies that constrain deployment

- **Tesseract OCR** — a system binary installed via `apt-get`. Cannot run in pure serverless (Lambda, Vercel Functions). Requires a container runtime.
- **Poppler** (`pdf2image`) — another system binary for PDF-to-image conversion. Same constraint.
- **LibreOffice** (`libreoffice-writer`) — system binary used to convert `.doc/.docx` invoices to PDF before parsing (`app/utils/document_converter.py`). Installed via `apt-get` in the Dockerfile. Same container-runtime constraint.
- **pdf2image on large PDFs** — converts pages to in-memory PNG. Needs ≥2GB RAM per container.

---

## 3. System Architecture

### Pipeline flow

```
┌──────────────────────────────────────────────────────────────┐
│                     INVOICE PIPELINE                         │
│                                                              │
│  SOURCES           PARSE           ROUTE           PUSH      │
│  ──────────        ─────────       ──────          ──────    │
│  Gmail      ──→               ──→            ──→  Zoho      │
│  Stripe     ──→  GPT-4o       ──→  Rules     ──→  QuickBooks│
│  Chargebee  ──→  Tesseract    ──→  Engine    ──→  Tally     │
│  Upload     ──→  LlamaParse   ──→            ──→            │
│                                   Vendor                     │
│                                   Mapping                    │
│                                   Check                      │
└──────────────────────────────────────────────────────────────┘
```

### Draft state machine

```
PENDING_REVIEW ──→ APPROVED ──→ PUSHED
       │              │
       │              └──→ PUSH_FAILED ──→ (retry) ──→ PUSHED
       │
       ├──→ PENDING_VENDOR ──→ (vendor mapped) ──→ APPROVED
       │
       └──→ REJECTED
```

### Multi-tenant isolation

```
Request → JWT cookie
            ↓
        get_current_user()  →  User
            ↓
        CompanyMember lookup  →  company_id
            ↓
        TenantContext.set(company_id)      [contextvars — request-scoped]
            ↓
        TenantBaseRepository._base_query()
        → WHERE company_id = {current_tenant}   [all queries auto-filtered]
```

Every tenant-scoped table has `company_id`. No separate databases, no sharding. Single MySQL instance with row-level isolation.

### Directory structure

```
day3/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app, startup, platform registration
│   │   ├── config.py                  # Settings with runtime overrides
│   │   ├── tenant/                    # Multi-tenant isolation layer
│   │   ├── api/                       # 11 route modules (80+ endpoints)
│   │   ├── platforms/                 # Plugin: zoho, tally, quickbooks, stripe, chargebee, gmail
│   │   ├── parsers/                   # Plugin: llm_parser, tesseract_parser, llamaparse_parser
│   │   ├── auth/                      # Google OAuth2 + JWT
│   │   ├── rules/                     # Recursive AND/OR rule engine
│   │   ├── models/                    # SQLAlchemy models (16 tables)
│   │   ├── db/                        # Session + 10 repository classes
│   │   └── services/                  # Draft, Email, Invoice services
│   ├── alembic/versions/              # 6 migration files
│   ├── tests/                         # 33 e2e + 26 unit tests
│   ├── data/
│   │   ├── runtime_config.json        # ⚠ Admin runtime overrides (local disk)
│   │   └── attachments/               # ⚠ Invoice files (local disk)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/app/                       # Next.js App Router pages
│   ├── src/components/                # UI, layout, providers
│   ├── src/lib/api.ts                 # Typed fetch wrapper
│   ├── Dockerfile
│   └── next.config.js                 # API proxy: /api/* → backend
├── docker-compose.yml
├── ARCHITECTURE.md
├── API_DOCS.md
├── TECH_DOC.md
└── DEPLOYMENT.md                      # ← this file
```

---

## 4. What Works Today

### Fully implemented and tested

| Feature | Status |
|---|---|
| Google OAuth2 login (per-tenant) | Done |
| Multi-tenant company isolation | Done |
| Invoice ingest: Gmail attachments | Done |
| Invoice ingest: Stripe invoices | Done |
| Invoice ingest: Chargebee invoices | Done |
| Invoice ingest: Manual file upload | Done |
| Invoice parsing: GPT-4o Vision | Done |
| Invoice parsing: Tesseract OCR | Done |
| Invoice parsing: LlamaParse API | Done |
| Rules engine (nested AND/OR) | Done |
| Vendor mapping enforcement | Done |
| Draft review UI (AG Grid) | Done |
| Push to Zoho Books | Done |
| Push to QuickBooks Online | Done |
| Push to Tally Prime | Done (LAN only) |
| Zoho GST/IGST/CGST auto-routing | Done |
| GSTIN validation pipeline | Done |
| Chart of Accounts sync | Done |
| Audit trail (immutable) | Done |
| Extraction logs (CGST S.36) | Done |
| Admin runtime config dashboard | Done |
| 80+ REST API endpoints | Done |
| 59 automated tests | Done |

### Not built (out of POC scope)

| Feature | Notes |
|---|---|
| Async job queue | Gmail polling is manual trigger; no background workers |
| Email scheduling | No cron-based auto-fetch |
| Redis caching | All queries hit MySQL directly |
| Background PDF processing | Parsing blocks the HTTP request |
| Multi-region support | Single region, single DB instance |
| Tally cloud relay | Tally only works on local LAN |

---

## 5. Deployment Decision: Why GCP + Vercel

### The constraint that decides everything

The backend runs **Tesseract OCR**, **Poppler**, and **LibreOffice** (for `.doc/.docx` → PDF conversion) — all system binaries installed via `apt-get` in the Dockerfile. This eliminates all pure-serverless options:

| Platform | Verdict | Reason |
|---|---|---|
| AWS Lambda | No | Cannot install system binaries |
| Vercel Functions | No | Serverless only |
| Google Cloud Functions | No | Serverless only |
| **AWS ECS Fargate** | Viable | Runs Docker containers |
| **GCP Cloud Run** | **Best** | Runs Docker, scales to zero, per-request billing |
| **Railway** | Early-stage only | No autoscaling, ephemeral volumes |
| **Render** | No | No managed MySQL |

### Why GCP over AWS

| Factor | GCP | AWS |
|---|---|---|
| **Gmail / Google OAuth** | Native ecosystem | Cross-cloud overhead |
| **Managed MySQL cost** | Cloud SQL db-f1-micro = ~$7/mo | RDS db.t3.micro = ~$25/mo |
| **Container runtime** | Cloud Run — scales to zero | ECS Fargate — always-on tasks |
| **India region** | `asia-south1` Mumbai — all services | `ap-south-1` — available but pricier |
| **DevOps complexity** | `gcloud run deploy` — one command | ECS task definitions + VPC setup |
| **Billing model** | Pay-per-request + per-second | Per-hour minimum billing |

### Why Vercel for the frontend

- Next.js 14 is built by Vercel — best-in-class optimization, ISR, edge CDN
- Zero-config SSL, preview deployments on every PR
- Free Hobby tier handles POC indefinitely
- Automatic deploys on `git push main`
- Running Next.js in a Docker container on Cloud Run wastes these advantages

### Final answer

```
Frontend   →  Vercel        (Next.js-native, free tier, global CDN)
Backend    →  GCP Cloud Run (Docker container, scales to zero, 2GB RAM for OCR)
Database   →  Cloud SQL     (Managed MySQL 8.0, asia-south1)
Files      →  Cloud Storage (Invoice PDFs, 72-month CGST retention)
Secrets    →  Secret Manager (JWT key, API keys, DB credentials)
Registry   →  Artifact Registry (Docker images tagged by git SHA)
CI/CD      →  GitHub Actions + Vercel GitHub integration
```

---

## 6. Cost Comparison

### POC / early stage (1–10 tenants, low traffic)

| Component | Vercel + GCP | AWS (ECS + RDS) | Railway |
|---|---|---|---|
| Frontend | $0 (Hobby) | $15–25 (Fargate) | $5 |
| Backend | $0–5 (Cloud Run, scales to zero) | $15–25 (Fargate) | $5 |
| Database | $7–10 (Cloud SQL micro) | $25–35 (RDS micro) | $5 |
| File storage | $1–2 (Cloud Storage, 10GB) | $1–2 (S3) | Ephemeral volume (risky) |
| Secrets | $0–1 (Secret Manager) | $1–3 (SSM) | $0 |
| **Total** | **~$8–18/mo** | **~$57–90/mo** | **~$15/mo** |

### Growth stage (100 tenants, moderate load)

| Component | Vercel + GCP | AWS | Railway |
|---|---|---|---|
| Frontend | $20 (Pro) | $40–60 | $20 |
| Backend | $30–50 (Cloud Run, min 1) | $80–120 (2–4 tasks) | $20 |
| Database | $50–80 (Cloud SQL g1-small) | $80–120 (RDS t3.small) | $25 |
| File storage | $5–15 | $5–10 | Not viable |
| **Total** | **~$105–165/mo** | **~$205–310/mo** | **~$65–80/mo (no autoscale)** |

**Railway note:** Railway's ~$65/mo estimate looks good on paper but it has no horizontal autoscaling, no SLA, and ephemeral volume storage. Not suitable beyond 20–30 tenants.

---

## 7. Target Production Architecture

```
  Users (India / Global)
         │ HTTPS
         ▼
 ┌────────────────────┐
 │   Vercel CDN       │    Next.js 14 frontend
 │   app.vithana.com  │    Tailwind + AG Grid + React Query
 │   (global edge)    │    NEXT_PUBLIC_API_URL → api.vithana.com
 └─────────┬──────────┘
           │  /api/* REST calls
           ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  GCP Project: vithana-prod  (region: asia-south1)            │
 │                                                              │
 │  ┌─────────────────────────────────────────────────────┐    │
 │  │  Cloud Run: vithana-backend                         │    │
 │  │  api.vithana.com                                    │    │
 │  │                                                     │    │
 │  │  Image: asia.gcr.io/vithana-prod/backend:<sha>      │    │
 │  │  Base:  python:3.11-slim                            │    │
 │  │         + tesseract-ocr + poppler-utils (apt)       │    │
 │  │         + FastAPI + uvicorn                         │    │
 │  │                                                     │    │
 │  │  min-instances: 1   (no cold start for users)       │    │
 │  │  max-instances: 10  (autoscale under load)          │    │
 │  │  memory: 2Gi        (pdf2image needs headroom)      │    │
 │  │  cpu: 2             (Tesseract is CPU-bound)        │    │
 │  │  concurrency: 80    (per instance)                  │    │
 │  │                                                     │    │
 │  │  Sidecar: cloud-sql-auth-proxy                      │    │
 │  │           Unix socket → Cloud SQL                   │    │
 │  └───────────────────┬─────────────────────────────────┘    │
 │                      │                                       │
 │           ┌──────────┴──────────┐                           │
 │           │                     │                           │
 │  ┌────────▼────────┐   ┌────────▼────────────────┐         │
 │  │  Cloud SQL      │   │  Cloud Storage           │         │
 │  │  MySQL 8.0      │   │  vithana-invoices-prod   │         │
 │  │                 │   │                          │         │
 │  │  db-f1-micro    │   │  Region: asia-south1     │         │
 │  │  (POC)          │   │  Lifecycle: 72 months    │         │
 │  │  db-g1-small    │   │  (CGST S.36 compliance)  │         │
 │  │  (growth)       │   │  Signed URLs for preview │         │
 │  │                 │   │                          │         │
 │  │  Alembic runs   │   │  invoice PDFs/images     │         │
 │  │  before deploy  │   │  stored as GCS objects   │         │
 │  └─────────────────┘   └──────────────────────────┘         │
 │                                                              │
 │  ┌──────────────────────────────────────────────────────┐   │
 │  │  Secret Manager                                      │   │
 │  │  DATABASE_URL · JWT_SECRET_KEY · ADMIN_API_KEY       │   │
 │  │  LLM_API_KEY · LLAMAPARSE_API_KEY                    │   │
 │  │  INTEGRATION_ENCRYPTION_KEY · GCS_BUCKET_NAME        │   │
 │  └──────────────────────────────────────────────────────┘   │
 │                                                              │
 │  ┌──────────────────────────────────────────────────────┐   │
 │  │  Artifact Registry                                   │   │
 │  │  asia.gcr.io/vithana-prod/backend:<git-sha>          │   │
 │  │  (immutable tags — rollback by SHA)                  │   │
 │  └──────────────────────────────────────────────────────┘   │
 └──────────────────────────────────────────────────────────────┘

  External APIs (outbound from Cloud Run):
  Gmail API · OpenAI GPT-4o · Zoho Books · QuickBooks · Stripe · Chargebee · LlamaParse
```

---

## 8. Pre-Deployment Blockers (Must Fix First)

These are not optional improvements — the app will **silently lose data** in production without them.

---

### Blocker 1: File Storage → Cloud Storage

**Problem:** `ingest_routes.py` writes uploaded PDFs to `open(file_path, "wb")` where `file_path` resolves to `data/attachments/` on the container's local disk. Cloud Run containers are **ephemeral** — any file written is lost when the container restarts (which happens on every new instance, deploy, or scale-in event).

**Files to change:**
- `backend/app/api/ingest_routes.py` — replace `open(file_path, "wb")` with GCS upload
- `backend/app/platforms/gmail/service.py` — replace attachment writes with GCS upload
- `backend/app/parsers/llm_parser.py` / `tesseract_parser.py` — download from GCS to `/tmp/` before parsing, delete after

**What to add:**
```
# requirements.txt
google-cloud-storage>=2.16.0
```

```python
# backend/app/config.py — add these settings
GCS_BUCKET_NAME: str = ""
GCS_PROJECT: str = ""
```

**Storage path convention:** Store GCS object keys in `invoices.file_path` instead of local paths.
- Example: `attachments/2026/05/company_42/invoice_uuid.pdf`
- No DB migration needed — `file_path` is already `String(500)`

**Tesseract note:** Cloud Run has a 512MB in-memory `/tmp` filesystem. Download GCS object → `/tmp/invoice.pdf` → parse → delete. Sufficient for invoice PDFs.

---

### Blocker 2: `runtime_config.json` → Database

**Problem:** `backend/app/config.py` writes admin overrides to `data/runtime_config.json`. On Cloud Run, this file is written to the ephemeral container filesystem. After a restart, all admin settings revert to defaults. Admins will change LLM provider, hit Save, get a 200 response, and silently lose the change on next deploy.

**Files to change:**
- `backend/app/config.py` — `_load_overrides()` and `_save_overrides()`

**What to do:** The `system_config` table already exists in `db_models.py` and has migrations. Rewrite these two methods to read from and write to `system_config` instead of the JSON file. The admin dashboard API routes (`admin_routes.py`) and frontend do not need changes.

---

### Blocker 3: Database Connection Pool

**Problem:** `backend/app/db/session.py` sets `pool_size=5, max_overflow=10`. Cloud Run autoscales horizontally. At 10 instances × 5 connections = **50 connections**. Cloud SQL `db-f1-micro` allows only **25 total connections**.

**File to change:** `backend/app/db/session.py`

```python
# Production pool settings for Cloud Run
pool_size=2
max_overflow=3
pool_recycle=300   # recycle every 5 minutes
pool_pre_ping=True
```

**Also:** Use the Cloud SQL Auth Proxy sidecar (configured in Cloud Run service YAML). This handles IAM authentication and connection management via a Unix socket:
```
DATABASE_URL = mysql+pymysql://vithana_app:<password>@/accounting_automation?unix_socket=/cloudsql/vithana-prod:asia-south1:vithana-mysql
```

---

### Blocker 4: Rotate All Secrets

**Problem:** The `.env` file contains live credentials that will be committed or shared before production. Every one of these must be rotated:

| Secret | Where to rotate |
|---|---|
| `LLM_API_KEY` (OpenAI) | platform.openai.com → API Keys |
| `LLAMAPARSE_API_KEY` | cloud.llamaindex.ai → API Keys |
| `JWT_SECRET_KEY` | Generate new: `openssl rand -hex 32` |
| `GOOGLE_CLIENT_SECRET` | console.cloud.google.com → Credentials |
| `ADMIN_API_KEY` | Generate new: `openssl rand -hex 16` |
| `INTEGRATION_ENCRYPTION_KEY` | Generate new: `openssl rand -base64 32` |
| MySQL password (`accounting`) | Create new strong password |

**After rotation:** Move all secrets to GCP Secret Manager (see Section 11).

---

### Blocker 5: Alembic Migrations

**Problem:** The first Alembic migration (`7fba66afdc13`) is an **empty no-op**. The schema is created by `Base.metadata.create_all()` at startup. In production, `create_all()` cannot safely migrate an existing database — it only creates tables that don't exist yet and silently ignores schema changes.

**What to do:**
```bash
# Against a fresh local database, generate the full real migration:
cd backend
alembic revision --autogenerate -m "full_schema_v1"
# Review the generated file, verify it captures all 16 tables
# Commit the migration file
```

In CI/CD, the migration runs as a Cloud Run Job **before** `gcloud run deploy` (see Section 10). If migrations fail, the deploy is blocked — old version keeps serving traffic safely.

---

### Blocker 6: Google OAuth Redirect URI

**Problem:** `GOOGLE_REDIRECT_URI` is `http://localhost:8001/api/auth/google/callback`. After cloud deployment, this must be updated everywhere:

1. `backend/.env` → Secret Manager: change to `https://api.vithana.com/api/auth/google/callback`
2. Google Cloud Console → Credentials → OAuth 2.0 Client → Authorized redirect URIs: add the production URL
3. For per-tenant integrations (companies using their own Google OAuth app): update their `redirect_uri` in the `integrations` table post-launch

---

### Non-blocking improvements (do before first real customer)

| Item | File | What to do |
|---|---|---|
| Upgrade credential encryption | `platforms/base.py` | Replace base64 with AES-256-GCM (the field exists, just upgrade the encryption) |
| Add CORS production config | `main.py` | Set `FRONTEND_URL=https://app.vithana.com` in Secret Manager |
| Tally relay agent | `platforms/tally/client.py` | Build a small reverse proxy for LAN Tally (see Section 13) |
| Async invoice parsing | `api/ingest_routes.py` | Move OCR/LLM calls to a background queue (Cloud Tasks) |

---

## 9. Deployment Playbook

### Phase 1: GCP Project Setup (~2 hours, one-time)

```bash
# 1. Create project and set region
gcloud projects create vithana-prod --name="Vithana Production"
gcloud config set project vithana-prod
export REGION=asia-south1

# 2. Enable all required APIs
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com

# 3. Artifact Registry (Docker image storage)
gcloud artifacts repositories create vithana \
  --repository-format=docker \
  --location=asia \
  --description="Vithana backend images"

# 4. Cloud SQL MySQL 8.0
gcloud sql instances create vithana-mysql \
  --database-version=MYSQL_8_0 \
  --tier=db-f1-micro \
  --region=$REGION \
  --storage-auto-increase \
  --backup-start-time=02:00 \
  --maintenance-window-day=SUN \
  --maintenance-window-hour=3

gcloud sql databases create accounting_automation --instance=vithana-mysql

gcloud sql users create vithana_app \
  --instance=vithana-mysql \
  --password=<GENERATE_STRONG_PASSWORD>

# 5. Cloud Storage bucket for invoice files
gsutil mb -l $REGION gs://vithana-invoices-prod

# Set 72-month lifecycle (CGST S.36 Act — 6-year retention)
cat > /tmp/lifecycle.json <<EOF
{
  "lifecycle": {
    "rule": [{ "action": {"type": "Delete"}, "condition": {"age": 2160} }]
  }
}
EOF
gsutil lifecycle set /tmp/lifecycle.json gs://vithana-invoices-prod

# 6. Service account for Cloud Run
gcloud iam service-accounts create vithana-backend-sa \
  --display-name="Vithana Backend Service Account"

SA=vithana-backend-sa@vithana-prod.iam.gserviceaccount.com

gcloud projects add-iam-policy-binding vithana-prod \
  --member="serviceAccount:$SA" \
  --role="roles/cloudsql.client"

gcloud projects add-iam-policy-binding vithana-prod \
  --member="serviceAccount:$SA" \
  --role="roles/storage.objectAdmin"

gcloud projects add-iam-policy-binding vithana-prod \
  --member="serviceAccount:$SA" \
  --role="roles/secretmanager.secretAccessor"
```

### Phase 2: Load Secrets into Secret Manager

```bash
# For each secret, run:
# echo -n "VALUE" | gcloud secrets create SECRET_NAME --data-file=-
# (use -n to avoid trailing newline)

echo -n "mysql+pymysql://vithana_app:<PASSWORD>@/accounting_automation?unix_socket=/cloudsql/vithana-prod:asia-south1:vithana-mysql" \
  | gcloud secrets create DATABASE_URL --data-file=-

echo -n "$(openssl rand -hex 32)" \
  | gcloud secrets create JWT_SECRET_KEY --data-file=-

echo -n "$(openssl rand -hex 16)" \
  | gcloud secrets create ADMIN_API_KEY --data-file=-

echo -n "$(openssl rand -base64 32)" \
  | gcloud secrets create INTEGRATION_ENCRYPTION_KEY --data-file=-

# Add your rotated keys:
echo -n "sk-..." | gcloud secrets create LLM_API_KEY --data-file=-
echo -n "llx-..." | gcloud secrets create LLAMAPARSE_API_KEY --data-file=-
echo -n "vithana-invoices-prod" | gcloud secrets create GCS_BUCKET_NAME --data-file=-
```

### Phase 3: Build and Deploy Backend (~45 minutes)

```bash
# Build image
docker build -t asia.gcr.io/vithana-prod/backend:v1 ./backend
docker push asia.gcr.io/vithana-prod/backend:v1

# Run Alembic migrations as a one-shot Cloud Run Job
# (this must succeed before deploy — if it fails, stop here)
gcloud run jobs create alembic-migrate \
  --image=asia.gcr.io/vithana-prod/backend:v1 \
  --region=$REGION \
  --command=alembic \
  --args="upgrade,head" \
  --set-secrets="DATABASE_URL=DATABASE_URL:latest" \
  --service-account=$SA

gcloud run jobs execute alembic-migrate --region=$REGION --wait
# Wait for: "Execution ... has succeeded"

# Deploy Cloud Run service
gcloud run deploy vithana-backend \
  --image=asia.gcr.io/vithana-prod/backend:v1 \
  --region=$REGION \
  --platform=managed \
  --min-instances=1 \
  --max-instances=10 \
  --memory=2Gi \
  --cpu=2 \
  --concurrency=80 \
  --timeout=300 \
  --service-account=$SA \
  --add-cloudsql-instances=vithana-prod:$REGION:vithana-mysql \
  --set-secrets="DATABASE_URL=DATABASE_URL:latest,JWT_SECRET_KEY=JWT_SECRET_KEY:latest,ADMIN_API_KEY=ADMIN_API_KEY:latest,LLM_API_KEY=LLM_API_KEY:latest,LLAMAPARSE_API_KEY=LLAMAPARSE_API_KEY:latest,INTEGRATION_ENCRYPTION_KEY=INTEGRATION_ENCRYPTION_KEY:latest,GCS_BUCKET_NAME=GCS_BUCKET_NAME:latest" \
  --set-env-vars="LLM_PROVIDER=openai,LLM_MODEL=gpt-4o,PARSER_MODE=llm,FRONTEND_URL=https://app.vithana.com" \
  --allow-unauthenticated

# Note the backend URL: https://vithana-backend-xxxx-el.a.run.app
```

### Phase 4: Deploy Frontend to Vercel (~30 minutes)

```bash
# Install Vercel CLI if needed
npm i -g vercel

# Link repo to Vercel project
vercel link

# In Vercel Dashboard → Project Settings → Environment Variables:
# NEXT_PUBLIC_API_URL = https://api.vithana.com

# Deploy to production
vercel --prod
```

### Phase 5: Configure Custom Domains and SSL

```bash
# Map api.vithana.com → Cloud Run
gcloud run domain-mappings create \
  --service=vithana-backend \
  --domain=api.vithana.com \
  --region=$REGION

# Point DNS:
# app.vithana.com → CNAME → cname.vercel-dns.com  (Vercel handles SSL)
# api.vithana.com → A/CNAME → value from gcloud output (GCP handles SSL)
```

GCP and Vercel both provision SSL certificates automatically via Let's Encrypt.

---

## 10. CI/CD Strategy

Two independent GitHub Actions workflows. Frontend and backend deploy separately.

### Backend: `.github/workflows/backend.yml`

Triggers on push to `main` where `backend/**` files changed.

```yaml
name: Deploy Backend

on:
  push:
    branches: [main]
    paths: ['backend/**']

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r backend/requirements.txt
      - run: pytest backend/tests/ -v

  build-deploy:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write   # for Workload Identity Federation

    steps:
      - uses: actions/checkout@v4

      - name: Authenticate to GCP
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}

      - name: Build and push image
        run: |
          IMAGE=asia.gcr.io/vithana-prod/backend:${{ github.sha }}
          docker build -t $IMAGE ./backend
          docker push $IMAGE

      - name: Run Alembic migrations
        run: |
          gcloud run jobs update alembic-migrate \
            --image=asia.gcr.io/vithana-prod/backend:${{ github.sha }} \
            --region=asia-south1
          gcloud run jobs execute alembic-migrate \
            --region=asia-south1 --wait
          # If this fails, workflow stops — old version keeps serving

      - name: Deploy Cloud Run (zero-downtime)
        run: |
          gcloud run deploy vithana-backend \
            --image=asia.gcr.io/vithana-prod/backend:${{ github.sha }} \
            --region=asia-south1
```

**Key design:** Alembic migrations run as a Cloud Run Job and **must complete before** `gcloud run deploy`. If migrations fail, the job fails, the workflow fails, and the current production image keeps serving. Zero-risk schema migrations.

### Frontend: `.github/workflows/frontend.yml`

Triggers on push to `main` where `frontend/**` files changed.

```yaml
name: Deploy Frontend

on:
  push:
    branches: [main]
    paths: ['frontend/**']

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
        working-directory: frontend
      - run: npx vercel pull --environment=production --token=${{ secrets.VERCEL_TOKEN }}
      - run: npx vercel build --prod --token=${{ secrets.VERCEL_TOKEN }}
      - run: npx vercel deploy --prebuilt --prod --token=${{ secrets.VERCEL_TOKEN }}
```

Vercel also automatically creates **preview deployments** on every pull request via its GitHub integration — no workflow needed for that.

### GitHub Secrets Required

| Secret | How to get it |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Set up Workload Identity Federation in GCP (preferred over service account keys) |
| `GCP_SERVICE_ACCOUNT` | `vithana-backend-sa@vithana-prod.iam.gserviceaccount.com` |
| `VERCEL_TOKEN` | vercel.com → Account Settings → Tokens |
| `VERCEL_ORG_ID` | From `vercel link` output |
| `VERCEL_PROJECT_ID` | From `vercel link` output |

---

## 11. Secrets Management

### Production secrets map

| Secret Name (Secret Manager) | Used by | Rotation frequency |
|---|---|---|
| `DATABASE_URL` | Backend | On DB password change |
| `JWT_SECRET_KEY` | Backend | Every 90 days (invalidates all sessions) |
| `ADMIN_API_KEY` | Backend | Every 90 days |
| `INTEGRATION_ENCRYPTION_KEY` | Backend | Once (rotating breaks all stored integrations) |
| `LLM_API_KEY` | Backend | On compromise / quarterly |
| `LLAMAPARSE_API_KEY` | Backend | On compromise |
| `GCS_BUCKET_NAME` | Backend | Rarely |
| `GOOGLE_CLIENT_ID` | Backend + Frontend | On app recreation |
| `GOOGLE_CLIENT_SECRET` | Backend | On compromise |

### What to never put in environment variables

The `integrations` table stores per-company OAuth tokens and API keys encrypted in the database. These are decrypted at runtime using `INTEGRATION_ENCRYPTION_KEY`. The encryption key itself must be in Secret Manager, not `.env`.

### Upgrading credential encryption

Currently, `platforms/base.py` uses base64 encoding for integration credentials (not true encryption). Before the first paying customer, upgrade to AES-256-GCM using Python's `cryptography` library (already in `requirements.txt`).

---

## 12. Scaling Roadmap

### Stage 1: POC → Early Access (0–10 tenants) — ~$8–20/month

- Cloud Run: `min-instances=0` (scale to zero when idle → near-zero idle cost)
- Cloud SQL: `db-f1-micro` (1 shared vCPU, 614MB RAM, 25 connections)
- Single Cloud Run service (frontend + backend)
- No Redis, no background workers
- Manual Gmail polling (user triggers ingest via UI)

### Stage 2: Product-Market Fit (10–50 tenants) — ~$50–80/month

- Cloud Run: `min-instances=1` (eliminate cold start for active users)
- Cloud SQL: upgrade to `db-g1-small` (1 dedicated vCPU, 1.7GB RAM, 1,000 connections)
- Add custom domain SSL (`app.vithana.com` + `api.vithana.com`)
- Add Cloud Armor basic DDoS protection (~$5/month)
- Enable Cloud SQL automated backups daily

### Stage 3: Growth (50–200 tenants) — ~$150–250/month

**Add async job worker** — the single most important architectural change at this stage.

Today, invoice parsing blocks the HTTP request. A 10-page PDF through GPT-4o vision takes 8–15 seconds. At 50 tenants, simultaneous parse requests will exhaust Cloud Run concurrency and timeout.

```
Current:  POST /api/ingest → parse PDF → return result   (blocks ~15s)
Target:   POST /api/ingest → enqueue job → return job_id (returns ~200ms)
          Worker:           dequeue → parse → update DB → notify
```

Implementation:
- **Queue:** Google Cloud Tasks (simpler) or Pub/Sub (more powerful)
- **Worker:** Second Cloud Run service running a Celery or ARQ worker
- **Same Docker image** — just different `CMD` (`uvicorn` vs `celery worker`)
- Add **Memorystore Redis** (~$25/month) for task queue broker + session caching

Also at this stage:
- Cloud SQL read replica for dashboard queries (avoid contention with write path)
- Consider moving `extraction_logs` + `audit_logs` to BigQuery for long-term storage (72-month CGST requirement is expensive on MySQL at scale)

### Stage 4: Scale (200+ tenants) — ~$400–800/month

- Evaluate schema-per-tenant if row-level isolation causes MySQL query planner issues at scale
- Multi-region Cloud SQL read replicas (if international clients)
- Cloud CDN for invoice file serving (signed GCS URLs cached at edge)
- Cloud Run multi-region traffic splitting (low latency for non-India clients)
- BigQuery + Looker Studio for compliance reporting dashboard

---

## 13. Known Limitations

### Tally Prime (LAN-only)

**Problem:** `backend/app/platforms/tally/client.py` makes HTTP calls to `http://localhost:9000` (or a configurable LAN IP). Tally ERP runs on a Windows machine on the client's local network. There is no way to reach it from a public cloud without a network bridge.

**This does not block deployment** — Zoho Books and QuickBooks work fully from the cloud. Tally can be marked as "coming soon" in the integration UI.

**Solution (when ready):** Build a small Tally Relay Agent — a lightweight Windows service installed at the client site that:
1. Connects outbound (not inbound) to `wss://api.vithana.com/tally-relay/{company_id}`
2. Receives Tally XML payloads over WebSocket
3. Forwards to local Tally at `http://localhost:9000`
4. Returns the response

This is a ~200-line Python script that clients install once and requires no firewall changes (outbound WebSocket only).

### Synchronous invoice parsing

All parsing (LLM vision, Tesseract, LlamaParse) currently runs synchronously within the HTTP request. Large PDFs (10+ pages) can take 15–30 seconds. This works at POC scale but becomes a user experience problem at ~50 tenants. See Stage 3 in the scaling roadmap.

### Gmail polling is manual

There is no scheduler. Users must manually trigger Gmail ingest via the UI or API. For a production product, add a scheduled Cloud Task that fires `POST /api/ingest/gmail` every N minutes per tenant.

### Single-region

All infrastructure is in `asia-south1` (Mumbai). Appropriate for Indian GST compliance use case. If international clients are onboarded, add Cloud Run traffic splitting and Cloud SQL read replicas in additional regions.

---

## 14. Verification Checklist

Run these checks after every deployment to confirm the system is healthy end-to-end.

```
[ ] GET https://api.vithana.com/health
    Expected: {"status": "ok", "database": "connected"}

[ ] Google OAuth login flow
    Steps: Open app.vithana.com → Click "Sign in with Google" →
           Authorize → Land on /dashboard
    Confirm: JWT cookie set, company auto-created if first login

[ ] File upload ingest
    Steps: Upload a test PDF via /invoices → Ingest
    Confirm: File appears in gs://vithana-invoices-prod (NOT in container /tmp)
    Check:   gsutil ls gs://vithana-invoices-prod/attachments/

[ ] Admin config persistence
    Steps: /admin → change LLM Provider to "anthropic" → Save
           Deploy a new backend image (triggers container restart)
           Open /admin again
    Confirm: LLM Provider is still "anthropic" (validates runtime_config DB migration)

[ ] Audit log immutability
    Check: No DELETE or UPDATE endpoints exist for extraction_logs or audit_logs tables

[ ] Database connection pool
    Check Cloud Run metrics → Max concurrent requests per instance ≤ 80
    Check Cloud SQL metrics → Max connections in use ≤ (instances × 5)

[ ] Alembic migration ran
    Check Cloud Run job execution logs for "Running upgrade ... -> ..., full_schema_v1"

[ ] Secret rotation
    Confirm old OpenAI key is revoked at platform.openai.com
    Confirm old LlamaParse key is revoked
```

---

## Quick Reference

| What | Where |
|---|---|
| Frontend URL | https://app.vithana.com |
| Backend URL | https://api.vithana.com |
| Health check | https://api.vithana.com/health |
| Admin panel | https://app.vithana.com/admin |
| GCP Console | console.cloud.google.com → project: vithana-prod |
| Cloud Run logs | GCP Console → Cloud Run → vithana-backend → Logs |
| Cloud SQL | GCP Console → SQL → vithana-mysql |
| Invoice files | GCP Console → Cloud Storage → vithana-invoices-prod |
| Vercel dashboard | vercel.com → vithana-app |
| Docker images | asia.gcr.io/vithana-prod/backend |
