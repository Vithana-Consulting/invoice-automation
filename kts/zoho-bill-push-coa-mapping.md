# KT: Pushing a Bill to Zoho — GL/COA Mapping Flow

## What is "pushing a bill"?

When an invoice is parsed (from Gmail / PDF / manual upload), it creates an `InvoiceDraft`. "Pushing" means creating a **Vendor Bill in Zoho Books** from that draft.

Zoho requires 4 things on every bill:

1. A **vendor** (who sent the invoice)
2. **Line items** (what was purchased)
3. An **expense account** per line item (which GL/COA account to debit)
4. A **tax** per line item (GST rate to apply)

---

## The Full Push Flow

```
Invoice Draft
     │
     ▼
1. Vendor Mapping Check
     │  Is there a VendorMapping for this vendor on Zoho?
     │  └─ Yes → use platform_vendor_id (Zoho contact ID)
     │  └─ No  → search Zoho by vendor name
     │            → fail if not found (block push)
     │
     ▼
2. COA/GL Resolution  (per line item)
     │
     │  For each line item in the invoice:
     │  ┌─────────────────────────────────────────────────┐
     │  │ Does the line item have an HSN/SAC code?        │
     │  │  Yes → look up chart_of_accounts.hsn_codes      │
     │  │         → use that account's platform_account_id│
     │  │  No  → fall back to draft.account_id            │
     │  │         (the GL attached manually in the UI)    │
     │  │  Still none → use default_account_id from       │
     │  │               Zoho integration config           │
     │  └─────────────────────────────────────────────────┘
     │
     ▼
3. Tax Selection
     │  Try intra-state GST (tax_id = GST18, CGST+SGST)
     │       Zoho says "IGST has to be applied"?
     │       └─ Auto-retry with igst_tax_id (IGST18)
     │
     ▼
4. Zoho Bills API
     └─ Success → external_bill_id saved, status = PUSHED
     └─ Duplicate → find existing bill by number, mark PUSHED
     └─ Failure  → status = PUSH_FAILED, push_error logged
```

---

## The COA/GL Setup

The **Chart of Accounts** (`chart_of_accounts` table) is a sync of your Zoho Books accounts. Each entry has:

| Field | Description |
|---|---|
| `name` | e.g. "Consultant Expense" |
| `sub_type` | `PURCHASE` = expense account, `SALE` = income account |
| `platform_account_id` | The Zoho account ID sent in the API payload |
| `hsn_codes` | JSON array of HSN/SAC codes tagged to this account |

### How to set up COA mappings

1. Go to **Chart of Accounts** in the UI
2. Sync accounts from Zoho (Sync button)
3. For each relevant expense account, tag the HSN/SAC codes that apply to it

Example mappings:

| Account | HSN/SAC codes |
|---|---|
| Consultant Expense | `998313` (management consulting) |
| IT and Internet Expenses | `998314`, `998316` |
| Bank Fees and Charges | `998222` |
| Automobile Expense | `998314` |

When an invoice is pushed, the system reads each line item's `hsn_or_sac` field, finds the matching COA entry, and puts that account's Zoho ID into the bill line item as `account_id`.

### Critical constraint

Zoho only accepts **expense-type accounts** on bill line items. The following account types are **rejected**:

- Accounts Receivable
- Accounts Payable
- Bank / Cash accounts
- Tax accounts (CGST payable, etc.)

If you tag an HSN code on any of these, Zoho returns `"Involved account types are not applicable"`.

---

## The Tax ID Setup

Zoho India (GST) requires every bill line item to declare its tax. Two IDs live in the Zoho integration config:

| Config key | Tax name | Rate | When used |
|---|---|---|---|
| `tax_id` | GST18 | 18% (auto-splits CGST 9% + SGST 9%) | Intra-state vendor |
| `igst_tax_id` | IGST18 | 18% (single IGST) | Inter-state vendor |

Zoho knows the vendor's registered state and the org's state. The system tries intra-state GST first. If Zoho rejects with `"IGST has to be applied"`, the push is automatically retried with the IGST tax ID.

### Where to get these IDs

1. Log in to Zoho Books
2. Go to **Settings → Taxes**
3. Copy the tax ID for `GST18` (intra-state) and `IGST18` (inter-state)
4. Paste them in **Integrations → Zoho Books → GST Tax ID fields**

---

## What Can Go Wrong

| Error | Root cause | Fix |
|---|---|---|
| `Involved account types are not applicable` | HSN tagged on AR / AP / bank account | Re-tag the HSN to an expense account in COA UI |
| `Specify either a Tax or Tax Exemption` | `tax_id` not configured in integration | Set GST Tax ID in Integrations → Zoho Books |
| `IGST has to be applied` | Using intra-state tax for an inter-state vendor | Auto-retried with `igst_tax_id` — ensure it is set |
| `IGST cannot be applied` | Using IGST for an intra-state vendor | Auto-retried with `tax_id` |
| `No vendor mapping for X` | Vendor not linked to a Zoho contact | Vendor Mappings → create mapping for this vendor |
| `No Chart of Accounts mapping` | No HSN tagged, no draft account, no default | Tag the HSN in COA UI, or set Default Account ID in integration config |
| `A bill with this number already exists` | Previous failed push partially created the bill | Auto-handled: system looks up existing bill ID and marks PUSHED |

---

## Setup Checklist (minimum to push a bill)

```
Integrations → Zoho Books
  ✓ Client ID, Client Secret set
  ✓ Organization ID set
  ✓ Refresh token obtained (via OAuth Authorise button)
  ✓ GST Tax ID (intra-state)   ← Zoho → Settings → Taxes → GST18
  ✓ IGST Tax ID (inter-state)  ← Zoho → Settings → Taxes → IGST18

Chart of Accounts
  ✓ Accounts synced from Zoho
  ✓ Expense accounts tagged with relevant HSN/SAC codes
  ✓ No HSN codes sitting on AR / AP / bank accounts

Vendor Mappings
  ✓ Each vendor alias mapped to a Zoho vendor (with platform_vendor_id)
  ✓ Vendor created in Zoho with correct GST number and GST treatment
```

Once all three are in place, every invoice with HSN codes on its line items will push to Zoho with the correct expense account and tax — no manual intervention needed.

---

## Code References

| File | What it does |
|---|---|
| `app/platforms/zoho/service.py` — `push_bill()` | Orchestrates the full push: vendor lookup → COA resolve → tax select → API call |
| `app/platforms/account_resolver.py` — `resolve_accounts_for_platform()` | Builds the HSN → Zoho account ID map from COA |
| `app/platforms/zoho/mappers.py` — `invoice_to_zoho_bill()` | Assembles the final Zoho bill payload with per-line-item account IDs |
| `app/platforms/zoho/client.py` — `create_bill()` | Sends the bill to Zoho Books API |
| `app/db/repository.py` — `ChartOfAccountRepository.get_by_hsn()` | Looks up COA entry by HSN/SAC code |
