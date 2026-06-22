"""Public read-only staff roster viewer.

Token-gated, no-auth endpoint that renders a recipient's week roster
when they click the link from their roster SMS or email delivery
(C3, C6). Hosted under ``/api/v2/public/staff-roster/`` so the auth
middleware's ``/api/v2/public/`` prefix bypass already applies — no
JWT required.

A per-IP rate limit of **30 req/min** is layered on top by
``app/middleware/rate_limit.py`` (G5) to defend against accidental
scraping (e.g. a token leaked into a public Slack channel and
spidered by a crawler). The 32-byte token's entropy already makes
brute-force impractical; the limit is a belt-and-braces guard.

Failure modes (R9.4, G4):

- Token doesn't exist → **HTTP 404** ``{"detail": "token_not_found"}``.
- Token exists, ``expires_at <= now()``, AND the staff is
  deactivated (``is_active=false``) — the deactivation/termination
  flow (C11) sets ``expires_at = now()`` to revoke all of a staff's
  tokens, so a deactivated staff is the signal we use to distinguish
  this case → **HTTP 410** ``{"detail": "token_expired_staff_deactivated"}``.
- Token exists, ``expires_at <= now()``, staff still active —
  natural 30-day TTL expiry → **HTTP 410**
  ``{"detail": "token_expired"}``.

On success the response is::

    {
        "staff_name": "...",
        "week_start": "YYYY-MM-DD",
        "week_end":   "YYYY-MM-DD",   # week_start + 7 days
        "entries": [
            {
                "start_time": "...",   # ISO 8601, UTC
                "end_time":   "...",
                "title":      "...",   # nullable
                "notes":      "...",   # nullable
                "entry_type": "..."
            },
            ...
        ]
    }

The endpoint deliberately exposes the **bare minimum** — no employee
ID, no contact details, no pay info, no PII. Just the staff's display
name and their schedule for the week. The recipient already knows
who they are; the link only needs to confirm the schedule.

**Validates: Requirements R9.4, R9.8, G5** (Phase 1 task C7).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import _set_rls_org_id, get_db_session
from app.core.encryption import envelope_encrypt
from app.modules.compliance_docs.service import ComplianceService
from app.modules.uploads.router import store_staff_photo
from app.modules.in_app_notifications.service import create_in_app_notification
from app.modules.organisations.service import get_org_settings
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff import onboarding_delivery, onboarding_tokens
from app.modules.staff.models import StaffMember, StaffRosterViewToken
from app.modules.staff.onboarding_validation import (
    MAX_DOCUMENT_COUNT,
    classify_token_state,
    compute_completion_percentage,
    humanize_onboarding_error,
    ird_mod11_ok,
    token_state_error_code,
    validate_documents,
    validate_emergency_contact,
    validate_ird_length,
    validate_nz_bank_account,
    validate_visa_expiry,
)
from app.modules.staff.schemas import (
    OnboardingDraftFields,
    OnboardingDraftRequest,
    OnboardingDraftResponse,
    OnboardingFieldError,
    OnboardingPrefillResponse,
    OnboardingSubmitResponse,
)
from app.modules.staff.security import mask_bank_account, mask_ird

logger = logging.getLogger(__name__)

public_router = APIRouter()

# Public onboarding router — mounted under ``/api/v2/public/staff-onboarding``
# in ``app/main.py`` (a DIFFERENT prefix from the roster viewer above). The
# ``/api/v2/public/`` prefix already bypasses the auth middleware (no JWT) and
# a dedicated 30-req/min per-IP rate limit applies via the rate-limit
# middleware. Tasks 8.2 / 8.3 add the submit + draft routes to this same
# router object.
onboarding_public_router = APIRouter()


def _staff_display_name(staff: StaffMember) -> str:
    """Build a sensible display name for the public viewer.

    Prefers ``"first last"`` but falls back to whichever fields are
    populated. Defensive against legacy rows where ``first_name`` was
    introduced later (server_default empty string) and ``name`` was
    the original single-field column.
    """
    first = (staff.first_name or "").strip()
    last = (staff.last_name or "").strip()
    combined = f"{first} {last}".strip()
    if combined:
        return combined
    return (staff.name or "").strip() or "Staff member"


@public_router.get(
    "/{token}",
    summary="Public read-only staff roster viewer (token-gated, no auth)",
    responses={
        200: {"description": "Roster for the week the token was issued for."},
        404: {"description": "Token does not exist."},
        410: {
            "description": (
                "Token has expired — either the natural 30-day TTL "
                "lapsed, or the staff was deactivated (which revoked "
                "all of their tokens by setting expires_at=now())."
            )
        },
        429: {
            "description": (
                "Per-IP rate limit (30 req/min) exceeded. Retry-After "
                "header indicates when to retry."
            )
        },
    },
)
async def view_staff_roster(
    token: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return the staff's week roster for a given viewer token.

    No authentication. Token validity + expiry are the only gates.
    See the module docstring for the three failure modes.
    """
    # ------------------------------------------------------------------
    # 1. Token lookup. Three outcomes follow:
    #    - row missing → 404 token_not_found
    #    - row present + expired + staff deactivated → 410 token_expired_staff_deactivated
    #    - row present + expired + staff still active → 410 token_expired
    #    - row present + valid → render the schedule
    # ------------------------------------------------------------------
    token_row = (
        await db.execute(
            select(StaffRosterViewToken).where(
                StaffRosterViewToken.token == token,
            )
        )
    ).scalar_one_or_none()

    if token_row is None:
        # Distinct from the 410 cases — this is a token that was never
        # issued (or was hard-deleted via the ON DELETE CASCADE from a
        # staff/org delete, G8). Avoid leaking which possibility it is.
        raise HTTPException(status_code=404, detail="token_not_found")

    # Need the staff record both for the 410-distinguishing check and
    # for the success-path display name. Fetch once and reuse.
    staff = (
        await db.execute(
            select(StaffMember).where(
                StaffMember.id == token_row.staff_id,
                StaffMember.org_id == token_row.org_id,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if token_row.expires_at <= now:
        # 410-distinguishing: a deactivated staff is the signal that
        # the deactivation/termination flow (C11) revoked the token by
        # setting expires_at=now(). Natural 30-day TTL expiry happens
        # while the staff is still active.
        if staff is not None and not staff.is_active:
            raise HTTPException(
                status_code=410,
                detail="token_expired_staff_deactivated",
            )
        raise HTTPException(status_code=410, detail="token_expired")

    if staff is None:
        # Defensive: the FK is ON DELETE CASCADE so a missing staff
        # with a present token shouldn't happen, but if it ever does
        # (e.g., a manual DB tweak), treat the link as unusable rather
        # than 500. Behaviour mirrors the 404 path so we don't leak
        # internal state.
        raise HTTPException(status_code=404, detail="token_not_found")

    # ------------------------------------------------------------------
    # 2. Load the week's schedule entries. Mirrors the window logic
    #    in ``roster_delivery._load_week_entries`` — schedule_entries
    #    are stored UTC; we compare against UTC midnight at week_start
    #    and week_start + 7 days.
    # ------------------------------------------------------------------
    week_end = token_row.week_start + timedelta(days=7)
    start_dt = datetime.combine(token_row.week_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(week_end, time.min, tzinfo=timezone.utc)

    entries = (
        await db.execute(
            select(ScheduleEntry)
            .where(
                ScheduleEntry.org_id == token_row.org_id,
                ScheduleEntry.staff_id == token_row.staff_id,
                ScheduleEntry.start_time >= start_dt,
                ScheduleEntry.start_time < end_dt,
            )
            .order_by(ScheduleEntry.start_time)
        )
    ).scalars().all()

    return {
        "staff_name": _staff_display_name(staff),
        "week_start": token_row.week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "entries": [
            {
                "start_time": e.start_time.isoformat() if e.start_time else None,
                "end_time": e.end_time.isoformat() if e.end_time else None,
                "title": e.title,
                "notes": e.notes,
                "entry_type": e.entry_type,
            }
            for e in entries
        ],
    }


# ---------------------------------------------------------------------------
# Public onboarding — prefill + draft resume (R4.2, R11.3, R11.4, R11.6,
# R12.3, R12.4, R14.1)
# ---------------------------------------------------------------------------


def _onboarding_error(state: str) -> HTTPException:
    """Build the humanized ``{message, code}`` HTTPException for a token state.

    ``not_found`` → 404, every other rejecting state → 410 (R11.4). The body
    carries the human-readable sentence from ``humanize_onboarding_error`` plus
    the machine code, and never contains raw DB/exception text (R14.1, R14.5).
    """
    code = token_state_error_code(state)
    message = humanize_onboarding_error(code)
    status_code = 404 if state == "not_found" else 410
    return HTTPException(status_code=status_code, detail={"message": message, "code": code})


def _draft_fields_from_payload(draft: dict) -> OnboardingDraftFields:
    """Map a decrypted draft payload to the masked, resume-safe response shape.

    Non-sensitive fields are passed through in full. IRD and bank account are
    returned **masked** (never the decrypted plaintext, R11.6) with ``has_ird``
    / ``has_bank`` presence flags so the client can render the masked
    placeholder and avoid re-sending it unless the value is retyped.
    """
    ird_value = draft.get("ird_number")
    bank_value = draft.get("bank_account_number")
    has_ird = bool(ird_value and str(ird_value).strip())
    has_bank = bool(bank_value and str(bank_value).strip())

    raw_count = draft.get("documents_staged_count")
    documents_staged_count = raw_count if isinstance(raw_count, int) and not isinstance(raw_count, bool) else 0

    return OnboardingDraftFields(
        last_name=draft.get("last_name"),
        phone=draft.get("phone"),
        emergency_contact_name=draft.get("emergency_contact_name"),
        emergency_contact_phone=draft.get("emergency_contact_phone"),
        tax_code=draft.get("tax_code"),
        student_loan=draft.get("student_loan"),
        kiwisaver_enrolled=draft.get("kiwisaver_enrolled"),
        kiwisaver_employee_rate=draft.get("kiwisaver_employee_rate"),
        residency_type=draft.get("residency_type"),
        visa_expiry_date=draft.get("visa_expiry_date"),
        ird_number=mask_ird(ird_value) if has_ird else None,
        has_ird=has_ird,
        bank_account_number=mask_bank_account(bank_value) if has_bank else None,
        has_bank=has_bank,
        documents_staged_count=documents_staged_count,
    )


@onboarding_public_router.get(
    "/{token}",
    response_model=OnboardingPrefillResponse,
    summary="Public onboarding prefill (token-gated, no auth)",
    responses={
        200: {"description": "Prefill identity + option lists + saved draft (if any)."},
        404: {"description": "Token does not exist."},
        410: {
            "description": (
                "Token is revoked, consumed, expired, or the staff member is "
                "inactive — a distinct {message, code} per state."
            )
        },
        429: {"description": "Per-IP rate limit (30 req/min) exceeded."},
    },
)
async def onboarding_prefill(
    token: str,
    db: AsyncSession = Depends(get_db_session),
) -> OnboardingPrefillResponse:
    """Return the prefill payload for an onboarding link (R4.2, R11.6, R12.3).

    Resolves the token, classifies its state, and:

    - rejects with a distinct humanized ``404``/``410`` per non-valid state
      (R11.4); on the *expired* state it lazily purges any lingering draft so
      a partial PII blob never outlives its link (R12.9);
    - on a valid token returns ONLY ``first_name`` / ``email`` of the staff
      identity (R11.6), the org display name, the static option lists, and
      ``bank_account_required`` from org config (R5.4);
    - includes the saved draft for resume when present — non-sensitive fields
      in full, IRD/bank masked with ``has_*`` flags (R11.6) — plus the
      top-level ``completion_percentage`` and ``last_saved_at`` (R12.3).
    """
    now = datetime.now(timezone.utc)

    row = await onboarding_tokens.resolve(db, token)

    # Need the staff record both to determine ``is_active`` for state
    # classification and to read first_name/email on the success path.
    staff: StaffMember | None = None
    if row is not None:
        staff = (
            await db.execute(
                select(StaffMember).where(
                    StaffMember.id == row.staff_id,
                    StaffMember.org_id == row.org_id,
                )
            )
        ).scalar_one_or_none()

    staff_is_active = bool(staff is not None and staff.is_active)
    state = classify_token_state(row, now, staff_is_active)

    if state == "expired" and row is not None:
        # Lazy purge: expiry is a derived state with no stored transition, so
        # NULL the draft columns here so no partial draft outlives the link
        # (R12.9). flush() (not commit()) — get_db_session auto-commits.
        await onboarding_tokens.purge_draft_if_expired(db, row)

    if state != "valid" or row is None or staff is None:
        raise _onboarding_error(state)

    # Org config — get_org_settings returns a flat dict carrying org_name plus
    # all settings keys. bank_account_required defaults to False when absent.
    settings = await get_org_settings(db, org_id=row.org_id)
    org_name = settings.get("org_name") or "your employer"
    bank_account_required = bool(settings.get("onboarding_bank_account_required", False))

    # Resume payload — decrypt the draft server-side; None when none saved.
    draft_payload = onboarding_tokens.load_draft(row)
    draft_fields: OnboardingDraftFields | None = None
    completion_percentage: int | None = None
    last_saved_at = None
    if draft_payload is not None:
        draft_fields = _draft_fields_from_payload(draft_payload)
        completion_percentage = compute_completion_percentage(draft_payload)
        last_saved_at = row.draft_updated_at

    return OnboardingPrefillResponse(
        first_name=(staff.first_name or staff.name or "").strip(),
        email=(staff.email or "").strip(),
        org_name=org_name,
        bank_account_required=bank_account_required,
        draft=draft_fields,
        completion_percentage=completion_percentage,
        last_saved_at=last_saved_at,
    )


# ---------------------------------------------------------------------------
# Public onboarding — submit (R4–R9, R14, R15, R16)
# ---------------------------------------------------------------------------
#
# Coordination note (task 5.1 / 8.2 — avoid a DUPLICATE in-app notification):
# ``onboarding_delivery.notify_org_onboarding_complete`` does TWO things — (a)
# create the org in-app notification AND (b) email each org_admin/branch_admin.
# The design wants the in-app notification created INSIDE the submit
# transaction (so it commits atomically with the submit, R16.1/R16.4). To avoid
# creating it twice, this handler implements **option (a)**:
#
#   * IN-TRANSACTION: call ``create_in_app_notification(...)`` directly (step 7).
#   * POST-COMMIT (best-effort): send ONLY the emails — the staff confirmation
#     email (R15) and the org_admin/branch_admin completion emails (R16.3),
#     the latter assembled here from ``resolve_org_notification_recipients`` +
#     ``compose_org_completion_email`` + ``send_email`` rather than calling
#     ``notify_org_onboarding_complete`` (which would re-create the in-app row).
#
# Dispatch ordering: the two completion emails are sent inline AFTER all DB
# writes (after the token is consumed), each wrapped in try/except so a send
# failure is logged and swallowed and can never roll back or block the
# already-successful submission (R15.4, R16.6). This is the design's sanctioned
# "send inline after the DB writes with the result ignored" post-commit
# discipline; the staff member has already been given the 200 thank-you (R9.5)
# and the submission is durable regardless of email outcome.


def _present(value: str | None) -> bool:
    """True when *value* is a non-empty (after-strip) string."""
    return bool(value is not None and value.strip())


def _field_error_body(
    errors: dict[str, OnboardingFieldError],
    *,
    message_code: str = "validation_failed",
) -> JSONResponse:
    """Build the top-level ``422 {ok:false, errors:{field:{message,code}}, message}`` body.

    Used for pre-write rejections (field validation, encryption failure). The
    body is top-level (not nested under ``detail``) per the design's submit
    contract; because these rejections fire BEFORE any DB write, returning a
    clean response leaves the token ``pending`` with its draft intact (R9.7) —
    nothing is persisted (R14.1, R14.5).
    """
    return JSONResponse(
        status_code=422,
        content={
            "ok": False,
            "message": humanize_onboarding_error(message_code),
            "errors": {
                field: {"message": err.message, "code": err.code}
                for field, err in errors.items()
            },
        },
    )


@onboarding_public_router.post(
    "/{token}",
    response_model=OnboardingSubmitResponse,
    summary="Public onboarding submit (multipart, token-gated, no auth)",
    responses={
        200: {"description": "Submission accepted; staff record updated and token consumed."},
        404: {"description": "Token does not exist."},
        410: {"description": "Token is revoked, consumed, expired, or staff inactive."},
        422: {"description": "Field validation or encryption failure ({ok:false, errors, message})."},
        429: {"description": "Per-IP rate limit (30 req/min) exceeded."},
    },
)
async def onboarding_submit(  # noqa: C901, PLR0912, PLR0915 — one cohesive handler
    token: str,
    request: Request = None,  # type: ignore[assignment]  # FastAPI injects; default lets tests omit it
    db: AsyncSession = Depends(get_db_session),
    last_name: str | None = Form(None),
    phone: str | None = Form(None),
    emergency_contact_name: str | None = Form(None),
    emergency_contact_phone: str | None = Form(None),
    bank_account_number: str | None = Form(None),
    ird_number: str | None = Form(None),
    tax_code: str | None = Form(None),
    student_loan: bool | None = Form(None),
    kiwisaver_enrolled: bool | None = Form(None),
    kiwisaver_employee_rate: Decimal | None = Form(None),
    residency_type: str | None = Form(None),
    visa_expiry_date: date | None = Form(None),
    documents: list[UploadFile] = File(default=[]),  # noqa: B008
    document_types: list[str] = Form(default=[]),  # noqa: B008
    document_descriptions: list[str] = Form(default=[]),  # noqa: B008
    profile_photo: UploadFile | None = File(default=None),  # noqa: B008
):
    """Accept and persist a completed onboarding form (R4–R9).

    Handler order (token re-validated first, consumed last):

    1. resolve + ``classify_token_state`` — reject non-valid states with the
       humanized ``404``/``410`` ``{message, code}`` via ``_onboarding_error``;
    2. ``_set_rls_org_id(db, token.org_id)`` — scope every write below to the
       trusted server-side org BEFORE any validation/write (the public request
       carries no ``app.current_org_id``);
    3. collect ALL field errors → ``422 {ok:false, errors, message}`` (R9.1,
       R9.2); IRD mod-11 / past-visa are non-blocking warnings (R8.3);
    4. envelope-encrypt IRD/bank (try/except → ``422 encryption_failed``,
       nothing written, token stays pending with draft intact, R9.7);
    5. write provided fields into ``staff_members`` (never first_name/email);
    6. store ≤3 working-rights docs via ``ComplianceService`` (R7.6);
    7. ``create_in_app_notification`` for org_admin/branch_admin (in-transaction,
       never raises, R16.1/R16.2/R16.4);
    8. ``consume`` the token (only on full success; purges the draft, R2.5/
       R9.6/R12.8); clean return auto-commits steps 5–8 (R9.6);
    9. AFTER the writes (best-effort, swallowed): staff confirmation email
       (R15) + org_admin/branch_admin completion emails (R16.3).

    Unexpected exceptions at the boundary roll the submit back and return the
    humanized ``server_error`` message (R14.5).
    """
    now = datetime.now(timezone.utc)

    try:
        # --- 1. Re-validate the token --------------------------------------
        row = await onboarding_tokens.resolve(db, token)

        staff: StaffMember | None = None
        if row is not None:
            staff = (
                await db.execute(
                    select(StaffMember).where(
                        StaffMember.id == row.staff_id,
                        StaffMember.org_id == row.org_id,
                    )
                )
            ).scalar_one_or_none()

        staff_is_active = bool(staff is not None and staff.is_active)
        state = classify_token_state(row, now, staff_is_active)

        if state == "expired" and row is not None:
            # Lazy purge so a partial PII draft never outlives its link (R12.9).
            await onboarding_tokens.purge_draft_if_expired(db, row)

        if state != "valid" or row is None or staff is None:
            raise _onboarding_error(state)

        # --- 2. Set RLS org context BEFORE any write -----------------------
        # org_id comes from the trusted server-side token row, NEVER the client.
        # Bound with is_local=true so it is transaction-scoped (no leakage) and
        # keeps these writes correct under the planned FORCE-RLS cutover.
        await _set_rls_org_id(db, str(row.org_id))

        # --- 3. Collect ALL field errors (R9.1, R9.2) ----------------------
        # Org config decides whether the bank account is mandatory (R5.4).
        settings = await get_org_settings(db, org_id=row.org_id)
        org_name = settings.get("org_name") or "your employer"
        bank_account_required = bool(
            settings.get("onboarding_bank_account_required", False)
        )

        # Read uploaded documents once to obtain real sizes, then rewind so the
        # storage layer can re-read them on save. Filter out empty file parts,
        # keeping each file's aligned document_type / description (the client
        # sends parallel arrays indexed with `documents`).
        doc_entries: list[tuple[UploadFile, str, str | None]] = []
        for idx, f in enumerate(documents or []):
            if f is None or not f.filename:
                continue
            dtype_raw = document_types[idx] if idx < len(document_types) else ""
            ddesc_raw = (
                document_descriptions[idx]
                if idx < len(document_descriptions)
                else ""
            )
            dtype = (dtype_raw or "").strip()[:50] or "working_rights"
            ddesc = (ddesc_raw or "").strip()[:1000] or None
            doc_entries.append((f, dtype, ddesc))
        doc_files = [e[0] for e in doc_entries]
        doc_descriptors: list[dict] = []
        for f in doc_files:
            data = await f.read()
            await f.seek(0)
            doc_descriptors.append({"content_type": f.content_type, "size": len(data)})

        # Optional profile photo (R: staff can supply their own avatar during
        # onboarding). Read once for validation, then rewind for the store.
        photo_file = (
            profile_photo
            if profile_photo is not None and profile_photo.filename
            else None
        )
        photo_size = 0
        if photo_file is not None:
            _photo_data = await photo_file.read()
            await photo_file.seek(0)
            photo_size = len(_photo_data)

        errors: dict[str, OnboardingFieldError] = {}

        # Emergency contact — both present or both empty (R4.3).
        if not validate_emergency_contact(emergency_contact_name, emergency_contact_phone):
            errors["emergency_contact_name"] = OnboardingFieldError(
                message=(
                    "Please provide both an emergency contact name and phone "
                    "number, or leave both blank."
                ),
                code="validation_failed",
            )

        # Bank account — validated when provided; required when org-configured (R5.2, R5.4).
        bank_provided = _present(bank_account_number)
        if bank_provided:
            if not validate_nz_bank_account(bank_account_number):
                errors["bank_account_number"] = OnboardingFieldError(
                    message=(
                        "Please enter a valid NZ bank account number in the "
                        "format 12-3456-7890123-00."
                    ),
                    code="validation_failed",
                )
        elif bank_account_required:
            errors["bank_account_number"] = OnboardingFieldError(
                message="A bank account number is required to complete onboarding.",
                code="validation_failed",
            )

        # IRD number — length gate when provided (R6.2, R6.3).
        ird_provided = _present(ird_number)
        if ird_provided and not validate_ird_length(ird_number):
            errors["ird_number"] = OnboardingFieldError(
                message="Please enter a valid IRD number (8 or 9 digits).",
                code="validation_failed",
            )

        # Documents — count / MIME allow-list / size (R7.2, R7.3).
        if not validate_documents(doc_descriptors):
            errors["documents"] = OnboardingFieldError(
                message=(
                    "You can upload up to 3 documents (PDF, JPEG or PNG), each "
                    "up to 10 MB. Please adjust your files and try again."
                ),
                code="validation_failed",
            )

        # Profile photo — image MIME allow-list + 10 MB cap (optional field).
        if photo_file is not None:
            photo_ct = (photo_file.content_type or "").lower()
            if photo_ct not in {"image/jpeg", "image/png", "image/webp"} or (
                photo_size > 10 * 1024 * 1024
            ):
                errors["profile_photo"] = OnboardingFieldError(
                    message=(
                        "Your profile photo must be a JPEG, PNG or WebP image "
                        "up to 10 MB. Please choose a different photo."
                    ),
                    code="validation_failed",
                )

        # Visa expiry — visa residency types require a valid future date (R8.2,
        # R8.3). A missing/past/current-dated value is a BLOCKING error.
        if not validate_visa_expiry(residency_type, visa_expiry_date, today=now.date()):
            errors["visa_expiry_date"] = OnboardingFieldError(
                message=(
                    "Enter a valid visa expiry date in the future — work and "
                    "student visas require current working rights to complete "
                    "onboarding."
                ),
                code="visa_expiry_invalid",
            )

        if errors:
            # Pre-write rejection — nothing persisted; token stays pending (R9.1).
            return _field_error_body(errors)

        # Non-blocking advisory (R6.x): a failing IRD mod-11 checksum is a
        # warning, NOT a blocker. Surfaced on the 200 body. (A past/invalid
        # visa date is a BLOCKING error handled in the validation block above,
        # R8.3.)
        warnings: list[str] = []
        if ird_provided and not ird_mod11_ok(ird_number):
            warnings.append(
                "The IRD number you entered did not pass the standard checksum. "
                "We have saved it — please double-check it is correct."
            )

        # --- 4. Encrypt IRD / bank (R9.4, R9.7) ----------------------------
        # Performed BEFORE any write so an encryption failure leaves nothing
        # persisted (token stays pending, draft intact) — the substance of the
        # R9.7 rollback guarantee, without a partial write to undo.
        enc_ird: bytes | None = None
        enc_bank: bytes | None = None
        try:
            if ird_provided:
                enc_ird = envelope_encrypt(ird_number.strip())
            if bank_provided:
                enc_bank = envelope_encrypt(bank_account_number.strip())
        except Exception:  # noqa: BLE001 — surface as a humanized encryption error
            logger.exception(
                "onboarding submit: envelope encryption failed (org=%s staff=%s)",
                row.org_id,
                staff.id,
            )
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "message": humanize_onboarding_error("encryption_failed"),
                    "errors": {
                        "_global": {
                            "message": humanize_onboarding_error("encryption_failed"),
                            "code": "encryption_failed",
                        }
                    },
                },
            )

        # --- 5. Write provided fields into staff_members -------------------
        # Only touch columns the staff member actually supplied; never mutate
        # first_name / email (R4.2, R5.3, R6.5, R11).
        if last_name is not None:
            staff.last_name = last_name.strip() or None
        if phone is not None:
            staff.phone = phone.strip() or None
        if emergency_contact_name is not None:
            staff.emergency_contact_name = emergency_contact_name.strip() or None
        if emergency_contact_phone is not None:
            staff.emergency_contact_phone = emergency_contact_phone.strip() or None
        if tax_code is not None and tax_code.strip():
            staff.tax_code = tax_code.strip()
        if student_loan is not None:
            staff.student_loan = student_loan
        if kiwisaver_enrolled is not None:
            staff.kiwisaver_enrolled = kiwisaver_enrolled
        if kiwisaver_employee_rate is not None:
            staff.kiwisaver_employee_rate = kiwisaver_employee_rate
        if residency_type is not None and residency_type.strip():
            staff.residency_type = residency_type.strip()
        if visa_expiry_date is not None:
            staff.visa_expiry_date = visa_expiry_date
        if enc_ird is not None:
            staff.ird_number_encrypted = enc_ird
        if enc_bank is not None:
            staff.bank_account_number_encrypted = enc_bank

        await db.flush()

        # --- 5b. Store the profile photo (optional) ------------------------
        # Same compression + envelope-encryption pipeline as the authenticated
        # /staff-photos endpoint, so the resulting file_key works with every
        # existing on_file_photo_url consumer (kiosk lookup, AuthorizedAvatar).
        if photo_file is not None:
            photo_bytes = await photo_file.read()
            try:
                stored = await store_staff_photo(
                    db, str(row.org_id), photo_bytes, photo_file.filename,
                )
                staff.on_file_photo_url = stored["file_key"]
                await db.flush()
            except HTTPException as exc:
                logger.warning(
                    "onboarding submit: profile photo rejected (org=%s staff=%s): %s",
                    row.org_id,
                    staff.id,
                    exc.detail,
                )
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": (
                            "Your profile photo could not be accepted. Please "
                            "upload a JPEG, PNG or WebP image and try again."
                        ),
                        "code": "validation_failed",
                    },
                ) from exc

        # --- 6. Store working-rights documents (R7.6) ----------------------
        # Belt-and-braces: the count/allow-list was validated above; re-guard
        # the count before delegating to the shared storage helper.
        if doc_files:
            compliance = ComplianceService(db)
            for f, dtype, ddesc in doc_entries[:MAX_DOCUMENT_COUNT]:
                try:
                    await compliance.upload_document_with_file(
                        org_id=row.org_id,
                        file=f,
                        metadata={
                            "document_type": dtype,
                            "description": ddesc,
                            "staff_id": staff.id,
                        },
                    )
                except HTTPException as exc:
                    # Storage-layer rejection (e.g. magic-byte mismatch) mid-write
                    # must roll the whole submit back (R9.7) — re-raise as a
                    # humanized, stack-trace-free document error (R14.1, R14.5).
                    logger.warning(
                        "onboarding submit: document storage rejected (org=%s "
                        "staff=%s): %s",
                        row.org_id,
                        staff.id,
                        exc.detail,
                    )
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "message": (
                                "One of your documents could not be accepted. "
                                "Please upload PDF, JPEG or PNG files only and "
                                "try again."
                            ),
                            "code": "validation_failed",
                        },
                    ) from exc

        # --- 7. In-app notification for org admins (in-transaction) --------
        # create_in_app_notification never raises; it commits atomically with
        # the submit and is org-scoped via the RLS context set in step 2
        # (R16.1, R16.2, R16.4). See the coordination note above — this is the
        # ONLY place the in-app notification is created (post-commit sends only
        # emails) to avoid a duplicate row.
        first_name = (staff.first_name or staff.name or "").strip() or "A staff member"
        await create_in_app_notification(
            db,
            org_id=row.org_id,
            category="staff_onboarding",
            severity="success",
            title=f"{first_name} completed onboarding",
            body=f"{first_name} completed their onboarding",
            audience_roles=["org_admin", "branch_admin"],
            link_url=f"/staff/{staff.id}",
            entity_type="staff_member",
            entity_id=staff.id,
        )

        # --- 8. Consume the token (only on full success) -------------------
        # Sets status=consumed, consumed_at=now, and NULLs the draft columns in
        # the same write (R2.5, R9.6, R12.8). The clean return below
        # auto-commits steps 5–8 together (session.begin()).
        await onboarding_tokens.consume(db, row)

        # --- 8b. Completion audit row (R9.9) -------------------------------
        # Security-relevant action on an unauthenticated endpoint (token
        # consumed + PII written), so record it in the same transaction.
        # Org-scoped, entity=staff_member, submitter IP captured; the
        # after_value carries only a non-sensitive summary — NEVER plaintext
        # IRD/bank values.
        client_ip = request.client.host if (request and request.client) else None
        await write_audit_log(
            session=db,
            org_id=row.org_id,
            action="onboarding.completed",
            entity_type="staff_member",
            entity_id=staff.id,
            after_value={
                "documents_uploaded": len(doc_files),
                "bank_provided": bank_provided,
                "ird_provided": ird_provided,
            },
            ip_address=client_ip,
        )

        # Snapshot the values the post-write emails need before returning.
        staff_email = (staff.email or "").strip()
        staff_id = staff.id
        org_id = row.org_id

        # --- 9. Best-effort completion emails (R15, R16.3) -----------------
        # Sent AFTER all DB writes; each wrapped so a failure is logged and
        # swallowed and can NEVER roll back or block the successful submit
        # (R15.4, R16.6). Only fired here on a successful submit — never on a
        # draft save (the draft handler does not call these).
        await _dispatch_completion_emails(
            db,
            org_id=org_id,
            org_name=org_name,
            staff_email=staff_email,
            staff_first_name=first_name,
            staff_name=(f"{first_name} {(staff.last_name or '').strip()}".strip()),
            staff_id=staff_id,
        )

        return OnboardingSubmitResponse(
            ok=True,
            message="Thanks — your details have been submitted.",
            warnings=warnings or None,
        )

    except HTTPException:
        # Token-state / document / explicit rejections — let them propagate so
        # any in-flight writes roll back under session.begin().
        raise
    except Exception:  # noqa: BLE001 — handler boundary (R14.5)
        logger.exception("onboarding submit: unexpected error (token=…)")
        raise HTTPException(
            status_code=500,
            detail={
                "message": humanize_onboarding_error("server_error"),
                "code": "server_error",
            },
        )


