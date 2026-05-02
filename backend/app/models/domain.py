from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = ""
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: float = 0.0
    hsn_or_sac: Optional[str] = None
    tax_rate: Optional[float] = None
    cgst_amount: Optional[float] = None
    sgst_amount: Optional[float] = None
    igst_amount: Optional[float] = None


class TaxBreakup(BaseModel):
    cgst_rate: Optional[float] = None
    cgst_amount: Optional[float] = None
    sgst_rate: Optional[float] = None
    sgst_amount: Optional[float] = None
    igst_rate: Optional[float] = None
    igst_amount: Optional[float] = None
    cess_amount: Optional[float] = None


class BankDetails(BaseModel):
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    ifsc_code: Optional[str] = None
    branch: Optional[str] = None
    account_holder: Optional[str] = None
    upi_id: Optional[str] = None


class Invoice(BaseModel):
    invoice_number: Optional[str] = None
    vendor_name: Optional[str] = None
    date: Optional[str] = None
    due_date: Optional[str] = None
    total_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    subtotal: Optional[float] = None
    line_items: List[LineItem] = Field(default_factory=list)
    tax_breakup: Optional[TaxBreakup] = None
    bank_details: Optional[BankDetails] = None
    buyer_gst_number: Optional[str] = None  # GSTIN of the buyer (our company)
    gst_number: Optional[str] = None        # GSTIN of the vendor/seller
    pan_number: Optional[str] = None        # PAN of the vendor/seller
    buyer_pan_number: Optional[str] = None  # PAN of the buyer (our company)
    vendor_address: Optional[str] = None    # Full address of the vendor/seller
    uan_number: Optional[str] = None
    currency: str = "INR"
    notes: Optional[str] = None
    raw_text: Optional[str] = None
    parser_mode: Optional[str] = None
    confidence_scores: Dict[str, float] = Field(default_factory=dict)


class APIResponse(BaseModel):
    status: str = "success"
    message: str = ""
    data: Optional[Any] = None
