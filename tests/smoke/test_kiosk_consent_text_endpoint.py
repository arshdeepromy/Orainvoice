"""Smoke test for ``GET /kiosk/consent-text`` (C1).

Feature: customer-reminder-consent

Asserts the endpoint returns ``{text, version}`` with the ``{workshop_name}``
placeholder substituted server-side from the org name, gated by the kiosk
role + rate-limit pattern (verified structurally — the handler is called
directly with a mocked org context).
"""

from __future__ import annotations

import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Configure ORM mappers (imports pull in related models).
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.modules.customers.consent_text import KIOSK_CONSENT_TEXT_VERSION


@pytest.mark.asyncio
async def test_consent_text_returns_text_and_version_with_workshop_name():
    from app.modules.kiosk.router import consent_text

    org_id = uuid.uuid4()
    request = MagicMock()
    request.state = types.SimpleNamespace(
        org_id=str(org_id), user_id=str(uuid.uuid4()), client_ip="203.0.113.9"
    )
    db = AsyncMock()

    with patch(
        "app.modules.kiosk.router.get_org_settings",
        AsyncMock(return_value={"org_name": "Acme Motors"}),
    ):
        result = await consent_text(request, db)

    assert set(result.keys()) == {"text", "version"}
    assert result["version"] == KIOSK_CONSENT_TEXT_VERSION
    # Placeholder substituted server-side with the org name; never leaked.
    assert "Acme Motors" in result["text"]
    assert "{workshop_name}" not in result["text"]


@pytest.mark.asyncio
async def test_consent_text_requires_org_context():
    from app.modules.kiosk.router import consent_text

    request = MagicMock()
    request.state = types.SimpleNamespace(
        org_id=None, user_id=None, client_ip="203.0.113.9"
    )
    db = AsyncMock()

    result = await consent_text(request, db)
    # Returns a 403 JSONResponse when org context is missing.
    assert getattr(result, "status_code", None) == 403
