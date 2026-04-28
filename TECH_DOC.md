# Vithana Accounting Platform — Technical Documentation

## Database Architecture & Multi-Tenant Implementation

**Version:** 0.3.0 (Day 3 POC)
**Database:** MySQL 8.0 (Docker)
**ORM:** SQLAlchemy 2.0
**Backend:** FastAPI + Python 3.12
**Frontend:** Next.js 14 + React 18 + AG Grid

---

## 1. Multi-Tenant Architecture

### Design Principle
Single MySQL database with **row-level tenant isolation** via `company_id` on every tenant-scoped table. No separate databases, no sharding — just filtered queries.

### How It Works

```
Request → JWT Cookie → get_current_user() → User
                                               ↓
                                    get_tenant_context()
                                               ↓
                                    CompanyMember lookup
                                               ↓
                                    TenantContext.set(company_id)
                                               ↓
                                    Repository._base_query()
                                    → SELECT * FROM invoices
                                      WHERE company_id = {tenant_id}
```

### Key Components

| Component | File | Purpose |
|---|---|---|
| `TenantContext` | `app/tenant/context.py` | Holds `company_id` per request via Python `contextvars` |
| `TenantBaseRepository` | `app/tenant/repository.py` | Base class — auto-filters queries, auto-stamps inserts |
| `get_tenant_context` | `app/auth/dependencies.py` | FastAPI dependency — resolves user → company |
| `CompanyService` | `app/tenant/service.py` | Company creation, membership, view provisioning |
| MySQL Views | `app/tenant/views.py` | Creates `v_company_{id}_{table}` views per tenant |

### Tenant Context Flow (contextvars)

```python
# Set by middleware at request start (per-request, async-safe)
TenantContext.set(company_id)

# Used by every repository automatically
class InvoiceRepository(TenantBaseRepository):
    model = InvoiceRecord

    def list_all(self):
        return self._base_query()  # → WHERE company_id = current_tenant
                  .order_by(...)
                  .all()

    def create(self, record):
        return self._create(record)  # → stamps company_id before INSERT
```

---

## 2. Database Schema

### Entity Relationship Diagram

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│   companies   │────<│ company_members  │>────│    users      │
│              │     │                 │     │              │
│ id (PK)      │     │ user_id (FK)    │     │ id (PK)      │
│ name         │     │ company_id (FK) │     │ email (UQ)   │
│ slug (UQ)    │     │ role            │     │ name         │
│ is_active    │     │ is_active       │     │ google_sub   │
└──────┬───────┘     └─────────────────┘     │ is_admin     │
       │                                      └──────────────┘
       │ company_id (FK on all tenant tables)
       │
       ├──→ invoices
       ├──→ invoice_drafts
       ├──→ rules
       ├──→ vendor_mappings
       ├──→ integrations
       ├──→ platform_vendors
       ├──→ processed_emails
       ├──→ vendor_cache
       └──→ audit_log
```

### Table Classification

| Table | Scope | Has company_id | Purpose |
|---|---|---|---|
| `companies` | Global | No (IS the tenant) | Tenant entities |
| `users` | Global | No | Auth users, can belong to multiple companies |
| `company_members` | Global | Has company_id FK | User ↔ Company link with roles |
| `invoices` | Tenant | Yes | Raw invoice files + parsed metadata |
| `invoice_drafts` | Tenant | Yes | Editable invoice snapshots for review/push |
| `rules` | Tenant | Yes | Routing rules (auto-assign platform) |
| `vendor_mappings` | Tenant | Yes | Source vendor → platform vendor mapping |
| `integrations` | Tenant | Yes | Platform credentials (encrypted) |
| `platform_vendors` | Tenant | Yes | Synced vendors from billing platforms |
| `processed_emails` | Tenant | Yes | Gmail/source email tracking |
| `vendor_cache` | Tenant | Yes | Legacy vendor lookup cache |
| `audit_log` | Tenant | Yes | Action audit trail |

### MySQL Views (per company)

On company signup, 9 views are auto-created:

```sql
CREATE VIEW v_company_{id}_invoices AS
  SELECT * FROM invoices WHERE company_id = {id};

