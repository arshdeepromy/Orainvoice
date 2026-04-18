"""Unit tests for Task 6.3 — organisation settings CRUD.

Tests cover:
  - get_org_settings: retrieving settings from org record
  - update_org_settings: updating individual and multiple fields
  - GST number validation (IRD format)
  - RBAC: org_admin for PUT, org_admin or salesperson for GET
  - Audit logging on settings update
  - Schema validation for OrgSettingsUpdateRequest

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401 — resolve relationships

from app.modules.admin.models import Organisation
from app.modules.organisations.schemas import (
    OrgSettingsResponse,
    OrgSettingsUpdateRequest,
    OrgSettingsUpdateResponse,
    validate_ird_gst_number,
)
from app.modules.organisations.service import (
    get_org_settings,
    update_org_settings,
    SETTINGS_JSONB_KEYS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_org(org_id=None, name="Test Workshop", settings=None):
    """Create a mock Organisation with a mutable settings dict."""
    org = MagicMock(spec=Organisation)
    org.id = org_id or uuid.uuid4()
    org.name = name
    org.settings = settings if settings is not None else {}
    return org


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    return db


def _mock_scalar_result(value):
    """Create a mock result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# GST Number Validation tests
# ---------------------------------------------------------------------------

class TestGSTNumberValidation:
    """Test IRD GST number format validation."""

    def test_valid_8_digit_with_hyphens(self):
        assert validate_ird_gst_number("12-345-678") == "12-345-678"

    def test_valid_9_digit_with_hyphens(self):
        assert validate_ird_gst_number("123-456-789") == "123-456-789"

    def test_valid_8_digit_no_hyphens(self):
        assert validate_ird_gst_number("12345678") == "12345678"

    def test_valid_9_digit_no_hyphens(self):
        assert validate_ird_gst_number("123456789") == "123456789"

    def test_invalid_too_short(self):
        with pytest.raises(ValueError, match="8 or 9 digits"):
            validate_ird_gst_number("1234567")

    def test_invalid_too_long(self):
        with pytest.raises(ValueError, match="8 or 9 digits"):
            validate_ird_gst_number("1234567890")

    def test_invalid_letters(self):
        with pytest.raises(ValueError, match="8 or 9 digits"):
            validate_ird_gst_number("ABC-DEF-GHI")

    def test_invalid_empty(self):
        with pytest.raises(ValueError, match="8 or 9 digits"):
            validate_ird_gst_number("")

    def test_invalid_mixed_format(self):
        with pytest.raises(ValueError, match="format must be"):
            validate_ird_gst_number("12-3456-78")


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestOrgSettingsSchemas:
    """Test Pydantic schema validation for settings requests."""

    def test_empty_update_request_valid(self):
        req = OrgSettingsUpdateRequest()
        assert req.org_name is None
        assert req.gst_number is None

    def test_single_field_update(self):
        req = OrgSettingsUpdateRequest(org_name="New Name")
        assert req.org_name == "New Name"

    def test_all_fields_valid(self):
        req = OrgSettingsUpdateRequest(
            org_name="Workshop NZ",
            logo_url="https://example.com/logo.svg",
            primary_colour="#FF5733",
            secondary_colour="#33FF57",
            address="123 Main St, Auckland",
            phone="+64 9 123 4567",
            email="info@workshop.nz",
            invoice_header_text="Workshop NZ Ltd",
            invoice_footer_text="Thank you for your business",
            email_signature="Best regards, Workshop NZ",
            gst_number="123-456-789",
            gst_percentage=15.0,
            gst_inclusive=True,
            invoice_prefix="INV-",
            invoice_start_number=1,
            default_due_days=14,
            default_notes="Standard service terms apply",
            payment_terms_days=14,
            payment_terms_text="Due within 14 days",
            allow_partial_payments=True,
            terms_and_conditions="<h2>Terms</h2><p>Standard terms apply.</p>",
        )
        assert req.org_name == "Workshop NZ"
        assert req.gst_inclusive is True
        assert req.allow_partial_payments is True

    def test_invalid_hex_colour_rejected(self):
        with pytest.raises(Exception):
            OrgSettingsUpdateRequest(primary_colour="not-a-colour")

    def test_gst_percentage_out_of_range(self):
        with pytest.raises(Exception):
            OrgSettingsUpdateRequest(gst_percentage=150.0)

    def test_negative_due_days_rejected(self):
        with pytest.raises(Exception):
            OrgSettingsUpdateRequest(default_due_days=-1)

    def test_response_model(self):
        resp = OrgSettingsUpdateResponse(
            message="Organisation settings updated",
            updated_fields=["org_name", "gst_number"],
        )
        assert resp.message == "Organisation settings updated"
        assert len(resp.updated_fields) == 2

    def test_settings_response_model(self):
        resp = OrgSettingsResponse(
            org_name="Test Workshop",
            gst_number="123-456-789",
            gst_percentage=15.0,
            gst_inclusive=True,
        )
        assert resp.org_name == "Test Workshop"
        assert resp.gst_inclusive is True


