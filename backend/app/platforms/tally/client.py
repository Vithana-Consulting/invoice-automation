from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.platforms.account_resolver import ResolvedAccounts

logger = logging.getLogger(__name__)


class TallyClient:
    """HTTP client for Tally Prime XML API."""

    def __init__(self, host: str = "http://localhost:9000", company_name: str = ""):
        self.host = host.rstrip("/")
        self.company_name = company_name

    def _post_xml(self, xml_body: str) -> str:
        resp = httpx.post(self.host, content=xml_body,
                         headers={"Content-Type": "application/xml"}, timeout=30)
        if resp.status_code >= 400:
            raise Exception(f"Tally error ({resp.status_code}): {resp.text[:500]}")
        return resp.text

    def test_connection(self) -> dict:
        """Send a simple info request to Tally."""
        xml = """<ENVELOPE>
            <HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
            <BODY><EXPORTDATA><REQUESTDESC>
                <REPORTNAME>List of Companies</REPORTNAME>
            </REQUESTDESC></EXPORTDATA></BODY>
        </ENVELOPE>"""
        result = self._post_xml(xml)
        if self.company_name.lower() in result.lower():
            return {"healthy": True, "message": f"Connected to Tally ({self.company_name})"}
        return {"healthy": True, "message": "Connected to Tally (company not verified)"}

    def create_voucher(self, voucher_xml: str) -> str:
        """Create a purchase voucher (bill) in Tally."""
        return self._post_xml(voucher_xml)

    def build_purchase_voucher_xml(
        self,
        vendor_name: str,
        bill_number: str,
        date: str,
        amount: float,
        ledger_name: str = "Purchase Accounts",
        accounts: Optional[ResolvedAccounts] = None,
        narration: str = "",
    ) -> str:
        """Build Tally XML for a purchase voucher with tax ledger entries.

        For Tally, platform_ref values are ledger names (strings), not IDs.
        e.g., platform_ref = {"tally": "Purchase Accounts"}

        If COA accounts are resolved:
          - Main ledger from accounts.main_account_ref (overrides ledger_name)
          - Separate ledger entries for CGST/SGST/IGST

        Accounting entry structure:
          Debit:  Purchase ledger (subtotal)
          Debit:  CGST Input Credit (cgst_amount)
          Debit:  SGST Input Credit (sgst_amount)
          Debit:  IGST Input Credit (igst_amount)
          Credit: Vendor ledger (total amount)
        """
        # Use COA-resolved ledger name if available
        if accounts and accounts.main_account_ref:
            ledger_name = accounts.main_account_ref

        # Calculate subtotal (total minus taxes)
        subtotal = amount
        tax_entries = ""
        if accounts and accounts.has_tax_lines:
            subtotal = amount - accounts.cgst_amount - accounts.sgst_amount - accounts.igst_amount

            if accounts.cgst_amount and accounts.cgst_account_ref:
                tax_entries += f"""
                                <ALLLEDGERENTRIES.LIST>
                                    <LEDGERNAME>{accounts.cgst_account_ref}</LEDGERNAME>
                                    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                                    <AMOUNT>-{accounts.cgst_amount}</AMOUNT>
                                </ALLLEDGERENTRIES.LIST>"""

            if accounts.sgst_amount and accounts.sgst_account_ref:
                tax_entries += f"""
                                <ALLLEDGERENTRIES.LIST>
                                    <LEDGERNAME>{accounts.sgst_account_ref}</LEDGERNAME>
                                    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                                    <AMOUNT>-{accounts.sgst_amount}</AMOUNT>
                                </ALLLEDGERENTRIES.LIST>"""

            if accounts.igst_amount and accounts.igst_account_ref:
                tax_entries += f"""
                                <ALLLEDGERENTRIES.LIST>
                                    <LEDGERNAME>{accounts.igst_account_ref}</LEDGERNAME>
                                    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                                    <AMOUNT>-{accounts.igst_amount}</AMOUNT>
                                </ALLLEDGERENTRIES.LIST>"""

        return f"""<ENVELOPE>
            <HEADER>
                <TALLYREQUEST>Import Data</TALLYREQUEST>
            </HEADER>
            <BODY>
                <IMPORTDATA>
                    <REQUESTDESC>
                        <REPORTNAME>Vouchers</REPORTNAME>
                        <STATICVARIABLES>
                            <SVCURRENTCOMPANY>{self.company_name}</SVCURRENTCOMPANY>
                        </STATICVARIABLES>
                    </REQUESTDESC>
                    <REQUESTDATA>
                        <TALLYMESSAGE xmlns:UDF="TallyUDF">
                            <VOUCHER VCHTYPE="Purchase" ACTION="Create">
                                <DATE>{date.replace('-', '')}</DATE>
                                <VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>
                                <VOUCHERNUMBER>{bill_number}</VOUCHERNUMBER>
                                <PARTYLEDGERNAME>{vendor_name}</PARTYLEDGERNAME>
                                <NARRATION>{narration}</NARRATION>
                                <ALLLEDGERENTRIES.LIST>
                                    <LEDGERNAME>{ledger_name}</LEDGERNAME>
                                    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                                    <AMOUNT>-{subtotal}</AMOUNT>
                                </ALLLEDGERENTRIES.LIST>{tax_entries}
                                <ALLLEDGERENTRIES.LIST>
                                    <LEDGERNAME>{vendor_name}</LEDGERNAME>
                                    <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                                    <AMOUNT>{amount}</AMOUNT>
                                </ALLLEDGERENTRIES.LIST>
                            </VOUCHER>
                        </TALLYMESSAGE>
                    </REQUESTDATA>
                </IMPORTDATA>
            </BODY>
        </ENVELOPE>"""
