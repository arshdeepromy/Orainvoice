"""Property-based tests for staff-onboarding humanized error totality.

Property 24 — Every onboarding error carries a non-empty human-readable
message.

The function under test is ``humanize_onboarding_error`` in
``app.modules.staff.onboarding_validation``. It maps a machine error *code* to
a non-empty, human-readable sentence that contains no raw DB/exception text
(R14.5). The function is **total**: every code in ``ONBOARDING_ERROR_CODES``
maps to a message, and any unknown / non-string code falls back to the generic
``server_error`` message (so a message is always available). The emitted error
object pairs ``{message, code}`` — verified here via the ``OnboardingFieldError``
schema (R9.2, R14).

**Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.staff.onboarding_validation import (
    ONBOARDING_ERROR_CODES,
    humanize_onboarding_error,
)
from app.modules.staff.schemas import OnboardingFieldError

# ---------------------------------------------------------------------------
# Constants / strategies
# ---------------------------------------------------------------------------

# Substrings that would betray raw DB/exception/stack-trace text leaking into a
# user-facing message. The check is deliberately case-insensitive and kept to a
# reasonable, well-known set of markers (R14.5).
_RAW_ERROR_MARKERS = (
    "traceback",
    "psycopg",
    "sqlalchemy",
    "exception",
    "stacktrace",
    "stack trace",
    "errno",
    "  file \"",  # python traceback frame marker
    "asyncpg",
    "integrityerror",
    "operationalerror",
    "0x",  # hex pointer/address fragments
)


def _assert_clean_message(message: str) -> None:
    """A humanized message must be a non-empty str free of raw error markers."""
    assert isinstance(message, str)
    assert message.strip() != ""
    lowered = message.lower()
    for marker in _RAW_ERROR_MARKERS:
        assert marker not in lowered, f"raw error marker {marker!r} leaked into message"


# Arbitrary strings that are NOT real codes (used to exercise the fallback).
_unknown_strings = st.text(min_size=0, max_size=40).filter(
    lambda s: s not in ONBOARDING_ERROR_CODES
)

# Non-string inputs (totality must hold for these too).
_non_string_inputs = st.one_of(
    st.none(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.booleans(),
    st.lists(st.text(), max_size=3),
    st.dictionaries(st.text(max_size=5), st.text(max_size=5), max_size=3),
    st.binary(max_size=10),
)


# ===========================================================================
# Feature: staff-onboarding-link, Property 24: Every onboarding error carries
# a non-empty human-readable message
# ===========================================================================


class TestProperty24HumanizedErrorTotality:
    """``humanize_onboarding_error`` is total and DB/exception-text free."""

    @given(code=st.sampled_from(ONBOARDING_ERROR_CODES))
    @settings(max_examples=200, deadline=None)
    def test_every_known_code_yields_clean_nonempty_message(self, code: str) -> None:
        """Property 24 — every canonical error code maps to a non-empty,
        marker-free human-readable message (R14.1–R14.5)."""
        message = humanize_onboarding_error(code)
        _assert_clean_message(message)

    @given(code=_unknown_strings)
    @settings(max_examples=200, deadline=None)
    def test_unknown_string_codes_fall_back_to_server_error(self, code: str) -> None:
        """Property 24 — any unrecognised string falls back to the generic
        ``server_error`` message (totality, R14.5)."""
        message = humanize_onboarding_error(code)
        _assert_clean_message(message)
        assert message == humanize_onboarding_error("server_error")

    @given(code=_non_string_inputs)
    @settings(max_examples=200, deadline=None)
    def test_non_string_inputs_still_return_clean_message(self, code: object) -> None:
        """Property 24 — non-string input still returns a non-empty,
        marker-free message without raising (totality, R14.5)."""
        message = humanize_onboarding_error(code)
        _assert_clean_message(message)
        assert message == humanize_onboarding_error("server_error")

    @given(code=st.sampled_from(ONBOARDING_ERROR_CODES))
    @settings(max_examples=200, deadline=None)
    def test_emitted_object_pairs_message_and_code(self, code: str) -> None:
        """Property 24 — the emitted error object carries BOTH ``message`` and
        ``code``, with no raw DB/exception text (R9.2, R14)."""
        error = OnboardingFieldError(message=humanize_onboarding_error(code), code=code)
        # Both fields present and populated.
        assert error.code == code
        _assert_clean_message(error.message)
        # Round-trips through serialisation carrying exactly the two fields.
        dumped = error.model_dump()
        assert set(dumped) == {"message", "code"}
        assert dumped["code"] == code
        _assert_clean_message(dumped["message"])


# ---------------------------------------------------------------------------
# Example test — concrete pairing pattern (mirrors a real submit rejection)
# ---------------------------------------------------------------------------


def test_example_field_error_pairing_for_validation_failure() -> None:
    """A submit rejection pairs a humanized ``message`` with its ``code``."""
    code = "validation_failed"
    error = OnboardingFieldError(message=humanize_onboarding_error(code), code=code)
    assert error.code == "validation_failed"
    assert error.message and isinstance(error.message, str)
    _assert_clean_message(error.message)


def test_example_all_known_codes_have_distinct_messages() -> None:
    """Each canonical (non-fallback) code has its own distinct message text."""
    # Exclude server_error since unknown codes intentionally alias to it.
    distinct_codes = [c for c in ONBOARDING_ERROR_CODES if c != "server_error"]
    messages = {humanize_onboarding_error(c) for c in distinct_codes}
    # Every distinct known code maps to its own message.
    assert len(messages) == len(distinct_codes)
