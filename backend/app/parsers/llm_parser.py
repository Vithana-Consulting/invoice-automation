"""Pluggable LLM-based invoice parser with vision support.

When the provider supports vision (GPT-4o, Claude, Gemini):
  - PDFs are converted to images and sent directly to the LLM
  - Images (JPG, PNG) are sent directly — no OCR needed
  - No Tesseract, no pdfplumber, no external OCR dependency

When the provider does NOT support vision:
  - Falls back to Tesseract OCR → text → LLM

Config (.env):
  PARSER_MODE=llm
  LLM_PROVIDER=openai
  LLM_MODEL=gpt-4o
  LLM_API_KEY=sk-...
  LLM_BASE_URL=                # optional
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime

from app.config import settings
from app.core.exceptions import ParsingError
from app.core.key_pool import KeyExhaustedError, get_key_pool, run_with_rotation
from app.models.domain import BankDetails, Invoice, LineItem, TaxBreakup
from app.parsers.base import InvoiceParser
from app.parsers.llm_providers import get_llm_provider

logger = logging.getLogger(__name__)

MAX_PARSE_ATTEMPTS = 3

SUPPORTED_TYPES = {"pdf", "jpg", "jpeg", "png", "tiff", "tif", "bmp"}

IMAGE_TYPES = {"jpg", "jpeg", "png", "tiff", "tif", "bmp", "webp"}

# ---------------------------------------------------------------------------
# GSTIN validation
# ---------------------------------------------------------------------------

_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_GSTIN_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]$")


def _validate_gstin_checksum(gstin: str) -> bool:
    """Validate GSTIN format + checksum (detects single-char transpositions)."""
    if not _GSTIN_PATTERN.match(gstin.upper()):
        return False
    total = 0
    for i, ch in enumerate(gstin.upper()[:14]):
        val = _GSTIN_CHARS.index(ch)
        if i % 2 == 1:
            val *= 2
        total += val // 36 + val % 36
    expected_idx = (36 - (total % 36)) % 36
    return gstin.upper()[14] == _GSTIN_CHARS[expected_idx]


# ---------------------------------------------------------------------------
# Legal entity suffixes used for vendor_name completeness check
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES = [
    "Private Limited", "Limited", "LLP", "Ltd", "Inc", "Corp", "Pvt",
    "Associates", "Enterprises", "Services", "Solutions", "Works",
    "Technologies", "Consulting", "Systems",
]


def _validate_invoice(invoice) -> list[str]:
    """Return a list of human-readable validation error strings (empty = valid)."""
    errors: list[str] = []

    # 1. invoice_number
    if not invoice.invoice_number or len(str(invoice.invoice_number).strip()) < 3:
        errors.append("invoice_number is missing or too short (must be ≥ 3 characters)")

    # 2. vendor_name
    if not invoice.vendor_name or len(str(invoice.vendor_name).strip()) < 2:
        errors.append("vendor_name is missing or too short (must be ≥ 2 characters)")

    # 3. total_amount
    if invoice.total_amount is None or invoice.total_amount <= 0:
        errors.append("total_amount is missing or not > 0")

    # 4. invoice_date
    raw_date = invoice.date
    if not raw_date:
        errors.append("invoice_date is missing")
    else:
        try:
            datetime.strptime(str(raw_date).strip(), "%Y-%m-%d")
        except ValueError:
            errors.append(f"invoice_date '{raw_date}' is not a valid YYYY-MM-DD date")

    # 5. vendor GSTIN — checksum + PAN cross-check
    if invoice.gst_number:
        gstin = str(invoice.gst_number).strip().upper()
        if len(gstin) != 15:
            errors.append(
                f"vendor_gstin '{invoice.gst_number}' is {len(gstin)} characters — must be exactly 15. "
                f"Format: <2-digit state><10-char PAN><1-digit entity><Z><1-char check>. "
                f"Re-read every character from the invoice."
            )
        elif not _validate_gstin_checksum(gstin):
            errors.append(
                f"vendor_gstin '{invoice.gst_number}' failed format/checksum — "
                "re-read it character by character from the invoice"
            )
        # Cross-check: GSTIN positions 3-12 must equal vendor PAN
        if invoice.pan_number:
            embedded_pan = gstin[2:12] if len(gstin) >= 12 else ""
            parsed_pan = str(invoice.pan_number).strip().upper()
            if embedded_pan and embedded_pan != parsed_pan:
                errors.append(
                    f"vendor_gstin '{invoice.gst_number}' embedded PAN ('{embedded_pan}') does not match "
                    f"parsed pan_number ('{parsed_pan}'). One of the two is mis-read — re-read both fields. "
                    f"GSTIN positions 3-12 must equal the PAN exactly."
                )

    # 6. buyer GSTIN — checksum + PAN cross-check
    if invoice.buyer_gst_number:
        b_gstin = str(invoice.buyer_gst_number).strip().upper()
        if len(b_gstin) != 15:
            errors.append(
                f"buyer_gst_number '{invoice.buyer_gst_number}' is {len(b_gstin)} characters — must be exactly 15."
            )
        elif not _validate_gstin_checksum(b_gstin):
            errors.append(
                f"buyer_gst_number '{invoice.buyer_gst_number}' failed format/checksum — "
                "re-read it character by character from the invoice"
            )
        if getattr(invoice, "buyer_pan_number", None):
            embedded_pan = b_gstin[2:12] if len(b_gstin) >= 12 else ""
            parsed_pan = str(invoice.buyer_pan_number).strip().upper()
            if embedded_pan and embedded_pan != parsed_pan:
                errors.append(
                    f"buyer_gst_number '{invoice.buyer_gst_number}' embedded PAN ('{embedded_pan}') does not match "
                    f"parsed buyer_pan_number ('{parsed_pan}'). Re-read both fields."
                )

    # 7. vendor_name legal suffix check (only when vendor has a GSTIN — i.e. registered entity)
    if invoice.gst_number and invoice.vendor_name:
        name = invoice.vendor_name
        if not any(suffix.lower() in name.lower() for suffix in _LEGAL_SUFFIXES):
            errors.append(
                f"vendor_name '{name}' may be truncated — verify it includes the complete "
                "legal entity name (e.g. 'Private Limited', 'LLP') as printed on the invoice"
            )

    return errors


def _build_correction_section(errors: list[str], attempt: int, max_attempts: int) -> str:
    """Build the correction prompt appendix for retry attempts."""
    bullet_lines = "\n".join(f"  • {e}" for e in errors)

    gstin_errors = [e for e in errors if "gstin" in e.lower() or "gst" in e.lower()]
    gstin_extra = ""
    if gstin_errors:
        gstin_extra = (
            "\n\n【GSTIN Re-read Procedure】\n"
            "For each GSTIN error above:\n"
            "  1. Locate the label 'GSTIN' or 'GST No.' on the invoice image\n"
            "  2. Place your attention on the 15-character string immediately after the label\n"
            "  3. Read positions 1-2: should be a 2-digit state code (01–38)\n"
            "  4. Read positions 3-7: should be 5 uppercase letters (the PAN prefix)\n"
            "  5. Read positions 8-11: should be 4 digits\n"
            "  6. Read position 12: should be 1 uppercase letter\n"
            "  7. Read position 13: usually '1' (entity number)\n"
            "  8. Read position 14: MUST be the letter 'Z' — if you see '2' you may have misread it\n"
            "  9. Read position 15: the check character (any alphanumeric)\n"
            "  10. Cross-check: positions 3-12 (10 chars) should match the PAN if printed on the invoice\n"
        )

    return (
        f"\n\n─── CORRECTION REQUIRED (Attempt {attempt}/{max_attempts}) ───\n"
        f"Your previous extraction had {len(errors)} validation error(s) that must be fixed:\n"
        f"{bullet_lines}\n"
        f"{gstin_extra}\n"
        "General instructions:\n"
        "- Re-examine the invoice image carefully for each flagged field\n"
        "- Read every character individually — transposing or dropping even one causes ITC failure\n"
        "- For vendor_name: copy the COMPLETE legal name including 'Private Limited', 'LLP', etc.\n"
        "- Return the complete corrected JSON (all fields, not just the changed ones)\n"
        "─────────────────────────────────────────────────────────"
    )


EXTRACTION_PROMPT = """You are a precise invoice data extraction system with vision capability. Extract structured data from this invoice image with extremely high accuracy for compliance-critical fields.