async def _dispatch_completion_emails(
    db: AsyncSession,
    *,
    org_id,
    org_name: str,
    staff_email: str,
    staff_first_name: str,
    staff_name: str,
    staff_id,
) -> None:
    """Send the staff confirmation + org-admin completion emails (best-effort).

    Implements **option (a)** of the task-5.1 coordination note: the in-app
    notification was already created inside the submit transaction, so here we
    send ONLY the emails — the staff thank-you (R15) and one email per active
    ``org_admin`` / ``branch_admin`` recipient (R16.3) — and deliberately do
    NOT call ``notify_org_onboarding_complete`` (which would re-create the
    in-app notification). Every send is wrapped so a failure is logged and
    swallowed and never affects the already-successful submission (R15.4,
    R16.6).
    """
    # (1) Staff confirmation email (R15) — the helper is already fully wrapped
    # and never raises, but guard again for total isolation.
    try:
        await onboarding_delivery.send_onboarding_confirmation_email(
            db,
            staff_email=staff_email,
            staff_first_name=staff_first_name,
            org_name=org_name,
            org_id=org_id,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort (R15.4)
        logger.warning(
            "onboarding submit: staff confirmation email swallowed (org=%s): %s",
            org_id,
            exc,
        )

    # (2) Org-admin / branch-admin completion EMAILS only (R16.3) — assembled
    # here (recipients + compose + send) so we do not re-create the in-app row.
    try:
        recipients = await onboarding_delivery.resolve_org_notification_recipients(
            db, org_id=org_id
        )
        staff_detail_url = onboarding_delivery.build_staff_detail_url(staff_id)
        for recipient_email in recipients:
            try:
                message = onboarding_delivery.compose_org_completion_email(
                    to_email=recipient_email,
                    staff_name=staff_name,
                    org_name=org_name,
                    staff_detail_url=staff_detail_url,
                    org_id=org_id,
                )
                await onboarding_delivery.send_email(
                    db,
                    message,
                    org_sender_name=org_name,
                    dlq_task_name="onboarding_completion_email",
                )
            except Exception as exc:  # noqa: BLE001 — best-effort per recipient (R16.6)
                logger.warning(
                    "onboarding submit: org completion email swallowed "
                    "(org=%s recipient=%s): %s",
                    org_id,
                    recipient_email,
                    exc,
                )
    except Exception as exc:  # noqa: BLE001 — recipient resolution must not break submit
        logger.warning(
            "onboarding submit: org completion recipient resolution swallowed "
            "(org=%s): %s",
            org_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Public onboarding — save/update draft (R12.1, R12.5, R12.6, R12.7)
# ---------------------------------------------------------------------------
#
# ``PUT /api/v2/public/staff-onboarding/{token}/draft`` — the autosave/resume
# companion to the submit route. It re-validates the token, scopes the write
# to the trusted server-side org, and persists the *whole* partial form blob
# (envelope-encrypted) on the token row. Unlike submit it:
#
#   * runs NO submit-time field validation — only basic shape/size guards
#     (partial data is the whole point of a draft, R12.5);
#   * NEVER consumes the token — status stays ``pending`` so the link keeps
#     working for further edits and the eventual real submit (R12.7);
#   * fires NO completion side-effects — no staff confirmation email and no
#     org completion notification (in-app or email) (R15.5, R16.5).
#
# It inherits the same 30/min per-IP rate limit + HTTPS as the rest of the
# ``/api/v2/public/staff-onboarding/`` prefix (R12.10).

# Cap the serialized draft blob to a sane size so a malicious/looping client
# cannot bloat the token row. 64 KiB is comfortably larger than the legitimate
# form payload (no documents are stored in the draft — only a staged count).
_MAX_DRAFT_BYTES = 64 * 1024


@onboarding_public_router.put(
    "/{token}/draft",
    response_model=OnboardingDraftResponse,
    summary="Public onboarding save/update draft (JSON, token-gated, no auth)",
    responses={
        200: {"description": "Draft saved; completion_percentage + last_saved_at returned."},
        404: {"description": "Token does not exist."},
        410: {"description": "Token is revoked, consumed, expired, or staff inactive."},
        413: {"description": "Draft payload too large ({message, code:draft_too_large})."},
        429: {"description": "Per-IP rate limit (30 req/min) exceeded."},
    },
)
async def onboarding_save_draft(
    token: str,
    request_model: OnboardingDraftRequest,
    db: AsyncSession = Depends(get_db_session),
) -> OnboardingDraftResponse:
    """Persist a partial onboarding form as an encrypted draft (R12.1, R12.6).

    Handler order (token re-validated first, never consumed):

    1. resolve + ``classify_token_state`` — reject non-valid states with the
       humanized ``404``/``410`` ``{message, code}`` via ``_onboarding_error``;
       lazily purge any draft on the *expired* state (R12.9);
    2. ``_set_rls_org_id(db, token.org_id)`` — scope the draft write to the
       trusted server-side org BEFORE writing (the public request carries no
       ``app.current_org_id``);
    3. basic size guard only (no submit-time field validation, R12.5): serialize
       the JSON-safe payload and reject anything over ``_MAX_DRAFT_BYTES`` with a
       humanized ``413 {message, code:"draft_too_large"}``;
    4. ``save_draft`` — envelope-encrypt the whole blob onto the row and bump
       ``draft_updated_at`` (R12.6); the token is NEVER consumed — status stays
       ``pending`` (R12.7). No completion email / notification fires (R15.5,
       R16.5);
    5. return ``200 {ok, completion_percentage, last_saved_at}`` — percentage
       from ``compute_completion_percentage`` on the saved payload, ``last_saved_at``
       from the freshly bumped ``draft_updated_at``. Clean return auto-commits.
    """
    now = datetime.now(timezone.utc)

    # --- 1. Re-validate the token --------------------------------------
    row = await onboarding_tokens.resolve(db, token)

    staff: StaffMember | None = None
    if row is not None:
        staff = (
            await db.execute(
                select(StaffMember).where(
                    StaffMember.id == row.staff_id,
                    StaffMember.org_id == row.org_id,
                )
            )
        ).scalar_one_or_none()

    staff_is_active = bool(staff is not None and staff.is_active)
    state = classify_token_state(row, now, staff_is_active)

    if state == "expired" and row is not None:
        # Lazy purge so a partial PII draft never outlives its link (R12.9).
        await onboarding_tokens.purge_draft_if_expired(db, row)

    if state != "valid" or row is None or staff is None:
        raise _onboarding_error(state)

    # --- 2. Set RLS org context BEFORE the write -----------------------
    # org_id comes from the trusted server-side token row, NEVER the client, so
    # the draft write is correctly org-scoped for this unauthenticated caller.
    await _set_rls_org_id(db, str(row.org_id))

    # --- 3. Basic size guard only (NO field validation, R12.5) ---------
    # ``mode="json"`` renders date/Decimal as JSON-safe primitives; we keep
    # ``exclude_none=False`` so the persisted blob preserves which fields the
    # user explicitly cleared. save_draft re-serializes via its own _json_default,
    # so this dict is purely for the size check + the value handed to save_draft.
    payload = request_model.model_dump(mode="json", exclude_none=False)
    serialized_size = len(json.dumps(payload).encode("utf-8"))
    if serialized_size > _MAX_DRAFT_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "message": humanize_onboarding_error("draft_too_large"),
                "code": "draft_too_large",
            },
        )

    # --- 4. Persist the encrypted draft (R12.6) — never consume (R12.7) ----
    # save_draft envelope-encrypts the whole blob, bumps draft_updated_at, and
    # flushes; status/consumed_at are left untouched so the link stays pending.
    # No completion side-effects are triggered here (R15.5, R16.5).
    await onboarding_tokens.save_draft(db, row, payload)

    # --- 5. Return progress (R12.1, R13.3/R13.4) -----------------------
    completion_percentage = compute_completion_percentage(payload)
    return OnboardingDraftResponse(
        ok=True,
        completion_percentage=completion_percentage,
        last_saved_at=row.draft_updated_at,
    )
