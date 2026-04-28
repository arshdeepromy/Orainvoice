"""Preservation property tests — Invoice Vehicle FK Fix.

These tests capture the EXISTING (correct) behavior for global-vehicle
and no-vehicle invoice creation/update paths.  They run on UNFIXED code
and must ALL PASS — confirming the baseline behavior that the fix must
preserve.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings as hyp_settings, strategies as st, HealthCheck
from sqlalchemy import select
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
from app.modules.admin.models import GlobalVehicle, Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.customers.models import Customer
from app.modules.invoices.service import create_invoice, update_invoice
from app.modules.module_management.models import OrgModule
from app.modules.vehicles.models import CustomerVehicle, OdometerReading


# ---------------------------------------------------------------------------
# Per-test engine/session factory
# ---------------------------------------------------------------------------

async def _make_session() -> tuple[AsyncSession, "AsyncEngine"]:
    """Create a fresh engine + session for each test."""
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
# Helpers — create prerequisite records with a GLOBAL vehicle
# ---------------------------------------------------------------------------

async def _create_global_vehicle_fixtures(session: AsyncSession):
    """Create a subscription plan, org, user, customer, and GLOBAL vehicle.

    Returns a dict with all the created objects and their IDs.
    """
    # 1. Subscription plan
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
        name="Preservation Test Org",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        settings={"gst_percentage": 15, "invoice_prefix": "PRES-"},
    )
    session.add(org)
    await session.flush()

    # 3. Enable the "vehicles" module
    org_module = OrgModule(
        org_id=org.id,
        module_slug="vehicles",
        is_enabled=True,
    )
    session.add(org_module)
    await session.flush()

    # 4. User
    user = User(
        org_id=org.id,
        email=f"pres-{uuid.uuid4().hex[:8]}@example.com",
        first_name="Preservation",
        last_name="Tester",
        role="org_admin",
        password_hash="not-a-real-hash",
    )
    session.add(user)
    await session.flush()

    # 5. Customer
    customer = Customer(
        org_id=org.id,
        first_name="Preserve",
        last_name="Baseline",
    )
    session.add(customer)
    await session.flush()

    # 6. GLOBAL vehicle — exists in global_vehicles table
    rego = f"GV{uuid.uuid4().hex[:6].upper()}"
    global_vehicle = GlobalVehicle(
        rego=rego,
        make="Honda",
        model="Civic",
        year=2021,
    )
    session.add(global_vehicle)
    await session.flush()

    # Set RLS context
    await _set_rls_org_id(session, str(org.id))

    return {
        "plan": plan,
        "org": org,
        "user": user,
        "customer": customer,
        "global_vehicle": global_vehicle,
    }


# ---------------------------------------------------------------------------
# Preservation Tests
# ---------------------------------------------------------------------------

class TestPreservationGlobalVehicle:
    """Preservation tests: global vehicle behavior must remain unchanged."""

    # -------------------------------------------------------------------
    # 3.1 — Global vehicle auto-link creates CustomerVehicle with
    #        global_vehicle_id set
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_3_1_global_vehicle_creates_customer_vehicle_link(self):
        """create_invoice() with a global vehicle creates CustomerVehicle
        with global_vehicle_id set.

        **Validates: Requirements 3.1**
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_global_vehicle_fixtures(session)

                result = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["global_vehicle"].id,
                    vehicle_rego=fixtures["global_vehicle"].rego,
                )

                assert result is not None
                assert "id" in result

                # Verify CustomerVehicle link uses global_vehicle_id
                cv_result = await session.execute(
                    select(CustomerVehicle).where(
                        CustomerVehicle.org_id == fixtures["org"].id,
                        CustomerVehicle.customer_id == fixtures["customer"].id,
                        CustomerVehicle.global_vehicle_id == fixtures["global_vehicle"].id,
                    )
                )
                cv = cv_result.scalar_one_or_none()
                assert cv is not None, (
                    "CustomerVehicle link should be created for global vehicle"
                )
                assert cv.global_vehicle_id == fixtures["global_vehicle"].id
                assert cv.org_vehicle_id is None, (
                    "org_vehicle_id should be NULL for global vehicle links"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -------------------------------------------------------------------
    # 3.2 — Duplicate link prevention for global vehicles
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_3_2_global_vehicle_duplicate_link_prevention(self):
        """create_invoice() with same global vehicle twice does not
        create a duplicate CustomerVehicle link.

        **Validates: Requirements 3.2**
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_global_vehicle_fixtures(session)

                # First invoice
                result1 = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["global_vehicle"].id,
                    vehicle_rego=fixtures["global_vehicle"].rego,
                )
                assert result1 is not None

                # Second invoice with same global vehicle + customer
                result2 = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["global_vehicle"].id,
                    vehicle_rego=fixtures["global_vehicle"].rego,
                )
                assert result2 is not None

                # Count links — should be exactly 1
                cv_result = await session.execute(
                    select(CustomerVehicle).where(
                        CustomerVehicle.org_id == fixtures["org"].id,
                        CustomerVehicle.customer_id == fixtures["customer"].id,
                        CustomerVehicle.global_vehicle_id == fixtures["global_vehicle"].id,
                    )
                )
                links = cv_result.scalars().all()
                assert len(links) == 1, (
                    f"Expected exactly 1 CustomerVehicle link, got {len(links)}"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -------------------------------------------------------------------
    # 3.3 — Odometer recording for global vehicles
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_3_3_global_vehicle_odometer_recording(self):
        """create_invoice() with a global vehicle and odometer calls
        record_odometer_reading() and updates GlobalVehicle.

        **Validates: Requirements 3.3**
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_global_vehicle_fixtures(session)

                result = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["global_vehicle"].id,
                    vehicle_rego=fixtures["global_vehicle"].rego,
                    vehicle_odometer=95000,
                )

                assert result is not None

                # Verify odometer was recorded on the global vehicle
                await session.refresh(fixtures["global_vehicle"])
                assert fixtures["global_vehicle"].odometer_last_recorded == 95000, (
                    "GlobalVehicle.odometer_last_recorded should be updated"
                )

                # Verify an OdometerReading record was created
                odom_result = await session.execute(
                    select(OdometerReading).where(
                        OdometerReading.global_vehicle_id == fixtures["global_vehicle"].id,
                    )
                )
                readings = odom_result.scalars().all()
                assert len(readings) >= 1, (
                    "At least one OdometerReading should be created"
                )
                assert any(r.reading_km == 95000 for r in readings), (
                    "OdometerReading with 95000 km should exist"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -------------------------------------------------------------------
    # 3.4 — Service due date update for global vehicles
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_3_4_global_vehicle_service_due_date_update(self):
        """create_invoice() with a global vehicle and service_due_date
        updates GlobalVehicle.service_due_date.

        **Validates: Requirements 3.4**
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_global_vehicle_fixtures(session)
                target_date = date(2025, 12, 15)

                result = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["global_vehicle"].id,
                    vehicle_rego=fixtures["global_vehicle"].rego,
                    vehicle_service_due_date=target_date,
                )

                assert result is not None

                await session.refresh(fixtures["global_vehicle"])
                assert fixtures["global_vehicle"].service_due_date == target_date, (
                    "GlobalVehicle.service_due_date should be updated"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -------------------------------------------------------------------
    # 3.5 — WOF expiry update for global vehicles
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_3_5_global_vehicle_wof_expiry_update(self):
        """create_invoice() with a global vehicle and wof_expiry_date
        updates GlobalVehicle.wof_expiry.

        **Validates: Requirements 3.5**
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_global_vehicle_fixtures(session)
                target_date = date(2026, 6, 30)

                result = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["global_vehicle"].id,
                    vehicle_rego=fixtures["global_vehicle"].rego,
                    vehicle_wof_expiry_date=target_date,
                )

                assert result is not None

                await session.refresh(fixtures["global_vehicle"])
                assert fixtures["global_vehicle"].wof_expiry == target_date, (
                    "GlobalVehicle.wof_expiry should be updated"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -------------------------------------------------------------------
    # 3.6 — No vehicle skips auto-link logic
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_3_6_no_vehicle_skips_auto_link(self):
        """create_invoice() with global_vehicle_id=None skips auto-link
        logic entirely — no CustomerVehicle created.

        **Validates: Requirements 3.6**
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_global_vehicle_fixtures(session)

                result = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=None,
                )

                assert result is not None
                assert "id" in result

                # Verify NO CustomerVehicle link was created
                cv_result = await session.execute(
                    select(CustomerVehicle).where(
                        CustomerVehicle.org_id == fixtures["org"].id,
                        CustomerVehicle.customer_id == fixtures["customer"].id,
                    )
                )
                links = cv_result.scalars().all()
                assert len(links) == 0, (
                    f"No CustomerVehicle links should exist, got {len(links)}"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -------------------------------------------------------------------
    # 3.7 — update_invoice() with global vehicle updates metadata
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_3_7_update_invoice_global_vehicle_metadata(self):
        """update_invoice() with a global vehicle ID updates
        GlobalVehicle service_due_date and wof_expiry.

        **Validates: Requirements 3.7**
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_global_vehicle_fixtures(session)

                # Create a draft invoice first (without vehicle to avoid
                # complicating with auto-link)
                draft = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    status="draft",
                )
                assert draft is not None
                invoice_id = uuid.UUID(str(draft["id"]))

                # Update with global vehicle metadata
                service_date = date(2025, 11, 1)
                wof_date = date(2026, 4, 15)

                updated = await update_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    invoice_id=invoice_id,
                    updates={
                        "global_vehicle_id": fixtures["global_vehicle"].id,
                        "vehicle_service_due_date": service_date,
                        "vehicle_wof_expiry_date": wof_date,
                    },
                )
                assert updated is not None

                # Verify GlobalVehicle metadata was updated
                await session.refresh(fixtures["global_vehicle"])
                assert fixtures["global_vehicle"].service_due_date == service_date, (
                    "GlobalVehicle.service_due_date should be updated via update_invoice"
                )
                assert fixtures["global_vehicle"].wof_expiry == wof_date, (
                    "GlobalVehicle.wof_expiry should be updated via update_invoice"
                )
        finally:
            await session.close()
            await test_engine.dispose()


