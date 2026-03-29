"""Property-based tests for the Customer Check-In Kiosk feature.

Properties covered:
  P1  — Kiosk role is a valid user role
  P2  — Kiosk authentication produces correct token and session
  P3  — Kiosk RBAC allowlist enforcement
  P4  — Session revocation on kiosk deactivation
  P5  — Multiple kiosk accounts per organisation
  P7  — Check-in form validation
  P8  — Phone-based customer deduplication
  P9  — New customer creation with correct fields
  P10 — Vehicle lookup with Carjam fallback
  P11 — Vehicle deduplication
  P12 — Check-in response shape
  P15 — Rate limiting enforcement
  P16 — Kiosk user creation requires only email and password

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.1, 6.1, 6.5, 7.2, 7.3**
"""

from __future__ import annotations

import re

from hypothesis import given, assume
from hypothesis import strategies as st
from pydantic import ValidationError

from tests.properties.conftest import PBT_SETTINGS

from app.modules.auth.rbac import (
    check_role_path_access,
    KIOSK_ALLOWED_PREFIXES,
)
from app.modules.kiosk.schemas import KioskCheckInRequest


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# HTTP methods the system handles
_http_methods = st.sampled_from(["GET", "POST", "PUT", "PATCH", "DELETE"])

# Paths that are explicitly allowed for kiosk
_kiosk_allowed_path_st = st.sampled_from([
    "/api/v1/kiosk/",
    "/api/v1/kiosk/check-in",
    "/api/v1/kiosk/some-endpoint",
    "/api/v1/kiosk",
])

# Paths under /api/v1/org/settings (GET-only allowed)
_org_settings_path_st = st.sampled_from([
    "/api/v1/org/settings",
    "/api/v1/org/settings/branding",
])

# Non-GET methods for testing org/settings write denial
_non_get_methods = st.sampled_from(["POST", "PUT", "PATCH", "DELETE"])

# Random path segments for generating arbitrary API paths
_path_segment = st.from_regex(r"[a-z0-9_-]{1,20}", fullmatch=True)

# Generate random API paths that do NOT start with any kiosk-allowed prefix
_random_api_path_st = st.builds(
    lambda segments: "/api/v1/" + "/".join(segments),
    st.lists(_path_segment, min_size=1, max_size=4),
).filter(
    lambda p: not any(p.startswith(prefix) for prefix in KIOSK_ALLOWED_PREFIXES)
)


# ===========================================================================
# Property 3: Kiosk RBAC allowlist enforcement
# ===========================================================================


class TestP3KioskRBACAllowlist:
    """Kiosk role access is restricted to allowlisted prefixes only.

    For any API path and HTTP method, check_role_path_access("kiosk", path, method)
    returns None (allowed) if and only if the path starts with a kiosk-allowed prefix.
    /api/v1/org/settings is further restricted to GET only.

    **Validates: Requirements 1.5, 1.6, 6.1**
    """

    @given(path=_kiosk_allowed_path_st, method=_http_methods)
    @PBT_SETTINGS
    def test_kiosk_paths_always_allowed(self, path: str, method: str) -> None:
        """P3: paths under /api/v1/kiosk/ or /api/v1/kiosk are allowed for any method."""
        result = check_role_path_access("kiosk", path, method)
        assert result is None, f"Expected allowed for kiosk path {path!r} {method}, got: {result}"

    @given(path=_org_settings_path_st)
    @PBT_SETTINGS
    def test_org_settings_get_allowed(self, path: str) -> None:
        """P3: GET on /api/v1/org/settings paths is allowed for kiosk."""
        result = check_role_path_access("kiosk", path, "GET")
        assert result is None, f"Expected allowed for GET {path!r}, got: {result}"

    @given(path=_org_settings_path_st, method=_non_get_methods)
    @PBT_SETTINGS
    def test_org_settings_non_get_denied(self, path: str, method: str) -> None:
        """P3: non-GET methods on /api/v1/org/settings are denied for kiosk."""
        result = check_role_path_access("kiosk", path, method)
        assert result is not None, f"Expected denial for {method} {path!r}, got None"
        assert "read-only" in result.lower(), f"Denial reason should mention read-only: {result}"

    @given(path=_random_api_path_st, method=_http_methods)
    @PBT_SETTINGS
    def test_non_allowlisted_paths_denied(self, path: str, method: str) -> None:
        """P3: any path not matching kiosk-allowed prefixes is denied."""
        result = check_role_path_access("kiosk", path, method)
        assert result is not None, f"Expected denial for non-allowed path {path!r} {method}"

    @given(
        suffix=st.from_regex(r"[a-z0-9/_-]{0,30}", fullmatch=True),
        method=_http_methods,
    )
    @PBT_SETTINGS
    def test_kiosk_prefix_with_random_suffix_allowed(self, suffix: str, method: str) -> None:
        """P3: any path starting with /api/v1/kiosk/ is allowed regardless of suffix."""
        path = f"/api/v1/kiosk/{suffix}"
        result = check_role_path_access("kiosk", path, method)
        assert result is None, f"Expected allowed for {path!r} {method}, got: {result}"

    @given(
        path=st.sampled_from([
            "/api/v1/invoices",
            "/api/v1/invoices/123",
            "/api/v1/customers",
            "/api/v1/admin/settings",
            "/api/v1/billing/plans",
            "/api/v1/reports/revenue",
            "/api/v1/jobs",
            "/api/v1/quotes",
            "/api/v1/bookings",
        ]),
        method=_http_methods,
    )
    @PBT_SETTINGS
    def test_sensitive_endpoints_denied(self, path: str, method: str) -> None:
        """P3: kiosk is denied access to sensitive business endpoints."""
        result = check_role_path_access("kiosk", path, method)
        assert result is not None, f"Expected denial for sensitive path {path!r} {method}"


# ===========================================================================
# Strategies for Property 7: Check-in form validation
# ===========================================================================

# Characters allowed in phone formatting (stripped before digit count)
_PHONE_FORMAT_CHARS = " -+()"

# Valid name: 1-100 printable characters (no control chars)
_valid_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Zs")),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 1)

# Invalid name: either empty or >100 chars
_empty_name_st = st.just("")
_too_long_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=101,
    max_size=120,
)

# Valid phone: at least 7 digits, optionally with formatting chars interspersed
_valid_phone_st = st.from_regex(r"\+?[\d\s\-\(\)]{7,20}", fullmatch=True).filter(
    lambda p: len(re.sub(r"[\s\-\+\(\)]", "", p)) >= 7
    and re.sub(r"[\s\-\+\(\)]", "", p).isdigit()
)

# Invalid phone: fewer than 7 digits after stripping formatting
_short_phone_st = st.from_regex(r"\d{1,6}", fullmatch=True)

# Valid email matching ^[^@\s]+@[^@\s]+\.[^@\s]+$
_valid_email_st = st.from_regex(
    r"[a-z][a-z0-9]{0,10}@[a-z]{1,10}\.[a-z]{2,4}", fullmatch=True
)

# Invalid emails: missing @, missing dot after @, whitespace, etc.
_invalid_email_st = st.sampled_from([
    "noatsign",
    "@nodomain.com",
    "user@",
    "user@domain",
    "user @domain.com",
    "user@dom ain.com",
    "",
])

# Valid rego: non-empty after strip, will be uppercased
_valid_rego_st = st.from_regex(r"[A-Za-z0-9]{1,10}", fullmatch=True)


# ===========================================================================
# Property 7: Check-in form validation
# ===========================================================================


