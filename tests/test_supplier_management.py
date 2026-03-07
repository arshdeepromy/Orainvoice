"""Unit tests for Task 20.2 — supplier management.

Tests cover:
  - Supplier schema validation (SupplierCreate, PartSupplierLink, PurchaseOrderRequest)
  - create_supplier: creates supplier record
  - list_suppliers: lists suppliers for org
  - link_part_to_supplier: links part with supplier-specific details
  - link_part_to_supplier: validation for missing supplier/part
  - generate_purchase_order_pdf: produces PDF bytes

Requirements: 63.1, 63.2, 63.3
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

from app.modules.inventory.models import Supplier, PartSupplier
from app.modules.catalogue.models import PartsCatalogue
from app.modules.inventory.schemas import (
    SupplierCreate,
    SupplierResponse,
    SupplierListResponse,
    PartSupplierLink,
    PartSupplierLinkResponse,
    PurchaseOrderRequest,
    PurchaseOrderItem,
)
from app.modules.inventory.service import (
    create_supplier,
    list_suppliers,
    link_part_to_supplier,
    generate_purchase_order_pdf,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_supplier(org_id=None, name="AutoParts NZ", contact_name="John Smith"):
    """Create a mock Supplier object."""
    s = MagicMock(spec=Supplier)
    s.id = uuid.uuid4()
    s.org_id = org_id or uuid.uuid4()
    s.name = name
    s.contact_name = contact_name
    s.email = "john@autoparts.co.nz"
    s.phone = "09-555-1234"
    s.address = "123 Main St, Auckland"
    s.account_number = "ACC-001"
    s.created_at = datetime.now(timezone.utc)
    s.updated_at = datetime.now(timezone.utc)
    return s


def _make_part(org_id=None, name="Brake Pad Set", part_number="BP-001"):
    """Create a mock PartsCatalogue object."""
    p = MagicMock(spec=PartsCatalogue)
    p.id = uuid.uuid4()
    p.org_id = org_id or uuid.uuid4()
    p.name = name
    p.part_number = part_number
    p.default_price = Decimal("45.00")
    p.current_stock = 20
    p.min_stock_threshold = 5
    p.reorder_quantity = 10
    p.is_active = True
    return p


def _make_part_supplier(part_id=None, supplier_id=None):
    """Create a mock PartSupplier object."""
    ps = MagicMock(spec=PartSupplier)
    ps.id = uuid.uuid4()
    ps.part_id = part_id or uuid.uuid4()
    ps.supplier_id = supplier_id or uuid.uuid4()
    ps.supplier_part_number = "SUP-BP-001"
    ps.supplier_cost = Decimal("30.00")
    ps.is_preferred = True
    return ps


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


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


def _mock_scalar_one_or_none(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSupplierSchemas:
    """Test supplier-related Pydantic schemas."""

    def test_supplier_create_valid(self):
        s = SupplierCreate(name="AutoParts NZ", email="info@ap.co.nz", phone="09-555-0000")
        assert s.name == "AutoParts NZ"
        assert s.email == "info@ap.co.nz"

    def test_supplier_create_name_required(self):
        with pytest.raises(Exception):
            SupplierCreate(name="")

    def test_supplier_create_minimal(self):
        s = SupplierCreate(name="Supplier X")
        assert s.contact_name is None
        assert s.email is None

    def test_supplier_response_serialisation(self):
        r = SupplierResponse(
            id=str(uuid.uuid4()),
            name="Test Supplier",
            created_at="2024-01-01T00:00:00+00:00",
        )
        assert r.name == "Test Supplier"

    def test_part_supplier_link_valid(self):
        link = PartSupplierLink(
            part_id=str(uuid.uuid4()),
            supplier_part_number="SUP-001",
            supplier_cost=25.50,
        )
        assert link.supplier_cost == 25.50
        assert link.is_preferred is False

    def test_part_supplier_link_negative_cost_rejected(self):
        with pytest.raises(Exception):
            PartSupplierLink(part_id=str(uuid.uuid4()), supplier_cost=-5.0)

    def test_purchase_order_request_valid(self):
        po = PurchaseOrderRequest(
            supplier_id=str(uuid.uuid4()),
            items=[PurchaseOrderItem(part_id=str(uuid.uuid4()), quantity=10)],
        )
        assert len(po.items) == 1

    def test_purchase_order_request_empty_items_rejected(self):
        with pytest.raises(Exception):
            PurchaseOrderRequest(
                supplier_id=str(uuid.uuid4()),
                items=[],
            )

    def test_purchase_order_item_zero_quantity_rejected(self):
        with pytest.raises(Exception):
            PurchaseOrderItem(part_id=str(uuid.uuid4()), quantity=0)


# ---------------------------------------------------------------------------
# Service tests — create_supplier
# ---------------------------------------------------------------------------


class TestCreateSupplier:
    """Test create_supplier service function."""

    @pytest.mark.asyncio
    async def test_creates_supplier(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()

        result = await create_supplier(
            db,
            org_id=org_id,
            name="AutoParts NZ",
            contact_name="John Smith",
            email="john@ap.co.nz",
            phone="09-555-1234",
        )

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert result["name"] == "AutoParts NZ"
        assert result["contact_name"] == "John Smith"
        assert result["email"] == "john@ap.co.nz"
        assert "id" in result


# ---------------------------------------------------------------------------
# Service tests — list_suppliers
# ---------------------------------------------------------------------------


class TestListSuppliers:
    """Test list_suppliers service function."""

    @pytest.mark.asyncio
    async def test_returns_suppliers(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        suppliers = [_make_supplier(org_id=org_id), _make_supplier(org_id=org_id, name="Parts Plus")]

        db.execute = AsyncMock(
            side_effect=[_mock_count_result(2), _mock_scalars_result(suppliers)]
        )

        result = await list_suppliers(db, org_id=org_id)
        assert result["total"] == 2
        assert len(result["suppliers"]) == 2
        assert result["suppliers"][0]["name"] == "AutoParts NZ"

    @pytest.mark.asyncio
    async def test_empty_list(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()

        db.execute = AsyncMock(
            side_effect=[_mock_count_result(0), _mock_scalars_result([])]
        )

        result = await list_suppliers(db, org_id=org_id)
        assert result["total"] == 0
        assert result["suppliers"] == []


# ---------------------------------------------------------------------------
# Service tests — link_part_to_supplier
# ---------------------------------------------------------------------------


class TestLinkPartToSupplier:
    """Test link_part_to_supplier service function."""

    @pytest.mark.asyncio
    async def test_links_part_to_supplier(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        supplier = _make_supplier(org_id=org_id)
        part = _make_part(org_id=org_id)

        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one_or_none(supplier),
                _mock_scalar_one_or_none(part),
            ]
        )

        result = await link_part_to_supplier(
            db,
            org_id=org_id,
            supplier_id=supplier.id,
            part_id=part.id,
            supplier_part_number="SUP-BP-001",
            supplier_cost=30.0,
            is_preferred=True,
        )

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert result["supplier_part_number"] == "SUP-BP-001"
        assert result["supplier_cost"] == 30.0
        assert result["is_preferred"] is True

    @pytest.mark.asyncio
    async def test_supplier_not_found_raises(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()

        db.execute = AsyncMock(
            side_effect=[_mock_scalar_one_or_none(None)]
        )

        with pytest.raises(ValueError, match="Supplier not found"):
            await link_part_to_supplier(
                db,
                org_id=org_id,
                supplier_id=uuid.uuid4(),
                part_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_part_not_found_raises(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        supplier = _make_supplier(org_id=org_id)

        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one_or_none(supplier),
                _mock_scalar_one_or_none(None),
            ]
        )

        with pytest.raises(ValueError, match="Part not found"):
            await link_part_to_supplier(
                db,
                org_id=org_id,
                supplier_id=supplier.id,
                part_id=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# Service tests — generate_purchase_order_pdf
# ---------------------------------------------------------------------------


class TestGeneratePurchaseOrderPdf:
    """Test generate_purchase_order_pdf service function."""

    @pytest.mark.asyncio
    async def test_generates_pdf_bytes(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        supplier = _make_supplier(org_id=org_id)
        part = _make_part(org_id=org_id)
        ps = _make_part_supplier(part_id=part.id, supplier_id=supplier.id)

        # Mock org
        org_mock = MagicMock()
        org_mock.name = "Test Workshop"
        org_mock.settings = {
            "address": "1 Queen St",
            "phone": "09-000-0000",
            "email": "info@workshop.co.nz",
            "gst_number": "123-456-789",
            "primary_colour": "#336699",
        }

        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one_or_none(supplier),  # supplier lookup
                _mock_scalar_one_or_none(org_mock),   # org lookup
                _mock_scalar_one_or_none(part),        # part lookup
                _mock_scalar_one_or_none(ps),          # part_supplier lookup
            ]
        )

        mock_html_instance = MagicMock()
        mock_html_instance.write_pdf.return_value = b"%PDF-fake-content"
        mock_html_cls = MagicMock(return_value=mock_html_instance)

        # Mock both weasyprint and jinja2 at the import level
        import sys
        mock_weasyprint = MagicMock()
        mock_weasyprint.HTML = mock_html_cls
        sys.modules["weasyprint"] = mock_weasyprint

        try:
            result = await generate_purchase_order_pdf(
                db,
                org_id=org_id,
                supplier_id=supplier.id,
                items=[{"part_id": str(part.id), "quantity": 5}],
                notes="Urgent order",
            )

            assert result == b"%PDF-fake-content"
            mock_html_cls.assert_called_once()
            mock_html_instance.write_pdf.assert_called_once()
        finally:
            del sys.modules["weasyprint"]

    @pytest.mark.asyncio
    async def test_supplier_not_found_raises(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()

        db.execute = AsyncMock(
            side_effect=[_mock_scalar_one_or_none(None)]
        )

        # Mock weasyprint so the import doesn't fail
        import sys
        sys.modules["weasyprint"] = MagicMock()

        try:
            with pytest.raises(ValueError, match="Supplier not found"):
                await generate_purchase_order_pdf(
                    db,
                    org_id=org_id,
                    supplier_id=uuid.uuid4(),
                    items=[{"part_id": str(uuid.uuid4()), "quantity": 1}],
                )
        finally:
            del sys.modules["weasyprint"]
