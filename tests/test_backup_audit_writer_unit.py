"""Unit tests for the backup/restore audit writer (Task 13.3, Req 1.5/1.6, 17).

Covers ``app.modules.backup_restore.audit.AuditWriter``:
  - durable write-ahead entry records actor/action/target/UTC start, committed
    in an independent session (Req 17.6);
  - write-ahead failure raises ``AuditWriteAheadError`` so the caller aborts
    before any change (Req 17.7);
  - completion entry records outcome and NEVER raises; a failed completion is
    queued for reconciliation rather than undone (Req 17.8);
  - rejected-attempt audit records the user id, or an unauthenticated indicator
    when no token is present, and never raises (Req 1.6);
  - secrets are scrubbed from every audit field including nested before/after
    values (Req 17.5);
  - the pipeline ``audit_hook`` adapter dispatches the two phases correctly.

Per the project test rule the DB session is a lightweight in-memory stand-in
(no mock framework) and the clock is injected for deterministic timestamps.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.modules.backup_restore import audit as audit_mod
from app.modules.backup_restore.audit import (
    ACTION_BACKUP_CREATED,
    ACTION_RESTORE_COMPLETED,
    ACTION_RESTORE_TRIGGERED,
    AuditWriteAheadError,
    AuditWriter,
    COMPLETION_RETRY_QUEUE,
    PHASE_COMPLETION,
    PHASE_WRITE_AHEAD,
    REDACTED,
    UNAUTHENTICATED_INDICATOR,
    scrub_secrets,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self._now


class _Begin:
    def __init__(self, session: "FakeSession") -> None:
        self._session = session

    async def __aenter__(self) -> "FakeSession":
        return self._session

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeSession:
    """In-memory async session capturing the INSERTed audit-log params."""

    def __init__(self, fail_on_insert: bool = False) -> None:
        self.fail_on_insert = fail_on_insert
        self.inserts: list[dict] = []
        self.committed = False

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def begin(self) -> _Begin:
        return _Begin(self)

    async def execute(self, statement, params=None):
        # The RLS reset call passes no params; the audit INSERT passes a dict.
        if params is None:
            return None
        if "action" in params:
            if self.fail_on_insert:
                raise RuntimeError("simulated audit-log write failure")
            self.inserts.append(params)
        return None


class SessionFactory:
    """Yields a fresh FakeSession per call; records each created session."""

    def __init__(self, fail_on_insert: bool = False) -> None:
        self.fail_on_insert = fail_on_insert
        self.sessions: list[FakeSession] = []

    def __call__(self) -> FakeSession:
        session = FakeSession(fail_on_insert=self.fail_on_insert)
        self.sessions.append(session)
        return session

    @property
    def all_inserts(self) -> list[dict]:
        rows: list[dict] = []
        for s in self.sessions:
            rows.extend(s.inserts)
        return rows


@pytest.fixture(autouse=True)
def _clear_retry_queue():
    COMPLETION_RETRY_QUEUE.pending.clear()
    yield
    COMPLETION_RETRY_QUEUE.pending.clear()


# ---------------------------------------------------------------------------
# scrub_secrets (Req 17.5, 2.8)
# ---------------------------------------------------------------------------


def test_scrub_secrets_redacts_known_secret_keys():
    raw = {
        "display_name": "Prod NAS",
        "access_token": "ya29.secret",
        "refresh_token": "1//refresh",
        "client_secret": "shhh",
        "passphrase": "correct horse",
        "api_key": "AKIA...",
        "region": "ap-southeast-2",
    }
    out = scrub_secrets(raw)
    assert out["display_name"] == "Prod NAS"
    assert out["region"] == "ap-southeast-2"
    for secret_key in ("access_token", "refresh_token", "client_secret", "passphrase", "api_key"):
        assert out[secret_key] == REDACTED


def test_scrub_secrets_is_recursive_over_nested_structures():
    raw = {
        "destination": {"provider": "s3", "secret_key": "deep-secret"},
        "items": [{"access_token": "t1"}, {"safe": "ok"}],
    }
    out = scrub_secrets(raw)
    assert out["destination"]["provider"] == "s3"
    assert out["destination"]["secret_key"] == REDACTED
    assert out["items"][0]["access_token"] == REDACTED
    assert out["items"][1]["safe"] == "ok"


def test_scrub_secrets_redacts_a_secret_named_container_wholesale():
    # A key that is itself secret-named (e.g. "tokens") is redacted wholesale
    # rather than recursed into, so nothing under it can leak.
    out = scrub_secrets({"tokens": [{"access_token": "t1"}], "region": "ap"})
    assert out["tokens"] == REDACTED
    assert out["region"] == "ap"


# ---------------------------------------------------------------------------
# write_ahead (Req 17.6, 17.7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_ahead_records_actor_action_target_and_commits_independently():
    factory = SessionFactory()
    writer = AuditWriter(session_factory=factory, clock=FakeClock())
    actor = uuid.uuid4()
    target = uuid.uuid4()

    entry_id = await writer.write_ahead(
        action=ACTION_BACKUP_CREATED, actor_id=actor, target_id=target
    )

    assert isinstance(entry_id, uuid.UUID)
    assert len(factory.all_inserts) == 1
    row = factory.all_inserts[0]
    assert row["action"] == ACTION_BACKUP_CREATED
    assert row["entity_type"] == "backup"  # derived from the action prefix
    assert row["user_id"] == str(actor)
    assert row["entity_id"] == str(target)
    # UTC start timestamp captured in the after_value payload.
    assert '"phase": "write_ahead"' in row["after_value"]
    assert "started_at" in row["after_value"]
    # created_at is a tz-aware UTC datetime.
    assert row["created_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_write_ahead_raises_on_durable_write_failure():
    factory = SessionFactory(fail_on_insert=True)
    writer = AuditWriter(session_factory=factory, clock=FakeClock())

    with pytest.raises(AuditWriteAheadError) as excinfo:
        await writer.write_ahead(
            action=ACTION_RESTORE_TRIGGERED, actor_id=uuid.uuid4(), target_id=uuid.uuid4()
        )
    assert excinfo.value.action == ACTION_RESTORE_TRIGGERED
    assert factory.all_inserts == []


@pytest.mark.asyncio
async def test_write_ahead_scrubs_secrets_before_persisting():
    factory = SessionFactory()
    writer = AuditWriter(session_factory=factory, clock=FakeClock())

    await writer.write_ahead(
        action="cloud_provider.connected",
        actor_id=uuid.uuid4(),
        target_id=uuid.uuid4(),
        after_value={"provider": "google_drive", "refresh_token": "1//leak"},
    )
    row = factory.all_inserts[0]
    assert "1//leak" not in row["after_value"]
    assert REDACTED in row["after_value"]
    assert row["entity_type"] == "cloud_provider"


# ---------------------------------------------------------------------------
# write_completion (Req 17.8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_completion_records_outcome():
    factory = SessionFactory()
    writer = AuditWriter(session_factory=factory, clock=FakeClock())
    target = uuid.uuid4()

    entry_id = await writer.write_completion(
        action=ACTION_RESTORE_COMPLETED,
        actor_id=uuid.uuid4(),
        target_id=target,
        outcome="succeeded",
    )
    assert isinstance(entry_id, uuid.UUID)
    row = factory.all_inserts[0]
    assert row["action"] == ACTION_RESTORE_COMPLETED
    assert row["entity_type"] == "restore"
    assert '"outcome": "succeeded"' in row["after_value"]
    assert COMPLETION_RETRY_QUEUE.pending == []


@pytest.mark.asyncio
async def test_write_completion_never_raises_and_queues_on_failure():
    factory = SessionFactory(fail_on_insert=True)
    writer = AuditWriter(session_factory=factory, clock=FakeClock())
    target = uuid.uuid4()

    # Must NOT raise — a completion-audit failure never undoes the operation.
    result = await writer.write_completion(
        action=ACTION_BACKUP_CREATED,
        actor_id=uuid.uuid4(),
        target_id=target,
        outcome="succeeded",
    )
    assert result is None
    # Flagged for reconciliation via the retry queue (Req 17.8).
    assert len(COMPLETION_RETRY_QUEUE.pending) == 1
    queued = COMPLETION_RETRY_QUEUE.pending[0]
    assert queued.action == ACTION_BACKUP_CREATED
    assert queued.entity_id == target
    assert queued.attempts == 1


@pytest.mark.asyncio
async def test_retry_pending_persists_queued_completion_records():
    # First, fail the completion to enqueue a record.
    failing = SessionFactory(fail_on_insert=True)
    writer = AuditWriter(session_factory=failing, clock=FakeClock())
    await writer.write_completion(
        action=ACTION_BACKUP_CREATED, actor_id=uuid.uuid4(), target_id=uuid.uuid4()
    )
    assert len(COMPLETION_RETRY_QUEUE.pending) == 1

    # Now retry with a healthy factory — the record persists and the queue drains.
    healthy = SessionFactory()
    writer_ok = AuditWriter(session_factory=healthy, clock=FakeClock())
    retried = await writer_ok.retry_pending()
    assert retried == 1
    assert COMPLETION_RETRY_QUEUE.pending == []
    assert len(healthy.all_inserts) == 1


# ---------------------------------------------------------------------------
# Rejected-attempt audit (Req 1.6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_attempt_records_requesting_user():
    factory = SessionFactory()
    writer = AuditWriter(session_factory=factory, clock=FakeClock())
    actor = uuid.uuid4()

    await writer.audit_rejected_attempt(action=ACTION_BACKUP_CREATED, actor_id=actor)
    row = factory.all_inserts[0]
    assert row["user_id"] == str(actor)
    assert '"outcome": "rejected"' in row["after_value"]
    assert UNAUTHENTICATED_INDICATOR not in row["after_value"]


@pytest.mark.asyncio
async def test_rejected_attempt_marks_unauthenticated_when_no_token():
    factory = SessionFactory()
    writer = AuditWriter(session_factory=factory, clock=FakeClock())

    await writer.audit_rejected_attempt(action=ACTION_RESTORE_TRIGGERED, actor_id=None)
    row = factory.all_inserts[0]
    assert row["user_id"] is None
    assert UNAUTHENTICATED_INDICATOR in row["after_value"]


@pytest.mark.asyncio
async def test_rejected_attempt_never_raises_on_write_failure():
    factory = SessionFactory(fail_on_insert=True)
    writer = AuditWriter(session_factory=factory, clock=FakeClock())

    # Even if the audit write fails, the rejection path must not raise.
    result = await writer.audit_rejected_attempt(
        action=ACTION_BACKUP_CREATED, actor_id=uuid.uuid4()
    )
    assert result is None


# ---------------------------------------------------------------------------
# Pipeline audit_hook adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_hook_write_ahead_phase_persists_and_propagates_failure():
    ok_factory = SessionFactory()
    writer = AuditWriter(session_factory=ok_factory, clock=FakeClock())
    await writer.audit_hook(
        phase=PHASE_WRITE_AHEAD,
        action=ACTION_BACKUP_CREATED,
        target_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        scope="both",
    )
    assert ok_factory.all_inserts[0]["action"] == ACTION_BACKUP_CREATED
    assert '"scope": "both"' in ok_factory.all_inserts[0]["after_value"]

    fail_factory = SessionFactory(fail_on_insert=True)
    writer_fail = AuditWriter(session_factory=fail_factory, clock=FakeClock())
    with pytest.raises(AuditWriteAheadError):
        await writer_fail.audit_hook(
            phase=PHASE_WRITE_AHEAD,
            action=ACTION_BACKUP_CREATED,
            target_id=uuid.uuid4(),
            actor_id=uuid.uuid4(),
            scope="both",
        )


@pytest.mark.asyncio
async def test_audit_hook_completion_phase_swallows_failure_and_queues():
    fail_factory = SessionFactory(fail_on_insert=True)
    writer = AuditWriter(session_factory=fail_factory, clock=FakeClock())
    # Completion phase must never raise even when the durable write fails.
    await writer.audit_hook(
        phase=PHASE_COMPLETION,
        action=ACTION_BACKUP_CREATED,
        target_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        scope="both",
        outcome="succeeded",
    )
    assert len(COMPLETION_RETRY_QUEUE.pending) == 1
