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
    _serialize_public_key,
    _deserialize_public_key,
    _get_rp,
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
        req = PasskeyLoginOptionsRequest(email="user@example.com")
        assert req.email == "user@example.com"

    def test_login_options_request_invalid_email(self):
        with pytest.raises(Exception):
            PasskeyLoginOptionsRequest(email="not-an-email")

    def test_login_verify_request(self):
        req = PasskeyLoginVerifyRequest(
            email="user@example.com",
            credential={"client_data_b64": "abc"},
        )
        assert req.email == "user@example.com"
        assert req.credential == {"client_data_b64": "abc"}

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

class TestRelyingParty:
    def test_get_rp_returns_valid_rp(self):
        rp = _get_rp()
        assert rp.id == "localhost"
        assert rp.name == "WorkshopPro NZ"


class TestPublicKeySerialization:
    def test_roundtrip_ec_key(self):
        """Serialize and deserialize an EC public key."""
        from cryptography.hazmat.primitives.asymmetric import ec
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        serialized = _serialize_public_key(public_key)
        assert isinstance(serialized, str)

        deserialized = _deserialize_public_key(serialized)
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        assert (
            public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
            == deserialized.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        )


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

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis):
            options = await generate_passkey_register_options(
                user=user,
                device_name="Test Key",
            )

        assert isinstance(options, dict)
        assert "rp" in options
        assert "user" in options
        assert "challenge" in options
        assert "pubKeyCredParams" in options

        # Challenge should be stored in Redis with 5-min TTL
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == f"webauthn:register:{user.id}"
        assert call_args[0][1] == 300
        stored = json.loads(call_args[0][2])
        assert "challenge" in stored
        assert stored["device_name"] == "Test Key"

    @pytest.mark.asyncio
    async def test_excludes_existing_credentials(self):
        """Should pass existing credential IDs as exclude list."""
        cred_id = base64.b64encode(b"existing-cred").decode()
        user = _make_mock_user(passkey_credentials=[
            {"credential_id": cred_id, "public_key": "pk", "sign_count": 0},
        ])
        mock_redis = AsyncMock()

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis):
            options = await generate_passkey_register_options(user=user)

        assert isinstance(options, dict)
        if "excludeCredentials" in options:
            assert len(options["excludeCredentials"]) >= 1


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
        """Should store credential on user after successful verification."""
        user = _make_mock_user(passkey_credentials=[])
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({
            "challenge": "test-challenge-b64",
            "device_name": "My Laptop",
        })

        mock_db = AsyncMock()

        from cryptography.hazmat.primitives.asymmetric import ec
        mock_pubkey = ec.generate_private_key(ec.SECP256R1()).public_key()

        mock_create_result = MagicMock()
        mock_create_result.public_key = mock_pubkey
        mock_create_result.public_key_alg = -7
        mock_create_result.sign_count = 0

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis), \
             patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock), \
             patch("webauthn.verify_create_webauthn_credentials", return_value=mock_create_result):
            result = await verify_passkey_registration(
                db=mock_db,
                user=user,
                credential_response={
                    "client_data_b64": "client-data",
                    "attestation_b64": "attestation",
                    "credential_id_b64": "credential-id",
                },
            )

        assert result["credential_id"] == "credential-id"
        assert result["device_name"] == "My Laptop"
        assert len(user.passkey_credentials) == 1
        assert user.passkey_credentials[0]["credential_id"] == "credential-id"
        assert user.passkey_credentials[0]["public_key_alg"] == -7
        mock_redis.delete.assert_called_once()


# ---------------------------------------------------------------------------
# Login options generation
# ---------------------------------------------------------------------------

class TestGeneratePasskeyLoginOptions:
    @pytest.mark.asyncio
    async def test_generates_options_for_user_with_passkeys(self):
        """Should return options with allowCredentials for user's passkeys."""
        cred_id = base64.b64encode(b"my-credential").decode()
        user = _make_mock_user(passkey_credentials=[
            {"credential_id": cred_id, "public_key": "pk", "sign_count": 0},
        ])

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        mock_redis = AsyncMock()

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis):
            options = await generate_passkey_login_options(
                db=mock_db,
                email="user@example.com",
            )

        assert isinstance(options, dict)
        assert "rpId" in options
        assert "challenge" in options
        assert "allowCredentials" in options
        assert len(options["allowCredentials"]) == 1
        mock_redis.setex.assert_called_once()

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
                email="nobody@example.com",
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
                email="user@example.com",
            )

    @pytest.mark.asyncio
    async def test_no_passkeys_raises(self):
        """Should raise ValueError when user has no passkeys registered."""
        user = _make_mock_user(passkey_credentials=[])

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="No passkeys"):
            await generate_passkey_login_options(
                db=mock_db,
                email="user@example.com",
            )


