# Vithana Accounting Platform - Setup Guide v2

## Table of Contents
1. [Gmail (Invoice Source)](#1-gmail-invoice-source)
2. [Zoho Books (Billing Platform)](#2-zoho-books-billing-platform)
3. [QuickBooks Online (Billing Platform)](#3-quickbooks-online-billing-platform)
4. [Chart of Accounts Sync](#4-chart-of-accounts-sync)
5. [End-to-End Flow](#5-end-to-end-flow)

---

## 1. Gmail (Invoice Source)

Gmail is used to pull invoice attachments (PDF, images) from a specific label.

### What You Need
- A Google Cloud Project with Gmail API enabled
- OAuth 2.0 credentials (Web Application type)

### Step-by-Step Setup

#### A. Google Cloud Console Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable the **Gmail API**:
   - APIs & Services > Library > search "Gmail API" > Enable
4. Create OAuth 2.0 Credentials:
   - APIs & Services > Credentials > Create Credentials > OAuth 2.0 Client ID
   - Application type: **Web Application**
   - Name: "Vithana"
   - Authorized redirect URIs: `http://localhost:8000/api/settings/gmail-callback`
   - Click Create
5. Download the `credentials.json` file (click the download icon next to the client ID)

#### B. Configure in Vithana

1. Go to **Settings > Gmail API** tab
2. Upload the `credentials.json` file you downloaded
3. Click **Authorize Gmail** — you'll be redirected to Google
4. Sign in with the Gmail account that receives invoices
5. Grant permissions — you'll be redirected back to Vithana
6. Status should show "Connected"

#### C. Set Gmail Label (Optional)

By default, Vithana watches the `invoices` label. To change:
- Go to **Settings > Gmail API** tab
- Update the label name

#### D. Test It

1. Go to **Invoices** page
2. Click **Ingest from Gmail**
3. Invoices from the configured label will be pulled and parsed

### Credentials Reference

| Field | Where to Get | Stored |
|-------|-------------|--------|
| `credentials.json` | Google Cloud Console > Credentials > Download JSON | Per-tenant in DB |
| `token_json` | Auto-generated after OAuth consent | Per-tenant in DB |
| Gmail Label | Your choice (create in Gmail) | Per-tenant in DB |

---

## 2. Zoho Books (Billing Platform)

Zoho Books is used to push parsed invoices as Bills.

### What You Need
- A Zoho Books account
- Zoho API Console access (Self Client)

### Step-by-Step Setup

#### A. Get Zoho API Credentials

1. Go to [Zoho API Console](https://api-console.zoho.in/)
2. Click **Add Client** > **Self Client** (or select existing Self Client)
3. Note your **Client ID** and **Client Secret** from the Client Secret tab

#### B. Generate Refresh Token

1. In the Self Client, go to **Generate Code** tab
2. Fill in:
   - **Scope:** `ZohoBooks.fullaccess.all`
   - **Time Duration:** 10 minutes
   - **Scope Description:** "Vithana accounting automation"
3. Click **Create** — copy the generated code immediately
4. Exchange the code for a refresh token using this curl command:

```bash
curl -X POST "https://accounts.zoho.in/oauth/v2/token" \
  -d "grant_type=authorization_code" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "code=THE_CODE_YOU_COPIED"
```

5. The response will contain your **refresh_token** — save it securely

> **Note:** The authorization code expires in 10 minutes and can only be used once.
> If it expires, generate a new code from the Self Client.

#### C. Get Organization ID

1. Log in to [Zoho Books](https://books.zoho.in/)
2. Go to **Settings** (gear icon) > **Organization Profile**
3. The **Organization ID** is displayed on that page
4. Or look at the URL: `https://books.zoho.in/app/XXXXXXXX/...` — the number is your Org ID

#### D. Configure in Vithana

1. Go to **Integrations** page
2. Click **Configure** on Zoho Books
3. Fill in:
   - **Client ID:** from Step A
   - **Client Secret:** from Step A
   - **Refresh Token:** from Step B
   - **Organization ID:** from Step C
   - **API Base URL:** `https://www.zohoapis.in/books/v3` (India)
     - For US: `https://www.zohoapis.com/books/v3`
     - For EU: `https://www.zohoapis.eu/books/v3`
   - **Auth URL:** `https://accounts.zoho.in/oauth/v2/token` (India)
     - For US: `https://accounts.zoho.com/oauth/v2/token`
     - For EU: `https://accounts.zoho.eu/oauth/v2/token`
   - **Default Account ID:** leave empty (we use Chart of Accounts sync instead)
4. Click **Save** and then **Test Connection**
5. Should show "Connected to Zoho Books"

#### E. Sync Chart of Accounts

1. Go to **Chart of Accounts** page
2. The Zoho Books card will appear (since it's now configured)
3. Click **Sync Accounts** — all Zoho COA entries will be pulled
4. Click **Auto-Tag** — system will auto-detect PURCHASE/SALE/TAX accounts
5. Review and adjust tags if needed (click "Tag" on any account)

#### F. Set Up Vendor Mappings

1. Go to **Vendor Mappings** page
2. Map invoice vendor names to Zoho contact names
3. Example: Invoice says "Slack Technologies Limited" → Zoho has "Slack Technologies Ltd"

#### G. Push an Invoice

1. Go to **Invoices** page
2. Select a draft > set **Push To** = "zoho"
3. Click **Approve** > then **Push**
4. The bill will appear in Zoho Books under the correct vendor and account

### Credentials Reference

| Field | Where to Get | Notes |
|-------|-------------|-------|
| Client ID | Zoho API Console > Self Client | Starts with `1000.` |
| Client Secret | Zoho API Console > Self Client | 40-char hex string |
| Refresh Token | Generated via code exchange (Step B) | Starts with `1000.` |
| Organization ID | Zoho Books > Settings > Organization Profile | Numeric string |
| API Base URL | Based on your Zoho region | Default: India |
| Auth URL | Based on your Zoho region | Default: India |

### Zoho Regional URLs

| Region | API Base URL | Auth URL |
|--------|-------------|----------|
| India | `https://www.zohoapis.in/books/v3` | `https://accounts.zoho.in/oauth/v2/token` |
| US | `https://www.zohoapis.com/books/v3` | `https://accounts.zoho.com/oauth/v2/token` |
| EU | `https://www.zohoapis.eu/books/v3` | `https://accounts.zoho.eu/oauth/v2/token` |
| AU | `https://www.zohoapis.com.au/books/v3` | `https://accounts.zoho.com.au/oauth/v2/token` |

---

## 3. QuickBooks Online (Billing Platform)

QuickBooks Online is used to push parsed invoices as Bills.

### What You Need
- A QuickBooks Online account
- An Intuit Developer account

### Step-by-Step Setup

#### A. Create an Intuit Developer App

1. Go to [Intuit Developer Portal](https://developer.intuit.com/)
2. Sign in (or create an account)
3. Go to **My Apps** > **Create an App**
4. Select **QuickBooks Online and Payments**
5. Name it "Vithana" and create
6. Go to the app's **Keys & OAuth** section
7. Note your **Client ID** and **Client Secret**
8. Under **Redirect URIs**, add: `http://localhost:8000/api/auth/quickbooks/callback`

#### B. Get Refresh Token via OAuth Playground

1. In the Intuit Developer Portal, go to your app
2. Click **OAuth 2.0 Playground** (or use the sandbox tools)
3. Select scopes: `com.intuit.quickbooks.accounting`
4. Click **Authorize** — sign in with your QuickBooks account
5. After authorization, you'll receive:
   - **Access Token** (expires in 1 hour)
   - **Refresh Token** (expires in 100 days — save this!)
   - **Realm ID** (your Company ID)

> **Alternative:** Use the [QuickBooks OAuth 2.0 Playground](https://developer.intuit.com/app/developer/playground)
> to generate tokens interactively.

#### C. Get Realm ID (Company ID)

The Realm ID is shown:
- In the OAuth Playground after authorization
- In your QuickBooks URL: `https://app.qbo.intuit.com/app/XXXXXXXX/...`
- Via API: `GET /v3/company/{realmId}/companyinfo/{realmId}`

#### D. Configure in Vithana

1. Go to **Integrations** page
2. Click **Configure** on QuickBooks Online
3. Fill in:
   - **Client ID:** from Step A
   - **Client Secret:** from Step A
   - **Refresh Token:** from Step B
   - **Realm ID (Company ID):** from Step C
4. Click **Save** and then **Test Connection**
5. Should show "Connected to QuickBooks (Your Company Name)"

#### E. Sync Chart of Accounts

1. Go to **Chart of Accounts** page
2. The QuickBooks card will appear
3. Click **Sync Accounts** — all QB COA entries will be pulled
4. Click **Auto-Tag** to auto-detect account categories
5. Review and adjust tags

#### F. Set Up Vendor Mappings

1. Go to **Vendor Mappings** page
2. Map invoice vendor names to QuickBooks vendor names
3. Set platform = "quickbooks"

#### G. Push an Invoice

1. Go to **Invoices** page
2. Select a draft > set **Push To** = "quickbooks"
3. Click **Approve** > then **Push**
4. The bill will appear in QuickBooks under Bills

### Credentials Reference

| Field | Where to Get | Notes |
|-------|-------------|-------|
| Client ID | Intuit Developer Portal > App > Keys & OAuth | |
| Client Secret | Intuit Developer Portal > App > Keys & OAuth | |
| Refresh Token | OAuth 2.0 Playground or OAuth flow | Expires in 100 days — refresh periodically |
| Realm ID | OAuth Playground / QB URL / Company Settings | Numeric string |

### Important Notes

- **Refresh Token Expiry:** QuickBooks refresh tokens expire after **100 days**. The system auto-refreshes the access token, but the refresh token itself needs to be regenerated every ~3 months.
- **Sandbox vs Production:** Use sandbox credentials for testing. Switch to production keys when going live.
- **Rate Limits:** QuickBooks allows 500 requests per minute per realm.

---

## 4. Chart of Accounts Sync

After connecting a billing platform, sync its Chart of Accounts so Vithana knows which accounts to use when pushing invoices.

### How It Works

1. **Sync** — Pulls all accounts from the platform's API
2. **Auto-Tag** — AI detects which accounts are for purchases, sales, CGST, SGST, IGST
3. **Manual Tag** — You can override any tag, add HSN codes, set defaults
4. **Push** — When an invoice is pushed, the system uses the tagged accounts

### Account Categories (Tags)

| Tag | Meaning | Example Account |
|-----|---------|----------------|
| `PURCHASE` | Expense accounts for inbound invoices | Cost of Goods Sold, Office Supplies |
| `SALE` | Income accounts for outbound invoices | Sales, General Income |
| `TAX_CGST` | CGST ledger (if platform supports tax line items) | CGST Input Credit |
| `TAX_SGST` | SGST ledger | SGST Input Credit |
| `TAX_IGST` | IGST ledger | IGST Input Credit |
| `TAX_CESS` | Cess ledger | Cess Input Credit |

### Default Account

Mark one account per category as **Default**. When an invoice doesn't match any HSN code, the default account for that category is used.

### HSN Code Mapping

You can map HSN/SAC codes to specific accounts:
- Example: HSN 8471 (computers) → "IT and Internet Expenses"
- Example: SAC 997331 (IT services) → "Consultant Expense"

When an invoice has a line item with that HSN code, it will be auto-assigned to that account instead of the default.

---

## 5. End-to-End Flow

```
1. CONFIGURE (one-time)
   ├── Connect Gmail in Settings
   ├── Connect Zoho/QuickBooks in Integrations
   ├── Sync Chart of Accounts
   ├── Tag accounts (PURCHASE, TAX_CGST, etc.)
   └── Set up Vendor Mappings

2. INGEST (daily)
   ├── Click "Ingest from Gmail" on Invoices page
   ├── System pulls emails with invoice attachments
   ├── GPT-4o parses: vendor, amount, tax breakup, bank details, HSN codes
   ├── Auto-detects: INBOUND vs OUTBOUND
   └── Auto-assigns GL account based on HSN or default

3. REVIEW (daily)
   ├── Review parsed invoices on Invoices page
   ├── Check warnings (GST mismatch, missing data)
   ├── Edit if needed (vendor name, amount, push_to platform)
   └── Click Approve

4. PUSH (daily)
   ├── Click Push on approved invoices
   ├── System resolves: vendor mapping → platform vendor ID
   ├── System resolves: GL account → platform account ID
   ├── Creates bill on Zoho/QuickBooks with correct accounts
   └── Bill ID stored, status = PUSHED

5. VERIFY
   ├── Check bill appeared in Zoho/QuickBooks
   ├── Verify correct account (Cost of Goods Sold, etc.)
   ├── Check Bank Details page for payment info
   └── Export to Excel if needed
```

---

## Troubleshooting

### Zoho: "invalid_code" or "Token refresh failed"
- The refresh token has expired. Regenerate using Self Client (see Section 2, Step B).

### Zoho: "The account field is required"
- Chart of Accounts not synced, or no default PURCHASE account set.
- Go to Chart of Accounts > Sync from Zoho > Auto-Tag > ensure one PURCHASE account is marked Default.

### QuickBooks: "Token expired"
- QB refresh tokens expire after 100 days. Regenerate via OAuth Playground.

### Gmail: "Insufficient permissions"
- Re-authorize Gmail in Settings > Gmail API > Authorize Gmail.

### Push fails with "No vendor mapping"
- Go to Vendor Mappings > create a mapping for the vendor on that platform.

---

*Last updated: April 2026*
*Vithana Accounting Platform v0.3*
