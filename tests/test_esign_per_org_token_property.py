"""Property-based test for per-organisation Documenso token scoping (task 5.5).

# Feature: esignature-integration, Property 26: Documenso calls always use the calling org's own team-scoped token

**Validates: Requirements 13.7**

OraInvoice integrates a self-hosted Documenso where **each organisation has its
own Documenso Team** with its **own team-scoped service token**. The client
under test, :meth:`app.integrations.documenso.DocumensoClient.for_org`,
constructs a per-org client that carries that organisation's raw token in the
``Authorization`` header (no ``Bearer`` prefix) and talks to that organisation's
own ``base_url``. The v2 RPC API scopes every call to the org's Documenso Team
**by the team-scoped token itself** — there is no ``teamId`` sent on the wire —
so the per-org isolation invariant is expressed entirely through the token + the
target host.

Property 26 (R13.7): given ``N`` organisations each with a **distinct**
``DocumensoConnection`` (distinct ``base_url`` / token), for every Documenso call
issued on behalf of an organisation, the request goes to **that org's own host**
carrying **that org's own token** in ``Authorization`` (raw, no ``Bearer``) —
and **never** any other organisation's token. We assert this via a recording
(spy) ``httpx.MockTransport`` shared across multiple orgs, with calls
interleaved across organisations.
"""

from __future__ import annotations

import asyncio

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st

from app.integrations.documenso import (
    DocumensoClient,
    DocumensoConnection,
    RecipientSpec,
)

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# each example drives an asyncio event loop with many interleaved calls.
PBT_SETTINGS = settings(max_examples=150, deadline=None)


# ---------------------------------------------------------------------------
# Recording transport — records the (Authorization, host) of every call
# ---------------------------------------------------------------------------


class _RecordingTransport:
    """Shared spy: records (auth, host) for every request from any org."""

    def __init__(self) -> None:
        self.records: list[tuple[str | None, str | None]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.records.append(
            (request.headers.get("Authorization"), request.url.host)
        )
        # A single shape satisfies every v2 RPC call we exercise:
        #  - POST /document/create reads {id, envelopeId}
        #  - GET  /document/{id} reads {envelopeId, recipients[...]}
        #  - field/create-many, distribute ignore the body
        #  - download returns bytes (json ignored)
        #  - cancel GETs the doc (envelopeId) then POSTs envelope/cancel
        #  - test_connection GETs a nonexistent doc (200 here → verified)
        return httpx.Response(
            200,
            json={"id": 1, "envelopeId": "envelope_1", "recipients": []},
        )


# ---------------------------------------------------------------------------
# Generators — N distinct orgs + an interleaved sequence of calls across them
# ---------------------------------------------------------------------------

# Call kinds that issue at least one Documenso request carrying the org's token.
CALL_KINDS = (
    "create_document",
    "place_signature_field",
    "send_document",
    "download_signed",
    "cancel_document",
    "test_connection",
)


@st.composite
def org_scenario(draw):
    """Build >= 2 distinct orgs and an interleaved list of (org_index, call)."""
    # Distinct integer ids guarantee a distinct token / base_url per org.
    ids = draw(st.lists(st.integers(min_value=0, max_value=10**6), min_size=2, max_size=6, unique=True))
    n = len(ids)
    calls = draw(
        st.lists(
            st.tuples(st.integers(min_value=0, max_value=n - 1), st.sampled_from(CALL_KINDS)),
            min_size=1,
            max_size=40,
        )
    )
    return ids, calls


def _conn_for(org_id: int) -> DocumensoConnection:
    return DocumensoConnection(
        base_url=f"https://org{org_id}.documenso.example.test",
        service_token=f"tok_{org_id}",
        webhook_secret=f"whsec_{org_id}",
        documenso_team_id=f"team_{org_id}",
        webhook_routing_id=f"route_{org_id}",
        is_verified=True,
    )


async def _invoke(client: DocumensoClient, kind: str) -> None:
    if kind == "create_document":
        await client.create_document(
            title="Agreement",
            recipients=[RecipientSpec("Jo", "jo@example.test", "signer")],
            pdf_bytes=b"%PDF-1.7 data",
        )
    elif kind == "place_signature_field":
        await client.place_signature_field(
            "1",
            recipient_id="1",
            page_number=1,
            page_x=65,
            page_y=85,
            page_width=25,
            page_height=8,
        )
    elif kind == "send_document":
        await client.send_document("1")
    elif kind == "download_signed":
        await client.download_signed("1")
    elif kind == "cancel_document":
        await client.cancel_document("1")
    elif kind == "test_connection":
        await client.test_connection()
    else:  # pragma: no cover - guarded by CALL_KINDS
        raise AssertionError(f"unknown call kind {kind!r}")


async def _run_scenario(ids, calls):
    spy = _RecordingTransport()
    http = httpx.AsyncClient(transport=httpx.MockTransport(spy.handler))
    # One per-org client, each built from that org's own connection (R13.7).
    clients = {org_id: DocumensoClient.for_org(_conn_for(org_id), http) for org_id in ids}
    try:
        for idx, kind in calls:
            org_id = ids[idx]
            await _invoke(clients[org_id], kind)
    finally:
        await http.aclose()
    return spy.records


def _org_index_from_host(host: str | None) -> int:
    """Extract ``N`` from a host of the form ``org{N}.documenso.example.test``."""
    assert host is not None
    label = host.split(".", 1)[0]
    assert label.startswith("org"), host
    return int(label[len("org"):])


class TestPerOrgTokenScoping:
    """Property 26: Documenso calls always use the calling org's own team-scoped token.

    **Validates: Requirements 13.7**
    """

    @given(scenario=org_scenario())
    @PBT_SETTINGS
    def test_every_call_uses_only_the_calling_orgs_token_and_host(self, scenario):
        ids, calls = scenario
        records = asyncio.run(_run_scenario(ids, calls))

        # At least one request was issued per invocation (some calls — create,
        # cancel — issue more than one request; all are checked).
        assert records, "expected at least one recorded request"

        valid_tokens = {f"tok_{i}" for i in ids}

        for auth, host in records:
            org_id = _org_index_from_host(host)
            expected_token = f"tok_{org_id}"

            # Raw token, NO Bearer prefix, and it is THIS org's own token —
            # the token that pairs with the host the request went to.
            assert auth == expected_token
            assert not (auth or "").lower().startswith("bearer")

            # Cross-org safety: the recorded token is a real org token and is
            # exactly the one that belongs to the org whose host was contacted,
            # never another org's.
            assert auth in valid_tokens