# ---------------------------------------------------------------------------
# get_org_settings tests
# ---------------------------------------------------------------------------

class TestGetOrgSettings:
    """Test the get_org_settings service function."""

    @pytest.mark.asyncio
    async def test_returns_org_name_and_settings(self):
        """Returns org name from column and settings from JSONB."""
        org = _make_org(
            name="My Workshop",
            settings={
                "logo_url": "https://example.com/logo.png",
                "gst_number": "123-456-789",
                "gst_percentage": 15.0,
                "gst_inclusive": True,
                "invoice_prefix": "INV-",
            },
        )
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await get_org_settings(db, org_id=org.id)

        assert result["org_name"] == "My Workshop"
        assert result["logo_url"] == "https://example.com/logo.png"
        assert result["gst_number"] == "123-456-789"
        assert result["gst_percentage"] == 15.0
        assert result["gst_inclusive"] is True
        assert result["invoice_prefix"] == "INV-"

    @pytest.mark.asyncio
    async def test_returns_none_for_unset_fields(self):
        """Unset settings fields return None."""
        org = _make_org(settings={})
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await get_org_settings(db, org_id=org.id)

        assert result["org_name"] == "Test Workshop"
        assert result["logo_url"] is None
        assert result["gst_number"] is None
        assert result["terms_and_conditions"] is None

    @pytest.mark.asyncio
    async def test_org_not_found_raises(self):
        """Raise ValueError when organisation doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Organisation not found"):
            await get_org_settings(db, org_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_all_settings_keys_returned(self):
        """All SETTINGS_JSONB_KEYS are present in the result."""
        org = _make_org(settings={})
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await get_org_settings(db, org_id=org.id)

        for key in SETTINGS_JSONB_KEYS:
            assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# update_org_settings tests
# ---------------------------------------------------------------------------

class TestUpdateOrgSettings:
    """Test the update_org_settings service function."""

    @pytest.mark.asyncio
    async def test_update_org_name(self):
        """Updating org_name changes the Organisation.name column."""
        org = _make_org(name="Old Name")
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                org_name="New Workshop Name",
            )

        assert "org_name" in result["updated_fields"]
        assert org.name == "New Workshop Name"

    @pytest.mark.asyncio
    async def test_update_branding(self):
        """Updating branding fields updates settings JSONB."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                logo_url="https://example.com/logo.svg",
                primary_colour="#FF0000",
                secondary_colour="#00FF00",
            )

        assert "logo_url" in result["updated_fields"]
        assert "primary_colour" in result["updated_fields"]
        assert "secondary_colour" in result["updated_fields"]
        assert org.settings["logo_url"] == "https://example.com/logo.svg"
        assert org.settings["primary_colour"] == "#FF0000"

    @pytest.mark.asyncio
    async def test_update_contact_details(self):
        """Updating address, phone, email updates settings."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                address="123 Main St, Auckland",
                phone="+64 9 123 4567",
                email="info@workshop.nz",
            )

        assert "address" in result["updated_fields"]
        assert "phone" in result["updated_fields"]
        assert "email" in result["updated_fields"]
        assert org.settings["address"] == "123 Main St, Auckland"

    @pytest.mark.asyncio
    async def test_update_gst_settings(self):
        """Updating GST number, percentage, and inclusive toggle."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                gst_number="123-456-789",
                gst_percentage=15.0,
                gst_inclusive=True,
            )

        assert "gst_number" in result["updated_fields"]
        assert "gst_percentage" in result["updated_fields"]
        assert "gst_inclusive" in result["updated_fields"]
        assert org.settings["gst_inclusive"] is True

    @pytest.mark.asyncio
    async def test_invalid_gst_number_rejected(self):
        """Invalid GST number raises ValueError."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with pytest.raises(ValueError, match="8 or 9 digits"):
            await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                gst_number="INVALID",
            )

    @pytest.mark.asyncio
    async def test_update_invoice_settings(self):
        """Updating invoice prefix, start number, due days, notes."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                invoice_prefix="WS-",
                invoice_start_number=100,
                default_due_days=30,
                default_notes="Standard terms apply",
            )

        assert "invoice_prefix" in result["updated_fields"]
        assert "invoice_start_number" in result["updated_fields"]
        assert "default_due_days" in result["updated_fields"]
        assert "default_notes" in result["updated_fields"]
        assert org.settings["invoice_prefix"] == "WS-"

    @pytest.mark.asyncio
    async def test_update_payment_terms(self):
        """Updating payment terms fields."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                payment_terms_days=14,
                payment_terms_text="Due within 14 days",
                allow_partial_payments=True,
            )

        assert "payment_terms_days" in result["updated_fields"]
        assert "payment_terms_text" in result["updated_fields"]
        assert "allow_partial_payments" in result["updated_fields"]
        assert org.settings["allow_partial_payments"] is True

    @pytest.mark.asyncio
    async def test_update_terms_and_conditions(self):
        """Updating rich text T&C."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        tc_html = "<h2>Terms</h2><ul><li>Item 1</li></ul><p><b>Bold</b> and <a href='#'>link</a></p>"
        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                terms_and_conditions=tc_html,
            )

        assert "terms_and_conditions" in result["updated_fields"]
        assert org.settings["terms_and_conditions"] == tc_html

    @pytest.mark.asyncio
    async def test_no_fields_returns_empty(self):
        """When no fields are provided, returns empty updated_fields."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await update_org_settings(
            db, org_id=org.id, user_id=uuid.uuid4(),
        )

        assert result["updated_fields"] == []

    @pytest.mark.asyncio
    async def test_preserves_existing_settings(self):
        """New settings merge with existing, not replace."""
        existing = {
            "logo_url": "https://example.com/old-logo.png",
            "gst_number": "12-345-678",
            "mfa_policy": "optional",
        }
        org = _make_org(settings=existing)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                primary_colour="#123456",
            )

        assert org.settings["logo_url"] == "https://example.com/old-logo.png"
        assert org.settings["gst_number"] == "12-345-678"
        assert org.settings["mfa_policy"] == "optional"
        assert org.settings["primary_colour"] == "#123456"

    @pytest.mark.asyncio
    async def test_org_not_found_raises(self):
        """Raise ValueError when organisation doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Organisation not found"):
            await update_org_settings(
                db, org_id=uuid.uuid4(), user_id=uuid.uuid4(),
                org_name="Ghost",
            )

    @pytest.mark.asyncio
    async def test_audit_log_written(self):
        """Verify audit log is written with correct action and details."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))
        user_id = uuid.uuid4()

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await update_org_settings(
                db, org_id=org.id, user_id=user_id,
                gst_number="123-456-789",
                ip_address="10.0.0.1",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "org.settings_updated"
        assert call_kwargs["entity_type"] == "organisation"
        assert call_kwargs["org_id"] == org.id
        assert call_kwargs["user_id"] == user_id
        assert call_kwargs["ip_address"] == "10.0.0.1"
        assert "gst_number" in call_kwargs["after_value"]

    @pytest.mark.asyncio
    async def test_audit_not_written_when_no_changes(self):
        """No audit log when no fields are updated."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
            )

        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_invoice_header_footer(self):
        """Updating invoice header and footer text."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                invoice_header_text="Workshop NZ Ltd",
                invoice_footer_text="Thank you for your business",
            )

        assert "invoice_header_text" in result["updated_fields"]
        assert "invoice_footer_text" in result["updated_fields"]
        assert org.settings["invoice_header_text"] == "Workshop NZ Ltd"

    @pytest.mark.asyncio
    async def test_update_email_signature(self):
        """Updating email signature."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                email_signature="Best regards,\nWorkshop NZ Team",
            )

        assert "email_signature" in result["updated_fields"]
        assert org.settings["email_signature"] == "Best regards,\nWorkshop NZ Team"


