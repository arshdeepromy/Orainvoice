"""Property-based test for the onboarding-email destination gate (Task 6.4).

Feature: staff-onboarding-link
Property 6: Onboarding email requires a destination address

The onboarding invite is useless without somewhere to send it, so the system
gates on a **non-empty (after strip) email** before doing any work. The exact
same predicate — ``not staff.email or not staff.email.strip()`` — guards two
places:

- the admin ``POST /api/v2/staff`` handler (``create_staff`` in ``router.py``),
  which raises ``422 onboarding_email_required`` BEFORE calling
  ``onboarding_tokens.mint(...)`` — so a blank email mints **no token**; and
- ``onboarding_delivery.send_onboarding_email`` (belt-and-braces), which
  early-returns ``OnboardingDeliveryResult(ok=False,
  error_code="onboarding_email_required")`` BEFORE composing or dispatching
  anything — so a blank email sends **no email**.

This test exercises the real ``send_onboarding_email`` gate across many
generated emails (``None``, empty, whitespace-only, and valid non-empty
addresses). ``send_email`` (the provider dispatch) and ``_load_org_name`` (the
only DB read) are mocked so the property is pure and needs no network/DB. For
every example we assert:

- acceptance matches the shared gate predicate ``bool(email and
  email.strip())`` exactly — the same boolean the router uses to decide whether
  to mint a token;
- a **rejected** (blank/whitespace/None) email yields ``ok is False`` with
  ``error_code == "onboarding_email_required"`` AND the sender is **never
  invoked** (no email dispatched, mirroring "no token minted");
- an **accepted** (non-empty) email yields ``ok is True`` AND the sender is
  invoked exactly once.

Validates: Requirements 1.2
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from app.integrations.email_sender import SendResult
from app.modules.staff import onboarding_delivery
from app.modules.staff.onboarding_delivery import (
    ERROR_NO_EMAIL,
    OnboardingDeliveryResult,
    send_onboarding_email,
)

# ---------------------------------------------------------------------------
# Email generators — cover the whole gate input space.
# ---------------------------------------------------------------------------

# Whitespace-only strings of various kinds (these MUST be rejected: the gate
# strips before testing for emptiness).
_whitespace_only = st.text(alphabet=" \t\n\r\f\v", min_size=1, max_size=6)

# Blank / missing destinations the gate must reject: None, "", and
# whitespace-only.
_blank_emails = st.one_of(
    st.none(),
    st.just(""),
    _whitespace_only,
)

# Non-empty (after strip) destinations the gate must accept. A plain non-blank
# string is enough for the gate (it does not validate address shape), so we mix
# realistic addresses with arbitrary non-blank text, including values that have
# surrounding whitespace but a non-blank core (e.g. "  a@b.com  ").
_realistic_emails = st.emails()
_arbitrary_nonblank = (
    st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")
)
_padded_nonblank = st.builds(
    lambda pad_l, core, pad_r: f"{pad_l}{core}{pad_r}",
    st.text(alphabet=" \t", max_size=3),
    st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != ""),
    st.text(alphabet=" \t", max_size=3),
)
_nonempty_emails = st.one_of(
    _realistic_emails, _arbitrary_nonblank, _padded_nonblank
)

# The full space: blanks and non-blanks, so the property covers both branches.
_any_email = st.one_of(_blank_emails, _nonempty_emails)


def _make_staff(email: str | None) -> SimpleNamespace:
    """A minimal StaffMember-shaped object the delivery helper can read.

    ``send_onboarding_email`` only touches ``email``, ``first_name``,
    ``last_name``, ``name`` and ``id`` — a ``SimpleNamespace`` duck-types
    cleanly without a DB row.
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        email=email,
        first_name="Aroha",
        last_name="Ngata",
        name="Aroha Ngata",
    )


def _gate_accepts(email: str | None) -> bool:
    """Mirror the exact gate predicate used by the router AND the delivery
    helper: ``not staff.email or not staff.email.strip()`` rejects, so an email
    is accepted iff it is truthy and non-blank after stripping."""
    return bool(email and email.strip())


