"""Service for managing single-use, token-gated staff onboarding links.

Mirrors ``app/modules/staff/roster_tokens.py`` in shape (a small helper
module the admin ``POST /api/v2/staff`` flow and the public
``/api/v2/public/staff-onboarding`` router both import) but with three
deliberate differences driven by the onboarding threat model:

1. **The token is hashed at rest.** Only ``SHA-256(token)`` is persisted
   in ``token_hash``; the raw URL-safe token lives only in the emailed
   link and the recipient's browser. A leaked DB snapshot cannot be
   replayed to submit a victim's PII (R2.2, R11.x uplift over roster).
2. **Explicit ``status`` lifecycle.** ``pending`` → ``consumed`` (on a
   successful submit) or ``pending`` → ``revoked`` (on resend / revoke /
   deactivation). Expiry is *derived* from ``expires_at``, never stored.
3. **Server-side encrypted draft.** The whole partial form payload is
   serialized to JSON and envelope-encrypted onto the token row so a
   half-finished onboarding is resumable on any device (R12). The draft
   never outlives its token: it is purged on submit (R12.8) and on
   revoke / resend / expiry / deactivation (R12.9).

Async-session conventions follow the project rule: services ``flush()``
(never ``commit()`` — the ``get_db_session`` dependency uses
``session.begin()`` which auto-commits on a clean return) and
``await db.refresh(obj)`` after flush before returning an ORM object so
Pydantic serialization does not trip ``MissingGreenlet``.

Validates: Requirements 2.1, 2.2, 2.3, 2.5, 10.2, 12.6, 12.7, 12.8, 12.9.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.modules.staff.models import StaffOnboardingToken

# R2.1 — ≥32 bytes of entropy → 43-char URL-safe base64 string. Identical
# to the ``secrets.token_urlsafe(32)`` pattern used by ``roster_tokens.py``
# and the customer portal, so the public URL has the same unguessability
# properties (~256 bits).
_TOKEN_NBYTES = 32

# R2.3 — onboarding link expires 7 days after issue.
_TOKEN_TTL_DAYS = 7


def _now_utc() -> datetime:
    """Timezone-aware "now" in UTC (matches the model's ``timezone=True`` columns)."""
    return datetime.now(timezone.utc)


def _hash_token(raw: str) -> str:
    """Return the SHA-256 hex digest (64 chars) of a raw token string.

    The raw token is never persisted — lookups hash the incoming token
    and match on ``token_hash`` (a unidirectional, deterministic lookup).
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json_default(value: Any) -> Any:
    """JSON serializer for the draft payload's non-primitive types.

    Callers may pass a plain ``dict`` containing ``date`` / ``datetime``
    (e.g. ``visa_expiry_date``), ``Decimal`` (e.g. ``kiwisaver_employee_rate``)
    or ``uuid.UUID`` values. Rather than require every caller to remember to
    pass ``model_dump(mode="json")``, this default makes ``save_draft``
    robust to those types on its own:

    - ``date`` / ``datetime`` → ISO-8601 string
    - ``Decimal`` → ``str`` (lossless; avoids float rounding of rates)
    - ``uuid.UUID`` → ``str``

    Anything else still raises ``TypeError`` so genuinely unserializable
    values (e.g. a file handle) fail loudly rather than corrupting a draft.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


async def mint(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
) -> str:
    """Mint a fresh pending onboarding token for ``staff_id`` and return the RAW token.

    Any prior *pending* token for this staff is revoked first (its draft
    purged along the way, R12.9) so there is at most one live link per
    staff member — re-sending an invite supersedes the previous one
    (R2.5). Stores only the SHA-256 hash; the returned raw string is the
    only place the live token exists and belongs in the emailed URL.
    """
    # Supersede any existing live link (and purge its draft) before issuing
    # a new one.
    await revoke_active(db, org_id=org_id, staff_id=staff_id)

    raw = secrets.token_urlsafe(_TOKEN_NBYTES)
    row = StaffOnboardingToken(
        org_id=org_id,
        staff_id=staff_id,
        token_hash=_hash_token(raw),
        status="pending",
        expires_at=_now_utc() + timedelta(days=_TOKEN_TTL_DAYS),
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return raw


async def resolve(db: AsyncSession, raw: str) -> StaffOnboardingToken | None:
    """Look up the token row whose ``token_hash`` matches ``hash(raw)``.

    Returns ``None`` when no row matches (the caller maps that to
    ``404 onboarding_token_not_found``). Does not interpret status /
    expiry — that classification lives in ``onboarding_logic``.
    """
    stmt = select(StaffOnboardingToken).where(
        StaffOnboardingToken.token_hash == _hash_token(raw)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def consume(db: AsyncSession, row: StaffOnboardingToken) -> None:
    """Mark ``row`` consumed on a successful submit (R2.5) and purge its draft.

    Sets ``status="consumed"`` + ``consumed_at=now`` and NULLs both draft
    columns in the same write so the partial PII blob never outlives the
    token once onboarding is submitted (R12.8).
    """
    row.status = "consumed"
    row.consumed_at = _now_utc()
    row.draft_data_encrypted = None
    row.draft_updated_at = None
    await db.flush()


async def revoke_active(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
) -> int:
    """Bulk-revoke all *pending* tokens for ``(org_id, staff_id)``; return the count.

    Used on resend (via ``mint``), explicit revoke, and the
    deactivation / termination auto-revoke path (R10.2/R10.4). NULLs the
    draft columns in the same UPDATE so a draft never outlives its token
    on revoke (R12.9).
    """
    stmt = (
        update(StaffOnboardingToken)
        .where(
            StaffOnboardingToken.org_id == org_id,
            StaffOnboardingToken.staff_id == staff_id,
            StaffOnboardingToken.status == "pending",
        )
        .values(
            status="revoked",
            draft_data_encrypted=None,
            draft_updated_at=None,
        )
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


# ---------------------------------------------------------------------------
# Draft helpers (R12) — whole-blob envelope encryption on the token row
# ---------------------------------------------------------------------------


async def save_draft(
    db: AsyncSession,
    row: StaffOnboardingToken,
    payload: dict,
) -> None:
    """Envelope-encrypt the partial form ``payload`` onto ``row`` as a draft.

    The entire payload is serialized to JSON (with ``_json_default``
    handling ``date`` / ``Decimal`` / ``UUID``) and encrypted as one blob
    via ``envelope_encrypt``, which satisfies R12.6 (partial IRD/bank
    encrypted at rest) with no field-by-field handling. ``draft_updated_at``
    is bumped to now.

    Saving a draft **never consumes** the token (R12.7): ``status`` and
    ``consumed_at`` are left untouched — only the two draft columns change.
    """
    serialized = json.dumps(payload, default=_json_default)
    row.draft_data_encrypted = envelope_encrypt(serialized)
    row.draft_updated_at = _now_utc()
    await db.flush()


def load_draft(row: StaffOnboardingToken) -> dict | None:
    """Decrypt and parse the stored draft blob back to a ``dict``.

    Returns ``None`` when no draft has been saved (``draft_data_encrypted``
    is NULL) — the ``not_started`` vs ``in_progress`` discriminator. Pure
    (no DB I/O) so it is cheap to call on a row already loaded by ``resolve``.
    """
    if row.draft_data_encrypted is None:
        return None
    return json.loads(envelope_decrypt_str(row.draft_data_encrypted))


async def purge_draft(db: AsyncSession, row: StaffOnboardingToken) -> None:
    """NULL both draft columns on ``row`` and flush (R12.9).

    Leaves ``status`` / ``consumed_at`` untouched — this is the low-level
    purge used by the lazy expiry path and by callers that want to discard
    a draft without changing the token's lifecycle.
    """
    row.draft_data_encrypted = None
    row.draft_updated_at = None
    await db.flush()


async def purge_draft_if_expired(
    db: AsyncSession,
    row: StaffOnboardingToken,
) -> bool:
    """Lazily purge the draft of a *pending-but-expired* token (R12.9).

    Expiry is a derived state — no stored transition fires at the expiry
    instant — so the encrypted draft of an expired link would otherwise
    linger until the next resend/revoke. Any access that classifies a
    token as expired should call this so the partial PII blob does not
    outlive the link: when ``status == "pending"`` and
    ``expires_at <= now()`` and a draft is present, both draft columns are
    NULLed and ``True`` is returned. Otherwise it is a no-op returning
    ``False`` (idempotent and safe to call on every resolve).
    """
    if (
        row.status == "pending"
        and row.expires_at is not None
        and row.expires_at <= _now_utc()
        and row.draft_data_encrypted is not None
    ):
        await purge_draft(db, row)
        return True
    return False
