"""Unit tests for the C2 + C1 auth security alert emails.

These functions used to be logger-only stubs. Phase 4 tasks 4.2 (C2)
and 4.3 (C1) of the email-provider-unification spec wire them up to
the unified sender.

  - C2 ``_send_anomalous_login_alert`` (``service.py:625``)
  - C1 ``_send_token_reuse_alert``    (``service.py:851``)

Both follow the auth-flow carve-out pattern (mirrors A7
``_send_permanent_lockout_email`` and C3 ``_send_password_reset_email``):

  - The function opens its own ``AsyncSession`` via
    ``async_session_factory`` because the caller's session is
    mid-transaction in ``authenticate_user`` / ``rotate_refresh_token``
    and may already be torn down by the time the best-effort send
    fires.
  - No ``log_email_sent`` (auth-flow carve-out — see
    in-app-notifications design §4.2).
  - No ``create_in_app_notification`` on failure.
  - Wrapped in a top-level ``try`` / ``except`` so delivery failure
    never blocks login or token rotation.

Per the task definition, these tests assert the email is **at least
attempted** — i.e. ``send_email`` is awaited exactly once with the
expected ``EmailMessage`` shape (recipient, body content, ``org_id``).
The unified sender's failover loop is exercised end-to-end by the
Phase 1 ``tests/test_email_sender_*.py`` suite, so we don't repeat
that here.

Validates: Requirements 8.2, 8.3
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.integrations.email_sender import (
    EmailAttempt,
    FailureKind,
    SendResult,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _success_result(provider_key: str = "brevo") -> SendResult:
    """A canned success ``SendResult`` for stubbing ``send_email``."""
    return SendResult(
        success=True,
        provider_key=provider_key,
        transport="rest_api",
        message_id=f"<msg-{provider_key}@example>",
        error=None,
        attempts=[
            EmailAttempt(
                provider_key=provider_key,
                transport="rest_api",
                success=True,
                message_id=f"<msg-{provider_key}@example>",
            )
        ],
    )


def _no_providers_result() -> SendResult:
    """A canned ``SendResult`` for the empty Active_Provider_Set case."""
    return SendResult(
        success=False,
        provider_key=None,
        transport=None,
        message_id=None,
        error="No active email providers configured",
        attempts=[],
    )


def _all_soft_auth_result() -> SendResult:
    """A canned total-failure ``SendResult`` (every provider 401'd)."""
    return SendResult(
        success=False,
        provider_key=None,
        transport=None,
        message_id=None,
        error="all providers returned 401",
        attempts=[
            EmailAttempt(
                provider_key="brevo",
                transport="rest_api",
                success=False,
                failure_kind=FailureKind.SOFT_AUTH,
                error="brevo REST 401",
            ),
            EmailAttempt(
                provider_key="sendgrid",
                transport="rest_api",
                success=False,
                failure_kind=FailureKind.SOFT_AUTH,
                error="sendgrid REST 401",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# C2 — _send_anomalous_login_alert
# ---------------------------------------------------------------------------


class TestC2SendAnomalousLoginAlert:
    """Pin the contract for the migrated ``_send_anomalous_login_alert``."""

    @pytest.mark.asyncio
    async def test_attempts_send_with_expected_message_shape(self):
        """Happy path: with one active provider, the function builds
        the right ``EmailMessage`` and dispatches via the unified
        sender exactly once.

        Pins per design row C2:

        - The unified sender is awaited exactly once (the email is at
          least attempted — the contract this task asks for).
        - ``EmailMessage.org_id`` propagates the caller's ``org_id``
          when the user is org-scoped.
        - Recipient on the message matches the function arg.
        - The IP address and device fingerprint appear in both the
          HTML and plain-text bodies so the user can spot the alert
          regardless of mail client.
        - Subject is security-themed.
        - The function uses ``async_session_factory`` (not the
          caller's session — there is no caller session for this
          function).
        - No attachments.

        Validates: Requirement 8.2
        """
        from app.modules.auth.service import _send_anomalous_login_alert

        # Mock the freshly opened async session — it just needs to act
        # like an async-context-manager that yields a session.
        opened_session = AsyncMock()
        factory_cm = MagicMock()
        factory_cm.__aenter__ = AsyncMock(return_value=opened_session)
        factory_cm.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(return_value=factory_cm)

        send_email_stub = AsyncMock(return_value=_success_result("brevo"))

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        with patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            await _send_anomalous_login_alert(
                email="user@example.com",
                user_id=user_id,
                anomalies=["new_device:mobile", "unusual_time:3:00"],
                ip_address="203.0.113.42",
                device_type="mobile",
                browser="Safari",
                org_id=org_id,
            )

        # Function opened its own session because the caller had none.
        factory.assert_called_once()

        # Email was at least attempted — exactly one dispatch.
        send_email_stub.assert_awaited_once()
        args, kwargs = send_email_stub.await_args

        # First positional is the freshly opened session.
        assert args[0] is opened_session

        message = args[1] if len(args) > 1 else kwargs.get("message")
        assert message is not None

        # org_id propagated from the caller (per design row C2).
        assert message.org_id == org_id

        # Recipient on the message matches the function arg.
        assert message.to_email == "user@example.com"

        # Subject is a security alert.
        assert "security" in message.subject.lower() or "sign-in" in message.subject.lower()

        # Both bodies present.
        assert message.html_body
        assert message.text_body

        # IP address shows up in both bodies.
        assert "203.0.113.42" in message.html_body
        assert "203.0.113.42" in message.text_body

        # Device fingerprint (device_type + browser) appears at least
        # in the text body — the design calls out "device fingerprint
        # (where available)".
        assert "mobile" in message.text_body or "Safari" in message.text_body

        # The "If this wasn't you, change your password immediately"
        # CTA copy lands in both bodies.
        cta_html = message.html_body.lower()
        cta_text = message.text_body.lower()
        assert "wasn't you" in cta_html and "password" in cta_html
        assert "wasn't you" in cta_text and "password" in cta_text

        # No attachments.
        assert message.attachments == []

    @pytest.mark.asyncio
    async def test_org_id_none_when_user_org_unknown(self):
        """When the caller passes no ``org_id`` (e.g. user lookup
        returned a user without an org), the message goes out with
        ``org_id=None`` so the bounce-blocklist pre-check uses the
        platform-wide rows.

        Validates: Requirement 8.2
        """
        from app.modules.auth.service import _send_anomalous_login_alert

        opened_session = AsyncMock()
        factory_cm = MagicMock()
        factory_cm.__aenter__ = AsyncMock(return_value=opened_session)
        factory_cm.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(return_value=factory_cm)

        send_email_stub = AsyncMock(return_value=_success_result("brevo"))

        with patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            await _send_anomalous_login_alert(
                email="user@example.com",
                user_id=uuid.uuid4(),
                anomalies=["new_device:desktop"],
                ip_address=None,
                device_type=None,
                browser=None,
                # org_id intentionally omitted — defaults to None
            )

        send_email_stub.assert_awaited_once()
        args, _ = send_email_stub.await_args
        message = args[1]
        assert message.org_id is None

    @pytest.mark.asyncio
    async def test_no_providers_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ):
        """When ``send_email`` returns ``attempts=[]``, the function
        logs a warning and returns ``None`` cleanly. A delivery error
        must never block the login flow.

        Validates: Requirement 8.2
        """
        from app.modules.auth.service import _send_anomalous_login_alert

        opened_session = AsyncMock()
        factory_cm = MagicMock()
        factory_cm.__aenter__ = AsyncMock(return_value=opened_session)
        factory_cm.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(return_value=factory_cm)

        send_email_stub = AsyncMock(return_value=_no_providers_result())

        with caplog.at_level(
            logging.WARNING, logger="app.modules.auth.service"
        ), patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            result = await _send_anomalous_login_alert(
                email="user@example.com",
                user_id=uuid.uuid4(),
                anomalies=["new_device:mobile"],
                ip_address="203.0.113.42",
                device_type="mobile",
                browser=None,
                org_id=uuid.uuid4(),
            )

        assert result is None
        send_email_stub.assert_awaited_once()


# ---------------------------------------------------------------------------
# C1 — _send_token_reuse_alert
# ---------------------------------------------------------------------------


class TestC1SendTokenReuseAlert:
    """Pin the contract for the migrated ``_send_token_reuse_alert``."""

    @pytest.mark.asyncio
    async def test_attempts_send_with_expected_message_shape(self):
        """Happy path: with one active provider, the function builds
        the right ``EmailMessage`` and dispatches via the unified
        sender exactly once.

        Pins per design row C1:

        - The unified sender is awaited exactly once.
        - ``EmailMessage.org_id is None`` — sessions are org-agnostic.
        - Recipient on the message matches the function arg.
        - The body explains "All your sessions have been invalidated"
          and includes a link to the active-sessions page.
        - The function opens its own session via
          ``async_session_factory``.
        - No attachments.

        Validates: Requirement 8.3
        """
        from app.modules.auth.service import _send_token_reuse_alert

        opened_session = AsyncMock()
        factory_cm = MagicMock()
        factory_cm.__aenter__ = AsyncMock(return_value=opened_session)
        factory_cm.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(return_value=factory_cm)

        send_email_stub = AsyncMock(return_value=_success_result("brevo"))

        with patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            await _send_token_reuse_alert("victim@example.com")

        # Function opened its own session.
        factory.assert_called_once()

        # Email was at least attempted.
        send_email_stub.assert_awaited_once()
        args, kwargs = send_email_stub.await_args

        # First positional is the freshly opened session.
        assert args[0] is opened_session

        message = args[1] if len(args) > 1 else kwargs.get("message")
        assert message is not None

        # Per design row C1: sessions are org-agnostic.
        assert message.org_id is None

        # Recipient on the message matches the function arg.
        assert message.to_email == "victim@example.com"

        # Subject is security-themed.
        assert (
            "security" in message.subject.lower()
            or "session" in message.subject.lower()
            or "token" in message.subject.lower()
        )

        # Both bodies present.
        assert message.html_body
        assert message.text_body

        # The body explains "sessions have been invalidated"
        # (paraphrased copy from the task definition).
        assert "invalidated" in message.text_body.lower()
        assert "invalidated" in message.html_body.lower()

        # Both bodies link to the active-sessions page.
        assert "/account/sessions" in message.html_body
        assert "/account/sessions" in message.text_body

        # No attachments.
        assert message.attachments == []

    @pytest.mark.asyncio
    async def test_total_failure_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ):
        """When every provider fails, the function still returns
        ``None`` cleanly. ``rotate_refresh_token`` already raises a
        ``ValueError`` to signal the reuse to its caller — a delivery
        error here must not stack on top of that.

        Validates: Requirement 8.3
        """
        from app.modules.auth.service import _send_token_reuse_alert

        opened_session = AsyncMock()
        factory_cm = MagicMock()
        factory_cm.__aenter__ = AsyncMock(return_value=opened_session)
        factory_cm.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(return_value=factory_cm)

        send_email_stub = AsyncMock(return_value=_all_soft_auth_result())

        with caplog.at_level(
            logging.WARNING, logger="app.modules.auth.service"
        ), patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            result = await _send_token_reuse_alert("victim@example.com")

        assert result is None
        send_email_stub.assert_awaited_once()
