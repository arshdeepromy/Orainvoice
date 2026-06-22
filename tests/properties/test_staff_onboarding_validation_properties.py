"""Property-based tests for staff-onboarding pure field validators.

Properties covered:
  Property 9 — IRD number length validation.

The function under test is ``validate_ird_length`` in
``app.modules.staff.onboarding_validation``: it strips ``-`` and `` `` (space)
separators and returns ``True`` iff the remainder is all digits AND has length
8 or 9 (R6.2, R6.3). Anything else — wrong length, non-digit characters, or a
non-string — is ``False``.

**Validates: Requirements 6.2, 6.3**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.staff.onboarding_validation import validate_ird_length

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_SEPARATORS = ("-", " ")

# Non-digit, non-separator characters. Deliberately excludes whitespace (which
# ``str.strip()`` would remove) and the ``-``/`` `` separators (which the
# validator removes), so that injecting one of these is guaranteed to leave a
# non-digit character in the stripped value.
_NON_DIGIT_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ@#$%/.*+_x"


@st.composite
def _digits(draw, *, min_size: int, max_size: int) -> str:
    """A string of ASCII digits with length in ``[min_size, max_size]``."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    return "".join(draw(st.lists(st.sampled_from("0123456789"), min_size=n, max_size=n)))


@st.composite
def _sprinkle_separators(draw, digits: str) -> str:
    """Insert random ``-``/`` `` separators at arbitrary positions in *digits*.

    The result strips back to exactly *digits* under the validator's
    ``replace("-", "").replace(" ", "")`` normalisation.
    """
    chars = list(digits)
    # Number of separators to insert (0..4) at random gap positions.
    count = draw(st.integers(min_value=0, max_value=4))
    for _ in range(count):
        pos = draw(st.integers(min_value=0, max_value=len(chars)))
        sep = draw(st.sampled_from(_SEPARATORS))
        chars.insert(pos, sep)
    return "".join(chars)


@st.composite
def _valid_ird_with_separators(draw) -> str:
    """8- or 9-digit IRD strings carrying hyphen/space separators (expect True)."""
    n = draw(st.sampled_from((8, 9)))
    digits = draw(_digits(min_size=n, max_size=n))
    return draw(_sprinkle_separators(digits))


@st.composite
def _wrong_length_ird(draw) -> str:
    """All-digit (with separators) strings whose digit count is NOT 8 or 9."""
    n = draw(st.integers(min_value=0, max_value=15).filter(lambda x: x not in (8, 9)))
    digits = draw(_digits(min_size=n, max_size=n))
    return draw(_sprinkle_separators(digits))


@st.composite
def _non_digit_ird(draw) -> str:
    """Strings that contain a non-digit, non-separator char after stripping."""
    # Start from a digit run of any length (possibly the "valid" 8/9 length, to
    # prove the bad character alone forces rejection) ...
    digits = draw(_digits(min_size=0, max_size=10))
    chars = list(digits)
    # ... inject at least one disallowed character at an arbitrary position.
    bad_count = draw(st.integers(min_value=1, max_value=3))
    for _ in range(bad_count):
        pos = draw(st.integers(min_value=0, max_value=len(chars)))
        chars.insert(pos, draw(st.sampled_from(_NON_DIGIT_CHARS)))
    # Optionally also sprinkle real separators around it.
    return draw(_sprinkle_separators("".join(chars)))


# ===========================================================================
# Feature: staff-onboarding-link, Property 9: IRD number length validation
# ===========================================================================


