"""Unit tests for Task 6.2 — onboarding wizard API.

Tests cover:
  - save_onboarding_step: saving individual fields, multiple fields,
    skipping steps, onboarding completion tracking, audit logging
  - Schema validation: hex colour patterns, field constraints
  - Organisation not found handling

Requirements: 8.2, 8.3, 8.4, 8.5
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401 — resolve relationships

from app.modules.admin.models import Organisation
from app.modules.organisations.schemas import (
    OnboardingStepRequest,
    OnboardingStepResponse,
)
from app.modules.organisations.service import (
    ALL_ONBOARDING_FIELDS,
    save_onboarding_step,
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
# Schema tests
# ---------------------------------------------------------------------------

class TestOnboardingSchemas:
    """Test Pydantic schema validation for onboarding requests."""

    def test_empty_request_valid(self):
        """An empty request is valid — represents a skipped step."""
        req = OnboardingStepRequest()
        assert req.org_name is None
        assert req.gst_percentage is None

    def test_single_field_valid(self):
        req = OnboardingStepRequest(org_name="My Workshop")
        assert req.org_name == "My Workshop"

    def test_all_fields_valid(self):
        req = OnboardingStepRequest(
            org_name="Workshop NZ",
            logo_url="https://example.com/logo.png",
            primary_colour="#FF5733",
            secondary_colour="#33FF57",
            gst_number="123-456-789",
            gst_percentage=15.0,
            invoice_prefix="INV-",
            invoice_start_number=1,
            default_due_days=14,
            payment_terms_text="Due within 14 days",
            first_service_name="Oil Change",
            first_service_price=49.99,
        )
        assert req.org_name == "Workshop NZ"
        assert req.gst_percentage == 15.0

    def test_invalid_hex_colour_rejected(self):
        with pytest.raises(Exception):
            OnboardingStepRequest(primary_colour="not-a-colour")

    def test_valid_hex_colour_accepted(self):
        req = OnboardingStepRequest(primary_colour="#AABBCC")
        assert req.primary_colour == "#AABBCC"

    def test_gst_percentage_out_of_range_rejected(self):
        with pytest.raises(Exception):
            OnboardingStepRequest(gst_percentage=150.0)

    def test_negative_invoice_start_rejected(self):
        with pytest.raises(Exception):
            OnboardingStepRequest(invoice_start_number=0)

    def test_due_days_out_of_range_rejected(self):
        with pytest.raises(Exception):
            OnboardingStepRequest(default_due_days=400)

    def test_response_model(self):
        resp = OnboardingStepResponse(
            message="Onboarding step saved",
            updated_fields=["org_name", "gst_number"],
            onboarding_complete=False,
            skipped=False,
        )
        assert resp.message == "Onboarding step saved"
        assert len(resp.updated_fields) == 2


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------

class TestSaveOnboardingStep:
    """Test the save_onboarding_step service function."""

    @pytest.mark.asyncio
    async def test_save_org_name(self):
        """Saving org_name updates the Organisation.name column."""
        org = _make_org(name="Old Name")
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            result = await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                org_name="New Workshop Name",
            )

        assert "org_name" in result["updated_fields"]
        assert org.name == "New Workshop Name"
        assert result["skipped"] is False
        mock_audit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_brand_colours(self):
        """Saving brand colours updates the settings JSONB."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                primary_colour="#FF0000",
                secondary_colour="#00FF00",
            )

        assert "primary_colour" in result["updated_fields"]
        assert "secondary_colour" in result["updated_fields"]
        assert org.settings["primary_colour"] == "#FF0000"
        assert org.settings["secondary_colour"] == "#00FF00"

    @pytest.mark.asyncio
    async def test_save_gst_details(self):
        """Saving GST number and percentage updates settings."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                gst_number="123-456-789",
                gst_percentage=15.0,
            )

        assert "gst_number" in result["updated_fields"]
        assert "gst_percentage" in result["updated_fields"]
        assert org.settings["gst_number"] == "123-456-789"
        assert org.settings["gst_percentage"] == 15.0

    @pytest.mark.asyncio
    async def test_save_invoice_numbering(self):
        """Saving invoice prefix and starting number updates settings."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                invoice_prefix="WS-",
                invoice_start_number=100,
            )

        assert "invoice_prefix" in result["updated_fields"]
        assert "invoice_start_number" in result["updated_fields"]
        assert org.settings["invoice_prefix"] == "WS-"
        assert org.settings["invoice_start_number"] == 100

    @pytest.mark.asyncio
    async def test_save_payment_terms(self):
        """Saving payment terms updates settings."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                default_due_days=14,
                payment_terms_text="Payment due within 14 days",
            )

        assert "default_due_days" in result["updated_fields"]
        assert "payment_terms_text" in result["updated_fields"]
        assert org.settings["default_due_days"] == 14

    @pytest.mark.asyncio
    async def test_save_first_service(self):
        """Saving first service type updates settings."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                first_service_name="Oil Change",
                first_service_price=49.99,
            )

        assert "first_service_name" in result["updated_fields"]
        assert org.settings["first_service_name"] == "Oil Change"
        assert org.settings["first_service_price"] == 49.99

    @pytest.mark.asyncio
    async def test_skip_step_no_fields(self):
        """When no fields are provided, the step is skipped."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            result = await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
            )

        assert result["skipped"] is True
        assert result["updated_fields"] == []
        assert result["onboarding_complete"] is False
        # No audit log for skipped steps
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_onboarding_complete_when_all_fields_set(self):
        """Onboarding is complete when all tracked fields have been saved."""
        # Pre-populate settings with all fields except org_name
        existing_settings = {
            "logo_url": "https://example.com/logo.png",
            "primary_colour": "#FF0000",
            "secondary_colour": "#00FF00",
            "gst_number": "123-456-789",
            "gst_percentage": 15.0,
            "invoice_prefix": "INV-",
            "invoice_start_number": 1,
            "default_due_days": 14,
            "payment_terms_text": "Due in 14 days",
            "first_service_name": "Oil Change",
            "onboarding_completed_fields": [
                "default_due_days",
                "first_service_name",
                "gst_number",
                "gst_percentage",
                "invoice_prefix",
                "invoice_start_number",
                "logo_url",
                "payment_terms_text",
                "primary_colour",
                "secondary_colour",
            ],
        }
        org = _make_org(settings=existing_settings)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                org_name="Final Name",
            )

        assert result["onboarding_complete"] is True
        assert "org_name" in result["updated_fields"]

    @pytest.mark.asyncio
    async def test_onboarding_incomplete_with_missing_fields(self):
        """Onboarding is not complete when some fields are still missing."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                org_name="Partial Setup",
                gst_number="123-456-789",
            )

        assert result["onboarding_complete"] is False

    @pytest.mark.asyncio
    async def test_org_not_found_raises(self):
        """Raise ValueError when organisation doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Organisation not found"):
            await save_onboarding_step(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                org_name="Ghost Org",
            )

    @pytest.mark.asyncio
    async def test_preserves_existing_settings(self):
        """New onboarding fields merge with existing settings, not replace."""
        existing_settings = {
            "logo_url": "https://example.com/old-logo.png",
            "mfa_policy": "optional",
        }
        org = _make_org(settings=existing_settings)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                primary_colour="#123456",
            )

        # Existing settings preserved
        assert org.settings["logo_url"] == "https://example.com/old-logo.png"
        assert org.settings["mfa_policy"] == "optional"
        # New setting added
        assert org.settings["primary_colour"] == "#123456"

    @pytest.mark.asyncio
    async def test_audit_log_written_on_save(self):
        """Verify audit log is written with correct action and details."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))
        user_id = uuid.uuid4()

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=user_id,
                gst_number="111-222-333",
                ip_address="10.0.0.1",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "org.onboarding_step_saved"
        assert call_kwargs["entity_type"] == "organisation"
        assert call_kwargs["org_id"] == org.id
        assert call_kwargs["user_id"] == user_id
        assert call_kwargs["ip_address"] == "10.0.0.1"
        assert "gst_number" in call_kwargs["after_value"]

    @pytest.mark.asyncio
    async def test_completed_fields_tracked_cumulatively(self):
        """Each save accumulates completed fields in onboarding_completed_fields."""
        org = _make_org(settings={
            "onboarding_completed_fields": ["logo_url"],
            "logo_url": "https://example.com/logo.png",
        })
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await save_onboarding_step(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                gst_number="123-456-789",
            )

        completed = org.settings["onboarding_completed_fields"]
        assert "logo_url" in completed
        assert "gst_number" in completed
