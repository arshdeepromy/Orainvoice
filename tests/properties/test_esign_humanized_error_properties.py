"""Property-based tests for esignatures error humanization (task 7.2).

The function under test is ``humanize_esign_error`` in
``app.modules.esignatures.errors``. It is the central, **total** mapper from an
internal exception to the humanized ``{ message, code }`` shape (R16). For ANY
input it returns an :class:`EsignError` whose ``message`` is a non-empty,
human-readable sentence drawn from the canonical ``ESIGN_ERROR_MESSAGES`` set,
and it NEVER embeds raw database text or raw exception text (R15.5) — in
particular it never interpolates ``str(exc)`` into the returned message.

This module exercises Property 24: regardless of the exception type or the
(possibly sensitive: SQL fragments, tracebacks, connection strings) message it
carries, the humanized message:

  * is non-empty and human-readable;
  * does NOT contain the injected raw exception text;
  * is one of the canonical ``ESIGN_ERROR_MESSAGES`` values;
  * carries a ``code`` (when present) that is a known esign error code.

# Feature: esignature-integration, Property 24: Error responses are human-readable and leak nothing

**Validates: Requirements 15.5, 16.1, 16.2, 16.3**
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
    ESIGN_ERROR_MESSAGES,
    esign_error,
    humanize_esign_error,
    status_for_code,
)
from app.modules.esignatures.schemas import EsignError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The canonical set of human-readable messages the mapper may ever return.
_CANONICAL_MESSAGES = set(ESIGN_ERROR_MESSAGES.values())

#: The set of known machine-readable codes.
_KNOWN_CODES = set(ESIGN_ERROR_MESSAGES.keys())

#: Sensitive substrings we deliberately inject into exception messages. If any
#: of these surface in the humanized message, the mapper has leaked raw text.
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
]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Arbitrary (potentially sensitive) text injected into exception messages.
_arbitrary_messages = st.one_of(
    st.sampled_from(_SENSITIVE_FRAGMENTS),
    st.text(max_size=200),
    # Compose a random message that embeds a sensitive fragment to be adversarial.
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
        # Duck-typed by class name in the mapper — define a local class so the
        # name matches without importing the optional adapter module.
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
# Assertions helper
# ---------------------------------------------------------------------------


_CANONICAL_BLOB = " ".join(_CANONICAL_MESSAGES).lower()


def _is_coincidental_substring(raw_lowered: str) -> bool:
    """True when the raw text already appears inside the canonical messages.

    Such a match cannot be evidence of a leak — the text is part of the fixed
    English sentences the mapper draws from, not echoed exception text.
    """
    return raw_lowered in _CANONICAL_BLOB


def _assert_clean_humanized(result: EsignError, raw_text: str) -> None:
    """Core Property 24 invariants on a humanized error."""
    # It is the right shape.
    assert isinstance(result, EsignError)
    # message is non-empty and human-readable.
    assert isinstance(result.message, str)
    assert result.message.strip() != ""
    # message is drawn from the canonical set.
    assert result.message in _CANONICAL_MESSAGES
    # message does NOT contain the raw exception text. We check the whole raw
    # string and each sensitive fragment as a substring (case-insensitive).
    #
    # Because the returned message is always one of a small set of fixed
    # English sentences, a short raw string (e.g. "L") can appear in it purely
    # by coincidence — that is NOT a leak. We therefore only flag the raw text
    # as leaked when it could *only* have come from the exception: i.e. it is
    # not already a coincidental substring of any canonical message.
    lowered = result.message.lower()
    raw_lowered = raw_text.lower()
    if raw_text.strip() and not _is_coincidental_substring(raw_lowered):
        assert raw_lowered not in lowered
    # The distinctive sensitive fragments must NEVER appear, unconditionally.
    for fragment in _SENSITIVE_FRAGMENTS:
        assert fragment.lower() not in lowered
    # code, when present, is a known code.
    if result.code is not None:
        assert result.code in _KNOWN_CODES


# ===========================================================================
# Property 24 — humanize_esign_error never leaks and is total
# ===========================================================================


class TestProperty24ErrorsHumanReadableLeakNothing:
    @given(payload=arbitrary_exceptions())
    @settings(max_examples=200, deadline=None)
    def test_arbitrary_exceptions_are_humanized_without_leaking(self, payload) -> None:
        """For ANY exception type/message the humanized error is non-empty,
        canonical, and free of the injected raw text (R15.5, R16.1–16.3)."""
        exc, raw_text = payload
        result = humanize_esign_error(exc)
        _assert_clean_humanized(result, raw_text)

    @given(message=_arbitrary_messages)
    @settings(max_examples=200, deadline=None)
    def test_value_error_with_db_like_text_maps_to_server_error(self, message: str) -> None:
        """A bare ValueError carrying SQL/DB-like text falls back to the generic
        server_error message and never echoes the raw text (R16.3)."""
        result = humanize_esign_error(ValueError(message))
        _assert_clean_humanized(result, message)
        assert result.code == "server_error"

    @given(message=_arbitrary_messages, status=st.one_of(st.none(), st.integers(400, 599)))
    @settings(max_examples=200, deadline=None)
    def test_documenso_api_error_status_is_never_surfaced(
        self, message: str, status: int | None
    ) -> None:
        """A DocumensoApiError maps to documenso_error; the upstream status and
        raw message are never surfaced in the humanized message."""
        result = humanize_esign_error(DocumensoApiError(message, status=status))
        _assert_clean_humanized(result, message)
        assert result.code == "documenso_error"
        if status is not None:
            assert str(status) not in result.message

    @given(message=_arbitrary_messages)
    @settings(max_examples=200, deadline=None)
    def test_not_configured_maps_to_integration_not_configured(self, message: str) -> None:
        """DocumensoNotConfiguredError always maps to the configured-integration
        message regardless of the raw text it carries (R1.9/1.10)."""
        result = humanize_esign_error(DocumensoNotConfiguredError(message))
        _assert_clean_humanized(result, message)
        assert result.code == "integration_not_configured"

    @given(
        raw_strings=st.text(max_size=200),
    )
    @settings(max_examples=200, deadline=None)
    def test_non_exception_inputs_are_total_and_clean(self, raw_strings: str) -> None:
        """The mapper is total even for non-exception inputs (e.g. raw strings):
        it returns a clean canonical message without raising."""
        result = humanize_esign_error(raw_strings)
        _assert_clean_humanized(result, raw_strings)
        # A bare string is not a recognised error -> generic fallback.
        assert result.code == "server_error"

    @given(
        value=st.one_of(
            st.none(),
            st.integers(),
            st.floats(allow_nan=True, allow_infinity=True),
            st.booleans(),
            st.lists(st.text(max_size=10), max_size=3),
            st.dictionaries(st.text(max_size=5), st.text(max_size=20), max_size=3),
            st.binary(max_size=20),
        )
    )
    @settings(max_examples=200, deadline=None)
    def test_totally_arbitrary_non_string_inputs(self, value: object) -> None:
        """Totality: any non-string, non-exception input still returns a clean,
        canonical, code-tagged error without raising."""
        result = humanize_esign_error(value)
        # raw_text empty -> only fragment checks apply.
        _assert_clean_humanized(result, "")
        assert result.code == "server_error"

    @given(code=st.sampled_from(sorted(_KNOWN_CODES)))
    @settings(max_examples=100, deadline=None)
    def test_already_humanized_esign_error_round_trips(self, code: str) -> None:
        """An EsignError fed back through the mapper round-trips unchanged, and
        every canonical code maps to a clean message with a valid status."""
        original = esign_error(code)
        result = humanize_esign_error(original)
        _assert_clean_humanized(result, "")
        assert result.code == original.code
        assert result.message == original.message
        # Status table is consistent for every code.
        assert isinstance(status_for_code(result.code), int)


# ---------------------------------------------------------------------------
# Example tests — concrete leak-free behaviour
# ---------------------------------------------------------------------------


def test_example_sql_injection_text_is_not_echoed() -> None:
    """A raw SQL fragment in the exception never appears in the response."""
    exc = ValueError("SELECT * FROM esign_envelopes WHERE org_id = 'abc'")
    result = humanize_esign_error(exc)
    assert "SELECT" not in result.message
    assert result.message in _CANONICAL_MESSAGES
    assert result.code == "server_error"


def test_example_connection_string_is_not_echoed() -> None:
    """A DB connection string with credentials never leaks into the message."""
    exc = RuntimeError("postgresql://user:s3cr3t@db:5432/invoicing")
    result = humanize_esign_error(exc)
    assert "s3cr3t" not in result.message
    assert "postgresql://" not in result.message
    assert result.message in _CANONICAL_MESSAGES


def test_example_all_canonical_messages_are_nonempty() -> None:
    """Every canonical message is a non-empty human-readable sentence."""
    for message in _CANONICAL_MESSAGES:
        assert isinstance(message, str) and message.strip() != ""
