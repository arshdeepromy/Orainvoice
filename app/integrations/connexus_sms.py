"""Connexus SMS client.

Provides the ``ConnexusSmsClient`` that communicates with the WebSMS
Connexus REST API (https://websms.co.nz/api/connexus/) for sending SMS,
checking balance, validating numbers, and managing webhooks.

This module replaces the legacy Twilio and AWS SNS providers as the
platform's sole outbound SMS provider.

Requirements: 1.1
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.integrations.sms_types import SmsMessage, SmsSendResult

logger = logging.getLogger(__name__)


DEFAULT_API_BASE_URL = "https://websms.co.nz/api/connexus"


@dataclass
class ConnexusConfig:
    """Configuration for the Connexus SMS API."""

    client_id: str
    client_secret: str
    sender_id: str
    api_base_url: str = DEFAULT_API_BASE_URL

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnexusConfig:
        """Create a ``ConnexusConfig`` from a plain dictionary."""
        return cls(
            client_id=data.get("client_id", ""),
            client_secret=data.get("client_secret", ""),
            sender_id=data.get("sender_id", ""),
            api_base_url=data.get("api_base_url", DEFAULT_API_BASE_URL),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the config to a plain dictionary."""
        return {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "sender_id": self.sender_id,
            "api_base_url": self.api_base_url,
        }

