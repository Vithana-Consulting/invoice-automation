"""Convert office documents (Word) to PDF for the parse pipeline.

The invoice parsers operate on PDFs/images (PDF -> images -> vision model). Word
documents (.doc/.docx) are not natively parseable, so we convert them to PDF
first ("convert-then-parse") using a headless LibreOffice process. LibreOffice
preserves layout fidelity far better than text-extraction libraries, which
matters for compliance-critical fields (GSTIN, invoice number, line-item tables).

Requires LibreOffice on the host/container (`soffice` on PATH). The backend
Dockerfile installs `libreoffice-writer`. On a macOS dev machine:
`brew install --cask libreoffice`. When LibreOffice is absent, conversion raises
a clear ParsingError instead of failing obscurely.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile

from app.core.exceptions import ParsingError

logger = logging.getLogger(__name__)

# Word formats handled via convert-then-parse. Kept here (not in the parsers) so
# both the converter and the parser base share one source of truth.
WORD_TYPES = {"doc", "docx"}

_SOFFICE_TIMEOUT = 120  # seconds — large docs can take a while on first launch


def _find_soffice() -> str | None:
    """Locate the LibreOffice headless binary, or None if not installed."""
    for name in ("soffice", "libreoffice", "soffice.bin"):
        path = shutil.which(name)
        if path:
            return path
    mac_path = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    if os.path.exists(mac_path):
        return mac_path
    return None


def convert_word_to_pdf(src_path: str) -> str:
    """Convert a .doc/.docx file to PDF using headless LibreOffice.

    Returns the path to the generated PDF, which lives in a fresh temp directory
    the caller is responsible for removing (e.g. ``shutil.rmtree(os.path.dirname(pdf))``).
    Raises ParsingError if LibreOffice is unavailable or the conversion fails.
    """
    if not os.path.exists(src_path):
        raise ParsingError(f"Cannot convert Word document: source file not found: {src_path}")

    soffice = _find_soffice()
    if not soffice:
        raise ParsingError(
            "Word document received but LibreOffice is not installed. Install it to "
            "enable .doc/.docx parsing (Docker: `apt-get install -y libreoffice-writer`; "
            "macOS: `brew install --cask libreoffice`) and ensure `soffice` is on PATH."
        )

    out_dir = tempfile.mkdtemp(prefix="word2pdf_")
    # Isolate the LibreOffice user profile per call so concurrent conversions
    # don't collide on the shared default profile lock.
    profile_uri = f"file://{os.path.join(out_dir, 'profile')}"
    try:
        proc = subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={profile_uri}",
                "--headless", "--norestore", "--nolockcheck",
                "--convert-to", "pdf",
                "--outdir", out_dir,
                src_path,
            ],
            capture_output=True, text=True, timeout=_SOFFICE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise ParsingError(f"Word->PDF conversion timed out after {_SOFFICE_TIMEOUT}s")
    except Exception as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise ParsingError(f"Word->PDF conversion failed to start: {type(e).__name__}: {e}")

    pdf_name = os.path.splitext(os.path.basename(src_path))[0] + ".pdf"
    pdf_path = os.path.join(out_dir, pdf_name)
    if proc.returncode != 0 or not os.path.exists(pdf_path):
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        shutil.rmtree(out_dir, ignore_errors=True)
        raise ParsingError(
            f"Word->PDF conversion produced no output (exit {proc.returncode}). {detail}"
        )

    logger.info("Converted Word document %s -> %s", os.path.basename(src_path), pdf_name)
    return pdf_path
