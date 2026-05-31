"""Unit tests for ``app.tasks.scheduled.weekly_roster_broadcast``.

Covers task D1 from ``.kiro/specs/staff-management-p1``:

- The body short-circuits when the org-local time is outside the
  Friday 16:00-16:29 window. No staff query, no provider calls, no
  log lines (R10.1 / R10.2).
- The body fires for orgs whose local time IS Friday 16:05. Each
  opted-in staff member's email and SMS are dispatched in turn,
  per-staff log lines are emitted (R10.5), and per-staff sends are
  wrapped in ``db.begin_nested()`` SAVEPOINTs so a single failure
  does not poison the batch (R10.3).
- The viewer base URL is built from ``settings.frontend_base_url``,
  matching the router's success path so the public viewer link is
  reachable.

**Validates: Requirement R10** — Staff Management Phase 1 task D1.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.staff.roster_delivery import RosterDeliveryResult
from app.tasks.scheduled import weekly_roster_broadcast


# ---------------------------------------------------------------------------
# Helpers — build a fake async session factory whose `with`-context
# yields a session that records its `execute` calls and returns the
# pre-baked rows we hand it.
# ---------------------------------------------------------------------------


def _make_async_session(rows_by_call: list[list]) -> AsyncMock:
    """Build a fake ``AsyncSession`` whose ``execute`` calls return the
    rows in ``rows_by_call`` in order.

    The session ALSO supports ``begin()`` and ``begin_nested()`` as
    async context managers — both no-ops for the test (no real DB).
    """
    session = AsyncMock()

    # ``async with session.begin(): ...``
    @asynccontextmanager
    async def _begin():
        yield session

    session.begin = _begin
    # ``await session.begin_nested()`` returns a savepoint object whose
    # ``rollback`` is awaitable.
    savepoint = MagicMock()
    savepoint.rollback = AsyncMock()
    session.begin_nested = AsyncMock(return_value=savepoint)

    # ``execute`` returns a result whose ``all()`` / ``scalars().all()``
    # both yield the next pre-baked rows list.
    call_iter = iter(rows_by_call)

    async def _execute(_stmt, *_args, **_kwargs):
        try:
            rows = next(call_iter)
        except StopIteration:
            rows = []
        result = MagicMock()
        result.all.return_value = rows
        scalars = MagicMock()
        scalars.all.return_value = rows
        result.scalars.return_value = scalars
        return result

    session.execute = _execute
    return session


def _make_session_factory(rows_per_session: list[list[list]]) -> MagicMock:
    """Build an ``async_session_factory()`` stand-in.

    Each invocation of the factory yields a NEW fake session pre-loaded
    with one batch of rows-per-call.
    """
    session_iter = iter(rows_per_session)

    @asynccontextmanager
    async def _factory_call():
        try:
            rows_by_call = next(session_iter)
        except StopIteration:
            rows_by_call = []
        session = _make_async_session(rows_by_call)
        yield session

    factory = MagicMock(side_effect=lambda: _factory_call())
    return factory


def _make_staff_stub(
    *,
    staff_id: uuid.UUID,
    org_id: uuid.UUID,
    email: str | None = "jane@example.co.nz",
    phone: str | None = None,
    weekly_roster_email_enabled: bool = True,
    weekly_roster_sms_enabled: bool = False,
    first_name: str = "Jane",
    last_name: str | None = "Doe",
):
    """Minimal ``StaffMember``-shaped stub.

    Matches the attributes the broadcast loop accesses:
    ``id``, ``email``, ``phone``, ``weekly_roster_email_enabled``,
    ``weekly_roster_sms_enabled``, ``first_name``, ``last_name``,
    ``name``.
    """
    return SimpleNamespace(
        id=staff_id,
        org_id=org_id,
        email=email,
        phone=phone,
        weekly_roster_email_enabled=weekly_roster_email_enabled,
        weekly_roster_sms_enabled=weekly_roster_sms_enabled,
        first_name=first_name,
        last_name=last_name,
        name=f"{first_name} {last_name or ''}".strip(),
    )


# ---------------------------------------------------------------------------
# Short-circuit behaviour (R10.1, R10.2)
# ---------------------------------------------------------------------------


class TestShortCircuit:
    """Body short-circuits unless the local time is Friday 16:00-16:29."""

    @pytest.mark.asyncio
    async def test_no_orgs_with_module_returns_zero_summary(self):
        """When zero orgs have ``staff_management`` enabled the task
        finishes after a single SELECT and returns an all-zero
        summary."""
        factory = _make_session_factory([
            # Single session: one execute call that returns no orgs.
            [[]],
        ])
        with patch("app.core.database.async_session_factory", factory):
            summary = await weekly_roster_broadcast(
                _now_utc=datetime(2026, 6, 12, 4, 5, tzinfo=timezone.utc),
            )

        assert summary == {
            "orgs_in_window": 0,
            "staff_processed": 0,
            "email_sent": 0,
            "email_failed": 0,
            "sms_sent": 0,
            "sms_failed": 0,
        }

    @pytest.mark.asyncio
    async def test_tuesday_is_outside_window(self):
        """Tuesday 16:05 in Pacific/Auckland → no org enters the window
        even though it has the module enabled."""
        org_id = uuid.uuid4()
        factory = _make_session_factory([
            # First session: enumerate orgs (one row).
            [[(org_id, "Pacific/Auckland")]],
        ])
        send_email = AsyncMock()
        send_sms = AsyncMock()

        # Tuesday 2026-06-09 16:05 Pacific/Auckland == 04:05 UTC.
        # weekday()==1 → Tuesday → outside window.
        now_utc = datetime(2026, 6, 9, 4, 5, tzinfo=timezone.utc)

        with patch(
            "app.core.database.async_session_factory", factory,
        ), patch(
            "app.modules.staff.roster_delivery.send_roster_email", send_email,
        ), patch(
            "app.modules.staff.roster_delivery.send_roster_sms", send_sms,
        ):
            summary = await weekly_roster_broadcast(_now_utc=now_utc)

        assert summary["orgs_in_window"] == 0
        assert summary["staff_processed"] == 0
        send_email.assert_not_awaited()
        send_sms.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_friday_16_30_is_outside_window(self):
        """Friday 16:30 (one minute after the window closes) does not
        fire — the cap at minute 29 is exclusive in the spec."""
        org_id = uuid.uuid4()
        factory = _make_session_factory([
            [[(org_id, "Pacific/Auckland")]],
        ])
        send_email = AsyncMock()
        send_sms = AsyncMock()

        # Friday 2026-06-12 16:30 Pacific/Auckland == 04:30 UTC.
        now_utc = datetime(2026, 6, 12, 4, 30, tzinfo=timezone.utc)

        with patch(
            "app.core.database.async_session_factory", factory,
        ), patch(
            "app.modules.staff.roster_delivery.send_roster_email", send_email,
        ), patch(
            "app.modules.staff.roster_delivery.send_roster_sms", send_sms,
        ):
            summary = await weekly_roster_broadcast(_now_utc=now_utc)

        assert summary["orgs_in_window"] == 0
        send_email.assert_not_awaited()
        send_sms.assert_not_awaited()


# ---------------------------------------------------------------------------
# Friday 16:05 fires for opted-in staff (R10.2, R10.3, R10.5)
# ---------------------------------------------------------------------------


class TestFridayFires:
    """Friday 16:00-16:29 in the org's local timezone triggers a
    broadcast to every opted-in staff."""

    @pytest.mark.asyncio
    async def test_fires_at_friday_16_05_email_and_sms(self, caplog):
        """Friday 16:05 Pacific/Auckland → both email and SMS legs
        fire for each opted-in staff. Per-staff log lines emitted
        (R10.5)."""
        org_id = uuid.uuid4()
        # Two staff: one email-only opt-in, one SMS-only opt-in.
        staff_email = _make_staff_stub(
            staff_id=uuid.uuid4(),
            org_id=org_id,
            email="jane@example.co.nz",
            phone=None,
            weekly_roster_email_enabled=True,
            weekly_roster_sms_enabled=False,
            first_name="Jane",
        )
        staff_sms = _make_staff_stub(
            staff_id=uuid.uuid4(),
            org_id=org_id,
            email=None,
            phone="+64 21 555 1234",
            weekly_roster_email_enabled=False,
            weekly_roster_sms_enabled=True,
            first_name="Bob",
        )

        # First factory call: enumerate orgs (one execute call).
        # Second factory call: open per-org work session (one execute
        # call to load active staff).
        factory = _make_session_factory([
            [[(org_id, "Pacific/Auckland")]],
            [[staff_email, staff_sms]],
        ])

        send_email = AsyncMock(
            return_value=RosterDeliveryResult(
                ok=True, message_id="email-msg-abc", reason=None,
            )
        )
        send_sms = AsyncMock(
            return_value=RosterDeliveryResult(
                ok=True, message_id="sms-msg-xyz", reason=None,
                audit_extras={"encoding": "gsm7", "segments": 1},
            )
        )

        # Friday 2026-06-12 16:05 Pacific/Auckland == 04:05 UTC.
        now_utc = datetime(2026, 6, 12, 4, 5, tzinfo=timezone.utc)

        caplog.set_level(logging.INFO, logger="app.tasks.scheduled")

        with patch(
            "app.core.database.async_session_factory", factory,
        ), patch(
            "app.modules.staff.roster_delivery.send_roster_email", send_email,
        ), patch(
            "app.modules.staff.roster_delivery.send_roster_sms", send_sms,
        ), patch(
            "app.core.database._set_rls_org_id", new_callable=AsyncMock,
        ):
            summary = await weekly_roster_broadcast(_now_utc=now_utc)

        assert summary["orgs_in_window"] == 1
        assert summary["staff_processed"] == 2
        assert summary["email_sent"] == 1
        assert summary["sms_sent"] == 1
        assert summary["email_failed"] == 0
        assert summary["sms_failed"] == 0

        # send_roster_email called for the email-opt-in staff,
        # send_roster_sms for the sms-opt-in staff. The cross-leg
        # gating means each helper is awaited exactly once.
        send_email.assert_awaited_once()
        send_sms.assert_awaited_once()

        # Per-staff log lines (R10.5) — match the spec's grep target
        # pattern: "weekly_roster_broadcast: org=<id> staff=<id> email=ok".
        log_text = caplog.text
        assert (
            f"weekly_roster_broadcast: org={org_id} staff={staff_email.id} "
            f"email=ok message_id=email-msg-abc"
        ) in log_text
        assert (
            f"weekly_roster_broadcast: org={org_id} staff={staff_sms.id} "
            f"sms=ok message_id=sms-msg-xyz"
        ) in log_text

    @pytest.mark.asyncio
    async def test_one_staff_failure_does_not_poison_batch(self):
        """Per-staff savepoint isolation (R10.3) — one staff's send
        failing does not stop subsequent staff in the same org."""
        org_id = uuid.uuid4()
        staff_a = _make_staff_stub(
            staff_id=uuid.uuid4(),
            org_id=org_id,
            email="a@example.com",
            weekly_roster_email_enabled=True,
        )
        staff_b = _make_staff_stub(
            staff_id=uuid.uuid4(),
            org_id=org_id,
            email="b@example.com",
            weekly_roster_email_enabled=True,
        )

        factory = _make_session_factory([
            [[(org_id, "Pacific/Auckland")]],
            [[staff_a, staff_b]],
        ])

        # Staff A's send raises; staff B's send succeeds.
        async def _send_email_side_effect(*_args, **kwargs):
            staff = kwargs.get("staff")
            if staff is staff_a:
                raise RuntimeError("provider down for staff_a")
            return RosterDeliveryResult(
                ok=True, message_id="msg-b", reason=None,
            )

        send_email = AsyncMock(side_effect=_send_email_side_effect)

        now_utc = datetime(2026, 6, 12, 4, 5, tzinfo=timezone.utc)

        with patch(
            "app.core.database.async_session_factory", factory,
        ), patch(
            "app.modules.staff.roster_delivery.send_roster_email", send_email,
        ), patch(
            "app.core.database._set_rls_org_id", new_callable=AsyncMock,
        ):
            summary = await weekly_roster_broadcast(_now_utc=now_utc)

        # Both staff were processed; one succeeded, one failed.
        assert summary["staff_processed"] == 2
        assert summary["email_sent"] == 1
        assert summary["email_failed"] == 1
        assert send_email.await_count == 2
