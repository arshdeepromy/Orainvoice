"""Property-based tests for onboarding invite email composition (Task 5.2).

Feature: staff-onboarding-link
Property 5: Onboarding email composition contains the required elements

Exercises the pure composition helper ``compose_onboarding_email`` from
``app.modules.staff.onboarding_delivery`` across many generated organisation
names, staff first names, recipient addresses, and URL tokens. The helper
performs no I/O, so it is fully property-testable without a network/DB.

For every generated input the composed ``EmailMessage`` MUST satisfy:

- the subject is exactly ``Complete your onboarding — {org_name}`` (em dash),
  built the same way the expectation is, so equality holds for any org name
  (including names that themselves contain an em dash or other unusual
  characters) — Requirement 3.2;
- the body opens with a first-name greeting ``Kia ora {first_name},`` where an
  empty/whitespace-only first name falls back to ``there`` — Requirement 3.3;
- the call-to-action links to the onboarding URL, which contains
  ``/onboard/{token}`` — Requirement 3.4.

Validates: Requirements 3.2, 3.3, 3.4
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.staff.onboarding_delivery import (
    build_onboard_url,
    compose_onboarding_email,
)

# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

# Organisation names: varied unicode text, including names that may contain the
# em dash, other punctuation, or be empty. Subject equality must hold for all.
_org_names = st.text(max_size=80)

# Staff first names: varied text, plus explicit empty/whitespace cases that
# must trigger the "there" greeting fallback.
_first_names = st.one_of(
    st.text(max_size=40),
    st.sampled_from(["", "   ", "\t", "\n", " \t \n "]),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyzĀāŌōŪū", min_size=1, max_size=20),
)

# Recipient addresses: realistic-ish, never empty (the composer does not gate
# on this — that is the sender's job — but a plausible address keeps the
# EmailMessage realistic).
_emails = st.builds(
    lambda local, domain: f"{local}@{domain}.example",
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789.", min_size=1, max_size=20),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=12),
)

# Tokens: URL-safe-base64 alphabet only (letters, digits, '-' and '_'), never
# containing a slash — mirroring ``secrets.token_urlsafe`` output.
_tokens = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
    min_size=1,
    max_size=64,
)


def _expected_greeting_name(first_name: str) -> str:
    """Mirror the composer's greeting fallback (empty/whitespace -> 'there')."""
    return (first_name or "").strip() or "there"


# ---------------------------------------------------------------------------
# Property 5: Onboarding email composition contains the required elements
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    org_name=_org_names,
    first_name=_first_names,
    to_email=_emails,
    token=_tokens,
)
def test_onboarding_email_composition_contains_required_elements(
    org_name: str,
    first_name: str,
    to_email: str,
    token: str,
):
    """The composed invite email carries the required subject, greeting, and CTA.

    **Validates: Requirements 3.2, 3.3, 3.4**
    """
    onboard_url = build_onboard_url(token)
    message = compose_onboarding_email(
        to_email=to_email,
        to_name=first_name,
        staff_first_name=first_name,
        org_name=org_name,
        onboard_url=onboard_url,
    )

    # R3.2 — subject is exactly the documented format (em dash). Built the same
    # way the composer does, so equality holds even when org_name itself
    # contains an em dash or other unusual characters.
    assert message.subject == f"Complete your onboarding — {org_name}"

    # R3.3 — body opens with a first-name greeting; empty/whitespace first
    # names fall back to "there".
    greeting_name = _expected_greeting_name(first_name)
    expected_greeting = f"Kia ora {greeting_name},"
    assert message.text_body.startswith(expected_greeting)
    assert expected_greeting in message.text_body

    # R3.4 — the CTA links to the onboarding URL, which targets /onboard/{token}.
    assert onboard_url == build_onboard_url(token)
    assert f"/onboard/{token}" in onboard_url
    # The raw URL appears verbatim in the text body, and the path appears in the
    # rendered HTML CTA button (HTML may escape, but the path itself is safe).
    assert onboard_url in message.text_body
    assert f"/onboard/{token}" in message.html_body


@settings(max_examples=100)
@given(org_name=_org_names, token=_tokens)
def test_onboarding_email_empty_first_name_greets_there(org_name: str, token: str):
    """An empty or whitespace-only first name produces the 'there' greeting.

    **Validates: Requirements 3.3**
    """
    onboard_url = build_onboard_url(token)
    message = compose_onboarding_email(
        to_email="staff@example.example",
        to_name="",
        staff_first_name="   ",
        org_name=org_name,
        onboard_url=onboard_url,
    )
    assert message.text_body.startswith("Kia ora there,")