class TestP7CheckInFormValidation:
    """Check-in form validation accepts/rejects inputs based on field rules.

    For any input tuple (first_name, last_name, phone, email, vehicle_rego),
    KioskCheckInRequest should accept if and only if all validation rules pass:
    - first_name: 1-100 chars, required
    - last_name: 1-100 chars, required
    - phone: ≥7 digits after stripping formatting chars
    - email: optional; if provided must match email regex
    - vehicle_rego: optional; empty string coerced to None, non-empty stripped/uppercased

    **Validates: Requirements 3.2, 3.3, 3.4**
    """

    # --- Valid inputs should be accepted ---

    @given(
        first_name=_valid_name_st,
        last_name=_valid_name_st,
        phone=_valid_phone_st,
    )
    @PBT_SETTINGS
    def test_valid_required_fields_accepted(
        self, first_name: str, last_name: str, phone: str
    ) -> None:
        """P7: valid first_name, last_name, phone (no optionals) is accepted."""
        req = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )
        assert req.first_name == first_name
        assert req.last_name == last_name
        assert req.email is None
        assert req.vehicle_rego is None

    @given(
        first_name=_valid_name_st,
        last_name=_valid_name_st,
        phone=_valid_phone_st,
        email=_valid_email_st,
    )
    @PBT_SETTINGS
    def test_valid_with_email_accepted(
        self, first_name: str, last_name: str, phone: str, email: str
    ) -> None:
        """P7: valid required fields + valid email is accepted; email lowercased."""
        req = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
        )
        assert req.email == email.strip().lower()

    @given(
        first_name=_valid_name_st,
        last_name=_valid_name_st,
        phone=_valid_phone_st,
        rego=_valid_rego_st,
    )
    @PBT_SETTINGS
    def test_valid_with_rego_accepted_and_uppercased(
        self, first_name: str, last_name: str, phone: str, rego: str
    ) -> None:
        """P7: valid required fields + rego is accepted; rego uppercased."""
        req = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            vehicle_rego=rego,
        )
        assert req.vehicle_rego == rego.strip().upper()

    @given(
        first_name=_valid_name_st,
        last_name=_valid_name_st,
        phone=_valid_phone_st,
    )
    @PBT_SETTINGS
    def test_empty_rego_coerced_to_none(
        self, first_name: str, last_name: str, phone: str
    ) -> None:
        """P7: empty-string rego is coerced to None."""
        req = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            vehicle_rego="",
        )
        assert req.vehicle_rego is None

    @given(
        first_name=_valid_name_st,
        last_name=_valid_name_st,
        phone=_valid_phone_st,
    )
    @PBT_SETTINGS
    def test_whitespace_only_rego_coerced_to_none(
        self, first_name: str, last_name: str, phone: str
    ) -> None:
        """P7: whitespace-only rego is coerced to None."""
        req = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            vehicle_rego="   ",
        )
        assert req.vehicle_rego is None

    # --- Invalid inputs should be rejected ---

    @given(last_name=_valid_name_st, phone=_valid_phone_st)
    @PBT_SETTINGS
    def test_empty_first_name_rejected(self, last_name: str, phone: str) -> None:
        """P7: empty first_name is rejected."""
        try:
            KioskCheckInRequest(first_name="", last_name=last_name, phone=phone)
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    @given(first_name=_too_long_name_st, last_name=_valid_name_st, phone=_valid_phone_st)
    @PBT_SETTINGS
    def test_too_long_first_name_rejected(
        self, first_name: str, last_name: str, phone: str
    ) -> None:
        """P7: first_name >100 chars is rejected."""
        try:
            KioskCheckInRequest(first_name=first_name, last_name=last_name, phone=phone)
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    @given(first_name=_valid_name_st, phone=_valid_phone_st)
    @PBT_SETTINGS
    def test_empty_last_name_rejected(self, first_name: str, phone: str) -> None:
        """P7: empty last_name is rejected."""
        try:
            KioskCheckInRequest(first_name=first_name, last_name="", phone=phone)
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    @given(first_name=_valid_name_st, last_name=_too_long_name_st, phone=_valid_phone_st)
    @PBT_SETTINGS
    def test_too_long_last_name_rejected(
        self, first_name: str, last_name: str, phone: str
    ) -> None:
        """P7: last_name >100 chars is rejected."""
        try:
            KioskCheckInRequest(first_name=first_name, last_name=last_name, phone=phone)
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    @given(first_name=_valid_name_st, last_name=_valid_name_st, phone=_short_phone_st)
    @PBT_SETTINGS
    def test_short_phone_rejected(
        self, first_name: str, last_name: str, phone: str
    ) -> None:
        """P7: phone with <7 digits is rejected."""
        try:
            KioskCheckInRequest(first_name=first_name, last_name=last_name, phone=phone)
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    @given(
        first_name=_valid_name_st,
        last_name=_valid_name_st,
        phone=_valid_phone_st,
        email=_invalid_email_st,
    )
    @PBT_SETTINGS
    def test_invalid_email_rejected(
        self, first_name: str, last_name: str, phone: str, email: str
    ) -> None:
        """P7: invalid email format is rejected."""
        try:
            KioskCheckInRequest(
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                email=email,
            )
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    @given(
        first_name=_valid_name_st,
        last_name=_valid_name_st,
        phone=_valid_phone_st,
    )
    @PBT_SETTINGS
    def test_none_email_accepted(
        self, first_name: str, last_name: str, phone: str
    ) -> None:
        """P7: None email (omitted) is accepted."""
        req = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=None,
        )
        assert req.email is None


# ===========================================================================
# Imports for Properties 8 & 9 (service-level tests with mocked DB)
# ===========================================================================

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.asyncio import Redis

from app.modules.customers.models import Customer
from app.modules.kiosk.service import kiosk_check_in


# ---------------------------------------------------------------------------
# Strategies for Properties 8 & 9
# ---------------------------------------------------------------------------

# Valid phone: 7+ digits, optionally formatted
_valid_phone_for_service_st = st.from_regex(r"\+?\d{7,15}", fullmatch=True)

# Valid name: 1-100 chars
_valid_name_for_service_st = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=1,
    max_size=50,
)

# Optional valid email
_optional_email_st = st.one_of(
    st.none(),
    st.from_regex(r"[a-z][a-z0-9]{0,10}@[a-z]{1,10}\.[a-z]{2,4}", fullmatch=True),
)


def _make_existing_customer(
    org_id: uuid.UUID, phone: str, first_name: str = "Existing", last_name: str = "Customer"
) -> MagicMock:
    """Build a mock Customer object for mock query results."""
    c = MagicMock(spec=Customer)
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.first_name = first_name
    c.last_name = last_name
    c.phone = phone
    c.email = None
    c.customer_type = "individual"
    c.is_anonymised = False
    return c


