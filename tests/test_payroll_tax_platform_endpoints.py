"""Example tests for the Payroll_Tax_Settings platform endpoints (spec task 8.5).

These are **example** tests (not property tests) for the platform tier of the
``payroll_tax`` module. They exercise the service functions that back the
platform router (``GET``/``PUT /api/v2/admin/platform-tax-default``):

* :func:`app.modules.payroll_tax.service.get_platform_default`
* :func:`app.modules.payroll_tax.service.update_platform_default`

They follow the DB-backed pattern used by the payroll-tax property tests
(``tests/property/test_resolution_totality.py`` and
``tests/test_payroll_tax_persistence_roundtrip_property.py``): a fresh async
engine per example (asyncpg connections are bound to the event loop
``asyncio.run`` creates), with everything done inside a single transaction that
is **rolled back** at the end so nothing persists. The services use ``flush``
(never ``commit``), so the trailing ``rollback`` discards any write.

Two behaviours are asserted:

1. **Platform GET returns every documented field (Req 2.1).** The single
   ``platform_tax_default`` row seeded by migration ``0231`` is read back via
   ``get_platform_default`` and projected through ``PlatformTaxDefaultView``
   (exactly as the router does). Every documented Tax_Field — the PAYE bracket
   set, all five secondary rates (SB, S, SH, ST, SA), the ACC levy rate + cap,
   the student-loan rate + threshold, the five IETC params, the two KiwiSaver
   defaults, and the tax-year label — is present and populated.

2. **A forced message-builder fault still rejects and persists nothing
   (Req 8.7).** An **invalid** platform fragment is submitted to
   ``update_platform_default`` while the validator's human-readable message
   generation is forced to raise (the real ``_field_error`` try/except is still
   exercised — only the supplied message builder is replaced with one that
   always throws). The submission is still rejected with ``HTTPException(422)``
   and the stored platform row is left unchanged (nothing persisted).

**Validates: Requirements 2.1, 8.7**
"""

from __future__ import annotations

import asyncio
import copy
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests, e.g. tests/test_payroll_tax_persistence_roundtrip_property.py).
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
from app.modules.payroll_tax import models as _payroll_tax_models  # noqa: F401

from app.modules.payroll_tax import validation as payroll_tax_validation
from app.modules.payroll_tax.models import PlatformTaxDefault
from app.modules.payroll_tax.schemas import SECONDARY_CODES, PlatformTaxDefaultView
from app.modules.payroll_tax.service import (
    get_platform_default,
    update_platform_default,
)


# ---------------------------------------------------------------------------
# Engine / session helpers (mirror the reference DB-backed property tests).
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _platform_view(row: PlatformTaxDefault) -> PlatformTaxDefaultView:
    """Project a platform row into its editable view, exactly as the router does."""
    data: dict = dict(row.config or {})
    data["tax_year_label"] = row.tax_year_label
    data["updated_at"] = row.updated_at
    data["updated_by"] = row.updated_by
    return PlatformTaxDefaultView.model_validate(data)


# ---------------------------------------------------------------------------
# Test 1 — Platform GET returns every documented field (Req 2.1).
# ---------------------------------------------------------------------------


_IETC_KEYS: tuple[str, ...] = (
    "amount",
    "lower",
    "abatement_start",
    "abatement_rate",
    "upper",
)


async def _run_get_returns_every_field() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                # Read the migration-seeded singleton platform row (the dev DB is
                # at head, so migration 0231 has created exactly one row).
                row = await get_platform_default(session)
                view = _platform_view(row)

                # PAYE bracket set: non-empty, every band populated, exactly one
                # open-ended top band (upper_limit is None) and it is last.
                assert len(view.paye_brackets) >= 1
                for bracket in view.paye_brackets:
                    assert bracket.rate is not None
                open_ended = [
                    i
                    for i, b in enumerate(view.paye_brackets)
                    if b.upper_limit is None
                ]
                assert open_ended == [len(view.paye_brackets) - 1]

                # Secondary rates: every one of the five documented codes present
                # and populated.
                for code in SECONDARY_CODES:
                    value = getattr(view.secondary_rates, code)
                    assert value is not None, f"secondary code {code} missing"

                # Scalar rate / cap / threshold / KiwiSaver fields populated.
                for attr in (
                    "acc_levy_rate",
                    "acc_max_liable_earnings",
                    "student_loan_rate",
                    "student_loan_threshold",
                    "default_kiwisaver_employee_rate",
                    "default_kiwisaver_employer_rate",
                ):
                    assert getattr(view, attr) is not None, f"{attr} is blank"

                # IETC params: every documented sub-field populated.
                for key in _IETC_KEYS:
                    assert getattr(view.ietc, key) is not None, f"ietc.{key} is blank"

                # Tax-year label: a non-blank string.
                assert isinstance(view.tax_year_label, str)
                assert view.tax_year_label.strip() != ""
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_platform_get_returns_every_documented_field() -> None:
    """Platform GET exposes every documented Tax_Field, all populated (Req 2.1)."""
    asyncio.run(_run_get_returns_every_field())


