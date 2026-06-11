from __future__ import annotations

import os
import shutil
from abc import ABC, abstractmethod
from typing import Callable, Optional, Tuple

from app.models.domain import Invoice
from app.utils.document_converter import WORD_TYPES


class InvoiceParser(ABC):
    """Abstract interface for all invoice parsers.

    Every parser -- OCR-based, AI-based, or future hybrid -- implements
    this contract. The orchestrator (invoice_service) calls parse() and
    does not know which implementation is active.

    To add a new parser:
      1. Create a class extending InvoiceParser.
      2. Register it in app/parsers/__init__.py _REGISTRY.
    """

    @abstractmethod
    def parse(self, file_path: str, file_type: str,
              buyer_hint: Optional[dict] = None) -> Invoice:
        """Extract invoice metadata from a document file.

        Args:
            file_path: Absolute path to the PDF or image file.
            file_type: File extension without dot (pdf, jpg, png, tiff).
            buyer_hint: Optional dict with keys legal_name, gst_number, pan_number
                        identifying the buyer/recipient (your company). Injected into
                        the LLM prompt so the AI never mistakes your company for the vendor.

        Returns:
            Invoice domain object with all extracted fields.

        Raises:
            ParsingError: If the document cannot be parsed.
        """
        ...

    @abstractmethod
    def supports(self, file_type: str) -> bool:
        """Check if this parser supports the given file type."""
        ...

    @staticmethod
    def _prepare_source(file_path: str, file_type: str) -> Tuple[str, str, Callable[[], None]]:
        """Normalise a source document for the PDF/image parse pipeline.

        Word documents (.doc/.docx) are transparently converted to a temporary
        PDF ("convert-then-parse"); every other type is passed through unchanged.

        Returns ``(path, normalized_extension, cleanup)`` — call ``cleanup()`` in
        a ``finally`` block to remove any temporary artifacts created here.
        """
        ft = file_type.lower().lstrip(".")
        if ft in WORD_TYPES:
            from app.utils.document_converter import convert_word_to_pdf
            pdf_path = convert_word_to_pdf(file_path)
            tmp_dir = os.path.dirname(pdf_path)
            return pdf_path, "pdf", lambda: shutil.rmtree(tmp_dir, ignore_errors=True)
        return file_path, ft, lambda: None
