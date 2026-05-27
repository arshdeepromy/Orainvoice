"""Bounce-correlation helper for the email-provider-unification spec.

Phase 8c (task 9.5). Encapsulates the three side-effects that happen
when a Brevo or SendGrid bounce webhook event arrives:

1. Look up the originating ``notification_log`` row by
   ``provider_message_id`` and flip its ``status`` to ``bounced``,
   set ``bounced_at = now()`` and ``bounce_reason = <reason>``. The
   update is a no-op when the row is already ``bounced``, making the
   helper idempotent against duplicate webhook deliveries.
2. Upsert into ``bounced_addresses`` keyed on
   ``(COALESCE(org_id, ''), lower(email_address))``. Hard bounces
   leave ``expires_at`` NULL (never expire); soft / blocked bounces
   set it seven days out so the daily cleanup task prunes them.
3. Fire an in-app notification for ``org_admin`` recipients in any org
   that has an active customer or user matching the bounced address.
   Deduped via Redis on a 24h window keyed on
   ``email_bounced:<address>``.

Public surface
--------------

``flag_bounce(db, *, provider_message_id, recipient, kind, reason,
provider_key, org_id=None) -> None``

The webhook handlers (``brevo_bounce_webhook`` /
``sendgrid_bounce_webhook``) call this once per event. The function
never raises: every failure path is logged and swallowed so a single
bad event can't poison the whole batch.

Requirements: 11.2, 12.2, 12.6, 12.8
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import BouncedAddress, NotificationLog


logger = logging.getLogger(__name__)


#: Soft-bounce expiry — matches ``BOUNCE_SOFT_EXPIRY_DAYS`` in the
#: design doc Components §2 and the project-wide constant in
#: ``email_sender.py``.
SOFT_BOUNCE_EXPIRY_DAYS = 7

#: In-app notification dedup TTL. Same address can fire at most one
#: alert per 24 hours regardless of how many bounce events stream in.
IN_APP_DEDUP_SECONDS = 24 * 60 * 60


def _normalise_kind(raw: str) -> str:
    """Map a webhook event name onto the three ``bounced_addresses`` kinds.

    Brevo uses ``hard_bounce`` / ``soft_bounce`` / ``blocked`` /
    ``invalid_email``; SendGrid uses ``bounce`` / ``dropped`` /
    ``deferred``. We squash these into the storage vocabulary
    (``hard`` / ``soft`` / ``blocked``) so the table CHECK constraint
    accepts them and the pre-send blocklist check can apply uniform
    rules.

    Anything we don't recognise is conservative-mapped to ``soft`` so
    a typo in the webhook event name never gets us stuck blocking a
    real recipient permanently.
    """
    raw_lower = (raw or "").lower().strip()
    if raw_lower in ("hard", "hard_bounce", "bounce"):
        return "hard"
    if raw_lower in ("blocked", "block", "invalid_email", "dropped"):
        return "blocked"
    if raw_lower in ("soft", "soft_bounce", "deferred"):
        return "soft"
    # Fallback — record as soft so we don't permanently block a
    # legitimate address on a parser surprise.
    return "soft"


async def _flip_notification_log_status(
    db: AsyncSession,
    *,
    provider_message_id: str,
    reason: str | None,
) -> uuid.UUID | None:
    """Flip the matching ``notification_log`` row to ``status='bounced'``.

    Returns the row's ``org_id`` for use by downstream side-effects
    (in-app notification dispatch). Returns ``None`` when no row
    matches — the webhook handler still upserts into
    ``bounced_addresses`` because we know the address bounced even if
    we lost the originating log row.

    Idempotent: ``UPDATE ... WHERE status != 'bounced'`` ensures
    repeated webhook deliveries don't churn the row's ``bounced_at``
    timestamp.
    """
    if not provider_message_id:
        return None

    # First fetch to record org_id; we need it for the in-app
    # notification regardless of whether the status flip is a no-op.
    fetch = select(NotificationLog).where(
        NotificationLog.provider_message_id == provider_message_id
    )
    log_row = (await db.execute(fetch)).scalar_one_or_none()
    if log_row is None:
        return None

    # No-op when already bounced — keeps the timestamp stable.
    if log_row.status != "bounced":
        log_row.status = "bounced"
        log_row.bounced_at = datetime.now(timezone.utc)
        if reason:
            log_row.bounce_reason = reason
        await db.flush()

    return log_row.org_id


async def _upsert_bounced_address(
    db: AsyncSession,
    *,
    org_id: uuid.UUID | None,
    email_address: str,
    kind: str,
    reason: str | None,
) -> None:
    """Upsert a row into ``bounced_addresses``.

    Keyed by the migration's functional unique index
    ``(COALESCE(org_id::text, ''), LOWER(email_address))``. Hard
    bounces never expire; soft and blocked bounces set ``expires_at``
    seven days out. Duplicate events bump ``hit_count`` and
    ``last_seen_at`` rather than inserting a new row.

    Implemented via raw SQL so we can speak the COALESCE-keyed
    conflict target directly — SQLAlchemy ORM ``on_conflict_do_update``
    expects a constraint name or column list, neither of which captures
    a functional unique index. Using parameter binding throughout to
    avoid any chance of injection.
    """
    expires_at: datetime | None
    if kind == "hard":
        expires_at = None
    else:
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=SOFT_BOUNCE_EXPIRY_DAYS
        )

    sql = text(
        """
        INSERT INTO bounced_addresses (
            org_id, email_address, bounce_kind, reason,
            first_seen_at, last_seen_at, hit_count, expires_at
        ) VALUES (
            :org_id, lower(:email_address), :bounce_kind, :reason,
            now(), now(), 1, :expires_at
        )
        ON CONFLICT (COALESCE(org_id::text, ''), LOWER(email_address))
        DO UPDATE SET
            last_seen_at = now(),
            hit_count = bounced_addresses.hit_count + 1,
            -- Promote to harder kind: hard > blocked > soft. Never
            -- demote a hard bounce back to soft.
            bounce_kind = CASE
                WHEN bounced_addresses.bounce_kind = 'hard' THEN 'hard'
                WHEN EXCLUDED.bounce_kind = 'hard' THEN 'hard'
                WHEN bounced_addresses.bounce_kind = 'blocked' THEN 'blocked'
                WHEN EXCLUDED.bounce_kind = 'blocked' THEN 'blocked'
                ELSE 'soft'
            END,
            -- Promote expiry: hard never expires; otherwise extend to
            -- the later of the existing and new expiry.
            expires_at = CASE
                WHEN bounced_addresses.bounce_kind = 'hard'
                  OR EXCLUDED.bounce_kind = 'hard' THEN NULL
                WHEN bounced_addresses.expires_at IS NULL THEN NULL
                WHEN EXCLUDED.expires_at IS NULL THEN NULL
                WHEN bounced_addresses.expires_at > EXCLUDED.expires_at
                  THEN bounced_addresses.expires_at
                ELSE EXCLUDED.expires_at
            END,
            reason = COALESCE(EXCLUDED.reason, bounced_addresses.reason)
        """
    )
    await db.execute(
        sql,
        {
            "org_id": org_id,
            "email_address": email_address,
            "bounce_kind": kind,
            "reason": reason,
            "expires_at": expires_at,
        },
    )
    await db.flush()


async def _dedup_should_fire_in_app(email_address: str) -> bool:
    """Redis SETNX-with-TTL guard for the per-address in-app alert.

    Returns ``True`` when the caller should fire (we just claimed the
    dedup key for ``IN_APP_DEDUP_SECONDS``) and ``False`` when an
    earlier call within the 24h window already fired. Fails open on
    Redis unavailability — better duplication than silence.
    """
    key = f"email_bounced:{email_address.lower()}"
    try:
        from app.core.redis import redis_pool

        was_new = await redis_pool.set(
            key, "1", nx=True, ex=IN_APP_DEDUP_SECONDS
        )
        return bool(was_new)
    except Exception as exc:
        logger.warning(
            "bounce_correlation: Redis unavailable for dedup key=%s — "
            "firing anyway: %s",
            key,
            exc,
        )
        return True


async def _fire_in_app_notification_for_bounce(
    db: AsyncSession,
    *,
    org_id: uuid.UUID | None,
    email_address: str,
    reason: str | None,
) -> None:
    """Fire ``email_bounced`` in-app notification for affected orgs.

    A bounce notification fires to ``org_admin`` audience in each org
    where the address matches an active customer or user. Deduped per
    ``email_address`` over 24 hours via Redis (one alert per address
    regardless of how many orgs / how many bounce events).

    When ``org_id`` is provided (the webhook handler resolved the
    originating notification_log row), we limit the notification to
    that org. Otherwise we fan out across all orgs where the address
    is on file — bounce events don't always carry org context, and
    every org with that customer/user benefits from knowing.
    """
    if not await _dedup_should_fire_in_app(email_address):
        return

    # Find orgs to notify. ``org_id`` from the notification_log row
    # takes precedence; otherwise we look up by customer/user email.
    target_orgs: list[uuid.UUID] = []
    if org_id is not None:
        target_orgs.append(org_id)
    else:
        # Local imports avoid a circular import at module load.
        from app.modules.auth.models import User
        from app.modules.customers.models import Customer

        cust_stmt = (
            select(Customer.org_id)
            .where(func.lower(Customer.email) == email_address.lower())
            .distinct()
        )
        cust_org_ids = (await db.execute(cust_stmt)).scalars().all()
        user_stmt = (
            select(User.org_id)
            .where(func.lower(User.email) == email_address.lower())
            .distinct()
        )
        user_org_ids = (await db.execute(user_stmt)).scalars().all()
        seen: set[uuid.UUID] = set()
        for oid in list(cust_org_ids) + list(user_org_ids):
            if oid is None or oid in seen:
                continue
            seen.add(oid)
            target_orgs.append(oid)

    if not target_orgs:
        return

    try:
        from app.modules.in_app_notifications.service import (
            create_in_app_notification,
        )
    except Exception:  # pragma: no cover — module load is stable in prod
        logger.exception(
            "bounce_correlation: failed to import "
            "create_in_app_notification — skipping in-app alert"
        )
        return

    body = (
        f"Email to {email_address} bounced"
        + (f": {reason}" if reason else ".")
    )
    for oid in target_orgs:
        try:
            await create_in_app_notification(
                db,
                org_id=oid,
                category="email_bounced",
                severity="warning",
                title="Email bounced",
                body=body,
                link_url="/admin/email-providers/delivery-health",
                audience_roles=["org_admin"],
                metadata={
                    "address": email_address,
                    "reason": reason or "",
                },
            )
        except Exception:  # pragma: no cover — helper is exception-safe
            logger.exception(
                "bounce_correlation: in-app notification create failed "
                "for org=%s",
                oid,
            )


async def flag_bounce(
    db: AsyncSession,
    *,
    provider_message_id: str | None,
    recipient: str,
    kind: str,
    reason: str | None,
    provider_key: str,
    org_id: uuid.UUID | None = None,
) -> None:
    """Top-level webhook side-effect dispatcher.

    Called once per bounce event by ``brevo_bounce_webhook`` /
    ``sendgrid_bounce_webhook``:

    - Flip the originating ``notification_log`` row to ``bounced``
      when ``provider_message_id`` matches a known row. This also
      surfaces the row's ``org_id`` so the in-app notification fans
      out to the right tenant.
    - Upsert into ``bounced_addresses`` so the next call to
      :func:`app.integrations.email_sender._check_bounce_blocklist`
      short-circuits delivery to the same address.
    - Fire one ``email_bounced`` in-app notification per address per
      24h to the affected orgs' ``org_admin`` audience.

    Idempotent on repeated webhook deliveries: the notification_log
    update is a no-op when the row is already bounced; the
    ``bounced_addresses`` upsert bumps ``hit_count`` rather than
    inserting; and the in-app notification is Redis-deduped.

    The function never raises — every step is wrapped in try/except so
    a single bad event in a batch can't take down the whole webhook.
    The ``provider_key`` argument is currently informational (used in
    logs and metadata); it'll surface on the in-app notification's
    metadata in a later UX iteration.
    """
    if not recipient:
        logger.warning(
            "bounce_correlation: flag_bounce called with empty recipient"
        )
        return

    normalised_kind = _normalise_kind(kind)

    # Step 1 — flip the originating notification_log row, capturing
    # its org_id for downstream fan-out. Wrapped because the lookup
    # can fail (e.g. unrelated DB error mid-batch) and we still want
    # the upsert to run.
    log_org_id: uuid.UUID | None = None
    try:
        log_org_id = await _flip_notification_log_status(
            db,
            provider_message_id=provider_message_id or "",
            reason=reason,
        )
    except Exception:
        logger.exception(
            "bounce_correlation: failed to flip notification_log for "
            "provider_message_id=%s",
            provider_message_id,
        )

    # Caller-supplied org_id takes precedence over the log row's
    # org_id — webhook handlers may know the right org from per-
    # provider secret matching even when the log row is missing.
    effective_org_id = org_id if org_id is not None else log_org_id

    # Step 2 — upsert bounced_addresses. Don't let an upsert failure
    # block the in-app notification.
    try:
        await _upsert_bounced_address(
            db,
            org_id=effective_org_id,
            email_address=recipient,
            kind=normalised_kind,
            reason=reason,
        )
    except Exception:
        logger.exception(
            "bounce_correlation: failed to upsert bounced_addresses for "
            "org_id=%s recipient=%s",
            effective_org_id,
            recipient,
        )

    # Step 3 — also flip ``customers.email_bounced=True`` for every
    # active customer matching the address in the affected org(s). This
    # preserves the pre-Phase-8c behaviour previously embedded in the
    # webhook handler so existing UI surfaces (Customer detail page)
    # keep showing the bounce flag.
    try:
        from app.modules.notifications.service import (
            flag_bounced_email_on_customer,
        )

        if effective_org_id is not None:
            await flag_bounced_email_on_customer(
                db,
                org_id=effective_org_id,
                email_address=recipient,
            )
        else:
            # Fan out across all orgs that have the address on file.
            from app.modules.customers.models import Customer

            stmt = (
                select(Customer.org_id)
                .where(
                    func.lower(Customer.email) == recipient.lower(),
                    Customer.email_bounced == False,  # noqa: E712
                )
                .distinct()
            )
            for oid in (await db.execute(stmt)).scalars().all():
                if oid is None:
                    continue
                await flag_bounced_email_on_customer(
                    db, org_id=oid, email_address=recipient
                )
    except Exception:
        logger.exception(
            "bounce_correlation: failed to flag bounced email on "
            "customer for recipient=%s",
            recipient,
        )

    # Step 4 — in-app notification (deduped per-address per 24h).
    try:
        await _fire_in_app_notification_for_bounce(
            db,
            org_id=effective_org_id,
            email_address=recipient,
            reason=reason,
        )
    except Exception:
        logger.exception(
            "bounce_correlation: in-app notification dispatch failed "
            "for recipient=%s",
            recipient,
        )

    logger.info(
        "bounce_correlation: flagged %s kind=%s provider=%s org=%s "
        "log_msg_id=%s",
        recipient,
        normalised_kind,
        provider_key,
        effective_org_id,
        provider_message_id,
    )


__all__ = ["flag_bounce", "SOFT_BOUNCE_EXPIRY_DAYS"]
