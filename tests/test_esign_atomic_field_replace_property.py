"""Property-based test: editing replaces the Documenso field set atomically (task 16.5).

# Feature: esignature-field-placement, Property 19: Atomic field replace on edit-after-send

**Validates: Requirements 13.3, 13.4, 13.6, 13.8**

The service path under test is
:func:`app.modules.esignatures.service.replace_envelope_fields`. Editing an
**editable** envelope's Field_Set replaces it atomically: on success the new set
is created via :meth:`DocumensoClient.replace_fields` (delete + create-many) and
a best-effort ``esign.envelope.fields_edited`` audit entry is written; on a
replace failure the prior set is left in effect, a humanized **502** is returned,
and no partial apply occurs (R13.3, R13.8). A Non_Editable_State envelope is
rejected with a humanized **422** ``not_editable`` and **no** Documenso mutation
(R13.4, R13.6).

A spy :class:`DocumensoClient` (injected via ``client=``) lets the test drive
the replace into success or failure directly — the real client's
``replace_fields`` is capability-gated (``esign_field_replace_supported``
defaults False and raises), but the spy bypasses it so the atomicity branches
are exercised deterministically. A lightweight fake async session isolates the
decision logic with no real DB or network, mirroring
``tests/test_esign_edit_after_send_service.py`` (the no-DB fake-session pattern).

Hypothesis generates varied envelope states (the full 8-status set × per-recipient
signed/unsigned flags) and valid edited Field_Sets (every signer carries a
signature field, all fields in-bounds), then asserts the three-way outcome
against the pure ``editable_state`` gate as an oracle.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import get_args
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
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from app.integrations.documenso import DocumensoError  # noqa: E402
from app.modules.esignatures import service as svc  # noqa: E402
from app.modules.esignatures.errors import (  # noqa: E402
    CODE_DOCUMENSO_ERROR,
    CODE_NOT_EDITABLE,
)
from app.modules.esignatures.field_validation import editable_state  # noqa: E402
from app.modules.esignatures.models import EsignEnvelope, EsignRecipient  # noqa: E402
from app.modules.esignatures.schemas import FieldIn, FieldSetReplace  # noqa: E402
from app.modules.esignatures.status import EnvelopeStatus  # noqa: E402


PBT_SETTINGS = settings(max_examples=150, deadline=None)

ALL_STATUSES = list(get_args(EnvelopeStatus))
# The six supported field types (lowercase, as carried on the wire body).
FIELD_TYPES = ["signature", "initials", "name", "date", "email", "text"]


# ---------------------------------------------------------------------------
# Spy client + fake session (mirrors test_esign_edit_after_send_service.py)
# ---------------------------------------------------------------------------


class _SpyClient:
    """Stand-in for ``DocumensoClient`` injected via ``client=``.

    Records document reads and replace calls. ``replace_fails`` flips the
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


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _signer(email, *, recipient_id, signed=False):
    return EsignRecipient(
        id=uuid.uuid4(),
        name=email.split("@")[0],
        email=email,
        signing_role="SIGNER",
        recipient_status="signed" if signed else "pending",
        documenso_recipient_id=str(recipient_id),
    )


def _make_envelope(*, status, org_id, recipients):
    return EsignEnvelope(
        id=uuid.uuid4(),
        org_id=org_id,
        agreement_type="sales_agreement",
        originating_entity_type="invoice",
        originating_entity_id=uuid.uuid4(),
        documenso_document_id="55",
        status=status,
        recipients=recipients,
    )


def _doc_from_recipients(recipients):
    """Build a live-document payload whose recipient emails/ids match so the
    by-email reconciliation in ``_build_documenso_field_specs`` succeeds."""
    return {
        "recipients": [
            {"id": int(r.documenso_recipient_id), "email": r.email, "role": "SIGNER"}
            for r in recipients
        ],
        "fields": [],
    }


