"""Vendor profile management routes.

Allows users to view and correct vendor fields (GSTIN, PAN, address, bank details)
across all invoices from a given vendor — fixing parse errors in bulk.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.repository import AuditLogRepository
from app.db.session import get_db
from app.models.db_models import InvoiceDraft, InvoiceRecord, VendorMapping
from app.tenant.context import TenantContext
from app.utils.gstin_utils import validate_gstin_format

logger = logging.getLogger(__name__)
router = APIRouter()

PAN_PATTERN = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]$')


class VendorProfileUpdate(BaseModel):
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    vendor_address: Optional[str] = None
    bank_details_json: Optional[dict] = None


@router.get("")
def list_vendors(
    search: str = Query(None),
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List unique vendors grouped by vendor_name with aggregate metadata."""
    company_id = TenantContext.get()

    query = (
        db.query(
            InvoiceRecord.vendor_name,
            func.count(InvoiceRecord.id).label("invoice_count"),
            func.max(InvoiceRecord.created_at).label("last_invoice_date"),
            func.max(InvoiceRecord.gst_number).label("gst_number"),
            func.max(InvoiceRecord.pan_number).label("pan_number"),
            func.max(InvoiceRecord.vendor_address).label("vendor_address"),
            func.max(InvoiceRecord.bank_details_json).label("bank_details_json"),
        )
        .filter(InvoiceRecord.company_id == company_id)
        .filter(InvoiceRecord.vendor_name.isnot(None))
        .filter(InvoiceRecord.vendor_name != "")
    )

    if search:
        query = query.filter(InvoiceRecord.vendor_name.ilike(f"%{search}%"))

    rows = (
        query
        .group_by(InvoiceRecord.vendor_name)
        .order_by(InvoiceRecord.vendor_name)
        .limit(limit)
        .all()
    )

    # Fetch all vendor mappings for this company in one shot
    mappings = (
        db.query(VendorMapping)
        .filter(VendorMapping.company_id == company_id)
        .all()
    )
    mapping_lookup: dict[str, list] = {}
    for m in mappings:
        key = m.alias_name.lower()
        if key not in mapping_lookup:
            mapping_lookup[key] = []
        mapping_lookup[key].append(m)

    results = []
    for row in rows:
        vendor_name = row.vendor_name
        vendor_mappings = mapping_lookup.get(vendor_name.lower(), [])
        mapped_platforms = [m.platform for m in vendor_mappings]
        first_mapping = vendor_mappings[0] if vendor_mappings else None

        results.append({
            "vendor_name": vendor_name,
            "gst_number": row.gst_number,
            "pan_number": row.pan_number,
            "vendor_address": row.vendor_address,
            "bank_details_json": row.bank_details_json,
            "invoice_count": row.invoice_count,
            "last_invoice_date": str(row.last_invoice_date) if row.last_invoice_date else None,
            "is_mapped": len(vendor_mappings) > 0,
            "platform_vendor_id": first_mapping.platform_vendor_id if first_mapping else None,
            "mapped_platforms": mapped_platforms,
        })

    return {"status": "success", "data": results, "total": len(results)}


@router.get("/{vendor_name}/invoices")
def list_vendor_invoices(
    vendor_name: str,
    db: Session = Depends(get_db),
):
    """Return the last 20 invoices for a specific vendor."""
    company_id = TenantContext.get()

    invoices = (
        db.query(InvoiceRecord)
        .filter(
            InvoiceRecord.company_id == company_id,
            func.lower(InvoiceRecord.vendor_name) == vendor_name.lower(),
        )
        .order_by(InvoiceRecord.created_at.desc())
        .limit(20)
        .all()
    )

    data = [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "invoice_date": inv.invoice_date,
            "total_amount": float(inv.total_amount) if inv.total_amount is not None else None,
            "gst_number": inv.gst_number,
            "pan_number": inv.pan_number,
            "parsing_status": inv.parsing_status,
            "created_at": str(inv.created_at),
        }
        for inv in invoices
    ]

    return {"status": "success", "data": data}


@router.put("/{vendor_name}")
def update_vendor_profile(
    vendor_name: str,
    body: VendorProfileUpdate,
    db: Session = Depends(get_db),
):
    """Bulk-update GSTIN, PAN, address, and/or bank details across all invoices from this vendor."""
    company_id = TenantContext.get()

    # Validate GSTIN if provided
    if body.gst_number is not None:
        gst = body.gst_number.strip().upper()
        if gst and not validate_gstin_format(gst):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid GSTIN format: '{gst}'. Must be 15 characters matching the GST pattern.",
            )
        body.gst_number = gst or None

    # Validate PAN if provided
    if body.pan_number is not None:
        pan = body.pan_number.strip().upper()
        if pan and not PAN_PATTERN.match(pan):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid PAN format: '{pan}'. Must be 5 letters + 4 digits + 1 letter (e.g. ABCDE1234F).",
            )
        body.pan_number = pan or None

    # Fetch all invoices for this vendor
    invoices = (
        db.query(InvoiceRecord)
        .filter(
            InvoiceRecord.company_id == company_id,
            func.lower(InvoiceRecord.vendor_name) == vendor_name.lower(),
        )
        .all()
    )

    if not invoices:
        raise HTTPException(status_code=404, detail=f"No invoices found for vendor '{vendor_name}'")

    fields_updated: list[str] = []

    # Determine which fields to update
    if body.gst_number is not None:
        fields_updated.append("gst_number")
    if body.pan_number is not None:
        fields_updated.append("pan_number")
    if body.vendor_address is not None:
        fields_updated.append("vendor_address")
    if body.bank_details_json is not None:
        fields_updated.append("bank_details_json")

    if not fields_updated:
        return {"status": "success", "updated_invoices": 0, "updated_drafts": 0}

    bank_json_str: Optional[str] = None
    if body.bank_details_json is not None:
        bank_json_str = json.dumps(body.bank_details_json)

    invoice_ids: list[int] = []
    for inv in invoices:
        if body.gst_number is not None:
            inv.gst_number = body.gst_number
        if body.pan_number is not None:
            inv.pan_number = body.pan_number
        if body.vendor_address is not None:
            inv.vendor_address = body.vendor_address
        if body.bank_details_json is not None:
            inv.bank_details_json = bank_json_str
        invoice_ids.append(inv.id)

    # Update InvoiceDraft.bank_details_json for all linked drafts
    updated_drafts = 0
    if body.bank_details_json is not None and invoice_ids:
        drafts = (
            db.query(InvoiceDraft)
            .filter(
                InvoiceDraft.company_id == company_id,
                InvoiceDraft.invoice_id.in_(invoice_ids),
            )
            .all()
        )
        for draft in drafts:
            draft.bank_details_json = bank_json_str
        updated_drafts = len(drafts)

    db.commit()

    # Audit log
    try:
        AuditLogRepository(db).log(
            entity_type="vendor_profile",
            entity_id=0,
            action="updated",
            details={
                "vendor": vendor_name,
                "fields_updated": fields_updated,
                "invoice_count": len(invoices),
                "draft_count": updated_drafts,
            },
        )
    except Exception:
        logger.exception("Failed to write audit log for vendor profile update")

    logger.info(
        "Vendor profile updated: vendor=%s fields=%s invoices=%d drafts=%d",
        vendor_name, fields_updated, len(invoices), updated_drafts,
    )

    return {
        "status": "success",
        "updated_invoices": len(invoices),
        "updated_drafts": updated_drafts,
    }
