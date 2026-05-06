from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_optional_user
from app.db.repository import AuditLogRepository, DraftRepository, InvoiceRepository, RuleRepository
from app.db.session import get_db
from app.models.db_models import User
from app.services.draft_service import DraftService  # noqa: F401 — also used in reparse_draft

logger = logging.getLogger(__name__)
router = APIRouter()


VALID_STATUSES = {"PENDING_REVIEW", "PENDING_VENDOR", "APPROVED", "PUSHED", "PUSH_FAILED", "REJECTED"}
VALID_PLATFORMS = {"zoho", "tally", "quickbooks"}
VALID_SOURCES = {"gmail", "stripe", "chargebee", "manual_upload"}

VALID_OVERRIDE_REASON_CODES = {
    "AMOUNT_VERIFIED_MANUALLY",
    "DUPLICATE_CONFIRMED_DIFFERENT",
    "GSTIN_CONFIRMED_VALID",
    "RCM_CONFIRMED_NOT_APPLICABLE",
    "ITC_CUTOFF_CONFIRMED_WITHIN_LIMIT",
    "GST_ROUTING_CONFIGURED_SEPARATELY",
    "OTHER",
}


@router.get("")
def list_drafts(
    status: str = Query(None, description="Filter by status", enum=list(VALID_STATUSES)),
    push_to: str = Query(None, description="Filter by platform", enum=list(VALID_PLATFORMS)),
    source: str = Query(None, description="Filter by source", enum=list(VALID_SOURCES)),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List invoice drafts with optional filters."""
    repo = DraftRepository(db)
    drafts = repo.list_all(status=status, push_to=push_to, source=source, limit=limit, offset=offset) # AI_TECH_EXPLAIN : it has ui pagination support right? verify with frontend code
    total = repo.count(status=status, push_to=push_to, source=source)

    return {
        "status": "success",
        "data": [_draft_to_dict(d) for d in drafts],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/export")
def export_drafts(
    status: str = Query(None),
    push_to: str = Query(None),
    source: str = Query(None),
    db: Session = Depends(get_db),
):
    """Export drafts as Excel file."""
    service = DraftService(db)
    output = service.export_to_excel(status=status, push_to=push_to, source=source)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=invoice_drafts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"},
    )


@router.get("/{draft_id}")
def get_draft(draft_id: int, db: Session = Depends(get_db)):
    """Get a single draft by ID."""
    repo = DraftRepository(db)
    draft = repo.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"status": "success", "data": _draft_to_dict(draft)}


@router.put("/{draft_id}")
def update_draft(draft_id: int, body: dict, db: Session = Depends(get_db)):
    """Update draft fields (vendor_name, amount, push_to, etc.)."""
    repo = DraftRepository(db)
    allowed_fields = {
        "vendor_name", "resolved_vendor_name", "invoice_number",
        "invoice_date", "due_date", "total_amount", "tax_amount",
        "currency", "push_to",
    }
    updates = {k: v for k, v in body.items() if k in allowed_fields}
    draft = repo.update(draft_id, **updates)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"status": "success", "data": _draft_to_dict(draft)}


@router.post("/{draft_id}/reparse")
def reparse_draft(draft_id: int, db: Session = Depends(get_db)):
    """Re-run LLM extraction on the source invoice and refresh the draft with new data.

    Useful when extraction produced wrong line items or amounts.
    Clears validation_errors so the next push re-runs the validation pipeline fresh.
    Draft status is preserved (stays APPROVED / PUSH_FAILED so user can push immediately after).
    If the local file is missing and the invoice came from Gmail, re-downloads it first.
    """
    import os
    from app.services.invoice_service import InvoiceService

    repo = DraftRepository(db)
    draft = repo.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    # If the PDF is missing from disk, try to recover it from Gmail before reparsing
    invoice = InvoiceRepository(db).get_by_id(draft.invoice_id)
    if invoice and invoice.file_path and not os.path.exists(invoice.file_path):
        if invoice.source == "gmail":
            from app.services.email_service import redownload_invoice_from_gmail
            recovered = redownload_invoice_from_gmail(invoice, db)
            if not recovered:
                raise HTTPException(
                    status_code=422,
                    detail="Invoice file not on disk and Gmail re-download failed. Check that the Gmail integration is connected and the original email is not deleted.",
                )
            logger.info("Reparse: recovered PDF from Gmail for invoice %d", invoice.id)
        else:
            raise HTTPException(
                status_code=422,
                detail="Invoice file not found on disk. Re-upload the original PDF to reparse.",
            )

    # Re-parse the source invoice
    invoice_service = InvoiceService(db)
    parsed = invoice_service.parse_invoice(draft.invoice_id)
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail="Reparse failed — check that the invoice file is accessible and the LLM is configured.",
        )

    # Sync fresh data back into the draft
    service = DraftService(db)
    updated = service.refresh_draft_from_invoice(draft_id)
    if not updated:
        raise HTTPException(status_code=400, detail="Invoice reparsed but draft refresh failed.")

    return {"status": "success", "data": _draft_to_dict(updated)}


@router.post("/{draft_id}/approve")
def approve_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Approve a draft for pushing."""
    service = DraftService(db)
    draft = service.approve_draft(draft_id, user_id=user.id if user else None)
    if not draft:
        raise HTTPException(status_code=400, detail="Draft not found or not in PENDING_REVIEW status")
    return {"status": "success", "data": _draft_to_dict(draft)}


@router.post("/{draft_id}/reject")
def reject_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Reject a draft."""
    service = DraftService(db)
    draft = service.reject_draft(draft_id, user_id=user.id if user else None)
    if not draft:
        raise HTTPException(status_code=400, detail="Draft not found or not in valid status")
    return {"status": "success", "data": _draft_to_dict(draft)}


@router.post("/{draft_id}/push")
def push_draft(
    draft_id: int,
    body: dict = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Push an approved draft to the designated billing platform.

    Credentials are loaded from the integrations table (configured via UI).
    Runs pre-push validation before pushing. Blocking issues return HTTP 422
    unless override_reason_code + override_reason are supplied in the request body.
    """
    import json as _json
    from app.services.validation.validators import build_pre_push_pipeline
    from app.db.repository import VendorMappingRepository, ComplianceAuditLogRepository

    repo = DraftRepository(db)
    draft = repo.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status not in ("APPROVED", "PUSH_FAILED"):
        raise HTTPException(status_code=400, detail="Draft must be APPROVED or PUSH_FAILED before pushing")
    if not draft.push_to:
        raise HTTPException(status_code=400, detail="No target platform set (push_to is empty)")

    # Block push if no vendor mapping exists
    mapping_repo = VendorMappingRepository(db)
    vendor_mapping = mapping_repo.get_by_alias(draft.vendor_name or "", platform=draft.push_to)
    if not vendor_mapping:
        repo.update(draft_id, status="PENDING_VENDOR", push_error=f"No vendor mapping for '{draft.vendor_name}' on {draft.push_to}")
        raise HTTPException(
            status_code=400,
            detail=f"No vendor mapping for '{draft.vendor_name}' on {draft.push_to}. Map the vendor first.",
        )

    # Update resolved vendor name from mapping before pushing
    if vendor_mapping.canonical_name:
        repo.update(draft_id, resolved_vendor_name=vendor_mapping.canonical_name)
        draft = repo.get_by_id(draft_id)  # refresh after update

    # ─── Pre-push validation ───────────────────────────────────────────────
    pipeline = build_pre_push_pipeline()
    results = pipeline.run(draft, draft.invoice, db)
    blocking = pipeline.blocking(results)
    non_overridable = pipeline.non_overridable_blocks(results)

    # Persist validation results on the draft (include detail + non_overridable for UI)
    # Use float() for Decimal values so json.dumps doesn't choke
    def _serialize_detail(d: dict) -> dict:
        from decimal import Decimal as _Decimal
        return {k: float(v) if isinstance(v, _Decimal) else v for k, v in (d or {}).items()}

    all_results_json = _json.dumps([
        {
            "code": r.code,
            "passed": r.passed,
            "severity": r.severity,
            "message": r.message,
            "detail": _serialize_detail(r.detail),
            "non_overridable": r.non_overridable,
        }
        for r in results
    ])
    repo.update(draft_id, validation_errors=all_results_json)

    if blocking:
        override_code = (body or {}).get("override_reason_code", "")
        override_reason = (body or {}).get("override_reason", "")

        # Validate override_reason_code is a known, allowlisted value
        if override_code and override_code not in VALID_OVERRIDE_REASON_CODES:
            raise HTTPException(status_code=400, detail="Invalid override_reason_code")

        # Non-overridable blocks (e.g. CompositionVendorValidator) — cannot be bypassed
        if non_overridable:
            raise HTTPException(status_code=422, detail={
                "error": "NON_OVERRIDABLE_BLOCK",
                "blocks": [{"code": r.code, "message": r.message, "detail": r.detail} for r in non_overridable],
                "hint": "These compliance blocks cannot be overridden. Resolve the underlying issue first.",
            })

        if not override_code:
            raise HTTPException(status_code=422, detail={
                "error": "VALIDATION_BLOCKED",
                "blocks": [{"code": r.code, "message": r.message, "detail": r.detail} for r in blocking],
                "hint": "To override, resubmit with override_reason_code and override_reason. "
                        "Requires admin or owner role.",
            })

        # Only admin or owner can override compliance blocks
        if not _user_can_override(user, db):
            raise HTTPException(status_code=403, detail={
                "error": "OVERRIDE_NOT_PERMITTED",
                "hint": "Only users with admin or owner role can override compliance validation blocks.",
            })

        # Resolve actor identity for the immutable audit trail
        actor_role = _get_user_role(user, db) if user else None

        # Log the override — immutable compliance record
        audit_repo = ComplianceAuditLogRepository(db)
        audit_repo.log(
            entity_type="invoice_draft",
            entity_id=draft_id,
            action="push_override",
            actor_id=user.id if user else None,
            actor_email=user.email if user else None,
            actor_name=user.name if user else None,
            actor_role=actor_role,
            override_reason_code=override_code,
            override_reason=override_reason,
            metadata={"blocked_by": [r.code for r in blocking]},
        )
        db.commit()

    # FIX 3: capture the vendor name as it was on the draft before push (for mutation detection)
    pre_push_vendor_name = draft.resolved_vendor_name

    try:
        logger.info("[PIPELINE] Stage 1/4 — Push draft %d to %s", draft_id, draft.push_to)
        result = _push_draft_to_platform(draft, db)
        external_bill_id = result.get("external_id", "")
        push_to = draft.push_to
        invoice_id = draft.invoice_id
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[PIPELINE] Stage 1 FAILED for draft %d: %s", draft_id, e)
        repo.update(draft_id, status="PUSH_FAILED", push_error=str(e))
        AuditLogRepository(db).log(
            entity_type="draft", entity_id=draft_id, action="pushed",
            details={"platform": draft.push_to, "invoice_id": draft.invoice_id, "error": str(e)},
            status="failure", error=str(e),
        )
        db.commit()
        raise HTTPException(status_code=500, detail="Push failed. Check the draft's error field for details.")

    # Stage 2: commit push result to DB
    logger.info("[PIPELINE] Stage 2/4 — Commit push result (bill_id=%s)", external_bill_id)
    repo.update(draft_id, status="PUSHED", external_bill_id=external_bill_id,
                push_error=None, pushed_at=datetime.utcnow())
    InvoiceRepository(db)._update(invoice_id, zoho_push_status="PUSHED", zoho_bill_id=external_bill_id)
    AuditLogRepository(db).log(
        entity_type="draft", entity_id=draft_id, action="pushed",
        details={"external_bill_id": external_bill_id, "platform": push_to, "invoice_id": invoice_id},
        status="success",
    )
    if pre_push_vendor_name and vendor_mapping.canonical_name and pre_push_vendor_name != vendor_mapping.canonical_name:
        AuditLogRepository(db).log(
            entity_type="draft", entity_id=draft_id, action="vendor_name_changed",
            details={"old_resolved_vendor_name": pre_push_vendor_name, "new_resolved_vendor_name": vendor_mapping.canonical_name},
            status="info",
        )
    db.commit()

    # Stages 3 + 4: attach PDF then clean up local file
    pipeline = _run_post_push_pipeline(draft, external_bill_id, push_to, db)

    return {
        "status": "success",
        "data": {
            "draft_id": draft_id,
            "external_bill_id": external_bill_id,
            "platform": push_to,
            "pipeline": pipeline,
        },
    }


def _run_post_push_pipeline(draft, bill_id: str, platform: str, db) -> dict:
    """Stage 3 + 4: attach PDF to the bill, then delete the local file.

    Sequential — cleanup only runs after attachment confirms.
    Returns a status dict so the API response includes pipeline results.
    """
    import os
    from app.db.repository import InvoiceRepository

    result = {"attach": "skipped", "cleanup": "skipped", "file": None}

    if platform != "zoho" or not bill_id:
        return result

    # Resolve absolute file path (stored path may be relative to backend root)
    invoice = InvoiceRepository(db).get_by_id(draft.invoice_id)
    if not invoice or not invoice.file_path:
        result["attach"] = "skipped — no file_path on invoice record"
        return result

    file_path = invoice.file_path
    if not os.path.isabs(file_path):
        from app.config import settings
        # Resolve relative to the project root (parent of data/)
        file_path = os.path.abspath(file_path)

    result["file"] = file_path

    if not os.path.exists(file_path):
        logger.info("[PIPELINE] Stage 3/4 — PDF not on disk, attempting Gmail re-download: %s", file_path)
        from app.services.email_service import redownload_invoice_from_gmail
        recovered = redownload_invoice_from_gmail(invoice, db)
        if recovered:
            file_path = recovered
            result["file"] = file_path
        else:
            result["attach"] = "skipped — file not on disk and Gmail re-download unavailable"
            logger.warning("[PIPELINE] Stage 3/4 — Could not recover PDF, skipping attachment")
            return result

    # Stage 3: attach
    logger.info("[PIPELINE] Stage 3/4 — Attach %s to Zoho bill %s", invoice.file_name, bill_id)
    try:
        from app.platforms.base import get_billing_platform
        zoho = get_billing_platform(db, "zoho")
        zoho.client.attach_document(bill_id, file_path)
        result["attach"] = "ok"
        logger.info("[PIPELINE] Stage 3/4 — Attached successfully")
        DraftRepository(db).update(draft.id, pdf_attached_at=datetime.utcnow())
        db.commit()
    except Exception as exc:
        result["attach"] = f"failed — {exc}"
        logger.warning("[PIPELINE] Stage 3/4 — Attachment failed, keeping local file: %s", exc)
        return result  # do NOT clean up if attachment failed

    # Stage 4: cleanup — only reached when attachment succeeded
    logger.info("[PIPELINE] Stage 4/4 — Cleanup local file: %s", file_path)
    try:
        os.remove(file_path)
        # Remove parent directory if now empty
        parent = os.path.dirname(file_path)
        if parent and os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)
        result["cleanup"] = "ok"
        logger.info("[PIPELINE] Stage 4/4 — Local file deleted")
    except Exception as exc:
        result["cleanup"] = f"failed — {exc}"
        logger.warning("[PIPELINE] Stage 4/4 — Cleanup failed: %s", exc)

    return result


