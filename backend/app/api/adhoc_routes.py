"""Ad-hoc invoice upload API — parse one-off uploads into their own table.

Deliberately decoupled from the Gmail pipeline: these never create
invoices/invoice_drafts and never show on the Invoices page. Flow:
  upload (multipart) → parse in-memory → persist to adhoc_invoice_uploads → Excel.

Critical: the parse route does NOT use Depends(get_db)/get_current_user, because
those hold a pooled DB connection for the whole request. A multi-second GPT-4o
parse holding a connection drains the small pool and starves every other API.
Here we only open SHORT-lived sessions (auth/buyer-hint, then persist) and hold
NO connection across the LLM parse.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from io import BytesIO
from typing import Optional

import jwt
from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config import settings
from app.db.repository import AdhocUploadRepository
from app.db.session import db_session, get_db
from app.models.db_models import AdhocInvoiceUpload, Company, User
from app.parsers import get_parser
from app.tenant.context import TenantContext

logger = logging.getLogger(__name__)
router = APIRouter()

# doc/docx are converted to PDF before parsing (convert-then-parse, see parsers).
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "tiff", "tif", "bmp", "doc", "docx"}


def _require_user_id(access_token: Optional[str]) -> int:
    """Validate the JWT cookie WITHOUT a DB hit. Returns user_id or raises 401."""
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(access_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        uid = payload.get("sub")
        if uid is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return int(uid)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def _serialize(rec: AdhocInvoiceUpload) -> dict:
    def num(v):
        return float(v) if v is not None else None
    return {
        "id": rec.id,
        "file_name": rec.file_name,
        "invoice_number": rec.invoice_number,
        "vendor_name": rec.vendor_name,
        "invoice_date": rec.invoice_date,
        "due_date": rec.due_date,
        "subtotal": num(rec.subtotal),
        "tax_amount": num(rec.tax_amount),
        "total_amount": num(rec.total_amount),
        "currency": rec.currency,
        "gst_number": rec.gst_number,
        "pan_number": rec.pan_number,
        "place_of_supply": rec.place_of_supply,
        "parse_status": rec.parse_status,
        "error_message": rec.error_message,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


@router.post("/parse")
async def parse_adhoc_upload(
    file: UploadFile = File(...),
    access_token: Optional[str] = Cookie(None),
):
    """Upload one invoice file, parse it, and store the result in its own table.

    Returns the persisted row. Never creates invoices/invoice_drafts.
    """
    # ── Auth (no DB connection) ────────────────────────────────────────────
    user_id = _require_user_id(access_token)
    company_id = TenantContext.get_optional()
    if company_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # ── Validate + persist the raw file to disk ────────────────────────────
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file.filename or "upload")
    adhoc_dir = os.path.join(settings.ATTACHMENT_DIR, "adhoc")
    os.makedirs(adhoc_dir, exist_ok=True)
    file_path = os.path.join(adhoc_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_name}")

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    content_hash = hashlib.sha256(content).hexdigest()

    # ── Short session: auth-user email, buyer hint, dedup ──────────────────
    uploaded_by_email = None
    buyer_hint = None
    with db_session() as db:
        user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
        if not user:
            _safe_remove(file_path)
            raise HTTPException(status_code=401, detail="User not found or inactive")
        uploaded_by_email = user.email

        company = db.query(Company).filter(Company.id == company_id).first()
        if company and (company.legal_name or company.gst_number or company.pan_number):
            buyer_hint = {
                "legal_name": company.legal_name or company.name,
                "gst_number": company.gst_number,
                "pan_number": company.pan_number,
            }

        existing = AdhocUploadRepository(db).get_by_content_hash(content_hash)
        if existing:
            _safe_remove(file_path)  # identical file already stored
            return {"status": "success", "message": "Duplicate file — already uploaded",
                    "data": {**_serialize(existing), "duplicate": True}}
    # connection released here — NONE held across the parse below

    # ── Parse (NO DB connection held) ──────────────────────────────────────
    parsed = None
    parse_status = "PARSED"
    error_message = None
    try:
        parsed = get_parser().parse(file_path, ext, buyer_hint=buyer_hint)
    except Exception as e:
        parse_status = "FAILED"
        error_message = str(e)[:1000]
        logger.warning("Ad-hoc parse failed for %s: %s", safe_name, e)

    # ── Persist (fresh short session) ──────────────────────────────────────
    rec = AdhocInvoiceUpload(
        uploaded_by_email=uploaded_by_email,
        file_name=file.filename or safe_name,
        file_path=file_path,
        file_type=ext,
        content_hash=content_hash,
        parser_mode=settings.PARSER_MODE,
        parse_status=parse_status,
        error_message=error_message,
    )
    if parsed is not None:
        rec.invoice_number = parsed.invoice_number
        rec.vendor_name = parsed.vendor_name
        rec.invoice_date = parsed.date
        rec.due_date = parsed.due_date
        rec.subtotal = parsed.subtotal
        rec.tax_amount = parsed.tax_amount
        rec.total_amount = parsed.total_amount
        rec.currency = parsed.currency or "INR"
        rec.gst_number = parsed.gst_number
        rec.pan_number = parsed.pan_number
        rec.place_of_supply = getattr(parsed, "place_of_supply", None)
        rec.line_items_json = json.dumps([li.model_dump() for li in parsed.line_items]) if parsed.line_items else None
        rec.tax_breakup_json = json.dumps(parsed.tax_breakup.model_dump()) if parsed.tax_breakup else None
        rec.bank_details_json = json.dumps(parsed.bank_details.model_dump()) if parsed.bank_details else None
        try:
            rec.raw_json = json.dumps(parsed.model_dump())
        except Exception:
            rec.raw_json = None

    with db_session() as db:
        repo = AdhocUploadRepository(db)
        try:
            rec = repo.create(rec)
        except IntegrityError:
            # Race on the per-tenant content_hash unique — return the winner.
            db.rollback()
            existing = repo.get_by_content_hash(content_hash)
            if existing:
                _safe_remove(file_path)
                return {"status": "success", "message": "Duplicate file — already uploaded",
                        "data": {**_serialize(existing), "duplicate": True}}
            raise
        row = _serialize(rec)

    return {"status": "success" if parse_status == "PARSED" else "error",
            "data": {**row, "duplicate": False, "parsed": parse_status == "PARSED"}}


@router.get("")
def list_adhoc_uploads(
    limit: int = Query(500, ge=1, le=5000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List this company's ad-hoc uploads, newest first."""
    rows = AdhocUploadRepository(db).list_all(limit=limit)
    return {"status": "success", "data": [_serialize(r) for r in rows], "total": len(rows)}


