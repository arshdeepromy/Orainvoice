"""Property-based test: slug-resolution minimal exposure.

# Feature: organisation-employee-portal, Property 21: Slug-resolution minimal exposure

**Validates: Requirements 9.3, 9.4, 9.5, 9.8, 8.3**

Property 21 (design.md): *For any* slug-resolution lookup, the response contains
only the matched organisation's name and Portal_Branding fields and nothing
else, returns at most 10 candidates on a name-disambiguation result, never
auto-resolves an ambiguous name to a single identity, and reveals no information
(not even branding) for organisations that do not match or whose requested
portal type is disabled.

The endpoint under test is the real route function
``app.modules.employee_portal.public_router.portal_resolve``
(``GET /api/v2/public/portal-resolve``, task 11.2). For ``portal_type=employee``
an org is "enabled" iff ``employee_portal_enabled`` is set in Org_Settings AND a
slug is present (mirrors the login-enablement gate, R4.4).

Each example seeds a fresh constellation of organisations that all share one
unique **name token** (so a name ``ILIKE`` lookup on that token returns many),
split into:

- ``num_enabled`` employee-portal-enabled orgs (distinct slug + branding +
  ``employee_portal_enabled=True``), and
- ``num_disabled`` orgs that carry a slug **and** the shared name token but have
  ``employee_portal_enabled=False`` (a "match exists but portal disabled" case),
  branded with a sentinel colour so any leakage is detectable.

Four scenarios are then exercised against the live route:

- ``match_exact_slug`` — query an enabled org's exact slug → ``200 {match}``
  carrying ONLY ``{org_id, org_name, branding}`` (branding = logo + colours
  only), and the resolved identity is that org (R9.1, R9.5).
- ``candidates_ambiguous`` — query the shared name token (matched by ≥2 enabled
  orgs) → ``200 {candidates}``: each candidate carries ONLY ``{org_name,
  branding}`` (never an org id), the list is capped at 10, the ambiguous name is
  never auto-resolved to a single ``match``, and no disabled org's sentinel
  branding leaks (R9.4, R9.5).
- ``disabled_slug`` — query a disabled org's exact slug → neutral
  ``404 not_found`` exposing nothing, not even branding or the org name
  (R9.8, R8.3).
- ``nonmatch`` — query a string that matches no org → neutral ``404 not_found``
  that enumerates nothing (R9.3).

DB-backed Hypothesis test against the transactional dev Postgres, mirroring the
established pattern in
``tests/test_employee_portal_login_resolution_property.py``: a fresh async
engine per example (asyncpg connections are bound to the loop ``asyncio.run``
creates), the full ORM import block, an org-name marker for orphan cleanup, and
an ``asyncio.run`` driver. The route is invoked directly with a seeded async
session.

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests, e.g. tests/test_employee_portal_login_resolution_property.py).
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.notifications import models as _notif_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.module_management import models as _module_mgmt_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401
from app.modules.compliance_docs import models as _compliance_models  # noqa: F401
from app.modules.employee_portal import models as _emp_portal_models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.employee_portal import public_router
from app.modules.employee_portal import schemas as S

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other portal DB property tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_P21_slug_resolution"

# Branding the seeder stamps on each role so leakage is detectable: an enabled
# org's colour may legitimately appear in a result; a disabled org's sentinel
# colour must NEVER appear in any response body (R9.8).
_ENABLED_COLOUR = "#E9AB1E"
_DISABLED_COLOUR = "#D15AB1"

# Maximum disambiguation candidates the endpoint returns (R9.4); mirrors
# ``public_router._MAX_CANDIDATES``.
_MAX_CANDIDATES = 10

# The four lookup scenarios exercised by the property.
_SCENARIOS = [
    "match_exact_slug",
    "candidates_ambiguous",
    "disabled_slug",
    "nonmatch",
]

# Only these keys may ever appear on a resolved match / candidate (R9.5).
_MATCH_KEYS = {"org_id", "org_name", "branding"}
_CANDIDATE_KEYS = {"org_name", "branding"}
_BRANDING_KEYS = {"logo_url", "primary_colour", "secondary_colour"}


# ---------------------------------------------------------------------------
# Engine / cleanup helpers (fresh engine per example).
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _cleanup(factory) -> None:
    """Delete every row created by the seeder (keyed on the org-name marker)."""
    async with factory() as session:
        async with session.begin():
            await session.execute(
                sa_text("DELETE FROM organisations WHERE name LIKE :marker"),
                {"marker": f"{_ORG_MARKER}%"},
            )
            await session.execute(
                sa_text("DELETE FROM subscription_plans WHERE name LIKE :marker"),
                {"marker": f"{_ORG_MARKER}_plan%"},
            )


def _valid_slug(prefix: str) -> str:
    """Build a globally-unique, format-valid slug (``^[a-z0-9]+(-[a-z0-9]+)*$``)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def _seed_constellation(
    factory, *, token: str, num_enabled: int, num_disabled: int
) -> dict:
    """Seed ``num_enabled`` enabled + ``num_disabled`` disabled orgs sharing ``token``.

    Every org's name embeds the unique ``token`` so a name ``ILIKE`` lookup on it
    matches the whole constellation; only the enabled ones should ever surface.

    Returns the slugs needed to drive each scenario.
    """
    async with factory() as session:
        async with session.begin():
            plan = SubscriptionPlan(
                name=f"{_ORG_MARKER}_plan_{uuid.uuid4().hex[:8]}",
                monthly_price_nzd=0,
                user_seats=5,
                storage_quota_gb=1,
                carjam_lookups_included=0,
                enabled_modules=[],
            )
            session.add(plan)
            await session.flush()

            enabled_slugs: list[str] = []
            disabled_slugs: list[str] = []

            for i in range(num_enabled):
                slug = _valid_slug("epr-en")
                enabled_slugs.append(slug)
                session.add(
                    Organisation(
                        name=f"{_ORG_MARKER}_{token}_EN_{i}_{uuid.uuid4().hex[:8]}",
                        plan_id=plan.id,
                        status="active",
                        storage_quota_gb=1,
                        locale="en",
                        slug=slug,
                        settings={
                            "employee_portal_enabled": True,
                            "logo_url": f"https://logo.example/{slug}.png",
                            "primary_colour": _ENABLED_COLOUR,
                            "secondary_colour": "#222222",
                        },
                    )
                )

            for i in range(num_disabled):
                # Disabled orgs DO carry a slug + the shared token, but the
                # employee portal flag is off → "match exists but disabled".
                slug = _valid_slug("epr-dis")
                disabled_slugs.append(slug)
                session.add(
                    Organisation(
                        name=f"{_ORG_MARKER}_{token}_DIS_{i}_{uuid.uuid4().hex[:8]}",
                        plan_id=plan.id,
                        status="active",
                        storage_quota_gb=1,
                        locale="en",
                        slug=slug,
                        settings={
                            "employee_portal_enabled": False,
                            "logo_url": f"https://logo.example/{slug}.png",
                            "primary_colour": _DISABLED_COLOUR,
                            "secondary_colour": "#333333",
                        },
                    )
                )

            return {
                "enabled_slugs": enabled_slugs,
                "disabled_slugs": disabled_slugs,
            }


