"""Property-based tests for platform security audit log service (Task 1.4).

Properties 3–7 validate the ``get_platform_security_audit_log`` service
function against the design document's correctness properties.

Uses Hypothesis to verify universal properties across randomly generated
filter combinations, audit log entries, and edge cases.

Feature: global-admin-security-settings
Properties 3–7

Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app.modules.auth.security_settings_schemas import (
    AuditLogFilters,
    PlatformAuditLogEntry,
    PlatformAuditLogPage,
)
from app.modules.auth.security_audit_service import (
    MAX_ENTRIES,
    SECURITY_ACTION_PREFIXES,
    SECURITY_ACTION_EXACT,
    SECURITY_ACTION_WILDCARD_PREFIX,
    get_platform_security_audit_log,
    is_security_action,
    get_action_description,
    parse_device_info,
)


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

# Security-related actions that match the SQL filter
security_action_strategy = st.sampled_from([
    "auth.login_success",
    "auth.login_failed_invalid_password",
    "auth.login_failed_unknown_email",
    "auth.login_failed_account_inactive",
    "auth.login_failed_account_locked",
    "auth.login_failed_ip_blocked",
    "auth.mfa_verified",
    "auth.mfa_failed",
    "auth.password_changed",
    "auth.password_reset",
    "auth.session_revoked",
    "auth.all_sessions_revoked",
    "org.mfa_policy_updated",
    "org.security_settings_updated",
    "org.custom_role_created",
    "org.custom_role_updated",
    "org.custom_role_deleted",
])

# Non-security actions that should NOT appear in results
non_security_action_strategy = st.sampled_from([
    "invoice.created",
    "invoice.issued",
    "customer.created",
    "customer.updated",
    "payment.received",
    "vehicle.lookup",
    "settings.updated",
    "plan.updated",
])

# IP addresses (v4)
ip_strategy = st.one_of(
    st.none(),
    st.tuples(
        st.integers(1, 254),
        st.integers(0, 255),
        st.integers(0, 255),
        st.integers(1, 254),
    ).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}"),
)

# User-Agent strings for device info parsing
device_info_strategy = st.one_of(
    st.none(),
    st.sampled_from([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Firefox/121.0",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1 Version/17.0",
        "Mozilla/5.0 (Linux; Android 14) Chrome/120.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0) Edg/120.0.0.0",
    ]),
)

# Valid page numbers
page_strategy = st.integers(min_value=1, max_value=100)

# Valid page sizes
page_size_strategy = st.integers(min_value=1, max_value=100)

# Optional datetime filters
optional_datetime_strategy = st.one_of(
    st.none(),
    st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 12, 31),
        timezones=st.just(timezone.utc),
    ),
)

# Email strategy
email_strategy = st.from_regex(r"[a-z]{3,8}@[a-z]{3,6}\.com", fullmatch=True)

# Org name strategy
org_name_strategy = st.one_of(
    st.none(),
    st.text(
        min_size=2,
        max_size=30,
        alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
    ).filter(lambda s: s.strip()),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_audit_row(
    *,
    action: str = "auth.login_success",
    user_email: str | None = "user@example.com",
    org_name: str | None = "Test Org",
    ip_address: str | None = "192.168.1.1",
    device_info: str | None = None,
    created_at: datetime | None = None,
    user_id: uuid.UUID | None = None,
    entity_type: str | None = "user",
    entity_id: uuid.UUID | None = None,
    before_value: dict | None = None,
    after_value: dict | None = None,
):
    """Build a mock DB row matching the platform audit log SELECT columns."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.user_id = user_id or uuid.uuid4()
    row.action = action
    row.entity_type = entity_type
    row.entity_id = entity_id
    row.before_value = before_value
    row.after_value = after_value
    row.ip_address = ip_address
    row.device_info = device_info
    row.created_at = created_at or datetime.now(timezone.utc)
    row.user_email = user_email
    row.org_name = org_name
    return row


def _make_mock_db(*, total: int, rows: list | None = None):
    """Build a mock AsyncSession that returns count and data results."""
    db = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = total

    data_result = MagicMock()
    data_result.fetchall.return_value = rows or []

    db.execute = AsyncMock(side_effect=[count_result, data_result])
    return db


# ===========================================================================
# Property 3: Platform audit log filter acceptance
# ===========================================================================


