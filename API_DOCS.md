# Vithana Accounting Platform - API Reference

Base URL: `http://localhost:8000`
Swagger UI: `http://localhost:8000/docs`

---

## Authentication

All tenant-scoped routes (`/api/drafts`, `/api/rules`, `/api/integrations`, etc.) require:
1. JWT cookie (`access_token`) — set by Google OAuth login
2. Tenant context — auto-resolved from user's company membership

Optional header `X-Company-Id` to switch between companies (for multi-company users).

### `GET /api/auth/google/login`
Redirects to Google OAuth consent screen.

### `GET /api/auth/google/callback?code={code}`
Handles OAuth callback. Creates/updates user. If new user → auto-creates company + MySQL views. Sets JWT cookie. Redirects to `/dashboard`.

### `POST /api/auth/logout`
Clears JWT cookie.

### `GET /api/auth/me`
Returns current user with company info.
```json
{
  "status": "success",
  "data": {
    "id": 1,
    "email": "finance@acme.com",
    "name": "Acme Finance",
    "picture_url": "https://...",
    "is_admin": false,
    "companies": [
      {"id": 1, "name": "Acme Accounting", "slug": "acme-accounting", "role": "owner"}
    ],
    "active_company": {"id": 1, "name": "Acme Accounting", "slug": "acme-accounting", "role": "owner"}
  }
}
```

---

## Admin Dashboard

All admin endpoints require `X-Admin-Key` header matching `ADMIN_API_KEY` in `.env`.

### `POST /api/admin/login`
Validate admin key.
```json
// Request
{"admin_key": "your-admin-key"}
// Response
{"status": "success", "data": {"authenticated": true}}
```

### `GET /api/admin/config`
List all config values with metadata (editable, secret, overridden).
```json
{
  "status": "success",
  "data": [
    {"key": "PARSER_MODE", "value": "llm", "is_editable": true, "is_overridden": false, "is_secret": false}
  ]
}
```

### `PUT /api/admin/config`
Update runtime config (no restart needed).
```json
// Request
{"PARSER_MODE": "tesseract", "LLM_MODEL": "gpt-4o-mini"}
// Response
{"status": "success", "data": {"updated": ["PARSER_MODE", "LLM_MODEL"], "errors": []}}
```

### `DELETE /api/admin/config/{key}`
Reset a config key to its `.env` value.

### `DELETE /api/admin/config`
Reset ALL runtime overrides.

### `POST /api/admin/flush`
Delete all invoice data, attachments, and audit logs. Preserves users and integrations.

---

## Integrations (Platform Marketplace)

All endpoints tenant-scoped — each company has its own integrations.

### `GET /api/integrations/platforms`
All available platforms with config field schemas (for dynamic form rendering).

### `GET /api/integrations`
All integrations (configured + unconfigured) for the current company.
```json
{
  "data": [
    {
      "id": 1, "platform": "zoho", "display_name": "Zoho Books",
      "category": "billing", "is_enabled": true, "is_configured": true,
      "health_status": "HEALTHY"
    },
    {
      "id": null, "platform": "stripe", "category": "source",
      "is_configured": false, "health_status": "NOT_CONFIGURED"
    }
  ]
}
```

### `GET /api/integrations/{id}`
Single integration with decrypted config (for edit form pre-population).

### `POST /api/integrations`
Create integration with platform credentials.
```json
{
  "platform": "zoho",
  "config": {"client_id": "...", "client_secret": "...", "refresh_token": "...", "organization_id": "..."},
  "is_enabled": true
}
```

### `PUT /api/integrations/{id}`
Update config or enable/disable.

### `DELETE /api/integrations/{id}`
Remove integration.

### `POST /api/integrations/{id}/test`
Test real API connectivity (token refresh, API call, returns org info).
```json
{
  "data": {
    "healthy": true, "message": "Connected to Zoho Books",
    "details": {"org_name": "vithana-company", "currency": "INR"}
  }
}
```

### `POST /api/integrations/{id}/toggle`
Enable/disable toggle.

---

## Ingestion

### `POST /api/ingest/{source}`
Pull invoices from source. `source` = `gmail` | `stripe` | `chargebee`.
```json
{
  "data": {"emails_found": 4, "new_emails": 4, "invoices_parsed": 7, "drafts_created": 7, "errors": []}
}
```

### `POST /api/ingest/upload/file`
Upload invoice file directly. Multipart form with `file` field.
```json
{"data": {"invoice_id": 12, "parsed": true, "draft_id": 8}}
```

### `POST /api/ingest/reparse/{invoice_id}`
Re-parse a single invoice with the current parser mode.
```json
{"data": {"invoice_id": 1, "vendor_name": "ZOHO Corporation Private Limited", "total_amount": 377.60, "parser_mode": "llm"}}
```

### `POST /api/ingest/reparse-all`
Re-parse all invoices.
```json
{"data": {"total": 8, "success": 7, "failed": 1, "results": [...]}}
```

---

## Invoice Drafts

### `GET /api/drafts?status={}&push_to={}&source={}&limit=50&offset=0`
List drafts with filters. Status values: `PENDING_REVIEW`, `PENDING_VENDOR`, `APPROVED`, `PUSHED`, `PUSH_FAILED`, `REJECTED`.

### `GET /api/drafts/{id}`
Single draft detail.

### `PUT /api/drafts/{id}`
Update editable fields: `vendor_name`, `resolved_vendor_name`, `invoice_number`, `invoice_date`, `due_date`, `total_amount`, `tax_amount`, `currency`, `push_to`.

### `POST /api/drafts/{id}/approve`
Approve draft. Checks vendor mapping — if missing, sets `PENDING_VENDOR` instead.

