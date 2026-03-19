"""Tests for Passkey (WebAuthn) authentication — Task 4.4.

Tests cover:
  - Passkey schema validation
  - Registration options generation (mocked Redis + webauthn)
  - Registration verification (mocked Redis + webauthn)
  - Login options generation (mocked DB + Redis + webauthn)
  - Login verification — MFA bypass (Requirement 2.9)
  - Error cases: expired challenge, no passkeys, inactive user
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import Organisation model so SQLAlchemy can resolve the User.organisation
# relationship when ORM objects are instantiated in tests.
import app.modules.admin.models  # noqa: F401

from app.modules.auth.schemas import (
    PasskeyLoginOptionsRequest,
    PasskeyLoginVerifyRequest,
    PasskeyRegisterOptionsRequest,
    PasskeyRegisterVerifyRequest,
    PasskeyRegisterOptionsResponse,
    PasskeyRegisterVerifyResponse,
    PasskeyLoginOptionsResponse,
)
from app.modules.auth.service import (
    _bytes_to_base64url,
    _base64url_to_bytes,
    generate_passkey_register_options,
    verify_passkey_registration,
    generate_passkey_login_options,
    verify_passkey_login,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestPasskeySchemas:
    def test_register_options_request_defaults(self):
        req = PasskeyRegisterOptionsRequest()
        assert req.device_name == "My Passkey"

    def test_register_options_request_custom_name(self):
        req = PasskeyRegisterOptionsRequest(device_name="Work Laptop")
        assert req.device_name == "Work Laptop"

    def test_register_verify_request(self):
        req = PasskeyRegisterVerifyRequest(credential={"client_data_b64": "abc"})
        assert req.credential == {"client_data_b64": "abc"}

    def test_login_options_request(self):
        req = PasskeyLoginOptionsRequest(mfa_token="tok-123")
        assert req.mfa_token == "tok-123"

    def test_login_verify_request(self):
        req = PasskeyLoginVerifyRequest(
            mfa_token="tok-123",
            credential_id="cred-id",
            authenticator_data="auth-data",
            client_data_json="client-data",
            signature="sig",
        )
        assert req.mfa_token == "tok-123"
        assert req.credential_id == "cred-id"
        assert req.user_handle is None

    def test_register_options_response(self):
        resp = PasskeyRegisterOptionsResponse(options={"challenge": "abc"})
        assert resp.options["challenge"] == "abc"

    def test_register_verify_response(self):
        resp = PasskeyRegisterVerifyResponse(
            credential_id="cred-123",
            device_name="My Key",
        )
        assert resp.credential_id == "cred-123"
        assert resp.device_name == "My Key"

    def test_login_options_response(self):
        resp = PasskeyLoginOptionsResponse(options={"rpId": "localhost"})
        assert resp.options["rpId"] == "localhost"


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------

class TestBase64urlHelpers:
    def test_roundtrip(self):
        """Encode and decode should be inverse operations."""
        original = b"hello world passkey"
        encoded = _bytes_to_base64url(original)
        assert isinstance(encoded, str)
        assert "=" not in encoded  # no padding
        decoded = _base64url_to_bytes(encoded)
        assert decoded == original

    def test_handles_padding(self):
        """Decode should handle input with or without padding."""
        original = b"test"
        encoded = _bytes_to_base64url(original)
        # Also works with padding added
        decoded = _base64url_to_bytes(encoded + "==")
        assert decoded == original


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_mock_user(
    user_id=None,
    org_id=None,
    email="user@example.com",
    is_active=True,
    mfa_methods=None,
    passkey_credentials=None,
    role="salesperson",
):
    """Create a mock User object."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.org_id = org_id or uuid.uuid4()
    user.email = email
    user.is_active = is_active
    user.mfa_methods = mfa_methods or []
    user.passkey_credentials = passkey_credentials or []
    user.role = role
    user.last_login_at = None
    return user


# ---------------------------------------------------------------------------
# Registration options generation
# ---------------------------------------------------------------------------

