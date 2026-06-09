# Feature: customer-reminder-consent
"""Integration tests for ``revoke_customer_reminders`` (A5).

Covers (A5):
  - Single-category revocation flips ``reminder_config[<cat>].enabled``
    to False, appends one revocation entry, and writes one audit row.
  - Multi-category revocation flips every affected category and appends
    one revocation entry that lists all of them.
  - Idempotent re-confirmation: when every affected category is already
    disabled, the function early-returns the unchanged config and does
    NOT append a new revocation entry or audit row.
  - Audit ``after_value`` is redacted: it contains neither
    ``recorded_by_user_id`` nor ``recorded_by_user_email`` (the actor
    identity lives on the audit row's own ``user_id`` column per
    Req 7.2).

The HTTP endpoint test ``test_revoke_endpoint_persists_and_audits``
called out in A5's verify line is deferred to B2 (it needs the new
``POST /customers/{id}/reminders/revoke`` route).

Refs: Requirements 3.4, 3.5, 3.6, 3.8, 3.9, NFR-7, 7.2.
"""

from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure SQLAlchemy relationship models are loaded.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401

from app.modules.customers.consent import RemindersRevocationRecord
from app.modules.customers.models import Customer
from app.modules.customers.service import revoke_customer_reminders


# ``flag_modified`` requires a real SQLAlchemy-instrumented instance; with a
# MagicMock-backed Customer it raises ``AttributeError: _sa_instance_state``.
# Patch it to a no-op for the duration of every test in this module — the
# mutation is observable via direct attribute assignment which our mocks
# capture, so we don't lose the ``custom_fields`` write signal.
@pytest.fixture(autouse=True)
def _patch_flag_modified():
    with patch(
        "app.modules.customers.consent.flag_modified", lambda *a, **kw: None
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers — minimal mocks for the service-level transaction surface
# ---------------------------------------------------------------------------


def _make_customer(
    *,
    org_id: uuid.UUID,
    custom_fields: dict | None = None,
) -> MagicMock:
    """Build a Customer ORM mock the service can mutate in place."""
    customer = MagicMock(spec=Customer)
    customer.id = uuid.uuid4()
    customer.org_id = org_id
    customer.custom_fields = custom_fields or {}
    return customer


def _make_db(customer: MagicMock, audit_rows: list[dict]) -> AsyncMock:
    """Build an AsyncMock DB session.

    * Returns ``customer`` on any ``select(Customer)`` execute (both the
      service's own SELECT and the SELECT inside ``record_consent_revoked``).
    * Captures every ``audit_log`` ``INSERT`` text statement: the bound
      parameters dict is appended to ``audit_rows`` so tests can assert
      on the redacted ``after_value`` payload.
    """

    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    def _execute(stmt, *args, **kwargs):
        # Detect audit INSERTs by looking at the bind parameters: they
        # carry ``action`` and ``after_value`` keys that ``select(Customer)``
        # never has.
        params = args[0] if args else kwargs.get("parameters")
        if isinstance(params, dict) and "action" in params and "after_value" in params:
            audit_rows.append(params)

        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=customer)
        result.scalar_one = MagicMock(return_value=customer)
        return result

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _current_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "staff@example.com"
    return user


def _revocation(
    *,
    user: MagicMock,
    categories: list[str],
    channel: str = "sms",
    obtained_method: str = "phone",
    reason_note: str = "Customer asked over the phone",
) -> RemindersRevocationRecord:
    return RemindersRevocationRecord(
        revoked_at=datetime.now(timezone.utc),
        source=f"manually_recorded_by_staff:{obtained_method}",
        recorded_by_user_id=user.id,
        recorded_by_user_email=user.email,
        channel=channel,  # type: ignore[arg-type]
        categories_affected=categories,  # type: ignore[arg-type]
        reason_note=reason_note,
    )


def _enabled_config(*categories: str, channel: str = "sms") -> dict:
    """Build a ``reminder_config`` dict with ``enabled: True`` for every
    category in ``categories`` and ``enabled: False`` for the others."""
    out: dict = {}
    for cat in (
        "service_due",
        "wof_expiry",
        "cof_expiry",
        "registration_expiry",
    ):
        out[cat] = {
            "enabled": cat in categories,
            "days_before": 30,
            "channel": channel,
        }
    return out


# ---------------------------------------------------------------------------
# 1. Single-category revoke flips and appends
# ---------------------------------------------------------------------------