class TestProperty9IrdLengthValidation:
    """``validate_ird_length`` accepts exactly 8/9-digit values (ignoring
    ``-``/`` `` separators) and rejects everything else (R6.2, R6.3)."""

    @given(value=_valid_ird_with_separators())
    @settings(max_examples=200, deadline=None)
    def test_eight_or_nine_digits_with_separators_accepted(self, value: str) -> None:
        """Separators stripped to 8 or 9 digits → accepted."""
        assert validate_ird_length(value) is True

    @given(value=_wrong_length_ird())
    @settings(max_examples=200, deadline=None)
    def test_non_eight_or_nine_digit_lengths_rejected(self, value: str) -> None:
        """Digit count outside {8, 9} after stripping → rejected."""
        assert validate_ird_length(value) is False

    @given(value=_non_digit_ird())
    @settings(max_examples=200, deadline=None)
    def test_non_digit_characters_rejected(self, value: str) -> None:
        """Any non-digit, non-separator character after stripping → rejected."""
        assert validate_ird_length(value) is False

    @given(value=st.one_of(st.integers(), st.none(), st.floats(), st.booleans()))
    @settings(max_examples=100, deadline=None)
    def test_non_string_input_rejected(self, value: object) -> None:
        """Non-string input is rejected without raising."""
        assert validate_ird_length(value) is False


# ===========================================================================
# Feature: staff-onboarding-link, Property 23: Admin lifecycle label is total
# and single-valued
# ===========================================================================
#
# The function under test is ``onboarding_lifecycle_label(row, now)`` in
# ``app.modules.staff.onboarding_validation``. It returns exactly one of six
# labels in strict precedence order (R13.1):
#
#     row is None                  -> "none"
#     status == "revoked"          -> "revoked"
#     status == "consumed"         -> "completed"
#     expires_at <= now (pending)  -> "expired"
#     draft_updated_at is not None -> "in_progress"
#     otherwise                    -> "not_started"
#
# **Validates: Requirements 13.1**

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.modules.staff.onboarding_validation import onboarding_lifecycle_label

_VALID_LABELS = frozenset(
    {"not_started", "in_progress", "completed", "expired", "revoked", "none"}
)

# A fixed timezone-aware reference instant. ``onboarding_lifecycle_label``
# compares ``expires_at <= now`` directly, so all generated datetimes are
# timezone-aware and comparable with this value.
_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# Statuses: the three meaningful values plus junk that must fall through the
# status branches (treated as "pending"-like for the expiry/draft branches).
_STATUS_VALUES = ("pending", "consumed", "revoked", "active", "", "REVOKED", "weird", None)


def _expected_label(row: object, now: datetime) -> str:
    """Independent re-implementation of the documented precedence (the oracle)."""
    if row is None:
        return "none"
    status = row.get("status") if isinstance(row, dict) else getattr(row, "status", None)
    if status == "revoked":
        return "revoked"
    if status == "consumed":
        return "completed"
    expires_at = (
        row.get("expires_at") if isinstance(row, dict) else getattr(row, "expires_at", None)
    )
    if expires_at is not None and expires_at <= now:
        return "expired"
    draft_updated_at = (
        row.get("draft_updated_at")
        if isinstance(row, dict)
        else getattr(row, "draft_updated_at", None)
    )
    if draft_updated_at is not None:
        return "in_progress"
    return "not_started"


@st.composite
def _aware_datetime_or_none(draw) -> object:
    """A timezone-aware datetime offset before/after ``_NOW``, or ``None``.

    Offsets straddle zero (and include exactly zero) so the boundary
    ``expires_at == now`` — which counts as expired — is exercised.
    """
    if draw(st.booleans()):
        return None
    offset_seconds = draw(st.integers(min_value=-1_000_000, max_value=1_000_000))
    return _NOW + timedelta(seconds=offset_seconds)


@st.composite
def _lifecycle_row(draw) -> object:
    """A row over all (status, expires_at, draft_updated_at) combos, or ``None``.

    Rows are emitted as both ``dict`` and ``SimpleNamespace`` so that both
    branches of the ``_get`` accessor (Mapping vs attribute object) are
    covered. ``None`` is included to exercise the "none" label.
    """
    if draw(st.integers(min_value=0, max_value=9)) == 0:
        return None
    fields = {
        "status": draw(st.sampled_from(_STATUS_VALUES)),
        "expires_at": draw(_aware_datetime_or_none()),
        "draft_updated_at": draw(_aware_datetime_or_none()),
    }
    return dict(fields) if draw(st.booleans()) else SimpleNamespace(**fields)


