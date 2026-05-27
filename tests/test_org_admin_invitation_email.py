"""Unit tests for ``_send_org_admin_invitation_email`` (Phase 4 task 4.4 — C4).

Phase 4 task 4.4 of the email-provider-unification spec replaces the
legacy ``logger.info("...queued...")`` stub at
``app/modules/admin/service.py:347`` with a real dispatch through
:func:`app.tasks.notifications.send_email_task`. ``send_email_task``
itself was rewritten in Phase 2 to delegate to the unified sender, so
the C4 site automatically inherits provider failover, error
classification, and time budgets — there is no per-site failover loop
to test here.

Per design row C4 in
``.kiro/specs/email-provider-unification/design.md``:

  - The function dispatches via ``send_email_task`` (not direct
    ``send_email``).
  - ``template_type="org_admin_invitation"``.
  - ``org_id`` is the freshly provisioned organisation id.
  - ``org_sender_name="OraInvoice"`` because the recipient is being
    invited to administer a brand-new org and isn't a customer of that
    org yet — the From name should read OraInvoice.
  - The signup link points at the ``/verify-email?token=…`` route, the
    same one ``_send_invitation_email`` (A8) uses, so the acceptance
    flow is identical.
  - The body explains that the invitation expires in 7 days.
  - ``log_email_sent`` records a ``queued`` row before dispatch so
    ``send_email_task`` can flip it to ``sent``/``failed`` on
    completion.

These tests assert the email is at least attempted with the expected
shape — i.e. ``send_email_task`` is awaited exactly once with the
right kwargs and ``log_email_sent`` is awaited exactly once with the
right template type. The unified sender's failover loop is exercised
end-to-end by Phase 1 ``tests/test_email_sender_*.py`` and Phase 2
``tests/test_send_email_task_integration.py``, so we don't repeat that
here.

Validates: Requirements 8.4, 8.5
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

# Import models so SQLAlchemy can resolve relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_entry(log_id: uuid.UUID) -> dict:
    """Canned ``log_email_sent`` return value (dict shape)."""
    return {
        "id": log_id,
        "org_id": uuid.uuid4(),
        "channel": "email",
        "recipient": "admin@workshop.co.nz",
        "template_type": "org_admin_invitation",
        "subject": "queued",
        "status": "queued",
        "error_message": None,
        "sent_at": None,
        "provider_key": None,
        "provider_message_id": None,
        "bounced_at": None,
        "bounce_reason": None,
        "delivered_at": None,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSendOrgAdminInvitationEmail:
    """Pin the contract for the Phase 4 ``_send_org_admin_invitation_email``."""

    @pytest.mark.asyncio
    async def test_dispatches_via_send_email_task_with_expected_kwargs(self):
        """Happy path: the function logs a queued ``notification_log``
        row and awaits ``send_email_task`` exactly once with the right
        kwargs.

        Pins per design row C4:

        - ``template_type="org_admin_invitation"`` on both the log row
          and the dispatch call.
        - ``org_id`` is the caller-supplied org id, threaded through to
          both ``log_email_sent`` and ``send_email_task`` as a string.
        - ``org_sender_name="OraInvoice"`` (platform-branded — see
          docstring).
        - ``to_email`` is the function arg.
        - The subject mentions the org name and the platform.
        - Both bodies contain the secure signup link with the token.
        - Both bodies contain the org name.
        - Both bodies state the 7-day expiry.

        Validates: Requirement 8.4
        """
        from app.modules.admin.service import _send_org_admin_invitation_email

        db = AsyncMock()
        org_id = uuid.uuid4()
        log_id = uuid.uuid4()
        token = "secure-token-abc123def456"
        email = "admin@workshop.co.nz"
        org_name = "Test Workshop"

        log_email_stub = AsyncMock(return_value=_log_entry(log_id))
        send_task_stub = AsyncMock(
            return_value={
                "success": True,
                "message_id": "<msg-1@example>",
                "provider": "brevo",
            }
        )

        with patch(
            "app.modules.notifications.service.log_email_sent",
            new=log_email_stub,
        ), patch(
            "app.tasks.notifications.send_email_task",
            new=send_task_stub,
        ):
            await _send_org_admin_invitation_email(
                email,
                token,
                org_name,
                db=db,
                org_id=org_id,
                base_url="https://app.example.com",
            )

        # 1. Notification log row is queued before dispatch.
        log_email_stub.assert_awaited_once()
        log_args, log_kwargs = log_email_stub.await_args
        assert log_args[0] is db
        assert log_kwargs["org_id"] == org_id
        assert log_kwargs["recipient"] == email
        assert log_kwargs["template_type"] == "org_admin_invitation"
        assert log_kwargs["status"] == "queued"
        assert org_name in log_kwargs["subject"]

        # 2. Email is dispatched exactly once via send_email_task.
        send_task_stub.assert_awaited_once()
        _, send_kwargs = send_task_stub.await_args

        # 3. Dispatch carries the right routing metadata.
        assert send_kwargs["org_id"] == str(org_id)
        assert send_kwargs["log_id"] == str(log_id)
        assert send_kwargs["to_email"] == email
        assert send_kwargs["template_type"] == "org_admin_invitation"
        assert send_kwargs["org_sender_name"] == "OraInvoice"

        # 4. Subject is the platform-branded invitation copy.
        assert org_name in send_kwargs["subject"]
        assert "OraInvoice" in send_kwargs["subject"]

        # 5. Both bodies contain the secure signup link with the token.
        expected_url = f"https://app.example.com/verify-email?token={token}"
        assert expected_url in send_kwargs["html_body"]
        assert expected_url in send_kwargs["text_body"]

        # 6. Both bodies reference the org name so the recipient knows
        # which org they're being invited to administer.
        assert org_name in send_kwargs["html_body"]
        assert org_name in send_kwargs["text_body"]

        # 7. Both bodies state the 7-day expiry policy explicitly.
        assert "7 days" in send_kwargs["html_body"]
        assert "7 days" in send_kwargs["text_body"]

    @pytest.mark.asyncio
    async def test_uses_settings_frontend_base_url_when_not_provided(self):
        """When the caller doesn't pass ``base_url``, the function
        falls back to ``settings.frontend_base_url`` so the link
        works in every environment.

        Validates: Requirement 8.4
        """
        from app.modules.admin.service import _send_org_admin_invitation_email

        db = AsyncMock()
        org_id = uuid.uuid4()
        log_id = uuid.uuid4()
        token = "fallback-token-xyz"

        log_email_stub = AsyncMock(return_value=_log_entry(log_id))
        send_task_stub = AsyncMock(return_value={"success": True})

        with patch(
            "app.modules.notifications.service.log_email_sent",
            new=log_email_stub,
        ), patch(
            "app.tasks.notifications.send_email_task",
            new=send_task_stub,
        ), patch(
            "app.modules.admin.service.settings"
        ) as mock_settings:
            mock_settings.frontend_base_url = "https://prod.example.com"

            await _send_org_admin_invitation_email(
                "admin@example.com",
                token,
                "Acme Co",
                db=db,
                org_id=org_id,
            )

        send_task_stub.assert_awaited_once()
        _, send_kwargs = send_task_stub.await_args
        expected_url = f"https://prod.example.com/verify-email?token={token}"
        assert expected_url in send_kwargs["html_body"]
        assert expected_url in send_kwargs["text_body"]

    @pytest.mark.asyncio
    async def test_strips_trailing_slash_from_base_url(self):
        """Caller-provided ``base_url`` with a trailing slash must not
        produce a double-slash in the signup link.

        Validates: Requirement 8.4
        """
        from app.modules.admin.service import _send_org_admin_invitation_email

        db = AsyncMock()
        org_id = uuid.uuid4()
        log_id = uuid.uuid4()
        token = "trail-slash-token"

        log_email_stub = AsyncMock(return_value=_log_entry(log_id))
        send_task_stub = AsyncMock(return_value={"success": True})

        with patch(
            "app.modules.notifications.service.log_email_sent",
            new=log_email_stub,
        ), patch(
            "app.tasks.notifications.send_email_task",
            new=send_task_stub,
        ):
            await _send_org_admin_invitation_email(
                "admin@example.com",
                token,
                "Acme Co",
                db=db,
                org_id=org_id,
                base_url="https://app.example.com/",
            )

        send_task_stub.assert_awaited_once()
        _, send_kwargs = send_task_stub.await_args
        assert "https://app.example.com//verify-email" not in send_kwargs["html_body"]
        assert "https://app.example.com//verify-email" not in send_kwargs["text_body"]
        expected_url = f"https://app.example.com/verify-email?token={token}"
        assert expected_url in send_kwargs["html_body"]
        assert expected_url in send_kwargs["text_body"]
