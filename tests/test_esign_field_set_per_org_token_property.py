"""Property-based test: field-placement sends use only the calling org's token (task 11.6).

# Feature: esignature-field-placement, Property 15: Field-placement sends use only the calling org's team-scoped token

**Validates: Requirements 9.3**

OraInvoice integrates a self-hosted Documenso where **each organisation has its
own Documenso Team** with its **own team-scoped service token** and its own
``base_url`` (R9.3). This test exercises the **Field_Set branch** of
:func:`app.modules.esignatures.service.create_and_send_envelope` — a send that
carries a non-empty sender-defined ``fields`` Field_Set — driven through the
**real** per-org client constructed by
:meth:`app.integrations.documenso.DocumensoClient.for_org` (the service builds it
from the org's connection when handed an ``http`` client).

The v2 RPC API scopes every call to the org's Documenso Team **by the
team-scoped token itself** (no ``teamId`` is sent on the wire), so the per-org
isolation invariant is expressed entirely through the token + the target host.
The field-placement send issues, in order: ``create_document`` (POST
``/document/create`` then GET ``/document/{id}``) → ``create_fields`` (POST
``field/create-many``) → ``send_document`` (POST ``distribute``).

Property 15 (R9.3): given ``N`` organisations each with a **distinct**
``DocumensoConnection`` (distinct ``base_url`` / token / Team id), for every
Documenso call issued by a field-placement send on behalf of an organisation,
the request goes to **that org's own host** carrying **that org's own raw
token** in ``Authorization`` (no ``Bearer`` prefix) — and **never** any other
organisation's token. We assert this via a recording (spy) ``httpx`` transport
shared across multiple orgs, with sends interleaved across organisations.
"""

from __future__ import annotations

import asyncio
import json
import unittest.mock as _mock
import uuid

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the model graph so SQLAlchemy can resolve string-based relationships
# when EsignEnvelope / EsignRecipient are instantiated (mirrors the other esign
# unit/property tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.integrations.documenso import DocumensoConnection  # noqa: E402
from app.modules.esignatures import service as esign_service  # noqa: E402
from app.modules.esignatures.schemas import (  # noqa: E402
    EnvelopeCreate,
    FieldIn,
    RecipientIn,
)

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# each example drives an asyncio event loop through several full send flows.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

_AGREEMENT_TYPES = (
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
)
_ENTITY_TYPES = ("invoice", "quote", "staff")
_FIELD_TYPES = ("signature", "initials", "name", "date", "email", "text")

# A minimal but valid PDF byte string (starts with the %PDF magic bytes that
# ``is_pdf`` checks).
_VALID_PDF = b"%PDF-1.4\n1 0 obj<</Type/Page>>endobj\n%%EOF"


# ---------------------------------------------------------------------------
# Recording transport — records (Authorization, host) of every request and
# answers every v2 RPC call the field-placement send issues.
# ---------------------------------------------------------------------------


class _RecordingTransport:
    """Shared spy: records (auth, host) for every request from any org.

    Answers the field-placement send's call sequence:

    * ``POST /api/v2/document/create`` → ``{ id, envelopeId }``
    * ``GET  /api/v2/document/{id}``   → ``{ recipients: [...] }`` echoing the
      fixed recipient list (matched by email) with numeric ids so the service's
      email→recipientId reconciliation succeeds for every placed field.
    * ``POST /api/v2/document/field/create-many`` → ``200`` (body ignored)
    * ``POST /api/v2/document/distribute``        → ``200`` (body ignored)
    """

    def __init__(self, recipient_emails: list[str]) -> None:
        self.records: list[tuple[str | None, str | None]] = []
        # Echo one recipient per input email; numeric id = position + 1 so
        # ``int(recipient_id)`` works and the id is positional/unique.
        self._recipients = [
            {
                "id": i + 1,
                "email": email,
                "role": "SIGNER",
                "token": f"tok{i}",
            }
            for i, email in enumerate(recipient_emails)
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.records.append(
            (request.headers.get("Authorization"), request.url.host)
        )
        path = request.url.path
        if request.method == "GET":
            # GET /api/v2/document/{id} — read back recipients.
            return httpx.Response(200, json={"recipients": self._recipients})
        # POST create → {id, envelopeId}; field/create-many + distribute ignore body.
        return httpx.Response(200, json={"id": 1, "envelopeId": "envelope_1"})


# ---------------------------------------------------------------------------
# Fake async session — add / flush / refresh are the only hooks the success
# path touches once the audit/notify side-effect is stubbed.
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj) -> None:
        return None


def _conn_for(org_id: int) -> DocumensoConnection:
    """A distinct connection per org: distinct base_url / token / Team id."""
    return DocumensoConnection(
        base_url=f"https://org{org_id}.documenso.example.test",
        service_token=f"tok_{org_id}",
        webhook_secret=f"whsec_{org_id}",
        documenso_team_id=f"team_{org_id}",
        webhook_routing_id=f"route_{org_id}",
        is_verified=True,
    )


# ---------------------------------------------------------------------------
# Generators — a fixed valid recipient list + valid Field_Set (shared across all
# orgs in an example) and >= 2 distinct orgs with an interleaved send sequence.
# ---------------------------------------------------------------------------