# ---------------------------------------------------------------------------
# Hypothesis strategy: an envelope state + a valid edited Field_Set
# ---------------------------------------------------------------------------


@st.composite
def _coord(draw):
    """A valid (in-bounds, positive-size) normalized rect as (x, y, w, h)."""
    x = draw(st.floats(min_value=0.0, max_value=80.0, allow_nan=False, allow_infinity=False))
    y = draw(st.floats(min_value=0.0, max_value=80.0, allow_nan=False, allow_infinity=False))
    w = draw(st.floats(min_value=1.0, max_value=100.0 - x, allow_nan=False, allow_infinity=False))
    h = draw(st.floats(min_value=1.0, max_value=100.0 - y, allow_nan=False, allow_infinity=False))
    return x, y, w, h


@st.composite
def _scenario(draw):
    status = draw(st.sampled_from(ALL_STATUSES))
    n_recipients = draw(st.integers(min_value=1, max_value=3))
    signed_flags = [draw(st.booleans()) for _ in range(n_recipients)]
    replace_fails = draw(st.booleans())

    recipients = [
        _signer(f"r{i}@example.com", recipient_id=10 + i, signed=signed_flags[i])
        for i in range(n_recipients)
    ]

    # Build a VALID edited Field_Set: every signer carries a signature field,
    # plus a few extra valid fields of varied types on varied recipients/pages.
    fields: list[FieldIn] = []
    for i in range(n_recipients):
        x, y, w, h = draw(_coord())
        fields.append(
            FieldIn(
                type="signature",
                page=1,
                recipient_index=i,
                position_x=x,
                position_y=y,
                width=w,
                height=h,
            )
        )
    for _ in range(draw(st.integers(min_value=0, max_value=3))):
        x, y, w, h = draw(_coord())
        fields.append(
            FieldIn(
                type=draw(st.sampled_from(FIELD_TYPES)),
                page=draw(st.integers(min_value=1, max_value=3)),
                recipient_index=draw(st.integers(min_value=0, max_value=n_recipients - 1)),
                position_x=x,
                position_y=y,
                width=w,
                height=h,
            )
        )

    return status, recipients, fields, replace_fails


def _run_replace(env, recipients, fields, spy, audit_calls):
    async def _spy_audit(db, *, org_id, user_id, envelope, field_count):
        audit_calls.append(field_count)

    org_id = env.org_id
    with mock.patch.object(svc, "_audit_fields_edited", _spy_audit):
        return asyncio.run(
            svc.replace_envelope_fields(
                _FakeSession(env),
                org_id=org_id,
                user_id=uuid.uuid4(),
                envelope_id=env.id,
                body=FieldSetReplace(fields=fields),
                client=spy,
            )
        )


# ---------------------------------------------------------------------------
# Property 19
# ---------------------------------------------------------------------------


