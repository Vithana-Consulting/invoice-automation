from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.repository import AuditLogRepository, InvoiceRepository
from app.db.session import get_db
from app.models.db_models import LegacyAuditLog
from app.services.invoice_service import InvoiceService
from app.tenant.context import TenantContext

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/reparse/{invoice_id}")
def reparse_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Re-parse a single invoice with the current parser mode.

    Updates the invoice record and refreshes the associated draft.
    """
    invoice_repo = InvoiceRepository(db)
    record = invoice_repo.get_by_id(invoice_id)
    if not record:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Re-parse
    invoice_service = InvoiceService(db)
    parsed = invoice_service.parse_invoice(invoice_id)

    if not parsed:
        # Get the error from the record
        record = invoice_repo.get_by_id(invoice_id)
        error = record.validation_errors if record else "Unknown error"
        raise HTTPException(status_code=400, detail=f"Re-parse failed: {error}")

    # Refresh the record
    record = invoice_repo.get_by_id(invoice_id)

    return {
        "status": "success",
        "data": {
            "invoice_id": invoice_id,
            "vendor_name": record.vendor_name,
            "total_amount": float(record.total_amount) if record.total_amount else None,
            "invoice_number": record.invoice_number,
            "parser_mode": record.parser_mode,
        },
    }


@router.post("/reparse-all")
def reparse_all_invoices(limit: int = Query(1000, ge=1, le=5000), db: Session = Depends(get_db)):
    """Re-parse all invoices with the current parser mode. Max 5000 per call."""
    invoice_repo = InvoiceRepository(db)
    all_invoices = invoice_repo.list_all(limit=limit)

    invoice_service = InvoiceService(db)
    results = []

    for record in all_invoices:
        try:
            parsed = invoice_service.parse_invoice(record.id)
            refreshed = invoice_repo.get_by_id(record.id)
            results.append({
                "invoice_id": record.id,
                "file_name": record.file_name,
                "success": parsed,
                "vendor_name": refreshed.vendor_name if refreshed else None,
                "total_amount": float(refreshed.total_amount) if refreshed and refreshed.total_amount else None,
                "parser_mode": refreshed.parser_mode if refreshed else None,
            })
        except Exception as e:
            results.append({
                "invoice_id": record.id,
                "file_name": record.file_name,
                "success": False,
                "error": str(e),
            })

    success_count = sum(1 for r in results if r.get("success"))
    return {
        "status": "success",
        "data": {
            "total": len(results),
            "success": success_count,
            "failed": len(results) - success_count,
            "results": results,
        },
    }


@router.get("/preflight")
def run_preflight(db: Session = Depends(get_db)):
    """Run pipeline preflight checks (company config, integrations).

    Call before ingestion to see if the company is ready.
    """
    service = InvoiceService(db)
    result = service.run_preflight()
    status_code = 200 if result["success"] else 400
    return {"status": "success" if result["success"] else "error", "data": result}


@router.get("/status")
def get_ingest_status(db: Session = Depends(get_db)):
    """Return the last ingest run state for the current company.

    state values:
      never_run  — no ingestion has ever been triggered
      running    — started but not yet finished (< 10 min ago)
      stalled    — started but not finished for > 10 min (server may have restarted)
      completed  — finished successfully
      failed     — finished with an error
    """
    company_id = TenantContext.get()

    latest_started = (
        db.query(LegacyAuditLog)
        .filter(LegacyAuditLog.company_id == company_id,
                LegacyAuditLog.entity_type == "ingest",
                LegacyAuditLog.action == "ingest_started")
        .order_by(LegacyAuditLog.created_at.desc())
        .first()
    )

    latest_finished = (
        db.query(LegacyAuditLog)
        .filter(LegacyAuditLog.company_id == company_id,
                LegacyAuditLog.entity_type == "ingest",
                LegacyAuditLog.action.in_(["ingest_completed", "ingest_failed"]))
        .order_by(LegacyAuditLog.created_at.desc())
        .first()
    )

    if not latest_started:
        return {"status": "success", "data": {"state": "never_run"}}

    started_at = latest_started.created_at
    start_details = json.loads(latest_started.details) if latest_started.details else {}

    if not latest_finished or latest_finished.created_at < started_at:
        elapsed = int((datetime.utcnow() - started_at).total_seconds())
        state = "running" if elapsed < 600 else "stalled"
        return {"status": "success", "data": {
            "state": state,
            "started_at": started_at.isoformat(),
            "elapsed_seconds": elapsed,
            "source": start_details.get("source", "gmail"),
        }}

    fin_details = json.loads(latest_finished.details) if latest_finished.details else {}
    state = "completed" if latest_finished.action == "ingest_completed" else "failed"
    return {"status": "success", "data": {
        "state": state,
        "started_at": started_at.isoformat(),
        "completed_at": latest_finished.created_at.isoformat(),
        "source": fin_details.get("source", "gmail"),
        "emails_found": fin_details.get("emails_found", 0),
        "new_emails": fin_details.get("new_emails", 0),
        "invoices_parsed": fin_details.get("invoices_parsed", 0),
        "drafts_created": fin_details.get("drafts_created", 0),
        "error": fin_details.get("error"),
    }}


@router.post("/{source}")
def ingest_from_source(source: str, db: Session = Depends(get_db)):
    """Pull invoices from a configured source platform.

    Pipeline:
      1. Preflight check (company GST/PAN configured?)
      2. Verify source integration is healthy
      3. Pull invoices
      4. Parse each (with validation gates)
      5. Create drafts

    Supported: gmail, stripe, chargebee.
    """
    from app.platforms.base import get_source_platform
    from app.services.pipeline import preflight_check

    # ─── Gate 1: Preflight check ───────────────────────────────
    preflight = preflight_check(db)
    if not preflight.success:
        errors = "; ".join(e["message"] for e in preflight.errors)
        raise HTTPException(
            status_code=400,
            detail=f"Cannot ingest: {errors}",
        )

    # ─── Gate 2: Source platform health ────────────────────────
    try:
        platform = get_source_platform(db, source)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    health = platform.test_connection()
    if not health.get("healthy"):
        raise HTTPException(
            status_code=400,
            detail=f"{source} integration not healthy: {health.get('message', 'Unknown error')}. "
            "Check Settings → Gmail API or Integrations.",
        )

    # ─── Gate 3: Ingest ────────────────────────────────────────
    audit = AuditLogRepository(db)
    audit.log(entity_type="ingest", entity_id=0, action="ingest_started", details={"source": source})

    try:
        stats = platform.fetch_invoices(db)
        audit.log(entity_type="ingest", entity_id=0, action="ingest_completed",
                  details={"source": source, **{k: v for k, v in stats.items() if k != "pipeline_warnings"}})

        # Add preflight warnings to response
        if preflight.warnings:
            stats["pipeline_warnings"] = preflight.warnings

        return {"status": "success", "data": stats}
    except Exception as e:
        logger.error("Ingestion from %s failed: %s", source, e)
        audit.log(entity_type="ingest", entity_id=0, action="ingest_failed",
                  details={"source": source, "error": str(e)}, status="error")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {type(e).__name__}")


# NOTE: the former POST /api/ingest/upload/file endpoint was removed. Ad-hoc
# manual uploads now go through /api/adhoc/* (app/api/adhoc_routes.py), which
# parse into a separate table without touching invoices/invoice_drafts and
# without holding a DB connection across the LLM parse.
