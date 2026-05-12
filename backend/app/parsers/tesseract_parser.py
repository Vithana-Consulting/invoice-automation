from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

from app.core.exceptions import OCRError, ParsingError
from app.models.domain import Invoice, LineItem
from app.parsers.base import InvoiceParser

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {"pdf", "jpg", "jpeg", "png", "tiff", "tif", "bmp"}

# -- Regex patterns for Indian invoices --

# GST: 2 digits + 5 uppercase + 4 digits + 1 uppercase + 1 digit + Z + 1 alphanumeric
GST_PATTERN = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d])\b")

# PAN: 5 uppercase + 4 digits + 1 uppercase
PAN_PATTERN = re.compile(r"\b([A-Z]{5}\d{4}[A-Z])\b")

# UAN: 12 digits
UAN_PATTERN = re.compile(r"\bUAN\s*:?\s*(\d{12})\b", re.IGNORECASE)

# Invoice number patterns — captured value must contain a digit (all real invoice numbers do)
INVOICE_NUM_PATTERNS = [
    # Explicit label: require at least one digit in the captured token
    re.compile(r"(?:Invoice|Inv|Bill)\s*(?:No|Number|#|Num)[.:\s#\-]*([A-Z0-9][\w\-/]*\d[\w\-/]*)", re.IGNORECASE),
    re.compile(r"(?:Invoice|Inv)\s*[:.#\-]\s*([A-Z0-9][\w\-/]*\d[\w\-/]*)", re.IGNORECASE),
    # "Inv. No. : MOS/25/0087" — dot-separated label with spaces
    re.compile(r"Inv\.?\s*No\.?\s*[:\s]+([A-Z0-9][\w\-/]*\d[\w\-/]*)", re.IGNORECASE),
    # Standalone "No: PPW-1092"
    re.compile(r"(?<!\w)No\s*[:]\s*([A-Z]{2,8}-\d{1,6})\b", re.IGNORECASE),
    # Indian 3-part without year-range: MOS/25/0087
    re.compile(r"\b([A-Z]{2,6}/\d{2,4}/\d{1,6})\b", re.IGNORECASE),
    # Indian-style tax invoice numbers: CA/25-26/340, INV/2024-25/696, CA/25\x0026/340 (OCR null bytes)
    re.compile(r"\b([A-Z]{2,4}[/\-]\d{2,4}[\-\x00]\d{2,4}[/\-]\d{1,6})\b", re.IGNORECASE),
]

# Date patterns
DATE_PATTERNS = [
    # DD/MM/YYYY or DD-MM-YYYY
    re.compile(r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})\b"),
    # YYYY-MM-DD
    re.compile(r"\b(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})\b"),
    # DD Mon YYYY
    re.compile(r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})\b", re.IGNORECASE),
]

