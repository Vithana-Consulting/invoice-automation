"""Normalization helpers for logical (semantic) duplicate detection.

Byte-level dedup (SHA-256 content_hash) only catches identical files. A re-scanned
or re-saved copy of the same invoice has different bytes but the same logical
identity. These normalizers produce comparison keys that ignore cosmetic
differences (case, whitespace, separator punctuation) so such copies can be
flagged.

Kept deliberately conservative — these drive a *warning*, never a hard block,
because a re-issue can be a legitimate correction.
"""
from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")
# Separators commonly inserted/dropped inconsistently in invoice numbers.
_INV_SEPARATORS = re.compile(r"[\s\-/]+")


def normalize_vendor(vendor_name: str | None) -> str:
    """Lowercase, collapse internal whitespace, strip ends. None -> ''."""
    if not vendor_name:
        return ""
    return _WHITESPACE.sub(" ", vendor_name).strip().lower()


def normalize_invoice_number(invoice_number: str | None) -> str:
    """Uppercase, strip, and drop spaces / '-' / '/' separators. None -> ''.

    Conservative: only removes separator punctuation so that e.g. ``INV-001``,
    ``inv 001`` and ``INV/001`` collapse to the same key.
    """
    if not invoice_number:
        return ""
    return _INV_SEPARATORS.sub("", invoice_number.strip()).upper()
