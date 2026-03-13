"""Tests for ConnexusSmsClient token management and _request helper.

Covers:
- Token acquisition via _refresh_token()
- Token caching and proactive refresh via _ensure_token()
- 401 retry logic in _request()
- 30-second HTTP timeout configuration
- Authorization header injection on all API calls

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 1.8
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.integrations.connexus_sms import ConnexusConfig, ConnexusSmsClient


@pytest.fixture
def config() -> ConnexusConfig:
    return ConnexusConfig(
        client_id="test-id",
        client_secret="test-secret",
        sender_id="TestSender",
        api_base_url="https://api.test.local",
    )


@pytest.fixture
def client(config: ConnexusConfig) -> ConnexusSmsClient:
    return ConnexusSmsClient(config)


class TestInit:
    """ConnexusSmsClient.__init__ tests."""

    def test_initial_state(self, client: ConnexusSmsClient) -> None:
        assert client._token is None
        assert client._token_expires_at == 0.0

    def test_timeout_configured(self, client: ConnexusSmsClient) -> None:
        assert client._http.timeout == httpx.Timeout(30)

    def test_class_constants(self) -> None:
        assert ConnexusSmsClient._REFRESH_MARGIN == 300
        assert ConnexusSmsClient._TOKEN_LIFETIME == 3600
        assert ConnexusSmsClient._TIMEOUT == 30


class TestRefreshToken:
    """ConnexusSmsClient._refresh_token() tests."""

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, client: ConnexusSmsClient) -> None:
        mock_resp = httpx.Response(
            200,
            json={"access_token": "abc123", "token_type": "Bearer", "expires_in": 3600},
            request=httpx.Request("POST", "https://api.test.local/auth/token"),
        )

        client._http = AsyncMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        before = time.time()
        await client._refresh_token()

        client._http.post.assert_called_once_with(
            "https://api.test.local/auth/token",
            data={"client_id": "test-id", "client_secret": "test-secret"},
        )
        assert client._token == "abc123"
        assert client._token_expires_at >= before + 3600

    @pytest.mark.asyncio
    async def test_refresh_token_failure_clears_state(
        self, client: ConnexusSmsClient
    ) -> None:
        client._token = "old-token"
        client._token_expires_at = time.time() + 9999

        mock_resp = httpx.Response(
            401,
            request=httpx.Request("POST", "https://api.test.local/auth/token"),
        )

        client._http = AsyncMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(httpx.HTTPStatusError):
            await client._refresh_token()

        assert client._token is None
        assert client._token_expires_at == 0.0


class TestEnsureToken:
    """ConnexusSmsClient._ensure_token() tests."""

    @pytest.mark.asyncio
    async def test_fetches_token_when_none(self, client: ConnexusSmsClient) -> None:
        client._refresh_token = AsyncMock()
        client._refresh_token.side_effect = lambda: setattr(client, "_token", "new-tok") or setattr(client, "_token_expires_at", time.time() + 3600)

        token = await client._ensure_token()
        assert token == "new-tok"
        client._refresh_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_reuses_cached_token(self, client: ConnexusSmsClient) -> None:
        client._token = "cached-tok"
        client._token_expires_at = time.time() + 3600  # well within margin
        client._refresh_token = AsyncMock()

        token = await client._ensure_token()
        assert token == "cached-tok"
        client._refresh_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_refreshes_when_within_margin(
        self, client: ConnexusSmsClient
    ) -> None:
        client._token = "expiring-tok"
        # Set expiry to 4 minutes from now (within 5-min margin)
        client._token_expires_at = time.time() + 240
        client._refresh_token = AsyncMock()
        client._refresh_token.side_effect = lambda: setattr(client, "_token", "fresh-tok") or setattr(client, "_token_expires_at", time.time() + 3600)

        token = await client._ensure_token()
        assert token == "fresh-tok"
        client._refresh_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_refresh_when_outside_margin(
        self, client: ConnexusSmsClient
    ) -> None:
        client._token = "valid-tok"
        # Set expiry to 10 minutes from now (outside 5-min margin)
        client._token_expires_at = time.time() + 600
        client._refresh_token = AsyncMock()

        token = await client._ensure_token()
        assert token == "valid-tok"
        client._refresh_token.assert_not_called()


class TestRequest:
    """ConnexusSmsClient._request() tests."""

    @pytest.mark.asyncio
    async def test_injects_auth_header(self, client: ConnexusSmsClient) -> None:
        client._ensure_token = AsyncMock(return_value="my-token")

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        resp = await client._request("GET", "https://api.test.local/sms/balance")

        client._http.request.assert_called_once()
        call_kwargs = client._http.request.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer my-token"

    @pytest.mark.asyncio
    async def test_no_auth_header_on_token_endpoint(
        self, client: ConnexusSmsClient
    ) -> None:
        """Token request itself (via _refresh_token) uses _http.post directly,
        not _request, so no Bearer header is injected."""
        mock_resp = httpx.Response(
            200,
            json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600},
            request=httpx.Request("POST", "https://api.test.local/auth/token"),
        )

        client._http = AsyncMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        await client._refresh_token()

        call_kwargs = client._http.post.call_args
        # post() should NOT have an Authorization header
        assert "headers" not in call_kwargs[1] or "Authorization" not in call_kwargs[1].get("headers", {})

    @pytest.mark.asyncio
    async def test_retries_on_401(self, client: ConnexusSmsClient) -> None:
        client._token = "old-token"
        client._token_expires_at = time.time() + 3600
        client._ensure_token = AsyncMock(return_value="old-token")

        resp_401 = AsyncMock()
        resp_401.status_code = 401

        resp_200 = AsyncMock()
        resp_200.status_code = 200

        client._http = AsyncMock()
        client._http.request = AsyncMock(side_effect=[resp_401, resp_200])

        # Mock _refresh_token to set a new token
        async def fake_refresh():
            client._token = "new-token"
            client._token_expires_at = time.time() + 3600

        client._refresh_token = AsyncMock(side_effect=fake_refresh)

        resp = await client._request("POST", "https://api.test.local/sms/out", json={"to": "+64123"})

        assert resp.status_code == 200
        assert client._http.request.call_count == 2
        client._refresh_token.assert_called_once()

        # Second call should use the new token
        second_call = client._http.request.call_args_list[1]
        assert second_call[1]["headers"]["Authorization"] == "Bearer new-token"

    @pytest.mark.asyncio
    async def test_does_not_retry_on_non_401(self, client: ConnexusSmsClient) -> None:
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = AsyncMock()
        mock_resp.status_code = 500
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        resp = await client._request("POST", "https://api.test.local/sms/out")

        assert resp.status_code == 500
        client._http.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_preserves_custom_headers(self, client: ConnexusSmsClient) -> None:
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        await client._request(
            "POST",
            "https://api.test.local/sms/out",
            headers={"X-Custom": "value"},
        )

        call_kwargs = client._http.request.call_args
        headers = call_kwargs[1]["headers"]
        assert headers["X-Custom"] == "value"
        assert headers["Authorization"] == "Bearer tok"


class TestSend:
    """ConnexusSmsClient.send() tests.

    Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 1.9
    """

    @pytest.mark.asyncio
    async def test_send_success_accepted(self, client: ConnexusSmsClient) -> None:
        """Accepted response returns success with message_sid and parts metadata."""
        from app.integrations.sms_types import SmsMessage

        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"status": "accepted", "message_id": "msg-001", "parts": 3},
            request=httpx.Request("POST", "https://api.test.local/sms/out"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        result = await client.send(SmsMessage(to_number="+6421000000", body="Hello"))

        assert result.success is True
        assert result.message_sid == "msg-001"
        assert result.metadata == {"parts_count": 3}

    @pytest.mark.asyncio
    async def test_send_success_defaults_parts_to_1(self, client: ConnexusSmsClient) -> None:
        """When Connexus response omits 'parts', default to 1."""
        from app.integrations.sms_types import SmsMessage

        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"status": "accepted", "message_id": "msg-002"},
            request=httpx.Request("POST", "https://api.test.local/sms/out"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        result = await client.send(SmsMessage(to_number="+6421000000", body="Hi"))

        assert result.success is True
        assert result.metadata == {"parts_count": 1}

    @pytest.mark.asyncio
    async def test_send_http_error(self, client: ConnexusSmsClient) -> None:
        """Non-success HTTP returns SmsSendResult with error."""
        from app.integrations.sms_types import SmsMessage

        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            400,
            text="Bad Request: invalid number",
            request=httpx.Request("POST", "https://api.test.local/sms/out"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        result = await client.send(SmsMessage(to_number="bad", body="test"))

        assert result.success is False
        assert "400" in result.error
        assert "Bad Request" in result.error

    @pytest.mark.asyncio
    async def test_send_non_accepted_status(self, client: ConnexusSmsClient) -> None:
        """HTTP 200 but non-accepted status returns failure."""
        from app.integrations.sms_types import SmsMessage

        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"status": "rejected", "reason": "quota exceeded"},
            request=httpx.Request("POST", "https://api.test.local/sms/out"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        result = await client.send(SmsMessage(to_number="+6421000000", body="test"))

        assert result.success is False
        assert "200" in result.error

    @pytest.mark.asyncio
    async def test_send_timeout_exception(self, client: ConnexusSmsClient) -> None:
        """Timeout exception returns structured error, no unhandled raise."""
        from app.integrations.sms_types import SmsMessage

        client._ensure_token = AsyncMock(return_value="tok")
        client._http = AsyncMock()
        client._http.request = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))

        result = await client.send(SmsMessage(to_number="+6421000000", body="test"))

        assert result.success is False
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_send_connect_error(self, client: ConnexusSmsClient) -> None:
        """Connection error returns structured error."""
        from app.integrations.sms_types import SmsMessage

        client._ensure_token = AsyncMock(return_value="tok")
        client._http = AsyncMock()
        client._http.request = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        result = await client.send(SmsMessage(to_number="+6421000000", body="test"))

        assert result.success is False
        assert "connection refused" in result.error

    @pytest.mark.asyncio
    async def test_send_payload_includes_from_number(self, client: ConnexusSmsClient) -> None:
        """When message has from_number, payload uses it instead of sender_id."""
        from app.integrations.sms_types import SmsMessage

        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"status": "accepted", "message_id": "m1", "parts": 1},
            request=httpx.Request("POST", "https://api.test.local/sms/out"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        await client.send(SmsMessage(to_number="+6421000000", body="Hi", from_number="+6422222222"))

        call_kwargs = client._http.request.call_args
        payload = call_kwargs[1]["json"]
        assert payload["from"] == "+6422222222"
        assert payload["to"] == "+6421000000"
        assert payload["body"] == "Hi"

    @pytest.mark.asyncio
    async def test_send_payload_uses_sender_id_when_no_from(self, client: ConnexusSmsClient) -> None:
        """When message has no from_number, payload uses config sender_id."""
        from app.integrations.sms_types import SmsMessage

        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"status": "accepted", "message_id": "m2", "parts": 1},
            request=httpx.Request("POST", "https://api.test.local/sms/out"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        await client.send(SmsMessage(to_number="+6421000000", body="Hi"))

        call_kwargs = client._http.request.call_args
        payload = call_kwargs[1]["json"]
        assert payload["from"] == "TestSender"

    @pytest.mark.asyncio
    async def test_send_posts_to_correct_url(self, client: ConnexusSmsClient) -> None:
        """send() POSTs to {api_base_url}/sms/out."""
        from app.integrations.sms_types import SmsMessage

        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"status": "accepted", "message_id": "m3", "parts": 1},
            request=httpx.Request("POST", "https://api.test.local/sms/out"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        await client.send(SmsMessage(to_number="+6421000000", body="test"))

        call_args = client._http.request.call_args
        assert call_args[0] == ("POST", "https://api.test.local/sms/out")


class TestCheckBalance:
    """ConnexusSmsClient.check_balance() tests.

    Requirements: 11.1, 11.3
    """

    @pytest.mark.asyncio
    async def test_check_balance_success(self, client: ConnexusSmsClient) -> None:
        """Successful balance check returns balance and currency."""
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"balance": 42.50, "currency": "NZD"},
            request=httpx.Request("POST", "https://api.test.local/sms/balance"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        result = await client.check_balance()

        assert result == {"balance": 42.50, "currency": "NZD"}

    @pytest.mark.asyncio
    async def test_check_balance_posts_to_correct_url(self, client: ConnexusSmsClient) -> None:
        """check_balance() POSTs to {api_base_url}/sms/balance."""
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"balance": 10.0, "currency": "NZD"},
            request=httpx.Request("POST", "https://api.test.local/sms/balance"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        await client.check_balance()

        call_args = client._http.request.call_args
        assert call_args[0] == ("POST", "https://api.test.local/sms/balance")

    @pytest.mark.asyncio
    async def test_check_balance_http_error(self, client: ConnexusSmsClient) -> None:
        """Non-success HTTP returns error dict."""
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            500,
            text="Internal Server Error",
            request=httpx.Request("POST", "https://api.test.local/sms/balance"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        result = await client.check_balance()

        assert "error" in result
        assert "500" in result["error"]

    @pytest.mark.asyncio
    async def test_check_balance_network_error(self, client: ConnexusSmsClient) -> None:
        """Network exception returns error dict, no unhandled raise."""
        client._ensure_token = AsyncMock(return_value="tok")
        client._http = AsyncMock()
        client._http.request = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        result = await client.check_balance()

        assert "error" in result
        assert "connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_check_balance_defaults_currency(self, client: ConnexusSmsClient) -> None:
        """When response omits currency, defaults to NZD."""
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"balance": 5.0},
            request=httpx.Request("POST", "https://api.test.local/sms/balance"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        result = await client.check_balance()

        assert result["currency"] == "NZD"
        assert result["balance"] == 5.0


class TestValidateNumber:
    """ConnexusSmsClient.validate_number() tests.

    Requirements: 12.1, 12.2, 12.3
    """

    @pytest.mark.asyncio
    async def test_validate_number_success(self, client: ConnexusSmsClient) -> None:
        """Successful lookup returns success=True with carrier data."""
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={
                "carrier": "Spark",
                "ported": False,
                "original_network": "Spark",
                "current_network": "Spark",
                "network_code": "530-01",
            },
            request=httpx.Request("POST", "https://api.test.local/number/lookup"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        result = await client.validate_number("+6421000000")

        assert result["success"] is True
        assert result["carrier"] == "Spark"
        assert result["ported"] is False

    @pytest.mark.asyncio
    async def test_validate_number_posts_correct_payload(self, client: ConnexusSmsClient) -> None:
        """validate_number() POSTs to {api_base_url}/number/lookup with number."""
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"carrier": "Vodafone"},
            request=httpx.Request("POST", "https://api.test.local/number/lookup"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        await client.validate_number("+6421999999")

        call_args = client._http.request.call_args
        assert call_args[0] == ("POST", "https://api.test.local/number/lookup")
        assert call_args[1]["json"] == {"number": "+6421999999"}

    @pytest.mark.asyncio
    async def test_validate_number_http_error(self, client: ConnexusSmsClient) -> None:
        """Non-success HTTP returns success=False with error."""
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            404,
            text="Number not found",
            request=httpx.Request("POST", "https://api.test.local/number/lookup"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        result = await client.validate_number("+6421000000")

        assert result["success"] is False
        assert "404" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_number_network_error(self, client: ConnexusSmsClient) -> None:
        """Network exception returns success=False, no unhandled raise."""
        client._ensure_token = AsyncMock(return_value="tok")
        client._http = AsyncMock()
        client._http.request = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))

        result = await client.validate_number("+6421000000")

        assert result["success"] is False
        assert "timed out" in result["error"]


class TestConfigureWebhooks:
    """ConnexusSmsClient.configure_webhooks() tests.

    Requirements: 13.1
    """

    @pytest.mark.asyncio
    async def test_configure_webhooks_success(self, client: ConnexusSmsClient) -> None:
        """Successful configuration returns response data."""
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"status": "ok", "mo_webhook_url": "https://app/incoming", "dlr_webhook_url": "https://app/status"},
            request=httpx.Request("POST", "https://api.test.local/configure"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        result = await client.configure_webhooks(
            mo_webhook_url="https://app/incoming",
            dlr_webhook_url="https://app/status",
        )

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_configure_webhooks_posts_correct_payload(self, client: ConnexusSmsClient) -> None:
        """configure_webhooks() POSTs to {api_base_url}/configure with both URLs."""
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            200,
            json={"status": "ok"},
            request=httpx.Request("POST", "https://api.test.local/configure"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        await client.configure_webhooks(
            mo_webhook_url="https://example.com/incoming",
            dlr_webhook_url="https://example.com/status",
        )

        call_args = client._http.request.call_args
        assert call_args[0] == ("POST", "https://api.test.local/configure")
        assert call_args[1]["json"] == {
            "mo_webhook_url": "https://example.com/incoming",
            "dlr_webhook_url": "https://example.com/status",
        }

    @pytest.mark.asyncio
    async def test_configure_webhooks_http_error(self, client: ConnexusSmsClient) -> None:
        """Non-success HTTP returns error dict."""
        client._ensure_token = AsyncMock(return_value="tok")

        mock_resp = httpx.Response(
            403,
            text="Forbidden",
            request=httpx.Request("POST", "https://api.test.local/configure"),
        )
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_resp)

        result = await client.configure_webhooks(
            mo_webhook_url="https://app/incoming",
            dlr_webhook_url="https://app/status",
        )

        assert "error" in result
        assert "403" in result["error"]

    @pytest.mark.asyncio
    async def test_configure_webhooks_network_error(self, client: ConnexusSmsClient) -> None:
        """Network exception returns error dict, no unhandled raise."""
        client._ensure_token = AsyncMock(return_value="tok")
        client._http = AsyncMock()
        client._http.request = AsyncMock(side_effect=httpx.ConnectError("dns failure"))

        result = await client.configure_webhooks(
            mo_webhook_url="https://app/incoming",
            dlr_webhook_url="https://app/status",
        )

        assert "error" in result
        assert "dns failure" in result["error"]