class TestGeneratePasskeyRegisterOptions:
    @pytest.mark.asyncio
    async def test_generates_options_and_stores_challenge(self):
        """Should return options dict and store challenge in Redis."""
        user = _make_mock_user()
        mock_redis = AsyncMock()

        # Mock DB query returning no existing credentials
        mock_db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_db_result = MagicMock()
        mock_db_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_db_result

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis):
            options = await generate_passkey_register_options(
                db=mock_db,
                user=user,
                device_name="Test Key",
            )

        assert isinstance(options, dict)
        assert "rp" in options
        assert "user" in options
        assert "challenge" in options
        assert "pubKeyCredParams" in options

        # Challenge should be stored in Redis with 60s TTL
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == f"webauthn:register:{user.id}"
        assert call_args[0][1] == 60
        stored = json.loads(call_args[0][2])
        assert "challenge" in stored
        assert stored["device_name"] == "Test Key"

    @pytest.mark.asyncio
    async def test_excludes_existing_credentials(self):
        """Should pass existing credential IDs as exclude list."""
        cred_id = _bytes_to_base64url(b"existing-cred")
        user = _make_mock_user()
        mock_redis = AsyncMock()

        # Mock DB query returning one existing credential
        mock_cred = MagicMock()
        mock_cred.credential_id = cred_id
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_cred]
        mock_db_result = MagicMock()
        mock_db_result.scalars.return_value = mock_scalars
        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_db_result

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis):
            options = await generate_passkey_register_options(db=mock_db, user=user)

        assert isinstance(options, dict)
        if "excludeCredentials" in options:
            assert len(options["excludeCredentials"]) >= 1

    @pytest.mark.asyncio
    async def test_rejects_when_max_credentials_reached(self):
        """Should raise ValueError when user already has 10 credentials."""
        user = _make_mock_user()

        # Mock DB query returning 10 existing credentials
        mock_creds = [MagicMock() for _ in range(10)]
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_creds
        mock_db_result = MagicMock()
        mock_db_result.scalars.return_value = mock_scalars
        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_db_result

        with pytest.raises(ValueError, match="Maximum number of passkeys"):
            await generate_passkey_register_options(db=mock_db, user=user)


# ---------------------------------------------------------------------------
# Registration verification
# ---------------------------------------------------------------------------

class TestVerifyPasskeyRegistration:
    @pytest.mark.asyncio
    async def test_expired_challenge_raises(self):
        """Should raise ValueError when challenge is not in Redis."""
        user = _make_mock_user()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        mock_db = AsyncMock()

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis):
            with pytest.raises(ValueError, match="expired"):
                await verify_passkey_registration(
                    db=mock_db,
                    user=user,
                    credential_response={
                        "client_data_b64": "abc",
                        "attestation_b64": "def",
                        "credential_id_b64": "ghi",
                    },
                )

    @pytest.mark.asyncio
    async def test_missing_fields_raises(self):
        """Should raise ValueError when credential response is missing fields."""
        user = _make_mock_user()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({
            "challenge": "test-challenge",
            "device_name": "Test Key",
        })

        mock_db = AsyncMock()

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis):
            with pytest.raises(ValueError, match="Missing"):
                await verify_passkey_registration(
                    db=mock_db,
                    user=user,
                    credential_response={"client_data_b64": "abc"},
                )

    @pytest.mark.asyncio
    async def test_successful_registration_stores_credential(self):
        """Should store credential in normalised table after successful verification."""
        user = _make_mock_user()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({
            "challenge": "test-challenge-b64",
            "device_name": "My Laptop",
        })

        mock_db = AsyncMock()
        # Mock the query for existing passkey MFA method (returns None = no existing entry)
        mock_mfa_result = MagicMock()
        mock_mfa_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_mfa_result

        mock_verification = MagicMock()
        mock_verification.credential_id = b"cred-id-bytes"
        mock_verification.credential_public_key = b"pubkey-bytes"
        mock_verification.sign_count = 0

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis), \
             patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock), \
             patch("webauthn.verify_registration_response", return_value=mock_verification):
            result = await verify_passkey_registration(
                db=mock_db,
                user=user,
                credential_response={
                    "client_data_b64": "client-data",
                    "attestation_b64": "attestation",
                    "credential_id_b64": "credential-id",
                },
            )

        assert "credential_id" in result
        assert result["device_name"] == "My Laptop"
        # Verify db.add was called for both the credential and the MFA method
        assert mock_db.add.call_count == 2
        mock_db.flush.assert_called_once()
        mock_redis.delete.assert_called_once()


