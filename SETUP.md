# Vithana Accounting Platform — Setup Guide

## Prerequisites

- **Docker Desktop** (for MySQL)
- **Python 3.12+** (`brew install python@3.12`)
- **Node.js 18+** (for frontend)
- **poppler** (`brew install poppler` — for PDF to image conversion)
- **Google Cloud account** (for OAuth and Gmail API)
- **OpenAI API key** (for LLM invoice parsing)

---

## 1. Start MySQL

The platform uses MySQL 8.0 via Docker.

```bash
cd poc/day1/day3
docker compose up -d db
```

Wait for healthy status:
```bash
docker ps  # Should show day3-db-1 or day2-db-1 as "healthy"
```

**Connection details:**
- Host: `localhost`
- Port: `3306`
- User: `accounting`
- Password: `accounting`
- Database: `accounting_automation`

To connect directly:
```bash
docker exec -it day2-db-1 mysql -uaccounting -paccounting accounting_automation
```

---

## 2. Backend Setup

```bash
cd backend

# Create Python 3.12 virtual environment
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the server
python -m uvicorn app.main:application --host 0.0.0.0 --port 8000 --reload
```

The backend auto-creates all database tables on first startup.

**Verify:** `curl http://localhost:8000/health`

---

## 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server on port 3001
npm run dev -- -p 3001
```

**Verify:** Open `http://localhost:3001` in browser.

---

## 4. Google Cloud Setup

You need **one OAuth 2.0 Client** (Web Application type) per company/tenant.

### 4a. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (e.g., "Vithana Accounting")

### 4b. Configure OAuth Consent Screen

1. Go to **APIs & Services** → **OAuth consent screen**
2. Choose **External** user type
3. Fill in:
   - App name: your company name
   - User support email: your email
   - Developer contact email: your email
4. **Scopes** → Add:
   - `openid`
   - `email`
   - `profile`
   - `https://www.googleapis.com/auth/gmail.readonly`
5. **Test users** → Add the email addresses that will sign in
6. Save

### 4c. Enable Gmail API

1. Go to **APIs & Services** → **Library**
2. Search for **"Gmail API"**
3. Click **Enable**

### 4d. Create OAuth 2.0 Client

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth 2.0 Client ID**
3. Application type: **Web application**
4. Name: e.g., "Vithana Web"
5. **Authorised JavaScript origins:**
   ```
   http://localhost:8000
   ```
6. **Authorised redirect URIs** (add both):
   ```
   http://localhost:8000/api/auth/google/callback
   http://localhost:8000/api/settings/gmail-callback
   ```
7. Click **Create**
8. Copy the **Client ID** and **Client Secret**

---

## 5. Admin Dashboard — Create Company

1. Open `http://localhost:3001/admin`
2. Enter the admin key: (value of `ADMIN_API_KEY` in `backend/.env`)
3. **Create Company:**
   - Company name: e.g., "Acme Corp"
   - Email domain: e.g., `gmail.com` (the domain part of user emails)
4. **Configure OAuth** for the company:
   - Click **"Configure OAuth"** on the company row
   - Enter the **Client ID** from step 4d
   - Enter the **Client Secret** from step 4d
   - Redirect URI: `http://localhost:8000/api/auth/google/callback`
   - Click **Save OAuth Config**

---

## 6. Sign In

1. Go to `http://localhost:3001/login`
2. Enter your email (must match the domain configured in step 5)
3. Click **Continue with Google**
4. Authenticate with Google
5. You'll be redirected to the dashboard

---

## 7. Configure Company Settings

After signing in:

1. Go to **Settings** → **Company** tab
2. Enter your company's **GSTIN** and/or **PAN**
3. Click **Save Company Details**

This is recommended before processing invoices — parsed invoices will be validated against these values.

---

## 8. Gmail Integration (Pull Invoices from Email)

1. Go to **Settings** → **Gmail API** tab
2. Click **Upload credentials.json**
   - This is the same OAuth client from step 4d
   - Download the JSON from Google Cloud Console → Credentials → your OAuth client → **Download JSON**
3. Click **Authorize Gmail Access**
4. Authenticate with Google and grant Gmail read access
5. Once connected, go to **Invoices** page
6. Click **Ingest from Gmail** to pull invoices

---

## 9. Configure Billing Platform (Zoho/QuickBooks/Tally)

1. Go to **Integrations** page
2. Click **Configure** on the platform you want
3. Enter the platform credentials:

### Zoho Books
- Client ID, Client Secret (from [Zoho API Console](https://api-console.zoho.in))
- Refresh Token (generated via OAuth grant code exchange)
- Organization ID
- Base URL: `https://www.zohoapis.in/books/v3` (India) or `https://www.zohoapis.com/books/v3` (US)
- Auth URL: `https://accounts.zoho.in/oauth/v2/token` (India) or `https://accounts.zoho.com/oauth/v2/token` (US)

### Generating Zoho Refresh Token
```bash
# 1. Generate a grant code in Zoho API Console (Self Client, scope: ZohoBooks.fullaccess.all)
# 2. Exchange for refresh token:
curl -X POST "https://accounts.zoho.in/oauth/v2/token" \
  -d "grant_type=authorization_code&code=YOUR_GRANT_CODE&client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET&redirect_uri=https://www.zoho.in"
# 3. Copy the refresh_token from the response
```

4. Click **Save & Enable**
5. Click **Test Connection** to verify

---

## 10. OpenAI Setup (Invoice Parsing)

The platform uses GPT-4o vision to parse invoices. Configure in `backend/.env`:

```env
PARSER_MODE=llm
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-your-openai-api-key
```

Or change at runtime via **Settings** → **System Config** tab (no restart needed).

### Alternative Providers

| Provider | Config |
|---|---|
| OpenAI | `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o` |
| Google Gemini | `LLM_PROVIDER=google`, `LLM_MODEL=gemini-2.0-flash` (free tier) |
| Anthropic | `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-4-20250514` |
| Local (Ollama) | `LLM_PROVIDER=ollama`, `LLM_MODEL=llama3`, `LLM_BASE_URL=http://localhost:11434/v1` |

---

## 11. Vendor Mapping (Required Before Pushing)

Invoices cannot be pushed to billing platforms without vendor mappings.

1. Go to **Vendor Mappings** → **Source Vendors** tab to see vendor names from parsed invoices
2. Go to **Platform Vendors** tab → select platform → click **Sync Now** to pull vendors from Zoho/QB
3. Click **Map** on an unmapped platform vendor → select the matching invoice vendor
4. Or use **Create on Platform** from Source Vendors tab to create a new vendor on the platform

---

## 12. Invoice Workflow

```
Ingest → Parse → Review → Approve → Push
```

1. **Ingest**: Click "Ingest from Gmail" on Invoices page
2. **Parse**: Automatic (GPT-4o extracts vendor, amount, invoice number)
3. **Review**: Check data in AG Grid, edit if needed
4. **Approve**: Click Approve (checks vendor mapping → PENDING_VENDOR if unmapped)
5. **Push**: Click Push to send bill to Zoho/QB/Tally

---

## Environment Variables (.env)

Located at `backend/.env`. Key settings:

```env
# Database
DATABASE_URL=mysql+pymysql://accounting:accounting@localhost:3306/accounting_automation

# Parser
PARSER_MODE=llm                    # llm | tesseract | llamaparse
LLM_PROVIDER=openai                # openai | anthropic | google | ollama
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-...

# Auth
JWT_SECRET_KEY=your-secret-key     # Change in production
ADMIN_API_KEY=your-admin-key       # For admin dashboard

# Frontend
FRONTEND_URL=http://localhost:3001

# Gmail (legacy fallback — prefer per-tenant config in DB)
GMAIL_LABEL=invoices
```

**Note:** Google OAuth credentials (client_id, secret) are NOT in .env — they're stored per-company in the database via the admin dashboard.

---

## Quick Reference

| Service | URL |
|---|---|
| Frontend | http://localhost:3001 |
| Backend | http://localhost:8000 |
| Admin Dashboard | http://localhost:3001/admin |
| API Docs (Swagger) | http://localhost:8000/docs |
| Health Check | http://localhost:8000/health |
| MySQL | localhost:3306 (Docker) |

| Command | Purpose |
|---|---|
| `docker compose up -d db` | Start MySQL |
| `source .venv/bin/activate && python -m uvicorn app.main:application --host 0.0.0.0 --port 8000 --reload` | Start backend |
| `npm run dev -- -p 3001` | Start frontend |
| `python tests/test_e2e.py` | Run integration tests |
| `alembic upgrade head` | Apply DB migrations |
| `alembic revision --autogenerate -m "msg"` | Generate migration |

---

## Troubleshooting

### "Access blocked: Authorization Error" on Google sign-in
- OAuth client may be deleted or disabled → check Google Cloud Console → Credentials
- Redirect URI mismatch → ensure `http://localhost:8000/api/auth/google/callback` is listed
- Test user not added → OAuth consent screen → Test users → add your email

### "No company configured for domain" on login
- Create the company in admin dashboard with the correct email domain

### "Company GST or PAN not configured" warning
- Go to Settings → Company → enter GSTIN or PAN

### "Token refresh failed: HTTP 400" on Zoho
- Refresh token expired → generate a new one via Zoho API Console
- Rate limited → wait 2-5 minutes and retry

### MySQL connection refused
- Start Docker: `docker start day2-db-1`
- Check port: `lsof -i :3306`

### Backend 500 errors
- Check logs: look at the terminal where uvicorn is running
- Or check: `tail -50 /path/to/background/task/output`