@given(scenario=_scenario())
@PBT_SETTINGS
def test_editing_replaces_field_set_atomically(scenario):
    """Property 19: atomic field replace on edit-after-send.

    * editable + valid + replace-ok  -> replace called once, audit attempted,
      returns the edited set;
    * Non_Editable_State             -> 422 ``not_editable``, replace NOT called,
      prior status intact, no audit;
    * editable + replace raises      -> 502 ``documenso_error``, prior status
      intact, no partial apply (no recorded replace, no audit).
    """
    status, recipients, fields, replace_fails = scenario
    org_id = uuid.uuid4()
    env = _make_envelope(status=status, org_id=org_id, recipients=recipients)
    spy = _SpyClient(doc=_doc_from_recipients(recipients), replace_fails=replace_fails)
    audit_calls: list[int] = []

    editable = editable_state(env.status, env.recipients)
    prior_status = env.status

    if not editable:
        # Non_Editable_State -> rejected before any Documenso field mutation.
        with pytest.raises(HTTPException) as exc:
            _run_replace(env, recipients, fields, spy, audit_calls)
        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == CODE_NOT_EDITABLE
        assert spy.replace_calls == []  # no delete + create-many
        assert audit_calls == []  # no audit on a rejected edit
        assert env.status == prior_status  # prior state untouched
        return

    if replace_fails:
        # Replace raised -> humanized 502, prior set intact, no partial apply.
        with pytest.raises(HTTPException) as exc:
            _run_replace(env, recipients, fields, spy, audit_calls)
        assert exc.value.status_code == 502
        assert exc.value.detail["code"] == CODE_DOCUMENSO_ERROR
        assert spy.replace_calls == []  # nothing recorded => no partial apply
        assert audit_calls == []  # no audit on failure
        assert env.status == prior_status  # prior status left intact
        return

    # editable + valid + replace-ok -> atomic replace of exactly the edited set.
    out = _run_replace(env, recipients, fields, spy, audit_calls)

    # Exactly one replace call (a single delete + create-many of the new set).
    assert len(spy.replace_calls) == 1
    document_id, specs = spy.replace_calls[0]
    assert document_id == "55"
    # Exactly the edited set, one wire-ready spec per placed field, in order.
    assert len(specs) == len(fields)
    for spec, field in zip(specs, fields):
        assert spec.type == svc.map_field_type(field.type)
        assert spec.page_number == field.page
        assert spec.page_x == field.position_x
        assert spec.page_y == field.position_y
        assert spec.width == field.width
        assert spec.height == field.height
        assert spec.field_meta is not None  # required always carried
        assert spec.recipient_id == int(recipients[field.recipient_index].documenso_recipient_id)

    # Best-effort audit attempted with the new field count (R13.7).
    assert audit_calls == [len(fields)]

    # Returns the newly-applied set; the envelope stays editable.
    assert out.editable is True
    assert len(out.fields) == len(fields)


# ---------------------------------------------------------------------------
# Supporting example cases (anchor the three branches explicitly)
# ---------------------------------------------------------------------------


def _one_signer_valid_fields():
    return [
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


def test_example_editable_success_replaces_once_and_audits():
    org_id = uuid.uuid4()
    recipients = [_signer("alex@example.com", recipient_id=10)]
    env = _make_envelope(status="sent", org_id=org_id, recipients=recipients)
    spy = _SpyClient(doc=_doc_from_recipients(recipients))
    audit_calls: list[int] = []
    out = _run_replace(env, recipients, _one_signer_valid_fields(), spy, audit_calls)
    assert len(spy.replace_calls) == 1
    assert audit_calls == [1]
    assert out.editable is True


def test_example_non_editable_rejects_without_mutation():
    org_id = uuid.uuid4()
    recipients = [_signer("alex@example.com", recipient_id=10, signed=True)]
    env = _make_envelope(status="sent", org_id=org_id, recipients=recipients)
    spy = _SpyClient(doc=_doc_from_recipients(recipients))
    audit_calls: list[int] = []
    with pytest.raises(HTTPException) as exc:
        _run_replace(env, recipients, _one_signer_valid_fields(), spy, audit_calls)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == CODE_NOT_EDITABLE
    assert spy.replace_calls == []
    assert audit_calls == []


def test_example_replace_failure_is_502_no_partial_apply():
    org_id = uuid.uuid4()
    recipients = [_signer("alex@example.com", recipient_id=10)]
    env = _make_envelope(status="sent", org_id=org_id, recipients=recipients)
    spy = _SpyClient(doc=_doc_from_recipients(recipients), replace_fails=True)
    audit_calls: list[int] = []
    with pytest.raises(HTTPException) as exc:
        _run_replace(env, recipients, _one_signer_valid_fields(), spy, audit_calls)
    assert exc.value.status_code == 502
    assert exc.value.detail["code"] == CODE_DOCUMENSO_ERROR
    assert spy.replace_calls == []
    assert audit_calls == []
    assert env.status == "sent"