class ConnexusSmsClient:
    """Async client for the WebSMS Connexus REST API.

    Handles Bearer-token authentication with in-memory caching,
    proactive refresh (5-minute margin before 1-hour expiry), and
    automatic retry on 401 responses.

    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 1.8
    """

    _REFRESH_MARGIN: int = 300  # seconds – refresh 5 min before expiry
    _TOKEN_LIFETIME: int = 3600  # seconds – 1 hour
    _TIMEOUT: int = 30  # seconds – HTTP timeout for all calls

    def __init__(self, config: ConnexusConfig) -> None:
        self._config = config
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._http = httpx.AsyncClient(timeout=self._TIMEOUT)

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _refresh_token(self) -> None:
        """Request a new Bearer token from the Connexus auth endpoint.

        POSTs ``client_id`` and ``client_secret`` as form-encoded data to
        ``{api_base_url}/auth/token`` and caches the returned token
        with an expiry timestamp.

        Requirements: 2.1, 2.5
        """
        url = f"{self._config.api_base_url}/auth/token"
        payload = {
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }
        try:
            resp = await self._http.post(url, data=payload)
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            expires_in = int(data.get("expires_in", self._TOKEN_LIFETIME))
            self._token_expires_at = time.time() + expires_in
        except Exception:
            self._token = None
            self._token_expires_at = 0.0
            logger.exception("Connexus token refresh failed")
            raise

    async def _ensure_token(self) -> str:
        """Return a valid Bearer token, refreshing proactively if needed.

        If the cached token is ``None`` or within ``_REFRESH_MARGIN``
        seconds of expiry, a fresh token is requested first.

        Requirements: 2.2, 2.3
        """
        if (
            self._token is None
            or time.time() >= self._token_expires_at - self._REFRESH_MARGIN
        ):
            await self._refresh_token()
        assert self._token is not None  # noqa: S101 – guaranteed by _refresh_token
        return self._token

    # ------------------------------------------------------------------
    # Generic request helper with 401 retry
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an authenticated HTTP request with automatic 401 retry.

        * Injects ``Authorization: Bearer <token>`` header.
        * On a 401 response, refreshes the token and retries exactly once.

        Requirements: 2.4, 2.6, 1.8
        """
        token = await self._ensure_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        resp = await self._http.request(method, url, headers=headers, **kwargs)

        if resp.status_code == 401:
            # Refresh and retry once
            await self._refresh_token()
            headers["Authorization"] = f"Bearer {self._token}"
            resp = await self._http.request(method, url, headers=headers, **kwargs)

        return resp

    # ------------------------------------------------------------------
    # Core SMS sending
    # ------------------------------------------------------------------

    async def send(self, message: SmsMessage) -> SmsSendResult:
        """Send an SMS via the Connexus API.

        POSTs to ``{api_base_url}/sms/out`` with ``to``, ``body``, and
        an optional ``from`` field (falls back to the configured
        ``sender_id``).

        Returns an ``SmsSendResult`` indicating success or failure.
        Network and timeout exceptions are caught, logged, and returned
        as structured error results rather than propagated.

        Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 1.9
        """
        url = f"{self._config.api_base_url}/sms/out"
        payload: dict[str, Any] = {
            "to": message.to_number,
            "body": message.body,
        }
        from_number = message.from_number or self._config.sender_id
        if from_number:
            payload["from"] = from_number

        try:
            resp = await self._request("POST", url, data=payload)

            if resp.is_success:
                data = resp.json()
                if data.get("status") == "accepted":
                    return SmsSendResult(
                        success=True,
                        message_sid=data["message_id"],
                        metadata={"parts_count": data.get("parts", 1)},
                    )

            # Non-success HTTP or unexpected status in body
            return SmsSendResult(
                success=False,
                error=f"{resp.status_code}: {resp.text}",
            )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            logger.exception("Connexus send failed due to network/timeout error")
            return SmsSendResult(success=False, error=str(exc))
        except Exception as exc:
            logger.exception("Connexus send failed with unexpected error")
            return SmsSendResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Balance, number validation, and webhook configuration
    # ------------------------------------------------------------------

    async def check_balance(self) -> dict:
        """Check the Connexus account balance.

        POSTs to ``{api_base_url}/sms/balance`` and returns the balance
        amount and currency.

        Returns ``{"balance": float, "currency": str}`` on success, or
        ``{"error": str}`` on failure.

        Requirements: 11.1, 11.3
        """
        url = f"{self._config.api_base_url}/sms/balance"
        try:
            resp = await self._request("POST", url)
            if resp.is_success:
                data = resp.json()
                return {
                    "balance": float(data.get("balance", 0)),
                    "currency": data.get("currency", "NZD"),
                }
            return {"error": f"{resp.status_code}: {resp.text}"}
        except Exception as exc:
            logger.exception("Connexus balance check failed")
            return {"error": str(exc)}

    async def validate_number(self, number: str) -> dict:
        """Validate a phone number via the Connexus IPMS lookup.

        POSTs to ``{api_base_url}/number/lookup`` with the number and
        returns carrier, porting status, and network information.

        Returns ``{"success": True, ...lookup data}`` on success, or
        ``{"success": False, "error": str}`` on failure.

        Requirements: 12.1, 12.2, 12.3
        """
        url = f"{self._config.api_base_url}/number/lookup"
        try:
            resp = await self._request("POST", url, data={"number": number})
            if resp.is_success:
                data = resp.json()
                return {"success": True, **data}
            return {
                "success": False,
                "error": f"{resp.status_code}: {resp.text}",
            }
        except Exception as exc:
            logger.exception("Connexus number validation failed")
            return {"success": False, "error": str(exc)}

    async def configure_webhooks(
        self, mo_webhook_url: str, dlr_webhook_url: str
    ) -> dict:
        """Configure Connexus webhook URLs for incoming SMS and delivery status.

        POSTs to ``{api_base_url}/configure`` with the MO (mobile-originated)
        and DLR (delivery report) webhook URLs.

        Returns the Connexus response data on success, or
        ``{"error": str}`` on failure.

        Requirements: 13.1
        """
        url = f"{self._config.api_base_url}/configure"
        payload = {
            "mo_webhook_url": mo_webhook_url,
            "dlr_webhook_url": dlr_webhook_url,
        }
        try:
            resp = await self._request("POST", url, json=payload)
            if resp.is_success:
                return resp.json()
            return {"error": f"{resp.status_code}: {resp.text}"}
        except Exception as exc:
            logger.exception("Connexus webhook configuration failed")
            return {"error": str(exc)}


