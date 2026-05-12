# Zoho Books Setup — Vithana Platform

Complete step-by-step guide to connect Vithana to Zoho Books for automated bill creation.

---

## Overview — What Gets Configured

| Step | What | Where |
|------|------|-------|
| 1 | Create a Zoho API client (OAuth app) | Zoho API Console |
| 2 | Find your Organisation ID | Zoho Books |
| 3 | Find Tax IDs (GST + IGST) | Zoho Books → Settings → Taxes |
| 4 | Find Default Account ID | Zoho Books → Chart of Accounts |
| 5 | Save integration config in Vithana | Vithana → Integrations |
| 6 | Authorise with Zoho (OAuth) | Browser redirect |
| 7 | Test the connection | Vithana → Integrations |
| 8 | Tag Chart of Accounts | Vithana → Chart of Accounts |
| 9 | Push a bill | Vithana → Invoices |

---

## Step 1 — Create a Zoho API Client

> Use `zoho.in` for India. Use `zoho.com` for other regions (and change all URLs accordingly).

1. Go to [https://api-console.zoho.in](https://api-console.zoho.in)
2. Sign in with the **same Zoho account** that owns your Zoho Books organisation
3. Click **Add Client**
4. Choose **Server-based Applications**
5. Fill in the form:

   | Field | Value |
   |-------|-------|
   | Client Name | `Vithana Accounting` |
   | Homepage URL | `http://localhost:3001` |
   | Authorized Redirect URIs | `http://localhost:8000/api/integrations/zoho/oauth/callback` |

   > For production, also add your production URL here, e.g.:
   > `https://app.yourdomain.com/api/integrations/zoho/oauth/callback`

6. Click **Create**

**You will see a credentials screen:**

```
Client ID:     1000.XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
Client Secret: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

7. **Copy both values now** — you will paste them into Vithana in Step 5
8. The Client Secret is shown only once on creation. If you lose it, you can regenerate it on the API Console → your client → **Client Secret** tab

---

## Step 2 — Find Your Organisation ID

The Organisation ID is required in every Zoho Books API call.

1. Log in to [https://books.zoho.in](https://books.zoho.in)
2. Click the **gear icon** (top-right) → **Settings**
3. Under **Organisation**, click **Organisation Profile**
4. Scroll to the bottom — you'll see:
   ```
   Organisation ID: 60069222256
   ```
5. Copy this number

**Alternative — via URL:**
When you are inside Zoho Books, the URL looks like:
```
https://books.zoho.in/app/60069222256#/dashboard
```
The number after `/app/` is your Organisation ID.

---

## Step 3 — Find Tax IDs

You need two tax IDs — one for intra-state (CGST+SGST) and one for inter-state (IGST). Vithana auto-selects the right one per vendor based on GSTIN state codes.

1. In Zoho Books go to **Settings** → **Taxes**
2. You will see a list of tax rates

**Finding the CGST+SGST (intra-state) Tax Group ID:**

Look for a tax group named something like `GST18`, `GST 18%`, or `IGST 18%`. Tax *groups* combine CGST+SGST into one entry. Click on it:
- The URL will contain the tax ID, e.g. `...tax/3699544000000109129`
- Or copy the ID from the tax details panel

**Finding the IGST (inter-state) Tax ID:**

Look for a single tax entry named `IGST 18%` or `IGST18`. Click on it and copy its ID.

> **Entvin Labs live IDs (Karnataka, org 60069222256):**
> - GST18 group (CGST9 + SGST9): `3699544000000109129`
> - CGST9 standalone: `3699544000000109057`
> - SGST9 standalone: `3699544000000109058`
>
> Use the **group ID** (`3699544000000109129`) in the CGST+SGST field, not individual component IDs.

**Alternative — via API (after you have a token):**
```bash
curl "https://www.zohoapis.in/books/v3/settings/taxes?organization_id=YOUR_ORG_ID" \
  -H "Authorization: Zoho-oauthtoken YOUR_ACCESS_TOKEN"
```
Each entry has a `tax_id` field.

---

## Step 4 — Find Default Account ID

The default account is the fallback GL account used when no Chart of Accounts mapping is set for a line item.

1. In Zoho Books go to **Accountant** → **Chart of Accounts**
2. Find the account you want as the default (e.g. `Professional Fees`, `Bank Fees and Charges`)
3. Click on the account name
4. The URL contains the account ID:
   ```
   https://books.zoho.in/app/60069222256#/chartofaccounts/3699544000000000507
   ```
   The last number is the account ID

> **Entvin Labs default:** `3699544000000000507` (Bank Fees & Charges)
>
> Note: For vendor invoices, `Professional Fees` is usually more appropriate. The default is only used as a fallback — individual line items get mapped precisely via Chart of Accounts tagging (Step 8).

**Alternative — via API:**
```bash
curl "https://www.zohoapis.in/books/v3/chartofaccounts?organization_id=YOUR_ORG_ID" \
  -H "Authorization: Zoho-oauthtoken YOUR_ACCESS_TOKEN"
```

---

## Step 5 — Save Zoho Integration in Vithana

1. Go to `http://localhost:3001/integrations`
2. You'll see a **Zoho Books** card in the list (status: Not Configured)
3. Click **Configure** on the Zoho Books card

Fill in the form with all the values collected in Steps 1–4:

| Field | Value | Notes |
|-------|-------|-------|
| **Client ID** | `1000.XXXXX...` | From Step 1 |
| **Client Secret** | `xxxxxx...` | From Step 1 |
| **Redirect URI** | `http://localhost:8000/api/integrations/zoho/oauth/callback` | Must match Step 1 exactly |
| **Refresh Token** | *(leave blank)* | Auto-filled after Step 6 |
| **Organisation ID** | `60069222256` | From Step 2 |
| **API Base URL** | `https://www.zohoapis.in/books/v3` | India region — use `.com` for others |
| **Auth URL** | `https://accounts.zoho.in/oauth/v2/token` | India region — use `.com` for others |
| **Default Account ID** | `3699544000000000507` | From Step 4 |
| **GST Tax ID (intra-state)** | `3699544000000109129` | From Step 3 — CGST+SGST group |
| **IGST Tax ID (inter-state)** | *(from Step 3)* | From Step 3 — IGST entry |
| **Organisation State Code** | `29` | Your GST state code (see table below) |

4. Click **Save**

The integration is now saved but **not yet authorised** — the Refresh Token field is empty.

### State Code Reference

| State | Code | State | Code |
|-------|------|-------|------|
| Karnataka | `29` | Tamil Nadu | `33` |
| Maharashtra | `27` | Delhi | `07` |
| Telangana | `36` | Gujarat | `24` |
| West Bengal | `19` | Rajasthan | `08` |
| Kerala | `32` | Andhra Pradesh | `37` |
| Uttar Pradesh | `09` | Haryana | `06` |

> The org state code is used to auto-detect inter-state vs intra-state for every vendor bill. The system compares the **vendor's GSTIN prefix** against your company's buyer GSTIN prefix. The org state code is only a fallback when buyer GSTIN is not on the invoice.

---

## Step 6 — Authorise with Zoho (OAuth)

This step gets the **Refresh Token** — the long-lived credential that allows Vithana to create bills without asking you to log in each time.

1. After saving in Step 5, the Zoho integration card shows **"Authorise with Zoho"** button
2. Click **Authorise with Zoho**
3. The backend builds the OAuth URL and redirects your browser to:
   ```
   https://accounts.zoho.in/oauth/v2/auth?scope=ZohoBooks.fullaccess.all&client_id=...
   ```
4. Zoho shows a consent screen: **"Vithana Accounting wants to access your Zoho Books data"**
5. Make sure the correct Zoho account (the one with your Books org) is selected
6. Click **Accept**
7. Zoho redirects back to:
   ```
   http://localhost:8000/api/integrations/zoho/oauth/callback?code=...&state=...
   ```
8. The backend exchanges the code for an `access_token` + `refresh_token`
9. The refresh token is **saved to the integration config** in the database
10. You are redirected back to `http://localhost:3001/integrations?zoho_connected=1`
11. The integration card now shows **Health: OK** (or it triggers a connection test automatically)

> **Scope used:** `ZohoBooks.fullaccess.all` — full read/write access to Zoho Books for the organisation.

> **If you see "Invalid Client":** The `redirect_uri` saved in Vithana (Step 5) does not exactly match what you registered in the Zoho API Console (Step 1). They must be identical character-for-character.

---

## Step 7 — Test the Connection

1. On the Integrations page, find the Zoho Books card
2. Click the **Test Connection** button (or it runs automatically after OAuth)
3. You should see:
   ```
   Connected to Zoho Books
   org_name: Entvin Labs Private Limited
   currency: INR
   ```

**Via API:**
```bash
curl -X POST "http://localhost:8000/api/integrations/{INTEGRATION_ID}/test" \
  -H "Cookie: access_token=YOUR_JWT"
```

If the test fails:
- `Token refresh failed: HTTP 401` → Refresh token expired or revoked → repeat Step 6
- `Invalid Client` → Client ID/Secret mismatch → check Step 5
- `Organisation not found` → Wrong Organisation ID → check Step 2

---

## Step 8 — Tag Chart of Accounts (for Line Item Mapping)

This step maps your GL accounts to the HSN/SAC codes on vendor invoices. Without this, all line items fall back to the Default Account ID from Step 5.

1. Go to `http://localhost:3001/coa` (Chart of Accounts)
2. Click **Sync from Zoho** — this pulls all accounts from Zoho Books into Vithana
3. For each account you want to map (e.g. `Professional Fees`):
   - Click the account row to expand it
   - In the **HSN/SAC Codes** field, type the HSN or SAC codes that belong to this account
   - e.g. `998314` for Management Consulting; `9983` for IT services
   - Click **Save**
4. When a bill is pushed, Vithana checks each line item's HSN code against this map and assigns the correct Zoho account ID

> If no HSN match is found, the line item uses the draft-level GL Account (editable in the invoice grid) → then falls back to the Default Account ID.

---

## Step 9 — Push a Bill to Zoho Books

### The Full Push Flow

```
Invoice parsed → Draft created → Review in Invoices grid
  → Set GL Account (optional override)
  → Click Push → 7 validation checks run:
      1. Composition vendor check (hard block — composition vendors can't claim ITC)
      2. GSTIN format check
      3. RCM (Reverse Charge) flag check
      4. GST routing check (intra vs inter-state)
      5. ITC cutoff check (30 Nov deadline for FY)
      6. Reconciliation check (amount vs line items)
      7. Duplicate invoice check
  → Vendor resolved (searched in Zoho by name, or via vendor mapping)
  → GST routing: vendor state code vs buyer state code → CGST+SGST or IGST
  → POST /bills to Zoho Books API
  → Bill ID saved to invoice_drafts.external_bill_id
  → Invoice status updated to PUSHED
  → Original PDF attached to the Zoho bill
  → Audit log entry created
```

### How to Push

1. Go to `http://localhost:3001/invoices`
2. Find the invoice to push — status should be `PARSED` or `WARNING`
3. In the **Push To** column, select `Zoho Books` from the dropdown
4. Review the extracted fields — you can edit GL Account and line items directly in the grid
5. Click the **Push** button (rocket icon)
6. If validation passes, the row turns green with status **PUSHED** and a Zoho bill ID appears
7. Log in to Zoho Books → **Purchases** → **Bills** to confirm the bill was created

### Overriding Validation Blocks

Some validation failures can be overridden (e.g. duplicate invoice, ITC cutoff):
1. Click the **Override** button on the failed validation row
2. Select a reason code from the dropdown
3. Enter a short justification note
4. Click **Confirm Override** — the override is logged to the compliance audit trail with your name, email, and role

> **COMPOSITION_VENDOR** is a hard block and cannot be overridden. Composition scheme vendors cannot issue tax invoices — the invoice is invalid for ITC purposes.

### Vendor Not Found

If the push fails with `"Vendor not found"`:

1. Go to `http://localhost:3001/vendor-mappings`
2. Click **New Mapping**
3. Set:
   - **Source Name:** the vendor name as extracted from the invoice (e.g. `VITHANA CONSULTING SERVICES PRIVATE LIMITED`)
   - **Canonical Name:** the exact name as it appears in Zoho Books (e.g. `Vithana Consulting`)
   - **Platform:** `Zoho Books`
   - **Platform Vendor ID:** the Zoho `contact_id` (find it in Zoho Books → Contacts → click vendor → copy from URL)
4. Click **Save**
5. Retry the push

Alternatively, create the vendor directly in Zoho Books first, then sync vendors:
- Go to Zoho Books → **Contacts** → **New Contact** → type: **Vendor**
- Fill in name, GSTIN, PAN
- Then in Vithana: Vendor Mappings → Sync Vendors from Zoho

---

## Credentials Summary

After completing all steps, here is where everything is stored:

| Credential | Where in Vithana | Used for |
|-----------|-----------------|---------|
| Client ID + Secret | DB `integrations` table (platform=`zoho`), encrypted | Building OAuth URL + token exchange |
| Refresh Token | Same DB row, `config_encrypted` field | Auto-refreshing access tokens (every ~60 min) |
| Access Token | In-memory only (`ZohoAuth` instance), never persisted | Making Zoho API calls |
| Organisation ID | Same DB row | Scoping all API calls to your org |
| Tax IDs (GST/IGST) | Same DB row | Assigning correct tax to line items |
| Default Account ID | Same DB row | Fallback GL account for unmapped line items |

**Nothing is stored on the filesystem.** All Zoho credentials are encrypted in MySQL (`integrations.config_encrypted` column).

---

## Region URLs Reference

| Region | Auth URL | API Base URL | API Console |
|--------|----------|-------------|-------------|
| India | `https://accounts.zoho.in/oauth/v2/token` | `https://www.zohoapis.in/books/v3` | `api-console.zoho.in` |
| US | `https://accounts.zoho.com/oauth/v2/token` | `https://www.zohoapis.com/books/v3` | `api-console.zoho.com` |
| EU | `https://accounts.zoho.eu/oauth/v2/token` | `https://www.zohoapis.eu/books/v3` | `api-console.zoho.eu` |
| AU | `https://accounts.zoho.com.au/oauth/v2/token` | `https://www.zohoapis.com.au/books/v3` | `api-console.zoho.com.au` |

> The platform is configured for **India** (`.in` endpoints). If your Zoho Books account is on a different region, update both the Auth URL and API Base URL in Step 5.

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `Invalid Client` on OAuth | Redirect URI mismatch between API Console and Vithana config | Make URI in Step 1 and Step 5 identical |
| `Token refresh failed: HTTP 401` | Refresh token expired or revoked | Re-authorise: Integrations → Zoho → Authorise with Zoho |
| `Vendor not found` | Vendor name in invoice doesn't match Zoho | Create a Vendor Mapping (see Step 9) |
| `No account mapping found` | No HSN match and no default account | Set Default Account ID (Step 5) or tag COA (Step 8) |
| `IGST has to be applied` | Vithana sent intra-state tax for an inter-state vendor | Auto-retried with IGST — if persistent, check org state code |
| `Already been created` | Bill already exists in Zoho | Idempotency check finds existing bill — returns existing bill ID, no duplicate created |
| `Organisation not found` | Wrong Organisation ID | Re-check Step 2 — use the number from Zoho Books Settings, not the account ID |
| `ZohoBooks.fullaccess.all` scope error | OAuth client type doesn't support this scope | Use **Server-based Applications** in API Console, not Desktop |
| Push blocked by `COMPOSITION_VENDOR` | Vendor is on GST composition scheme | Hard block — cannot be overridden. Composition vendors cannot issue tax invoices |
| Push blocked by `ITC_CUTOFF` | Invoice date beyond ITC claim deadline | Override with reason code if legitimate |

---

## Production Checklist

- [ ] Add production redirect URI in Zoho API Console (alongside localhost)
- [ ] Update `redirect_uri` in Vithana integration config to production URL
- [ ] Re-authorise after deploying to production (refresh token is scoped to the redirect URI)
- [ ] Set `base_url` and `auth_url` to production region URLs if changed
- [ ] Verify `organization_id` matches the production Zoho Books org (not a test org)
- [ ] Confirm tax IDs are from the production Zoho org (not a sandbox)
- [ ] Set `org_state_code` correctly for your registered GST state
- [ ] Tag all high-volume HSN/SAC codes in Chart of Accounts to avoid fallback account
- [ ] Check all live bills are on the correct GL account in Zoho Books (e.g. Professional Fees vs Bank Fees)