class TestProperty3FilterAcceptance:
    """# Feature: global-admin-security-settings, Property 3: Platform audit log filter acceptance

    *For any* valid combination of filter parameters (``start_date``,
    ``end_date``, ``action``, ``user_id``, ``page``, ``page_size``),
    the ``get_platform_security_audit_log`` function SHALL return a valid
    ``PlatformAuditLogPage`` response without error.

    **Validates: Requirements 7.2**
    """

    @given(
        start_date=optional_datetime_strategy,
        end_date=optional_datetime_strategy,
        action=st.one_of(st.none(), security_action_strategy),
        user_id=st.one_of(st.none(), st.uuids()),
        page=page_strategy,
        page_size=page_size_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_any_valid_filter_combo_returns_valid_page(
        self,
        start_date: datetime | None,
        end_date: datetime | None,
        action: str | None,
        user_id: uuid.UUID | None,
        page: int,
        page_size: int,
    ):
        """Random valid filter combinations always return a valid
        PlatformAuditLogPage.

        **Validates: Requirements 7.2**
        """
        # Build a few sample rows so the response is non-trivial
        rows = [
            _make_audit_row(action="auth.login_success"),
            _make_audit_row(action="auth.mfa_verified"),
        ]
        db = _make_mock_db(total=len(rows), rows=rows)

        filters = AuditLogFilters(
            start_date=start_date,
            end_date=end_date,
            action=action,
            user_id=user_id,
            page=page,
            page_size=page_size,
        )

        result = await get_platform_security_audit_log(db, filters)

        # Must return a valid PlatformAuditLogPage
        assert isinstance(result, PlatformAuditLogPage)
        assert isinstance(result.items, list)
        assert isinstance(result.total, int)
        assert result.total >= 0
        assert isinstance(result.page, int)
        assert result.page >= 1
        assert isinstance(result.page_size, int)
        assert result.page_size >= 1
        assert isinstance(result.truncated, bool)

        # Every item must be a PlatformAuditLogEntry
        for item in result.items:
            assert isinstance(item, PlatformAuditLogEntry)


# ===========================================================================
# Property 4: Platform audit log returns cross-org security actions
# ===========================================================================


class TestProperty4CrossOrgSecurityActions:
    """# Feature: global-admin-security-settings, Property 4: Platform audit log returns cross-org security actions

    *For any* set of audit log entries in the database, the
    ``get_platform_security_audit_log`` function SHALL return all entries
    whose action matches the security action filter (``auth.*``,
    ``org.mfa_policy_updated``, ``org.security_settings_updated``,
    ``org.custom_role_*``) regardless of their ``org_id`` value.

    **Validates: Requirements 7.3**
    """

    @given(
        action=security_action_strategy,
        org_name=org_name_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_security_actions_from_any_org_appear_without_org_filter(
        self,
        action: str,
        org_name: str | None,
    ):
        """Security actions from any org appear in results without org_id
        filtering.

        **Validates: Requirements 7.3**
        """
        # Create a row with the given action and org_name (could be None for platform-level)
        rows = [_make_audit_row(action=action, org_name=org_name)]
        db = _make_mock_db(total=1, rows=rows)

        filters = AuditLogFilters(page=1, page_size=25)
        result = await get_platform_security_audit_log(db, filters)

        assert len(result.items) == 1
        assert result.items[0].action == action
        assert result.items[0].org_name == org_name

        # Verify the SQL query does NOT contain org_id filtering
        # The first execute call is the count query
        count_call = db.execute.call_args_list[0]
        count_sql = str(count_call[0][0].text)
        assert "a.org_id = :org_id" not in count_sql, (
            "Platform audit log must NOT filter by org_id"
        )

        # The second execute call is the data query
        data_call = db.execute.call_args_list[1]
        data_sql = str(data_call[0][0].text)
        assert "a.org_id = :org_id" not in data_sql, (
            "Platform audit log must NOT filter by org_id"
        )

    @given(action=security_action_strategy)
    @PBT_SETTINGS
    def test_is_security_action_accepts_all_security_actions(self, action: str):
        """Every action in the security action set is recognized by
        is_security_action.

        **Validates: Requirements 7.3**
        """
        assert is_security_action(action) is True, (
            f"Action '{action}' should be recognized as a security action"
        )

    @given(action=non_security_action_strategy)
    @PBT_SETTINGS
    def test_is_security_action_rejects_non_security_actions(self, action: str):
        """Non-security actions are rejected by is_security_action.

        **Validates: Requirements 7.3**
        """
        assert is_security_action(action) is False, (
            f"Action '{action}' should NOT be recognized as a security action"
        )


# ===========================================================================
# Property 5: Platform audit log response enrichment
# ===========================================================================


class TestProperty5ResponseEnrichment:
    """# Feature: global-admin-security-settings, Property 5: Platform audit log response enrichment

    *For any* audit log entry returned by ``get_platform_security_audit_log``,
    the entry SHALL include a resolved ``user_email`` (from the ``users``
    table join, or ``null`` if the user was deleted) and a resolved
    ``org_name`` (from the ``organisations`` table join, or ``null`` for
    platform-level events with no ``org_id``), conforming to the
    ``PlatformAuditLogEntry`` schema.

    **Validates: Requirements 7.4, 7.5**
    """

    @given(
        user_email=st.one_of(st.none(), email_strategy),
        org_name=org_name_strategy,
        action=security_action_strategy,
        ip_address=ip_strategy,
        device_info=device_info_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_every_entry_has_resolved_user_email_and_org_name(
        self,
        user_email: str | None,
        org_name: str | None,
        action: str,
        ip_address: str | None,
        device_info: str | None,
    ):
        """Every entry has resolved user_email and org_name conforming to
        PlatformAuditLogEntry.

        **Validates: Requirements 7.4, 7.5**
        """
        rows = [
            _make_audit_row(
                action=action,
                user_email=user_email,
                org_name=org_name,
                ip_address=ip_address,
                device_info=device_info,
            )
        ]
        db = _make_mock_db(total=1, rows=rows)

        filters = AuditLogFilters(page=1, page_size=25)
        result = await get_platform_security_audit_log(db, filters)

        assert len(result.items) == 1
        entry = result.items[0]

        # Entry must conform to PlatformAuditLogEntry schema
        assert isinstance(entry, PlatformAuditLogEntry)

        # user_email is resolved from the users table join (None if user deleted)
        assert entry.user_email == user_email

        # org_name is resolved from the organisations table join (None for platform events)
        assert entry.org_name == org_name

        # Standard fields must be present
        assert entry.action == action
        assert entry.id is not None
        assert entry.timestamp is not None
        assert entry.action_description is not None
        assert len(entry.action_description) > 0

    @given(
        action=security_action_strategy,
        device_info=device_info_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_entry_has_parsed_browser_and_os(
        self,
        action: str,
        device_info: str | None,
    ):
        """Every entry has browser and os fields parsed from device_info.

        **Validates: Requirements 7.4, 7.5**
        """
        rows = [_make_audit_row(action=action, device_info=device_info)]
        db = _make_mock_db(total=1, rows=rows)

        filters = AuditLogFilters(page=1, page_size=25)
        result = await get_platform_security_audit_log(db, filters)

        entry = result.items[0]
        expected_browser, expected_os = parse_device_info(device_info)

        assert entry.browser == expected_browser
        assert entry.os == expected_os

    @given(
        user_email=st.one_of(st.none(), email_strategy),
        org_name=org_name_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_data_query_joins_users_and_organisations(
        self,
        user_email: str | None,
        org_name: str | None,
    ):
        """The data query JOINs with users and organisations tables.

        **Validates: Requirements 7.4, 7.5**
        """
        rows = [_make_audit_row(user_email=user_email, org_name=org_name)]
        db = _make_mock_db(total=1, rows=rows)

        filters = AuditLogFilters(page=1, page_size=25)
        await get_platform_security_audit_log(db, filters)

        # The data query (second execute call) must JOIN users and organisations
        data_call = db.execute.call_args_list[1]
        data_sql = str(data_call[0][0].text)

        assert "LEFT JOIN users u ON u.id = a.user_id" in data_sql, (
            "Data query must LEFT JOIN users to resolve user_email"
        )
        assert "LEFT JOIN organisations o ON o.id = a.org_id" in data_sql, (
            "Data query must LEFT JOIN organisations to resolve org_name"
        )
        assert "u.email AS user_email" in data_sql, (
            "Data query must SELECT u.email AS user_email"
        )
        assert "o.name AS org_name" in data_sql, (
            "Data query must SELECT o.name AS org_name"
        )


# ===========================================================================
# Property 6: Platform audit log 10,000-entry hard cap
# ===========================================================================


class TestProperty6HardCap:
    """# Feature: global-admin-security-settings, Property 6: Platform audit log 10,000-entry hard cap

    *For any* query where the total matching audit log entries exceed
    10,000, the endpoint SHALL return ``truncated: true`` and the
    ``total`` field SHALL be capped at 10,000.

    **Validates: Requirements 7.6**
    """

    @given(
        total=st.integers(min_value=MAX_ENTRIES + 1, max_value=MAX_ENTRIES * 3),
        page=page_strategy,
        page_size=page_size_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_exceeding_max_entries_sets_truncated_true(
        self,
        total: int,
        page: int,
        page_size: int,
    ):
        """When total exceeds 10,000, truncated is true and total is capped.

        **Validates: Requirements 7.6**
        """
        rows = [_make_audit_row() for _ in range(min(page_size, 5))]
        db = _make_mock_db(total=total, rows=rows)

        filters = AuditLogFilters(page=page, page_size=page_size)
        result = await get_platform_security_audit_log(db, filters)

        assert result.truncated is True, (
            f"truncated must be True when total ({total}) > MAX_ENTRIES ({MAX_ENTRIES})"
        )
        assert result.total <= MAX_ENTRIES, (
            f"total ({result.total}) must be capped at MAX_ENTRIES ({MAX_ENTRIES})"
        )
        assert result.total == MAX_ENTRIES

    @given(
        total=st.integers(min_value=0, max_value=MAX_ENTRIES),
        page_size=page_size_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_within_max_entries_truncated_is_false(
        self,
        total: int,
        page_size: int,
    ):
        """When total is within 10,000, truncated is false and total is exact.

        **Validates: Requirements 7.6**
        """
        rows = [_make_audit_row() for _ in range(min(total, page_size, 3))]
        db = _make_mock_db(total=total, rows=rows)

        filters = AuditLogFilters(page=1, page_size=page_size)
        result = await get_platform_security_audit_log(db, filters)

        assert result.truncated is False, (
            f"truncated must be False when total ({total}) <= MAX_ENTRIES ({MAX_ENTRIES})"
        )
        assert result.total == total

    @given(
        page=st.integers(min_value=1, max_value=500),
        page_size=st.integers(min_value=1, max_value=100),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_offset_beyond_max_entries_returns_empty_items(
        self,
        page: int,
        page_size: int,
    ):
        """When offset exceeds MAX_ENTRIES, items list is empty.

        **Validates: Requirements 7.6**
        """
        offset = (page - 1) * min(page_size, MAX_ENTRIES)
        assume(offset >= MAX_ENTRIES)

        total = MAX_ENTRIES + 500
        # When offset >= MAX_ENTRIES, the function returns early with empty items
        # Only the count query is executed
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = total
        db.execute = AsyncMock(return_value=count_result)

        filters = AuditLogFilters(page=page, page_size=page_size)
        result = await get_platform_security_audit_log(db, filters)

        assert result.items == [], (
            "Items must be empty when offset exceeds MAX_ENTRIES"
        )
        assert result.total == MAX_ENTRIES
        assert result.truncated is True


# ===========================================================================
# Property 7: Platform audit log ordering invariant
# ===========================================================================


class TestProperty7OrderingInvariant:
    """# Feature: global-admin-security-settings, Property 7: Platform audit log ordering invariant

    *For any* page of results returned by ``get_platform_security_audit_log``,
    the entries SHALL be ordered by ``created_at`` descending — that is,
    for every consecutive pair of entries ``(entries[i], entries[i+1])``,
    ``entries[i].timestamp >= entries[i+1].timestamp``.

    **Validates: Requirements 7.7**
    """

    @given(
        num_entries=st.integers(min_value=2, max_value=20),
        page_size=st.integers(min_value=2, max_value=25),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_entries_ordered_by_created_at_descending(
        self,
        num_entries: int,
        page_size: int,
    ):
        """Entries are ordered by created_at descending.

        **Validates: Requirements 7.7**
        """
        # Generate rows with descending timestamps (as the SQL ORDER BY would produce)
        base_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        rows = [
            _make_audit_row(
                created_at=base_time - timedelta(minutes=i),
            )
            for i in range(num_entries)
        ]

        db = _make_mock_db(total=num_entries, rows=rows[:page_size])

        filters = AuditLogFilters(page=1, page_size=page_size)
        result = await get_platform_security_audit_log(db, filters)

        # Verify descending order
        for i in range(len(result.items) - 1):
            assert result.items[i].timestamp >= result.items[i + 1].timestamp, (
                f"Entry {i} timestamp ({result.items[i].timestamp}) must be >= "
                f"entry {i+1} timestamp ({result.items[i + 1].timestamp})"
            )

    @given(
        page=page_strategy,
        page_size=page_size_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_sql_query_contains_order_by_created_at_desc(
        self,
        page: int,
        page_size: int,
    ):
        """The SQL query always includes ORDER BY a.created_at DESC.

        **Validates: Requirements 7.7**
        """
        rows = [_make_audit_row()]
        db = _make_mock_db(total=1, rows=rows)

        filters = AuditLogFilters(page=page, page_size=page_size)

        # Only run if offset won't exceed MAX_ENTRIES (otherwise early return skips data query)
        offset = (page - 1) * min(page_size, MAX_ENTRIES)
        assume(offset < MAX_ENTRIES)

        result = await get_platform_security_audit_log(db, filters)

        # The data query (second execute call) must have ORDER BY
        data_call = db.execute.call_args_list[1]
        data_sql = str(data_call[0][0].text)

        assert "ORDER BY a.created_at DESC" in data_sql, (
            "Data query must ORDER BY a.created_at DESC"
        )
