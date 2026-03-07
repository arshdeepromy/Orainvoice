"""Unit tests for Task 18.3 — Job Card CRUD.

Requirements: 59.1, 59.2, 59.5
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
from app.modules.invoices.models import Invoice, LineItem  # noqa: F401
from app.modules.catalogue.models import PartsCatalogue  # noqa: F401
from app.modules.quotes.models import Quote, QuoteLineItem  # noqa: F401
from app.modules.job_cards.models import JobCard, JobCardItem
from app.modules.job_cards.service import (
    _calculate_line_total,
    _validate_status_transition,
    create_job_card,
    get_job_card,
    list_job_cards,
    update_job_card,
)
from app.modules.job_cards.schemas import (
    JobCardCreate,
    JobCardItemCreate,
    JobCardStatus,
    JobCardUpdate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_customer(org_id):
    cust = MagicMock()
    cust.id = uuid.uuid4()
    cust.org_id = org_id
    cust.first_name = "Jane"
    cust.last_name = "Smith"
    return cust


def _make_job_card(org_id=None, status="open"):
    jc = MagicMock(spec=JobCard)
    jc.id = uuid.uuid4()
    jc.org_id = org_id or uuid.uuid4()
    jc.customer_id = uuid.uuid4()
    jc.vehicle_rego = "ABC123"
    jc.status = status
    jc.description = "Full service"
    jc.notes = None
    jc.created_by = uuid.uuid4()
    jc.created_at = datetime.now(timezone.utc)
    jc.updated_at = datetime.now(timezone.utc)
    return jc


def _make_job_card_item(job_card_id=None):
    li = MagicMock(spec=JobCardItem)
    li.id = uuid.uuid4()
    li.job_card_id = job_card_id or uuid.uuid4()
    li.item_type = "service"
    li.description = "Oil Change"
    li.quantity = Decimal("1")
    li.unit_price = Decimal("50.00")
    li.is_completed = False
    li.sort_order = 0
    return li


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestJobCardSchemas:
    """Test Pydantic schema validation for job cards."""

    def test_valid_status_values(self):
        assert JobCardStatus.open == "open"
        assert JobCardStatus.in_progress == "in_progress"
        assert JobCardStatus.completed == "completed"
        assert JobCardStatus.invoiced == "invoiced"

    def test_item_create_requires_description(self):
        with pytest.raises(Exception):
            JobCardItemCreate(
                item_type="service",
                description="",
                unit_price=Decimal("10.00"),
            )

    def test_item_create_valid(self):
        item = JobCardItemCreate(
            item_type="part",
            description="Brake pad",
            quantity=Decimal("2"),
            unit_price=Decimal("45.00"),
        )
        assert item.item_type.value == "part"
        assert item.quantity == Decimal("2")

    def test_create_schema_defaults(self):
        payload = JobCardCreate(customer_id=uuid.uuid4())
        assert payload.vehicle_rego is None
        assert payload.description is None
        assert payload.line_items == []

    def test_update_schema_all_optional(self):
        payload = JobCardUpdate()
        assert payload.status is None
        assert payload.customer_id is None
        assert payload.line_items is None


# ---------------------------------------------------------------------------
# Line total calculation tests
# ---------------------------------------------------------------------------


class TestLineCalculations:
    """Test line total calculation."""

    def test_basic_total(self):
        result = _calculate_line_total(Decimal("2"), Decimal("50.00"))
        assert result == Decimal("100.00")

    def test_fractional_quantity(self):
        result = _calculate_line_total(Decimal("1.5"), Decimal("80.00"))
        assert result == Decimal("120.00")

    def test_rounding(self):
        result = _calculate_line_total(Decimal("3"), Decimal("33.33"))
        assert result == Decimal("99.99")


# ---------------------------------------------------------------------------
# Status transition tests
# ---------------------------------------------------------------------------


class TestStatusTransitions:
    """Test job card status transition validation."""

    def test_open_to_in_progress(self):
        _validate_status_transition("open", "in_progress")

    def test_in_progress_to_completed(self):
        _validate_status_transition("in_progress", "completed")

    def test_completed_to_invoiced(self):
        _validate_status_transition("completed", "invoiced")

    def test_open_to_completed_rejected(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("open", "completed")

    def test_open_to_invoiced_rejected(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("open", "invoiced")

    def test_in_progress_to_open_rejected(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("in_progress", "open")

    def test_completed_to_open_rejected(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("completed", "open")

    def test_invoiced_is_terminal(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("invoiced", "open")
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("invoiced", "in_progress")
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("invoiced", "completed")


# ---------------------------------------------------------------------------
# Service function tests
# ---------------------------------------------------------------------------


class TestCreateJobCard:
    """Test job card creation service."""

    @pytest.mark.asyncio
    async def test_create_job_card_success(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_customer(org_id)

        db = _mock_db()

        # Mock customer lookup
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        # Mock audit log insert
        audit_result = MagicMock()

        db.execute = AsyncMock(side_effect=[cust_result, audit_result])

        with patch("app.modules.job_cards.service.write_audit_log", new_callable=AsyncMock):
            result = await create_job_card(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer.id,
                vehicle_rego="XYZ789",
                description="Brake service",
                line_items_data=[
                    {
                        "item_type": "service",
                        "description": "Brake pad replacement",
                        "quantity": Decimal("1"),
                        "unit_price": Decimal("120.00"),
                    }
                ],
            )

        assert result["status"] == "open"
        assert result["vehicle_rego"] == "XYZ789"
        assert result["description"] == "Brake service"
        assert len(result["line_items"]) == 1
        assert result["line_items"][0]["line_total"] == Decimal("120.00")

    @pytest.mark.asyncio
    async def test_create_job_card_customer_not_found(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = _mock_db()
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=cust_result)

        with pytest.raises(ValueError, match="Customer not found"):
            await create_job_card(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=uuid.uuid4(),
            )


class TestGetJobCard:
    """Test job card retrieval."""

    @pytest.mark.asyncio
    async def test_get_job_card_success(self):
        org_id = uuid.uuid4()
        job_card = _make_job_card(org_id)
        line_item = _make_job_card_item(job_card.id)

        db = _mock_db()

        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        li_scalars = MagicMock()
        li_scalars.all.return_value = [line_item]
        li_result = MagicMock()
        li_result.scalars.return_value = li_scalars

        db.execute = AsyncMock(side_effect=[jc_result, li_result])

        result = await get_job_card(db, org_id=org_id, job_card_id=job_card.id)

        assert result["id"] == job_card.id
        assert result["status"] == "open"
        assert len(result["line_items"]) == 1

    @pytest.mark.asyncio
    async def test_get_job_card_not_found(self):
        db = _mock_db()
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=jc_result)

        with pytest.raises(ValueError, match="Job card not found"):
            await get_job_card(db, org_id=uuid.uuid4(), job_card_id=uuid.uuid4())


class TestUpdateJobCard:
    """Test job card update service."""

    @pytest.mark.asyncio
    async def test_update_status_transition(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, status="open")

        db = _mock_db()

        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        li_scalars = MagicMock()
        li_scalars.all.return_value = []
        li_result = MagicMock()
        li_result.scalars.return_value = li_scalars

        db.execute = AsyncMock(side_effect=[jc_result, li_result])

        with patch("app.modules.job_cards.service.write_audit_log", new_callable=AsyncMock):
            result = await update_job_card(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                updates={"status": "in_progress"},
            )

        assert result["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_invalid_transition_rejected(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, status="open")

        db = _mock_db()
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card
        db.execute = AsyncMock(return_value=jc_result)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_job_card(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                updates={"status": "invoiced"},
            )

    @pytest.mark.asyncio
    async def test_update_job_card_not_found(self):
        db = _mock_db()
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=jc_result)

        with pytest.raises(ValueError, match="Job card not found"):
            await update_job_card(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                job_card_id=uuid.uuid4(),
                updates={"notes": "test"},
            )

    @pytest.mark.asyncio
    async def test_update_notes_on_open_card(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, status="open")

        db = _mock_db()

        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        li_scalars = MagicMock()
        li_scalars.all.return_value = []
        li_result = MagicMock()
        li_result.scalars.return_value = li_scalars

        db.execute = AsyncMock(side_effect=[jc_result, li_result])

        with patch("app.modules.job_cards.service.write_audit_log", new_callable=AsyncMock):
            result = await update_job_card(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                updates={"notes": "Updated notes"},
            )

        assert result["notes"] == "Updated notes"
