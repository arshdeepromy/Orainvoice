"""Property-based test: signed documents stored only via the encrypted pipeline.

# Feature: esignature-integration, Property 19: Signed documents are stored only via the encrypted pipeline

**Validates: Requirements 9.2, 9.3, 9.4, 9.5, 9.7, 15.2**

Property 19 (task 13.4): *for staff origin, the signed PDF is stored only on the
envelope's encrypted ``file_key`` (no ``ComplianceDocument`` row) and surfaced
via the merged staff documents listing, served through
``GET /api/v2/esign/envelopes/{id}/signed-document``; for invoice/quote it is
referenced on the entity. In all cases nothing is written to the plaintext
compliance store.*

This exercises :func:`app.modules.esignatures.signed_document.retrieve_and_store_signed_document`
— the single seam both the webhook ``completed`` transition (task 12.2) and the
scheduled retry sweep (task 13.3) drive. Two complementary properties are
checked across **all** originating-entity types (``staff`` / ``invoice`` /
``quote``):

* **Success** — when Documenso returns the signed bytes, those bytes are stored
  through **exactly one** storage seam, the encrypted uploads pipeline
  (``_store_via_encrypted_pipeline`` → ``app.modules.uploads.router._store``,
  category ``esign_signed``). The envelope ends ``signed_doc_status='stored'``
  with the returned ``signed_doc_file_key``, and **no other ORM row is created**
  (no ``ComplianceDocument`` — ``session.add`` is never called), uniformly for
  every origin including staff (R9.2, R9.3, R9.4, R15.2).

* **Failure** — when ``download_signed`` raises a ``DocumensoError`` the envelope
  is **kept** ``completed``, flagged ``signed_doc_status='pending_retrieval'``
  with a humanized ``last_error``, **no** storage call is made and **nothing**
  is written anywhere else (no ``session.add``) so the sweep retries (R9.5,
  R9.7).

The whole flow runs in-memory: ``async_session_factory`` is replaced with a
capturing fake session that serves a generated ``completed`` envelope and
records every ``add``/``flush``; the Documenso client is an injected spy; the
encrypted-pipeline store is a recording spy that isolates the test from real
``StorageManager``/disk while still proving the encrypted pipeline is the path
used; ``write_audit_log`` is a no-op. Mirrors the no-DB, ``asyncio.run``
convention of ``test_esign_sweep_unit`` / ``test_esign_documenso_failure_property``.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the model graph so SQLAlchemy can resolve string-based relationships
# when EsignEnvelope is instantiated (mirrors the other esign unit/property tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.integrations.documenso import DocumensoError  # noqa: E402
from app.modules.esignatures import signed_document as sd  # noqa: E402
from app.modules.esignatures.models import EsignEnvelope  # noqa: E402
from app.modules.esignatures.signed_document import (  # noqa: E402
    retrieve_and_store_signed_document,
)

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# each example drives an asyncio event loop through the full retrieval flow.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

_ENTITY_TYPES = ("staff", "invoice", "quote")
_AGREEMENT_TYPES = (
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
)
# The two non-terminal signed-doc states an envelope can be in before storage.
_PRE_STORE_SIGNED_STATUSES = ("none", "pending_retrieval")


# ---------------------------------------------------------------------------
# Spy Documenso client — returns the signed bytes, or raises at download.
# ---------------------------------------------------------------------------


class _SpyClient:
    """A DocumensoClient stand-in for the retrieval step.

    ``download_signed`` returns the scripted PDF bytes (success) or raises the
    scripted exception (failure), recording each call so the test can assert the
    document id requested.
    """

    DEFAULT_TIMEOUT = 10.0

    def __init__(self, pdf_bytes: bytes, raise_exc: Exception | None = None) -> None:
        self._pdf_bytes = pdf_bytes
        self._raise_exc = raise_exc
        self.download_calls: list[str] = []

    async def download_signed(self, document_id):  # noqa: ANN001
        self.download_calls.append(document_id)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._pdf_bytes


# ---------------------------------------------------------------------------
# Capturing fake session/factory — serves one envelope, records add/flush.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, envelope):
        self._envelope = envelope

    def scalar_one_or_none(self):
        return self._envelope


class _FakeTxn:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *_exc):
        return False


class _FakeSavepoint:
    async def commit(self):
        return None

    async def rollback(self):
        return None


class _CapturingSession:
    """Minimal AsyncSession stand-in.

    ``_load_envelope`` does ``execute(...).scalar_one_or_none()`` → the generated
    envelope. The success path mutates that envelope in place and ``flush``es;
    it must NEVER ``add`` a new ORM row (a ``ComplianceDocument`` row would show
    up here). ``begin_nested`` backs the best-effort audit SAVEPOINT.
    """

    def __init__(self, envelope) -> None:
        self._envelope = envelope
        self.added: list = []
        self.flushes = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def begin(self):
        return _FakeTxn()

    async def begin_nested(self):
        return _FakeSavepoint()

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._envelope)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1


def _make_envelope(*, org_id, entity_type, agreement_type, signed_doc_status):
    env = EsignEnvelope()
    env.id = uuid.uuid4()
    env.org_id = org_id
    env.agreement_type = agreement_type
    env.originating_entity_type = entity_type
    env.originating_entity_id = uuid.uuid4()
    env.documenso_document_id = f"doc-{uuid.uuid4().hex[:8]}"
    env.status = "completed"
    env.signed_doc_status = signed_doc_status
    env.signed_doc_file_key = None
    env.last_error = None
    return env


async def _noop_set_rls(_session, _org_id):
    return None


async def _noop_audit(*_args, **_kwargs):
    return None


@contextmanager
def _patched_seams(session, store_fn):
    """Patch every no-DB seam for one example via context managers.

    Hypothesis disallows function-scoped fixtures (e.g. ``monkeypatch``) inside
    ``@given`` because they are not reset per generated input, so each example
    patches the seams itself: the fresh-session factory, the RLS no-op, the
    audit no-op, and the encrypted-pipeline store spy.
    """
    with patch.object(sd, "async_session_factory", lambda: session), patch.object(
        sd, "_set_rls_org_id", _noop_set_rls
    ), patch.object(sd, "write_audit_log", _noop_audit), patch.object(
        sd, "_store_via_encrypted_pipeline", store_fn
    ):
        yield


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

_PDF_BYTES = st.binary(min_size=1, max_size=64)


@st.composite
def _success_scenario(draw):
    return {
        "entity_type": draw(st.sampled_from(_ENTITY_TYPES)),
        "agreement_type": draw(st.sampled_from(_AGREEMENT_TYPES)),
        "signed_doc_status": draw(st.sampled_from(_PRE_STORE_SIGNED_STATUSES)),
        "pdf_bytes": draw(_PDF_BYTES),
    }


@st.composite
def _failure_scenario(draw):
    return {
        "entity_type": draw(st.sampled_from(_ENTITY_TYPES)),
        "agreement_type": draw(st.sampled_from(_AGREEMENT_TYPES)),
        "signed_doc_status": draw(st.sampled_from(_PRE_STORE_SIGNED_STATUSES)),
    }


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestSignedDocumentStoredOnlyViaEncryptedPipeline:
    """Property 19: signed documents are stored only via the encrypted pipeline.

    **Validates: Requirements 9.2, 9.3, 9.4, 9.5, 9.7, 15.2**
    """

    @given(scenario=_success_scenario())
    @PBT_SETTINGS
    def test_success_stores_only_via_encrypted_pipeline(self, scenario):
        """For every origin (incl. staff): the signed bytes go through the
        encrypted pipeline ONLY, no ComplianceDocument row is created, and the
        envelope is flagged ``stored`` with the pipeline's ``file_key``."""
        org_id = uuid.uuid4()
        envelope = _make_envelope(
            org_id=org_id,
            entity_type=scenario["entity_type"],
            agreement_type=scenario["agreement_type"],
            signed_doc_status=scenario["signed_doc_status"],
        )
        session = _CapturingSession(envelope)

        # Recording spy for the ONLY permitted storage seam (encrypted pipeline).
        store_calls: list[dict] = []
        expected_key = f"esign_signed/{org_id}/{uuid.uuid4().hex}.pdf"

        async def _spy_store(_db, *, org_id, envelope_id, pdf_bytes):  # noqa: ANN001
            store_calls.append(
                {"org_id": org_id, "envelope_id": envelope_id, "pdf_bytes": pdf_bytes}
            )
            return expected_key

        spy = _SpyClient(scenario["pdf_bytes"])
        with _patched_seams(session, _spy_store):
            outcome = asyncio.run(
                retrieve_and_store_signed_document(
                    envelope_id=envelope.id, org_id=org_id, client=spy
                )
            )

        # The signed document was retrieved for this envelope's Documenso doc.
        assert spy.download_calls == [envelope.documenso_document_id]

        # Stored through the encrypted pipeline EXACTLY once, with the exact
        # bytes Documenso returned (R9.2, R15.2).
        assert len(store_calls) == 1
        assert store_calls[0]["pdf_bytes"] == scenario["pdf_bytes"]
        assert store_calls[0]["org_id"] == org_id
        assert store_calls[0]["envelope_id"] == envelope.id

        # No OTHER ORM row was written — no ComplianceDocument, for ANY origin
        # including staff (R9.3 — staff signed docs live only on the encrypted
        # file_key, surfaced via the merged staff listing).
        assert session.added == []

        # The envelope itself carries the encrypted-pipeline file_key + stored
        # status (the reference the entity/staff listing reads, R9.4).
        assert outcome.status == "stored"
        assert outcome.file_key == expected_key
        assert envelope.signed_doc_status == "stored"
        assert envelope.signed_doc_file_key == expected_key
        assert envelope.last_error is None
        # The envelope is never re-categorised away from its origin.
        assert envelope.originating_entity_type == scenario["entity_type"]

    @given(scenario=_failure_scenario())
    @PBT_SETTINGS
    def test_retrieval_failure_writes_nothing_and_marks_pending(self, scenario):
        """When download fails: no storage call, nothing written anywhere, the
        envelope stays ``completed`` and is flagged ``pending_retrieval`` (R9.5,
        R9.7)."""
        org_id = uuid.uuid4()
        envelope = _make_envelope(
            org_id=org_id,
            entity_type=scenario["entity_type"],
            agreement_type=scenario["agreement_type"],
            signed_doc_status=scenario["signed_doc_status"],
        )
        session = _CapturingSession(envelope)

        store_calls: list = []

        async def _spy_store(_db, **_kwargs):
            store_calls.append(_kwargs)
            return "should-never-be-used"

        spy = _SpyClient(b"", raise_exc=DocumensoError("download boom"))
        with _patched_seams(session, _spy_store):
            outcome = asyncio.run(
                retrieve_and_store_signed_document(
                    envelope_id=envelope.id, org_id=org_id, client=spy
                )
            )

        # Download was attempted, then failed — the encrypted pipeline was never
        # invoked, and NOTHING was written to any alternative/temporary location
        # (no storage seam call, no ORM add).
        assert spy.download_calls == [envelope.documenso_document_id]
        assert store_calls == []
        assert session.added == []

        # Envelope retained as completed, flagged pending with a humanized error.
        assert outcome.status == "pending_retrieval"
        assert envelope.status == "completed"
        assert envelope.signed_doc_status == "pending_retrieval"
        assert envelope.signed_doc_file_key is None
        assert isinstance(envelope.last_error, str) and envelope.last_error
        # No raw exception text leaks into the stored error.
        assert "DocumensoError" not in envelope.last_error
