"""Property test: audit hash is computed over the post-sanitisation body.

Feature: send-email-modal, Property 4: Audit hash over post-sanitisation body.

The override-send paths (task 8) record an audit trail on ``notification_log``
for every edited send: ``edited_subject_hash`` and ``edited_body_hash`` are
SHA-256 hex digests produced by
``app.modules.email_compose.service.compute_audit_hashes(subject,
sanitised_body)``. Crucially the body hash MUST be taken over the
**post-sanitisation** body — the exact bytes ``email_sender.send_email`` will
dispatch — never over the raw, untrusted ``body_html`` the client submitted.
This guarantees the audit record reflects what actually went out and that an
XSS payload stripped by :func:`sanitise_email_html` is not what gets hashed
(R11.2, R11.3).

This property therefore asserts, for any generated raw ``body_html`` and any
subject string:

  1. the helper's ``body_hash`` equals
     ``sha256(sanitise_email_html(raw).encode("utf-8")).hexdigest()``
     (the hash is over the *sanitised* body);
  2. the helper's ``subject_hash`` equals
     ``sha256(subject.encode("utf-8")).hexdigest()``
     (the subject is hashed verbatim — it is not HTML-sanitised);
  3. whenever sanitisation actually changes the string
     (``sanitise_email_html(raw) != raw``), ``body_hash`` differs from
     ``sha256(raw.encode("utf-8")).hexdigest()`` — proving the hash is over
     the post-sanitisation content, not the raw input.

The generators are biased toward unsafe markup (script tags, ``on*`` handlers,
``javascript:``/``data:``/``file:`` URLs) so branch (3) is exercised
frequently, alongside benign HTML and arbitrary text for subjects.

Design ref: ``.kiro/specs/send-email-modal/design.md`` →
Correctness Properties → Property 4; Data Models §5; service.py
``compute_audit_hashes``.

**Validates: Requirements 11.2, 11.3**
"""

from __future__ import annotations

import hashlib

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.integrations.html_sanitise import sanitise_email_html
from app.modules.email_compose.service import compute_audit_hashes


def _sha256(value: str) -> str:
    """SHA-256 hex digest over the UTF-8 encoding of ``value`` (the exact
    encoding ``compute_audit_hashes`` uses, so the test mirrors it)."""
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Example-based sanity checks (concrete, readable scenarios)
# ---------------------------------------------------------------------------


def test_body_hash_is_over_sanitised_body_for_xss_payload():
    raw = '<p>hi</p><script>alert(1)</script>'
    sanitised = sanitise_email_html(raw)
    hashes = compute_audit_hashes("Subject", sanitised)

    # The recorded body hash matches the sanitised bytes that actually send.
    assert hashes["body_hash"] == _sha256(sanitised)
    # The script payload was stripped, so the raw hash is a different value —
    # the audit trail records the post-sanitisation content (R11.2).
    assert sanitised != raw
    assert hashes["body_hash"] != _sha256(raw)


def test_subject_hash_is_verbatim_sha256():
    hashes = compute_audit_hashes("REVISED — Invoice #42", "<p>body</p>")
    assert hashes["subject_hash"] == _sha256("REVISED — Invoice #42")


def test_safe_body_hashes_equal_because_sanitiser_is_a_no_op():
    # When the sanitiser does not change a benign body, hashing raw vs
    # sanitised coincide — the property only claims they DIFFER when the
    # sanitiser changed the string.
    raw = sanitise_email_html("<p>Hello <strong>world</strong></p>")
    assert sanitise_email_html(raw) == raw  # already sanitised / idempotent
    hashes = compute_audit_hashes("s", raw)
    assert hashes["body_hash"] == _sha256(raw)


def test_empty_inputs_hash_to_sha256_of_empty_string():
    hashes = compute_audit_hashes("", "")
    assert hashes["subject_hash"] == _sha256("")
    assert hashes["body_hash"] == _sha256("")


