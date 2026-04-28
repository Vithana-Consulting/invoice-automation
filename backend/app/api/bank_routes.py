"""Bank Details API — list and export banking info extracted from invoices."""
from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.repository import InvoiceRepository
from app.db.session import get_db
from app.models.db_models import InvoiceRecord, User
from app.tenant.context import TenantContext

router = APIRouter()


@router.get("")
def list_bank_details(
    limit: int = Query(500, ge=1, le=5000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all unique bank details extracted from parsed invoices."""
    company_id = TenantContext.get_optional()
    invoices = (
        db.query(InvoiceRecord)
        .filter(
            InvoiceRecord.company_id == company_id,
            InvoiceRecord.bank_details_json.isnot(None),
            InvoiceRecord.parsing_status.in_(["PARSED", "WARNING"]),
        )
        .order_by(InvoiceRecord.created_at.desc())
        .limit(limit)
        .all()
    ) # AI_RECOMMENDATION : does it fetches the invoice in a single query or batch fetches it?

    results = []
    for inv in invoices:
        try:
            bd = json.loads(inv.bank_details_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not any(bd.values()):
            continue
        results.append({
            "invoice_id": inv.id,
            "invoice_number": inv.invoice_number,
            "vendor_name": inv.vendor_name,
            "invoice_date": inv.invoice_date,
            "bank_name": bd.get("bank_name"),
            "account_number": bd.get("account_number"),
            "ifsc_code": bd.get("ifsc_code"),
            "branch": bd.get("branch"),
            "account_holder": bd.get("account_holder"),
            "upi_id": bd.get("upi_id"),
        })

    return {"status": "success", "data": results, "total": len(results)}


@router.get("/export")
def export_bank_details(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export bank details as Excel."""
    # Reuse the list logic
    company_id = TenantContext.get_optional()
    invoices = (
        db.query(InvoiceRecord)
        .filter(
            InvoiceRecord.company_id == company_id,
            InvoiceRecord.bank_details_json.isnot(None),
            InvoiceRecord.parsing_status.in_(["PARSED", "WARNING"]),
        )
        .order_by(InvoiceRecord.created_at.desc())
        .limit(5000)
        .all() # AI_TECH_EXPLAIN : is it same as offset and limit?
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Bank Details"
    headers = [
        "Invoice #", "Vendor Name", "Invoice Date",
        "Bank Name", "Account Number", "IFSC Code",
        "Branch", "Account Holder", "UPI ID",
    ]
    ws.append(headers)

    for inv in invoices:
        try:
            bd = json.loads(inv.bank_details_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not any(bd.values()):
            continue
        ws.append([
            inv.invoice_number or "",
            inv.vendor_name or "",
            inv.invoice_date or "",
            bd.get("bank_name") or "",
            bd.get("account_number") or "",
            bd.get("ifsc_code") or "",
            bd.get("branch") or "",
            bd.get("account_holder") or "",
            bd.get("upi_id") or "",
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=bank_details_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"},
    )