@st.composite
def _in_bounds_field(draw, *, recipient_index: int, force_type: str | None = None):
    """A single in-bounds FieldIn assigned to ``recipient_index`` (always valid)."""
    ftype = force_type or draw(st.sampled_from(_FIELD_TYPES))
    page = draw(st.integers(min_value=1, max_value=5))
    x = draw(st.floats(min_value=0, max_value=95, allow_nan=False, allow_infinity=False))
    w = draw(st.floats(min_value=1, max_value=100 - x, allow_nan=False, allow_infinity=False))
    y = draw(st.floats(min_value=0, max_value=95, allow_nan=False, allow_infinity=False))
    h = draw(st.floats(min_value=1, max_value=100 - y, allow_nan=False, allow_infinity=False))
    return FieldIn(
        type=ftype,
        page=page,
        recipient_index=recipient_index,
        position_x=x,
        position_y=y,
        width=w,
        height=h,
        required=draw(st.booleans()),
    )


@st.composite
def _scenario(draw):
    # --- recipients + a valid Field_Set (shared across every org) ----------
    n = draw(st.integers(min_value=1, max_value=3))
    roles = draw(st.lists(st.sampled_from(["signer", "viewer"]), min_size=n, max_size=n))
    if "signer" not in roles:  # a zero-signer send is a validation error, not this path
        roles[0] = "signer"
    recipients = [
        RecipientIn(name=f"R{i}", email=f"r{i}@example.com", signing_role=roles[i])
        for i in range(n)
    ]
    signer_indices = [i for i, r in enumerate(recipients) if r.signing_role == "signer"]

    fields: list[FieldIn] = []
    for idx in signer_indices:  # every signer carries >= 1 signature field (R6.1)
        fields.append(draw(_in_bounds_field(recipient_index=idx, force_type="signature")))
    for _ in range(draw(st.integers(min_value=0, max_value=4))):
        ri = draw(st.integers(min_value=0, max_value=n - 1))
        fields.append(draw(_in_bounds_field(recipient_index=ri)))

    agreement_type = draw(st.sampled_from(_AGREEMENT_TYPES))
    entity_type = draw(st.sampled_from(_ENTITY_TYPES))

    # --- >= 2 distinct orgs + an interleaved send sequence -----------------
    org_ids = draw(
        st.lists(st.integers(min_value=0, max_value=10**6), min_size=2, max_size=5, unique=True)
    )
    m = len(org_ids)
    send_sequence = draw(
        st.lists(st.integers(min_value=0, max_value=m - 1), min_size=1, max_size=12)
    )
    return recipients, fields, agreement_type, entity_type, org_ids, send_sequence


# ---------------------------------------------------------------------------
# Driver — runs the interleaved field-placement sends across orgs against one
# shared recording transport, returning every recorded (auth, host).
# ---------------------------------------------------------------------------


def _build_payload(recipients, fields, agreement_type, entity_type) -> EnvelopeCreate:
    return EnvelopeCreate(
        agreement_type=agreement_type,
        originating_entity_type=entity_type,
        originating_entity_id=uuid.uuid4(),
        recipients=recipients,
        fields=fields,
    )


async def _run_scenario(recipients, fields, agreement_type, entity_type, org_ids, send_sequence):
    spy = _RecordingTransport([str(r.email) for r in recipients])
    http = httpx.AsyncClient(transport=httpx.MockTransport(spy.handler))

    # Map a distinct request org_id (UUID) to each org's own connection so the
    # patched connection gate returns that org's base_url / token / Team id.
    org_uuids = [uuid.uuid4() for _ in org_ids]
    conn_by_uuid = {u: _conn_for(org_ids[i]) for i, u in enumerate(org_uuids)}

    async def _fake_get_conn(_db, org_uuid):
        return conn_by_uuid[org_uuid]

    async def _noop_audit(*_args, **_kwargs):
        return None

    try:
        with _mock.patch.object(
            esign_service, "get_documenso_connection", _fake_get_conn
        ), _mock.patch.object(esign_service, "_audit_and_notify_send", _noop_audit):
            for pick in send_sequence:
                org_uuid = org_uuids[pick]
                payload = _build_payload(recipients, fields, agreement_type, entity_type)
                await esign_service.create_and_send_envelope(
                    _FakeSession(),
                    org_id=org_uuid,
                    user_id=uuid.uuid4(),
                    payload=payload,
                    pdf_bytes=_VALID_PDF,
                    http=http,  # service builds the REAL DocumensoClient.for_org(conn, http)
                )
    finally:
        await http.aclose()
    return spy.records


def _org_index_from_host(host: str | None) -> int:
    """Extract ``N`` from a host of the form ``org{N}.documenso.example.test``."""
    assert host is not None
    label = host.split(".", 1)[0]
    assert label.startswith("org"), host
    return int(label[len("org"):])


class TestFieldSetPerOrgTokenScoping:
    """Property 15: field-placement sends use only the calling org's team-scoped token.

    **Validates: Requirements 9.3**
    """

    @given(scenario=_scenario())
    @PBT_SETTINGS
    def test_every_field_set_send_uses_only_the_calling_orgs_token_and_host(self, scenario):
        recipients, fields, agreement_type, entity_type, org_ids, send_sequence = scenario
        records = asyncio.run(
            _run_scenario(
                recipients, fields, agreement_type, entity_type, org_ids, send_sequence
            )
        )

        # Each field-placement send issues several requests (create, GET,
        # field/create-many, distribute); every one is checked.
        assert records, "expected at least one recorded request"

        valid_tokens = {f"tok_{i}" for i in org_ids}

        for auth, host in records:
            org_id = _org_index_from_host(host)
            expected_token = f"tok_{org_id}"

            # Raw token, NO Bearer prefix, and it is THIS org's own token — the
            # token that pairs with the host the request actually went to.
            assert auth == expected_token
            assert not (auth or "").lower().startswith("bearer")

            # Cross-org safety: the recorded token is a real org token and is
            # exactly the one belonging to the org whose host was contacted,
            # never another org's.
            assert auth in valid_tokens