@router.post("/{draft_id}/reattach")
async def reattach_invoice_to_bill(
    draft_id: int,
    db: Session = Depends(get_db),
    file: "UploadFile | None" = None,
):
    """Attach an invoice PDF to an already-pushed Zoho bill.

    For Gmail-sourced invoices: re-downloads the original attachment directly
    from Gmail — no file upload needed.

    For manual-upload invoices: upload the PDF as multipart/form-data.
    """
    import os, tempfile
    from fastapi import UploadFile

    repo = DraftRepository(db)
    draft = repo.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status != "PUSHED":
        raise HTTPException(status_code=400, detail="Draft must be in PUSHED state to reattach")
    if draft.push_to != "zoho":
        raise HTTPException(status_code=400, detail="Reattach is only supported for Zoho bills")
    if not draft.external_bill_id:
        raise HTTPException(status_code=400, detail="No Zoho bill_id on this draft")

    invoice = InvoiceRepository(db).get_by_id(draft.invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice record not found")

    tmp_path = None
    file_used = None

    try:
        from app.platforms.base import get_billing_platform

        if invoice.source == "gmail":
            # Re-download from Gmail — no file upload required
            from app.services.email_service import redownload_invoice_from_gmail
            local_path = invoice.file_path if os.path.exists(invoice.file_path or "") else None
            if not local_path:
                local_path = redownload_invoice_from_gmail(invoice, db)
            if not local_path:
                raise HTTPException(
                    status_code=422,
                    detail="Could not re-download from Gmail. Check that the Gmail integration is connected and the original email is not deleted.",
                )
            file_used = invoice.file_name
            attach_path = local_path
        else:
            # Manual upload source — file must be provided
            if file is None:
                raise HTTPException(status_code=400, detail="This invoice was manually uploaded. Provide the PDF as a file upload.")
            content = await file.read()
            suffix = os.path.splitext(file.filename or "invoice.pdf")[1] or ".pdf"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            file_used = file.filename
            attach_path = tmp_path

        zoho = get_billing_platform(db, "zoho")
        zoho.client.attach_document(draft.external_bill_id, attach_path)
        logger.info("Reattached %s to Zoho bill %s", file_used, draft.external_bill_id)

        AuditLogRepository(db).log(
            entity_type="draft", entity_id=draft_id, action="pdf_reattached",
            details={"bill_id": draft.external_bill_id, "filename": file_used, "source": invoice.source},
            status="success",
        )
        DraftRepository(db).update(draft_id, pdf_attached_at=datetime.utcnow())
        db.commit()

        # Cleanup: delete the local file now that it's safely in Zoho
        try:
            os.remove(attach_path)
            parent = os.path.dirname(attach_path)
            if parent and os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
        except Exception:
            pass

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Attachment failed: {exc}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return {"status": "success", "data": {"bill_id": draft.external_bill_id, "file": file_used, "source": invoice.source}}


@router.post("/bulk-approve")
def bulk_approve_drafts(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Bulk approve multiple drafts."""
    draft_ids = body.get("draft_ids", [])
    if len(draft_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 drafts per bulk operation")
    service = DraftService(db)
    results = service.bulk_approve(draft_ids, user_id=user.id if user else None)
    return {"status": "success", "data": results}


@router.post("/bulk-push")
def bulk_push_drafts(body: dict, db: Session = Depends(get_db)):
    """Bulk push multiple approved drafts.

    Runs pre-push validation on each draft. Drafts with blocking issues are
    skipped (with a warning in results) rather than hard-blocking the whole batch.
    """
    import json as _json
    from app.db.repository import VendorMappingRepository
    from app.services.validation.validators import build_pre_push_pipeline

    draft_ids = body.get("draft_ids", [])
    if len(draft_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 drafts per bulk operation")
    repo = DraftRepository(db)
    mapping_repo = VendorMappingRepository(db)

    # Pre-instantiate one platform instance per platform key so the OAuth token
    # is refreshed once and reused across all drafts — avoids Zoho rate-limiting.
    from app.platforms.base import get_billing_platform
    platform_cache: dict = {}
    pipeline = build_pre_push_pipeline()

    results = []
    for draft_id in draft_ids:
        try:
            draft = repo.get_by_id(draft_id)
            if not draft or draft.status not in ("APPROVED", "PUSH_FAILED"):
                results.append({"draft_id": draft_id, "success": False, "error": "Not approved or failed"})
                continue
            if not draft.push_to:
                results.append({"draft_id": draft_id, "success": False, "error": "No platform set"})
                continue

            # Check vendor mapping
            vendor_mapping = mapping_repo.get_by_alias(draft.vendor_name or "", platform=draft.push_to)
            if not vendor_mapping:
                repo.update(draft_id, status="PENDING_VENDOR",
                            push_error=f"No vendor mapping for '{draft.vendor_name}' on {draft.push_to}")
                results.append({"draft_id": draft_id, "success": False,
                                "error": f"No vendor mapping for '{draft.vendor_name}' on {draft.push_to}"})
                continue

            # Update resolved name
            if vendor_mapping.canonical_name:
                repo.update(draft_id, resolved_vendor_name=vendor_mapping.canonical_name)
                draft = repo.get_by_id(draft_id)  # refresh

            # ── Pre-push validation (bulk: skip blocking drafts, log warnings) ──
            val_results = pipeline.run(draft, draft.invoice, db)
            blocking = pipeline.blocking(val_results)
            from decimal import Decimal as _Decimal
            def _sd(d):
                return {k: float(v) if isinstance(v, _Decimal) else v for k, v in (d or {}).items()}
            all_results_json = _json.dumps([
                {
                    "code": r.code,
                    "passed": r.passed,
                    "severity": r.severity,
                    "message": r.message,
                    "detail": _sd(r.detail),
                    "non_overridable": r.non_overridable,
                }
                for r in val_results
            ])
            repo.update(draft_id, validation_errors=all_results_json)

            if blocking:
                block_codes = [r.code for r in blocking]
                results.append({
                    "draft_id": draft_id,
                    "success": False,
                    "error": f"Blocked by validation: {', '.join(block_codes)}",
                    "validation_blocks": [
                        {"code": r.code, "message": r.message} for r in blocking
                    ],
                })
                continue

            # Reuse cached platform instance (shared token across bulk push)
            if draft.push_to not in platform_cache:
                platform_cache[draft.push_to] = get_billing_platform(db, draft.push_to)
            platform = platform_cache[draft.push_to]

            result = platform.push_bill(draft, db)
            external_id = result.get("external_id", "")
            repo.update(draft_id, status="PUSHED", external_bill_id=external_id, push_error=None, pushed_at=datetime.utcnow())
            db.commit()

            post_pipeline = _run_post_push_pipeline(draft, external_id, draft.push_to, db)
            results.append({"draft_id": draft_id, "success": True, "external_bill_id": external_id, "pipeline": post_pipeline})
        except Exception as e:
            repo.update(draft_id, status="PUSH_FAILED", push_error=str(e))
            results.append({"draft_id": draft_id, "success": False, "error": str(e)})
    return {"status": "success", "data": results}


@router.post("/resolve-vendors")
def resolve_pending_vendors(db: Session = Depends(get_db)):
    """Check all PENDING_VENDOR drafts and auto-approve those with mappings now."""
    service = DraftService(db)
    results = service.resolve_pending_vendors()
    return {
        "status": "success",
        "data": {
            "resolved": len(results),
            "results": results,
        },
    }


@router.post("/apply-rules")
def apply_rules_to_drafts(body: dict = None, db: Session = Depends(get_db)):
    """Apply rules to drafts that don't have a push_to set yet.

    If draft_ids is provided, only apply to those drafts. Otherwise apply to all
    PENDING_REVIEW drafts without a push_to.
    """
    from app.rules.engine import apply_rules

    repo = DraftRepository(db)
    rule_repo = RuleRepository(db)

    active_rules = rule_repo.list_all(active_only=True)
    if not active_rules:
        return {"status": "success", "data": {"matched": 0, "skipped": 0, "message": "No active rules"}}

    rule_dicts = [
        {
            "id": r.id,
            "name": r.name,
            "conditions_json": r.conditions_json,
            "action_type": r.action_type,
            "action_value": r.action_value,
        }
        for r in active_rules
    ]

    # Get target drafts
    draft_ids = (body or {}).get("draft_ids")
    if draft_ids:
        drafts = [repo.get_by_id(did) for did in draft_ids]
        drafts = [d for d in drafts if d]
    else:
        # Batch process in chunks of 50 to avoid loading all pending drafts at once
        BATCH_SIZE = 50
        drafts = []
        offset = 0
        while True:
            batch = repo.list_all(status="PENDING_REVIEW", limit=BATCH_SIZE, offset=offset)
            if not batch:
                break
            drafts.extend(batch)
            if len(batch) < BATCH_SIZE:
                break
            offset += BATCH_SIZE

    matched = 0
    skipped = 0
    results = []

    for draft in drafts:
        if draft.push_to and not draft_ids:
            skipped += 1
            continue

        invoice_fields = {
            "vendor_name": draft.vendor_name or "",
            "resolved_vendor_name": draft.resolved_vendor_name or "",
            "invoice_number": draft.invoice_number or "",
            "total_amount": float(draft.total_amount) if draft.total_amount else 0,
            "tax_amount": float(draft.tax_amount) if draft.tax_amount else 0,
            "currency": draft.currency or "",
            "source": draft.source or "",
            "invoice_date": draft.invoice_date or "",
        }

        rule = apply_rules(rule_dicts, invoice_fields)
        if rule:
            repo.update(draft.id, push_to=rule["action_value"], push_to_rule_id=rule["id"])
            matched += 1
            results.append({
                "draft_id": draft.id,
                "vendor": draft.vendor_name,
                "rule_name": rule["name"],
                "push_to": rule["action_value"],
            })
        else:
            skipped += 1

    return {
        "status": "success",
        "data": {
            "matched": matched,
            "skipped": skipped,
            "results": results,
        },
    }


def _user_can_override(user, db: Session) -> bool:
    """Returns True if the user has admin or owner role in the current tenant."""
    if not user:
        return False
    from app.models.db_models import CompanyMember
    from app.tenant.context import TenantContext
    company_id = TenantContext.get()
    if not company_id:
        return False
    membership = (
        db.query(CompanyMember)
        .filter(
            CompanyMember.user_id == user.id,
            CompanyMember.company_id == company_id,
            CompanyMember.is_active == True,
        )
        .first()
    )
    return membership is not None and membership.role in ("owner", "admin")


def _get_user_role(user, db: Session) -> str:
    """Returns the user's role in the current tenant, or 'unknown'."""
    if not user:
        return "unknown"
    from app.models.db_models import CompanyMember
    from app.tenant.context import TenantContext
    company_id = TenantContext.get()
    if not company_id:
        return "unknown"
    membership = (
        db.query(CompanyMember)
        .filter(
            CompanyMember.user_id == user.id,
            CompanyMember.company_id == company_id,
            CompanyMember.is_active == True,
        )
        .first()
    )
    return membership.role if membership else "unknown"


def _push_draft_to_platform(draft, db: Session) -> dict:
    """Push a draft to its designated billing platform using DB-stored credentials.

    Uses the platform registry - supports Zoho, Tally, QuickBooks out of the box.
    """
    from app.platforms.base import get_billing_platform

    platform = get_billing_platform(db, draft.push_to)
    return platform.push_bill(draft, db)


def _draft_to_dict(draft) -> dict:
    return {
        "id": draft.id,
        "invoice_id": draft.invoice_id,
        "vendor_name": draft.vendor_name,
        "resolved_vendor_name": draft.resolved_vendor_name,
        "invoice_number": draft.invoice_number,
        "invoice_date": draft.invoice_date,
        "due_date": draft.due_date,
        "total_amount": float(draft.total_amount) if draft.total_amount else None,
        "tax_amount": float(draft.tax_amount) if draft.tax_amount else None,
        "currency": draft.currency,
        "line_items": json.loads(draft.line_items_json) if draft.line_items_json else [],
        "source": draft.source,
        "push_to": draft.push_to,
        "push_to_rule_id": draft.push_to_rule_id,
        "status": draft.status,
        "reviewed_by": draft.reviewed_by,
        "reviewed_at": str(draft.reviewed_at) if draft.reviewed_at else None,
        "push_error": draft.push_error,
        "pushed_at": str(draft.pushed_at) if draft.pushed_at else None,
        "external_bill_id": draft.external_bill_id,
        "validation_warnings": json.loads(draft.validation_warnings) if draft.validation_warnings else [],
        "validation_errors": json.loads(draft.validation_errors) if draft.validation_errors else [],
        "tax_breakup": json.loads(draft.tax_breakup_json) if draft.tax_breakup_json else None,
        "invoice_type": draft.invoice_type,
        "account_id": draft.account_id,
        "account_name": draft.account.name if draft.account else None,
        "itc_status": draft.itc_status,
        "tds_applicable": draft.tds_applicable,
        "place_of_supply": draft.place_of_supply,
        "pdf_attached_at": str(draft.pdf_attached_at) if draft.pdf_attached_at else None,
        "created_at": str(draft.created_at) if draft.created_at else None,
        "updated_at": str(draft.updated_at) if draft.updated_at else None,
    }
