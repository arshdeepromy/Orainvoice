"""Unit tests for the scheduled signed-document retry sweep (task 13.3).

``sweep_pending_signed_documents`` is the R9.5/R9.7 backstop: it enumerates
``completed`` envelopes whose ``signed_doc_status`` is not yet ``stored`` across
**all** orgs (system context) and re-drives the idempotent
``retrieve_and_store_signed_document`` for each, isolating per-envelope failures
and bounding the batch.

These tests drive the sweep with lightweight fakes (a fake async-session factory
that serves a scripted candidate set, plus a stubbed retrieval entrypoint) — no
FastAPI/DB stack needed. They assert:

1. Each enumerated candidate is retried and outcomes are tallied
   (stored / pending / noop), with per-envelope exceptions isolated and counted
   as errors rather than aborting the batch.
2. An empty candidate set short-circuits without calling the retrieval seam.
3. The configured ``batch_size`` bounds the candidate scan (passed to LIMIT).

Requirements: 9.5, 9.7
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

# Pre-load the model graph so SQLAlchemy can resolve string-based relationships
# (mirrors the other esign unit/example tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.modules.esignatures import signed_document as sd  # noqa: E402
from app.modules.esignatures.signed_document import (  # noqa: E402
    RetrievalOutcome,
    sweep_pending_signed_documents,
)


# ---------------------------------------------------------------------------
# Fakes — a stateful async session whose SELECT returns scripted candidate rows
# and records the LIMIT it was asked for.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows, limit_box):
        self._rows = rows
        self._limit_box = limit_box

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def begin(self):
        session = self

        class _Tx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_exc):
                return False

        return _Tx()

    async def execute(self, stmt, _params=None):
        # Capture the compiled LIMIT so the batch-size bound can be asserted.
        try:
            self._limit_box.append(stmt._limit)
        except Exception:
            pass
        return _FakeResult(self._rows)


def _factory_for(rows, limit_box):
    def _factory():
        return _FakeSession(rows, limit_box)

    return _factory


@pytest.fixture(autouse=True)
def _noop_set_rls(monkeypatch):
    async def _noop(_session, _org_id):
        return None

    monkeypatch.setattr(sd, "_set_rls_org_id", _noop)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sweep_retries_each_candidate_and_tallies_outcomes(monkeypatch):
    """Every candidate is retried; stored/pending/noop tallied; failures isolated."""
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    env_stored = uuid.uuid4()
    env_pending = uuid.uuid4()
    env_noop = uuid.uuid4()
    env_error = uuid.uuid4()

    rows = [
        (env_stored, org_a),
        (env_pending, org_a),
        (env_noop, org_b),
        (env_error, org_b),
    ]
    limit_box: list = []
    monkeypatch.setattr(sd, "async_session_factory", _factory_for(rows, limit_box))

    seen: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def _fake_retrieve(*, envelope_id, org_id, **_kwargs):
        seen.append((envelope_id, org_id))
        if envelope_id == env_stored:
            return RetrievalOutcome(status="stored", file_key="esign_signed/x.pdf")
        if envelope_id == env_pending:
            return RetrievalOutcome(status="pending_retrieval", error="nope")
        if envelope_id == env_noop:
            return RetrievalOutcome(status="noop", reason="already_stored")
        raise RuntimeError("boom")  # env_error — must be isolated + counted

    monkeypatch.setattr(sd, "retrieve_and_store_signed_document", _fake_retrieve)

    summary = asyncio.run(sweep_pending_signed_documents())

    # Every candidate was attempted, with the right (envelope, org) pairs.
    assert seen == [
        (env_stored, org_a),
        (env_pending, org_a),
        (env_noop, org_b),
        (env_error, org_b),
    ]
    assert summary == {
        "candidates": 4,
        "stored": 1,
        "pending": 1,
        "noop": 1,
        "errors": 1,
    }


def test_sweep_noop_on_empty_candidate_set(monkeypatch):
    """No candidates → no retrieval calls, zeroed summary."""
    limit_box: list = []
    monkeypatch.setattr(sd, "async_session_factory", _factory_for([], limit_box))

    calls = 0

    async def _fake_retrieve(**_kwargs):
        nonlocal calls
        calls += 1
        return RetrievalOutcome(status="noop")

    monkeypatch.setattr(sd, "retrieve_and_store_signed_document", _fake_retrieve)

    summary = asyncio.run(sweep_pending_signed_documents())

    assert calls == 0
    assert summary == {
        "candidates": 0,
        "stored": 0,
        "pending": 0,
        "noop": 0,
        "errors": 0,
    }


def test_sweep_bounds_batch_size(monkeypatch):
    """The configured batch_size is applied as the candidate-scan LIMIT."""
    limit_box: list = []
    monkeypatch.setattr(sd, "async_session_factory", _factory_for([], limit_box))

    async def _fake_retrieve(**_kwargs):
        return RetrievalOutcome(status="noop")

    monkeypatch.setattr(sd, "retrieve_and_store_signed_document", _fake_retrieve)

    asyncio.run(sweep_pending_signed_documents(batch_size=37))

    assert limit_box == [37]
