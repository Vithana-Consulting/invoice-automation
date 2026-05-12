from __future__ import annotations

import json
import logging
from typing import List

from app.config import settings
from app.core.exceptions import ParsingError
from app.models.domain import Invoice, LineItem
from app.parsers.base import InvoiceParser

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {"pdf", "jpg", "jpeg", "png", "tiff", "tif", "bmp"}


class LlamaParseParser(InvoiceParser):
    """AI-based parser using LlamaParse API.

    Requires LLAMAPARSE_API_KEY to be set in environment.
    """

    def supports(self, file_type: str) -> bool:
        return file_type.lower().lstrip(".") in SUPPORTED_TYPES

    def parse(self, file_path: str, file_type: str, buyer_hint=None) -> Invoice:
        if not settings.LLAMAPARSE_API_KEY:
            raise ParsingError(
                "LLAMAPARSE_API_KEY is not set. Cannot use LlamaParse parser."
            )

        ft = file_type.lower().lstrip(".")
        if not self.supports(ft):
            raise ParsingError(f"Unsupported file type: {ft}")

        try:
            from llama_parse import LlamaParse
        except ImportError:
            raise ParsingError(
                "llama-parse package not installed. Run: pip install llama-parse"
            )

        try:
            parser = LlamaParse(
                api_key=settings.LLAMAPARSE_API_KEY,
                result_type="markdown",
                verbose=False,
            )
            documents = parser.load_data(file_path)
        except Exception as e:
            raise ParsingError(f"LlamaParse API call failed: {e}")

        if not documents:
            raise ParsingError(f"LlamaParse returned no results for {file_path}")

        full_text = "\n".join(doc.text for doc in documents)

        if not full_text.strip():
            raise ParsingError(f"LlamaParse returned empty text for {file_path}")

        logger.info(
            "LlamaParse extracted %d characters from %s", len(full_text), file_path
        )

        # LlamaParse returns structured markdown. We parse it for invoice fields.
        invoice = self._extract_fields_from_markdown(full_text)
        invoice.raw_text = full_text[:50000]
        invoice.parser_mode = "llamaparse"
        return invoice

    def _extract_fields_from_markdown(self, text: str) -> Invoice:
        """Extract invoice fields from LlamaParse markdown output.

        Uses the improved shared extraction logic for vendor, amount, invoice#.
        """
        from app.parsers.extraction import extract_vendor_name, extract_total_amount, extract_invoice_number
        from app.parsers.tesseract_parser import (
            DUE_DATE_PATTERNS,
            GST_PATTERN,
            INVOICE_DATE_PATTERNS,
            PAN_PATTERN,
            SUBTOTAL_PATTERNS,
            TAX_AMOUNT_PATTERNS,
            UAN_PATTERN,
            _first_match,
            _parse_amount,
        )
        import re

        invoice_number = extract_invoice_number(text)
        vendor_name = extract_vendor_name(text)
        invoice_date = _first_match(text, INVOICE_DATE_PATTERNS)
        due_date = _first_match(text, DUE_DATE_PATTERNS)

        total_amount = extract_total_amount(text)

        # Tax: sum all matches
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

        gst_match = GST_PATTERN.search(text)
        gst_number = gst_match.group(1) if gst_match else None

        pan_match = PAN_PATTERN.search(text)
        pan_number = pan_match.group(1) if pan_match else None

        uan_match = UAN_PATTERN.search(text)
        uan_number = uan_match.group(1) if uan_match else None

        # Extract line items from markdown tables
        line_items = self._extract_line_items_from_markdown(text)

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
            pan_number=pan_number,
            uan_number=uan_number,
            currency=currency,
            confidence_scores={"llamaparse": 0.9},
        )

    def _extract_line_items_from_markdown(self, text: str) -> List[LineItem]:
        """Parse markdown tables for line items."""
        items = []
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # Detect markdown table (pipes)
            if "|" in line and i + 1 < len(lines) and "---" in lines[i + 1]:
                header_cells = [c.strip().lower() for c in line.split("|") if c.strip()]
                i += 2  # Skip header and separator

                desc_idx = self._find_md_col(header_cells, ["description", "item", "particular", "product", "name"])
                qty_idx = self._find_md_col(header_cells, ["qty", "quantity"])
                rate_idx = self._find_md_col(header_cells, ["rate", "price", "unit price"])
                amount_idx = self._find_md_col(header_cells, ["amount", "total", "value"])
                hsn_idx = self._find_md_col(header_cells, ["hsn", "sac"])

                while i < len(lines) and "|" in lines[i]:
                    cells = [c.strip() for c in lines[i].split("|") if c.strip()]
                    if cells:
                        desc = cells[desc_idx] if desc_idx is not None and desc_idx < len(cells) else ""
                        if desc and not desc.startswith("---"):
                            from app.parsers.tesseract_parser import _parse_amount

                            qty = _parse_amount(cells[qty_idx]) if qty_idx is not None and qty_idx < len(cells) else None
                            rate = _parse_amount(cells[rate_idx]) if rate_idx is not None and rate_idx < len(cells) else None
                            amt = _parse_amount(cells[amount_idx]) if amount_idx is not None and amount_idx < len(cells) else 0.0
                            hsn = cells[hsn_idx] if hsn_idx is not None and hsn_idx < len(cells) else None

                            items.append(LineItem(
                                description=desc,
                                quantity=qty,
                                unit_price=rate,
                                amount=amt or 0.0,
                                hsn_or_sac=hsn,
                            ))
                    i += 1
            else:
                i += 1
        return items

    def _find_md_col(self, header: list, keywords: list):
        for idx, col in enumerate(header):
            for kw in keywords:
                if kw in col:
                    return idx
        return None