CREATE VIEW v_company_{id}_invoice_drafts AS
  SELECT * FROM invoice_drafts WHERE company_id = {id};

-- ... same for all 9 tenant tables
```

Views are for:
- Direct DB access / reporting tools
- Admin dashboards
- Data export without application layer

---

## 3. Invoice Processing Pipeline

### Full Lifecycle

```
Email/Upload → Parse → Draft → Review → Vendor Check → Push
     ↓           ↓       ↓        ↓          ↓           ↓
  processed   invoices  invoice  PENDING   PENDING     PUSHED
  _emails     (PARSED)  _drafts  _REVIEW   _VENDOR     or
                                    ↓         ↓       PUSH_FAILED
                                 APPROVED  Map vendor
                                    ↓         ↓
                                  Push    Auto-approve
                                    ↓
                                 PUSHED
```

### Draft Status Machine

```
PENDING_REVIEW ──→ APPROVED ──→ PUSHED
       │              │
       │              ↓
       │         PUSH_FAILED ──→ (retry) ──→ PUSHED
       │
       ├──→ PENDING_VENDOR ──→ (vendor mapped) ──→ APPROVED
       │
       └──→ REJECTED
```

### Parser Pipeline

```
Invoice File (PDF/JPG/PNG)
        ↓
   PARSER_MODE?
        ↓
  ┌─── llm ──────────┐─── tesseract ─────┐─── llamaparse ────┐
  │                   │                    │                    │
  │ Vision-capable?   │ pdfplumber/OCR     │ LlamaParse API     │
  │  YES → send images│    ↓               │    ↓               │
  │  NO  → OCR → text │ regex extraction   │ markdown → regex   │
  │    ↓              │                    │                    │
  │ LLM Provider      │                    │                    │
  │ (OpenAI/Anthropic │                    │                    │
  │  /Google/Ollama)  │                    │                    │
  └───────────────────┴────────────────────┴────────────────────┘
        ↓
  Invoice {vendor_name, total_amount, invoice_number, ...}
```

### LLM Provider Registry (pluggable)

```python
@register_llm_provider("openai")     # GPT-4o (vision)
@register_llm_provider("anthropic")  # Claude (vision)
@register_llm_provider("google")     # Gemini (vision)
@register_llm_provider("ollama")     # Local models

# To add a new provider:
@register_llm_provider("groq")
class GroqProvider(LLMProvider):
    def call(self, prompt: str) -> str: ...
```

---

## 4. Vendor Management Workflow

### The Problem
Invoice says "Google PVP Ltd" but Zoho has "Google Private Limited". Without mapping, the push fails or creates duplicates.

### Solution: Mandatory Vendor Mapping

```
Source Vendors                Platform Vendors
(from parsed invoices)        (synced from Zoho/QB)

"Google PVP Ltd"    ←──MAP──→  "Google Private Limited"
"Sarvam"            ←──MAP──→  "Sarvam AI Pvt Ltd"
"Slack"             ←──MAP──→  "Slack Technologies Ltd"

     ↓                              ↓
vendor_mappings table:
  alias_name → canonical_name + platform + platform_vendor_id
```

### Enforcement Chain

```
Approve Draft → Check vendor_mapping → Missing? → PENDING_VENDOR (blocked)
Push Draft    → Check vendor_mapping → Missing? → PENDING_VENDOR (blocked)
Bulk Push     → Check vendor_mapping → Missing? → PENDING_VENDOR (blocked)
Platform Push → Check vendor_mapping → Missing? → Exception (blocked)
```

No invoice reaches any billing platform without an explicit vendor mapping.

---

## 5. Platform Integration Architecture

### Plugin Registry Pattern

```python
# Billing platforms (PUSH bills to)
@register_billing
class ZohoBilling(BillingPlatform): ...
class QuickBooksBilling(BillingPlatform): ...
class TallyBilling(BillingPlatform): ...

# Invoice sources (PULL invoices from)
@register_source
class GmailSource(InvoiceSource): ...
class StripeSource(InvoiceSource): ...
class ChargebeeSource(InvoiceSource): ...
```

### Platform Interface

```python
class BillingPlatform(ABC):
    def test_connection() → {healthy, message, details}
    def push_bill(draft, db) → {external_id, platform}
    def find_vendor(name) → vendor_id | None
    def create_vendor(name) → vendor_id
    def list_vendors() → [{id, name, email, status}]
    def get_config_fields() → [{key, label, type, required}]
