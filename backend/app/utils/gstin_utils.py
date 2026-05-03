"""GSTIN validation and parsing utilities."""
from __future__ import annotations
import re
from typing import Optional

GSTIN_PATTERN = re.compile(
    r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'
)

STATE_CODES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
    "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra",
    "28": "Andhra Pradesh", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman & Nicobar", "36": "Telangana",
    "37": "Andhra Pradesh (New)", "38": "Ladakh",
    "97": "Other Territory", "99": "Centre Jurisdiction",
}

def validate_gstin_format(gstin: str) -> bool:
    if not gstin:
        return False
    return bool(GSTIN_PATTERN.match(gstin.strip().upper()))

def extract_state_code(gstin: str) -> str:
    gstin = (gstin or "").strip()
    return gstin[:2] if len(gstin) >= 2 else ""

def get_state_name(gstin: str) -> str:
    return STATE_CODES.get(extract_state_code(gstin), "Unknown")

def is_interstate(vendor_gstin: str, org_state_code: str) -> Optional[bool]:
    """Returns True=IGST, False=CGST+SGST, None=cannot determine."""
    vendor_state = extract_state_code(vendor_gstin)
    if not vendor_state or not org_state_code:
        return None
    return vendor_state != org_state_code.strip()
