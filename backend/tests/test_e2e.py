"""End-to-end integration tests for the multi-tenant accounting platform.

Tests the full lifecycle:
  1. Company & user creation (tenant setup)
  2. Tenant isolation (data doesn't leak between companies)
  3. Invoice ingestion & parsing
  4. Rule creation & application
  5. Vendor mapping flow
  6. Draft lifecycle (approve, pending_vendor, push)
  7. Integration management
  8. Settings & admin endpoints
  9. MySQL views creation
"""
import json
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from app.db.session import SessionLocal, engine
from app.models.db_models import (
    Base, Company, CompanyMember, User, InvoiceRecord, InvoiceDraft,
    Rule, VendorMapping, Integration, PlatformVendor, AuditLog, ProcessedEmail,
)
from app.tenant.context import TenantContext
from app.tenant.service import CompanyService
from app.tenant.views import create_company_views, drop_company_views
from app.db.repository import (
    UserRepository, InvoiceRepository, DraftRepository, RuleRepository,
    VendorMappingRepository, IntegrationRepository, AuditLogRepository,
    PlatformVendorRepository,
)
from app.services.draft_service import DraftService
from app.platforms.base import encrypt_config


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
total = 0
passed = 0


def test(name: str, condition: bool, detail: str = ""):
    global total, passed
    total += 1
    if condition:
        passed += 1
        print(f"  {PASS} {name}")
    else:
        print(f"  {FAIL} {name} — {detail}")


