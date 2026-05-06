"""Shared field extraction logic for all parsers.

Improved vendor name, amount, and invoice number extraction
with better heuristics and negative filters.
"""
from __future__ import annotations

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# -- Company suffix patterns (strong signal for vendor name) --
COMPANY_SUFFIXES = re.compile(
    r"\b(?:Pvt\.?\s*Ltd|Private\s+Limited|Limited|LLC|LLP|Inc\.?|Corp\.?|Corporation"
    r"|Technologies|Entertainment|Solutions|Enterprises|Services|Consulting"
    r"|Systems|Software|Communications|Industries|Associates|Partners"
    r"|Infotech|Infosystems|Foundation|Trust)\b",
    re.IGNORECASE,
)

# Strong legal entity endings only — used to find where a company name definitively ends
# (excludes ambiguous words like "Technologies" that are mid-name, not end-of-name)
COMPANY_ENTITY_ENDINGS = re.compile(
    r"\b(?:Pvt\.?\s*Ltd\.?|Private\s+Limited|Limited|LLC|LLP|Inc\.?|Corp\.?|Corporation)\b",
    re.IGNORECASE,
)

# -- Negative filters: lines that should NEVER be vendor names --
VENDOR_NEGATIVE_KEYWORDS = {
    "nagar", "road", "street", "floor", "pin code", "pin:", "state",
    "place of supply", "payment", "summary", "credit card", "authorized",
    "acknowledgement", "receipt", "tax invoice", "invoice details",
    "bill to", "ship to", "shipping", "billing address", "customer",
    "computer generated", "does not require", "terms", "conditions",
    "page ", "www.", "http", "copy to be kept",
}

# -- Vendor extraction patterns (ordered by confidence) --
VENDOR_EXTRACT_PATTERNS = [
    # Explicit labels
    re.compile(r"(?:Invoice\s*issued\s*by|Billed\s*from|Sold\s*by)\s*[:\s]+\n?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"(?:From|Vendor|Supplier|Billed\s*By|Company\s*Name)\s*[:\s]+\n?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"^Seller\s*:\s*(.+?)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"Seller\s*Name\s*[:\s]+(.+?)(?:\n|$)", re.IGNORECASE),
]

# GST pattern for GSTIN-holder heuristic
GST_PATTERN = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d])\b")