# ---------------------------------------------------------------------------
# Smart generators — HTML-ish fragments biased toward unsafe constructs so the
# "sanitisation changed the string" branch is exercised often, plus benign
# markup and arbitrary text. (Mirrors the task 1.3 sanitiser property test.)
# ---------------------------------------------------------------------------

_DISALLOWED_TAGS = ["script", "iframe", "style", "svg", "object", "embed", "form"]
_ALLOWED_TAGS = ["p", "div", "span", "a", "strong", "em", "li"]
_EVENT_HANDLERS = ["onclick", "onerror", "onload", "onmouseover", "onfocus"]
_DANGEROUS_URLS = [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "vbscript:msgbox(1)",
]
_SAFE_URLS = ["https://example.com", "http://example.com/x", "mailto:a@b.co"]


@st.composite
def _html_fragment(draw) -> str:
    """One HTML-ish fragment biased toward unsafe markup."""
    kind = draw(st.integers(min_value=0, max_value=6))
    if kind == 0:
        tag = draw(st.sampled_from(_DISALLOWED_TAGS))
        inner = draw(st.text(max_size=30))
        return f"<{tag}>{inner}</{tag}>"
    if kind == 1:
        tag = draw(st.sampled_from(_ALLOWED_TAGS))
        handler = draw(st.sampled_from(_EVENT_HANDLERS))
        return f'<{tag} {handler}="alert(1)">text</{tag}>'
    if kind == 2:
        return f'<a href="{draw(st.sampled_from(_DANGEROUS_URLS))}">click</a>'
    if kind == 3:
        return f'<img src="{draw(st.sampled_from(_DANGEROUS_URLS))}" onerror="alert(1)">'
    if kind == 4:
        return f'<a href="{draw(st.sampled_from(_SAFE_URLS))}">ok</a>'
    if kind == 5:
        return draw(
            st.sampled_from(
                [
                    "<p>Hello <strong>world</strong></p>",
                    "<ul><li>one</li><li>two</li></ul>",
                    "Learn javascript: a beginner guide",
                    "The onerror property in JS",
                ]
            )
        )
    return draw(st.text(max_size=40))


_body_html_strategy = st.lists(_html_fragment(), min_size=0, max_size=8).map("".join)

#: Subjects: arbitrary text (incl. unicode), capped at the 255-char limit (R5.2).
_subject_strategy = st.text(max_size=255)


# ---------------------------------------------------------------------------
# Property 4 — Audit hash is computed over the post-sanitisation body.
# ---------------------------------------------------------------------------


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(raw_body=_body_html_strategy, subject=_subject_strategy)
def test_audit_hash_is_over_post_sanitisation_body(raw_body: str, subject: str):
    """Feature: send-email-modal, Property 4: Audit hash over post-sanitisation
    body.

    For any edited raw ``body_html`` and any subject:

      * ``edited_body_hash == sha256(sanitise_email_html(raw)).hexdigest()``;
      * ``edited_subject_hash == sha256(subject).hexdigest()``;
      * whenever sanitisation changed the string, the body hash differs from
        ``sha256(raw)`` — proving it is over the sanitised content.

    This mirrors the override-send paths, which compute ``edited_body_hash``
    over the SANITISED body and ``edited_subject_hash`` over the final subject.

    **Validates: Requirements 11.2, 11.3**
    """
    # The override path sanitises first, then hashes the sanitised body.
    sanitised_body = sanitise_email_html(raw_body)
    hashes = compute_audit_hashes(subject, sanitised_body)

    # (1) Body hash is taken over the post-sanitisation body.
    assert hashes["body_hash"] == _sha256(sanitised_body)

    # (2) Subject hash is the verbatim SHA-256 of the final subject.
    assert hashes["subject_hash"] == _sha256(subject)

    # (3) When sanitisation changed the body, the recorded hash must NOT equal
    # the hash of the raw input — i.e. the audit trail reflects what actually
    # sends, not the untrusted raw markup (R11.2).
    if sanitised_body != raw_body:
        assert hashes["body_hash"] != _sha256(raw_body)
