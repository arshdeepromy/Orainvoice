"""Unit tests for :class:`DocumensoClient` (task 5.2).

Exercises the per-organisation **Documenso v2 RPC API** client through a
``httpx.MockTransport`` spy so we can assert on the exact requests it issues
without touching a real Documenso instance:

* raw team-scoped token in ``Authorization`` (NO ``Bearer`` prefix);
* HTTPS enforcement (non-HTTPS base URL rejected at construction);
* recipient role mapping (lowercase ``signer``/``viewer`` → UPPERCASE);
* per-org team scoping (``for_org`` carries the org's own token; the team is
  derived from the token, so no ``teamId`` is sent on the wire);
* explicit timeout + retry/backoff on transient failures (timeout, 5xx);
* immediate raise (no retry) on non-transient 4xx failures;
* the v2 RPC flow: multipart ``document/create`` (PDF uploaded inline) →
  ``document/field/create-many`` → ``document/distribute`` →
  download / ``envelope/cancel`` / connection test.

Requirements: 1.6, 7.2, 9.1, 9.5, 13.7, 15.4
"""

from __future__ import annotations

import httpx
import pytest

from app.integrations.documenso import (
    CreatedRecipient,
    DocumensoApiError,
    DocumensoClient,
    DocumensoConnection,
    DocumensoCreateResult,
    DocumensoError,
    DocumensoFieldSpec,
    RecipientSpec,
    map_recipient_role,
)

BASE_URL = "https://documenso.example.test"
TOKEN = "tok_team_scoped_raw"
TEAM_ID = "team-123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Spy:
    """Records every request the client makes for later assertions."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []


def _make_client(
    handler,
    *,
    base_url: str = BASE_URL,
    token: str = TOKEN,
    team_id: str | None = TEAM_ID,
    timeout=None,
) -> tuple[DocumensoClient, httpx.AsyncClient]:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    client = DocumensoClient(base_url, token, http, team_id=team_id, timeout=timeout)
    return client, http


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make backoff sleeps instant so retry tests run fast."""

    async def _instant(_seconds):
        return None

    monkeypatch.setattr("app.integrations.documenso.asyncio.sleep", _instant)


# ---------------------------------------------------------------------------
# Role mapping
# ---------------------------------------------------------------------------


def test_role_mapping_lowercase_to_uppercase():
    assert map_recipient_role("signer") == "SIGNER"
    assert map_recipient_role("viewer") == "VIEWER"
    assert map_recipient_role("cc") == "CC"
    assert map_recipient_role("approver") == "APPROVER"
    assert map_recipient_role("assistant") == "ASSISTANT"


def test_role_mapping_is_case_insensitive_and_trims():
    assert map_recipient_role("  Signer ") == "SIGNER"
    assert map_recipient_role("VIEWER") == "VIEWER"


def test_role_mapping_rejects_unknown_role():
    with pytest.raises(DocumensoError):
        map_recipient_role("notarole")


# ---------------------------------------------------------------------------
# HTTPS enforcement
# ---------------------------------------------------------------------------


def test_rejects_non_https_base_url():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(DocumensoError):
        DocumensoClient("http://insecure.example.test", TOKEN, http, team_id=TEAM_ID)


def test_rejects_schemeless_base_url():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(DocumensoError):
        DocumensoClient("documenso.example.test", TOKEN, http)


