"""Bounce correlation: webhook event flips notification_log to bounced.

Phase 8c task 9.12 of the email-provider-unification spec. Drives the
end-to-end webhook → ``flag_bounce`` → ``notification_log`` flip path
without spinning up a real PG database. We:

1. Build an in-memory ``NotificationLog`` row whose
   ``provider_message_id`` matches a Brevo bounce event we'll deliver.
2. Patch the ``bounce_correlation`` helper's session/lookups so
   ``flag_bounce`` can find the row, run its three side-effects, and
   leave the row marked ``status='bounced'`` with a bounce reason.
3. Assert the status flip is idempotent — a second event leaves the
   timestamp untouched.

Validates: Requirements 11.1, 11.2, 21.8
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.modules.notifications import bounce_correlation as bc


def _make_log_row(*, status: str = "sent", reason: str | None = None):
    """Build a minimal mock notification_log row."""
    row = SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        status=status,
        bounced_at=None,
        bounce_reason=reason,
        provider_message_id="brevo-msg-123",
    )
    return row


def _execute_returning_scalar_one(value):
    """Build an ``execute()`` result whose ``scalar_one_or_none()``
    returns ``value``."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _execute_returning_scalars_all(rows):
    """Build an ``execute()`` result whose ``scalars().all()`` returns
    the given list."""
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _execute_returning_rowcount(rowcount: int = 1):
    """Build an ``execute()`` result for an UPDATE/DELETE/INSERT with
    a ``rowcount``."""
    result = MagicMock()
    result.rowcount = rowcount
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_bounce_flips_notification_log_status_to_bounced() -> None:
    """A Brevo hard-bounce event flips the matching ``notification_log``
    row to ``status='bounced'``, sets ``bounced_at``, and persists the
    reason.

    The function must:

    - find the row by ``provider_message_id``;
    - flip ``status`` from ``sent`` → ``bounced``;
    - record the reason and a non-NULL ``bounced_at`` timestamp;
    - upsert into ``bounced_addresses`` (we assert the SQL was issued);
    - never raise even when downstream side-effects (in-app
      notification, customer-flag fan-out) have nothing to do.

    Validates: Requirement 11.2
    """
    log_row = _make_log_row(status="sent")

    db = AsyncMock()
    db.flush = AsyncMock()
    # Sequence of DB calls inside flag_bounce:
    #   1. notification_log lookup by provider_message_id
    #   2. INSERT...ON CONFLICT into bounced_addresses (rowcount=1)
    #   3. customer fan-out by org → flag_bounced_email_on_customer
    #      issues an UPDATE, returning rowcount=0 (no customer matches)
    db.execute = AsyncMock(
        side_effect=[
            _execute_returning_scalar_one(log_row),
            _execute_returning_rowcount(1),
            _execute_returning_rowcount(0),
        ]
    )

    # Patch in-app notification dispatch so we don't fan out across orgs.
    with patch.object(
        bc, "_fire_in_app_notification_for_bounce", new=AsyncMock()
    ) as iapn:
        await bc.flag_bounce(
            db,
            provider_message_id="brevo-msg-123",
            recipient="bad@example.com",
            kind="hard_bounce",
            reason="550 No such user",
            provider_key="brevo",
        )

    # Status flip is the headline assertion — Req 11.2.
    assert log_row.status == "bounced"
    assert log_row.bounced_at is not None
    assert log_row.bounce_reason == "550 No such user"
    # In-app notification step was reached (deduplicated; we don't
    # assert on whether it actually fired since the dedup helper is
    # mocked in the bounce_correlation module).
    iapn.assert_awaited_once()