# Amount patterns — ordered by specificity
AMOUNT_PATTERNS_SPECIFIC = [
    re.compile(r"(?:Grand\s*Total|Amount\s*Due|Net\s*Payable|Amount\s*Payable|Balance\s*Due)\s*[:\s]*(?:Rs\.?|INR|₹|\$|USD|€|£)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
]
AMOUNT_PATTERNS_GENERAL = [
    re.compile(r"(?:Total\s*Amount|Net\s*Amount)\s*[:\s]*(?:Rs\.?|INR|₹|\$|USD|€|£)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"(?:Total)\s*[:\s]*(?:Rs\.?|INR|₹|\$|USD|€|£)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
]

# Amount with currency symbol (e.g. "₹1,935.53 due")
AMOUNT_CURRENCY_PATTERN = re.compile(r"[₹\$€£]\s*([\d,]+\.?\d*)\s*(?:due|payable)", re.IGNORECASE)


def _parse_amount(raw: str) -> Optional[float]:
    cleaned = raw.replace(",", "").strip()
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def _is_bad_vendor_line(line: str) -> bool:
    """Check if a line is clearly NOT a vendor name."""
    lower = line.lower().strip()
    if len(lower) < 3 or len(lower) > 200:
        return True
    for kw in VENDOR_NEGATIVE_KEYWORDS:
        if kw in lower:
            return True
    # All caps short codes are likely not vendor names
    if re.match(r"^[A-Z0-9]{3,10}$", line.strip()):
        return True
    # Lines that are mostly numbers
    digits = sum(c.isdigit() for c in line)
    if len(line) > 0 and digits / len(line) > 0.5:
        return True
    return False


def _clean_vendor(name: str) -> str:
    """Clean markdown artifacts and noise from vendor name."""
    # Strip markdown headers
    name = re.sub(r"^#+\s*", "", name).strip()
    # Strip markdown bold/italic
    name = re.sub(r"\*+", "", name).strip()
    # Strip leading/trailing pipes (markdown tables)
    name = name.strip("|").strip()
    return name


def _first_company_in_line(line: str) -> Optional[str]:
    """Extract the FIRST company name from a line that may contain multiple.

    Uses strong legal-entity endings (Private Limited, Ltd, LLP, etc.) to find
    where the first company name ends, ignoring weaker words like "Technologies"
    that appear mid-name.

    Handles OCR-merged two-column lines like:
      "Kodo Technologies Private Limited Entvin Labs Private Limited"
    → returns "Kodo Technologies Private Limited"
    """
    # Prefer strong entity endings (Private Limited, Ltd, LLP…)
    m = COMPANY_ENTITY_ENDINGS.search(line)
    if not m:
        # Fall back to any company suffix if no strong ending found
        m = COMPANY_SUFFIXES.search(line)
    if not m:
        return None
    candidate = line[:m.end()].strip()
    # Strip any leading label like "FROM " or "GSTIN - "
    candidate = re.sub(r"^(?:FROM|TO|GSTIN\s*[-:\s]*\S+)\s*", "", candidate, flags=re.IGNORECASE).strip()
    return candidate if candidate else None


def extract_vendor_name(text: str) -> Optional[str]:
    """Extract the VENDOR (seller/issuer) name from a purchase invoice.

    Strategies are ordered by confidence for Indian purchase invoice layouts:

    S0 — FROM/TO two-column (Kodo style):
         "FROM TO" header → next line has both names concatenated by OCR →
         take text up to first company-suffix match (left = FROM = vendor).

    S1 — Bill To boundary (Zoho/Freshbooks style):
         Restrict search to text BEFORE "Bill To" marker (everything after is buyer).
         Within that section use first-line letterhead heuristic then suffix scan.

    S2 — Explicit seller labels (Invoice issued by:, Sold by:, etc.)

    S3 — Company suffix scan with buyer-name exclusion.

    S4 — GSTIN-holder heuristic (skips known buyer GSTIN).

    S5 — None (prefer no vendor over a wrong one).
    """
    # Known buyer identifiers — lines containing these are the RECIPIENT, not the vendor
    BUYER_KEYWORDS = {"entvin labs", "29aahce1996r1zl"}

    def _is_buyer_line(line: str) -> bool:
        lower = line.lower()
        return any(kw in lower for kw in BUYER_KEYWORDS)

    # Pre-clean markdown
    clean_text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)

    # ── Strategy 0: FROM/TO two-column layout ────────────────────────────────
    # Kodo-style invoices have "FROM TO" as a header, then both company names
    # on the SAME line because OCR flattens the two-column table.
    from_to_m = re.search(r"\bFROM\s+TO\b", clean_text, re.IGNORECASE)
    if from_to_m:
        rest = clean_text[from_to_m.end():]
        for line in rest.split("\n"):
            line = line.strip()
            if not line or not COMPANY_SUFFIXES.search(line):
                continue
            candidate = _first_company_in_line(line)
            if candidate and not _is_bad_vendor_line(candidate) and not _is_buyer_line(candidate):
                return _clean_vendor(candidate)[:200]
            break  # Only check the first non-blank line after FROM/TO header

    # ── Strategy 1: Bill To boundary ─────────────────────────────────────────
    # Zoho/Freshbooks invoices have seller block at top, then "Bill To" section.
    # Everything AFTER "Bill To" is buyer — restrict search to the header block.
    bill_to_m = re.search(r"\bBill(?:ed)?\s+To\b", clean_text, re.IGNORECASE)
    search_text = clean_text[:bill_to_m.start()] if bill_to_m else clean_text

    if bill_to_m:
        # First-line letterhead: for Zoho-style PDFs, line 1 is the seller entity name
        # followed by "TAX INVOICE" or similar on the same line.
        top_lines = [l.strip() for l in search_text.split("\n") if l.strip()]
        for line in top_lines[:5]:
            # Strip trailing document-type keywords
            clean = re.sub(
                r"\s*(?:TAX\s+INVOICE|INVOICE|CREDIT\s+NOTE|DEBIT\s+NOTE|RECEIPT|PROFORMA)\s*$",
                "", line, flags=re.IGNORECASE,
            ).strip()
            if COMPANY_SUFFIXES.search(clean) and not _is_bad_vendor_line(clean) and not _is_buyer_line(clean):
                return _clean_vendor(clean)[:200]

    # ── Strategy 2: Explicit seller labels ───────────────────────────────────
    for pat in VENDOR_EXTRACT_PATTERNS:
        m = pat.search(search_text)
        if m:
            candidate = _clean_vendor(m.group(1).strip())
            if not _is_bad_vendor_line(candidate) and not _is_buyer_line(candidate):
                return candidate[:200]

    # ── Strategy 3: Company suffix scan (buyer-aware) ─────────────────────────
    lines = [l.strip() for l in search_text.split("\n") if l.strip()]
    for line in lines:
        if not COMPANY_SUFFIXES.search(line):
            continue
        if _is_bad_vendor_line(line) or _is_buyer_line(line):
            continue
        # If a single line contains multiple company names (two-column OCR merge),
        # extract only the first one.
        candidate = _first_company_in_line(line)
        if not candidate:
            candidate = line
        cleaned = _clean_vendor(candidate)
        if ":" in cleaned:
            parts = cleaned.split(":", 1)
            cleaned = parts[1].strip() if COMPANY_SUFFIXES.search(parts[1]) else parts[0].strip()
        result = _clean_vendor(cleaned)
        if result and not _is_bad_vendor_line(result) and not _is_buyer_line(result):
            return result[:200]

    # ── Strategy 4: GSTIN-holder heuristic (skip buyer GSTIN) ────────────────
    CIN_PATTERN = re.compile(r"\bCIN\s*[:\s]*[A-Z]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}", re.IGNORECASE)
    all_lines = [l.strip() for l in clean_text.split("\n") if l.strip()]
    for i, line in enumerate(all_lines):
        if _is_buyer_line(line):
            continue
        if not (GST_PATTERN.search(line) or CIN_PATTERN.search(line)):
            continue
        for j in range(i - 1, max(i - 5, -1), -1):
            candidate = all_lines[j].strip()
            if not candidate or _is_bad_vendor_line(candidate) or _is_buyer_line(candidate):
                continue
            if GST_PATTERN.search(candidate) or CIN_PATTERN.search(candidate):
                continue
            if re.match(r"^(GSTIN|GST|PAN|CIN|TAN|Phone|Email|Fax)\s*", candidate, re.IGNORECASE):
                continue
            if re.match(r"^\d+.*,", candidate):
                continue
            return _clean_vendor(candidate)[:200]

    # ── Strategy 5: Give up ───────────────────────────────────────────────────
    logger.warning("Could not extract vendor name from text")
    return None


def extract_total_amount(text: str) -> Optional[float]:
    """Extract total amount with preference for specific labels over generic 'Total'."""
    # Try specific patterns first (Grand Total, Amount Due, etc.)
    for pat in AMOUNT_PATTERNS_SPECIFIC:
        m = pat.search(text)
        if m:
            val = _parse_amount(m.group(1))
            if val and val > 0:
                return val

    # Try currency-prefixed "due" pattern (₹1,935.53 due)
    m = AMOUNT_CURRENCY_PATTERN.search(text)
    if m:
        val = _parse_amount(m.group(1))
        if val and val > 0:
            return val

    # Try general total patterns — if multiple, take the largest
    amounts = []
    for pat in AMOUNT_PATTERNS_GENERAL:
        for m in pat.finditer(text):
            val = _parse_amount(m.group(1))
            if val and val > 0:
                amounts.append(val)

    if amounts:
        return max(amounts)

    return None


def extract_invoice_number(text: str) -> Optional[str]:
    """Extract invoice number with improved patterns. Works line-by-line to avoid cross-line matches.

    All candidates must contain at least one digit — real invoice numbers always do.
    Handles OCR null-byte artifacts (e.g. CA/25\x0026/340 where \x00 replaces the dash).
    """
    patterns = [
        re.compile(r"(?:Invoice\s*Number|Invoice\s*No\.?|Inv\s*No\.?|Invoice\s*#|INVOICE\s*#)\s*[:\s#\-]*([A-Z0-9][\w\-/]{2,30})", re.IGNORECASE),
        re.compile(r"(?:Bill\s*No\.?|Bill\s*Number)\s*[:\s#\-]*([A-Z0-9][\w\-/]{2,30})", re.IGNORECASE),
        re.compile(r"(?:Receipt\s*Number)\s*[:\s#\-]*([A-Z0-9][\w\-/]{2,30})", re.IGNORECASE),
        re.compile(r"(?:Invoice|Inv)\s*[:.#\-]\s*([A-Z0-9][\w\-/]{2,30})", re.IGNORECASE),
        # Indian tax invoice format: CA/25-26/340, INV/2024-25/696
        # Also handles OCR null-byte artefacts where '-' becomes '\x00'
        re.compile(r"\b([A-Z]{2,6}[/\-]\d{2,4}[\-\x00]\d{2,4}[/\-]\d{1,6})\b", re.IGNORECASE),
    ]

    # Search line by line to avoid cross-line captures
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for pat in patterns:
            m = pat.search(line)
            if m:
                candidate = m.group(1).strip()
                # Must be at least 3 chars AND contain at least one digit
                # (filters prose matches like "invoice no signature required")
                if len(candidate) >= 3 and any(c.isdigit() for c in candidate):
                    # Normalise OCR null-byte artefacts back to dashes
                    candidate = candidate.replace("\x00", "-")
                    return candidate

    return None
