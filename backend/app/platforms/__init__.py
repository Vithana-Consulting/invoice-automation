"""Platform integrations package.

Each platform (zoho, stripe, tally, quickbooks, chargebee, gmail) has its own
sub-package with:
  - auth.py     — Authentication (OAuth, API key, etc.)
  - client.py   — HTTP client for the platform API
  - service.py  — Business logic (push bill, pull invoices, etc.)
  - schema.py   — Config schema + Pydantic models
  - __init__.py  — Platform metadata
"""
