"""Smoke test for external signing without an account (task 19.1).

Covers Requirement 5 — "External Signing Without an Account":

* **R5.1** — A send relies on Documenso-issued **one-time signing links** for
  external recipients and does **not** require those recipients to hold an
  OraInvoice account: every persisted ``esign_recipients`` row carries the
  one-time ``signingUrl`` Documenso returned, and the send creates **no**
  OraInvoice account record (``users`` / ``employee_portal_users``).
* **R5.2** — (corollary of the above) external recipients are external signers,
  not OraInvoice users; a send must not silently provision accounts for them.
* **R5.3** — The Documenso **administrative / organisation UI is never exposed**
  to OraInvoice users: no registered FastAPI route proxies, embeds, or
  redirects to the Documenso web UI. We assert this by scanning the assembled
  application's routes.

This is an **example/smoke** test (not a Hypothesis property). Part 1 drives the
real :func:`app.modules.esignatures.service.create_and_send_envelope` with a spy
Documenso client (returning a distinct one-time ``signingUrl`` per recipient)
and an account-recording fake session, mirroring the conventions of
``test_esign_send_orchestration_example.py``. Part 2 assembles the real FastAPI
app via ``app.main.create_app`` and inspects ``app.routes``.

_Requirements: 5.1, 5.2, 5.3_
"""

from __future__ import annotations

import asyncio
import uuid

# Pre-load the full model graph (mirrors app/main.py + the esign example tests)
# so SQLAlchemy can resolve every string-based relationship reference when
# ``EsignEnvelope`` / ``EsignRecipient`` are instantiated and the mapper
# registry is configured.
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.employee_portal.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.integrations.documenso import (  # noqa: E402
    CreatedRecipient,
    DocumensoConnection,
    DocumensoCreateResult,
    RecipientSpec,
)
from app.modules.auth.models import User  # noqa: E402
from app.modules.employee_portal.models import EmployeePortalUser  # noqa: E402
from app.modules.esignatures import service as esign_service  # noqa: E402
from app.modules.esignatures.models import EsignEnvelope, EsignRecipient  # noqa: E402
from app.modules.esignatures.schemas import EnvelopeCreate, RecipientIn  # noqa: E402

# A minimal but genuine PDF byte string (starts with the %PDF magic marker so
# the pure ``is_pdf`` validation passes).
_PDF_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\n"

# OraInvoice "account" model types — a send must create NONE of these (R5.1/5.2).
_ACCOUNT_TYPES = (User, EmployeePortalUser)


# ---------------------------------------------------------------------------
# Spy DocumensoClient — issues a distinct one-time signing link per recipient.
# ---------------------------------------------------------------------------