def test_for_org_rejects_non_https_connection():
    conn = DocumensoConnection(
        base_url="http://insecure.example.test",
        service_token=TOKEN,
        webhook_secret="whsec",
        documenso_team_id=TEAM_ID,
        webhook_routing_id="route-abc",
        is_verified=True,
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(DocumensoError):
        DocumensoClient.for_org(conn, http)


# ---------------------------------------------------------------------------
# Raw-token Authorization header (no Bearer) + HTTPS scheme on every call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_document_uses_raw_token_no_bearer():
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/document/create"):
            return httpx.Response(200, json={"id": 7, "envelopeId": "env-7"})
        # GET readback of the created document (recipients).
        return httpx.Response(200, json={"envelopeId": "env-7", "recipients": []})

    client, http = _make_client(handler)
    try:
        await client.create_document(
            title="Agreement",
            recipients=[RecipientSpec("Jo", "jo@example.test", "signer")],
            pdf_bytes=b"%PDF-1.4",
        )
    finally:
        await http.aclose()

    req = spy.requests[0]
    assert req.method == "POST"
    assert req.url.path == "/api/v2/document/create"
    assert req.headers["Authorization"] == TOKEN  # raw, NO "Bearer " prefix
    assert not req.headers["Authorization"].lower().startswith("bearer")
    assert req.url.scheme == "https"


@pytest.mark.asyncio
async def test_create_document_uploads_pdf_inline_as_multipart():
    """The PDF is uploaded inline with the create request as multipart/form-data
    (no separate presigned PUT under the v2 RPC flow)."""
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/document/create"):
            return httpx.Response(200, json={"id": 7, "envelopeId": "env-7"})
        return httpx.Response(200, json={"envelopeId": "env-7", "recipients": []})

    client, http = _make_client(handler)
    try:
        await client.create_document(
            title="Agreement",
            recipients=[RecipientSpec("Jo", "jo@example.test", "signer")],
            pdf_bytes=b"%PDF-1.7 inline-bytes",
        )
    finally:
        await http.aclose()

    create_req = next(r for r in spy.requests if r.method == "POST")
    content_type = create_req.headers["Content-Type"]
    assert content_type.startswith("multipart/form-data")
    raw = create_req.content
    # The raw PDF bytes and the JSON payload part both travel in the one request.
    assert b"%PDF-1.7 inline-bytes" in raw
    assert b'name="payload"' in raw
    assert b'name="file"' in raw


@pytest.mark.asyncio
async def test_create_document_maps_roles_and_scopes_team_on_the_wire():
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/document/create"):
            return httpx.Response(200, json={"id": 55, "envelopeId": "env-55"})
        # The v2 create response carries no recipients; they are read back via
        # GET /document/{id} (with their per-recipient tokens + numeric ids).
        return httpx.Response(
            200,
            json={
                "envelopeId": "env-55",
                "recipients": [
                    {"id": 1, "email": "jo@example.test", "role": "SIGNER", "token": "rtok"},
                    {"id": 2, "email": "vee@example.test", "role": "VIEWER", "token": "vtok"},
                ],
            },
        )

    client, http = _make_client(handler)
    try:
        result = await client.create_document(
            title="Agreement",
            recipients=[
                RecipientSpec("Jo", "jo@example.test", "signer"),
                RecipientSpec("Vee", "vee@example.test", "viewer"),
            ],
            pdf_bytes=b"%PDF-1.4",
        )
    finally:
        await http.aclose()

    create_req = next(r for r in spy.requests if r.method == "POST")
    payload = _extract_create_payload(create_req)
    assert [r["role"] for r in payload["recipients"]] == ["SIGNER", "VIEWER"]
    # The team is scoped by the team-scoped token itself — no teamId on the wire.
    assert "teamId" not in payload
    assert "teamId" not in create_req.url.params

    assert isinstance(result, DocumensoCreateResult)
    assert result.document_id == "55"
    assert result.envelope_id == "env-55"
    assert result.recipients == [
        CreatedRecipient(
            recipient_id="1",
            email="jo@example.test",
            role="SIGNER",
            token="rtok",
            signing_url="https://documenso.example.test/sign/rtok",
        ),
        CreatedRecipient(
            recipient_id="2",
            email="vee@example.test",
            role="VIEWER",
            token="vtok",
            signing_url="https://documenso.example.test/sign/vtok",
        ),
    ]


@pytest.mark.asyncio
async def test_create_document_invalid_payload_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        # The create response is missing the document id → must raise before any
        # readback GET is issued.
        return httpx.Response(200, json={"envelopeId": "env-1"})

    client, http = _make_client(handler)
    try:
        with pytest.raises(DocumensoApiError):
            await client.create_document(
                title="x",
                recipients=[RecipientSpec("Jo", "jo@example.test", "signer")],
                pdf_bytes=b"%PDF-1.4",
            )
    finally:
        await http.aclose()


# ---------------------------------------------------------------------------
# Per-org team scoping (R13.7) — each org's own token is used
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_for_org_uses_orgs_own_token_and_team():
    seen: list[tuple[str | None, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (request.headers.get("Authorization"), request.url.params.get("teamId"))
        )
        return httpx.Response(200, json={})

    conn_a = DocumensoConnection(
        base_url=BASE_URL,
        service_token="tok_A",
        webhook_secret="s",
        documenso_team_id="team-A",
        webhook_routing_id="ra",
        is_verified=True,
    )
    conn_b = DocumensoConnection(
        base_url=BASE_URL,
        service_token="tok_B",
        webhook_secret="s",
        documenso_team_id="team-B",
        webhook_routing_id="rb",
        is_verified=True,
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        client_a = DocumensoClient.for_org(conn_a, http)
        client_b = DocumensoClient.for_org(conn_b, http)
        await client_a.test_connection()
        await client_b.test_connection()
    finally:
        await http.aclose()

    # Each org's call carries its OWN raw token. The team is derived from the
    # team-scoped token, so no teamId param is ever placed on the wire (v2 RPC).
    assert seen[0] == ("tok_A", None)
    assert seen[1] == ("tok_B", None)


# ---------------------------------------------------------------------------
# Retry / backoff on transient failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retries_on_5xx_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={})

    client, http = _make_client(handler)
    try:
        ok = await client.test_connection()
    finally:
        await http.aclose()

    assert ok is True
    assert calls["n"] == 3  # 1 initial + 2 retries


@pytest.mark.asyncio
async def test_5xx_exhausts_retries_and_raises():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    client, http = _make_client(handler)
    try:
        with pytest.raises(DocumensoApiError) as exc:
            await client.send_document("7")
    finally:
        await http.aclose()

    assert calls["n"] == DocumensoClient.MAX_ATTEMPTS  # 3 attempts total
    assert exc.value.status == 500


@pytest.mark.asyncio
async def test_retries_on_timeout_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.TimeoutException("slow", request=request)
        return httpx.Response(200, json={})

    client, http = _make_client(handler)
    try:
        ok = await client.test_connection()
    finally:
        await http.aclose()

    assert ok is True
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_backoff_schedule_applied_between_retries(monkeypatch):
    slept: list[float] = []

    async def _record(seconds):
        slept.append(seconds)

    monkeypatch.setattr("app.integrations.documenso.asyncio.sleep", _record)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502)

    client, http = _make_client(handler)
    try:
        with pytest.raises(DocumensoApiError):
            await client.send_document("7")
    finally:
        await http.aclose()

    # 3 attempts -> 2 backoff sleeps using the 1s, 2s schedule.
    assert slept == [1.0, 2.0]


# ---------------------------------------------------------------------------
# Non-transient (4xx) — raise immediately, NO retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_4xx_raises_immediately_without_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"message": "bad"})

    client, http = _make_client(handler)
    try:
        with pytest.raises(DocumensoApiError) as exc:
            await client.send_document("7")
    finally:
        await http.aclose()

    assert calls["n"] == 1  # no retry on 4xx
    assert exc.value.status == 400


@pytest.mark.asyncio
async def test_test_connection_returns_false_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    client, http = _make_client(handler)
    try:
        ok = await client.test_connection()
    finally:
        await http.aclose()

    assert ok is False


# ---------------------------------------------------------------------------
# fields / send / download / cancel  (v2 RPC shape)
# ---------------------------------------------------------------------------
# Note: there is no separate ``upload_pdf`` presigned-PUT step under the v2 RPC
# flow — the PDF is uploaded inline with ``document/create`` (asserted by
# ``test_create_document_uploads_pdf_inline_as_multipart`` above).


@pytest.mark.asyncio
async def test_place_signature_field_posts_field_payload():
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        return httpx.Response(200, json={})

    client, http = _make_client(handler)
    try:
        await client.place_signature_field(
            "1",
            recipient_id="11",
            page_number=2,
            page_x=65,
            page_y=85,
            page_width=25,
            page_height=8,
        )
    finally:
        await http.aclose()

    req = spy.requests[0]
    assert req.method == "POST"
    # The single-field auto-placement uses the same create-many endpoint, with
    # exactly one field in the ``fields`` array.
    assert req.url.path == "/api/v2/document/field/create-many"
    body = _json.loads(req.content)
    assert body["documentId"] == 1  # coerced to int
    assert len(body["fields"]) == 1
    f = body["fields"][0]
    assert f["type"] == "SIGNATURE"
    assert f["recipientId"] == 11  # coerced to int
    assert f["pageNumber"] == 2
    assert f["pageX"] == 65
    assert f["pageY"] == 85
    assert f["width"] == 25
    assert f["height"] == 8


@pytest.mark.asyncio
async def test_send_document_posts_to_distribute_endpoint():
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        return httpx.Response(200, json={})

    client, http = _make_client(handler)
    try:
        await client.send_document("7")
    finally:
        await http.aclose()

    assert spy.requests[0].url.path == "/api/v2/document/distribute"


@pytest.mark.asyncio
async def test_download_signed_returns_bytes():
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        return httpx.Response(200, content=b"%PDF-signed")

    client, http = _make_client(handler)
    try:
        data = await client.download_signed("7")
    finally:
        await http.aclose()

    assert data == b"%PDF-signed"
    req = spy.requests[0]
    assert req.method == "GET"
    assert req.url.path == "/api/v2/document/7/download"
    assert req.url.params.get("version") == "signed"


@pytest.mark.asyncio
async def test_cancel_document_posts_envelope_cancel():
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        if request.method == "GET":
            # Resolve the (string) envelopeId from the numeric document id.
            return httpx.Response(200, json={"envelopeId": "env-7"})
        return httpx.Response(200, json={})

    client, http = _make_client(handler)
    try:
        await client.cancel_document("7")
    finally:
        await http.aclose()

    # v2 cancel: GET the document to resolve its envelopeId, then POST cancel.
    get_req = spy.requests[0]
    assert get_req.method == "GET"
    assert get_req.url.path == "/api/v2/document/7"

    cancel_req = spy.requests[1]
    assert cancel_req.method == "POST"
    assert cancel_req.url.path == "/api/v2/envelope/cancel"
    body = _json.loads(cancel_req.content)
    assert body["envelopeId"] == "env-7"
    assert body.get("reason")


# ---------------------------------------------------------------------------
# Explicit timeout is always set (never the unbounded default)
# ---------------------------------------------------------------------------


def test_client_sets_explicit_timeout_by_default():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    client = DocumensoClient(BASE_URL, TOKEN, http, team_id=TEAM_ID)
    assert isinstance(client._timeout, httpx.Timeout)
    assert client._timeout.read == DocumensoClient.DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# create_fields — multi-field create-many (task 10.1, R8.1/R8.2)
# ---------------------------------------------------------------------------


def _spec(**overrides) -> DocumensoFieldSpec:
    base = dict(
        recipient_id=11,
        type="SIGNATURE",
        page_number=1,
        page_x=10.0,
        page_y=20.0,
        width=25.0,
        height=8.0,
        field_meta=None,
    )
    base.update(overrides)
    return DocumensoFieldSpec(**base)


@pytest.mark.asyncio
async def test_create_fields_mirrors_place_signature_field_wire_shape():
    """The payload mirrors the proven single-field shape: same envelope + keys, N fields."""
    import json

    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        return httpx.Response(200, json={})

    client, http = _make_client(handler)
    try:
        await client.create_fields(
            "42",
            [
                _spec(recipient_id=11, type="SIGNATURE", page_number=1,
                      page_x=10.0, page_y=20.0, width=25.0, height=8.0),
                _spec(recipient_id=12, type="TEXT", page_number=3,
                      page_x=5.5, page_y=6.5, width=30.0, height=10.0),
            ],
        )
    finally:
        await http.aclose()

    req = spy.requests[0]
    assert req.method == "POST"
    assert req.url.path == "/api/v2/document/field/create-many"
    # Raw team-scoped token, NO "Bearer" prefix.
    assert req.headers["Authorization"] == TOKEN

    body = json.loads(req.content)
    assert body["documentId"] == 42  # coerced to int
    assert len(body["fields"]) == 2

    f0 = body["fields"][0]
    assert f0 == {
        "recipientId": 11,
        "type": "SIGNATURE",
        "pageNumber": 1,
        "pageX": 10.0,
        "pageY": 20.0,
        "width": 25.0,
        "height": 8.0,
    }
    f1 = body["fields"][1]
    assert f1["recipientId"] == 12
    assert f1["type"] == "TEXT"
    assert f1["pageNumber"] == 3
    # The internal NormalizedRect names are never sent on the wire.
    for f in body["fields"]:
        assert "positionX" not in f
        assert "positionY" not in f
        assert "page" not in f


@pytest.mark.asyncio
async def test_create_fields_omits_field_meta_by_default(monkeypatch):
    """fieldMeta is UNVERIFIED → omitted on the wire by default (conservative)."""
    import json

    monkeypatch.setattr(
        "app.integrations.documenso.settings.esign_field_create_many_honours_field_meta",
        False,
        raising=False,
    )
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        return httpx.Response(200, json={})

    client, http = _make_client(handler)
    try:
        await client.create_fields(
            "1",
            [_spec(type="TEXT", field_meta={"required": True, "label": "Notes"})],
        )
    finally:
        await http.aclose()

    body = json.loads(spy.requests[0].content)
    assert "fieldMeta" not in body["fields"][0]


@pytest.mark.asyncio
async def test_create_fields_includes_field_meta_when_capability_enabled(monkeypatch):
    """When the capability flag is on, fieldMeta is carried per field."""
    import json

    monkeypatch.setattr(
        "app.integrations.documenso.settings.esign_field_create_many_honours_field_meta",
        True,
        raising=False,
    )
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        return httpx.Response(200, json={})

    meta = {"required": True, "label": "Notes", "placeholder": "Type here"}
    client, http = _make_client(handler)
    try:
        await client.create_fields("1", [_spec(type="TEXT", field_meta=meta)])
    finally:
        await http.aclose()

    body = json.loads(spy.requests[0].content)
    assert body["fields"][0]["fieldMeta"] == meta


@pytest.mark.asyncio
async def test_create_fields_empty_list_posts_empty_fields():
    """An empty Field_Set still posts the proven envelope shape with no fields."""
    import json

    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        return httpx.Response(200, json={})

    client, http = _make_client(handler)
    try:
        await client.create_fields("7", [])
    finally:
        await http.aclose()

    body = json.loads(spy.requests[0].content)
    assert body == {"documentId": 7, "fields": []}


@pytest.mark.asyncio
async def test_create_fields_raises_on_4xx():
    """A non-transient Documenso error surfaces as DocumensoApiError (no retry)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "bad field"})

    client, http = _make_client(handler)
    try:
        with pytest.raises(DocumensoApiError):
            await client.create_fields("1", [_spec()])
    finally:
        await http.aclose()


# ---------------------------------------------------------------------------
# Signing order (R15) — RecipientSpec.signing_order on create + distribution
# mode on send_document, gated behind esign_signing_order_supported (task 19.2)
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402  (local alias for payload extraction)


def _extract_create_payload(request: httpx.Request) -> dict:
    """Pull the JSON ``payload`` part out of a multipart ``document/create`` body."""
    raw = request.content.decode("utf-8", "replace")
    marker = 'name="payload"'
    after = raw[raw.index(marker) + len(marker) :]
    start = after.index("{")
    obj, _ = _json.JSONDecoder().raw_decode(after[start:])
    return obj


def _create_handler(spy: _Spy):
    """Route the create POST + the readback GET for create_document tests."""

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/document/create"):
            return httpx.Response(200, json={"id": 7, "envelopeId": "env-7"})
        if request.method == "GET" and "/document/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "envelopeId": "env-7",
                    "recipients": [
                        {"id": 11, "email": "jo@example.test", "role": "SIGNER", "token": "t1"}
                    ],
                },
            )
        return httpx.Response(200, json={})

    return handler


@pytest.mark.asyncio
async def test_create_document_omits_signing_order_when_capability_disabled(monkeypatch):
    """Default (flag False): signing_order is accepted but omitted from the wire."""
    monkeypatch.setattr(
        "app.integrations.documenso.settings.esign_signing_order_supported", False
    )
    spy = _Spy()
    client, http = _make_client(_create_handler(spy))
    try:
        await client.create_document(
            title="Agreement",
            pdf_bytes=b"%PDF-1.4",
            recipients=[
                RecipientSpec("Jo", "jo@example.test", "signer", signing_order=1),
                RecipientSpec("Vee", "vee@example.test", "signer", signing_order=2),
            ],
        )
    finally:
        await http.aclose()

    create_req = next(r for r in spy.requests if r.method == "POST")
    payload = _extract_create_payload(create_req)
    assert [r["role"] for r in payload["recipients"]] == ["SIGNER", "SIGNER"]
    assert all("signingOrder" not in r for r in payload["recipients"])


@pytest.mark.asyncio
async def test_create_document_includes_signing_order_when_capability_enabled(monkeypatch):
    """Flag True: each recipient's 1-based signing_order is emitted as signingOrder."""
    monkeypatch.setattr(
        "app.integrations.documenso.settings.esign_signing_order_supported", True
    )
    spy = _Spy()
    client, http = _make_client(_create_handler(spy))
    try:
        await client.create_document(
            title="Agreement",
            pdf_bytes=b"%PDF-1.4",
            recipients=[
                RecipientSpec("Jo", "jo@example.test", "signer", signing_order=1),
                RecipientSpec("Vee", "vee@example.test", "viewer"),  # no position
            ],
        )
    finally:
        await http.aclose()

    create_req = next(r for r in spy.requests if r.method == "POST")
    payload = _extract_create_payload(create_req)
    assert payload["recipients"][0]["signingOrder"] == 1
    # A recipient with no explicit position never carries the key.
    assert "signingOrder" not in payload["recipients"][1]


@pytest.mark.asyncio
async def test_send_document_defaults_to_parallel_distribution_mode():
    """Backward compat: no signing_order_mode → PARALLEL (EMAIL distribution)."""
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        return httpx.Response(200, json={})

    client, http = _make_client(handler)
    try:
        await client.send_document("7")
    finally:
        await http.aclose()

    body = _json.loads(spy.requests[0].content)
    assert body["meta"]["distributionMethod"] == "EMAIL"
    assert body["meta"]["distributionMode"] == "PARALLEL"


@pytest.mark.asyncio
async def test_send_document_sequential_degrades_to_parallel_when_disabled(monkeypatch):
    """Flag False: a sequential request degrades to PARALLEL (no enforcement claimed)."""
    monkeypatch.setattr(
        "app.integrations.documenso.settings.esign_signing_order_supported", False
    )
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        return httpx.Response(200, json={})

    client, http = _make_client(handler)
    try:
        await client.send_document("7", signing_order_mode="sequential")
    finally:
        await http.aclose()

    body = _json.loads(spy.requests[0].content)
    assert body["meta"]["distributionMode"] == "PARALLEL"


@pytest.mark.asyncio
async def test_send_document_sequential_maps_to_sequential_when_enabled(monkeypatch):
    """Flag True: a sequential request maps to the SEQUENTIAL distribution mode."""
    monkeypatch.setattr(
        "app.integrations.documenso.settings.esign_signing_order_supported", True
    )
    spy = _Spy()

    def handler(request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        return httpx.Response(200, json={})

    client, http = _make_client(handler)
    try:
        await client.send_document("7", signing_order_mode="sequential")
    finally:
        await http.aclose()

    body = _json.loads(spy.requests[0].content)
    assert body["meta"]["distributionMode"] == "SEQUENTIAL"
