"""Integration tests for printer config CRUD with new connection types and paper width range.

Tests Pydantic schema validation for:
- New connection types (star_webprnt, epson_epos, generic_http, browser_print)
- Legacy 'network' → 'generic_http' mapping
- Paper width range (30–120)
- Invalid connection types rejected
- Update operations

Also tests the router endpoints via httpx AsyncClient with mocked DB.

**Validates: Task 12.6 — POS Printer Integration**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.modules.receipt_printer.schemas import (
    PrinterConfigCreate,
    PrinterConfigUpdate,
    PrinterConfigResponse,
)
from app.modules.receipt_printer.router import router

ORG_ID = uuid.uuid4()

# ---------------------------------------------------------------------------
# Schema-level validation tests (no DB needed)
# ---------------------------------------------------------------------------


class TestPrinterConfigCreateSchema:
    """Validate PrinterConfigCreate schema accepts/rejects correctly."""

    @pytest.mark.parametrize("conn_type", [
        "star_webprnt", "epson_epos", "generic_http", "browser_print",
        "usb", "bluetooth",
    ])
    def test_create_with_valid_connection_types(self, conn_type: str):
        """Each new connection type is accepted."""
        cfg = PrinterConfigCreate(name="Test Printer", connection_type=conn_type)
        # 'network' maps to 'generic_http', others stay as-is
        assert cfg.connection_type == conn_type

    def test_create_legacy_network_maps_to_generic_http(self):
        """Legacy 'network' type is accepted and mapped to 'generic_http'."""
        cfg = PrinterConfigCreate(
            name="Legacy Printer",
            connection_type="network",
            address="192.168.1.50",
        )
        assert cfg.connection_type == "generic_http"

    def test_create_paper_width_min_30(self):
        """Paper width of 30 (minimum) is accepted."""
        cfg = PrinterConfigCreate(
            name="Narrow Printer",
            connection_type="generic_http",
            paper_width=30,
        )
        assert cfg.paper_width == 30

    def test_create_paper_width_max_120(self):
        """Paper width of 120 (maximum) is accepted."""
        cfg = PrinterConfigCreate(
            name="Wide Printer",
            connection_type="generic_http",
            paper_width=120,
        )
        assert cfg.paper_width == 120

    def test_create_paper_width_below_min_rejected(self):
        """Paper width of 29 is rejected with validation error."""
        with pytest.raises(ValidationError) as exc_info:
            PrinterConfigCreate(
                name="Too Narrow",
                connection_type="generic_http",
                paper_width=29,
            )
        assert "paper_width" in str(exc_info.value)

    def test_create_paper_width_above_max_rejected(self):
        """Paper width of 121 is rejected with validation error."""
        with pytest.raises(ValidationError) as exc_info:
            PrinterConfigCreate(
                name="Too Wide",
                connection_type="generic_http",
                paper_width=121,
            )
        assert "paper_width" in str(exc_info.value)

    def test_create_invalid_connection_type_rejected(self):
        """Invalid connection type is rejected with validation error."""
        with pytest.raises(ValidationError) as exc_info:
            PrinterConfigCreate(
                name="Bad Printer",
                connection_type="invalid_type",
            )
        assert "connection_type" in str(exc_info.value)

    def test_create_default_paper_width_is_80(self):
        """Default paper width is 80mm when not specified."""
        cfg = PrinterConfigCreate(name="Default", connection_type="usb")
        assert cfg.paper_width == 80


class TestPrinterConfigUpdateSchema:
    """Validate PrinterConfigUpdate schema accepts/rejects correctly."""

    @pytest.mark.parametrize("conn_type", [
        "star_webprnt", "epson_epos", "generic_http", "browser_print",
    ])
    def test_update_connection_type(self, conn_type: str):
        """Update with new connection types is accepted."""
        cfg = PrinterConfigUpdate(connection_type=conn_type)
        assert cfg.connection_type == conn_type

    def test_update_legacy_network_maps_to_generic_http(self):
        """Update with legacy 'network' maps to 'generic_http'."""
        cfg = PrinterConfigUpdate(connection_type="network")
        assert cfg.connection_type == "generic_http"

    def test_update_paper_width_valid_range(self):
        """Update paper width within valid range."""
        cfg = PrinterConfigUpdate(paper_width=58)
        assert cfg.paper_width == 58

    def test_update_paper_width_below_min_rejected(self):
        """Update paper width below minimum is rejected."""
        with pytest.raises(ValidationError):
            PrinterConfigUpdate(paper_width=29)

    def test_update_paper_width_above_max_rejected(self):
        """Update paper width above maximum is rejected."""
        with pytest.raises(ValidationError):
            PrinterConfigUpdate(paper_width=121)

    def test_update_invalid_connection_type_rejected(self):
        """Update with invalid connection type is rejected."""
        with pytest.raises(ValidationError):
            PrinterConfigUpdate(connection_type="wifi_direct")


# ---------------------------------------------------------------------------
# Router-level integration tests (mocked DB via httpx AsyncClient)
# ---------------------------------------------------------------------------


def _make_mock_printer(
    *,
    name: str = "Test Printer",
    connection_type: str = "generic_http",
    address: str | None = "192.168.1.100",
    paper_width: int = 80,
) -> MagicMock:
    """Create a mock PrinterConfig ORM object."""
    printer = MagicMock()
    printer.id = uuid.uuid4()
    printer.org_id = ORG_ID
    printer.location_id = None
    printer.name = name
    printer.connection_type = connection_type
    printer.address = address
    printer.paper_width = paper_width
    printer.is_default = False
    printer.is_kitchen_printer = False
    printer.is_active = True
    printer.created_at = datetime.now(timezone.utc)
    return printer


def _build_test_app() -> FastAPI:
    """Build a FastAPI app with the printer router and a mock DB dependency."""
    from app.core.database import get_db_session

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/printers")

    # Override the DB dependency so it never tries to connect
    async def _mock_db_session():
        yield AsyncMock()

    test_app.dependency_overrides[get_db_session] = _mock_db_session

    # Inject org_id into request.state via middleware
    @test_app.middleware("http")
    async def _inject_org_id(request, call_next):
        request.state.org_id = str(ORG_ID)
        return await call_next(request)

    return test_app


class TestPrinterRouterCRUD:
    """Integration tests for printer config CRUD endpoints."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("conn_type", [
        "star_webprnt", "epson_epos", "generic_http", "browser_print",
    ])
    async def test_create_printer_with_new_connection_types(self, conn_type: str):
        """POST /api/printers with each new connection type returns 201."""
        mock_printer = _make_mock_printer(connection_type=conn_type)
        test_app = _build_test_app()

        with patch(
            "app.modules.receipt_printer.router.PrinterService"
        ) as MockSvc:
            instance = MockSvc.return_value
            instance.configure_printer = AsyncMock(return_value=mock_printer)

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/printers",
                    json={
                        "name": "Test Printer",
                        "connection_type": conn_type,
                        "address": "192.168.1.100",
                    },
                )

        assert resp.status_code == 201
        data = resp.json()
        assert data["connection_type"] == conn_type

    @pytest.mark.asyncio
    async def test_create_printer_legacy_network_stored_as_generic_http(self):
        """POST with 'network' type → Pydantic maps to 'generic_http' before service call."""
        mock_printer = _make_mock_printer(connection_type="generic_http")
        test_app = _build_test_app()

        with patch(
            "app.modules.receipt_printer.router.PrinterService"
        ) as MockSvc:
            instance = MockSvc.return_value
            instance.configure_printer = AsyncMock(return_value=mock_printer)

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/printers",
                    json={
                        "name": "Legacy Printer",
                        "connection_type": "network",
                        "address": "192.168.1.50",
                    },
                )

        assert resp.status_code == 201
        # The service receives 'generic_http' after Pydantic validator maps it
        call_args = instance.configure_printer.call_args
        payload = call_args[0][1]  # second positional arg is the schema
        assert payload.connection_type == "generic_http"

    @pytest.mark.asyncio
    async def test_create_printer_invalid_connection_type_422(self):
        """POST with invalid connection_type returns 422."""
        test_app = _build_test_app()

        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/printers",
                json={
                    "name": "Bad Printer",
                    "connection_type": "invalid_type",
                },
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_printer_paper_width_too_low_422(self):
        """POST with paper_width=29 returns 422."""
        test_app = _build_test_app()

        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/printers",
                json={
                    "name": "Narrow",
                    "connection_type": "generic_http",
                    "paper_width": 29,
                },
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_printer_paper_width_too_high_422(self):
        """POST with paper_width=121 returns 422."""
        test_app = _build_test_app()

        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/printers",
                json={
                    "name": "Wide",
                    "connection_type": "generic_http",
                    "paper_width": 121,
                },
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_printer_connection_type_and_paper_width(self):
        """PUT /{printer_id} updates connection_type and paper_width."""
        printer_id = uuid.uuid4()
        mock_printer = _make_mock_printer(
            connection_type="epson_epos", paper_width=58,
        )
        mock_printer.id = printer_id
        test_app = _build_test_app()

        with patch(
            "app.modules.receipt_printer.router.PrinterService"
        ) as MockSvc:
            instance = MockSvc.return_value
            instance.update_printer = AsyncMock(return_value=mock_printer)

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    f"/api/printers/{printer_id}",
                    json={
                        "connection_type": "epson_epos",
                        "paper_width": 58,
                    },
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["connection_type"] == "epson_epos"
        assert data["paper_width"] == 58

    @pytest.mark.asyncio
    async def test_read_printer_config_returns_all_fields(self):
        """GET /api/printers returns all fields correctly."""
        mock_printer = _make_mock_printer(
            name="Star Printer",
            connection_type="star_webprnt",
            address="192.168.1.200",
            paper_width=80,
        )
        test_app = _build_test_app()

        with patch(
            "app.modules.receipt_printer.router.PrinterService"
        ) as MockSvc:
            instance = MockSvc.return_value
            instance.list_printers = AsyncMock(return_value=[mock_printer])

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/printers")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        printer = data[0]
        assert printer["name"] == "Star Printer"
        assert printer["connection_type"] == "star_webprnt"
        assert printer["address"] == "192.168.1.200"
        assert printer["paper_width"] == 80
        assert printer["is_default"] is False
        assert printer["is_active"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("paper_width", [30, 120])
    async def test_create_printer_boundary_paper_widths(self, paper_width: int):
        """POST with paper_width at boundaries (30, 120) succeeds."""
        mock_printer = _make_mock_printer(paper_width=paper_width)
        test_app = _build_test_app()

        with patch(
            "app.modules.receipt_printer.router.PrinterService"
        ) as MockSvc:
            instance = MockSvc.return_value
            instance.configure_printer = AsyncMock(return_value=mock_printer)

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/printers",
                    json={
                        "name": "Boundary Printer",
                        "connection_type": "generic_http",
                        "paper_width": paper_width,
                    },
                )

        assert resp.status_code == 201
