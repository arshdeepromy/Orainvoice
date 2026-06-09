# Feature: customer-reminder-consent
"""Integration tests for the consent gate on ``update_customer_reminder_config``.

Covers (A4):
  - All four reminder categories validate when a covering consent_record is
    supplied directly to the service function.
  - No consent + newly-enabled pair raises ``RemindersConsentRequiredError``
    with a wire-shaped ``missing`` payload.
  - With covering consent_record, both ``reminder_consent`` and
    ``reminder_config`` are persisted on the customer row in one transaction.
  - Idempotent re-submit of the same config does not re-trigger the gate.
  - Already-disabled pairs (``enabled: false``) do NOT trigger the gate.
  - Partial coverage on a multi-pair newly-enabled config raises with only
    the still-uncovered pair in ``missing``.

The two HTTP endpoint tests called out in A4
(``test_put_returns_409_with_missing_list`` and
``test_put_with_consent_record_persists_both``) ship in B1 below — they
exercise the router handler directly with a mocked Request to verify the
409 mapping and the ``consent_record`` extraction from ``request.json()``.

Refs: Requirements 2.2, 2.3, 2.7, 2.8, 2.10, 2.11, 2.12, 2.13, 1.16.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure SQLAlchemy relationship models are loaded
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401

from app.modules.customers.consent import (
    RemindersConsentEntry,
    RemindersConsentRecord,
)
from app.modules.customers.exceptions import RemindersConsentRequiredError
from app.modules.customers.models import Customer
from app.modules.customers.service import update_customer_reminder_config


# ``flag_modified`` requires a real SQLAlchemy-instrumented instance; with a
# MagicMock-backed Customer it raises ``AttributeError: _sa_instance_state``.
# Patch it to a no-op for the duration of every test in this module — the
# mutation is observable via direct attribute assignment which our mocks
# capture, so we don't lose the ``custom_fields`` write signal.
@pytest.fixture(autouse=True)
def _patch_flag_modified():
    with patch(
        "app.modules.customers.service.flag_modified", lambda *a, **kw: None
    ), patch(
        "app.modules.customers.consent.flag_modified", lambda *a, **kw: None
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers — minimal mocks for the service-level transaction surface
# ---------------------------------------------------------------------------


def _make_customer(*, org_id: uuid.UUID, custom_fields: dict | None = None) -> MagicMock:
    """Build a Customer ORM mock the service can mutate in place."""
    customer = MagicMock(spec=Customer)
    customer.id = uuid.uuid4()
    customer.org_id = org_id
    customer.custom_fields = custom_fields or {}
    return customer


def _make_db(customer: MagicMock) -> AsyncMock:
    """Build an AsyncMock DB session that:

    * Returns ``customer`` on any ``select(Customer)`` execute (i.e. both the
      service's own SELECT and the SELECT inside ``record_consent_given``).
    * Returns a no-op result on the ``audit_log`` ``INSERT`` text statement.

    The service is expected to mutate ``customer.custom_fields`` in place;
    we rely on that mutation for the post-call assertions.
    """

    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    def _execute(stmt, *args, **kwargs):
        # We don't care which select fired — Customer is the only entity
        # selected from this code path. Audit INSERTs are TextClause objects
        # that flow through the same execute() and just need a result.
        result = MagicMock()
        # scalar_one_or_none is used by both the service's select and the
        # consent helper's _load_customer.
        result.scalar_one_or_none = MagicMock(return_value=customer)
        result.scalar_one = MagicMock(return_value=customer)
        return result

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _entry(category: str, channel: str) -> RemindersConsentEntry:
    return RemindersConsentEntry(
        vehicle_id=None, category=category, channel=channel
    )


def _consent_record(entries: list[RemindersConsentEntry]) -> RemindersConsentRecord:
    return RemindersConsentRecord(
        given_at=datetime.now(timezone.utc),
        source="manually_recorded_by_staff:phone",
        entries=entries,
        consent_text_version="2026-06-08-v1",
        recorded_by_user_id=uuid.uuid4(),
        recorded_by_user_email="staff@example.com",
    )


# ---------------------------------------------------------------------------
# 1. All four categories validate when a covering consent record is supplied
# ---------------------------------------------------------------------------


class TestAllFourCategoriesValidate:
    """A4 / Req 1.1, 2.7: all four categories accepted with covering consent."""

    @pytest.mark.asyncio
    async def test_all_four_categories_validate(self):
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)
        db = _make_db(customer)

        reminders = {
            "service_due": {"enabled": True, "channel": "sms", "days_before": 30},
            "wof_expiry": {"enabled": True, "channel": "email", "days_before": 14},
            "cof_expiry": {"enabled": True, "channel": "both", "days_before": 30},
            "registration_expiry": {"enabled": True, "channel": "sms", "days_before": 30},
        }

        consent_record = _consent_record(
            entries=[
                _entry("service_due", "sms"),
                _entry("wof_expiry", "email"),
                _entry("cof_expiry", "both"),
                _entry("registration_expiry", "sms"),
            ]
        )

        validated = await update_customer_reminder_config(
            db,
            org_id=org_id,
            customer_id=customer.id,
            reminders=reminders,
            consent_record=consent_record,
        )

        # All four keys present in the returned validated config — proves the
        # post-A0 ``VALID_REMINDER_TYPES`` set drives the loop.
        assert set(validated.keys()) == {
            "service_due",
            "wof_expiry",
            "cof_expiry",
            "registration_expiry",
        }
        for cat in validated:
            assert validated[cat]["enabled"] is True

        # And persisted onto the customer row.
        persisted = customer.custom_fields["reminder_config"]
        assert persisted == validated
        # Consent record was co-persisted.
        assert customer.custom_fields["reminder_consent"]["source"] == (
            "manually_recorded_by_staff:phone"
        )


# ---------------------------------------------------------------------------
# 2. No consent on a newly-enabled pair raises with the wire-shape payload
# ---------------------------------------------------------------------------


class TestNoConsentRaises409Payload:
    """A4 / Req 2.2, 2.12: gate fires + payload shape is wire-correct."""

    @pytest.mark.asyncio
    async def test_no_consent_raises_409_payload(self):
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)  # no existing consent
        db = _make_db(customer)

        reminders = {
            "service_due": {"enabled": False},
            "wof_expiry": {"enabled": True, "channel": "sms", "days_before": 30},
            "cof_expiry": {"enabled": False},
            "registration_expiry": {"enabled": False},
        }

        with pytest.raises(RemindersConsentRequiredError) as exc_info:
            await update_customer_reminder_config(
                db,
                org_id=org_id,
                customer_id=customer.id,
                reminders=reminders,
                consent_record=None,
            )

        assert exc_info.value.missing == [
            {"category": "wof_expiry", "channel": "sms"}
        ]
        # And the config was NOT persisted.
        assert "reminder_config" not in customer.custom_fields


# ---------------------------------------------------------------------------
# 3. With covering consent record, both blobs are persisted
# ---------------------------------------------------------------------------


class TestWithCoveringConsentRecordPersistsBoth:
    """A4 / Req 1.13, 2.7, 2.10: co-persist consent + config in one transaction."""

    @pytest.mark.asyncio
    async def test_with_covering_consent_record_persists_both(self):
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)
        db = _make_db(customer)

        reminders = {
            "service_due": {"enabled": False},
            "wof_expiry": {"enabled": True, "channel": "email", "days_before": 30},
            "cof_expiry": {"enabled": False},
            "registration_expiry": {"enabled": False},
        }

        consent_record = _consent_record(
            entries=[_entry("wof_expiry", "email")]
        )

        await update_customer_reminder_config(
            db,
            org_id=org_id,
            customer_id=customer.id,
            reminders=reminders,
            consent_record=consent_record,
        )

        # Both blobs landed on the customer row.
        assert "reminder_consent" in customer.custom_fields
        assert "reminder_config" in customer.custom_fields

        consent = customer.custom_fields["reminder_consent"]
        assert consent["consent_text_version"] == "2026-06-08-v1"
        assert any(
            e["category"] == "wof_expiry" and e["channel"] == "email"
            for e in consent["entries"]
        )

        config = customer.custom_fields["reminder_config"]
        assert config["wof_expiry"]["enabled"] is True
        assert config["wof_expiry"]["channel"] == "email"


# ---------------------------------------------------------------------------
# 4. Idempotent re-submit of the same config does not re-trigger the gate
# ---------------------------------------------------------------------------


class TestIdempotentResubmitSameConfigNoGate:
    """A4 / Req 2.10: existing covering consent makes the gate a no-op."""

    @pytest.mark.asyncio
    async def test_idempotent_resubmit_same_config_no_gate(self):
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)
        db = _make_db(customer)

        reminders = {
            "service_due": {"enabled": False},
            "wof_expiry": {"enabled": True, "channel": "sms", "days_before": 30},
            "cof_expiry": {"enabled": False},
            "registration_expiry": {"enabled": False},
        }

        consent_record = _consent_record(
            entries=[_entry("wof_expiry", "sms")]
        )

        # First call enables the pair with a fresh consent record.
        await update_customer_reminder_config(
            db,
            org_id=org_id,
            customer_id=customer.id,
            reminders=reminders,
            consent_record=consent_record,
        )

        first_consent = dict(customer.custom_fields["reminder_consent"])
        first_config = dict(customer.custom_fields["reminder_config"])

        # Second call: SAME config, NO consent_record. The gate must be a
        # no-op because the already-persisted consent covers (wof_expiry, sms).
        validated = await update_customer_reminder_config(
            db,
            org_id=org_id,
            customer_id=customer.id,
            reminders=reminders,
            consent_record=None,
        )

        assert validated["wof_expiry"]["enabled"] is True
        assert validated["wof_expiry"]["channel"] == "sms"
        # Config still present and equal.
        assert customer.custom_fields["reminder_config"] == first_config
        # And the existing consent was not overwritten by a second
        # ``record_consent_given`` (we passed ``consent_record=None``).
        assert customer.custom_fields["reminder_consent"] == first_consent


# ---------------------------------------------------------------------------
# 5. ``enabled: false`` pairs never trigger the gate
# ---------------------------------------------------------------------------


class TestAlreadyEnabledPairNotInNewConfigNoGate:
    """A4 / Req 2.11: only newly-enabled pairs are gated."""

    @pytest.mark.asyncio
    async def test_already_enabled_pair_not_in_new_config_no_gate(self):
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)  # no existing consent
        db = _make_db(customer)

        # All four categories are explicitly disabled — even though no
        # consent is on file, the gate must not fire because nothing is
        # being newly enabled.
        reminders = {
            "service_due": {"enabled": False},
            "wof_expiry": {"enabled": False},
            "cof_expiry": {"enabled": False},
            "registration_expiry": {"enabled": False},
        }

        validated = await update_customer_reminder_config(
            db,
            org_id=org_id,
            customer_id=customer.id,
            reminders=reminders,
            consent_record=None,
        )

        for cat in (
            "service_due",
            "wof_expiry",
            "cof_expiry",
            "registration_expiry",
        ):
            assert validated[cat]["enabled"] is False

        assert customer.custom_fields["reminder_config"] == validated
        assert "reminder_consent" not in customer.custom_fields


# ---------------------------------------------------------------------------
# 6. Partial-coverage consent record raises with only still-uncovered pairs
# ---------------------------------------------------------------------------


class TestConsentRecordPartialCoverage:
    """A4 / Req 2.12: partial coverage still raises 409 — with only what is missing."""

    @pytest.mark.asyncio
    async def test_consent_record_partial_coverage_raises_with_still_missing(self):
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)
        db = _make_db(customer)

        # Two newly-enabled pairs, but the supplied consent only covers one.
        reminders = {
            "service_due": {"enabled": True, "channel": "sms", "days_before": 30},
            "wof_expiry": {"enabled": True, "channel": "email", "days_before": 30},
            "cof_expiry": {"enabled": False},
            "registration_expiry": {"enabled": False},
        }

        consent_record = _consent_record(
            entries=[_entry("service_due", "sms")]  # missing wof_expiry/email
        )

        with pytest.raises(RemindersConsentRequiredError) as exc_info:
            await update_customer_reminder_config(
                db,
                org_id=org_id,
                customer_id=customer.id,
                reminders=reminders,
                consent_record=consent_record,
            )

        assert exc_info.value.missing == [
            {"category": "wof_expiry", "channel": "email"}
        ]
        # Neither blob persisted (we raised before writing either).
        assert "reminder_config" not in customer.custom_fields
        assert "reminder_consent" not in customer.custom_fields


# ---------------------------------------------------------------------------
# B1 — HTTP endpoint tests against ``update_customer_reminders_endpoint``
# ---------------------------------------------------------------------------
#
# These tests exercise the router handler directly with a mocked Request
# object. We avoid the full TestClient stack because the existing app
# requires a real DB session and AuthMiddleware setup that is heavyweight
# for the surface we want to lock down here. The handler is a plain
# ``async def`` so calling it with mocks is sufficient to verify (a) that
# the consent_record block is popped off the body before being passed
# through to the service, (b) that ``RemindersConsentRequiredError``
# rendered by the service maps to ``HTTP 409`` with the ``consent_required``
# wire body, and (c) that a body carrying both the new pair and a
# covering consent_record results in both blobs being persisted on the
# customer row.


def _make_request(
    *,
    org_uuid: uuid.UUID,
    user_uuid: uuid.UUID,
    body: dict,
    user_agent: str | None = "test-agent/1.0",
    ip_address: str | None = "10.0.0.1",
) -> MagicMock:
    """Build a Starlette-compatible Request mock for the router handler.

    The handler reads ``request.state.org_id``, ``request.state.user_id``,
    ``request.state.client_ip``, ``request.headers.get("user-agent")``,
    and ``await request.json()``.
    """
    request = MagicMock()
    request.state.org_id = str(org_uuid)
    request.state.user_id = str(user_uuid)
    request.state.client_ip = ip_address

    headers = {"user-agent": user_agent} if user_agent is not None else {}
    request.headers = headers

    request.json = AsyncMock(return_value=body)
    return request


# ---------------------------------------------------------------------------
# B1.1 — PUT with newly-enabled pair, no consent_record -> 409 + missing list
# ---------------------------------------------------------------------------


class TestPutReturns409WithMissingList:
    """B1 / Req 2.12, 2.13: HTTP 409 maps from RemindersConsentRequiredError."""

    @pytest.mark.asyncio
    async def test_put_returns_409_with_missing_list(self):
        from app.modules.customers.router import update_customer_reminders_endpoint

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)  # no existing consent
        db = _make_db(customer)

        # Body newly enables (wof_expiry, sms) — no consent_record provided.
        body = {
            "service_due": {"enabled": False},
            "wof_expiry": {"enabled": True, "channel": "sms", "days_before": 30},
            "cof_expiry": {"enabled": False},
            "registration_expiry": {"enabled": False},
        }
        request = _make_request(org_uuid=org_id, user_uuid=user_id, body=body)

        response = await update_customer_reminders_endpoint(
            customer_id=str(customer.id),
            request=request,
            db=db,
        )

        # JSONResponse renders to status 409 with the wire-shape body.
        assert response.status_code == 409
        # ``JSONResponse.body`` is bytes — decode and parse to compare.
        import json as _json

        payload = _json.loads(response.body.decode("utf-8"))
        assert payload == {
            "error": "consent_required",
            "missing": [{"category": "wof_expiry", "channel": "sms"}],
        }
        # And ``reminder_config`` was NOT persisted (gate raised before write).
        assert "reminder_config" not in customer.custom_fields


# ---------------------------------------------------------------------------
# B1.2 — PUT with newly-enabled pair AND consent_record -> 200 + both persisted
# ---------------------------------------------------------------------------


class TestPutWithConsentRecordPersistsBoth:
    """B1 / Req 2.7, 2.8: consent_record on PUT body co-persists both blobs."""

    @pytest.mark.asyncio
    async def test_put_with_consent_record_persists_both(self):
        from app.modules.customers.router import update_customer_reminders_endpoint

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)
        db = _make_db(customer)

        # Body newly enables (wof_expiry, email) AND carries a covering
        # consent_record. The router pops ``consent_record`` off the body
        # BEFORE the remainder is forwarded as ``reminders=`` to the
        # service, so the service must not see the consent_record key
        # mixed into the per-category dict.
        consent_block = {
            "given_at": datetime.now(timezone.utc).isoformat(),
            "source": "manually_recorded_by_staff:phone",
            "entries": [
                {
                    "vehicle_id": None,
                    "category": "wof_expiry",
                    "channel": "email",
                }
            ],
            "consent_text_version": "2026-06-08-v1",
            "recorded_by_user_id": str(uuid.uuid4()),
            "recorded_by_user_email": "staff@example.com",
        }
        body = {
            "service_due": {"enabled": False},
            "wof_expiry": {"enabled": True, "channel": "email", "days_before": 30},
            "cof_expiry": {"enabled": False},
            "registration_expiry": {"enabled": False},
            "consent_record": consent_block,
        }
        request = _make_request(org_uuid=org_id, user_uuid=user_id, body=body)

        result = await update_customer_reminders_endpoint(
            customer_id=str(customer.id),
            request=request,
            db=db,
        )

        # Successful 200 path returns the validated config dict directly
        # (not a JSONResponse). Confirm the (wof_expiry, email) pair landed.
        assert isinstance(result, dict)
        assert result["wof_expiry"]["enabled"] is True
        assert result["wof_expiry"]["channel"] == "email"

        # Both blobs persisted on the customer row.
        assert "reminder_consent" in customer.custom_fields
        assert "reminder_config" in customer.custom_fields

        # And the consent_record key was NOT written into reminder_config —
        # i.e. the router popped it off the body before forwarding.
        assert "consent_record" not in customer.custom_fields["reminder_config"]
        assert customer.custom_fields["reminder_consent"]["source"] == (
            "manually_recorded_by_staff:phone"
        )
        assert customer.custom_fields["reminder_consent"]["consent_text_version"] == (
            "2026-06-08-v1"
        )