# ---------------------------------------------------------------------------
# Property-Based Tests (Hypothesis)
# ---------------------------------------------------------------------------

# Hypothesis strategies for generating test data
_service_due_dates = st.dates(
    min_value=date(2025, 1, 1),
    max_value=date(2030, 12, 31),
)

_wof_expiry_dates = st.dates(
    min_value=date(2025, 1, 1),
    max_value=date(2030, 12, 31),
)

_odometer_values = st.integers(min_value=1, max_value=500000)


class TestPreservationPropertyBased:
    """Property-based preservation tests using Hypothesis.

    These generate many combinations of vehicle metadata inputs to verify
    that global-vehicle and no-vehicle paths are preserved across the
    full non-buggy input domain.
    """

    # -------------------------------------------------------------------
    # Property: Global vehicle metadata updates are always applied
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    @hyp_settings(
        max_examples=5,
        deadline=30000,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
    )
    @given(
        service_due=st.one_of(st.none(), _service_due_dates),
        wof_expiry=st.one_of(st.none(), _wof_expiry_dates),
        odometer=st.one_of(st.none(), _odometer_values),
    )
    async def test_prop_global_vehicle_metadata_preserved(
        self, service_due, wof_expiry, odometer,
    ):
        """For any combination of metadata fields on a global vehicle,
        create_invoice() applies all provided updates to GlobalVehicle.

        **Validates: Requirements 3.3, 3.4, 3.5**
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_global_vehicle_fixtures(session)

                result = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=fixtures["global_vehicle"].id,
                    vehicle_rego=fixtures["global_vehicle"].rego,
                    vehicle_service_due_date=service_due,
                    vehicle_wof_expiry_date=wof_expiry,
                    vehicle_odometer=odometer,
                )

                assert result is not None, "Invoice creation should succeed"

                await session.refresh(fixtures["global_vehicle"])

                if service_due is not None:
                    assert fixtures["global_vehicle"].service_due_date == service_due, (
                        f"service_due_date should be {service_due}"
                    )

                if wof_expiry is not None:
                    assert fixtures["global_vehicle"].wof_expiry == wof_expiry, (
                        f"wof_expiry should be {wof_expiry}"
                    )

                if odometer is not None and odometer > 0:
                    assert fixtures["global_vehicle"].odometer_last_recorded == odometer, (
                        f"odometer_last_recorded should be {odometer}"
                    )

                # CustomerVehicle link should always use global_vehicle_id
                cv_result = await session.execute(
                    select(CustomerVehicle).where(
                        CustomerVehicle.org_id == fixtures["org"].id,
                        CustomerVehicle.customer_id == fixtures["customer"].id,
                        CustomerVehicle.global_vehicle_id == fixtures["global_vehicle"].id,
                    )
                )
                cv = cv_result.scalar_one_or_none()
                assert cv is not None, "CustomerVehicle link should exist"
                assert cv.org_vehicle_id is None, "org_vehicle_id should be NULL"
        finally:
            await session.close()
            await test_engine.dispose()

    # -------------------------------------------------------------------
    # Property: No-vehicle invoices never create links
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    @hyp_settings(
        max_examples=3,
        deadline=30000,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
    )
    @given(
        status=st.just("draft"),
    )
    async def test_prop_no_vehicle_never_creates_link(self, status):
        """For any invoice created without a vehicle ID, no CustomerVehicle
        link is created regardless of other parameters.

        **Validates: Requirements 3.6**
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_global_vehicle_fixtures(session)

                result = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    global_vehicle_id=None,
                    status=status,
                )

                assert result is not None

                cv_result = await session.execute(
                    select(CustomerVehicle).where(
                        CustomerVehicle.org_id == fixtures["org"].id,
                        CustomerVehicle.customer_id == fixtures["customer"].id,
                    )
                )
                links = cv_result.scalars().all()
                assert len(links) == 0, (
                    "No CustomerVehicle links should exist for no-vehicle invoices"
                )
        finally:
            await session.close()
            await test_engine.dispose()

    # -------------------------------------------------------------------
    # Property: update_invoice with global vehicle always updates metadata
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    @hyp_settings(
        max_examples=5,
        deadline=30000,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
    )
    @given(
        service_due=st.one_of(st.none(), _service_due_dates),
        wof_expiry=st.one_of(st.none(), _wof_expiry_dates),
    )
    async def test_prop_update_invoice_global_vehicle_metadata_preserved(
        self, service_due, wof_expiry,
    ):
        """For any combination of metadata fields on update_invoice() with
        a global vehicle, the GlobalVehicle record is updated correctly.

        **Validates: Requirements 3.7**
        """
        session, test_engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)
                fixtures = await _create_global_vehicle_fixtures(session)

                # Create a draft invoice first
                draft = await create_invoice(
                    session,
                    org_id=fixtures["org"].id,
                    user_id=fixtures["user"].id,
                    customer_id=fixtures["customer"].id,
                    status="draft",
                )
                assert draft is not None
                invoice_id = uuid.UUID(str(draft["id"]))

                # Build updates dict
                updates: dict = {
                    "global_vehicle_id": fixtures["global_vehicle"].id,
                }
                if service_due is not None:
                    updates["vehicle_service_due_date"] = service_due
                if wof_expiry is not None:
                    updates["vehicle_wof_expiry_date"] = wof_expiry

                # Only run update if we have metadata to update
                if service_due is not None or wof_expiry is not None:
                    updated = await update_invoice(
                        session,
                        org_id=fixtures["org"].id,
                        user_id=fixtures["user"].id,
                        invoice_id=invoice_id,
                        updates=updates,
                    )
                    assert updated is not None

                    await session.refresh(fixtures["global_vehicle"])

                    if service_due is not None:
                        assert fixtures["global_vehicle"].service_due_date == service_due, (
                            f"service_due_date should be {service_due}"
                        )

                    if wof_expiry is not None:
                        assert fixtures["global_vehicle"].wof_expiry == wof_expiry, (
                            f"wof_expiry should be {wof_expiry}"
                        )
        finally:
            await session.close()
            await test_engine.dispose()
