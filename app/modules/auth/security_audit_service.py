"""Security Audit Log Service.

Queries the ``audit_log`` table for security-related actions scoped to a
single organisation.  Results are paginated, ordered descending by
``created_at``, and enriched with human-readable action descriptions,
resolved user emails, and parsed device info (browser / OS).
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.security_settings_schemas import (
    ACTION_DESCRIPTIONS,
    AuditLogEntry,
    AuditLogFilters,
    AuditLogPage,
    PlatformAuditLogEntry,
    PlatformAuditLogPage,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Hard cap on total entries returned per query (requirement 6.7).
MAX_ENTRIES = 10_000

#: Actions considered "security-related" for the audit log viewer.
SECURITY_ACTION_SQL_FILTER = (
    "(a.action LIKE 'auth.%%' "
    "OR a.action IN ('org.mfa_policy_updated', 'org.security_settings_updated') "
    "OR a.action LIKE 'org.custom_role_%%')"
)

#: Set of security-related action prefixes / exact matches for pure-logic checks.
SECURITY_ACTION_PREFIXES = ("auth.",)
SECURITY_ACTION_EXACT = frozenset({
    "org.mfa_policy_updated",
    "org.security_settings_updated",
})
SECURITY_ACTION_WILDCARD_PREFIX = "org.custom_role_"


def is_security_action(action: str) -> bool:
    """Return ``True`` if *action* is a security-related audit action."""
    if action.startswith(SECURITY_ACTION_PREFIXES):
        return True
    if action in SECURITY_ACTION_EXACT:
        return True
    if action.startswith(SECURITY_ACTION_WILDCARD_PREFIX):
        return True
    return False


# ---------------------------------------------------------------------------
# Device-info parsing
# ---------------------------------------------------------------------------

# Simple regex patterns for common browsers and operating systems.
_BROWSER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Edg(?:e|A)?/([\d.]+)", re.I), "Edge"),
    (re.compile(r"OPR/([\d.]+)", re.I), "Opera"),
    (re.compile(r"Chrome/([\d.]+)", re.I), "Chrome"),
    (re.compile(r"Firefox/([\d.]+)", re.I), "Firefox"),
    (re.compile(r"Safari/([\d.]+).*Version/([\d.]+)", re.I), "Safari"),
    (re.compile(r"Version/([\d.]+).*Safari", re.I), "Safari"),
]

_OS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Windows NT 10\.0", re.I), "Windows 10"),
    (re.compile(r"Windows NT 6\.3", re.I), "Windows 8.1"),
    (re.compile(r"Windows NT 6\.1", re.I), "Windows 7"),
    (re.compile(r"Windows", re.I), "Windows"),
    (re.compile(r"Mac OS X ([\d_]+)", re.I), "macOS"),
    (re.compile(r"Android ([\d.]+)", re.I), "Android"),
    (re.compile(r"iPhone OS ([\d_]+)", re.I), "iOS"),
    (re.compile(r"iPad.*OS ([\d_]+)", re.I), "iPadOS"),
    (re.compile(r"Linux", re.I), "Linux"),
    (re.compile(r"CrOS", re.I), "Chrome OS"),
]


def parse_device_info(device_info: str | None) -> tuple[str | None, str | None]:
    """Parse a User-Agent string into ``(browser, os)``.

    Returns ``(None, None)`` when *device_info* is ``None`` or unparseable.
    """
    if not device_info:
        return None, None

    browser: str | None = None
    os_name: str | None = None

    for pattern, name in _BROWSER_PATTERNS:
        if pattern.search(device_info):
            browser = name
            break

    for pattern, name in _OS_PATTERNS:
        if pattern.search(device_info):
            os_name = name
            break

    return browser, os_name


def get_action_description(action: str) -> str:
    """Return a human-readable description for *action*.

    Falls back to title-casing the action key when no mapping exists.
    """
    if action in ACTION_DESCRIPTIONS:
        return ACTION_DESCRIPTIONS[action]
    # Fallback: "auth.login_success" → "Auth Login Success"
    return action.replace(".", " ").replace("_", " ").title()


# ---------------------------------------------------------------------------
# Main query
# ---------------------------------------------------------------------------

async def get_security_audit_log(
    db: AsyncSession,
    org_id: UUID,
    filters: AuditLogFilters,
) -> AuditLogPage:
    """Query the audit log for security-related actions, paginated.

    Parameters
    ----------
    db:
        Active async database session.
    org_id:
        Organisation to scope the query to.
    filters:
        Pagination and optional date/action/user filters.

    Returns
    -------
    AuditLogPage
        Paginated result with enriched entries.  When the total matching
        rows exceed :data:`MAX_ENTRIES`, ``truncated`` is ``True`` and only
        the most recent 10,000 entries are returned.
    """
    # -- Build WHERE clause ---------------------------------------------------
    where_clauses = [
        "a.org_id = :org_id",
        SECURITY_ACTION_SQL_FILTER,
    ]
    params: dict = {"org_id": str(org_id)}

    if filters.start_date is not None:
        where_clauses.append("a.created_at >= :start_date")
        params["start_date"] = filters.start_date

    if filters.end_date is not None:
        where_clauses.append("a.created_at <= :end_date")
        params["end_date"] = filters.end_date

    if filters.action is not None:
        where_clauses.append("a.action = :action_filter")
        params["action_filter"] = filters.action

    if filters.user_id is not None:
        where_clauses.append("a.user_id = :user_id_filter")
        params["user_id_filter"] = str(filters.user_id)

    where_sql = " AND ".join(where_clauses)

    # -- Count total matching rows --------------------------------------------
    count_sql = f"SELECT COUNT(*) FROM audit_log a WHERE {where_sql}"
    count_result = await db.execute(text(count_sql), params)
    total: int = count_result.scalar_one()

    truncated = total > MAX_ENTRIES

    # -- Fetch page -----------------------------------------------------------
    page_size = min(filters.page_size, MAX_ENTRIES)
    offset = (filters.page - 1) * page_size

    # Clamp offset so we never go beyond MAX_ENTRIES
    if offset >= MAX_ENTRIES:
        return AuditLogPage(
            items=[],
            total=min(total, MAX_ENTRIES),
            page=filters.page,
            page_size=page_size,
            truncated=truncated,
        )

    # Limit rows fetched to not exceed MAX_ENTRIES boundary
    effective_limit = min(page_size, MAX_ENTRIES - offset)

    data_sql = (
        f"SELECT a.id, a.user_id, a.action, a.entity_type, a.entity_id, "
        f"       a.before_value, a.after_value, "
        f"       CAST(a.ip_address AS TEXT) AS ip_address, "
        f"       a.device_info, a.created_at, "
        f"       u.email AS user_email "
        f"FROM audit_log a "
        f"LEFT JOIN users u ON u.id = a.user_id "
        f"WHERE {where_sql} "
        f"ORDER BY a.created_at DESC "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"] = effective_limit
    params["offset"] = offset

    result = await db.execute(text(data_sql), params)
    rows = result.fetchall()

    # -- Build response entries -----------------------------------------------
    items: list[AuditLogEntry] = []
    for row in rows:
        browser, os_name = parse_device_info(row.device_info)
        items.append(AuditLogEntry(
            id=row.id,
            timestamp=row.created_at,
            user_email=row.user_email,  # None for deleted users (LEFT JOIN)
            action=row.action,
            action_description=get_action_description(row.action),
            ip_address=row.ip_address,
            browser=browser,
            os=os_name,
            entity_type=row.entity_type,
            entity_id=str(row.entity_id) if row.entity_id else None,
            before_value=row.before_value,
            after_value=row.after_value,
        ))

    return AuditLogPage(
        items=items,
        total=min(total, MAX_ENTRIES),
        page=filters.page,
        page_size=page_size,
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Platform-wide query (no org_id filter)
# ---------------------------------------------------------------------------

async def get_platform_security_audit_log(
    db: AsyncSession,
    filters: AuditLogFilters,
) -> PlatformAuditLogPage:
    """Query the audit log for security-related actions across ALL organisations.

    Unlike :func:`get_security_audit_log`, this function:
    - Does **not** filter by ``org_id``
    - JOINs with the ``organisations`` table to resolve ``org_name``
    - Returns :class:`PlatformAuditLogEntry` items with an ``org_name`` field

    Parameters
    ----------
    db:
        Active async database session.
    filters:
        Pagination and optional date/action/user filters.

    Returns
    -------
    PlatformAuditLogPage
        Paginated result with enriched entries.  When the total matching
        rows exceed :data:`MAX_ENTRIES`, ``truncated`` is ``True`` and only
        the most recent 10,000 entries are returned.
    """
    # -- Build WHERE clause ---------------------------------------------------
    where_clauses = [
        SECURITY_ACTION_SQL_FILTER,
    ]
    params: dict = {}

    if filters.start_date is not None:
        where_clauses.append("a.created_at >= :start_date")
        params["start_date"] = filters.start_date

    if filters.end_date is not None:
        where_clauses.append("a.created_at <= :end_date")
        params["end_date"] = filters.end_date

    if filters.action is not None:
        where_clauses.append("a.action = :action_filter")
        params["action_filter"] = filters.action

    if filters.user_id is not None:
        where_clauses.append("a.user_id = :user_id_filter")
        params["user_id_filter"] = str(filters.user_id)

    where_sql = " AND ".join(where_clauses)

    # -- Count total matching rows --------------------------------------------
    count_sql = f"SELECT COUNT(*) FROM audit_log a WHERE {where_sql}"
    count_result = await db.execute(text(count_sql), params)
    total: int = count_result.scalar_one()

    truncated = total > MAX_ENTRIES

    # -- Fetch page -----------------------------------------------------------
    page_size = min(filters.page_size, MAX_ENTRIES)
    offset = (filters.page - 1) * page_size

    # Clamp offset so we never go beyond MAX_ENTRIES
    if offset >= MAX_ENTRIES:
        return PlatformAuditLogPage(
            items=[],
            total=min(total, MAX_ENTRIES),
            page=filters.page,
            page_size=page_size,
            truncated=truncated,
        )

    # Limit rows fetched to not exceed MAX_ENTRIES boundary
    effective_limit = min(page_size, MAX_ENTRIES - offset)

    data_sql = (
        f"SELECT a.id, a.user_id, a.action, a.entity_type, a.entity_id, "
        f"       a.before_value, a.after_value, "
        f"       CAST(a.ip_address AS TEXT) AS ip_address, "
        f"       a.device_info, a.created_at, "
        f"       u.email AS user_email, "
        f"       o.name AS org_name "
        f"FROM audit_log a "
        f"LEFT JOIN users u ON u.id = a.user_id "
        f"LEFT JOIN organisations o ON o.id = a.org_id "
        f"WHERE {where_sql} "
        f"ORDER BY a.created_at DESC "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"] = effective_limit
    params["offset"] = offset

    result = await db.execute(text(data_sql), params)
    rows = result.fetchall()

    # -- Build response entries -----------------------------------------------
    items: list[PlatformAuditLogEntry] = []
    for row in rows:
        browser, os_name = parse_device_info(row.device_info)
        items.append(PlatformAuditLogEntry(
            id=row.id,
            timestamp=row.created_at,
            user_email=row.user_email,
            action=row.action,
            action_description=get_action_description(row.action),
            ip_address=row.ip_address,
            browser=browser,
            os=os_name,
            entity_type=row.entity_type,
            entity_id=str(row.entity_id) if row.entity_id else None,
            before_value=row.before_value,
            after_value=row.after_value,
            org_name=row.org_name,
        ))

    return PlatformAuditLogPage(
        items=items,
        total=min(total, MAX_ENTRIES),
        page=filters.page,
        page_size=page_size,
        truncated=truncated,
    )
