"""Property-based tests for HMAC sign/verify round-trip.

Properties covered:
  P2 — For any payload and secret, compute then verify returns True;
        a different secret returns False.

**Validates: Requirements 11.4**
"""

from __future__ import annotations

from hypothesis import given, assume
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS

from app.modules.ha.hmac_utils import compute_hmac, verify_hmac

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

payload_st = st.dictionaries(
    keys=st.text(min_size=1, max_size=10),
    values=st.text(max_size=50),
    min_size=0,
    max_size=10,
)

secret_st = st.text(min_size=1, max_size=50)


# ===========================================================================
# Property 2: HMAC sign/verify round-trip
# ===========================================================================


class TestP2HmacSignVerifyRoundTrip:
    """HMAC compute then verify with the same secret returns True;
    a different secret returns False.

    **Validates: Requirements 11.4**
    """

    @given(payload=payload_st, secret=secret_st)
    @PBT_SETTINGS
    def test_compute_then_verify_same_secret_returns_true(
        self, payload: dict, secret: str,
    ) -> None:
        """P2: verify(payload, compute(payload, secret), secret) is True."""
        signature = compute_hmac(payload, secret)
        assert verify_hmac(payload, signature, secret) is True

    @given(payload=payload_st, secret1=secret_st, secret2=secret_st)
    @PBT_SETTINGS
    def test_compute_then_verify_different_secret_returns_false(
        self, payload: dict, secret1: str, secret2: str,
    ) -> None:
        """P2: verify(payload, compute(payload, s1), s2) is False when s1 != s2."""
        assume(secret1 != secret2)
        signature = compute_hmac(payload, secret1)
        assert verify_hmac(payload, signature, secret2) is False
