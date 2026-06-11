# QuickBooks Online Setup — Vithana Platform

Complete step-by-step guide to connect Vithana to QuickBooks Online (QBO) for automated bill creation. This guide leads with the **Sandbox** environment for safe testing, then covers the switch to **Production**.

> **How auth works.** Vithana has a built-in **"Authorise with QuickBooks"** button (just like Zoho). You enter only your **Client ID**, **Client Secret**, and **Redirect URI**, click Authorise, approve on Intuit's screen, and Vithana automatically captures and stores the **Refresh Token** and **Realm ID (Company ID)** for you. Vithana then mints short-lived access tokens on every API call. (A manual OAuth Playground fallback is documented at the end for headless setups.)

---

## Overview — What Gets Configured

| Step | What | Where |
|------|------|-------|
| 1 | Create an Intuit Developer app + register the Redirect URI | Intuit Developer Portal |
| 2 | Copy Client ID & Secret | Developer Portal → Keys & OAuth |
| 3 | (Optional) Enable multicurrency | QBO Company Settings — only for foreign-currency bills |
| 4 | Save Client ID / Secret / Redirect URI in Vithana | Vithana → Integrations |
| 5 | Click **Authorise with QuickBooks** | Vithana → Integrations (browser redirect) |
| 6 | Test the connection | Vithana → Integrations |
| 7 | Sync + tag Chart of Accounts | Vithana → Chart of Accounts |
| 8 | Set up Vendor Mappings | Vithana → Vendor Mappings |
| 9 | Push a bill | Vithana → Invoices |

---

## Step 1 — Create an Intuit Developer App

