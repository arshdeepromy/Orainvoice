"""Unit tests for Task 1.2 — auto-clock-out policy defaults + validation.

Covers the three auto-clock-out keys added to the clock-in-policy read/write
path (Task 1.1):
  - ``auto_clock_out_enabled``       (bool, default False)
  - ``auto_clock_out_after_hours``   (int, default 14, range 1..48)
  - ``auto_clock_out_grace_minutes`` (int, default 15, range 0..240)

Tests verify:
  - Absent keys resolve to the documented defaults (grace 15, after-hours 14,
    enabled False) via ``get_clock_in_policy`` merge-with-defaults.
  - Out-of-range values are rejected by ``ClockInPolicyBlock`` validation.
  - A partial PUT (only the three auto-clock-out keys) leaves the other
    clock-in-policy keys intact (field-by-field merge in
    ``update_clock_in_policy``).

Requirements: 1.1, 1.2, 1.3, 1.5
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

import app.modules.admin.models  # noqa: F401 — resolve relationships

from app.modules.organisations.schemas import ClockInPolicyBlock
from app.modules.organisations.service import (
    _CLOCK_IN_POLICY_DEFAULTS,
    get_clock_in_policy,
    update_clock_in_policy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db_session():
    """Create a mock AsyncSession with an awaitable flush()."""
    db = AsyncMock()
    db.flush = AsyncMock()
    return db


def _mock_policy_row(clock_in_policy=None, overtime_policy=None,
                     overtime_handling="pay_cash"):
    """Mock the row returned by the ``get_clock_in_policy`` SELECT.

    The service reads ``row[0]`` (clock_in_policy JSONB), ``row[1]``
    (overtime_policy JSONB) and ``row[2]`` (overtime_handling) from
    ``result.first()`` — so the row must be index-accessible.
    """
    row = (clock_in_policy, overtime_policy, overtime_handling)
    result = MagicMock()
    result.first.return_value = row
    return result


# ---------------------------------------------------------------------------
# Defaults — absent keys resolve to documented defaults (Req 1.1, 1.2, 1.3)
# ---------------------------------------------------------------------------

class TestAutoClockOutDefaults:
    """The three auto-clock-out keys default correctly when absent."""

    def test_defaults_constant_has_documented_values(self):
        """The service defaults constant carries the documented defaults."""
        assert _CLOCK_IN_POLICY_DEFAULTS["auto_clock_out_enabled"] is False
        assert _CLOCK_IN_POLICY_DEFAULTS["auto_clock_out_after_hours"] == 14
        assert _CLOCK_IN_POLICY_DEFAULTS["auto_clock_out_grace_minutes"] == 15

    @pytest.mark.asyncio
    async def test_absent_keys_resolve_to_defaults(self):
        """Empty JSONB → defaults: enabled False, after-hours 14, grace 15."""
        db = _mock_db_session()
        # Raw clock_in_policy JSONB is empty ({}), so every key comes from defaults.
        db.execute = AsyncMock(return_value=_mock_policy_row(clock_in_policy={}))

        result = await get_clock_in_policy(db, org_id=uuid.uuid4())
        policy = result["clock_in_policy"]

        assert policy["auto_clock_out_enabled"] is False
        assert policy["auto_clock_out_after_hours"] == 14
        assert policy["auto_clock_out_grace_minutes"] == 15

    @pytest.mark.asyncio
    async def test_null_jsonb_resolves_to_defaults(self):
        """A NULL clock_in_policy column (None) still resolves to defaults."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_policy_row(clock_in_policy=None))

        result = await get_clock_in_policy(db, org_id=uuid.uuid4())
        policy = result["clock_in_policy"]

        assert policy["auto_clock_out_enabled"] is False
        assert policy["auto_clock_out_after_hours"] == 14
        assert policy["auto_clock_out_grace_minutes"] == 15

    @pytest.mark.asyncio
    async def test_stored_values_override_defaults(self):
        """Stored auto-clock-out values are surfaced over the defaults."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_policy_row(clock_in_policy={
            "auto_clock_out_enabled": True,
            "auto_clock_out_after_hours": 10,
            "auto_clock_out_grace_minutes": 30,
        }))

        result = await get_clock_in_policy(db, org_id=uuid.uuid4())
        policy = result["clock_in_policy"]

        assert policy["auto_clock_out_enabled"] is True
        assert policy["auto_clock_out_after_hours"] == 10
        assert policy["auto_clock_out_grace_minutes"] == 30

    @pytest.mark.asyncio
    async def test_partial_jsonb_fills_missing_auto_keys(self):
        """A JSONB carrying only one auto key defaults the other two."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_policy_row(clock_in_policy={
            "auto_clock_out_enabled": True,
        }))

        result = await get_clock_in_policy(db, org_id=uuid.uuid4())
        policy = result["clock_in_policy"]

        assert policy["auto_clock_out_enabled"] is True
        # The two omitted keys fall back to their documented defaults.
        assert policy["auto_clock_out_after_hours"] == 14
        assert policy["auto_clock_out_grace_minutes"] == 15

    def test_block_defaults_match_service_defaults(self):
        """ClockInPolicyBlock() defaults agree with the service defaults."""
        block = ClockInPolicyBlock()
        assert block.auto_clock_out_enabled is False
        assert block.auto_clock_out_after_hours == 14
        assert block.auto_clock_out_grace_minutes == 15


# ---------------------------------------------------------------------------
# Validation — out-of-range values rejected (Req 1.2, 1.3)
# ---------------------------------------------------------------------------

