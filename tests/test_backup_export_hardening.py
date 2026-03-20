"""Tests for integration backup export hardening (REM-04).

Covers:
- Password re-confirmation via x-confirm-password header
- Secret redaction in exported config
- Audit logging on successful export
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.admin.service import _redact_config, _REDACTED_FIELDS


# ---------------------------------------------------------------------------
# _redact_config unit tests
# ---------------------------------------------------------------------------

class TestRedactConfig:
    """Unit tests for the _redact_config helper."""

    def test_redacts_all_sensitive_fields(self):
        config = {
            "api_key": "sk-live-abc123",
            "auth_token": "tok_xyz",
            "password": "hunter2",
            "secret": "s3cr3t",
            "token": "refresh_tok",
            "credentials": "cred_blob",
        }
        result = _redact_config(config)
        for key in _REDACTED_FIELDS:
            assert result[key] == "***REDACTED***"

    def test_preserves_non_sensitive_fields(self):
        config = {
            "host": "smtp.example.com",
            "port": 587,
            "api_key": "sk-live-abc123",
            "display_name": "My SMTP",
        }
        result = _redact_config(config)
        assert result["host"] == "smtp.example.com"
        assert result["port"] == 587
        assert result["display_name"] == "My SMTP"
        assert result["api_key"] == "***REDACTED***"

    def test_empty_dict_returns_empty(self):
        assert _redact_config({}) == {}

    def test_no_sensitive_keys_unchanged(self):
        config = {"host": "localhost", "port": 5432, "name": "mydb"}
        result = _redact_config(config)
        assert result == config

    def test_mixed_types_preserved(self):
        config = {
            "enabled": True,
            "count": 42,
            "tags": ["a", "b"],
            "token": "should_be_redacted",
        }
        result = _redact_config(config)
        assert result["enabled"] is True
        assert result["count"] == 42
        assert result["tags"] == ["a", "b"]
        assert result["token"] == "***REDACTED***"


# ---------------------------------------------------------------------------
# Backup endpoint password re-confirmation tests
# ---------------------------------------------------------------------------

class TestBackupPasswordReconfirmation:
    """Tests for the password re-confirmation gate on the backup endpoint."""

    @pytest.mark.asyncio
    async def test_missing_password_header_returns_401(self):
        """When x-confirm-password header is absent, return 401."""
        from app.modules.admin.router import backup_integration_settings

        request = MagicMock()
        request.headers = {}  # No x-confirm-password
        request.state = MagicMock()
        request.state.user_id = "some-user-id"
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        db = AsyncMock()

        response = await backup_integration_settings(request=request, db=db)
        assert response.status_code == 401
        assert b"Password confirmation required" in response.body

    @pytest.mark.asyncio
    async def test_wrong_password_returns_400(self):
        """When x-confirm-password doesn't match user's hash, return 400."""
        from app.modules.admin.router import backup_integration_settings

        mock_user = MagicMock()
        mock_user.password_hash = "$2b$12$fakehash"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        request = MagicMock()
        request.headers = {"x-confirm-password": "wrong-password"}
        request.state = MagicMock()
        request.state.user_id = "some-user-id"
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        with patch(
            "app.modules.auth.password.verify_password",
            return_value=False,
        ):
            response = await backup_integration_settings(request=request, db=db)

        assert response.status_code == 400
        assert b"Invalid password" in response.body

    @pytest.mark.asyncio
    async def test_correct_password_returns_backup(self):
        """When password is correct, return the backup data."""
        from app.modules.admin.router import backup_integration_settings

        mock_user = MagicMock()
        mock_user.password_hash = "$2b$12$realhash"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()

        request = MagicMock()
        request.headers = {"x-confirm-password": "correct-password"}
        request.state = MagicMock()
        request.state.user_id = "some-user-id"
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        fake_backup = {"version": 1, "integrations": {}}

        with (
            patch("app.modules.auth.password.verify_password", return_value=True),
            patch(
                "app.modules.admin.service.export_integration_settings",
                new_callable=AsyncMock,
                return_value=fake_backup,
            ),
            patch(
                "app.core.audit.write_audit_log",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            response = await backup_integration_settings(request=request, db=db)

        assert response.status_code == 200
        # Verify audit log was called
        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args
        assert call_kwargs.kwargs["action"] == "admin.integration_backup_exported"
        assert call_kwargs.kwargs["user_id"] == "some-user-id"
        assert call_kwargs.kwargs["ip_address"] == "127.0.0.1"

    @pytest.mark.asyncio
    async def test_user_not_found_returns_400(self):
        """When user_id doesn't match any user, return 400."""
        from app.modules.admin.router import backup_integration_settings

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        request = MagicMock()
        request.headers = {"x-confirm-password": "some-password"}
        request.state = MagicMock()
        request.state.user_id = "nonexistent-user"
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        response = await backup_integration_settings(request=request, db=db)
        assert response.status_code == 400
        assert b"Invalid password" in response.body
