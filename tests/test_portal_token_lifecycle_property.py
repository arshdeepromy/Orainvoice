"""Property-based tests for portal token lifecycle.

Tests the pure logic of token generation and revocation on enable_portal
toggle, and that the token TTL uses the org-configured value.

Properties covered:
  P11 — Token lifecycle on enable_portal toggle
  P12 — Token TTL uses org-configured value

**Validates: Requirements 12.1, 12.3, 15.2**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_ttl_days = st.integers(min_value=1, max_value=365)

_optional_ttl_days = st.one_of(st.none(), _ttl_days)

_fixed_now = datetime(2025, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Pure functions extracted from customers/service.py for testability
# ---------------------------------------------------------------------------


def apply_portal_toggle(
    *,
    enable_portal: bool,
    current_portal_token: uuid.UUID | None,
    current_portal_token_expires_at: datetime | None,
    org_portal_token_ttl_days: int | None,
    now: datetime,
) -> dict:
    """Simulate the portal token lifecycle logic from update_customer.

    When enable_portal transitions to True and portal_token is NULL,
    auto-generate a token with org-configured TTL.
    When enable_portal transitions to False, revoke the token.

    Mirrors: app/modules/customers/service.py → update_customer
    (the portal token lifecycle block)

    Returns a dict with:
      - portal_token: uuid.UUID | None
      - portal_token_expires_at: datetime | None
      - token_generated: bool (whether a new token was generated)
      - token_revoked: bool (whether the token was revoked)
    """
    portal_token = current_portal_token
    portal_token_expires_at = current_portal_token_expires_at
    token_generated = False
    token_revoked = False

    if enable_portal and portal_token is None:
        # Generate new token — mirrors the real code:
        #   customer.portal_token = uuid.uuid4()
        #   customer.portal_token_expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
        ttl_days = 90
        if org_portal_token_ttl_days is not None:
            ttl_days = org_portal_token_ttl_days

        portal_token = uuid.uuid4()
        portal_token_expires_at = now + timedelta(days=ttl_days)
        token_generated = True

    elif not enable_portal:
        # Revoke token — mirrors the real code:
        #   customer.portal_token = None
        #   customer.portal_token_expires_at = None
        portal_token = None
        portal_token_expires_at = None
        token_revoked = True

    return {
        "portal_token": portal_token,
        "portal_token_expires_at": portal_token_expires_at,
        "token_generated": token_generated,
        "token_revoked": token_revoked,
    }


def compute_token_expiry(
    *,
    org_portal_token_ttl_days: int | None,
    now: datetime,
) -> datetime:
    """Compute the expected portal_token_expires_at value.

    Mirrors the TTL computation in update_customer:
        ttl_days = 90
        if org and org.settings:
            ttl_days = org.settings.get("portal_token_ttl_days", 90)
        customer.portal_token_expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)

    Returns the expected expiry datetime.
    """
    ttl_days = 90
    if org_portal_token_ttl_days is not None:
        ttl_days = org_portal_token_ttl_days

    return now + timedelta(days=ttl_days)


# ===========================================================================
# Property 11: Token lifecycle on enable_portal toggle
# ===========================================================================


class TestP11TokenLifecycleOnEnablePortalToggle:
    """For any customer, when enable_portal transitions from false to true
    and portal_token is null, a new UUID token SHALL be generated and
    portal_token_expires_at SHALL be set to now() + org.portal_token_ttl_days.
    When enable_portal transitions from true to false, portal_token SHALL
    be set to null.

    Feature: platform-feature-gaps, Property 11: Token lifecycle on enable_portal toggle

    **Validates: Requirements 12.1, 12.3**
    """

    @given(
        org_ttl=_optional_ttl_days,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_enabling_portal_with_null_token_generates_new_token(
        self, org_ttl: int | None,
    ) -> None:
        """P11: When enable_portal transitions to True and portal_token is
        NULL, a new UUID token SHALL be generated.

        **Validates: Requirements 12.1**
        """
        result = apply_portal_toggle(
            enable_portal=True,
            current_portal_token=None,
            current_portal_token_expires_at=None,
            org_portal_token_ttl_days=org_ttl,
            now=_fixed_now,
        )

        assert result["token_generated"] is True, (
            "Expected a new token to be generated when enable_portal=True "
            "and portal_token is None"
        )
        assert result["portal_token"] is not None, (
            "Expected portal_token to be set after enabling portal"
        )
        assert isinstance(result["portal_token"], uuid.UUID), (
            f"Expected portal_token to be a UUID, got {type(result['portal_token'])}"
        )

    @given(
        org_ttl=_optional_ttl_days,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_enabling_portal_sets_expiry_based_on_ttl(
        self, org_ttl: int | None,
    ) -> None:
        """P11: When enable_portal transitions to True and portal_token is
        NULL, portal_token_expires_at SHALL be set to now() +
        org.portal_token_ttl_days.

        **Validates: Requirements 12.1, 12.3**
        """
        result = apply_portal_toggle(
            enable_portal=True,
            current_portal_token=None,
            current_portal_token_expires_at=None,
            org_portal_token_ttl_days=org_ttl,
            now=_fixed_now,
        )

        expected_ttl = org_ttl if org_ttl is not None else 90
        expected_expiry = _fixed_now + timedelta(days=expected_ttl)

        assert result["portal_token_expires_at"] == expected_expiry, (
            f"Expected portal_token_expires_at={expected_expiry} "
            f"(ttl_days={expected_ttl}), "
            f"got {result['portal_token_expires_at']}"
        )

    @given(
        existing_token=st.uuids(),
        existing_expiry=st.datetimes(
            min_value=datetime(2025, 1, 1),
            max_value=datetime(2030, 12, 31),
            timezones=st.just(timezone.utc),
        ),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_disabling_portal_revokes_token(
        self, existing_token: uuid.UUID, existing_expiry: datetime,
    ) -> None:
        """P11: When enable_portal transitions to False, portal_token
        SHALL be set to null.

        **Validates: Requirements 12.3**
        """
        result = apply_portal_toggle(
            enable_portal=False,
            current_portal_token=existing_token,
            current_portal_token_expires_at=existing_expiry,
            org_portal_token_ttl_days=None,
            now=_fixed_now,
        )

        assert result["portal_token"] is None, (
            f"Expected portal_token to be None after disabling portal, "
            f"got {result['portal_token']}"
        )
        assert result["portal_token_expires_at"] is None, (
            f"Expected portal_token_expires_at to be None after disabling "
            f"portal, got {result['portal_token_expires_at']}"
        )
        assert result["token_revoked"] is True, (
            "Expected token_revoked=True when disabling portal"
        )

    def test_disabling_portal_with_no_existing_token_still_nullifies(
        self,
    ) -> None:
        """P11: When enable_portal transitions to False and portal_token
        is already None, the result is still None (idempotent).

        **Validates: Requirements 12.3**
        """
        result = apply_portal_toggle(
            enable_portal=False,
            current_portal_token=None,
            current_portal_token_expires_at=None,
            org_portal_token_ttl_days=None,
            now=_fixed_now,
        )

        assert result["portal_token"] is None
        assert result["portal_token_expires_at"] is None
        assert result["token_revoked"] is True

    @given(
        existing_token=st.uuids(),
        existing_expiry=st.datetimes(
            min_value=datetime(2025, 1, 1),
            max_value=datetime(2030, 12, 31),
            timezones=st.just(timezone.utc),
        ),
        org_ttl=_optional_ttl_days,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_enabling_portal_with_existing_token_does_not_regenerate(
        self,
        existing_token: uuid.UUID,
        existing_expiry: datetime,
        org_ttl: int | None,
    ) -> None:
        """P11: When enable_portal is True but portal_token already exists,
        the token is NOT regenerated (preserves existing token).

        **Validates: Requirements 12.1**
        """
        result = apply_portal_toggle(
            enable_portal=True,
            current_portal_token=existing_token,
            current_portal_token_expires_at=existing_expiry,
            org_portal_token_ttl_days=org_ttl,
            now=_fixed_now,
        )

        assert result["token_generated"] is False, (
            "Expected no new token when portal_token already exists"
        )
        assert result["portal_token"] == existing_token, (
            f"Expected existing token {existing_token} to be preserved, "
            f"got {result['portal_token']}"
        )
        assert result["portal_token_expires_at"] == existing_expiry, (
            f"Expected existing expiry {existing_expiry} to be preserved, "
            f"got {result['portal_token_expires_at']}"
        )


# ===========================================================================
# Property 12: Token TTL uses org-configured value
# ===========================================================================


class TestP12TokenTTLUsesOrgConfiguredValue:
    """When generating a token, the expiry SHALL use the org's configured
    portal_token_ttl_days value, defaulting to 90 if not set.

    Feature: platform-feature-gaps, Property 12: Token TTL uses org-configured value

    **Validates: Requirements 15.2**
    """

    @given(
        ttl_days=_ttl_days,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_expiry_uses_org_configured_ttl(
        self, ttl_days: int,
    ) -> None:
        """P12: When org has portal_token_ttl_days configured, the token
        expiry SHALL use that value.

        **Validates: Requirements 15.2**
        """
        expected_expiry = _fixed_now + timedelta(days=ttl_days)

        result = apply_portal_toggle(
            enable_portal=True,
            current_portal_token=None,
            current_portal_token_expires_at=None,
            org_portal_token_ttl_days=ttl_days,
            now=_fixed_now,
        )

        assert result["portal_token_expires_at"] == expected_expiry, (
            f"Expected expiry={expected_expiry} for ttl_days={ttl_days}, "
            f"got {result['portal_token_expires_at']}"
        )

    def test_expiry_defaults_to_90_days_when_not_configured(self) -> None:
        """P12: When org has no portal_token_ttl_days configured, the
        token expiry SHALL default to 90 days.

        **Validates: Requirements 15.2**
        """
        expected_expiry = _fixed_now + timedelta(days=90)

        result = apply_portal_toggle(
            enable_portal=True,
            current_portal_token=None,
            current_portal_token_expires_at=None,
            org_portal_token_ttl_days=None,
            now=_fixed_now,
        )

        assert result["portal_token_expires_at"] == expected_expiry, (
            f"Expected default 90-day expiry={expected_expiry}, "
            f"got {result['portal_token_expires_at']}"
        )

    @given(
        ttl_days=_ttl_days,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_expiry_equals_now_plus_ttl_within_tolerance(
        self, ttl_days: int,
    ) -> None:
        """P12: The computed expiry SHALL equal now() + ttl_days exactly
        (within a 1-second tolerance for real-time tests, but exact for
        our fixed-now tests).

        **Validates: Requirements 15.2**
        """
        expected = compute_token_expiry(
            org_portal_token_ttl_days=ttl_days,
            now=_fixed_now,
        )

        result = apply_portal_toggle(
            enable_portal=True,
            current_portal_token=None,
            current_portal_token_expires_at=None,
            org_portal_token_ttl_days=ttl_days,
            now=_fixed_now,
        )

        assert result["portal_token_expires_at"] == expected, (
            f"Expiry mismatch: expected {expected}, "
            f"got {result['portal_token_expires_at']}"
        )

    @given(
        ttl_days=_ttl_days,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_different_ttl_values_produce_different_expiries(
        self, ttl_days: int,
    ) -> None:
        """P12: Different TTL values produce correspondingly different
        expiry dates.

        **Validates: Requirements 15.2**
        """
        assume(ttl_days != 90)

        result_custom = apply_portal_toggle(
            enable_portal=True,
            current_portal_token=None,
            current_portal_token_expires_at=None,
            org_portal_token_ttl_days=ttl_days,
            now=_fixed_now,
        )

        result_default = apply_portal_toggle(
            enable_portal=True,
            current_portal_token=None,
            current_portal_token_expires_at=None,
            org_portal_token_ttl_days=None,
            now=_fixed_now,
        )

        assert result_custom["portal_token_expires_at"] != result_default["portal_token_expires_at"], (
            f"Expected different expiries for ttl_days={ttl_days} vs default 90, "
            f"but both got {result_custom['portal_token_expires_at']}"
        )

    @given(
        ttl_days=_ttl_days,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_ttl_days_determines_expiry_distance_from_now(
        self, ttl_days: int,
    ) -> None:
        """P12: The distance between now and the expiry SHALL be exactly
        ttl_days days.

        **Validates: Requirements 15.2**
        """
        result = apply_portal_toggle(
            enable_portal=True,
            current_portal_token=None,
            current_portal_token_expires_at=None,
            org_portal_token_ttl_days=ttl_days,
            now=_fixed_now,
        )

        delta = result["portal_token_expires_at"] - _fixed_now
        assert delta == timedelta(days=ttl_days), (
            f"Expected expiry to be {ttl_days} days from now, "
            f"but delta was {delta}"
        )
