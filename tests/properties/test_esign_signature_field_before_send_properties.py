"""Property-based test: every signer has a signature field before send (task 8.8).

# Feature: esignature-integration, Property 25: Every signer has a signature field before send

**Validates: Requirements 17.1, 17.2**

The function under test is
:func:`app.modules.esignatures.service.create_and_send_envelope`, with the R17
hardening implemented in task 8.7. The property has two halves:

* **Success half (R17.1).** For *any* send that completes successfully (verified
  org connection, valid PDF, ≥1 signer recipient with valid emails, and a
  Documenso client that lets every field be placed), ``send_document`` is called
  **exactly once** and **every** signer recipient (Documenso role
  ``SIGNER``/``APPROVER``) had ``place_signature_field`` called for *its* own
  Documenso ``recipient_id`` **before** ``send_document``. Viewer recipients
  never receive a field.

* **Failure half (R17.2).** For *any* send where a signature field cannot be
  placed for ≥1 signer — either because the placement call itself raises, or
  because the ``create_document`` result omits that signer's ``recipient_id`` —
  the send is **rejected**: ``send_document`` is **never** called, the service
  raises :class:`fastapi.HTTPException` **422** ``signature_field_failed`` whose
  human-readable message **names** the offending signer, and an ``error``-status
  envelope is recorded on the fresh, independently-committed session (via
  ``_record_error_envelope`` → ``async_session_factory``).

The whole flow runs in-memory, mirroring the no-DB ``asyncio.run`` convention of
``test_esign_documenso_failure_property`` and ``test_esign_send_persistence_properties``:
the per-org connection gate is satisfied with a stub verified connection, the
Documenso client is a recording spy (with modes that make a chosen signer's
field un-placeable), ``_audit_and_notify_send`` is a no-op, and — for the
failure half — ``async_session_factory`` is replaced with a capturing fake
session so the fresh-session error-envelope write is observed without a
database.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest import mock

import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph so SQLAlchemy can resolve every string-based
# relationship reference when EsignEnvelope/EsignRecipient are instantiated
# (mirrors the other esign property tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.integrations.documenso import (  # noqa: E402
    CreatedRecipient,
    DocumensoApiError,
    DocumensoConnection,
    DocumensoCreateResult,
    map_recipient_role,
)
from app.modules.esignatures import service  # noqa: E402
from app.modules.esignatures.errors import (  # noqa: E402
    CODE_SIGNATURE_FIELD_FAILED,
)
from app.modules.esignatures.models import EsignEnvelope, EsignRecipient  # noqa: E402
from app.modules.esignatures.schemas import EnvelopeCreate, RecipientIn  # noqa: E402

# >= 100 examples per the task; deadline disabled because each example drives an
# asyncio event loop through the full send flow.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

# The Documenso roles that actually sign and therefore must carry a SIGNATURE
# field before send (mirrors ``service._SIGNING_ROLES``).
_SIGNING_ROLES = frozenset({"SIGNER", "APPROVER"})

_AGREEMENT_TYPES = (
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
)
_ENTITY_TYPES = ("invoice", "quote", "staff")

# A minimal but valid PDF (starts with the %PDF magic bytes ``is_pdf`` checks).
_VALID_PDF = b"%PDF-1.4\n1 0 obj<</Type/Page>>endobj\n%%EOF"


# ---------------------------------------------------------------------------
# Spy DocumensoClient — records ordered calls and supports field-placement
# failure modes for a chosen signer.
# ---------------------------------------------------------------------------


class _SpyClient:
    """A DocumensoClient stand-in that records the multi-step flow.

    Two failure modes target a single signer (identified by lowercased email):

    * ``raise_field_for`` — ``place_signature_field`` raises a
      :class:`DocumensoApiError` when called for that signer's recipient id.
    * ``omit_recipient_id_for`` — ``create_document`` returns that signer's
      :class:`CreatedRecipient` with an **empty** ``recipient_id`` so the
      service can never bind a field to it.

    When neither mode is set the spy lets every field be placed (the success
    half). ``calls`` is the ordered list of method names; ``field_calls`` is the
    ordered list of ``recipient_id`` values passed to ``place_signature_field``.
    """

    DEFAULT_TIMEOUT = 10.0

    def __init__(
        self,
        document_id: str,
        *,
        raise_field_for: str | None = None,
        omit_recipient_id_for: str | None = None,
    ) -> None:
        self.document_id = document_id
        self._raise_field_for = raise_field_for
        self._omit_recipient_id_for = omit_recipient_id_for
        self.calls: list[str] = []
        self.field_calls: list[str] = []
        # email (lowercased) -> CreatedRecipient returned by create_document
        self.created_by_email: dict[str, CreatedRecipient] = {}
        # recipient_id -> email (lowercased) for the raise-mode lookup
        self._email_by_recipient_id: dict[str, str] = {}

    async def create_document(self, *, title, recipients, pdf_bytes) -> DocumensoCreateResult:
        self.calls.append("create_document")
        created: list[CreatedRecipient] = []
        for i, spec in enumerate(recipients):
            email_l = str(spec.email).strip().lower()
            recipient_id = f"r{i}"
            if self._omit_recipient_id_for == email_l:
                recipient_id = ""  # the service cannot bind a field to this one
            cr = CreatedRecipient(
                recipient_id=recipient_id,
                email=str(spec.email),
                role=map_recipient_role(spec.role),
                token=f"tok{i}",
                signing_url=f"https://sign.example.test/{i}",
            )
            created.append(cr)
            self.created_by_email[email_l] = cr
            if recipient_id:
                self._email_by_recipient_id[recipient_id] = email_l
        return DocumensoCreateResult(
            document_id=self.document_id,
            upload_url="https://upload.example.test/doc",
            recipients=created,
        )

    async def upload_pdf(self, upload_url, pdf_bytes) -> None:
        self.calls.append("upload_pdf")

    async def place_signature_field(
        self,
        document_id,
        *,
        recipient_id,
        page_number,
        page_x,
        page_y,
        page_width,
        page_height,
    ) -> None:
        self.calls.append("place_signature_field")
        # Record placement BEFORE a possible raise so the test can confirm the
        # service attempted to bind a field to this recipient.
        self.field_calls.append(recipient_id)
        if (
            self._raise_field_for is not None
            and self._email_by_recipient_id.get(recipient_id) == self._raise_field_for
        ):
            raise DocumensoApiError("field placement failed", status=500)

    async def send_document(self, document_id, **_kwargs) -> None:
        self.calls.append("send_document")


# ---------------------------------------------------------------------------
# Capturing fake session/factory — observes the fresh-session error envelope.
# (Same shape as test_esign_documenso_failure_property.)
# ---------------------------------------------------------------------------


class _FakeTxn:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _CapturingSession:
    """AsyncSession stand-in capturing ORM objects written by
    ``_record_error_envelope`` on the fresh ``async_session_factory`` session."""

    def __init__(self, captured: list) -> None:
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def begin(self):
        return _FakeTxn()

    async def execute(self, *_args, **_kwargs):
        return None

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self._captured.append(obj)

    async def flush(self):
        for obj in self._captured:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def refresh(self, _obj):
        return None


# ---------------------------------------------------------------------------
# Request-session fake — used for the SUCCESS half (captures the sent envelope).
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def refresh(self, _obj):
        return None


class _DummyDb:
    """Placeholder request session for the failure half (only handed to the
    patched connection loader; the error envelope goes to the fresh session)."""


def _verified_connection() -> DocumensoConnection:
    return DocumensoConnection(
        base_url="https://documenso.example.test",
        service_token="tok_raw",
        webhook_secret="whsec",
        documenso_team_id="team-1",
        webhook_routing_id="route-1",
        is_verified=True,
    )


# ---------------------------------------------------------------------------
# Generators — recipients with a mix of signers + viewers, unique valid emails.
# ---------------------------------------------------------------------------

_LOCAL = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=8
)
_NAME = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ",
    min_size=1,
    max_size=14,
)


@st.composite
def _recipients(draw) -> list[RecipientIn]:
    """A non-empty recipient list with >= 1 signer, unique emails, mixed roles.

    The index guarantees a unique email per recipient so the email-keyed
    matching in the service (and the spy) is unambiguous.
    """
    n = draw(st.integers(min_value=1, max_value=4))
    out: list[RecipientIn] = []
    for i in range(n):
        local = draw(_LOCAL)
        name = (draw(_NAME).strip() or f"Recipient {i}")
        role = "signer" if i == 0 else draw(st.sampled_from(("signer", "viewer")))
        out.append(
            RecipientIn(
                name=name,
                email=f"{local}{i}@mailhost.io",
                signing_role=role,
            )
        )
    # Guarantee at least one signer (the first recipient is already a signer,
    # but keep this explicit so a future edit to the loop can't break R17).
    if not any(r.signing_role == "signer" for r in out):
        out[0] = RecipientIn(
            name=out[0].name, email=str(out[0].email), signing_role="signer"
        )
    return out


@st.composite
def _payloads(draw) -> EnvelopeCreate:
    return EnvelopeCreate(
        agreement_type=draw(st.sampled_from(_AGREEMENT_TYPES)),
        originating_entity_type=draw(st.sampled_from(_ENTITY_TYPES)),
        originating_entity_id=uuid.uuid4(),
        recipients=draw(_recipients()),
    )


def _signer_emails(payload: EnvelopeCreate) -> list[str]:
    """Lowercased emails of recipients whose mapped Documenso role signs."""
    return [
        str(r.email).strip().lower()
        for r in payload.recipients
        if map_recipient_role(r.signing_role) in _SIGNING_ROLES
    ]


# ---------------------------------------------------------------------------
# Property 25 — success half: every signer has a field, placed before send.
# ---------------------------------------------------------------------------


class TestEverySignerHasFieldBeforeSend:
    """Property 25 (success half): R17.1.

    For any successful send, ``send_document`` is called exactly once and every
    signer had a SIGNATURE field placed (for its own recipient id) before it.

    **Validates: Requirements 17.1**
    """

    @PBT_SETTINGS
    @given(payload=_payloads(), org_id=st.uuids(), user_id=st.uuids())
    def test_success_every_signer_field_placed_before_send(
        self, payload: EnvelopeCreate, org_id, user_id
    ):
        session = _FakeSession()
        spy = _SpyClient(document_id="doc-ok")
        conn = _verified_connection()

        async def _fake_get_conn(_db, _org_id):
            return conn

        async def _noop_audit(*_args, **_kwargs):
            return None

        with mock.patch.object(service, "get_documenso_connection", _fake_get_conn), \
                mock.patch.object(service, "_audit_and_notify_send", _noop_audit):
            envelope = asyncio.run(
                service.create_and_send_envelope(
                    session,
                    org_id=org_id,
                    user_id=user_id,
                    payload=payload,
                    pdf_bytes=_VALID_PDF,
                    client=spy,
                )
            )

        signer_emails = _signer_emails(payload)
        assert signer_emails, "generator must always produce >= 1 signer"

        # send_document was called exactly once.
        assert spy.calls.count("send_document") == 1

        # Every signer had place_signature_field called for ITS own recipient id
        # BEFORE send_document was called.
        send_index = spy.calls.index("send_document")
        # No place_signature_field call occurs after send_document.
        assert "place_signature_field" not in spy.calls[send_index + 1:]

        placed_recipient_ids = set(spy.field_calls)
        for email_l in signer_emails:
            created = spy.created_by_email[email_l]
            assert created.recipient_id, "spy gave the signer a recipient id"
            assert created.recipient_id in placed_recipient_ids, (
                f"signer {email_l} had no signature field placed"
            )

        # Exactly one field per signer; viewers got none → field count == signers.
        assert len(spy.field_calls) == len(signer_emails)
        viewer_recipient_ids = {
            spy.created_by_email[str(r.email).strip().lower()].recipient_id
            for r in payload.recipients
            if map_recipient_role(r.signing_role) not in _SIGNING_ROLES
        }
        assert placed_recipient_ids.isdisjoint(viewer_recipient_ids), (
            "a viewer recipient was given a signature field"
        )

        # A faithful, sent envelope was persisted.
        assert isinstance(envelope, EsignEnvelope)
        assert envelope.status == "sent"
        assert envelope in session.added


# ---------------------------------------------------------------------------
# Property 25 — failure half: an un-placeable signer field rejects the send.
# ---------------------------------------------------------------------------


class TestUnplaceableSignerFieldRejectsSend:
    """Property 25 (failure half): R17.2.

    For any send where a signature field cannot be placed for >= 1 signer (the
    placement call raises, OR ``create_document`` omits that signer's recipient
    id), the send is rejected: no ``send_document`` call, a humanized 422
    ``signature_field_failed`` naming the signer, and an ``error`` envelope is
    recorded.

    **Validates: Requirements 17.2**
    """

    @PBT_SETTINGS
    @given(
        payload=_payloads(),
        mode=st.sampled_from(("raise", "omit_id")),
        target_pick=st.integers(min_value=0, max_value=3),
        org_id=st.uuids(),
        user_id=st.uuids(),
    )
    def test_failure_unplaceable_signer_blocks_send_and_records_error(
        self, payload: EnvelopeCreate, mode: str, target_pick: int, org_id, user_id
    ):
        signer_emails = _signer_emails(payload)
        assert signer_emails
        # Choose one signer to be un-placeable (deterministic from target_pick).
        target_email = signer_emails[target_pick % len(signer_emails)]
        # The human-readable name the service should put in the message.
        target_name = next(
            r.name
            for r in payload.recipients
            if str(r.email).strip().lower() == target_email
        )

        if mode == "raise":
            spy = _SpyClient(document_id="doc-fail", raise_field_for=target_email)
        else:
            spy = _SpyClient(
                document_id="doc-fail", omit_recipient_id_for=target_email
            )

        captured: list = []
        conn = _verified_connection()

        async def _fake_get_conn(_db, _org_id):
            return conn

        def _factory():
            return _CapturingSession(captured)

        async def _noop_audit(*_args, **_kwargs):
            return None

        exc: HTTPException | None = None
        with mock.patch.object(service, "get_documenso_connection", _fake_get_conn), \
                mock.patch.object(service, "async_session_factory", _factory), \
                mock.patch.object(service, "_audit_and_notify_send", _noop_audit):
            try:
                asyncio.run(
                    service.create_and_send_envelope(
                        _DummyDb(),
                        org_id=org_id,
                        user_id=user_id,
                        payload=payload,
                        pdf_bytes=_VALID_PDF,
                        client=spy,
                    )
                )
            except HTTPException as e:
                exc = e

        # The send was rejected with a humanized 422 signature_field_failed ...
        assert exc is not None, "expected the send to be rejected"
        assert exc.status_code == 422
        assert isinstance(exc.detail, dict)
        assert exc.detail.get("code") == CODE_SIGNATURE_FIELD_FAILED
        message = exc.detail.get("message")
        assert isinstance(message, str) and message
        # ... naming the offending signer (by name, falling back to email).
        assert target_name in message or target_email in message, (
            f"message must identify the failing signer: {message!r}"
        )
        # No raw exception text is leaked.
        assert "DocumensoApiError" not in message
        assert "field placement failed" not in message

        # ... send_document was NEVER called ...
        assert "send_document" not in spy.calls

        # ... and an error-status envelope was recorded on the fresh session.
        envelopes = [obj for obj in captured if isinstance(obj, EsignEnvelope)]
        assert len(envelopes) == 1
        env = envelopes[0]
        assert env.status == "error"
        assert env.org_id == org_id
        assert env.agreement_type == payload.agreement_type
        assert env.originating_entity_type == payload.originating_entity_type
        assert env.originating_entity_id == payload.originating_entity_id
        assert env.last_error
        assert "DocumensoApiError" not in (env.last_error or "")
        # The document id known at the point of failure (create succeeded).
        assert env.documenso_document_id == "doc-fail"
        # No successful envelope/recipient leaked onto the request session.
        assert not any(isinstance(o, EsignRecipient) for o in captured)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