class TestProperty23AdminLifecycleLabel:
    """``onboarding_lifecycle_label`` is total and single-valued: it always
    returns exactly one of the six valid labels following the documented
    precedence, for every (status, expiry, draft) combination and ``None``
    (R13.1)."""

    @given(row=_lifecycle_row())
    @settings(max_examples=300, deadline=None)
    def test_result_is_always_one_of_six_valid_labels(self, row: object) -> None:
        """Total: never blank/ambiguous — result is always a valid label."""
        result = onboarding_lifecycle_label(row, _NOW)
        assert result in _VALID_LABELS

    @given(row=_lifecycle_row())
    @settings(max_examples=300, deadline=None)
    def test_documented_precedence_holds(self, row: object) -> None:
        """Single-valued: matches the independently-computed precedence oracle."""
        assert onboarding_lifecycle_label(row, _NOW) == _expected_label(row, _NOW)

    # --- Targeted branch coverage (each precedence step in isolation) -------

    def test_none_row_yields_none(self) -> None:
        """``row is None`` → "none"."""
        assert onboarding_lifecycle_label(None, _NOW) == "none"

    def test_revoked_wins_over_everything(self) -> None:
        """``status == "revoked"`` beats expiry and draft presence → "revoked"."""
        row = {
            "status": "revoked",
            "expires_at": _NOW - timedelta(days=1),
            "draft_updated_at": _NOW,
        }
        assert onboarding_lifecycle_label(row, _NOW) == "revoked"

    def test_consumed_yields_completed_over_expiry(self) -> None:
        """``status == "consumed"`` beats a past expiry → "completed"."""
        row = {
            "status": "consumed",
            "expires_at": _NOW - timedelta(days=1),
            "draft_updated_at": _NOW,
        }
        assert onboarding_lifecycle_label(row, _NOW) == "completed"

    def test_pending_past_expiry_yields_expired(self) -> None:
        """Pending with ``expires_at <= now`` → "expired" (even with a draft)."""
        row = {
            "status": "pending",
            "expires_at": _NOW - timedelta(seconds=1),
            "draft_updated_at": _NOW,
        }
        assert onboarding_lifecycle_label(row, _NOW) == "expired"

    def test_expiry_boundary_equal_now_is_expired(self) -> None:
        """``expires_at == now`` counts as expired (``<=`` boundary)."""
        row = {"status": "pending", "expires_at": _NOW, "draft_updated_at": None}
        assert onboarding_lifecycle_label(row, _NOW) == "expired"

    def test_pending_with_draft_not_expired_yields_in_progress(self) -> None:
        """Pending, not expired, draft present → "in_progress"."""
        row = {
            "status": "pending",
            "expires_at": _NOW + timedelta(days=1),
            "draft_updated_at": _NOW - timedelta(hours=1),
        }
        assert onboarding_lifecycle_label(row, _NOW) == "in_progress"

    def test_pending_no_draft_not_expired_yields_not_started(self) -> None:
        """Pending, not expired, no draft → "not_started"."""
        row = {
            "status": "pending",
            "expires_at": _NOW + timedelta(days=1),
            "draft_updated_at": None,
        }
        assert onboarding_lifecycle_label(row, _NOW) == "not_started"

    def test_attribute_object_row_supported(self) -> None:
        """Rows exposed as attribute objects work the same as dict rows."""
        row = SimpleNamespace(
            status="pending",
            expires_at=_NOW + timedelta(days=1),
            draft_updated_at=_NOW,
        )
        assert onboarding_lifecycle_label(row, _NOW) == "in_progress"