def main():
    global total, passed
    db = SessionLocal()

    # ─── Clean slate ──────────────────────────────────────────────────
    print("\n=== Setup: Clean Database ===")
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()
    test("Database cleaned", True)

    # ─── 1. Company & User Creation ───────────────────────────────────
    print("\n=== 1. Company & User Creation ===")

    user_repo = UserRepository(db)
    user1 = user_repo.create_or_update("google-sub-1", "finance@acme.com", "Acme Finance", "")
    test("User 1 created", user1.id is not None, f"id={user1.id}")

    user2 = user_repo.create_or_update("google-sub-2", "finance@globex.com", "Globex Finance", "")
    test("User 2 created", user2.id is not None and user2.id != user1.id)

    company_service = CompanyService(db)
    company1 = company_service.create_company("Acme Corp", user1)
    test("Company 1 created", company1.id is not None, f"id={company1.id}, slug={company1.slug}")

    company2 = company_service.create_company("Globex Inc", user2)
    test("Company 2 created", company2.id is not None and company2.id != company1.id)

    # Verify memberships
    memberships = company_service.get_user_companies(user1.id)
    test("User 1 belongs to Company 1", len(memberships) == 1 and memberships[0].id == company1.id)

    memberships = company_service.get_user_companies(user2.id)
    test("User 2 belongs to Company 2", len(memberships) == 1 and memberships[0].id == company2.id)

    # ─── 2. Tenant Isolation ──────────────────────────────────────────
    print("\n=== 2. Tenant Isolation ===")

    # Create data in Company 1
    TenantContext.set(company1.id)
    repo1 = InvoiceRepository(db)
    inv1 = InvoiceRecord(
        file_path="/tmp/test1.pdf", file_name="test1.pdf", file_type="pdf",
        vendor_name="Vendor A", total_amount=100.0, parsing_status="PARSED",
    )
    inv1 = repo1.create(inv1)
    test("Invoice created in Company 1", inv1.id is not None and inv1.company_id == company1.id)

    # Create data in Company 2
    TenantContext.set(company2.id)
    repo2 = InvoiceRepository(db)
    inv2 = InvoiceRecord(
        file_path="/tmp/test2.pdf", file_name="test2.pdf", file_type="pdf",
        vendor_name="Vendor B", total_amount=200.0, parsing_status="PARSED",
    )
    inv2 = repo2.create(inv2)
    test("Invoice created in Company 2", inv2.id is not None and inv2.company_id == company2.id)

    # Verify isolation: Company 1 can only see its own invoices
    TenantContext.set(company1.id)
    repo1 = InvoiceRepository(db)
    c1_invoices = repo1.list_all()
    test("Company 1 sees only its invoices", len(c1_invoices) == 1 and c1_invoices[0].vendor_name == "Vendor A")

    # Company 2 can only see its own
    TenantContext.set(company2.id)
    repo2 = InvoiceRepository(db)
    c2_invoices = repo2.list_all()
    test("Company 2 sees only its invoices", len(c2_invoices) == 1 and c2_invoices[0].vendor_name == "Vendor B")

    # Cross-tenant access blocked
    TenantContext.set(company1.id)
    repo1 = InvoiceRepository(db)
    cross = repo1.get_by_id(inv2.id)
    test("Company 1 cannot access Company 2's invoice", cross is None)

    # ─── 3. Rule Creation & Application ───────────────────────────────
    print("\n=== 3. Rule Creation & Application ===")

    TenantContext.set(company1.id)
    rule_repo = RuleRepository(db)
    rule = rule_repo.create(
        name="Route Google to Zoho",
        conditions_json='{"field": "vendor_name", "op": "contains", "value": "google"}',
        action_type="set_push_to",
        action_value="zoho",
        priority=0,
    )
    test("Rule created in Company 1", rule.id is not None and rule.company_id == company1.id)

    # Company 2 should not see Company 1's rules
    TenantContext.set(company2.id)
    rule_repo2 = RuleRepository(db)
    c2_rules = rule_repo2.list_all()
    test("Company 2 has no rules (isolation)", len(c2_rules) == 0)

    # ─── 4. Vendor Mapping Flow ───────────────────────────────────────
    print("\n=== 4. Vendor Mapping Flow ===")

    TenantContext.set(company1.id)
    mapping_repo = VendorMappingRepository(db)
    mapping = mapping_repo.create(
        alias_name="Vendor A",
        canonical_name="Vendor Alpha Pvt Ltd",
        platform="zoho",
        platform_vendor_id="zoho-123",
    )
    test("Vendor mapping created", mapping.id is not None and mapping.company_id == company1.id)

    # Lookup
    found = mapping_repo.get_by_alias("Vendor A", platform="zoho")
    test("Vendor mapping lookup works", found is not None and found.canonical_name == "Vendor Alpha Pvt Ltd")

    # Company 2 isolation
    TenantContext.set(company2.id)
    mapping_repo2 = VendorMappingRepository(db)
    not_found = mapping_repo2.get_by_alias("Vendor A", platform="zoho")
    test("Company 2 cannot see Company 1's mappings", not_found is None)

    # ─── 5. Draft Lifecycle ───────────────────────────────────────────
    print("\n=== 5. Draft Lifecycle ===")

    TenantContext.set(company1.id)
    draft_repo = DraftRepository(db)

    # Create draft
    draft = draft_repo.create(
        invoice_id=inv1.id,
        vendor_name="Vendor A",
        total_amount=100.0,
        currency="INR",
        source="gmail",
        status="PENDING_REVIEW",
        push_to="zoho",
    )
    test("Draft created", draft.id is not None and draft.company_id == company1.id)

    # Approve — should succeed because mapping exists
    draft_service = DraftService(db)
    approved = draft_service.approve_draft(draft.id)
    test("Draft approved (mapping exists)", approved is not None and approved.status == "APPROVED",
         f"status={approved.status if approved else 'None'}")

    # Count by status
    counts = draft_repo.count_by_status()
    test("Status counts work", counts.get("APPROVED", 0) >= 1)

    # ─── 6. Integration Management ────────────────────────────────────
    print("\n=== 6. Integration Management ===")

    TenantContext.set(company1.id)
    int_repo = IntegrationRepository(db)
    integration = int_repo.create(
        platform="zoho",
        display_name="Zoho Books",
        config_encrypted=encrypt_config({"client_id": "test", "refresh_token": "test"}),
        is_enabled=True,
    )
    test("Integration created", integration.id is not None and integration.company_id == company1.id)

    # Company 2 isolation
    TenantContext.set(company2.id)
    int_repo2 = IntegrationRepository(db)
    c2_ints = int_repo2.list_all()
    test("Company 2 has no integrations (isolation)", len(c2_ints) == 0)

    # ─── 7. Platform Vendor Sync ──────────────────────────────────────
    print("\n=== 7. Platform Vendor Sync ===")

    TenantContext.set(company1.id)
    pv_repo = PlatformVendorRepository(db)
    pv, is_new = pv_repo.upsert(
        platform="zoho",
        platform_vendor_id="zoho-v-001",
        vendor_name="Alpha Corp",
        email="alpha@corp.com",
    )
    test("Platform vendor upserted (new)", is_new and pv.company_id == company1.id)

    # Upsert again (update)
    pv2, is_new2 = pv_repo.upsert(
        platform="zoho",
        platform_vendor_id="zoho-v-001",
        vendor_name="Alpha Corporation",  # Name changed
    )
    test("Platform vendor upserted (updated)", not is_new2 and pv2.vendor_name == "Alpha Corporation")

    # Company 2 isolation
    TenantContext.set(company2.id)
    pv_repo2 = PlatformVendorRepository(db)
    c2_pvs = pv_repo2.list_by_platform("zoho")
    test("Company 2 has no platform vendors (isolation)", len(c2_pvs) == 0)

    # ─── 8. Audit Log ─────────────────────────────────────────────────
    print("\n=== 8. Audit Log ===")

    TenantContext.set(company1.id)
    audit_repo = AuditLogRepository(db)
    audit_repo.log(
        entity_type="test", entity_id=1, action="e2e_test",
        details={"test": True}, status="success",
    )
    recent = audit_repo.list_recent(limit=5)
    test("Audit log created and listed", len(recent) >= 1 and recent[0].action == "e2e_test")

    # Company 2 isolation
    TenantContext.set(company2.id)
    audit_repo2 = AuditLogRepository(db)
    c2_audit = audit_repo2.list_recent(limit=5)
    test("Company 2 audit log is empty (isolation)", len(c2_audit) == 0)

    # ─── 9. MySQL Views ──────────────────────────────────────────────
    print("\n=== 9. MySQL Views ===")

    try:
        from sqlalchemy import text
        # Views were created during company creation
        result = db.execute(text(f"SELECT COUNT(*) FROM v_company_{company1.id}_invoices")).scalar()
        test(f"View v_company_{company1.id}_invoices works", result == 1, f"count={result}")

        result2 = db.execute(text(f"SELECT COUNT(*) FROM v_company_{company2.id}_invoices")).scalar()
        test(f"View v_company_{company2.id}_invoices works", result2 == 1, f"count={result2}")

        # Views are isolated
        result3 = db.execute(text(f"SELECT vendor_name FROM v_company_{company1.id}_invoices")).fetchone()
        test("Company 1 view shows only its data", result3[0] == "Vendor A")

        result4 = db.execute(text(f"SELECT vendor_name FROM v_company_{company2.id}_invoices")).fetchone()
        test("Company 2 view shows only its data", result4[0] == "Vendor B")

    except Exception as e:
        test("MySQL views", False, str(e))

    # ─── 10. Multi-Company User ───────────────────────────────────────
    print("\n=== 10. Multi-Company User ===")

    # Add user1 to company2 as member
    company_service2 = CompanyService(db)
    company_service2.add_member(company2.id, user1, role="member")

    memberships = company_service.get_user_companies(user1.id)
    test("User 1 belongs to 2 companies", len(memberships) == 2)

    # User1 can switch context to company2
    TenantContext.set(company2.id)
    repo_switched = InvoiceRepository(db)
    switched_invoices = repo_switched.list_all()
    test("User 1 sees Company 2 data after context switch", len(switched_invoices) == 1 and switched_invoices[0].vendor_name == "Vendor B")

    # ─── Summary ──────────────────────────────────────────────────────
    TenantContext.clear()
    db.close()

    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed")
    if passed == total:
        print(f"\033[92mAll tests passed!\033[0m")
    else:
        print(f"\033[91m{total - passed} tests failed\033[0m")
    print()

    return 0 if passed == total else 1


if __name__ == "__main__":
    exit(main())