# ---------------------------------------------------------------------------
# Test 2 — A forced message-builder fault still rejects and persists nothing
#          (Req 8.7).
# ---------------------------------------------------------------------------

#: A platform document that is INVALID: ``acc_max_liable_earnings`` must be > 0
#: (Req 8.2) and the secondary set omits the required codes (Req 8.5), so
#: ``validate_config_fragment`` is guaranteed to emit at least one FieldError —
#: forcing the (now-faulty) message builder to run.
_INVALID_FRAGMENT: dict = {
    "paye_brackets": [
        {"upper_limit": 15600, "rate": 0.105},
        {"upper_limit": None, "rate": 0.39},
    ],
    "secondary_rates": {"SB": 0.105},  # missing S, SH, ST, SA (Req 8.5)
    "acc_levy_rate": 0.016,
    "acc_max_liable_earnings": 0,  # not > 0 (Req 8.2)
    "student_loan_rate": 0.12,
    "student_loan_threshold": 24128,
    "ietc": {
        "amount": 520,
        "lower": 24000,
        "abatement_start": 44000,
        "abatement_rate": 0.13,
        "upper": 48000,
    },
    "default_kiwisaver_employee_rate": 3.00,
    "default_kiwisaver_employer_rate": 3.00,
    "tax_year_label": "test/26",
}


async def _run_message_builder_fault_rejects_and_persists_nothing() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                # Snapshot the seeded platform row before the (doomed) update so
                # we can prove nothing was persisted.
                row_before = await get_platform_default(session)
                config_before = copy.deepcopy(row_before.config)
                label_before = row_before.tax_year_label
                updated_at_before = row_before.updated_at
                row_id_before = row_before.id

                # Submit the invalid fragment. The validator must still reject it
                # with a 422 even though message generation throws.
                raised: HTTPException | None = None
                try:
                    await update_platform_default(
                        session,
                        fields=_INVALID_FRAGMENT,
                        user_id=uuid.uuid4(),
                        request=None,
                    )
                except HTTPException as exc:
                    raised = exc

                assert raised is not None, (
                    "an invalid submission must be rejected even when the "
                    "validation message builder raises (Req 8.7)"
                )
                assert raised.status_code == 422, (
                    f"expected 422 rejection, got {raised.status_code}"
                )
                # The rejection still carries per-field detail (with the generic
                # substituted message, since the builder was forced to raise).
                assert isinstance(raised.detail, list) and len(raised.detail) >= 1
                for item in raised.detail:
                    assert item.get("field")
                    assert item.get("message")

                # Nothing persisted: the stored platform row is unchanged. Expire
                # any cached state and re-read from the database.
                session.expire_all()
                row_after = await get_platform_default(session)
                assert row_after.id == row_id_before
                assert row_after.config == config_before, (
                    "platform config must be unchanged after a rejected submission"
                )
                assert row_after.tax_year_label == label_before
                assert row_after.updated_at == updated_at_before
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_message_builder_fault_still_rejects_and_persists_nothing(monkeypatch) -> None:
    """A forced message-builder fault still rejects and persists nothing (Req 8.7).

    The validator's ``_field_error`` wraps message generation in a try/except
    that substitutes a generic message if the builder raises, so an invalid
    submission is still rejected. Here every message builder is forced to raise
    (while the real try/except is still exercised) and we assert the invalid
    platform submission is rejected with a 422 and the stored row is unchanged.
    """
    real_field_error = payroll_tax_validation._field_error

    def _faulty_field_error(field, message_builder):
        # Replace the supplied builder with one that always raises, but route it
        # through the REAL _field_error so its try/except fallback is exercised.
        def _boom() -> str:
            raise RuntimeError("forced message-builder fault")

        return real_field_error(field, _boom)

    monkeypatch.setattr(
        payroll_tax_validation, "_field_error", _faulty_field_error
    )

    asyncio.run(_run_message_builder_fault_rejects_and_persists_nothing())
