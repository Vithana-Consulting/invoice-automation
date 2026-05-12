# Vithana Accounting Automation — Integration Setup Guide

Complete end-to-end setup for Google OAuth (login), Gmail (email ingestion), and Zoho Books (bill push).

---

## Prerequisites

- Backend running: `cd backend && .venv/bin/uvicorn app.main:application --reload --port 8000`
- Frontend running: `cd frontend && npm run dev` (port 3001)
- MySQL running: `docker compose up -d`
- Admin API key: `v1th4n4-flush-s3cr3t-2026` (or whatever is set in `backend/.env`)

---

## Part 1 — Google OAuth (User Login)

Each company has its own Google OAuth credentials. Users log in with Google, and the system maps their email domain to the correct company.

### 1.1 Create Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth 2.0 Client ID**
3. Application type: **Web application**
4. Under **Authorised redirect URIs**, add:
   ```
   http://localhost:8000/api/auth/callback
   ```
   > For production, replace with your actual backend URL.
5. Click **Create** — note down **Client ID** and **Client Secret**

### 1.2 Configure System-Level Redirect URI

This is a one-time app-level setting (not per-company). Set it via the Admin dashboard or API:

**Via Admin UI** (`http://localhost:3001/admin` → System Config tab):

| Key | Value |
|-----|-------|
| `GOOGLE_CLIENT_ID` | *(leave blank — set per-company instead, see 1.3)* |
| `GOOGLE_CLIENT_SECRET` | *(leave blank)* |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/auth/callback` |

**Via API:**
```bash
curl -X PUT http://localhost:8000/api/settings/system-config \
  -H "Cookie: access_token=<your_jwt>" \
  -H "Content-Type: application/json" \
  -d '{"GOOGLE_REDIRECT_URI": "http://localhost:8000/api/auth/callback"}'
```

### 1.3 Set Google OAuth Credentials Per Company

Each company stores its own Client ID + Secret in the `integrations` table (platform = `google_oauth`).

**Via Admin API:**
```bash
curl -X PUT http://localhost:8000/api/admin/companies/{COMPANY_ID}/oauth \
  -H "X-Admin-Key: v1th4n4-flush-s3cr3t-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "123456789-abc.apps.googleusercontent.com",
    "client_secret": "GOCSPX-xxxxxxxxxxxxxxxxxxxx",
    "redirect_uri": "http://localhost:8000/api/auth/callback"
  }'
```

> **Get your company ID:** `GET /api/admin/companies` with `X-Admin-Key` header.

### 1.4 Create the Company (if not already)

```bash
curl -X POST http://localhost:8000/api/admin/companies \
  -H "X-Admin-Key: v1th4n4-flush-s3cr3t-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corp",
    "domain": "acmecorp.com"
  }'