```

### Credential Storage
- Stored in `integrations` table, per company
- Config encrypted via base64 (upgrade to AES for production)
- Decrypted at runtime when platform is instantiated

---

## 6. Authentication & Authorization

### Flow

```
Browser → Google OAuth → Callback → JWT Cookie → Authenticated Requests
                           ↓
                    Create User (if new)
                    Create Company (if first login)
                    Create MySQL Views
                    Issue JWT
```

### Request Pipeline

```
Request
  ↓
  JWT Cookie → get_current_user() → User object
                                       ↓
  X-Company-Id header (optional) → get_tenant_context()
                                       ↓
                                  CompanyMember lookup
                                       ↓
                                  TenantContext.set(company_id)
                                       ↓
                                  Route Handler
                                       ↓
                                  Repository (auto-filtered)
```

### Role Model

| Role | Permissions |
|---|---|
| `owner` | Full access, manage members, delete company |
| `admin` | Full access, manage members |
| `member` | Standard access, no member management |

---

## 7. API Endpoints

### Public (no auth)
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/config` | App configuration |
| GET | `/api/auth/google/login` | Start OAuth |
| GET | `/api/auth/google/callback` | OAuth callback |

### Admin (admin key via X-Admin-Key header)
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/admin/login` | Validate admin key |
| GET | `/api/admin/config` | List all config |
| PUT | `/api/admin/config` | Update runtime config |
| DELETE | `/api/admin/config/{key}` | Reset config to .env |
| POST | `/api/admin/flush` | Delete all data |

### Tenant-Scoped (JWT + tenant context)
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/drafts` | List/create drafts |
| POST | `/api/drafts/{id}/approve` | Approve draft |
| POST | `/api/drafts/{id}/push` | Push to platform |
| POST | `/api/drafts/apply-rules` | Run rules on drafts |
| POST | `/api/drafts/resolve-vendors` | Resolve pending vendors |
| GET/POST | `/api/rules` | List/create rules |
| PUT | `/api/rules/reorder` | Reorder rule priority |
| POST | `/api/rules/{id}/apply` | Apply single rule |
| GET/POST | `/api/vendor-mappings` | List/create mappings |
| GET | `/api/vendor-mappings/source-vendors` | Invoice vendor names |
| GET | `/api/vendor-mappings/platform-vendors/{p}` | Synced platform vendors |
| POST | `/api/vendor-mappings/platform-vendors/{p}/sync` | Pull from platform |
| POST | `/api/vendor-mappings/create-platform-vendor` | Create vendor on platform |
| GET/POST | `/api/integrations` | List/create integrations |
| POST | `/api/integrations/{id}/test` | Test connection |
| POST | `/api/ingest/{source}` | Ingest from source |
| POST | `/api/ingest/reparse/{id}` | Re-parse invoice |
| POST | `/api/ingest/reparse-all` | Re-parse all |
| GET | `/api/dashboard/summary` | Dashboard metrics |

---

## 8. Runtime Configuration

### Precedence (highest to lowest)

```
1. Integration Config (per-platform, per-company, in DB)
2. Runtime Overrides (data/runtime_config.json, via admin dashboard)
3. Environment Variables (.env file)
4. Code Defaults (app/config.py)
```

### Editable at Runtime (via Admin Dashboard)
`PARSER_MODE`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`,
`LLAMAPARSE_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`FRONTEND_URL`, `DEBUG`, `MAX_RETRIES`

### Read-Only (require restart)
`DATABASE_URL`, `ADMIN_API_KEY`, `JWT_SECRET_KEY`

---

## 9. File Structure

