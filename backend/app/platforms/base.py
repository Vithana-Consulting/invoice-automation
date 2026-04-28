from __future__ import annotations

import base64
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from sqlalchemy.orm import Session

from app.core.exceptions import IntegrationError
from app.db.repository import IntegrationRepository

logger = logging.getLogger(__name__)


# ─── Abstract Interfaces ─────────────────────────────────────────────────

class BillingPlatform(ABC):
    """A platform you PUSH bills TO (Zoho, Tally, QuickBooks)."""

    platform_key: str = ""
    display_name: str = ""
    description: str = ""
    category: str = "billing"

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """Test API connectivity. Return {'healthy': bool, 'message': str}."""
        ...

    @abstractmethod
    def push_bill(self, draft: Any, db: Session) -> Dict[str, Any]:
        """Push a draft as a bill. Return {'external_id': str, 'platform': str}."""
        ...

    @abstractmethod
    def find_vendor(self, vendor_name: str) -> Optional[str]:
        """Search for vendor. Return platform vendor ID or None."""
        ...

    @abstractmethod
    def create_vendor(self, vendor_name: str, **kwargs) -> str:
        """Create vendor. Return platform vendor ID."""
        ...

    def list_vendors(self) -> List[Dict[str, Any]]:
        """List all vendors from the platform. Return list of {'id': str, 'name': str, ...}.

        Not all platforms support this. Default returns empty list.
        """
        return []

    def list_accounts(self) -> List[Dict[str, Any]]:
        """List Chart of Accounts from the platform.

        Returns list of:
          {'id': str, 'name': str, 'type': str, 'code': str, 'description': str, 'is_active': bool}

        Not all platforms support this. Default returns empty list.
        """
        return []

    @classmethod
    @abstractmethod
    def get_config_fields(cls) -> List[Dict[str, Any]]:
        """Return config field definitions for the frontend form."""
        ...


class InvoiceSource(ABC):
    """A platform you PULL invoices FROM (Gmail, Stripe, Chargebee)."""

    platform_key: str = ""
    display_name: str = ""
    description: str = ""
    category: str = "source"

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        ...

    @abstractmethod
    def fetch_invoices(self, db: Session, since: Optional[datetime] = None) -> Dict[str, Any]:
        """Pull invoices. Return stats dict."""
        ...

    @classmethod
    @abstractmethod
    def get_config_fields(cls) -> List[Dict[str, Any]]:
        ...


# ─── Registry ────────────────────────────────────────────────────────────

_BILLING_REGISTRY: Dict[str, Type[BillingPlatform]] = {}
_SOURCE_REGISTRY: Dict[str, Type[InvoiceSource]] = {}


def register_billing(cls: Type[BillingPlatform]) -> Type[BillingPlatform]:
    """Decorator to register a billing platform."""
    _BILLING_REGISTRY[cls.platform_key] = cls
    return cls


def register_source(cls: Type[InvoiceSource]) -> Type[InvoiceSource]:
    """Decorator to register an invoice source."""
    _SOURCE_REGISTRY[cls.platform_key] = cls
    return cls


def get_all_platforms() -> List[Dict[str, Any]]:
    """Return metadata for all registered platforms (for the Integrations UI)."""
    platforms = []
    for key, cls in {**_BILLING_REGISTRY, **_SOURCE_REGISTRY}.items():
        platforms.append({
            "platform": key,
            "display_name": cls.display_name,
            "description": cls.description,
            "category": cls.category,
            "fields": cls.get_config_fields(),
        })
    return sorted(platforms, key=lambda p: (p["category"], p["platform"]))


def get_platform_class(platform_key: str) -> Type[BillingPlatform] | Type[InvoiceSource]:
    """Get the platform class by key."""
    cls = _BILLING_REGISTRY.get(platform_key) or _SOURCE_REGISTRY.get(platform_key)
    if not cls:
        raise IntegrationError(f"Unknown platform: {platform_key}")
    return cls


# ─── Factory: create configured platform from DB ─────────────────────────

def encrypt_config(config: dict) -> str:
    return base64.b64encode(json.dumps(config).encode()).decode()


def decrypt_config(encrypted: str) -> dict:
    try:
        return json.loads(base64.b64decode(encrypted).decode())
    except Exception:
        return {}


def get_billing_platform(db: Session, platform_key: str) -> BillingPlatform:
    """Get a configured billing platform instance from DB credentials.

    Raises IntegrationError if not configured or disabled.
    """
    cls = _BILLING_REGISTRY.get(platform_key)
    if not cls:
        raise IntegrationError(f"Billing platform '{platform_key}' is not supported")

    repo = IntegrationRepository(db)
    integration = repo.get_by_platform(platform_key)

    if not integration:
        raise IntegrationError(f"{cls.display_name} is not configured. Go to Integrations to set it up.")
    if not integration.is_enabled:
        raise IntegrationError(f"{cls.display_name} is disabled. Enable it in Integrations.")

    config = decrypt_config(integration.config_encrypted)
    return cls(config)


def get_source_platform(db: Session, platform_key: str) -> InvoiceSource:
    """Get a configured source platform instance from DB credentials."""
    cls = _SOURCE_REGISTRY.get(platform_key)
    if not cls:
        raise IntegrationError(f"Source platform '{platform_key}' is not supported")

    repo = IntegrationRepository(db)
    integration = repo.get_by_platform(platform_key)

    if not integration:
        raise IntegrationError(f"{cls.display_name} is not configured. Go to Integrations to set it up.")
    if not integration.is_enabled:
        raise IntegrationError(f"{cls.display_name} is disabled. Enable it in Integrations.")

    config = decrypt_config(integration.config_encrypted)
    return cls(config)


def test_platform(platform_key: str, config: dict) -> Dict[str, Any]:
    """Test a platform connection with given config (before saving to DB)."""
    cls = _BILLING_REGISTRY.get(platform_key) or _SOURCE_REGISTRY.get(platform_key)
    if not cls:
        return {"healthy": False, "message": f"Unknown platform: {platform_key}"}

    try:
        instance = cls(config)
        return instance.test_connection()
    except Exception as e:
        return {"healthy": False, "message": str(e)}