class TestAutoClockOutValidation:
    """ClockInPolicyBlock enforces the documented sane ranges."""

    def test_after_hours_lower_bound_accepted(self):
        assert ClockInPolicyBlock(auto_clock_out_after_hours=1).auto_clock_out_after_hours == 1

    def test_after_hours_upper_bound_accepted(self):
        assert ClockInPolicyBlock(auto_clock_out_after_hours=48).auto_clock_out_after_hours == 48

    def test_after_hours_below_range_rejected(self):
        with pytest.raises(ValidationError):
            ClockInPolicyBlock(auto_clock_out_after_hours=0)

    def test_after_hours_above_range_rejected(self):
        with pytest.raises(ValidationError):
            ClockInPolicyBlock(auto_clock_out_after_hours=49)

    def test_grace_minutes_lower_bound_accepted(self):
        assert ClockInPolicyBlock(auto_clock_out_grace_minutes=0).auto_clock_out_grace_minutes == 0

    def test_grace_minutes_upper_bound_accepted(self):
        assert ClockInPolicyBlock(auto_clock_out_grace_minutes=240).auto_clock_out_grace_minutes == 240

    def test_grace_minutes_below_range_rejected(self):
        with pytest.raises(ValidationError):
            ClockInPolicyBlock(auto_clock_out_grace_minutes=-1)

    def test_grace_minutes_above_range_rejected(self):
        with pytest.raises(ValidationError):
            ClockInPolicyBlock(auto_clock_out_grace_minutes=241)

    def test_enabled_accepts_bool(self):
        assert ClockInPolicyBlock(auto_clock_out_enabled=True).auto_clock_out_enabled is True


# ---------------------------------------------------------------------------
# Partial PUT — merge field-by-field, leave other keys intact (Req 1.5)
# ---------------------------------------------------------------------------

class TestPartialUpdatePreservesOtherKeys:
    """update_clock_in_policy merges field-by-field without a migration."""

    @pytest.mark.asyncio
    async def test_partial_put_preserves_other_policy_keys(self):
        """PUT of only the three auto keys leaves the rest of the policy intact."""
        db = _mock_db_session()
        # Existing JSONB carries non-default values for unrelated keys.
        existing = {
            "default_channel": "self_service",
            "self_service_require_photo": False,
            "branch_radius_metres": 500,
            "missed_clock_out_alert_enabled": False,
            "missed_clock_out_alert_channels": ["email"],
        }
        db.execute = AsyncMock(return_value=_mock_policy_row(clock_in_policy=existing))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_clock_in_policy(
                db, org_id=uuid.uuid4(), user_id=uuid.uuid4(),
                clock_in_policy={
                    "auto_clock_out_enabled": True,
                    "auto_clock_out_after_hours": 12,
                    "auto_clock_out_grace_minutes": 30,
                },
            )

        policy = result["clock_in_policy"]
        # The three auto keys are applied.
        assert policy["auto_clock_out_enabled"] is True
        assert policy["auto_clock_out_after_hours"] == 12
        assert policy["auto_clock_out_grace_minutes"] == 30
        # The unrelated keys are untouched.
        assert policy["default_channel"] == "self_service"
        assert policy["self_service_require_photo"] is False
        assert policy["branch_radius_metres"] == 500
        assert policy["missed_clock_out_alert_enabled"] is False
        assert policy["missed_clock_out_alert_channels"] == ["email"]

    @pytest.mark.asyncio
    async def test_partial_put_persists_via_jsonb_write(self):
        """The merged policy (old + new keys) is written back to the JSONB column."""
        import json

        db = _mock_db_session()
        existing = {"branch_radius_metres": 500, "missed_clock_out_alert_enabled": False}
        db.execute = AsyncMock(return_value=_mock_policy_row(clock_in_policy=existing))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await update_clock_in_policy(
                db, org_id=uuid.uuid4(), user_id=uuid.uuid4(),
                clock_in_policy={"auto_clock_out_enabled": True},
            )

        # Two execute calls: the SELECT (get) then the UPDATE (write).
        assert db.execute.await_count == 2
        update_kwargs = db.execute.await_args_list[1].args[1]
        written = json.loads(update_kwargs["clock_in_policy"])
        # New key applied, existing key preserved.
        assert written["auto_clock_out_enabled"] is True
        assert written["branch_radius_metres"] == 500
        assert written["missed_clock_out_alert_enabled"] is False
        await db.flush()  # flush was awaited inside the service

    @pytest.mark.asyncio
    async def test_partial_put_writes_audit_log(self):
        """A successful clock-in-policy update writes the audit-log entry."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_policy_row(clock_in_policy={}))
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await update_clock_in_policy(
                db, org_id=org_id, user_id=user_id,
                clock_in_policy={"auto_clock_out_enabled": True},
                ip_address="10.0.0.1",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "org.clock_in_policy_updated"
        assert call_kwargs["entity_type"] == "organisation"
        assert call_kwargs["org_id"] == org_id
        assert call_kwargs["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_no_fields_returns_state_without_audit(self):
        """An update with no policy blocks returns current state and skips audit."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_policy_row(clock_in_policy={}))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            result = await update_clock_in_policy(
                db, org_id=uuid.uuid4(), user_id=uuid.uuid4(),
            )

        mock_audit.assert_not_awaited()
        # Defaults still surface for the auto keys.
        assert result["clock_in_policy"]["auto_clock_out_after_hours"] == 14
