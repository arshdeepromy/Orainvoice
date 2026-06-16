"""Operator-initiated backup deletion, gated behind a 6-digit verification code.

Deleting a Full_Backup is destructive and irreversible, so — like a sensitive
MFA action — it requires a second factor: the requesting global admin is emailed
a 6-digit code that must be presented to confirm the deletion. The two-step
contract is:

1. **Request** (:func:`create_deletion_challenge`) — validate that the selected
   backups are manually-created and not already pruned, generate a single-use
   6-digit code, store a *hashed* copy in Redis with a 10-minute TTL alongside
   the exact backup-id set the code authorises, and email the code to the
   requesting admin. No backup is touched.

2. **Confirm** (:func:`verify_deletion_challenge`) — re-present the code; on a
   constant-time match (within the attempt budget and before expiry) the
   challenge is consumed and the authorised backup ids are returned for the
   caller to delete via :meth:`BlobPruner.delete_specific`.

The code is never stored in plaintext, is bound to the requesting user and the
specific backup-id set, is single-use, and is rate-limited to a small number of
attempts — so a leaked challenge id alone cannot authorise a deletion.

Only **manually-created** backups (a ``backup_jobs`` row with
``triggered_by='manual'``) may be deleted here; scheduled/retention-managed
backups are left to the retention pruner.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup_restore.models import Backup

logger = logging.getLogger(__name__)

_CODE_LENGTH = 6
_CODE_TTL_SECONDS = 600  # 10 minutes
_MAX_ATTEMPTS = 5
_REDIS_PREFIX = "backup_delete_challenge:"
_DELETE_JOB_PREFIX = "backup_delete_job:"
_DELETE_JOB_TTL_SECONDS = 3600  # keep the result around for an hour
_MANUAL_TRIGGER = "manual"


class DeletionChallengeError(Exception):
    """Base error for the backup-deletion challenge flow."""


class NoDeletableBackupsError(DeletionChallengeError):
    """None of the requested backups are deletable (manual + not yet pruned)."""


class ChallengeNotFoundError(DeletionChallengeError):
    """The challenge id is unknown or has expired."""


class ChallengeUserMismatchError(DeletionChallengeError):
    """The confirming user is not the one who requested the challenge."""


class InvalidCodeError(DeletionChallengeError):
    """The supplied code is wrong; ``attempts_remaining`` may guide the user."""

    def __init__(self, message: str, *, attempts_remaining: int) -> None:
        super().__init__(message)
        self.attempts_remaining = attempts_remaining


@dataclass
class DeletionChallenge:
    """The created challenge handed back to the request endpoint."""

    challenge_id: str
    expires_at: datetime
    recipient_masked: str
    backup_count: int


def _generate_code() -> str:
    """A cryptographically-random 6-digit code (mirrors the MFA OTP format)."""
    return "".join(str(secrets.randbelow(10)) for _ in range(_CODE_LENGTH))


def _hash_code(code: str) -> str:
    """SHA-256 hex of the code so the plaintext is never stored."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _mask_email(email: str) -> str:
    """Mask an email for display, e.g. ``a***@example.com``."""
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return "your registered email"
    if len(local) <= 1:
        masked_local = local + "***"
    else:
        masked_local = local[0] + "***"
    return f"{masked_local}@{domain}"


def _redis():
    from app.core.redis import redis_pool

    return redis_pool