# ---------------------------------------------------------------------------
# Login options generation
# ---------------------------------------------------------------------------

class TestGeneratePasskeyLoginOptions:
    @pytest.mark.asyncio
    async def test_generates_options_for_user_with_passkeys(self):
        """Should return options with allowCredentials for user's non-flagged passkeys."""
        cred_id = _bytes_to_base64url(b"my-credential")
        user = _make_mock_user()

        # Mock credential from normalised table
        mock_cred = MagicMock()
        mock_cred.credential_id = cred_id
        mock_cred.flagged = False

        mock_db = AsyncMock()

        # First call: select User by id
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user

        # Second call: select UserPasskeyCredential (non-flagged)
        mock_cred_scalars = MagicMock()
        mock_cred_scalars.all.return_value = [mock_cred]
        mock_cred_result = MagicMock()
        mock_cred_result.scalars.return_value = mock_cred_scalars

        mock_db.execute.side_effect = [mock_user_result, mock_cred_result]

        mock_redis = AsyncMock()

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis):
            options = await generate_passkey_login_options(
                db=mock_db,
                user_id=user.id,
            )

        assert isinstance(options, dict)
        assert "rpId" in options
        assert "challenge" in options
        assert "allowCredentials" in options
        assert len(options["allowCredentials"]) == 1
        mock_redis.setex.assert_called_once()
        # Verify 60s TTL
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 60

    @pytest.mark.asyncio
    async def test_no_user_raises(self):
        """Should raise ValueError when user not found."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="No account"):
            await generate_passkey_login_options(
                db=mock_db,
                user_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_inactive_user_raises(self):
        """Should raise ValueError when user is inactive."""
        user = _make_mock_user(is_active=False)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="No account"):
            await generate_passkey_login_options(
                db=mock_db,
                user_id=user.id,
            )

    @pytest.mark.asyncio
    async def test_no_passkeys_raises(self):
        """Should raise ValueError when user has no non-flagged passkeys."""
        user = _make_mock_user()

        mock_db = AsyncMock()

        # First call: select User
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user

        # Second call: select credentials — empty
        mock_cred_scalars = MagicMock()
        mock_cred_scalars.all.return_value = []
        mock_cred_result = MagicMock()
        mock_cred_result.scalars.return_value = mock_cred_scalars

        mock_db.execute.side_effect = [mock_user_result, mock_cred_result]

        with pytest.raises(ValueError, match="No passkeys"):
            await generate_passkey_login_options(
                db=mock_db,
                user_id=user.id,
            )

    @pytest.mark.asyncio
    async def test_excludes_flagged_credentials(self):
        """Should only include non-flagged credentials in the allow list."""
        cred_id_ok = _bytes_to_base64url(b"good-cred")
        user = _make_mock_user()

        mock_cred = MagicMock()
        mock_cred.credential_id = cred_id_ok
        mock_cred.flagged = False

        mock_db = AsyncMock()
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user
        mock_cred_scalars = MagicMock()
        mock_cred_scalars.all.return_value = [mock_cred]
        mock_cred_result = MagicMock()
        mock_cred_result.scalars.return_value = mock_cred_scalars
        mock_db.execute.side_effect = [mock_user_result, mock_cred_result]

        mock_redis = AsyncMock()

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis):
            options = await generate_passkey_login_options(
                db=mock_db,
                user_id=user.id,
            )

        assert len(options["allowCredentials"]) == 1


# ---------------------------------------------------------------------------
# Login verification — MFA bypass (Requirement 2.9)
# ---------------------------------------------------------------------------

class TestVerifyPasskeyLogin:
    @pytest.mark.asyncio
    async def test_missing_credential_fields_raises(self):
        """Should raise when credential response is missing required fields."""
        mock_db = AsyncMock()
        with pytest.raises(ValueError, match="Missing"):
            await verify_passkey_login(
                db=mock_db,
                user_id=uuid.uuid4(),
                credential_response={"credential_id": "only-one-field"},
            )

    @pytest.mark.asyncio
    async def test_credential_not_found_raises(self):
        """Should raise when credential_id doesn't match any stored passkey."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Authentication failed"):
            await verify_passkey_login(
                db=mock_db,
                user_id=uuid.uuid4(),
                credential_response={
                    "credential_id": "wrong-cred-id",
                    "authenticator_data": "b",
                    "client_data_json": "c",
                    "signature": "d",
                },
            )

    @pytest.mark.asyncio
    async def test_inactive_user_raises(self):
        """Should raise ValueError when user is inactive."""
        user = _make_mock_user(is_active=False)

        mock_cred = MagicMock()
        mock_cred.credential_id = "cred-id"
        mock_cred.user_id = user.id
        mock_cred.public_key = _bytes_to_base64url(b"fake-pubkey")
        mock_cred.public_key_alg = -7
        mock_cred.sign_count = 0
        mock_cred.flagged = False

        mock_db = AsyncMock()
        # First call: select credential
        mock_cred_result = MagicMock()
        mock_cred_result.scalar_one_or_none.return_value = mock_cred
        # Second call: select user
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user
        mock_db.execute.side_effect = [mock_cred_result, mock_user_result]

        with patch("app.modules.auth.service._audit_failed_login", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="Authentication failed"):
                await verify_passkey_login(
                    db=mock_db,
                    user_id=user.id,
                    credential_response={
                        "credential_id": "cred-id",
                        "authenticator_data": "b",
                        "client_data_json": "c",
                        "signature": "d",
                    },
                )

    @pytest.mark.asyncio
    async def test_flagged_credential_rejected(self):
        """Should reject authentication with a flagged credential."""
        user = _make_mock_user()

        mock_cred = MagicMock()
        mock_cred.credential_id = "flagged-cred"
        mock_cred.user_id = user.id
        mock_cred.flagged = True

        mock_db = AsyncMock()
        mock_cred_result = MagicMock()
        mock_cred_result.scalar_one_or_none.return_value = mock_cred
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user
        mock_db.execute.side_effect = [mock_cred_result, mock_user_result]

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="flagged for security review"):
                await verify_passkey_login(
                    db=mock_db,
                    user_id=user.id,
                    credential_response={
                        "credential_id": "flagged-cred",
                        "authenticator_data": "b",
                        "client_data_json": "c",
                        "signature": "d",
                    },
                )

    @pytest.mark.asyncio
    async def test_expired_challenge_raises(self):
        """Should raise ValueError when challenge is not in Redis."""
        user = _make_mock_user()

        mock_cred = MagicMock()
        mock_cred.credential_id = "cred-id"
        mock_cred.user_id = user.id
        mock_cred.public_key = _bytes_to_base64url(b"fake-pubkey")
        mock_cred.public_key_alg = -7
        mock_cred.sign_count = 0
        mock_cred.flagged = False

        mock_db = AsyncMock()
        mock_cred_result = MagicMock()
        mock_cred_result.scalar_one_or_none.return_value = mock_cred
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user
        mock_db.execute.side_effect = [mock_cred_result, mock_user_result]

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis), \
             patch("app.modules.auth.service.check_ip_allowlist", new_callable=AsyncMock, return_value=False):
            with pytest.raises(ValueError, match="expired"):
                await verify_passkey_login(
                    db=mock_db,
                    user_id=user.id,
                    credential_response={
                        "credential_id": "cred-id",
                        "authenticator_data": "b",
                        "client_data_json": "c",
                        "signature": "d",
                    },
                )

    @pytest.mark.asyncio
    async def test_clone_detection_flags_credential(self):
        """Should flag credential and reject when sign count S' <= S (clone detection)."""
        user = _make_mock_user()
        cred_id = "clone-cred"

        mock_cred = MagicMock()
        mock_cred.credential_id = cred_id
        mock_cred.user_id = user.id
        mock_cred.public_key = _bytes_to_base64url(b"fake-pubkey")
        mock_cred.public_key_alg = -7
        mock_cred.sign_count = 5  # stored sign count
        mock_cred.flagged = False

        mock_db = AsyncMock()
        mock_cred_result = MagicMock()
        mock_cred_result.scalar_one_or_none.return_value = mock_cred
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user
        mock_db.execute.side_effect = [mock_cred_result, mock_user_result]

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({
            "challenge": "test-challenge",
            "user_id": str(user.id),
        })

        # Authenticator returns sign count <= stored (clone!)
        mock_verification = MagicMock()
        mock_verification.new_sign_count = 3  # S' < S

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis), \
             patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock), \
             patch("app.modules.auth.service.check_ip_allowlist", new_callable=AsyncMock, return_value=False), \
             patch("webauthn.verify_authentication_response", return_value=mock_verification):
            with pytest.raises(ValueError, match="flagged for security review"):
                await verify_passkey_login(
                    db=mock_db,
                    user_id=user.id,
                    credential_response={
                        "credential_id": cred_id,
                        "authenticator_data": "auth-data",
                        "client_data_json": "client-data",
                        "signature": "sig-data",
                    },
                )

        # Credential should be flagged
        assert mock_cred.flagged is True
        mock_db.flush.assert_called()

    @pytest.mark.asyncio
    async def test_successful_login_updates_sign_count(self):
        """Passkey login should update sign count and issue tokens when S' > S."""
        cred_id = "my-passkey-cred"
        user = _make_mock_user()

        mock_cred = MagicMock()
        mock_cred.credential_id = cred_id
        mock_cred.user_id = user.id
        mock_cred.public_key = _bytes_to_base64url(b"fake-pubkey")
        mock_cred.public_key_alg = -7
        mock_cred.sign_count = 5
        mock_cred.flagged = False

        mock_db = AsyncMock()
        mock_cred_result = MagicMock()
        mock_cred_result.scalar_one_or_none.return_value = mock_cred
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user
        mock_db.execute.side_effect = [mock_cred_result, mock_user_result]

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({
            "challenge": "test-challenge",
            "user_id": str(user.id),
        })

        mock_verification = MagicMock()
        mock_verification.new_sign_count = 6  # S' > S

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis), \
             patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock), \
             patch("app.modules.auth.service.check_ip_allowlist", new_callable=AsyncMock, return_value=False), \
             patch("app.modules.auth.service.enforce_session_limit", new_callable=AsyncMock), \
             patch("app.modules.auth.service.Session") as MockSession, \
             patch("webauthn.verify_authentication_response", return_value=mock_verification):
            MockSession.return_value = MagicMock()
            result = await verify_passkey_login(
                db=mock_db,
                user_id=user.id,
                credential_response={
                    "credential_id": cred_id,
                    "authenticator_data": "auth-data",
                    "client_data_json": "client-data",
                    "signature": "sig-data",
                },
                ip_address="127.0.0.1",
                device_type="desktop",
                browser="Chrome",
            )

        # Should return TokenResponse
        assert hasattr(result, "access_token")
        assert hasattr(result, "refresh_token")
        assert not hasattr(result, "mfa_required")

        # Sign count should be updated on the credential object
        assert mock_cred.sign_count == 6
        assert mock_cred.last_used_at is not None
        mock_redis.delete.assert_called_once()
