"""Unit tests for IRD Gateway SOAP Integration — Sprint 6.

Tests mock SOAP responses, XML mapping, error codes, rate limiting,
credential masking, retry logic, and timeout enforcement.

Requirements: 24.1–24.6, 25.1–25.6, 26.1–26.7, 27.1–27.4, 28.1–28.3
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.ird.gateway import (
    FILING_TIMEOUT_SECONDS,
    STATUS_TIMEOUT_SECONDS,
    IRD_ERROR_CODES,
    IrdSoapClient,
    IrdSoapResponse,
    _retry_with_backoff,
    get_error_message,
    parse_gst_from_xml,
    serialize_gst_to_xml,
    serialize_income_tax_to_xml,
)
from app.modules.ird.schemas import (
    IrdConnectRequest,
    _is_masked,
    _mask_credential,
    validate_ird_number,
)
from app.modules.ird.service import _check_filing_rate_limit


# ---------------------------------------------------------------------------
# Mock SOAP Responses
# ---------------------------------------------------------------------------


class TestMockSOAPResponses:
    """Tests for mock SOAP response handling (Req 24.1–24.6)."""

    @pytest.mark.asyncio
    async def test_rfo_returns_obligation_status(self) -> None:
        """RFO operation returns filing obligation status."""
        client = IrdSoapClient("49-091-850", {}, "sandbox")
        response = await client.retrieve_filing_obligation(
            "49-091-850", uuid.uuid4(), "gst"
        )
        assert response.success is True
        assert response.operation == "RFO"
        assert "obligation_met" in response.data
        assert response.request_xml  # XML logged
        assert response.response_xml  # XML logged

    @pytest.mark.asyncio
    async def test_rr_returns_existing_return_status(self) -> None:
        """RR operation returns whether a return already exists."""
        client = IrdSoapClient("49-091-850", {}, "sandbox")
        response = await client.retrieve_return(
            "49-091-850", uuid.uuid4(), "gst"
        )
        assert response.success is True
        assert response.operation == "RR"
        assert "existing_return" in response.data

    @pytest.mark.asyncio
    async def test_file_return_returns_reference(self) -> None:
        """File Return operation returns IRD reference."""
        client = IrdSoapClient("49-091-850", {}, "sandbox")
        response = await client.file_return(
            "49-091-850", "<GSTReturn/>", "gst"
        )
        assert response.success is True
        assert response.operation == "FileReturn"
        assert response.ird_reference is not None

    @pytest.mark.asyncio
    async def test_retrieve_status_returns_accepted(self) -> None:
        """RS operation returns filing status."""
        client = IrdSoapClient("49-091-850", {}, "sandbox")
        response = await client.retrieve_status(
            "49-091-850", "IRD-GST-2025-001"
        )
        assert response.success is True
        assert response.operation == "RS"
        assert response.data.get("status") == "accepted"


# ---------------------------------------------------------------------------
# GST XML Mapping
# ---------------------------------------------------------------------------


class TestGSTXMLMapping:
    """Tests for GST return XML serialization (Req 26.3)."""

    def test_serialize_gst_produces_valid_xml(self) -> None:
        """Serialized GST data produces parseable XML."""
        gst_data = {
            "period_start": "2025-05-01",
            "period_end": "2025-06-30",
            "total_sales": Decimal("10000.00"),
            "total_gst_collected": Decimal("1500.00"),
            "standard_rated_sales": Decimal("8000.00"),
            "zero_rated_sales": Decimal("2000.00"),
            "total_refunds": Decimal("500.00"),
            "refund_gst": Decimal("65.22"),
            "adjusted_total_sales": Decimal("9500.00"),
            "adjusted_output_gst": Decimal("1434.78"),
            "total_purchases": Decimal("3000.00"),
            "total_input_tax": Decimal("391.30"),
            "net_gst_payable": Decimal("1043.48"),
        }
        xml_str = serialize_gst_to_xml(gst_data)
        assert "GSTReturn" in xml_str
        assert "10000.00" in xml_str
        assert "1500.00" in xml_str

    def test_round_trip_preserves_all_fields(self) -> None:
        """Serialize → parse round-trip preserves all numeric fields."""
        gst_data = {
            "period_start": "2025-05-01",
            "period_end": "2025-06-30",
            "total_sales": Decimal("10000.00"),
            "total_gst_collected": Decimal("1500.00"),
            "standard_rated_sales": Decimal("8000.00"),
            "zero_rated_sales": Decimal("2000.00"),
            "total_refunds": Decimal("500.00"),
            "refund_gst": Decimal("65.22"),
            "adjusted_total_sales": Decimal("9500.00"),
            "adjusted_output_gst": Decimal("1434.78"),
            "total_purchases": Decimal("3000.00"),
            "total_input_tax": Decimal("391.30"),
            "net_gst_payable": Decimal("1043.48"),
        }
        xml_str = serialize_gst_to_xml(gst_data)
        parsed = parse_gst_from_xml(xml_str)

        assert parsed["total_sales"] == Decimal("10000.00")
        assert parsed["net_gst_payable"] == Decimal("1043.48")
        assert parsed["total_input_tax"] == Decimal("391.30")

    def test_ird_box_mapping_correct(self) -> None:
        """Verify IRD box mapping: Sales, Purchases, NetPosition elements."""
        gst_data = {
            "period_start": "2025-01-01",
            "period_end": "2025-02-28",
            "total_sales": Decimal("5000.00"),
            "total_gst_collected": Decimal("750.00"),
            "standard_rated_sales": Decimal("5000.00"),
            "zero_rated_sales": Decimal("0.00"),
            "total_refunds": Decimal("0.00"),
            "refund_gst": Decimal("0.00"),
            "adjusted_total_sales": Decimal("5000.00"),
            "adjusted_output_gst": Decimal("750.00"),
            "total_purchases": Decimal("1000.00"),
            "total_input_tax": Decimal("130.43"),
            "net_gst_payable": Decimal("619.57"),
        }
        xml_str = serialize_gst_to_xml(gst_data)
        assert "<TotalSales>5000.00</TotalSales>" in xml_str
        assert "<TotalPurchases>1000.00</TotalPurchases>" in xml_str
        assert "<NetGSTPayable>619.57</NetGSTPayable>" in xml_str


# ---------------------------------------------------------------------------
# Income Tax Filing
# ---------------------------------------------------------------------------


class TestIncomeTaxFiling:
    """Tests for income tax return type selection (Req 27.1, 27.2)."""

    def test_sole_trader_uses_ir3(self) -> None:
        """Sole trader business type maps to IR3 return format."""
        xml = serialize_income_tax_to_xml("IR3", {
            "tax_year": 2025,
            "total_revenue": Decimal("80000"),
            "total_expenses": Decimal("20000"),
            "taxable_income": Decimal("60000"),
            "estimated_tax": Decimal("11020"),
        })
        assert 'returnType="IR3"' in xml
        assert "<TaxYear>2025</TaxYear>" in xml

    def test_company_uses_ir4(self) -> None:
        """Company business type maps to IR4 return format."""
        xml = serialize_income_tax_to_xml("IR4", {
            "tax_year": 2025,
            "total_revenue": Decimal("200000"),
            "total_expenses": Decimal("100000"),
            "taxable_income": Decimal("100000"),
            "estimated_tax": Decimal("28000"),
        })
        assert 'returnType="IR4"' in xml


# ---------------------------------------------------------------------------
# Error Code Mapping
# ---------------------------------------------------------------------------


class TestErrorCodeMapping:
    """Tests for IRD error code to plain English mapping (Req 24.6)."""

    def test_known_error_codes_have_messages(self) -> None:
        """All known error codes map to plain English messages."""
        for code in IRD_ERROR_CODES:
            msg = get_error_message(code)
            assert msg, f"Error code {code} has no message"
            assert code not in msg or "Unknown" not in msg

    def test_unknown_error_code_returns_fallback(self) -> None:
        """Unknown error codes return a descriptive fallback."""
        msg = get_error_message("ERR_UNKNOWN_999")
        assert "Unknown IRD error" in msg
        assert "ERR_UNKNOWN_999" in msg

    def test_auth_failure_message(self) -> None:
        """ERR_005 maps to authentication failure message."""
        msg = get_error_message("ERR_005")
        assert "credential" in msg.lower() or "authentication" in msg.lower()


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Tests for filing rate limit enforcement (Req 25.5)."""

    @pytest.mark.asyncio
    async def test_first_filing_allowed(self) -> None:
        """First filing for a period should be allowed."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        db.execute.return_value = mock_result

        # Should not raise
        await _check_filing_rate_limit(db, uuid.uuid4(), uuid.uuid4(), "gst")

    @pytest.mark.asyncio
    async def test_second_filing_rejected(self) -> None:
        """Second filing for the same period should be rejected with 429."""
        from fastapi import HTTPException

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await _check_filing_rate_limit(db, uuid.uuid4(), uuid.uuid4(), "gst")

        assert exc_info.value.status_code == 429
        assert exc_info.value.detail["code"] == "FILING_RATE_LIMITED"

    @pytest.mark.asyncio
    async def test_different_period_allowed(self) -> None:
        """Filing for a different period should be allowed."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        db.execute.return_value = mock_result

        org_id = uuid.uuid4()
        # Both should pass
        await _check_filing_rate_limit(db, org_id, uuid.uuid4(), "gst")
        await _check_filing_rate_limit(db, org_id, uuid.uuid4(), "gst")


