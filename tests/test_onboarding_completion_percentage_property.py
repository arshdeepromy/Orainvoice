"""Property-based test: onboarding completion-percentage computation.

# Feature: staff-onboarding-link, Property 22: Completion percentage is
# deterministic, total, bounded, and monotonic

**Validates: Requirements 13.3, 13.4**

The onboarding-link admin status surfaces a section-weighted Completion_Percentage
computed server-side by the pure, side-effect-free helper
``compute_completion_percentage(draft) -> int`` in
``app/modules/staff/onboarding_validation.py``.

The form has five equally-weighted (20%) sections, each decided by a crisp
boolean predicate over the draft fields:

* **Personal** — ``last_name`` AND ``phone`` both present;
* **Bank** — ``bank_account_number`` present (or the resume-mode ``has_bank`` flag);
* **IRD/Tax** — (``ird_number`` present OR ``has_ird``) AND ``tax_code`` present;
* **Residency** — ``residency_type`` set; visa types (``work_visa`` /
  ``student_visa``) additionally require ``visa_expiry_date``;
* **Documents** — ``documents_staged_count`` is an int > 0.

R13.3 / R13.4 require the figure to be:

* **deterministic** — same draft ⇒ same integer (asserted by calling twice);
* **total** — defined for every draft including ``None`` / empty / partial,
  never raising;
* **bounded** — always in ``[0, 100]``;
* **monotonic non-decreasing** — filling additional previously-unset fields
  never lowers the percentage.

For the monotonicity property we build a draft and a *field superset* safely:
the superset only ADDS values for fields that were absent in the base draft and
never mutates an existing ``residency_type`` (in particular never downgrades a
non-visa value to a visa value, which would introduce the expiry requirement
and could otherwise lower the score). This is the natural superset-fill
interpretation, which is monotone non-decreasing.

This is a pure in-memory computation — no database or storage is involved.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.staff.onboarding_validation import compute_completion_percentage

# ---------------------------------------------------------------------------
# Hypothesis settings (≥100 iterations) — pure in-memory computation.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

_RESIDENCY_TYPES = (
    "citizen",
    "permanent_resident",
    "work_visa",
    "student_visa",
    "other",
)
_TAX_CODES = ("M", "ME", "SB", "S", "SH", "ST", "WT", "ND")

# The fields that influence the completion percentage. ``has_bank`` / ``has_ird``
# are the resume-mode presence flags surfaced in place of masked secrets.
_COMPLETION_FIELDS = (
    "last_name",
    "phone",
    "bank_account_number",
    "has_bank",
    "ird_number",
    "has_ird",
    "tax_code",
    "residency_type",
    "visa_expiry_date",
    "documents_staged_count",
)

# Extra noise keys that must never affect the score (totality / robustness).
_NOISE_KEYS = (
    "emergency_contact_name",
    "emergency_contact_phone",
    "student_loan",
    "kiwisaver_enrolled",
    "email",
    "first_name",
)


# ---------------------------------------------------------------------------
# Value strategies
# ---------------------------------------------------------------------------

# Text guaranteed non-empty after stripping (a "present" textual value).
_present_text = st.builds(
    lambda pad_l, core, pad_r: f"{pad_l}{core}{pad_r}",
    st.text(alphabet=" \t", max_size=2),
    st.text(
        alphabet=st.characters(blacklist_categories=("Cc", "Cs", "Zs", "Zl", "Zp")),
        min_size=1,
        max_size=12,
    ).filter(lambda s: s.strip() != ""),
    st.text(alphabet=" \t", max_size=2),
)

# Arbitrary value used to stress totality: anything at all.
_arbitrary_value = st.one_of(
    st.none(),
    st.just(""),
    st.text(alphabet=" \t\r\n", min_size=1, max_size=4),  # whitespace-only ⇒ absent
    _present_text,
    st.booleans(),
    st.integers(min_value=-5, max_value=10),
    st.dates(),
    st.floats(allow_nan=False, allow_infinity=False, width=16),
)


@st.composite
def _arbitrary_draft(draw):
    """A wholly arbitrary draft: random subset of known + noise keys, any values."""
    keys = draw(
        st.lists(
            st.sampled_from(_COMPLETION_FIELDS + _NOISE_KEYS),
            unique=True,
            max_size=len(_COMPLETION_FIELDS) + len(_NOISE_KEYS),
        )
    )
    return {k: draw(_arbitrary_value) for k in keys}


# Concrete "present/complete" value for each completion field, used to build
# monotone (base, superset) pairs.
def _complete_value(draw, field):
    if field in ("last_name", "phone", "bank_account_number", "ird_number"):
        return draw(_present_text)
    if field in ("has_bank", "has_ird"):
        return True
    if field == "tax_code":
        return draw(st.sampled_from(_TAX_CODES))
    if field == "residency_type":
        return draw(st.sampled_from(_RESIDENCY_TYPES))
    if field == "visa_expiry_date":
        return draw(st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31)))
    if field == "documents_staged_count":
        return draw(st.integers(min_value=1, max_value=5))
    raise AssertionError(f"unexpected field {field!r}")  # pragma: no cover


@st.composite
def _monotone_pair(draw):
    """Build a (base, superset) pair where superset only ADDS absent fields.

    Each completion field is independently assigned to one of three buckets:
      * ``"absent"`` — present in neither draft;
      * ``"base"``   — present in BOTH base and superset (value never changes);
      * ``"super"``  — present in the superset ONLY (a newly-filled field).

    Because base values are copied verbatim into the superset and only absent
    fields are added, the superset is a true field-presence superset of base.
    In particular an existing ``residency_type`` is never mutated, so a non-visa
    value is never downgraded to a visa value — preserving monotonicity.
    """
    # Precompute a concrete value for every field so base/super share values.
    values = {f: _complete_value(draw, f) for f in _COMPLETION_FIELDS}
    buckets = draw(
        st.fixed_dictionaries(
            {f: st.sampled_from(("absent", "base", "super")) for f in _COMPLETION_FIELDS}
        )
    )
    base = {f: values[f] for f, b in buckets.items() if b == "base"}
    superset = {f: values[f] for f, b in buckets.items() if b in ("base", "super")}

    # Sprinkle identical noise keys into both so they cannot explain a delta.
    noise = {k: draw(_arbitrary_value) for k in draw(st.lists(st.sampled_from(_NOISE_KEYS), unique=True))}
    base.update(noise)
    superset.update(noise)
    return base, superset


# ---------------------------------------------------------------------------
# Property 22: deterministic, total, bounded, monotonic
# ---------------------------------------------------------------------------


class TestProperty22CompletionPercentage:
    """Property 22: Completion percentage is deterministic, total, bounded, monotonic.

    # Feature: staff-onboarding-link, Property 22

    **Validates: Requirements 13.3, 13.4**
    """

    @PBT_SETTINGS
    @given(draft=_arbitrary_draft())
    def test_deterministic(self, draft):
        """Same draft ⇒ same integer on repeated calls (deterministic).

        **Validates: Requirements 13.3**
        """
        first = compute_completion_percentage(draft)
        second = compute_completion_percentage(draft)
        assert first == second

    @PBT_SETTINGS
    @given(draft=_arbitrary_draft())
    def test_total_returns_int(self, draft):
        """Defined for any draft without raising, returning an int (total).

        **Validates: Requirements 13.3, 13.4**
        """
        result = compute_completion_percentage(draft)
        assert isinstance(result, int) and not isinstance(result, bool)

    @PBT_SETTINGS
    @given(draft=st.one_of(st.none(), _arbitrary_draft()))
    def test_bounded(self, draft):
        """Result is always within [0, 100] (and a multiple of 20).

        **Validates: Requirements 13.4**
        """
        result = compute_completion_percentage(draft)
        assert 0 <= result <= 100
        assert result % 20 == 0

    @PBT_SETTINGS
    @given(pair=_monotone_pair())
    def test_monotonic_non_decreasing(self, pair):
        """Filling more (previously-absent) fields never lowers the score.

        **Validates: Requirements 13.4**
        """
        base, superset = pair
        assert compute_completion_percentage(superset) >= compute_completion_percentage(base)

    # --- Explicit examples (non-property, co-located) -----------------------

    def test_none_is_zero(self):
        """A ``None`` draft is total and scores 0.

        **Validates: Requirements 13.3, 13.4**
        """
        assert compute_completion_percentage(None) == 0

    def test_empty_is_zero(self):
        """An empty draft scores 0.

        **Validates: Requirements 13.4**
        """
        assert compute_completion_percentage({}) == 0

    def test_all_sections_complete_is_100(self):
        """A fully-populated draft scores 100.

        **Validates: Requirements 13.4**
        """
        draft = {
            "last_name": "Smith",
            "phone": "021123456",
            "bank_account_number": "01-0123-0123456-00",
            "ird_number": "123456789",
            "tax_code": "M",
            "residency_type": "citizen",
            "documents_staged_count": 2,
        }
        assert compute_completion_percentage(draft) == 100

    def test_attribute_object_draft_supported(self):
        """An attribute-bearing object draft is accepted (parity with dict).

        **Validates: Requirements 13.3, 13.4**
        """
        obj = SimpleNamespace(last_name="Smith", phone="021123456")
        assert compute_completion_percentage(obj) == 20

    def test_visa_without_expiry_not_complete(self):
        """A visa residency without an expiry date does not complete the section.

        **Validates: Requirements 13.4**
        """
        without = {"residency_type": "work_visa"}
        with_expiry = {
            "residency_type": "work_visa",
            "visa_expiry_date": date.today() + timedelta(days=30),
        }
        assert compute_completion_percentage(without) == 0
        assert compute_completion_percentage(with_expiry) == 20

    def test_datetime_now_unused_but_safe(self):
        """Sanity: computation is independent of wall-clock time.

        **Validates: Requirements 13.3**
        """
        draft = {"last_name": "A", "phone": "B"}
        before = compute_completion_percentage(draft)
        _ = datetime.now()
        after = compute_completion_percentage(draft)
        assert before == after == 20