1. Go to [https://developer.intuit.com](https://developer.intuit.com) and sign in (create a free developer account if needed)
2. Open the **Dashboard** → **Create an app**
3. Choose the platform: **QuickBooks Online and Payments**
4. When prompted for scopes, select **`com.intuit.quickbooks.accounting`** (Accounting) — this is the scope Vithana needs to read accounts/vendors and create bills
5. Give the app a name, e.g. `Vithana Accounting`

> Intuit automatically provisions a **sandbox company** for every developer account. You'll connect to this sandbox first (Steps 1–10), then switch to your real production company at the end.

---

## Step 2 — Copy Client ID & Secret

1. Open your app → **Keys & OAuth** tab
2. There are **two** key sets:

   | Key set | Use for | Base URL |
   |---------|---------|----------|
   | **Development** | Sandbox testing (this guide) | `https://sandbox-quickbooks.api.intuit.com` |
   | **Production** | Live company (after Intuit app review) | `https://quickbooks.api.intuit.com` |

3. Under **Development**, copy the **Client ID** and **Client Secret** — you'll paste these into Vithana in Step 4
4. Scroll to **Redirect URIs** and add Vithana's callback URL exactly:
   ```
   http://localhost:8000/api/integrations/quickbooks/oauth/callback
   ```
   > This must match **character-for-character** the Redirect URI you enter in Vithana (Step 4). For production, also add your production host, e.g. `https://app.yourdomain.com/api/integrations/quickbooks/oauth/callback`.
5. Click **Save**

> The **Production** Client ID/Secret only become available after your app passes Intuit's review. For sandbox testing, the **Development** keys are all you need.

---

## Step 3 — (Optional) Enable Multicurrency in QBO

**Skip this step if all your bills are in your company's home currency (e.g. INR).**

If you will push bills in a currency other than the QBO company's home currency (e.g. a USD invoice on an INR company), QBO requires multicurrency:

1. Open the QBO company → **gear icon** → **Account and Settings** → **Advanced**
2. Under **Currency**, set your **Home Currency**, then toggle **Multicurrency** on

> **Multicurrency is irreversible** — once enabled it cannot be turned off, and the home currency cannot be changed afterward. The `home_currency` you enter in Vithana (Step 4) **must match** the QBO company's home currency exactly. See [Currency & Multicurrency](#currency--multicurrency) for how Vithana posts foreign-currency bills.

---

## Step 4 — Save the Integration in Vithana

1. Go to `http://localhost:3000/integrations`

   > The frontend dev server defaults to port **3000**. Port 3001 may belong to an unrelated local project — don't assume it's this app. If your `FRONTEND_URL` differs, use that.

2. Find the **QuickBooks Online** card (status: Not Configured)
3. Click **Configure**
4. Fill in **only** these fields — leave Refresh Token and Realm ID blank (the Authorise step fills them):

   | Field | Sandbox value | Notes |
   |-------|---------------|-------|
   | **Client ID** | from Step 2 (Development) | |
   | **Client Secret** | from Step 2 (Development) | Stored encrypted |
   | **Redirect URI** | `http://localhost:8000/api/integrations/quickbooks/oauth/callback` | Must match Step 1 exactly |
   | **Refresh Token** | *(leave blank)* | Auto-filled by Authorise (Step 5) |
   | **Realm ID (Company ID)** | *(leave blank)* | Auto-filled from the OAuth callback |
   | **API Base URL** | `https://sandbox-quickbooks.api.intuit.com` | This is the config default |
   | **Home Currency** | `INR` | Must equal the QBO company's home currency |
   | **Default Exchange Rate** | *(leave blank)* | Only for foreign-currency bills |

5. Click **Save & Enable**

The integration is created with `platform = "quickbooks"` and stored encrypted in the `integrations` table.

---

## Step 5 — Authorise with QuickBooks

This is the OAuth handshake that captures your **Refresh Token** and **Realm ID** automatically.

1. On the saved **QuickBooks Online** card, click **Authorise with QuickBooks** (green button)
2. The backend builds the Intuit consent URL and redirects your browser to:
   ```
   https://appcenter.intuit.com/connect/oauth2?client_id=...&scope=com.intuit.quickbooks.accounting&...
   ```
3. On Intuit's consent screen, select your **sandbox company** and click **Connect**
4. Intuit redirects back to `…/api/integrations/quickbooks/oauth/callback?code=…&state=…&realmId=…`
5. The backend exchanges the `code` for tokens (HTTP Basic against `https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer`), then **saves the Refresh Token and the Realm ID** into the integration config and enables it
6. You land back on `http://localhost:3000/integrations?quickbooks_connected=1` with a green success banner

> **Refresh token lifetime:** ~**100 days**, and it *rolls forward* — each refresh may return a new token which Vithana persists automatically. If the integration sits idle past ~100 days, the token expires; just click **Authorise with QuickBooks** again.

> **"Invalid redirect_uri" / consent error:** the Redirect URI saved in Vithana (Step 4) does not exactly match what you registered in the Intuit app (Step 1). They must be identical character-for-character.

---

## Step 6 — Test the Connection

1. On the Integrations page, find the **QuickBooks Online** card
2. Click **Test Connection**
3. You should see:
   ```
   Connected to QuickBooks (Sandbox Company_US_1)
   ```
   (The name is whatever your sandbox company is called.)

Internally this calls `GET /companyinfo/{realm_id}` and reads back the company name.

**Via API:**
```bash
curl -X POST "http://localhost:8000/api/integrations/{INTEGRATION_ID}/test" \
  -H "Cookie: access_token=YOUR_JWT"
```

If the test fails:
- `401` / `invalid_grant` → Refresh token expired or revoked → re-click **Authorise with QuickBooks** (Step 5)
- `AuthenticationFailed` → Token from one environment used against the other's base URL → ensure `base_url` matches the key set you authorised with
- Realm mismatch → Authorised against the wrong company → re-authorise and pick the correct company

---

## Step 7 — Sync & Tag Chart of Accounts

This maps your QBO GL accounts so line items post to the right account. Without it, line items fall back to QB account `"1"`.

1. Go to `http://localhost:3000/coa` (Chart of Accounts)
2. Click **Sync from QuickBooks** — this pulls all accounts (`SELECT * FROM Account MAXRESULTS 500`)
3. For each account you want mapped (e.g. `Professional Fees`):
   - Expand the account row
   - Enter the **HSN/SAC codes** that belong to this account (e.g. `998314` for Management Consulting)
   - Click **Save**

> **Tax lines are separate.** Vithana posts **CGST, SGST, and IGST as their own expense lines** on the bill (one line each, when the amount is non-zero), with the main net amount on the primary account line. Make sure your tax/GST GL accounts are synced and resolvable too.

> If a line item has no HSN match and no resolved account, it falls back to QuickBooks account ID `"1"` — set up tagging to avoid this.

---

## Step 8 — Set Up Vendor Mappings

When pushing, Vithana resolves the vendor in this order:
1. **Vendor mapping** — if a mapping exists for the invoice's vendor name, it uses the mapped QB Vendor ID
2. **Exact name search** — otherwise it searches QBO for a vendor whose `DisplayName` exactly matches
3. **Hard error** — if neither resolves, the push fails with *"Vendor not found … Create a vendor mapping before pushing."*

To add a mapping:
1. Go to `http://localhost:3000/vendor-mappings`
2. Click **New Mapping**
3. Set:
   - **Source Name:** the vendor name exactly as extracted from the invoice
   - **Canonical Name:** the vendor's `DisplayName` in QuickBooks
   - **Platform:** `QuickBooks Online`
   - **Platform Vendor ID:** the QB Vendor `Id` (find it in QBO → Expenses → Vendors → open vendor → the `...vendordetail?nameId=<Id>` in the URL)
4. Click **Save**

Alternatively, create the vendor in QBO first (Expenses → Vendors → New vendor), then sync vendors in Vithana.

---

## Step 9 — Push a Bill to QuickBooks

### How to Push

1. Go to `http://localhost:3000/invoices`
2. Find an invoice with status `PARSED` or `WARNING`
3. In the **Push To** column, select **QuickBooks Online**
4. Review the extracted fields — edit GL Account / line items in the grid if needed
5. Click the **Push** button

The same 8-validator pre-push pipeline as Zoho runs first (composition vendor, reconciliation, GSTIN format, GSTIN↔PAN, RCM, GST routing, ITC time limit, duplicate). On success:
- A bill is created via `POST /bill`
- The QuickBooks bill `Id` is saved as the draft's `external_id`
- The invoice status flips to `PUSHED`

6. Log in to the QBO sandbox → **Expenses** → confirm the bill was created

### Overriding Validation Blocks

Most validation failures (duplicate, ITC cutoff, reconciliation, etc.) can be overridden with a reason code, which is logged to the compliance audit trail. **`COMPOSITION_VENDOR` is an absolute hard stop and cannot be overridden.**

---

## Currency & Multicurrency

Vithana follows the QBO API rules for currency on each bill:

- **Home-currency bills** (bill currency == `home_currency`, e.g. INR): `CurrencyRef` is **omitted** — QBO defaults to the company home currency.
- **Foreign-currency bills** (bill currency != `home_currency`, e.g. a USD bill on an INR company): both **`CurrencyRef`** and **`ExchangeRate`** are required by QBO, and **multicurrency must be enabled** in QBO (Step 3).

The exchange rate is sourced from, in order:
1. The invoice's `exchange_rate` field (if set on the draft)
2. The integration's **Default Exchange Rate** config (`default_exchange_rate`)

If neither is set for a foreign-currency bill, the push fails with:
```
Bill currency is USD but QBO home currency is INR. QuickBooks requires an
ExchangeRate for foreign currency bills. Set 'default_exchange_rate' in the
QuickBooks integration config (e.g. 1 USD = X INR), or enable multicurrency
in QBO Company Settings > Advanced and supply an exchange rate.
```

> Enter the **Default Exchange Rate** as: `1 foreign unit = X home units` (e.g. `84.5` if 1 USD = 84.50 INR).

---

## Sandbox → Production

Once you've validated the full flow in the sandbox, switch to your live company:

1. **Get Intuit app approval** — Production keys only unlock after Intuit reviews your app
2. **Copy the Production Client ID & Secret** (Keys & OAuth → Production), and confirm the production Redirect URI is registered
3. **Update the Vithana integration** (or create a separate one) with the Production **Client ID / Secret / Redirect URI**, and set **API Base URL** → `https://quickbooks.api.intuit.com`
4. Click **Authorise with QuickBooks** again and connect your **real company** — this captures the production Refresh Token and Realm ID automatically

> **Recommendation:** keep a **separate integration row per environment** (one sandbox, one production) and toggle `is_enabled` to switch, rather than editing one row back and forth. The token, realm, and base URL must all belong to the same environment — mixing them causes `AuthenticationFailed`.

---

## Credentials Summary

After completing all steps, here is where everything is stored:

| Credential | Where in Vithana | Used for |
|-----------|-----------------|---------|
| Client ID + Secret | DB `integrations` table (platform=`quickbooks`), in `config_encrypted` | Refreshing access tokens (HTTP Basic auth on `/tokens/bearer`) |
| Refresh Token | Same row, `config_encrypted` | Minting short-lived access tokens; auto-rolled forward on refresh |
| Access Token | In-memory only (`QuickBooksAuth` instance), never persisted | Making QBO API calls (Bearer header) |
| Realm ID | Same row | Scoping all API calls (`/v3/company/{realm_id}`) |
| Base URL | Same row | Sandbox vs production endpoint selection |
| Home Currency / Default Exchange Rate | Same row | Currency handling on bills |

> **Encoding note:** the POC stores `config_encrypted` as **base64-encoded JSON** (not yet true encryption). Upgrading to AES-256-GCM is on the production checklist. Nothing is stored on the filesystem.

---

## Environment URLs Reference

| Environment | API Base URL | Keys |
|-------------|-------------|------|
| **Sandbox** | `https://sandbox-quickbooks.api.intuit.com` | Development |
| **Production** | `https://quickbooks.api.intuit.com` | Production |
| OAuth token endpoint (both) | `https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer` | — |
| OAuth Playground | `https://developer.intuit.com/app/developer/playground` | — |

> The full API path Vithana calls is `{base_url}/v3/company/{realm_id}/...` — built internally, you only configure the base URL.

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `400 Bad Request` on `/tokens/bearer` (test) | Refresh token expired (~100 days), revoked, or from the wrong environment | Re-click **Authorise with QuickBooks** (Step 5) — do **not** hand-paste tokens |
| `invalid redirect_uri` on consent screen | Redirect URI in Vithana ≠ the one registered in the Intuit app | Make Step 1 and Step 4 identical character-for-character |
| `AuthenticationFailed` | Token from one environment used against the other's base URL | Ensure Client ID/Secret, Base URL, and the company you authorised all belong to the **same** environment |
| `Vendor '<name>' not found on QuickBooks and no vendor mapping exists` | Invoice vendor name doesn't match any QBO `DisplayName` | Create a Vendor Mapping (Step 8) or create the vendor in QBO |
| `QuickBooks requires an ExchangeRate for foreign currency bills` | Foreign-currency bill with no exchange rate | Set **Default Exchange Rate** in config, and enable multicurrency in QBO (Step 3) |
| Company not found / wrong realm | Authorised against the wrong company | Re-authorise (Step 5) and pick the correct company |
| Line items post to the wrong account | No HSN match and no resolved account → falls back to QB account `"1"` | Sync + tag Chart of Accounts (Step 7) |
| Push blocked by `COMPOSITION_VENDOR` | Vendor is on the GST composition scheme | Absolute hard block — cannot be overridden |

---

## Production Checklist

- [ ] Intuit app approved and **Production** keys obtained
- [ ] Production Redirect URI registered in the Intuit app and saved in Vithana
- [ ] Re-authorised against the **production** company (not sandbox) — refresh token + realm captured
- [ ] `base_url` set to `https://quickbooks.api.intuit.com`
- [ ] `home_currency` matches the production QBO company's home currency
- [ ] Multicurrency enabled **only if** foreign-currency bills are expected; `default_exchange_rate` set
- [ ] Chart of Accounts synced and high-volume HSN/SAC codes tagged (avoid fallback to account `"1"`)
- [ ] Vendor mappings created for recurring vendors
- [ ] Refresh-token expiry reminder in place (~100 days of inactivity invalidates it — just re-authorise)

---

## Appendix — Manual Token (Headless / No Browser)

If you cannot use the in-app Authorise button (e.g. a scripted/headless setup), you can supply a refresh token directly:

1. Use Intuit's **OAuth 2.0 Playground** ([developer.intuit.com/app/developer/playground](https://developer.intuit.com/app/developer/playground)) → select your app → scope `com.intuit.quickbooks.accounting` → **Get authorization code** → **Get tokens**
2. Copy the **Refresh Token** and the **Realm ID** shown
3. In the Vithana integration form, paste them into the **Refresh Token** and **Realm ID** fields and **Save**

> This is the fallback the original integration relied on. A hand-pasted token is the usual cause of a `400 Bad Request` on the token endpoint — prefer the **Authorise with QuickBooks** button, which captures a fresh, environment-correct token automatically.
