"""Unit tests for Task 12.2 — parts catalogue and labour rates CRUD.

Tests cover:
  - Schema validation for part and labour rate create requests
  - list_parts: listing with active_only filter
  - create_part: creation with audit logging and validation
  - list_labour_rates: listing with active_only filter
  - create_labour_rate: creation with audit logging and validation

Requirements: 28.1, 28.2, 28.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.catalogue.models import LabourRate, PartsCatalogue
from app.modules.catalogue.schemas import (
    LabourRateCreateRequest,
    LabourRateListResponse,
    LabourRateResponse,
    PartCreateRequest,
    PartListResponse,
    PartResponse,
)
from app.modules.catalogue.service import (
    create_labour_rate,
    create_part,
    list_labour_rates,
    list_parts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_part(
    org_id=None,
    name="Brake Pad Set",
    part_number="BP-001",
    default_price=Decimal("45.00"),
    is_active=True,
):
    """Create a mock PartsCatalogue object."""
    part = MagicMock(spec=PartsCatalogue)
    part.id = uuid.uuid4()
    part.org_id = org_id or uuid.uuid4()
    part.name = name
    part.part_number = part_number
    part.default_price = default_price
    part.is_active = is_active
    part.created_at = datetime.now(timezone.utc)
    part.updated_at = datetime.now(timezone.utc)
    part._supplier_name = None
    return part


def _make_labour_rate(
    org_id=None,
    name="Standard Rate",
    hourly_rate=Decimal("95.00"),
    is_active=True,
):
    """Create a mock LabourRate object."""
    rate = MagicMock(spec=LabourRate)
    rate.id = uuid.uuid4()
    rate.org_id = org_id or uuid.uuid4()
    rate.name = name
    rate.hourly_rate = hourly_rate
    rate.is_active = is_active
    rate.created_at = datetime.now(timezone.utc)
    rate.updated_at = datetime.now(timezone.utc)
    return rate


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_result(values):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


def _mock_count_result(count):
    result = MagicMock()
    result.scalar.return_value = count
    return result


# ---------------------------------------------------------------------------
# Part Schema tests
# ---------------------------------------------------------------------------


class TestPartSchemas:
    """Validate Pydantic schema constraints for parts catalogue."""

    def test_create_request_valid(self):
        req = PartCreateRequest(
            name="Oil Filter",
            default_price="12.50",
        )
        assert req.name == "Oil Filter"
        assert req.default_price == "12.50"
        assert req.part_number is None
        assert req.supplier is None
        assert req.is_active is True

    def test_create_request_all_fields(self):
        req = PartCreateRequest(
            name="Brake Pad Set",
            part_number="BP-001",
            default_price="45.00",
            supplier="Repco NZ",
            is_active=False,
        )
        assert req.part_number == "BP-001"
        assert req.supplier == "Repco NZ"
        assert req.is_active is False

    def test_create_request_empty_name_rejected(self):
        with pytest.raises(Exception):
            PartCreateRequest(name="", default_price="10.00")

    def test_part_response_serialisation(self):
        resp = PartResponse(
            id=str(uuid.uuid4()),
            name="Spark Plug",
            part_number="SP-100",
            default_price="8.50",
            supplier=None,
            is_active=True,
            created_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
        )
        assert resp.name == "Spark Plug"


# ---------------------------------------------------------------------------
# Labour Rate Schema tests
# ---------------------------------------------------------------------------


class TestLabourRateSchemas:
    """Validate Pydantic schema constraints for labour rates."""

    def test_create_request_valid(self):
        req = LabourRateCreateRequest(
            name="Standard Rate",
            hourly_rate="95.00",
        )
        assert req.name == "Standard Rate"
        assert req.hourly_rate == "95.00"
        assert req.is_active is True

    def test_create_request_inactive(self):
        req = LabourRateCreateRequest(
            name="Specialist Rate",
            hourly_rate="150.00",
            is_active=False,
        )
        assert req.is_active is False

    def test_create_request_empty_name_rejected(self):
        with pytest.raises(Exception):
            LabourRateCreateRequest(name="", hourly_rate="95.00")

    def test_labour_rate_response_serialisation(self):
        resp = LabourRateResponse(
            id=str(uuid.uuid4()),
            name="Standard Rate",
            hourly_rate="95.00",
            is_active=True,
            created_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
        )
        assert resp.hourly_rate == "95.00"


# ---------------------------------------------------------------------------
# list_parts tests
# ---------------------------------------------------------------------------


class TestListParts:
    """Test parts catalogue listing with filters."""

    @pytest.mark.asyncio
    async def test_returns_all_parts(self):
        org_id = uuid.uuid4()
        parts = [_make_part(org_id=org_id), _make_part(org_id=org_id, name="Oil Filter")]
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(2),
            _mock_scalars_result(parts),
        ])

        result = await list_parts(db, org_id=org_id)
        assert result["total"] == 2
        assert len(result["parts"]) == 2

    @pytest.mark.asyncio
    async def test_active_only_filter(self):
        org_id = uuid.uuid4()
        active_part = _make_part(org_id=org_id, is_active=True)
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(1),
            _mock_scalars_result([active_part]),
        ])

        result = await list_parts(db, org_id=org_id, active_only=True)
        assert result["total"] == 1
        assert result["parts"][0]["is_active"] is True

    @pytest.mark.asyncio
    async def test_empty_catalogue(self):
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(0),
            _mock_scalars_result([]),
        ])

        result = await list_parts(db, org_id=uuid.uuid4())
        assert result["total"] == 0
        assert result["parts"] == []


# ---------------------------------------------------------------------------
# create_part tests
# ---------------------------------------------------------------------------


class TestCreatePart:
    """Test part creation with validation and audit logging."""

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_creates_part_successfully(self, mock_audit):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        result = await create_part(
            db,
            org_id=org_id,
            user_id=user_id,
            name="Brake Pad Set",
            part_number="BP-001",
            default_price="45.00",
            supplier="Repco NZ",
        )

        assert result["name"] == "Brake Pad Set"
        assert result["default_price"] == "45.00"
        assert result["supplier"] == "Repco NZ"
        assert result["is_active"] is True
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_audit_log_written_on_create(self, mock_audit):
        db = _mock_db_session()
        await create_part(
            db,
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Test Part",
            default_price="10.00",
        )
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "catalogue.part.created"
        assert call_kwargs["entity_type"] == "parts_catalogue"

    @pytest.mark.asyncio
    async def test_invalid_price_raises(self):
        db = _mock_db_session()
        with pytest.raises(ValueError, match="Invalid price format"):
            await create_part(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                name="Test",
                default_price="not-a-number",
            )

    @pytest.mark.asyncio
    async def test_negative_price_raises(self):
        db = _mock_db_session()
        with pytest.raises(ValueError, match="Price cannot be negative"):
            await create_part(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                name="Test",
                default_price="-5.00",
            )

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_creates_part_without_optional_fields(self, mock_audit):
        """Req 28.1 — supplier is optional."""
        db = _mock_db_session()
        result = await create_part(
            db,
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Generic Filter",
            default_price="8.00",
        )
        assert result["part_number"] is None
        assert result["supplier"] is None


# ---------------------------------------------------------------------------
# list_labour_rates tests
# ---------------------------------------------------------------------------


class TestListLabourRates:
    """Test labour rate listing with filters."""

    @pytest.mark.asyncio
    async def test_returns_all_rates(self):
        org_id = uuid.uuid4()
        rates = [
            _make_labour_rate(org_id=org_id),
            _make_labour_rate(org_id=org_id, name="Specialist Rate", hourly_rate=Decimal("150.00")),
        ]
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(2),
            _mock_scalars_result(rates),
        ])

        result = await list_labour_rates(db, org_id=org_id)
        assert result["total"] == 2
        assert len(result["labour_rates"]) == 2

    @pytest.mark.asyncio
    async def test_active_only_filter(self):
        org_id = uuid.uuid4()
        active_rate = _make_labour_rate(org_id=org_id, is_active=True)
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(1),
            _mock_scalars_result([active_rate]),
        ])

        result = await list_labour_rates(db, org_id=org_id, active_only=True)
        assert result["total"] == 1
        assert result["labour_rates"][0]["is_active"] is True

    @pytest.mark.asyncio
    async def test_empty_rates(self):
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(0),
            _mock_scalars_result([]),
        ])

        result = await list_labour_rates(db, org_id=uuid.uuid4())
        assert result["total"] == 0
        assert result["labour_rates"] == []


# ---------------------------------------------------------------------------
# create_labour_rate tests
# ---------------------------------------------------------------------------


class TestCreateLabourRate:
    """Test labour rate creation with validation and audit logging."""

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_creates_rate_successfully(self, mock_audit):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        result = await create_labour_rate(
            db,
            org_id=org_id,
            user_id=user_id,
            name="Standard Rate",
            hourly_rate="95.00",
        )

        assert result["name"] == "Standard Rate"
        assert result["hourly_rate"] == "95.00"
        assert result["is_active"] is True
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_audit_log_written_on_create(self, mock_audit):
        db = _mock_db_session()
        await create_labour_rate(
            db,
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Test Rate",
            hourly_rate="80.00",
        )
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "catalogue.labour_rate.created"
        assert call_kwargs["entity_type"] == "labour_rates"

    @pytest.mark.asyncio
    async def test_invalid_rate_raises(self):
        db = _mock_db_session()
        with pytest.raises(ValueError, match="Invalid hourly rate format"):
            await create_labour_rate(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                name="Test",
                hourly_rate="not-a-number",
            )

    @pytest.mark.asyncio
    async def test_negative_rate_raises(self):
        db = _mock_db_session()
        with pytest.raises(ValueError, match="Hourly rate cannot be negative"):
            await create_labour_rate(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                name="Test",
                hourly_rate="-10.00",
            )
