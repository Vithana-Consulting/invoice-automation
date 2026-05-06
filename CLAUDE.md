# Vithana Accounting Automation — POC (Day 3)

## What This Is

Multi-tenant invoice automation SaaS POC. Gmail → PDF → GPT-4o parse → validate → push to Zoho Books (or QuickBooks).
Built by Deepak (deepak2004sakthi@gmail.com / Deepak.sakthi@vithanaconsulting.com).

---

## How to Start

```bash
# Backend — app object is `application`, NOT `app`
cd backend && .venv/bin/uvicorn app.main:application --reload --port 8000

# Frontend
cd frontend && npm run dev   # port 3001 (FRONTEND_URL=http://localhost:3001)
```

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic |
| Frontend | Next.js 14 (App Router), TypeScript, AG Grid, TanStack Query |
| Database | MySQL 8.0 (Docker: `day3-db-1`, port 3306) |
| Parser | GPT-4o vision (LLM provider registry pattern) |
| Auth | Google OAuth per-tenant, JWT cookie (`access_token`) |
| Accounting | Zoho Books (India, INR) + QuickBooks (pluggable) |

**MySQL connect:**
```bash
docker exec -it day3-db-1 mysql -uaccounting -paccounting accounting_automation
```

---

## .env (backend/.env)

```
DATABASE_URL=mysql+pymysql://accounting:accounting@localhost:3306/accounting_automation
PARSER_MODE=llm
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=<openai key>
LLAMAPARSE_API_KEY=<llamaparse key>
JWT_SECRET_KEY=v1th4n4-d4y3-p0c-s3cr3t-k3y-2026
ADMIN_API_KEY=v1th4n4-flush-s3cr3t-2026
FRONTEND_URL=http://localhost:3001
```

---

## Multi-Tenancy

- Single MySQL DB, `company_id` on ALL tenant tables — no exceptions
- `TenantContext` via Python `contextvars` (async-safe)
- ASGI middleware (`TenantMiddleware`) sets context from JWT cookie — NOT a FastAPI dependency
- `TenantBaseRepository` auto-filters all queries by `company_id`
- `Company.domain` maps email domains to companies at login
- Google OAuth credentials stored per-company (`platform="google_oauth"` in `integrations` table)

**Auth flow:** email → domain lookup → company's OAuth credentials → signed state JWT (5 min TTL) → callback

---

## Parser Pipeline

```
PDF → images → GPT-4o vision → validate (7 checks, GSTIN checksum) → retry up to 3× with correction prompt
```

- **Three modes:** `llm` (default), `llamaparse`, `tesseract`
- **Registry pattern:** `@register_llm_provider` — add new providers without touching existing code
- **Validation gates:**
  1. Preflight — company GST/PAN check (warning, not blocking)
  2. Source health — Gmail/integration check before pull
  3. Parse validation — `invoice_number` mandatory; GST/PAN mismatch = warning
  4. Pre-push — 7 validators (composition, GSTIN format, RCM, routing, ITC cutoff, reconciliation, duplicate)
- **Override:** HARD_BLOCK validators can be bypassed with reason code (except `COMPOSITION_VENDOR`)
- **All overrides logged** to immutable `audit_logs` table with actor identity (email, name, role)

**Critical:** `invoice_number` must be copied CHARACTER BY CHARACTER — digit transposition = ITC failure.

---

## Zoho Integration

- **Org ID:** 60069222256 — India region (`.in` endpoints)
- **Auth URL:** `https://accounts.zoho.in/oauth/v2/token`
- **Base URL:** `https://www.zohoapis.in/books/v3`
- **GST routing:** `org_state_code` in integration config vs vendor GSTIN state prefix
  - Same state → CGST+SGST (intra-state)
  - Different state → IGST (inter-state)
  - State codes: TN=33, MH=27, KA=29, DL=07
- **Push is draft-centric:** always goes through `invoice_drafts`, not `invoices` directly
- After push: update BOTH `invoice_drafts.status/external_bill_id` AND `invoices.zoho_push_status/zoho_bill_id`
- **Zoho line item fields required:** `name`, `description`, `hsn_or_sac`, `tax_id`, `account_id`, `rate`, `quantity`

**Key Zoho account/tax IDs (live org):**
- GST18 tax group: `3699544000000109129`
- CGST9: `3699544000000109057`
- SGST9: `3699544000000109058`
- Default account (Bank Fees & Charges): `3699544000000000507`

---

## QuickBooks Integration

- Bills in home currency (`home_currency` config, default `"INR"`): no `CurrencyRef` needed
- Bills in foreign currency: BOTH `CurrencyRef` AND `ExchangeRate` required
- Config fields: `home_currency`, `default_exchange_rate`

---

## Database Schema — Key Tables

| Table | Notes |
|-------|-------|
| `companies` | Global — no company_id |
| `company_members` | Users → company mapping |
| `invoices` | Parsed invoices, one per PDF |
| `invoice_drafts` | Push-ready view of invoice, platform-specific |
| `invoice_payments` | Append-only payment ledger (references drafts + company_bank_accounts) |
| `company_bank_accounts` | Entvin's own bank accounts (payer side) |
| `vendor_mappings` | Source vendor → platform vendor |
| `platform_vendors` | Vendors synced from Zoho/QB |
| `audit_log` | Routine events (parsed, pushed, etc.) |
| `audit_logs` | Compliance events — overrides with full actor identity |
| `system_config` | Runtime config overrides (no restart needed) |
| `integrations` | Per-tenant OAuth/API credentials (base64 encoded) |

**FK delete order matters:** `invoice_payments` → `invoice_drafts` → `invoices` → `company_bank_accounts`

---

## Admin Dashboard

