# Vithana Accounting Platform - Architecture

## Overview

Multi-tenant, multi-platform invoice automation. Each client company gets isolated data within a single MySQL database. Ingest invoices from any source (Gmail, Stripe, Chargebee), parse with AI (GPT-4o vision), apply routing rules, map vendors, review in an Excel-like UI, and push as bills to any billing platform (Zoho Books, Tally Prime, QuickBooks Online).

## System Diagram

```
                  ┌───────────────────┐
                  │   Next.js 14      │
                  │   Frontend :3001  │
                  │   + Admin :3001/admin
                  └─────────┬─────────┘
                            │ REST API (proxied)
                  ┌─────────▼─────────┐
                  │   FastAPI Backend  │
                  │   :8000            │
                  │                    │
                  │  ┌──────────────┐  │
                  │  │ Tenant Layer │  │  ← TenantContext (contextvars)
                  │  │ company_id   │  │  ← TenantBaseRepository
                  │  └──────────────┘  │
                  └─────────┬─────────┘
                            │
       ┌────────┬───────────┼───────────┬──────────┐
       │        │           │           │          │
  ┌────▼───┐ ┌──▼────┐ ┌───▼────┐ ┌───▼────┐ ┌──▼─────┐
  │ Zoho   │ │ Tally │ │  QB    │ │ Stripe │ │Chargebee│
  │ Books  │ │ Prime │ │ Online │ │  API   │ │  API   │
  └────────┘ └───────┘ └────────┘ └────────┘ └────────┘
  BILLING     BILLING    BILLING    SOURCE     SOURCE
                            │
                  ┌─────────▼─────────┐
                  │   MySQL 8.0       │
                  │   (Docker)        │
                  │   + Views per     │
                  │     company       │
                  └───────────────────┘
```

## Multi-Tenant Architecture

### Design: Row-Level Isolation

Single MySQL database. Every tenant-scoped table has a `company_id` column. No separate DBs, no sharding.

```
Request → JWT → get_current_user() → User
                                       ↓
                            get_tenant_context()
                                       ↓
                            CompanyMember lookup → company_id
                                       ↓
                            TenantContext.set(company_id)
                                       ↓
                            TenantBaseRepository._base_query()
                            → WHERE company_id = {current_tenant}
```

### Key Components

| Component | File | Purpose |
|---|---|---|
| `TenantContext` | `app/tenant/context.py` | Holds `company_id` per request (contextvars) |
| `TenantBaseRepository` | `app/tenant/repository.py` | Auto-filters queries, auto-stamps inserts |
| `get_tenant_context` | `app/auth/dependencies.py` | FastAPI dependency: user → company |
| `CompanyService` | `app/tenant/service.py` | Signup: create company + views |
| MySQL Views | `app/tenant/views.py` | `v_company_{id}_{table}` per tenant |

### Signup Flow

```
Google OAuth → Create User → No company? → Auto-create Company
                                                    ↓
                                          Create CompanyMember (owner)
                                          Create 9 MySQL views
                                          Issue JWT → Redirect to /dashboard
```

### MySQL Views (per company)

On signup, 9 views auto-created: `v_company_{id}_invoices`, `v_company_{id}_invoice_drafts`, etc. Used for reporting and direct DB access.

---

## Pipeline Flow

```
1. INGEST   → POST /api/ingest/{source}  (gmail | stripe | chargebee | upload)
2. PARSE    → LLM Vision (GPT-4o) | Tesseract OCR | LlamaParse
3. RULE     → First-match-wins rule engine → sets push_to platform
4. VENDOR   → Check vendor_mapping → Missing? → PENDING_VENDOR (blocked)
5. DRAFT    → InvoiceDraft created with status=PENDING_REVIEW
6. REVIEW   → User reviews in AG Grid, edits fields, approves
7. APPROVE  → Vendor mapping check → APPROVED or PENDING_VENDOR
8. PUSH     → Vendor mapping re-check → Push to billing platform
```