class _SpyDocumensoClient:
    """Returns one :class:`CreatedRecipient` per input recipient, each carrying a
    distinct one-time ``signing_url`` (matched back to the input by email)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_document(
        self, *, title: str, recipients: list[RecipientSpec], pdf_bytes: bytes
    ) -> DocumensoCreateResult:
        self.calls.append("create_document")
        created = [
            CreatedRecipient(
                recipient_id=f"rcpt-{i}",
                email=spec.email,
                role=spec.role.upper(),
                token=f"tok-{i}",
                signing_url=f"https://signer.documenso.example.test/sign/one-time-{i}",
            )
            for i, spec in enumerate(recipients)
        ]
        return DocumensoCreateResult(
            document_id="doc-smoke-123",
            envelope_id="envelope_doc-smoke-123",
            recipients=created,
        )

    async def place_signature_field(self, document_id: str, **kwargs) -> None:
        self.calls.append("place_signature_field")

    async def send_document(
        self, document_id: str, *, signing_order_mode: str = "parallel"
    ) -> None:
        self.calls.append("send_document")


# ---------------------------------------------------------------------------
# Account-recording fake session — captures every object handed to ``add`` so
# the test can prove no OraInvoice account row was created during a send.
# ---------------------------------------------------------------------------


class _AccountRecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj) -> None:
        return None


def _verified_connection() -> DocumensoConnection:
    return DocumensoConnection(
        base_url="https://documenso.example.test",
        service_token="tok_org",
        webhook_secret="whsec_org",
        documenso_team_id="team_org",
        webhook_routing_id="route_org",
        is_verified=True,
    )


def _all_persisted_objects(session: _AccountRecordingSession) -> list[object]:
    """Every ORM object the send touched: the objects added directly plus the
    recipients attached to any added envelope (appended via the relationship)."""
    objects: list[object] = list(session.added)
    for obj in session.added:
        if isinstance(obj, EsignEnvelope):
            objects.extend(list(obj.recipients))
    return objects


def _run_send(monkeypatch, payload: EnvelopeCreate):
    """Drive ``create_and_send_envelope`` with the spy client + recording
    session, returning ``(envelope, spy, session)``."""

    async def _fake_get_connection(_db, _org_id):
        return _verified_connection()

    monkeypatch.setattr(esign_service, "get_documenso_connection", _fake_get_connection)

    # Isolate the orchestration from the best-effort audit/notification writes
    # (those run in a SAVEPOINT the fake session does not implement).
    async def _noop_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(esign_service, "_audit_and_notify_send", _noop_audit)

    spy = _SpyDocumensoClient()
    session = _AccountRecordingSession()

    envelope = asyncio.run(
        esign_service.create_and_send_envelope(
            session,
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            payload=payload,
            pdf_bytes=_PDF_BYTES,
            client=spy,  # type: ignore[arg-type]
        )
    )
    return envelope, spy, session


# ---------------------------------------------------------------------------
# Part 1 — R5.1 / R5.2: one-time links, no OraInvoice account creation.
# ---------------------------------------------------------------------------


def test_send_yields_one_time_signing_links_for_every_recipient(monkeypatch):
    """Every persisted recipient carries the Documenso one-time signing link (R5.1)."""
    payload = EnvelopeCreate(
        agreement_type="sales_agreement",
        originating_entity_type="invoice",
        originating_entity_id=uuid.uuid4(),
        recipients=[
            RecipientIn(name="Alice", email="alice@example.com", signing_role="signer"),
            RecipientIn(name="Bob", email="bob@example.com", signing_role="signer"),
        ],
    )

    envelope, _spy, _session = _run_send(monkeypatch, payload)

    assert envelope.status == "sent"
    assert len(envelope.recipients) == 2

    seen_urls: set[str] = set()
    for recipient in envelope.recipients:
        # Each external recipient gets a Documenso-issued one-time signing link.
        assert recipient.signing_url, (
            f"recipient {recipient.email!r} has no one-time signing link"
        )
        assert recipient.signing_url.startswith("https://"), recipient.signing_url
        assert "/sign/one-time-" in recipient.signing_url
        seen_urls.add(recipient.signing_url)

    # The links are one-time and per-recipient: distinct for each signer.
    assert len(seen_urls) == len(envelope.recipients)


def test_send_creates_no_orainvoice_account_for_external_recipients(monkeypatch):
    """A send provisions NO OraInvoice account record (R5.1, R5.2).

    External recipients sign via the one-time link; they are not OraInvoice
    ``users`` and not Employee-Portal ``employee_portal_users``. The only rows a
    successful send persists are the envelope and its recipient rows.
    """
    payload = EnvelopeCreate(
        agreement_type="employment_agreement",
        originating_entity_type="staff",
        originating_entity_id=uuid.uuid4(),
        recipients=[
            RecipientIn(name="Carol", email="carol@example.com", signing_role="signer"),
            RecipientIn(name="Dave", email="dave@example.com", signing_role="viewer"),
        ],
    )

    envelope, _spy, session = _run_send(monkeypatch, payload)

    persisted = _all_persisted_objects(session)

    # No account model was instantiated/added anywhere in the send path.
    account_rows = [obj for obj in persisted if isinstance(obj, _ACCOUNT_TYPES)]
    assert account_rows == [], (
        f"send must not create OraInvoice accounts, but created: {account_rows!r}"
    )

    # The only persisted types are the esign envelope + its recipients.
    assert all(isinstance(obj, (EsignEnvelope, EsignRecipient)) for obj in persisted)
    assert any(isinstance(obj, EsignEnvelope) for obj in persisted)

    # Recipients still exist and still carry their one-time link (no account swap).
    assert len(envelope.recipients) == 2
    for recipient in envelope.recipients:
        assert recipient.signing_url and recipient.signing_url.startswith("https://")


# ---------------------------------------------------------------------------
# Part 2 — R5.3: no route exposes the Documenso admin/organisation UI.
# ---------------------------------------------------------------------------

# Substrings that would betray a route proxying/embedding the Documenso web UI.
# The Documenso UI proxy, if it ever existed, would carry the vendor name in its
# path; the legitimate esign API surface is named ``/api/v2/esign/...`` and the
# webhook header (``X-Documenso-Secret``) is a header, not a path.
_DOCUMENSO_UI_PATH_MARKERS = ("documenso",)

# Path shapes that would indicate a generic UI proxy/embed/iframe surface.
_UI_PROXY_SUFFIXES = ("/ui", "/app", "/embed", "/iframe", "/proxy", "/console")


def _registered_paths() -> set[str]:
    """Materialise every effective route path of the assembled app.

    The app uses a lazy router-inclusion scheme: ``app.routes`` holds
    ``_IncludedRouter`` wrappers whose concrete routes are only realised by
    calling ``effective_candidates()`` (which yields ``_EffectiveRouteContext``
    leaves carrying the fully-prefixed ``.path``, and possibly nested
    ``_IncludedRouter`` branches). We walk that tree so the scan sees the real,
    prefixed paths (e.g. ``/api/v2/esign/envelopes``) rather than the wrappers.
    """
    from app.main import create_app

    app = create_app()
    paths: set[str] = set()

    def _walk(routes) -> None:
        for route in routes:
            if type(route).__name__ == "_IncludedRouter":
                _walk(route.effective_candidates())
            else:
                path = getattr(route, "path", None)
                if path is not None:
                    paths.add(path)

    _walk(app.routes)
    return paths


def test_no_route_exposes_the_documenso_ui():
    """No registered route proxies/embeds the Documenso admin or org UI (R5.3)."""
    paths = _registered_paths()

    # 1. No path references Documenso directly — a UI proxy would name the vendor.
    documenso_paths = [
        p for p in paths if any(m in p.lower() for m in _DOCUMENSO_UI_PATH_MARKERS)
    ]
    assert documenso_paths == [], (
        "no route may expose a Documenso UI proxy, but found: "
        f"{sorted(documenso_paths)!r}"
    )

    # 2. No esign route is shaped like a UI proxy/embed surface — the esign API
    #    exposes data endpoints only (envelopes, signed-document, webhook).
    esign_ui_proxies = [
        p
        for p in paths
        if p.startswith("/api/v2/esign")
        and any(p.lower().rstrip("/").endswith(s) for s in _UI_PROXY_SUFFIXES)
    ]
    assert esign_ui_proxies == [], (
        "esign routes must not expose a Documenso UI surface, but found: "
        f"{sorted(esign_ui_proxies)!r}"
    )


def test_esign_routes_are_data_endpoints_only():
    """Sanity: the esign surface is the expected data/API + webhook routes only,
    confirming there is no UI-serving route hiding under the prefix (R5.3)."""
    paths = _registered_paths()
    esign_paths = {p for p in paths if p.startswith("/api/v2/esign")}

    # The module must actually be mounted (otherwise the assertion is vacuous).
    assert esign_paths, "expected /api/v2/esign routes to be registered"

    # Every esign path is one of the known API/webhook shapes — none serve HTML
    # or proxy the Documenso web app.
    allowed_exact = {
        "/api/v2/esign/envelopes",
        "/api/v2/esign/field-templates",
    }
    allowed_templates = (
        "/api/v2/esign/envelopes/{",  # detail / void / signed-document / fields (GET+PUT)
        "/api/v2/esign/field-templates/{",  # template detail / delete
        "/api/v2/esign/webhook/{",  # per-org webhook ingestion
    )
    for p in esign_paths:
        ok = p in allowed_exact or any(p.startswith(t) for t in allowed_templates)
        assert ok, f"unexpected esign route (possible UI exposure): {p!r}"