Return ONLY valid JSON with these fields (use null for missing fields):
{
  "vendor_name": "The company/business that ISSUED this invoice (the seller, not the buyer)",
  "vendor_address": "Full address of the vendor/seller (street, city, state, pincode) or null",
  "buyer_name": "The company/person the invoice is billed TO (the buyer/customer)",
  "invoice_number": "The invoice/bill number — copy EXACTLY as printed, character by character",
  "invoice_date": "Date in YYYY-MM-DD format",
  "due_date": "Due date in YYYY-MM-DD format or null",
  "total_amount": 0.00,
  "tax_amount": 0.00,
  "subtotal": 0.00,
  "currency": "INR or USD or EUR or GBP",
  "gst_number": "GSTIN of the seller/vendor or null",
  "buyer_gst_number": "GSTIN of the buyer/recipient (Billed To / Ship To / Customer GSTIN) or null",
  "pan_number": "PAN of the seller/vendor or null",
  "buyer_pan_number": "PAN of the buyer/recipient or null",
  "tax_breakup": {
    "cgst_rate": null,
    "cgst_amount": null,
    "sgst_rate": null,
    "sgst_amount": null,
    "igst_rate": null,
    "igst_amount": null,
    "cess_amount": null
  },
  "bank_details": {
    "bank_name": "Bank name or null",
    "account_number": "Account number or null",
    "ifsc_code": "IFSC code or null",
    "branch": "Branch name or null",
    "account_holder": "Account holder name or null",
    "upi_id": "UPI ID if present or null"
  },
  "place_of_supply": "2-digit GST state code of place of supply (e.g. '29' for Karnataka) or null",
  "confidence_scores": {
    "invoice_number": 0.95,
    "vendor_name": 0.95,
    "total_amount": 0.95,
    "gst_number": 0.95
  },
  "line_items": [
    {
      "description": "item name",
      "quantity": 1,
      "unit_price": 100.00,
      "amount": 100.00,
      "hsn_or_sac": "HSN/SAC code or null",
      "tax_rate": 18.0,
      "cgst_amount": null,
      "sgst_amount": null,
      "igst_amount": null
    }
  ]
}

