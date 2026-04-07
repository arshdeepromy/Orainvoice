"""Unit tests for the require_branch_module FastAPI dependency.

Tests the dependency function that gates endpoints behind the
branch_management module toggle.

Requirements: 9.1, 9.2, 9.3, 11.1, 12.1
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.organisations.router import require_branch_module


@pytest.fixture
def mock_db():
    return AsyncMock()


def _make_request(org_id: str | None = None):
    """Create a mock Request with optional org_id on state."""
    request = MagicMock()
    request.state = MagicMock()
    if org_id is not None:
        request.state.org_id = org_id
    else:
        # getattr(request.state, "org_id", None) should return None
        del request.state.org_id
        request.state.org_id = None
    return request


class TestRequireBranchModule:
    """Tests for require_branch_module dependency."""

    @pytest.mark.asyncio
    async def test_raises_403_when_module_disabled(self, mock_db):
        """When branch_management is disabled, raises HTTPException 403."""
        org_id = str(uuid.uuid4())
        request = _make_request(org_id)

        with patch.object(
            __import__("app.core.modules", fromlist=["ModuleService"]).ModuleService,
            "is_enabled",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await require_branch_module(request, mock_db)

            assert exc_info.value.status_code == 403
            assert "Branch management module is not enabled" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_passes_when_module_enabled(self, mock_db):
        """When branch_management is enabled, dependency returns without error."""
        org_id = str(uuid.uuid4())
        request = _make_request(org_id)

        with patch.object(
            __import__("app.core.modules", fromlist=["ModuleService"]).ModuleService,
            "is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await require_branch_module(request, mock_db)
            assert result is None  # No exception, returns None

    @pytest.mark.asyncio
    async def test_passes_when_no_org_context(self, mock_db):
        """When no org_id on request.state, dependency returns without error."""
        request = _make_request(org_id=None)

        # Should not even check the module — just return
        result = await require_branch_module(request, mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_error_message_matches_spec(self, mock_db):
        """The 403 detail message matches the exact spec wording."""
        org_id = str(uuid.uuid4())
        request = _make_request(org_id)

        with patch.object(
            __import__("app.core.modules", fromlist=["ModuleService"]).ModuleService,
            "is_enabled",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await require_branch_module(request, mock_db)

            assert exc_info.value.detail == (
                "Branch management module is not enabled for this organisation"
            )
