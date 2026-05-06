# Enable Google Drive Storage for Invoice Attachments

By default, invoice attachments are saved to the local filesystem (`data/attachments/`).
This guide walks through switching `STORAGE_BACKEND` to `google_drive` so every invoice
is also uploaded to a per-tenant Google Drive folder and attached to its Zoho bill.

---

## How it works

| Setting | Behaviour |
|---------|-----------|
| `STORAGE_BACKEND=local` | Invoice saved to disk only. Google Drive is never called. *(default)* |
| `STORAGE_BACKEND=google_drive` | Invoice saved to disk **and** uploaded to Drive. After a successful Zoho push the PDF is attached to the Zoho bill automatically. |

Drive folder structure created per upload:
```
/{parent_folder}
  └── {year}/
        └── {vendor_name}/
              └── invoice_filename.pdf
```

---

## Prerequisites

- A Google Cloud project with an OAuth 2.0 Client ID (the same project used for Gmail — `poc-vithana-automation`)
- The Google Drive API enabled on that project
- Docker MySQL container running (`day3-db-1`)
- Backend venv at `backend/.venv/`

---

## Step 1 — Enable the Google Drive API

1. Open [Google Cloud Console → APIs & Services → Library](https://console.cloud.google.com/apis/library)
2. Search **Google Drive API**
3. Click **Enable**

---

## Step 2 — Add the Drive scope to the OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen → Edit App**
2. Under **Scopes**, click **Add or Remove Scopes**
3. Add: `https://www.googleapis.com/auth/drive.file`
4. Save and continue through all screens

> `drive.file` is the minimum scope — the app can only access files it creates itself.
> It cannot read the user's existing Drive files.

---

## Step 3 — Generate a new OAuth token with Drive scope

The existing Gmail token does **not** include the Drive scope. Run this once to get a
combined token covering both Gmail and Drive.

```bash
cd /path/to/backend

.venv/bin/python3 - <<'EOF'
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

# credentials.json = downloaded from Google Cloud Console → Credentials → your OAuth Client
flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

print(json.dumps(json.loads(creds.to_json()), indent=2))
EOF
```

A browser window opens. Log in as the account that should own the Drive folder
(e.g. `deepak2004sakthi@gmail.com`). Copy the full JSON printed to the terminal —
that is your `token_json`.

---

## Step 4 — (Optional) Create a parent folder in Google Drive

If you want all invoices grouped under a single root folder:

1. Open [Google Drive](https://drive.google.com)
2. Create a folder, e.g. `Vithana Invoices`
3. Right-click → **Get link** → copy the URL
4. Extract the folder ID from the URL:
   ```
   https://drive.google.com/drive/folders/1ABC123XYZ_your_folder_id
                                           ^^^^^^^^^^^^^^^^^^^^^^^^
   ```
5. Keep this ID for Step 5. If you skip this step, invoices are uploaded to the Drive root.

---

## Step 5 — Insert the `google_drive` integration into the database

Connect to MySQL:

```bash
docker exec -it day3-db-1 mysql -uaccounting -paccounting accounting_automation
```

Find the company ID:

```sql
SELECT id, name FROM companies;
```

Insert the integration (replace `<company_id>`, `<token_json>`, and `<parent_folder_id>`):

```sql
INSERT INTO integrations
  (company_id, platform, display_name, config_encrypted, is_enabled, health_status, created_at, updated_at)
VALUES (
  <company_id>,
  'google_drive',
  'Google Drive',
  TO_BASE64(JSON_OBJECT(
    'token_json',        '<paste token_json here as a single-line JSON string>',
    'parent_folder_id',  '<paste folder ID here, or empty string>'
  )),
  1,
  'UNKNOWN',
  NOW(),
  NOW()
);
```

> `config_encrypted` is base64-encoded JSON — `TO_BASE64(JSON_OBJECT(...))` handles this in one step.

Verify it was inserted:

```sql
SELECT id, platform, is_enabled FROM integrations WHERE platform = 'google_drive';
```

---

## Step 6 — Set `STORAGE_BACKEND=google_drive`

**Option A — `.env` file** (requires server restart):

```dotenv
# backend/.env
STORAGE_BACKEND=google_drive
```

**Option B — Admin dashboard** (no restart needed):

```bash
# Using the admin API directly
curl -X POST http://localhost:8000/api/admin/config \
  -H "X-Admin-Key: v1th4n4-flush-s3cr3t-2026" \
  -H "Content-Type: application/json" \
  -d '{"STORAGE_BACKEND": "google_drive"}'
```

---

## Step 7 — Verify

**Check the health endpoint:**

```bash
curl http://localhost:8000/api/health | python3 -m json.tool
```

Expected:
```json
{
  "storage_backend": "google_drive",
  ...
}
```

**Upload a test invoice:**

```bash
curl -X POST http://localhost:8000/api/ingest/upload/file \
  -F "file=@/path/to/test_invoice.pdf"
```

**Confirm Drive file ID was stored:**

```sql
SELECT id, file_name, drive_file_id FROM invoices ORDER BY id DESC LIMIT 5;
```

**Confirm the file is visible in Drive:**
Open Google Drive → navigate to `/{year}/{vendor_name}/` → the PDF should be there.

**Confirm Zoho bill attachment:**
After pushing any draft to Zoho, open the bill in [Zoho Books](https://books.zoho.in) →
click **Attachments** tab → the invoice PDF should appear.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `drive_file_id` is NULL after upload | `STORAGE_BACKEND` is still `local` | Set `STORAGE_BACKEND=google_drive` (Step 6) |
| `STORAGE_BACKEND=google_drive but no google_drive integration configured` in logs | Integration row missing or `is_enabled=0` | Complete Step 5; check `is_enabled=1` |
| `Google Drive OAuth token invalid` | Token expired or scope missing | Re-run Step 3, update `config_encrypted` in DB |
| `insufficient authentication scopes` | Old token without `drive.file` scope | Re-run Step 3 |
| Zoho attachment tab is empty | `file_path` on disk was deleted before push | Keep `data/attachments/` intact; attachment uses the local copy |
| `parent_folder_id` not found error | Wrong folder ID or wrong Drive account | Double-check the ID from the folder URL (Step 4) |

---

## Reverting to local storage

```bash
# .env
STORAGE_BACKEND=local
```

Or via admin API:

```bash
curl -X POST http://localhost:8000/api/admin/config \
  -H "X-Admin-Key: v1th4n4-flush-s3cr3t-2026" \
  -H "Content-Type: application/json" \
  -d '{"STORAGE_BACKEND": "local"}'
```

Existing `drive_file_id` values in the database are preserved — switching back to `local`
does not delete any files already uploaded to Drive.