@router.get("/export")
def export_adhoc_uploads(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export all ad-hoc uploads as an Excel file (one row per upload)."""
    rows = AdhocUploadRepository(db).list_all(limit=5000)

    wb = Workbook()
    ws = wb.active
    ws.title = "Ad-hoc Invoices"
    ws.append([
        "File", "Invoice #", "Vendor", "Invoice Date", "Due Date",
        "Subtotal", "Tax", "Total", "Currency", "Vendor GSTIN", "Vendor PAN",
        "Place of Supply", "Status", "Uploaded At",
    ])
    for r in rows:
        ws.append([
            r.file_name or "",
            r.invoice_number or "",
            r.vendor_name or "",
            r.invoice_date or "",
            r.due_date or "",
            float(r.subtotal) if r.subtotal is not None else "",
            float(r.tax_amount) if r.tax_amount is not None else "",
            float(r.total_amount) if r.total_amount is not None else "",
            r.currency or "",
            r.gst_number or "",
            r.pan_number or "",
            r.place_of_supply or "",
            r.parse_status or "",
            r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=adhoc_invoices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"},
    )


@router.delete("/{upload_id}")
def delete_adhoc_upload(
    upload_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete one ad-hoc upload row (tenant-scoped)."""
    ok = AdhocUploadRepository(db).delete(upload_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Upload not found")
    return {"status": "success"}


def _safe_remove(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