```
backend/
├── app/
│   ├── api/                    # Route handlers
│   │   ├── admin_routes.py     # Admin dashboard API
│   │   ├── auth_routes.py      # OAuth + signup
│   │   ├── dashboard_routes.py # Dashboard metrics
│   │   ├── draft_routes.py     # Invoice draft CRUD
│   │   ├── ingest_routes.py    # Email ingestion + reparse
│   │   ├── integration_routes.py # Platform integrations
│   │   ├── rule_routes.py      # Routing rules
│   │   ├── settings_routes.py  # User settings + Gmail
│   │   ├── vendor_mapping_routes.py # Vendor mappings
│   │   └── router.py          # Route registration + tenant deps
│   ├── auth/
│   │   ├── dependencies.py     # JWT + tenant resolution
│   │   └── oauth.py           # Google OAuth helpers
│   ├── db/
│   │   ├── repository.py      # All repository classes
│   │   └── session.py         # SQLAlchemy engine + session
│   ├── models/
│   │   ├── db_models.py       # SQLAlchemy models (12 tables)
│   │   └── domain.py          # Pydantic domain models
│   ├── parsers/
│   │   ├── __init__.py        # Parser registry
│   │   ├── base.py            # Abstract parser interface
│   │   ├── extraction.py      # Shared regex extraction logic
│   │   ├── llm_parser.py      # LLM parser (vision + text)
│   │   ├── llm_providers.py   # Pluggable LLM provider registry
│   │   ├── llamaparse_parser.py # LlamaParse parser
│   │   └── tesseract_parser.py # Tesseract OCR parser
│   ├── platforms/
│   │   ├── base.py            # Platform registry + interfaces
│   │   ├── zoho/              # Zoho Books integration
│   │   ├── quickbooks/        # QuickBooks integration
│   │   ├── tally/             # Tally Prime integration
│   │   ├── gmail/             # Gmail source
│   │   ├── stripe/            # Stripe source
│   │   └── chargebee/         # Chargebee source
│   ├── tenant/
│   │   ├── __init__.py        # Exports TenantContext, TenantBaseRepository
│   │   ├── context.py         # TenantContext (contextvars)
│   │   ├── repository.py      # TenantBaseRepository (auto-filter)
│   │   ├── service.py         # CompanyService (signup orchestration)
│   │   └── views.py           # MySQL view creation/deletion
│   ├── services/
│   │   ├── draft_service.py   # Draft lifecycle orchestration
│   │   ├── email_service.py   # Gmail fetching
│   │   └── invoice_service.py # Parse orchestration
│   ├── config.py              # Settings with runtime overrides
│   └── main.py                # FastAPI app entry point
├── data/
│   ├── attachments/           # Invoice files
│   └── runtime_config.json    # Runtime config overrides
├── tests/
│   └── test_e2e.py           # End-to-end integration tests (33 tests)
├── .env                       # Environment configuration
├── requirements.txt           # Python dependencies
└── docker-compose.yml         # Docker services (MySQL, backend, frontend)
```

---

## 10. Running the Platform

### Prerequisites
- Docker (for MySQL)
- Python 3.12+ (venv at `.venv/`)
- Node.js 18+ (for frontend)

### Start Services

```bash
# 1. MySQL (Docker)
docker compose up -d db

# 2. Backend
cd backend
source .venv/bin/activate
python -m uvicorn app.main:application --host 0.0.0.0 --port 8000 --reload

# 3. Frontend
cd frontend
npm run dev -- -p 3001
```

### Run Tests

```bash
cd backend
source .venv/bin/activate
python tests/test_e2e.py
```

### Admin Access

```bash
# Admin dashboard (browser)
http://localhost:3001/admin
# Key: value of ADMIN_API_KEY in .env

# Flush all data (curl)
curl -X POST http://localhost:8000/api/admin/flush -H "X-Admin-Key: YOUR_KEY"
```

---

## 11. Security Considerations

| Area | Implementation | Production TODO |
|---|---|---|
| Auth | Google OAuth + JWT cookies | Add CSRF, secure=True |
| Tenant Isolation | company_id on every query | Audit raw SQL for leaks |
| Secrets | Base64 encoded in DB | Upgrade to AES encryption |
| Admin | API key in header | Add rate limiting |
| CORS | Explicit origins | Restrict to production domain |
| File Upload | Stored locally | Move to S3/GCS |
| JWT | HS256, 24h expiry | Rotate keys, add refresh tokens |
