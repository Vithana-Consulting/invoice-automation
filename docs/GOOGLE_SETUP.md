# Google Cloud Setup — Vithana Platform

Complete step-by-step guide to configure Google Cloud for **user login (OAuth)** and **Gmail inbox access** on the Vithana platform.

One Google Cloud project covers both. You create **two separate OAuth 2.0 Client IDs** — one for login, one for Gmail — because they use different redirect URIs and scopes.

---

## Overview

| What | OAuth Client | Redirect URI (sub-route) | Scope |
|------|-------------|--------------------------|-------|
| User login | Web application | `/api/auth/google/callback` | `openid email profile` |
| Gmail read | Web application | `/api/settings/gmail-callback` | `https://mail.google.com/` |

> Prefix each sub-route with your backend base URL when entering them in Google Cloud Console.
> Local: `http://localhost:8000`  |  Production: `https://api.yourdomain.com`

---

## Step 1 — Create or Open a Google Cloud Project

1. Go to [https://console.cloud.google.com](https://console.cloud.google.com)
2. In the top nav bar click the **project selector** dropdown (next to "Google Cloud" logo)
3. Click **New Project**
   - **Project name:** `Vithana Accounting` (or any name)
   - **Location:** leave as "No organisation" unless you have a Google Workspace org
4. Click **Create** — wait ~10 seconds for the project to provision
5. Make sure the new project is **selected** in the dropdown before continuing

---

## Step 2 — Enable Required APIs

### 2a — Enable Gmail API

1. In the left sidebar go to **APIs & Services** → **Library**
2. In the search box type `Gmail API`
3. Click the **Gmail API** card
4. Click the blue **Enable** button
5. Wait for it to enable — you'll land on the Gmail API overview page

> If you see "API enabled" with a green checkmark, it's already on.

### 2b — Enable Google People API (required for login user info)

1. Go back to **APIs & Services** → **Library**
2. Search `People API`
3. Click **Google People API** → **Enable**

---

## Step 3 — Configure OAuth Consent Screen

This is the "permission dialog" users see when they click **Sign in with Google**.

1. Go to **APIs & Services** → **OAuth consent screen**
2. Choose **External** (unless you have Google Workspace and want Internal-only)
3. Click **Create**

**Fill in App information:**
| Field | Value |
|-------|-------|
| App name | `Vithana Accounting` |
| User support email | `deepak2004sakthi@gmail.com` |
| App logo | *(optional — upload a logo PNG)* |
| Developer contact email | `deepak2004sakthi@gmail.com` |

4. Click **Save and Continue**

**Scopes page:**
1. Click **Add or Remove Scopes**
2. In the filter, search for and tick these scopes:
   - `openid`
   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/userinfo.profile`
   - `https://mail.google.com/` — (search "Gmail" — this is the full Gmail scope)
3. Click **Update** → **Save and Continue**

**Test users page** (only needed while app is in "Testing" status):
1. Click **Add Users**
2. Add all email addresses that need to log in during development:
   - e.g. `deepak2004sakthi@gmail.com`
   - Add every team member who will test the platform
3. Click **Save and Continue** → **Back to Dashboard**

> **Publishing:** When ready for production, click **Publish App** on the consent screen page to move from "Testing" to "In production". Until then, only test users can log in.

---

## Step 4 — Create OAuth Client for User Login

This client handles the **Sign in with Google** flow.

1. Go to **APIs & Services** → **Credentials**
2. Click **+ Create Credentials** → **OAuth 2.0 Client ID**
3. **Application type:** `Web application`
4. **Name:** `Vithana Login`

**Authorised redirect URIs — click "+ Add URI":**

```
http://localhost:8000/api/auth/google/callback
```

> Sub-route: `/api/auth/google/callback`
> For production add: `https://api.yourdomain.com/api/auth/google/callback`

5. Click **Create**

**A dialog pops up showing your credentials:**

```
Client ID:     123456789012-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.apps.googleusercontent.com
Client Secret: GOCSPX-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

6. **Copy both values** — you will need them in Step 6
7. Click **Download JSON** — save the file as `google_oauth_credentials.json` somewhere safe
8. Click **OK**

---

## Step 5 — Create OAuth Client for Gmail

This is a **separate** client for Gmail inbox access (different redirect URI and scope).

1. Still on **APIs & Services** → **Credentials**
2. Click **+ Create Credentials** → **OAuth 2.0 Client ID**
3. **Application type:** `Web application`
4. **Name:** `Vithana Gmail`

**Authorised redirect URIs — click "+ Add URI":**

```
http://localhost:8000/api/settings/gmail-callback
```

> Sub-route: `/api/settings/gmail-callback`
> For production add: `https://api.yourdomain.com/api/settings/gmail-callback`

5. Click **Create**

**The credentials dialog appears again:**

6. **Copy the Client ID and Client Secret** for the Gmail client
7. Click **Download JSON** — save as `gmail_credentials.json`

> This downloaded JSON is exactly the file you upload in the Vithana Settings page (Step 8). Keep it safe.

8. Click **OK**

---

## Step 6 — Configure Vithana Admin: Create Company + Set Login OAuth

This wires the Google login credentials to your company in Vithana.

### 6a — Open the Admin Dashboard

1. Go to **Admin** in the Vithana UI
2. Enter the Admin API Key
3. Click **Login**

### 6b — Create the Company (if not done yet)

1. Click the **Companies** tab
2. Click **New Company**
3. Fill in:
   | Field | Example |
   |-------|---------|
   | Company Name | `Entvin Labs Private Limited` |
   | Domain | `entvin.com` |
4. Click **Create**
5. Note the **Company ID** shown (e.g. `10`) — you need it next

> **Domain mapping is how login works.** A user who logs in with `user@entvin.com` is automatically routed to this company. Set the domain to match your team's Google Workspace email domain.

### 6c — Set Google OAuth Credentials for the Company

1. Click on the company row → **OAuth Settings**
2. Paste the credentials from Step 4:
   | Field | Value |
   |-------|-------|
   | Client ID | *(Login client ID from Step 4)* |
   | Client Secret | *(Login client secret from Step 4)* |
   | Redirect URI | `http://localhost:8000/api/auth/google/callback` |
3. Click **Save**

**Via API (alternative):**
```bash
curl -X PUT http://localhost:8000/api/admin/companies/{COMPANY_ID}/oauth \
  -H "X-Admin-Key: YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "YOUR_LOGIN_CLIENT_ID",
    "client_secret": "YOUR_LOGIN_CLIENT_SECRET",
    "redirect_uri": "http://localhost:8000/api/auth/google/callback"
  }'
```

### 6d — Set the System Redirect URI

1. In the Admin dashboard click **System Config**
2. Set:
   | Key | Value |
   |-----|-------|
   | `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/auth/google/callback` |
3. Click **Save**

---

## Step 7 — Test User Login

1. Open the Vithana app in your browser
2. The login page asks for your **email address** (not a username)
3. Enter your email (e.g. `deepak2004sakthi@gmail.com`)
4. Click **Continue** — the system looks up your email domain → finds your company → builds the Google OAuth URL
5. You're redirected to Google's consent screen
6. Click **Allow** / **Continue**
7. Google redirects back to `/api/auth/google/callback`
8. The backend creates your user + company_member record and sets a JWT cookie
9. You land on the **Invoices** page — login is complete

> **If you see "Login failed: Company not found"** — your email domain does not match any company's `domain` field. Check Step 6b.
>
> **If you see Google error "redirect_uri_mismatch"** — the URI in Step 4 does not exactly match what's saved in Step 6c. They must be character-for-character identical.
>
> **If you see "Access blocked: app not verified"** — your app is in Testing mode and your email is not in the test users list. Add it in Step 3.

---

## Step 8 — Configure Gmail Integration

After logging in, set up Gmail so the platform can read your inbox.

### 8a — Upload Gmail Credentials

1. Go to **Settings** in the Vithana app
2. Click the **Gmail** tab
3. Click **Upload credentials.json**
4. Select the `gmail_credentials.json` file you downloaded in Step 5
5. You should see **"Gmail credentials uploaded"** confirmation

What this does: the file is parsed and stored **encrypted** in the database for your company. It is never written to the filesystem.

### 8b — Set the Gmail Redirect URI in System Config

The Gmail OAuth callback URI must match what you registered in Step 5.

**Via Admin dashboard → System Config**, set:

| Key | Value |
|-----|-------|
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/settings/gmail-callback` |

> Sub-route: `/api/settings/gmail-callback` — must match exactly what you entered in Google Cloud Console in Step 5.

### 8c — Authorise Gmail Access

1. Still on **Settings** → Gmail tab
2. Click **Authorise Gmail**
3. You're redirected to Google's consent screen — this time it asks for **Gmail access** (`Read, compose, send, and permanently delete all your email from Gmail`)
4. Click **Allow**
5. Google redirects back to `/api/settings/gmail-callback`
6. The backend exchanges the code for a token and stores it encrypted in the database
7. You're redirected back to **Settings** — the page shows **Gmail: Connected** with a green indicator

### 8d — Set Gmail Label (Optional)

By default the system fetches emails with the Gmail label **`Invoices`**.

To use a different label:
1. In Gmail, create a label (e.g. `Bills`, `AP`, `Vendor Invoices`)
2. In Vithana **Settings** → Gmail → **Label** field, type the exact label name
3. Click **Save**

The label match is case-sensitive and must exactly match your Gmail label.

---

## Step 9 — Ingest Emails

1. Go to the **Invoices** page in Vithana
2. Click **Ingest Emails** (top-right button)
3. The system fetches up to 200 emails labelled with your configured label
4. PDF and image attachments are extracted, parsed by GPT-4o, and appear as invoices
5. A status banner shows progress — it survives page reload and updates every 3 seconds while running

**What counts as a processable email:**
- Has a PDF or image attachment (`.pdf`, `.jpg`, `.jpeg`, `.png`, `.tiff`)
- Has not been processed before (tracked by Gmail `message_id` — re-ingesting is safe and idempotent)
- Replies and forwarded emails in threads are all processed individually

---

## Redirect URI Reference

| Flow | Sub-route | Full URI (local) |
|------|-----------|-----------------|
| User login | `/api/auth/google/callback` | `http://localhost:8000/api/auth/google/callback` |
| Gmail access | `/api/settings/gmail-callback` | `http://localhost:8000/api/settings/gmail-callback` |

Enter the **Full URI** in Google Cloud Console. Enter only the **Sub-route** in Vithana's System Config (`GOOGLE_REDIRECT_URI`).

---

## Credentials Summary

After completing all steps you will have:

| Credential | Where stored | Used for |
|-----------|-------------|---------|
| Login Client ID + Secret | Vithana DB (`integrations`, platform=`google_oauth`) | User login per company |
| Gmail Client ID + Secret | `gmail_credentials.json` uploaded via Settings → DB (`integrations`, platform=`gmail`) | Gmail inbox read access |
| Gmail OAuth Token | Vithana DB (`integrations`, platform=`gmail`) | Auto-refreshed; stored after Step 8c |
| Vithana JWT | Browser cookie (`access_token`, HttpOnly) | All API calls after login |

**Nothing is stored on the filesystem in production** — all credentials are encrypted in MySQL (`integrations.config_encrypted`).

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `redirect_uri_mismatch` | URI in Google Cloud ≠ URI saved in Vithana | Make them character-for-character identical, including http/https and port |
| `Access blocked: app not verified` | App in Testing mode, user not in test list | Add user email in OAuth Consent Screen → Test users |
| `Invalid grant` | Gmail token expired or revoked | Re-authorise: Settings → Gmail → Authorise Gmail |
| `Company not found` | Email domain not mapped to a company | Check company domain in Admin → Companies |
| `Gmail credentials not found` | credentials.json not uploaded | Settings → Gmail → Upload credentials.json |
| `API not enabled` | Gmail API or People API disabled | Enable in Cloud Console → APIs & Services → Library |
| Google asks for permission twice | Using two separate OAuth clients (correct) | Normal — first for login, second for Gmail access |

---

## Production Checklist (before go-live)

- [ ] Move from `http://` to `https://` for all redirect URIs in Google Cloud Console
- [ ] Add production domain URIs alongside localhost URIs in both OAuth clients
- [ ] Publish the OAuth consent screen (move from Testing → In production)
- [ ] If using Google Workspace, consider switching consent screen to **Internal** (no review needed)
- [ ] Rotate the Gmail OAuth token by re-authorising after moving to production domain
- [ ] Set `GOOGLE_REDIRECT_URI` in system config to the production backend URL
- [ ] Update the Login client's redirect URI in the company OAuth config (Admin → Company → OAuth)
