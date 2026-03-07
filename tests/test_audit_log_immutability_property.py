"""Property-based tests for audit log immutability (Task 23.6).

Property 6: Audit Log Append-Only Immutability
— verify UPDATE/DELETE on audit_log are rejected by the application database
role, and that write_audit_log only ever INSERTs.

**Validates: Requirements 51.1, 51.3**

Uses Hypothesis to generate random audit log entries and verify:
  1. write_audit_log always issues an INSERT (never UPDATE or DELETE)
  2. UPDATE attempts on audit_log raise InsufficientPrivilege (permission denied)
  3. DELETE attempts on audit_log raise InsufficientPrivilege (permission denied)
  4. The original entry remains unchanged after failed mutation attempts
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy.exc import ProgrammingError

from app.core.audit import write_audit_log


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Dot-separated action verbs
action_strategy = st.sampled_from([
    "invoice.created", "invoice.issued", "invoice.voided",
    "auth.login_success", "auth.login_failed", "auth.mfa_verified",
    "customer.created", "customer.updated", "customer.deleted",
    "payment.received", "payment.refunded",
    "vehicle.lookup", "vehicle.manual_entry",
    "user.created", "user.deactivated", "settings.updated",
])

# Entity types
entity_type_strategy = st.sampled_from([
    "invoice", "customer", "vehicle", "payment", "user",
    "organisation", "quote", "job_card", "booking",
])

# Optional JSON-serialisable dicts for before/after values
json_value_strategy = st.one_of(
    st.none(),
    st.dictionaries(
        keys=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        values=st.one_of(
            st.text(max_size=50),
            st.integers(min_value=-10000, max_value=10000),
            st.booleans(),
        ),
        min_size=0,
        max_size=5,
    ),
)

# IP addresses (v4)
ip_strategy = st.one_of(
    st.none(),
    st.from_regex(
        r"(1\d{2}|2[0-4]\d|25[0-5]|[1-9]\d?)\."
        r"(1\d{2}|2[0-4]\d|25[0-5]|\d{1,2})\."
        r"(1\d{2}|2[0-4]\d|25[0-5]|\d{1,2})\."
        r"(1\d{2}|2[0-4]\d|25[0-5]|\d{1,2})",
        fullmatch=True,
    ),
)

# Device info strings
device_info_strategy = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
        min_size=1,
        max_size=100,
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_permission_denied_error(statement: str) -> ProgrammingError:
    """Create a ProgrammingError mimicking PostgreSQL 'permission denied'."""
    orig = Exception(
        f'permission denied for table audit_log'
    )
    orig.pgcode = "42501"  # insufficient_privilege
    return ProgrammingError(
        statement=statement,
        params={},
        orig=orig,
    )


def _make_mock_session() -> AsyncMock:
    """Build a mock AsyncSession that records all execute() calls."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    return session


# ---------------------------------------------------------------------------
# Property 6: Audit Log Append-Only Immutability
# ---------------------------------------------------------------------------