═══════════════════════════════════════════════════════
CRITICAL EXTRACTION RULES — READ CAREFULLY
═══════════════════════════════════════════════════════

【GSTIN — Compliance Critical】
A GSTIN is EXACTLY 15 characters in this fixed format:
  Position 1-2  : 2 digits (state code, e.g. 29, 33, 27, 07)
  Position 3-7  : 5 UPPERCASE letters (PAN chars 1-5)
  Position 8-11 : 4 digits (PAN chars 6-9)
  Position 12   : 1 UPPERCASE letter (PAN char 10)
  Position 13   : 1 digit or letter (entity number, usually '1')
  Position 14   : always the letter 'Z'
  Position 15   : 1 alphanumeric check character

HOW TO READ THE GSTIN FROM THE INVOICE IMAGE:
  1. Find the label "GSTIN", "GSTIN No.", "GST Reg. No.", "GST No." on the invoice
  2. The 15 characters immediately following that label are the GSTIN
  3. Count them: you must have exactly 15 characters
  4. Read each character individually — do NOT group or skim
  5. Common OCR confusion pairs to watch for: 0 vs O, 1 vs I vs L, 5 vs S, 8 vs B, 2 vs Z, 6 vs G
  6. The middle 10 characters (positions 3-12) are the vendor's PAN — if PAN is printed separately, cross-check they match
  7. Position 14 is ALWAYS the letter 'Z' — if you read something else, re-examine
  8. Set confidence_scores.gst_number = 1.0 only if every character is clearly legible; use 0.8 if any character required inference

