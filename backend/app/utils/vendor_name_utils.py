"""Vendor name normalisation for fuzzy matching."""
import re

_LEGAL = re.compile(
    r'\b(private limited|pvt\.?\s*ltd\.?|limited|ltd\.?|llp|llc|inc\.?|'
    r'co\.?|company|corp\.?|corporation|pvt|pte|plc|bv|gmbh|sas|srl)\b',
    re.IGNORECASE,
)
_PUNCT = re.compile(r'[^\w\s]')
_SPACE = re.compile(r'\s+')

def normalize(name: str) -> str:
    name = _LEGAL.sub('', name or '')
    name = _PUNCT.sub(' ', name)
    return _SPACE.sub(' ', name).strip().lower()

def is_match(a: str, b: str) -> bool:
    return normalize(a) == normalize(b)
