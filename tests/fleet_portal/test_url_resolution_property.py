"""Property test for Workshop_Org URL resolution (Property 4).

Implements Property 4: ``resolve_workshop_org_from_request`` returns
exactly one Workshop_Org or HTTP 404; never silently picks a different
org and never falls through to the staff ``/login`` page.

Validates Requirements: 2.3, 2.4.

Tests are pure-Python — they exercise the helper functions
``_extract_subdomain_slug`` and ``_extract_path_slug`` directly, plus
end-to-end resolver behaviour via a stubbed DB session that returns a
canned org row when the slug matches a fixture string.

File path mandated by spec ``.kiro/specs/b2b-fleet-portal/tasks.md``
task 3.4.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st

# Ensure relationship models are loaded for SQLAlchemy mapper init.
# Without this, Organisation.users (-> User) cannot resolve when we
# build select() statements against Organisation in the resolver.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.modules.fleet_portal import dependencies as fp_deps


# ---------------------------------------------------------------------------
# _extract_subdomain_slug
# ---------------------------------------------------------------------------


def test_subdomain_slug_extracted_from_matching_host() -> None:
    assert (
        fp_deps._extract_subdomain_slug("acme.fleet.example.com", "fleet.example.com")
        == "acme"
    )


def test_subdomain_slug_none_when_host_equals_fleet_host() -> None:
    """``fleet.example.com`` itself is not a slug — single-tenant case."""
    assert (
        fp_deps._extract_subdomain_slug("fleet.example.com", "fleet.example.com")
        is None
    )


def test_subdomain_slug_none_for_unrelated_host() -> None:
    assert (
        fp_deps._extract_subdomain_slug("acme.example.com", "fleet.example.com")
        is None
    )


def test_subdomain_slug_none_for_deeper_subdomain() -> None:
    """Multi-label subdomains aren't allowed — only ``<slug>.fleet.<...>``."""
    assert (
        fp_deps._extract_subdomain_slug(
            "a.b.fleet.example.com", "fleet.example.com"
        )
        is None
    )


def test_subdomain_slug_none_when_fleet_host_unset() -> None:
    assert fp_deps._extract_subdomain_slug("acme.fleet.example.com", "") is None


def test_subdomain_slug_strips_port() -> None:
    assert (
        fp_deps._extract_subdomain_slug(
            "acme.fleet.example.com:8080", "fleet.example.com"
        )
        == "acme"
    )


@given(slug=st.text(min_size=1, max_size=64))
@hyp_settings(max_examples=200)
def test_subdomain_slug_only_returns_validated_slugs(slug: str) -> None:
    """Property 4 — a slug is returned iff it matches the slug regex.

    The host header is lowercased before extraction (DNS is
    case-insensitive), so the returned slug is the lower-case form of
    the input.
    """
    host = f"{slug}.fleet.example.com"
    result = fp_deps._extract_subdomain_slug(host, "fleet.example.com")
    if result is not None:
        assert fp_deps._SLUG_RE.fullmatch(result) is not None
        assert result == slug.lower()


# ---------------------------------------------------------------------------
# _extract_path_slug
# ---------------------------------------------------------------------------


def test_path_slug_extracted_from_two_segment_path() -> None:
    assert fp_deps._extract_path_slug("/fleet/acme/dashboard") == "acme"


def test_path_slug_none_for_login_route() -> None:
    """``/fleet/login`` has no slug — single-tenant entry path."""
    assert fp_deps._extract_path_slug("/fleet/login") is None


def test_path_slug_none_for_api_route() -> None:
    assert fp_deps._extract_path_slug("/fleet/api/auth/login") is None


def test_path_slug_none_for_bare_fleet_path() -> None:
    assert fp_deps._extract_path_slug("/fleet") is None
    assert fp_deps._extract_path_slug("/fleet/") is None


def test_path_slug_none_for_unrelated_path() -> None:
    assert fp_deps._extract_path_slug("/admin") is None
    assert fp_deps._extract_path_slug("/api/v2/customers") is None


@given(slug=st.text(min_size=1, max_size=64))
@hyp_settings(max_examples=200)
def test_path_slug_only_returns_validated_slugs(slug: str) -> None:
    """A returned slug always matches the slug regex AND is not reserved."""
    path = f"/fleet/{slug}/dashboard"
    result = fp_deps._extract_path_slug(path)
    if result is not None:
        assert fp_deps._SLUG_RE.fullmatch(result) is not None
        assert result not in fp_deps._PATH_RESERVED


# ---------------------------------------------------------------------------
# End-to-end resolver — exhaustive precedence check
# ---------------------------------------------------------------------------


@dataclass
class _FakeOrg:
    id: UUID
    name: str


def _build_request(host: str, path: str) -> MagicMock:
    """Construct a minimal Request-like mock for the resolver."""
    req = MagicMock()
    req.headers = {"host": host}
    req.url.path = path
    return req