# ---------------------------------------------------------------------------
# Credential Masking
# ---------------------------------------------------------------------------


class TestCredentialMasking:
    """Tests for credential masking in API responses (Req 25.2, 33.2)."""

    def test_mask_long_credential(self) -> None:
        """Credentials > 8 chars show ****<last4>."""
        masked = _mask_credential("my-secret-ird-password")
        assert masked == "****word"

    def test_mask_short_credential(self) -> None:
        """Credentials ≤ 8 chars are fully masked."""
        masked = _mask_credential("short")
        assert masked == "****"

    def test_mask_none_returns_none(self) -> None:
        """None input returns None."""
        assert _mask_credential(None) is None

    def test_mask_empty_returns_none(self) -> None:
        """Empty string returns None."""
        assert _mask_credential("") is None

    def test_is_masked_detects_mask_pattern(self) -> None:
        """Masked values are detected correctly."""
        assert _is_masked("****word") is True
        assert _is_masked("****") is True
        assert _is_masked("********") is True

    def test_is_masked_real_value_not_detected(self) -> None:
        """Real credential values are not detected as masked."""
        assert _is_masked("my-real-password") is False
        assert _is_masked("49-091-850") is False

    def test_is_masked_none_and_empty(self) -> None:
        """None and empty string return False."""
        assert _is_masked(None) is False
        assert _is_masked("") is False