async def deletable_backup_ids(
    db: AsyncSession, backup_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Filter *backup_ids* to those that are manual-origin and not yet pruned.

    A backup is manual-origin when a ``backup_jobs`` row with
    ``triggered_by='manual'`` references it. Already-``pruned`` rows are excluded
    (nothing left to delete).
    """
    if not backup_ids:
        return []
    rows = await db.execute(
        text(
            """
            SELECT b.id
            FROM backups b
            WHERE b.id = ANY(:ids)
              AND b.prune_status <> 'pruned'
              AND EXISTS (
                  SELECT 1 FROM backup_jobs j
                  WHERE j.backup_id = b.id AND j.triggered_by = :trigger
              )
            """
        ),
        {"ids": [str(i) for i in backup_ids], "trigger": _MANUAL_TRIGGER},
    )
    return [r[0] for r in rows.fetchall()]


async def all_manual_backup_ids(db: AsyncSession) -> list[uuid.UUID]:
    """Every manual-origin, not-yet-pruned backup id (for "select all")."""
    rows = await db.execute(
        text(
            """
            SELECT b.id
            FROM backups b
            WHERE b.prune_status <> 'pruned'
              AND EXISTS (
                  SELECT 1 FROM backup_jobs j
                  WHERE j.backup_id = b.id AND j.triggered_by = :trigger
              )
            ORDER BY b.created_at DESC
            """
        ),
        {"trigger": _MANUAL_TRIGGER},
    )
    return [r[0] for r in rows.fetchall()]


async def create_deletion_challenge(
    db: AsyncSession,
    *,
    requested_by: uuid.UUID,
    recipient_email: str,
    backup_ids: list[uuid.UUID],
) -> DeletionChallenge:
    """Validate the selection, store a hashed code in Redis, and email the code.

    Raises:
        NoDeletableBackupsError: if none of *backup_ids* are deletable.
        RuntimeError: if the verification email could not be sent.
    """
    deletable = await deletable_backup_ids(db, backup_ids)
    if not deletable:
        raise NoDeletableBackupsError(
            "None of the selected backups can be deleted (they must be manually "
            "created and not already removed)."
        )

    code = _generate_code()
    challenge_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=_CODE_TTL_SECONDS)
    payload = {
        "code_hash": _hash_code(code),
        "user_id": str(requested_by),
        "backup_ids": [str(i) for i in deletable],
        "attempts": 0,
        "created_at": now.isoformat(),
    }
    await _redis().setex(
        f"{_REDIS_PREFIX}{challenge_id}", _CODE_TTL_SECONDS, json.dumps(payload)
    )

    await _send_deletion_code_email(db, recipient_email, code, len(deletable))

    logger.info(
        "Backup deletion challenge %s created by %s for %d backup(s)",
        challenge_id,
        requested_by,
        len(deletable),
    )
    return DeletionChallenge(
        challenge_id=challenge_id,
        expires_at=expires_at,
        recipient_masked=_mask_email(recipient_email),
        backup_count=len(deletable),
    )


async def verify_deletion_challenge(
    *,
    challenge_id: str,
    code: str,
    user_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Verify a code and consume the challenge, returning the authorised ids.

    Raises:
        ChallengeNotFoundError: unknown/expired challenge.
        ChallengeUserMismatchError: a different user is confirming.
        InvalidCodeError: wrong code (with ``attempts_remaining``); the challenge
            is destroyed once the attempt budget is exhausted.
    """
    redis = _redis()
    key = f"{_REDIS_PREFIX}{challenge_id}"
    raw = await redis.get(key)
    if raw is None:
        raise ChallengeNotFoundError(
            "This verification code has expired or was already used. Start the "
            "deletion again to receive a new code."
        )
    payload = json.loads(raw)

    if payload.get("user_id") != str(user_id):
        raise ChallengeUserMismatchError(
            "This verification code was issued to a different user."
        )

    supplied_hash = _hash_code(code.strip())
    if not secrets.compare_digest(supplied_hash, payload.get("code_hash", "")):
        attempts = int(payload.get("attempts", 0)) + 1
        remaining = max(0, _MAX_ATTEMPTS - attempts)
        if remaining <= 0:
            await redis.delete(key)
        else:
            payload["attempts"] = attempts
            # Preserve the remaining TTL so an attacker cannot extend the window.
            ttl = await redis.ttl(key)
            await redis.setex(
                key, ttl if ttl and ttl > 0 else _CODE_TTL_SECONDS, json.dumps(payload)
            )
        raise InvalidCodeError(
            "Incorrect verification code.", attempts_remaining=remaining
        )

    # Success — consume the challenge so the code is strictly single-use.
    await redis.delete(key)
    return [uuid.UUID(i) for i in payload.get("backup_ids", [])]


async def _send_deletion_code_email(
    db: AsyncSession, email: str, code: str, count: int
) -> None:
    """Email the 6-digit deletion code via the unified email sender."""
    from app.integrations.email_sender import EmailMessage, send_email

    noun = "backup" if count == 1 else "backups"
    subject = "Confirm backup deletion — verification code"
    text_body = (
        f"You requested to permanently delete {count} {noun}.\n\n"
        f"Your verification code is: {code}\n\n"
        "Enter this code to confirm. It expires in 10 minutes. "
        "If you did not request this, ignore this email and your backups will "
        "remain untouched."
    )
    html_body = (
        '<div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:24px">'
        '<h2 style="color:#DC2626;margin-bottom:16px">Confirm backup deletion</h2>'
        f"<p>You requested to permanently delete <strong>{count} {noun}</strong>. "
        "This cannot be undone.</p>"
        "<p>Your verification code is:</p>"
        '<p style="font-size:32px;font-weight:bold;letter-spacing:4px;color:#991B1B;'
        'background:#FEF2F2;padding:16px;border-radius:8px;text-align:center">'
        f"{code}</p>"
        '<p style="color:#6B7280;font-size:14px">This code expires in 10 minutes.<br>'
        "If you did not request this, ignore this email — nothing will be deleted."
        "</p></div>"
    )
    message = EmailMessage(
        to_email=email,
        to_name="",
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        attachments=[],
        org_id=None,
    )
    result = await send_email(db, message)
    if not result.success:
        logger.warning(
            "Backup deletion code email failed for %s: %s", email, result.error
        )
        raise RuntimeError(
            "Could not send the verification email. Check the email provider "
            "configuration and try again."
        )


# ---------------------------------------------------------------------------
# Background deletion job state (Redis) — lets the UI poll a long deletion
# instead of blocking the HTTP request (which can drop over a proxy/tunnel for
# many backups). No DB migration needed; the job record is ephemeral.
# ---------------------------------------------------------------------------


async def create_delete_job(requested: int) -> str:
    """Create a 'running' deletion job record in Redis and return its id."""
    job_id = uuid.uuid4().hex
    await _redis().setex(
        f"{_DELETE_JOB_PREFIX}{job_id}",
        _DELETE_JOB_TTL_SECONDS,
        json.dumps(
            {
                "status": "running",
                "requested": int(requested),
                "deleted": 0,
                "failed": 0,
                "blobs_deleted": 0,
                "error": None,
            }
        ),
    )
    return job_id


async def set_delete_job(job_id: str, **fields: object) -> None:
    """Merge *fields* into a deletion job record (best-effort)."""
    redis = _redis()
    key = f"{_DELETE_JOB_PREFIX}{job_id}"
    try:
        raw = await redis.get(key)
        data = json.loads(raw) if raw else {}
        data.update(fields)
        await redis.setex(key, _DELETE_JOB_TTL_SECONDS, json.dumps(data))
    except Exception:  # noqa: BLE001 - status is best-effort
        logger.debug("could not update delete job %s", job_id, exc_info=True)


async def get_delete_job(job_id: str) -> dict | None:
    """Return a deletion job record, or ``None`` if unknown/expired."""
    raw = await _redis().get(f"{_DELETE_JOB_PREFIX}{job_id}")
    return json.loads(raw) if raw else None
