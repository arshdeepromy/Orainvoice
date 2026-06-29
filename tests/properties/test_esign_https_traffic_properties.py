"""Property-based test — HTTPS for all Documenso traffic (task 5.4).

The class under test is :class:`app.integrations.documenso.DocumensoClient`,
constructed per organisation. This module exercises Property 23: every Documenso
v2 RPC API call OraInvoice issues goes over **HTTPS** carrying the
organisation's **raw team-scoped token** in the ``Authorization`` header (with
**no** ``Bearer`` prefix), and a non-HTTPS configured base URL is rejected at
construction time so no call can ever leave over plaintext HTTP.

We drive the client through an :class:`httpx.MockTransport` spy (mirroring
``tests/test_documenso_client.py``) so we can assert on the exact wire requests
without touching a real Documenso instance.

# Feature: esignature-integration, Property 23: HTTPS for all Documenso traffic

**Validates: Requirements 15.4**
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.config import settings as _app_settings
from app.integrations.documenso import (
    DocumensoClient,
    DocumensoError,
    RecipientSpec,
)


@pytest.fixture(autouse=True)
def _https_only_policy():
    """Pin the transport policy to its secure default for this module.

    The dev/test container enables ``esign_allow_insecure_internal_base_url``
    (the trusted-network escape hatch that permits plaintext HTTP to a
    private/internal host for container-to-container calls). This module
    validates the **default** HTTPS-only policy (R15.4), so force the flag off
    for its duration and restore it afterwards.
    """
    original = _app_settings.esign_allow_insecure_internal_base_url
    _app_settings.esign_allow_insecure_internal_base_url = False
    try:
        yield
    finally:
        _app_settings.esign_allow_insecure_internal_base_url = original

# ---------------------------------------------------------------------------
# Strategies — base URLs (valid https, http, schemeless) and raw tokens
# ---------------------------------------------------------------------------

_HOST_LABEL = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=12
)

# A dotted hostname like "documenso.example.test".
_hostnames = st.lists(_HOST_LABEL, min_size=1, max_size=4).map(lambda ls: ".".join(ls))

# Optional ":port" and trailing path so URLs are realistically varied.
_ports = st.one_of(st.none(), st.integers(min_value=1, max_value=65535))
_paths = st.one_of(st.none(), st.just("/"), st.just("/documenso"), st.just("/api"))


@st.composite
def _https_base_urls(draw) -> str:
    host = draw(_hostnames)
    port = draw(_ports)
    path = draw(_paths)
    netloc = host if port is None else f"{host}:{port}"
    return f"https://{netloc}{path or ''}"


@st.composite
def _non_https_base_urls(draw) -> str:
    """An http:// URL or a schemeless host — both must be rejected."""
    host = draw(_hostnames)
    port = draw(_ports)
    netloc = host if port is None else f"{host}:{port}"
    kind = draw(st.sampled_from(["http", "schemeless"]))
    if kind == "http":
        return f"http://{netloc}"
    return netloc  # schemeless -> urlparse yields no https scheme


# Raw team-scoped tokens: non-empty, header-safe ASCII (no spaces/control chars).
_tokens = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=48,
)


def _spy_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        # A single shape satisfies every v2 RPC call we exercise:
        #  - POST /document/create reads {id, envelopeId}
        #  - GET  /document/{id} reads {envelopeId, recipients[...]}
        #  - field/create-many, distribute ignore the body
        #  - download returns bytes (json ignored)
        #  - test_connection GETs a nonexistent doc (200 here → verified)
        return httpx.Response(
            200,
            json={
                "id": 1,
                "envelopeId": "envelope_1",
                "recipients": [],
            },
        )

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Property 23 — non-HTTPS base URLs are rejected at construction
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(_non_https_base_urls(), _tokens)
def test_non_https_base_url_is_rejected(base_url, token):
    """Any http:// or schemeless base URL raises DocumensoError on construction."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    try:
        with pytest.raises(DocumensoError):
            DocumensoClient(base_url, token, http, team_id="team-x")
    finally:
        asyncio.run(http.aclose())


# ---------------------------------------------------------------------------
# Property 23 — every v2 call uses https + the raw token (no Bearer prefix)
# ---------------------------------------------------------------------------


async def _exercise_all_calls(base_url: str, token: str) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=_spy_transport(seen))
    client = DocumensoClient(base_url, token, http, team_id="team-x")
    try:
        await client.create_document(
            title="Agreement",
            recipients=[RecipientSpec("Jo", "jo@example.test", "signer")],
            pdf_bytes=b"%PDF-1.7 data",
        )
        await client.place_signature_field(
            "1",
            recipient_id="1",
            page_number=1,
            page_x=65,
            page_y=85,
            page_width=25,
            page_height=8,
        )
        await client.send_document("1")
        await client.download_signed("1")
        await client.cancel_document("1")
        await client.test_connection()
    finally:
        await http.aclose()
    return seen


@settings(max_examples=100, deadline=None)
@given(_https_base_urls(), _tokens)
def test_https_base_url_every_call_is_https_with_raw_token(base_url, token):
    """For any https base URL the client builds and every call goes over https
    carrying the raw token verbatim in Authorization (no Bearer prefix)."""
    seen = asyncio.run(_exercise_all_calls(base_url, token))

    assert seen, "expected the client to issue at least one request"
    for req in seen:
        assert req.url.scheme == "https"
        auth = req.headers["Authorization"]
        assert auth == token  # raw token, byte-for-byte
        assert not auth.lower().startswith("bearer")
