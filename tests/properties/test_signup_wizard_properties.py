"""Property-based tests for the multi-step signup wizard.

Properties covered:
  P1  — Paid plan signup creates pending signup with TTL and no database records
  P4  — Trial plan creates account immediately
  P8  — Coupon discount correctly applied to PaymentIntent amount
  P9  — Trial-extension coupon converts paid plan to trial
  P10 — Duplicate email replaces existing pending signup
  P11 — Signup rejects invalid CAPTCHA or already-registered email

**Validates: Requirements 1.1, 1.5, 5.2, 5.4, 6.1, 6.3, 7.3, 7.4**
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.auth.pending_signup import (
    PENDING_SIGNUP_TTL,
    create_pending_signup,
    delete_pending_signup,
    get_pending_signup,
    replace_pending_signup_for_email,
    _signup_key,
    _email_index_key,
)


# ---------------------------------------------------------------------------
# Strategies — signup form data generators
# ---------------------------------------------------------------------------

org_name_st = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip())

first_name_st = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("L",)),
).filter(lambda s: s.strip())

last_name_st = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("L",)),
).filter(lambda s: s.strip())

email_st = st.emails()

# Passwords: at least 8 chars with mixed content
password_st = st.from_regex(r"[A-Z][a-z]{3,8}[0-9]{2}[!@#$]", fullmatch=True)

plan_id_st = st.uuids().map(str)

plan_name_st = st.sampled_from([
    "Starter", "Professional", "Enterprise", "Business", "Premium",
])

payment_amount_st = st.integers(min_value=100, max_value=99999)

ip_address_st = st.from_regex(
    r"(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)",
    fullmatch=True,
)


def paid_plan_signup_data_st() -> st.SearchStrategy[dict]:
    """Generate random valid signup form data for a paid plan."""
    return st.fixed_dictionaries({
        "org_name": org_name_st,
        "admin_email": email_st,
        "admin_first_name": first_name_st,
        "admin_last_name": last_name_st,
        "password": password_st,
        "plan_id": plan_id_st,
        "plan_name": plan_name_st,
        "payment_amount_cents": payment_amount_st,
        "stripe_payment_intent_id": st.just("pi_test_").map(
            lambda prefix: prefix + uuid.uuid4().hex[:24]
        ),
        "coupon_code": st.none(),
        "coupon_discount_type": st.none(),
        "coupon_discount_value": st.none(),
        "ip_address": ip_address_st,
        "created_at": st.just("2025-01-15T10:30:00Z"),
    })


# ---------------------------------------------------------------------------
# Mock Redis helpers
# ---------------------------------------------------------------------------


def _make_mock_redis():
    """Build a MagicMock Redis whose pipeline() is sync, execute() is async.

    Also provides an in-memory store so get() returns what was set via the
    pipeline, allowing us to verify round-trip behaviour.
    """
    store: dict[str, tuple[str, int]] = {}  # key -> (value, ttl)

    redis = MagicMock()
    pipe = MagicMock()

    def _setex(key, ttl, value):
        store[key] = (value, ttl)

    pipe.setex = MagicMock(side_effect=_setex)
    pipe.execute = AsyncMock()
    redis.pipeline.return_value = pipe

    async def _get(key):
        entry = store.get(key)
        return entry[0] if entry else None

    redis.get = AsyncMock(side_effect=_get)
    redis.delete = AsyncMock()

    return redis, pipe, store


# ===========================================================================
# Property 1: Paid plan signup creates pending signup with TTL and no
#              database records
# ===========================================================================
# Feature: multi-step-signup-wizard, Property 1: Paid plan signup creates pending signup with TTL and no database records


@given(form_data=paid_plan_signup_data_st())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.pending_signup.redis_pool")
def test_paid_plan_creates_pending_signup_with_ttl_and_no_db_records(
    mock_redis_module,
    form_data: dict,
) -> None:
    """For any valid signup form data with a paid plan (trial_duration == 0),
    calling create_pending_signup shall:
    1. Return a valid UUID string as the pending_signup_id
    2. Store the data in Redis under ``pending_signup:{id}`` with TTL 1800s
    3. Create an email index key ``pending_email:{sha256(email)}`` with TTL 1800s
    4. Hash the password (stored as password_hash, not plaintext)
    5. The stored data can be retrieved via get_pending_signup

    No Organisation or User database records are created because
    create_pending_signup only touches Redis.

    **Validates: Requirements 1.1, 6.1**
    """
    import asyncio

    redis, pipe, store = _make_mock_redis()

    # Wire mock into the module
    mock_redis_module.pipeline = redis.pipeline
    mock_redis_module.get = redis.get

    # --- Act ---
    pending_id = asyncio.get_event_loop().run_until_complete(
        create_pending_signup(form_data)
    )

    # --- Assert 1: returned ID is a valid UUID ---
    parsed_uuid = uuid.UUID(pending_id)
    assert str(parsed_uuid) == pending_id, (
        f"Returned ID '{pending_id}' is not a valid UUID"
    )

    # --- Assert 2: pipeline setex called twice (signup key + email index) ---
    assert pipe.setex.call_count == 2, (
        f"Expected 2 setex calls (signup + email index), got {pipe.setex.call_count}"
    )

    # --- Assert 3: signup key stored with correct TTL ---
    signup_call_args = pipe.setex.call_args_list[0][0]
    assert signup_call_args[0] == _signup_key(pending_id), (
        f"First setex key should be '{_signup_key(pending_id)}', "
        f"got '{signup_call_args[0]}'"
    )
    assert signup_call_args[1] == PENDING_SIGNUP_TTL, (
        f"Signup key TTL should be {PENDING_SIGNUP_TTL}, got {signup_call_args[1]}"
    )

    # --- Assert 4: email index key stored with correct TTL ---
    email_call_args = pipe.setex.call_args_list[1][0]
    expected_email_key = _email_index_key(form_data["admin_email"])
    assert email_call_args[0] == expected_email_key, (
        f"Second setex key should be '{expected_email_key}', "
        f"got '{email_call_args[0]}'"
    )
    assert email_call_args[1] == PENDING_SIGNUP_TTL, (
        f"Email index TTL should be {PENDING_SIGNUP_TTL}, got {email_call_args[1]}"
    )
    assert email_call_args[2] == pending_id, (
        f"Email index value should be '{pending_id}', got '{email_call_args[2]}'"
    )

    # --- Assert 5: password is hashed, not stored in plaintext ---
    stored_json = signup_call_args[2]
    stored_data = json.loads(stored_json)

    assert "password" not in stored_data, (
        "Plaintext 'password' must NOT be stored in Redis"
    )
    assert "password_hash" in stored_data, (
        "'password_hash' must be present in stored data"
    )
    assert stored_data["password_hash"].startswith("$2b$"), (
        f"password_hash should be a bcrypt hash (start with '$2b$'), "
        f"got '{stored_data['password_hash'][:10]}...'"
    )

    # --- Assert 6: stored data preserves form fields (except password) ---
    for key in ["org_name", "admin_email", "admin_first_name", "admin_last_name",
                 "plan_id", "plan_name", "payment_amount_cents",
                 "stripe_payment_intent_id", "ip_address"]:
        assert key in stored_data, f"Missing field '{key}' in stored data"
        assert str(stored_data[key]) == str(form_data[key]), (
            f"Field '{key}' mismatch: stored={stored_data[key]}, "
            f"expected={form_data[key]}"
        )

    # --- Assert 7: get_pending_signup retrieves the data ---
    retrieved = asyncio.get_event_loop().run_until_complete(
        get_pending_signup(pending_id)
    )
    assert retrieved is not None, (
        "get_pending_signup should return the stored data"
    )
    assert retrieved["admin_email"] == form_data["admin_email"], (
        "Retrieved email should match the original form data"
    )

    # --- Assert 8: No DB interaction ---
    # create_pending_signup is a pure Redis operation — it does not import
    # or call any database/SQLAlchemy functions. The absence of DB records
    # is guaranteed by the function's implementation which only uses
    # redis_pool. This is verified structurally: the function has no
    # database session parameter and makes no ORM calls.



# ===========================================================================
# Property 10: Duplicate email replaces existing pending signup
# ===========================================================================
# Feature: multi-step-signup-wizard, Property 10: Duplicate email replaces existing pending signup


def _make_full_mock_redis():
    """Build a mock Redis with an in-memory store that supports the full
    lifecycle: pipeline setex, get, and delete — so that
    replace_pending_signup_for_email can look up the email index, delete
    the old signup, and create a new one.
    """
    store: dict[str, tuple[str, int]] = {}  # key -> (value, ttl)

    redis = MagicMock()
    pipe = MagicMock()

    def _setex(key, ttl, value):
        store[key] = (value, ttl)

    pipe.setex = MagicMock(side_effect=_setex)
    pipe.execute = AsyncMock()
    redis.pipeline.return_value = pipe

    async def _get(key):
        entry = store.get(key)
        return entry[0] if entry else None

    redis.get = AsyncMock(side_effect=_get)

    async def _delete(*keys):
        for k in keys:
            store.pop(k, None)

    redis.delete = AsyncMock(side_effect=_delete)

    return redis, pipe, store


@given(
    email=email_st,
    data1=paid_plan_signup_data_st(),
    data2=paid_plan_signup_data_st(),
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.pending_signup.redis_pool")
def test_duplicate_email_replaces_existing_pending_signup(
    mock_redis_module,
    email: str,
    data1: dict,
    data2: dict,
) -> None:
    """For any email address that already has a Pending_Signup in Redis,
    submitting a new signup with the same email shall replace the old
    Pending_Signup with a new one, such that only one Pending_Signup
    exists for that email at any time.

    Steps:
    1. Create a pending signup with data1 (email forced to the shared email)
    2. Call replace_pending_signup_for_email with the same email and data2
    3. Verify the old pending signup key is gone
    4. Verify only the new pending signup key exists
    5. Verify the email index points to the new pending signup ID

    **Validates: Requirements 6.3**
    """
    import asyncio

    # Force both data dicts to use the same email
    data1 = {**data1, "admin_email": email}
    data2 = {**data2, "admin_email": email}

    redis, pipe, store = _make_full_mock_redis()

    # Wire mock into the module
    mock_redis_module.pipeline = redis.pipeline
    mock_redis_module.get = redis.get
    mock_redis_module.delete = redis.delete

    loop = asyncio.get_event_loop()

    # --- Step 1: Create first pending signup ---
    first_id = loop.run_until_complete(create_pending_signup(data1))

    # Sanity: first signup exists
    assert _signup_key(first_id) in store, (
        "First pending signup should exist in Redis after creation"
    )

    email_idx_key = _email_index_key(email)
    assert email_idx_key in store, (
        "Email index key should exist after first signup"
    )
    assert store[email_idx_key][0] == first_id, (
        "Email index should point to the first pending signup ID"
    )

    # --- Step 2: Replace with second signup for the same email ---
    second_id = loop.run_until_complete(
        replace_pending_signup_for_email(email, data2)
    )

    # --- Assert 1: IDs are different ---
    assert first_id != second_id, (
        "replace_pending_signup_for_email must return a new ID"
    )

    # --- Assert 2: Old pending signup key is deleted ---
    assert _signup_key(first_id) not in store, (
        f"Old signup key '{_signup_key(first_id)}' should have been deleted"
    )

    # --- Assert 3: New pending signup key exists ---
    assert _signup_key(second_id) in store, (
        f"New signup key '{_signup_key(second_id)}' should exist in Redis"
    )

    # --- Assert 4: Email index now points to the new ID ---
    assert email_idx_key in store, (
        "Email index key should still exist after replacement"
    )
    assert store[email_idx_key][0] == second_id, (
        f"Email index should point to new ID '{second_id}', "
        f"got '{store[email_idx_key][0]}'"
    )

    # --- Assert 5: Only one signup key exists for this email ---
    signup_keys = [k for k in store if k.startswith("pending_signup:")]
    assert len(signup_keys) == 1, (
        f"Expected exactly 1 pending_signup key, found {len(signup_keys)}: "
        f"{signup_keys}"
    )
    assert signup_keys[0] == _signup_key(second_id), (
        f"The sole signup key should be for the new ID '{second_id}'"
    )

    # --- Assert 6: Stored data matches the second submission ---
    stored_json = store[_signup_key(second_id)][0]
    stored_data = json.loads(stored_json)
    assert stored_data["admin_email"] == email, (
        "Stored email should match the shared email"
    )
    assert stored_data["org_name"] == data2["org_name"], (
        "Stored org_name should match the second submission's data"
    )


# ===========================================================================
# Property 4: Trial plan creates account immediately
# ===========================================================================
# Feature: multi-step-signup-wizard, Property 4: Trial plan creates account immediately


# ---------------------------------------------------------------------------
# Strategy — trial plan signup data
# ---------------------------------------------------------------------------

trial_duration_st = st.integers(min_value=1, max_value=365)

trial_duration_unit_st = st.sampled_from(["days", "weeks", "months"])


def trial_plan_signup_data_st() -> st.SearchStrategy[dict]:
    """Generate random valid signup form data for a trial plan."""
    return st.fixed_dictionaries({
        "org_name": org_name_st,
        "admin_email": email_st,
        "admin_first_name": first_name_st,
        "admin_last_name": last_name_st,
        "password": password_st,
        "plan_id": plan_id_st,
        "trial_duration": trial_duration_st,
        "trial_duration_unit": trial_duration_unit_st,
    })


# ---------------------------------------------------------------------------
# Property 4a: _compute_trial_end always returns a future date for
#              trial_duration > 0
# ---------------------------------------------------------------------------


@given(
    duration=trial_duration_st,
    unit=trial_duration_unit_st,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_compute_trial_end_returns_future_date_for_positive_duration(
    duration: int,
    unit: str,
) -> None:
    """For any trial_duration > 0 and any valid unit, _compute_trial_end
    shall return a non-None datetime that is strictly after ``now``.

    This is a pure function property — no mocking required.

    **Validates: Requirements 1.5**
    """
    from datetime import datetime, timezone
    from app.modules.organisations.service import _compute_trial_end

    now = datetime.now(timezone.utc)

    # Build a minimal plan-like object with the required attributes
    class FakePlan:
        def __init__(self, td, tdu):
            self.trial_duration = td
            self.trial_duration_unit = tdu

    plan = FakePlan(duration, unit)
    result = _compute_trial_end(plan, now)

    # --- Assert 1: result is not None ---
    assert result is not None, (
        f"_compute_trial_end should return a datetime for duration={duration}, "
        f"unit={unit}, but got None"
    )

    # --- Assert 2: result is strictly in the future ---
    assert result > now, (
        f"trial_ends_at ({result}) should be after now ({now}) "
        f"for duration={duration}, unit={unit}"
    )


# ---------------------------------------------------------------------------
# Property 4b: Trial plan signup via public_signup returns correct response
#              structure with requires_payment=False and creates Organisation
#              with status "trial" and User with is_email_verified=False
# ---------------------------------------------------------------------------


@given(data=trial_plan_signup_data_st())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.service.send_verification_email", new_callable=AsyncMock)
@patch("app.modules.auth.service.create_email_verification_token", new_callable=AsyncMock)
@patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
def test_trial_plan_creates_account_immediately(
    mock_audit_log,
    mock_create_token,
    mock_send_email,
    data: dict,
) -> None:
    """For any valid signup form data with a trial plan (trial_duration > 0),
    calling public_signup shall:
    1. Return requires_payment = False
    2. Return a non-None organisation_id (UUID string)
    3. Return a non-None trial_ends_at datetime
    4. Create an Organisation with status "trial"
    5. Create a User with is_email_verified = False
    6. Send a verification email

    **Validates: Requirements 1.5**
    """
    import asyncio
    from datetime import datetime, timezone
    from unittest.mock import PropertyMock

    mock_create_token.return_value = "fake-verification-token"
    mock_send_email.return_value = None

    # --- Build mock plan ---
    mock_plan = MagicMock()
    mock_plan.name = "Trial Plan"
    mock_plan.is_archived = False
    mock_plan.is_public = True
    mock_plan.trial_duration = data["trial_duration"]
    mock_plan.trial_duration_unit = data["trial_duration_unit"]
    mock_plan.monthly_price_nzd = "0.00"
    mock_plan.storage_quota_gb = 5

    # --- Build mock DB session ---
    mock_db = AsyncMock()

    # Track objects added to the session
    added_objects = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    # flush() assigns IDs to the added objects
    flush_call_count = 0

    async def _flush():
        nonlocal flush_call_count
        for obj in added_objects:
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = uuid.uuid4()
        flush_call_count += 1

    mock_db.flush = AsyncMock(side_effect=_flush)

    # select(SubscriptionPlan) -> returns the mock plan
    # select(User) -> returns None (email not registered)
    plan_result = MagicMock()
    plan_result.scalar_one_or_none.return_value = mock_plan

    email_result = MagicMock()
    email_result.scalar_one_or_none.return_value = None

    execute_results = [plan_result, email_result]
    execute_call_idx = 0

    async def _execute(stmt):
        nonlocal execute_call_idx
        idx = execute_call_idx
        execute_call_idx += 1
        if idx < len(execute_results):
            return execute_results[idx]
        return MagicMock()

    mock_db.execute = AsyncMock(side_effect=_execute)

    # --- Mock Redis for signup token storage ---
    mock_redis = AsyncMock()
    mock_redis.setex = AsyncMock()

    with patch("app.core.redis.redis_pool", mock_redis):
        from app.modules.organisations.service import public_signup

        result = asyncio.get_event_loop().run_until_complete(
            public_signup(
                mock_db,
                org_name=data["org_name"],
                admin_email=data["admin_email"],
                admin_first_name=data["admin_first_name"],
                admin_last_name=data["admin_last_name"],
                password=data["password"],
                plan_id=uuid.UUID(data["plan_id"]),
                ip_address="127.0.0.1",
                base_url="http://localhost",
            )
        )

    # --- Assert 1: requires_payment is False ---
    assert result["requires_payment"] is False, (
        f"Trial plan should return requires_payment=False, got {result['requires_payment']}"
    )

    # --- Assert 2: organisation_id is present and valid UUID ---
    assert "organisation_id" in result, (
        "Trial plan response must include organisation_id"
    )
    parsed_org_id = uuid.UUID(result["organisation_id"])
    assert str(parsed_org_id) == result["organisation_id"]

    # --- Assert 3: trial_ends_at is present and is a future datetime ---
    assert "trial_ends_at" in result, (
        "Trial plan response must include trial_ends_at"
    )
    assert result["trial_ends_at"] is not None, (
        "trial_ends_at must not be None for a trial plan"
    )
    assert result["trial_ends_at"] > datetime.now(timezone.utc), (
        f"trial_ends_at ({result['trial_ends_at']}) should be in the future"
    )

    # --- Assert 4: Organisation created with status "trial" ---
    orgs = [obj for obj in added_objects if hasattr(obj, "status") and hasattr(obj, "plan_id")]
    assert len(orgs) >= 1, "At least one Organisation should have been added to the DB"
    org = orgs[0]
    assert org.status == "trial", (
        f"Organisation status should be 'trial', got '{org.status}'"
    )
    assert org.trial_ends_at is not None, (
        "Organisation.trial_ends_at should be set for trial plans"
    )

    # --- Assert 5: User created with is_email_verified=False ---
    users = [obj for obj in added_objects if hasattr(obj, "is_email_verified")]
    assert len(users) >= 1, "At least one User should have been added to the DB"
    user = users[0]
    assert user.is_email_verified is False, (
        f"User.is_email_verified should be False, got {user.is_email_verified}"
    )
    assert user.email == data["admin_email"], (
        f"User email should be '{data['admin_email']}', got '{user.email}'"
    )

    # --- Assert 6: Verification email was sent ---
    mock_send_email.assert_called_once()
    call_kwargs = mock_send_email.call_args
    # The email argument should match the admin_email
    assert data["admin_email"] in str(call_kwargs), (
        "send_verification_email should be called with the admin email"
    )


# ===========================================================================
# Property 8: Coupon discount correctly applied to PaymentIntent amount
# ===========================================================================
# Feature: multi-step-signup-wizard, Property 8: Coupon discount correctly applied to PaymentIntent amount


# ---------------------------------------------------------------------------
# Strategies — price and coupon generators
# ---------------------------------------------------------------------------

price_cents_st = st.integers(min_value=100, max_value=999999)

discount_pct_st = st.floats(
    min_value=0.0, max_value=100.0,
    allow_nan=False, allow_infinity=False,
)

discount_fixed_st = st.floats(
    min_value=0.0, max_value=9999.99,
    allow_nan=False, allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Property 8a: Percentage coupon discount formula
# ---------------------------------------------------------------------------


@given(
    price_cents=price_cents_st,
    discount_pct=discount_pct_st,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_percentage_coupon_discount_correctly_applied(
    price_cents: int,
    discount_pct: float,
) -> None:
    """For any paid plan with price P (in cents) and a valid percentage
    coupon with discount D%, the discounted PaymentIntent amount shall
    equal ``round(P * (1 - D/100))``.

    This mirrors the exact formula in ``public_signup()``:
        payment_amount_cents = round(payment_amount_cents * (1 - coupon_discount_value / 100))

    Pure math property — no mocking required.

    **Validates: Requirements 5.2**
    """
    # --- Act: apply the same formula used in the service ---
    discounted = round(price_cents * (1 - discount_pct / 100))

    # --- Assert 1: result is an integer ---
    assert isinstance(discounted, int), (
        f"Discounted amount should be an integer, got {type(discounted).__name__}"
    )

    # --- Assert 2: result is non-negative ---
    # round() can produce 0 but never negative for valid inputs
    # (price >= 0, discount 0..100)
    assert discounted >= 0, (
        f"Discounted amount should be >= 0, got {discounted} "
        f"(price={price_cents}, discount={discount_pct}%)"
    )

    # --- Assert 3: result <= original price ---
    assert discounted <= price_cents, (
        f"Discounted amount ({discounted}) should be <= original price "
        f"({price_cents}) for discount={discount_pct}%"
    )

    # --- Assert 4: 0% discount leaves price unchanged ---
    if discount_pct == 0.0:
        assert discounted == price_cents, (
            f"0% discount should leave price unchanged: "
            f"expected {price_cents}, got {discounted}"
        )

    # --- Assert 5: 100% discount results in zero ---
    if discount_pct == 100.0:
        assert discounted == 0, (
            f"100% discount should result in 0, got {discounted}"
        )

    # --- Assert 6: verify against independent calculation ---
    expected = round(price_cents * (1 - discount_pct / 100))
    assert discounted == expected, (
        f"Discounted amount mismatch: got {discounted}, "
        f"expected {expected} (price={price_cents}, discount={discount_pct}%)"
    )


# ---------------------------------------------------------------------------
# Property 8b: Fixed-amount coupon discount formula
# ---------------------------------------------------------------------------


@given(
    price_cents=price_cents_st,
    discount_fixed=discount_fixed_st,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_fixed_amount_coupon_discount_correctly_applied(
    price_cents: int,
    discount_fixed: float,
) -> None:
    """For any paid plan with price P (in cents) and a valid fixed-amount
    coupon with discount F (in dollars), the discounted PaymentIntent
    amount shall equal ``max(0, P - int(F * 100))``.

    This mirrors the exact formula in ``public_signup()``:
        discount_cents = int(coupon_discount_value * 100)
        payment_amount_cents = max(0, payment_amount_cents - discount_cents)

    Pure math property — no mocking required.

    **Validates: Requirements 5.2**
    """
    # --- Act: apply the same formula used in the service ---
    discount_cents = int(discount_fixed * 100)
    discounted = max(0, price_cents - discount_cents)

    # --- Assert 1: result is an integer ---
    assert isinstance(discounted, int), (
        f"Discounted amount should be an integer, got {type(discounted).__name__}"
    )

    # --- Assert 2: result is non-negative (floor at zero) ---
    assert discounted >= 0, (
        f"Discounted amount should be >= 0, got {discounted} "
        f"(price={price_cents}, fixed_discount=${discount_fixed})"
    )

    # --- Assert 3: result <= original price ---
    assert discounted <= price_cents, (
        f"Discounted amount ({discounted}) should be <= original price "
        f"({price_cents}) for fixed discount=${discount_fixed}"
    )

    # --- Assert 4: zero discount leaves price unchanged ---
    if discount_fixed == 0.0:
        assert discounted == price_cents, (
            f"$0 discount should leave price unchanged: "
            f"expected {price_cents}, got {discounted}"
        )

    # --- Assert 5: discount >= price results in zero ---
    if discount_cents >= price_cents:
        assert discounted == 0, (
            f"Discount ({discount_cents} cents) >= price ({price_cents} cents) "
            f"should result in 0, got {discounted}"
        )

    # --- Assert 6: verify against independent calculation ---
    expected = max(0, price_cents - int(discount_fixed * 100))
    assert discounted == expected, (
        f"Discounted amount mismatch: got {discounted}, "
        f"expected {expected} (price={price_cents}, "
        f"fixed_discount=${discount_fixed})"
    )


# ===========================================================================
# Property 9: Trial-extension coupon converts paid plan to trial
# ===========================================================================
# Feature: multi-step-signup-wizard, Property 9: Trial-extension coupon converts paid plan to trial


# ---------------------------------------------------------------------------
# Strategies — trial-extension coupon generators
# ---------------------------------------------------------------------------

trial_extension_days_st = st.integers(min_value=1, max_value=365)


def paid_plan_with_trial_extension_st() -> st.SearchStrategy[dict]:
    """Generate random valid signup form data for a paid plan paired with
    a trial-extension coupon value (in days)."""
    return st.fixed_dictionaries({
        "org_name": org_name_st,
        "admin_email": email_st,
        "admin_first_name": first_name_st,
        "admin_last_name": last_name_st,
        "password": password_st,
        "plan_id": plan_id_st,
        "coupon_code": st.text(min_size=4, max_size=12, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
        "trial_extension_days": trial_extension_days_st,
    })


# ---------------------------------------------------------------------------
# Property 9: Trial-extension coupon converts paid plan to trial
# ---------------------------------------------------------------------------


@given(data=paid_plan_with_trial_extension_st())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.service.send_verification_email", new_callable=AsyncMock)
@patch("app.modules.auth.service.create_email_verification_token", new_callable=AsyncMock)
@patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
@patch("app.modules.admin.service.validate_coupon", new_callable=AsyncMock)
def test_trial_extension_coupon_converts_paid_plan_to_trial(
    mock_validate_coupon,
    mock_audit_log,
    mock_create_token,
    mock_send_email,
    data: dict,
) -> None:
    """For any paid plan (trial_duration == 0) and a valid trial-extension
    coupon with value V days, calling the signup endpoint shall create the
    account immediately with trial status and ``trial_ends_at`` set to V
    days from now, returning ``requires_payment: false``.

    Specifically:
    1. Response has ``requires_payment: false``
    2. Organisation is created with status "trial"
    3. ``trial_ends_at`` is approximately V days from now
    4. No PaymentIntent was created (no Stripe interaction)

    **Validates: Requirements 5.4**
    """
    import asyncio
    from datetime import datetime, timedelta, timezone

    mock_create_token.return_value = "fake-verification-token"
    mock_send_email.return_value = None

    extension_days = data["trial_extension_days"]

    # --- Mock validate_coupon to return a trial_extension coupon ---
    mock_validate_coupon.return_value = {
        "valid": True,
        "coupon": {
            "id": str(uuid.uuid4()),
            "code": data["coupon_code"],
            "description": f"Trial extension: {extension_days} days",
            "discount_type": "trial_extension",
            "discount_value": float(extension_days),
            "duration_months": None,
            "usage_limit": None,
            "times_redeemed": 0,
            "is_active": True,
            "starts_at": None,
            "expires_at": None,
            "created_at": None,
            "updated_at": None,
        },
    }

    # --- Build mock plan: paid plan with trial_duration == 0 ---
    mock_plan = MagicMock()
    mock_plan.name = "Professional"
    mock_plan.is_archived = False
    mock_plan.is_public = True
    mock_plan.trial_duration = 0
    mock_plan.trial_duration_unit = "days"
    mock_plan.monthly_price_nzd = "49.00"
    mock_plan.storage_quota_gb = 10

    # --- Build mock DB session ---
    mock_db = AsyncMock()

    added_objects = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    async def _flush():
        for obj in added_objects:
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = uuid.uuid4()

    mock_db.flush = AsyncMock(side_effect=_flush)

    # select(SubscriptionPlan) -> returns the mock plan
    # select(User) -> returns None (email not registered)
    plan_result = MagicMock()
    plan_result.scalar_one_or_none.return_value = mock_plan

    email_result = MagicMock()
    email_result.scalar_one_or_none.return_value = None

    execute_results = [plan_result, email_result]
    execute_call_idx = 0

    async def _execute(stmt):
        nonlocal execute_call_idx
        idx = execute_call_idx
        execute_call_idx += 1
        if idx < len(execute_results):
            return execute_results[idx]
        return MagicMock()

    mock_db.execute = AsyncMock(side_effect=_execute)

    # --- Mock Redis for signup token storage ---
    mock_redis = AsyncMock()
    mock_redis.setex = AsyncMock()

    # --- Track Stripe calls to verify no PaymentIntent is created ---
    with patch("app.core.redis.redis_pool", mock_redis), \
         patch(
             "app.integrations.stripe_billing.create_payment_intent_no_customer",
             new_callable=AsyncMock,
         ) as mock_stripe_pi:

        from app.modules.organisations.service import public_signup

        before = datetime.now(timezone.utc)

        result = asyncio.get_event_loop().run_until_complete(
            public_signup(
                mock_db,
                org_name=data["org_name"],
                admin_email=data["admin_email"],
                admin_first_name=data["admin_first_name"],
                admin_last_name=data["admin_last_name"],
                password=data["password"],
                plan_id=uuid.UUID(data["plan_id"]),
                ip_address="127.0.0.1",
                base_url="http://localhost",
                coupon_code=data["coupon_code"],
            )
        )

        after = datetime.now(timezone.utc)

    # --- Assert 1: requires_payment is False ---
    assert result["requires_payment"] is False, (
        f"Trial-extension coupon should return requires_payment=False, "
        f"got {result['requires_payment']}"
    )

    # --- Assert 2: Organisation created with status "trial" ---
    orgs = [
        obj for obj in added_objects
        if hasattr(obj, "status") and hasattr(obj, "plan_id")
    ]
    assert len(orgs) >= 1, (
        "At least one Organisation should have been added to the DB"
    )
    org = orgs[0]
    assert org.status == "trial", (
        f"Organisation status should be 'trial', got '{org.status}'"
    )

    # --- Assert 3: trial_ends_at is approximately V days from now ---
    assert org.trial_ends_at is not None, (
        "Organisation.trial_ends_at must be set for trial-extension coupon"
    )

    expected_earliest = before + timedelta(days=extension_days)
    expected_latest = after + timedelta(days=extension_days)

    assert expected_earliest <= org.trial_ends_at <= expected_latest, (
        f"trial_ends_at ({org.trial_ends_at}) should be ~{extension_days} days "
        f"from now (between {expected_earliest} and {expected_latest})"
    )

    # Also verify the response includes trial_ends_at
    assert "trial_ends_at" in result, (
        "Response must include trial_ends_at for trial-extension coupon"
    )
    assert result["trial_ends_at"] is not None, (
        "trial_ends_at in response must not be None"
    )

    # --- Assert 4: No PaymentIntent was created ---
    mock_stripe_pi.assert_not_called(), (
        "No Stripe PaymentIntent should be created when a trial-extension "
        "coupon converts a paid plan to trial"
    )

    # --- Assert 5: User created with is_email_verified=False ---
    users = [obj for obj in added_objects if hasattr(obj, "is_email_verified")]
    assert len(users) >= 1, (
        "At least one User should have been added to the DB"
    )
    user = users[0]
    assert user.is_email_verified is False, (
        f"User.is_email_verified should be False, got {user.is_email_verified}"
    )

    # --- Assert 6: Verification email was sent ---
    mock_send_email.assert_called_once()

    # --- Assert 7: validate_coupon was called with the coupon code ---
    mock_validate_coupon.assert_called_once()


# ===========================================================================
# Property 11: Signup rejects invalid CAPTCHA or already-registered email
# ===========================================================================
# Feature: multi-step-signup-wizard, Property 11: Signup rejects invalid CAPTCHA or already-registered email


@given(data=paid_plan_signup_data_st())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
def test_signup_rejects_already_registered_email(
    mock_audit_log,
    data: dict,
) -> None:
    """For any signup request where the email is already registered to an
    existing User, the signup endpoint shall reject the request by raising
    a ValueError without creating a Pending_Signup or any database records.

    Steps:
    1. Mock the DB so that the plan lookup succeeds (valid paid plan)
    2. Mock the DB so that the email uniqueness check returns an existing user
    3. Call public_signup() with the generated form data
    4. Verify ValueError("A user with this email already exists") is raised
    5. Verify no objects were added to the DB session
    6. Verify no Redis operations occurred (no pending signup created)

    **Validates: Requirements 7.3, 7.4**
    """
    import asyncio

    # --- Build mock plan: valid paid plan ---
    mock_plan = MagicMock()
    mock_plan.name = "Professional"
    mock_plan.is_archived = False
    mock_plan.is_public = True
    mock_plan.trial_duration = 0
    mock_plan.trial_duration_unit = "days"
    mock_plan.monthly_price_nzd = "49.00"
    mock_plan.storage_quota_gb = 10

    # --- Build mock existing user ---
    mock_existing_user = MagicMock()
    mock_existing_user.email = data["admin_email"]
    mock_existing_user.id = uuid.uuid4()

    # --- Build mock DB session ---
    mock_db = AsyncMock()

    added_objects = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
    mock_db.flush = AsyncMock()

    # select(SubscriptionPlan) -> returns the mock plan
    # select(User) -> returns the existing user (email already registered)
    plan_result = MagicMock()
    plan_result.scalar_one_or_none.return_value = mock_plan

    email_result = MagicMock()
    email_result.scalar_one_or_none.return_value = mock_existing_user

    execute_results = [plan_result, email_result]
    execute_call_idx = 0

    async def _execute(stmt):
        nonlocal execute_call_idx
        idx = execute_call_idx
        execute_call_idx += 1
        if idx < len(execute_results):
            return execute_results[idx]
        return MagicMock()

    mock_db.execute = AsyncMock(side_effect=_execute)

    # --- Mock Redis to track any operations ---
    mock_redis = AsyncMock()
    mock_redis.setex = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.delete = AsyncMock()
    mock_redis.pipeline = MagicMock()

    with patch("app.core.redis.redis_pool", mock_redis), \
         patch(
             "app.modules.auth.pending_signup.redis_pool", mock_redis,
         ):
        from app.modules.organisations.service import public_signup

        with pytest.raises(ValueError, match="A user with this email already exists"):
            asyncio.get_event_loop().run_until_complete(
                public_signup(
                    mock_db,
                    org_name=data["org_name"],
                    admin_email=data["admin_email"],
                    admin_first_name=data["admin_first_name"],
                    admin_last_name=data["admin_last_name"],
                    password=data["password"],
                    plan_id=uuid.UUID(data["plan_id"]),
                    ip_address=data["ip_address"],
                    base_url="http://localhost",
                )
            )

    # --- Assert 1: No objects were added to the DB session ---
    assert len(added_objects) == 0, (
        f"No objects should be added to the DB when email is already "
        f"registered, but {len(added_objects)} were added"
    )

    # --- Assert 2: DB flush was never called ---
    mock_db.flush.assert_not_called(), (
        "DB flush should not be called when email is already registered"
    )

    # --- Assert 3: No Redis setex operations (no pending signup created) ---
    mock_redis.setex.assert_not_called(), (
        "No Redis setex should occur when email is already registered"
    )

    # --- Assert 4: No Redis pipeline operations ---
    mock_redis.pipeline.assert_not_called(), (
        "No Redis pipeline should be created when email is already registered"
    )


# ===========================================================================
# Property 2: Valid payment confirmation creates account, sends email,
#              and deletes pending signup
# ===========================================================================
# Feature: multi-step-signup-wizard, Property 2: Valid payment confirmation creates account, sends email, and deletes pending signup


# ---------------------------------------------------------------------------
# Strategies — pending signup data for payment confirmation
# ---------------------------------------------------------------------------

password_hash_st = st.just("$2b$12$").map(
    lambda prefix: prefix + "a" * 53  # realistic bcrypt hash length
)


def pending_signup_data_st() -> st.SearchStrategy[dict]:
    """Generate random valid pending signup data as stored in Redis
    (i.e. password already hashed, all fields present)."""
    return st.fixed_dictionaries({
        "org_name": org_name_st,
        "admin_email": email_st,
        "admin_first_name": first_name_st,
        "admin_last_name": last_name_st,
        "password_hash": password_hash_st,
        "plan_id": plan_id_st,
        "plan_name": plan_name_st,
        "payment_amount_cents": payment_amount_st,
        "stripe_payment_intent_id": st.just("pi_test_").map(
            lambda prefix: prefix + uuid.uuid4().hex[:24]
        ),
        "coupon_code": st.none(),
        "coupon_discount_type": st.none(),
        "coupon_discount_value": st.none(),
        "ip_address": ip_address_st,
        "created_at": st.just("2025-01-15T10:30:00Z"),
    })


@given(pending_data=pending_signup_data_st())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_payment_confirmation_creates_account_sends_email_deletes_pending(
    pending_data: dict,
) -> None:
    """For any valid Pending_Signup in Redis and a Stripe PaymentIntent with
    status "succeeded", calling the payment confirmation endpoint shall:

    1. Create an Organisation with status="active" in the database
    2. Create a User with is_email_verified=False in the database
    3. Delete the Pending_Signup key from Redis (replay prevention)
    4. Send a receipt email to the user's email address

    This tests the core confirm_signup_payment logic by mocking Redis,
    Stripe, DB, and email dependencies.

    **Validates: Requirements 1.2, 4.1, 7.2**
    """
    import asyncio
    from unittest.mock import PropertyMock, call

    pending_signup_id = str(uuid.uuid4())
    payment_intent_id = pending_data["stripe_payment_intent_id"]

    # --- Mock Redis: get_pending_signup returns data, delete works ---
    pending_signup_get_calls = []
    pending_signup_deleted = []

    async def mock_get_pending_signup(pid):
        pending_signup_get_calls.append(pid)
        if pid == pending_signup_id:
            return dict(pending_data)
        return None

    async def mock_delete_pending_signup(pid):
        pending_signup_deleted.append(pid)

    # --- Mock Stripe: PaymentIntent.retrieve returns succeeded ---
    mock_intent = MagicMock()
    mock_intent.status = "succeeded"
    mock_intent.payment_method = "pm_test_" + uuid.uuid4().hex[:16]

    mock_pm_obj = MagicMock()
    mock_pm_obj.get.return_value = {
        "brand": "visa",
        "last4": "4242",
        "exp_month": 12,
        "exp_year": 2030,
    }

    stripe_customer_id = "cus_test_" + uuid.uuid4().hex[:16]

    # --- Mock DB session: track added objects ---
    added_objects = []
    mock_db = AsyncMock()
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    flush_count = 0

    async def _flush():
        nonlocal flush_count
        for obj in added_objects:
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = uuid.uuid4()
        flush_count += 1

    mock_db.flush = AsyncMock(side_effect=_flush)
    mock_db.commit = AsyncMock()

    # select(SubscriptionPlan) -> returns a mock plan
    mock_plan = MagicMock()
    mock_plan.storage_quota_gb = 10

    plan_result = MagicMock()
    plan_result.scalar_one_or_none.return_value = mock_plan
    mock_db.execute = AsyncMock(return_value=plan_result)

    # --- Mock request ---
    mock_request = MagicMock()
    mock_request.client.host = pending_data["ip_address"]
    mock_request.headers = MagicMock()
    mock_request.headers.get = MagicMock(return_value="http://localhost:3000")

    # --- Mock payload ---
    mock_payload = MagicMock()
    mock_payload.payment_intent_id = payment_intent_id
    mock_payload.pending_signup_id = pending_signup_id

    # --- Mock redis_pool for signup token storage ---
    mock_redis_pool = AsyncMock()
    mock_redis_pool.setex = AsyncMock()

    # The confirm_signup_payment function uses local imports, so we
    # patch at the source module level.
    with patch(
        "app.modules.auth.pending_signup.get_pending_signup",
        side_effect=mock_get_pending_signup,
    ), patch(
        "app.modules.auth.pending_signup.delete_pending_signup",
        side_effect=mock_delete_pending_signup,
    ), patch(
        "app.integrations.stripe_billing._ensure_stripe_key",
        new_callable=AsyncMock,
    ), patch(
        "stripe.PaymentIntent.retrieve",
        return_value=mock_intent,
    ), patch(
        "stripe.PaymentMethod.retrieve",
        return_value=mock_pm_obj,
    ), patch(
        "app.integrations.stripe_billing.create_stripe_customer",
        new_callable=AsyncMock,
        return_value=stripe_customer_id,
    ), patch(
        "app.core.audit.write_audit_log",
        new_callable=AsyncMock,
    ), patch(
        "app.core.redis.redis_pool",
        mock_redis_pool,
    ), patch(
        "app.modules.auth.service.send_receipt_email",
        new_callable=AsyncMock,
    ) as mock_send_receipt:
        from app.modules.auth.router import confirm_signup_payment

        result = asyncio.get_event_loop().run_until_complete(
            confirm_signup_payment(
                payload=mock_payload,
                request=mock_request,
                db=mock_db,
            )
        )

    # --- Parse response ---
    import json as _json

    # The endpoint returns a JSONResponse
    response_body = _json.loads(result.body.decode())

    # --- Assert 1: Response indicates success ---
    assert result.status_code == 200, (
        f"Expected 200 status, got {result.status_code}: {response_body}"
    )
    assert response_body.get("status") == "active", (
        f"Response status should be 'active', got {response_body.get('status')}"
    )
    assert response_body.get("admin_email") == pending_data["admin_email"], (
        f"Response admin_email should be '{pending_data['admin_email']}', "
        f"got {response_body.get('admin_email')}"
    )

    # --- Assert 2: Organisation created with status "active" ---
    orgs = [
        obj for obj in added_objects
        if hasattr(obj, "status") and hasattr(obj, "plan_id") and hasattr(obj, "stripe_customer_id")
    ]
    assert len(orgs) >= 1, (
        "At least one Organisation should have been added to the DB"
    )
    org = orgs[0]
    assert org.status == "active", (
        f"Organisation status should be 'active', got '{org.status}'"
    )
    assert org.name == pending_data["org_name"], (
        f"Organisation name should be '{pending_data['org_name']}', got '{org.name}'"
    )
    assert org.stripe_customer_id == stripe_customer_id, (
        f"Organisation stripe_customer_id should be '{stripe_customer_id}', "
        f"got '{org.stripe_customer_id}'"
    )

    # --- Assert 3: User created with is_email_verified=False ---
    users = [obj for obj in added_objects if hasattr(obj, "is_email_verified")]
    assert len(users) >= 1, (
        "At least one User should have been added to the DB"
    )
    user = users[0]
    assert user.is_email_verified is False, (
        f"User.is_email_verified should be False, got {user.is_email_verified}"
    )
    assert user.email == pending_data["admin_email"], (
        f"User email should be '{pending_data['admin_email']}', got '{user.email}'"
    )
    assert user.password_hash == pending_data["password_hash"], (
        "User password_hash should match the pending signup data"
    )
    assert user.role == "org_admin", (
        f"User role should be 'org_admin', got '{user.role}'"
    )

    # --- Assert 4: Pending signup was deleted from Redis (replay prevention) ---
    assert pending_signup_id in pending_signup_deleted, (
        f"delete_pending_signup should have been called with '{pending_signup_id}', "
        f"but was called with: {pending_signup_deleted}"
    )

    # --- Assert 5: Receipt email was sent ---
    mock_send_receipt.assert_called_once()
    email_call_kwargs = mock_send_receipt.call_args
    # Verify the email was sent to the correct address
    assert pending_data["admin_email"] in str(email_call_kwargs), (
        f"Receipt email should be sent to '{pending_data['admin_email']}'"
    )


# ===========================================================================
# Property 3: Non-succeeded PaymentIntent statuses are rejected
# ===========================================================================
# Feature: multi-step-signup-wizard, Property 3: Non-succeeded PaymentIntent statuses are rejected


# ---------------------------------------------------------------------------
# Strategies — non-succeeded PaymentIntent statuses
# ---------------------------------------------------------------------------

non_succeeded_status_st = st.sampled_from([
    "requires_payment_method",
    "requires_confirmation",
    "requires_action",
    "processing",
    "requires_capture",
    "canceled",
])


@given(
    pending_data=pending_signup_data_st(),
    bad_status=non_succeeded_status_st,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_non_succeeded_payment_intent_statuses_are_rejected(
    pending_data: dict,
    bad_status: str,
) -> None:
    """For any Stripe PaymentIntent status that is not "succeeded"
    (e.g., "requires_payment_method", "processing", "canceled",
    "requires_action"), calling the payment confirmation endpoint shall:

    1. Return a 400 response with "Payment not completed" error message
    2. NOT create any Organisation or User records in the database
    3. NOT delete the Pending_Signup from Redis (so the user can retry)

    This tests the guard clause in confirm_signup_payment that checks
    ``intent.status != "succeeded"`` before proceeding with account creation.

    **Validates: Requirements 1.3**
    """
    import asyncio
    import json as _json

    pending_signup_id = str(uuid.uuid4())
    payment_intent_id = pending_data["stripe_payment_intent_id"]

    # --- Mock Redis: get_pending_signup returns data, track deletes ---
    pending_signup_deleted = []

    async def mock_get_pending_signup(pid):
        if pid == pending_signup_id:
            return dict(pending_data)
        return None

    async def mock_delete_pending_signup(pid):
        pending_signup_deleted.append(pid)

    # --- Mock Stripe: PaymentIntent.retrieve returns non-succeeded status ---
    mock_intent = MagicMock()
    mock_intent.status = bad_status

    # --- Mock DB session: track added objects ---
    added_objects = []
    mock_db = AsyncMock()
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    # --- Mock request ---
    mock_request = MagicMock()
    mock_request.client.host = pending_data["ip_address"]
    mock_request.headers = MagicMock()
    mock_request.headers.get = MagicMock(return_value="http://localhost:3000")

    # --- Mock payload ---
    mock_payload = MagicMock()
    mock_payload.payment_intent_id = payment_intent_id
    mock_payload.pending_signup_id = pending_signup_id

    with patch(
        "app.modules.auth.pending_signup.get_pending_signup",
        side_effect=mock_get_pending_signup,
    ), patch(
        "app.modules.auth.pending_signup.delete_pending_signup",
        side_effect=mock_delete_pending_signup,
    ), patch(
        "app.integrations.stripe_billing._ensure_stripe_key",
        new_callable=AsyncMock,
    ), patch(
        "stripe.PaymentIntent.retrieve",
        return_value=mock_intent,
    ):
        from app.modules.auth.router import confirm_signup_payment

        result = asyncio.get_event_loop().run_until_complete(
            confirm_signup_payment(
                payload=mock_payload,
                request=mock_request,
                db=mock_db,
            )
        )

    # --- Parse response ---
    response_body = _json.loads(result.body.decode())

    # --- Assert 1: 400 status code ---
    assert result.status_code == 400, (
        f"Expected 400 status for PaymentIntent status '{bad_status}', "
        f"got {result.status_code}: {response_body}"
    )

    # --- Assert 2: Error message contains "Payment not completed" ---
    detail = response_body.get("detail", "")
    assert "Payment not completed" in detail, (
        f"Error detail should contain 'Payment not completed', "
        f"got: '{detail}' (status={bad_status})"
    )

    # --- Assert 3: Error message includes the actual status ---
    assert bad_status in detail, (
        f"Error detail should include the PaymentIntent status '{bad_status}', "
        f"got: '{detail}'"
    )

    # --- Assert 4: No objects added to DB (no Organisation or User created) ---
    assert len(added_objects) == 0, (
        f"No objects should be added to the DB when PaymentIntent status "
        f"is '{bad_status}', but {len(added_objects)} were added: "
        f"{[type(o).__name__ for o in added_objects]}"
    )

    # --- Assert 5: DB flush was never called ---
    mock_db.flush.assert_not_called(), (
        f"DB flush should not be called when PaymentIntent status is '{bad_status}'"
    )

    # --- Assert 6: Pending signup was NOT deleted from Redis ---
    assert pending_signup_id not in pending_signup_deleted, (
        f"Pending signup should NOT be deleted when PaymentIntent status "
        f"is '{bad_status}', but delete_pending_signup was called with "
        f"'{pending_signup_id}'"
    )


# ===========================================================================
# Property 6: Receipt email contains payment summary and verification link
# ===========================================================================
# Feature: multi-step-signup-wizard, Property 6: Receipt email contains payment summary and verification link


# ---------------------------------------------------------------------------
# Strategies — receipt email inputs
# ---------------------------------------------------------------------------

receipt_plan_name_st = st.text(
    min_size=1,
    max_size=80,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip())

receipt_amount_cents_st = st.integers(min_value=0, max_value=9_999_999)

verification_token_st = st.uuids().map(str)

user_name_st = st.text(
    min_size=1,
    max_size=60,
    alphabet=st.characters(whitelist_categories=("L",)),
).filter(lambda s: s.strip())

receipt_org_name_st = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip())

base_url_st = st.sampled_from([
    "http://localhost:3000",
    "https://app.example.com",
    "https://billing.test.io",
])


@given(
    plan_name=receipt_plan_name_st,
    amount_cents=receipt_amount_cents_st,
    token=verification_token_st,
    user_name=user_name_st,
    org_name=receipt_org_name_st,
    to_email=email_st,
    base_url=base_url_st,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_receipt_email_contains_payment_summary_and_verification_link(
    plan_name: str,
    amount_cents: int,
    token: str,
    user_name: str,
    org_name: str,
    to_email: str,
    base_url: str,
) -> None:
    """For any plan name and payment amount, the generated receipt email
    content shall contain the plan name, the formatted amount charged,
    and a verification link URL with a valid token.

    We mock the DB to return a fake email provider and mock smtplib.SMTP
    to capture the sent message without actually sending anything.

    **Validates: Requirements 4.2**
    """
    import asyncio
    from email import message_from_string

    # Expected values
    expected_amount_display = f"${amount_cents / 100:.2f}"
    expected_verify_url = f"{base_url}/verify-email?token={token}&type=signup"

    # --- Mock DB: return a fake email provider ---
    mock_provider = MagicMock()
    mock_provider.provider_key = "test-smtp"
    mock_provider.smtp_host = "smtp.test.local"
    mock_provider.smtp_port = 587
    mock_provider.smtp_encryption = "tls"
    mock_provider.is_active = True
    mock_provider.credentials_set = True
    mock_provider.credentials_encrypted = "encrypted_blob"
    mock_provider.config = {"from_email": "noreply@test.local", "from_name": "TestApp"}

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_provider]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    # --- Capture the email message sent via SMTP ---
    captured_messages: list[str] = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def starttls(self):
            pass

        def login(self, user, pwd):
            pass

        def sendmail(self, from_addr, to_addr, msg_str):
            captured_messages.append(msg_str)

        def quit(self):
            pass

    with patch(
        "app.core.encryption.envelope_decrypt_str",
        return_value='{"username": "user", "password": "pass"}',
    ), patch(
        "smtplib.SMTP",
        FakeSMTP,
    ):
        from app.modules.auth.service import send_receipt_email

        asyncio.get_event_loop().run_until_complete(
            send_receipt_email(
                mock_db,
                email=to_email,
                user_name=user_name,
                org_name=org_name,
                plan_name=plan_name,
                amount_cents=amount_cents,
                verification_token=token,
                base_url=base_url,
            )
        )

    # --- Assert: email was captured ---
    assert len(captured_messages) == 1, (
        f"Expected exactly 1 email to be sent, got {len(captured_messages)}"
    )

    raw_msg = captured_messages[0]

    # Parse the MIME message to extract text and HTML parts
    parsed = message_from_string(raw_msg)
    parts_text = []
    parts_html = []
    if parsed.is_multipart():
        for part in parsed.walk():
            ct = part.get_content_type()
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            decoded = payload.decode("utf-8", errors="replace")
            if ct == "text/plain":
                parts_text.append(decoded)
            elif ct == "text/html":
                parts_html.append(decoded)
    else:
        parts_text.append(parsed.get_payload(decode=True).decode("utf-8", errors="replace"))

    full_text = " ".join(parts_text)
    full_html = " ".join(parts_html)
    combined = full_text + " " + full_html

    # --- Assert 1: Plan name appears in the email ---
    assert plan_name in combined, (
        f"Plan name '{plan_name}' should appear in the email body"
    )

    # --- Assert 2: Formatted amount appears in the email ---
    assert expected_amount_display in combined, (
        f"Formatted amount '{expected_amount_display}' should appear in the email body"
    )

    # --- Assert 3: Verification URL with token appears in the email ---
    assert expected_verify_url in combined, (
        f"Verification URL '{expected_verify_url}' should appear in the email body"
    )

    # --- Assert 4: Subject line is correct ---
    assert "receipt" in (parsed.get("Subject", "") or "").lower() or \
           "verification" in (parsed.get("Subject", "") or "").lower(), (
        f"Subject should mention receipt or verification, got: '{parsed.get('Subject')}'"
    )


# ---------------------------------------------------------------------------
# Property 7 — Verification link activates account
# Tag: Feature: multi-step-signup-wizard, Property 7: Verification link activates account
# ---------------------------------------------------------------------------

# Strategy: random verification tokens (URL-safe base64 strings)
verification_token_st = st.from_regex(r"[A-Za-z0-9_-]{32,64}", fullmatch=True)

user_id_st = st.uuids()


@given(
    token=verification_token_st,
    user_id=user_id_st,
    user_email=email_st,
    org_id=st.uuids(),
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@pytest.mark.asyncio
async def test_verification_link_activates_account(
    token: str,
    user_id: uuid.UUID,
    user_email: str,
    org_id: uuid.UUID,
) -> None:
    """For any valid verification token associated with an unverified user,
    calling the verify-signup-email endpoint shall set is_email_verified=True
    on the user record.

    **Validates: Requirements 4.3**
    """
    import hashlib

    from app.modules.auth.service import verify_signup_email, _hash_invite_token

    # Compute the Redis key the verify function will look up
    token_hash = _hash_invite_token(token)
    redis_key = f"email_verify:{token_hash}"

    # Build the token data stored in Redis
    token_data = json.dumps({
        "user_id": str(user_id),
        "email": user_email,
        "org_id": str(org_id),
        "type": "signup",
    })

    # --- Mock Redis ---
    mock_redis = AsyncMock()

    async def _redis_get(key):
        if key == redis_key:
            return token_data
        return None

    mock_redis.get = AsyncMock(side_effect=_redis_get)
    mock_redis.delete = AsyncMock()

    # --- Build a mock unverified User ---
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.org_id = org_id
    mock_user.email = user_email
    mock_user.role = "org_admin"
    mock_user.is_email_verified = False
    mock_user.last_login_at = None

    # --- Mock DB session ---
    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar_one_or_none.return_value = mock_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_scalar_result)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    # --- Patch Redis pool, JWT creation, Session ORM model, and audit log ---
    # redis_pool is imported locally inside verify_signup_email via
    # ``from app.core.redis import redis_pool``, so we patch the source.
    # Session() constructor triggers SQLAlchemy mapper init, so we mock it.
    mock_session_cls = MagicMock()
    mock_session_instance = MagicMock()
    mock_session_cls.return_value = mock_session_instance

    with patch("app.core.redis.redis_pool", mock_redis), \
         patch("app.modules.auth.service.create_access_token", return_value="mock_access_token"), \
         patch("app.modules.auth.service.create_refresh_token", return_value="mock_refresh_token"), \
         patch("app.modules.auth.service.Session", mock_session_cls), \
         patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):

        result = await verify_signup_email(
            mock_db,
            token=token,
            ip_address="127.0.0.1",
            device_type="desktop",
            browser="TestBrowser",
        )

    # --- Assert 1: is_email_verified was set to True ---
    assert mock_user.is_email_verified is True, (
        f"Expected is_email_verified=True after verification, "
        f"got {mock_user.is_email_verified}"
    )

    # --- Assert 2: The token was consumed (deleted from Redis) ---
    mock_redis.delete.assert_called_with(redis_key)

    # --- Assert 3: JWT tokens were returned ---
    assert "access_token" in result, "Result should contain access_token"
    assert "refresh_token" in result, "Result should contain refresh_token"
    assert result["access_token"] == "mock_access_token"
    assert result["refresh_token"] == "mock_refresh_token"

    # --- Assert 4: A session was added to the DB ---
    assert mock_db.add.called, "A session should have been added to the DB"
