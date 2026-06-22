"""Property-based test: slug normalisation is idempotent and case-insensitive.

# Feature: organisation-employee-portal, Property 5: Slug normalisation is idempotent and case-insensitive

**Validates: Requirements 2.7, 2.8**

R2.7 requires that when an Org_Slug is stored it is stored in *normalised
lowercase form*, and R2.8 requires that all slug comparison, reservation, and
uniqueness checks are case-insensitive. Both rest on the single pure helper
``slug_service.normalise_slug(raw)`` (trim leading/trailing whitespace + fold
to lowercase) in ``app/modules/organisations/slug_service.py``.

For normalisation to be a sound basis for storage and case-insensitive
comparison it must satisfy two algebraic properties:

* **Idempotent** — normalising an already-normalised value changes nothing:
  ``normalise(normalise(x)) == normalise(x)``. This guarantees a stored slug
  re-read and re-normalised is stable, so equality comparisons are well-defined.
* **Case-insensitive** — any two case variants of the same input normalise to
  the identical value, so reservation/uniqueness checks can never be fooled by
  letter casing.

``normalise_slug`` is pure and side-effect-free, so it is exercised directly
with no database, over ≥100 generated examples.
"""

from __future__ import annotations

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.organisations.slug_service import normalise_slug

# ---------------------------------------------------------------------------
# Hypothesis settings (≥100 iterations) — pure in-memory normalisation.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=300, deadline=None)

# Arbitrary text (including surrounding whitespace, unicode, control chars) for
# the idempotency property, which must hold universally.
_any_text = st.text(max_size=80)

# Curated alphabet for the case-insensitivity property. ASCII letters/digits,
# whitespace, and slug-shaped punctuation all have well-behaved single-character
# casing where ``upper``/``lower`` round-trip cleanly (unlike e.g. ``ß`` → ``SS``),
# which is exactly the input space slugs live in (R2.8).
_CASE_SAFE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 \t-_"
_case_safe_text = st.text(alphabet=_CASE_SAFE_ALPHABET, max_size=80)


def _random_case_variant(base: str, rnd: random.Random) -> str:
    """Return a string equal to ``base`` up to per-character letter casing."""
    return "".join(rnd.choice((ch.lower(), ch.upper())) for ch in base)


# ---------------------------------------------------------------------------
# Property 5: Slug normalisation is idempotent and case-insensitive
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(raw=_any_text)
def test_normalise_is_idempotent(raw: str) -> None:
    """normalise(normalise(x)) == normalise(x) for any input.

    Property 5 (idempotency) — applying normalisation a second time is a no-op,
    so a stored, already-normalised slug stays stable under re-normalisation.

    **Validates: Requirements 2.7, 2.8**
    """
    once = normalise_slug(raw)
    assert normalise_slug(once) == once


@PBT_SETTINGS
@given(raw=_case_safe_text, seed=st.integers())
def test_normalise_is_case_insensitive(raw: str, seed: int) -> None:
    """Any two case variants of the same input normalise identically.

    Property 5 (case-insensitivity) — two strings differing only in letter
    casing produce the same normalised slug, so reservation and uniqueness
    comparisons cannot be defeated by casing (R2.8).

    **Validates: Requirements 2.7, 2.8**
    """
    rnd = random.Random(seed)
    variant_a = _random_case_variant(raw, rnd)
    variant_b = _random_case_variant(raw, rnd)

    assert normalise_slug(variant_a) == normalise_slug(variant_b)
    # And both agree with the canonical lower-cased form.
    assert normalise_slug(variant_a) == normalise_slug(raw)


@PBT_SETTINGS
@given(raw=_case_safe_text)
def test_upper_and_lower_normalise_identically(raw: str) -> None:
    """The all-upper and all-lower variants normalise to the same value.

    A direct, explicit witness of case-insensitivity (R2.8) over the case-safe
    alphabet where casing round-trips per character.

    **Validates: Requirements 2.7, 2.8**
    """
    assert normalise_slug(raw.upper()) == normalise_slug(raw.lower())


@PBT_SETTINGS
@given(raw=_any_text)
def test_normalised_value_is_lowercase_and_stripped(raw: str) -> None:
    """The normalised form is lowercase and free of surrounding whitespace.

    Establishes the post-condition R2.7 relies on for stored slugs: the result
    equals its own lower-cased, stripped form.

    **Validates: Requirements 2.7, 2.8**
    """
    result = normalise_slug(raw)
    assert result == result.lower()
    assert result == result.strip()


@PBT_SETTINGS
@given(raw=_case_safe_text)
def test_idempotent_after_case_change(raw: str) -> None:
    """Normalising any case variant is itself idempotent.

    Combines both halves of Property 5: re-normalising the normalised form of a
    case variant is a no-op.

    **Validates: Requirements 2.7, 2.8**
    """
    once = normalise_slug(raw.upper())
    assert normalise_slug(once) == once
