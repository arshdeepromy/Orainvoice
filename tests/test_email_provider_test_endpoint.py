"""Unit tests for ``email_providers/service.py::test_email_provider``.

Covers task 3.15 of the email-provider-unification spec: the per-provider
admin "Test" endpoint must delegate transport work to
:func:`app.integrations.email_sender.dispatch_one_provider` and translate
the returned :class:`~app.integrations.email_sender.EmailAttempt` into
the legacy ``{success, message, error}`` response shape that the admin
Email Providers page consumes.

These tests pin:

  - the success path still calls
    ``write_audit_log(action="admin.email_provider_test_sent")`` and
    returns ``success=True`` with the expected ``message``;
  - SOFT_AUTH failures from the unified dispatcher surface as the
    legacy "Authentication failed" message;
  - generic SOFT_PROVIDER failures surface as the legacy
    "Failed to send test email" message;
  - early-return branches (provider-not-found, credentials not set,
    missing recipient) do not call into ``dispatch_one_provider``.

Validates: Requirements 1.7, 6.2
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time.
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.integrations.email_sender import EmailAttempt, FailureKind
from app.modules.email_providers import service as ep_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(
    provider_key: str = "brevo",
    *,
    credentials_set: bool = True,
) -> MagicMock:
    """Mock an ``EmailProvider`` row sufficient for the test endpoint."""
    provider = MagicMock()
    provider.id = uuid.uuid4()
    provider.provider_key = provider_key
    provider.display_name = provider_key.title()
    provider.credentials_set = credentials_set
    provider.credentials_encrypted = b"x" if credentials_set else None
    provider.config = {"from_email": "from@example.com"}
    provider.smtp_host = None
    provider.smtp_port = None
    provider.smtp_encryption = "tls"
    return provider


def _make_db_with_provider(provider: MagicMock | None) -> AsyncMock:
    """Return an ``AsyncSession`` mock whose first ``execute`` resolves to
    a result containing ``provider`` (or ``None`` when not found)."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=provider)
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_success_when_dispatch_succeeds() -> None:
    """Happy path: ``dispatch_one_provider`` returns a successful attempt
    so the endpoint returns ``success=True`` and writes the audit log.

    Validates: Requirements 1.7
    """
    provider = _make_provider("brevo")
    db = _make_db_with_provider(provider)

    success_attempt = EmailAttempt(
        provider_key="brevo",
        transport="rest_api",
        success=True,
        duration_ms=12,
        message_id="<abc@example.com>",
    )

    with patch.object(
        ep_service,
        "dispatch_one_provider",
        new=AsyncMock(return_value=success_attempt),
    ) as dispatch_mock, patch.object(
        ep_service,
        "write_audit_log",
        new=AsyncMock(),
    ) as audit_mock:
        result = await ep_service.test_email_provider(
            db,
            provider_key="brevo",
            to_email="recipient@example.com",
        )

    assert result == {
        "success": True,
        "message": "Test email sent to recipient@example.com",
    }
    dispatch_mock.assert_awaited_once()
    # The provider and message must be forwarded; no chain, no failover.
    args, _kwargs = dispatch_mock.await_args
    assert args[1] is provider
    assert args[2].to_email == "recipient@example.com"
    assert args[2].subject == "Test Email from Brevo"
    audit_mock.assert_awaited_once()
    audit_kwargs = audit_mock.await_args.kwargs
    assert audit_kwargs["action"] == "admin.email_provider_test_sent"
    assert audit_kwargs["after_value"]["success"] is True


@pytest.mark.asyncio
async def test_returns_auth_failed_when_dispatch_soft_auth() -> None:
    """SOFT_AUTH failures map to the legacy "Authentication failed"
    message so the admin UI's existing copy keeps working.

    Validates: Requirements 1.7
    """
    provider = _make_provider("sendgrid")
    db = _make_db_with_provider(provider)

    auth_attempt = EmailAttempt(
        provider_key="sendgrid",
        transport="rest_api",
        success=False,
        error="API key rejected (401): unauthorized",
        failure_kind=FailureKind.SOFT_AUTH,
        duration_ms=5,
    )

    with patch.object(
        ep_service,
        "dispatch_one_provider",
        new=AsyncMock(return_value=auth_attempt),
    ), patch.object(
        ep_service,
        "write_audit_log",
        new=AsyncMock(),
    ) as audit_mock:
        result = await ep_service.test_email_provider(
            db,
            provider_key="sendgrid",
            to_email="recipient@example.com",
        )

    assert result["success"] is False
    assert result["message"] == "Authentication failed"
    assert "401" in result["error"]
    audit_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_returns_generic_failure_when_dispatch_soft_provider() -> None:
    """Non-auth provider failures surface as the legacy generic
    "Failed to send test email" message.

    Validates: Requirements 1.7
    """
    provider = _make_provider("mailgun")
    db = _make_db_with_provider(provider)

    network_attempt = EmailAttempt(
        provider_key="mailgun",
        transport="smtp",
        success=False,
        error="connection refused",
        failure_kind=FailureKind.SOFT_PROVIDER,
        duration_ms=3,
    )

    with patch.object(
        ep_service,
        "dispatch_one_provider",
        new=AsyncMock(return_value=network_attempt),
    ), patch.object(
        ep_service,
        "write_audit_log",
        new=AsyncMock(),
    ):
        result = await ep_service.test_email_provider(
            db,
            provider_key="mailgun",
            to_email="recipient@example.com",
        )

    assert result["success"] is False
    assert result["message"] == "Failed to send test email"
    assert result["error"] == "connection refused"


@pytest.mark.asyncio
async def test_provider_not_found_short_circuits() -> None:
    """When the row doesn't exist, the endpoint returns 404-shape and
    never calls ``dispatch_one_provider``.

    Validates: Requirements 1.7
    """
    db = _make_db_with_provider(None)

    with patch.object(
        ep_service,
        "dispatch_one_provider",
        new=AsyncMock(),
    ) as dispatch_mock:
        result = await ep_service.test_email_provider(
            db,
            provider_key="nonexistent",
            to_email="recipient@example.com",
        )

    assert result == {
        "success": False,
        "message": "Provider not found",
        "error": "Provider not found",
    }
    dispatch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_credentials_not_set_short_circuits() -> None:
    """Provider exists but no credentials configured: short-circuit
    without dispatching.

    Validates: Requirements 1.7
    """
    provider = _make_provider("brevo", credentials_set=False)
    db = _make_db_with_provider(provider)

    with patch.object(
        ep_service,
        "dispatch_one_provider",
        new=AsyncMock(),
    ) as dispatch_mock:
        result = await ep_service.test_email_provider(
            db,
            provider_key="brevo",
            to_email="recipient@example.com",
        )

    assert result["success"] is False
    assert result["message"] == "Credentials not configured"
    dispatch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_recipient_short_circuits() -> None:
    """Empty/None recipient: short-circuit without dispatching.

    Validates: Requirements 1.7
    """
    provider = _make_provider("brevo")
    db = _make_db_with_provider(provider)

    with patch.object(
        ep_service,
        "dispatch_one_provider",
        new=AsyncMock(),
    ) as dispatch_mock:
        result = await ep_service.test_email_provider(
            db,
            provider_key="brevo",
            to_email=None,
        )

    assert result["success"] is False
    assert result["message"] == "No recipient email"
    dispatch_mock.assert_not_awaited()
