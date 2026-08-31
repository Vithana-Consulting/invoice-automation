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

        Two independent normalisation steps, both transparent to callers:
          1. Remote acquisition — when STORAGE_BACKEND=s3, `file_path` is an
             ``s3://`` URI. Tesseract/pdf2image/LibreOffice all require an
             actual local file, so it's downloaded to a `tempfile` first.
          2. Word documents (.doc/.docx) are converted to a temporary PDF
             ("convert-then-parse"); every other type passes through unchanged.

        Returns ``(path, normalized_extension, cleanup)`` — call ``cleanup()`` in
        a ``finally`` block to remove any temporary artifacts created here.
        """
        from app.services.attachment_storage import is_remote, download_to_temp

        ft = file_type.lower().lstrip(".")
        cleanups: list[Callable[[], None]] = []

        local_path = file_path
        if is_remote(file_path):
            local_path, s3_cleanup = download_to_temp(file_path)
            cleanups.append(s3_cleanup)

        if ft in WORD_TYPES:
            from app.utils.document_converter import convert_word_to_pdf
            try:
                pdf_path = convert_word_to_pdf(local_path)
            except Exception:
                for c in cleanups:
                    c()
                raise
            tmp_dir = os.path.dirname(pdf_path)
            cleanups.append(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))
            result_path, result_ft = pdf_path, "pdf"
        else:
            result_path, result_ft = local_path, ft

        def cleanup() -> None:
            for c in cleanups:
                try:
                    c()
                except Exception:
                    pass

        return result_path, result_ft, cleanup