### Draft Status Machine

```
PENDING_REVIEW ──→ APPROVED ──→ PUSHED
       │              │
       │              └──→ PUSH_FAILED ──→ (retry) ──→ PUSHED
       │
       ├──→ PENDING_VENDOR ──→ (vendor mapped) ──→ APPROVED
       │
       └──→ REJECTED
```

### Vendor Mapping Enforcement

No invoice reaches any billing platform without an explicit vendor mapping. Enforced at 4 layers:
1. Approve: checks mapping → PENDING_VENDOR if missing
2. Push endpoint: checks mapping → blocks if missing
3. Bulk push: per-draft mapping check
4. Platform push_bill(): checks mapping → exception if missing

---

## Directory Structure

```
day3/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app, platform registration
│   │   ├── config.py                  # Settings with runtime overrides
│   │   │
│   │   ├── tenant/                    # Multi-tenant isolation layer
│   │   │   ├── context.py            # TenantContext (contextvars)
│   │   │   ├── repository.py         # TenantBaseRepository (auto-filter)
│   │   │   ├── service.py            # CompanyService (signup orchestration)
│   │   │   └── views.py              # MySQL view creation/deletion
│   │   │
│   │   ├── api/                       # Route handlers
│   │   │   ├── router.py             # Central router + tenant deps
│   │   │   ├── auth_routes.py        # Google OAuth + signup flow
│   │   │   ├── admin_routes.py       # Admin dashboard + runtime config
│   │   │   ├── draft_routes.py       # Draft CRUD + approve/push/rules
│   │   │   ├── rule_routes.py        # Rule CRUD + evaluate + reorder + apply
│   │   │   ├── vendor_mapping_routes.py # Mappings + source/platform vendors
│   │   │   ├── integration_routes.py # Platform config CRUD + health
│   │   │   ├── ingest_routes.py      # Ingest + reparse endpoints
│   │   │   ├── settings_routes.py    # User settings + Gmail credentials
│   │   │   ├── dashboard_routes.py   # Stats + activity + health
│   │   │   └── health_routes.py      # Public health check
│   │   │
│   │   ├── platforms/                 # Plugin architecture
│   │   │   ├── base.py               # ABCs, registry, factory
│   │   │   ├── zoho/                  # Zoho Books (auth, client, mappers, service)
│   │   │   ├── tally/                 # Tally Prime (XML client, service)
│   │   │   ├── quickbooks/            # QuickBooks Online (OAuth2, client, service)
│   │   │   ├── stripe/                # Stripe source (client, service)
│   │   │   ├── chargebee/             # Chargebee source (client, service)
│   │   │   └── gmail/                 # Gmail source (service)
│   │   │
│   │   ├── parsers/                   # Document parsing (pluggable)
│   │   │   ├── base.py               # InvoiceParser ABC
│   │   │   ├── extraction.py         # Shared regex extraction logic
│   │   │   ├── llm_parser.py         # LLM parser (vision + text fallback)
│   │   │   ├── llm_providers.py      # Pluggable LLM registry (OpenAI, Anthropic, Google, Ollama)
│   │   │   ├── tesseract_parser.py   # OCR-based parser
│   │   │   └── llamaparse_parser.py  # LlamaParse API parser
│   │   │
│   │   ├── auth/
│   │   │   ├── oauth.py              # Google OAuth2 web flow + JWT creation
│   │   │   └── dependencies.py       # JWT + tenant context resolution
│   │   │
│   │   ├── rules/
│   │   │   ├── engine.py             # Recursive AND/OR evaluator
│   │   │   └── schema.py             # Pydantic models
│   │   │
│   │   ├── models/
│   │   │   ├── db_models.py          # 12 SQLAlchemy models (multi-tenant)
│   │   │   └── domain.py             # Invoice, LineItem, APIResponse
│   │   │
│   │   ├── db/
│   │   │   ├── session.py            # Engine + SessionLocal (MySQL)
│   │   │   └── repository.py         # 10 repository classes (9 tenant-scoped)
│   │   │
│   │   ├── services/
│   │   │   ├── draft_service.py      # Draft lifecycle + vendor resolution
│   │   │   ├── email_service.py      # Gmail API fetcher
│   │   │   └── invoice_service.py    # Parser orchestration
│   │   │
│   │   └── core/
│   │       ├── exceptions.py         # Exception hierarchy
│   │       └── retry.py              # Tenacity retry decorator
│   │
│   ├── tests/
│   │   ├── test_e2e.py              # 33 integration tests (multi-tenant)
│   │   └── test_rule_engine.py       # 26 unit tests
│   ├── data/
│   │   ├── runtime_config.json       # Admin runtime overrides
│   │   └── attachments/              # Invoice files
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx            # Root layout + QueryProvider
│   │   │   ├── page.tsx              # Redirect to /login
│   │   │   ├── login/page.tsx        # Google OAuth sign-in
│   │   │   ├── admin/page.tsx        # Admin dashboard (runtime config)
│   │   │   └── (authenticated)/
│   │   │       ├── layout.tsx        # Sidebar + Topbar shell
│   │   │       ├── dashboard/        # Summary cards + activity (sub-tabs)
│   │   │       ├── invoices/         # AG Grid draft table (sub-tabs by status)
│   │   │       ├── rules/            # Rule builder + edit modal + apply
│   │   │       ├── vendor-mappings/  # Source/platform vendors + mapping
│   │   │       ├── integrations/     # Platform config + test connection
│   │   │       └── settings/         # Profile + Gmail API credentials
│   │   ├── components/
│   │   │   ├── ui/                   # SubTabs, VendorSelect, HoverText
│   │   │   ├── layout/              # Sidebar, Topbar
│   │   │   └── providers/           # QueryProvider
│   │   ├── lib/api.ts               # Typed fetch wrapper (FormData support)
│   │   └── types/index.ts           # TypeScript interfaces
│   ├── Dockerfile
│   ├── package.json
│   └── next.config.js               # API proxy to backend
│
├── docker-compose.yml                # Backend + Frontend + MySQL 8.0
├── ARCHITECTURE.md                   # This file
├── API_DOCS.md                       # API reference
└── TECH_DOC.md                       # Full technical documentation
```

