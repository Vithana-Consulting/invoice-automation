"""Tests for .doc/.docx convert-then-parse support across the parse pipeline."""
from __future__ import annotations

import os
import tempfile

import pytest

from app.core.exceptions import ParsingError
from app.parsers.base import InvoiceParser
from app.parsers.llamaparse_parser import LlamaParseParser
from app.parsers.llm_parser import LLMParser
from app.parsers.tesseract_parser import TesseractParser


def test_all_parsers_accept_word_types():
    """Every parser must report doc/docx as supported (else the orchestrator skips them)."""
    for parser in (LLMParser(), TesseractParser(), LlamaParseParser()):
        assert parser.supports("docx")
        assert parser.supports("doc")
        assert parser.supports(".DOCX")  # case- and dot-insensitive


def test_prepare_source_passthrough_for_non_word():
    """Non-Word types are returned unchanged with a no-op cleanup."""
    path, ft, cleanup = InvoiceParser._prepare_source("/tmp/invoice.pdf", "pdf")
    assert path == "/tmp/invoice.pdf"
    assert ft == "pdf"
    cleanup()  # must be a harmless no-op


def test_prepare_source_converts_word_and_cleans_up(monkeypatch):
    """docx routes through the converter; cleanup removes the temp PDF dir."""
    import app.utils.document_converter as conv

    tmp_dir = tempfile.mkdtemp()
    fake_pdf = os.path.join(tmp_dir, "converted.pdf")
    open(fake_pdf, "w").close()
    monkeypatch.setattr(conv, "convert_word_to_pdf", lambda src: fake_pdf)

    path, ft, cleanup = InvoiceParser._prepare_source("/tmp/invoice.docx", "docx")
    assert ft == "pdf"
    assert path == fake_pdf
    assert os.path.isdir(tmp_dir)

    cleanup()
    assert not os.path.exists(tmp_dir)  # cleanup removed the whole temp dir


def test_convert_without_libreoffice_raises_clear_error(monkeypatch):
    """When LibreOffice is missing, conversion fails with an actionable message."""
    import app.utils.document_converter as conv

    monkeypatch.setattr(conv, "_find_soffice", lambda: None)
    with tempfile.NamedTemporaryFile(suffix=".docx") as f:
        with pytest.raises(ParsingError, match="LibreOffice"):
            conv.convert_word_to_pdf(f.name)


def test_convert_missing_source_raises():
    import app.utils.document_converter as conv

    with pytest.raises(ParsingError, match="not found"):
        conv.convert_word_to_pdf("/no/such/file.docx")
