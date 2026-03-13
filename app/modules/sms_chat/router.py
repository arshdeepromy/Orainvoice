"""Org-scoped SMS chat endpoints.

Provides conversation listing, message history, reply/new conversation,
mark-as-read, archive, number validation, and usage summary.

All endpoints are scoped via RLS tenant middleware (``get_db_session``
sets ``app.current_org_id``).

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 12.4, 14.2
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_any_org_member, require_role
from app.modules.sms_chat.schemas import (
    ConversationListResponse,
    MessageListResponse,
    NewConversationRequest,
    NumberValidationRequest,
    NumberValidationResponse,
    ReplyRequest,
    UsageSummaryResponse,
)
from app.modules.sms_chat.service import (
    _get_connexus_client,
    archive_conversation,
    get_messages,
    get_usage_summary,
    list_conversations,
    mark_read,
    send_reply,
    start_conversation,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/org/sms", tags=["sms-chat"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_org_context(request: Request) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    """Extract org_id, user_id, and role from request state."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    role = getattr(request.state, "role", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None, None
    return org_uuid, user_uuid, role


# ---------------------------------------------------------------------------
# Conversation endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    summary="List SMS conversations",
    dependencies=[require_any_org_member()],
)
async def list_conversations_endpoint(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(None, description="Search by phone number or contact name"),
    db: AsyncSession = Depends(get_db_session),
):
    """Return paginated SMS conversations for the authenticated user's org.

    Ordered by ``last_message_at`` descending. Supports optional search
    filtering on phone_number or contact_name.

    Requirements: 8.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    result = await list_conversations(db, org_id=org_uuid, page=page, per_page=per_page, search=search)
    return ConversationListResponse(
        conversations=result["items"],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="Get message history for a conversation",
    dependencies=[require_any_org_member()],
)
async def get_messages_endpoint(
    conversation_id: uuid.UUID,
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=200, description="Items per page"),
    db: AsyncSession = Depends(get_db_session),
):
    """Return paginated messages for a conversation, ordered by ``created_at`` ascending.

    Requirements: 8.2
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    result = await get_messages(db, org_id=org_uuid, conversation_id=conversation_id, page=page, per_page=per_page)
    return MessageListResponse(
        messages=result["items"],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


# ---------------------------------------------------------------------------
# Send / create endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/conversations/{conversation_id}/reply",
    summary="Send a reply in a conversation",
    dependencies=[require_any_org_member()],
)
async def reply_endpoint(
    conversation_id: uuid.UUID,
    payload: ReplyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Send an outbound SMS reply within an existing conversation.

    Requirements: 8.3, 8.5, 8.6
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        result = await send_reply(db, org_id=org_uuid, conversation_id=conversation_id, body=payload.body)
        return result
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})


@router.post(
    "/conversations/new",
    summary="Start a new conversation",
    dependencies=[require_any_org_member()],
)
async def new_conversation_endpoint(
    payload: NewConversationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new conversation (or reuse existing) and send the first message.

    Requirements: 8.4, 8.5, 8.6
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        result = await start_conversation(db, org_id=org_uuid, phone_number=payload.phone_number, body=payload.body)
        return result
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Conversation state endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/conversations/{conversation_id}/read",
    summary="Mark conversation as read",
    dependencies=[require_any_org_member()],
)
async def mark_read_endpoint(
    conversation_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Reset the unread count to 0 for a conversation.

    Requirements: 8.7
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    await mark_read(db, org_id=org_uuid, conversation_id=conversation_id)
    return {"status": "ok"}


@router.post(
    "/conversations/{conversation_id}/archive",
    summary="Archive a conversation",
    dependencies=[require_any_org_member()],
)
async def archive_endpoint(
    conversation_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Set is_archived to true for a conversation.

    Requirements: 8.8
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    await archive_conversation(db, org_id=org_uuid, conversation_id=conversation_id)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Number validation
# ---------------------------------------------------------------------------


@router.post(
    "/validate-number",
    response_model=NumberValidationResponse,
    summary="Validate a phone number via Connexus IPMS lookup",
    dependencies=[require_any_org_member()],
)
async def validate_number_endpoint(
    payload: NumberValidationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Validate a phone number and return carrier/network information.

    Requirements: 12.4
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        client = await _get_connexus_client(db)
    except ValueError as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    result = await client.validate_number(payload.phone_number)
    return NumberValidationResponse(
        success=result.get("success", False),
        phone_number=result.get("number") or result.get("phone_number"),
        carrier=result.get("carrier"),
        porting_status=result.get("porting_status"),
        original_network=result.get("original_network"),
        current_network=result.get("current_network"),
        network_code=result.get("network_code"),
        error=result.get("error"),
    )


# ---------------------------------------------------------------------------
# Usage summary (org_admin only)
# ---------------------------------------------------------------------------


@router.get(
    "/usage-summary",
    response_model=UsageSummaryResponse,
    summary="Get SMS usage summary for the organisation",
    dependencies=[require_role("org_admin")],
)
async def usage_summary_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return SMS usage summary including total sent, cost, quota, and overage.

    Requires org_admin role.

    Requirements: 14.2
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        result = await get_usage_summary(db, org_id=org_uuid)
        return UsageSummaryResponse(**result)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
