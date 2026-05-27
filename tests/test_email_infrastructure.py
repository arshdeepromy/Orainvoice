"""Unit tests for the still-live admin SMTP Pydantic schemas.

Phase 7 of the email-provider-unification spec retired the legacy admin
``PUT/POST /api/v1/admin/integrations/smtp`` endpoints (replaced by HTTP
410 Gone stubs) and removed ``save_smtp_config`` / ``send_test_email``
from ``app/modules/admin/service.py``. Phase 9 (task 10.2) then removed
the ``send_org_email`` / ``EmailClient`` / ``SmtpConfig`` shims that
used to live in ``app/integrations/brevo.py`` — those tests have been
deleted. The unified email path is exercised by
``tests/test_email_sender_*.py``,
``tests/test_send_email_task_integration.py`` and
``tests/test_email_provider_*.py``.

What's left here: validation tests for the still-live
``SmtpConfigRequest`` / ``SmtpConfigResponse`` / ``SmtpTestEmailResponse``
Pydantic schemas in ``app.modules.admin.schemas``. Those schemas are
still referenced by the 410-Gone endpoint stubs' OpenAPI surface and by
the email-providers admin page until they are removed in a follow-up.
"""

from __future__ import annotations

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401

from app.modules.admin.schemas import (
    SmtpConfigRequest,
    SmtpConfigResponse,
    SmtpTestEmailResponse,
)


# ---------------------------------------------------------------------------
# Schema validation tests (still live — schemas back the 410-Gone stubs'
# OpenAPI surface and are referenced by the email-providers-page rewrite
# until a follow-up cleanup deletes them)
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