# ===========================================================================
# Feature: staff-onboarding-link, Property 3: Token state classification is
# total and distinct
# ===========================================================================
#
# The functions under test are ``classify_token_state(row, now,
# staff_is_active)`` and ``token_state_error_code(state)`` in
# ``app.modules.staff.onboarding_validation``. ``classify_token_state`` returns
# exactly one of six ``TokenState`` values in strict precedence order (R2.4,
# R2.6, R10.1, R11.3, R11.4):
#
#     row is None                            -> "not_found"
#     status == "revoked"                    -> "revoked"
#     status == "consumed"                   -> "consumed"
#     pending AND expires_at <= now          -> "expired"
#     pending, not expired, staff inactive   -> "staff_inactive"
#     pending, not expired, staff active     -> "valid"
#
# ``token_state_error_code`` maps every non-"valid" state to one of the
# ``ONBOARDING_ERROR_CODES`` (an ``onboarding_token_*`` code) and "valid" to
# ``None``.
#
# **Validates: Requirements 2.4, 2.6, 10.1, 11.3, 11.4**

from app.modules.staff.onboarding_validation import (
    ONBOARDING_ERROR_CODES,
    classify_token_state,
    token_state_error_code,
)

_VALID_TOKEN_STATES = frozenset(
    {"not_found", "revoked", "consumed", "expired", "staff_inactive", "valid"}
)

# The error code each non-"valid" state must map to (single source of truth for
# the oracle below).
_EXPECTED_ERROR_CODE = {
    "not_found": "onboarding_token_not_found",
    "revoked": "onboarding_token_revoked",
    "consumed": "onboarding_token_consumed",
    "expired": "onboarding_token_expired",
    "staff_inactive": "onboarding_token_staff_inactive",
}


def _expected_token_state(row: object, now: datetime, staff_is_active: bool) -> str:
    """Independent re-implementation of the documented precedence (the oracle)."""
    if row is None:
        return "not_found"
    status = row.get("status") if isinstance(row, dict) else getattr(row, "status", None)
    if status == "revoked":
        return "revoked"
    if status == "consumed":
        return "consumed"
    expires_at = (
        row.get("expires_at") if isinstance(row, dict) else getattr(row, "expires_at", None)
    )
    if expires_at is not None and expires_at <= now:
        return "expired"
    if not staff_is_active:
        return "staff_inactive"
    return "valid"


@st.composite
def _token_row(draw) -> object:
    """A row over all (status, expires_at) combos, or ``None``.

    Rows are emitted as both ``dict`` and ``SimpleNamespace`` so both branches
    of the ``_get`` accessor (Mapping vs attribute object) are covered. ``None``
    is included to exercise the "not_found" state. Statuses include the three
    meaningful values plus junk that must fall through to the expiry/active
    branches.
    """
    if draw(st.integers(min_value=0, max_value=9)) == 0:
        return None
    fields = {
        "status": draw(st.sampled_from(_STATUS_VALUES)),
        "expires_at": draw(_aware_datetime_or_none()),
    }
    return dict(fields) if draw(st.booleans()) else SimpleNamespace(**fields)