## Platform Plugin System

### How it works

Each platform implements `BillingPlatform` (push) or `InvoiceSource` (pull). Self-registers via decorators.

```python
@register_billing
class ZohoBilling(BillingPlatform):
    platform_key = "zoho"
    def test_connection() → {healthy, message, details}
    def push_bill(draft, db) → {external_id, platform}
    def find_vendor(name) → vendor_id | None
    def create_vendor(name) → vendor_id
    def list_vendors() → [{id, name, email, status}]  # For sync
    def get_config_fields() → [{key, label, type, required}]
```

### Credential flow

```
User configures in UI → encrypted → integrations table (per company)
                                           ↓
API request → TenantContext → get_billing_platform(db, key)
                → decrypt → instantiate → API call
```

### Adding a new platform

1. Create `app/platforms/newplatform/`
2. Add `client.py` + `service.py` with `@register_billing` or `@register_source`
3. Import in `main.py`
4. Done — UI auto-discovers via `GET /api/integrations/platforms`

### Platform inventory

| Platform    | Type    | Auth        | Features                    |
|-------------|---------|-------------|-----------------------------|
| Zoho Books  | billing | OAuth2      | Push bills, list/create vendors |
| Tally Prime | billing | None (LAN)  | Push XML vouchers           |
| QuickBooks  | billing | OAuth2      | Push bills, query vendors   |
| Stripe      | source  | API Key     | Pull invoices               |
| Chargebee   | source  | API Key     | Pull invoices               |
| Gmail       | source  | OAuth2      | Pull email attachments      |

