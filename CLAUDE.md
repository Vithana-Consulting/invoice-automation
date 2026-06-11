# Vithana Accounting Automation — POC (Day 3)

## What This Is

Multi-tenant invoice automation SaaS POC. Gmail → PDF → LLM parse → validate → push to Zoho Books (or QuickBooks / Tally).
Built by Deepak (deepak2004sakthi@gmail.com / Deepak.sakthi@vithanaconsulting.com).

---

## How to Start

```bash
# 1. Database (MySQL in Docker). Base compose does NOT publish 3306 to the host;
#    docker-compose.override.yml adds 127.0.0.1:3306 so local uvicorn can connect.
docker compose up -d db        # brings up day3-db-1 (waits for healthy)

# 2. Backend — app object is `application`, NOT `app`
cd backend && .venv/bin/uvicorn app.main:application --reload --port 8000

# 3. Frontend — `next dev` defaults to port 3000 (no port is hardcoded)
cd frontend && npm run dev     # → http://localhost:3000
```

**Port reality (read this):**
- Backend listens on **8000**.
- Frontend `next dev` defaults to **3000**. The CORS allow-list in `app/main.py` covers `localhost:3000–3005`, so any of those works.
- `.env` `FRONTEND_URL=http://localhost:3005` — this is only used for the **OAuth post-login redirect** (`/dashboard`). If you run the FE on 3000 and want the login redirect to land correctly, either run the FE on the port matching `FRONTEND_URL` or update `FRONTEND_URL`.
- Port **3001** may be occupied by an unrelated local project — don't assume it's this app.