async def _run_send(email: str | None) -> tuple[OnboardingDeliveryResult, int]:
    """Call ``send_onboarding_email`` with the provider + org-name read mocked.

    Returns the delivery result and the number of times ``send_email`` was
    invoked (0 ⇒ nothing dispatched, mirroring "no token delivered").
    """
    fake_send = AsyncMock(
        return_value=SendResult(success=True, message_id="msg-test-123")
    )
    fake_load_org = AsyncMock(return_value="Kauri Auto Ltd")

    staff = _make_staff(email)
    db = object()  # never used for I/O — both DB-touching calls are mocked.

    with patch.object(onboarding_delivery, "send_email", fake_send), patch.object(
        onboarding_delivery, "_load_org_name", fake_load_org
    ):
        result = await send_onboarding_email(
            db,
            org_id=uuid.uuid4(),
            staff=staff,
            token="tok_" + uuid.uuid4().hex,
        )
    return result, fake_send.await_count


# ===========================================================================
# Property 6: Onboarding email requires a destination address
# ===========================================================================


@settings(max_examples=200, deadline=None)
@given(email=_any_email)
def test_onboarding_email_requires_destination(email: str | None):
    """Acceptance tracks the non-empty-after-strip gate; blanks mint/send
    nothing.

    **Validates: Requirements 1.2**
    """
    result, send_calls = asyncio.run(_run_send(email))
    accepted = _gate_accepts(email)

    if accepted:
        # Non-empty destination → the invite is dispatched exactly once.
        assert result.ok is True, (
            f"non-empty email {email!r} should be accepted and delivered"
        )
        assert send_calls == 1, (
            f"accepted email {email!r} must dispatch exactly one send"
        )
    else:
        # Blank/whitespace/None → rejected with the required-email code and
        # NOTHING is dispatched (no token delivered, R1.2).
        assert result.ok is False, (
            f"blank email {email!r} must be rejected"
        )
        assert result.error_code == ERROR_NO_EMAIL == "onboarding_email_required"
        assert send_calls == 0, (
            f"rejected email {email!r} must not dispatch any send "
            "(no token delivered)"
        )


@settings(max_examples=150, deadline=None)
@given(email=_blank_emails)
def test_blank_emails_never_dispatch(email: str | None):
    """Every blank/whitespace/None destination is rejected before any send.

    **Validates: Requirements 1.2**
    """
    result, send_calls = asyncio.run(_run_send(email))
    assert result.ok is False
    assert result.error_code == "onboarding_email_required"
    assert send_calls == 0


@settings(max_examples=150, deadline=None)
@given(email=_nonempty_emails)
def test_nonempty_emails_are_accepted(email: str):
    """Every non-empty (after strip) destination is accepted and dispatched.

    **Validates: Requirements 1.2**
    """
    result, send_calls = asyncio.run(_run_send(email))
    assert result.ok is True
    assert result.error_code is None
    assert send_calls == 1


# ---------------------------------------------------------------------------
# Example tests — concrete boundary cases.
# ---------------------------------------------------------------------------


def test_example_none_email_rejected() -> None:
    """A missing email (None) is rejected with no dispatch."""
    result, send_calls = asyncio.run(_run_send(None))
    assert result.ok is False
    assert result.error_code == "onboarding_email_required"
    assert send_calls == 0


def test_example_whitespace_only_email_rejected() -> None:
    """A whitespace-only email is rejected with no dispatch."""
    result, send_calls = asyncio.run(_run_send("   \t  "))
    assert result.ok is False
    assert result.error_code == "onboarding_email_required"
    assert send_calls == 0


def test_example_valid_email_accepted() -> None:
    """A normal address is accepted and dispatched once."""
    result, send_calls = asyncio.run(_run_send("aroha@example.com"))
    assert result.ok is True
    assert send_calls == 1