gst_number = vendor/seller GSTIN (usually top-left of invoice, in vendor's letterhead)
buyer_gst_number = buyer/customer GSTIN (usually in Bill To / Ship To section)

【INVOICE NUMBER — ITC Critical】
  1. Find the label "Invoice No.", "Invoice Number", "Bill No.", "Ref No.", or "Invoice #"
  2. Copy the value CHARACTER BY CHARACTER — including all slashes, hyphens, and alphanumerics
  3. Do NOT paraphrase, reconstruct, or abbreviate
  4. Common formats: INV/2024-25/047, BCT/2025/0089, KFS-2025-0312, SPT/MAR25/00891
  5. After extracting, mentally re-read it from the document one more time to verify
  6. Set confidence_scores.invoice_number = 1.0 only if every character is unambiguous

【LINE ITEMS — Table Extraction】
  - Scan every row of the line-item table; extract ALL rows (not just the first few)
  - For each row: description, quantity, unit price, amount, HSN/SAC code, tax rate
  - HSN/SAC codes: 4-8 digit numbers in "HSN", "SAC", "HSN/SAC" column — extract even if the column is narrow
  - Do NOT skip rows where the description spans multiple lines — merge them
  - Tax rows (CGST, SGST, IGST) at the bottom of the table are NOT line items — put their amounts in tax_breakup instead

【AMOUNTS】
  - Use numeric values only — no ₹ symbols, commas, or spaces
  - total_amount = the final payable amount including all taxes
  - subtotal = pre-tax total (before CGST/SGST/IGST)
  - tax_amount = total tax (CGST+SGST or IGST)

【VENDOR NAME】
  - Copy the COMPLETE legal name: include "Private Limited", "LLP", "Pvt. Ltd.", etc.
  - vendor_name = seller/issuer (top of invoice, usually large text in letterhead)
  - Do NOT use the buyer's company name
  - The vendor is the party who SIGNED and ISSUED this invoice, not the party it was addressed TO

【CONFIDENCE SCORES】
  - 1.0 = every character unambiguous and clearly printed
  - 0.8-0.9 = field required careful reading or minor inference
  - 0.7 = field partially obscured or required guessing
  - Below 0.7 = field is unreliable

Return ONLY the JSON object — no markdown, no explanation, no preamble."""


_OCR_SUBS: list[tuple[str, str]] = [
    ("0", "O"), ("O", "0"),
    ("1", "I"), ("I", "1"),
    ("1", "L"), ("L", "1"),
    ("5", "S"), ("S", "5"),
    ("8", "B"), ("B", "8"),
    ("2", "Z"), ("Z", "2"),
    ("6", "G"), ("G", "6"),
    ("9", "Q"), ("Q", "9"),
]


def _try_fix_gstin(gstin: str) -> str | None:
    """Single-character OCR substitution search for a valid GSTIN.

    Tries every position × every substitution pair. Returns the first valid
    GSTIN found, or None if no correction produces a valid checksum.
    """
    g = gstin.strip().upper()
    if len(g) != 15:
        return None
    for i, ch in enumerate(g):
        for src, dst in _OCR_SUBS:
            if ch == src:
                candidate = g[:i] + dst + g[i+1:]
                if _validate_gstin_checksum(candidate):
                    return candidate
    return None


def _reconstruct_gstin_from_pan(pan: str, state_code: str) -> str | None:
    """If PAN is valid and state code is known, reconstruct GSTIN with correct check digit.

    GSTIN = state_code(2) + PAN(10) + entity_number(1) + 'Z' + check_char(1)
    We try entity numbers 1-9 and pick the first that produces a valid checksum.
    """
    from app.utils.gstin_utils import validate_pan_format
    pan = (pan or "").strip().upper()
    state_code = (state_code or "").strip()
    if not validate_pan_format(pan) or len(state_code) != 2 or not state_code.isdigit():
        return None
    for entity in "1234567890ABCDE":
        prefix = state_code + pan + entity + "Z"
        if len(prefix) != 14:
            continue
        total = 0
        for i, ch in enumerate(prefix):
            val = _GSTIN_CHARS.index(ch) if ch in _GSTIN_CHARS else 0
            if i % 2 == 1:
                val *= 2
            total += val // 36 + val % 36
        check_idx = (36 - (total % 36)) % 36
        candidate = prefix + _GSTIN_CHARS[check_idx]
        if _validate_gstin_checksum(candidate):
            return candidate
    return None


def _pdf_to_images(pdf_path: str, dpi: int = 300) -> list[str]:
    """Convert PDF pages to temporary PNG images. Returns list of file paths."""
    try:
        from pdf2image import convert_from_path
    except ImportError:
        raise ParsingError("pdf2image not installed. Run: pip install pdf2image")

    images = convert_from_path(pdf_path, dpi=dpi)
    paths = []
    for i, img in enumerate(images):
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(tmp.name, "PNG")
        paths.append(tmp.name)
    return paths


def _build_buyer_hint_section(buyer_hint: dict) -> str:
    """Build a prompt section that tells the AI who the buyer/recipient is.

    Prevents the AI from mistaking the client's name in the Bill-To box for the vendor.
    """
    lines = ["", "【BUYER IDENTITY — DO NOT USE AS VENDOR】"]
    if buyer_hint.get("legal_name"):
        lines.append(f"  Your client (the bill recipient) is: {buyer_hint['legal_name']}")
    if buyer_hint.get("gst_number"):
        lines.append(f"  Their GSTIN: {buyer_hint['gst_number']}")
    if buyer_hint.get("pan_number"):
        lines.append(f"  Their PAN: {buyer_hint['pan_number']}")
    lines += [
        "  If you see this name or GSTIN in the invoice's 'Bill To', 'Billed To', or address box,",
        "  that entity is the BUYER — not the vendor.",
        "  The vendor_name MUST be the other party: the one who issued and signed this invoice.",
    ]
    return "\n".join(lines)


class LLMParser(InvoiceParser):
    """LLM parser with pluggable providers and vision support."""

    def supports(self, file_type: str) -> bool:
        return file_type.lower().lstrip(".") in SUPPORTED_TYPES

    def parse(self, file_path: str, file_type: str,
              buyer_hint: dict | None = None) -> Invoice:
        provider_name = settings.LLM_PROVIDER.lower()
        model = settings.LLM_MODEL
        base_url = settings.LLM_BASE_URL

        # LLM_API_KEY may hold a comma/newline-separated POOL of keys. On a rate
        # limit (429) or failure the pool rotates to the next key so a single
        # exhausted key never sinks the whole demo.
        pool = get_key_pool("llm", settings.LLM_API_KEY,
                            cooldown_seconds=settings.KEY_POOL_COOLDOWN_SECONDS)
        if len(pool) == 0:
            raise ParsingError(
                "LLM_API_KEY is not set in .env. "
                "Set LLM_PROVIDER, LLM_MODEL, and LLM_API_KEY to use the LLM parser. "
                "Multiple keys can be supplied comma-separated for automatic rotation."
            )
        if len(pool) > 1:
            logger.info("LLM parser using a pool of %d API keys (rotation enabled)", len(pool))

        ft = file_type.lower().lstrip(".")
        if not self.supports(ft):
            raise ParsingError(f"Unsupported file type: {ft}")

        # Capability probe — provider class decides vision support (key-agnostic,
        # no API call is made by the constructor).
        try:
            probe = get_llm_provider(
                name=provider_name, api_key=pool.acquire(),
                model=model, base_url=base_url,
            )
        except ValueError as e:
            raise ParsingError(str(e))

        # Choose strategy: vision (direct images) or text (OCR → LLM)
        if probe.supports_vision():
            return self._parse_with_vision(pool, file_path, ft, provider_name, model, base_url, buyer_hint)
        else:
            return self._parse_with_text(pool, file_path, ft, provider_name, model, base_url, buyer_hint)

    def _call_llm(self, pool, provider_name: str, model: str, base_url: str,
                  prompt: str, image_paths: list[str] | None = None) -> str:
        """Invoke the LLM through the key pool, rotating on rate-limit/failure.

        A fresh provider is built per attempt bound to the active key, so each
        rotation actually swaps the credential used for the API call.
        """
        def _fn(key: str) -> str:
            provider = get_llm_provider(
                name=provider_name, api_key=key, model=model, base_url=base_url,
            )
            if image_paths is not None:
                return provider.call_with_images(prompt, image_paths)
            return provider.call(prompt)

        try:
            return run_with_rotation(pool, _fn)
        except KeyExhaustedError as e:
            raise ParsingError(
                f"All LLM API keys are rate-limited or failing: {e}"
            )

    def _parse_with_vision(self, pool, file_path: str, ft: str,
                           provider_name: str, model: str, base_url: str = "",
                           buyer_hint: dict | None = None) -> Invoice:
        """Send document images directly to the LLM — no OCR needed."""
        tmp_images = []
        try:
            if ft == "pdf":
                image_paths = _pdf_to_images(file_path)
                tmp_images = image_paths  # track for cleanup
            elif ft in IMAGE_TYPES:
                image_paths = [file_path]
            else:
                raise ParsingError(f"Cannot process {ft} with vision")

            if not image_paths:
                raise ParsingError(f"No images extracted from {file_path}")

            logger.info("Sending %d image(s) to %s/%s for extraction", len(image_paths), provider_name, model)

            base_prompt = EXTRACTION_PROMPT
            if buyer_hint:
                base_prompt += _build_buyer_hint_section(buyer_hint)

            last_invoice = None
            last_errors: list[str] = []

            for attempt in range(1, MAX_PARSE_ATTEMPTS + 1):
                prompt = base_prompt
                if attempt > 1 and last_errors:
                    prompt += _build_correction_section(last_errors, attempt, MAX_PARSE_ATTEMPTS)

                response_text = self._call_llm(pool, provider_name, model, base_url,
                                               prompt, image_paths=image_paths)
                if not response_text:
                    raise ParsingError(f"LLM returned empty response for {file_path}")

                last_invoice = self._parse_response(response_text, provider_name, model, file_path)
                last_errors = _validate_invoice(last_invoice)

                if not last_errors:
                    if attempt > 1:
                        logger.info(
                            "Invoice %s validated successfully on attempt %d",
                            file_path, attempt,
                        )
                    return last_invoice

                logger.warning(
                    "Invoice %s attempt %d/%d validation errors: %s",
                    file_path, attempt, MAX_PARSE_ATTEMPTS, last_errors,
                )

            # Exhausted retries — attempt auto-correction before stripping GSTINs.
            if last_invoice is not None:
                if last_invoice.gst_number and not _validate_gstin_checksum(str(last_invoice.gst_number).strip().upper()):
                    raw_gstin = str(last_invoice.gst_number).strip().upper()
                    fixed = _try_fix_gstin(raw_gstin)
                    if not fixed and last_invoice.pan_number:
                        # Derive state code from buyer GSTIN or place_of_supply as fallback
                        state_code = ""
                        if last_invoice.buyer_gst_number and len(str(last_invoice.buyer_gst_number)) >= 2:
                            state_code = str(last_invoice.buyer_gst_number)[:2]
                        elif last_invoice.place_of_supply:
                            sc = str(last_invoice.place_of_supply).strip()
                            if sc.isdigit() and len(sc) == 2:
                                state_code = sc
                        if state_code:
                            fixed = _reconstruct_gstin_from_pan(str(last_invoice.pan_number), state_code)
                    if fixed:
                        logger.info("Auto-corrected vendor GSTIN '%s' → '%s'", raw_gstin, fixed)
                        last_invoice.gst_number = fixed
                    else:
                        logger.warning("Stripping invalid vendor GSTIN '%s' — no auto-correction found", raw_gstin)
                        last_invoice.gst_number = None

                if last_invoice.buyer_gst_number and not _validate_gstin_checksum(str(last_invoice.buyer_gst_number).strip().upper()):
                    raw_bgstin = str(last_invoice.buyer_gst_number).strip().upper()
                    fixed_b = _try_fix_gstin(raw_bgstin)
                    if fixed_b:
                        logger.info("Auto-corrected buyer GSTIN '%s' → '%s'", raw_bgstin, fixed_b)
                        last_invoice.buyer_gst_number = fixed_b
                    else:
                        logger.warning("Stripping invalid buyer GSTIN '%s' — no auto-correction found", raw_bgstin)
                        last_invoice.buyer_gst_number = None
            logger.error(
                "Invoice %s failed validation after %d attempts. "
                "Returning best-effort result. Errors: %s",
                file_path, MAX_PARSE_ATTEMPTS, last_errors,
            )
            return last_invoice

        except ParsingError:
            raise
        except Exception as e:
            raise ParsingError(f"Vision parsing failed for {file_path}: {type(e).__name__}: {e}")
        finally:
            # Cleanup temporary images
            for tmp in tmp_images:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def _parse_with_text(self, pool, file_path: str, ft: str,
                         provider_name: str, model: str, base_url: str = "",
                         buyer_hint: dict | None = None) -> Invoice:
        """Fallback: OCR → text → LLM (for providers without vision)."""
        from app.parsers.tesseract_parser import TesseractParser

        text_parser = TesseractParser()
        base_invoice = text_parser.parse(file_path, ft)
        raw_text = base_invoice.raw_text or ""

        if not raw_text.strip():
            raise ParsingError(f"No text extracted from {file_path}")

        base_prompt = EXTRACTION_PROMPT
        if buyer_hint:
            base_prompt += _build_buyer_hint_section(buyer_hint)
        base_prompt += "\n\nInvoice text:\n" + raw_text[:15000]

        try:
            last_invoice = None
            last_errors: list[str] = []

            for attempt in range(1, MAX_PARSE_ATTEMPTS + 1):
                prompt = base_prompt
                if attempt > 1 and last_errors:
                    prompt += _build_correction_section(last_errors, attempt, MAX_PARSE_ATTEMPTS)

                response_text = self._call_llm(pool, provider_name, model, base_url, prompt)
                last_invoice = self._parse_response(response_text, provider_name, model, file_path)
                last_invoice.raw_text = raw_text[:50000]
                last_errors = _validate_invoice(last_invoice)

                if not last_errors:
                    if attempt > 1:
                        logger.info(
                            "Invoice %s validated successfully on attempt %d",
                            file_path, attempt,
                        )
                    return last_invoice

                logger.warning(
                    "Invoice %s attempt %d/%d validation errors: %s",
                    file_path, attempt, MAX_PARSE_ATTEMPTS, last_errors,
                )

            # Exhausted retries — attempt auto-correction before stripping GSTINs.
            if last_invoice is not None:
                if last_invoice.gst_number and not _validate_gstin_checksum(str(last_invoice.gst_number).strip().upper()):
                    raw_gstin = str(last_invoice.gst_number).strip().upper()
                    fixed = _try_fix_gstin(raw_gstin)
                    if not fixed and last_invoice.pan_number:
                        # Derive state code from buyer GSTIN or place_of_supply as fallback
                        state_code = ""
                        if last_invoice.buyer_gst_number and len(str(last_invoice.buyer_gst_number)) >= 2:
                            state_code = str(last_invoice.buyer_gst_number)[:2]
                        elif last_invoice.place_of_supply:
                            sc = str(last_invoice.place_of_supply).strip()
                            if sc.isdigit() and len(sc) == 2:
                                state_code = sc
                        if state_code:
                            fixed = _reconstruct_gstin_from_pan(str(last_invoice.pan_number), state_code)
                    if fixed:
                        logger.info("Auto-corrected vendor GSTIN '%s' → '%s'", raw_gstin, fixed)
                        last_invoice.gst_number = fixed
                    else:
                        logger.warning("Stripping invalid vendor GSTIN '%s' — no auto-correction found", raw_gstin)
                        last_invoice.gst_number = None

                if last_invoice.buyer_gst_number and not _validate_gstin_checksum(str(last_invoice.buyer_gst_number).strip().upper()):
                    raw_bgstin = str(last_invoice.buyer_gst_number).strip().upper()
                    fixed_b = _try_fix_gstin(raw_bgstin)
                    if fixed_b:
                        logger.info("Auto-corrected buyer GSTIN '%s' → '%s'", raw_bgstin, fixed_b)
                        last_invoice.buyer_gst_number = fixed_b
                    else:
                        logger.warning("Stripping invalid buyer GSTIN '%s' — no auto-correction found", raw_bgstin)
                        last_invoice.buyer_gst_number = None
            logger.error(
                "Invoice %s failed validation after %d attempts. "
                "Returning best-effort result. Errors: %s",
                file_path, MAX_PARSE_ATTEMPTS, last_errors,
            )
            return last_invoice

        except ParsingError:
            raise
        except Exception as e:
            logger.error("LLM text call failed, returning regex result: %s", e)
            return base_invoice

    def _parse_response(self, response_text: str, provider_name: str,
                        model: str, file_path: str) -> Invoice:
        """Parse LLM JSON response into Invoice object."""
        if not response_text:
            raise ParsingError(f"LLM returned empty response for {file_path}")

        # Strip markdown code fences
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("LLM returned invalid JSON: %s\nResponse: %s", e, text[:500])
            raise ParsingError(f"LLM returned invalid JSON: {e}")

        line_items = []
        for item in data.get("line_items", []):
            if isinstance(item, dict) and item.get("description"):
                line_items.append(LineItem(
                    description=item.get("description", ""),
                    quantity=item.get("quantity"),
                    unit_price=item.get("unit_price"),
                    amount=float(item.get("amount", 0)),
                    hsn_or_sac=item.get("hsn_or_sac"),
                    tax_rate=item.get("tax_rate"),
                    cgst_amount=item.get("cgst_amount"),
                    sgst_amount=item.get("sgst_amount"),
                    igst_amount=item.get("igst_amount"),
                ))

        # Parse tax breakup
        tax_breakup = None
        tb = data.get("tax_breakup")
        if isinstance(tb, dict) and any(v is not None for v in tb.values()):
            tax_breakup = TaxBreakup(**{k: tb.get(k) for k in TaxBreakup.model_fields})

        # Parse bank details
        bank_details = None
        bd = data.get("bank_details")
        if isinstance(bd, dict) and any(v is not None for v in bd.values()):
            bank_details = BankDetails(**{k: bd.get(k) for k in BankDetails.model_fields})

        return Invoice(
            invoice_number=data.get("invoice_number"),
            vendor_name=data.get("vendor_name"),
            vendor_address=data.get("vendor_address"),
            date=data.get("invoice_date"),
            due_date=data.get("due_date"),
            total_amount=float(data["total_amount"]) if data.get("total_amount") else None,
            tax_amount=float(data["tax_amount"]) if data.get("tax_amount") else None,
            subtotal=float(data["subtotal"]) if data.get("subtotal") else None,
            line_items=line_items,
            tax_breakup=tax_breakup,
            bank_details=bank_details,
            buyer_gst_number=data.get("buyer_gst_number"),
            gst_number=data.get("gst_number"),
            pan_number=data.get("pan_number"),
            buyer_pan_number=data.get("buyer_pan_number"),
            currency=data.get("currency", "INR"),
            place_of_supply=data.get("place_of_supply"),
            parser_mode=f"llm:{provider_name}/{model}",
            confidence_scores=data.get("confidence_scores") or {"llm": 0.9},
        )