class TestProperty3TokenStateClassification:
    """``classify_token_state`` is total and distinct: it always returns exactly
    one of the six valid ``TokenState`` values following the documented
    precedence, for every (status, expiry, is_active) combination and ``None``;
    ``token_state_error_code`` maps every rejecting state to a valid
    ``onboarding_token_*`` code and "valid" to ``None`` (R2.4, R2.6, R10.1,
    R11.3, R11.4)."""

    @given(row=_token_row(), staff_is_active=st.booleans())
    @settings(max_examples=300, deadline=None)
    def test_result_is_always_one_of_six_valid_states(
        self, row: object, staff_is_active: bool
    ) -> None:
        """Total: never blank/ambiguous — result is always a valid TokenState."""
        result = classify_token_state(row, _NOW, staff_is_active)
        assert result in _VALID_TOKEN_STATES

    @given(row=_token_row(), staff_is_active=st.booleans())
    @settings(max_examples=300, deadline=None)
    def test_documented_precedence_holds(
        self, row: object, staff_is_active: bool
    ) -> None:
        """Distinct/single-valued: matches the independent precedence oracle."""
        assert classify_token_state(row, _NOW, staff_is_active) == _expected_token_state(
            row, _NOW, staff_is_active
        )

    @given(row=_token_row(), staff_is_active=st.booleans())
    @settings(max_examples=300, deadline=None)
    def test_error_code_is_consistent_with_state(
        self, row: object, staff_is_active: bool
    ) -> None:
        """``token_state_error_code`` agrees with the classified state: a valid
        ``onboarding_token_*`` code for every rejecting state, ``None`` for
        "valid"."""
        state = classify_token_state(row, _NOW, staff_is_active)
        code = token_state_error_code(state)
        if state == "valid":
            assert code is None
        else:
            assert code == _EXPECTED_ERROR_CODE[state]
            assert code in ONBOARDING_ERROR_CODES

    # --- Targeted branch coverage (each precedence step in isolation) -------

    def test_none_row_yields_not_found(self) -> None:
        """``row is None`` → "not_found" (regardless of staff activity)."""
        assert classify_token_state(None, _NOW, True) == "not_found"
        assert classify_token_state(None, _NOW, False) == "not_found"

    def test_revoked_wins_over_expiry_and_inactivity(self) -> None:
        """``status == "revoked"`` beats a past expiry and inactive staff."""
        row = {"status": "revoked", "expires_at": _NOW - timedelta(days=1)}
        assert classify_token_state(row, _NOW, False) == "revoked"

    def test_consumed_wins_over_expiry_and_inactivity(self) -> None:
        """``status == "consumed"`` beats a past expiry and inactive staff."""
        row = {"status": "consumed", "expires_at": _NOW - timedelta(days=1)}
        assert classify_token_state(row, _NOW, False) == "consumed"

    def test_pending_past_expiry_yields_expired(self) -> None:
        """Pending with ``expires_at <= now`` → "expired" (even if inactive)."""
        row = {"status": "pending", "expires_at": _NOW - timedelta(seconds=1)}
        assert classify_token_state(row, _NOW, False) == "expired"

    def test_expiry_boundary_equal_now_is_expired(self) -> None:
        """``expires_at == now`` counts as expired (``<=`` boundary)."""
        row = {"status": "pending", "expires_at": _NOW}
        assert classify_token_state(row, _NOW, True) == "expired"

    def test_pending_not_expired_inactive_yields_staff_inactive(self) -> None:
        """Pending, not expired, staff inactive → "staff_inactive"."""
        row = {"status": "pending", "expires_at": _NOW + timedelta(days=1)}
        assert classify_token_state(row, _NOW, False) == "staff_inactive"

    def test_pending_not_expired_active_yields_valid(self) -> None:
        """Pending, not expired, staff active → "valid"."""
        row = {"status": "pending", "expires_at": _NOW + timedelta(days=1)}
        assert classify_token_state(row, _NOW, True) == "valid"

    def test_none_expiry_treated_as_not_expired(self) -> None:
        """A missing ``expires_at`` is treated as not-expired (stays total)."""
        row = {"status": "pending", "expires_at": None}
        assert classify_token_state(row, _NOW, True) == "valid"
        assert classify_token_state(row, _NOW, False) == "staff_inactive"

    def test_attribute_object_row_supported(self) -> None:
        """Rows exposed as attribute objects work the same as dict rows."""
        row = SimpleNamespace(status="pending", expires_at=_NOW + timedelta(days=1))
        assert classify_token_state(row, _NOW, True) == "valid"

    def test_valid_state_has_no_error_code(self) -> None:
        """``token_state_error_code("valid")`` is ``None``."""
        assert token_state_error_code("valid") is None
