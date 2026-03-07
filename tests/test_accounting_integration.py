"""Unit tests for Task 25.4 — Accounting software integration (Xero & MYOB).

Tests cover:
  - Schema validation (AccountingConnectionResponse, SyncLogEntry, etc.)
  - Xero OAuth URL generation and token exchange
  - MYOB OAuth URL generation and token exchange
  - Service: list_connections, initiate_oauth, handle_oauth_callback
  - Service: disconnect, sync_entity, get_sync_log, retry_failed_syncs
  - Token refresh logic
  - Sync failure logging
  - Credential encryption

Requirements: 68.1, 68.2, 68.3, 68.4, 68.5, 68.6
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.accounting.models import AccountingIntegration, AccountingSyncLog

# Import related models so SQLAlchemy mapper can resolve all relationships
from app.modules.admin.models import Organisation  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.accounting.schemas import (
    VALID_PROVIDERS,
    AccountingConnectionListResponse,
    AccountingConnectionResponse,
    OAuthRedirectResponse,
    SyncLogEntry,
    SyncLogListResponse,
    SyncStatusResponse,
)
from app.modules.accounting.service import (
    _ensure_valid_token,
    disconnect,
    get_sync_log,
    handle_oauth_callback,
    initiate_oauth,
    list_connections,
    retry_failed_syncs,
    sync_entity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_result(values):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = values
    result.scalars.return_value = scalars
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestAccountingSchemas:
    """Test Pydantic schema validation for accounting integration."""

    def test_valid_providers(self):
        assert "xero" in VALID_PROVIDERS
        assert "myob" in VALID_PROVIDERS

    def test_connection_response(self):
        resp = AccountingConnectionResponse(
            id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            provider="xero",
            is_connected=True,
            last_sync_at="2024-01-15T10:00:00+00:00",
            created_at="2024-01-01T00:00:00+00:00",
        )
        assert resp.provider == "xero"
        assert resp.is_connected is True

    def test_connection_response_no_sync(self):
        resp = AccountingConnectionResponse(
            id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            provider="myob",
            is_connected=False,
            last_sync_at=None,
            created_at="2024-01-01T00:00:00+00:00",
        )
        assert resp.last_sync_at is None

    def test_connection_list_response(self):
        resp = AccountingConnectionListResponse(connections=[], total=0)
        assert resp.total == 0

    def test_oauth_redirect_response(self):
        resp = OAuthRedirectResponse(authorization_url="https://login.xero.com/...")
        assert resp.authorization_url.startswith("https://")

    def test_sync_log_entry(self):
        entry = SyncLogEntry(
            id=str(uuid.uuid4()),
            provider="xero",
            entity_type="invoice",
            entity_id=str(uuid.uuid4()),
            external_id="INV-001",
            status="synced",
            error_message=None,
            created_at="2024-01-15T10:00:00+00:00",
        )
        assert entry.status == "synced"

    def test_sync_log_entry_failed(self):
        entry = SyncLogEntry(
            id=str(uuid.uuid4()),
            provider="myob",
            entity_type="payment",
            entity_id=str(uuid.uuid4()),
            external_id=None,
            status="failed",
            error_message="Connection timeout",
            created_at="2024-01-15T10:00:00+00:00",
        )
        assert entry.error_message == "Connection timeout"

    def test_sync_status_response(self):
        resp = SyncStatusResponse(
            provider="xero", synced=3, failed=1, message="Retried 4 syncs"
        )
        assert resp.synced == 3
        assert resp.failed == 1


# ---------------------------------------------------------------------------
# Xero OAuth tests
# ---------------------------------------------------------------------------

class TestXeroOAuth:
    """Test Xero OAuth URL generation and token exchange."""

    def test_authorization_url_generation(self):
        from app.integrations.xero import get_authorization_url

        url = get_authorization_url("https://example.com/callback", "test-state")
        assert "login.xero.com" in url
        assert "response_type=code" in url
        assert "state=test-state" in url
        assert "offline_access" in url

    @pytest.mark.asyncio
    async def test_exchange_code_success(self):
        from app.integrations.xero import exchange_code

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "xero_access",
            "refresh_token": "xero_refresh",
            "expires_in": 1800,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await exchange_code("auth_code", "https://example.com/callback")

        assert result["access_token"] == "xero_access"
        assert result["refresh_token"] == "xero_refresh"

    @pytest.mark.asyncio
    async def test_refresh_tokens(self):
        from app.integrations.xero import refresh_tokens

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 1800,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await refresh_tokens("old_refresh")

        assert result["access_token"] == "new_access"


# ---------------------------------------------------------------------------
# MYOB OAuth tests
# ---------------------------------------------------------------------------

class TestMYOBOAuth:
    """Test MYOB OAuth URL generation and token exchange."""

    def test_authorization_url_generation(self):
        from app.integrations.myob import get_authorization_url

        url = get_authorization_url("https://example.com/callback", "test-state")
        assert "secure.myob.com" in url
        assert "response_type=code" in url
        assert "state=test-state" in url

    @pytest.mark.asyncio
    async def test_exchange_code_success(self):
        from app.integrations.myob import exchange_code

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "myob_access",
            "refresh_token": "myob_refresh",
            "expires_in": 1200,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await exchange_code("auth_code", "https://example.com/callback")

        assert result["access_token"] == "myob_access"

    @pytest.mark.asyncio
    async def test_refresh_tokens(self):
        from app.integrations.myob import refresh_tokens

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "new_myob_access",
            "refresh_token": "new_myob_refresh",
            "expires_in": 1200,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await refresh_tokens("old_refresh")

        assert result["access_token"] == "new_myob_access"


# ---------------------------------------------------------------------------
# Service tests — list_connections
# ---------------------------------------------------------------------------

class TestListConnections:
    """Test list_connections service function."""

    @pytest.mark.asyncio
    async def test_empty_connections(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalars_result([]))

        result = await list_connections(db, org_id=uuid.uuid4())
        assert result["total"] == 0
        assert result["connections"] == []

    @pytest.mark.asyncio
    async def test_returns_connections(self):
        conn = MagicMock(spec=AccountingIntegration)
        conn.id = uuid.uuid4()
        conn.org_id = uuid.uuid4()
        conn.provider = "xero"
        conn.is_connected = True
        conn.last_sync_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        conn.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalars_result([conn]))

        result = await list_connections(db, org_id=conn.org_id)
        assert result["total"] == 1
        assert result["connections"][0]["provider"] == "xero"
        assert result["connections"][0]["is_connected"] is True


# ---------------------------------------------------------------------------
# Service tests — initiate_oauth
# ---------------------------------------------------------------------------

class TestInitiateOAuth:
    """Test initiate_oauth service function."""

    @pytest.mark.asyncio
    async def test_invalid_provider_returns_none(self):
        db = _mock_db()
        result = await initiate_oauth(db, org_id=uuid.uuid4(), provider="quickbooks")
        assert result is None

    @pytest.mark.asyncio
    async def test_xero_returns_auth_url(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        result = await initiate_oauth(db, org_id=uuid.uuid4(), provider="xero")
        assert result is not None
        assert "login.xero.com" in result

    @pytest.mark.asyncio
    async def test_myob_returns_auth_url(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        result = await initiate_oauth(db, org_id=uuid.uuid4(), provider="myob")
        assert result is not None
        assert "secure.myob.com" in result

    @pytest.mark.asyncio
    async def test_reuses_existing_connection_row(self):
        existing = MagicMock(spec=AccountingIntegration)
        existing.org_id = uuid.uuid4()
        existing.provider = "xero"

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(existing))

        result = await initiate_oauth(db, org_id=existing.org_id, provider="xero")
        assert result is not None
        db.add.assert_not_called()  # Should not create a new row


# ---------------------------------------------------------------------------
# Service tests — handle_oauth_callback
# ---------------------------------------------------------------------------

class TestHandleOAuthCallback:
    """Test handle_oauth_callback service function."""

    @pytest.mark.asyncio
    async def test_invalid_provider(self):
        db = _mock_db()
        result = await handle_oauth_callback(
            db, org_id=uuid.uuid4(), provider="invalid", code="abc"
        )
        assert result == "Invalid provider"

    @pytest.mark.asyncio
    @patch("app.modules.accounting.service.envelope_encrypt")
    @patch("app.modules.accounting.service.xero_client")
    async def test_xero_callback_stores_encrypted_tokens(self, mock_xero, mock_encrypt):
        mock_xero.exchange_code = AsyncMock(return_value={
            "access_token": "xero_at",
            "refresh_token": "xero_rt",
            "expires_in": 1800,
        })
        mock_encrypt.return_value = b"encrypted"

        conn = MagicMock(spec=AccountingIntegration)
        conn.id = uuid.uuid4()
        conn.org_id = uuid.uuid4()
        conn.provider = "xero"
        conn.is_connected = False
        conn.last_sync_at = None
        conn.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(conn))

        result = await handle_oauth_callback(
            db, org_id=conn.org_id, provider="xero", code="auth_code"
        )

        assert isinstance(result, dict)
        assert result["is_connected"] is True
        assert conn.access_token_encrypted == b"encrypted"
        assert conn.refresh_token_encrypted == b"encrypted"
        assert mock_encrypt.call_count == 2  # access + refresh

    @pytest.mark.asyncio
    @patch("app.modules.accounting.service.myob_client")
    async def test_myob_callback_failure(self, mock_myob):
        mock_myob.exchange_code = AsyncMock(side_effect=Exception("Network error"))

        db = _mock_db()
        result = await handle_oauth_callback(
            db, org_id=uuid.uuid4(), provider="myob", code="bad_code"
        )

        assert isinstance(result, str)
        assert "Network error" in result


# ---------------------------------------------------------------------------
# Service tests — disconnect
# ---------------------------------------------------------------------------

class TestDisconnect:
    """Test disconnect service function."""

    @pytest.mark.asyncio
    async def test_disconnect_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        result = await disconnect(db, org_id=uuid.uuid4(), provider="xero")
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_clears_tokens(self):
        conn = MagicMock(spec=AccountingIntegration)
        conn.access_token_encrypted = b"token"
        conn.refresh_token_encrypted = b"token"
        conn.is_connected = True

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(conn))

        result = await disconnect(db, org_id=uuid.uuid4(), provider="xero")
        assert result is True
        assert conn.access_token_encrypted is None
        assert conn.refresh_token_encrypted is None
        assert conn.is_connected is False


# ---------------------------------------------------------------------------
# Service tests — token refresh
# ---------------------------------------------------------------------------

class TestTokenRefresh:
    """Test _ensure_valid_token helper."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_tokens(self):
        conn = MagicMock(spec=AccountingIntegration)
        conn.access_token_encrypted = None
        conn.refresh_token_encrypted = None

        db = _mock_db()
        result = await _ensure_valid_token(db, conn)
        assert result is None

    @pytest.mark.asyncio
    @patch("app.modules.accounting.service.envelope_decrypt_str")
    async def test_returns_existing_token_when_valid(self, mock_decrypt):
        mock_decrypt.return_value = "valid_token"

        conn = MagicMock(spec=AccountingIntegration)
        conn.access_token_encrypted = b"enc_access"
        conn.refresh_token_encrypted = b"enc_refresh"
        conn.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        conn.provider = "xero"

        db = _mock_db()
        result = await _ensure_valid_token(db, conn)
        assert result == "valid_token"

    @pytest.mark.asyncio
    @patch("app.modules.accounting.service.envelope_encrypt")
    @patch("app.modules.accounting.service.envelope_decrypt_str")
    @patch("app.modules.accounting.service.xero_client")
    async def test_refreshes_expired_xero_token(self, mock_xero, mock_decrypt, mock_encrypt):
        mock_decrypt.return_value = "old_token"
        mock_encrypt.return_value = b"new_encrypted"
        mock_xero.refresh_tokens = AsyncMock(return_value={
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 1800,
        })

        conn = MagicMock(spec=AccountingIntegration)
        conn.access_token_encrypted = b"enc_access"
        conn.refresh_token_encrypted = b"enc_refresh"
        conn.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        conn.provider = "xero"
        conn.org_id = uuid.uuid4()

        db = _mock_db()
        result = await _ensure_valid_token(db, conn)
        assert result == "new_access"
        assert conn.access_token_encrypted == b"new_encrypted"


