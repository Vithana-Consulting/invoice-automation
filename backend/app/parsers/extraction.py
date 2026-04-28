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


def extract_vendor_name(text: str) -> Optional[str]:
    """Extract vendor name using multiple strategies, ordered by confidence.

    Strategy 1: Explicit labels (From:, Vendor:, Invoice issued by:)
    Strategy 2: Company suffix detection (Pvt Ltd, LLC, etc.)
    Strategy 3: GSTIN-holder heuristic (line before/after GSTIN)
    Strategy 4: None (prefer no vendor over wrong vendor)
    """
    # Pre-clean markdown from text for pattern matching
    clean_text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)

    # Strategy 1: Labeled vendor
    for pat in VENDOR_EXTRACT_PATTERNS:
        m = pat.search(clean_text)
        if m:
            candidate = _clean_vendor(m.group(1).strip())
            if not _is_bad_vendor_line(candidate):
                return candidate[:200]

    # Strategy 2: Company suffix — find lines containing known business entity types
    lines = [l.strip() for l in clean_text.split("\n") if l.strip()]
    for line in lines:
        if COMPANY_SUFFIXES.search(line) and not _is_bad_vendor_line(line):
            cleaned = _clean_vendor(line)
            if ":" in cleaned:
                parts = cleaned.split(":", 1)
                if COMPANY_SUFFIXES.search(parts[1]):
                    cleaned = parts[1].strip()
                elif COMPANY_SUFFIXES.search(parts[0]):
                    cleaned = parts[0].strip()
            return _clean_vendor(cleaned)[:200]

    # Strategy 3: CIN/GSTIN-holder — look for CIN or GSTIN and work backwards
    CIN_PATTERN = re.compile(r"\bCIN\s*[:\s]*[A-Z]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}", re.IGNORECASE)
    for i, line in enumerate(lines):
        if GST_PATTERN.search(line) or CIN_PATTERN.search(line):
            # Walk backwards to find the vendor name (skip label lines, addresses)
            for j in range(i - 1, max(i - 5, -1), -1):
                candidate = lines[j].strip()
                if not candidate or _is_bad_vendor_line(candidate):
                    continue
                if GST_PATTERN.search(candidate) or CIN_PATTERN.search(candidate):
                    continue
                if re.match(r"^(GSTIN|GST|PAN|CIN|TAN|Phone|Email|Fax)\s*", candidate, re.IGNORECASE):
                    continue
                # Skip address-like lines (contain numbers followed by comma)
                if re.match(r"^\d+.*,", candidate):
                    continue
                return _clean_vendor(candidate)[:200]
            # Check if GSTIN line has vendor name before the number
            before_gst = GST_PATTERN.split(line)[0].strip()
            if before_gst and len(before_gst) > 5 and not _is_bad_vendor_line(before_gst):
                before_gst = re.sub(r"^(?:GSTIN|GST)\s*[:\s]*", "", before_gst, flags=re.IGNORECASE).strip()
                if before_gst:
                    return _clean_vendor(before_gst)[:200]

    # Strategy 4: Return None — better to have no vendor than wrong vendor
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
    """Extract invoice number with improved patterns. Works line-by-line to avoid cross-line matches."""
    patterns = [
        re.compile(r"(?:Invoice\s*Number|Invoice\s*No\.?|Inv\s*No\.?|Invoice\s*#|INVOICE\s*#)\s*[:\s#\-]*([A-Z0-9][\w\-/]{2,30})", re.IGNORECASE),
        re.compile(r"(?:Bill\s*No\.?|Bill\s*Number)\s*[:\s#\-]*([A-Z0-9][\w\-/]{2,30})", re.IGNORECASE),
        re.compile(r"(?:Receipt\s*Number)\s*[:\s#\-]*([A-Z0-9][\w\-/]{2,30})", re.IGNORECASE),
        re.compile(r"(?:Invoice|Inv)\s*[:.#\-]\s*([A-Z0-9][\w\-/]{2,30})", re.IGNORECASE),
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
                if len(candidate) >= 3:
                    return candidate

    return None
