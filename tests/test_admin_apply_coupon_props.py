# Feature: org-coupon-application, Property 3/4/5
"""Property-based tests for admin_apply_coupon_to_org() service function.

Property 3: Validation rejects invalid coupon applications
Property 4: Successful application creates correct state
Property 5: Successful response contains required fields

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.6, 3.7, 3.8, 3.9**

Uses Hypothesis to generate coupon states (active/inactive, expired/valid,
usage limit reached/available, already applied/new) and valid coupon
parameters, then verifies validation, state changes, and response shape
using a mocked async DB session.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.admin.service import admin_apply_coupon_to_org


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

invalid_coupon_states = st.sampled_from([
    "inactive",
    "expired",
    "not_yet_active",
    "usage_limit_reached",
    "already_applied",
    "org_not_found",
    "coupon_not_found",
])

discount_types = st.sampled_from(["percentage", "fixed_amount", "trial_extension"])

discount_values = st.floats(min_value=0.01, max_value=10000, allow_nan=False)

duration_months_strategy = st.one_of(
    st.none(), st.integers(min_value=1, max_value=120)
)


# ---------------------------------------------------------------------------
# Helpers — mock object builders
# ---------------------------------------------------------------------------


def _make_coupon(
    *,
    coupon_id: uuid.UUID | None = None,
    code: str = "TEST-CODE",
    is_active: bool = True,
    discount_type: str = "percentage",
    discount_value: float = 20.0,
    duration_months: int | None = 3,
    usage_limit: int | None = 100,
    times_redeemed: int = 0,
    starts_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> SimpleNamespace:
    """Build a mock Coupon-like object with the required attributes."""
    return SimpleNamespace(
        id=coupon_id or uuid.uuid4(),
        code=code,
        is_active=is_active,
        discount_type=discount_type,
        discount_value=discount_value,
        duration_months=duration_months,
        usage_limit=usage_limit,
        times_redeemed=times_redeemed,
        starts_at=starts_at,
        expires_at=expires_at,
    )


def _make_org(
    *,
    org_id: uuid.UUID | None = None,
    status: str = "active",
    trial_ends_at: datetime | None = None,
) -> SimpleNamespace:
    """Build a mock Organisation-like object with the required attributes."""
    return SimpleNamespace(
        id=org_id or uuid.uuid4(),
        status=status,
        trial_ends_at=trial_ends_at,
    )


def _build_mock_db(
    coupon: SimpleNamespace | None,
    org: SimpleNamespace | None,
    existing_org_coupon: SimpleNamespace | None,
) -> AsyncMock:
    """Build a mock AsyncSession that returns the given objects for queries.

    The function under test issues these queries in order:
      1. select(Coupon).where(Coupon.id == coupon_id).with_for_update()
      2. select(Organisation).where(Organisation.id == org_id)
      3. select(OrganisationCoupon).where(org_id, coupon_id)

    After that it calls db.add(), db.flush(), db.refresh().
    """
    call_count = 0

    async def mock_execute(stmt, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()

        if call_count == 1:
            # Coupon query
            result.scalar_one_or_none.return_value = coupon
        elif call_count == 2:
            # Organisation query
            result.scalar_one_or_none.return_value = org
        elif call_count == 3:
            # Duplicate check query
            result.scalar_one_or_none.return_value = existing_org_coupon
        else:
            result.scalar_one_or_none.return_value = None

        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=mock_execute)
    db.add = MagicMock()
    db.flush = AsyncMock()

    # db.refresh should assign an id to the org_coupon object
    async def mock_refresh(obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = uuid.uuid4()

    db.refresh = AsyncMock(side_effect=mock_refresh)

    return db


# ---------------------------------------------------------------------------
# Property 3: Validation rejects invalid coupon applications
# **Validates: Requirements 3.1, 3.2, 3.3, 3.7, 3.8, 3.9**
# ---------------------------------------------------------------------------


class TestValidationRejectsInvalid:
    """Property 3: for any invalid coupon state, admin_apply_coupon_to_org()
    raises ValueError and does NOT create an OrganisationCoupon record."""

    @settings(max_examples=100)
    @given(invalid_state=invalid_coupon_states)
    def test_validation_rejects_invalid_coupon_applications(
        self, invalid_state: str
    ):
        """Property 3: Validation rejects invalid coupon applications —
        for any invalid coupon state, assert ValueError is raised.

        **Validates: Requirements 3.1, 3.2, 3.3, 3.7, 3.8, 3.9**
        """
        now = datetime.now(timezone.utc)
        org_id = uuid.uuid4()
        coupon_id = uuid.uuid4()
        applied_by = uuid.uuid4()

        coupon = None
        org = _make_org(org_id=org_id)
        existing_org_coupon = None

        if invalid_state == "coupon_not_found":
            coupon = None
        elif invalid_state == "inactive":
            coupon = _make_coupon(coupon_id=coupon_id, is_active=False)
        elif invalid_state == "expired":
            coupon = _make_coupon(
                coupon_id=coupon_id,
                expires_at=now - timedelta(days=1),
            )
        elif invalid_state == "not_yet_active":
            coupon = _make_coupon(
                coupon_id=coupon_id,
                starts_at=now + timedelta(days=30),
            )
        elif invalid_state == "usage_limit_reached":
            coupon = _make_coupon(
                coupon_id=coupon_id,
                usage_limit=5,
                times_redeemed=5,
            )
        elif invalid_state == "org_not_found":
            coupon = _make_coupon(coupon_id=coupon_id)
            org = None
        elif invalid_state == "already_applied":
            coupon = _make_coupon(coupon_id=coupon_id)
            existing_org_coupon = SimpleNamespace(id=uuid.uuid4())

        db = _build_mock_db(coupon, org, existing_org_coupon)

        with patch(
            "app.modules.admin.service.write_audit_log", new_callable=AsyncMock
        ), patch(
            "app.modules.admin.notifications_service.PlatformNotificationService"
        ):
            with pytest.raises(ValueError):
                asyncio.get_event_loop().run_until_complete(
                    admin_apply_coupon_to_org(
                        db,
                        org_id=org_id,
                        coupon_id=coupon_id,
                        applied_by=applied_by,
                    )
                )

        # db.add should NOT have been called (no OrganisationCoupon created)
        db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Property 4: Successful application creates correct state
# **Validates: Requirements 3.4**
# ---------------------------------------------------------------------------


class TestSuccessfulApplicationState:
    """Property 4: for any valid coupon + existing org, the function creates
    correct state — OrganisationCoupon added, times_redeemed incremented,
    trial extended when discount_type is trial_extension."""

    @settings(max_examples=100)
    @given(
        discount_type=discount_types,
        discount_value=discount_values,
        dur=duration_months_strategy,
    )
    def test_successful_application_creates_correct_state(
        self, discount_type: str, discount_value: float, dur: int | None
    ):
        """Property 4: Successful application creates correct state —
        for any valid coupon + existing org, assert OrganisationCoupon record
        exists with correct fields, times_redeemed incremented by 1, and
        trial_ends_at extended when discount_type == "trial_extension".

        **Validates: Requirements 3.4**
        """
        org_id = uuid.uuid4()
        coupon_id = uuid.uuid4()
        applied_by = uuid.uuid4()
        now = datetime.now(timezone.utc)

        initial_times_redeemed = 3
        initial_trial_ends_at = now + timedelta(days=10)

        coupon = _make_coupon(
            coupon_id=coupon_id,
            is_active=True,
            discount_type=discount_type,
            discount_value=discount_value,
            duration_months=dur,
            usage_limit=100,
            times_redeemed=initial_times_redeemed,
            expires_at=now + timedelta(days=365),
        )

        org = _make_org(
            org_id=org_id,
            status="active",
            trial_ends_at=initial_trial_ends_at,
        )

        db = _build_mock_db(coupon, org, existing_org_coupon=None)

        # Capture the object passed to db.add
        added_objects = []

        def capture_add(obj):
            added_objects.append(obj)

        db.add = MagicMock(side_effect=capture_add)

        with patch(
            "app.modules.admin.service.write_audit_log", new_callable=AsyncMock
        ) as mock_audit, patch(
            "app.modules.admin.notifications_service.PlatformNotificationService"
        ):
            result = asyncio.get_event_loop().run_until_complete(
                admin_apply_coupon_to_org(
                    db,
                    org_id=org_id,
                    coupon_id=coupon_id,
                    applied_by=applied_by,
                )
            )

        # 1. An OrganisationCoupon was added to the session
        assert len(added_objects) >= 1, "Expected at least one object added to session"
        org_coupon = added_objects[0]
        assert org_coupon.org_id == org_id
        assert org_coupon.coupon_id == coupon_id
        assert org_coupon.billing_months_used == 0
        assert org_coupon.is_expired is False

        # 2. times_redeemed incremented by exactly 1
        assert coupon.times_redeemed == initial_times_redeemed + 1

        # 3. If trial_extension, trial_ends_at is extended
        if discount_type == "trial_extension":
            expected_trial = initial_trial_ends_at + timedelta(
                days=float(discount_value)
            )
            assert org.trial_ends_at == expected_trial, (
                f"Expected trial_ends_at={expected_trial}, got {org.trial_ends_at}"
            )
        else:
            # trial_ends_at should remain unchanged
            assert org.trial_ends_at == initial_trial_ends_at

        # 4. Audit log was called
        mock_audit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Property 5: Successful response contains required fields
# **Validates: Requirements 3.6, 7.4**
# ---------------------------------------------------------------------------


class TestSuccessfulResponseFields:
    """Property 5: for any successful application, the returned dict contains
    organisation_coupon_id (valid UUID), coupon_code (non-empty),
    benefit_description (non-empty), message (non-empty)."""

    @settings(max_examples=100)
    @given(
        discount_type=discount_types,
        discount_value=discount_values,
        dur=duration_months_strategy,
    )
    def test_successful_response_contains_required_fields(
        self, discount_type: str, discount_value: float, dur: int | None
    ):
        """Property 5: Successful response contains required fields —
        for any successful application, assert response dict contains
        organisation_coupon_id (valid UUID string), coupon_code (non-empty),
        benefit_description (non-empty), message (non-empty).

        **Validates: Requirements 3.6, 7.4**
        """
        org_id = uuid.uuid4()
        coupon_id = uuid.uuid4()
        applied_by = uuid.uuid4()
        coupon_code = f"COUPON-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)

        coupon = _make_coupon(
            coupon_id=coupon_id,
            code=coupon_code,
            is_active=True,
            discount_type=discount_type,
            discount_value=discount_value,
            duration_months=dur,
            usage_limit=100,
            times_redeemed=0,
            expires_at=now + timedelta(days=365),
        )

        org = _make_org(
            org_id=org_id,
            status="active",
            trial_ends_at=now + timedelta(days=10),
        )

        db = _build_mock_db(coupon, org, existing_org_coupon=None)

        with patch(
            "app.modules.admin.service.write_audit_log", new_callable=AsyncMock
        ), patch(
            "app.modules.admin.notifications_service.PlatformNotificationService"
        ):
            result = asyncio.get_event_loop().run_until_complete(
                admin_apply_coupon_to_org(
                    db,
                    org_id=org_id,
                    coupon_id=coupon_id,
                    applied_by=applied_by,
                )
            )

        # 1. Result is a dict
        assert isinstance(result, dict)

        # 2. organisation_coupon_id is a valid UUID string
        assert "organisation_coupon_id" in result
        uuid.UUID(result["organisation_coupon_id"])  # raises if invalid

        # 3. coupon_code is non-empty and matches the coupon's code
        assert "coupon_code" in result
        assert isinstance(result["coupon_code"], str)
        assert len(result["coupon_code"]) > 0
        assert result["coupon_code"] == coupon_code

        # 4. benefit_description is non-empty
        assert "benefit_description" in result
        assert isinstance(result["benefit_description"], str)
        assert len(result["benefit_description"]) > 0

        # 5. message is non-empty
        assert "message" in result
        assert isinstance(result["message"], str)
        assert len(result["message"]) > 0
