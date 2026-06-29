"""Property-based tests for esignature **field-placement** error shape (task 14.3).

This module mirrors and extends ``test_esign_humanized_error_properties.py``
(esignature-integration Property 24) for the field-placement feature. It covers
**every** field-placement error path and asserts the one humanized error shape
the whole module guarantees (R12.1, R12.2, R12.3):

  * a non-empty, human-readable ``message`` is **always** present;
  * an optional machine-readable ``code`` may accompany it, and when present it
    is one of the module's known codes;
  * the response **never** contains raw database text, raw exception text, or a
    stack trace / traceback.

The error paths exercised here:

  * **Central humanizer** ``humanize_esign_error`` over arbitrary exception
    types carrying adversarial (SQL / traceback / connection-string / token)
    text — including the new field-set codes raised via ``esign_error``.
  * **Every registered code** in ``ESIGN_ERROR_MESSAGES`` — in particular the
    four NEW field-set codes ``field_unassigned`` / ``field_out_of_bounds`` /
    ``invalid_field_type`` / ``signature_field_missing`` (all HTTP 422) — folds
    through ``esign_error`` + ``status_for_code`` to a clean shape.
  * **Server-side Field_Set validation** ``validate_field_set`` over adversarial
    field sets (out-of-bounds, unassigned, unsupported type, signer with no
    signature field): the failure ``message`` it produces is non-empty,
    human-readable, leak-free, and its ``code`` folds cleanly through the
    central error tables to an HTTP 422.

# Feature: esignature-field-placement, Property 17: Error responses are human-readable and leak nothing

**Validates: Requirements 12.1, 12.2, 12.3**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.integrations.documenso import (
    DocumensoApiError,
    DocumensoError,
    DocumensoNotConfiguredError,
)
from app.modules.esignatures.errors import (
    CODE_FIELD_OUT_OF_BOUNDS,
    CODE_FIELD_UNASSIGNED,
    CODE_INVALID_FIELD_TYPE,
    CODE_SIGNATURE_FIELD_MISSING,
    ESIGN_ERROR_MESSAGES,
    esign_error,
    humanize_esign_error,
    status_for_code,
)
from app.modules.esignatures.field_validation import (
    FieldIn,
    validate_field_set,
)
from app.modules.esignatures.schemas import EsignError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The canonical set of human-readable messages the central mapper may return.
_CANONICAL_MESSAGES = set(ESIGN_ERROR_MESSAGES.values())

#: The set of known machine-readable codes.
_KNOWN_CODES = set(ESIGN_ERROR_MESSAGES.keys())

#: The four NEW field-set validation codes this feature adds. All HTTP 422.
_FIELD_SET_CODES = frozenset(
    {
        CODE_FIELD_UNASSIGNED,
        CODE_FIELD_OUT_OF_BOUNDS,
        CODE_INVALID_FIELD_TYPE,
        CODE_SIGNATURE_FIELD_MISSING,
    }
)

#: Sensitive substrings we deliberately inject into exception messages. If any
#: surfaces in a humanized message, the module has leaked raw text. These also
#: stand in for "raw DB / exception / traceback text" generally.
_SENSITIVE_FRAGMENTS = [
    "SELECT * FROM esign_envelopes WHERE org_id = 'abc'",
    "Traceback (most recent call last):",
    'File "/app/service.py", line 42, in send',
    "psycopg2.errors.UniqueViolation",
    "postgresql://user:s3cr3t@db:5432/invoicing",
    "DETAIL:  Key (id)=(7) already exists.",
    "Bearer sk_live_abc123deadbeef",
    "sqlalchemy.exc.IntegrityError",
    "0xDEADBEEF",
    "DROP TABLE esign_recipients; --",
    "asyncpg.exceptions.ConnectionDoesNotExistError",
    "INSERT INTO esign_fields (page, position_x) VALUES (1, 0.5)",
]

#: The six supported field types plus a pool of unsupported ones (to drive the
#: invalid_field_type path in validate_field_set).
_SUPPORTED_TYPES = ["signature", "initials", "name", "date", "email", "text"]
_UNSUPPORTED_TYPES = ["SIGNATURE", "checkbox", "radio", "", "Signature", "sig", "  text"]


# ---------------------------------------------------------------------------
# Strategies — central humanizer over arbitrary exceptions
# ---------------------------------------------------------------------------

# Arbitrary (potentially sensitive) text injected into exception messages.
_arbitrary_messages = st.one_of(
    st.sampled_from(_SENSITIVE_FRAGMENTS),
    st.text(max_size=200),
    st.builds(
        lambda pre, frag, post: f"{pre}{frag}{post}",
        st.text(max_size=30),
        st.sampled_from(_SENSITIVE_FRAGMENTS),
        st.text(max_size=30),
    ),
)


def _build_exception(kind: str, message: str, status: int | None):
    """Construct an exception of the requested type carrying ``message``."""
    if kind == "not_configured":
        return DocumensoNotConfiguredError(message)
    if kind == "api_error":
        return DocumensoApiError(message, status=status)
    if kind == "documenso_error":
        return DocumensoError(message)
    if kind == "value_error":
        return ValueError(message)
    if kind == "runtime_error":
        return RuntimeError(message)
    if kind == "key_error":
        return KeyError(message)
    if kind == "exception":
        return Exception(message)
    if kind == "provisioning_error":
        ProvisioningError = type("ProvisioningError", (Exception,), {})
        return ProvisioningError(message)
    raise AssertionError(f"unknown kind {kind!r}")


_exception_kinds = st.sampled_from(
    [
        "not_configured",
        "api_error",
        "documenso_error",
        "value_error",
        "runtime_error",
        "key_error",
        "exception",
        "provisioning_error",
    ]
)


@st.composite
def arbitrary_exceptions(draw):
    """Build an exception of a random type carrying an arbitrary message."""
    kind = draw(_exception_kinds)
    message = draw(_arbitrary_messages)
    status = draw(st.one_of(st.none(), st.integers(min_value=400, max_value=599)))
    return _build_exception(kind, message, status), message


# ---------------------------------------------------------------------------
# Strategies — adversarial Field_Sets for validate_field_set
# ---------------------------------------------------------------------------

# Benign recipient names/emails. We deliberately DO NOT inject sensitive DB /
# exception text here: a recipient name is user-supplied content that the
# humanized message legitimately echoes (it names the offending signer), so it
# is not "raw DB / exception text" and is out of scope for the leak property.
_benign_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ '-",
    min_size=0,
    max_size=20,
)


@st.composite
def recipients_strategy(draw):
    """A small recipient list with benign names + emails."""
    count = draw(st.integers(min_value=1, max_value=4))
    recipients = []
    for i in range(count):
        recipients.append(
            {
                "name": draw(_benign_names),
                "email": f"user{i}@example.com",
            }
        )
    return recipients


@st.composite
def field_strategy(draw, recipient_count: int):
    """One placed field — possibly out-of-bounds / unassigned / bad-typed."""
    # recipient_index may be out of range (drives field_unassigned).
    recipient_index = draw(st.integers(min_value=-2, max_value=recipient_count + 2))
    # type may be supported or not (drives invalid_field_type).
    field_type = draw(st.sampled_from(_SUPPORTED_TYPES + _UNSUPPORTED_TYPES))
    # coords may exceed bounds (drives field_out_of_bounds).
    position_x = draw(st.floats(min_value=-20, max_value=120, allow_nan=False))
    position_y = draw(st.floats(min_value=-20, max_value=120, allow_nan=False))
    width = draw(st.floats(min_value=-5, max_value=120, allow_nan=False))
    height = draw(st.floats(min_value=-5, max_value=120, allow_nan=False))
    return FieldIn(
        type=field_type,
        page=draw(st.integers(min_value=1, max_value=5)),
        recipient_index=recipient_index,
        position_x=position_x,
        position_y=position_y,
        width=width,
        height=height,
        required=draw(st.booleans()),
        label=draw(st.one_of(st.none(), _benign_names)),
        placeholder=draw(st.one_of(st.none(), _benign_names)),
    )


@st.composite
def field_set_scenario(draw):
    """A recipient list, a (possibly invalid) field set, and signer indices."""
    recipients = draw(recipients_strategy())
    n = len(recipients)
    fields = draw(st.lists(field_strategy(n), min_size=0, max_size=6))
    # Any subset of recipient indices are signers (may include out-of-range).
    signer_indices = tuple(
        draw(
            st.lists(
                st.integers(min_value=-1, max_value=n + 1),
                min_size=0,
                max_size=n + 1,
                unique=True,
            )
        )
    )
    return recipients, fields, signer_indices


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

_CANONICAL_BLOB = " ".join(_CANONICAL_MESSAGES).lower()


def _is_coincidental_substring(raw_lowered: str) -> bool:
    """True when the raw text already appears inside the canonical messages.

    Such a match cannot be evidence of a leak — the text is part of the fixed
    English sentences the mapper draws from, not echoed exception text.
    """
    return raw_lowered in _CANONICAL_BLOB


def _assert_no_sensitive_fragment(message: str) -> None:
    """No distinctive raw DB / exception / traceback fragment ever appears."""
    lowered = message.lower()
    for fragment in _SENSITIVE_FRAGMENTS:
        assert fragment.lower() not in lowered, f"leaked fragment: {fragment!r}"


def _assert_clean_humanized(result: EsignError, raw_text: str) -> None:
    """Core Property 17 invariants on a humanized error from the central mapper."""
    assert isinstance(result, EsignError)
    # message is non-empty and human-readable.
    assert isinstance(result.message, str)
    assert result.message.strip() != ""
    # message is drawn from the canonical set.
    assert result.message in _CANONICAL_MESSAGES
    # message does NOT contain the raw exception text (unless coincidental).
    lowered = result.message.lower()
    raw_lowered = raw_text.lower()
    if raw_text.strip() and not _is_coincidental_substring(raw_lowered):
        assert raw_lowered not in lowered
    _assert_no_sensitive_fragment(result.message)
    # code, when present, is a known code.
    if result.code is not None:
        assert result.code in _KNOWN_CODES


# ===========================================================================
# Property 17 — every field-placement error path is human-readable and leaks nothing
# ===========================================================================


class TestProperty17ErrorsHumanReadableLeakNothing:
    # --- Central humanizer over arbitrary exceptions ----------------------

    @given(payload=arbitrary_exceptions())
    @settings(max_examples=200, deadline=None)
    def test_arbitrary_exceptions_are_humanized_without_leaking(self, payload) -> None:
        """For ANY exception type/message (Documenso failure, connection/config,
        bare DB/value errors) the humanized error is non-empty, canonical, and
        free of the injected raw text (R12.1–12.3)."""
        exc, raw_text = payload
        result = humanize_esign_error(exc)
        _assert_clean_humanized(result, raw_text)

    # --- Every registered code, including the NEW field-set codes ---------

    @given(code=st.sampled_from(sorted(_KNOWN_CODES)))
    @settings(max_examples=100, deadline=None)
    def test_every_code_folds_to_clean_shape_with_status(self, code: str) -> None:
        """Every registered error code — client/server validation, the new
        field-set codes, Documenso failure, connection/config, access control —
        folds through esign_error + status_for_code to a non-empty human-readable
        message, a known code, and a valid HTTP status (R12.1, R12.2)."""
        result = esign_error(code)
        _assert_clean_humanized(result, "")
        assert result.code == code
        status = status_for_code(result.code)
        assert isinstance(status, int)
        assert 100 <= status <= 599

    @given(code=st.sampled_from(sorted(_FIELD_SET_CODES)))
    @settings(max_examples=100, deadline=None)
    def test_field_set_codes_are_422_and_clean(self, code: str) -> None:
        """The four NEW field-placement validation codes each produce a clean,
        non-empty humanized message and map to HTTP 422 (R6.6, R12.1–12.3)."""
        result = esign_error(code)
        _assert_clean_humanized(result, code)
        assert result.code in _FIELD_SET_CODES
        assert status_for_code(result.code) == 422

    # --- Server-side Field_Set validation path ----------------------------

    @given(scenario=field_set_scenario())
    @settings(max_examples=200, deadline=None)
    def test_field_validation_failures_are_clean(self, scenario) -> None:
        """Over adversarial Field_Sets (out-of-bounds, unassigned, unsupported
        type, signer with no signature field), validate_field_set never raises;
        on failure its message is non-empty + human-readable + leak-free and its
        code folds through the central tables to an HTTP 422 with a clean,
        canonical fallback message (R6.6, R12.1–12.3)."""
        recipients, fields, signer_indices = scenario
        result = validate_field_set(fields, recipients, signer_indices)

        if result.ok:
            # A valid set carries no error to leak.
            assert result.code is None
            return

        # Failure: the validator's own message must be clean and human-readable.
        assert isinstance(result.message, str)
        assert result.message.strip() != ""
        _assert_no_sensitive_fragment(result.message)

        # The code is one of the four field-set codes and is registered centrally.
        assert result.code in _FIELD_SET_CODES
        assert result.code in _KNOWN_CODES

        # Folding the code through the central error tables yields a clean shape
        # and an HTTP 422 (the canonical fallback message is leak-free too).
        humanized = esign_error(result.code, message=result.message)
        assert humanized.message.strip() != ""
        _assert_no_sensitive_fragment(humanized.message)
        assert humanized.code == result.code
        assert status_for_code(humanized.code) == 422

        # The canonical (message-less) fallback is also clean.
        fallback = esign_error(result.code)
        _assert_clean_humanized(fallback, "")


# ---------------------------------------------------------------------------
# Example tests — concrete field-placement leak-free behaviour
# ---------------------------------------------------------------------------


def test_example_field_set_codes_registered_centrally() -> None:
    """All four field-set codes are registered in the central message + status
    tables (so the service can raise them via esign_error / status_for_code)."""
    for code in _FIELD_SET_CODES:
        assert code in ESIGN_ERROR_MESSAGES
        assert ESIGN_ERROR_MESSAGES[code].strip() != ""
        assert status_for_code(code) == 422


def test_example_out_of_bounds_field_names_page_not_coords() -> None:
    """An out-of-bounds field yields a human-readable message naming the page,
    not raw coordinate/DB text."""
    recipients = [{"name": "Alex Tran", "email": "alex@example.com"}]
    fields = [
        FieldIn(
            type="signature",
            page=2,
            recipient_index=0,
            position_x=90.0,
            position_y=10.0,
            width=50.0,  # 90 + 50 = 140 > 100 -> out of bounds
            height=10.0,
        )
    ]
    result = validate_field_set(fields, recipients, signer_indices=[0])
    assert not result.ok
    assert result.code == CODE_FIELD_OUT_OF_BOUNDS
    assert "page 2" in result.message
    _assert_no_sensitive_fragment(result.message)


def test_example_missing_signature_names_signer() -> None:
    """A signer with no signature field is named in a human-readable message."""
    recipients = [{"name": "Jordan Lee", "email": "jordan@example.com"}]
    fields = [
        FieldIn(
            type="text",
            page=1,
            recipient_index=0,
            position_x=10.0,
            position_y=10.0,
            width=20.0,
            height=10.0,
        )
    ]
    result = validate_field_set(fields, recipients, signer_indices=[0])
    assert not result.ok
    assert result.code == CODE_SIGNATURE_FIELD_MISSING
    assert "Jordan Lee" in result.message
    _assert_no_sensitive_fragment(result.message)


def test_example_unassigned_field_is_clean() -> None:
    """A field with an out-of-range recipient index is reported leak-free."""
    recipients = [{"name": "Sam", "email": "sam@example.com"}]
    fields = [
        FieldIn(
            type="signature",
            page=1,
            recipient_index=5,  # out of range
            position_x=10.0,
            position_y=10.0,
            width=20.0,
            height=10.0,
        )
    ]
    result = validate_field_set(fields, recipients, signer_indices=[0])
    assert not result.ok
    assert result.code == CODE_FIELD_UNASSIGNED
    assert result.message.strip() != ""
    _assert_no_sensitive_fragment(result.message)