class _FakeDB:
    """Stub that monkey-patches the resolver's lookup helpers.

    Rather than mock the AsyncSession.execute machinery, we patch
    ``_lookup_org_by_slug`` and ``_lookup_org_by_id_string`` at module
    level via ``monkeypatch.setattr`` in the fixture below. This keeps
    the test focused on resolver precedence semantics, not SQLAlchemy
    wire format.
    """

    def __init__(self, slug_to_org: dict[str, _FakeOrg]):
        self._slug_to_org = {k.lower(): v for k, v in slug_to_org.items()}

    async def lookup_slug(self, _db, slug: str):  # noqa: ARG002
        return self._slug_to_org.get(slug.strip().lower())

    async def lookup_id(self, _db, candidate: str):  # noqa: ARG002
        for v in self._slug_to_org.values():
            if str(v.id) == candidate:
                return v
        return None


def _patch_lookups(monkeypatch, fake_db: _FakeDB) -> None:
    """Wire the fake DB lookups into the resolver module."""
    monkeypatch.setattr(fp_deps, "_lookup_org_by_slug", fake_db.lookup_slug)
    monkeypatch.setattr(fp_deps, "_lookup_org_by_id_string", fake_db.lookup_id)


@pytest.mark.asyncio
async def test_resolver_picks_subdomain_first(monkeypatch) -> None:
    """Property 4 — subdomain takes precedence over path and default."""
    org_a = _FakeOrg(id=uuid4(), name="acme")
    org_b = _FakeOrg(id=uuid4(), name="beta")

    monkeypatch.setattr(fp_deps.settings, "fleet_portal_host", "fleet.example.com")
    monkeypatch.setattr(
        fp_deps.settings, "fleet_portal_default_org_slug", "beta"
    )

    db = _FakeDB({"acme": org_a, "beta": org_b})
    _patch_lookups(monkeypatch, db)
    req = _build_request("acme.fleet.example.com", "/fleet/beta/dashboard")
    result = await fp_deps.resolve_workshop_org_from_request(req, MagicMock())
    assert result is org_a


@pytest.mark.asyncio
async def test_resolver_picks_path_when_no_subdomain(monkeypatch) -> None:
    org_a = _FakeOrg(id=uuid4(), name="acme")
    monkeypatch.setattr(fp_deps.settings, "fleet_portal_host", "")
    monkeypatch.setattr(fp_deps.settings, "fleet_portal_default_org_slug", "")

    db = _FakeDB({"acme": org_a})
    _patch_lookups(monkeypatch, db)
    req = _build_request("example.com", "/fleet/acme/dashboard")
    result = await fp_deps.resolve_workshop_org_from_request(req, MagicMock())
    assert result is org_a


@pytest.mark.asyncio
async def test_resolver_falls_back_to_default(monkeypatch) -> None:
    org_default = _FakeOrg(id=uuid4(), name="default-org")
    monkeypatch.setattr(fp_deps.settings, "fleet_portal_host", "")
    db = _FakeDB({"default-org": org_default})
    _patch_lookups(monkeypatch, db)
    # Patch the single-tenant fallback to return the org (simulates DB lookup)
    async def _single_tenant_returns_org(_db):
        return org_default
    monkeypatch.setattr(fp_deps, "_resolve_single_tenant_org", _single_tenant_returns_org)
    req = _build_request("example.com", "/fleet/login")
    result = await fp_deps.resolve_workshop_org_from_request(req, MagicMock())
    assert result is org_default


@pytest.mark.asyncio
async def test_resolver_returns_none_when_unresolvable(monkeypatch) -> None:
    monkeypatch.setattr(fp_deps.settings, "fleet_portal_host", "")
    db = _FakeDB({})
    _patch_lookups(monkeypatch, db)
    # Also patch the single-tenant fallback to return None
    async def _no_single_tenant(_db):
        return None
    monkeypatch.setattr(fp_deps, "_resolve_single_tenant_org", _no_single_tenant)
    req = _build_request("example.com", "/fleet/login")
    result = await fp_deps.resolve_workshop_org_from_request(req, MagicMock())
    assert result is None


@pytest.mark.asyncio
async def test_resolver_never_falls_through_to_arbitrary_org(monkeypatch) -> None:
    """Property 4 — an unknown slug returns None, NOT some other org."""
    real_org = _FakeOrg(id=uuid4(), name="acme")
    monkeypatch.setattr(fp_deps.settings, "fleet_portal_host", "fleet.example.com")
    monkeypatch.setattr(fp_deps.settings, "fleet_portal_default_org_slug", "")
    db = _FakeDB({"acme": real_org})
    _patch_lookups(monkeypatch, db)
    req = _build_request("ghost.fleet.example.com", "/fleet/login")
    result = await fp_deps.resolve_workshop_org_from_request(req, MagicMock())
    assert result is None