```

The `domain` field maps email domains to companies at login. A user with `user@acmecorp.com` will be routed to this company automatically.

### 1.5 Login Flow (How It Works)

```
User visits /login
  → enters email
  → backend looks up company by email domain
  → redirects to Google OAuth consent screen (using that company's credentials)
  → Google redirects back to /api/auth/callback
  → backend verifies state JWT (5 min TTL, contains company_id)
  → upserts user + company_member
  → sets JWT cookie (access_token, HttpOnly)
  → frontend redirects to /invoices
```

---

## Part 2 — Gmail Integration (Email Ingestion)

Gmail credentials are stored **per-tenant** in the `integrations` table (platform = `gmail`). Nothing is stored on the filesystem.

### 2.1 Create Gmail API Credentials

1. In the same Google Cloud project, go to **APIs & Services** → **Library**
2. Search for and enable **Gmail API**
3. Go back to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
4. Application type: **Desktop app** (for `installed` flow) — or **Web application**
5. Download the JSON file — this is your `credentials.json`

> You can reuse the same Google Cloud project as login, but create a **separate** OAuth 2.0 Client ID for Gmail. The scopes differ — Gmail uses `https://mail.google.com/`.

### 2.2 Upload credentials.json

**Via Settings UI** (`http://localhost:3001/settings` → Gmail tab):

1. Click **Upload credentials.json**
2. Select the file you downloaded

**Via API:**
```bash
curl -X POST http://localhost:8000/api/settings/gmail-credentials \
  -H "Cookie: access_token=<your_jwt>" \
  -F "file=@/path/to/credentials.json"
```

The file is validated (must contain `installed` or `web` key) and stored encrypted in the DB.

### 2.3 Authorise Gmail Access

After uploading credentials, authorise the inbox:

**Via Settings UI:** Click **Authorise Gmail** — you'll be redirected to Google's consent screen.

**Via API:**
```bash
# 1. Get the authorization URL
curl http://localhost:8000/api/settings/gmail-authorize \
  -H "Cookie: access_token=<your_jwt>"
# → redirects to Google consent page

# 2. Google redirects back to:
#    http://localhost:8000/api/settings/gmail-callback?code=...
# This is handled automatically — the token is stored in the DB.
```

After authorisation, the Settings page shows **Gmail: Connected**.

### 2.4 OAuth Scopes Required

The Gmail OAuth consent screen must approve:
```
https://mail.google.com/
```

This is the full Gmail scope. The app reads emails and attachments; it never sends or deletes.

### 2.5 Configure Gmail Label (Optional)

By default the system fetches emails labelled **`Invoices`** in Gmail. To change this:

**Via Settings UI:** Settings → Gmail → Label field

**Via API:**
```bash
curl -X PUT http://localhost:8000/api/settings/system-config \
  -H "Cookie: access_token=<your_jwt>" \
  -H "Content-Type: application/json" \
  -d '{"GMAIL_LABEL": "Bills"}'
```

### 2.6 Ingest Emails

**Via UI:** Invoices page → **Ingest Emails** button

**Via API:**
```bash
curl -X POST http://localhost:8000/api/ingest/gmail \
  -H "Cookie: access_token=<your_jwt>"
```

The system fetches up to 200 messages, extracts PDF/image attachments, runs them through the LLM parser, and creates invoice records. Each message is tracked by `message_id` in `processed_emails` — re-ingesting is idempotent (already-processed messages are skipped).

### 2.7 Check Ingest Status

```bash
curl http://localhost:8000/api/ingest/status \
  -H "Cookie: access_token=<your_jwt>"
```

Returns:
```json
{
  "state": "completed",
  "started_at": "2026-05-12T10:00:00",
  "elapsed_seconds": 47,
  "emails_found": 12,
  "invoices_parsed": 10,
  "drafts_created": 8
}
```

States: `never_run` | `running` | `stalled` | `completed` | `failed`

---

## Part 3 — Zoho Books Integration (Bill Push)

### 3.1 Create a Zoho API Client

1. Go to [Zoho API Console](https://api-console.zoho.in/) (use `.in` for India)
2. Click **Add Client** → **Server-based Applications**
3. Set **Authorised Redirect URI** to:
   ```
   http://localhost:8000/api/integrations/zoho/oauth/callback
   ```
4. Note down **Client ID** and **Client Secret**

> Use `zoho.in` console for India region. Use `zoho.com` for other regions and adjust all URLs accordingly.

### 3.2 Find Your Zoho Organisation ID

1. Log in to [Zoho Books](https://books.zoho.in)
2. Go to **Settings** → **Organisation Profile**
3. The Organisation ID is shown at the bottom (e.g. `60069222256`)

Or via API (after auth):
```bash
curl "https://www.zohoapis.in/books/v3/organizations" \
  -H "Authorization: Zoho-oauthtoken <access_token>"
```

### 3.3 Find Tax IDs and Account IDs

**Tax IDs (Settings → Taxes in Zoho Books):**

| Tax | Where to find |
|-----|---------------|
| GST 18% intra-state (CGST+SGST group) | Zoho Books → Settings → Taxes → copy the Tax ID |
| IGST 18% inter-state | Same page — separate IGST tax entry |

For Entvin Labs (Karnataka, org `60069222256`):
- GST18 group: `3699544000000109129`
- CGST9: `3699544000000109057`
- SGST9: `3699544000000109058`

**Account IDs (Settings → Chart of Accounts):**

1. Go to Zoho Books → **Accountant** → **Chart of Accounts**
2. Find the account (e.g. "Bank Fees and Charges", "Professional Fees")
3. The ID is in the URL when you click into it — or use the API:
```bash
curl "https://www.zohoapis.in/books/v3/chartofaccounts?organization_id=60069222256" \
  -H "Authorization: Zoho-oauthtoken <access_token>"
```

Default fallback account: `3699544000000000507` (Bank Fees & Charges)

### 3.4 Save Zoho Integration via the UI

Go to `http://localhost:3001/integrations` → click **Zoho Books** → **Configure**:

| Field | Value | Notes |
|-------|-------|-------|
| Client ID | `1000.XXXX...` | From Zoho API Console |
| Client Secret | `xxxxxx...` | From Zoho API Console |
| Redirect URI | `http://localhost:8000/api/integrations/zoho/oauth/callback` | Must match exactly |
| Organisation ID | `60069222256` | Your Zoho org ID |
| API Base URL | `https://www.zohoapis.in/books/v3` | `.in` for India |
| Auth URL | `https://accounts.zoho.in/oauth/v2/token` | `.in` for India |
| Default Account ID | `3699544000000000507` | Fallback GL account for line items |
| GST Tax ID (intra-state) | `3699544000000109129` | CGST+SGST group |
| IGST Tax ID (inter-state) | *(from Zoho Settings → Taxes)* | For vendors in other states |
| Organisation State Code | `29` | 29=Karnataka, 33=Tamil Nadu, 27=Maharashtra, 07=Delhi |

Click **Save**.

### 3.5 Authorise Zoho (OAuth)

After saving, click **Authorise with Zoho** in the integration card. This:
1. Calls `GET /api/integrations/zoho/oauth/authorize?integration_id={id}`
2. Redirects you to Zoho's consent screen (scope: `ZohoBooks.fullaccess.all`)
3. Zoho redirects back to `http://localhost:8000/api/integrations/zoho/oauth/callback`
4. The backend exchanges the code for a **refresh token** and saves it to the integration config
5. Redirects back to `http://localhost:3001/integrations`

The integration card should now show **Health: OK**.

**Via API (manual):**
```bash
# Step 1: Get authorize URL
curl "http://localhost:8000/api/integrations/zoho/oauth/authorize?integration_id=1" \
  -H "Cookie: access_token=<your_jwt>"
# → {"data": {"authorize_url": "https://accounts.zoho.in/oauth/v2/auth?..."}}

# Step 2: Open that URL in a browser — Zoho redirects back automatically
```

### 3.6 State Code Reference

| State | Code |
|-------|------|
| Tamil Nadu | 33 |
| Karnataka | 29 |
| Maharashtra | 27 |
| Delhi | 07 |
| Telangana | 36 |
| Gujarat | 24 |
| West Bengal | 19 |
| Rajasthan | 08 |

The system auto-detects intra-state vs inter-state by comparing the **vendor's GSTIN prefix** against the **org state code**. Same state → CGST+SGST; different state → IGST.

### 3.7 How a Bill Push Works

```
Invoice grid → Push to Zoho button
  → validate (7 checks: GSTIN format, RCM, ITC cutoff, duplicate, etc.)
  → resolve vendor (create in Zoho if new)
  → map line items → Zoho payload
  → POST /bills  (Zoho Books API)
  → save bill_id to invoice_drafts.external_bill_id
  → update invoices.zoho_push_status = "PUSHED"
  → attach original PDF to the Zoho bill
  → log to audit_logs
```

### 3.8 Test the Connection

```bash
curl -X POST "http://localhost:8000/api/integrations/{integration_id}/test" \
  -H "Cookie: access_token=<your_jwt>"
```

Returns `health_status: OK` or an error message from the Zoho API.

---

## Part 4 — Company Settings (Parser Accuracy)

After all integrations are connected, configure your company profile so the AI parser correctly identifies your company as the **recipient** (not the vendor):

Go to `http://localhost:3001/settings` → **Company** tab:

| Field | Example | Purpose |
|-------|---------|---------|
| Legal Name | `GRNRM TALENT NETWORK PRIVATE LIMITED` | AI uses this to avoid misidentifying your company as the vendor on "Billed To" |
| GSTIN | `29AAGCG0740A1Z3` | Validates vendor GST match; also used as buyer identity hint |
| PAN | `AAHCE1996R` | Secondary buyer identity hint |

These values are injected into the LLM prompt as a `【BUYER IDENTITY — DO NOT USE AS VENDOR】` block on every parse.

---

## Part 5 — Runtime Config (No Restart Needed)

Go to `http://localhost:3001/settings` → **Runtime Config** tab to change:

| Key | Default | Notes |
|-----|---------|-------|
| `PARSER_MODE` | `llm` | `llm`, `tesseract`, or `llamaparse` |
| `LLM_PROVIDER` | `openai` | `openai` or `ollama` |
| `LLM_MODEL` | `gpt-4o` | Any model your provider supports |
| `LLM_API_KEY` | *(from .env)* | Override without restarting |

Changes take effect immediately — no server restart required.

---

## Troubleshooting

### Google OAuth: "redirect_uri_mismatch"
The redirect URI in your Google Cloud Console credentials must match **exactly** (including trailing slash, http vs https). Check the URI configured in Step 1.2 and 1.3.

### Zoho: "Invalid Client" on token exchange
The `redirect_uri` saved in the Zoho integration must match **exactly** what you registered in the Zoho API Console in Step 3.1. Any mismatch causes this error.

### Zoho: "Token refresh failed: HTTP 401"
The refresh token has expired or been revoked. Re-authorise by clicking **Authorise with Zoho** again (Step 3.5).

### Gmail: "Token expired" / "Invalid grant"
The Gmail OAuth token has expired. Go to Settings → Gmail → **Authorise Gmail** to re-authorise.

### Invoice parsed with wrong vendor
Your company was identified as the vendor instead of the recipient. Set **Legal Name** in Settings → Company (Part 4). Then reparse the invoice from the invoices grid.

### Alembic: "Multiple head revisions"
Run migrations one at a time, or apply directly via MySQL:
```bash
docker exec day3-db-1 mysql -uaccounting -paccounting accounting_automation \
  -e "ALTER TABLE companies ADD COLUMN IF NOT EXISTS legal_name VARCHAR(500) NULL;"
```

---

## Quick Reference: Key URLs

| Purpose | URL |
|---------|-----|
| Frontend | `http://localhost:3001` |
| Backend API | `http://localhost:8000` |
| Admin dashboard | `http://localhost:3001/admin` |
| Settings | `http://localhost:3001/settings` |
| Integrations | `http://localhost:3001/integrations` |
| Zoho Books (India) | `https://books.zoho.in` |
| Zoho API Console (India) | `https://api-console.zoho.in` |
| Google Cloud Console | `https://console.cloud.google.com` |
| Backend health check | `http://localhost:8000/health` |

## Quick Reference: Key API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/admin/companies` | List all companies |
| `POST` | `/api/admin/companies` | Create a company (admin) |
| `PUT` | `/api/admin/companies/{id}/oauth` | Set Google OAuth credentials for a company |
| `GET` | `/api/settings` | Get current user/company/Gmail config |
| `PUT` | `/api/settings/company` | Update company GST/PAN/legal name |
| `POST` | `/api/settings/gmail-credentials` | Upload credentials.json |
| `GET` | `/api/settings/gmail-authorize` | Start Gmail OAuth flow |
| `GET` | `/api/settings/system-config` | Get system config (redirect URI etc.) |
| `PUT` | `/api/settings/system-config` | Update system config |
| `GET` | `/api/integrations` | List all integrations |
| `POST` | `/api/integrations` | Create integration (save Zoho config) |
| `GET` | `/api/integrations/zoho/oauth/authorize` | Get Zoho OAuth URL |
| `GET` | `/api/integrations/zoho/oauth/callback` | Zoho OAuth callback (auto-called) |
| `POST` | `/api/integrations/{id}/test` | Test integration health |
| `POST` | `/api/ingest/gmail` | Trigger Gmail ingest |
| `GET` | `/api/ingest/status` | Check ingest status |
| `POST` | `/api/ingest/reparse/{invoice_id}` | Reparse a single invoice |