# ---------------------------------------------------------------------------
# Service tests — sync_entity
# ---------------------------------------------------------------------------

class TestSyncEntity:
    """Test sync_entity service function."""

    @pytest.mark.asyncio
    @patch("app.modules.accounting.service._log_sync")
    async def test_sync_fails_when_no_connection(self, mock_log):
        mock_log_entry = MagicMock(spec=AccountingSyncLog)
        mock_log_entry.id = uuid.uuid4()
        mock_log_entry.provider = "xero"
        mock_log_entry.entity_type = "invoice"
        mock_log_entry.entity_id = uuid.uuid4()
        mock_log_entry.external_id = None
        mock_log_entry.status = "failed"
        mock_log_entry.error_message = "No active xero connection for this organisation"
        mock_log_entry.created_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        mock_log.return_value = mock_log_entry

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        result = await sync_entity(
            db,
            org_id=uuid.uuid4(),
            provider="xero",
            entity_type="invoice",
            entity_id=uuid.uuid4(),
            entity_data={},
        )

        assert result["status"] == "failed"
        assert "No active xero connection" in result["error_message"]

    @pytest.mark.asyncio
    @patch("app.modules.accounting.service._log_sync")
    @patch("app.modules.accounting.service._dispatch_sync")
    @patch("app.modules.accounting.service._ensure_valid_token")
    async def test_sync_success_logs_synced(self, mock_token, mock_dispatch, mock_log):
        mock_token.return_value = "valid_token"
        mock_dispatch.return_value = "EXT-123"

        mock_log_entry = MagicMock(spec=AccountingSyncLog)
        mock_log_entry.id = uuid.uuid4()
        mock_log_entry.provider = "xero"
        mock_log_entry.entity_type = "invoice"
        mock_log_entry.entity_id = uuid.uuid4()
        mock_log_entry.external_id = "EXT-123"
        mock_log_entry.status = "synced"
        mock_log_entry.error_message = None
        mock_log_entry.created_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        mock_log.return_value = mock_log_entry

        conn = MagicMock(spec=AccountingIntegration)
        conn.is_connected = True
        conn.last_sync_at = None

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(conn))

        result = await sync_entity(
            db,
            org_id=uuid.uuid4(),
            provider="xero",
            entity_type="invoice",
            entity_id=uuid.uuid4(),
            entity_data={"invoice_number": "INV-001"},
        )

        assert result["status"] == "synced"
        assert result["external_id"] == "EXT-123"

    @pytest.mark.asyncio
    @patch("app.modules.accounting.service._log_sync")
    @patch("app.modules.accounting.service._dispatch_sync")
    @patch("app.modules.accounting.service._ensure_valid_token")
    async def test_sync_failure_logs_error(self, mock_token, mock_dispatch, mock_log):
        mock_token.return_value = "valid_token"
        mock_dispatch.side_effect = Exception("API timeout")

        mock_log_entry = MagicMock(spec=AccountingSyncLog)
        mock_log_entry.id = uuid.uuid4()
        mock_log_entry.provider = "myob"
        mock_log_entry.entity_type = "payment"
        mock_log_entry.entity_id = uuid.uuid4()
        mock_log_entry.external_id = None
        mock_log_entry.status = "failed"
        mock_log_entry.error_message = "API timeout"
        mock_log_entry.created_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        mock_log.return_value = mock_log_entry

        conn = MagicMock(spec=AccountingIntegration)
        conn.is_connected = True

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(conn))

        result = await sync_entity(
            db,
            org_id=uuid.uuid4(),
            provider="myob",
            entity_type="payment",
            entity_id=uuid.uuid4(),
            entity_data={},
        )

        assert result["status"] == "failed"
        assert "API timeout" in result["error_message"]

    @pytest.mark.asyncio
    @patch("app.modules.accounting.service._log_sync")
    @patch("app.modules.accounting.service._ensure_valid_token")
    async def test_sync_fails_when_token_invalid(self, mock_token, mock_log):
        mock_token.return_value = None

        mock_log_entry = MagicMock(spec=AccountingSyncLog)
        mock_log_entry.id = uuid.uuid4()
        mock_log_entry.provider = "xero"
        mock_log_entry.entity_type = "credit_note"
        mock_log_entry.entity_id = uuid.uuid4()
        mock_log_entry.external_id = None
        mock_log_entry.status = "failed"
        mock_log_entry.error_message = "Failed to obtain valid access token"
        mock_log_entry.created_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        mock_log.return_value = mock_log_entry

        conn = MagicMock(spec=AccountingIntegration)
        conn.is_connected = True

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(conn))

        result = await sync_entity(
            db,
            org_id=uuid.uuid4(),
            provider="xero",
            entity_type="credit_note",
            entity_id=uuid.uuid4(),
            entity_data={},
        )

        assert result["status"] == "failed"
        assert "access token" in result["error_message"].lower()