## Parser System (Pluggable)

### Three modes (configurable via `PARSER_MODE`)

| Mode | Engine | Vision | Accuracy | Cost |
|---|---|---|---|---|
| `llm` | GPT-4o / Claude / Gemini / Ollama | Yes (direct image) | Highest | ~$0.01/invoice |
| `llamaparse` | LlamaParse API | No (markdown) | High | LlamaParse pricing |
| `tesseract` | Tesseract OCR + pdfplumber | No (text) | Medium | Free |

### LLM Provider Registry (pluggable)

```python
@register_llm_provider("openai")     # GPT-4o with vision
@register_llm_provider("anthropic")  # Claude with vision
@register_llm_provider("google")     # Gemini with vision
@register_llm_provider("ollama")     # Local models (text only)
```

### Vision flow (LLM parser)

```
PDF → pdf2image → PNG pages → GPT-4o vision API → Structured JSON
JPG/PNG → direct → GPT-4o vision API → Structured JSON
(No Tesseract or OCR needed for vision-capable providers)
```

## Rule Engine

Recursive evaluator for nested AND/OR condition trees. Stored as JSON.

```json
{
  "operator": "AND",
  "conditions": [
    {"field": "vendor_name", "op": "contains", "value": "Google"},
    {"field": "total_amount", "op": "greater_than", "value": 10000}
  ]
}
```

**Operators:** equals, not_equals, contains, starts_with, ends_with, in_list, greater_than, less_than, is_empty, is_not_empty

**Evaluation:** First-match-wins by priority. Sets `push_to` on the draft.

## Database Schema (12 tables)

| Table | Scope | Purpose |
|---|---|---|
| `companies` | Global | Tenant entities |
| `users` | Global | OAuth users (multi-company) |
| `company_members` | Global | User ↔ Company (role: owner/admin/member) |
| `invoices` | Tenant | Raw invoice files + parsed metadata |
| `invoice_drafts` | Tenant | Editable staging table (the Excel view) |
| `rules` | Tenant | Routing rule conditions + actions |
| `vendor_mappings` | Tenant | Source vendor → platform vendor mapping |
| `integrations` | Tenant | Platform credentials (encrypted) |
| `platform_vendors` | Tenant | Synced vendors from billing platforms |
| `processed_emails` | Tenant | Gmail/source email tracking |
| `vendor_cache` | Tenant | Legacy vendor lookup cache |
| `audit_log` | Tenant | Full audit trail |

## Authentication

- **Web login:** Google OAuth2 → JWT in HTTP-only cookie
- **Tenant resolution:** JWT → User → CompanyMember → TenantContext
- **Multi-company:** Users can belong to multiple companies, switch via X-Company-Id header
- **Platform auth:** Per-platform (OAuth2, API key) stored encrypted per company
- **Admin:** Separate admin key for runtime config and destructive operations

## Runtime Configuration

Precedence (highest → lowest):
1. Integration config (per-platform, per-company, in DB)
2. Runtime overrides (`data/runtime_config.json`, via admin dashboard)
3. Environment variables (`.env`)
4. Code defaults (`app/config.py`)

Admin dashboard at `/admin` allows changing parser mode, LLM config, OAuth settings without restart.

## Tech Stack

| Layer    | Technology                                      |
|----------|-------------------------------------------------|
| Frontend | Next.js 14, TypeScript, Tailwind, AG Grid       |
| Backend  | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic  |
| Database | MySQL 8.0 (Docker), row-level tenant isolation   |
| Parsing  | GPT-4o Vision, Tesseract, LlamaParse             |
| Auth     | Google OAuth2 (authlib), JWT (pyjwt)             |
| Docker   | Python 3.12, Node 20, MySQL 8.0                  |
| Tests    | 33 e2e integration tests, 26 rule engine tests   |
