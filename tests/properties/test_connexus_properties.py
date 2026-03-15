"""Property-based tests for ConnexusConfig and ConnexusSmsClient.

Properties covered:
  P1 — ConnexusConfig serialization round-trip
  P2 — Send payload construction
  P3 — API failures return structured error results
  P4 — Successful send includes parts metadata
  P5 — Token caching and Authorization header
  P6 — API calls never trigger token refresh (background refresher's job)

**Validates: Requirements 1.1, 1.4, 1.6, 1.7, 1.9, 2.2, 2.3, 2.6, 11.3, 12.3**
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from hypothesis import given, assume
from hypothesis import strategies as st

from hypothesis import settings as h_settings, HealthCheck

PBT_SETTINGS = h_settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

from app.integrations.connexus_sms import ConnexusConfig, ConnexusSmsClient, _token_cache
from app.integrations.sms_types import SmsMessage, SmsSendResult


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

non_empty_text_st = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip())

api_base_url_st = st.from_regex(
    r"https://[a-z]{3,12}\.[a-z]{2,6}/api/[a-z]+",
    fullmatch=True,
)

phone_number_st = st.from_regex(r"\+\d{7,15}", fullmatch=True)

sms_body_st = st.text(min_size=1, max_size=500).filter(lambda s: s.strip())

parts_count_st = st.integers(min_value=1, max_value=20)

http_error_code_st = st.sampled_from([400, 403, 404, 422, 429, 500, 502, 503])


def _make_client(
    client_id: str = "cid",
    client_secret: str = "csec",
    sender_id: str = "Sender",
    api_base_url: str = "https://api.test.local/api/connexus",
) -> ConnexusSmsClient:
    """Create a ConnexusSmsClient with a mocked HTTP layer."""
    _token_cache._tokens.clear()
    config = ConnexusConfig(
        client_id=client_id,
        client_secret=client_secret,
        sender_id=sender_id,
        api_base_url=api_base_url,
    )
    client = ConnexusSmsClient(config)
    client._http = AsyncMock()
    return client


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = ""):
    """Build a fake httpx.Response-like mock with sync .json()."""
    from unittest.mock import MagicMock
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.json.return_value = json_data or {}
    resp.text = text or str(json_data or "")
    return resp


# ===========================================================================
# Property 1: ConnexusConfig serialization round-trip
# ===========================================================================
# Feature: connexus-sms-integration, Property 1: ConnexusConfig serialization round-trip


class TestProperty1ConfigRoundTrip:
    """``from_dict(config.to_dict())`` produces identical fields.

    **Validates: Requirement 1.1**
    """

    @given(
        client_id=non_empty_text_st,
        client_secret=non_empty_text_st,
        sender_id=non_empty_text_st,
        api_base_url=api_base_url_st,
    )
    @PBT_SETTINGS
    def test_round_trip_preserves_all_fields(
        self,
        client_id: str,
        client_secret: str,
        sender_id: str,
        api_base_url: str,
    ) -> None:
        """P1: Serialising then deserialising a config preserves every field."""
        original = ConnexusConfig(
            client_id=client_id,
            client_secret=client_secret,
            sender_id=sender_id,
            api_base_url=api_base_url,
        )
        restored = ConnexusConfig.from_dict(original.to_dict())

        assert restored.client_id == original.client_id
        assert restored.client_secret == original.client_secret
        assert restored.sender_id == original.sender_id
        assert restored.api_base_url == original.api_base_url

    @given(
        client_id=non_empty_text_st,
        client_secret=non_empty_text_st,
        sender_id=non_empty_text_st,
    )
    @PBT_SETTINGS
    def test_round_trip_with_default_url(
        self,
        client_id: str,
        client_secret: str,
        sender_id: str,
    ) -> None:
        """P1: Round-trip works when api_base_url uses the default value."""
        original = ConnexusConfig(
            client_id=client_id,
            client_secret=client_secret,
            sender_id=sender_id,
        )
        restored = ConnexusConfig.from_dict(original.to_dict())

        assert restored.client_id == original.client_id
        assert restored.api_base_url == original.api_base_url


# ===========================================================================
# Property 2: Send payload construction
# ===========================================================================
# Feature: connexus-sms-integration, Property 2: Send payload construction


class TestProperty2SendPayload:
    """HTTP payload contains correct ``to``, ``body``, ``from`` fields.

    **Validates: Requirement 1.4**
    """

    @given(
        to_number=phone_number_st,
        body=sms_body_st,
        sender_id=non_empty_text_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_payload_uses_sender_id_when_no_from(
        self,
        to_number: str,
        body: str,
        sender_id: str,
    ) -> None:
        """P2: Payload ``from`` equals configured sender_id when message has no from_number."""
        client = _make_client(sender_id=sender_id)
        client._ensure_token = AsyncMock(return_value="tok")

        # Mock the _request method to capture the payload
        captured_kwargs: dict = {}

        async def _capture_request(method, url, **kwargs):
            captured_kwargs.update(kwargs)
            return _mock_response(
                200,
                json_data={"status": "accepted", "message_id": "m1", "parts": 1},
            )

        client._request = _capture_request  # type: ignore[assignment]

        msg = SmsMessage(to_number=to_number, body=body)
        await client.send(msg)

        payload = captured_kwargs["data"]
        assert payload["to"] == to_number
        assert payload["body"] == body
        assert payload["from"] == sender_id

    @given(
        to_number=phone_number_st,
        body=sms_body_st,
        from_number=phone_number_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_payload_uses_message_from_number_when_provided(
        self,
        to_number: str,
        body: str,
        from_number: str,
    ) -> None:
        """P2: Payload ``from`` equals message.from_number when provided."""
        client = _make_client(sender_id="DefaultSender")
        client._ensure_token = AsyncMock(return_value="tok")

        captured_kwargs: dict = {}

        async def _capture_request(method, url, **kwargs):
            captured_kwargs.update(kwargs)
            return _mock_response(
                200,
                json_data={"status": "accepted", "message_id": "m1", "parts": 1},
            )

        client._request = _capture_request  # type: ignore[assignment]

        msg = SmsMessage(to_number=to_number, body=body, from_number=from_number)
        await client.send(msg)

        payload = captured_kwargs["data"]
        assert payload["to"] == to_number
        assert payload["body"] == body
        assert payload["from"] == from_number


# ===========================================================================
# Property 3: API failures return structured error results
# ===========================================================================
# Feature: connexus-sms-integration, Property 3: API failures return structured error results


class TestProperty3ApiFailuresStructured:
    """Non-success responses return ``success=False`` with non-empty error.

    **Validates: Requirements 1.6, 1.7, 11.3, 12.3**
    """

    @given(status_code=http_error_code_st)
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_send_http_error_returns_structured_result(
        self,
        status_code: int,
    ) -> None:
        """P3: send() returns success=False with error on HTTP error codes."""
        client = _make_client()
        client._ensure_token = AsyncMock(return_value="tok")

        error_resp = _mock_response(status_code, text=f"Error {status_code}")
        client._request = AsyncMock(return_value=error_resp)

        msg = SmsMessage(to_number="+6421000000", body="test")
        result = await client.send(msg)

        assert result.success is False
        assert result.error is not None
        assert len(result.error) > 0

    @given(status_code=http_error_code_st)
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_check_balance_http_error_returns_error_dict(
        self,
        status_code: int,
    ) -> None:
        """P3: check_balance() returns error dict on HTTP error codes."""
        client = _make_client()
        client._ensure_token = AsyncMock(return_value="tok")

        error_resp = _mock_response(status_code, text=f"Error {status_code}")
        client._request = AsyncMock(return_value=error_resp)

        result = await client.check_balance()

        assert "error" in result
        assert len(result["error"]) > 0

    @given(status_code=http_error_code_st)
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_validate_number_http_error_returns_structured_result(
        self,
        status_code: int,
    ) -> None:
        """P3: validate_number() returns success=False with error on HTTP error codes."""
        client = _make_client()
        client._ensure_token = AsyncMock(return_value="tok")

        error_resp = _mock_response(status_code, text=f"Error {status_code}")
        client._request = AsyncMock(return_value=error_resp)

        result = await client.validate_number("+6421000000")

        assert result["success"] is False
        assert "error" in result
        assert len(result["error"]) > 0

    @pytest.mark.asyncio
    async def test_send_network_exception_returns_structured_result(self) -> None:
        """P3: send() returns success=False on network/timeout exceptions."""
        client = _make_client()
        client._ensure_token = AsyncMock(return_value="tok")
        client._request = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        msg = SmsMessage(to_number="+6421000000", body="test")
        result = await client.send(msg)

        assert result.success is False
        assert result.error is not None
        assert len(result.error) > 0


# ===========================================================================
# Property 4: Successful send includes parts metadata
# ===========================================================================
# Feature: connexus-sms-integration, Property 4: Successful send includes parts metadata


class TestProperty4PartsMetadata:
    """``metadata["parts_count"]`` equals Connexus response parts value.

    **Validates: Requirement 1.9**
    """

    @given(parts=parts_count_st)
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_parts_count_matches_response(self, parts: int) -> None:
        """P4: SmsSendResult.metadata['parts_count'] equals the API response parts."""
        client = _make_client()
        client._ensure_token = AsyncMock(return_value="tok")

        success_resp = _mock_response(
            200,
            json_data={
                "status": "accepted",
                "message_id": "msg-123",
                "parts": parts,
            },
        )
        client._request = AsyncMock(return_value=success_resp)

        msg = SmsMessage(to_number="+6421000000", body="hello")
        result = await client.send(msg)

        assert result.success is True
        assert result.metadata is not None
        assert result.metadata["parts_count"] == parts


# ===========================================================================
# Property 5: Token caching and Authorization header
# ===========================================================================
# Feature: connexus-sms-integration, Property 5: Token caching and Authorization header


class TestProperty5TokenCaching:
    """Cached token reused across calls within validity window.

    **Validates: Requirements 2.2, 2.6**
    """

    @given(call_count=st.integers(min_value=2, max_value=10))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_token_reused_within_validity_window(self, call_count: int) -> None:
        """P5: Multiple send() calls reuse the same cached token."""
        client = _make_client()

        # Simulate a valid cached token well within the validity window
        _token_cache.put(
            client._config.client_id,
            client._config.api_base_url,
            "cached-token-abc",
            3600,  # 1 hour from now
        )

        # Track _refresh_token calls — should NOT be called
        client._refresh_token = AsyncMock()  # type: ignore[method-assign]

        success_resp = _mock_response(
            200,
            json_data={"status": "accepted", "message_id": "m1", "parts": 1},
        )
        client._http.request = AsyncMock(return_value=success_resp)

        msg = SmsMessage(to_number="+6421000000", body="hello")
        for _ in range(call_count):
            await client.send(msg)

        # Token should never have been refreshed
        client._refresh_token.assert_not_called()

        # Every HTTP call should have the Authorization header
        for call_args in client._http.request.call_args_list:
            headers = call_args.kwargs.get("headers") or call_args[1].get("headers", {})
            assert headers.get("Authorization") == "Bearer cached-token-abc"


# ===========================================================================
# Property 6: Token not refreshed by API calls — background refresher's job
# ===========================================================================
# Feature: connexus-sms-integration, Property 6: API calls never trigger refresh


class TestProperty6NoInlineRefresh:
    """API calls use cached token without triggering refresh.

    The background ``_TokenRefresher`` handles proactive refresh.
    ``_ensure_token`` only refreshes when no token exists at all
    (bootstrap case).

    **Validates: Requirement 2.3**
    """

    @given(seconds_until_expiry=st.integers(min_value=1, max_value=299))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_near_expiry_token_still_used_without_refresh(
        self,
        seconds_until_expiry: int,
    ) -> None:
        """P6: _ensure_token returns near-expiry token without refreshing."""
        client = _make_client()

        # Token within the old 5-minute margin — still valid (not expired)
        _token_cache.put(
            client._config.client_id,
            client._config.api_base_url,
            "near-expiry-token",
            seconds_until_expiry,
        )

        client._refresh_token = AsyncMock()  # type: ignore[method-assign]

        token = await client._ensure_token()

        assert token == "near-expiry-token"
        client._refresh_token.assert_not_called()

    @given(seconds_until_expiry=st.integers(min_value=301, max_value=3600))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_no_refresh_outside_margin(
        self,
        seconds_until_expiry: int,
    ) -> None:
        """P6: _ensure_token does NOT refresh when token has plenty of time left."""
        client = _make_client()

        _token_cache.put(
            client._config.client_id,
            client._config.api_base_url,
            "valid-token",
            seconds_until_expiry,
        )

        client._refresh_token = AsyncMock()  # type: ignore[method-assign]

        token = await client._ensure_token()

        assert token == "valid-token"
        client._refresh_token.assert_not_called()
