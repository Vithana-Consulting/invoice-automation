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
import tempfile

from app.config import settings
from app.core.exceptions import ParsingError
from app.models.domain import BankDetails, Invoice, LineItem, TaxBreakup
from app.parsers.base import InvoiceParser
from app.parsers.llm_providers import get_llm_provider

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {"pdf", "jpg", "jpeg", "png", "tiff", "tif", "bmp"}

IMAGE_TYPES = {"jpg", "jpeg", "png", "tiff", "tif", "bmp", "webp"}

EXTRACTION_PROMPT = """You are an invoice data extraction system. Extract structured data from this invoice.

Return ONLY valid JSON with these fields (use null for missing fields):
{
  "vendor_name": "The company/business that ISSUED this invoice (the seller, not the buyer)",
  "vendor_address": "Full address of the vendor/seller (street, city, state, pincode) or null",
  "buyer_name": "The company/person the invoice is billed TO (the buyer/customer)",
  "invoice_number": "The invoice/bill number",
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

IMPORTANT:
- vendor_name is the SELLER/ISSUER, not the buyer/customer
- buyer_gst_number is the GSTIN printed as "Billed To" / "Ship To" / "Customer GSTIN"
- For amounts, use numeric values without currency symbols or commas
- Extract CGST, SGST, IGST amounts separately in tax_breakup (look for tax summary table)
- Extract bank/payment details if present on the invoice (often at the bottom)
- If this is not an invoice (e.g., receipt, ticket, form), still extract what you can
- hsn_or_sac: look for columns labelled "HSN", "SAC", "HSN/SAC", "HSN Code", "SAC Code" on every line item row. For Indian service invoices, SAC codes are 6-digit numbers (e.g. 998211, 998314). Extract even if the column header is abbreviated. If no code is printed on a line item, return null for that item.
- Return ONLY the JSON object, no other text"""


def _pdf_to_images(pdf_path: str, dpi: int = 200) -> list[str]:
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


class LLMParser(InvoiceParser):
    """LLM parser with pluggable providers and vision support."""

    def supports(self, file_type: str) -> bool:
        return file_type.lower().lstrip(".") in SUPPORTED_TYPES

    def parse(self, file_path: str, file_type: str) -> Invoice:
        api_key = settings.LLM_API_KEY
        provider_name = settings.LLM_PROVIDER.lower()
        model = settings.LLM_MODEL

        if not api_key:
            raise ParsingError(
                "LLM_API_KEY is not set in .env. "
                "Set LLM_PROVIDER, LLM_MODEL, and LLM_API_KEY to use the LLM parser."
            )

        ft = file_type.lower().lstrip(".")
        if not self.supports(ft):
            raise ParsingError(f"Unsupported file type: {ft}")

        try:
            provider = get_llm_provider(
                name=provider_name, api_key=api_key,
                model=model, base_url=settings.LLM_BASE_URL,
            )
        except ValueError as e:
            raise ParsingError(str(e))

        # Choose strategy: vision (direct images) or text (OCR → LLM)
        if provider.supports_vision():
            return self._parse_with_vision(provider, file_path, ft, provider_name, model)
        else:
            return self._parse_with_text(provider, file_path, ft, provider_name, model)

    def _parse_with_vision(self, provider, file_path: str, ft: str,
                           provider_name: str, model: str) -> Invoice:
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

            response_text = provider.call_with_images(EXTRACTION_PROMPT, image_paths)
            if not response_text:
                raise ParsingError(f"LLM returned empty response for {file_path}")
            return self._parse_response(response_text, provider_name, model, file_path)

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

    def _parse_with_text(self, provider, file_path: str, ft: str,
                         provider_name: str, model: str) -> Invoice:
        """Fallback: OCR → text → LLM (for providers without vision)."""
        from app.parsers.tesseract_parser import TesseractParser

        text_parser = TesseractParser()
        base_invoice = text_parser.parse(file_path, ft)
        raw_text = base_invoice.raw_text or ""

        if not raw_text.strip():
            raise ParsingError(f"No text extracted from {file_path}")

        prompt = EXTRACTION_PROMPT + "\n\nInvoice text:\n" + raw_text[:15000]

        try:
            response_text = provider.call(prompt)
            invoice = self._parse_response(response_text, provider_name, model, file_path)
            invoice.raw_text = raw_text[:50000]
            return invoice
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
            parser_mode=f"llm:{provider_name}/{model}",
            confidence_scores={"llm": 0.95, "vendor_name": 0.95, "total_amount": 0.95},
        )