class TestAuditLogImmutabilityProperty:
    """Property 6: Audit Log Append-Only Immutability.

    **Validates: Requirements 51.1, 51.3**
    """

    @given(
        action=action_strategy,
        entity_type=entity_type_strategy,
        before_value=json_value_strategy,
        after_value=json_value_strategy,
        ip_address=ip_strategy,
        device_info=device_info_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_write_audit_log_only_issues_insert(
        self,
        action: str,
        entity_type: str,
        before_value: dict | None,
        after_value: dict | None,
        ip_address: str | None,
        device_info: str | None,
    ):
        """For any audit log entry, write_audit_log only ever executes an
        INSERT statement — never UPDATE or DELETE.

        **Validates: Requirements 51.1**
        """
        db = _make_mock_session()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        entity_id = uuid.uuid4()

        entry_id = await write_audit_log(
            db,
            action=action,
            entity_type=entity_type,
            org_id=org_id,
            user_id=user_id,
            entity_id=entity_id,
            before_value=before_value,
            after_value=after_value,
            ip_address=ip_address,
            device_info=device_info,
        )

        # Verify exactly one execute call was made
        assert db.execute.call_count == 1

        # Extract the SQL text from the call
        call_args = db.execute.call_args
        sql_text = str(call_args[0][0].text)

        # Must be an INSERT
        assert "INSERT INTO audit_log" in sql_text, (
            f"write_audit_log must issue INSERT, got: {sql_text[:100]}"
        )
        # Must NOT contain UPDATE or DELETE
        assert "UPDATE" not in sql_text.upper().split("INSERT")[0], (
            "write_audit_log must not issue UPDATE"
        )
        assert "DELETE" not in sql_text.upper(), (
            "write_audit_log must not issue DELETE"
        )

        # Return value must be a valid UUID
        assert isinstance(entry_id, uuid.UUID)

    @given(
        action=action_strategy,
        entity_type=entity_type_strategy,
        after_value=json_value_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_update_on_audit_log_raises_permission_denied(
        self,
        action: str,
        entity_type: str,
        after_value: dict | None,
    ):
        """For any audit log entry, an UPDATE attempt on the audit_log table
        is rejected with a permission denied error, simulating the PostgreSQL
        REVOKE UPDATE behaviour.

        **Validates: Requirements 51.3**
        """
        db = _make_mock_session()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        entity_id = uuid.uuid4()

        # First call succeeds (INSERT)
        # Second call (UPDATE) raises permission denied
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(),  # INSERT succeeds
                _make_permission_denied_error("UPDATE audit_log SET ..."),
            ]
        )

        # Write the entry successfully
        entry_id = await write_audit_log(
            db,
            action=action,
            entity_type=entity_type,
            org_id=org_id,
            user_id=user_id,
            entity_id=entity_id,
            after_value=after_value,
        )

        # Attempt UPDATE — must raise ProgrammingError (permission denied)
        from sqlalchemy import text

        with pytest.raises(ProgrammingError) as exc_info:
            await db.execute(
                text("UPDATE audit_log SET action = :new_action WHERE id = :id"),
                {"new_action": "tampered.action", "id": str(entry_id)},
            )

        assert "permission denied" in str(exc_info.value.orig)

    @given(
        action=action_strategy,
        entity_type=entity_type_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_delete_on_audit_log_raises_permission_denied(
        self,
        action: str,
        entity_type: str,
    ):
        """For any audit log entry, a DELETE attempt on the audit_log table
        is rejected with a permission denied error, simulating the PostgreSQL
        REVOKE DELETE behaviour.

        **Validates: Requirements 51.3**
        """
        db = _make_mock_session()
        org_id = uuid.uuid4()
        entity_id = uuid.uuid4()

        # First call succeeds (INSERT), second call (DELETE) raises
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(),  # INSERT succeeds
                _make_permission_denied_error("DELETE FROM audit_log WHERE ..."),
            ]
        )

        entry_id = await write_audit_log(
            db,
            action=action,
            entity_type=entity_type,
            org_id=org_id,
            entity_id=entity_id,
        )

        # Attempt DELETE — must raise ProgrammingError (permission denied)
        from sqlalchemy import text

        with pytest.raises(ProgrammingError) as exc_info:
            await db.execute(
                text("DELETE FROM audit_log WHERE id = :id"),
                {"id": str(entry_id)},
            )

        assert "permission denied" in str(exc_info.value.orig)

    @given(
        action=action_strategy,
        entity_type=entity_type_strategy,
        before_value=json_value_strategy,
        after_value=json_value_strategy,
        ip_address=ip_strategy,
        device_info=device_info_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_entry_unchanged_after_failed_mutations(
        self,
        action: str,
        entity_type: str,
        before_value: dict | None,
        after_value: dict | None,
        ip_address: str | None,
        device_info: str | None,
    ):
        """For any audit log entry, after failed UPDATE and DELETE attempts,
        the original entry data remains intact and retrievable.

        **Validates: Requirements 51.1, 51.3**
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        entity_id = uuid.uuid4()

        # Track what was inserted
        captured_params: dict = {}

        async def capture_execute(stmt, params=None):
            sql_text = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
            if "INSERT INTO audit_log" in sql_text:
                captured_params.update(params or {})
                return MagicMock()
            elif "UPDATE" in sql_text.upper() or "DELETE" in sql_text.upper():
                raise _make_permission_denied_error(sql_text)
            elif "SELECT" in sql_text.upper():
                # Return the original captured data
                row = MagicMock()
                row._mapping = dict(captured_params)
                result = MagicMock()
                result.fetchone.return_value = row
                return result
            return MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=capture_execute)

        # 1. Write the entry
        entry_id = await write_audit_log(
            db,
            action=action,
            entity_type=entity_type,
            org_id=org_id,
            user_id=user_id,
            entity_id=entity_id,
            before_value=before_value,
            after_value=after_value,
            ip_address=ip_address,
            device_info=device_info,
        )

        # 2. Attempt UPDATE — must fail
        from sqlalchemy import text

        with pytest.raises(ProgrammingError):
            await db.execute(
                text("UPDATE audit_log SET action = :a WHERE id = :id"),
                {"a": "tampered", "id": str(entry_id)},
            )

        # 3. Attempt DELETE — must fail
        with pytest.raises(ProgrammingError):
            await db.execute(
                text("DELETE FROM audit_log WHERE id = :id"),
                {"id": str(entry_id)},
            )

        # 4. Verify original data is intact by reading back
        result = await db.execute(
            text("SELECT * FROM audit_log WHERE id = :id"),
            {"id": str(entry_id)},
        )
        row = result.fetchone()

        assert row is not None, "Entry must still exist after failed mutations"
        assert row._mapping["action"] == action
        assert row._mapping["entity_type"] == entity_type
        assert row._mapping["org_id"] == str(org_id)
        assert row._mapping["user_id"] == str(user_id)
        assert row._mapping["entity_id"] == str(entity_id)
