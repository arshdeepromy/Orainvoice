"""Per-provider webhook secret iteration.

Phase 8c task 9.14 of the email-provider-unification spec. Verifies
the contract pinned by Requirement 13:

- The Brevo webhook handler iterates each active Brevo provider's
  ``brevo_webhook_secret`` from ``email_providers.config`` in priority
  order, accepting on the first match.
- An env-var fallback (``app_settings.brevo_webhook_secret``) is tried
  last; matching it logs a deprecation warning but still admits the
  payload — the env path stays alive for one release per Req 25.5.
- A signature that matches none of the candidates returns HTTP 403
  and writes nothing to the database.

Validates: Requirements 13.1, 13.2, 13.3, 13.4, 25.5
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.core.webhook_security import sign_webhook_payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _provider_row(
    *,
    provider_key: str = "brevo",
    priority: int = 1,
    config: dict | None = None,
):
    """Build a minimal active EmailProvider mock with only the fields
    ``_candidate_provider_secrets`` reads."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        provider_key=provider_key,
        priority=priority,
        is_active=True,
        config=config or {},
    )


def _execute_returning_scalars(rows):
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _fake_request(body: bytes, headers: dict):
    r = AsyncMock()
    r.body = AsyncMock(return_value=body)
    r.json = AsyncMock(return_value=json.loads(body))
    r.headers = headers
    r.state = MagicMock()
    r.client = MagicMock()
    r.client.host = "127.0.0.1"
    return r


# ---------------------------------------------------------------------------
# Tests of the candidate-secret iterator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidate_secrets_returns_active_providers_then_env() -> None:
    """The candidate list is providers in priority order, then env.

    Each provider's ``config[<config_key>]`` is included; providers
    with no secret configured are skipped. The env-var fallback always
    appears last when present.

    Validates: Requirements 13.1, 13.3, 25.5
    """
    from app.modules.notifications.router import _candidate_provider_secrets

    p1 = _provider_row(priority=1, config={"brevo_webhook_secret": "secret-A"})
    p2 = _provider_row(priority=2, config={"brevo_webhook_secret": "secret-B"})
    # No secret configured — must be skipped.
    p3 = _provider_row(priority=3, config={})

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_execute_returning_scalars([p1, p2, p3])
    )

    candidates = await _candidate_provider_secrets(
        db,
        provider_kind="brevo",
        config_key="brevo_webhook_secret",
        env_fallback="env-fallback-secret",
    )

    secrets = [s for s, _ in candidates]
    keys = [k for _, k in candidates]
    # Priority-ordered, env-fallback last.
    assert secrets == ["secret-A", "secret-B", "env-fallback-secret"]
    # Env-fallback's provider_key is None — used by the deprecation
    # log to detect "still on the env-var path".
    assert keys == ["brevo", "brevo", None]


@pytest.mark.asyncio
async def test_candidate_secrets_omits_env_when_unset() -> None:
    """When ``env_fallback`` is empty / None, the candidate list ends
    at the providers — there is no synthetic env entry.

    Validates: Requirement 13.4 (no fallback ⇒ reject)
    """
    from app.modules.notifications.router import _candidate_provider_secrets

    p1 = _provider_row(priority=1, config={"brevo_webhook_secret": "only-A"})
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_execute_returning_scalars([p1]))

    candidates = await _candidate_provider_secrets(
        db,
        provider_kind="brevo",
        config_key="brevo_webhook_secret",
        env_fallback=None,
    )
    assert candidates == [("only-A", "brevo")]


# ---------------------------------------------------------------------------
# Tests of the verifier helper
# ---------------------------------------------------------------------------


def test_verify_with_any_secret_first_match_wins() -> None:
    """The verifier tries each candidate and returns the first match.

    Validates: Requirement 13.3
    """
    from app.modules.notifications.router import _verify_with_any_secret

    body = b'{"event":"hard_bounce"}'
    sig_b = sign_webhook_payload(body, "B")
    matched, key = _verify_with_any_secret(
        payload=body,
        signature=sig_b,
        candidates=[("A", "brevo-1"), ("B", "brevo-2"), ("C", "brevo-3")],
    )
    assert matched is True
    assert key == "brevo-2"


def test_verify_with_any_secret_no_match() -> None:
    """No candidate matches → ``(False, None)``.

    Validates: Requirement 13.4
    """
    from app.modules.notifications.router import _verify_with_any_secret

    matched, key = _verify_with_any_secret(
        payload=b"x",
        signature="bad",
        candidates=[("A", "brevo-1"), ("B", "brevo-2")],
    )
    assert matched is False
    assert key is None


