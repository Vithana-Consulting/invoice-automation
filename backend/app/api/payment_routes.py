"""Payment routes — company bank accounts and invoice payment recording."""
from __future__ import annotations

import json
import logging
from datetime import datetime, date as date_type

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_optional_user
from app.db.session import get_db
from app.models.db_models import (
    CompanyBankAccount,
    InvoiceDraft,
    InvoicePayment,
    User,
)
from app.tenant.context import TenantContext
from app.db.repository import AuditLogRepository

logger = logging.getLogger(__name__)
router = APIRouter(tags=["payments"])


# ─── Company Bank Accounts ────────────────────────────────────────────────────


@router.get("/company/bank-accounts")
def list_company_bank_accounts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all active company bank accounts for the current tenant."""
    company_id = TenantContext.get_optional()
    accounts = (
        db.query(CompanyBankAccount)
        .filter(
            CompanyBankAccount.company_id == company_id,
            CompanyBankAccount.is_active == True,
        )
        .order_by(CompanyBankAccount.is_default.desc(), CompanyBankAccount.id)
        .all()
    )
    return {
        "status": "success",
        "data": [_account_to_dict(a) for a in accounts],
    }


@router.post("/company/bank-accounts")
def create_company_bank_account(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new company bank account."""
    company_id = TenantContext.get_optional()

    required = ["bank_name", "account_number", "ifsc_code", "account_alias"]
    for field in required:
        if not body.get(field):
            raise HTTPException(status_code=422, detail=f"'{field}' is required")

    account_number = body["account_number"].strip()
    # Auto-mask: first 4 chars + *** + last 4
    if len(account_number) > 8:
        masked = account_number[:4] + "X" * (len(account_number) - 8) + account_number[-4:]
    else:
        masked = "X" * len(account_number)

    # If this is set as default, unset any existing default first
    if body.get("is_default"):
        db.query(CompanyBankAccount).filter(
            CompanyBankAccount.company_id == company_id,
            CompanyBankAccount.is_default == True,
        ).update({"is_default": False})
        db.flush()

    now = datetime.utcnow()
    account = CompanyBankAccount(
        company_id=company_id,
        bank_name=body["bank_name"].strip(),
        account_number=account_number,
        account_number_masked=masked,
        ifsc_code=body["ifsc_code"].strip().upper(),
        account_type=body.get("account_type", "CURRENT").upper(),
        account_alias=body["account_alias"].strip(),
        is_default=bool(body.get("is_default", False)),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    AuditLogRepository(db).log(
        entity_type="company_bank_account",
        entity_id=account.id,
        action="bank_account_created",
        details={"alias": account.account_alias, "bank": account.bank_name},
    )
    db.commit()

    return {"status": "success", "data": _account_to_dict(account)}


# ─── Invoice Payments ─────────────────────────────────────────────────────────


@router.get("/drafts/{draft_id}/payments")
def list_payments(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all payments for a draft with running balance_due."""
    company_id = TenantContext.get_optional()
    draft = db.query(InvoiceDraft).filter(
        InvoiceDraft.id == draft_id,
        InvoiceDraft.company_id == company_id,
    ).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    payments = (
        db.query(InvoicePayment)
        .filter(
            InvoicePayment.draft_id == draft_id,
            InvoicePayment.company_id == company_id,
        )
        .order_by(InvoicePayment.payment_date.asc(), InvoicePayment.id.asc())
        .all()
    )

    invoice_total = float(draft.total_amount or 0)
    total_paid = float(draft.amount_paid or 0)
    total_due = float(draft.amount_due) if draft.amount_due is not None else invoice_total - total_paid

    return {
        "status": "success",
        "data": [_payment_to_dict(p) for p in payments],
        "summary": {
            "invoice_total": invoice_total,
            "total_paid": total_paid,
            "balance_due": total_due,
            "payment_status": draft.payment_status or "UNPAID",
            "payment_count": len(payments),
        },
    }


@router.post("/drafts/{draft_id}/payments")
def record_payment(
    draft_id: int,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Record a payment against an invoice draft."""
    company_id = TenantContext.get_optional()
    draft = db.query(InvoiceDraft).filter(
        InvoiceDraft.id == draft_id,
        InvoiceDraft.company_id == company_id,
    ).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    # Validate required fields
    required = ["payment_method", "payment_date", "payment_amount"]
    for field in required:
        if body.get(field) is None:
            raise HTTPException(status_code=422, detail=f"'{field}' is required")

    payment_amount = float(body["payment_amount"])
    if payment_amount <= 0:
        raise HTTPException(status_code=422, detail="payment_amount must be positive")

    # Parse payment date
    try:
        if isinstance(body["payment_date"], str):
            payment_date = date_type.fromisoformat(body["payment_date"])
        else:
            payment_date = body["payment_date"]
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid payment_date format (use YYYY-MM-DD)")

    # Resolve payer bank account if provided
    payer_bank_name = None
    payer_masked = None
    payer_account_id = body.get("payer_bank_account_id")
    if payer_account_id:
        payer_acct = db.query(CompanyBankAccount).filter(
            CompanyBankAccount.id == payer_account_id,
            CompanyBankAccount.company_id == company_id,
        ).first()
        if payer_acct:
            payer_bank_name = payer_acct.bank_name
            payer_masked = payer_acct.account_number_masked

    now = datetime.utcnow()
    payment = InvoicePayment(
        company_id=company_id,
        invoice_id=draft.invoice_id,
        draft_id=draft_id,
        payment_method=body["payment_method"].upper(),
        payment_date=payment_date,
        payment_amount=payment_amount,
        currency=body.get("currency", "INR"),
        payment_reference=body.get("payment_reference"),
        cheque_number=body.get("cheque_number"),
        cheque_date=_parse_optional_date(body.get("cheque_date")),
        cheque_clearing_date=_parse_optional_date(body.get("cheque_clearing_date")),
        payer_bank_account_id=payer_account_id,
        payer_bank_name=payer_bank_name,
        payer_account_number_masked=payer_masked,
        payee_account_number=body.get("payee_account_number"),
        payee_ifsc_code=body.get("payee_ifsc_code"),
        payee_upi_id=body.get("payee_upi_id"),
        invoice_total_amount=float(draft.total_amount or 0),
        tds_amount=float(body.get("tds_amount") or 0),
        tds_section=body.get("tds_section"),
        advance_adjusted=float(body.get("advance_adjusted") or 0),
        advance_reference=body.get("advance_reference"),
        payment_status="INITIATED",
        payment_type=body.get("payment_type", "FULL"),
        remarks=body.get("remarks"),
        recorded_by_email=user.email if user else "system",
        recorded_by_name=user.name if user else None,
        recorded_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(payment)
    db.flush()

    # Recompute amount_paid and amount_due on the draft
    _recompute_draft_payment_totals(draft_id, draft, db)
    db.commit()
    db.refresh(payment)

    AuditLogRepository(db).log(
        entity_type="invoice_draft",
        entity_id=draft_id,
        action="payment_recorded",
        details={
            "payment_id": payment.id,
            "amount": payment_amount,
            "method": payment.payment_method,
            "reference": payment.payment_reference,
            "recorded_by": payment.recorded_by_email,
        },
    )
    db.commit()

    return {"status": "success", "data": _payment_to_dict(payment)}


@router.patch("/payments/{payment_id}/status")
def update_payment_status(
    payment_id: int,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update payment status (CLEARED / BOUNCED / CANCELLED)."""
    company_id = TenantContext.get_optional()
    payment = db.query(InvoicePayment).filter(
        InvoicePayment.id == payment_id,
        InvoicePayment.company_id == company_id,
    ).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    valid_statuses = {"INITIATED", "PENDING_CLEARANCE", "CLEARED", "BOUNCED", "CANCELLED"}
    new_status = body.get("payment_status", "").upper()
    if new_status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"Invalid status. Must be one of: {', '.join(sorted(valid_statuses))}")

    payment.payment_status = new_status
    payment.updated_at = datetime.utcnow()

    # If a draft is linked, recompute totals (bounced payments are excluded from paid sum)
    if payment.draft_id:
        draft = db.query(InvoiceDraft).filter(InvoiceDraft.id == payment.draft_id).first()
        if draft:
            _recompute_draft_payment_totals(payment.draft_id, draft, db)

    db.commit()
    db.refresh(payment)

    return {"status": "success", "data": _payment_to_dict(payment)}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _recompute_draft_payment_totals(draft_id: int, draft: InvoiceDraft, db: Session) -> None:
    """Sum non-BOUNCED payments, update draft amount_paid/amount_due/payment_status."""
    result = (
        db.query(
            func.coalesce(func.sum(InvoicePayment.payment_amount), 0).label("total_paid"),
            func.coalesce(func.sum(InvoicePayment.tds_amount), 0).label("total_tds"),
            func.coalesce(func.sum(InvoicePayment.advance_adjusted), 0).label("total_advance"),
        )
        .filter(
            InvoicePayment.draft_id == draft_id,
            InvoicePayment.payment_status.notin_(["BOUNCED", "CANCELLED"]),
        )
        .one()
    )

    invoice_total = float(draft.total_amount or 0)
    total_paid = float(result.total_paid)
    total_tds = float(result.total_tds)
    total_advance = float(result.total_advance)
    amount_due = max(0.0, invoice_total - total_paid - total_tds - total_advance)

    if total_paid <= 0:
        pay_status = "UNPAID"
    elif amount_due <= 0.01:  # tolerance for float rounding
        pay_status = "FULLY_PAID"
    else:
        pay_status = "PARTIALLY_PAID"

    draft.amount_paid = total_paid
    draft.amount_due = amount_due
    draft.payment_status = pay_status
    draft.updated_at = datetime.utcnow()


def _parse_optional_date(value):
    if not value:
        return None
    try:
        return date_type.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _account_to_dict(a: CompanyBankAccount) -> dict:
    return {
        "id": a.id,
        "bank_name": a.bank_name,
        "account_number_masked": a.account_number_masked,
        "ifsc_code": a.ifsc_code,
        "account_type": a.account_type,
        "account_alias": a.account_alias,
        "is_default": a.is_default,
        "is_active": a.is_active,
        "created_at": str(a.created_at) if a.created_at else None,
    }


def _payment_to_dict(p: InvoicePayment) -> dict:
    return {
        "id": p.id,
        "draft_id": p.draft_id,
        "invoice_id": p.invoice_id,
        "payment_method": p.payment_method,
        "payment_date": str(p.payment_date) if p.payment_date else None,
        "payment_amount": float(p.payment_amount) if p.payment_amount else 0.0,
        "currency": p.currency,
        "payment_reference": p.payment_reference,
        "cheque_number": p.cheque_number,
        "payer_bank_name": p.payer_bank_name,
        "payer_account_number_masked": p.payer_account_number_masked,
        "payee_account_number": p.payee_account_number,
        "payee_ifsc_code": p.payee_ifsc_code,
        "payee_upi_id": p.payee_upi_id,
        "tds_amount": float(p.tds_amount) if p.tds_amount else 0.0,
        "tds_section": p.tds_section,
        "advance_adjusted": float(p.advance_adjusted) if p.advance_adjusted else 0.0,
        "payment_status": p.payment_status,
        "payment_type": p.payment_type,
        "remarks": p.remarks,
        "recorded_by_email": p.recorded_by_email,
        "recorded_by_name": p.recorded_by_name,
        "recorded_at": str(p.recorded_at) if p.recorded_at else None,
        "created_at": str(p.created_at) if p.created_at else None,
    }
