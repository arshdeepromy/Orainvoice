"""Unit tests for the pending_signup Redis service module.

Covers create, get, delete, replace, and password hashing behaviour.
Requirements: 1.1, 6.1, 6.2, 6.3, 7.2
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.auth.pending_signup import (
    PENDING_SIGNUP_TTL,
    create_pending_signup,
    delete_pending_signup,
    get_pending_signup,
    replace_pending_signup_for_email,
    _signup_key,
    _email_index_key,
)


def _sample_data(**overrides) -> dict:
    base = {
        "org_name": "Acme Corp",
        "admin_email": "admin@acme.test",
        "admin_first_name": "Jane",
        "admin_last_name": "Doe",
        "password": "S3cret!Pass",
        "plan_id": "plan-123",
        "plan_name": "Professional",
        "payment_amount_cents": 4900,
        "stripe_payment_intent_id": "pi_test_abc",
        "coupon_code": None,
        "coupon_discount_type": None,
        "coupon_discount_value": None,
        "ip_address": "127.0.0.1",
        "created_at": "2025-01-15T10:30:00Z",
    }
    base.update(overrides)
    return base


def _make_mock_redis():
    """Build a MagicMock redis whose pipeline() is sync, execute() is async."""
    redis = MagicMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock()
    redis.pipeline.return_value = pipe
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock()
    redis.setex = AsyncMock()
    return redis, pipe


# ---------------------------------------------------------------------------
# create_pending_signup
# ---------------------------------------------------------------------------


class TestCreatePendingSignup:

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_returns_uuid_string(self, mock_redis_module):
        redis, pipe = _make_mock_redis()
        mock_redis_module.pipeline = redis.pipeline
        mock_redis_module.get = redis.get

        result = await create_pending_signup(_sample_data())

        parts = result.split("-")
        assert len(parts) == 5

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_stores_with_correct_ttl(self, mock_redis_module):
        redis, pipe = _make_mock_redis()
        mock_redis_module.pipeline = redis.pipeline

        pending_id = await create_pending_signup(_sample_data())

        assert pipe.setex.call_count == 2

        signup_call = pipe.setex.call_args_list[0]
        assert signup_call[0][0] == _signup_key(pending_id)
        assert signup_call[0][1] == PENDING_SIGNUP_TTL

        email_call = pipe.setex.call_args_list[1]
        assert email_call[0][0] == _email_index_key("admin@acme.test")
        assert email_call[0][1] == PENDING_SIGNUP_TTL
        assert email_call[0][2] == pending_id

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_password_hashed_before_storage(self, mock_redis_module):
        redis, pipe = _make_mock_redis()
        mock_redis_module.pipeline = redis.pipeline

        await create_pending_signup(_sample_data())

        stored_json = pipe.setex.call_args_list[0][0][2]
        stored = json.loads(stored_json)

        assert "password" not in stored
        assert "password_hash" in stored
        assert stored["password_hash"].startswith("$2b$")

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_email_index_key_uses_sha256(self, mock_redis_module):
        redis, pipe = _make_mock_redis()
        mock_redis_module.pipeline = redis.pipeline

        await create_pending_signup(_sample_data())

        email_key = pipe.setex.call_args_list[1][0][0]
        assert email_key.startswith("pending_email:")
        digest_part = email_key.split("pending_email:")[1]
        assert len(digest_part) == 64


# ---------------------------------------------------------------------------
# get_pending_signup
# ---------------------------------------------------------------------------


class TestGetPendingSignup:

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_returns_parsed_dict(self, mock_redis):
        data = {"org_name": "Test", "admin_email": "a@b.com"}
        mock_redis.get = AsyncMock(return_value=json.dumps(data))

        result = await get_pending_signup("some-id")

        assert result == data
        mock_redis.get.assert_called_once_with(_signup_key("some-id"))

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_returns_none_when_missing(self, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)

        result = await get_pending_signup("nonexistent")

        assert result is None


# ---------------------------------------------------------------------------
# delete_pending_signup
# ---------------------------------------------------------------------------


class TestDeletePendingSignup:

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_deletes_both_keys(self, mock_redis):
        data = {"admin_email": "admin@acme.test"}
        mock_redis.get = AsyncMock(return_value=json.dumps(data))
        mock_redis.delete = AsyncMock()

        await delete_pending_signup("abc-123")

        mock_redis.delete.assert_called_once()
        deleted_keys = mock_redis.delete.call_args[0]
        assert _signup_key("abc-123") in deleted_keys
        assert _email_index_key("admin@acme.test") in deleted_keys

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_deletes_signup_key_only_when_no_data(self, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.delete = AsyncMock()

        await delete_pending_signup("gone-id")

        mock_redis.delete.assert_called_once_with(_signup_key("gone-id"))


# ---------------------------------------------------------------------------
# replace_pending_signup_for_email
# ---------------------------------------------------------------------------


class TestReplacePendingSignupForEmail:

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.delete_pending_signup", new_callable=AsyncMock)
    @patch("app.modules.auth.pending_signup.create_pending_signup", new_callable=AsyncMock)
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_replaces_existing(self, mock_redis, mock_create, mock_delete):
        mock_redis.get = AsyncMock(return_value="old-id")
        mock_create.return_value = "new-id"

        result = await replace_pending_signup_for_email(
            "admin@acme.test", _sample_data()
        )

        mock_delete.assert_called_once_with("old-id")
        mock_create.assert_called_once()
        assert result == "new-id"

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.delete_pending_signup", new_callable=AsyncMock)
    @patch("app.modules.auth.pending_signup.create_pending_signup", new_callable=AsyncMock)
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_creates_new_when_no_existing(self, mock_redis, mock_create, mock_delete):
        mock_redis.get = AsyncMock(return_value=None)
        mock_create.return_value = "fresh-id"

        result = await replace_pending_signup_for_email(
            "new@user.test", _sample_data(admin_email="new@user.test")
        )

        mock_delete.assert_not_called()
        mock_create.assert_called_once()
        assert result == "fresh-id"