- URL: `http://localhost:3001/admin`
- Requires `ADMIN_API_KEY` entered in the UI (header: `X-Admin-Key`)
- **Truncate (flush):** deletes all invoice/payment/draft data for a company, keeps company + members + integrations
- Flush tables (in order): `invoice_payments`, `invoice_drafts`, `invoices`, `company_bank_accounts`, `processed_emails`, `vendor_cache`, `audit_log`, `rules`, `vendor_mappings`, `platform_vendors`

---

## Coding Standards (enforced)

1. **No raw SQL with string interpolation** — SQLAlchemy ORM or parameterised queries only
2. **No runtime `__import__()`** — top-level imports only (except circular import avoidance)
3. **Sanitize all user input** — filenames, headers, query params
4. **Never expose raw exceptions to client** — log internally, return generic message
5. **All bulk operations capped** — max 500 items per call
6. **All list queries bounded** — require `limit`, max 5000
7. **File uploads validated** — check extension against whitelist before processing
8. **Secrets never in error messages** — mask API keys/tokens in user-facing output
9. **Audit log all mutations** — create/update/delete on business entities
10. **Standardised error format** — `{status: "error", message: "..."}`
11. **Tenant-scoped repos only** — never `db.query(Model)` directly, always `TenantBaseRepository`
12. **No hardcoded magic strings** — constants, enums, or registry lookups
13. **Sensitive files: `0o600` permissions** — OAuth state, token files

---

## Runtime Config (no restart needed)

All settings can be overridden at runtime via `POST /api/admin/config`:
- `PARSER_MODE` — `llm`, `tesseract`, `llamaparse`
- `LLM_PROVIDER` — `openai`, `ollama`
- `LLM_MODEL` — `gpt-4o`, etc.
- `LLM_API_KEY` — overrides `.env`

Overrides stored in `system_config` table. `settings.__getattribute__` checks DB first, then `.env`.

---

## Audit Trail

Two tables — both must be queried for complete trail:
- `audit_log` — routine events (parsed, draft_created, pushed, vendor_resolved)
- `audit_logs` — compliance events (overrides with actor email, name, role)

---

## Live Zoho Bills (as of 2026-05-06)

| Bill ID | Bill # | Vendor | Total | Status |
|---------|--------|--------|-------|--------|
| 3699544000000148002 | INV/2024-25-748 | Vithana Consulting | ₹17,110 | overdue |
| 3699544000000147002 | INV/2024-25-696 | Vithana Consulting | ₹76,700 | overdue |
| 3699544000000146002 | CA/25-26/340 | Kodo Technologies | ₹11.80 | overdue |
| 3699544000000145002 | CA/25-26/63 | Kodo Technologies | ₹11.80 | overdue |

**ITC at risk:** ₹14,313.60 total — cutoff 30 Nov 2026 (FY 2025-26). All overdue, unpaid.

**Known open issues:**
- Vithana bills use GL account "Bank Fees and Charges" — should be "Professional Fees" (fix manually in Zoho)
- Kodo CA/25-26/340 and CA/25-26/63 are structurally identical — possible duplicate, verify with Kodo
- No post-push GET verification — bill ID stored from response but never confirmed

---

## Production Checklist (before go-live)

**Security:**
- [ ] Remove `localhost` from CORS origins (`app/main.py`)
- [ ] Remove default `JWT_SECRET_KEY` — fail hard if not set in env
- [ ] Remove default `DATABASE_URL` credentials from `app/config.py`
- [ ] Upgrade integration encryption from base64 → AES-256-GCM (`app/platforms/base.py`)
- [ ] Set `secure=True, samesite="strict"` on JWT cookies + add CSRF protection
- [ ] Verify Google OAuth redirect URI resolves correctly in production

**Performance:**
- [ ] Fix N+1 query in vendor mapping listing — replace Python iteration with SQL JOIN
- [ ] Use explicit column lists in MySQL views (not `SELECT *`)
- [ ] Tune DB connection pool (`pool_size`, `max_overflow`, `pool_recycle`)
- [ ] Add rate limiting on admin endpoints, bulk ops, and LLM parser calls

**Ops:**
- [ ] Move Gmail fetch to background worker (Celery/ARQ)
- [ ] Add request logging middleware (method, path, status, duration, user_id, company_id)
- [ ] Add deep health check (MySQL + LLM API reachability)
- [ ] Add OAuth token TTL tracking + expiry alerts
- [ ] Set up MySQL backups
- [ ] Configure nginx reverse proxy with HTTPS
- [ ] Add Sentry (error tracking) + Prometheus/Grafana (metrics)
- [ ] Run `alembic upgrade head` (never `create_all`) on deploy

---

## Key File Locations

| Purpose | Path |
|---------|------|
| LLM parser | `backend/app/parsers/llm_parser.py` |
| Tesseract parser | `backend/app/parsers/tesseract_parser.py` |
| Zoho client | `backend/app/platforms/zoho/client.py` |
| Zoho mapper | `backend/app/platforms/zoho/mappers.py` |
| Draft routes (push) | `backend/app/api/draft_routes.py` |
| Payment routes | `backend/app/api/payment_routes.py` |
| Admin routes (flush) | `backend/app/api/admin_routes.py` |
| DB models | `backend/app/models/db_models.py` |
| Tenant middleware | `backend/app/tenant/middleware.py` |
| Config + runtime override | `backend/app/config.py` |
| Alembic migrations | `backend/alembic/versions/` |
| Test invoices + ground truth | `backend/data/test_invoices/` |
| LLM accuracy test | `backend/test_llm_parser_accuracy.py` |
| Admin UI | `frontend/src/app/admin/page.tsx` |
| Invoice list + bank panel | `frontend/src/app/(authenticated)/invoices/page.tsx` |
| Payments page | `frontend/src/app/(authenticated)/payments/page.tsx` |