### `POST /api/drafts/{id}/reject`
Reject draft.

### `POST /api/drafts/{id}/push`
Push approved draft to billing platform. Checks vendor mapping — blocks if missing.
```json
{"data": {"draft_id": 1, "external_bill_id": "3699544000001234567", "platform": "zoho"}}
```

### `POST /api/drafts/bulk-approve`
```json
{"draft_ids": [1, 2, 3]}
```

### `POST /api/drafts/bulk-push`
Per-draft vendor mapping check. Unmapped drafts → PENDING_VENDOR.

### `POST /api/drafts/apply-rules`
Apply all active rules to pending drafts. Optional `draft_ids` to target specific drafts.
```json
// Request (optional)
{"draft_ids": [1, 2]}
// Response
{"data": {"matched": 3, "skipped": 5, "results": [{"draft_id": 1, "rule_name": "...", "push_to": "zoho"}]}}
```

### `POST /api/drafts/resolve-vendors`
Re-check all PENDING_VENDOR drafts — auto-approve those with mappings now.

### `GET /api/drafts/export`
Download as `.xlsx` Excel file. Supports same filters.

---

## Rules

### `GET /api/rules`
All rules ordered by priority.

### `POST /api/rules`
Create rule.
```json
{
  "name": "Google invoices to Zoho",
  "conditions": {"operator": "AND", "conditions": [
    {"field": "vendor_name", "op": "contains", "value": "Google"},
    {"field": "total_amount", "op": "greater_than", "value": 1000}
  ]},
  "action_type": "set_push_to",
  "action_value": "zoho",
  "priority": 0
}
```

### `PUT /api/rules/{id}`
Update rule.

### `DELETE /api/rules/{id}`

### `POST /api/rules/{id}/toggle`
Enable/disable.

### `POST /api/rules/{id}/apply`
Apply a single rule to all pending drafts without push_to.

### `PUT /api/rules/reorder`
```json
{"rule_ids": [3, 1, 2]}
```

### `POST /api/rules/evaluate`
Dry-run: test rules against sample data.

---

## Vendor Mappings

Mandatory before pushing. Maps invoice vendor names (source) to platform vendor names (destination).

### `GET /api/vendor-mappings?search={}&platform={}`
List mappings.

### `POST /api/vendor-mappings`
Create mapping. Both source (invoice vendor) and destination (platform vendor) must exist in DB.
```json
{
  "alias_name": "Google PVP Limited",
  "canonical_name": "Google Private Limited",
  "platform": "zoho",
  "platform_vendor_id": "3699544000000012345"
}
```

### `POST /api/vendor-mappings/bulk`
Create multiple mappings at once. Per-item validation.

### `GET /api/vendor-mappings/source-vendors`
Unique vendor names from invoice drafts with mapping status.
```json
{
  "data": [
    {"vendor_name": "Sarvam", "invoice_count": 3, "sources": ["gmail"], "is_fully_mapped": true, "mappings": [...]}
  ],
  "unmapped": 2
}
```

### `GET /api/vendor-mappings/platform-vendors/{platform}`
Vendors synced from platform (from local DB, no API call).
```json
{
  "data": [
    {"platform_vendor_id": "123", "platform_vendor_name": "Google Pvt Ltd", "is_mapped": false}
  ],
  "last_synced": "2026-04-12 10:00:00"
}
```

### `POST /api/vendor-mappings/platform-vendors/{platform}/sync`
Pull vendors from platform API and sync to local DB. Returns stats.
```json
{"data": {"platform": "zoho", "total_from_api": 7, "new": 2, "updated": 1, "unchanged": 4}}
```

### `POST /api/vendor-mappings/link-vendor`
Link a source vendor to a platform vendor. Both must exist in DB.
```json
{
  "alias_name": "Google PVP Limited",
  "platform": "zoho",
  "platform_vendor_id": "123456",
  "platform_vendor_name": "Google Private Limited"
}
```

### `POST /api/vendor-mappings/create-platform-vendor`
Create vendor on the billing platform + auto-create mapping + resolve pending drafts. Source vendor must exist in invoices.
```json
{
  "vendor_name": "New Vendor Inc",
  "canonical_name": "New Vendor Inc",
  "platform": "zoho"
}
```

### `PUT /api/vendor-mappings/{id}`
### `DELETE /api/vendor-mappings/{id}`

---

## Settings

### `GET /api/settings`
User profile + Gmail credential status.

### `POST /api/settings/gmail-credentials`
Upload Gmail API `credentials.json` file (multipart).

### `DELETE /api/settings/gmail-credentials`
Remove Gmail credentials.

### `GET /api/settings/gmail-authorize`
Start Gmail OAuth flow (redirects to Google).

### `GET /api/settings/gmail-callback`
Gmail OAuth callback (saves token, redirects to settings).

---

## Dashboard

### `GET /api/dashboard/summary`
```json
{
  "data": {
    "total": 42, "pending_review": 10, "pending_vendor": 3,
    "approved": 5, "pushed": 25, "push_failed": 1, "rejected": 1,
    "by_source": {"gmail": 30, "stripe": 10},
    "by_platform": {"zoho": 20, "tally": 3, "unassigned": 17}
  }
}
```

### `GET /api/dashboard/recent-activity`
Last 20 audit log entries with error details.

### `GET /api/dashboard/integration-health`
Health status of all enabled integrations.

---

## Health (Public)

### `GET /health`
```json
{"status": "healthy", "app": "vithana-accounting-platform", "parser_mode": "llm"}
```

### `GET /config`
Non-sensitive app configuration.