async def _resolve(factory, q: str):
    """Invoke the real ``portal_resolve`` route with a seeded session.

    Returns ``("ok", body_dict)`` for a 2xx return or ``("404", detail)`` when the
    route raises the neutral not-found ``HTTPException``.
    """
    async with factory() as session:
        try:
            result = await public_router.portal_resolve(
                q=q, portal_type="employee", db=session
            )
        except HTTPException as exc:
            assert exc.status_code == 404
            return "404", exc.detail
    return "ok", result


def _assert_branding_only(branding) -> None:
    """A branding object exposes ONLY logo + brand colours (R9.5)."""
    assert isinstance(branding, S.PortalBranding)
    assert set(branding.model_dump().keys()) == _BRANDING_KEYS


def _assert_reveals_nothing(detail, *, token: str, slugs: list[str]) -> None:
    """A neutral 404 body enumerates nothing — no branding, name, slug, token.

    R9.3/R9.8/R8.3: the not-found result must not expose any organisation
    identity or its Portal_Branding.
    """
    assert isinstance(detail, dict), detail
    assert set(detail.keys()) <= {"message", "code"}, detail
    assert detail.get("code") == "not_found", detail
    serialised = str(detail)
    # Neither the shared name token, any slug, nor any branding colour leaks.
    assert token not in serialised, detail
    for slug in slugs:
        assert slug not in serialised, detail
    assert _ENABLED_COLOUR not in serialised, detail
    assert _DISABLED_COLOUR not in serialised, detail
    assert "logo.example" not in serialised, detail


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(scenario: str, num_enabled: int, num_disabled: int) -> None:
    engine, factory = await _make_engine_and_factory()
    # Unique-per-example name token so the name ILIKE lookup only ever matches
    # this example's constellation (never real data or another example's orgs).
    token = f"p21t{uuid.uuid4().hex[:18]}"
    all_slugs: list[str] = []
    try:
        seed = await _seed_constellation(
            factory, token=token, num_enabled=num_enabled, num_disabled=num_disabled
        )
        enabled_slugs = seed["enabled_slugs"]
        disabled_slugs = seed["disabled_slugs"]
        all_slugs = enabled_slugs + disabled_slugs

        if scenario == "match_exact_slug":
            # Exact slug of an enabled org → single resolved match, name +
            # branding + id only (R9.1, R9.5).
            target_slug = enabled_slugs[0]
            kind, result = await _resolve(factory, target_slug)
            assert kind == "ok", result
            assert "match" in result, result
            assert "candidates" not in result, result
            match = result["match"]
            assert isinstance(match, S.PortalResolveMatch)
            assert set(match.model_dump().keys()) == _MATCH_KEYS
            _assert_branding_only(match.branding)
            # Branding is the enabled org's, and the token never leaks via name.
            assert match.branding.primary_colour == _ENABLED_COLOUR
            assert match.branding.secondary_colour == "#222222"
            assert match.org_name.startswith(f"{_ORG_MARKER}_{token}_EN_")

        elif scenario == "candidates_ambiguous":
            # The shared name token is matched by >= 2 enabled orgs → a
            # disambiguation list, never an auto-resolved single identity (R9.4).
            kind, result = await _resolve(factory, token)
            assert kind == "ok", result
            assert "candidates" in result, result
            # Never auto-resolve an ambiguous name to a single match (R9.4).
            assert "match" not in result, result
            candidates = result["candidates"]
            expected = min(num_enabled, _MAX_CANDIDATES)
            assert len(candidates) == expected, (len(candidates), expected)
            # At most 10 candidates (R9.4).
            assert len(candidates) <= _MAX_CANDIDATES
            for cand in candidates:
                assert isinstance(cand, S.PortalResolveCandidate)
                # A candidate carries ONLY name + branding — never an org id, so
                # the ambiguous name is not resolved to an addressable identity.
                assert set(cand.model_dump().keys()) == _CANDIDATE_KEYS
                assert "org_id" not in cand.model_dump()
                _assert_branding_only(cand.branding)
                # Every candidate is an ENABLED org — no disabled-org leakage.
                assert cand.branding.primary_colour == _ENABLED_COLOUR
                assert cand.org_name.startswith(f"{_ORG_MARKER}_{token}_EN_")
            # The disabled orgs' sentinel branding must not appear anywhere.
            assert all(
                c.branding.primary_colour != _DISABLED_COLOUR for c in candidates
            )

        elif scenario == "disabled_slug":
            # Exact slug of a portal-DISABLED org → neutral 404 exposing nothing,
            # not even branding (R9.8, R8.3).
            target_slug = disabled_slugs[0]
            kind, detail = await _resolve(factory, target_slug)
            assert kind == "404", detail
            _assert_reveals_nothing(detail, token=token, slugs=all_slugs)

        else:  # nonmatch — a query that matches no organisation at all (R9.3).
            miss = f"nomatch-{uuid.uuid4().hex}"
            kind, detail = await _resolve(factory, miss)
            assert kind == "404", detail
            _assert_reveals_nothing(detail, token=token, slugs=all_slugs)
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 21: Slug-resolution minimal exposure.
# ---------------------------------------------------------------------------


