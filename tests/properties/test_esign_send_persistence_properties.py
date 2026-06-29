"""Property-based test for faithful envelope persistence on a successful send
(task 8.3).

# Feature: esignature-integration, Property 7: Successful send persists a faithful envelope

When :func:`app.modules.esignatures.service.create_and_send_envelope` completes
a successful send (verified org connection, valid PDF, ≥1 signer recipient with
valid emails), it persists exactly one :class:`EsignEnvelope` that faithfully
reflects the inputs plus the Documenso create result:

  * ``org_id``, ``agreement_type`` (one of the 5), ``originating_entity_type``
    / ``originating_entity_id`` and ``created_by`` mirror the caller's inputs;
  * ``status == 'sent'`` and ``documenso_document_id`` is the id returned by the
    Documenso create call;
  * one :class:`EsignRecipient` row per input recipient (same order), each with
    the matching ``name``/``email``, ``recipient_status == 'pending'``, the
    ``signing_role`` stored UPPERCASE, and the ``signing_url`` +
    ``documenso_recipient_id`` captured from the create result.

The test drives the real service flow with a **spy** ``DocumensoClient`` (so the
multi-step create → upload → field → send sequence runs without a real
Documenso) over a lightweight fake async session that captures the added
envelope. The per-org connection gate is satisfied by patching
``service.get_documenso_connection`` to return a verified connection, and the
best-effort audit/notify side-effect is patched to a no-op so the fake session
needs no SAVEPOINT support.

**Validates: Requirements 3.2, 3.6, 4.4, 10.3, 10.4, 13.1**
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph so SQLAlchemy can resolve every string-based
# relationship reference when EsignEnvelope/EsignRecipient are instantiated
# (mirrors tests/properties/test_esign_credential_storage_properties.py).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.integrations.documenso import (  # noqa: E402
    CreatedRecipient,
    DocumensoConnection,
    DocumensoCreateResult,
    map_recipient_role,
)
from app.modules.esignatures import service  # noqa: E402
from app.modules.esignatures.models import EsignEnvelope  # noqa: E402
from app.modules.esignatures.schemas import EnvelopeCreate  # noqa: E402

_AGREEMENT_TYPES = [
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
]
_ENTITY_TYPES = ["invoice", "quote", "staff"]


# ---------------------------------------------------------------------------
# Spy DocumensoClient — records the multi-step flow and returns a faithful
# create result (one CreatedRecipient per input recipient, matched by email,
# each carrying a recipient_id / token / signingUrl).
# ---------------------------------------------------------------------------


class _SpyDocumensoClient:
    def __init__(self, document_id: str, upload_url: str = "https://up.example.test/x"):
        self._document_id = document_id
        self._upload_url = upload_url
        self.create_calls: list[dict] = []
        self.uploads: list[tuple[str, bytes]] = []
        self.field_calls: list[str] = []
        self.send_calls: list[str] = []
        # email (lowercased) -> CreatedRecipient returned by create_document
        self.created_by_email: dict[str, CreatedRecipient] = {}

    async def create_document(
        self, *, title, recipients, pdf_bytes
    ) -> DocumensoCreateResult:
        created: list[CreatedRecipient] = []
        for i, spec in enumerate(recipients):
            cr = CreatedRecipient(
                recipient_id=f"r{i}",
                email=spec.email,
                role=map_recipient_role(spec.role),
                token=f"tok{i}",
                signing_url=f"https://documenso.example.test/sign/tok{i}",
            )
            created.append(cr)
            self.created_by_email[spec.email.strip().lower()] = cr
        self.create_calls.append({"title": title, "recipients": list(recipients)})
        return DocumensoCreateResult(
            document_id=self._document_id,
            upload_url=self._upload_url,
            recipients=created,
        )

    async def upload_pdf(self, upload_url, pdf_bytes) -> None:
        self.uploads.append((upload_url, pdf_bytes))

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
        self.field_calls.append(recipient_id)

    async def send_document(self, document_id, *, signing_order_mode="parallel") -> None:
        self.send_calls.append(document_id)


# ---------------------------------------------------------------------------
# Fake async session — captures the added envelope; flush/refresh are no-ops.
# (Audit/notify are patched to a no-op so begin_nested is never needed.)
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self):
        self.added: list[object] = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def refresh(self, _obj):
        return None


# ---------------------------------------------------------------------------
# Generators — a valid send: valid PDF, ≥1 signer with unique valid emails,
# one of the 5 agreement types, a valid originating entity ref, and the
# Documenso document id the spy will return.
# ---------------------------------------------------------------------------


@st.composite
def _valid_send(draw):
    n = draw(st.integers(min_value=1, max_value=4))
    recipients: list[dict] = []
    for i in range(n):
        local = draw(st.from_regex(r"[a-z]{1,8}", fullmatch=True))
        name = draw(st.from_regex(r"[A-Za-z][A-Za-z ]{0,18}", fullmatch=True))
        role = draw(st.sampled_from(["signer", "viewer"]))
        # Index guarantees a unique email per recipient. The domain avoids
        # reserved/special-use names (e.g. *.test) that EmailStr rejects.
        recipients.append(
            {"name": name, "email": f"{local}{i}@mailhost.io", "signing_role": role}
        )
    # Guarantee at least one signer so the R17 / no-signers guard passes.
    if not any(r["signing_role"] == "signer" for r in recipients):
        recipients[0]["signing_role"] = "signer"

    payload = EnvelopeCreate(
        agreement_type=draw(st.sampled_from(_AGREEMENT_TYPES)),
        originating_entity_type=draw(st.sampled_from(_ENTITY_TYPES)),
        originating_entity_id=draw(st.uuids()),
        recipients=recipients,
    )
    document_id = draw(st.from_regex(r"doc-[a-z0-9]{1,12}", fullmatch=True))
    pdf_bytes = b"%PDF-1.7\n" + draw(st.binary(max_size=64))
    return payload, document_id, pdf_bytes


def _verified_connection() -> DocumensoConnection:
    return DocumensoConnection(
        base_url="https://documenso.example.test",
        service_token="tok_team_scoped_raw",
        webhook_secret="whsec",
        documenso_team_id="team-1",
        webhook_routing_id="route-1",
        is_verified=True,
    )


@settings(max_examples=150, deadline=None)
@given(send=_valid_send(), org_id=st.uuids(), user_id=st.uuids())
def test_successful_send_persists_faithful_envelope(send, org_id, user_id):
    payload, document_id, pdf_bytes = send

    session = _FakeSession()
    spy = _SpyDocumensoClient(document_id=document_id)
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
                pdf_bytes=pdf_bytes,
                client=spy,
            )
        )

    # A successful send actually happened against the (spy) Documenso client.
    assert spy.create_calls, "create_document was never called"
    assert spy.send_calls == [document_id], "send_document was not called with the doc id"

    # Exactly one envelope was persisted, and it is the returned object.
    assert len(session.added) == 1
    persisted = session.added[0]
    assert isinstance(persisted, EsignEnvelope)
    assert persisted is envelope

    # Envelope faithfully reflects the inputs + the create result.
    assert persisted.org_id == org_id
    assert persisted.agreement_type == payload.agreement_type
    assert persisted.agreement_type in _AGREEMENT_TYPES
    assert persisted.originating_entity_type == payload.originating_entity_type
    assert persisted.originating_entity_id == payload.originating_entity_id
    assert persisted.created_by == user_id
    assert persisted.status == "sent"
    assert persisted.documenso_document_id == document_id

    # One recipient row per input recipient, in input order.
    assert len(persisted.recipients) == len(payload.recipients)
    for row, r_in in zip(persisted.recipients, payload.recipients):
        expected_email = str(r_in.email)
        assert row.name == r_in.name
        assert row.email == expected_email
        assert row.recipient_status == "pending"

        # signing_role is persisted UPPERCASE and matches the input role.
        assert row.signing_role == row.signing_role.upper()
        assert row.signing_role == map_recipient_role(r_in.signing_role)

        # signing_url + documenso_recipient_id captured from the create result.
        created = spy.created_by_email[expected_email.strip().lower()]
        assert row.signing_url == created.signing_url
        assert row.documenso_recipient_id == created.recipient_id


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