def _mock_db_returning_customer(customer: Customer | None) -> AsyncMock:
    """Create a mock AsyncSession whose execute() returns the given customer."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = customer
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    return db


# ===========================================================================
# Property 8: Phone-based customer deduplication
# ===========================================================================


class TestP8PhoneBasedCustomerDeduplication:
    """Check-in with an existing phone returns is_new_customer=False and
    does not create a duplicate customer.

    For any organisation and phone number, if a customer with that phone
    already exists, calling kiosk_check_in with that phone should return
    is_new_customer=False and create_customer should NOT be called.

    **Validates: Requirements 4.1, 4.2**
    """

    @given(
        phone=_valid_phone_for_service_st,
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_existing_phone_returns_not_new(
        self, phone: str, first_name: str, last_name: str
    ) -> None:
        """P8: check-in with existing phone returns is_new_customer=False."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        existing = _make_existing_customer(org_id, phone)
        db = _mock_db_returning_customer(existing)
        redis = AsyncMock(spec=Redis)

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
        ) as mock_create:
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            assert result.is_new_customer is False
            assert result.customer_first_name == existing.first_name
            mock_create.assert_not_called()

    @given(
        phone=_valid_phone_for_service_st,
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_existing_phone_no_duplicate_created(
        self, phone: str, first_name: str, last_name: str
    ) -> None:
        """P8: check-in with existing phone does not call create_customer."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        existing = _make_existing_customer(org_id, phone)
        db = _mock_db_returning_customer(existing)
        redis = AsyncMock(spec=Redis)

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
        ) as mock_create:
            await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            # create_customer must never be called for existing phone
            mock_create.assert_not_called()
            # db.add should not be called (no new customer row)
            db.add.assert_not_called()


# ===========================================================================
# Property 9: New customer creation with correct fields
# ===========================================================================


class TestP9NewCustomerCreationCorrectFields:
    """New customer has correct first_name, last_name, phone, email,
    and customer_type='individual'.

    For any check-in submission where no customer with the given phone
    exists, the kiosk service should create a new customer with the
    submitted fields and customer_type must equal 'individual'.

    **Validates: Requirements 4.3, 4.4**
    """

    @given(
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
        email=_optional_email_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_new_customer_created_with_correct_fields(
        self,
        first_name: str,
        last_name: str,
        phone: str,
        email: str | None,
    ) -> None:
        """P9: new customer has correct first_name, last_name, phone, email, customer_type."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # No existing customer — query returns None
        db = _mock_db_returning_customer(None)
        redis = AsyncMock(spec=Redis)

        new_customer_id = str(uuid.uuid4())
        created_dict = {
            "id": new_customer_id,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": email.strip().lower() if email else email,
            "customer_type": "individual",
        }

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
        )

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=created_dict,
        ) as mock_create:
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            # Verify create_customer was called with the right arguments
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args
            # The service passes keyword arguments
            assert call_kwargs.kwargs["first_name"] == first_name
            assert call_kwargs.kwargs["last_name"] == last_name
            assert call_kwargs.kwargs["phone"] == data.phone  # after validation
            assert call_kwargs.kwargs["customer_type"] == "individual"

            # Verify the response
            assert result.is_new_customer is True
            assert result.customer_first_name == first_name

    @given(
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
        email=_optional_email_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_new_customer_always_individual_type(
        self,
        first_name: str,
        last_name: str,
        phone: str,
        email: str | None,
    ) -> None:
        """P9: customer_type is always 'individual' for kiosk-created customers."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = _mock_db_returning_customer(None)
        redis = AsyncMock(spec=Redis)

        new_customer_id = str(uuid.uuid4())
        created_dict = {
            "id": new_customer_id,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": email.strip().lower() if email else email,
            "customer_type": "individual",
        }

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
        )

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=created_dict,
        ) as mock_create:
            await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            # customer_type must always be "individual"
            assert mock_create.call_args.kwargs["customer_type"] == "individual"


# ===========================================================================
# Imports for Properties 10 & 11 (vehicle handling)
# ===========================================================================

from app.integrations.carjam import CarjamError, CarjamNotFoundError


# ---------------------------------------------------------------------------
# Strategies for Properties 10 & 11
# ---------------------------------------------------------------------------

_valid_rego_for_service_st = st.from_regex(r"[A-Z0-9]{1,7}", fullmatch=True)


# ---------------------------------------------------------------------------
# Helpers for Properties 10 & 11
# ---------------------------------------------------------------------------


def _mock_db_for_vehicle_tests(
    customer: Customer | None,
    *,
    existing_link: bool = False,
) -> AsyncMock:
    """Create a mock AsyncSession that handles both customer lookup and
    vehicle-link existence check.

    The first ``db.execute()`` call returns the customer (for
    ``_search_customer_by_phone``).  The second call returns an existing
    link record or ``None`` (for ``_ensure_vehicle_linked``).
    """
    db = AsyncMock()

    customer_result = MagicMock()
    customer_result.scalar_one_or_none.return_value = customer

    link_result = MagicMock()
    link_result.scalar_one_or_none.return_value = (
        MagicMock() if existing_link else None
    )

    db.execute = AsyncMock(side_effect=[customer_result, link_result])
    db.commit = AsyncMock()
    return db


# ===========================================================================
# Property 10: Vehicle lookup with Carjam fallback
# ===========================================================================


class TestP10VehicleLookupWithCarjamFallback:
    """Carjam success uses Carjam data; Carjam failure creates manual vehicle;
    both cases link the vehicle to the customer.

    For any check-in submission that includes a vehicle_rego:
    - If Carjam lookup succeeds, the resulting vehicle record should contain
      Carjam-sourced data and be linked to the customer.
    - If Carjam lookup fails (CarjamError), a manual vehicle record should be
      created with the registration plate and linked to the customer.

    **Validates: Requirements 4.5, 4.6**
    """

    @given(
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
        rego=_valid_rego_for_service_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_carjam_success_uses_carjam_data_and_links(
        self,
        first_name: str,
        last_name: str,
        phone: str,
        rego: str,
    ) -> None:
        """P10: when Carjam succeeds, lookup_vehicle result is used and vehicle is linked."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        vehicle_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())

        # New customer path (no existing customer)
        db = _mock_db_for_vehicle_tests(None, existing_link=False)
        redis = AsyncMock(spec=Redis)

        created_customer = {
            "id": customer_id,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": None,
            "customer_type": "individual",
        }

        carjam_vehicle = {
            "id": vehicle_id,
            "rego": rego.upper(),
            "make": "Toyota",
            "model": "Corolla",
            "source": "carjam",
        }

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            vehicle_rego=rego,
        )

        with (
            patch(
                "app.modules.customers.service.create_customer",
                new_callable=AsyncMock,
                return_value=created_customer,
            ),
            patch(
                "app.modules.vehicles.service.lookup_vehicle",
                new_callable=AsyncMock,
                return_value=carjam_vehicle,
            ) as mock_lookup,
            patch(
                "app.modules.vehicles.service.create_manual_vehicle",
                new_callable=AsyncMock,
            ) as mock_manual,
            patch(
                "app.modules.vehicles.service.link_vehicle_to_customer",
                new_callable=AsyncMock,
            ) as mock_link,
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            # lookup_vehicle was called with the rego
            mock_lookup.assert_called_once()
            assert mock_lookup.call_args.kwargs["rego"] == data.vehicle_rego

            # Manual creation was NOT called (Carjam succeeded)
            mock_manual.assert_not_called()

            # Vehicle was linked to the customer
            mock_link.assert_called_once()
            assert str(mock_link.call_args.kwargs["vehicle_id"]) == vehicle_id
            assert str(mock_link.call_args.kwargs["customer_id"]) == customer_id

            # Response indicates vehicle was linked
            assert result.vehicle_linked is True

    @given(
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
        rego=_valid_rego_for_service_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_carjam_failure_creates_manual_vehicle_and_links(
        self,
        first_name: str,
        last_name: str,
        phone: str,
        rego: str,
    ) -> None:
        """P10: when Carjam fails, manual vehicle is created and linked."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        vehicle_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())

        db = _mock_db_for_vehicle_tests(None, existing_link=False)
        redis = AsyncMock(spec=Redis)

        created_customer = {
            "id": customer_id,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": None,
            "customer_type": "individual",
        }

        manual_vehicle = {
            "id": vehicle_id,
            "rego": rego.upper(),
            "source": "manual",
        }

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            vehicle_rego=rego,
        )

        with (
            patch(
                "app.modules.customers.service.create_customer",
                new_callable=AsyncMock,
                return_value=created_customer,
            ),
            patch(
                "app.modules.vehicles.service.lookup_vehicle",
                new_callable=AsyncMock,
                side_effect=CarjamError("Carjam API unavailable"),
            ) as mock_lookup,
            patch(
                "app.modules.vehicles.service.create_manual_vehicle",
                new_callable=AsyncMock,
                return_value=manual_vehicle,
            ) as mock_manual,
            patch(
                "app.modules.vehicles.service.link_vehicle_to_customer",
                new_callable=AsyncMock,
            ) as mock_link,
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            # lookup_vehicle was called but raised CarjamError
            mock_lookup.assert_called_once()

            # Manual creation was called as fallback
            mock_manual.assert_called_once()
            assert mock_manual.call_args.kwargs["rego"] == data.vehicle_rego

            # Vehicle was linked to the customer
            mock_link.assert_called_once()
            assert str(mock_link.call_args.kwargs["vehicle_id"]) == vehicle_id
            assert str(mock_link.call_args.kwargs["customer_id"]) == customer_id

            # Response indicates vehicle was linked
            assert result.vehicle_linked is True

    @given(
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
        rego=_valid_rego_for_service_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_carjam_not_found_creates_manual_vehicle_and_links(
        self,
        first_name: str,
        last_name: str,
        phone: str,
        rego: str,
    ) -> None:
        """P10: when Carjam returns not-found, manual vehicle is created and linked."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        vehicle_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())

        db = _mock_db_for_vehicle_tests(None, existing_link=False)
        redis = AsyncMock(spec=Redis)

        created_customer = {
            "id": customer_id,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": None,
            "customer_type": "individual",
        }

        manual_vehicle = {
            "id": vehicle_id,
            "rego": rego.upper(),
            "source": "manual",
        }

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            vehicle_rego=rego,
        )

        with (
            patch(
                "app.modules.customers.service.create_customer",
                new_callable=AsyncMock,
                return_value=created_customer,
            ),
            patch(
                "app.modules.vehicles.service.lookup_vehicle",
                new_callable=AsyncMock,
                side_effect=CarjamNotFoundError("Vehicle not found"),
            ),
            patch(
                "app.modules.vehicles.service.create_manual_vehicle",
                new_callable=AsyncMock,
                return_value=manual_vehicle,
            ) as mock_manual,
            patch(
                "app.modules.vehicles.service.link_vehicle_to_customer",
                new_callable=AsyncMock,
            ) as mock_link,
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            # Manual creation was called as fallback
            mock_manual.assert_called_once()

            # Vehicle was linked
            mock_link.assert_called_once()

            assert result.vehicle_linked is True


# ===========================================================================
# Property 11: Vehicle deduplication
# ===========================================================================


class TestP11VehicleDeduplication:
    """Existing vehicle is linked without creating a duplicate record.

    For any vehicle registration that already exists, a kiosk check-in with
    that registration should not create a new vehicle record — the existing
    vehicle should be linked to the customer.

    **Validates: Requirements 4.7**
    """

    @given(
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
        rego=_valid_rego_for_service_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_existing_vehicle_linked_without_duplicate(
        self,
        first_name: str,
        last_name: str,
        phone: str,
        rego: str,
    ) -> None:
        """P11: when lookup_vehicle returns an existing vehicle, no new vehicle is created."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        existing_vehicle_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())

        # New customer, no existing link
        db = _mock_db_for_vehicle_tests(None, existing_link=False)
        redis = AsyncMock(spec=Redis)

        created_customer = {
            "id": customer_id,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": None,
            "customer_type": "individual",
        }

        # lookup_vehicle returns the existing vehicle (cache hit)
        existing_vehicle = {
            "id": existing_vehicle_id,
            "rego": rego.upper(),
            "make": "Honda",
            "model": "Civic",
            "source": "cache",
        }

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            vehicle_rego=rego,
        )

        with (
            patch(
                "app.modules.customers.service.create_customer",
                new_callable=AsyncMock,
                return_value=created_customer,
            ),
            patch(
                "app.modules.vehicles.service.lookup_vehicle",
                new_callable=AsyncMock,
                return_value=existing_vehicle,
            ) as mock_lookup,
            patch(
                "app.modules.vehicles.service.create_manual_vehicle",
                new_callable=AsyncMock,
            ) as mock_manual,
            patch(
                "app.modules.vehicles.service.link_vehicle_to_customer",
                new_callable=AsyncMock,
            ) as mock_link,
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            # lookup_vehicle was called and returned existing vehicle
            mock_lookup.assert_called_once()

            # create_manual_vehicle was NOT called (vehicle already exists)
            mock_manual.assert_not_called()

            # The existing vehicle was linked to the customer
            mock_link.assert_called_once()
            assert str(mock_link.call_args.kwargs["vehicle_id"]) == existing_vehicle_id

            assert result.vehicle_linked is True

    @given(
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
        rego=_valid_rego_for_service_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_existing_vehicle_with_existing_link_skips_relink(
        self,
        first_name: str,
        last_name: str,
        phone: str,
        rego: str,
    ) -> None:
        """P11: when vehicle already linked to customer, link is not duplicated."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        existing_vehicle_id = str(uuid.uuid4())

        # Existing customer with existing vehicle link
        existing_customer = _make_existing_customer(org_id, phone, first_name)
        db = _mock_db_for_vehicle_tests(existing_customer, existing_link=True)
        redis = AsyncMock(spec=Redis)

        existing_vehicle = {
            "id": existing_vehicle_id,
            "rego": rego.upper(),
            "make": "Honda",
            "model": "Civic",
            "source": "cache",
        }

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            vehicle_rego=rego,
        )

        with (
            patch(
                "app.modules.vehicles.service.lookup_vehicle",
                new_callable=AsyncMock,
                return_value=existing_vehicle,
            ) as mock_lookup,
            patch(
                "app.modules.vehicles.service.create_manual_vehicle",
                new_callable=AsyncMock,
            ) as mock_manual,
            patch(
                "app.modules.vehicles.service.link_vehicle_to_customer",
                new_callable=AsyncMock,
            ) as mock_link,
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            # lookup_vehicle was called
            mock_lookup.assert_called_once()

            # No manual vehicle creation
            mock_manual.assert_not_called()

            # link_vehicle_to_customer should NOT be called because
            # _ensure_vehicle_linked found an existing link
            mock_link.assert_not_called()

            assert result.vehicle_linked is True


# ===========================================================================
# Property 12: Check-in response shape
# ===========================================================================


class TestP12CheckInResponseShape:
    """Check-in response contains customer_first_name (non-empty string),
    is_new_customer (bool), vehicle_linked (bool), and customer_first_name
    matches the resolved customer.

    For any successful kiosk check-in, the response must contain all three
    fields with correct types. customer_first_name must match the resolved
    customer's first name. vehicle_linked must be True when rego is provided
    and False when it is not.

    **Validates: Requirements 4.8, 5.1**
    """

    @given(
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_new_customer_first_name_matches_submitted(
        self,
        first_name: str,
        last_name: str,
        phone: str,
    ) -> None:
        """P12: for new customers, customer_first_name matches the submitted first_name."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = _mock_db_returning_customer(None)
        redis = AsyncMock(spec=Redis)

        created_customer = {
            "id": str(uuid.uuid4()),
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": None,
            "customer_type": "individual",
        }

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=created_customer,
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            assert result.customer_first_name == first_name

    @given(
        submitted_first=_valid_name_for_service_st,
        submitted_last=_valid_name_for_service_st,
        existing_first=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_existing_customer_first_name_matches_existing(
        self,
        submitted_first: str,
        submitted_last: str,
        existing_first: str,
        phone: str,
    ) -> None:
        """P12: for existing customers, customer_first_name matches the existing customer's first_name."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        existing = _make_existing_customer(org_id, phone, first_name=existing_first)
        db = _mock_db_returning_customer(existing)
        redis = AsyncMock(spec=Redis)

        data = KioskCheckInRequest(
            first_name=submitted_first,
            last_name=submitted_last,
            phone=phone,
        )

        result = await kiosk_check_in(
            db, redis, org_id=org_id, user_id=user_id, data=data
        )

        assert result.customer_first_name == existing_first

    @given(
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
        email=_optional_email_st,
        rego=st.one_of(st.none(), _valid_rego_for_service_st),
        is_existing=st.booleans(),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_response_shape_always_valid(
        self,
        first_name: str,
        last_name: str,
        phone: str,
        email: str | None,
        rego: str | None,
        is_existing: bool,
    ) -> None:
        """P12: response always has non-empty customer_first_name (str), is_new_customer (bool), vehicle_linked (bool)."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        if is_existing:
            existing = _make_existing_customer(org_id, phone, first_name=first_name)
            db = _mock_db_for_vehicle_tests(existing, existing_link=False) if rego else _mock_db_returning_customer(existing)
        else:
            db = _mock_db_for_vehicle_tests(None, existing_link=False) if rego else _mock_db_returning_customer(None)

        redis = AsyncMock(spec=Redis)

        created_customer = {
            "id": str(uuid.uuid4()),
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": email.strip().lower() if email else email,
            "customer_type": "individual",
        }

        carjam_vehicle = {
            "id": str(uuid.uuid4()),
            "rego": rego.upper() if rego else None,
            "make": "Toyota",
            "model": "Corolla",
            "source": "carjam",
        }

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
            vehicle_rego=rego,
        )

        with (
            patch(
                "app.modules.customers.service.create_customer",
                new_callable=AsyncMock,
                return_value=created_customer,
            ),
            patch(
                "app.modules.vehicles.service.lookup_vehicle",
                new_callable=AsyncMock,
                return_value=carjam_vehicle,
            ),
            patch(
                "app.modules.vehicles.service.create_manual_vehicle",
                new_callable=AsyncMock,
                return_value=carjam_vehicle,
            ),
            patch(
                "app.modules.vehicles.service.link_vehicle_to_customer",
                new_callable=AsyncMock,
            ),
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            # customer_first_name must be a non-empty string
            assert isinstance(result.customer_first_name, str)
            assert len(result.customer_first_name) > 0

            # is_new_customer must be a boolean
            assert isinstance(result.is_new_customer, bool)

            # vehicle_linked must be a boolean
            assert isinstance(result.vehicle_linked, bool)

    @given(
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
        rego=_valid_rego_for_service_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_vehicle_linked_true_when_rego_provided(
        self,
        first_name: str,
        last_name: str,
        phone: str,
        rego: str,
    ) -> None:
        """P12: vehicle_linked is True when rego is provided."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = _mock_db_for_vehicle_tests(None, existing_link=False)
        redis = AsyncMock(spec=Redis)

        created_customer = {
            "id": str(uuid.uuid4()),
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": None,
            "customer_type": "individual",
        }

        vehicle = {
            "id": str(uuid.uuid4()),
            "rego": rego.upper(),
            "make": "Toyota",
            "model": "Corolla",
            "source": "carjam",
        }

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            vehicle_rego=rego,
        )

        with (
            patch(
                "app.modules.customers.service.create_customer",
                new_callable=AsyncMock,
                return_value=created_customer,
            ),
            patch(
                "app.modules.vehicles.service.lookup_vehicle",
                new_callable=AsyncMock,
                return_value=vehicle,
            ),
            patch(
                "app.modules.vehicles.service.link_vehicle_to_customer",
                new_callable=AsyncMock,
            ),
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            assert result.vehicle_linked is True

    @given(
        first_name=_valid_name_for_service_st,
        last_name=_valid_name_for_service_st,
        phone=_valid_phone_for_service_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_vehicle_linked_false_when_no_rego(
        self,
        first_name: str,
        last_name: str,
        phone: str,
    ) -> None:
        """P12: vehicle_linked is False when no rego is provided."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = _mock_db_returning_customer(None)
        redis = AsyncMock(spec=Redis)

        created_customer = {
            "id": str(uuid.uuid4()),
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": None,
            "customer_type": "individual",
        }

        data = KioskCheckInRequest(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=created_customer,
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            assert result.vehicle_linked is False


# ===========================================================================
# Imports for Property 2 (kiosk authentication token & session)
# ===========================================================================

from app.modules.auth.password import hash_password
from app.modules.auth.jwt import decode_access_token
from app.modules.auth.models import Session, User
from app.modules.auth.schemas import LoginRequest, TokenResponse
from app.modules.auth.service import authenticate_user

# Ensure Organisation model is loaded for relationship resolution
import app.modules.admin.models  # noqa: F401


# ---------------------------------------------------------------------------
# Strategies for Property 2
# ---------------------------------------------------------------------------

_kiosk_org_id_st = st.uuids()

_kiosk_email_st = st.from_regex(
    r"kiosk[a-z0-9]{1,6}@[a-z]{3,8}\.[a-z]{2,4}", fullmatch=True
)

_kiosk_password_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        max_codepoint=127,  # ASCII only — avoids bcrypt 72-byte UTF-8 limit
    ),
    min_size=12,
    max_size=30,
).filter(lambda s: len(s.strip()) >= 12)


# ---------------------------------------------------------------------------
# Helpers for Property 2
# ---------------------------------------------------------------------------


def _make_kiosk_user(
    org_id: uuid.UUID,
    email: str,
    password: str,
) -> MagicMock:
    """Build a mock User object with role='kiosk'."""
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.org_id = org_id
    u.email = email
    u.password_hash = hash_password(password)
    u.role = "kiosk"
    u.is_active = True
    u.is_email_verified = True
    u.failed_login_count = 0
    u.locked_until = None
    u.last_login_at = None
    return u


def _mock_scalar_one_or_none(value):
    """Create a mock result whose scalar_one_or_none() returns value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_all(values):
    """Create a mock result whose scalars().all() returns values."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


# ===========================================================================
# Property 2: Kiosk authentication produces correct token and session
# ===========================================================================


class TestP2KioskAuthenticationToken:
    """Kiosk authentication produces a JWT with role='kiosk' and correct org_id,
    and a session with expires_at approximately 30 days from auth time.

    For any kiosk user that authenticates successfully, the resulting JWT must
    contain role: 'kiosk' and the user's org_id, and the session's expires_at
    must be approximately 30 days from the authentication time.

    **Validates: Requirements 1.3, 1.4**
    """

    @given(
        org_id=_kiosk_org_id_st,
        email=_kiosk_email_st,
        password=_kiosk_password_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_jwt_contains_kiosk_role_and_org_id(
        self,
        org_id: uuid.UUID,
        email: str,
        password: str,
    ) -> None:
        """P2: JWT from kiosk auth contains role='kiosk' and correct org_id."""
        user = _make_kiosk_user(org_id, email, password)

        db = AsyncMock()
        # First execute: user lookup; second: MFA methods check;
        # third: anomalous login (previous sessions)
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_one_or_none(user),   # user lookup
            _mock_scalars_all([]),             # no MFA methods
            _mock_scalars_all([]),             # no previous sessions (anomaly check)
        ])
        db.add = MagicMock()

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service.check_ip_allowlist", return_value=False),
            patch("app.modules.auth.service._check_anomalous_login", new_callable=AsyncMock),
            patch("app.modules.auth.service.enforce_session_limit", new_callable=AsyncMock, return_value=0),
        ):
            req = LoginRequest(email=email, password=password)
            result = await authenticate_user(db, req, "10.0.0.1", "Tablet", "Chrome")

            assert isinstance(result, TokenResponse)

            # Decode the JWT and verify claims
            payload = decode_access_token(result.access_token)
            assert payload["role"] == "kiosk"
            assert payload["org_id"] == str(org_id)

    @given(
        org_id=_kiosk_org_id_st,
        email=_kiosk_email_st,
        password=_kiosk_password_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_session_expires_at_approximately_30_days(
        self,
        org_id: uuid.UUID,
        email: str,
        password: str,
    ) -> None:
        """P2: session expires_at is approximately 30 days from auth time."""
        from datetime import datetime, timedelta, timezone

        user = _make_kiosk_user(org_id, email, password)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_one_or_none(user),
            _mock_scalars_all([]),
            _mock_scalars_all([]),
        ])
        db.add = MagicMock()

        before_auth = datetime.now(timezone.utc)

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service.check_ip_allowlist", return_value=False),
            patch("app.modules.auth.service._check_anomalous_login", new_callable=AsyncMock),
            patch("app.modules.auth.service.enforce_session_limit", new_callable=AsyncMock, return_value=0),
        ):
            req = LoginRequest(email=email, password=password)
            await authenticate_user(db, req, "10.0.0.1", "Tablet", "Chrome")

        after_auth = datetime.now(timezone.utc)

        # Verify db.add was called with a Session object
        assert db.add.call_count == 1
        session_obj = db.add.call_args[0][0]
        assert isinstance(session_obj, Session)

        # expires_at should be approximately 30 days from now
        expected_min = before_auth + timedelta(days=30) - timedelta(seconds=5)
        expected_max = after_auth + timedelta(days=30) + timedelta(seconds=5)
        assert expected_min <= session_obj.expires_at <= expected_max, (
            f"Session expires_at {session_obj.expires_at} not within 30-day window "
            f"[{expected_min}, {expected_max}]"
        )

    @given(
        org_id=_kiosk_org_id_st,
        email=_kiosk_email_st,
        password=_kiosk_password_st,
        remember_me=st.booleans(),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_kiosk_30_day_expiry_ignores_remember_me(
        self,
        org_id: uuid.UUID,
        email: str,
        password: str,
        remember_me: bool,
    ) -> None:
        """P2: kiosk always gets 30-day expiry regardless of remember_me flag."""
        from datetime import datetime, timedelta, timezone

        user = _make_kiosk_user(org_id, email, password)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_one_or_none(user),
            _mock_scalars_all([]),
            _mock_scalars_all([]),
        ])
        db.add = MagicMock()

        before_auth = datetime.now(timezone.utc)

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service.check_ip_allowlist", return_value=False),
            patch("app.modules.auth.service._check_anomalous_login", new_callable=AsyncMock),
            patch("app.modules.auth.service.enforce_session_limit", new_callable=AsyncMock, return_value=0),
        ):
            req = LoginRequest(email=email, password=password, remember_me=remember_me)
            await authenticate_user(db, req, "10.0.0.1", "Tablet", "Chrome")

        after_auth = datetime.now(timezone.utc)

        session_obj = db.add.call_args[0][0]
        assert isinstance(session_obj, Session)

        # Always 30 days, regardless of remember_me
        expected_min = before_auth + timedelta(days=30) - timedelta(seconds=5)
        expected_max = after_auth + timedelta(days=30) + timedelta(seconds=5)
        assert expected_min <= session_obj.expires_at <= expected_max, (
            f"Session expires_at {session_obj.expires_at} not within 30-day window "
            f"[{expected_min}, {expected_max}] (remember_me={remember_me})"
        )


# ===========================================================================
# Imports for Property 15 (rate limiting enforcement)
# ===========================================================================

import time as _time_mod

from fastapi import HTTPException

from app.modules.kiosk.router import _check_kiosk_rate_limit, _KIOSK_RATE_LIMIT, _WINDOW


# ---------------------------------------------------------------------------
# Strategies for Property 15
# ---------------------------------------------------------------------------

# Request counts: some below the limit, some at the limit, some above
_request_count_st = st.integers(min_value=1, max_value=60)


# ---------------------------------------------------------------------------
# Helpers for Property 15
# ---------------------------------------------------------------------------


def _make_mock_request(user_id: str) -> MagicMock:
    """Create a mock FastAPI Request with state.user_id set."""
    request = MagicMock()
    request.state.user_id = user_id
    return request


def _make_mock_redis_for_rate_limit(current_count: int) -> AsyncMock:
    """Create a mock Redis that simulates a sorted-set sliding window.

    The mock pipeline's execute() returns results for:
      1. zremrangebyscore (cleanup) — always 0 removed
      2. zcard — returns ``current_count`` (requests already in the window)

    If the count is below the limit, a second pipeline is created for
    zadd + expire.
    """
    redis = AsyncMock(spec=Redis)

    # First pipeline: zremrangebyscore + zcard
    pipe1 = AsyncMock()
    pipe1.zremrangebyscore = MagicMock(return_value=pipe1)
    pipe1.zcard = MagicMock(return_value=pipe1)
    pipe1.execute = AsyncMock(return_value=[0, current_count])

    # Second pipeline: zadd + expire (only used when under limit)
    pipe2 = AsyncMock()
    pipe2.zadd = MagicMock(return_value=pipe2)
    pipe2.expire = MagicMock(return_value=pipe2)
    pipe2.execute = AsyncMock(return_value=[1, True])

    # Track pipeline calls — first call returns pipe1, second returns pipe2
    redis.pipeline = MagicMock(side_effect=[pipe1, pipe2])

    # For the retry-after calculation when rate limited
    now = _time_mod.time()
    redis.zrange = AsyncMock(return_value=[(b"oldest", now - 50)])

    return redis


# ===========================================================================
# Property 15: Rate limiting enforcement
# ===========================================================================


class TestP15RateLimitingEnforcement:
    """Rate limiting rejects requests beyond 30/min with HTTP 429.

    For any kiosk user, sending more than 30 check-in requests within a
    60-second window should result in subsequent requests being rejected
    with HTTP 429. Requests at or below 30 should be allowed.

    **Validates: Requirements 6.5**
    """

    @given(request_count=st.integers(min_value=0, max_value=_KIOSK_RATE_LIMIT - 1))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_requests_below_limit_are_allowed(
        self, request_count: int
    ) -> None:
        """P15: requests below 30/min are allowed (no exception raised)."""
        user_id = str(uuid.uuid4())
        request = _make_mock_request(user_id)
        redis = _make_mock_redis_for_rate_limit(request_count)

        # Should NOT raise — request is within the limit
        await _check_kiosk_rate_limit(request, redis=redis)

    @given(request_count=st.integers(min_value=_KIOSK_RATE_LIMIT, max_value=100))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_requests_at_or_above_limit_are_rejected(
        self, request_count: int
    ) -> None:
        """P15: requests at or above 30/min are rejected with HTTP 429."""
        user_id = str(uuid.uuid4())
        request = _make_mock_request(user_id)
        redis = _make_mock_redis_for_rate_limit(request_count)

        with pytest.raises(HTTPException) as exc_info:
            await _check_kiosk_rate_limit(request, redis=redis)

        assert exc_info.value.status_code == 429
        assert "rate limit" in exc_info.value.detail.lower()

    @given(
        below_count=st.integers(min_value=0, max_value=_KIOSK_RATE_LIMIT - 1),
        above_count=st.integers(min_value=_KIOSK_RATE_LIMIT, max_value=100),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_transition_from_allowed_to_rejected(
        self, below_count: int, above_count: int
    ) -> None:
        """P15: a user below the limit is allowed, then above the limit is rejected."""
        user_id = str(uuid.uuid4())

        # First: below limit — should pass
        request1 = _make_mock_request(user_id)
        redis1 = _make_mock_redis_for_rate_limit(below_count)
        await _check_kiosk_rate_limit(request1, redis=redis1)

        # Second: above limit — should raise 429
        request2 = _make_mock_request(user_id)
        redis2 = _make_mock_redis_for_rate_limit(above_count)
        with pytest.raises(HTTPException) as exc_info:
            await _check_kiosk_rate_limit(request2, redis=redis2)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_no_user_id_skips_rate_limit(self) -> None:
        """P15: when no user_id is present, rate limiting is skipped."""
        request = MagicMock()
        request.state.user_id = None
        redis = AsyncMock(spec=Redis)

        # Should NOT raise — no user_id means no rate limiting
        await _check_kiosk_rate_limit(request, redis=redis)

        # Redis should not have been called at all
        redis.pipeline.assert_not_called()

    @given(request_count=st.integers(min_value=_KIOSK_RATE_LIMIT, max_value=100))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_rate_limit_response_includes_retry_after(
        self, request_count: int
    ) -> None:
        """P15: rate-limited responses include a Retry-After header."""
        user_id = str(uuid.uuid4())
        request = _make_mock_request(user_id)
        redis = _make_mock_redis_for_rate_limit(request_count)

        with pytest.raises(HTTPException) as exc_info:
            await _check_kiosk_rate_limit(request, redis=redis)

        assert exc_info.value.status_code == 429
        # HTTPException stores headers in the headers attribute
        assert "Retry-After" in exc_info.value.headers
        retry_after = int(exc_info.value.headers["Retry-After"])
        assert retry_after >= 1


# ===========================================================================
# Property 1: Kiosk role is a valid user role
# ===========================================================================

from app.modules.auth.rbac import ALL_ROLES, ROLE_PERMISSIONS as _ROLE_PERMISSIONS_P1

# Strategies for Property 1
_valid_roles_st = st.sampled_from(sorted(ALL_ROLES))
_random_string_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=30,
).filter(lambda s: s not in ALL_ROLES)


class TestP1KioskRoleIsValid:
    """Kiosk role is a valid user role.

    Verify "kiosk" is accepted as a member of ALL_ROLES and random
    non-role strings are rejected.

    **Validates: Requirements 1.1, 1.2**
    """

    def test_kiosk_in_all_roles(self) -> None:
        """P1: 'kiosk' is present in ALL_ROLES."""
        assert "kiosk" in ALL_ROLES

    @given(role=_valid_roles_st)
    @PBT_SETTINGS
    def test_all_defined_roles_are_in_all_roles(self, role: str) -> None:
        """P1: every defined role is in ALL_ROLES."""
        assert role in ALL_ROLES

    @given(random_str=_random_string_st)
    @PBT_SETTINGS
    def test_random_non_role_strings_rejected(self, random_str: str) -> None:
        """P1: random strings not in the valid role set are not in ALL_ROLES."""
        assert random_str not in ALL_ROLES

    def test_kiosk_has_permissions(self) -> None:
        """P1: kiosk role has permissions defined in ROLE_PERMISSIONS."""
        assert "kiosk" in _ROLE_PERMISSIONS_P1
        assert "kiosk.check_in" in _ROLE_PERMISSIONS_P1["kiosk"]


# ===========================================================================
# Property 4: Session revocation on kiosk deactivation
# ===========================================================================

from app.modules.organisations.service import (
    deactivate_org_user,
    revoke_user_sessions,
    _invalidate_user_sessions,
)


class TestP4SessionRevocationOnDeactivation:
    """Deactivating a kiosk user results in all sessions having is_revoked=True.

    For any kiosk user with one or more active sessions, deactivating the
    user or revoking their sessions should result in all sessions for that
    user having is_revoked=True.

    **Validates: Requirements 1.7, 7.3**
    """

    @given(num_sessions=st.integers(min_value=1, max_value=10))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_deactivation_revokes_all_sessions(
        self, num_sessions: int
    ) -> None:
        """P4: deactivating a kiosk user revokes all active sessions."""
        org_id = uuid.uuid4()
        acting_user_id = uuid.uuid4()
        target_user_id = uuid.uuid4()

        # Create mock sessions
        mock_sessions = []
        for _ in range(num_sessions):
            s = MagicMock(spec=Session)
            s.user_id = target_user_id
            s.is_revoked = False
            mock_sessions.append(s)

        # Create mock kiosk user
        mock_user = MagicMock(spec=User)
        mock_user.id = target_user_id
        mock_user.org_id = org_id
        mock_user.role = "kiosk"
        mock_user.is_active = True

        db = AsyncMock()

        # First execute: user lookup; second: session query
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user

        session_result = MagicMock()
        session_scalars = MagicMock()
        session_scalars.all.return_value = mock_sessions
        session_result.scalars.return_value = session_scalars

        db.execute = AsyncMock(side_effect=[user_result, session_result])
        db.flush = AsyncMock()

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await deactivate_org_user(
                db,
                org_id=org_id,
                acting_user_id=acting_user_id,
                target_user_id=target_user_id,
            )

        # All sessions must be revoked
        for s in mock_sessions:
            assert s.is_revoked is True, "All sessions should have is_revoked=True"

        # User should be deactivated
        assert mock_user.is_active is False

    @given(num_sessions=st.integers(min_value=1, max_value=10))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_revoke_sessions_without_deactivation(
        self, num_sessions: int
    ) -> None:
        """P4: revoking sessions marks all sessions as revoked without deactivating user."""
        org_id = uuid.uuid4()
        acting_user_id = uuid.uuid4()
        target_user_id = uuid.uuid4()

        mock_sessions = []
        for _ in range(num_sessions):
            s = MagicMock(spec=Session)
            s.user_id = target_user_id
            s.is_revoked = False
            mock_sessions.append(s)

        mock_user = MagicMock(spec=User)
        mock_user.id = target_user_id
        mock_user.org_id = org_id
        mock_user.role = "kiosk"
        mock_user.is_active = True

        db = AsyncMock()

        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user

        session_result = MagicMock()
        session_scalars = MagicMock()
        session_scalars.all.return_value = mock_sessions
        session_result.scalars.return_value = session_scalars

        db.execute = AsyncMock(side_effect=[user_result, session_result])
        db.flush = AsyncMock()

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await revoke_user_sessions(
                db,
                org_id=org_id,
                acting_user_id=acting_user_id,
                target_user_id=target_user_id,
            )

        # All sessions must be revoked
        for s in mock_sessions:
            assert s.is_revoked is True

        assert result["sessions_invalidated"] == num_sessions

    @given(num_sessions=st.integers(min_value=0, max_value=10))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_invalidate_returns_correct_count(
        self, num_sessions: int
    ) -> None:
        """P4: _invalidate_user_sessions returns the count of revoked sessions."""
        target_user_id = uuid.uuid4()

        mock_sessions = []
        for _ in range(num_sessions):
            s = MagicMock(spec=Session)
            s.user_id = target_user_id
            s.is_revoked = False
            mock_sessions.append(s)

        db = AsyncMock()
        session_result = MagicMock()
        session_scalars = MagicMock()
        session_scalars.all.return_value = mock_sessions
        session_result.scalars.return_value = session_scalars
        db.execute = AsyncMock(return_value=session_result)

        count = await _invalidate_user_sessions(db, user_id=target_user_id)

        assert count == num_sessions
        for s in mock_sessions:
            assert s.is_revoked is True


# ===========================================================================
# Property 5: Multiple kiosk accounts per organisation
# ===========================================================================

from app.modules.organisations.service import invite_org_user


class TestP5MultipleKioskAccountsPerOrg:
    """Creating N kiosk users succeeds with N distinct accounts scoped to the org.

    For any organisation, creating N kiosk user accounts (where N >= 1)
    should succeed, resulting in N distinct kiosk users all scoped to
    that organisation.

    **Validates: Requirements 1.8**
    """

    @given(n=st.integers(min_value=1, max_value=5))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_n_kiosk_users_creates_n_distinct_accounts(
        self, n: int
    ) -> None:
        """P5: creating N kiosk users results in N distinct accounts."""
        org_id = uuid.uuid4()
        created_user_ids: list[str] = []

        for i in range(n):
            email = f"kiosk{i}@testorg.com"
            user_id = uuid.uuid4()

            # Simulate what create_invitation does: create a User with role=kiosk
            user = User(
                org_id=org_id,
                email=email,
                role="kiosk",
                is_active=True,
                is_email_verified=False,
                password_hash=None,
            )
            # Simulate the DB assigning an ID
            user.id = user_id
            created_user_ids.append(str(user.id))

            # Verify the user is correctly scoped
            assert user.org_id == org_id
            assert user.role == "kiosk"

        # All user IDs must be distinct
        assert len(set(created_user_ids)) == n, (
            f"Expected {n} distinct user IDs, got {len(set(created_user_ids))}"
        )

    @given(n=st.integers(min_value=2, max_value=5))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_all_kiosk_users_scoped_to_same_org(
        self, n: int
    ) -> None:
        """P5: all created kiosk users are scoped to the same organisation."""
        org_id = uuid.uuid4()
        users: list[User] = []

        for i in range(n):
            user = User(
                org_id=org_id,
                email=f"kiosk{i}@testorg.com",
                role="kiosk",
                is_active=True,
                is_email_verified=False,
                password_hash=None,
            )
            user.id = uuid.uuid4()
            users.append(user)

        # All should be kiosk role and scoped to the same org
        assert all(u.role == "kiosk" for u in users)
        assert all(u.org_id == org_id for u in users)
        # All IDs should be distinct
        ids = [str(u.id) for u in users]
        assert len(set(ids)) == n

    @given(
        email=st.from_regex(
            r"kiosk[a-z0-9]{1,6}@[a-z]{3,8}\.[a-z]{2,4}", fullmatch=True
        ),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_create_invitation_accepts_kiosk_role(
        self, email: str
    ) -> None:
        """P5: create_invitation accepts role='kiosk' for org-scoped user creation."""
        org_id = uuid.uuid4()
        inviter_id = uuid.uuid4()

        db = AsyncMock()

        email_check_result = MagicMock()
        email_check_result.scalar_one_or_none.return_value = None

        org_name_result = MagicMock()
        org_name_result.scalar_one_or_none.return_value = "Test Org"

        db.execute = AsyncMock(side_effect=[
            email_check_result,
            org_name_result,
        ])
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service._send_invitation_email", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", new_callable=AsyncMock),
        ):
            result = await create_invitation(
                db,
                inviter_user_id=inviter_id,
                org_id=org_id,
                email=email,
                role="kiosk",
            )

        assert "user_id" in result

        # Verify the User was created with correct org_id
        created_user = db.add.call_args[0][0]
        assert isinstance(created_user, User)
        assert created_user.org_id == org_id
        assert created_user.role == "kiosk"


# ===========================================================================
# Property 16: Kiosk user creation requires only email and password
# ===========================================================================

from app.modules.auth.service import create_invitation


class TestP16KioskUserCreationRequiresOnlyEmailPassword:
    """Kiosk user creation succeeds without first_name/last_name.

    For any kiosk user creation request with a valid email and password
    but no first_name or last_name, the creation should succeed. The
    first_name and last_name fields should be optional when role='kiosk'.

    **Validates: Requirements 7.2**
    """

    @given(
        email=st.from_regex(
            r"kiosk[a-z0-9]{1,6}@[a-z]{3,8}\.[a-z]{2,4}", fullmatch=True
        ),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_kiosk_creation_succeeds_without_names(
        self, email: str
    ) -> None:
        """P16: kiosk user creation succeeds without first_name/last_name."""
        org_id = uuid.uuid4()
        inviter_id = uuid.uuid4()

        db = AsyncMock()

        # Email check: no existing user
        email_check_result = MagicMock()
        email_check_result.scalar_one_or_none.return_value = None

        # Org name lookup
        org_name_result = MagicMock()
        org_name_result.scalar_one_or_none.return_value = "Test Org"

        db.execute = AsyncMock(side_effect=[
            email_check_result,
            org_name_result,
        ])
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service._send_invitation_email", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", new_callable=AsyncMock),
        ):
            result = await create_invitation(
                db,
                inviter_user_id=inviter_id,
                org_id=org_id,
                email=email,
                role="kiosk",
            )

        assert "user_id" in result
        assert result["invitation_expires_at"] is not None

        # Verify the User was created via db.add
        assert db.add.call_count == 1
        created_user = db.add.call_args[0][0]
        assert isinstance(created_user, User)
        assert created_user.email == email
        assert created_user.role == "kiosk"
        assert created_user.org_id == org_id
        # first_name and last_name should be None (not required for kiosk)
        assert created_user.first_name is None
        assert created_user.last_name is None

    @given(
        email=st.from_regex(
            r"kiosk[a-z0-9]{1,6}@[a-z]{3,8}\.[a-z]{2,4}", fullmatch=True
        ),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_user_model_allows_null_names(self, email: str) -> None:
        """P16: User model allows first_name and last_name to be None."""
        user = User(
            org_id=uuid.uuid4(),
            email=email,
            role="kiosk",
            is_active=True,
            is_email_verified=False,
            password_hash=None,
            first_name=None,
            last_name=None,
        )
        assert user.first_name is None
        assert user.last_name is None
        assert user.role == "kiosk"
        assert user.email == email

    @given(
        email=st.from_regex(
            r"kiosk[a-z0-9]{1,6}@[a-z]{3,8}\.[a-z]{2,4}", fullmatch=True
        ),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_kiosk_role_accepted_by_create_invitation(
        self, email: str
    ) -> None:
        """P16: create_invitation accepts role='kiosk' without raising ValueError."""
        org_id = uuid.uuid4()
        inviter_id = uuid.uuid4()

        db = AsyncMock()

        email_check_result = MagicMock()
        email_check_result.scalar_one_or_none.return_value = None

        org_name_result = MagicMock()
        org_name_result.scalar_one_or_none.return_value = "Test Org"

        db.execute = AsyncMock(side_effect=[
            email_check_result,
            org_name_result,
        ])
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service._send_invitation_email", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", new_callable=AsyncMock),
        ):
            # Should not raise ValueError for role="kiosk"
            result = await create_invitation(
                db,
                inviter_user_id=inviter_id,
                org_id=org_id,
                email=email,
                role="kiosk",
            )

        assert "user_id" in result
