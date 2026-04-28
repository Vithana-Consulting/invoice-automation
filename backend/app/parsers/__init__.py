"""Parser factory with strategy pattern.

The active parser is determined by the PARSER_MODE environment variable.
To add a new parser:
  1. Create a class extending InvoiceParser in a new module.
  2. Add it to _REGISTRY below.
  3. Set PARSER_MODE=<your_key> in .env.
"""

from __future__ import annotations

from typing import Dict, Type

from app.config import settings
from app.parsers.base import InvoiceParser
from app.parsers.llamaparse_parser import LlamaParseParser
from app.parsers.llm_parser import LLMParser
from app.parsers.tesseract_parser import TesseractParser

_REGISTRY: Dict[str, Type[InvoiceParser]] = {
    "tesseract": TesseractParser,
    "llamaparse": LlamaParseParser,
    "llm": LLMParser,
}


def get_parser() -> InvoiceParser:
    """Return the parser configured by PARSER_MODE env var."""
    mode = settings.PARSER_MODE.lower()
    cls = _REGISTRY.get(mode)
    if cls is None:
        raise ValueError(
            f"Unknown PARSER_MODE: '{mode}'. Available: {list(_REGISTRY.keys())}"
        )
    return cls()


def register_parser(name: str, cls: Type[InvoiceParser]) -> None:
    """Register a new parser implementation at runtime.

    Useful for plugins or testing.
    """
    _REGISTRY[name] = cls