# ---------------------------------------------------------------------------
# Retry Logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    """Tests for retry with exponential backoff (Req 24.3)."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_third_attempt(self) -> None:
        """Retry succeeds after transient failures."""
        call_count = 0

        async def flaky_call():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            return "success"

        with patch("app.modules.ird.gateway.asyncio.sleep", new_callable=AsyncMock):
            result = await _retry_with_backoff(flaky_call, max_retries=3, backoff_base=0.01)

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self) -> None:
        """After max retries, the last exception is raised."""
        async def always_fail():
            raise ConnectionError("Persistent failure")

        with patch("app.modules.ird.gateway.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ConnectionError, match="Persistent failure"):
                await _retry_with_backoff(always_fail, max_retries=3, backoff_base=0.01)

    @pytest.mark.asyncio
    async def test_retry_not_triggered_on_success(self) -> None:
        """Successful first call does not trigger retry."""
        call_count = 0

        async def success_call():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await _retry_with_backoff(success_call, max_retries=3)
        assert result == "ok"
        assert call_count == 1


# ---------------------------------------------------------------------------
# Timeout Enforcement
# ---------------------------------------------------------------------------


class TestTimeoutEnforcement:
    """Tests for timeout configuration (Req 24.4)."""

    def test_filing_timeout_is_30_seconds(self) -> None:
        """Filing operations use 30-second timeout."""
        assert FILING_TIMEOUT_SECONDS == 30

    def test_status_timeout_is_10_seconds(self) -> None:
        """Status check operations use 10-second timeout."""
        assert STATUS_TIMEOUT_SECONDS == 10


# ---------------------------------------------------------------------------
# IRD Number Validation (via schemas)
# ---------------------------------------------------------------------------


class TestIrdNumberValidation:
    """Tests for IRD number validation in connect request (Req 25.1)."""

    def test_valid_ird_number_accepted(self) -> None:
        """Known valid IRD number 49-091-850 is accepted."""
        req = IrdConnectRequest(
            ird_number="49-091-850",
            username="user",
            password="pass",
        )
        assert req.ird_number == "49-091-850"

    def test_invalid_ird_number_rejected(self) -> None:
        """Invalid IRD number is rejected with validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            IrdConnectRequest(
                ird_number="12-345-678",
                username="user",
                password="pass",
            )

    def test_non_digit_ird_rejected(self) -> None:
        """Non-digit IRD number is rejected."""
        with pytest.raises(Exception):
            IrdConnectRequest(
                ird_number="abc-def-ghi",
                username="user",
                password="pass",
            )
