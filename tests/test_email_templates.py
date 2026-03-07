"""Unit tests for Task 15.2 — Email template customisation.

Tests cover:
  - Schema validation for template types and variables
  - Default template seeding (all 16 types)
  - Template CRUD operations (list, get, update)
  - Template preview rendering with variable substitution
  - Validation of invalid template types

Requirements: 34.1, 34.2, 34.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401

from app.modules.notifications.models import NotificationTemplate
from app.modules.notifications.schemas import (
    EMAIL_TEMPLATE_TYPES,
    DEFAULT_SUBJECTS,
    TEMPLATE_VARIABLES,
    TemplateBlock,
    TemplateListResponse,
    TemplatePreviewResponse,
    TemplateResponse,
    TemplateUpdateRequest,
    TemplateUpdateResponse,
    get_default_body_blocks,
)
from app.modules.notifications.service import (
    _template_to_dict,
    list_templates,
    get_template,
    update_template,
    render_template_preview,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestEmailTemplateTypes:
    """Verify the 16 required email template types are defined (Req 34.3)."""

    def test_exactly_16_template_types(self):
        assert len(EMAIL_TEMPLATE_TYPES) == 16

    def test_required_types_present(self):
        required = [
            "invoice_issued",
            "payment_received",
            "payment_overdue_reminder",
            "invoice_voided",
            "storage_warning_80",
            "storage_critical_90",
            "storage_full_100",
            "subscription_renewal_reminder",
            "subscription_payment_failed",
            "wof_expiry_reminder",
            "registration_expiry_reminder",
            "user_invitation",
            "password_reset",
            "mfa_enrolment",
            "login_alert",
            "account_locked",
        ]
        for t in required:
            assert t in EMAIL_TEMPLATE_TYPES, f"Missing template type: {t}"

    def test_all_types_have_default_subjects(self):
        for t in EMAIL_TEMPLATE_TYPES:
            assert t in DEFAULT_SUBJECTS, f"Missing default subject for: {t}"

    def test_all_types_have_default_body_blocks(self):
        for t in EMAIL_TEMPLATE_TYPES:
            blocks = get_default_body_blocks(t)
            assert isinstance(blocks, list), f"No default blocks for: {t}"
            assert len(blocks) > 0, f"Empty default blocks for: {t}"


class TestTemplateVariables:
    """Verify template variables are documented (Req 34.2)."""

    def test_variables_not_empty(self):
        assert len(TEMPLATE_VARIABLES) > 0

    def test_required_variables_present(self):
        var_names = {v["name"] for v in TEMPLATE_VARIABLES}
        required = [
            "customer_first_name",
            "invoice_number",
            "total_due",
            "due_date",
            "payment_link",
        ]
        for v in required:
            assert v in var_names, f"Missing variable: {v}"

    def test_variables_have_descriptions(self):
        for v in TEMPLATE_VARIABLES:
            assert "name" in v
            assert "description" in v
            assert len(v["description"]) > 0


class TestSchemaValidation:
    """Test Pydantic schema validation."""

    def test_template_block_valid(self):
        block = TemplateBlock(type="header", content="Hello")
        assert block.type == "header"
        assert block.content == "Hello"

    def test_template_block_button_with_url(self):
        block = TemplateBlock(type="button", content="Click", url="https://example.com")
        assert block.url == "https://example.com"

    def test_template_update_request_all_optional(self):
        req = TemplateUpdateRequest()
        assert req.subject is None
        assert req.body_blocks is None
        assert req.is_enabled is None

    def test_template_update_request_with_blocks(self):
        req = TemplateUpdateRequest(
            subject="Test Subject",
            body_blocks=[TemplateBlock(type="text", content="Hello")],
            is_enabled=True,
        )
        assert req.subject == "Test Subject"
        assert len(req.body_blocks) == 1
        assert req.is_enabled is True

    def test_template_response_schema(self):
        resp = TemplateResponse(
            id=str(uuid.uuid4()),
            template_type="invoice_issued",
            channel="email",
            subject="Test",
            body_blocks=[],
            is_enabled=False,
            updated_at="2025-01-15T00:00:00+00:00",
        )
        assert resp.template_type == "invoice_issued"

    def test_template_list_response(self):
        resp = TemplateListResponse(templates=[], total=0, available_variables=[])
        assert resp.total == 0

    def test_template_preview_response(self):
        resp = TemplatePreviewResponse(subject="Hi", html_body="<p>Hello</p>")
        assert resp.subject == "Hi"


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


def _make_template(
    template_type: str = "invoice_issued",
    org_id: uuid.UUID | None = None,
    **overrides,
) -> NotificationTemplate:
    """Create a NotificationTemplate instance for testing."""
    tpl = NotificationTemplate()
    tpl.id = overrides.get("id", uuid.uuid4())
    tpl.org_id = org_id or uuid.uuid4()
    tpl.template_type = template_type
    tpl.channel = overrides.get("channel", "email")
    tpl.subject = overrides.get("subject", DEFAULT_SUBJECTS.get(template_type, ""))
    tpl.body_blocks = overrides.get("body_blocks", get_default_body_blocks(template_type))
    tpl.is_enabled = overrides.get("is_enabled", False)
    tpl.updated_at = overrides.get("updated_at", datetime.now(timezone.utc))
    return tpl


class TestTemplateToDictHelper:
    """Test the _template_to_dict helper."""

    def test_converts_all_fields(self):
        tpl = _make_template()
        d = _template_to_dict(tpl)
        assert d["template_type"] == "invoice_issued"
        assert d["channel"] == "email"
        assert isinstance(d["id"], str)
        assert isinstance(d["body_blocks"], list)
        assert isinstance(d["updated_at"], str)

    def test_empty_body_blocks_returns_list(self):
        tpl = _make_template(body_blocks=None)
        tpl.body_blocks = None
        d = _template_to_dict(tpl)
        assert d["body_blocks"] == []


class TestRenderTemplatePreview:
    """Test template preview rendering (Req 34.2)."""

    def test_replaces_variables(self):
        result = render_template_preview(
            subject="Invoice {{invoice_number}}",
            body_blocks=[
                {"type": "text", "content": "Hi {{customer_first_name}}"},
            ],
        )
        assert "INV-0042" in result["subject"]
        assert "Jane" in result["html_body"]

    def test_unknown_variable_preserved(self):
        result = render_template_preview(
            subject="{{unknown_var}}",
            body_blocks=[],
        )
        assert "{{unknown_var}}" in result["subject"]

    def test_header_block_renders_h2(self):
        result = render_template_preview(
            subject="",
            body_blocks=[{"type": "header", "content": "Title"}],
        )
        assert "<h2>Title</h2>" in result["html_body"]

    def test_text_block_renders_p(self):
        result = render_template_preview(
            subject="",
            body_blocks=[{"type": "text", "content": "Paragraph"}],
        )
        assert "<p>Paragraph</p>" in result["html_body"]

    def test_button_block_renders_link(self):
        result = render_template_preview(
            subject="",
            body_blocks=[
                {"type": "button", "content": "Pay Now", "url": "{{payment_link}}"},
            ],
        )
        assert "https://pay.example.com/inv-0042" in result["html_body"]
        assert "Pay Now" in result["html_body"]

    def test_divider_block_renders_hr(self):
        result = render_template_preview(
            subject="",
            body_blocks=[{"type": "divider"}],
        )
        assert "<hr />" in result["html_body"]

    def test_image_block_renders_img(self):
        result = render_template_preview(
            subject="",
            body_blocks=[{"type": "image", "content": "Logo", "url": "https://img.example.com/logo.png"}],
        )
        assert '<img src="https://img.example.com/logo.png"' in result["html_body"]

    def test_footer_block_renders_footer(self):
        result = render_template_preview(
            subject="",
            body_blocks=[{"type": "footer", "content": "© {{org_name}}"}],
        )
        assert "Workshop Pro Demo" in result["html_body"]
        assert "<footer" in result["html_body"]

    def test_empty_subject_renders_empty(self):
        result = render_template_preview(subject=None, body_blocks=[])
        assert result["subject"] == ""
        assert result["html_body"] == ""

    def test_multiple_blocks_combined(self):
        result = render_template_preview(
            subject="Test",
            body_blocks=[
                {"type": "header", "content": "H"},
                {"type": "text", "content": "T"},
                {"type": "divider"},
            ],
        )
        assert "<h2>H</h2>" in result["html_body"]
        assert "<p>T</p>" in result["html_body"]
        assert "<hr />" in result["html_body"]


# ---------------------------------------------------------------------------
# Service layer tests with mocked DB
# ---------------------------------------------------------------------------


class TestListTemplates:
    """Test list_templates service function."""

    @pytest.mark.asyncio
    async def test_seeds_and_returns_templates(self):
        """On first access, seeds 16 templates and returns them."""
        org_id = uuid.uuid4()
        created_templates = []

        # Mock DB session
        db = AsyncMock()

        # First call: count returns 0 (no templates yet)
        # Second call: existing types returns empty
        # Third call: count returns 16 (after seeding)
        # Fourth call: select all templates
        count_result_0 = MagicMock()
        count_result_0.scalar.return_value = 0

        existing_types_result = MagicMock()
        existing_types_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        count_result_16 = MagicMock()
        count_result_16.scalar.return_value = 16

        # Create mock templates for the final select
        for ttype in EMAIL_TEMPLATE_TYPES:
            created_templates.append(_make_template(ttype, org_id=org_id))

        templates_result = MagicMock()
        templates_result.scalars.return_value = MagicMock(all=MagicMock(return_value=created_templates))

        # The function calls db.execute multiple times:
        # 1. count (seed check) -> 0
        # 2. select existing types -> empty
        # 3. flush
        # 4. count (seed check in list_templates -> _seed called again but count is now 16)
        # Actually, list_templates calls _seed first, then does its own select.
        # _seed: execute(count) -> 0, execute(existing_types) -> [], flush
        # list_templates: execute(select all) -> templates

        db.execute = AsyncMock(
            side_effect=[count_result_0, existing_types_result, templates_result]
        )
        db.flush = AsyncMock()

        result = await list_templates(db, org_id=org_id)

        assert result["total"] == 16
        assert len(result["templates"]) == 16
        assert len(result["available_variables"]) > 0

    @pytest.mark.asyncio
    async def test_already_seeded_skips_creation(self):
        """When templates already exist, skip seeding."""
        org_id = uuid.uuid4()

        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 16

        templates = [_make_template(t, org_id=org_id) for t in EMAIL_TEMPLATE_TYPES]
        templates_result = MagicMock()
        templates_result.scalars.return_value = MagicMock(all=MagicMock(return_value=templates))

        db.execute = AsyncMock(side_effect=[count_result, templates_result])

        result = await list_templates(db, org_id=org_id)

        assert result["total"] == 16
        # flush should not be called since seeding was skipped
        db.flush.assert_not_called()


class TestGetTemplate:
    """Test get_template service function."""

    @pytest.mark.asyncio
    async def test_returns_template(self):
        org_id = uuid.uuid4()
        tpl = _make_template("invoice_issued", org_id=org_id)

        db = AsyncMock()

        # Seed check: already seeded
        count_result = MagicMock()
        count_result.scalar.return_value = 16

        # Get template
        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = tpl

        db.execute = AsyncMock(side_effect=[count_result, get_result])

        result = await get_template(db, org_id=org_id, template_type="invoice_issued")

        assert result is not None
        assert result["template_type"] == "invoice_issued"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self):
        org_id = uuid.uuid4()

        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 16

        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(side_effect=[count_result, get_result])

        result = await get_template(db, org_id=org_id, template_type="nonexistent")
        assert result is None


class TestUpdateTemplate:
    """Test update_template service function."""

    @pytest.mark.asyncio
    async def test_updates_subject(self):
        org_id = uuid.uuid4()
        tpl = _make_template("invoice_issued", org_id=org_id)

        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 16

        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = tpl

        db.execute = AsyncMock(side_effect=[count_result, get_result])
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        result = await update_template(
            db,
            org_id=org_id,
            template_type="invoice_issued",
            subject="New Subject",
        )

        assert result is not None
        assert tpl.subject == "New Subject"

    @pytest.mark.asyncio
    async def test_updates_body_blocks(self):
        org_id = uuid.uuid4()
        tpl = _make_template("invoice_issued", org_id=org_id)

        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 16

        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = tpl

        db.execute = AsyncMock(side_effect=[count_result, get_result])
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        new_blocks = [{"type": "text", "content": "Custom content"}]
        result = await update_template(
            db,
            org_id=org_id,
            template_type="invoice_issued",
            body_blocks=new_blocks,
        )

        assert result is not None
        assert tpl.body_blocks == new_blocks

    @pytest.mark.asyncio
    async def test_updates_enabled_state(self):
        org_id = uuid.uuid4()
        tpl = _make_template("invoice_issued", org_id=org_id, is_enabled=False)

        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 16

        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = tpl

        db.execute = AsyncMock(side_effect=[count_result, get_result])
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        await update_template(
            db,
            org_id=org_id,
            template_type="invoice_issued",
            is_enabled=True,
        )

        assert tpl.is_enabled is True

    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self):
        org_id = uuid.uuid4()

        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 16

        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(side_effect=[count_result, get_result])

        result = await update_template(
            db,
            org_id=org_id,
            template_type="nonexistent",
            subject="X",
        )
        assert result is None
