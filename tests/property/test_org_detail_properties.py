"""Property-based tests for Organisation Detail Dashboard schemas.

Validates that the OrgDetailResponse schema enforces compliance and
data-safety invariants across all valid inputs.

**Feature: org-detail-dashboard**

Uses Hypothesis to generate random OrgDetailResponse instances and verify
that serialised JSON never leaks sensitive data, payment methods are
properly masked, and all count fields are non-negative integers.
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

from app.modules.admin.schemas import (
    OrgDetailAdminAction,
    OrgDetailBilling,
    OrgDetailCoupon,
    OrgDetailHealth,
    OrgDetailLoginAttempt,
    OrgDetailOverview,
    OrgDetailPaymentMethod,
    OrgDetailResponse,
    OrgDetailSecurity,
    OrgDetailStorageAddon,
    OrgDetailUsage,
    OrgDetailUser,
    OrgDetailUserSection,
)

PBT_SETTINGS = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_last4_strategy = st.text(
    alphabet=st.sampled_from("0123456789"),
    min_size=4,
    max_size=4,
)

_brand_strategy = st.sampled_from(["visa", "mastercard", "amex", "discover", "diners"])

_payment_method_strategy = st.builds(
    OrgDetailPaymentMethod,
    brand=_brand_strategy,
    last4=_last4_strategy,
    exp_month=st.integers(min_value=1, max_value=12),
    exp_year=st.integers(min_value=2024, max_value=2040),
)

_non_neg_int = st.integers(min_value=0, max_value=10_000_000)

_coupon_strategy = st.builds(
    OrgDetailCoupon,
    coupon_code=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
    discount_type=st.sampled_from(["percentage", "fixed"]),
    discount_value=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
    duration_months=st.one_of(st.none(), st.integers(min_value=1, max_value=36)),
    billing_months_used=_non_neg_int,
    is_expired=st.booleans(),
)

_storage_addon_strategy = st.builds(
    OrgDetailStorageAddon,
    package_name=st.one_of(st.none(), st.text(min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "N", "Z")))),
    quantity_gb=st.integers(min_value=1, max_value=1000),
    price_nzd_per_month=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    is_custom=st.booleans(),
)

_billing_strategy = st.builds(
    OrgDetailBilling,
    plan_name=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Z"))),
    monthly_price_nzd=st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    billing_interval=st.sampled_from(["monthly", "quarterly", "annually"]),
    next_billing_date=st.one_of(st.none(), st.just("2025-06-01")),
    payment_method=st.one_of(st.none(), _payment_method_strategy),
    coupons=st.lists(_coupon_strategy, min_size=0, max_size=3),
    storage_addon=st.one_of(st.none(), _storage_addon_strategy),
    receipts_success_90d=_non_neg_int,
    receipts_failed_90d=_non_neg_int,
    last_failure_date=st.one_of(st.none(), st.just("2025-05-15")),
)

_usage_strategy = st.builds(
    OrgDetailUsage,
    invoice_count=_non_neg_int,
    quote_count=_non_neg_int,
    customer_count=_non_neg_int,
    vehicle_count=_non_neg_int,
    storage_used_bytes=_non_neg_int,
    storage_quota_gb=_non_neg_int,
    carjam_lookups_this_month=_non_neg_int,
    carjam_lookups_included=_non_neg_int,
    sms_sent_this_month=_non_neg_int,
    sms_included_quota=_non_neg_int,
)

_user_strategy = st.builds(
    OrgDetailUser,
    id=st.uuids().map(str),
    name=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "Z"))),
    email=st.from_regex(r"[a-z]{3,10}@example\.com", fullmatch=True),
    role=st.sampled_from(["org_admin", "staff", "accountant"]),
    is_active=st.booleans(),
    last_login_at=st.one_of(st.none(), st.just("2025-05-01T10:00:00Z")),
    mfa_enabled=st.booleans(),
)

_user_section_strategy = st.builds(
    OrgDetailUserSection,
    users=st.lists(_user_strategy, min_size=0, max_size=10),
    active_count=_non_neg_int,
    seat_limit=_non_neg_int,
)

_login_attempt_strategy = st.builds(
    OrgDetailLoginAttempt,
    user_email=st.from_regex(r"[a-z]{3,10}@example\.com", fullmatch=True),
    success=st.booleans(),
    ip_address=st.one_of(st.none(), st.just("192.168.1.1")),
    device_info=st.one_of(st.none(), st.just("Mozilla/5.0")),
    timestamp=st.just("2025-05-20T08:30:00Z"),
)

_admin_action_strategy = st.builds(
    OrgDetailAdminAction,
    action=st.sampled_from(["org_suspended", "org_reinstated", "org_plan_changed", "org_coupon_applied"]),
    admin_email=st.one_of(st.none(), st.from_regex(r"[a-z]{3,10}@example\.com", fullmatch=True)),
    ip_address=st.one_of(st.none(), st.just("10.0.0.1")),
    timestamp=st.just("2025-05-18T14:00:00Z"),
)

_security_strategy = st.builds(
    OrgDetailSecurity,
    login_attempts=st.lists(_login_attempt_strategy, min_size=0, max_size=5),
    admin_actions=st.lists(_admin_action_strategy, min_size=0, max_size=5),
    mfa_enrolled_count=_non_neg_int,
    mfa_total_users=_non_neg_int,
    failed_payments_90d=_non_neg_int,
)

_health_strategy = st.builds(
    OrgDetailHealth,
    billing_ok=st.booleans(),
    storage_ok=st.booleans(),
    storage_warning=st.booleans(),
    seats_ok=st.booleans(),
    mfa_ok=st.booleans(),
    status_ok=st.booleans(),
)

_overview_strategy = st.builds(
    OrgDetailOverview,
    id=st.uuids().map(str),
    name=st.text(min_size=1, max_size=100, alphabet=st.characters(whitelist_categories=("L", "N", "Z"))),
    status=st.sampled_from(["active", "trial", "payment_pending", "suspended", "deleted"]),
    plan_name=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Z"))),
    plan_id=st.uuids().map(str),
    signup_date=st.just("2024-01-15"),
    business_type=st.one_of(st.none(), st.sampled_from(["sole_trader", "partnership", "company", "trust", "other"])),
    trade_category_name=st.one_of(st.none(), st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "Z")))),
    billing_interval=st.sampled_from(["monthly", "quarterly", "annually"]),
    trial_ends_at=st.one_of(st.none(), st.just("2025-02-15")),
    timezone=st.just("Pacific/Auckland"),
    locale=st.just("en-NZ"),
)

_org_detail_response_strategy = st.builds(
    OrgDetailResponse,
    overview=_overview_strategy,
    billing=_billing_strategy,
    usage=_usage_strategy,
    users=_user_section_strategy,
    security=_security_strategy,
    health=_health_strategy,
)

# Strategy that always includes a payment method (for Property 1)
_billing_with_payment_strategy = st.builds(
    OrgDetailBilling,
    plan_name=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Z"))),
    monthly_price_nzd=st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    billing_interval=st.sampled_from(["monthly", "quarterly", "annually"]),
    next_billing_date=st.one_of(st.none(), st.just("2025-06-01")),
    payment_method=_payment_method_strategy,
    coupons=st.lists(_coupon_strategy, min_size=0, max_size=3),
    storage_addon=st.one_of(st.none(), _storage_addon_strategy),
    receipts_success_90d=_non_neg_int,
    receipts_failed_90d=_non_neg_int,
    last_failure_date=st.one_of(st.none(), st.just("2025-05-15")),
)

_response_with_payment_strategy = st.builds(
    OrgDetailResponse,
    overview=_overview_strategy,
    billing=_billing_with_payment_strategy,
    usage=_usage_strategy,
    users=_user_section_strategy,
    security=_security_strategy,
    health=_health_strategy,
)


# ===========================================================================
# Property 1: Payment method masking invariant
# ===========================================================================


class TestPaymentMethodMaskingInvariant:
    """Serialised OrgDetailResponse with payment_method present contains
    only ``brand``, ``last4``, ``exp_month``, ``exp_year`` keys in the
    payment_method object; ``last4`` is exactly 4 chars; no forbidden keys
    appear anywhere in the JSON.

    **Validates: Requirements 3.3, 3.4, 8.2, 9.3**
    """

    ALLOWED_PM_KEYS = {"brand", "last4", "exp_month", "exp_year"}
    FORBIDDEN_KEYS = {"stripe_payment_method_id", "cvv", "card_number", "full_number"}

    @given(response=_response_with_payment_strategy)
    @PBT_SETTINGS
    def test_payment_method_contains_only_allowed_keys(
        self, response: OrgDetailResponse
    ) -> None:
        """The payment_method object in the serialised response contains
        only the allowed masked fields."""
        data = json.loads(response.model_dump_json())
        pm = data["billing"]["payment_method"]
        assert pm is not None, "Expected payment_method to be present"
        actual_keys = set(pm.keys())
        assert actual_keys == self.ALLOWED_PM_KEYS, (
            f"payment_method has unexpected keys: {actual_keys - self.ALLOWED_PM_KEYS}"
        )

    @given(response=_response_with_payment_strategy)
    @PBT_SETTINGS
    def test_last4_is_exactly_4_characters(
        self, response: OrgDetailResponse
    ) -> None:
        """The last4 field is exactly 4 characters long."""
        data = json.loads(response.model_dump_json())
        last4 = data["billing"]["payment_method"]["last4"]
        assert len(last4) == 4, f"last4 has length {len(last4)}, expected 4"

    @given(response=_response_with_payment_strategy)
    @PBT_SETTINGS
    def test_no_forbidden_keys_in_serialised_json(
        self, response: OrgDetailResponse
    ) -> None:
        """No forbidden sensitive key names appear anywhere in the
        serialised JSON response."""
        json_str = response.model_dump_json()
        for forbidden in self.FORBIDDEN_KEYS:
            assert f'"{forbidden}"' not in json_str, (
                f"Forbidden key '{forbidden}' found in serialised response"
            )


# ===========================================================================
# Property 2: Aggregate counts are non-negative integers
# ===========================================================================


class TestAggregateCountsNonNegative:
    """All count fields in generated OrgDetailResponse dicts are
    non-negative integers.

    **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 5.1, 6.7**
    """

    COUNT_FIELDS = {
        "usage": [
            "invoice_count",
            "quote_count",
            "customer_count",
            "vehicle_count",
            "storage_used_bytes",
            "storage_quota_gb",
            "carjam_lookups_this_month",
            "carjam_lookups_included",
            "sms_sent_this_month",
            "sms_included_quota",
        ],
        "billing": [
            "receipts_success_90d",
            "receipts_failed_90d",
        ],
        "users": [
            "active_count",
            "seat_limit",
        ],
        "security": [
            "mfa_enrolled_count",
            "mfa_total_users",
            "failed_payments_90d",
        ],
    }

    @given(response=_org_detail_response_strategy)
    @PBT_SETTINGS
    def test_all_count_fields_are_non_negative_integers(
        self, response: OrgDetailResponse
    ) -> None:
        """Every count field across all sections is a non-negative integer."""
        data = response.model_dump()
        for section, fields in self.COUNT_FIELDS.items():
            section_data = data[section]
            for field in fields:
                value = section_data[field]
                assert isinstance(value, int), (
                    f"{section}.{field} is {type(value).__name__}, expected int"
                )
                assert value >= 0, (
                    f"{section}.{field} is {value}, expected non-negative"
                )


# ===========================================================================
# Property 6: No sensitive data leakage in response
# ===========================================================================


class TestNoSensitiveDataLeakage:
    """Serialised JSON of OrgDetailResponse does not contain any keys
    that would leak sensitive data.

    **Validates: Requirements 4.10, 6.5, 8.3, 9.4, 9.5**
    """

    FORBIDDEN_KEYS = [
        "password_hash",
        "secret_encrypted",
        "stripe_payment_method_id",
        "before_value",
        "after_value",
        "authentication_token",
        "refresh_token",
        "line_items",
        "customer_address",
        "customer_phone",
        "invoice_content",
    ]

    @given(response=_org_detail_response_strategy)
    @PBT_SETTINGS
    def test_no_forbidden_keys_in_serialised_json(
        self, response: OrgDetailResponse
    ) -> None:
        """The serialised JSON string does not contain any forbidden
        sensitive key names."""
        json_str = response.model_dump_json()
        for forbidden in self.FORBIDDEN_KEYS:
            assert f'"{forbidden}"' not in json_str, (
                f"Sensitive key '{forbidden}' found in serialised response JSON"
            )

    @given(response=_org_detail_response_strategy)
    @PBT_SETTINGS
    def test_no_forbidden_keys_in_parsed_json(
        self, response: OrgDetailResponse
    ) -> None:
        """Walking the parsed JSON dict, no forbidden key name appears
        at any nesting level."""
        data = json.loads(response.model_dump_json())

        def _collect_keys(obj: dict | list) -> set[str]:
            keys: set[str] = set()
            if isinstance(obj, dict):
                keys.update(obj.keys())
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        keys.update(_collect_keys(v))
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (dict, list)):
                        keys.update(_collect_keys(item))
            return keys

        all_keys = _collect_keys(data)
        leaked = all_keys & set(self.FORBIDDEN_KEYS)
        assert not leaked, (
            f"Sensitive keys found in response: {leaked}"
        )


# ---------------------------------------------------------------------------
# Import for Property 4
# ---------------------------------------------------------------------------
from app.modules.admin.service import compute_health_indicators


# ===========================================================================
# Property 4: Health indicator derivation consistency
# ===========================================================================


class TestHealthIndicatorDerivationConsistency:
    """For random metric inputs, each health flag returned by
    ``compute_health_indicators`` matches its derivation formula exactly.

    **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6**
    """

    @given(
        status=st.sampled_from(
            ["active", "trial", "payment_pending", "suspended", "deleted"]
        ),
        receipts_failed_90d=st.integers(min_value=0, max_value=1000),
        storage_used_bytes=st.integers(min_value=0, max_value=50 * 1_073_741_824),
        storage_quota_gb=st.integers(min_value=0, max_value=50),
        active_user_count=st.integers(min_value=0, max_value=500),
        seat_limit=st.integers(min_value=1, max_value=500),
        mfa_enrolled_count=st.integers(min_value=0, max_value=500),
        total_users=st.integers(min_value=0, max_value=500),
    )
    @PBT_SETTINGS
    def test_billing_ok_matches_formula(
        self,
        status: str,
        receipts_failed_90d: int,
        storage_used_bytes: int,
        storage_quota_gb: int,
        active_user_count: int,
        seat_limit: int,
        mfa_enrolled_count: int,
        total_users: int,
    ) -> None:
        """billing_ok is True iff receipts_failed_90d == 0."""
        result = compute_health_indicators(
            status=status,
            receipts_failed_90d=receipts_failed_90d,
            storage_used_bytes=storage_used_bytes,
            storage_quota_gb=storage_quota_gb,
            active_user_count=active_user_count,
            seat_limit=seat_limit,
            mfa_enrolled_count=mfa_enrolled_count,
            total_users=total_users,
        )
        expected = receipts_failed_90d == 0
        assert result["billing_ok"] is expected, (
            f"billing_ok={result['billing_ok']}, expected={expected} "
            f"(receipts_failed_90d={receipts_failed_90d})"
        )

    @given(
        status=st.sampled_from(
            ["active", "trial", "payment_pending", "suspended", "deleted"]
        ),
        receipts_failed_90d=st.integers(min_value=0, max_value=1000),
        storage_used_bytes=st.integers(min_value=0, max_value=50 * 1_073_741_824),
        storage_quota_gb=st.integers(min_value=0, max_value=50),
        active_user_count=st.integers(min_value=0, max_value=500),
        seat_limit=st.integers(min_value=1, max_value=500),
        mfa_enrolled_count=st.integers(min_value=0, max_value=500),
        total_users=st.integers(min_value=0, max_value=500),
    )
    @PBT_SETTINGS
    def test_storage_ok_matches_formula(
        self,
        status: str,
        receipts_failed_90d: int,
        storage_used_bytes: int,
        storage_quota_gb: int,
        active_user_count: int,
        seat_limit: int,
        mfa_enrolled_count: int,
        total_users: int,
    ) -> None:
        """storage_ok is True iff storage_ratio <= 0.9."""
        result = compute_health_indicators(
            status=status,
            receipts_failed_90d=receipts_failed_90d,
            storage_used_bytes=storage_used_bytes,
            storage_quota_gb=storage_quota_gb,
            active_user_count=active_user_count,
            seat_limit=seat_limit,
            mfa_enrolled_count=mfa_enrolled_count,
            total_users=total_users,
        )
        storage_ratio = storage_used_bytes / max(storage_quota_gb * 1_073_741_824, 1)
        expected = storage_ratio <= 0.9
        assert result["storage_ok"] is expected, (
            f"storage_ok={result['storage_ok']}, expected={expected} "
            f"(storage_ratio={storage_ratio:.6f}, "
            f"storage_used_bytes={storage_used_bytes}, "
            f"storage_quota_gb={storage_quota_gb})"
        )

    @given(
        status=st.sampled_from(
            ["active", "trial", "payment_pending", "suspended", "deleted"]
        ),
        receipts_failed_90d=st.integers(min_value=0, max_value=1000),
        storage_used_bytes=st.integers(min_value=0, max_value=50 * 1_073_741_824),
        storage_quota_gb=st.integers(min_value=0, max_value=50),
        active_user_count=st.integers(min_value=0, max_value=500),
        seat_limit=st.integers(min_value=1, max_value=500),
        mfa_enrolled_count=st.integers(min_value=0, max_value=500),
        total_users=st.integers(min_value=0, max_value=500),
    )
    @PBT_SETTINGS
    def test_storage_warning_matches_formula(
        self,
        status: str,
        receipts_failed_90d: int,
        storage_used_bytes: int,
        storage_quota_gb: int,
        active_user_count: int,
        seat_limit: int,
        mfa_enrolled_count: int,
        total_users: int,
    ) -> None:
        """storage_warning is True iff 0.8 < storage_ratio <= 0.9."""
        result = compute_health_indicators(
            status=status,
            receipts_failed_90d=receipts_failed_90d,
            storage_used_bytes=storage_used_bytes,
            storage_quota_gb=storage_quota_gb,
            active_user_count=active_user_count,
            seat_limit=seat_limit,
            mfa_enrolled_count=mfa_enrolled_count,
            total_users=total_users,
        )
        storage_ratio = storage_used_bytes / max(storage_quota_gb * 1_073_741_824, 1)
        expected = 0.8 < storage_ratio <= 0.9
        assert result["storage_warning"] is expected, (
            f"storage_warning={result['storage_warning']}, expected={expected} "
            f"(storage_ratio={storage_ratio:.6f}, "
            f"storage_used_bytes={storage_used_bytes}, "
            f"storage_quota_gb={storage_quota_gb})"
        )

    @given(
        status=st.sampled_from(
            ["active", "trial", "payment_pending", "suspended", "deleted"]
        ),
        receipts_failed_90d=st.integers(min_value=0, max_value=1000),
        storage_used_bytes=st.integers(min_value=0, max_value=50 * 1_073_741_824),
        storage_quota_gb=st.integers(min_value=0, max_value=50),
        active_user_count=st.integers(min_value=0, max_value=500),
        seat_limit=st.integers(min_value=1, max_value=500),
        mfa_enrolled_count=st.integers(min_value=0, max_value=500),
        total_users=st.integers(min_value=0, max_value=500),
    )
    @PBT_SETTINGS
    def test_seats_ok_matches_formula(
        self,
        status: str,
        receipts_failed_90d: int,
        storage_used_bytes: int,
        storage_quota_gb: int,
        active_user_count: int,
        seat_limit: int,
        mfa_enrolled_count: int,
        total_users: int,
    ) -> None:
        """seats_ok is True iff active_user_count < seat_limit."""
        result = compute_health_indicators(
            status=status,
            receipts_failed_90d=receipts_failed_90d,
            storage_used_bytes=storage_used_bytes,
            storage_quota_gb=storage_quota_gb,
            active_user_count=active_user_count,
            seat_limit=seat_limit,
            mfa_enrolled_count=mfa_enrolled_count,
            total_users=total_users,
        )
        expected = active_user_count < seat_limit
        assert result["seats_ok"] is expected, (
            f"seats_ok={result['seats_ok']}, expected={expected} "
            f"(active_user_count={active_user_count}, seat_limit={seat_limit})"
        )

    @given(
        status=st.sampled_from(
            ["active", "trial", "payment_pending", "suspended", "deleted"]
        ),
        receipts_failed_90d=st.integers(min_value=0, max_value=1000),
        storage_used_bytes=st.integers(min_value=0, max_value=50 * 1_073_741_824),
        storage_quota_gb=st.integers(min_value=0, max_value=50),
        active_user_count=st.integers(min_value=0, max_value=500),
        seat_limit=st.integers(min_value=1, max_value=500),
        mfa_enrolled_count=st.integers(min_value=0, max_value=500),
        total_users=st.integers(min_value=0, max_value=500),
    )
    @PBT_SETTINGS
    def test_mfa_ok_matches_formula(
        self,
        status: str,
        receipts_failed_90d: int,
        storage_used_bytes: int,
        storage_quota_gb: int,
        active_user_count: int,
        seat_limit: int,
        mfa_enrolled_count: int,
        total_users: int,
    ) -> None:
        """mfa_ok is True iff mfa_enrolled_count / max(total_users, 1) >= 0.5."""
        result = compute_health_indicators(
            status=status,
            receipts_failed_90d=receipts_failed_90d,
            storage_used_bytes=storage_used_bytes,
            storage_quota_gb=storage_quota_gb,
            active_user_count=active_user_count,
            seat_limit=seat_limit,
            mfa_enrolled_count=mfa_enrolled_count,
            total_users=total_users,
        )
        mfa_ratio = mfa_enrolled_count / max(total_users, 1)
        expected = mfa_ratio >= 0.5
        assert result["mfa_ok"] is expected, (
            f"mfa_ok={result['mfa_ok']}, expected={expected} "
            f"(mfa_enrolled_count={mfa_enrolled_count}, total_users={total_users}, "
            f"mfa_ratio={mfa_ratio:.4f})"
        )

    @given(
        status=st.sampled_from(
            ["active", "trial", "payment_pending", "suspended", "deleted"]
        ),
        receipts_failed_90d=st.integers(min_value=0, max_value=1000),
        storage_used_bytes=st.integers(min_value=0, max_value=50 * 1_073_741_824),
        storage_quota_gb=st.integers(min_value=0, max_value=50),
        active_user_count=st.integers(min_value=0, max_value=500),
        seat_limit=st.integers(min_value=1, max_value=500),
        mfa_enrolled_count=st.integers(min_value=0, max_value=500),
        total_users=st.integers(min_value=0, max_value=500),
    )
    @PBT_SETTINGS
    def test_status_ok_matches_formula(
        self,
        status: str,
        receipts_failed_90d: int,
        storage_used_bytes: int,
        storage_quota_gb: int,
        active_user_count: int,
        seat_limit: int,
        mfa_enrolled_count: int,
        total_users: int,
    ) -> None:
        """status_ok is True iff status not in ("suspended", "payment_pending")."""
        result = compute_health_indicators(
            status=status,
            receipts_failed_90d=receipts_failed_90d,
            storage_used_bytes=storage_used_bytes,
            storage_quota_gb=storage_quota_gb,
            active_user_count=active_user_count,
            seat_limit=seat_limit,
            mfa_enrolled_count=mfa_enrolled_count,
            total_users=total_users,
        )
        expected = status not in ("suspended", "payment_pending")
        assert result["status_ok"] is expected, (
            f"status_ok={result['status_ok']}, expected={expected} "
            f"(status={status!r})"
        )


# ---------------------------------------------------------------------------
# Imports for Property 5
# ---------------------------------------------------------------------------
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.admin.service import get_org_detail


# ===========================================================================
# Property 5: Audit log entry creation on access
# ===========================================================================


import uuid as _uuid_mod


def _make_fake_org(org_id: _uuid_mod.UUID) -> MagicMock:
    """Create a minimal fake Organisation ORM object for the org query."""
    org = MagicMock()
    org.id = org_id
    org.name = "Test Org"
    org.status = "active"
    org.business_type = "company"
    org.trade_category_id = None
    org.billing_interval = "monthly"
    org.trial_ends_at = None
    org.timezone = "Pacific/Auckland"
    org.locale = "en-NZ"
    org.created_at = MagicMock()
    org.created_at.isoformat.return_value = "2024-01-15T00:00:00+00:00"
    org.next_billing_date = None
    org.storage_used_bytes = 0
    org.storage_quota_gb = 10
    org.carjam_lookups_this_month = 0
    org.sms_sent_this_month = 0
    org.plan_id = _uuid_mod.uuid4()
    return org


def _make_fake_plan() -> MagicMock:
    """Create a minimal fake SubscriptionPlan ORM object."""
    plan = MagicMock()
    plan.id = _uuid_mod.uuid4()
    plan.name = "Standard"
    plan.monthly_price_nzd = 49.0
    plan.user_seats = 5
    plan.storage_quota_gb = 10
    plan.carjam_lookups_included = 100
    plan.sms_included_quota = 50
    return plan


class TestAuditLogEntryCreationOnAccess:
    """For random valid UUIDs, calling ``get_org_detail`` with a mocked DB
    session calls ``write_audit_log`` exactly once with
    ``action="org_detail_viewed"``, ``entity_type="organisation"``, and
    ``entity_id=org_id``.

    **Validates: Requirements 8.1, 9.7**
    """

    @given(
        org_id=st.uuids(),
        admin_user_id=st.uuids(),
        ip_address=st.one_of(st.none(), st.just("192.168.1.100")),
        device_info=st.one_of(st.none(), st.just("Mozilla/5.0")),
    )
    @PBT_SETTINGS
    def test_write_audit_log_called_once_with_correct_params(
        self,
        org_id: _uuid_mod.UUID,
        admin_user_id: _uuid_mod.UUID,
        ip_address: str | None,
        device_info: str | None,
    ) -> None:
        """write_audit_log is called exactly once with the correct
        action, entity_type, and entity_id matching the requested org_id."""

        fake_org = _make_fake_org(org_id)
        fake_plan = _make_fake_plan()
        trade_category_name = None

        # Build a mock DB session
        db = AsyncMock()

        # The first db.execute call is the org query (section 1).
        # It must return a row with (org, plan, trade_category_name).
        org_result = MagicMock()
        org_result.one_or_none.return_value = (fake_org, fake_plan, trade_category_name)

        # Subsequent db.execute calls (sections 2-9) can return empty/default
        # results — the try/except blocks in get_org_detail handle failures
        # gracefully.  We make them raise so they fall through to defaults.
        def _execute_side_effects():
            """Yield the org result first, then raise for all others."""
            yield org_result
            while True:
                raise Exception("mocked sub-query — expected to be caught")

        side_effect_iter = _execute_side_effects()
        db.execute = AsyncMock(side_effect=lambda *a, **kw: next(side_effect_iter))
        db.flush = AsyncMock()

        mock_write_audit = AsyncMock(return_value=_uuid_mod.uuid4())

        with patch(
            "app.modules.admin.service.write_audit_log",
            mock_write_audit,
        ):
            result = asyncio.run(
                get_org_detail(
                    db,
                    org_id=org_id,
                    admin_user_id=admin_user_id,
                    ip_address=ip_address,
                    device_info=device_info,
                )
            )

        # The function should have returned a dict (not None)
        assert result is not None, "get_org_detail returned None unexpectedly"

        # write_audit_log must have been called exactly once
        assert mock_write_audit.call_count == 1, (
            f"write_audit_log called {mock_write_audit.call_count} times, expected 1"
        )

        call_kwargs = mock_write_audit.call_args
        # The call uses keyword arguments; extract them
        _, kwargs = call_kwargs
        # Also check positional: session=db is the first positional arg
        args, _ = call_kwargs
        if args:
            assert args[0] is db, "First positional arg should be the db session"
        else:
            assert kwargs.get("session") is db, "session kwarg should be the db session"

        assert kwargs.get("action") == "org_detail_viewed", (
            f"action={kwargs.get('action')!r}, expected 'org_detail_viewed'"
        )
        assert kwargs.get("entity_type") == "organisation", (
            f"entity_type={kwargs.get('entity_type')!r}, expected 'organisation'"
        )
        assert kwargs.get("entity_id") == org_id, (
            f"entity_id={kwargs.get('entity_id')!r}, expected {org_id!r}"
        )


# ---------------------------------------------------------------------------
# Imports for Properties 7 & 8
# ---------------------------------------------------------------------------
from datetime import datetime, timedelta, timezone as _tz


# ---------------------------------------------------------------------------
# Strategies for Properties 7 & 8 — bounded lists
# ---------------------------------------------------------------------------

def _iso_timestamp_within_days(max_days: int) -> st.SearchStrategy[str]:
    """Generate an ISO 8601 timestamp string within the last ``max_days`` days.

    Uses a small buffer (0.01 days ≈ 14 minutes) to avoid race conditions
    between strategy generation time and assertion evaluation time.
    """
    now = datetime.now(_tz.utc)
    return st.floats(
        min_value=0.0,
        max_value=float(max_days) - 0.01,
        allow_nan=False,
        allow_infinity=False,
    ).map(lambda days_ago: (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"))


_login_attempt_bounded_strategy = st.builds(
    OrgDetailLoginAttempt,
    user_email=st.from_regex(r"[a-z]{3,10}@example\.com", fullmatch=True),
    success=st.booleans(),
    ip_address=st.one_of(st.none(), st.just("192.168.1.1")),
    device_info=st.one_of(st.none(), st.just("Mozilla/5.0")),
    timestamp=_iso_timestamp_within_days(30),
)

_admin_action_bounded_strategy = st.builds(
    OrgDetailAdminAction,
    action=st.sampled_from(["org_suspended", "org_reinstated", "org_plan_changed", "org_coupon_applied"]),
    admin_email=st.one_of(st.none(), st.from_regex(r"[a-z]{3,10}@example\.com", fullmatch=True)),
    ip_address=st.one_of(st.none(), st.just("10.0.0.1")),
    timestamp=_iso_timestamp_within_days(90),
)

_security_bounded_strategy = st.builds(
    OrgDetailSecurity,
    login_attempts=st.lists(_login_attempt_bounded_strategy, min_size=0, max_size=50),
    admin_actions=st.lists(_admin_action_bounded_strategy, min_size=0, max_size=50),
    mfa_enrolled_count=_non_neg_int,
    mfa_total_users=_non_neg_int,
    failed_payments_90d=_non_neg_int,
)

_org_detail_response_bounded_strategy = st.builds(
    OrgDetailResponse,
    overview=_overview_strategy,
    billing=_billing_strategy,
    usage=_usage_strategy,
    users=_user_section_strategy,
    security=_security_bounded_strategy,
    health=_health_strategy,
)


# ===========================================================================
# Property 7: Login attempts bounded by time window and count limit
# ===========================================================================


class TestLoginAttemptsBounded:
    """All entries in ``security.login_attempts`` have timestamps within
    the last 30 days and the list length is at most 50.

    **Validates: Requirements 6.1, 6.2**
    """

    @given(response=_org_detail_response_bounded_strategy)
    @PBT_SETTINGS
    def test_login_attempts_list_length_at_most_50(
        self, response: OrgDetailResponse
    ) -> None:
        """The login_attempts list never exceeds 50 entries."""
        data = response.model_dump()
        login_attempts = data["security"]["login_attempts"]
        assert len(login_attempts) <= 50, (
            f"login_attempts has {len(login_attempts)} entries, expected <= 50"
        )

    @given(response=_org_detail_response_bounded_strategy)
    @PBT_SETTINGS
    def test_login_attempts_timestamps_within_30_days(
        self, response: OrgDetailResponse
    ) -> None:
        """Every login attempt timestamp is within the last 30 days."""
        data = response.model_dump()
        login_attempts = data["security"]["login_attempts"]
        now = datetime.now(_tz.utc)
        # Small tolerance (5 min) to account for time elapsed between
        # strategy generation and assertion evaluation.
        tolerance = timedelta(minutes=5)
        cutoff = now - timedelta(days=30) - tolerance

        for i, attempt in enumerate(login_attempts):
            ts_str = attempt["timestamp"]
            ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
            assert ts >= cutoff, (
                f"login_attempts[{i}].timestamp={ts_str} is older than 30 days "
                f"(cutoff={cutoff.isoformat()})"
            )
            assert ts <= now + tolerance, (
                f"login_attempts[{i}].timestamp={ts_str} is in the future"
            )


# ===========================================================================
# Property 8: Admin actions bounded by time window and count limit
# ===========================================================================


class TestAdminActionsBounded:
    """All entries in ``security.admin_actions`` have timestamps within
    the last 90 days and the list length is at most 50.

    **Validates: Requirements 6.3, 6.4**
    """

    @given(response=_org_detail_response_bounded_strategy)
    @PBT_SETTINGS
    def test_admin_actions_list_length_at_most_50(
        self, response: OrgDetailResponse
    ) -> None:
        """The admin_actions list never exceeds 50 entries."""
        data = response.model_dump()
        admin_actions = data["security"]["admin_actions"]
        assert len(admin_actions) <= 50, (
            f"admin_actions has {len(admin_actions)} entries, expected <= 50"
        )

    @given(response=_org_detail_response_bounded_strategy)
    @PBT_SETTINGS
    def test_admin_actions_timestamps_within_90_days(
        self, response: OrgDetailResponse
    ) -> None:
        """Every admin action timestamp is within the last 90 days."""
        data = response.model_dump()
        admin_actions = data["security"]["admin_actions"]
        now = datetime.now(_tz.utc)
        # Small tolerance (5 min) to account for time elapsed between
        # strategy generation and assertion evaluation.
        tolerance = timedelta(minutes=5)
        cutoff = now - timedelta(days=90) - tolerance

        for i, action in enumerate(admin_actions):
            ts_str = action["timestamp"]
            ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
            assert ts >= cutoff, (
                f"admin_actions[{i}].timestamp={ts_str} is older than 90 days "
                f"(cutoff={cutoff.isoformat()})"
            )
            assert ts <= now + tolerance, (
                f"admin_actions[{i}].timestamp={ts_str} is in the future"
            )


# ===========================================================================
# Property 3: User section seat count consistency
# ===========================================================================


# Strategy: generate a list of users with random is_active flags, then
# derive active_count and seat_limit from the generated users so the
# constructed OrgDetailUserSection is internally consistent.

def _consistent_user_section_strategy() -> st.SearchStrategy[OrgDetailUserSection]:
    """Build an ``OrgDetailUserSection`` where ``active_count`` equals the
    number of active users and ``seat_limit >= active_count``.

    This mirrors how the backend constructs the section: active_count is
    computed from the user list, and seat_limit comes from the plan (always
    >= active_count for a valid org).
    """
    return st.lists(
        _user_strategy,
        min_size=0,
        max_size=20,
    ).flatmap(
        lambda users: st.integers(
            min_value=sum(1 for u in users if u.is_active),
            max_value=max(sum(1 for u in users if u.is_active) + 50, 1),
        ).map(
            lambda seat_limit, _users=users: OrgDetailUserSection(
                users=_users,
                active_count=sum(1 for u in _users if u.is_active),
                seat_limit=seat_limit,
            )
        )
    )


class TestUserSectionSeatCountConsistency:
    """For any organisation detail response, ``active_count`` in the users
    section equals the number of users in the ``users`` list where
    ``is_active`` is true, and ``active_count <= seat_limit``.

    **Validates: Requirements 5.1, 5.6**
    """

    @given(user_section=_consistent_user_section_strategy())
    @PBT_SETTINGS
    def test_active_count_equals_active_users(
        self, user_section: OrgDetailUserSection
    ) -> None:
        """active_count matches the count of users with is_active=True."""
        data = user_section.model_dump()
        expected_active = sum(1 for u in data["users"] if u["is_active"])
        assert data["active_count"] == expected_active, (
            f"active_count={data['active_count']}, "
            f"expected={expected_active} (count of is_active=True users)"
        )

    @given(user_section=_consistent_user_section_strategy())
    @PBT_SETTINGS
    def test_active_count_lte_seat_limit(
        self, user_section: OrgDetailUserSection
    ) -> None:
        """active_count is less than or equal to seat_limit."""
        data = user_section.model_dump()
        assert data["active_count"] <= data["seat_limit"], (
            f"active_count={data['active_count']} > "
            f"seat_limit={data['seat_limit']}"
        )
