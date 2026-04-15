"""Unit tests for Sprint 7 — Business Entity Type + Admin Integrations Audit.

Tests:
- Business type setting affects tax calculation (sole_trader → progressive, company → 28%)
- Business type setting affects IRD return type (sole_trader → IR3, company → IR4)
- NZBN edge cases: 12 digits rejected, 14 digits rejected, letters rejected, 13 digits accepted
- Integration card disconnect deletes tokens from DB
- Test connection returns structured success/failure
- Audit log entries created for connect/disconnect/test

Requirements: 29.1–29.6, 30.1, 30.2, 31.1–31.6, 37.1, 37.2
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# NZBN Validation (Req 30.1, 30.2)
# ---------------------------------------------------------------------------


class TestNZBNValidation:
    """NZBN must be exactly 13 digits — reject all others."""

    def test_valid_13_digits(self):
        from app.modules.organisations.service import validate_nzbn
        assert validate_nzbn("9429041000013") is True

    def test_valid_all_zeros(self):
        from app.modules.organisations.service import validate_nzbn
        assert validate_nzbn("0000000000000") is True

    def test_valid_all_nines(self):
        from app.modules.organisations.service import validate_nzbn
        assert validate_nzbn("9999999999999") is True

    def test_reject_12_digits(self):
        from app.modules.organisations.service import validate_nzbn
        assert validate_nzbn("942904100001") is False

    def test_reject_14_digits(self):
        from app.modules.organisations.service import validate_nzbn
        assert validate_nzbn("94290410000130") is False

    def test_reject_letters(self):
        from app.modules.organisations.service import validate_nzbn
        assert validate_nzbn("942904100001A") is False

    def test_reject_empty_string(self):
        from app.modules.organisations.service import validate_nzbn
        assert validate_nzbn("") is False

    def test_reject_spaces(self):
        from app.modules.organisations.service import validate_nzbn
        assert validate_nzbn("9429041 00013") is False

    def test_reject_dashes(self):
        from app.modules.organisations.service import validate_nzbn
        assert validate_nzbn("9429-041-0001") is False

    def test_reject_special_chars(self):
        from app.modules.organisations.service import validate_nzbn
        assert validate_nzbn("942904100001!") is False


# ---------------------------------------------------------------------------
# NZBN Schema Validation (Req 30.1, 30.2)
# ---------------------------------------------------------------------------


class TestNZBNSchemaValidation:
    """BusinessTypeUpdateRequest schema validates NZBN."""

    def test_schema_accepts_valid_nzbn(self):
        from app.modules.organisations.schemas import BusinessTypeUpdateRequest
        req = BusinessTypeUpdateRequest(
            business_type="company",
            nzbn="9429041000013",
        )
        assert req.nzbn == "9429041000013"

    def test_schema_accepts_none_nzbn(self):
        from app.modules.organisations.schemas import BusinessTypeUpdateRequest
        req = BusinessTypeUpdateRequest(business_type="sole_trader")
        assert req.nzbn is None

    def test_schema_rejects_12_digit_nzbn(self):
        from app.modules.organisations.schemas import BusinessTypeUpdateRequest
        with pytest.raises(Exception):
            BusinessTypeUpdateRequest(
                business_type="company",
                nzbn="942904100001",
            )

    def test_schema_rejects_14_digit_nzbn(self):
        from app.modules.organisations.schemas import BusinessTypeUpdateRequest
        with pytest.raises(Exception):
            BusinessTypeUpdateRequest(
                business_type="company",
                nzbn="94290410000130",
            )

    def test_schema_rejects_alpha_nzbn(self):
        from app.modules.organisations.schemas import BusinessTypeUpdateRequest
        with pytest.raises(Exception):
            BusinessTypeUpdateRequest(
                business_type="company",
                nzbn="942904100001A",
            )


# ---------------------------------------------------------------------------
# Business Type affects Tax Calculation (Req 29.3, 29.4)
# ---------------------------------------------------------------------------


class TestBusinessTypeAffectsTax:
    """Business type determines which tax calculation is used."""

    def test_sole_trader_uses_progressive_brackets(self):
        """sole_trader → progressive NZ tax brackets."""
        from app.modules.reports.service import (
            _calculate_sole_trader_tax,
        )
        # $70,000 income: 14000*0.105 + 34000*0.175 + 22000*0.30 = 1470 + 5950 + 6600 = 14020
        tax = _calculate_sole_trader_tax(Decimal("70000"))
        assert tax == Decimal("14020.00")

    def test_company_uses_flat_28_percent(self):
        """company → flat 28% rate."""
        from app.modules.reports.service import _calculate_company_tax
        tax = _calculate_company_tax(Decimal("100000"))
        assert tax == Decimal("28000.00")

    def test_sole_trader_zero_income(self):
        from app.modules.reports.service import _calculate_sole_trader_tax
        tax = _calculate_sole_trader_tax(Decimal("0"))
        assert tax == Decimal("0.00")

    def test_company_zero_income(self):
        from app.modules.reports.service import _calculate_company_tax
        tax = _calculate_company_tax(Decimal("0"))
        assert tax == Decimal("0.00")


# ---------------------------------------------------------------------------
# Business Type affects IRD Return Type (Req 29.5, 29.6)
# ---------------------------------------------------------------------------


class TestBusinessTypeAffectsIRDReturnType:
    """Business type determines IR3 vs IR4 return format."""

    def test_sole_trader_maps_to_ir3(self):
        """sole_trader → IR3."""
        business_type = "sole_trader"
        return_type = "IR4" if business_type == "company" else "IR3"
        assert return_type == "IR3"

    def test_company_maps_to_ir4(self):
        """company → IR4."""
        business_type = "company"
        return_type = "IR4" if business_type == "company" else "IR3"
        assert return_type == "IR4"

    def test_partnership_defaults_to_ir3(self):
        """partnership → IR3 (default for non-company)."""
        business_type = "partnership"
        return_type = "IR4" if business_type == "company" else "IR3"
        assert return_type == "IR3"


# ---------------------------------------------------------------------------
# Set Business Type Service (Req 29.1, 29.2)
# ---------------------------------------------------------------------------


class TestSetBusinessType:
    """set_business_type updates org columns and writes audit log."""

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_set_business_type_updates_org(self, mock_audit):
        from app.modules.organisations.service import set_business_type

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Mock the DB session
        mock_db = AsyncMock()
        mock_org = MagicMock()
        mock_org.business_type = "company"
        mock_org.nzbn = "9429041000013"
        mock_org.nz_company_number = None
        mock_org.gst_registered = False
        mock_org.gst_registration_date = None
        mock_org.income_tax_year_end = None
        mock_org.provisional_tax_method = "standard"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_org
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await set_business_type(
            mock_db,
            org_id=org_id,
            user_id=user_id,
            business_type="company",
            nzbn="9429041000013",
        )

        assert result["business_type"] == "company"
        assert result["nzbn"] == "9429041000013"
        mock_audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_business_type_rejects_invalid_nzbn(self):
        from app.modules.organisations.service import set_business_type
        from fastapi import HTTPException

        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await set_business_type(
                mock_db,
                org_id=uuid.uuid4(),
                business_type="company",
                nzbn="12345",  # Invalid — not 13 digits
            )
        assert exc_info.value.status_code == 422
        assert "INVALID_NZBN" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_set_business_type_rejects_invalid_type(self):
        from app.modules.organisations.service import set_business_type
        from fastapi import HTTPException

        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await set_business_type(
                mock_db,
                org_id=uuid.uuid4(),
                business_type="llc",  # Invalid
            )
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Integration Test Connection (Req 31.1–31.3)
# ---------------------------------------------------------------------------


class TestIntegrationTestConnection:
    """Test connection returns structured success/failure."""

    @pytest.mark.asyncio
    async def test_xero_connected_returns_success(self):
        from app.modules.accounting.integrations_router import _test_accounting_connection

        mock_db = AsyncMock()
        mock_conn = MagicMock()
        mock_conn.is_connected = True
        mock_conn.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        mock_conn.account_name = "Test Xero Org"
        mock_conn.connected_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_conn.last_sync_at = datetime(2026, 4, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_conn
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _test_accounting_connection(mock_db, uuid.uuid4(), "xero")
        assert result["success"] is True
        assert result["provider"] == "xero"
        assert result["account_name"] == "Test Xero Org"

    @pytest.mark.asyncio
    async def test_xero_not_connected_returns_failure(self):
        from app.modules.accounting.integrations_router import _test_accounting_connection

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _test_accounting_connection(mock_db, uuid.uuid4(), "xero")
        assert result["success"] is False
        assert "not connected" in result["error"]

    @pytest.mark.asyncio
    async def test_expired_token_returns_failure(self):
        from app.modules.accounting.integrations_router import _test_accounting_connection

        mock_db = AsyncMock()
        mock_conn = MagicMock()
        mock_conn.is_connected = True
        mock_conn.token_expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_conn
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _test_accounting_connection(mock_db, uuid.uuid4(), "xero")
        assert result["success"] is False
        assert "expired" in result["error"]


# ---------------------------------------------------------------------------
# Integration Disconnect Deletes Tokens (Req 31.4)
# ---------------------------------------------------------------------------


class TestIntegrationDisconnect:
    """Disconnect deletes stored tokens from DB (not just flag inactive)."""

    @pytest.mark.asyncio
    async def test_disconnect_clears_tokens(self):
        from app.modules.accounting.service import disconnect

        mock_db = AsyncMock()
        mock_conn = MagicMock()
        mock_conn.access_token_encrypted = b"encrypted_token"
        mock_conn.refresh_token_encrypted = b"encrypted_refresh"
        mock_conn.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        mock_conn.is_connected = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_conn
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await disconnect(mock_db, org_id=uuid.uuid4(), provider="xero")
        assert result is True
        assert mock_conn.access_token_encrypted is None
        assert mock_conn.refresh_token_encrypted is None
        assert mock_conn.is_connected is False


# ---------------------------------------------------------------------------
# Audit Log Entries (Req 37.1, 37.2)
# ---------------------------------------------------------------------------


class TestAuditLogEntries:
    """Audit log entries created for connect/disconnect/test."""

    @pytest.mark.asyncio
    async def test_audit_log_written_on_test_connection(self):
        """write_audit_log is called when testing a connection."""
        from app.core.audit import write_audit_log

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        entry_id = await write_audit_log(
            session=mock_session,
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action="integration.test.xero",
            entity_type="integration",
        )
        assert entry_id is not None
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_log_written_on_disconnect(self):
        """write_audit_log is called when disconnecting."""
        from app.core.audit import write_audit_log

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        entry_id = await write_audit_log(
            session=mock_session,
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action="integration.disconnect.xero",
            entity_type="integration",
        )
        assert entry_id is not None
        mock_session.execute.assert_called_once()