def test_verify_with_any_secret_empty_signature() -> None:
    """An empty signature short-circuits to ``(False, None)`` — the
    handler must never accept an unsigned payload.

    Validates: Requirement 13.4
    """
    from app.modules.notifications.router import _verify_with_any_secret

    matched, key = _verify_with_any_secret(
        payload=b"x",
        signature="",
        candidates=[("A", "brevo-1")],
    )
    assert matched is False
    assert key is None


# ---------------------------------------------------------------------------
# Endpoint integration: signature signed with provider 2's secret
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brevo_webhook_accepts_secondary_provider_secret() -> None:
    """A webhook signed with provider 2's secret is accepted; provider
    1's mismatch is silent and provider 2's match wins.

    Validates: Requirement 13.3
    """
    from app.modules.notifications.router import brevo_bounce_webhook

    p1 = _provider_row(priority=1, config={"brevo_webhook_secret": "secret-A"})
    p2 = _provider_row(priority=2, config={"brevo_webhook_secret": "secret-B"})

    body = json.dumps(
        {"event": "hard_bounce", "email": "bad@example.com"}
    ).encode()
    sig = sign_webhook_payload(body, "secret-B")

    db = AsyncMock()
    db.flush = AsyncMock()
    # Only the provider-secret lookup runs before signature
    # verification; flag_bounce is patched, so no further DB calls.
    db.execute = AsyncMock(
        return_value=_execute_returning_scalars([p1, p2])
    )

    with patch(
        "app.modules.notifications.router.app_settings"
    ) as ms, patch(
        "app.modules.notifications.router.flag_bounce", new=AsyncMock()
    ) as flag_mock:
        ms.brevo_webhook_secret = ""  # env fallback unset → only providers
        resp = await brevo_bounce_webhook(
            request=_fake_request(body, {"X-Brevo-Signature": sig}),
            db=db,
        )

    assert resp.status_code == 200
    flag_mock.assert_awaited_once()
    # Only one execute call (the candidate-secret lookup) — flag_bounce
    # is mocked so no further DB activity.
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_brevo_webhook_rejects_when_no_secret_matches() -> None:
    """Signature signed with an unknown secret → 403, no DB writes.

    Validates: Requirement 13.4
    """
    from app.modules.notifications.router import brevo_bounce_webhook

    p1 = _provider_row(priority=1, config={"brevo_webhook_secret": "secret-A"})

    body = json.dumps(
        {"event": "hard_bounce", "email": "bad@example.com"}
    ).encode()
    sig = sign_webhook_payload(body, "totally-different-secret")

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_execute_returning_scalars([p1]))

    with patch("app.modules.notifications.router.app_settings") as ms, patch(
        "app.modules.notifications.router.flag_bounce", new=AsyncMock()
    ) as flag_mock:
        ms.brevo_webhook_secret = ""
        resp = await brevo_bounce_webhook(
            request=_fake_request(body, {"X-Brevo-Signature": sig}),
            db=db,
        )

    assert resp.status_code == 403
    # No DB writes beyond the candidate-secret lookup.
    flag_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_brevo_webhook_accepts_env_var_fallback_one_release() -> None:
    """When no provider secrets match but the env-var matches, the
    handler still admits the payload — the env path is alive for one
    release per Req 25.5.

    Validates: Requirement 25.5
    """
    from app.modules.notifications.router import brevo_bounce_webhook

    body = json.dumps(
        {"event": "hard_bounce", "email": "bad@example.com"}
    ).encode()
    sig = sign_webhook_payload(body, "env-secret")

    db = AsyncMock()
    db.flush = AsyncMock()
    # No active providers configured → only the env fallback in the
    # candidate list.
    db.execute = AsyncMock(return_value=_execute_returning_scalars([]))

    with patch("app.modules.notifications.router.app_settings") as ms, patch(
        "app.modules.notifications.router.flag_bounce", new=AsyncMock()
    ) as flag_mock:
        ms.brevo_webhook_secret = "env-secret"
        resp = await brevo_bounce_webhook(
            request=_fake_request(body, {"X-Brevo-Signature": sig}),
            db=db,
        )

    assert resp.status_code == 200
    flag_mock.assert_awaited_once()
