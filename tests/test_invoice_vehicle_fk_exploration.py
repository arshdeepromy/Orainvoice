"""Bug condition exploration tests — Invoice Vehicle FK Fix.

These tests demonstrate the bug where create_invoice() crashes with a
ForeignKeyViolationError when the provided vehicle ID belongs to an
org_vehicles record (not global_vehicles).  They also demonstrate that
update_invoice() silently skips metadata updates for org vehicles.

**IMPORTANT**: These tests are written BEFORE the fix is implemented.
They encode the EXPECTED (correct) behavior.  On UNFIXED code they will
FAIL — that failure confirms the bug exists.

Validates: Requirements 1.1, 1.2, 1.3, 1.4
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# Import ALL ORM models so SQLAlchemy can resolve string-based relationships
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401

from app.core.database import _set_rls_org_id
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.customers.models import Customer
from app.modules.invoices.service import create_invoice, update_invoice
from app.modules.module_management.models import OrgModule
from app.modules.vehicles.models import CustomerVehicle, OrgVehicle


# ---------------------------------------------------------------------------
# Per-test engine/session factory — avoids connection pool corruption
# between tests when FK errors invalidate connections.
# ---------------------------------------------------------------------------

async def _make_session() -> tuple[AsyncSession, "AsyncEngine"]:
    """Create a fresh engine + session for each test.

    This avoids the problem where a ForeignKeyViolationError in one test
    corrupts the shared connection pool and causes subsequent tests to fail
    with 'attached to a different loop' errors.
    """
    test_engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    session = factory()
    return session, test_engine


# ---------------------------------------------------------------------------
# Helpers — create prerequisite records for each test
# ---------------------------------------------------------------------------

async def _create_test_fixtures(session: AsyncSession):
    """Create a subscription plan, org, user, customer, and org vehicle.

    Returns a dict with all the created objects and their IDs.
    """
    # 1. Subscription plan (required FK for Organisation)
    plan = SubscriptionPlan(
        name="Test Plan",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    # 2. Organisation
    org = Organisation(
        name="Test Org for Vehicle FK",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        settings={"gst_percentage": 15, "invoice_prefix": "TEST-"},
    )
    session.add(org)
    await session.flush()

    # 3. Enable the "vehicles" module for this org
    org_module = OrgModule(
        org_id=org.id,
        module_slug="vehicles",
        is_enabled=True,
    )
    session.add(org_module)
    await session.flush()

    # 4. User (created_by FK on Invoice)
    user = User(
        org_id=org.id,
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        first_name="Test",
        last_name="User",
        role="org_admin",
        password_hash="not-a-real-hash",
    )
    session.add(user)
    await session.flush()

    # 5. Customer
    customer = Customer(
        org_id=org.id,
        first_name="Bug",
        last_name="Tester",
    )
    session.add(customer)
    await session.flush()

    # 6. Org vehicle (NO matching GlobalVehicle — this is the bug condition)
    org_vehicle = OrgVehicle(
        org_id=org.id,
        rego="TEST123",
        make="Toyota",
        model="Corolla",
        year=2020,
    )
    session.add(org_vehicle)
    await session.flush()

    # Set RLS context so queries work
    await _set_rls_org_id(session, str(org.id))

    return {
        "plan": plan,
        "org": org,
        "user": user,
        "customer": customer,
        "org_vehicle": org_vehicle,
    }


# ---------------------------------------------------------------------------
# Test 1a — Create invoice with org vehicle
# ---------------------------------------------------------------------------

class TestBugConditionExploration:
    """Exploration tests that surface the ForeignKeyViolationError bug."""

    @pytest.mark.asyncio
    async def test_1a_create_invoice_with_org_vehicle(self):
        """Create invoice with org vehicle: should succeed, link via org_vehicle_id.

        **Validates: Requirements 1.1, 1.2, 1.3**

        Bug condition: global_vehicle_id is set to an ID that exists in
        org_vehicles but NOT in global_vehicles.  On UNFIXED code this
        raises ForeignKeyViolationError because the code inserts the ID
        into customer_vehicles.global_vehicle_id (FK to global_vehicles.id).
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_test_fixtures(session)

                result = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["org_vehicle"].id,
                    vehicle_rego="TEST123",
                )

                # Assert invoice was created successfully
                assert result is not None
                assert "id" in result

                # Assert the CustomerVehicle link uses org_vehicle_id
                cv_result = await session.execute(
                    select(CustomerVehicle).where(
                        CustomerVehicle.org_id == fixtures["org"].id,
                        CustomerVehicle.customer_id == fixtures["customer"].id,
                    )
                )
                cv = cv_result.scalar_one_or_none()
                assert cv is not None, "CustomerVehicle link should have been created"
                assert cv.org_vehicle_id == fixtures["org_vehicle"].id, (
                    "Link should use org_vehicle_id for org vehicles"
                )
                assert cv.global_vehicle_id is None, (
                    "global_vehicle_id should be NULL for org vehicle links"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -----------------------------------------------------------------------
    # Test 1b — Create invoice with org vehicle + service due date
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_1b_create_invoice_with_org_vehicle_service_due_date(self):
        """Create invoice with org vehicle + service_due_date: should update OrgVehicle.

        **Validates: Requirements 1.4**

        On UNFIXED code the GlobalVehicle query returns None and the
        service_due_date update is silently skipped.
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_test_fixtures(session)
                target_date = date(2025, 12, 1)

                result = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["org_vehicle"].id,
                    vehicle_rego="TEST123",
                    vehicle_service_due_date=target_date,
                )

                assert result is not None

                await session.refresh(fixtures["org_vehicle"])
                assert fixtures["org_vehicle"].service_due_date == target_date, (
                    "OrgVehicle.service_due_date should be updated"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -----------------------------------------------------------------------
    # Test 1c — Create invoice with org vehicle + WOF expiry
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_1c_create_invoice_with_org_vehicle_wof_expiry(self):
        """Create invoice with org vehicle + wof_expiry: should update OrgVehicle.

        **Validates: Requirements 1.4**

        On UNFIXED code the GlobalVehicle query returns None and the
        wof_expiry update is silently skipped.
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_test_fixtures(session)
                target_date = date(2026, 3, 15)

                result = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["org_vehicle"].id,
                    vehicle_rego="TEST123",
                    vehicle_wof_expiry_date=target_date,
                )

                assert result is not None

                await session.refresh(fixtures["org_vehicle"])
                assert fixtures["org_vehicle"].wof_expiry == target_date, (
                    "OrgVehicle.wof_expiry should be updated"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -----------------------------------------------------------------------
    # Test 1d — Create invoice with org vehicle + odometer
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_1d_create_invoice_with_org_vehicle_odometer(self):
        """Create invoice with org vehicle + odometer: should record on OrgVehicle.

        **Validates: Requirements 1.1, 1.2**

        On UNFIXED code this either crashes (ForeignKeyViolationError on
        customer_vehicles insert) or the odometer recording fails because
        record_odometer_reading() only supports global vehicles.
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_test_fixtures(session)

                result = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["org_vehicle"].id,
                    vehicle_rego="TEST123",
                    vehicle_odometer=85000,
                )

                assert result is not None

                await session.refresh(fixtures["org_vehicle"])
                assert fixtures["org_vehicle"].odometer_last_recorded == 85000, (
                    "OrgVehicle.odometer_last_recorded should be updated"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -----------------------------------------------------------------------
    # Test 1e — Update invoice with org vehicle + metadata
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_1e_update_invoice_with_org_vehicle_metadata(self):
        """Update draft invoice with org vehicle metadata: should update OrgVehicle.

        **Validates: Requirements 1.4**

        On UNFIXED code the GlobalVehicle query returns None and the
        metadata updates are silently skipped.
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_test_fixtures(session)

                # First create a draft invoice WITHOUT the org vehicle
                # (to avoid the FK crash on create)
                draft = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    status="draft",
                )
                assert draft is not None
                invoice_id = uuid.UUID(str(draft["id"]))

                # Now update the draft with org vehicle metadata
                service_date = date(2025, 11, 1)
                wof_date = date(2026, 2, 28)

                updated = await update_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    invoice_id=invoice_id,
                    updates={
                        "global_vehicle_id": fixtures["org_vehicle"].id,
                        "vehicle_service_due_date": service_date,
                        "vehicle_wof_expiry_date": wof_date,
                    },
                )
                assert updated is not None

                # Refresh the org vehicle and check metadata was updated
                await session.refresh(fixtures["org_vehicle"])
                assert fixtures["org_vehicle"].service_due_date == service_date, (
                    "OrgVehicle.service_due_date should be updated via update_invoice"
                )
                assert fixtures["org_vehicle"].wof_expiry == wof_date, (
                    "OrgVehicle.wof_expiry should be updated via update_invoice"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -----------------------------------------------------------------------
    # Test 1f — Duplicate link detection for org vehicles
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_1f_duplicate_link_detection_for_org_vehicles(self):
        """Creating two invoices with same org vehicle should not duplicate the link.

        **Validates: Requirements 1.2**

        On UNFIXED code the duplicate check queries
        CustomerVehicle.global_vehicle_id which never matches org vehicle
        links (stored under org_vehicle_id), so a duplicate link would be
        created.
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_test_fixtures(session)

                # Create first invoice with org vehicle
                result1 = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["org_vehicle"].id,
                    vehicle_rego="TEST123",
                )
                assert result1 is not None

                # Create second invoice with same org vehicle and customer
                result2 = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["org_vehicle"].id,
                    vehicle_rego="TEST123",
                )
                assert result2 is not None

                # Count CustomerVehicle links — should be exactly 1
                cv_result = await session.execute(
                    select(CustomerVehicle).where(
                        CustomerVehicle.org_id == fixtures["org"].id,
                        CustomerVehicle.customer_id == fixtures["customer"].id,
                        CustomerVehicle.org_vehicle_id == fixtures["org_vehicle"].id,
                    )
                )
                links = cv_result.scalars().all()
                assert len(links) == 1, (
                    f"Expected exactly 1 CustomerVehicle link, got {len(links)}. "
                    "Duplicate link detection should prevent duplicates for org vehicles."
                )
        finally:
            await session.close()
            await test_engine.dispose()
