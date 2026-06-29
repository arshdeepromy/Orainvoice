"""Property-based test for server-side Field_Set validation (task 8.5).

# Feature: esignature-field-placement, Property 10: Server-side Field_Set validation is correct and names offenders

**Validates: Requirements 2.4, 4.6, 6.1, 6.2, 6.3**

The pure function under test is
:func:`app.modules.esignatures.field_validation.validate_field_set`. It
re-validates a sender-defined Field_Set on the server **before** any Documenso
call, mirroring the client-side rules:

* **R6.2** — every field references a real recipient (``recipient_index`` in
  range); otherwise the field is unassigned.
* **R2.4** — every field's ``type`` maps to a Documenso field type.
* **R6.3** — every field is in bounds (``x>=0, y>=0, x+w<=100, y+h<=100, w>0,
  h>0``, normalized percent).
* **R6.1** — every signer recipient carries >= 1 signature-type field.
* **R4.6** — viewer recipients are exempt: a viewer may have no fields.

This property asserts:

1. ``validate_field_set`` returns ``ok=True`` **iff** every rule holds (checked
   against an independent oracle built from generation-time tags).
2. On failure the result names the offender — a field-level failure reports the
   first offending field (by index/page) with the correct machine code; a
   missing-signature failure reports the exact unsatisfied signer(s) by name.
3. The failure ``message`` is always a non-empty, human-readable string that
   leaks no raw DB/exception text.
4. Viewers with no fields never cause a failure.

The function is pure and deterministic (no I/O), so it is exercised directly
over many generated recipient lists and mixed Field_Sets.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.esignatures.field_validation import (
    CODE_FIELD_OUT_OF_BOUNDS,
    CODE_FIELD_UNASSIGNED,
    CODE_INVALID_FIELD_TYPE,
    CODE_SIGNATURE_FIELD_MISSING,
    validate_field_set,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (>= 100 iterations) — pure, in-memory validator.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=300, deadline=None)

# The six supported lowercase types and a pool of clearly-unsupported strings
# (each rejected by field_mapping.map_field_type: wrong case / unknown / blank).
SUPPORTED_TYPES = ["signature", "initials", "name", "date", "email", "text"]
UNSUPPORTED_TYPES = ["SIGNATURE", "Signature", "checkbox", "radio", "sign", "", "Text"]

# A safe alphabet for recipient names so the stripped name is a clean substring
# of the humanized message (no punctuation that collides with the list join).
_NAME_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "


def _expected_display_name(recipient: dict) -> str:
    """Mirror ``field_validation._recipient_name`` for verifying the message.

    Prefers a non-blank name, then a non-blank email, then ``"this signer"``.
    """
    name = recipient.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    email = recipient.get("email")
    if isinstance(email, str) and email.strip():
        return email.strip()
    return "this signer"


@st.composite
def recipient_strategy(draw):
    """A recipient with a sometimes-present name and a sometimes-present email."""
    name = draw(
        st.one_of(
            st.none(),
            st.text(alphabet=_NAME_ALPHABET, min_size=1, max_size=12).filter(
                lambda s: s.strip() != ""
            ),
        )
    )
    email = draw(
        st.one_of(
            st.none(),
            st.builds(lambda u: f"{u}@example.com",
                      st.text(alphabet="abcdefghijklmnop", min_size=1, max_size=8)),
        )
    )
    return {"name": name, "email": email, "signing_role": "signer"}


@st.composite
def field_strategy(draw, recipient_count: int):
    """One placed field plus generation-time validity tags.

    The field is deliberately built to be *clearly* valid or *clearly* invalid
    on each independent axis (assignment / type / bounds), away from the
    epsilon boundary, so an independent oracle can decide its validity from the
    tags without recomputing the implementation's float comparisons.
    """
    # --- assignment (R6.2) ---
    rec_valid = draw(st.booleans())
    if rec_valid:
        recipient_index = draw(st.integers(min_value=0, max_value=recipient_count - 1))
    else:
        recipient_index = draw(
            st.one_of(
                st.integers(min_value=-5, max_value=-1),
                st.integers(min_value=recipient_count, max_value=recipient_count + 4),
                st.none(),
                st.just(True),  # bool is excluded by the validator -> unassigned
            )
        )

    # --- type (R2.4) ---
    type_supported = draw(st.booleans())
    ftype = draw(
        st.sampled_from(SUPPORTED_TYPES if type_supported else UNSUPPORTED_TYPES)
    )

    # --- bounds (R6.3) ---
    in_bounds = draw(st.booleans())
    if in_bounds:
        x = draw(st.integers(min_value=0, max_value=80))
        w = draw(st.integers(min_value=1, max_value=100 - x))
        y = draw(st.integers(min_value=0, max_value=80))
        h = draw(st.integers(min_value=1, max_value=100 - y))
    else:
        # Default to an otherwise-valid rect, then break exactly one constraint
        # by a clear margin so the implementation unambiguously rejects it.
        x, y, w, h = 10, 10, 20, 20
        violation = draw(
            st.sampled_from(["neg_x", "neg_y", "over_x", "over_y", "zero_w", "zero_h"])
        )
        if violation == "neg_x":
            x = draw(st.integers(min_value=-50, max_value=-1))
        elif violation == "neg_y":
            y = draw(st.integers(min_value=-50, max_value=-1))
        elif violation == "over_x":
            x, w = 80, draw(st.integers(min_value=30, max_value=80))
        elif violation == "over_y":
            y, h = 80, draw(st.integers(min_value=30, max_value=80))
        elif violation == "zero_w":
            w = draw(st.integers(min_value=-20, max_value=0))
        else:  # zero_h
            h = draw(st.integers(min_value=-20, max_value=0))

    page = draw(st.integers(min_value=1, max_value=5))
    field = {
        "type": ftype,
        "page": page,
        "recipient_index": recipient_index,
        "position_x": float(x),
        "position_y": float(y),
        "width": float(w),
        "height": float(h),
        "required": draw(st.booleans()),
    }
    return {
        "field": field,
        "rec_valid": rec_valid,
        "type_supported": type_supported,
        "in_bounds": in_bounds,
        "is_signature": ftype == "signature",
        "recipient_index": recipient_index,
    }


@st.composite
def scenario_strategy(draw):
    """A recipient list, a subset of signer indices, and a mixed Field_Set."""
    recipients = draw(st.lists(recipient_strategy(), min_size=1, max_size=5))
    count = len(recipients)
    # signer_indices is a subset of the recipient indices; the complement are
    # viewers (exempt from the signature-field rule, R4.6).
    signer_indices = draw(
        st.lists(
            st.integers(min_value=0, max_value=count - 1),
            unique=True,
            max_size=count,
        )
    )
    tagged = draw(st.lists(field_strategy(count), min_size=0, max_size=8))
    return recipients, sorted(signer_indices), tagged


def _first_offending(tagged):
    """Return (index, code) of the first field-level offender, or None.

    Replicates the implementation's per-field rule priority (assignment ->
    type -> bounds) purely from the generation tags so we can verify which
    offender the validator names.
    """
    for i, t in enumerate(tagged):
        if not t["rec_valid"]:
            return i, CODE_FIELD_UNASSIGNED
        if not t["type_supported"]:
            return i, CODE_INVALID_FIELD_TYPE
        if not t["in_bounds"]:
            return i, CODE_FIELD_OUT_OF_BOUNDS
    return None


def _expected_missing_signers(tagged, signer_indices, count):
    """Signers (valid range) that carry no signature field, when all fields pass."""
    satisfied = {
        t["recipient_index"]
        for t in tagged
        if t["is_signature"]
    }
    return [i for i in signer_indices if 0 <= i < count and i not in satisfied]


def _assert_human_readable(message: str) -> None:
    """The failure message is a non-empty, leak-free, human-readable sentence."""
    assert isinstance(message, str)
    assert message.strip() != ""
    lowered = message.lower()
    assert "traceback" not in lowered
    assert 'file "' not in lowered
    assert "select " not in lowered  # no raw SQL
    assert "\n" not in message


class TestServerSideFieldSetValidation:
    """Property 10: Server-side Field_Set validation is correct and names offenders.

    **Validates: Requirements 2.4, 4.6, 6.1, 6.2, 6.3**
    """

    @given(scenario=scenario_strategy())
    @PBT_SETTINGS
    def test_validation_is_correct_and_names_offenders(self, scenario):
        recipients, signer_indices, tagged = scenario
        count = len(recipients)
        fields = [t["field"] for t in tagged]

        result = validate_field_set(fields, recipients, signer_indices)

        first_bad = _first_offending(tagged)
        missing = _expected_missing_signers(tagged, signer_indices, count)

        if first_bad is not None:
            # A field-level rule failed: validation must reject and name the
            # FIRST offending field with the matching machine code (R6.2/2.4/6.3).
            expected_index, expected_code = first_bad
            assert result.ok is False
            assert result.code == expected_code
            assert result.field_index == expected_index
            _assert_human_readable(result.message)
            # The named field is genuinely the offender, and the page is cited
            # for the locating codes.
            if expected_code in (CODE_FIELD_UNASSIGNED, CODE_FIELD_OUT_OF_BOUNDS):
                page = fields[expected_index]["page"]
                assert f"page {page}" in result.message
        elif missing:
            # Every field is valid but a signer has no signature field (R6.1).
            assert result.ok is False
            assert result.code == CODE_SIGNATURE_FIELD_MISSING
            assert result.signer_indices == tuple(missing)
            _assert_human_readable(result.message)
            # Each unsatisfied signer is named in the message.
            for idx in missing:
                assert _expected_display_name(recipients[idx]) in result.message
        else:
            # All rules hold -> validation succeeds.
            assert result.ok is True
            assert result.code is None
            assert result.field_index is None
            assert result.signer_indices is None

    @given(
        recipients=st.lists(recipient_strategy(), min_size=1, max_size=5),
        signer_subset=st.data(),
    )
    @PBT_SETTINGS
    def test_viewers_with_no_fields_never_fail(self, recipients, signer_subset):
        """R4.6 — viewers (non-signers) with no fields never cause a failure.

        Each signer gets exactly one valid signature field; viewers get none.
        Validation must succeed regardless of how many viewers exist.
        """
        count = len(recipients)
        # Choose an arbitrary subset of recipients to be signers; the rest are
        # viewers with zero assigned fields.
        signer_indices = sorted(
            signer_subset.draw(
                st.lists(
                    st.integers(min_value=0, max_value=count - 1),
                    unique=True,
                    max_size=count,
                )
            )
        )
        fields = [
            {
                "type": "signature",
                "page": 1,
                "recipient_index": idx,
                "position_x": 10.0,
                "position_y": 10.0,
                "width": 20.0,
                "height": 10.0,
                "required": True,
            }
            for idx in signer_indices
        ]

        result = validate_field_set(fields, recipients, signer_indices)
        assert result.ok is True
        assert result.code is None
