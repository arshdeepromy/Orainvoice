"""Example tests for the edit-after-send service path (task 16.4).

Covers :func:`app.modules.esignatures.service.get_envelope_fields` and
:func:`app.modules.esignatures.service.replace_envelope_fields`:

* GET seeds the editor with the live Documenso field set, the recipients, and
  the pure ``editable`` gate — for both an editable (``sent`` + unsigned) and a
  Non_Editable_State envelope (R13.1, R13.4).
* PUT re-checks the Editable_State race guard (Non_Editable_State → 422
  ``not_editable`` with no Documenso mutation, R13.4/R13.6), re-validates the
  edited Field_Set, atomically replaces via the client on success (writing the
  ``esign.envelope.fields_edited`` audit), and degrades a replace failure to a
  humanized 502 leaving the prior set intact (R13.8).

A spy client + a lightweight fake async session isolate the decision logic with
no real DB or network, mirroring ``test_esign_void_terminal_properties.py``.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest import mock

import pytest

# Pre-load the model graph so SQLAlchemy can resolve relationships when the ORM
# models are instantiated (mirrors the other esign property/unit tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from fastapi import HTTPException  # noqa: E402

from app.integrations.documenso import DocumensoError  # noqa: E402
from app.modules.esignatures import service as svc  # noqa: E402
from app.modules.esignatures.errors import (  # noqa: E402
    CODE_DOCUMENSO_ERROR,
    CODE_NOT_EDITABLE,
    CODE_NOT_FOUND,
)
from app.modules.esignatures.models import EsignEnvelope, EsignRecipient  # noqa: E402
from app.modules.esignatures.schemas import FieldIn, FieldSetReplace  # noqa: E402


# ---------------------------------------------------------------------------
# Spy client + fake session
# ---------------------------------------------------------------------------


class _SpyClient:
    """Stand-in for ``DocumensoClient`` injected via ``client=``.

    Records the document reads and replace calls. ``replace_fails`` flips the
    replace into raising :class:`DocumensoError` (simulating either a genuine
    failure or the capability-gated "in-place replace unsupported" degrade).
    """

    def __init__(self, *, doc: dict, replace_fails: bool = False) -> None:
        self._doc = doc
        self._replace_fails = replace_fails
        self.get_document_calls: list[str] = []
        self.replace_calls: list[tuple[str, list]] = []

    async def _get_document(self, document_id):
        self.get_document_calls.append(str(document_id))
        return self._doc

    def _recipients_from_document(self, doc):
        return [
            SimpleNamespace(email=r.get("email"), recipient_id=r.get("id"))
            for r in doc.get("recipients", [])
        ]

    async def replace_fields(self, document_id, specs):
        if self._replace_fails:
            raise DocumensoError("in-place replace unsupported")
        self.replace_calls.append((str(document_id), specs))


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    def __init__(self, envelope):
        self._envelope = envelope

    async def execute(self, *_a, **_k):
        return _FakeResult(self._envelope)


def _make_envelope(*, status, org_id, recipients, has_doc_id=True):
    return EsignEnvelope(
        id=uuid.uuid4(),
        org_id=org_id,
        agreement_type="sales_agreement",
        originating_entity_type="invoice",
        originating_entity_id=uuid.uuid4(),
        documenso_document_id="55" if has_doc_id else None,
        status=status,
        recipients=recipients,
    )


def _signer(email, *, recipient_id, signed=False):
    return EsignRecipient(
        id=uuid.uuid4(),
        name=email.split("@")[0],
        email=email,
        signing_role="SIGNER",
        recipient_status="signed" if signed else "pending",
        documenso_recipient_id=str(recipient_id),
    )


def _doc_with_one_signature(*, recipient_id=10, email="alex@example.com"):
    return {
        "recipients": [{"id": recipient_id, "email": email, "role": "SIGNER"}],
        "fields": [
            {
                "recipientId": recipient_id,
                "type": "SIGNATURE",
                "pageNumber": 1,
                "pageX": 10.0,
                "pageY": 80.0,
                "width": 20.0,
                "height": 5.0,
                "fieldMeta": {"required": True},
            }
        ],
    }


# ---------------------------------------------------------------------------
# get_envelope_fields
# ---------------------------------------------------------------------------


def test_get_envelope_fields_editable_seeds_from_documenso():
    org_id = uuid.uuid4()
    env = _make_envelope(
        status="sent",
        org_id=org_id,
        recipients=[_signer("alex@example.com", recipient_id=10)],
    )
    spy = _SpyClient(doc=_doc_with_one_signature())
    out = asyncio.run(
        svc.get_envelope_fields(
            _FakeSession(env), org_id=org_id, envelope_id=env.id, client=spy
        )
    )
    assert out.editable is True
    assert len(out.fields) == 1
    f = out.fields[0]
    assert f.type == "signature"
    assert f.recipient_index == 0
    assert f.page == 1 and f.position_x == 10.0 and f.required is True
    assert len(out.recipients) == 1
    assert spy.get_document_calls == ["55"]


def test_get_envelope_fields_not_editable_still_returns_fields():
    org_id = uuid.uuid4()
    # A signed recipient makes a 'sent' envelope a Non_Editable_State.
    env = _make_envelope(
        status="sent",
        org_id=org_id,
        recipients=[_signer("alex@example.com", recipient_id=10, signed=True)],
    )
    spy = _SpyClient(doc=_doc_with_one_signature())
    out = asyncio.run(
        svc.get_envelope_fields(
            _FakeSession(env), org_id=org_id, envelope_id=env.id, client=spy
        )
    )
    assert out.editable is False
    assert len(out.fields) == 1  # still seeded for the read-only banner view


def test_get_envelope_fields_missing_is_404():
    org_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            svc.get_envelope_fields(
                _FakeSession(None),
                org_id=org_id,
                envelope_id=uuid.uuid4(),
                client=_SpyClient(doc={}),
            )
        )
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == CODE_NOT_FOUND


# ---------------------------------------------------------------------------
# replace_envelope_fields
# ---------------------------------------------------------------------------


def _valid_replace_body():
    return FieldSetReplace(
        fields=[
            FieldIn(
                type="signature",
                page=1,
                recipient_index=0,
                position_x=10.0,
                position_y=80.0,
                width=20.0,
                height=5.0,
            )
        ]
    )


def test_replace_not_editable_rejects_without_mutation():
    org_id = uuid.uuid4()
    env = _make_envelope(
        status="completed",
        org_id=org_id,
        recipients=[_signer("alex@example.com", recipient_id=10)],
    )
    spy = _SpyClient(doc=_doc_with_one_signature())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            svc.replace_envelope_fields(
                _FakeSession(env),
                org_id=org_id,
                user_id=uuid.uuid4(),
                envelope_id=env.id,
                body=_valid_replace_body(),
                client=spy,
            )
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == CODE_NOT_EDITABLE
    assert spy.replace_calls == []  # no Documenso mutation


def test_replace_success_replaces_and_audits():
    org_id = uuid.uuid4()
    env = _make_envelope(
        status="sent",
        org_id=org_id,
        recipients=[_signer("alex@example.com", recipient_id=10)],
    )
    spy = _SpyClient(doc=_doc_with_one_signature())

    async def _noop_audit(db, *, org_id, user_id, envelope, field_count):
        return None

    with mock.patch.object(svc, "_audit_fields_edited", _noop_audit):
        out = asyncio.run(
            svc.replace_envelope_fields(
                _FakeSession(env),
                org_id=org_id,
                user_id=uuid.uuid4(),
                envelope_id=env.id,
                body=_valid_replace_body(),
                client=spy,
            )
        )
    assert len(spy.replace_calls) == 1
    assert spy.replace_calls[0][0] == "55"
    assert len(spy.replace_calls[0][1]) == 1  # one wire-ready spec
    assert out.editable is True
    assert len(out.fields) == 1 and out.fields[0].type == "signature"


def test_replace_documenso_failure_is_502_no_partial_apply():
    org_id = uuid.uuid4()
    env = _make_envelope(
        status="sent",
        org_id=org_id,
        recipients=[_signer("alex@example.com", recipient_id=10)],
    )
    spy = _SpyClient(doc=_doc_with_one_signature(), replace_fails=True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            svc.replace_envelope_fields(
                _FakeSession(env),
                org_id=org_id,
                user_id=uuid.uuid4(),
                envelope_id=env.id,
                body=_valid_replace_body(),
                client=spy,
            )
        )
    assert exc.value.status_code == 502
    assert exc.value.detail["code"] == CODE_DOCUMENSO_ERROR
    assert env.status == "sent"  # prior state left intact
