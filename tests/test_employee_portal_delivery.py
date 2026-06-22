"""Tests for ``app/modules/employee_portal/employee_portal_delivery.py`` (R15).

Covers the two never-raising senders (``send_credential_setup_email`` and
``send_password_reset_email``) and their pure composition helpers:

- Example unit tests for the gate (missing email → ``portal_email_required``,
  no dispatch), the success path, and the provider-exhaustion path
  (``send_failed``, never raises) — R15.1/R15.3/R15.5/R15.6.
- Property tests over the pure composition helpers asserting the message
  always names the organisation, carries the link + expiry copy, and **never**
  contains a raw password (R15.4) across many generated inputs.

``send_email`` is patched at the module boundary so no network/DB is touched.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.integrations.email_sender import EmailMessage, SendResult
from app.modules.employee_portal import employee_portal_delivery as epd
from app.modules.employee_portal.employee_portal_delivery import (
    ERROR_NO_EMAIL,
    ERROR_SEND_FAILED,
    EmployeePortalDeliveryResult,
    compose_credential_setup_email,
    compose_password_reset_email,
    send_credential_setup_email,
    send_password_reset_email,
)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Org names: non-empty visible text (no leading/trailing whitespace surprises).
_org_names = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=0x2FFF),
    min_size=1,
    max_size=60,
).filter(lambda s: s.strip() != "")

# A URL token (the branded /e/{slug}/accept-invite/{token} or reset link).
_urls = st.from_regex(
    r"https://[a-z0-9-]{3,20}\.example\.com/e/[a-z0-9-]{3,20}/(accept-invite|reset)/[a-z0-9]{8,40}",
    fullmatch=True,
)

# A raw password we assert NEVER appears in any composed email (R15.4).
_passwords = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=8,
    max_size=128,
)


# ===========================================================================
# Property: composition never leaks a raw password and carries required parts
# ===========================================================================


@settings(max_examples=200, deadline=None)
@given(org_name=_org_names, url=_urls, password=_passwords, expiry=st.sampled_from(
    ["7 days", "60 minutes", "24 hours", "1 hour"]
))
def test_credential_email_never_contains_password_and_has_required_parts(
    org_name: str, url: str, password: str, expiry: str
):
    """The credential-setup email names the org, carries the link + expiry,
    and never embeds the raw password (R15.1, R15.4).

    **Validates: Requirements 15.1, 15.4**
    """
    # The email legitimately contains the org name + link; a generated
    # "password" that coincides with that text is a generator collision, not
    # a leak (compose takes no password argument). Exclude those cases.
    assume(password not in url and password not in org_name)
    msg = compose_credential_setup_email(
        staff_email="employee@example.com",
        org_name=org_name,
        set_password_url=url,
        expiry_hint=expiry,
    )
    assert isinstance(msg, EmailMessage)
    # Org name present in subject + body.
    assert org_name in msg.subject
    assert org_name in msg.text_body
    # Link present in both plaintext and HTML.
    assert url in msg.text_body
    assert url in msg.html_body
    # Expiry copy present.
    assert expiry in msg.text_body
    # The raw password is NEVER present anywhere in the message (R15.4).
    assert password not in msg.text_body
    assert password not in msg.html_body
    assert password not in msg.subject


@settings(max_examples=200, deadline=None)
@given(org_name=_org_names, url=_urls, password=_passwords, expiry=st.sampled_from(
    ["60 minutes", "1 hour", "30 minutes"]
))
def test_reset_email_never_contains_password_and_has_required_parts(
    org_name: str, url: str, password: str, expiry: str
):
    """The password-reset email names the org, carries the link + expiry, and
    never embeds the raw password (R15.5, R15.4).

    **Validates: Requirements 15.4, 15.5**
    """
    assume(password not in url and password not in org_name)
    msg = compose_password_reset_email(
        staff_email="employee@example.com",
        org_name=org_name,
        reset_url=url,
        expiry_hint=expiry,
    )
    assert org_name in msg.subject
    assert org_name in msg.text_body
    assert url in msg.text_body
    assert url in msg.html_body
    assert expiry in msg.text_body
    assert password not in msg.text_body
    assert password not in msg.html_body


# ===========================================================================
# Example unit tests — gate, success, failure (never raises)
# ===========================================================================


def _ok_result() -> SendResult:
    return SendResult(success=True, message_id="msg-abc-123")


def _fail_result() -> SendResult:
    return SendResult(success=False, error="all providers failed", attempts=[])


def test_credential_setup_defaults_to_seven_day_expiry():
    """Default expiry copy for credential setup is '7 days' (R15.1)."""
    msg = compose_credential_setup_email(
        staff_email="e@example.com",
        org_name="Kauri Auto",
        set_password_url="https://kauri.example.com/e/kauri/accept-invite/tok123",
    )
    assert "7 days" in msg.text_body
    assert "Set your password" in msg.html_body


def test_reset_defaults_to_sixty_minute_expiry():
    """Default expiry copy for password reset is '60 minutes' (R15.5)."""
    msg = compose_password_reset_email(
        staff_email="e@example.com",
        org_name="Kauri Auto",
        reset_url="https://kauri.example.com/e/kauri/reset/tok123",
    )
    assert "60 minutes" in msg.text_body
    assert "Reset your password" in msg.html_body


def test_credential_setup_missing_email_rejected_without_dispatch():
    """A blank/None staff email is rejected up front and dispatches nothing
    (R15.6)."""
    fake_send = AsyncMock(return_value=_ok_result())
    with patch.object(epd, "send_email", fake_send):
        for bad in (None, "", "   "):
            result = asyncio.run(
                send_credential_setup_email(
                    object(),
                    staff_email=bad,  # type: ignore[arg-type]
                    org_name="Kauri Auto",
                    set_password_url="https://x.example.com/e/k/accept-invite/t",
                )
            )
            assert result.ok is False
            assert result.success is False
            assert result.error_code == ERROR_NO_EMAIL
    assert fake_send.await_count == 0


def test_credential_setup_success_returns_message_id():
    """A provider acceptance yields ok=True with the provider message id."""
    fake_send = AsyncMock(return_value=_ok_result())
    with patch.object(epd, "send_email", fake_send):
        result = asyncio.run(
            send_credential_setup_email(
                object(),
                staff_email="employee@example.com",
                org_name="Kauri Auto",
                set_password_url="https://x.example.com/e/k/accept-invite/t",
                org_id=uuid.uuid4(),
            )
        )
    assert result.ok is True
    assert result.message_id == "msg-abc-123"
    assert fake_send.await_count == 1


def test_credential_setup_provider_failure_returns_send_failed_never_raises():
    """When every provider fails, the helper returns send_failed and does NOT
    raise (R15.3)."""
    fake_send = AsyncMock(return_value=_fail_result())
    with patch.object(epd, "send_email", fake_send):
        result = asyncio.run(
            send_credential_setup_email(
                object(),
                staff_email="employee@example.com",
                org_name="Kauri Auto",
                set_password_url="https://x.example.com/e/k/accept-invite/t",
            )
        )
    assert result.ok is False
    assert result.error_code == ERROR_SEND_FAILED


def test_reset_missing_email_rejected_without_dispatch():
    """A blank reset destination is rejected up front (R15.6)."""
    fake_send = AsyncMock(return_value=_ok_result())
    with patch.object(epd, "send_email", fake_send):
        result = asyncio.run(
            send_password_reset_email(
                object(),
                staff_email="   ",
                org_name="Kauri Auto",
                reset_url="https://x.example.com/e/k/reset/t",
            )
        )
    assert result.ok is False
    assert result.error_code == ERROR_NO_EMAIL
    assert fake_send.await_count == 0


def test_reset_success_and_failure_paths():
    """Reset helper returns ok on acceptance and send_failed (never raises) on
    exhaustion (R15.3, R15.5)."""
    with patch.object(epd, "send_email", AsyncMock(return_value=_ok_result())):
        ok = asyncio.run(
            send_password_reset_email(
                object(),
                staff_email="employee@example.com",
                org_name="Kauri Auto",
                reset_url="https://x.example.com/e/k/reset/t",
            )
        )
    assert ok.ok is True and ok.message_id == "msg-abc-123"

    with patch.object(epd, "send_email", AsyncMock(return_value=_fail_result())):
        failed = asyncio.run(
            send_password_reset_email(
                object(),
                staff_email="employee@example.com",
                org_name="Kauri Auto",
                reset_url="https://x.example.com/e/k/reset/t",
            )
        )
    assert failed.ok is False
    assert failed.error_code == ERROR_SEND_FAILED


def test_result_success_alias_matches_ok():
    """``EmployeePortalDeliveryResult.success`` is an alias of ``ok``."""
    assert EmployeePortalDeliveryResult(ok=True).success is True
    assert EmployeePortalDeliveryResult(ok=False).success is False
