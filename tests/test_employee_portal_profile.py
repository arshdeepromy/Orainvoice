"""Unit / smoke tests for the Employee Portal profile endpoint wiring.

Covers task 11.3 at the level that does not require a live database:

- the router mounts ``GET /e/api/profile`` under ``/e/api`` (session-gated);
- the neutral ``not_linked`` 409 envelope is the single source of truth for an
  unlinked portal user (R7.7);
- the ``GET /e/api/profile`` route declares the ``require_portal_session``
  dependency (own-record-only is enforced by the session staff_id + RLS org —
  R7.1, R7.5, R16.3, R16.4);
- ``ProfileResponse`` serialises its UUID/date fields to JSON-safe primitives
  and surfaces the masked PII display values it is given (the IRD/bank fields
  are masked server-side before they ever reach the schema — R7.5).

The DB-backed tenant/owner isolation property (a foreign/other-org staff id
never resolves) is covered by the dedicated property test in task 11.6.

Implements: Organisation Employee Portal task 11.3 — Requirements 7.1, 7.5,
7.7, 16.3, 16.4.
"""

from __future__ import annotations

import uuid
from datetime import date


def test_app_factory_mounts_profile() -> None:
    """``GET /e/api/profile`` is registered under /e/api."""
    from app.main import create_app

    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/e/api/profile" in paths


def test_profile_route_requires_portal_session() -> None:
    """The profile route is gated by ``require_portal_session`` (R7.1, R16.3)."""
    from app.modules.employee_portal import router as R

    profile_routes = [
        r
        for r in R.router.routes
        if getattr(r, "path", None) == "/profile" and "GET" in getattr(r, "methods", set())
    ]
    assert profile_routes, "GET /profile route should be registered on the router"

    route = profile_routes[0]
    dep_calls = [d.call for d in route.dependant.dependencies]
    assert R.require_portal_session in dep_calls
    # A safe GET must NOT pull in the state-changing CSRF gate.
    assert R.validate_emp_portal_csrf not in dep_calls


def test_not_linked_envelope_is_the_single_source_of_truth() -> None:
    """The 409 envelope carries the human-readable ``not_linked`` code (R7.7)."""
    from app.modules.employee_portal import router as R

    exc = R._not_linked_exc()
    assert exc.status_code == 409
    assert exc.detail["code"] == "not_linked"
    assert exc.detail["message"] == R._NOT_LINKED_MESSAGE
    # Human-readable, non-empty message so the SPA can surface it.
    assert isinstance(R._NOT_LINKED_MESSAGE, str) and R._NOT_LINKED_MESSAGE.strip()


def test_profile_response_serialises_json_safe_and_surfaces_masked_pii() -> None:
    """ProfileResponse → JSON-safe dict carrying the masked PII it was given."""
    from app.modules.employee_portal.schemas import ProfileResponse

    staff_id = uuid.uuid4()
    resp = ProfileResponse(
        staff_id=staff_id,
        first_name="Ada",
        last_name="Lovelace",
        name="Ada Lovelace",
        email="ada@example.test",
        phone="021 000 000",
        position="Technician",
        employee_id="E-001",
        employment_basis="full_time",
        employment_type="permanent",
        working_arrangement="rostered",
        employment_start_date=date(2024, 1, 15),
        tax_code="M",
        kiwisaver_enrolled=True,
        ird_number="***123",
        bank_account_number="**-****-****56-**",
        emergency_contact_name="Grace",
        emergency_contact_phone="021 111 111",
    )

    dumped = resp.model_dump(mode="json")
    # UUID + date are serialised to JSON-safe strings.
    assert dumped["staff_id"] == str(staff_id)
    assert dumped["employment_start_date"] == "2024-01-15"
    # Masked PII passes through unchanged — plaintext never reaches the schema.
    assert dumped["ird_number"] == "***123"
    assert dumped["bank_account_number"] == "**-****-****56-**"


def test_profile_response_pii_fields_default_to_none() -> None:
    """When no PII is supplied the masked fields are ``None`` (no leak)."""
    from app.modules.employee_portal.schemas import ProfileResponse

    resp = ProfileResponse(staff_id=uuid.uuid4())
    dumped = resp.model_dump(mode="json")
    assert dumped["ird_number"] is None
    assert dumped["bank_account_number"] is None
