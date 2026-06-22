"""Unit tests for Task 9.3 — PUT /api/v2/organisations/slug (set/change Org_Slug).

Covers the ``update_org_slug`` service function and the ``SlugUpdate*`` schemas:
  - success: set a new slug, stored normalised (R2.7), returns the stored value
  - hard cut-over (D2): an existing slug is replaced; the old value is freed and
    recorded as the audit ``before_value`` (R2.9, R2.11)
  - normalisation: mixed-case / whitespace input is stored trimmed + lowercased
  - own-slug re-submit: the save-time uniqueness re-check excludes the requesting
    org, so re-saving the org's current slug is accepted (R3.9)
  - rejection mapping: bad format → ``slug_invalid_format`` (R2.3); reserved →
    ``slug_reserved`` (R2.4); held by another org → ``slug_taken`` (R2.6/R3.9)
  - org not found → ValueError
  - audit log + cache invalidation are invoked on success (R4.7)

Requirements: 2.1, 2.6, 2.7, 2.9, 2.11, 3.9, 4.2, 4.3, 4.7
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401 — resolve ORM relationships

from app.modules.admin.models import Organisation
from app.modules.organisations.schemas import SlugUpdateRequest, SlugUpdateResponse
from app.modules.organisations.service import SlugUpdateError, update_org_slug


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_org(org_id=None, name="Test Workshop", slug=None):
    org = MagicMock(spec=Organisation)
    org.id = org_id or uuid.uuid4()
    org.name = name
    org.slug = slug
    return org


def _mock_db_session():
    db = AsyncMock()
    db.flush = AsyncMock()
    return db


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _db_for_update(org, holder_org_id):
    """A mock db whose two ``execute`` calls return the org then the holder lookup."""
    db = _mock_db_session()
    db.execute = AsyncMock(
        side_effect=[_scalar_result(org), _scalar_result(holder_org_id)]
    )
    return db


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSlugUpdateSchemas:
    def test_request_carries_slug(self):
        req = SlugUpdateRequest(slug="Acme-Motors")
        assert req.slug == "Acme-Motors"

    def test_response_carries_slug(self):
        resp = SlugUpdateResponse(slug="acme-motors")
        assert resp.slug == "acme-motors"


# ---------------------------------------------------------------------------
# update_org_slug — success paths
# ---------------------------------------------------------------------------

class TestUpdateOrgSlugSuccess:
    @pytest.mark.asyncio
    async def test_sets_new_slug_and_returns_stored_value(self):
        org = _make_org(slug=None)
        db = _db_for_update(org, holder_org_id=None)

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.organisations.service.invalidate_org_settings_cache",
            new_callable=AsyncMock,
        ):
            stored = await update_org_slug(
                db, org_id=org.id, user_id=uuid.uuid4(), candidate="acme-motors"
            )

        assert stored == "acme-motors"
        assert org.slug == "acme-motors"
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stores_normalised_form(self):
        """Mixed-case / whitespace input is trimmed + lowercased before storage (R2.7)."""
        org = _make_org(slug=None)
        db = _db_for_update(org, holder_org_id=None)

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.organisations.service.invalidate_org_settings_cache",
            new_callable=AsyncMock,
        ):
            stored = await update_org_slug(
                db, org_id=org.id, user_id=uuid.uuid4(), candidate="  ACME-Motors  "
            )

        assert stored == "acme-motors"
        assert org.slug == "acme-motors"

    @pytest.mark.asyncio
    async def test_hard_cutover_replaces_existing_slug_and_records_previous(self):
        """An existing slug is replaced; the old value is recorded in the audit before_value (D2, R2.11)."""
        org = _make_org(slug="old-slug")
        db = _db_for_update(org, holder_org_id=None)

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit, patch(
            "app.modules.organisations.service.invalidate_org_settings_cache",
            new_callable=AsyncMock,
        ):
            stored = await update_org_slug(
                db, org_id=org.id, user_id=uuid.uuid4(), candidate="new-slug"
            )

        assert stored == "new-slug"
        assert org.slug == "new-slug"
        kwargs = mock_audit.await_args.kwargs
        assert kwargs["before_value"] == {"slug": "old-slug"}
        assert kwargs["after_value"] == {"slug": "new-slug"}
        assert kwargs["action"] == "org.slug_updated"

    @pytest.mark.asyncio
    async def test_resubmitting_own_slug_is_accepted(self):
        """The uniqueness re-check excludes the requesting org, so own slug re-save is fine (R3.9)."""
        org = _make_org(slug="acme")
        # holder lookup excludes own org → returns None even though org holds it.
        db = _db_for_update(org, holder_org_id=None)

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.organisations.service.invalidate_org_settings_cache",
            new_callable=AsyncMock,
        ):
            stored = await update_org_slug(
                db, org_id=org.id, user_id=uuid.uuid4(), candidate="acme"
            )

        assert stored == "acme"

    @pytest.mark.asyncio
    async def test_invalidates_cache_on_success(self):
        org = _make_org(slug=None)
        db = _db_for_update(org, holder_org_id=None)

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.organisations.service.invalidate_org_settings_cache",
            new_callable=AsyncMock,
        ) as mock_invalidate:
            await update_org_slug(
                db, org_id=org.id, user_id=uuid.uuid4(), candidate="acme-motors"
            )

        mock_invalidate.assert_awaited_once_with(org.id)


# ---------------------------------------------------------------------------
# update_org_slug — rejection paths
# ---------------------------------------------------------------------------

class TestUpdateOrgSlugRejections:
    @pytest.mark.asyncio
    async def test_bad_format_raises_invalid_format(self):
        """A malformed slug is rejected with code slug_invalid_format before any DB access (R2.3)."""
        db = _mock_db_session()
        db.execute = AsyncMock()

        with pytest.raises(SlugUpdateError) as exc:
            await update_org_slug(
                db, org_id=uuid.uuid4(), user_id=uuid.uuid4(), candidate="ab"
            )

        assert exc.value.code == "slug_invalid_format"
        assert exc.value.message
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_reserved_raises_slug_reserved(self):
        """A reserved slug is rejected with code slug_reserved (R2.4)."""
        db = _mock_db_session()
        db.execute = AsyncMock()

        with pytest.raises(SlugUpdateError) as exc:
            await update_org_slug(
                db, org_id=uuid.uuid4(), user_id=uuid.uuid4(), candidate="admin"
            )

        assert exc.value.code == "slug_reserved"
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_taken_by_other_org_raises_slug_taken(self):
        """A slug held by another org is rejected with code slug_taken (R2.6, R3.9)."""
        org = _make_org(slug=None)
        other_org_id = uuid.uuid4()
        db = _db_for_update(org, holder_org_id=other_org_id)

        with pytest.raises(SlugUpdateError) as exc:
            await update_org_slug(
                db, org_id=org.id, user_id=uuid.uuid4(), candidate="taken-slug"
            )

        assert exc.value.code == "slug_taken"
        # The slug must not have been written.
        assert org.slug is None
        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_org_raises_value_error(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(ValueError, match="Organisation not found"):
            await update_org_slug(
                db, org_id=uuid.uuid4(), user_id=uuid.uuid4(), candidate="acme-motors"
            )