# Amount patterns
TOTAL_AMOUNT_PATTERNS = [
    re.compile(r"(?:Grand\s*Total|Total\s*Amount|Net\s*(?:Amount|Payable)|Amount\s*(?:Due|Payable))\s*[:\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"(?:Total)\s*[:\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
]

TAX_AMOUNT_PATTERNS = [
    re.compile(r"(?:CGST|SGST|IGST)\s*[^:\n]*[:\s]+(?:Rs\.?|INR|₹)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"(?:GST|Tax)\s*(?:Amount|Value|Total)[^:\n]*[:\s]+(?:Rs\.?|INR|₹)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
]

SUBTOTAL_PATTERNS = [
    re.compile(r"(?:Sub\s*[-\s]?\s*Total|Taxable\s*(?:Amount|Value))\s*[:\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
]

# Vendor name: typically near top of invoice, after "From:" or "Vendor:" or "Seller:"
VENDOR_PATTERNS = [
    re.compile(r"(?:From|Vendor|Supplier|Billed\s*By|Company\s*Name)\s*[:\s]+\n?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"^Seller\s*:\s*(.+?)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"Seller\s*Name\s*[:\s]+(.+?)(?:\n|$)", re.IGNORECASE),
]

# Due date
DUE_DATE_PATTERNS = [
    re.compile(r"(?:Due\s*Date|Payment\s*Due|Pay\s*(?:By|Before))\s*[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})", re.IGNORECASE),
    re.compile(r"(?:Due\s*Date|Payment\s*Due)\s*[:\s]*(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})", re.IGNORECASE),
    re.compile(r"(?:Due\s*Date|Payment\s*Due)\s*[:\s]*(\d{1,2}\s+\w+\s+\d{4})", re.IGNORECASE),
]

# Invoice date
INVOICE_DATE_PATTERNS = [
    re.compile(r"(?:Invoice\s*Date|Date\s*of\s*Invoice|Bill\s*Date|Dated|Dt\.?|Date)\s*[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})", re.IGNORECASE),
    re.compile(r"(?:Invoice\s*Date|Date\s*of\s*Invoice|Bill\s*Date|Dated|Dt\.?|Date)\s*[:\s]*(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})", re.IGNORECASE),
    re.compile(r"(?:Invoice\s*Date|Bill\s*Date|Dated|Dt\.?|Date)\s*[:\s]*(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})", re.IGNORECASE),
    # "Dt. : 12-Jan-2025" — dash-separated month-name date
    re.compile(r"(?:Invoice\s*Date|Bill\s*Date|Dated|Dt\.?|Date)\s*[:\s]*(\d{1,2}[.\-](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[.\-]\d{4})", re.IGNORECASE),
]


def _parse_amount(raw: str) -> Optional[float]:
    """Convert '1,23,456.78' or '123456.78' to float."""
    cleaned = raw.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _first_match(text: str, patterns: list) -> Optional[str]:
    """Return the first match from a list of compiled regex patterns."""
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return None


def _extract_text_from_pdf(file_path: str) -> Tuple[str, List[list]]:
    """Extract text and tables from a text-based PDF using pdfplumber."""
    full_text = []
    all_tables = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            full_text.append(text)
            tables = page.extract_tables() or []
            all_tables.extend(tables)
    return "\n".join(full_text), all_tables


def _ocr_image(file_path: str) -> str:
    """Run Tesseract OCR on an image file."""
    try:
        img = Image.open(file_path)
        return pytesseract.image_to_string(img)
    except Exception as e:
        raise OCRError(f"Failed to OCR image {file_path}: {e}")


def _ocr_pdf(file_path: str) -> str:
    """Convert PDF to images and run OCR."""
    try:
        images = convert_from_path(file_path, dpi=300)
    except Exception as e:
        raise OCRError(f"Failed to convert PDF to images: {e}")

    texts = []
    for img in images:
        text = pytesseract.image_to_string(img)
        texts.append(text)
    return "\n".join(texts)


def _extract_line_items_from_tables(tables: List[list]) -> List[LineItem]:
    """Extract line items from pdfplumber tables."""
    items = []
    for table in tables:
        if not table or len(table) < 2:
            continue

        # Find header row
        header = [str(cell).lower().strip() if cell else "" for cell in table[0]]

        # Map column indices
        desc_idx = _find_col(header, ["description", "item", "particular", "product", "service", "name"])
        qty_idx = _find_col(header, ["qty", "quantity", "units"])
        rate_idx = _find_col(header, ["rate", "price", "unit price", "unit_price"])
        amount_idx = _find_col(header, ["amount", "total", "value", "net"])
        hsn_idx = _find_col(header, ["hsn", "sac", "hsn/sac", "hsn_or_sac"])

        if desc_idx is None and amount_idx is None:
            continue

        for row in table[1:]:
            if not row or all(not cell for cell in row):
                continue
            desc = str(row[desc_idx]).strip() if desc_idx is not None and desc_idx < len(row) and row[desc_idx] else ""
            if not desc:
                continue

            qty = None
            if qty_idx is not None and qty_idx < len(row) and row[qty_idx]:
                qty = _parse_amount(str(row[qty_idx]))

            rate = None
            if rate_idx is not None and rate_idx < len(row) and row[rate_idx]:
                rate = _parse_amount(str(row[rate_idx]))

            amt = 0.0
            if amount_idx is not None and amount_idx < len(row) and row[amount_idx]:
                amt = _parse_amount(str(row[amount_idx])) or 0.0

            hsn = None
            if hsn_idx is not None and hsn_idx < len(row) and row[hsn_idx]:
                hsn = str(row[hsn_idx]).strip()

            items.append(LineItem(
                description=desc,
                quantity=qty,
                unit_price=rate,
                amount=amt,
                hsn_or_sac=hsn,
            ))

    return items


def _extract_line_items_from_text(text: str) -> List[LineItem]:
    """Extract line items from raw text using heuristics.

    Looks for lines that end with a number (amount) and contain
    numeric fields that could be quantity and rate.
    """
    items = []
    lines = text.split("\n")

    # Find the header line to know where items start
    header_idx = -1
    for i, line in enumerate(lines):
        lower = line.lower()
        if ("description" in lower or "particular" in lower) and (
            "amount" in lower or "total" in lower or "rate" in lower
        ):
            header_idx = i
            break

    if header_idx < 0:
        return items

    # Parse lines after header until a summary line (Sub Total, Total, etc.)
    stop_keywords = {"sub total", "subtotal", "total", "grand total", "cgst", "sgst", "igst", "tax"}
    # Regex: description text followed by optional numbers (hsn, qty, rate) and amount
    item_pattern = re.compile(
        r"^(.+?)\s+"           # description (greedy until numbers)
        r"(\d{4,6})?\s*"       # optional HSN/SAC (4-6 digits)
        r"(\d+(?:\.\d+)?)\s+"  # qty or rate
        r"([\d,]+\.?\d*)\s+"   # rate or amount
        r"([\d,]+\.?\d*)\s*$"  # amount
    )
    item_pattern_simple = re.compile(
        r"^(.+?)\s+([\d,]+\.?\d*)\s*$"  # description + amount only
    )

    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(kw in lower for kw in stop_keywords):
            break

        m = item_pattern.match(stripped)
        if m:
            desc = m.group(1).strip()
            hsn = m.group(2)
            val3 = _parse_amount(m.group(3))
            val4 = _parse_amount(m.group(4))
            val5 = _parse_amount(m.group(5))
            items.append(LineItem(
                description=desc,
                hsn_or_sac=hsn,
                quantity=val3,
                unit_price=val4,
                amount=val5 or 0.0,
            ))
            continue

        m = item_pattern_simple.match(stripped)
        if m:
            desc = m.group(1).strip()
            amt = _parse_amount(m.group(2))
            if desc and amt and len(desc) > 3:
                items.append(LineItem(description=desc, amount=amt or 0.0))

    return items


def _find_col(header: List[str], keywords: List[str]) -> Optional[int]:
    """Find column index by keyword matching."""
    for idx, col in enumerate(header):
        for kw in keywords:
            if kw in col:
                return idx
    return None


class TesseractParser(InvoiceParser):
    """Default parser: pdfplumber for text PDFs, Tesseract OCR for scanned/images."""

    def supports(self, file_type: str) -> bool:
        return file_type.lower().lstrip(".") in SUPPORTED_TYPES

    def parse(self, file_path: str, file_type: str, buyer_hint=None) -> Invoice:
        ft = file_type.lower().lstrip(".")
        if not self.supports(ft):
            raise ParsingError(f"Unsupported file type: {ft}")

        text = ""
        tables = []
        confidence = {}

        if ft == "pdf":
            text, tables = self._parse_pdf(file_path)
        else:
            text = _ocr_image(file_path)
            confidence["ocr"] = 0.7  # OCR text is inherently lower confidence

        if not text.strip():
            raise ParsingError(f"No text extracted from {file_path}")

        logger.info("Extracted %d characters from %s", len(text), file_path)

        # Extract fields using improved extraction logic
        from app.parsers.extraction import extract_vendor_name, extract_total_amount, extract_invoice_number

        invoice_number = extract_invoice_number(text)
        vendor_name = extract_vendor_name(text)
        invoice_date = _first_match(text, INVOICE_DATE_PATTERNS)
        due_date = _first_match(text, DUE_DATE_PATTERNS)

        # Amounts — use improved extraction
        total_amount = extract_total_amount(text)

        # Tax: sum all CGST/SGST/IGST/GST occurrences
        tax_amount = 0.0
        for pat in TAX_AMOUNT_PATTERNS:
            for m in pat.finditer(text):
                val = _parse_amount(m.group(1))
                if val:
                    tax_amount += val
        if tax_amount == 0.0:
            tax_amount = None

        sub_raw = _first_match(text, SUBTOTAL_PATTERNS)
        subtotal = _parse_amount(sub_raw) if sub_raw else None

        # Identifiers — find all GSTINs; first = vendor (seller), second = buyer
        all_gstins = GST_PATTERN.findall(text)
        gst_number = all_gstins[0] if all_gstins else None
        # For purchase invoices the buyer GSTIN is the second distinct GSTIN found
        buyer_gst_number = None
        seen = {gst_number} if gst_number else set()
        for g in all_gstins[1:]:
            if g not in seen:
                buyer_gst_number = g
                break

        pan_match = PAN_PATTERN.search(text)
        pan_number = pan_match.group(1) if pan_match else None

        uan_match = UAN_PATTERN.search(text)
        uan_number = uan_match.group(1) if uan_match else None

        # Line items from tables (structured) or text (fallback)
        line_items = _extract_line_items_from_tables(tables)
        if not line_items:
            line_items = _extract_line_items_from_text(text)

        # Confidence scoring
        if invoice_number:
            confidence["invoice_number"] = 0.9
        if vendor_name:
            confidence["vendor_name"] = 0.7 if "ocr" in confidence else 0.85
        if total_amount is not None:
            confidence["total_amount"] = 0.85
        if gst_number:
            confidence["gst_number"] = 0.95  # Regex is very specific

        # Currency detection
        currency = "INR"
        if re.search(r"\$|USD", text):
            currency = "USD"
        elif re.search(r"€|EUR", text):
            currency = "EUR"
        elif re.search(r"£|GBP", text):
            currency = "GBP"

        return Invoice(
            invoice_number=invoice_number,
            vendor_name=vendor_name,
            date=invoice_date,
            due_date=due_date,
            total_amount=total_amount,
            tax_amount=tax_amount,
            subtotal=subtotal,
            line_items=line_items,
            gst_number=gst_number,
            buyer_gst_number=buyer_gst_number,
            pan_number=pan_number,
            uan_number=uan_number,
            currency=currency,
            raw_text=text[:50000],
            parser_mode="tesseract",
            confidence_scores=confidence,
        )

    def _parse_pdf(self, file_path: str) -> Tuple[str, List[list]]:
        """Try pdfplumber first; fall back to OCR if text is sparse."""
        text, tables = _extract_text_from_pdf(file_path)

        # Heuristic: if less than 50 chars per page, it's likely scanned
        with pdfplumber.open(file_path) as pdf:
            num_pages = len(pdf.pages)

        chars_per_page = len(text) / max(num_pages, 1)
        if chars_per_page < 50:
            logger.info(
                "PDF appears scanned (%.0f chars/page). Falling back to OCR.",
                chars_per_page,
            )
            text = _ocr_pdf(file_path)
            tables = []  # OCR path doesn't have table structure

        return text, tables
