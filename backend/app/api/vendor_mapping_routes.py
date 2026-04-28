from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Optional

from sqlalchemy import distinct, func

from app.auth.dependencies import get_optional_user
from app.db.repository import IntegrationRepository, VendorMappingRepository
from app.db.session import get_db
from app.models.db_models import InvoiceDraft, PlatformVendor, User
from app.platforms.base import decrypt_config, get_platform_class, _BILLING_REGISTRY
from app.services.draft_service import DraftService
from app.tenant.context import TenantContext

logger = logging.getLogger(__name__)
router = APIRouter()


class VendorMappingCreate(BaseModel):
    alias_name: str = Field(min_length=1, max_length=500)
    canonical_name: str = Field(min_length=1, max_length=500)
    platform: str = Field(min_length=1, max_length=50)  # Required: zoho, tally, quickbooks
    platform_vendor_id: Optional[str] = None


class VendorMappingUpdate(BaseModel):
    alias_name: Optional[str] = Field(None, min_length=1, max_length=500)
    canonical_name: Optional[str] = Field(None, min_length=1, max_length=500)
    platform: Optional[str] = Field(None, min_length=1, max_length=50)
    platform_vendor_id: Optional[str] = None


def _validate_mapping_sides(db: Session, alias_name: str, platform: str, canonical_name: str = None, platform_vendor_id: str = None):
    """Validate that both source (invoice vendor) and destination (platform vendor) exist in DB.

    Raises HTTPException if either side is missing.
    """
    from app.db.repository import PlatformVendorRepository

    # Validate source: alias_name must exist in invoice drafts
    source_exists = (
        db.query(InvoiceDraft)
        .filter(func.lower(InvoiceDraft.vendor_name) == alias_name.lower())
        .first()
    )
    if not source_exists:
        raise HTTPException(
            status_code=400,
            detail=f"Source vendor '{alias_name}' not found in any invoice draft. "
            "Only vendors from parsed invoices can be mapped.",
        )

    # Validate destination: canonical_name or platform_vendor_id must exist in platform_vendors
    if platform_vendor_id:
        pv_repo = PlatformVendorRepository(db)
        dest = pv_repo.get_by_platform_vendor_id(platform, platform_vendor_id)
        if not dest:
            raise HTTPException(
                status_code=400,
                detail=f"Platform vendor ID '{platform_vendor_id}' not found in synced {platform} vendors. "
                "Sync vendors from the Platform Vendors tab first.",
            )
    elif canonical_name:
        dest = (
            db.query(PlatformVendor)
            .filter(PlatformVendor.platform == platform)
            .filter(func.lower(PlatformVendor.vendor_name) == canonical_name.lower())
            .first()
        )
        if not dest:
            raise HTTPException(
                status_code=400,
                detail=f"Destination vendor '{canonical_name}' not found in synced {platform} vendors. "
                "Sync vendors from the Platform Vendors tab, or use 'Create on Platform' to create it first.",
            )