@settings(
    max_examples=110,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    scenario=st.sampled_from(_SCENARIOS),
    # >= 2 enabled so the shared-name lookup is genuinely ambiguous; up to 12 so
    # the 10-candidate cap (R9.4) is exercised.
    num_enabled=st.integers(min_value=2, max_value=12),
    num_disabled=st.integers(min_value=1, max_value=3),
)
def test_slug_resolution_minimal_exposure(
    scenario: str, num_enabled: int, num_disabled: int
) -> None:
    """Property 21: Slug-resolution minimal exposure.

    # Feature: organisation-employee-portal, Property 21: Slug-resolution minimal exposure

    A slug-resolution lookup exposes only org name + Portal_Branding for genuine
    enabled matches, returns at most 10 candidates, never auto-resolves an
    ambiguous name to a single identity, and reveals nothing (not even branding)
    for non-matching or disabled-portal organisations.

    **Validates: Requirements 9.3, 9.4, 9.5, 9.8, 8.3**
    """
    asyncio.run(_run_example(scenario, num_enabled, num_disabled))


@pytest.fixture(scope="module", autouse=True)
def _final_cleanup():
    """Best-effort teardown of any rows left behind by an aborted example."""
    yield

    async def _do():
        engine, factory = await _make_engine_and_factory()
        try:
            await _cleanup(factory)
        finally:
            await engine.dispose()

    asyncio.run(_do())
