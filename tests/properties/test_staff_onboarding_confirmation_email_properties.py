"""Property-based tests for the staff onboarding **confirmation** email.

Property 25 — Confirmation email composition contains org name and thank-you.

The function under test is ``compose_confirmation_email`` in
``app.modules.staff.onboarding_delivery``. It is a PURE composition helper
(no I/O) returning an :class:`~app.integrations.email_sender.EmailMessage`
with:

- subject ``Thanks for completing your onboarding — {org_name}``;
- a ``Kia ora {first_name},`` greeting that falls back to ``"there"`` when the
  first name is empty/whitespace;
- a friendly thank-you line that names the organisation.

Across many generated org names / staff first names / staff emails this
asserts:

- the organisation name appears in the composed message (subject and/or body);
- a friendly thank-you is present (subject "Thanks" / body "Thank you");
- the greeting addresses the staff member by first name, or uses the
  ``"there"`` fallback for empty/whitespace first names.

**Validates: Requirements 15.2**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.integrations.email_sender import EmailMessage
from app.modules.staff.onboarding_delivery import compose_confirmation_email

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Organisation names: realistic, non-empty text (no surrounding whitespace so a
# substring assertion against the interpolated subject/body is meaningful).
_org_names = st.text(min_size=1, max_size=60).map(str.strip).filter(lambda s: s != "")

# First names: a mix of ordinary names AND empty/whitespace-only values that
# must trigger the "there" fallback.
_non_empty_first_names = (
    st.text(min_size=1, max_size=40).map(str.strip).filter(lambda s: s != "")
)
_empty_first_names = st.text(alphabet=" \t\n\r", max_size=5)  # "" or whitespace-only
_first_names = st.one_of(_non_empty_first_names, _empty_first_names)

# Staff emails: kept simple — varied but plausible address shapes.
_emails = st.emails()


def _expected_greeting_name(first_name: str) -> str:
    """Mirror the composer's greeting rule: stripped first name or 'there'."""
    return (first_name or "").strip() or "there"


# ===========================================================================
# Feature: staff-onboarding-link, Property 25: Confirmation email composition
# contains org name and thank-you
# ===========================================================================


class TestProperty25ConfirmationEmailComposition:
    """``compose_confirmation_email`` names the org and thanks the staff member."""

    @given(org_name=_org_names, first_name=_first_names, email=_emails)
    @settings(max_examples=200, deadline=None)
    def test_org_name_present(
        self, org_name: str, first_name: str, email: str
    ) -> None:
        """Property 25 — the organisation name appears in the composed message
        (subject and/or body) (R15.2)."""
        msg = compose_confirmation_email(
            staff_email=email,
            staff_first_name=first_name,
            org_name=org_name,
        )
        assert isinstance(msg, EmailMessage)
        assert (
            org_name in msg.subject
            or org_name in msg.text_body
            or org_name in msg.html_body
        ), f"org name {org_name!r} missing from composed confirmation email"

    @given(org_name=_org_names, first_name=_first_names, email=_emails)
    @settings(max_examples=200, deadline=None)
    def test_friendly_thank_you_present(
        self, org_name: str, first_name: str, email: str
    ) -> None:
        """Property 25 — a friendly thank-you greeting is present (R15.2)."""
        msg = compose_confirmation_email(
            staff_email=email,
            staff_first_name=first_name,
            org_name=org_name,
        )
        haystack = f"{msg.subject}\n{msg.text_body}".lower()
        assert ("thank you" in haystack) or ("thanks" in haystack), (
            "expected a friendly thank-you in the confirmation email"
        )

    @given(org_name=_org_names, first_name=_first_names, email=_emails)
    @settings(max_examples=200, deadline=None)
    def test_greeting_addresses_staff_member(
        self, org_name: str, first_name: str, email: str
    ) -> None:
        """Property 25 — the greeting addresses the staff member by first name,
        falling back to ``there`` for empty/whitespace names (R15.2)."""
        msg = compose_confirmation_email(
            staff_email=email,
            staff_first_name=first_name,
            org_name=org_name,
        )
        greeting_name = _expected_greeting_name(first_name)
        assert f"Kia ora {greeting_name}," in msg.text_body, (
            f"expected greeting for {greeting_name!r} in body"
        )
        # Empty/whitespace first names must use the friendly fallback.
        if not (first_name or "").strip():
            assert "Kia ora there," in msg.text_body


# ---------------------------------------------------------------------------
# Example tests — concrete shape checks
# ---------------------------------------------------------------------------


def test_example_subject_and_thank_you_for_named_staff() -> None:
    """A named staff member gets a first-name greeting, thank-you, and org name."""
    msg = compose_confirmation_email(
        staff_email="aroha@example.com",
        staff_first_name="Aroha",
        org_name="Kauri Auto Ltd",
    )
    assert msg.subject == "Thanks for completing your onboarding — Kauri Auto Ltd"
    assert "Kia ora Aroha," in msg.text_body
    assert "Thank you for completing your onboarding with Kauri Auto Ltd" in msg.text_body
    assert msg.to_email == "aroha@example.com"


def test_example_blank_first_name_uses_there_fallback() -> None:
    """A blank/whitespace first name falls back to the friendly 'there'."""
    msg = compose_confirmation_email(
        staff_email="staff@example.com",
        staff_first_name="   ",
        org_name="Rata Electrical",
    )
    assert "Kia ora there," in msg.text_body
    assert "Rata Electrical" in msg.text_body
