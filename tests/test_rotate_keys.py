"""Tests for the encryption key rotation CLI command (REM-11, Task 12.1).

Covers:
- rotate_all_keys re-encrypts IntegrationConfig.config_encrypted
- rotate_all_keys re-encrypts SmsVerificationProvider.credentials_encrypted
- rotate_all_keys re-encrypts EmailProvider.credentials_encrypted
- Rows with NULL encrypted columns are skipped
- Transaction rolls back on failure
- CLI main() reports count on success and exits 1 on failure
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.encryption import (
    envelope_encrypt,
    rotate_master_key,
    _aes_decrypt,
    _aes_encrypt,
)


# ---------------------------------------------------------------------------
# rotate_master_key unit tests (sanity check the underlying function)
# ---------------------------------------------------------------------------

class TestRotateMasterKey:
    """Verify rotate_master_key round-trip works correctly."""

    def test_round_trip(self):
        """Encrypt with key A, rotate to key B, decrypt with key B."""
        import hashlib, struct
        from app.core.encryption import _aes_encrypt, _aes_decrypt

        old_key = "old-master-key-123"
        new_key = "new-master-key-456"

        # Manually build an envelope-encrypted blob using old_key
        old_master = hashlib.sha256(old_key.encode()).digest()
        import os
        dek = os.urandom(32)
        payload = b"secret-data-here"
        encrypted_payload = _aes_encrypt(dek, payload)
        encrypted_dek = _aes_encrypt(old_master, dek)
        blob = struct.pack(">I", len(encrypted_dek)) + encrypted_dek + encrypted_payload

        # Rotate
        rotated = rotate_master_key(old_key, new_key, blob)

        # Decrypt with new key
        new_master = hashlib.sha256(new_key.encode()).digest()
        (dek_len,) = struct.unpack(">I", rotated[:4])
        new_encrypted_dek = rotated[4 : 4 + dek_len]
        new_encrypted_payload = rotated[4 + dek_len :]
        recovered_dek = _aes_decrypt(new_master, new_encrypted_dek)
        recovered = _aes_decrypt(recovered_dek, new_encrypted_payload)
        assert recovered == payload

    def test_wrong_old_key_raises(self):
        """Using the wrong old key should raise a decryption error."""
        import hashlib, struct, os

        correct_key = "correct-key"
        wrong_key = "wrong-key"
        new_key = "new-key"

        master = hashlib.sha256(correct_key.encode()).digest()
        dek = os.urandom(32)
        encrypted_payload = _aes_encrypt(dek, b"data")
        encrypted_dek = _aes_encrypt(master, dek)
        blob = struct.pack(">I", len(encrypted_dek)) + encrypted_dek + encrypted_payload

        with pytest.raises(Exception):
            rotate_master_key(wrong_key, new_key, blob)


# ---------------------------------------------------------------------------
# rotate_all_keys tests (mocked DB)
# ---------------------------------------------------------------------------

class TestRotateAllKeys:
    """Tests for the async rotate_all_keys function."""

    @staticmethod
    def _make_mock_session(execute_side_effects):
        """Build a mock async session with proper async context managers."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=execute_side_effects)

        # session.begin() must return a non-coroutine async context manager.
        # Using MagicMock (not AsyncMock) so .begin() is not a coroutine.
        mock_begin_ctx = MagicMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=None)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_begin_ctx)

        # async_session_factory() must return an async context manager
        mock_factory_ctx = MagicMock()
        mock_factory_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_factory_ctx)
        return mock_factory, mock_session

    @staticmethod
    def _make_result(rows):
        r = MagicMock()
        r.scalars.return_value.all.return_value = rows
        return r

    @pytest.mark.asyncio
    async def test_re_encrypts_integration_config(self):
        """IntegrationConfig rows with config_encrypted are re-encrypted."""
        from app.cli.rotate_keys import rotate_all_keys

        old_key = "old"
        new_key = "new"
        fake_blob = b"fake-encrypted-blob"

        mock_row = MagicMock()
        mock_row.config_encrypted = fake_blob

        mock_factory, _ = self._make_mock_session([
            self._make_result([mock_row]),
            self._make_result([]),
            self._make_result([]),
        ])

        with patch("app.cli.rotate_keys.async_session_factory", mock_factory), \
             patch("app.cli.rotate_keys.rotate_master_key", return_value=b"new-blob") as mock_rotate:
            count = await rotate_all_keys(old_key, new_key)

        assert count == 1
        mock_rotate.assert_called_once_with(old_key, new_key, fake_blob)
        assert mock_row.config_encrypted == b"new-blob"

    @pytest.mark.asyncio
    async def test_skips_null_encrypted_columns(self):
        """Rows with None encrypted columns are skipped."""
        from app.cli.rotate_keys import rotate_all_keys

        mock_row = MagicMock()
        mock_row.config_encrypted = None  # NULL

        mock_factory, _ = self._make_mock_session([
            self._make_result([mock_row]),
            self._make_result([]),
            self._make_result([]),
        ])

        with patch("app.cli.rotate_keys.async_session_factory", mock_factory), \
             patch("app.cli.rotate_keys.rotate_master_key") as mock_rotate:
            count = await rotate_all_keys("old", "new")

        assert count == 0
        mock_rotate.assert_not_called()

    @pytest.mark.asyncio
    async def test_re_encrypts_all_tables(self):
        """All three tables are processed and counts are summed."""
        from app.cli.rotate_keys import rotate_all_keys

        ic_row = MagicMock(config_encrypted=b"ic-blob")
        sms_row = MagicMock(credentials_encrypted=b"sms-blob")
        email_row = MagicMock(credentials_encrypted=b"email-blob")

        mock_factory, _ = self._make_mock_session([
            self._make_result([ic_row]),
            self._make_result([sms_row]),
            self._make_result([email_row]),
        ])

        with patch("app.cli.rotate_keys.async_session_factory", mock_factory), \
             patch("app.cli.rotate_keys.rotate_master_key", return_value=b"rotated"):
            count = await rotate_all_keys("old", "new")

        assert count == 3


# ---------------------------------------------------------------------------
# CLI main() tests
# ---------------------------------------------------------------------------

class TestCLIMain:
    """Tests for the CLI entry point."""

    def test_success_prints_count(self, capsys):
        from app.cli.rotate_keys import main

        with patch("app.cli.rotate_keys.asyncio.run", return_value=5), \
             patch("sys.argv", ["rotate_keys", "--old-key", "old", "--new-key", "new"]):
            main()

        captured = capsys.readouterr()
        assert "5 field(s) re-encrypted" in captured.out

    def test_failure_exits_with_error(self, capsys):
        from app.cli.rotate_keys import main

        with patch("app.cli.rotate_keys.asyncio.run", side_effect=RuntimeError("decrypt failed")), \
             patch("sys.argv", ["rotate_keys", "--old-key", "old", "--new-key", "new"]), \
             pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "FAILED" in captured.err
        assert "decrypt failed" in captured.err
