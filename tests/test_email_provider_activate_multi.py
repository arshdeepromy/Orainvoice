"""Unit tests for ``activate_email_provider`` — multi-active failover.

Covers task 5.4 of the email-provider-unification spec: activating a
second provider must not deactivate the first. After both activate
calls land, the list endpoint must report both keys in
``active_providers`` (priority-ordered), with ``active_provider``
(singular, kept for one release of backwards-compat) holding the
highest-priority key.

This pins the Phase 5 contract from Requirement 9.1 — the legacy
"there can be only one" behaviour was removed in commit 4971047 — and
the response shape from Requirement 9.6.

Validates: Requirements 9.1, 9.6, 21.7
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time.
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.email_providers import service as ep_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(
    provider_key: str,
    *,
    priority: int = 1,
    is_active: bool = False,
) -> MagicMock:
    """Mock an ``EmailProvider`` row sufficient for activate + list paths.

    Includes every attribute ``_provider_to_dict`` reads — including the
    ``created_at`` / ``updated_at`` ``.isoformat()`` calls — so the
    serialiser doesn't blow up when the activate path returns the dict
    after a successful flip.
    """
    provider = MagicMock()
    provider.id = uuid.uuid4()
    provider.provider_key = provider_key
    provider.display_name = provider_key.title()
    provider.description = None
    provider.smtp_host = None
    provider.smtp_port = None
    provider.smtp_encryption = "tls"
    provider.priority = priority
    provider.is_active = is_active
    provider.credentials_encrypted = b"x"
    provider.credentials_set = True
    provider.config = {"from_email": "from@example.com"}
    provider.setup_guide = None
    provider.created_at = datetime.now(timezone.utc)
    provider.updated_at = datetime.now(timezone.utc)
    return provider


def _make_lookup_result(provider: MagicMock | None) -> MagicMock:
    """Result whose ``scalar_one_or_none()`` returns ``provider``.

    Mirrors the shape produced by ``db.execute(select(...).where(...))``
    in the activate code path.
    """
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=provider)
    return result


def _make_list_result(providers: list[MagicMock]) -> MagicMock:
    """Result whose ``scalars().all()`` returns the provider list.

    Mirrors the shape produced by
    ``db.execute(select(EmailProvider).order_by(...))`` in the list code
    path.
    """
    scalars_proxy = MagicMock()
    scalars_proxy.all = MagicMock(return_value=providers)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars_proxy)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activating_second_provider_does_not_deactivate_first() -> None:
    """Activate A, then activate B — both end ``is_active=True``.

    The Phase 5 rewrite removed the legacy
    ``UPDATE email_providers SET is_active=false`` line that ran ahead
    of every activate. Without that change the second call would flip
    A back to inactive and break failover before the chain ever ran.
    This test pins the new behaviour so a regression is caught the
    first time someone "tidies up" the activate function.

    Validates: Requirement 9.1
    """
    provider_a = _make_provider("brevo", priority=1, is_active=False)
    provider_b = _make_provider("sendgrid", priority=2, is_active=False)

    db = AsyncMock()
    # Two activate calls → two lookups, each returning the matching row.
    db.execute = AsyncMock(
        side_effect=[
            _make_lookup_result(provider_a),
            _make_lookup_result(provider_b),
        ]
    )
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    with patch.object(
        ep_service,
        "write_audit_log",
        new=AsyncMock(),
    ) as audit_mock:
        first = await ep_service.activate_email_provider(
            db, provider_key="brevo"
        )
        second = await ep_service.activate_email_provider(
            db, provider_key="sendgrid"
        )

    # Both rows ended active.
    assert provider_a.is_active is True
    assert provider_b.is_active is True

    # The activate path returned the post-flip dict for each — no
    # short-circuit through the "already active" idempotent branch.
    assert first is not None and first["provider_key"] == "brevo"
    assert first["is_active"] is True
    assert second is not None and second["provider_key"] == "sendgrid"
    assert second["is_active"] is True

    # One audit-log entry per real flip (Req 9.7: action name is
    # ``email_provider_activated``).
    assert audit_mock.await_count == 2
    for call in audit_mock.await_args_list:
        assert call.kwargs["action"] == "admin.email_provider_activated"


@pytest.mark.asyncio
async def test_second_activate_does_not_run_deactivation_query() -> None:
    """The activate path must not issue a bulk-deactivate UPDATE.

    A regression that re-introduced the legacy
    ``update(EmailProvider).values(is_active=False)`` statement would
    show up here as a third ``db.execute`` call on the second activate
    (one for the lookup, one for the bulk deactivate). Pinning the call
    count to exactly one execute per activate makes that regression
    unmissable.

    Validates: Requirement 9.1
    """
    provider_a = _make_provider("brevo", priority=1, is_active=False)
    provider_b = _make_provider("sendgrid", priority=2, is_active=False)

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _make_lookup_result(provider_a),
            _make_lookup_result(provider_b),
        ]
    )
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    with patch.object(ep_service, "write_audit_log", new=AsyncMock()):
        await ep_service.activate_email_provider(db, provider_key="brevo")
        await ep_service.activate_email_provider(
            db, provider_key="sendgrid"
        )

    # Exactly one execute per activate — the lookup. No bulk deactivate.
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_list_after_dual_activate_returns_both_in_priority_order() -> None:
    """``list_email_providers`` exposes both keys via ``active_providers``.

    With A (priority 1) and B (priority 2) both active, the list
    response must:

    - return ``active_providers == ["brevo", "sendgrid"]`` ordered by
      ``priority ASC``;
    - retain ``active_provider == "brevo"`` (the legacy singular field
      kept for one release per Req 9.6) as the first element of that
      list.

    The provider sort key for the active-set computation is
    ``priority``, even though the SQL ``order_by`` is by
    ``display_name`` — that's deliberate: the SQL sort is for the
    admin-UI table, the Python sort is for the failover chain.

    Validates: Requirements 9.1, 9.6
    """
    # A (brevo, priority 1) and B (sendgrid, priority 2) both active,
    # plus an inactive provider C to prove the filter excludes it.
    provider_a = _make_provider("brevo", priority=1, is_active=True)
    provider_b = _make_provider("sendgrid", priority=2, is_active=True)
    provider_c = _make_provider("mailgun", priority=3, is_active=False)

    db = AsyncMock()
    # ``list_email_providers`` does ORDER BY display_name; the mock
    # returns the rows in that order (Brevo, Mailgun, Sendgrid).
    db.execute = AsyncMock(
        return_value=_make_list_result(
            [provider_a, provider_c, provider_b]
        )
    )

    response = await ep_service.list_email_providers(db)

    # active_providers is priority-sorted, not display_name-sorted.
    assert response["active_providers"] == ["brevo", "sendgrid"]
    # Singular field retained for one release; equals the head of the list.
    assert response["active_provider"] == "brevo"
    # All three rows surface in the providers list.
    assert {p["provider_key"] for p in response["providers"]} == {
        "brevo",
        "sendgrid",
        "mailgun",
    }
    # Inactive row is not included in active_providers.
    assert "mailgun" not in response["active_providers"]


@pytest.mark.asyncio
async def test_activate_is_idempotent_for_already_active_row() -> None:
    """Re-activating an already-active row is a no-op (Req 9.2).

    The idempotent branch returns the current dict without writing to
    the audit log. This guards the case where the admin double-clicks
    the Activate button — we don't want a spurious second log entry.

    Validates: Requirement 9.1 (idempotence corollary)
    """
    provider_a = _make_provider("brevo", priority=1, is_active=True)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_lookup_result(provider_a))
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    with patch.object(
        ep_service,
        "write_audit_log",
        new=AsyncMock(),
    ) as audit_mock:
        result = await ep_service.activate_email_provider(
            db, provider_key="brevo"
        )

    assert result is not None
    assert result["is_active"] is True
    # Still active — no flip.
    assert provider_a.is_active is True
    # No audit-log entry for an idempotent call.
    audit_mock.assert_not_awaited()
    # No flush (nothing to write).
    db.flush.assert_not_awaited()