class TestSingleCategoryRevokeFlipAndAppend:
    """A5 / Req 3.4, 3.5, 3.7: flip + append + audit on single category."""

    @pytest.mark.asyncio
    async def test_single_category_revoke_flip_and_append(self):
        org_id = uuid.uuid4()
        customer = _make_customer(
            org_id=org_id,
            custom_fields={"reminder_config": _enabled_config("wof_expiry")},
        )
        audit_rows: list[dict] = []
        db = _make_db(customer, audit_rows)
        user = _current_user()

        record = _revocation(user=user, categories=["wof_expiry"])

        result = await revoke_customer_reminders(
            db,
            org_id=org_id,
            customer_id=customer.id,
            current_user=user,
            record=record,
        )

        # Returned config matches the post-revocation customer state.
        assert result["wof_expiry"]["enabled"] is False
        assert customer.custom_fields["reminder_config"]["wof_expiry"]["enabled"] is False
        # Other categories untouched.
        assert customer.custom_fields["reminder_config"]["service_due"]["enabled"] is False

        # Exactly one revocation entry was appended.
        revocations = customer.custom_fields["reminder_consent_revocations"]
        assert len(revocations) == 1
        rev = revocations[0]
        assert rev["categories_affected"] == ["wof_expiry"]
        assert rev["channel"] == "sms"
        assert rev["source"] == "manually_recorded_by_staff:phone"

        # And exactly one audit row was written.
        revoke_audit_rows = [
            r for r in audit_rows if r.get("action") == "customer.reminder_consent.revoked"
        ]
        assert len(revoke_audit_rows) == 1


# ---------------------------------------------------------------------------
# 2. Multi-category revoke flips all and appends one entry
# ---------------------------------------------------------------------------


class TestMultiCategoryRevoke:
    """A5 / Req 3.4: a single revocation modal action covers multiple
    categories and produces ONE revocation entry listing all of them."""

    @pytest.mark.asyncio
    async def test_multi_category_revoke(self):
        org_id = uuid.uuid4()
        customer = _make_customer(
            org_id=org_id,
            custom_fields={
                "reminder_config": _enabled_config(
                    "wof_expiry", "service_due", "registration_expiry"
                )
            },
        )
        audit_rows: list[dict] = []
        db = _make_db(customer, audit_rows)
        user = _current_user()

        record = _revocation(
            user=user,
            categories=["wof_expiry", "service_due", "registration_expiry"],
            channel="both",
        )

        result = await revoke_customer_reminders(
            db,
            org_id=org_id,
            customer_id=customer.id,
            current_user=user,
            record=record,
        )

        # All three flipped to disabled.
        for cat in ("wof_expiry", "service_due", "registration_expiry"):
            assert result[cat]["enabled"] is False
            assert customer.custom_fields["reminder_config"][cat]["enabled"] is False

        # Exactly one revocation entry — listing all three categories.
        revocations = customer.custom_fields["reminder_consent_revocations"]
        assert len(revocations) == 1
        assert sorted(revocations[0]["categories_affected"]) == sorted(
            ["wof_expiry", "service_due", "registration_expiry"]
        )
        assert revocations[0]["channel"] == "both"


# ---------------------------------------------------------------------------
# 3. Idempotent re-confirmation: nothing currently enabled -> no-op
# ---------------------------------------------------------------------------


class TestIdempotentOnAlreadyRevoked:
    """A5 / CP-5: when every affected category is already disabled the
    function early-returns the unchanged config and does NOT append a new
    revocation entry."""

    @pytest.mark.asyncio
    async def test_idempotent_on_already_revoked(self):
        org_id = uuid.uuid4()
        # All four categories are already disabled.
        existing_config = _enabled_config()  # no categories enabled
        # Pre-existing revocations list to assert it is NOT mutated.
        existing_revocations = [{"prior": "entry"}]
        customer = _make_customer(
            org_id=org_id,
            custom_fields={
                "reminder_config": existing_config,
                "reminder_consent_revocations": list(existing_revocations),
            },
        )
        audit_rows: list[dict] = []
        db = _make_db(customer, audit_rows)
        user = _current_user()

        record = _revocation(user=user, categories=["wof_expiry", "cof_expiry"])

        result = await revoke_customer_reminders(
            db,
            org_id=org_id,
            customer_id=customer.id,
            current_user=user,
            record=record,
        )

        # Returned the unchanged config.
        assert result == existing_config
        # No mutation of revocations list.
        assert customer.custom_fields["reminder_consent_revocations"] == existing_revocations
        # No audit row written.
        revoke_audit_rows = [
            r for r in audit_rows if r.get("action") == "customer.reminder_consent.revoked"
        ]
        assert revoke_audit_rows == []


