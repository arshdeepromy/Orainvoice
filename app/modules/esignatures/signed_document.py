"""Signed-document retrieval, encrypted-pipeline storage, and envelope attach.

When an :class:`~app.modules.esignatures.models.EsignEnvelope` reaches
``completed`` (Documenso emitted ``DOCUMENT_COMPLETED``), the completed,
fully-signed PDF must be pulled back from Documenso and stored **securely** in
OraInvoice. This module owns that retrieval → store → attach step (task 13.1).

Storage is **uniform for every originating-entity type, including staff**: the
signed PDF is written ONLY through the same encrypted uploads pipeline every
other encrypted upload uses (``zlib`` + :func:`~app.core.encryption.envelope_encrypt`
+ :class:`~app.core.storage_manager.StorageManager`, under
``esign_signed/<org_id>/<uuid>.pdf``), and the resulting opaque ``file_key`` is
persisted on the envelope (``signed_doc_status='stored'`` + ``signed_doc_file_key``).
It is **never** written to the plaintext compliance document store (R9.2,
R15.2). For a **staff** originating entity we deliberately do NOT create a
``ComplianceDocument`` row — those store files unencrypted on disk; the signed
staff PDF lives only on the envelope's encrypted ``file_key`` and is surfaced
via the staff documents listing merge (task 13.2) and downloaded through the
org-checked ``GET /api/v2/esign/envelopes/{id}/signed-document`` endpoint
(task 10.1). For an invoice/quote origin, the envelope (which already records
the originating entity) plus its ``file_key`` is the attachment reference
(R9.4) — still the encrypted pipeline, no plaintext copy.

The on-disk byte format written here is **exactly** the format the download
endpoint reads back (``app/modules/esignatures/router.py``
``_read_stored_signed_document``): a one-byte compression flag followed by the
envelope-encrypted payload, with PDFs ``zlib``-compressed (``COMP_ZLIB``). This
module reuses :func:`app.modules.uploads.router._store` so the write and read
formats can never drift.

Fresh session after commit (ISSUE-005/048 pattern)
--------------------------------------------------
Retrieval is triggered **after** the webhook handler's transaction has already
committed and closed (and, for the sweep, well after any request). So every DB
write here runs on a **fresh** :data:`~app.core.database.async_session_factory`
session with the envelope's ``org_id`` set on the new RLS context via
:func:`~app.core.database._set_rls_org_id` — never the already-committed webhook
session.

Resilience
----------
On any retrieval or storage failure the envelope is **kept** in ``completed``
status, ``signed_doc_status`` is set to ``pending_retrieval`` with a humanized
``last_error``, and **nothing** is written to any alternative or temporary
location (R9.7). The scheduled sweep (task 13.3) then retries.

Entry point
-----------
:func:`retrieve_and_store_signed_document` is the single seam both the webhook
apply (task 12.2, on the ``completed`` transition) and the scheduled retry
sweep (task 13.3) call. It is injectable (``client`` / ``http`` /
``client_factory``) so tests can drive it with a spy/stub Documenso client.

Refs: requirements 9.1, 9.2, 9.3, 9.4, 9.6, 9.7, 13.6, 15.2; design
§"Send → sign → store sequence", §"Signed-document retrieval + sweep".
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import _set_rls_org_id, async_session_factory
from app.integrations.documenso import (
    DocumensoClient,
    DocumensoConnection,
    DocumensoError,
    DocumensoNotConfiguredError,
    get_documenso_connection,
)
from app.modules.esignatures.errors import humanize_esign_error
from app.modules.esignatures.models import EsignEnvelope
from app.modules.esignatures.status import EnvelopeStatus

logger = logging.getLogger(__name__)

# A client factory takes a per-org connection and returns a ready DocumensoClient
# (mirrors the seam used by ``service.create_and_send_envelope``).
ClientFactory = Callable[[DocumensoConnection], DocumensoClient]

# The completed status that triggers retrieval (R9.1). Only an envelope in this
# status has a signed document to pull back.
_COMPLETED_STATUS: EnvelopeStatus = "completed"

# Signed-document storage status values (mirror the migration CHECK + models).
_SIGNED_STATUS_NONE = "none"
_SIGNED_STATUS_PENDING = "pending_retrieval"
_SIGNED_STATUS_STORED = "stored"

# The encrypted uploads pipeline category for signed agreements. Files land at
# ``esign_signed/<org_id>/<uuid>.pdf`` under the upload base, exactly like every
# other encrypted upload (R9.2, R15.2).
_STORAGE_CATEGORY = "esign_signed"

# Audit action recorded when the signed document is stored (R9.6). The audit
# entry carries only non-secret metadata — never the document contents (R14.4).
_AUDIT_ACTION_STORED = "esign.envelope.signed_document_stored"
_AUDIT_ENTITY_TYPE = "esign_envelope"

# The two non-terminal signed-doc states the sweep retries (everything that is
# not yet ``stored``). Mirrors the migration CHECK + models.
_SWEEP_RETRY_STATUSES = (_SIGNED_STATUS_NONE, _SIGNED_STATUS_PENDING)

# Upper bound on how many candidate envelopes a single sweep pass picks up, so a
# large backlog can never turn one tick into an unbounded run. Oldest-updated
# candidates are taken first, so a backlog drains deterministically across ticks.
_SWEEP_BATCH_SIZE = 200


def _pdf_is_signed(pdf_bytes: bytes) -> bool:
    """Return True if ``pdf_bytes`` carries a PDF digital signature.

    Documenso applies its platform signing certificate ("Signed by Documenso")
    on completion, which embeds a signature dictionary with a ``/ByteRange`` and
    ``/Sig`` entry. The *unsigned* original upload has neither. We use this to
    avoid persisting a pre-seal snapshot: a ``DOCUMENT_COMPLETED`` event can race
    ahead of Documenso finishing the sealed PDF, and the download endpoint then
    returns the still-unsigned original. When that happens we defer (mark
    pending) so the scheduled sweep re-fetches once the sealed version exists,
    rather than storing the original as the final signed document.
    """
    if not pdf_bytes:
        return False
    return b"/ByteRange" in pdf_bytes or b"adbe.pkcs7" in pdf_bytes


# ---------------------------------------------------------------------------
# Outcome value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalOutcome:
    """The result of a :func:`retrieve_and_store_signed_document` attempt.

    ``status`` is one of:

    * ``"stored"``    — the signed PDF was retrieved and stored; ``file_key`` set.
    * ``"noop"``      — nothing to do (envelope missing, not yet ``completed``,
                        already stored, or no Documenso document id); ``reason``
                        explains which.
    * ``"pending_retrieval"`` — retrieval or storage failed; the envelope was
                        left ``completed`` with ``signed_doc_status='pending_retrieval'``
                        and a humanized ``last_error`` (``error`` mirrors it) so
                        the sweep retries.
    """

    status: str
    file_key: str | None = None
    reason: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Best-effort audit (write_audit_log does NOT swallow its own exceptions)
# ---------------------------------------------------------------------------


async def _run_best_effort(db: AsyncSession, what: str, coro: Awaitable[object]) -> None:
    """Await a best-effort DB side-effect inside a SAVEPOINT.

    ``write_audit_log`` (``app/core/audit.py``) does NOT swallow exceptions, so
    the audit write is wrapped in a nested transaction: on any failure the
    SAVEPOINT is rolled back and the failure logged, while the surrounding
    (envelope-update) transaction is preserved. Mirrors
    ``service._run_best_effort`` (R14.3 spirit applied to the storage audit).
    """
    try:
        savepoint = await db.begin_nested()
    except Exception:  # pragma: no cover - session already unusable
        logger.warning("esign: could not open SAVEPOINT for %s; skipped", what)
        return
    try:
        await coro
        await savepoint.commit()
    except Exception:
        logger.warning(
            "esign: %s failed (best-effort; envelope not rolled back)",
            what,
            exc_info=True,
        )
        try:
            await savepoint.rollback()
        except Exception:  # pragma: no cover - defensive
            logger.warning("esign: SAVEPOINT rollback for %s failed", what)


# ---------------------------------------------------------------------------
# Encrypted-pipeline storage (reuses the uploads pipeline verbatim)
# ---------------------------------------------------------------------------


async def _store_via_encrypted_pipeline(
    db: AsyncSession, *, org_id: UUID, envelope_id: UUID, pdf_bytes: bytes
) -> str:
    """Store ``pdf_bytes`` through the encrypted uploads pipeline; return file_key.

    Delegates to :func:`app.modules.uploads.router._store` so the on-disk byte
    format (``flag + envelope_encrypt(zlib(pdf))``) is byte-for-byte identical to
    every other encrypted upload — and, critically, to what the signed-document
    download endpoint reads back. The category ``esign_signed`` yields a file_key
    of the form ``esign_signed/<org_id>/<uuid>.pdf`` (R9.2, R15.2). Never writes
    to the plaintext compliance store.
    """
    # Imported lazily to avoid importing the uploads router (and its FastAPI
    # surface) at module import time / to sidestep any import-order coupling.
    from app.modules.uploads.router import _store

    filename = f"signed-agreement-{envelope_id}.pdf"
    result = await _store(pdf_bytes, filename, str(org_id), _STORAGE_CATEGORY, db)
    return result["file_key"]


# ---------------------------------------------------------------------------
# Client resolution (injectable for tests)
# ---------------------------------------------------------------------------


async def _resolve_client(
    db: AsyncSession,
    *,
    org_id: UUID,
    client: DocumensoClient | None,
    client_factory: ClientFactory | None,
    http: httpx.AsyncClient | None,
) -> tuple[DocumensoClient, httpx.AsyncClient | None]:
    """Resolve the per-org :class:`DocumensoClient` to use for retrieval.

    Mirrors ``service.create_and_send_envelope`` client resolution:

    * an explicit ``client`` is used as-is (test spy/stub) and needs no
      connection load;
    * otherwise the org's connection is loaded (R13.7 — the org's own
      team-scoped token) and a client is built via ``client_factory`` or
      ``DocumensoClient.for_org`` over the injected ``http``;
    * with neither, a managed ``httpx.AsyncClient`` is created here and returned
      so the caller can close it.

    Returns ``(client, created_http)`` where ``created_http`` is the client this
    function opened (and the caller must close), else ``None``.
    """
    if client is not None:
        return client, None

    conn = await get_documenso_connection(db, org_id)
    if client_factory is not None:
        return client_factory(conn), None
    if http is not None:
        return DocumensoClient.for_org(conn, http), None

    created_http = httpx.AsyncClient(
        timeout=httpx.Timeout(DocumensoClient.DEFAULT_TIMEOUT)
    )
    return DocumensoClient.for_org(conn, created_http), created_http


# ---------------------------------------------------------------------------
# Entry point — retrieve + store + attach
# ---------------------------------------------------------------------------


async def retrieve_and_store_signed_document(
    *,
    envelope_id: UUID,
    org_id: UUID,
    http: httpx.AsyncClient | None = None,
    client: DocumensoClient | None = None,
    client_factory: ClientFactory | None = None,
) -> RetrievalOutcome:
    """Retrieve the completed signed PDF from Documenso and store it securely.

    The single entry point invoked by the webhook apply (task 12.2) on the
    ``completed`` transition and by the scheduled retry sweep (task 13.3).

    All DB work runs on a **fresh** session from
    :data:`~app.core.database.async_session_factory` with the envelope's
    ``org_id`` set on the RLS context — never an already-committed caller
    session (ISSUE-005/048). The flow:

    1. Load the envelope (org-scoped). Missing / not-yet-``completed`` /
       already-``stored`` / no Documenso document id → ``noop`` (idempotent;
       safe to call repeatedly from both the webhook and the sweep).
    2. ``download_signed`` over HTTPS using this org's own team-scoped client
       (R9.1, R13.7, R15.4).
    3. Store the bytes ONLY via the encrypted uploads pipeline (R9.2, R15.2),
       uniformly for **all** originating-entity types including staff — no
       ``ComplianceDocument`` is created for staff origin.
    4. Persist ``signed_doc_status='stored'`` + ``signed_doc_file_key`` on the
       envelope and write a (contents-free) audit entry (R9.6, R14.4).

    On any failure in steps 2–4 the envelope is kept ``completed``,
    ``signed_doc_status`` becomes ``pending_retrieval`` with a humanized
    ``last_error``, nothing is written elsewhere/temporarily, and the sweep
    retries (R9.7).

    Args:
        envelope_id: The envelope whose signed document to retrieve.
        org_id: The envelope's organisation (sets the fresh RLS context, R13.6).
        http: Optional injected ``httpx.AsyncClient`` (built into a per-org
            client). Closed by the caller.
        client: Optional pre-built :class:`DocumensoClient` (test spy/stub);
            bypasses the connection load.
        client_factory: Optional ``conn -> DocumensoClient`` (test seam that
            still exercises the real per-org connection load).

    Returns:
        A :class:`RetrievalOutcome` describing what happened.
    """
    created_http: httpx.AsyncClient | None = None
    try:
        async with async_session_factory() as session:
            # --- Fresh RLS context for the envelope's org (R13.6) ----------
            async with session.begin():
                await _set_rls_org_id(session, str(org_id))

                envelope = await _load_envelope(session, org_id=org_id, envelope_id=envelope_id)
                if envelope is None:
                    logger.info(
                        "esign: signed-doc retrieval skipped — envelope %s not found for org %s",
                        envelope_id,
                        org_id,
                    )
                    return RetrievalOutcome(status="noop", reason="envelope_not_found")

                # Idempotency / precondition guards. Both the webhook and the
                # sweep can call this; only a completed-and-not-yet-stored
                # envelope with a Documenso document id has work to do.
                if envelope.signed_doc_status == _SIGNED_STATUS_STORED:
                    return RetrievalOutcome(status="noop", reason="already_stored")
                if envelope.status != _COMPLETED_STATUS:
                    return RetrievalOutcome(status="noop", reason="not_completed")
                if not envelope.documenso_document_id:
                    # Cannot retrieve without a document id — mark for retry so a
                    # later attempt (once the id is known) picks it up.
                    return await _mark_pending(
                        session,
                        envelope=envelope,
                        org_id=org_id,
                        message="The signing service document reference is missing.",
                    )

                document_id = envelope.documenso_document_id

                # --- Step 2: download + Step 3: store, atomically guarded ---
                try:
                    active_client, created_http = await _resolve_client(
                        session,
                        org_id=org_id,
                        client=client,
                        client_factory=client_factory,
                        http=http,
                    )
                    signed_bytes = await active_client.download_signed(document_id)
                    if not signed_bytes:
                        raise DocumensoError(
                            "The signing service returned an empty signed document."
                        )

                    # Guard against a completion/seal race: if the bytes are not
                    # yet digitally signed, Documenso hasn't finished sealing the
                    # document and is still serving the unsigned original. Defer
                    # (mark pending) so the sweep re-fetches the sealed version,
                    # rather than storing the original as the final signed PDF.
                    if not _pdf_is_signed(signed_bytes):
                        logger.warning(
                            "esign: downloaded document for envelope %s (org %s) "
                            "has no signature yet (%d bytes); deferring retrieval",
                            envelope.id,
                            org_id,
                            len(signed_bytes),
                        )
                        if created_http is not None:
                            await created_http.aclose()
                            created_http = None
                        return await _mark_pending(
                            session,
                            envelope=envelope,
                            org_id=org_id,
                            message="The signed document is still being finalised by the signing service.",
                        )

                    file_key = await _store_via_encrypted_pipeline(
                        session,
                        org_id=org_id,
                        envelope_id=envelope.id,
                        pdf_bytes=signed_bytes,
                    )
                except (DocumensoNotConfiguredError, DocumensoError) as exc:
                    # Retrieval failure — humanize, keep completed, mark pending.
                    message = humanize_esign_error(exc).message
                    logger.warning(
                        "esign: signed-doc retrieval failed for envelope %s (org %s): %s",
                        envelope.id,
                        org_id,
                        type(exc).__name__,
                    )
                    return await _mark_pending(
                        session, envelope=envelope, org_id=org_id, message=message
                    )
                except Exception as exc:  # noqa: BLE001 - storage/quota/etc.
                    # Storage failure (quota, disk, encryption) — never write to
                    # an alternative/temporary location; mark pending for retry.
                    message = humanize_esign_error(exc).message
                    logger.warning(
                        "esign: signed-doc storage failed for envelope %s (org %s): %s",
                        envelope.id,
                        org_id,
                        type(exc).__name__,
                    )
                    return await _mark_pending(
                        session, envelope=envelope, org_id=org_id, message=message
                    )

                # --- Step 4: attach on the envelope + contents-free audit ---
                envelope.signed_doc_file_key = file_key
                envelope.signed_doc_status = _SIGNED_STATUS_STORED
                envelope.last_error = None
                await session.flush()

                await _run_best_effort(
                    session,
                    "audit_log",
                    write_audit_log(
                        session,
                        org_id=org_id,
                        user_id=None,
                        action=_AUDIT_ACTION_STORED,
                        entity_type=_AUDIT_ENTITY_TYPE,
                        entity_id=envelope.id,
                        after_value={
                            "signed_doc_status": _SIGNED_STATUS_STORED,
                            "originating_entity_type": envelope.originating_entity_type,
                            "originating_entity_id": str(envelope.originating_entity_id),
                        },
                    ),
                )

                logger.info(
                    "esign: stored signed document for envelope %s (org %s)",
                    envelope.id,
                    org_id,
                )
                return RetrievalOutcome(status="stored", file_key=file_key)
    finally:
        if created_http is not None:
            await created_http.aclose()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _load_envelope(
    session: AsyncSession, *, org_id: UUID, envelope_id: UUID
) -> EsignEnvelope | None:
    """Load the envelope, org-scoped (RLS + explicit ``org_id`` predicate)."""
    result = await session.execute(
        select(EsignEnvelope).where(
            EsignEnvelope.id == envelope_id,
            EsignEnvelope.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def _mark_pending(
    session: AsyncSession,
    *,
    envelope: EsignEnvelope,
    org_id: UUID,
    message: str,
) -> RetrievalOutcome:
    """Keep the envelope ``completed`` but flag retrieval as pending (R9.7).

    Sets ``signed_doc_status='pending_retrieval'`` and a humanized
    ``last_error`` so the scheduled sweep retries. Nothing is written to any
    alternative/temporary location. The status itself is left untouched
    (``completed``).
    """
    envelope.signed_doc_status = _SIGNED_STATUS_PENDING
    envelope.last_error = message
    await session.flush()
    return RetrievalOutcome(
        status=_SIGNED_STATUS_PENDING, reason="retrieval_failed", error=message
    )


# ---------------------------------------------------------------------------
# Scheduled retry sweep (task 13.3, R9.5/R9.7)
# ---------------------------------------------------------------------------


async def sweep_pending_signed_documents(
    *, batch_size: int = _SWEEP_BATCH_SIZE
) -> dict:
    """Retry signed-document retrieval for every ``completed`` envelope whose
    document is not yet ``stored``, across **all** organisations.

    This is the "subsequent scheduled attempt" backstop for R9.5/R9.7: the
    webhook ``DOCUMENT_COMPLETED`` path is the primary trigger for retrieval, but
    if that retrieval (or the storage write) fails the envelope is left
    ``completed`` with ``signed_doc_status='pending_retrieval'`` (or never left
    ``none`` if the webhook never fired the retrieval). This sweep finds those
    laggards and re-drives :func:`retrieve_and_store_signed_document`, which is
    idempotent and no-op-safe — calling it on an already-``stored`` envelope (or
    one not yet ``completed``) does nothing, so a race with a concurrent webhook
    retrieval is harmless.

    **Cross-org enumeration.** ``esign_envelopes`` is RLS-scoped per org, so the
    candidate scan runs in a **system context** (``RESET app.current_org_id`` via
    ``_set_rls_org_id(session, None)``) on a dedicated session — exactly the
    cross-org enumeration pattern the other scheduled sweeps use. Only the
    minimal ``(id, org_id)`` pairs are read here; the actual retrieval +
    storage + RLS re-scoping happens inside
    :func:`retrieve_and_store_signed_document`, which opens its **own** fresh
    session and sets the RLS context to the candidate's ``org_id``.

    **Robustness.** The candidate set is bounded by ``batch_size`` (oldest
    ``updated_at`` first, so a backlog drains deterministically) and each
    envelope is retried inside its own ``try/except`` so one failing org/envelope
    never aborts the batch. Counts are logged.

    Registered as a WRITE ``_DAILY_TASKS`` entry in ``app/tasks/scheduled.py`` so
    it runs only on the primary node (skipped on read-only standby nodes).

    Returns:
        A summary dict: ``{candidates, stored, pending, noop, errors}``.
    """
    summary = {"candidates": 0, "stored": 0, "pending": 0, "noop": 0, "errors": 0}

    # --- Enumerate candidates across all orgs (system context) -------------
    try:
        async with async_session_factory() as session:
            async with session.begin():
                # System context: RESET app.current_org_id so the scan is not
                # bound to any single tenant. (The owning DB role bypasses the
                # ENABLE-not-FORCE RLS policy; the explicit RESET documents the
                # cross-org intent and clears any inherited context.)
                await _set_rls_org_id(session, None)
                result = await session.execute(
                    select(EsignEnvelope.id, EsignEnvelope.org_id)
                    .where(
                        EsignEnvelope.status == _COMPLETED_STATUS,
                        EsignEnvelope.signed_doc_status.in_(_SWEEP_RETRY_STATUSES),
                    )
                    .order_by(EsignEnvelope.updated_at.asc())
                    .limit(batch_size)
                )
                candidates = [(row[0], row[1]) for row in result.all()]
    except Exception as exc:  # noqa: BLE001 - enumeration must not crash the loop
        logger.exception("esign sweep: failed to enumerate candidates: %s", exc)
        return {"error": str(exc)}

    summary["candidates"] = len(candidates)
    if not candidates:
        return summary

    # --- Retry each candidate in isolation ---------------------------------
    for envelope_id, org_id in candidates:
        try:
            outcome = await retrieve_and_store_signed_document(
                envelope_id=envelope_id, org_id=org_id
            )
            if outcome.status == "stored":
                summary["stored"] += 1
            elif outcome.status == _SIGNED_STATUS_PENDING:
                summary["pending"] += 1
            else:  # "noop"
                summary["noop"] += 1
        except Exception as exc:  # noqa: BLE001 - isolate per-envelope failures
            summary["errors"] += 1
            logger.warning(
                "esign sweep: retry failed for envelope %s (org %s): %s",
                envelope_id,
                org_id,
                exc,
            )

    if summary["stored"] or summary["pending"] or summary["errors"]:
        logger.info(
            "esign sweep: candidates=%d stored=%d pending=%d noop=%d errors=%d",
            summary["candidates"],
            summary["stored"],
            summary["pending"],
            summary["noop"],
            summary["errors"],
        )
    return summary
