"""Unit / smoke tests for the public portal-resolve endpoint wiring.

Covers task 11.2 (``GET /api/v2/public/portal-resolve``) at the level that does
not require a live database:

- the route is mounted at **exactly** ``/api/v2/public/portal-resolve`` (so the
  ``/api/v2/public/`` JWT bypass applies, R9.2, and the rate-limit path constant
  ``_PORTAL_RESOLVE_PATH`` matches, task 12.2);
- the ``PortalResolveMatch`` response carries org id + name + branding only and
  the ``PortalResolveCandidate`` carries name + branding only — never any other
  org data, and a candidate never carries the org id so an ambiguous name is not
  auto-resolved (R9.4, R9.5);
- the ``PortalBranding`` projection exposes only the logo + brand colours (R9.5);
- the ``_ilike_pattern`` helper escapes ``LIKE`` wildcards so a query like ``%``
  cannot match every organisation;
- the not-found body is the single neutral ``not_found`` envelope used for both
  "no match" and "match exists but portal disabled" (R9.3, R9.8).

The DB-backed behavioural property (slug-resolution minimal exposure: only name
+ branding for genuine enabled matches, at most 10 candidates, never
auto-resolve an ambiguous name, and reveal nothing for non-matching or
disabled-portal orgs) is covered by Property 21 in task 11.5.

Implements: Organisation Employee Portal task 11.2 — Requirements 9.1, 9.2, 9.3,
9.4, 9.5, 9.8, 8.3.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace


def test_app_factory_mounts_portal_resolve_at_exact_path() -> None:
    """The lookup route is registered at exactly ``/api/v2/public/portal-resolve``."""
    from app.main import create_app

    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/v2/public/portal-resolve" in paths


def test_rate_limit_constant_matches_mounted_path() -> None:
    """The rate-limit path constant matches the mounted route (task 12.2)."""
    from app.middleware.rate_limit import _PORTAL_RESOLVE_PATH

    assert _PORTAL_RESOLVE_PATH == "/api/v2/public/portal-resolve"


def test_match_schema_exposes_only_id_name_and_branding() -> None:
    """``PortalResolveMatch`` carries only org_id + org_name + branding (R9.5)."""
    from app.modules.employee_portal import schemas as S

    m = S.PortalResolveMatch(
        org_id=uuid.uuid4(),
        org_name="Acme Ltd",
        branding=S.PortalBranding(
            logo_url="https://cdn.example/logo.png",
            primary_colour="#112233",
            secondary_colour="#445566",
        ),
    )
    assert set(m.model_dump().keys()) == {"org_id", "org_name", "branding"}
    assert set(m.branding.model_dump().keys()) == {
        "logo_url",
        "primary_colour",
        "secondary_colour",
    }


def test_candidate_schema_exposes_only_name_and_branding_no_id() -> None:
    """``PortalResolveCandidate`` carries name + branding only — never the id (R9.4)."""
    from app.modules.employee_portal import schemas as S

    c = S.PortalResolveCandidate(
        org_name="Acme Ltd", branding=S.PortalBranding()
    )
    keys = set(c.model_dump().keys())
    assert keys == {"org_name", "branding"}
    # A candidate must NOT carry the org id, so an ambiguous name is never
    # auto-resolved to a single addressable identity.
    assert "org_id" not in keys


def test_branding_fields_are_nullable() -> None:
    """Unset logo/colours default to None so a neutral default can render (R13.2)."""
    from app.modules.employee_portal import schemas as S

    b = S.PortalBranding()
    assert b.logo_url is None
    assert b.primary_colour is None
    assert b.secondary_colour is None


def test_ilike_pattern_escapes_wildcards() -> None:
    """A query containing LIKE wildcards is matched literally, not as a wildcard."""
    from app.modules.employee_portal.public_router import _ilike_pattern

    # Percent and underscore are escaped so they cannot match arbitrary text.
    assert _ilike_pattern("%") == "%\\%%"
    assert _ilike_pattern("a_b") == "%a\\_b%"
    # Backslash itself is escaped first so the escape char is literal.
    assert _ilike_pattern("a\\b") == "%a\\\\b%"
    # Surrounding whitespace is trimmed before wrapping.
    assert _ilike_pattern("  acme  ") == "%acme%"


def test_branding_projection_reads_only_branding_keys_from_settings() -> None:
    """``_branding`` projects only logo + colours from the org settings (R9.5)."""
    from app.modules.employee_portal.public_router import _branding

    org = SimpleNamespace(
        id=uuid.uuid4(),
        name="Acme Ltd",
        slug="acme",
        settings={
            "logo_url": "https://cdn.example/logo.png",
            "primary_colour": "#112233",
            "secondary_colour": "#445566",
            # Sensitive / unrelated org data that must NOT leak through.
            "gst_number": "123-456-789",
            "employee_portal_enabled": True,
            "address": "1 Secret Way",
        },
    )
    branding = _branding(org)
    dumped = branding.model_dump()
    assert dumped == {
        "logo_url": "https://cdn.example/logo.png",
        "primary_colour": "#112233",
        "secondary_colour": "#445566",
    }
    assert "gst_number" not in dumped
    assert "address" not in dumped


def test_branding_projection_handles_missing_settings() -> None:
    """A null/empty settings JSONB yields all-null branding rather than raising."""
    from app.modules.employee_portal.public_router import _branding

    org = SimpleNamespace(id=uuid.uuid4(), name="Acme", slug="acme", settings=None)
    branding = _branding(org)
    assert branding.model_dump() == {
        "logo_url": None,
        "primary_colour": None,
        "secondary_colour": None,
    }


def test_not_found_message_is_a_single_neutral_constant() -> None:
    """No-match and disabled-portal share one neutral not_found message (R9.3, R9.8)."""
    from app.modules.employee_portal import public_router as P

    assert isinstance(P._NOT_FOUND_MESSAGE, str)
    assert P._MAX_CANDIDATES == 10
