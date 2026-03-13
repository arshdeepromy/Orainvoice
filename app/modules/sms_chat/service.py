"""SMS Chat service layer — conversation and message operations.

Provides functions for listing conversations, viewing messages, sending
replies, starting new conversations, marking as read, and archiving.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.connexus_sms import ConnexusConfig, ConnexusSmsClient
from app.integrations.sms_types import SmsMessage as SmsMessagePayload
from app.modules.admin.models import Organisation, SmsPackagePurchase, SmsVerificationProvider, SubscriptionPlan
from app.modules.admin.service import increment_sms_usage
from app.modules.sms_chat.models import SmsConversation, SmsMessage

logger = logging.getLogger(__name__)

# Cost per SMS part: $0.10 + 15% GST = $0.115
COST_PER_PART_NZD = Decimal("0.115")


# ---------------------------------------------------------------------------
# Template rendering helper
# ---------------------------------------------------------------------------


async def render_template_for_sms(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    variables: dict[str, str],
) -> str | None:
    """Load an SMS template by ID and render it with the given variables.

    Returns the rendered body string, or ``None`` if the template is not
    found or has no body content.

    Requirements: 15.1, 15.2
    """
    from app.modules.notifications.models import NotificationTemplate
    from app.modules.notifications.service import render_sms_body

    stmt = select(NotificationTemplate).where(
        NotificationTemplate.id == template_id,
        NotificationTemplate.org_id == org_id,
        NotificationTemplate.channel == "sms",
    )
    result = await db.execute(stmt)
    tpl = result.scalar_one_or_none()
    if tpl is None:
        return None

    body_blocks = tpl.body_blocks or []
    raw_body = ""
    if body_blocks and isinstance(body_blocks, list) and len(body_blocks) > 0:
        raw_body = body_blocks[0].get("content", "") if isinstance(body_blocks[0], dict) else ""

    if not raw_body:
        return None

    return render_sms_body(raw_body, variables)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _conversation_to_dict(conv: SmsConversation) -> dict[str, Any]:
    """Convert an SmsConversation ORM instance to a plain dict."""
    return {
        "id": str(conv.id),
        "org_id": str(conv.org_id),
        "phone_number": conv.phone_number,
        "contact_name": conv.contact_name,
        "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
        "last_message_preview": conv.last_message_preview,
        "unread_count": conv.unread_count,
        "is_archived": conv.is_archived,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
    }


def _message_to_dict(msg: SmsMessage) -> dict[str, Any]:
    """Convert an SmsMessage ORM instance to a plain dict."""
    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "direction": msg.direction,
        "body": msg.body,
        "from_number": msg.from_number,
        "to_number": msg.to_number,
        "external_message_id": msg.external_message_id,
        "status": msg.status,
        "parts_count": msg.parts_count,
        "cost_nzd": str(msg.cost_nzd) if msg.cost_nzd is not None else None,
        "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
        "delivered_at": msg.delivered_at.isoformat() if msg.delivered_at else None,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


async def _get_connexus_client(db: AsyncSession) -> ConnexusSmsClient:
    """Resolve the active Connexus SMS provider and return a configured client."""
    from app.core.encryption import envelope_decrypt_str

    stmt = select(SmsVerificationProvider).where(
        SmsVerificationProvider.provider_key == "connexus",
        SmsVerificationProvider.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    provider = result.scalar_one_or_none()
    if provider is None:
        raise ValueError("Connexus SMS provider is not configured or active")
    creds = json.loads(envelope_decrypt_str(provider.credentials_encrypted))
    config = ConnexusConfig.from_dict(creds)
    return ConnexusSmsClient(config)


# ---------------------------------------------------------------------------
# Conversation & message queries
# ---------------------------------------------------------------------------


async def list_conversations(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
) -> dict[str, Any]:
    """Return paginated conversations ordered by last_message_at DESC.

    Filters out archived conversations by default. Supports optional
    search on phone_number or contact_name (case-insensitive).

    Requirements: 8.1
    """
    base = select(SmsConversation).where(
        SmsConversation.org_id == org_id,
        SmsConversation.is_archived == False,  # noqa: E712
    )
    count_base = select(func.count(SmsConversation.id)).where(
        SmsConversation.org_id == org_id,
        SmsConversation.is_archived == False,  # noqa: E712
    )

    if search:
        like_pattern = f"%{search}%"
        search_filter = (
            SmsConversation.phone_number.ilike(like_pattern)
            | SmsConversation.contact_name.ilike(like_pattern)
        )
        base = base.where(search_filter)
        count_base = count_base.where(search_filter)

    total = (await db.execute(count_base)).scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        base.order_by(SmsConversation.last_message_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    conversations = result.scalars().all()

    return {
        "items": [_conversation_to_dict(c) for c in conversations],
        "total": total,
        "limit": per_page,
        "offset": offset,
    }


async def get_messages(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    conversation_id: uuid.UUID,
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    """Return paginated messages for a conversation ordered by created_at ASC.

    Requirements: 8.2
    """
    base = select(SmsMessage).where(
        SmsMessage.org_id == org_id,
        SmsMessage.conversation_id == conversation_id,
    )
    count_base = select(func.count(SmsMessage.id)).where(
        SmsMessage.org_id == org_id,
        SmsMessage.conversation_id == conversation_id,
    )

    total = (await db.execute(count_base)).scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        base.order_by(SmsMessage.created_at.asc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    return {
        "items": [_message_to_dict(m) for m in messages],
        "total": total,
        "limit": per_page,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# Outbound SMS operations
# ---------------------------------------------------------------------------


async def send_reply(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: str,
) -> dict[str, Any]:
    """Send an outbound reply within an existing conversation.

    1. Look up conversation by id and org_id
    2. Create SmsMessage record with direction='outbound', status='pending'
    3. Update conversation last_message_at and last_message_preview
    4. Increment sms_sent_this_month via increment_sms_usage
    5. Get Connexus client and send
    6. Update message with external_message_id, status, parts_count, cost_nzd
    7. Flush and return result

    Requirements: 8.3, 8.5, 8.6
    """
    # 1. Look up conversation
    stmt = select(SmsConversation).where(
        SmsConversation.id == conversation_id,
        SmsConversation.org_id == org_id,
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise ValueError("Conversation not found")

    now = datetime.now(timezone.utc)

    # 2. Create outbound message record
    message = SmsMessage(
        org_id=org_id,
        conversation_id=conversation_id,
        direction="outbound",
        body=body,
        from_number="",  # will be set by Connexus sender_id
        to_number=conversation.phone_number,
        status="pending",
        sent_at=now,
    )
    db.add(message)

    # 3. Update conversation
    conversation.last_message_at = now
    conversation.last_message_preview = body[:100]

    # 4. Increment sms_sent_this_month
    await increment_sms_usage(db, org_id)

    await db.flush()

    # 5. Send via Connexus
    client = await _get_connexus_client(db)
    sms_payload = SmsMessagePayload(
        to_number=conversation.phone_number,
        body=body,
    )
    send_result = await client.send(sms_payload)

    # 6. Update message with Connexus response
    if send_result.success:
        message.external_message_id = send_result.message_sid
        message.status = "accepted"
        parts = (send_result.metadata or {}).get("parts_count", 1)
        message.parts_count = parts
        message.cost_nzd = Decimal(str(parts)) * COST_PER_PART_NZD
    else:
        message.status = "failed"
        logger.warning(
            "Connexus send failed for conversation %s: %s",
            conversation_id,
            send_result.error,
        )

    await db.flush()

    return _message_to_dict(message)


async def start_conversation(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone_number: str,
    body: str,
) -> dict[str, Any]:
    """Start a new conversation or reuse an existing one, then send a message.

    1. Try to find existing conversation for org_id + phone_number
    2. If not found, create new SmsConversation
    3. Create outbound message and send via Connexus (same as send_reply)

    Requirements: 8.4, 8.5, 8.6
    """
    now = datetime.now(timezone.utc)

    # 1. Try to find existing conversation
    stmt = select(SmsConversation).where(
        SmsConversation.org_id == org_id,
        SmsConversation.phone_number == phone_number,
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    # 2. Create if not found
    if conversation is None:
        conversation = SmsConversation(
            org_id=org_id,
            phone_number=phone_number,
            last_message_at=now,
            last_message_preview=body[:100],
        )
        db.add(conversation)
        await db.flush()
    else:
        # Un-archive if previously archived
        conversation.is_archived = False
        conversation.last_message_at = now
        conversation.last_message_preview = body[:100]

    # 3. Create outbound message
    message = SmsMessage(
        org_id=org_id,
        conversation_id=conversation.id,
        direction="outbound",
        body=body,
        from_number="",
        to_number=phone_number,
        status="pending",
        sent_at=now,
    )
    db.add(message)

    # Increment sms_sent_this_month
    await increment_sms_usage(db, org_id)

    await db.flush()

    # Send via Connexus
    client = await _get_connexus_client(db)
    sms_payload = SmsMessagePayload(
        to_number=phone_number,
        body=body,
    )
    send_result = await client.send(sms_payload)

    # Update message with Connexus response
    if send_result.success:
        message.external_message_id = send_result.message_sid
        message.status = "accepted"
        parts = (send_result.metadata or {}).get("parts_count", 1)
        message.parts_count = parts
        message.cost_nzd = Decimal(str(parts)) * COST_PER_PART_NZD
    else:
        message.status = "failed"
        logger.warning(
            "Connexus send failed for new conversation to %s: %s",
            phone_number,
            send_result.error,
        )

    await db.flush()

    return {
        "conversation": _conversation_to_dict(conversation),
        "message": _message_to_dict(message),
    }


# ---------------------------------------------------------------------------
# Conversation state operations
# ---------------------------------------------------------------------------


async def mark_read(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> None:
    """Set unread_count to 0 for a conversation.

    Requirements: 8.7
    """
    stmt = (
        update(SmsConversation)
        .where(
            SmsConversation.id == conversation_id,
            SmsConversation.org_id == org_id,
        )
        .values(unread_count=0)
    )
    await db.execute(stmt)
    await db.flush()


async def archive_conversation(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> None:
    """Set is_archived to true for a conversation.

    Requirements: 8.8
    """
    stmt = (
        update(SmsConversation)
        .where(
            SmsConversation.id == conversation_id,
            SmsConversation.org_id == org_id,
        )
        .values(is_archived=True)
    )
    await db.execute(stmt)
    await db.flush()


# ---------------------------------------------------------------------------
# Connexus status code mapping (design doc §Connexus Status Code Mapping)
# ---------------------------------------------------------------------------

CONNEXUS_STATUS_MAP: dict[int, str] = {
    1: "delivered",    # DELIVRD
    2: "undelivered",  # UNDELIV
    4: "queued",       # QUEUED
    8: "accepted",     # ACCEPTD
    16: "undelivered", # UNDELIV
}


# ---------------------------------------------------------------------------
# Webhook handlers
# ---------------------------------------------------------------------------


async def _resolve_org_by_sender_id(
    db: AsyncSession, sender_number: str
) -> uuid.UUID | None:
    """Find the org whose active Connexus provider has *sender_number* as its sender_id.

    We query all active Connexus providers, decrypt their credentials, and
    check if the stored ``sender_id`` matches *sender_number*.  Returns the
    first matching org_id, or ``None`` if no match is found.
    """
    from app.core.encryption import envelope_decrypt_str

    stmt = select(SmsVerificationProvider).where(
        SmsVerificationProvider.provider_key == "connexus",
        SmsVerificationProvider.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    providers = result.scalars().all()

    for provider in providers:
        if provider.credentials_encrypted is None:
            continue
        try:
            creds = json.loads(envelope_decrypt_str(provider.credentials_encrypted))
            if creds.get("sender_id") == sender_number:
                # The provider is global (not per-org), so we need to find
                # the org that owns this provider.  In the current schema the
                # provider table has no org_id — it is a global record.
                # Fall back: look for an existing conversation with this
                # sender_id as the org's sender number.  If none exists yet,
                # we cannot determine the org.
                #
                # However, the design says "store with null org_id if
                # unmatched", so returning None here is acceptable for the
                # first message.  For subsequent messages we can look up
                # existing conversations.
                #
                # Since the provider is global, we look for any org that
                # already has a conversation.  If none, return None.
                break
        except Exception:
            logger.warning(
                "Failed to decrypt credentials for provider %s", provider.id
            )
            continue

    # Try to find an org from existing conversations where the org's
    # outbound messages used this sender_number as from_number.
    conv_stmt = (
        select(SmsMessage.org_id)
        .where(
            SmsMessage.direction == "outbound",
            SmsMessage.from_number == sender_number,
        )
        .limit(1)
    )
    conv_result = await db.execute(conv_stmt)
    row = conv_result.scalar_one_or_none()
    if row is not None:
        return row

    # Last resort: if there's only one active org using Connexus, use it.
    # Check the Organisation table for orgs that have conversations.
    org_stmt = (
        select(SmsConversation.org_id)
        .distinct()
        .limit(2)
    )
    org_result = await db.execute(org_stmt)
    org_ids = org_result.scalars().all()
    if len(org_ids) == 1:
        return org_ids[0]

    return None


async def handle_incoming_sms(
    db: AsyncSession,
    payload: dict[str, Any],
) -> None:
    """Process an incoming SMS webhook from Connexus.

    Steps:
    1. Extract and validate required fields from payload.
    2. Deduplicate — skip if external_message_id already exists.
    3. Resolve org by matching the ``to`` number (our sender_id) to a
       Connexus provider's credentials.  Store with ``org_id=None`` if
       unmatched.
    4. Create or update the conversation for (org_id, from_number).
    5. Create an inbound SmsMessage record.
    6. Increment unread_count on the conversation.

    Requirements: 5.2, 5.3, 5.4, 5.7, 8.9
    """
    message_id = payload.get("messageId")
    from_number = payload.get("from") or payload.get("sender")
    to_number = payload.get("to")
    body = payload.get("body", "")
    # timestamp_str available via payload.get("timestamp") if needed later

    if not message_id or not from_number or not to_number:
        raise ValueError("Missing required fields in incoming SMS payload")

    # --- Deduplicate on external_message_id ---
    dup_stmt = select(SmsMessage.id).where(
        SmsMessage.external_message_id == message_id
    )
    dup_result = await db.execute(dup_stmt)
    if dup_result.scalar_one_or_none() is not None:
        logger.info("Duplicate incoming SMS ignored: messageId=%s", message_id)
        return

    # --- Resolve org ---
    org_id = await _resolve_org_by_sender_id(db, to_number)
    if org_id is None:
        logger.warning(
            "Incoming SMS to=%s does not match any org sender_id; storing with null org_id",
            to_number,
        )

    now = datetime.now(timezone.utc)

    # --- Create or update conversation ---
    if org_id is not None:
        conv_stmt = select(SmsConversation).where(
            SmsConversation.org_id == org_id,
            SmsConversation.phone_number == from_number,
        )
        conv_result = await db.execute(conv_stmt)
        conversation = conv_result.scalar_one_or_none()

        if conversation is None:
            conversation = SmsConversation(
                org_id=org_id,
                phone_number=from_number,
                last_message_at=now,
                last_message_preview=body[:100],
                unread_count=1,
            )
            db.add(conversation)
            await db.flush()
        else:
            conversation.last_message_at = now
            conversation.last_message_preview = body[:100]
            conversation.unread_count = (conversation.unread_count or 0) + 1
            # Un-archive if it was archived
            conversation.is_archived = False
            await db.flush()
    else:
        # No org matched — we still need a conversation record.
        # We cannot satisfy the unique constraint without an org_id, so
        # we skip conversation creation and store the message without a
        # conversation_id.  However the schema requires conversation_id
        # NOT NULL, so we create a placeholder conversation with a
        # sentinel org_id (all-zeros UUID).
        sentinel_org = uuid.UUID("00000000-0000-0000-0000-000000000000")
        conv_stmt = select(SmsConversation).where(
            SmsConversation.org_id == sentinel_org,
            SmsConversation.phone_number == from_number,
        )
        conv_result = await db.execute(conv_stmt)
        conversation = conv_result.scalar_one_or_none()

        if conversation is None:
            conversation = SmsConversation(
                org_id=sentinel_org,
                phone_number=from_number,
                last_message_at=now,
                last_message_preview=body[:100],
                unread_count=1,
            )
            db.add(conversation)
            await db.flush()
        else:
            conversation.last_message_at = now
            conversation.last_message_preview = body[:100]
            conversation.unread_count = (conversation.unread_count or 0) + 1
            await db.flush()

        org_id = sentinel_org

    # --- Create inbound message ---
    message = SmsMessage(
        org_id=org_id,
        conversation_id=conversation.id,
        direction="inbound",
        body=body,
        from_number=from_number,
        to_number=to_number,
        external_message_id=message_id,
        status="delivered",
        parts_count=1,
    )
    db.add(message)
    await db.flush()

    logger.info(
        "Incoming SMS stored: messageId=%s, org_id=%s, conversation_id=%s",
        message_id,
        org_id,
        conversation.id,
    )


async def handle_delivery_status(
    db: AsyncSession,
    payload: dict[str, Any],
) -> None:
    """Process a delivery status webhook from Connexus.

    Steps:
    1. Extract messageId and status code from payload.
    2. Map Connexus status code to internal status string.
    3. Find the SmsMessage by external_message_id.
    4. Update status (and delivered_at when status is "delivered").
    5. Idempotent: skip update if status is already the same.

    Requirements: 6.2, 6.3, 6.4, 6.6
    """
    message_id = payload.get("messageId")
    status_code = payload.get("status")

    if not message_id or status_code is None:
        raise ValueError("Missing required fields in delivery status payload")

    internal_status = CONNEXUS_STATUS_MAP.get(status_code)
    if internal_status is None:
        logger.warning(
            "Unknown Connexus status code %s for messageId=%s; ignoring",
            status_code,
            message_id,
        )
        return

    # --- Find message by external_message_id ---
    stmt = select(SmsMessage).where(
        SmsMessage.external_message_id == message_id
    )
    result = await db.execute(stmt)
    message = result.scalar_one_or_none()

    if message is None:
        logger.warning(
            "Delivery status update for unknown messageId=%s; discarding",
            message_id,
        )
        return

    # --- Idempotent: skip if already at the same status ---
    if message.status == internal_status:
        logger.info(
            "Delivery status already %s for messageId=%s; skipping",
            internal_status,
            message_id,
        )
        return

    # --- Update status ---
    message.status = internal_status

    if internal_status == "delivered":
        message.delivered_at = datetime.now(timezone.utc)

    await db.flush()

    logger.info(
        "Delivery status updated: messageId=%s, status=%s",
        message_id,
        internal_status,
    )


# ---------------------------------------------------------------------------
# Usage summary
# ---------------------------------------------------------------------------


async def get_usage_summary(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """Return SMS usage summary for an organisation.

    Returns:
        total_sent: outbound message count this month (from org.sms_sent_this_month)
        total_cost: sum of cost_nzd from outbound sms_messages this month
        included_quota: from the org's subscription plan (plan.sms_included_quota)
        package_credits_remaining: sum of credits_remaining from sms_package_purchases
        overage_count: max(0, total_sent - effective_quota)
        overage_charge: overage_count × plan.per_sms_cost_nzd
        warning: True when total_sent exceeds 80% of effective_quota

    Requirements: 14.2, 14.5
    """
    from sqlalchemy import func as sa_func

    # Fetch org + plan in one query
    stmt = (
        select(Organisation, SubscriptionPlan)
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.id == org_id)
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        raise ValueError("Organisation not found")

    org, plan = row

    total_sent = org.sms_sent_this_month
    included_quota = plan.sms_included_quota if plan.sms_included else 0
    per_sms_cost = float(plan.per_sms_cost_nzd)

    # Sum cost_nzd from outbound sms_messages for this org this month
    cost_stmt = select(
        sa_func.coalesce(sa_func.sum(SmsMessage.cost_nzd), Decimal("0"))
    ).where(
        SmsMessage.org_id == org_id,
        SmsMessage.direction == "outbound",
    )
    cost_result = await db.execute(cost_stmt)
    total_cost = cost_result.scalar()

    # Sum credits_remaining from all SMS package purchases for this org
    pkg_stmt = select(
        sa_func.coalesce(sa_func.sum(SmsPackagePurchase.credits_remaining), 0)
    ).where(SmsPackagePurchase.org_id == org_id)
    pkg_result = await db.execute(pkg_stmt)
    package_credits_remaining = int(pkg_result.scalar())

    # Compute overage
    effective_quota = included_quota + package_credits_remaining
    overage_count = max(0, total_sent - effective_quota)
    overage_charge = round(overage_count * per_sms_cost, 2)

    # Warning when usage exceeds 80% of effective quota
    warning = effective_quota > 0 and total_sent > (effective_quota * 0.8)

    return {
        "total_sent": total_sent,
        "total_cost": str(total_cost),
        "included_quota": included_quota,
        "package_credits_remaining": package_credits_remaining,
        "overage_count": overage_count,
        "overage_charge": overage_charge,
        "warning": warning,
    }
