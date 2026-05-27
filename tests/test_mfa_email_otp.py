"""Failover integration tests for the MFA email-OTP sender.

Pins the Phase 3 / task 3.11 (A11) contract for
``app.modules.auth.mfa_service._send_email_otp``:

- Failover walks the full Active_Provider_Set in priority order — the
  legacy ``.limit(1)`` (BUG-2) is gone.
- The unified sender (``app.integrations.email_sender.send_email``)
  owns the loop; this test asserts the function correctly delegates
  and surfaces the right outcome to its caller.
- ``EmailMessage.org_id`` is ``None`` (A11 row in the per-site
  variation table — MFA challenge has no org context).
- ``org_sender_name`` is **not** passed (also A11 row).
- **A11-specific deviation from A7-A10:** on total failure, the
  function MUST raise ``RuntimeError(f"MFA email send failed: ...")``
  so the MFA challenge contract is preserved (the caller cannot
  proceed without the OTP).

Tests are standalone — local helpers only, no imports from sibling
test files.

Validates: Requirements 6.1, 6.6
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import
# time. ``app.modules.auth.mfa_service`` pulls in ``User`` and a
# network of cross-module relationships — admin and inventory carry
# the relationships those rely on.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.mfa_service  # noqa: F401  # so patch(...) can resolve it
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401


# ---------------------------------------------------------------------------
# Local helpers — kept self-contained (per task brief)
# ---------------------------------------------------------------------------


def _make_provider(provider_key: str, priority: int) -> MagicMock:
    """Mock an active ``EmailProvider`` ORM row.

    Mirrors the shape the REST dispatchers
    (``_dispatch_brevo_rest`` / ``_dispatch_sendgrid_rest``) expect:
    ``credentials_set``, ``credentials_encrypted``, ``provider_key``,
    and ``config['from_email']``. The blob bytes are opaque because
    we patch ``envelope_decrypt_str`` to return canned credentials.
    """
    provider = MagicMock()
    provider.provider_key = provider_key
    provider.priority = priority
    provider.is_active = True
    provider.credentials_set = True
    provider.credentials_encrypted = b"encrypted-blob"
    provider.config = {
        "from_email": "noreply@example.com",
        "from_name": "OraInvoice",
    }
    provider.smtp_host = None
    provider.smtp_port = None
    provider.smtp_encryption = "tls"
    return provider


class _FakeResponse:
    """Drop-in replacement for ``httpx.Response`` (status_code, text,
    headers, json())."""

    def __init__(
        self,
        status_code: int,
        *,
        text: str = "",
        headers: dict | None = None,
        json_body: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._json_body = json_body

    def json(self) -> dict:
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


class _FailoverClient:
    """``httpx.AsyncClient`` stand-in: Brevo 401 → SendGrid 202.

    Drives the success-path failover scenario:

    - Brevo returns 401 (classified as ``SOFT_AUTH``, loop continues)
    - SendGrid returns 202 with ``X-Message-Id`` (success)
    """

    BREVO_URL = "https://api.brevo.com/v3/smtp/email"
    SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

    posted_urls: list[str] = []
    posted_payloads: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        self._args = args
        self._kwargs = kwargs

    async def __aenter__(self) -> "_FailoverClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).posted_urls.append(url)
        type(self).posted_payloads.append(json or {})
        if url == self.BREVO_URL:
            return _FakeResponse(
                401,
                text='{"code":"unauthorized","message":"invalid api key"}',
                headers={"content-type": "application/json"},
                json_body={
                    "code": "unauthorized",
                    "message": "invalid api key",
                },
            )
        if url == self.SENDGRID_URL:
            return _FakeResponse(
                202,
                text="",
                headers={"X-Message-Id": "msg-mfa-otp-1"},
            )
        raise AssertionError(f"unexpected URL hit by the test: {url!r}")


class _AllFail401Client(_FailoverClient):
    """Variant where every URL returns 401 (every attempt SOFT_AUTH)."""

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).posted_urls.append(url)
        type(self).posted_payloads.append(json or {})
        return _FakeResponse(
            401,
            text='{"code":"unauthorized","message":"invalid api key"}',
            headers={"content-type": "application/json"},
            json_body={
                "code": "unauthorized",
                "message": "invalid api key",
            },
        )


# ---------------------------------------------------------------------------
# A11 — _send_email_otp
# ---------------------------------------------------------------------------


class TestA11SendEmailOtpFailover:
    """End-to-end failover for ``_send_email_otp`` (task 3.11).

    With Brevo at priority 1 and SendGrid at priority 2, the function
    must walk past the Brevo 401 (``SOFT_AUTH``), succeed on SendGrid
    (202), and return ``None`` cleanly. On total failure (every
    provider 401), the function MUST raise ``RuntimeError`` so the
    MFA challenge caller can abort the flow.

    Validates: Requirements 6.1, 6.6
    """

    @pytest.mark.asyncio
    async def test_failover_to_second_provider_succeeds(self) -> None:
        """Brevo 401 → SendGrid 202 → function returns ``None``.

        Pins:

        1. The full Active_Provider_Set is loaded (no ``.limit(1)`` —
           BUG-2 fix). Both REST endpoints are hit in priority order.
        2. ``EmailMessage.org_id`` is ``None`` (A11 per-site
           variation row): the bounce-blocklist pre-check fires with
           ``org_id=None``.
        3. The function uses the caller's session directly — there is
           no call to ``async_session_factory``. The MFA challenge
           always supplies a live session.
        4. On success the function returns ``None`` without raising.
        5. The recipient on each REST payload matches the function's
           ``email`` argument; the OTP code appears in both bodies.

        Validates: Requirements 6.1, 6.6
        """
        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        caller_session = AsyncMock()

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        platform_name_stub = AsyncMock(return_value="OraInvoice")

        # Reset class-level state on the fake client so this test is
        # order-independent within the suite.
        _FailoverClient.posted_urls = []
        _FailoverClient.posted_payloads = []

        # Sentinel — A11 must NOT open its own session. The MFA
        # challenge layer always passes a live session to
        # ``_send_email_otp`` (see ``send_challenge_otp`` and
        # ``_enrol_email``).
        factory = MagicMock(side_effect=AssertionError(
            "async_session_factory must not be called by _send_email_otp"
        ))

        with patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.modules.auth.mfa_service._get_platform_name",
            new=platform_name_stub,
        ), patch(
            "app.integrations.email_sender.envelope_decrypt_str",
            return_value='{"api_key": "test-api-key"}',
        ), patch(
            "app.integrations.email_sender.httpx.AsyncClient",
            _FailoverClient,
        ):
            from app.modules.auth.mfa_service import _send_email_otp

            result = await _send_email_otp(
                caller_session,
                "user@example.com",
                "654321",
            )

        # 1. Function returns None on success — it is a fire-and-go
        #    contract from the MFA layer's perspective.
        assert result is None

        # 2. async_session_factory was NOT called — the caller's
        #    session was used directly.
        factory.assert_not_called()

        # 3. The provider chain was loaded against the caller's
        #    session and the bounce-blocklist pre-check fired exactly
        #    once.
        load_providers_stub.assert_awaited_once()
        load_providers_stub.assert_awaited_with(caller_session)
        blocklist_stub.assert_awaited_once()
        # Per design row A11: org_id=None on the EmailMessage, so the
        # blocklist pre-check is also called with org_id=None.
        _bl_args, bl_kwargs = blocklist_stub.await_args
        assert bl_kwargs.get("org_id") is None
        assert bl_kwargs.get("email_address") == "user@example.com"

        # 4. Both REST endpoints were hit in priority order — Brevo
        #    first (401, SOFT_AUTH), then SendGrid (202, success).
        #    This is the BUG-2 fix: the legacy ``.limit(1)`` would
        #    have stopped the chain at Brevo.
        assert _FailoverClient.posted_urls == [
            _FailoverClient.BREVO_URL,
            _FailoverClient.SENDGRID_URL,
        ]

        # 5. Recipient on each payload matches the function arg.
        brevo_payload = _FailoverClient.posted_payloads[0]
        sendgrid_payload = _FailoverClient.posted_payloads[1]
        assert brevo_payload["to"][0]["email"] == "user@example.com"
        assert (
            sendgrid_payload["personalizations"][0]["to"][0]["email"]
            == "user@example.com"
        )

        # 6. The OTP code appears in both bodies (HTML + text) on
        #    both providers — the email is useless without the code.
        assert "654321" in brevo_payload.get("htmlContent", "")
        assert "654321" in brevo_payload.get("textContent", "")
        sendgrid_contents = {
            c.get("type"): c.get("value", "")
            for c in sendgrid_payload.get("content", [])
        }
        assert "654321" in sendgrid_contents.get("text/html", "")
        assert "654321" in sendgrid_contents.get("text/plain", "")

        # 7. No attachments — A11 sends an OTP body only.
        assert brevo_payload.get("attachment", []) == []
        assert sendgrid_payload.get("attachments", []) == []

        # 8. No ``org_sender_name`` override (A11 row): the From
        #    header reads as the provider's configured sender, not
        #    an org-scoped name. ``OraInvoice`` is the provider's
        #    default in our fixture; the test pins that the override
        #    knob was NOT passed.
        assert brevo_payload.get("sender", {}).get("name") == "OraInvoice"
        assert sendgrid_payload.get("from", {}).get("name") == "OraInvoice"

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises_runtime_error(self) -> None:
        """Both providers 401 → ``RuntimeError("MFA email send failed: ...")``.

        Pins the A11-specific deviation from A7-A10: on total send
        failure, the function MUST raise ``RuntimeError`` so the MFA
        challenge caller (``send_challenge_otp`` /
        ``_enrol_email`` / ``request_email_change``) can surface the
        failure to the user. Best-effort silent return would leave
        the caller hanging without the OTP.

        The error message must start with ``"MFA email send failed:"``
        so callers and operators can grep for it.

        Validates: Requirements 6.1, 6.6
        """
        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        caller_session = AsyncMock()

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        platform_name_stub = AsyncMock(return_value="OraInvoice")

        _AllFail401Client.posted_urls = []
        _AllFail401Client.posted_payloads = []

        with patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender._maybe_fire_all_auth_fail_alert",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.auth.mfa_service._get_platform_name",
            new=platform_name_stub,
        ), patch(
            "app.integrations.email_sender.envelope_decrypt_str",
            return_value='{"api_key": "test-api-key"}',
        ), patch(
            "app.integrations.email_sender.httpx.AsyncClient",
            _AllFail401Client,
        ):
            from app.modules.auth.mfa_service import _send_email_otp

            with pytest.raises(RuntimeError) as exc_info:
                await _send_email_otp(
                    caller_session,
                    "user@example.com",
                    "111222",
                )

        # 1. The error message follows the contract:
        #    ``"MFA email send failed: <inner-error>"``. The inner
        #    error comes from the unified sender's last-attempt
        #    error string. We pin the prefix so callers and grep
        #    rules don't break on inner-error wording shifts.
        assert str(exc_info.value).startswith("MFA email send failed:")

        # 2. Both REST endpoints WERE attempted before the raise —
        #    the loop walked the full Active_Provider_Set despite
        #    each one failing with SOFT_AUTH. (BUG-2 fix verified
        #    on the failure path too — legacy ``.limit(1)`` would
        #    have stopped at Brevo.)
        assert _AllFail401Client.posted_urls == [
            _AllFail401Client.BREVO_URL,
            _AllFail401Client.SENDGRID_URL,
        ]

        # 3. Provider chain was loaded once and the bounce-blocklist
        #    pre-check fired once with the right shape.
        load_providers_stub.assert_awaited_once()
        blocklist_stub.assert_awaited_once()
        _bl_args, bl_kwargs = blocklist_stub.await_args
        assert bl_kwargs.get("org_id") is None
        assert bl_kwargs.get("email_address") == "user@example.com"