@router.get("")
def list_mappings(
    search: str = Query(None),
    platform: str = Query(None, description="Filter by platform: zoho, tally, quickbooks"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List vendor mappings, optionally filtered by platform."""
    repo = VendorMappingRepository(db)
    mappings = repo.list_all(search=search, platform=platform, limit=limit, offset=offset)
    total = repo.count(search=search, platform=platform)
    return {
        "status": "success",
        "data": [_mapping_to_dict(m) for m in mappings],
        "total": total,
    }


@router.post("")
def create_mapping(
    body: VendorMappingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Create a vendor mapping for a specific platform.

    The same alias can map to different names on different platforms:
      "Google Private Limited" → "Google PVTL" (zoho)
      "Google Private Limited" → "Google LLC"  (quickbooks)
    """
    # Validate both sides exist in DB
    _validate_mapping_sides(db, body.alias_name, body.platform, body.canonical_name, body.platform_vendor_id)

    repo = VendorMappingRepository(db)
    existing = repo.get_exact(body.alias_name, body.platform)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Mapping for '{body.alias_name}' on {body.platform} already exists (id={existing.id})",
        )
    mapping = repo.create(
        alias_name=body.alias_name,
        canonical_name=body.canonical_name,
        platform=body.platform,
        platform_vendor_id=body.platform_vendor_id,
        created_by=user.id if user else None,
    )

    # Auto-resolve any PENDING_VENDOR drafts that match this mapping
    draft_service = DraftService(db)
    resolved = draft_service.resolve_pending_vendors(platform=body.platform)

    return {
        "status": "success",
        "data": _mapping_to_dict(mapping),
        "drafts_resolved": len(resolved),
    }


@router.post("/bulk")
def create_mappings_bulk(
    body: List[dict] = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Create vendor mappings for multiple platforms at once.

    Example: map "Google Private Limited" to all 3 billing platforms in one call.
    Body: [{"alias_name": "...", "canonical_name": "...", "platform": "zoho"}, ...]
    """
    repo = VendorMappingRepository(db)
    results = []
    for item in body:
        alias = item.get("alias_name", "")
        platform = item.get("platform", "")
        canonical = item.get("canonical_name", alias)
        vendor_id = item.get("platform_vendor_id")
        if not alias or not platform:
            results.append({"alias_name": alias, "platform": platform, "success": False, "error": "Missing fields"})
            continue
        # Validate both sides
        try:
            _validate_mapping_sides(db, alias, platform, canonical, vendor_id)
        except HTTPException as e:
            results.append({"alias_name": alias, "platform": platform, "success": False, "error": e.detail})
            continue
        existing = repo.get_exact(alias, platform)
        if existing:
            results.append({"alias_name": alias, "platform": platform, "success": False, "error": "Already exists"})
            continue
        mapping = repo.create(
            alias_name=alias,
            canonical_name=canonical,
            platform=platform,
            platform_vendor_id=vendor_id,
            created_by=user.id if user else None,
        )
        results.append({"alias_name": alias, "platform": platform, "success": True, "id": mapping.id})

    # Auto-resolve PENDING_VENDOR drafts
    draft_service = DraftService(db)
    resolved = draft_service.resolve_pending_vendors()

    return {"status": "success", "data": results, "drafts_resolved": len(resolved)}


@router.get("/source-vendors")
def list_source_vendors(db: Session = Depends(get_db)):
    """List unique vendor names from invoice drafts with their mapping status per platform.

    These are the 'source' vendors — names as they appear on invoices from
    Gmail, Stripe, file uploads, etc.
    """
    from app.models.db_models import VendorMapping

    company_id = TenantContext.get()

    # Get unique vendor names from drafts
    query = db.query(
        InvoiceDraft.vendor_name,
        func.count(InvoiceDraft.id).label("invoice_count"),
        func.group_concat(distinct(InvoiceDraft.source)).label("sources"),
    ).filter(InvoiceDraft.vendor_name.isnot(None)).filter(InvoiceDraft.vendor_name != "")

    if company_id:
        query = query.filter(InvoiceDraft.company_id == company_id)

    rows = (
        query
        .group_by(InvoiceDraft.vendor_name)
        .order_by(InvoiceDraft.vendor_name)
        .all()
    )

    # Get all existing mappings
    mapping_repo = VendorMappingRepository(db)
    all_mappings = mapping_repo.list_all(limit=5000)
    mapping_lookup: dict = {}
    for m in all_mappings:
        key = m.alias_name.lower()
        if key not in mapping_lookup:
            mapping_lookup[key] = []
        mapping_lookup[key].append({
            "platform": m.platform,
            "canonical_name": m.canonical_name,
            "platform_vendor_id": m.platform_vendor_id,
            "mapping_id": m.id,
        })

    results = []
    for row in rows:
        vendor_name = row[0]
        invoice_count = row[1]
        sources = row[2] or ""
        mappings_for_vendor = mapping_lookup.get(vendor_name.lower(), [])
        mapped_platforms = [m["platform"] for m in mappings_for_vendor]

        results.append({
            "vendor_name": vendor_name,
            "invoice_count": invoice_count,
            "sources": sources.split(",") if sources else [],
            "mappings": mappings_for_vendor,
            "mapped_platforms": mapped_platforms,
            "is_fully_mapped": len(mapped_platforms) > 0,
        })

    unmapped_count = sum(1 for r in results if not r["is_fully_mapped"])
    return {
        "status": "success",
        "data": results,
        "total": len(results),
        "unmapped": unmapped_count,
    }


@router.get("/platform-vendors/{platform}")
def list_platform_vendors(platform: str, search: str = Query(None), db: Session = Depends(get_db)):
    """List platform vendors from the local database (no API call to platform).

    Returns vendors with their mapping status. Use POST /platform-vendors/{platform}/sync
    to refresh from the platform.
    """
    from app.db.repository import PlatformVendorRepository

    pv_repo = PlatformVendorRepository(db)
    vendors = pv_repo.list_by_platform(platform, search=search)
    last_sync = pv_repo.last_synced(platform)

    mapping_repo = VendorMappingRepository(db)
    all_mappings = mapping_repo.list_all(platform=platform, limit=5000)
    mapped_by_vendor_id = {m.platform_vendor_id: m for m in all_mappings if m.platform_vendor_id}
    mapped_by_canonical = {m.canonical_name.lower(): m for m in all_mappings}

    results = []
    for v in vendors:
        mapping = mapped_by_vendor_id.get(v.platform_vendor_id) or mapped_by_canonical.get(v.vendor_name.lower())
        results.append({
            "id": v.id,
            "platform_vendor_id": v.platform_vendor_id,
            "platform_vendor_name": v.vendor_name,
            "email": v.email or "",
            "status": v.status or "",
            "platform": v.platform,
            "synced_at": str(v.synced_at) if v.synced_at else None,
            "is_mapped": mapping is not None,
            "mapping_id": mapping.id if mapping else None,
            "mapped_alias": mapping.alias_name if mapping else None,
        })

    results.sort(key=lambda r: (r["is_mapped"], r["platform_vendor_name"].lower()))
    unmapped_count = sum(1 for r in results if not r["is_mapped"])

    return {
        "status": "success",
        "data": results,
        "total": len(results),
        "unmapped": unmapped_count,
        "last_synced": str(last_sync) if last_sync else None,
    }


@router.post("/platform-vendors/{platform}/sync")
def sync_platform_vendors(platform: str, db: Session = Depends(get_db)):
    """Pull vendors from the billing platform API and sync to local database.

    - New vendors are inserted
    - Existing vendors are updated if name/email/status changed
    - Returns sync stats
    """
    import json as json_mod
    from app.db.repository import PlatformVendorRepository

    if platform not in _BILLING_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown billing platform: {platform}")

    integration_repo = IntegrationRepository(db)
    integration = integration_repo.get_by_platform(platform)
    if not integration:
        raise HTTPException(status_code=400, detail=f"{platform} is not configured. Set it up in Integrations.")
    if not integration.is_enabled:
        raise HTTPException(status_code=400, detail=f"{platform} is disabled. Enable it in Integrations.")

    config = decrypt_config(integration.config_encrypted)
    cls = _BILLING_REGISTRY[platform]
    instance = cls(config)

    # Fetch from platform API
    api_vendors = instance.list_vendors()

    pv_repo = PlatformVendorRepository(db)
    new_count = 0
    updated_count = 0
    unchanged_count = 0

    for v in api_vendors:
        vendor_id = v.get("id", "")
        vendor_name = v.get("name", "")
        if not vendor_id or not vendor_name:
            continue

        record, is_new = pv_repo.upsert(
            platform=platform,
            platform_vendor_id=vendor_id,
            vendor_name=vendor_name,
            email=v.get("email", ""),
            status=v.get("status", "active"),
            raw_data=json_mod.dumps(v),
        )

        if is_new:
            new_count += 1
        else:
            # Check if anything actually changed
            if record.updated_at and record.updated_at > record.created_at:
                updated_count += 1
            else:
                unchanged_count += 1

    logger.info("Synced %s vendors from %s: %d new, %d updated, %d unchanged",
                len(api_vendors), platform, new_count, updated_count, unchanged_count)

    return {
        "status": "success",
        "data": {
            "platform": platform,
            "total_from_api": len(api_vendors),
            "new": new_count,
            "updated": updated_count,
            "unchanged": unchanged_count,
        },
    }


@router.post("/link-vendor")
def link_vendor_mapping(body: dict, db: Session = Depends(get_db), user: User = Depends(get_optional_user)):
    """Create a mapping linking an invoice vendor name to a platform vendor.

    Body: {
        "alias_name": "Google PVP Limited",       (name as it appears on invoices)
        "platform": "zoho",
        "platform_vendor_id": "123456",
        "platform_vendor_name": "Google Private Limited"  (canonical name on the platform)
    }
    """
    alias = body.get("alias_name", "").strip()
    platform = body.get("platform", "").strip()
    vendor_id = body.get("platform_vendor_id", "").strip()
    canonical = body.get("platform_vendor_name", "").strip()

    if not alias or not platform or not canonical:
        raise HTTPException(status_code=400, detail="alias_name, platform, and platform_vendor_name are required")

    # Validate both sides exist in DB
    _validate_mapping_sides(db, alias, platform, canonical, vendor_id)

    repo = VendorMappingRepository(db)
    existing = repo.get_exact(alias, platform)
    if existing:
        # Update existing mapping with the platform vendor ID
        mapping = repo.update(existing.id,
                              canonical_name=canonical,
                              platform_vendor_id=vendor_id)
        return {"status": "success", "data": _mapping_to_dict(mapping), "updated": True}

    mapping = repo.create(
        alias_name=alias,
        canonical_name=canonical,
        platform=platform,
        platform_vendor_id=vendor_id,
        created_by=user.id if user else None,
    )
    # Auto-resolve PENDING_VENDOR drafts
    draft_service = DraftService(db)
    resolved = draft_service.resolve_pending_vendors(platform=platform)

    return {"status": "success", "data": _mapping_to_dict(mapping), "updated": False, "drafts_resolved": len(resolved)}


@router.post("/create-platform-vendor")
def create_vendor_on_platform(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Create a vendor on the billing platform, save to platform_vendors, and auto-create mapping.

    Body: {
        "vendor_name": "Google PVP Limited",  (name as it appears on invoices — the alias)
        "canonical_name": "Google PVP Limited",  (optional: name to create on platform, defaults to vendor_name)
        "platform": "zoho"
    }

    Flow:
      1. Create vendor on platform (Zoho/QuickBooks) via API
      2. Save to platform_vendors table
      3. Create vendor_mapping (alias → canonical + platform_vendor_id)
      4. Auto-resolve any PENDING_VENDOR drafts
    """
    import json as json_mod
    from app.db.repository import PlatformVendorRepository

    alias_name = body.get("vendor_name", "").strip()
    canonical_name = body.get("canonical_name", "").strip() or alias_name
    platform = body.get("platform", "").strip()

    if not alias_name or not platform:
        raise HTTPException(status_code=400, detail="vendor_name and platform are required")

    # Validate source side: alias must exist in invoice drafts
    from sqlalchemy import func
    from app.models.db_models import InvoiceDraft
    source_exists = (
        db.query(InvoiceDraft)
        .filter(func.lower(InvoiceDraft.vendor_name) == alias_name.lower())
        .first()
    )
    if not source_exists:
        raise HTTPException(
            status_code=400,
            detail=f"Source vendor '{alias_name}' not found in any invoice draft. "
            "Only vendors from parsed invoices can be mapped.",
        )

    if platform not in _BILLING_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {platform}")

    # Check integration is configured
    integration_repo = IntegrationRepository(db)
    integration = integration_repo.get_by_platform(platform)
    if not integration or not integration.is_enabled:
        raise HTTPException(status_code=400, detail=f"{platform} is not configured or disabled.")

    config = decrypt_config(integration.config_encrypted)
    cls = _BILLING_REGISTRY[platform]
    instance = cls(config)

    # Step 1: Create vendor on the platform
    try:
        platform_vendor_id = instance.create_vendor(canonical_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create vendor on {platform}: {e}")

    if not platform_vendor_id:
        raise HTTPException(status_code=500, detail=f"Platform returned empty vendor ID")

    # Step 2: Save to platform_vendors table
    pv_repo = PlatformVendorRepository(db)
    pv_repo.upsert(
        platform=platform,
        platform_vendor_id=str(platform_vendor_id),
        vendor_name=canonical_name,
        raw_data=json_mod.dumps({"created_from": "source_vendor", "alias": alias_name}),
    )

    # Step 3: Create vendor mapping
    mapping_repo = VendorMappingRepository(db)
    existing = mapping_repo.get_exact(alias_name, platform)
    if existing:
        mapping = mapping_repo.update(
            existing.id,
            canonical_name=canonical_name,
            platform_vendor_id=str(platform_vendor_id),
        )
    else:
        mapping = mapping_repo.create(
            alias_name=alias_name,
            canonical_name=canonical_name,
            platform=platform,
            platform_vendor_id=str(platform_vendor_id),
            created_by=user.id if user else None,
        )

    # Step 4: Auto-resolve PENDING_VENDOR drafts
    draft_service = DraftService(db)
    resolved = draft_service.resolve_pending_vendors(platform=platform)

    logger.info(
        "Created vendor '%s' on %s (ID: %s), mapping from '%s', resolved %d drafts",
        canonical_name, platform, platform_vendor_id, alias_name, len(resolved),
    )

    return {
        "status": "success",
        "data": {
            "mapping": _mapping_to_dict(mapping),
            "platform_vendor_id": str(platform_vendor_id),
            "drafts_resolved": len(resolved),
        },
    }


@router.put("/{mapping_id}")
def update_mapping(mapping_id: int, body: VendorMappingUpdate, db: Session = Depends(get_db)):
    from app.db.repository import AuditLogRepository
    repo = VendorMappingRepository(db)
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    mapping = repo.update(mapping_id, **updates)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    AuditLogRepository(db).log(
        entity_type="vendor_mapping", entity_id=mapping_id,
        action="updated", details=updates,
    )
    return {"status": "success", "data": _mapping_to_dict(mapping)}


@router.delete("/{mapping_id}")
def delete_mapping(mapping_id: int, db: Session = Depends(get_db)):
    from app.db.repository import AuditLogRepository
    repo = VendorMappingRepository(db)
    if not repo.delete(mapping_id):
        raise HTTPException(status_code=404, detail="Mapping not found")
    AuditLogRepository(db).log(
        entity_type="vendor_mapping", entity_id=mapping_id,
        action="deleted",
    )
    return {"status": "success", "message": "Mapping deleted"}


def _mapping_to_dict(m) -> dict:
    return {
        "id": m.id,
        "alias_name": m.alias_name,
        "canonical_name": m.canonical_name,
        "platform": m.platform,
        "platform_vendor_id": m.platform_vendor_id,
        "created_at": str(m.created_at) if m.created_at else None,
        "updated_at": str(m.updated_at) if m.updated_at else None,
    }
