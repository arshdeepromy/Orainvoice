"""Two-phase reminder queue: enqueue (daily scan) + process (batch worker).

Phase 1 — ``enqueue_customer_reminders(db)``:
    Scans all customers with reminder_config, checks vehicle expiry dates,
    and inserts rows into ``reminder_queue`` with status='pending'.
    Uses INSERT ... ON CONFLICT DO NOTHING for dedup.

Phase 2 — ``process_reminder_queue(db, batch_size, delay)``:
    Picks up a batch of pending items, locks them, sends via email/SMS,
    marks sent/failed. Sleeps between batches for rate limiting.

Config constants at the top control batch size, concurrency, and delays.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Any

from sqlalchemy import select, update, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import ReminderQueue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
DEFAULT_BATCH_SIZE = 50          # items per batch
BATCH_DELAY_SECONDS = 2.0       # pause between batches (rate limiting)
SEND_CONCURRENCY = 5            # max concurrent sends within a batch
LOCK_TIMEOUT_MINUTES = 10       # stale lock threshold
MAX_RETRIES = 3
WORKER_ID = "reminder-worker"   # identifies this worker in locked_by


# ---------------------------------------------------------------------------
# Phase 1: Enqueue reminders (daily scan)
# ---------------------------------------------------------------------------

async def enqueue_customer_reminders(db: AsyncSession) -> dict[str, Any]:
    """Scan customers with reminder_config and enqueue pending reminders.

    This is the lightweight "planning" phase — no provider I/O.
    Returns stats dict with counts.
    """
    from app.modules.customers.models import Customer
    from app.modules.vehicles.models import CustomerVehicle
    from app.modules.admin.models import GlobalVehicle, Organisation
    from app.modules.admin.models import SubscriptionPlan
    from app.modules.admin.models import SmsVerificationProvider
    from app.modules.admin.models import EmailProvider
    from app.modules.notifications.service import normalize_phone_number
    from app.core.errors import log_error, Severity, Category

    now = datetime.now(timezone.utc)
    today = now.date()

    stats: dict[str, Any] = {
        "customers_scanned": 0,
        "reminders_enqueued": 0,
        "skipped": 0,
        "errors": 0,
    }

    # Find all customers with reminder_config
    cust_stmt = select(Customer).where(
        Customer.is_anonymised == False,  # noqa: E712
        Customer.custom_fields.has_key("reminder_config"),  # noqa: W601
    )
    cust_result = await db.execute(cust_stmt)
    customers = cust_result.scalars().all()

    # Cache org data
    org_cache: dict[uuid.UUID, dict | None] = {}

    async def _get_org_data(org_id: uuid.UUID) -> dict | None:
        if org_id in org_cache:
            return org_cache[org_id]

        org_result = await db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        if org is None:
            org_cache[org_id] = None
            return None

        org_settings = org.settings or {}

        # SMS plan check
        sms_allowed = False
        if org.plan_id:
            sp_result = await db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
            )
            sp = sp_result.scalar_one_or_none()
            sms_allowed = sp.sms_included if sp else False

        # SMS provider check
        sms_prov_result = await db.execute(
            select(SmsVerificationProvider).where(
                SmsVerificationProvider.is_active == True,  # noqa: E712
            )
        )
        sms_provider = sms_prov_result.scalar_one_or_none()
        sms_configured = (
            sms_provider is not None
            and sms_provider.credentials_encrypted is not None
        )

        # Email provider check
        email_prov_result = await db.execute(
            select(EmailProvider).where(
                EmailProvider.is_active == True,  # noqa: E712
                EmailProvider.credentials_set == True,  # noqa: E712
            ).order_by(EmailProvider.priority)
        )
        email_configured = email_prov_result.scalar_one_or_none() is not None

        # Country code
        country_row = await db.execute(
            text("SELECT country_code FROM organisations WHERE id = :oid"),
            {"oid": str(org_id)},
        )
        country_code_val = country_row.scalar_one_or_none()

        data = {
            "org": org,
            "org_name": org.name,
            "org_phone": org_settings.get("phone", ""),
            "org_email": org_settings.get("email", ""),
            "org_country_code": country_code_val or "NZ",
            "sms_allowed": sms_allowed,
            "sms_configured": sms_configured,
            "email_configured": email_configured,
        }
        org_cache[org_id] = data
        return data

    for customer in customers:
        custom_fields = customer.custom_fields or {}
        reminder_config = custom_fields.get("reminder_config", {})
        if not reminder_config:
            continue

        stats["customers_scanned"] += 1
        org_id = customer.org_id

        org_data = await _get_org_data(org_id)
        if org_data is None:
            stats["skipped"] += 1
            continue

        # Get linked vehicles
        cv_stmt = (
            select(CustomerVehicle, GlobalVehicle)
            .join(GlobalVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)
            .where(
                CustomerVehicle.customer_id == customer.id,
                CustomerVehicle.org_id == org_id,
            )
        )
        cv_result = await db.execute(cv_stmt)
        vehicle_rows = cv_result.all()
        if not vehicle_rows:
            continue

        customer_name = f"{customer.first_name} {customer.last_name}".strip()

        for reminder_type, config_entry in reminder_config.items():
            if not isinstance(config_entry, dict):
                continue
            if not config_entry.get("enabled", False):
                continue

            days_before = config_entry.get("days_before", 30)
            channel = config_entry.get("channel", "email")
            target_date = today + timedelta(days=days_before)

            # Map reminder type to vehicle field
            if reminder_type == "service_due":
                expiry_field = "service_due_date"
                reminder_label = "Service Due"
            elif reminder_type == "wof_expiry":
                expiry_field = "wof_expiry"
                reminder_label = "WOF Expiry"
            else:
                continue

            for cv, gv in vehicle_rows:
                expiry_date = getattr(gv, expiry_field, None)
                if expiry_date is None or expiry_date != target_date:
                    continue

                rego = gv.rego or "Unknown"
                vehicle_desc = " ".join(
                    filter(None, [str(gv.year) if gv.year else None, gv.make, gv.model])
                )

                send_email = channel in ("email", "both")
                send_sms = channel in ("sms", "both")

                # --- Enqueue Email ---
                if send_email:
                    if not org_data["email_configured"]:
                        await log_error(
                            db, severity=Severity.WARNING, category=Category.INTEGRATION,
                            module="notifications.customer_reminders",
                            function_name="enqueue_customer_reminders",
                            message=(
                                f"Reminder ({reminder_label}) skipped for {customer_name} "
                                f"— Email not configured."
                            ),
                            org_id=str(org_id),
                        )
                        stats["errors"] += 1
                        continue
                    if not customer.email:
                        await log_error(
                            db, severity=Severity.WARNING, category=Category.INTEGRATION,
                            module="notifications.customer_reminders",
                            function_name="enqueue_customer_reminders",
                            message=(
                                f"Reminder ({reminder_label}) skipped for {customer_name} "
                                f"— No email on file."
                            ),
                            org_id=str(org_id),
                        )
                        stats["errors"] += 1
                        continue

                    email_subject = f"{reminder_label} reminder for {rego}"
                    email_body = (
                        f"<p>Hi {customer.first_name},</p>"
                        f"<p>{reminder_label} for your vehicle <strong>{rego}</strong>"
                        f"{(' (' + vehicle_desc + ')') if vehicle_desc else ''}"
                        f" is coming up on <strong>{expiry_date}</strong>.</p>"
                        f"<p>Please contact {org_data['org_name']}"
                        f"{(' on ' + org_data['org_phone']) if org_data['org_phone'] else ''}"
                        f" to book your appointment.</p>"
                    )

                    await _insert_queue_item(
                        db, org_id=org_id, customer_id=customer.id,
                        vehicle_id=gv.id, reminder_type=reminder_type,
                        channel="email", recipient=customer.email,
                        subject=email_subject, body=email_body,
                        scheduled_for=now,
                    )
                    stats["reminders_enqueued"] += 1

                # --- Enqueue SMS ---
                if send_sms:
                    if not org_data["sms_configured"]:
                        await log_error(
                            db, severity=Severity.WARNING, category=Category.INTEGRATION,
                            module="notifications.customer_reminders",
                            function_name="enqueue_customer_reminders",
                            message=(
                                f"Reminder ({reminder_label}) skipped for {customer_name} "
                                f"— SMS not configured."
                            ),
                            org_id=str(org_id),
                        )
                        stats["errors"] += 1
                        continue
                    if not org_data["sms_allowed"]:
                        await log_error(
                            db, severity=Severity.WARNING, category=Category.INTEGRATION,
                            module="notifications.customer_reminders",
                            function_name="enqueue_customer_reminders",
                            message=(
                                f"Reminder ({reminder_label}) skipped for {customer_name} "
                                f"— SMS not in plan."
                            ),
                            org_id=str(org_id),
                        )
                        stats["errors"] += 1
                        continue
                    if not customer.phone:
                        await log_error(
                            db, severity=Severity.WARNING, category=Category.INTEGRATION,
                            module="notifications.customer_reminders",
                            function_name="enqueue_customer_reminders",
                            message=(
                                f"Reminder ({reminder_label}) skipped for {customer_name} "
                                f"— No phone on file."
                            ),
                            org_id=str(org_id),
                        )
                        stats["errors"] += 1
                        continue

                    normalized_phone = normalize_phone_number(
                        customer.phone,
                        customer_address=customer.address,
                        org_country_code=org_data["org_country_code"],
                    )
                    if not normalized_phone:
                        await log_error(
                            db, severity=Severity.WARNING, category=Category.INTEGRATION,
                            module="notifications.customer_reminders",
                            function_name="enqueue_customer_reminders",
                            message=(
                                f"Reminder ({reminder_label}) skipped for {customer_name} "
                                f"— Cannot normalize phone number."
                            ),
                            org_id=str(org_id),
                        )
                        stats["errors"] += 1
                        continue

                    sms_body = (
                        f"Hi {customer.first_name}, "
                        f"{reminder_label} for {rego} is due on {expiry_date}. "
                        f"Contact {org_data['org_name']}"
                        f"{(' on ' + org_data['org_phone']) if org_data['org_phone'] else ''}."
                    )

                    await _insert_queue_item(
                        db, org_id=org_id, customer_id=customer.id,
                        vehicle_id=gv.id, reminder_type=reminder_type,
                        channel="sms", recipient=normalized_phone,
                        subject=None, body=sms_body,
                        scheduled_for=now,
                    )
                    stats["reminders_enqueued"] += 1

    return stats


async def _insert_queue_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    vehicle_id: uuid.UUID | None,
    reminder_type: str,
    channel: str,
    recipient: str,
    subject: str | None,
    body: str,
    scheduled_for: datetime,
) -> None:
    """Insert a reminder queue item with ON CONFLICT DO NOTHING for dedup."""
    await db.execute(
        text(
            "INSERT INTO reminder_queue "
            "(id, org_id, customer_id, vehicle_id, reminder_type, channel, "
            " recipient, subject, body, status, scheduled_date, scheduled_for) "
            "VALUES (:id, :org_id, :cid, :vid, :rtype, :channel, "
            " :recipient, :subject, :body, 'pending', :scheduled_date, :scheduled_for) "
            "ON CONFLICT (org_id, customer_id, vehicle_id, reminder_type, scheduled_date) "
            "DO NOTHING"
        ),
        {
            "id": str(uuid.uuid4()),
            "org_id": str(org_id),
            "cid": str(customer_id),
            "vid": str(vehicle_id) if vehicle_id else None,
            "subject": subject,
            "rtype": reminder_type,
            "channel": channel,
            "recipient": recipient,
            "body": body,
            "scheduled_date": scheduled_for.date(),
            "scheduled_for": scheduled_for,
        },
    )


# ---------------------------------------------------------------------------
# Phase 2: Process queue in batches (worker loop)
# ---------------------------------------------------------------------------

async def process_reminder_queue(
    db: AsyncSession,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    delay: float = BATCH_DELAY_SECONDS,
) -> dict[str, Any]:
    """Pick up pending reminders in batches, send them, mark results.

    Uses SELECT ... FOR UPDATE SKIP LOCKED for safe concurrent workers.
    Returns stats dict.
    """
    stats: dict[str, Any] = {
        "batches_processed": 0,
        "sent": 0,
        "failed": 0,
        "retried": 0,
    }

    # First, unlock any stale locks (crashed workers)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOCK_TIMEOUT_MINUTES)
    await db.execute(
        update(ReminderQueue)
        .where(
            ReminderQueue.status == "locked",
            ReminderQueue.locked_at < stale_cutoff,
        )
        .values(status="pending", locked_at=None, locked_by=None)
    )
    await db.commit()

    while True:
        # Lock a batch of pending items
        batch_stmt = (
            select(ReminderQueue)
            .where(
                ReminderQueue.status == "pending",
                ReminderQueue.scheduled_for <= datetime.now(timezone.utc),
            )
            .order_by(ReminderQueue.scheduled_for)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        batch_result = await db.execute(batch_stmt)
        items = batch_result.scalars().all()

        if not items:
            break  # No more pending items

        # Mark as locked
        item_ids = [item.id for item in items]
        await db.execute(
            update(ReminderQueue)
            .where(ReminderQueue.id.in_(item_ids))
            .values(
                status="locked",
                locked_at=datetime.now(timezone.utc),
                locked_by=WORKER_ID,
            )
        )
        await db.commit()

        # Process items with concurrency limit
        semaphore = asyncio.Semaphore(SEND_CONCURRENCY)

        async def _send_one(item: ReminderQueue) -> tuple[str, str | None]:
            async with semaphore:
                try:
                    if item.channel == "email":
                        return await _send_email_reminder(item)
                    elif item.channel == "sms":
                        return await _send_sms_reminder(item)
                    else:
                        return "failed", f"Unknown channel: {item.channel}"
                except Exception as exc:
                    logger.exception("Reminder send failed for %s", item.id)
                    return "failed", str(exc)

        results = await asyncio.gather(*[_send_one(item) for item in items])

        # Update statuses
        now = datetime.now(timezone.utc)
        for item, (result_status, error_msg) in zip(items, results):
            if result_status == "sent":
                await db.execute(
                    update(ReminderQueue)
                    .where(ReminderQueue.id == item.id)
                    .values(
                        status="sent",
                        completed_at=now,
                        locked_at=None,
                        locked_by=None,
                    )
                )
                stats["sent"] += 1
            else:
                new_retry = item.retry_count + 1
                if new_retry >= item.max_retries:
                    await db.execute(
                        update(ReminderQueue)
                        .where(ReminderQueue.id == item.id)
                        .values(
                            status="failed",
                            retry_count=new_retry,
                            error_message=error_msg,
                            completed_at=now,
                            locked_at=None,
                            locked_by=None,
                        )
                    )
                    stats["failed"] += 1
                else:
                    # Put back as pending for retry with backoff
                    backoff = timedelta(seconds=60 * (2 ** new_retry))
                    await db.execute(
                        update(ReminderQueue)
                        .where(ReminderQueue.id == item.id)
                        .values(
                            status="pending",
                            retry_count=new_retry,
                            error_message=error_msg,
                            scheduled_for=now + backoff,
                            locked_at=None,
                            locked_by=None,
                        )
                    )
                    stats["retried"] += 1

        await db.commit()
        stats["batches_processed"] += 1

        # Rate limit: pause between batches
        if delay > 0:
            await asyncio.sleep(delay)

    return stats


async def _send_email_reminder(item: ReminderQueue) -> tuple[str, str | None]:
    """Send a single email reminder. Returns (status, error_msg)."""
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        async with session.begin():
            log_entry = await log_email_sent(
                session,
                org_id=item.org_id,
                recipient=item.recipient,
                template_type=f"customer_{item.reminder_type}_reminder",
                subject=item.subject or "",
                status="queued",
                channel="email",
            )

    text_body = item.body.replace("<p>", "").replace("</p>", "\n").replace("<strong>", "").replace("</strong>", "")

    result = await send_email_task(
        str(item.org_id),
        log_entry["id"],
        item.recipient,
        "",  # to_name
        item.subject or "",
        item.body,
        text_body,
        None,
        None,
        f"customer_{item.reminder_type}_reminder",
    )

    if result and result.get("success"):
        return "sent", None
    return "failed", result.get("error", "Unknown email error") if result else "No result"


async def _send_sms_reminder(item: ReminderQueue) -> tuple[str, str | None]:
    """Send a single SMS reminder. Returns (status, error_msg)."""
    from app.modules.notifications.service import log_sms_sent
    from app.modules.admin.service import increment_sms_usage
    from app.tasks.notifications import send_sms_task
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        async with session.begin():
            sms_log = await log_sms_sent(
                session,
                org_id=item.org_id,
                recipient=item.recipient,
                template_type=f"customer_{item.reminder_type}_reminder",
                body=item.body,
                status="queued",
            )

    result = await send_sms_task(
        str(item.org_id),
        sms_log["id"],
        item.recipient,
        item.body,
        None,
        f"customer_{item.reminder_type}_reminder",
    )

    if result and result.get("success"):
        # Track SMS usage
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    await increment_sms_usage(session, item.org_id)
        except Exception:
            logger.error("Failed to increment SMS usage for org %s", item.org_id, exc_info=True)
        return "sent", None
    return "failed", result.get("error", "Unknown SMS error") if result else "No result"
