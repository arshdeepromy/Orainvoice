"""Unit tests for Task 4.7 — session management.

Tests cover:
  - list_user_sessions: returns active sessions with correct fields and current flag
  - terminate_session: revokes a session, rejects invalid/foreign sessions
  - enforce_session_limit: revokes oldest sessions when limit exceeded
  - Schema validation
  - Config defaults
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.auth.models import Session, User
from app.modules.auth.schemas import SessionListResponse, SessionResponse, SessionTerminateResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id=None, org_id=None):
    """Create a mock User object."""
    user = MagicMock(spec=User)
    user.id = user_id or uuid.uuid4()
    user.org_id = org_id or uuid.uuid4()
    user.email = "test@example.com"
    user.role = "org_admin"
    return user


def _make_session(
    user_id,
    org_id=None,
    session_id=None,
    is_revoked=False,
    created_at=None,
    expires_at=None,
    device_type="desktop",
    browser="Chrome",
    ip_address="192.168.1.1",
):
    """Create a mock Session object."""
    s = MagicMock(spec=Session)
    s.id = session_id or uuid.uuid4()
    s.user_id = user_id
    s.org_id = org_id or uuid.uuid4()
    s.is_revoked = is_revoked
    s.device_type = device_type
    s.browser = browser
    s.ip_address = ip_address
    s.last_activity_at = created_at or datetime.now(timezone.utc)
    s.created_at = created_at or datetime.now(timezone.utc)
    s.expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(days=7))
    return s


# ---------------------------------------------------------------------------
# list_user_sessions tests
# ---------------------------------------------------------------------------

class TestListUserSessions:
    @pytest.mark.asyncio
    async def test_returns_active_sessions(self):
        """Active, non-revoked, non-expired sessions are returned."""
        from app.modules.auth.service import list_user_sessions

        user_id = uuid.uuid4()
        s1 = _make_session(user_id, device_type="desktop", browser="Chrome")
        s2 = _make_session(user_id, device_type="mobile", browser="Safari")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [s1, s2]

        db = AsyncMock()
        db.execute.return_value = mock_result

        sessions = await list_user_sessions(db=db, user_id=user_id)

        assert len(sessions) == 2
        assert sessions[0]["device_type"] == "desktop"
        assert sessions[1]["device_type"] == "mobile"

    @pytest.mark.asyncio
    async def test_current_flag_set_correctly(self):
        """The session matching current_session_id gets current=True."""
        from app.modules.auth.service import list_user_sessions

        user_id = uuid.uuid4()
        current_sid = uuid.uuid4()
        s1 = _make_session(user_id, session_id=current_sid)
        s2 = _make_session(user_id)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [s1, s2]

        db = AsyncMock()
        db.execute.return_value = mock_result

        sessions = await list_user_sessions(
            db=db, user_id=user_id, current_session_id=current_sid
        )

        current_sessions = [s for s in sessions if s["current"]]
        assert len(current_sessions) == 1
        assert current_sessions[0]["id"] == str(current_sid)

    @pytest.mark.asyncio
    async def test_empty_when_no_sessions(self):
        """Returns empty list when user has no active sessions."""
        from app.modules.auth.service import list_user_sessions

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute.return_value = mock_result

        sessions = await list_user_sessions(db=db, user_id=uuid.uuid4())
        assert sessions == []

    @pytest.mark.asyncio
    async def test_ip_address_converted_to_string(self):
        """ip_address is returned as a string."""
        from app.modules.auth.service import list_user_sessions

        user_id = uuid.uuid4()
        s1 = _make_session(user_id, ip_address="10.0.0.1")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [s1]

        db = AsyncMock()
        db.execute.return_value = mock_result

        sessions = await list_user_sessions(db=db, user_id=user_id)
        assert sessions[0]["ip_address"] == "10.0.0.1"


# ---------------------------------------------------------------------------
# terminate_session tests
# ---------------------------------------------------------------------------

class TestTerminateSession:
    @pytest.mark.asyncio
    async def test_revokes_own_session(self):
        """User can revoke their own active session."""
        from app.modules.auth.service import terminate_session

        user_id = uuid.uuid4()
        org_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session_obj = _make_session(user_id, org_id=org_id, session_id=session_id)
        session_obj.is_revoked = False

        user = _make_user(user_id=user_id, org_id=org_id)

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session_obj

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user

        db = AsyncMock()
        db.execute.side_effect = [mock_session_result, mock_user_result]

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            await terminate_session(
                db=db, session_id=session_id, user_id=user_id
            )

        assert session_obj.is_revoked is True

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_session(self):
        """Raises ValueError for a session that doesn't exist."""
        from app.modules.auth.service import terminate_session

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Session not found"):
            await terminate_session(
                db=db, session_id=uuid.uuid4(), user_id=uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_rejects_other_users_session(self):
        """Raises ValueError when trying to revoke another user's session."""
        from app.modules.auth.service import terminate_session

        other_user_id = uuid.uuid4()
        session_obj = _make_session(other_user_id)
        session_obj.is_revoked = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = session_obj

        db = AsyncMock()
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Session not found"):
            await terminate_session(
                db=db, session_id=session_obj.id, user_id=uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_rejects_already_revoked_session(self):
        """Raises ValueError for an already-revoked session."""
        from app.modules.auth.service import terminate_session

        user_id = uuid.uuid4()
        session_obj = _make_session(user_id)
        session_obj.is_revoked = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = session_obj

        db = AsyncMock()
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Session already revoked"):
            await terminate_session(
                db=db, session_id=session_obj.id, user_id=user_id
            )


# ---------------------------------------------------------------------------
# enforce_session_limit tests
# ---------------------------------------------------------------------------

class TestEnforceSessionLimit:
    @pytest.mark.asyncio
    async def test_no_revocation_under_limit(self):
        """No sessions revoked when count is below the limit."""
        from app.modules.auth.service import enforce_session_limit

        user_id = uuid.uuid4()
        sessions = [_make_session(user_id) for _ in range(3)]
        for s in sessions:
            s.is_revoked = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = sessions

        db = AsyncMock()
        db.execute.return_value = mock_result

        revoked = await enforce_session_limit(db=db, user_id=user_id, max_sessions=5)
        assert revoked == 0
        assert all(s.is_revoked is False for s in sessions)

    @pytest.mark.asyncio
    async def test_revokes_oldest_when_at_limit(self):
        """Oldest session is revoked when count equals the limit."""
        from app.modules.auth.service import enforce_session_limit

        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        sessions = [
            _make_session(user_id, created_at=now - timedelta(hours=5)),
            _make_session(user_id, created_at=now - timedelta(hours=3)),
            _make_session(user_id, created_at=now - timedelta(hours=1)),
        ]
        for s in sessions:
            s.is_revoked = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = sessions

        db = AsyncMock()
        db.execute.return_value = mock_result

        revoked = await enforce_session_limit(db=db, user_id=user_id, max_sessions=3)
        assert revoked == 1
        assert sessions[0].is_revoked is True
        assert sessions[1].is_revoked is False
        assert sessions[2].is_revoked is False

    @pytest.mark.asyncio
    async def test_revokes_multiple_when_over_limit(self):
        """Multiple oldest sessions revoked when count exceeds limit."""
        from app.modules.auth.service import enforce_session_limit

        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        sessions = [
            _make_session(user_id, created_at=now - timedelta(hours=i))
            for i in range(5, 0, -1)
        ]
        for s in sessions:
            s.is_revoked = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = sessions

        db = AsyncMock()
        db.execute.return_value = mock_result

        revoked = await enforce_session_limit(db=db, user_id=user_id, max_sessions=2)
        assert revoked == 4
        for i in range(4):
            assert sessions[i].is_revoked is True
        assert sessions[4].is_revoked is False

    @pytest.mark.asyncio
    async def test_uses_default_from_settings(self):
        """Uses settings.max_sessions_per_user when max_sessions not provided."""
        from app.modules.auth.service import enforce_session_limit

        user_id = uuid.uuid4()
        sessions = [_make_session(user_id) for _ in range(4)]
        for s in sessions:
            s.is_revoked = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = sessions

        db = AsyncMock()
        db.execute.return_value = mock_result

        with patch("app.modules.auth.service.settings") as mock_settings:
            mock_settings.max_sessions_per_user = 5
            revoked = await enforce_session_limit(db=db, user_id=user_id)

        assert revoked == 0

    @pytest.mark.asyncio
    async def test_empty_sessions_no_error(self):
        """No error when user has zero active sessions."""
        from app.modules.auth.service import enforce_session_limit

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute.return_value = mock_result

        revoked = await enforce_session_limit(
            db=db, user_id=uuid.uuid4(), max_sessions=5
        )
        assert revoked == 0


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSessionSchemas:
    def test_session_response_defaults(self):
        s = SessionResponse(id="abc-123")
        assert s.current is False
        assert s.device_type is None

    def test_session_list_response(self):
        resp = SessionListResponse(sessions=[
            SessionResponse(id="s1", device_type="desktop", current=True),
            SessionResponse(id="s2", device_type="mobile"),
        ])
        assert len(resp.sessions) == 2
        assert resp.sessions[0].current is True

    def test_session_terminate_response(self):
        resp = SessionTerminateResponse(message="Session terminated successfully")
        assert resp.message == "Session terminated successfully"


# ---------------------------------------------------------------------------
# Config test
# ---------------------------------------------------------------------------

class TestSessionConfig:
    def test_default_max_sessions(self):
        from app.config import Settings
        s = Settings()
        assert s.max_sessions_per_user == 5
