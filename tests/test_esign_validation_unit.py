"""Unit tests for the pure esignatures validators (task 4.1).

Covers ``is_pdf``, ``is_valid_email``, ``validate_recipients`` and
``secret_compare`` — all pure functions, no I/O.

Requirements: 3.3, 3.4, 4.2, 4.3, 4.6, 8.1
"""

from __future__ import annotations

from app.modules.esignatures.validation import (
    CODE_INVALID_RECIPIENT_EMAIL,
    CODE_NO_RECIPIENTS,
    is_pdf,
    is_valid_email,
    secret_compare,
    validate_recipients,
)


# ---------------------------------------------------------------------------
# is_pdf
# ---------------------------------------------------------------------------


def test_is_pdf_accepts_pdf_magic_bytes():
    assert is_pdf(b"%PDF-1.7\n...rest of file...") is True


def test_is_pdf_accepts_exact_magic_prefix():
    assert is_pdf(b"%PDF") is True


def test_is_pdf_accepts_bytearray_and_memoryview():
    assert is_pdf(bytearray(b"%PDF-1.4")) is True
    assert is_pdf(memoryview(b"%PDF-1.4")) is True


def test_is_pdf_rejects_non_pdf_bytes():
    assert is_pdf(b"PK\x03\x04 this is a zip") is False
    assert is_pdf(b"\xff\xd8\xff jpeg") is False


def test_is_pdf_rejects_empty_and_none():
    assert is_pdf(b"") is False
    assert is_pdf(None) is False


def test_is_pdf_rejects_non_bytes():
    assert is_pdf("%PDF") is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# is_valid_email
# ---------------------------------------------------------------------------


def test_is_valid_email_accepts_typical_addresses():
    assert is_valid_email("alice@example.com") is True
    assert is_valid_email("bob.smith+tag@sub.example.co.nz") is True


def test_is_valid_email_trims_surrounding_whitespace():
    assert is_valid_email("  alice@example.com  ") is True


def test_is_valid_email_rejects_malformed():
    assert is_valid_email("not-an-email") is False
    assert is_valid_email("missing@domain") is False
    assert is_valid_email("@example.com") is False
    assert is_valid_email("a@b.c") is False  # TLD too short


def test_is_valid_email_rejects_empty_and_non_string():
    assert is_valid_email("") is False
    assert is_valid_email("   ") is False
    assert is_valid_email(None) is False  # type: ignore[arg-type]
    assert is_valid_email(123) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# validate_recipients
# ---------------------------------------------------------------------------


def test_validate_recipients_rejects_empty_list():
    result = validate_recipients([])
    assert result.ok is False
    assert result.code == CODE_NO_RECIPIENTS


def test_validate_recipients_rejects_none():
    result = validate_recipients(None)
    assert result.ok is False
    assert result.code == CODE_NO_RECIPIENTS


def test_validate_recipients_accepts_all_valid_mappings():
    recipients = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "Bob", "email": "bob@example.com"},
    ]
    result = validate_recipients(recipients)
    assert result.ok is True
    assert result.code is None


def test_validate_recipients_identifies_first_invalid_email():
    recipients = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "Bad One", "email": "nope"},
        {"name": "Carol", "email": "also-bad"},
    ]
    result = validate_recipients(recipients)
    assert result.ok is False
    assert result.code == CODE_INVALID_RECIPIENT_EMAIL
    # FIRST offending recipient identified, not the second.
    assert result.index == 1
    assert result.name == "Bad One"
    assert "Bad One" in (result.message or "")


def test_validate_recipients_supports_attribute_objects():
    class R:
        def __init__(self, name, email):
            self.name = name
            self.email = email

    result = validate_recipients([R("Dave", "dave@example.com")])
    assert result.ok is True

    bad = validate_recipients([R("Eve", "eve@invalid")])
    assert bad.ok is False
    assert bad.code == CODE_INVALID_RECIPIENT_EMAIL
    assert bad.name == "Eve"


def test_validate_recipients_falls_back_when_name_missing():
    result = validate_recipients([{"email": "bogus"}])
    assert result.ok is False
    assert result.code == CODE_INVALID_RECIPIENT_EMAIL
    assert result.name is None
    # Message still humanized using the email fallback.
    assert "bogus" in (result.message or "")


# ---------------------------------------------------------------------------
# secret_compare
# ---------------------------------------------------------------------------


def test_secret_compare_matches_identical_strings():
    assert secret_compare("super-secret-value", "super-secret-value") is True


def test_secret_compare_rejects_mismatch():
    assert secret_compare("super-secret-value", "wrong") is False


def test_secret_compare_is_case_sensitive_and_verbatim():
    assert secret_compare("Secret", "secret") is False
    assert secret_compare("secret ", "secret") is False


def test_secret_compare_handles_unicode():
    assert secret_compare("sécrét-😀", "sécrét-😀") is True
    assert secret_compare("sécrét-😀", "secret") is False


def test_secret_compare_rejects_none_and_non_strings():
    assert secret_compare(None, "x") is False
    assert secret_compare("x", None) is False
    assert secret_compare(None, None) is False
    assert secret_compare(b"x", b"x") is False  # type: ignore[arg-type]
