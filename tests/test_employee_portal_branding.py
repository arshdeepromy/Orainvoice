"""Unit / smoke tests for the Employee Portal branding endpoint wiring.

Covers task 11.1 (``GET /e/api/branding/{slug}``) at the level that does not
require a live database: the route is mounted under ``/e/api``, the
``BrandingResponse`` schema loads and exposes only name + branding fields (no
other org data, R13.4), and the neutral-unavailable constant is the single
shared anti-enumeration message used for both the unknown-slug and
disabled-portal paths (R8.3).

The DB-backed behavioural property (slug-resolution minimal exposure: only name
+ branding for a genuine, enabled match; a neutral 404 with no fields for an
unknown slug or a disabled portal) is covered by Property 21 in task 11.5.

Implements: Organisation Employee Portal task 11.1 — Requirements 8.1, 8.2,
8.3, 13.1, 13.4.
"""

from __future__ import annotations


def test_app_factory_mounts_employee_portal_branding() -> None:
    """The branding route is registered under ``/e/api/branding/{slug}``."""
    from app.main import create_app

    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/e/api/branding/{slug}" in paths


def test_branding_response_schema_exposes_only_name_and_branding() -> None:
    """``BrandingResponse`` carries only name + branding fields (R13.4)."""
    from app.modules.employee_portal import schemas as S

    resp = S.BrandingResponse(
        org_name="Acme Ltd",
        logo_url="https://cdn.example/logo.png",
        primary_colour="#112233",
        secondary_colour="#445566",
    )
    assert set(resp.model_dump().keys()) == {
        "org_name",
        "logo_url",
        "primary_colour",
        "secondary_colour",
    }


def test_branding_response_branding_fields_are_nullable() -> None:
    """Unset logo/colours default to None so the SPA renders a neutral default."""
    from app.modules.employee_portal import schemas as S

    resp = S.BrandingResponse(org_name="Acme Ltd")
    assert resp.logo_url is None
    assert resp.primary_colour is None
    assert resp.secondary_colour is None


def test_portal_unavailable_message_is_a_single_constant() -> None:
    """Unknown-slug and disabled-portal share one neutral message (R8.3)."""
    from app.modules.employee_portal import router as R

    # The branding endpoint returns this identical body for both the unknown
    # slug and the disabled-portal paths so org existence never leaks.
    assert R._PORTAL_UNAVAILABLE_MESSAGE == "This portal is unavailable"