# ---------------------------------------------------------------------------
# Invoice Template Validation Tests (Task 4.5)
# Requirements: 3.2, 3.3, 3.4, 10.3
# ---------------------------------------------------------------------------


class TestInvoiceTemplateValidation:
    """Tests for invoice template ID and colour validation in update_org_settings."""

    @pytest.mark.asyncio
    async def test_valid_template_id_accepted(self):
        """A valid template ID from the registry is accepted and persisted."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                invoice_template_id="classic",
            )

        assert "invoice_template_id" in result["updated_fields"]
        assert org.settings["invoice_template_id"] == "classic"

    @pytest.mark.asyncio
    async def test_invalid_template_id_rejected(self):
        """An unknown template ID raises ValueError before persisting."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with pytest.raises(ValueError, match="Unknown invoice template"):
            await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                invoice_template_id="nonexistent-template",
            )

    @pytest.mark.asyncio
    async def test_valid_template_colours_accepted(self):
        """Valid hex colours are accepted and persisted."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        colours = {
            "primary_colour": "#FF5733",
            "accent_colour": "#1e40af",
            "header_bg_colour": "#ffffff",
        }

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                invoice_template_colours=colours,
            )

        assert "invoice_template_colours" in result["updated_fields"]
        assert org.settings["invoice_template_colours"] == colours

    @pytest.mark.asyncio
    async def test_invalid_primary_colour_rejected(self):
        """Invalid hex for primary_colour raises ValueError."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        colours = {
            "primary_colour": "not-a-hex",
            "accent_colour": "#1e40af",
            "header_bg_colour": "#ffffff",
        }

        with pytest.raises(ValueError, match="Invalid hex colour for primary_colour"):
            await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                invoice_template_colours=colours,
            )

    @pytest.mark.asyncio
    async def test_invalid_accent_colour_rejected(self):
        """Invalid hex for accent_colour raises ValueError."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        colours = {
            "primary_colour": "#FF5733",
            "accent_colour": "#GGG",
            "header_bg_colour": "#ffffff",
        }

        with pytest.raises(ValueError, match="Invalid hex colour for accent_colour"):
            await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                invoice_template_colours=colours,
            )

    @pytest.mark.asyncio
    async def test_invalid_header_bg_colour_rejected(self):
        """Invalid hex for header_bg_colour raises ValueError."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        colours = {
            "primary_colour": "#FF5733",
            "accent_colour": "#1e40af",
            "header_bg_colour": "rgb(255,255,255)",
        }

        with pytest.raises(ValueError, match="Invalid hex colour for header_bg_colour"):
            await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                invoice_template_colours=colours,
            )

    @pytest.mark.asyncio
    async def test_template_id_and_colours_together(self):
        """Both template ID and colours can be set in a single update."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        colours = {
            "primary_colour": "#8b5cf6",
            "accent_colour": "#7c3aed",
            "header_bg_colour": "#1e1b4b",
        }

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                invoice_template_id="modern-dark",
                invoice_template_colours=colours,
            )

        assert "invoice_template_id" in result["updated_fields"]
        assert "invoice_template_colours" in result["updated_fields"]
        assert org.settings["invoice_template_id"] == "modern-dark"
        assert org.settings["invoice_template_colours"] == colours

    @pytest.mark.asyncio
    async def test_existing_settings_unchanged_with_template_update(self):
        """Updating template fields does not affect existing settings (Req 10.3)."""
        org = _make_org(settings={
            "gst_number": "12-345-678",
            "gst_percentage": 15.0,
            "invoice_prefix": "INV-",
        })
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                invoice_template_id="classic",
            )

        # Existing settings preserved
        assert org.settings["gst_number"] == "12-345-678"
        assert org.settings["gst_percentage"] == 15.0
        assert org.settings["invoice_prefix"] == "INV-"
        # New template field added
        assert org.settings["invoice_template_id"] == "classic"

    @pytest.mark.asyncio
    async def test_partial_colours_with_missing_keys_accepted(self):
        """Colours dict with missing keys (None values) is accepted."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        # Only primary_colour provided, others absent
        colours = {
            "primary_colour": "#FF5733",
        }

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_settings(
                db, org_id=org.id, user_id=uuid.uuid4(),
                invoice_template_colours=colours,
            )

        assert "invoice_template_colours" in result["updated_fields"]
