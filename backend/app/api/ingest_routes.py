from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.db.repository import InvoiceRepository
from app.db.session import get_db
from app.models.db_models import InvoiceRecord
from app.services.draft_service import DraftService
from app.services.drive_upload import try_drive_upload
from app.services.invoice_service import InvoiceService

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
    try:
        stats = platform.fetch_invoices(db)

        # Add preflight warnings to response
        if preflight.warnings:
            stats["pipeline_warnings"] = preflight.warnings

        return {"status": "success", "data": stats}
    except Exception as e:
        logger.error("Ingestion from %s failed: %s", source, e)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {type(e).__name__}")


ALLOWED_UPLOAD_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/tiff", "image/bmp"}
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "tiff", "tif", "bmp"}


@router.post("/upload/file")
async def ingest_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a file directly, parse it, and create a draft."""
    # Validate file type
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', file.filename or 'upload')
    os.makedirs(settings.ATTACHMENT_DIR, exist_ok=True)
    file_path = os.path.join(
        settings.ATTACHMENT_DIR,
        f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}",
    )

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    content_hash = hashlib.sha256(content).hexdigest()

    invoice_repo = InvoiceRepository(db)
    existing = invoice_repo.get_by_content_hash(content_hash)
    if existing:
        return {
            "status": "success",
            "message": "Duplicate file detected",
            "data": {"invoice_id": existing.id, "duplicate": True},
        }

    ext = os.path.splitext(file.filename)[1].lower().lstrip(".")
    invoice_record = InvoiceRecord(
        file_path=file_path,
        file_name=file.filename,
        file_type=ext,
        content_hash=content_hash,
        parsing_status="PENDING",
        source="manual_upload",
    )
    invoice_record = invoice_repo.create(invoice_record)

    drive_file_id = try_drive_upload(file_path, invoice_record, db)
    if drive_file_id:
        invoice_repo._update(invoice_record.id, drive_file_id=drive_file_id)

    invoice_service = InvoiceService(db)
    parsed = invoice_service.parse_invoice(invoice_record.id)

    draft = None
    if parsed:
        draft_service = DraftService(db)
        draft = draft_service.create_draft_from_invoice(invoice_record.id, source="manual_upload")

    return {
        "status": "success",
        "data": {
            "invoice_id": invoice_record.id,
            "parsed": parsed,
            "draft_id": draft.id if draft else None,
        },
    }