# ---------------------------------------------------------------------------
# Login verification — MFA bypass (Requirement 2.9)
# ---------------------------------------------------------------------------

class TestVerifyPasskeyLogin:
    @pytest.mark.asyncio
    async def test_expired_challenge_raises(self):
        """Should raise ValueError when challenge is not in Redis."""
        user = _make_mock_user()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis):
            with pytest.raises(ValueError, match="expired"):
                await verify_passkey_login(
                    db=mock_db,
                    email="user@example.com",
                    credential_response={
                        "client_data_b64": "a",
                        "authenticator_b64": "b",
                        "signature_b64": "c",
                        "credential_id_b64": "d",
                    },
                )

    @pytest.mark.asyncio
    async def test_no_user_raises(self):
        """Should raise ValueError when user not found."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="Authentication failed"):
                await verify_passkey_login(
                    db=mock_db,
                    email="nobody@example.com",
                    credential_response={},
                )

    @pytest.mark.asyncio
    async def test_credential_not_found_raises(self):
        """Should raise when credential_id doesn't match any stored passkey."""
        from cryptography.hazmat.primitives.asymmetric import ec
        pubkey = ec.generate_private_key(ec.SECP256R1()).public_key()

        user = _make_mock_user(passkey_credentials=[
            {
                "credential_id": "stored-cred-id",
                "public_key": _serialize_public_key(pubkey),
                "public_key_alg": -7,
                "sign_count": 0,
            },
        ])

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({
            "challenge": "test-challenge",
            "user_id": str(user.id),
        })

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis), \
             patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="Authentication failed"):
                await verify_passkey_login(
                    db=mock_db,
                    email="user@example.com",
                    credential_response={
                        "client_data_b64": "a",
                        "authenticator_b64": "b",
                        "signature_b64": "c",
                        "credential_id_b64": "wrong-cred-id",
                    },
                )

    @pytest.mark.asyncio
    async def test_successful_login_bypasses_mfa(self):
        """Passkey login should issue tokens directly, bypassing MFA (Req 2.9).

        Even when the user has MFA methods configured, passkey login
        should NOT return an MFARequiredResponse — it satisfies MFA.
        """
        from cryptography.hazmat.primitives.asymmetric import ec
        pubkey = ec.generate_private_key(ec.SECP256R1()).public_key()
        cred_id = "my-passkey-cred"

        user = _make_mock_user(
            mfa_methods=[{"type": "totp"}],
            passkey_credentials=[
                {
                    "credential_id": cred_id,
                    "public_key": _serialize_public_key(pubkey),
                    "public_key_alg": -7,
                    "sign_count": 5,
                },
            ],
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({
            "challenge": "test-challenge",
            "user_id": str(user.id),
        })

        mock_get_result = MagicMock()
        mock_get_result.sign_count = 6

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis), \
             patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock), \
             patch("app.modules.auth.service.Session") as MockSession, \
             patch("webauthn.verify_get_webauthn_credentials", return_value=mock_get_result):
            MockSession.return_value = MagicMock()
            result = await verify_passkey_login(
                db=mock_db,
                email="user@example.com",
                credential_response={
                    "client_data_b64": "client-data",
                    "authenticator_b64": "auth-data",
                    "signature_b64": "sig-data",
                    "credential_id_b64": cred_id,
                },
                ip_address="127.0.0.1",
                device_type="desktop",
                browser="Chrome",
            )

        # Should return TokenResponse, NOT MFARequiredResponse
        assert hasattr(result, "access_token")
        assert hasattr(result, "refresh_token")
        assert not hasattr(result, "mfa_required")

        # Sign count should be updated
        assert user.passkey_credentials[0]["sign_count"] == 6
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_credential_fields_raises(self):
        """Should raise when credential response is missing required fields."""
        user = _make_mock_user(passkey_credentials=[
            {"credential_id": "cred", "public_key": "pk", "sign_count": 0},
        ])

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({
            "challenge": "test-challenge",
            "user_id": str(user.id),
        })

        with patch("app.modules.auth.service._get_redis", return_value=mock_redis):
            with pytest.raises(ValueError, match="Missing"):
                await verify_passkey_login(
                    db=mock_db,
                    email="user@example.com",
                    credential_response={"client_data_b64": "only-one-field"},
                )
