"""Unit tests for HA heartbeat HMAC signing and verification.

Requirements: 11.4, 11.5
"""

from __future__ import annotations

from app.modules.ha.hmac_utils import compute_hmac, verify_hmac


# ── compute_hmac ─────────────────────────────────────────────────────


def test_compute_hmac_returns_hex_string():
    sig = compute_hmac({"node": "pi-1"}, "secret")
    assert isinstance(sig, str)
    # SHA-256 hex digest is always 64 hex chars
    assert len(sig) == 64
    assert all(c in "0123456789abcdef" for c in sig)


def test_compute_hmac_deterministic():
    """Same payload + secret always produces the same signature."""
    payload = {"a": 1, "b": "two"}
    sig1 = compute_hmac(payload, "s3cret")
    sig2 = compute_hmac(payload, "s3cret")
    assert sig1 == sig2


def test_compute_hmac_key_order_independent():
    """Dict key insertion order does not affect the signature."""
    sig1 = compute_hmac({"z": 1, "a": 2}, "key")
    sig2 = compute_hmac({"a": 2, "z": 1}, "key")
    assert sig1 == sig2


def test_compute_hmac_different_secrets_differ():
    payload = {"x": 42}
    sig_a = compute_hmac(payload, "secret-A")
    sig_b = compute_hmac(payload, "secret-B")
    assert sig_a != sig_b


def test_compute_hmac_different_payloads_differ():
    sig_a = compute_hmac({"x": 1}, "key")
    sig_b = compute_hmac({"x": 2}, "key")
    assert sig_a != sig_b


# ── verify_hmac ──────────────────────────────────────────────────────


def test_verify_hmac_correct_signature():
    payload = {"role": "primary", "status": "healthy"}
    secret = "shared-secret"
    sig = compute_hmac(payload, secret)
    assert verify_hmac(payload, sig, secret) is True


def test_verify_hmac_wrong_secret():
    payload = {"role": "primary"}
    sig = compute_hmac(payload, "correct-secret")
    assert verify_hmac(payload, sig, "wrong-secret") is False


def test_verify_hmac_tampered_payload():
    payload = {"role": "primary"}
    sig = compute_hmac(payload, "key")
    tampered = {"role": "standby"}
    assert verify_hmac(tampered, sig, "key") is False


def test_verify_hmac_garbage_signature():
    assert verify_hmac({"a": 1}, "not-a-real-sig", "key") is False


def test_verify_hmac_empty_payload():
    """Empty dict is a valid payload."""
    sig = compute_hmac({}, "key")
    assert verify_hmac({}, sig, "key") is True
