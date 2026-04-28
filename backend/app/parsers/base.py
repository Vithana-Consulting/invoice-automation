from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.domain import Invoice


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
    def parse(self, file_path: str, file_type: str) -> Invoice:
        """Extract invoice metadata from a document file.

        Args:
            file_path: Absolute path to the PDF or image file.
            file_type: File extension without dot (pdf, jpg, png, tiff).

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
