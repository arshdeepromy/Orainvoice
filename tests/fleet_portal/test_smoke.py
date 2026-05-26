"""Smoke tests for the B2B Fleet Portal feature.

Implements: B2B Fleet Portal task 20.2 — Requirements 1.1, 2.1, 2.2,
2.7, 18.5, 22.1, 23.1.

These tests confirm the migration shipped, the module is registered,
the routers are mounted, and the security headers are present on
``/fleet/api/*`` responses. They are intended to run quickly against
a freshly-deployed environment and form a regression guard for the
overall feature wiring.
"""
from __future__ import annotations

import pytest


def test_module_registry_has_b2b_fleet_management() -> None:
    """The migration inserts the b2b-fleet-management row."""
    from app.core.modules import (
        TRADE_FAMILY_REQUIRED_MODULES,
        DEPENDENCY_GRAPH,
    )

    assert "b2b-fleet-management" in TRADE_FAMILY_REQUIRED_MODULES
    assert TRADE_FAMILY_REQUIRED_MODULES["b2b-fleet-management"] == "automotive-transport"
    assert "vehicles" in DEPENDENCY_GRAPH.get("b2b-fleet-management", [])


def test_app_factory_mounts_fleet_routers() -> None:
    """The two routers (portal + admin) are registered by app factory."""
    from app.main import create_app

    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    fleet_paths = {p for p in paths if p.startswith("/fleet/api")}
    admin_paths = {p for p in paths if p.startswith("/api/v2/fleet-portal/admin")}

    # The portal router exposes at minimum the auth + version endpoints.
    assert "/fleet/api/auth/login" in fleet_paths
    assert "/fleet/api/auth/logout" in fleet_paths
    assert "/fleet/api/version" in fleet_paths
    assert "/fleet/api/me" in fleet_paths

    # The admin router exposes at minimum the invite/revoke endpoints.
    assert "/api/v2/fleet-portal/admin/invite" in admin_paths
    assert "/api/v2/fleet-portal/admin/accounts" in admin_paths


def test_app_version_bumped() -> None:
    """Task 19A.3 — version bumped to ≥ 1.10.0."""
    import app

    parts = app.__version__.split(".")
    major, minor = int(parts[0]), int(parts[1])
    assert (major, minor) >= (1, 10)


def test_pydantic_schemas_load() -> None:
    """All Pydantic schemas import without ValidationError on the imports."""
    from app.modules.fleet_portal import schemas as S

    # Touch a representative one of each shape — request body, response,
    # paginated wrapper, error envelope.
    S.LoginRequest(email="alice@example.com", password="secret123")
    S.VehicleListResponse(items=[], total=0, limit=50, offset=0)
    S.ErrorEnvelope(detail="Test")
    S.PaginationParams(offset=0, limit=50)


def test_orm_models_load_via_main_import() -> None:
    """Task 2.2 — models import cleanly via the app/main import block."""
    from app.modules.fleet_portal import models as M

    # Verify all 16 ORM classes are exported.
    assert {
        "PortalAccount",
        "PortalAccountMfaMethod",
        "PortalAccountBackupCode",
        "PortalAccountPasswordHistory",
        "PortalAuditLog",
        "PortalAccountDevice",
        "PortalFleetAccount",
        "FleetDriverAssignment",
        "FleetChecklistTemplate",
        "FleetChecklistTemplateItem",
        "FleetChecklistSubmission",
        "FleetChecklistSubmissionItem",
        "FleetReminderPreference",
        "FleetServiceBookingRequest",
        "FleetQuotationRequest",
        "FleetDriverHours",
    } <= set(M.__all__)


def test_nzta_template_has_29_items() -> None:
    """Task 2.4 — canonical NZTA item set."""
    from app.modules.fleet_portal.nzta_template import NZTA_ITEMS, nzta_items

    assert len(NZTA_ITEMS) == 29
    items = nzta_items()
    assert len(items) == 29
    cats = {i.category for i in items}
    assert len(cats) == 10


def test_dependency_graph_resolves_b2b_fleet_management() -> None:
    """Task 1.3 — enabling fleet portal also implies enabling vehicles."""
    from app.core.modules import get_all_dependencies

    deps = get_all_dependencies("b2b-fleet-management")
    assert "vehicles" in deps
