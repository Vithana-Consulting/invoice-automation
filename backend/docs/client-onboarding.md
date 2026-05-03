# Vithana — Client Onboarding Guide
**For: Vithana Internal Auditing Team**
**Platforms covered: Zoho Books · QuickBooks**

---

## Overview

This guide walks through every step required to onboard a new client onto the Vithana accounting automation platform. Complete all steps in order. A client is considered ready when:

- Their company is created in the system
- GST / PAN is configured
- Gmail is connected and fetching invoices
- At least one billing platform (Zoho or QuickBooks) is connected and a test push succeeds

**Estimated time per client: 30–45 minutes**

---

## Step 1 — Create the Company

> Done by: Vithana Admin
> Where: Admin panel → Companies

1. Log in to the Vithana platform as a Vithana admin.
2. Go to **Admin → Companies → New Company**.
3. Fill in:
   | Field | Notes |
   |-------|-------|
   | Company Name | Client's legal entity name (e.g. `Acme Pvt Ltd`) |
   | Domain | Client's email domain (e.g. `acme.com`) — used for login matching |

4. Click **Create**. The system generates a unique slug (e.g. `acme-pvt-ltd`).
5. Note down the **Company ID** shown after creation — you'll need it later.

---

## Step 2 — Configure Company Identity (GST / PAN)

> Done by: Vithana Admin or client's owner account
> Where: Settings → Company

This is mandatory. The system will refuse to parse any invoice until at least one of these is set. It uses these to identify inbound vs. outbound invoices and validate buyer GSTIN on parsed documents.

1. Go to **Settings → Company**.
2. Fill in:
   | Field | Required | Notes |
   |-------|----------|-------|
   | GST Number | Yes (if GST registered) | 15-character GSTIN, e.g. `29AABCU9603R1ZX` |
   | PAN Number | Yes (if not GST registered) | 10-character PAN |
   | Company State | Recommended | Used for IGST vs CGST+SGST routing cross-check |

3. Save. The system will now allow invoice parsing.

> **Tip:** If the client is GST-registered, always enter the GSTIN. PAN alone is a fallback for unregistered entities.

---

## Step 3 — Invite Client Users

> Done by: Vithana Admin
> Where: Admin panel → Companies → Members

1. Go to **Admin → Companies → [Client Name] → Members**.
2. Click **Invite User**.
3. Enter the client's email address and assign a role:
   | Role | Can do |
   |------|--------|
   | `owner` | Everything — approve, push, override compliance blocks, manage integrations |
   | `admin` | Same as owner except cannot delete the company |
   | `member` | View and approve drafts only — cannot push or override compliance blocks |

4. The user logs in via **Google OAuth** using their work email.

> **Note:** The login redirect is configured at `{PRODUCTION-URL}/api/auth/google/callback`. Ensure this is set as an Authorized Redirect URI in the Google Cloud Console OAuth app (see Step 4).

---

## Step 4 — Connect Gmail (Invoice Source)

> Done by: Client's owner/admin
> Where: Settings → Integrations → Gmail

The platform pulls invoice attachments directly from the client's Gmail inbox via a label filter.

### 4a — Pre-requisite: Google Cloud Console Setup

This is a one-time setup per Google Workspace / Gmail account. The client (or their IT admin) must do this.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services → Credentials**.
2. Create an **OAuth 2.0 Client ID** (type: **Web application**).
3. Under **Authorized Redirect URIs**, add:
   ```
   {PRODUCTION-URL}/api/auth/google/callback
   ```
4. Download the credentials JSON file (`credentials.json`).
5. Enable the **Gmail API** under **APIs & Services → Library**.

### 4b — Upload Credentials in Vithana

1. Go to **Settings → Integrations → Gmail → Configure**.
2. Upload the `credentials.json` file downloaded above.
3. Set the **Gmail Label** to watch. Default is `invoices`.
   - The client must create this label in their Gmail and apply it to emails containing invoice attachments.
   - Label name is case-insensitive.
4. Click **Authorize Gmail** — this opens a Google OAuth consent screen.
5. The client logs in with the Gmail account whose inbox should be monitored.
6. After authorization, a token is stored. The connection status should show **Connected**.

### 4c — Verify Gmail Connection

1. Click **Test Connection** on the Gmail integration card.
2. Confirm it shows: `healthy: true`, `label_exists: true`.
3. If label is not found, ask the client to create it in Gmail and re-test.

---

## Step 5 — Connect Zoho Books