**Full dockerized stack (LAN deployment):** `docker compose up -d` builds and runs backend + frontend + db together (see [Deployment](#deployment)). The dockerized images are built from committed code, so they will NOT reflect uncommitted local edits — use the local uvicorn/npm flow for active development.

**MySQL connect:**
```bash
docker exec -it day3-db-1 mysql -uaccounting -paccounting accounting_automation
```

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic (13 migrations) |
| Frontend | Next.js 14.2.15 (App Router), React 18, TypeScript, AG Grid 32, TanStack Query 5, Recharts |
| Database | MySQL 8.0 (Docker: `day3-db-1`) |
| Parser | LLM vision (provider registry) — default `gpt-4o`; LlamaParse + Tesseract fallbacks |
| Auth | Google OAuth per-tenant, JWT cookie (`access_token`) |
| Accounting | Zoho Books (India, INR) + QuickBooks + Tally (pluggable) |

---

## .env (backend/.env)

Real secret values are masked here — see the actual file for live keys. POC-level non-secrets (`JWT_SECRET_KEY`, `ADMIN_API_KEY`) are shown verbatim because they're needed to operate the app.

```
APP_NAME=vithana-accounting-platform
DEBUG=true

DATABASE_URL=mysql+pymysql://accounting:accounting@localhost:3306/accounting_automation
PARSER_MODE=llm
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=<openai key>
LLM_BASE_URL=

GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json
GMAIL_LABEL=invoices

LLAMAPARSE_API_KEY=<llamaparse key>
ATTACHMENT_DIR=data/attachments

GOOGLE_CLIENT_ID=<google client id>
GOOGLE_CLIENT_SECRET=<google client secret>
GOOGLE_REDIRECT_URI=http://localhost:8001/api/auth/google/callback   # see note below

JWT_SECRET_KEY=v1th4n4-d4y3-p0c-s3cr3t-k3y-2026
ADMIN_API_KEY=1

FRONTEND_URL=http://localhost:3005
```

> **`PARSER_MODE` default mismatch:** the code default in `app/config.py` is `tesseract`, but `.env` sets `llm`. The `.env` value wins.
>
> **`GOOGLE_REDIRECT_URI` is read from the DB, not `.env`.** The Gmail-connect flow calls `sysconfig.get("GOOGLE_REDIRECT_URI")`, which reads **only** the `system_config` table (no `.env` fallback — it raises `ConfigNotSetError` if missing). Set it via the Admin config API (below). The per-company login flow uses its own `redirect_uri` stored in the `integrations` row instead.
>
> **`ADMIN_API_KEY=1`** — the admin API header is `X-Admin-Key: 1`. (Older docs referenced `v1th4n4-flush-s3cr3t-2026`; that is stale.)

**Frontend env** (`frontend/.env.local`): `NEXT_PUBLIC_API_URL=http://localhost:8000`. `next.config.js` rewrites `/api/:path*` → `${NEXT_PUBLIC_API_URL}/api/:path*` (falls back to `http://localhost:8000`).

---

## Multi-Tenancy

- Single MySQL DB, `company_id` on ALL tenant tables — no exceptions
- `TenantContext` via Python `contextvars` (async-safe) — `app/tenant/context.py`
- ASGI middleware (`TenantMiddleware`) sets context from JWT cookie — NOT a FastAPI dependency (`app/tenant/middleware.py`)
- `TenantBaseRepository` auto-filters all queries by `company_id` and stamps it on insert (`app/tenant/repository.py`)
- `Company.domain` maps email domains to companies at login
- Google OAuth credentials stored per-company (`platform="google_oauth"` in `integrations` table)

**Middleware skips:** `/health`, `/config`, `/docs`, `/openapi.json`, `/redoc`, and prefixes `/api/auth/`, `/api/admin/`. For all other routes it decodes the `access_token` cookie → `sub` (user_id) → resolves company via `CompanyMember` (first active membership, or the one named by an optional `X-Company-Id` header after membership check) → `TenantContext.set(company_id)`. Context is always cleared in a `finally`.

**Auth flow:** email/slug → company lookup → company's OAuth credentials → signed state JWT (5 min TTL, `type=oauth_state`) → Google → callback decodes company_id → upsert user + membership → JWT cookie.

> **Known data quirk:** the demo company's `domain` is set to a full email (`deepak...@gmail.com`) rather than `gmail.com`, so `login-by-email` 404s for that domain. Slug login (`/api/auth/login` with the company slug) works.

---

## Parser Pipeline

```
PDF → images (pdf2image) → LLM vision → validate → retry up to 3× with correction prompt
                                                  ↘ (non-vision providers: Tesseract OCR → LLM text)
```

- **Three modes** (`PARSER_MODE`): `llm` (default in `.env`), `llamaparse`, `tesseract`. Factory in `app/parsers/__init__.py`.
- **LLM provider registry** (`@register_llm_provider` in `app/parsers/llm_providers.py`) — registered: **`openai`, `anthropic`, `google` (Gemini, OpenAI-compatible), `ollama`**. Vision-capable providers extract from images directly; others fall back to OCR→text.
- **Retry loop** (`MAX_PARSE_ATTEMPTS = 3`): re-parses while validation errors exist, appending a human-readable correction section. After 3 attempts, a final auto-correction pass attempts single-char GSTIN fixes / PAN-based reconstruction.
- **In-parser validation** (`_validate_invoice`): `invoice_number` (≥3 chars), `vendor_name`, `total_amount > 0`, `invoice_date` format, GSTIN format + **checksum** (detects single-char transposition), GSTIN↔PAN cross-check, buyer GSTIN. GSTIN utils in `app/utils/gstin_utils.py`.

**Critical:** `invoice_number` must be copied CHARACTER BY CHARACTER — digit transposition = ITC failure.

### Pre-push validation pipeline (8 validators)

`app/services/validation/validators.py` — `build_pre_push_pipeline()`. All are `HARD_BLOCK` unless noted:

| # | Validator | Code | Overridable? |
|---|-----------|------|--------------|
| 1 | `CompositionVendorValidator` | `COMPOSITION_VENDOR_ITC_INELIGIBLE` | **NO — absolute hard stop** (`non_overridable=True`) |
| 2 | `AmountReconciliationValidator` | `RECONCILIATION_FAILED` | yes |
| 3 | `GSTINFormatValidator` | `INVALID_GSTIN_FORMAT` | yes |
| 4 | `GSTINPanMatchValidator` | `GSTIN_PAN_MISMATCH` | yes |
| 5 | `RCMValidator` (blank GSTIN → S.9(4) self-assessment) | `RCM_SELF_ASSESSMENT_REQUIRED` | yes |
| 6 | `GSTRoutingValidator` (Zoho `org_state_code` configured) | `GST_ROUTING_UNCONFIGURED` | yes |
| 7 | `ITCTimeLimitValidator` (S.16(4) — 30 Nov cutoff) | `ITC_TIME_LIMIT_EXCEEDED` | yes (WARNING within 60 days of cutoff) |
| 8 | `DuplicateBillValidator` (two-tier: vendor+number, vendor+date+amount) | `PROBABLE_DUPLICATE` | yes |

- **Override:** overridable HARD_BLOCKs are bypassed by supplying an `override_reason_code` (validated against an allowlist) on the draft push. `CompositionVendorValidator` can NEVER be overridden (`draft_routes.py` rejects any override of a non-overridable block).
- **All overrides logged** to the immutable `audit_logs` table with denormalized actor identity (email, name, role).

---

## API Routes

Registered in `app/api/router.py`. Tenant context is set by middleware before handlers run.

| Prefix | File | Purpose |
|--------|------|---------|
| *(none)* `/health` | `health_routes.py` | Health + status (db, parser_mode, llm config) |
| `/api/auth` | `auth_routes.py` | Per-tenant Google OAuth login, callback, logout, `/me`, public company list |
| `/api/admin` | `admin_routes.py` | Company CRUD, runtime config, flush, per-company OAuth, **key-pool status** |
| `/api/drafts` | `draft_routes.py` | Draft lifecycle: review, validate, override, push to platform |
| `/api/rules` | `rule_routes.py` | Rule engine (priority, conditions, actions) |
| `/api/vendor-mappings` | `vendor_mapping_routes.py` | Source vendor → platform vendor (per platform) |
| `/api/vendors` | `vendor_routes.py` | Vendor master + invoice aggregation |
| `/api/integrations` | `integration_routes.py` | Connect/manage Zoho, QB, Tally, Gmail, etc. |
| `/api/ingest` | `ingest_routes.py` | Reparse / reparse-all / preflight |
| `/api/dashboard` | `dashboard_routes.py` | Summary stats, recent activity, integration health |
| `/api/settings` | `settings_routes.py` | Company settings, Gmail credentials/connect |
| `/api/coa` | `coa_routes.py` | Chart of Accounts sync + tagging (sub_type, HSN, TDS) |
| `/api/bank-details` | `bank_routes.py` | Vendor bank details extracted from PDFs |
| `/api` | `payment_routes.py` | Company bank accounts + invoice payment ledger |

---

## API-Key Pool / Failover (`app/core/key_pool.py` — newer)

Rotating credential pool with per-key cooldown, used by the LLM parser, LlamaParse, and Zoho auth. A single key string is treated as a pool of one (backward-compatible, zero-config). Keys can be comma/semicolon/newline-separated.

- On rate-limit (429) or transient failure, the key is **parked** for `KEY_POOL_COOLDOWN_SECONDS` (default `60.0`, an EDITABLE key) and the next healthy key is used; it re-enters rotation after cooldown.
- `run_with_rotation(pool, fn)` drives the retry; `is_fatal_error()` short-circuits on 400/404/422 (bad request — rotating won't help).
- Process-wide registry keyed by integration name (e.g. `zoho:<org_id>` for multi-org isolation).
- Health snapshot (masked) surfaced via the admin key-pool endpoint.

---

## Runtime Config (no restart needed)

`app/config.py` Settings reads DB overrides first for **`EDITABLE_KEYS`** via a `__getattribute__` hook (`_load_overrides()` queries the `system_config` table). Bootstrap keys are never read from DB.

- **EDITABLE_KEYS:** `PARSER_MODE`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLAMAPARSE_API_KEY`, `STORAGE_BACKEND`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `FRONTEND_URL`, `DEBUG`, `MAX_RETRIES`, `KEY_POOL_COOLDOWN_SECONDS`
- **READONLY_KEYS** (never overridable at runtime): `DATABASE_URL`, `ADMIN_API_KEY`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`
- **SECRET_KEYS** (masked in API responses): `LLM_API_KEY`, `LLAMAPARSE_API_KEY`, `GOOGLE_CLIENT_SECRET`, `JWT_SECRET_KEY`, `ADMIN_API_KEY`, `INTEGRATION_ENCRYPTION_KEY`, `ANTHROPIC_API_KEY`

**Set a config value** (e.g. the Gmail redirect — required before connecting Gmail on a fresh DB):
```bash
curl -X PUT http://localhost:8000/api/admin/config \
  -H "X-Admin-Key: 1" -H "Content-Type: application/json" \
  -d '{"GOOGLE_REDIRECT_URI": "http://localhost:8000/api/auth/google/callback"}'
```
Endpoints: `GET/PUT /api/admin/config`, `DELETE /api/admin/config/{key}`, `DELETE /api/admin/config` (reset all editable). The Gmail redirect is derived as `<base of GOOGLE_REDIRECT_URI>/api/settings/gmail-callback`.

---

## Zoho Integration

- **Region:** India (`.in` endpoints). Defaults: auth `https://accounts.zoho.in/oauth/v2/token`, base `https://www.zohoapis.in/books/v3`.
- **All IDs are config-driven, not hardcoded:** `organization_id`, `default_account_id`, `tax_id` (CGST+SGST group), `igst_tax_id`, `org_state_code`, `base_url`, `auth_url`, OAuth creds — all in the encrypted `integrations` config (`app/platforms/zoho/service.py` `get_config_fields()`).
- **GST routing** (`service.py`): compares **vendor state (vendor GSTIN[:2]) vs buyer state (buyer GSTIN[:2])**, falling back to `org_state_code` only when the buyer GSTIN is absent.
  - Same state → CGST+SGST (`tax_id`). Different → IGST (`igst_tax_id`).
  - State codes: TN=33, MH=27, KA=29, DL=07.
- **Self-healing push:** on Zoho "igst has to be applied" / "cannot be applied" errors it retries with the other tax grouping; on "already created" it dedupes by bill number.
- **Push is draft-centric:** always via `invoice_drafts` (`PENDING_REVIEW → APPROVED → PUSHED`), never `invoices` directly. Idempotency via `find_bill_by_number()` before create.
- **Zoho line item fields:** `name`, `description`, `hsn_or_sac`, `tax_id`, `account_id`, `rate`, `quantity`.
- **OAuth:** `ZohoAuth` supports a list of backup credential sets and pools them (`pool_name=zoho:<org_id>`); refreshes are rate-limited and parked on 401.

**Reference — live demo-org IDs (as of 2026-05-06, stored in integration config; may be stale, NOT in code):**
GST18 group `3699544000000109129` · CGST9 `3699544000000109057` · SGST9 `3699544000000109058` · default account (Bank Fees & Charges) `3699544000000000507`.

---

## QuickBooks Integration

- Bills in home currency (`home_currency`, default `"INR"`): no `CurrencyRef`.
- Foreign currency: BOTH `CurrencyRef` AND `ExchangeRate` required (from `draft.exchange_rate` → config `default_exchange_rate` → else error).
- Config fields: `home_currency`, `default_exchange_rate`, `realm_id`, base/OAuth fields.

## Tally

Also registered as a billing platform (`@register_billing`); COA sync supported.

---

## Database Schema — Key Tables

**Global (no `company_id`):** `companies`, `users`, `company_members`, `system_config`.

**Tenant-scoped (all carry `company_id`):**

| Table | Model | Notes |
|-------|-------|-------|
| `processed_emails` | `ProcessedEmail` | Gmail fetch log |
| `invoices` | `InvoiceRecord` | Parsed invoice, one per PDF (INBOUND/OUTBOUND) |
| `invoice_drafts` | `InvoiceDraft` | Push-ready, platform-specific; carries `override_reason_code`, ITC/TDS, payment tracking |
| `invoice_payments` | `InvoicePayment` | Append-only payment ledger (method, payer bank acct, payee, TDS, status) |
| `company_bank_accounts` | `CompanyBankAccount` | Own (payer-side) bank accounts |
| `vendor_mappings` | `VendorMapping` | Source vendor → platform vendor; `is_composition_vendor` flag |
| `platform_vendors` | `PlatformVendor` | Vendors synced from Zoho/QB |
| `platform_tds_taxes` | `PlatformTdsTax` | TDS tax masters (section+rate → platform tax id) |
| `chart_of_accounts` | `ChartOfAccount` | Synced COA + tags (sub_type, HSN, TDS) |
| `integrations` | `Integration` | Per-tenant OAuth/API creds (base64-encoded config) |
| `rules` | `Rule` | Auto-routing rules |
| `vendor_cache` | `VendorCache` | Legacy Day2 cache |
| `extraction_logs` | `ExtractionLog` | **Immutable, insert-only** — raw LLM JSON per invoice (S.36 CGST, 72-mo retention) |
| `audit_log` | `LegacyAuditLog` | Routine events (parsed, draft_created, pushed) — mutable |
| `audit_logs` | `AuditLog` | **Immutable** compliance events — overrides with denormalized actor identity |
| `secret_rotation_log` | `SecretRotationLog` | Insert-only secret-rotation events |

**FK delete order matters:** `invoice_payments` → `invoice_drafts` → `invoices` → `company_bank_accounts`.

---

## Audit Trail

Three insert-only tables, queried together for a complete picture:
- `audit_log` — routine events (mutable legacy log).
- `audit_logs` — compliance events (overrides) with actor email/name/role stamped at write time.
- `extraction_logs` — raw parser output retained for statutory compliance.

---

## Integration Encryption

`app/platforms/base.py` `encrypt_config`/`decrypt_config` are **base64 of JSON — encoding, not encryption.** Platforms register via `@register_billing` / `@register_source`; configs load through `get_billing_platform()`. Upgrading to real AES-256-GCM is on the production checklist.

---

## Admin Dashboard

- URL: `http://localhost:3000/admin` (header `X-Admin-Key: 1`).
- **Truncate (flush):** deletes invoice/payment/draft data for a company, keeps company + members + integrations.
- Flush order: `invoice_payments` → `invoice_drafts` → `invoices` → `company_bank_accounts` → `processed_emails` → `vendor_cache` → `audit_log` → `rules` → `vendor_mappings` → `platform_vendors`.

---

## Deployment

| File | Role |
|------|------|
| `docker-compose.yml` | LAN deployment: builds backend+frontend+db. DB has **no host port** (docker network only). Backend `DATABASE_URL` → `db:3306`; `FRONTEND_URL`/`NEXT_PUBLIC_API_URL` hardcoded to LAN IP `192.168.68.113`. |
| `docker-compose.override.yml` | Local-dev convenience: publishes MySQL on `127.0.0.1:3306` so local uvicorn can reach it. (Untracked.) |
| `docker-compose.prod.yml` | Production: Caddy reverse proxy (80/443, HTTPS), MySQL backup to Backblaze B2; backend/frontend internal-only. |

---

## Coding Standards (enforced)

1. No raw SQL with string interpolation — ORM or parameterised only
2. No runtime `__import__()` — top-level imports (except circular-import avoidance)
3. Sanitize all user input — filenames, headers, query params
4. Never expose raw exceptions to client — log internally, return generic message
5. All bulk operations capped — max 500 items per call
6. All list queries bounded — require `limit`, max 5000
7. File uploads validated — extension whitelist before processing
8. Secrets never in error messages — mask API keys/tokens
9. Audit log all mutations — create/update/delete on business entities
10. Standardised error format — `{status: "error", message: "..."}`
11. Tenant-scoped repos only — never `db.query(Model)` for tenant data; use `TenantBaseRepository`
12. No hardcoded magic strings — constants, enums, registry lookups
13. Sensitive files: `0o600` permissions — OAuth state, token files

---

## Production Checklist (before go-live)

**Security:**
- [ ] Remove `localhost` from CORS origins (`app/main.py`)
- [ ] Remove default `JWT_SECRET_KEY` — fail hard if unset
- [ ] Remove default `DATABASE_URL` credentials from `app/config.py`
- [ ] Upgrade integration encryption from base64 → AES-256-GCM (`app/platforms/base.py`)
- [ ] Set `secure=True, samesite="strict"` on JWT cookies + CSRF protection
- [ ] Verify Google OAuth redirect URI resolves in production
- [ ] Real `ADMIN_API_KEY` (currently `1`)

**Performance:**
- [ ] Fix N+1 in vendor mapping listing — SQL JOIN
- [ ] Explicit column lists in MySQL views (not `SELECT *`)
- [ ] Tune DB pool (`pool_size`, `max_overflow`, `pool_recycle`)
- [ ] Rate-limit admin endpoints, bulk ops, LLM parser calls

**Ops:**
- [ ] Move Gmail fetch to background worker (Celery/ARQ)
- [ ] Request logging middleware (method, path, status, duration, user_id, company_id)
- [ ] Deep health check (MySQL + LLM API reachability)
- [ ] OAuth token TTL tracking + expiry alerts
- [ ] MySQL backups (prod compose ships B2 backup)
- [ ] nginx/Caddy reverse proxy with HTTPS (prod compose ships Caddy)
- [ ] Sentry + Prometheus/Grafana
- [ ] `alembic upgrade head` (never `create_all`) on deploy

---

## Key File Locations

| Purpose | Path |
|---------|------|
| App entry (`application`) + middleware | `backend/app/main.py` |
| Config + runtime override | `backend/app/config.py` |
| API-key pool / failover | `backend/app/core/key_pool.py` |
| LLM parser | `backend/app/parsers/llm_parser.py` |
| LLM provider registry | `backend/app/parsers/llm_providers.py` |
| Tesseract / LlamaParse parsers | `backend/app/parsers/{tesseract,llamaparse}_parser.py` |
| Validators (pre-push) | `backend/app/services/validation/validators.py` |
| Zoho client / mapper / auth / service | `backend/app/platforms/zoho/{client,mappers,auth,service}.py` |
| Platform base + encryption + registry | `backend/app/platforms/base.py` |
| Account/TDS resolver | `backend/app/platforms/account_resolver.py` |
| Draft routes (push) | `backend/app/api/draft_routes.py` |
| Payment routes | `backend/app/api/payment_routes.py` |
| Admin routes (config/flush) | `backend/app/api/admin_routes.py` |
| DB models | `backend/app/models/db_models.py` |
| Tenant (context/middleware/repo) | `backend/app/tenant/{context,middleware,repository}.py` |
| OAuth helpers | `backend/app/auth/oauth.py` |
| Alembic migrations | `backend/alembic/versions/` |
| Test invoices + ground truth | `backend/data/test_invoices/` (14 PDFs + `ground_truth.json`) |
| LLM accuracy test | `backend/test_llm_parser_accuracy.py` |
| Frontend API client | `frontend/src/lib/api.ts` |
| Admin UI | `frontend/src/app/admin/page.tsx` |
| Authenticated pages | `frontend/src/app/(authenticated)/{invoices,payments,vendors,vendor-mappings,integrations,settings,chart-of-accounts,bank-details,rules,dashboard}/page.tsx` |
| Docs | `docs/GOOGLE_SETUP.md`, `docs/ZOHO_SETUP.md`, `docs/INTEGRATIONS.md` |
