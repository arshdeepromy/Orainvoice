"""Unit tests for legacy email integration shims.

Phase 7 of the email-provider-unification spec retired the legacy admin
``PUT/POST /api/v1/admin/integrations/smtp`` endpoints (replaced by HTTP
410 Gone stubs) and removed ``save_smtp_config`` / ``send_test_email``
from ``app/modules/admin/service.py``. Those service-layer tests have
been deleted from this file. The remaining tests cover the deprecated
``brevo.py`` shims (``SmtpConfig`` dataclass, ``send_org_email`` shim
delegating to the unified sender) and the still-live
``SmtpConfigRequest`` / ``SmtpConfigResponse`` Pydantic schemas. Phase 9
deletes these shims and schemas wholesale, at which point this file can
go too.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401

from app.integrations.brevo import (
    SendResult,
    SmtpConfig,
    send_org_email,
)
from app.modules.admin.schemas import (
    SmtpConfigRequest,
    SmtpConfigResponse,
    SmtpTestEmailResponse,
)


# ---------------------------------------------------------------------------
# SmtpConfig tests (legacy dataclass — still re-exported by brevo.py shim)
# ---------------------------------------------------------------------------


class TestSmtpConfig:
    def test_from_dict_defaults(self):
        config = SmtpConfig.from_dict({})
        assert config.provider == "smtp"
        assert config.port == 587
        assert config.api_key == ""
        assert config.from_email == ""

    def test_from_dict_full(self):
        data = {
            "provider": "brevo",
            "api_key": "xkeysib-abc123",
            "host": "",
            "port": 587,
            "domain": "workshoppro.nz",
            "from_email": "noreply@workshoppro.nz",
            "from_name": "WorkshopPro NZ",
            "reply_to": "support@workshoppro.nz",
        }
        config = SmtpConfig.from_dict(data)
        assert config.provider == "brevo"
        assert config.api_key == "xkeysib-abc123"
        assert config.domain == "workshoppro.nz"
        assert config.from_name == "WorkshopPro NZ"

    def test_to_dict_roundtrip(self):
        original = {
            "provider": "sendgrid",
            "api_key": "SG.test",
            "host": "",
            "port": 587,
            "username": "",
            "password": "",
            "domain": "example.com",
            "from_email": "no-reply@example.com",
            "from_name": "Test",
            "reply_to": "reply@example.com",
        }
        config = SmtpConfig.from_dict(original)
        result = config.to_dict()
        assert result == original


# ---------------------------------------------------------------------------
# send_org_email shim test (delegates to the unified sender)
# ---------------------------------------------------------------------------


class TestSendOrgEmail:
    @pytest.mark.asyncio
    async def test_org_overrides_forwarded_to_unified_sender(self):
        """Org sender name and reply-to are forwarded to ``send_email``.

        Phase 2 turned ``send_org_email`` into a thin shim over
        ``app.integrations.email_sender.send_email``. This test asserts
        the override args still travel through cleanly so existing
        callers keep their org-branded From / Reply-To headers.
        """
        with patch("app.integrations.brevo.send_email", new_callable=AsyncMock) as send_mock:
            send_mock.return_value = SendResult(
                success=True, provider_key="brevo", transport="rest_api"
            )
            result = await send_org_email(
                AsyncMock(),
                to_email="customer@example.com",
                subject="Invoice",
                html_body="<p>Invoice</p>",
                org_sender_name="Acme Workshop",
                org_reply_to="acme@workshop.nz",
            )

        assert result.success is True
        send_mock.assert_awaited_once()
        kwargs = send_mock.await_args.kwargs
        assert kwargs["org_sender_name"] == "Acme Workshop"
        assert kwargs["org_reply_to"] == "acme@workshop.nz"


# ---------------------------------------------------------------------------
# Schema validation tests (still live — schemas back the 410-Gone stubs'
# OpenAPI surface and are referenced by the email-providers-page rewrite
# until Phase 9 deletes them)
# ---------------------------------------------------------------------------


class TestSmtpSchemas:
    def test_request_requires_domain(self):
        with pytest.raises(Exception):
            SmtpConfigRequest(
                from_email="noreply@test.com",
                from_name="Test",
                domain="",  # min_length=1
            )

    def test_request_requires_from_email(self):
        with pytest.raises(Exception):
            SmtpConfigRequest(
                domain="test.com",
                from_email="",  # min_length=1
                from_name="Test",
            )

    def test_request_requires_from_name(self):
        with pytest.raises(Exception):
            SmtpConfigRequest(
                domain="test.com",
                from_email="noreply@test.com",
                from_name="",  # min_length=1
            )

    def test_valid_request(self):
        req = SmtpConfigRequest(
            provider="brevo",
            api_key="xkeysib-test",
            domain="workshoppro.nz",
            from_email="noreply@workshoppro.nz",
            from_name="WorkshopPro NZ",
            reply_to="support@workshoppro.nz",
        )
        assert req.provider == "brevo"
        assert req.domain == "workshoppro.nz"

    def test_request_defaults(self):
        req = SmtpConfigRequest(
            domain="test.com",
            from_email="noreply@test.com",
            from_name="Test",
        )
        assert req.provider == "smtp"
        assert req.port == 587
        assert req.api_key == ""
        assert req.reply_to == ""

    def test_response_schema(self):
        resp = SmtpConfigResponse(
            message="Saved",
            provider="brevo",
            domain="test.com",
            from_email="noreply@test.com",
            from_name="Test",
            reply_to="reply@test.com",
            is_verified=False,
        )
        assert resp.is_verified is False

    def test_test_email_response_schema(self):
        resp = SmtpTestEmailResponse(
            success=True,
            message="Test email sent",
            provider="brevo",
        )
        assert resp.success is True
        assert resp.error is None