> Done by: Vithana Admin (with client's Zoho credentials)
> Where: Settings → Integrations → Zoho Books

### 5a — Pre-requisite: Create a Zoho API Application

The client (or Vithana on their behalf) must create an app in the Zoho API Console.

1. Go to [Zoho API Console](https://api-console.zoho.in/) → **Add Client → Server-based Applications**.
2. Fill in:
   | Field | Value |
   |-------|-------|
   | Client Name | `Vithana Accounting` (or any name) |
   | Homepage URL | `{PRODUCTION-URL}` |
   | Authorized Redirect URI | `{PRODUCTION-URL}/api/integrations/zoho/oauth/callback` |
3. Click **Create**. Note down the **Client ID** and **Client Secret**.

### 5b — Generate a Refresh Token

Zoho uses OAuth 2.0. You need a long-lived refresh token.

1. Construct the authorization URL:
   ```
   https://accounts.zoho.in/oauth/v2/auth
     ?response_type=code
     &client_id={CLIENT_ID}
     &scope=ZohoBooks.bills.CREATE,ZohoBooks.bills.READ,ZohoBooks.contacts.READ,ZohoBooks.contacts.CREATE,ZohoBooks.settings.READ
     &redirect_uri={PRODUCTION-URL}/api/integrations/zoho/oauth/callback
     &access_type=offline
   ```
2. Open the URL in a browser. Log in with the client's Zoho account.
3. After approval, Zoho redirects to `{PRODUCTION-URL}/api/integrations/zoho/oauth/callback?code=XXXX`.
4. Exchange the code for a refresh token:
   ```bash
   curl -X POST https://accounts.zoho.in/oauth/v2/token \
     -d "code=XXXX" \
     -d "client_id={CLIENT_ID}" \
     -d "client_secret={CLIENT_SECRET}" \
     -d "redirect_uri={PRODUCTION-URL}/api/integrations/zoho/oauth/callback" \
     -d "grant_type=authorization_code"
   ```
5. Copy the `refresh_token` from the response. This does not expire unless revoked.

### 5c — Find Zoho Organization ID

1. Log in to [Zoho Books](https://books.zoho.in/).
2. Go to **Settings → Organisation Profile**.
3. The **Organization ID** is shown at the top of the page (numeric, e.g. `3699544000000000001`).

### 5d — Find GST Tax IDs in Zoho

Zoho Books manages taxes internally. You need to find the Tax IDs for the taxes already configured in the client's Zoho org.

1. In Zoho Books, go to **Settings → Taxes**.
2. Find the tax entry for **GST 18% (Intra-state)** — this applies CGST 9% + SGST 9%.
   - Click on it and copy the Tax ID from the URL:
     `https://books.zoho.in/app/3699544000000000001#/settings/taxes/{TAX_ID}/edit`
3. Find the tax entry for **IGST 18% (Inter-state)**.
   - Copy its Tax ID the same way.

> If the client has multiple GST rates (5%, 12%, 28%), note which one applies to the majority of their invoices. The Tax IDs configured here are used as defaults. Per-line HSN-based overrides can be configured later via Chart of Accounts.

### 5e — Find Default Account ID

1. In Zoho Books, go to **Chart of Accounts**.
2. Find the account where purchase invoices should be booked by default (e.g. `Professional Charges`, `Cost of Goods Sold`).
3. Click the account → copy the Account ID from the URL:
   `https://books.zoho.in/app/...#/chartofaccounts/{ACCOUNT_ID}/edit`

### 5f — Configure in Vithana

1. Go to **Settings → Integrations → Zoho Books → Configure**.
2. Fill in all fields:

   | Field | Value | Notes |
   |-------|-------|-------|
   | Client ID | From Step 5a | |
   | Client Secret | From Step 5a | |
   | Redirect URI | `{PRODUCTION-URL}/api/integrations/zoho/oauth/callback` | Must match exactly |
   | Refresh Token | From Step 5b | |
   | Organization ID | From Step 5c | |
   | API Base URL | `https://www.zohoapis.in/books/v3` | India region — do not change |
   | Auth URL | `https://accounts.zoho.in/oauth/v2/token` | India region — do not change |
   | Default Account ID | From Step 5e | |
   | GST Tax ID — Intra-state (CGST+SGST) | From Step 5d | For vendors in same state as client |
   | IGST Tax ID — Inter-state | From Step 5d | For vendors in different state |
   | Organisation State Code | 2-digit GST state code | **Critical — see table below** |

3. Click **Save**, then **Test Connection**.

### 5g — Organisation State Code Reference

This determines whether bills are routed as IGST (inter-state) or CGST+SGST (intra-state). Set it to the state where the client's GST registration is.

| State | Code | State | Code |
|-------|------|-------|------|
| Andhra Pradesh | 37 | Maharashtra | 27 |
| Delhi | 07 | Rajasthan | 08 |
| Gujarat | 24 | Tamil Nadu | 33 |
| Haryana | 06 | Telangana | 36 |
| Karnataka | 29 | Uttar Pradesh | 09 |
| Kerala | 32 | West Bengal | 19 |
| Madhya Pradesh | 23 | — | — |

> **How to find it:** First 2 digits of the client's GSTIN are their state code. E.g. GSTIN `29AABCU9603R1ZX` → state code `29` → Karnataka.

### 5h — Sync Chart of Accounts (Optional but Recommended)

1. Go to **Chart of Accounts → Sync from Zoho**.
2. This pulls all accounts from the client's Zoho org into Vithana.
3. Tag key accounts with **HSN/SAC codes** so line items auto-map to the right GL account per invoice.

---

## Step 6 — Connect QuickBooks

> Done by: Vithana Admin (with client's QuickBooks credentials)
> Where: Settings → Integrations → QuickBooks

### 6a — Pre-requisite: Create an Intuit Developer App

1. Go to [Intuit Developer Portal](https://developer.intuit.com/) → **My Apps → Create an App**.
2. Select **QuickBooks Online and Payments**.
3. Fill in the app name (e.g. `Vithana Accounting`).
4. Under **Redirect URIs**, add:
   ```
   {PRODUCTION-URL}/api/integrations/quickbooks/oauth/callback
   ```
5. Note down the **Client ID** and **Client Secret** from the **Keys & OAuth** tab.

> **Environment:** Use **Production** keys for live client data. Sandbox is only for testing.

### 6b — Generate a Refresh Token

1. Go to the **QuickBooks OAuth Playground** in the Intuit Developer portal, or construct the authorization URL manually:
   ```
   https://appcenter.intuit.com/connect/oauth2
     ?client_id={CLIENT_ID}
     &response_type=code
     &scope=com.intuit.quickbooks.accounting
     &redirect_uri={PRODUCTION-URL}/api/integrations/quickbooks/oauth/callback
     &state=vithana_onboarding
   ```
2. Open the URL in a browser. Log in with the client's QuickBooks account.
3. After approval, you are redirected to:
   ```
   {PRODUCTION-URL}/api/integrations/quickbooks/oauth/callback?code=XXXX&realmId=YYYY
   ```
4. Note the `realmId` from the URL — this is the **Company ID / Realm ID**.
5. Exchange the code for tokens:
   ```bash
   curl -X POST https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer \
     -H "Authorization: Basic $(echo -n '{CLIENT_ID}:{CLIENT_SECRET}' | base64)" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=authorization_code" \
     -d "code=XXXX" \
     -d "redirect_uri={PRODUCTION-URL}/api/integrations/quickbooks/oauth/callback"
   ```
6. Copy the `refresh_token` from the response.

> QuickBooks refresh tokens expire after **100 days of inactivity**. The system auto-refreshes on each use, so as long as the client has regular invoice activity, it stays alive.

### 6c — Configure in Vithana

1. Go to **Settings → Integrations → QuickBooks → Configure**.
2. Fill in:

   | Field | Value | Notes |
   |-------|-------|-------|
   | Client ID | From Step 6a | |
   | Client Secret | From Step 6a | |
   | Refresh Token | From Step 6b | |
   | Realm ID (Company ID) | From Step 6b URL (`realmId=...`) | |
   | API Base URL | `https://quickbooks.api.intuit.com` | Production — change to `https://sandbox-quickbooks.api.intuit.com` for testing only |

3. Click **Save**, then **Test Connection**.

### 6d — Sync Chart of Accounts

1. Go to **Chart of Accounts → Sync from QuickBooks**.
2. Tag accounts with HSN/SAC codes as needed.

---

## Step 7 — Configure Routing Rules

> Done by: Vithana Admin
> Where: Rules

Rules tell the system which invoices go to which platform automatically.

1. Go to **Rules → New Rule**.
2. Example rules to set up:

   | Rule Name | Condition | Action |
   |-----------|-----------|--------|
   | All to Zoho | `source = gmail` | Push to `zoho` |
   | Large invoices to QB | `total_amount > 100000` | Push to `quickbooks` |
   | Specific vendor | `vendor_name = Acme Services` | Push to `zoho` |

3. Rules are evaluated in priority order (top = highest priority). Drag to reorder.
4. If no rule matches an invoice, the draft stays in **Pending Review** with no platform assigned — the reviewer sets it manually.

---

## Step 8 — Set Up Vendor Mappings

> Done by: Vithana Admin or client
> Where: Vendor Mappings

Vendor mappings translate the vendor name as it appears on the invoice to the exact name as it exists in Zoho / QuickBooks. Without a mapping, the push will be blocked.

1. Go to **Vendor Mappings → Add Mapping**.
2. For each frequent vendor:
   | Field | Example |
   |-------|---------|
   | Invoice Vendor Name | `Kodo Technologies Pvt Ltd` (as it appears on PDF) |
   | Platform | `zoho` |
   | Canonical Name | `Kodo Pay` (exact name in Zoho contacts) |
   | Platform Vendor ID | (optional — fill if known from Zoho contact list) |

3. Mappings are case-insensitive on lookup but stored as-entered.

> **Tip:** After the first ingest, the dashboard will show all drafts in **Pending Vendor** status for unmapped vendors. Use that list to bulk-add mappings.

---

## Step 9 — Run First Ingest and Verify

1. Go to **Invoice Drafts → Ingest from Gmail**.
2. Wait for the ingest to complete. The banner shows: `Ingested X emails, parsed Y, created Z drafts`.
3. Review the drafts:
   - **Pending Review** → approve each draft
   - **Pending Vendor** → go to Vendor Mappings and add the missing mapping, then click Resolve Vendors
   - **Validation blocks** → hover the Blocks column to see what's failing and why
4. Once a draft is **Approved** with a platform set, click **Push**.
5. Confirm the bill appears in Zoho Books / QuickBooks.

---

## Onboarding Checklist

Use this as a sign-off checklist before handing over to the client.

```
[ ] Company created in Admin panel
[ ] GST number configured in Settings → Company
[ ] At least one owner user invited and logged in
[ ] Gmail: credentials uploaded, label created, connection tested
[ ] Gmail: test ingest ran, at least one invoice parsed successfully

[ ] Zoho Books (if applicable):
    [ ] Zoho API app created with correct redirect URI
    [ ] Refresh token generated and saved
    [ ] Organization ID entered
    [ ] Intra-state Tax ID (CGST+SGST) entered
    [ ] IGST Tax ID entered
    [ ] Default Account ID entered
    [ ] Organisation State Code entered and verified
    [ ] Test connection passed
    [ ] Chart of Accounts synced

[ ] QuickBooks (if applicable):
    [ ] Intuit Developer app created with correct redirect URI
    [ ] Refresh token generated and saved
    [ ] Realm ID entered
    [ ] API Base URL set to production (not sandbox)
    [ ] Test connection passed
    [ ] Chart of Accounts synced

[ ] Routing rules configured
[ ] Vendor mappings added for top 5 frequent vendors
[ ] First ingest completed, at least one bill pushed successfully to platform
[ ] Client owner verified they can see the bill in Zoho / QuickBooks
```

---

## Common Issues & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `Preflight failed: company GST or PAN not configured` | Step 2 skipped | Go to Settings → Company and enter GSTIN |
| `No vendor mapping for '...' on zoho` | Vendor not in mappings | Add mapping in Vendor Mappings |
| `GST_ROUTING_UNCONFIGURED` | Organisation State Code missing | Add state code in Zoho integration config |
| `IGST cannot be applied — intrastate transaction` | State code set to wrong state | Fix Organisation State Code to match client GSTIN |
| `Gmail credentials not configured` | credentials.json not uploaded | Upload in Integrations → Gmail |
| `Zoho API error 401` | Refresh token expired or revoked | Re-generate refresh token (Step 5b) |
| `RECONCILIATION_FAILED` | Line items don't sum to invoice subtotal | Use Reparse to re-extract; if persists, use Override with manual verification |
| `ITC_TIME_LIMIT_EXCEEDED` | Invoice older than 30 Nov of following FY | Cannot claim ITC — book to expense account |
| QuickBooks `refresh_token expired` | No activity for 100+ days | Re-authorize QuickBooks (Step 6b) |

---

## Reference: Redirect URIs Summary

Configure all of these in the respective developer consoles before starting.

| Service | Redirect URI |
|---------|-------------|
| Google OAuth (login) | `{PRODUCTION-URL}/api/auth/google/callback` |
| Gmail (invoice source) | `{PRODUCTION-URL}/api/auth/google/callback` |
| Zoho Books | `{PRODUCTION-URL}/api/integrations/zoho/oauth/callback` |
| QuickBooks | `{PRODUCTION-URL}/api/integrations/quickbooks/oauth/callback` |

---

*Document maintained by Vithana Engineering. Last updated: 2026-05-03.*