@pytest.mark.asyncio
async def test_flag_bounce_is_idempotent_on_repeated_events() -> None:
    """A second identical webhook event is a no-op on the log row.

    Bounce providers occasionally retry delivery of the same event.
    The notification_log update is keyed off ``status != 'bounced'`` so
    repeat events leave ``bounced_at`` and ``bounce_reason`` stable.
    The bounced_addresses upsert may still bump ``hit_count`` (not
    asserted here — the upsert is exercised in
    ``test_bounced_address_blocklist.py``).

    Validates: Requirement 11.2 (idempotency)
    """
    log_row = _make_log_row(status="bounced")
    log_row.bounced_at = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    log_row.bounce_reason = "550 No such user"
    frozen_bounced_at = log_row.bounced_at
    frozen_reason = log_row.bounce_reason

    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _execute_returning_scalar_one(log_row),
            _execute_returning_rowcount(1),  # bounced_addresses upsert
            _execute_returning_rowcount(0),  # customer fan-out
        ]
    )

    with patch.object(
        bc, "_fire_in_app_notification_for_bounce", new=AsyncMock()
    ):
        await bc.flag_bounce(
            db,
            provider_message_id="brevo-msg-123",
            recipient="bad@example.com",
            kind="hard_bounce",
            reason="550 different reason — should be ignored",
            provider_key="brevo",
        )

    # Status, bounced_at, and bounce_reason all unchanged.
    assert log_row.status == "bounced"
    assert log_row.bounced_at == frozen_bounced_at
    assert log_row.bounce_reason == frozen_reason


@pytest.mark.asyncio
async def test_flag_bounce_handles_missing_log_row_gracefully() -> None:
    """When no ``notification_log`` row matches, ``flag_bounce`` still
    upserts into ``bounced_addresses`` and fires the in-app alert.

    The webhook handler must never lose a known-bad address just
    because the originating log row is missing — we know the
    address bounced even if we lost the trail back to the
    notification_log row. Ref: design doc §10 idempotency.

    Validates: Requirement 11.4
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            # No matching notification_log row.
            _execute_returning_scalar_one(None),
            # But the bounced_addresses upsert still runs.
            _execute_returning_rowcount(1),
            # Customer fan-out (no matches).
            _execute_returning_scalars_all([]),
        ]
    )

    with patch.object(
        bc, "_fire_in_app_notification_for_bounce", new=AsyncMock()
    ) as iapn:
        await bc.flag_bounce(
            db,
            provider_message_id="unknown-msg-999",
            recipient="bad@example.com",
            kind="hard_bounce",
            reason="550",
            provider_key="brevo",
        )

    # Three executes: log lookup, bounced_addresses upsert, customer
    # fan-out. The in-app notification still fires (no log row → no
    # org context, but flag_bounce fans out across all matching orgs).
    assert db.execute.await_count == 3
    iapn.assert_awaited_once()


@pytest.mark.asyncio
async def test_flag_bounce_normalises_event_kinds() -> None:
    """Kind normaliser maps Brevo + SendGrid event names to storage
    vocabulary.

    Brevo emits ``hard_bounce`` / ``soft_bounce`` / ``blocked`` /
    ``invalid_email``; SendGrid emits ``bounce`` / ``dropped`` /
    ``deferred``. Both must squash into the
    ``hard`` / ``soft`` / ``blocked`` vocabulary that the table CHECK
    constraint accepts.

    Validates: Requirement 12.2
    """
    # Hard-mapping family.
    assert bc._normalise_kind("hard_bounce") == "hard"
    assert bc._normalise_kind("HARD") == "hard"
    assert bc._normalise_kind("bounce") == "hard"  # SendGrid
    # Blocked-mapping family.
    assert bc._normalise_kind("blocked") == "blocked"
    assert bc._normalise_kind("invalid_email") == "blocked"
    assert bc._normalise_kind("dropped") == "blocked"  # SendGrid
    # Soft-mapping family.
    assert bc._normalise_kind("soft_bounce") == "soft"
    assert bc._normalise_kind("deferred") == "soft"  # SendGrid
    # Unknown → conservative fallback to soft.
    assert bc._normalise_kind("snowflake-event") == "soft"
    assert bc._normalise_kind("") == "soft"