# ---------------------------------------------------------------------------
# 4. Audit after_value is redacted
# ---------------------------------------------------------------------------


class TestAuditAfterValueLacksRecordedByUser:
    """A5 / Req 7.2: ``after_value`` does NOT contain ``recorded_by_user_id``
    or ``recorded_by_user_email`` — the actor identity is captured by the
    audit row's own ``user_id`` column."""

    @pytest.mark.asyncio
    async def test_audit_after_value_lacks_recorded_by_user(self):
        org_id = uuid.uuid4()
        customer = _make_customer(
            org_id=org_id,
            custom_fields={"reminder_config": _enabled_config("wof_expiry")},
        )
        audit_rows: list[dict] = []
        db = _make_db(customer, audit_rows)
        user = _current_user()

        record = _revocation(user=user, categories=["wof_expiry"])

        await revoke_customer_reminders(
            db,
            org_id=org_id,
            customer_id=customer.id,
            current_user=user,
            record=record,
        )

        revoke_audit_rows = [
            r for r in audit_rows if r.get("action") == "customer.reminder_consent.revoked"
        ]
        assert len(revoke_audit_rows) == 1

        after_value = revoke_audit_rows[0]["after_value"]
        # ``after_value`` is JSON-serialised by ``write_audit_log`` —
        # accept either dict or string form.
        if isinstance(after_value, str):
            import json

            after_value = json.loads(after_value)

        assert isinstance(after_value, dict)
        assert "recorded_by_user_id" not in after_value
        assert "recorded_by_user_email" not in after_value
        # Sanity: the redacted-out fields are still on the customer record.
        rev = customer.custom_fields["reminder_consent_revocations"][0]
        assert rev["recorded_by_user_id"] == str(user.id)
        assert rev["recorded_by_user_email"] == user.email


# ---------------------------------------------------------------------------
# 5. HTTP endpoint (B2) — POST /customers/{id}/reminders/revoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_endpoint_persists_and_audits():
    """B2 / Req 3.2, 3.4, 3.5: the route handler composes the
    ``RemindersRevocationRecord`` (source =
    ``manually_recorded_by_staff:<obtained_method>``, recorded-by from the
    resolved User), calls :func:`revoke_customer_reminders`, flips the
    config, appends the revocation entry, writes exactly one audit row, and
    returns the post-revocation ``reminder_config``."""
    from app.modules.customers.router import revoke_customer_reminders_endpoint

    org_id = uuid.uuid4()
    user = _current_user()
    customer = _make_customer(
        org_id=org_id,
        custom_fields={"reminder_config": _enabled_config("wof_expiry")},
    )
    audit_rows: list[dict] = []
    db = _make_db(customer, audit_rows)
    # The handler resolves the acting user's email via ``db.get(User, id)``.
    db.get = AsyncMock(return_value=user)

    request = MagicMock()
    request.state = types.SimpleNamespace(
        org_id=str(org_id),
        user_id=str(user.id),
        client_ip="203.0.113.7",
    )
    request.json = AsyncMock(
        return_value={
            "obtained_method": "phone",
            "channel": "sms",
            "categories_affected": ["wof_expiry"],
            "reason_note": "Customer asked over the phone",
        }
    )

    updated = await revoke_customer_reminders_endpoint(
        str(customer.id), request, db
    )

    # Response carries the post-revocation config (the affected category off).
    assert updated["wof_expiry"]["enabled"] is False

    # The revocation entry was appended with the staff-composed source.
    revocations = customer.custom_fields["reminder_consent_revocations"]
    assert len(revocations) == 1
    assert revocations[0]["source"] == "manually_recorded_by_staff:phone"
    assert revocations[0]["categories_affected"] == ["wof_expiry"]
    assert revocations[0]["recorded_by_user_email"] == user.email

    # Exactly one redacted audit row.
    revoke_audit_rows = [
        r for r in audit_rows
        if r.get("action") == "customer.reminder_consent.revoked"
    ]
    assert len(revoke_audit_rows) == 1