# ---------------------------------------------------------------------------
# Service tests — get_sync_log
# ---------------------------------------------------------------------------

class TestGetSyncLog:
    """Test get_sync_log service function."""

    @pytest.mark.asyncio
    async def test_empty_log(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalars_result([]))

        result = await get_sync_log(db, org_id=uuid.uuid4())
        assert result["total"] == 0
        assert result["entries"] == []

    @pytest.mark.asyncio
    async def test_returns_log_entries(self):
        entry = MagicMock(spec=AccountingSyncLog)
        entry.id = uuid.uuid4()
        entry.provider = "xero"
        entry.entity_type = "invoice"
        entry.entity_id = uuid.uuid4()
        entry.external_id = "INV-X001"
        entry.status = "synced"
        entry.error_message = None
        entry.created_at = datetime(2024, 6, 1, tzinfo=timezone.utc)

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalars_result([entry]))

        result = await get_sync_log(db, org_id=uuid.uuid4(), provider="xero")
        assert result["total"] == 1
        assert result["entries"][0]["status"] == "synced"


# ---------------------------------------------------------------------------
# Service tests — retry_failed_syncs
# ---------------------------------------------------------------------------

class TestRetryFailedSyncs:
    """Test retry_failed_syncs service function."""

    @pytest.mark.asyncio
    async def test_no_failed_entries(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalars_result([]))

        result = await retry_failed_syncs(db, org_id=uuid.uuid4(), provider="xero")
        assert result["synced"] == 0
        assert result["failed"] == 0
        assert result["provider"] == "xero"
