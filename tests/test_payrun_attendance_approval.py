# Feature: weekly Attendance approval drives the pay run (cycle-decoupled)
"""DB-backed tests: the pay run consumes weekly Attendance sign-offs.

Review/approval is decoupled from the pay cycle — hours are signed off per
shift on the Attendance tab (``time_clock_entries.flags.reviewed``), and
``run_pay_period`` auto-locks + pays the staff whose period is fully reviewed,
while skipping staff who still have un-reviewed shifts.

Mirrors the DB-backed pattern in
``tests/test_payrun_independent_per_cycle_property.py`` (fresh async engine per
test, full ORM imports, everything rolled back).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.notifications import models as _notif_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.module_management import models as _module_mgmt_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401
from app.modules.compliance_docs import models as _compliance_models  # noqa: F401
from app.modules.scheduling_v2 import models as _scheduling_v2_models  # noqa: F401
from app.modules.leave import models as _leave_models  # noqa: F401
from app.modules.time_clock import models as _time_clock_models  # noqa: F401
from app.modules.payslips import models as _payslip_models  # noqa: F401
from app.modules.timesheets import models as _timesheet_models  # noqa: F401
from app.modules.timesheets import pay_cycles as _pay_cycle_models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.organisations.models import Branch
from app.modules.payslips.models import PayPeriod, Payslip
from app.modules.staff.models import StaffMember
from app.modules.time_clock.models import TimeClockEntry
from app.modules.timesheets.models import Timesheet
from app.modules.timesheets.pay_cycles import PayCycle
from app.modules.timesheets.payrun import run_pay_period


_PERIOD_START = date(2026, 6, 1)
_PERIOD_END = date(2026, 6, 7)
_PERIOD_PAY = date(2026, 6, 10)
_WORK_DAY = date(2026, 6, 2)


async def _make_engine_and_factory():
    engine = create_async_engine(app_settings.database_url, echo=False, pool_size=2, max_overflow=0, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed(session: AsyncSession):
    plan = SubscriptionPlan(
        name=f"pr_appr_plan_{uuid.uuid4().hex[:8]}", monthly_price_nzd=0,
        user_seats=5, storage_quota_gb=1, carjam_lookups_included=0, enabled_modules=[],
    )
    session.add(plan)
    await session.flush()
    org = Organisation(
        name=f"pr_appr_org_{uuid.uuid4().hex[:8]}", plan_id=plan.id, status="active",
        storage_quota_gb=1, locale="en", timezone="UTC", settings={},
    )
    session.add(org)
    await session.flush()
    branch = Branch(org_id=org.id, name="Main", is_default=True)
    session.add(branch)
    await session.flush()
    cycle = PayCycle(
        org_id=org.id, name="Weekly", frequency="weekly",
        anchor_date=date(2026, 1, 5), pay_date_offset_days=3, is_default=True, active=True,
    )
    session.add(cycle)
    await session.flush()
    period = PayPeriod(
        org_id=org.id, start_date=_PERIOD_START, end_date=_PERIOD_END,
        pay_date=_PERIOD_PAY, pay_cycle_id=cycle.id, status="open",
    )
    session.add(period)
    await session.flush()
    return org.id, branch.id, period


async def _new_staff(session, *, org_id, name) -> StaffMember:
    staff = StaffMember(
        org_id=org_id, name=name, first_name=name.split()[0],
        employment_type="permanent", working_arrangement="rostered",
        hourly_rate=Decimal("25.00"), tax_code="M", is_active=True,
    )
    session.add(staff)
    await session.flush()
    return staff


async def _clock(session, *, org_id, staff_id, branch_id, reviewed: bool):
    session.add(TimeClockEntry(
        org_id=org_id, staff_id=staff_id, branch_id=branch_id,
        clock_in_at=datetime.combine(_WORK_DAY, time(9, 0), tzinfo=timezone.utc),
        clock_out_at=datetime.combine(_WORK_DAY, time(17, 0), tzinfo=timezone.utc),
        source="admin_manual", worked_minutes=480,
        flags={"reviewed": True} if reviewed else {},
    ))
    await session.flush()


async def _run_reviewed_pays_unreviewed_skipped() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id, period = await _seed(session)
                s_ok = await _new_staff(session, org_id=org_id, name="Approved Amy")
                s_pending = await _new_staff(session, org_id=org_id, name="Pending Pete")
                await _clock(session, org_id=org_id, staff_id=s_ok.id, branch_id=branch_id, reviewed=True)
                await _clock(session, org_id=org_id, staff_id=s_pending.id, branch_id=branch_id, reviewed=False)

                actor = User(org_id=org_id, email=f"actor_{uuid.uuid4().hex[:10]}@example.com", role="org_admin", is_active=True)
                session.add(actor)
                await session.flush()

                summary = await run_pay_period(
                    session, org_id=org_id, pay_period_id=period.id, actor_id=actor.id,
                )

                # The reviewed staff member is paid; the un-reviewed one is skipped.
                assert summary.payslips_generated == 1
                assert len(summary.skipped_pending_review) == 1
                assert summary.skipped_pending_review[0]["staff_id"] == str(s_pending.id)

                # The reviewed staff member's timesheet was auto-locked from the
                # Attendance sign-off (no manual approve/lock step).
                ok_ts = (await session.execute(
                    select(Timesheet).where(
                        Timesheet.staff_id == s_ok.id, Timesheet.pay_period_id == period.id,
                    )
                )).scalar_one()
                assert ok_ts.status == "locked"

                # A payslip draft exists for the reviewed staff, none for the pending one.
                pay_staff = {
                    r[0] for r in (await session.execute(
                        select(Payslip.staff_id).where(Payslip.pay_period_id == period.id)
                    )).all()
                }
                assert s_ok.id in pay_staff
                assert s_pending.id not in pay_staff
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_reviewed_pays_and_unreviewed_is_skipped():
    """Pay run pays staff approved on Attendance and skips un-reviewed staff.

    **Validates: weekly Attendance sign-off drives the pay run (no manual lock).**
    """
    asyncio.run(_run_reviewed_pays_unreviewed_skipped())
