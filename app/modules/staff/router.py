"""Staff management API router.

Endpoints:
- GET    /api/v2/staff                          — list (paginated/filterable)
- POST   /api/v2/staff                          — create
- GET    /api/v2/staff/{id}                     — get
- PUT    /api/v2/staff/{id}                     — update
- DELETE /api/v2/staff/{id}                     — deactivate
- POST   /api/v2/staff/{id}/assign-location     — assign to location
- DELETE /api/v2/staff/{id}/locations/{loc_id}  — remove from location
- GET    /api/v2/staff/utilisation              — utilisation report
- GET    /api/v2/staff/labour-costs             — labour cost report

**Validates: Requirement — Staff Module**
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.core.audit import write_audit_log
from app.core.database import get_db_session
from app.core.encryption import envelope_decrypt_str
from app.modules.admin.models import Organisation
from app.modules.compliance_docs.file_storage import ComplianceFileStorage
from app.modules.compliance_docs.service import ComplianceService
from app.modules.employee_portal import employee_portal_delivery
from app.modules.employee_portal.services import account_service
from app.modules.organisations.service import get_org_settings
from app.modules.staff.models import (
    StaffLocationAssignment,
    StaffMember,
    StaffOnboardingToken,
    StaffRosterViewToken,
)
from app.modules.staff import onboarding_tokens
from app.modules.staff.onboarding_delivery import send_onboarding_email
from app.modules.staff.onboarding_validation import (
    compute_completion_percentage,
    humanize_onboarding_error,
    onboarding_lifecycle_label,
)
from app.modules.staff.roster_delivery import (
    REASON_NO_EMAIL,
    REASON_NO_PHONE,
    REASON_NO_SHIFTS_IN_WEEK,
    REASON_OPT_OUT,
    send_roster_email,
    send_roster_sms,
)
from app.modules.staff.schemas import (
    AssignToLocationRequest,
    ComplianceSummary,
    CreateStaffAccountRequest,
    EmploymentAgreementRequest,
    LabourCostResponse,
    LocationAssignmentResponse,
    RosterEmailRequest,
    RosterSendResponse,
    RosterSmsRequest,
    IssuePortalAccessResponse,
    RevokePortalAccessResponse,
    PortalAccessStatusResponse,
    StaffListKpisResponse,
    StaffMemberCreate,
    StaffMemberListResponse,
    StaffMemberResponse,
    StaffMemberUpdate,
    StaffMetricValue,
    StaffMonthStatsResponse,
    StaffPayRateListResponse,
    StaffDocumentItem,
    StaffDocumentListResponse,
    UtilisationReportResponse,
)
from app.modules.staff.schemas import OnboardingLinkStatusResponse
from app.modules.staff.service import (
    _DEFAULT_MINIMUM_WAGE_THRESHOLD,
    DuplicateStaffError,
    MinimumWageBelowThresholdError,
    StaffService,
)
from app.modules.timesheets.pay_cycles import (
    PayCycleValidationError,
    resolve_pay_cycles_for_staff_batch,
)

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


async def _require_staff_management_module(
    request: Request, db: AsyncSession
) -> None:
    """Raise 404 ``not_enabled`` when the ``staff_management`` module is
    disabled for the requesting org.

    This is a finer-grained gate than the path-prefix ``staff`` module
    middleware (which returns 403 — see ``app/middleware/modules.py``).
    Phase 1 sub-feature endpoints use 404 so the legacy view degrades
    gracefully: the frontend pre-checks the module flag and renders
    ``LegacyStaffDetail`` when disabled, so users never see a 404 in
    the UI.

    The legacy list endpoint (``GET /staff``) deliberately does NOT
    call this helper — the list stays accessible when the new module
    is disabled; only the new fields (e.g. ``compliance_summary``) are
    stripped from the response.

    **Validates: Requirement R11.5** (Phase 1 task C1).
    """
    from app.core.modules import ModuleService

    org_id = _get_org_id(request)
    service = ModuleService(db)
    if not await service.is_enabled(str(org_id), "staff_management"):
        raise HTTPException(
            status_code=404,
            detail={"detail": "not_enabled", "module": "staff_management"},
        )


async def _enrich_reporting_to(db: AsyncSession, staff: StaffMember) -> dict:
    """Build response dict with reporting_to_name + decrypted PII fields.

    The ORM model stores ``ird_number_encrypted`` and
    ``bank_account_number_encrypted`` as ``LargeBinary`` ciphertext —
    not plain attributes named ``ird_number`` / ``bank_account_number``.
    ``StaffMemberResponse.model_validate(staff)`` therefore reads
    ``None`` for both fields by default, which is why org users saw
    blank rows even though plaintext had been entered and encrypted
    correctly on save.

    Here we decrypt the ciphertext (best-effort — a missing encryption
    key or corrupt envelope yields ``None`` rather than raising) and
    inject the plaintext into the response dict. The values are returned
    in FULL (unmasked): they are operationally required on the staff
    details page, and this endpoint is restricted to staff-management
    roles. The values remain envelope-encrypted at rest.
    """
    data = StaffMemberResponse.model_validate(staff).model_dump()

    # IRD + bank — decrypt the ciphertext columns so the masked
    # display value is non-empty when a value exists.
    ird_ct = getattr(staff, "ird_number_encrypted", None)
    if ird_ct:
        try:
            data["ird_number"] = envelope_decrypt_str(ird_ct)
        except Exception:  # noqa: BLE001 - best-effort PII decryption
            data["ird_number"] = None
    bank_ct = getattr(staff, "bank_account_number_encrypted", None)
    if bank_ct:
        try:
            data["bank_account_number"] = envelope_decrypt_str(bank_ct)
        except Exception:  # noqa: BLE001 - best-effort PII decryption
            data["bank_account_number"] = None

    # Re-inject the decrypted plaintext so the staff details page shows the
    # FULL IRD + bank account (operationally required; this endpoint is
    # RBAC-gated to staff-management roles). The values remain
    # envelope-encrypted at rest — only this trusted serialisation path
    # decrypts them.

    if staff.reporting_to:
        result = await db.execute(
            select(StaffMember.first_name, StaffMember.last_name)
            .where(StaffMember.id == staff.reporting_to)
        )
        row = result.first()
        if row:
            data["reporting_to_name"] = f"{row[0] or ''} {row[1] or ''}".strip()

    # Resolved pay cycle (per-staff-pay-cycle feature, REQ 5.1-5.3). A
    # one-element batch keeps a single resolution path shared with the list
    # endpoint. All three fields stay None/False when the staff member has no
    # resolved cycle (no match and no default — REQ 5.3).
    resolved_map = await resolve_pay_cycles_for_staff_batch(
        db, org_id=staff.org_id, staff_members=[staff],
    )
    resolved = resolved_map.get(staff.id)
    if resolved is not None:
        data["pay_cycle_id"] = resolved.cycle.id
        data["pay_cycle_name"] = resolved.cycle.name
        data["pay_cycle_is_default"] = resolved.is_default
    else:
        data["pay_cycle_id"] = None
        data["pay_cycle_name"] = None
        data["pay_cycle_is_default"] = False

    return data


async def _revoke_active_roster_tokens(
    db: AsyncSession,
    *,
    org_id: UUID,
    staff_id: UUID,
    user_id: UUID | None,
    ip_address: str | None = None,
) -> int:
    """Revoke any non-expired roster viewer tokens for ``staff_id``.

    Sets ``expires_at = now()`` on every active row in
    ``staff_roster_view_tokens`` for the (org, staff) pair so the
    public viewer endpoint surfaces 410 ``token_expired_staff_deactivated``
    on the next request (per the discriminator in
    ``app/modules/staff/public_router.py``).

    Designed to be called inside the same DB transaction as the staff
    state change that triggered the revocation (deactivation, or
    ``employment_end_date`` being set for the first time). The caller
    is expected to have already mutated the staff row; this helper
    only touches the tokens table + audit_log.

    Returns the number of tokens revoked. Writes a single ``audit_log``
    row with ``action='roster.tokens_revoked'`` when at least one
    token was revoked — staff who never had a roster sent generate
    no audit noise.

    **Validates: Requirement R9.7, gap-closure tag G4** (Phase 1 task C11).
    """
    result = await db.execute(
        sa_update(StaffRosterViewToken)
        .where(
            StaffRosterViewToken.staff_id == staff_id,
            StaffRosterViewToken.org_id == org_id,
            StaffRosterViewToken.expires_at > func.now(),
        )
        .values(expires_at=func.now())
        .returning(StaffRosterViewToken.id)
    )
    revoked_rows = result.fetchall()
    revoked_count = len(revoked_rows)
    if revoked_count > 0:
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="roster.tokens_revoked",
            entity_type="staff_member",
            entity_id=staff_id,
            after_value={"tokens_revoked_count": revoked_count},
            ip_address=ip_address,
        )
    return revoked_count


async def _revoke_active_onboarding_tokens(
    db: AsyncSession,
    *,
    org_id: UUID,
    staff_id: UUID,
    user_id: UUID | None,
    ip_address: str | None = None,
) -> int:
    """Revoke any active onboarding tokens for ``staff_id`` (R10.4).

    Delegates to ``onboarding_tokens.revoke_active`` which bulk-sets
    ``status='revoked'`` and NULLs both draft columns
    (``draft_data_encrypted`` / ``draft_updated_at``) in the same UPDATE,
    purging any in-flight draft on auto-revoke (R12.9).

    Designed to run inside the same DB transaction as the staff state
    change that triggered the revocation (deactivation, or
    ``employment_end_date`` being set for the first time) so a failure in
    either step rolls both back. Writes a single ``audit_log`` row with
    ``action='onboarding.tokens_revoked'`` only when at least one token
    was actually revoked — staff who never had an onboarding link sent
    generate no audit noise.

    Returns the number of tokens revoked.

    **Validates: Requirements 10.4, 12.9.**
    """
    revoked_count = await onboarding_tokens.revoke_active(
        db, org_id=org_id, staff_id=staff_id
    )
    if revoked_count > 0:
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="onboarding.tokens_revoked",
            entity_type="staff_member",
            entity_id=staff_id,
            after_value={"tokens_revoked_count": revoked_count},
            ip_address=ip_address,
        )
    return revoked_count


@router.get("/check-duplicate")
async def check_staff_duplicate(
    request: Request,
    field: str = Query(..., pattern="^(email|phone|employee_id)$"),
    value: str = Query(..., min_length=1),
    exclude_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    """Check if a staff field value is already in use (real-time validation)."""
    org_id = _get_org_id(request)
    col = getattr(StaffMember, field)
    stmt = select(StaffMember.id).where(
        StaffMember.org_id == org_id,
        col == value.strip(),
        StaffMember.is_active.is_(True),
    )
    if exclude_id:
        stmt = stmt.where(StaffMember.id != exclude_id)
    result = await db.execute(stmt.limit(1))
    exists = result.scalar_one_or_none() is not None
    label = field.replace("_", " ").title()
    return {"duplicate": exists, "message": f"{label} already in use" if exists else ""}




# ---------------------------------------------------------------------------
# Reports (must be before /{staff_id} to avoid path conflict)
# ---------------------------------------------------------------------------

@router.get("/utilisation", response_model=UtilisationReportResponse, summary="Staff utilisation report")
async def utilisation_report(
    request: Request,
    date_from: date = Query(...),
    date_to: date = Query(...),
    staff_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    data = await svc.calculate_utilisation(org_id, date_from, date_to, staff_id=staff_id)
    return UtilisationReportResponse(
        staff=data, date_from=date_from.isoformat(), date_to=date_to.isoformat(),
    )


@router.get("/labour-costs", response_model=LabourCostResponse, summary="Labour cost report")
async def labour_cost_report(
    request: Request,
    date_from: date = Query(...),
    date_to: date = Query(...),
    staff_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    data = await svc.get_labour_costs(org_id, date_from, date_to, staff_id=staff_id)
    return LabourCostResponse(**data)


@router.get(
    "/kpis",
    response_model=StaffListKpisResponse,
    summary="Org-wide staff list KPIs",
)
async def get_list_kpis(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> StaffListKpisResponse:
    """Return the org-wide staff list KPIs surfaced on the Staff list page.

    Module-gated (404 ``not_enabled`` when ``staff_management`` is off for the
    org). Maps the ``StaffListKpis`` service dataclass onto the response model.

    Declared here — among the static-suffix routes — so it is registered
    BEFORE the dynamic ``/{staff_id}`` handler. Otherwise FastAPI would parse
    the literal ``kpis`` segment as a ``staff_id`` UUID path param and 422.

    **Validates: Requirements 1.6, 14.5.**
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    svc = StaffService(db)
    kpis = await svc.get_list_kpis(org_id)
    return StaffListKpisResponse(
        total_staff=kpis.total_staff,
        employee_count=kpis.employee_count,
        with_login_count=kpis.with_login_count,
        avg_hourly_rate=kpis.avg_hourly_rate,
    )


@router.get(
    "/{staff_id}/stats",
    response_model=StaffMonthStatsResponse,
    summary="Staff month stats (this month metrics + last sign-in)",
)
async def get_staff_stats(
    staff_id: UUID,
    request: Request,
    period: str = Query("this_month", pattern="^this_month$"),
    db: AsyncSession = Depends(get_db_session),
) -> StaffMonthStatsResponse:
    """Return the "this month" metrics + last sign-in for one staff member.

    Module-gated (404 ``not_enabled`` when ``staff_management`` is off) and
    access-controlled per R13:

    - ``org_admin`` / ``salesperson`` — any staff member in the org.
    - ``branch_admin`` — only staff whose ``staff_location_assignments``
      intersect the admin's ``request.state.branch_ids`` (else 403).
    - ``staff_member`` — only their own record where
      ``staff.user_id == request.state.user_id`` (else 403).

    A target in another org surfaces as 404 (``get_staff`` filters by
    ``org_id``). The path-based RBAC middleware already admits all four
    roles to this GET; the self-scope / branch-scope check below is the
    authoritative data gate (do NOT rely on ``rbac.py`` prefix lists).

    **Validates: Requirements 11.1, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 14.5.**
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    role = str(getattr(request.state, "role", "") or "")
    user_id = getattr(request.state, "user_id", None)

    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        # Covers both a genuinely missing record and a record belonging
        # to another org (R13.6 — get_staff filters by org_id).
        raise HTTPException(status_code=404, detail="Staff member not found")

    # ------------------------------------------------------------------
    # RBAC / self-scope access-control matrix (R13.2–R13.5)
    # ------------------------------------------------------------------
    if role in ("org_admin", "global_admin", "salesperson"):
        # Any staff member in the requester's org (R13.2).
        pass
    elif role == "branch_admin":
        # Allowed only when the target staff member is assigned to a
        # location in the admin's branch scope (R13.3).
        branch_ids_raw = getattr(request.state, "branch_ids", None) or []
        branch_uuids: list[UUID] = []
        for raw in branch_ids_raw:
            try:
                branch_uuids.append(UUID(str(raw)))
            except (ValueError, TypeError):
                continue
        in_scope = False
        if branch_uuids:
            scoped = (
                await db.execute(
                    select(StaffLocationAssignment.id)
                    .where(
                        StaffLocationAssignment.staff_id == staff_id,
                        StaffLocationAssignment.location_id.in_(branch_uuids),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            in_scope = scoped is not None
        if not in_scope:
            raise HTTPException(
                status_code=403,
                detail="Staff member is outside your branch scope",
            )
    elif role == "staff_member":
        # Self-scope: only the requester's own staff record (R13.4, R13.5).
        requester_user_id = None
        if user_id is not None:
            try:
                requester_user_id = UUID(str(user_id))
            except (ValueError, TypeError):
                requester_user_id = None
        if staff.user_id is None or staff.user_id != requester_user_id:
            raise HTTPException(
                status_code=403,
                detail="You may only view your own staff stats",
            )
    else:
        # Any other role has no scope to staff stats.
        raise HTTPException(
            status_code=403,
            detail="You are not permitted to view staff stats",
        )

    stats = await svc.get_staff_month_stats(org_id, staff_id)

    return StaffMonthStatsResponse(
        staff_id=staff_id,
        period="this_month",
        hours_logged=StaffMetricValue(
            value=stats.hours_logged,
            has_data=stats.hours_logged_has_data,
        ),
        jobs_completed=StaffMetricValue(
            value=Decimal(stats.jobs_completed),
            has_data=stats.jobs_completed_has_data,
        ),
        billable_ratio=StaffMetricValue(
            value=Decimal(stats.billable_ratio),
            has_data=stats.billable_ratio_has_data,
        ),
        on_time_rate=StaffMetricValue(
            value=Decimal(stats.on_time_rate),
            has_data=stats.on_time_rate_has_data,
        ),
        last_sign_in=stats.last_sign_in,
        user_role=stats.user_role,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=StaffMemberListResponse, summary="List staff members")
async def list_staff(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    role_type: str | None = Query(None),
    is_active: bool | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff_list, total = await svc.list_staff(
        org_id, page=page, page_size=page_size,
        role_type=role_type, is_active=is_active,
    )
    # Resolve reporting_to names in bulk
    manager_ids = {s.reporting_to for s in staff_list if s.reporting_to}
    manager_names: dict[UUID, str] = {}
    if manager_ids:
        result = await db.execute(
            select(StaffMember.id, StaffMember.first_name, StaffMember.last_name)
            .where(StaffMember.id.in_(manager_ids))
        )
        for row in result:
            manager_names[row[0]] = f"{row[1] or ''} {row[2] or ''}".strip()

    resp_staff = []
    # Resolve the whole page's pay cycles in one batch (no N+1) — REQ 5.1-5.3.
    pay_cycle_map = await resolve_pay_cycles_for_staff_batch(
        db, org_id=org_id, staff_members=staff_list,
    )
    for s in staff_list:
        data = StaffMemberResponse.model_validate(s).model_dump()
        if s.reporting_to and s.reporting_to in manager_names:
            data["reporting_to_name"] = manager_names[s.reporting_to]
        # Resolved pay cycle for this staff member (from the batch above).
        resolved = pay_cycle_map.get(s.id)
        if resolved is not None:
            data["pay_cycle_id"] = resolved.cycle.id
            data["pay_cycle_name"] = resolved.cycle.name
            data["pay_cycle_is_default"] = resolved.is_default
        else:
            data["pay_cycle_id"] = None
            data["pay_cycle_name"] = None
            data["pay_cycle_is_default"] = False
        # Decrypt PII fields so the FULL IRD + bank account show in the
        # list (operationally required; same RBAC-gated access as the
        # details page). Best-effort: a missing key or corrupt envelope
        # leaves the field as None.
        ird_ct = getattr(s, "ird_number_encrypted", None)
        if ird_ct:
            try:
                data["ird_number"] = envelope_decrypt_str(ird_ct)
            except Exception:  # noqa: BLE001
                data["ird_number"] = None
        bank_ct = getattr(s, "bank_account_number_encrypted", None)
        if bank_ct:
            try:
                data["bank_account_number"] = envelope_decrypt_str(bank_ct)
            except Exception:  # noqa: BLE001
                data["bank_account_number"] = None
        resp_staff.append(StaffMemberResponse(**data))

    # Compliance counters (R6, G1, G2, G3 — Phase 1 task C9). Resolved
    # from the org-settings cache so the threshold reflects whatever
    # was set via the Settings UI; defaults to 23.15 NZD when the key
    # is missing or the cache lookup fails.
    threshold = _DEFAULT_MINIMUM_WAGE_THRESHOLD
    try:
        settings = await get_org_settings(db, org_id=org_id)
        raw_threshold = settings.get("minimum_wage_threshold_nzd")
        if raw_threshold is not None:
            try:
                threshold = Decimal(str(raw_threshold))
            except Exception:
                threshold = _DEFAULT_MINIMUM_WAGE_THRESHOLD
    except Exception:
        # Settings lookup is best-effort; the default keeps the
        # counter accurate for orgs that never customised the value.
        threshold = _DEFAULT_MINIMUM_WAGE_THRESHOLD
    summary_dict = await svc.get_compliance_summary(org_id, threshold)
    compliance_summary = ComplianceSummary(**summary_dict)

    return StaffMemberListResponse(
        staff=resp_staff,
        total=total,
        page=page,
        page_size=page_size,
        compliance_summary=compliance_summary,
    )


@router.post("", response_model=StaffMemberResponse, status_code=201, summary="Create staff member")
async def create_staff(
    payload: StaffMemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    svc = StaffService(db)
    try:
        staff = await svc.create_staff(org_id, payload, changed_by=user_id)
    except MinimumWageBelowThresholdError as exc:
        # R4 / C10 — surface the explicit detail body the frontend
        # dispatcher matches on so it can render the override modal.
        raise HTTPException(
            status_code=422,
            detail={
                "detail": "minimum_wage_below_threshold",
                "threshold": float(exc.threshold),
            },
        )
    except PayCycleValidationError as exc:
        # per-staff-pay-cycle REQ 2.4, 2.5 — wrong-org or inactive cycle id.
        # The service raised before returning, so get_db_session rolled the
        # staff insert back: nothing was created.
        raise HTTPException(status_code=422, detail={"detail": exc.code})
    except DuplicateStaffError as exc:
        # R1.5 — duplicate active staff member in this org. Surface the
        # humanized {message, code} contract so the client can map the
        # machine code (e.g. "duplicate_email") to inline field feedback.
        raise HTTPException(
            status_code=409,
            detail={"message": exc.message, "code": exc.code},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.flush()
    await db.refresh(staff)

    # R4 / C10 — when the request supplied an explicit override AND the
    # rate landed below the org's threshold, record the override in
    # ``audit_log`` so the org admin who waved it through is on the
    # paper trail. Resolve the threshold the service already used so
    # the audit row reflects the same comparison value.
    if (
        payload.minimum_wage_override
        and payload.hourly_rate is not None
    ):
        threshold = await svc._resolve_minimum_wage_threshold(org_id)
        if payload.hourly_rate < threshold:
            await write_audit_log(
                session=db,
                org_id=org_id,
                user_id=user_id,
                action="staff.minimum_wage_override",
                entity_type="staff_member",
                entity_id=staff.id,
                after_value={
                    "hourly_rate": str(payload.hourly_rate),
                    "threshold": str(threshold),
                },
                ip_address=ip_address,
            )

    enriched = await _enrich_reporting_to(db, staff)

    # R1.3 / R3 — when the admin opted to send an onboarding link, mint a
    # single-use token now (in the same transaction as the staff insert, so
    # staff + token commit atomically on a clean return — R3.7) and then
    # dispatch the invite email. The token mint happens BEFORE the fallible
    # email side-effect; the email send NEVER raises (it returns a result
    # object), so a provider failure folds into the advisory response fields
    # and the created staff record is preserved (R3.6).
    #
    # ``send_onboarding_link`` is fully independent of the frontend-only
    # 'Also create as a user' invite (which is a separate
    # ``POST /api/v2/org/users/invite`` call from StaffList.tsx, not a field
    # on this schema) — both may be active for the same create with no special
    # backend handling here (R1.5).
    if payload.send_onboarding_link:
        # R1.2 belt-and-braces — an onboarding link is useless without a
        # destination address. Block before minting so we never create a
        # dangling token that can never be delivered.
        if not staff.email or not staff.email.strip():
            raise HTTPException(
                status_code=422,
                detail={"detail": "onboarding_email_required"},
            )

        token_raw = await onboarding_tokens.mint(
            db,
            org_id=org_id,
            staff_id=staff.id,
        )

        # Prefer the request Origin so the emailed link points at the same
        # domain the admin is on; the delivery helper falls back to
        # ``settings.frontend_base_url`` then localhost.
        base_url = request.headers.get("origin")

        delivery = await send_onboarding_email(
            db,
            org_id=org_id,
            staff=staff,
            token=token_raw,
            base_url=base_url,
        )

        enriched["onboarding_email_sent"] = delivery.ok
        enriched["onboarding_email_error"] = delivery.error_code

        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="onboarding.link_sent",
            entity_type="staff_member",
            entity_id=staff.id,
            after_value={
                "onboarding_email_sent": delivery.ok,
                "onboarding_email_error": delivery.error_code,
            },
            ip_address=ip_address,
        )

    return StaffMemberResponse(**enriched)


@router.get("/{staff_id}", response_model=StaffMemberResponse, summary="Get staff member")
async def get_staff(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    enriched = await _enrich_reporting_to(db, staff)
    return StaffMemberResponse(**enriched)


@router.put("/{staff_id}", response_model=StaffMemberResponse, summary="Update staff member")
async def update_staff(
    staff_id: UUID,
    payload: StaffMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    svc = StaffService(db)

    # G4 / R9.7 — capture the prior employment_end_date BEFORE the
    # service mutates the staff row so we can detect a
    # None → set transition (the "termination" flow that should
    # revoke any active roster viewer tokens). ``model_dump`` with
    # ``exclude_unset=True`` lets us distinguish "field omitted" from
    # "explicitly set to None"; only the former should NOT trigger
    # revocation.
    payload_fields = payload.model_dump(exclude_unset=True)
    is_termination_event = False
    if "employment_end_date" in payload_fields:
        new_end_date = payload_fields["employment_end_date"]
        if new_end_date is not None:
            prior = await svc.get_staff(org_id, staff_id)
            if prior is not None and prior.employment_end_date is None:
                is_termination_event = True

    try:
        staff = await svc.update_staff(
            org_id, staff_id, payload, changed_by=user_id,
        )
    except MinimumWageBelowThresholdError as exc:
        # R4 / C10 — same envelope as the create path so the frontend
        # can reuse the override-modal dispatcher.
        raise HTTPException(
            status_code=422,
            detail={
                "detail": "minimum_wage_below_threshold",
                "threshold": float(exc.threshold),
            },
        )
    except PayCycleValidationError as exc:
        # per-staff-pay-cycle REQ 2.4, 2.5 — wrong-org or inactive cycle id.
        # The service raised before returning, so the staff update is rolled
        # back: the staff member is left unchanged and no assignment persists.
        raise HTTPException(status_code=422, detail={"detail": exc.code})
    except DuplicateStaffError as exc:
        # R1.5 — duplicate active staff member in this org. Same humanized
        # {message, code} envelope as the create path; the existing staff
        # member is left unchanged (no mutation has been flushed yet).
        raise HTTPException(
            status_code=409,
            detail={"message": exc.message, "code": exc.code},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    await db.flush()
    await db.refresh(staff)

    # G4 / R9.7 — termination flow runs the token-revocation SQL in the
    # same transaction as the staff update. Reactivation (``POST
    # /staff/:id/activate``) does NOT un-revoke; the staff has to
    # receive a fresh roster send to get a new viewer link.
    if is_termination_event:
        await _revoke_active_roster_tokens(
            db,
            org_id=org_id,
            staff_id=staff_id,
            user_id=user_id,
            ip_address=ip_address,
        )
        await _revoke_active_onboarding_tokens(
            db,
            org_id=org_id,
            staff_id=staff_id,
            user_id=user_id,
            ip_address=ip_address,
        )
        # R5.11 — auto-revoke Employee Portal access on termination. Runs in
        # the same transaction as the staff mutation (the employment_end_date
        # set above) so the portal-user deactivation + session tear-down
        # commit or roll back atomically with it. Mirrors the roster/onboarding
        # token revocation wired immediately above.
        await account_service.revoke_portal_access_for_staff(
            db,
            org_id,
            staff_id,
            actor_user_id=user_id,
            ip_address=ip_address,
        )

    # R4 / C10 — the override flag is only meaningful when ``hourly_rate``
    # is actually being changed AND lands below the threshold. ``payload``
    # uses ``model_dump(exclude_unset=True)`` semantics (an unset field
    # is None on the schema), so we check ``payload.hourly_rate`` for
    # presence first.
    if (
        payload.minimum_wage_override
        and payload.hourly_rate is not None
    ):
        threshold = await svc._resolve_minimum_wage_threshold(org_id)
        if payload.hourly_rate < threshold:
            await write_audit_log(
                session=db,
                org_id=org_id,
                user_id=user_id,
                action="staff.minimum_wage_override",
                entity_type="staff_member",
                entity_id=staff.id,
                after_value={
                    "hourly_rate": str(payload.hourly_rate),
                    "threshold": str(threshold),
                },
                ip_address=ip_address,
            )

    enriched = await _enrich_reporting_to(db, staff)
    return StaffMemberResponse(**enriched)


@router.delete("/{staff_id}", status_code=200, summary="Deactivate staff member")
async def deactivate_staff(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    staff.is_active = False
    await db.flush()
    # G4 / R9.7 — revoking active roster viewer tokens runs in the
    # same DB transaction as the deactivation flag flip so a failure
    # in either step rolls both back. The audit row is only written
    # when at least one token was actually revoked (avoids audit-log
    # noise for staff who never had a roster sent).
    await _revoke_active_roster_tokens(
        db,
        org_id=org_id,
        staff_id=staff_id,
        user_id=user_id,
        ip_address=ip_address,
    )
    await _revoke_active_onboarding_tokens(
        db,
        org_id=org_id,
        staff_id=staff_id,
        user_id=user_id,
        ip_address=ip_address,
    )
    # R5.11 — auto-revoke Employee Portal access on staff deactivation. Runs in
    # the same DB transaction as the ``is_active = False`` flip above so the
    # portal-user deactivation + session deletions commit or roll back
    # atomically. Mirrors the roster/onboarding token auto-revoke.
    await account_service.revoke_portal_access_for_staff(
        db,
        org_id,
        staff_id,
        actor_user_id=user_id,
        ip_address=ip_address,
    )
    return {"message": "Staff member deactivated", "id": str(staff_id)}


@router.get(
    "/{staff_id}/portal-access",
    response_model=PortalAccessStatusResponse,
    summary="Get a staff member's Employee Portal access status",
)
async def get_portal_access_status(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PortalAccessStatusResponse:
    """Report whether the staff member currently holds Employee Portal access.

    ``state`` is ``none`` (no active portal user), ``invited`` (issued but the
    invite hasn't been accepted), or ``active`` (password set / can log in).
    """
    from app.modules.employee_portal.models import EmployeePortalUser

    org_id_raw = getattr(request.state, "org_id", None)
    if not org_id_raw:
        raise HTTPException(status_code=403, detail="Organisation context required")
    org_id = UUID(str(org_id_raw))

    row = (
        await db.execute(
            select(EmployeePortalUser)
            .where(
                EmployeePortalUser.org_id == org_id,
                EmployeePortalUser.staff_id == staff_id,
                EmployeePortalUser.is_active.is_(True),
            )
            .order_by(EmployeePortalUser.created_at.desc())
        )
    ).scalars().first()

    if row is None:
        return PortalAccessStatusResponse(state="none")

    accepted = row.invite_accepted_at is not None or row.password_hash is not None
    return PortalAccessStatusResponse(
        state="active" if accepted else "invited",
        email=row.email,
        invite_sent_at=row.invite_sent_at,
        invite_accepted_at=row.invite_accepted_at,
        last_login_at=row.last_login_at,
    )


@router.post(
    "/{staff_id}/portal-access",
    response_model=IssuePortalAccessResponse,
    status_code=201,
    summary="Issue Employee Portal access for a staff member",
)
async def issue_portal_access(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> IssuePortalAccessResponse:
    """Provision Employee Portal credentials for a staff member (R5.3, R5.5, R5.7, R5.8).

    Flow (mirrors the onboarding-link create path):
      1. Module-gated (404 ``not_enabled`` when ``staff_management`` is off) and
         org-scoped — the staff record is loaded via ``svc.get_staff`` so a
         record in another org surfaces as 404.
      2. Require ``staff.email`` — 422 ``email_required`` otherwise (R15.6).
      3. ``account_service.issue_access`` runs the app-level dup check
         (409 ``duplicate``, R5.7) and INSERTs the Portal_User with a hashed,
         single-use invite token, returning the raw token exactly once.
      4. **After** the row is flushed, build the branded
         ``/e/{slug}/accept-invite/{token}`` set-password URL and dispatch
         ``send_credential_setup_email``; the result is folded into
         ``{invite_sent, invite_error}``. The email helper never raises, so a
         provider failure still returns ``201`` with the Portal_User preserved
         (R15.3).
      5. Write a ``staff.portal_access_issued`` audit row.

    **Validates: Requirements 5.3, 5.5, 5.7, 5.8, 15.1, 15.3, 15.6.**
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    svc = StaffService(db)

    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    # R15.6 — a credential-setup invite is useless without a destination
    # address. Gate before issuing so we never create a Portal_User that can
    # never receive its set-password link.
    if not staff.email or not staff.email.strip():
        raise HTTPException(
            status_code=422,
            detail={"detail": "email_required", "code": "email_required"},
        )

    try:
        portal_user, raw_token = await account_service.issue_access(
            db,
            org_id,
            staff,
            actor_user_id=user_id,
            ip_address=ip_address,
        )
    except account_service.EmailRequired as exc:
        # Belt-and-braces — the service re-checks the email too (R15.6).
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.message, "code": exc.code},
        )
    except account_service.DuplicatePortalUser as exc:
        # R5.7 — an active Portal_User already holds this email; leave it
        # unchanged and surface the humanized {message, code} envelope.
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.message, "code": exc.code},
        )

    # Resolve the org slug + display name so the emailed link is branded
    # (``/e/{slug}/accept-invite/{token}``) and the copy names the org.
    org_row = (
        await db.execute(
            select(Organisation.slug, Organisation.name).where(
                Organisation.id == org_id
            )
        )
    ).first()
    org_slug = (org_row[0] if org_row else None) or ""
    org_name = (org_row[1] if org_row else None) or "Your organisation"

    # Prefer the request Origin so the link points at the domain the admin is
    # on; fall back to the configured frontend base url, then localhost — the
    # same precedence the onboarding/portal email links use.
    base = (
        request.headers.get("origin")
        or app_settings.frontend_base_url
        or "http://localhost"
    ).rstrip("/")
    set_password_url = f"{base}/e/{org_slug}/accept-invite/{raw_token}"

    # AFTER the credential row is flushed: dispatch the credential-setup email
    # and fold the result into the advisory response fields. The helper never
    # raises on a provider failure (R15.3), so the created Portal_User is
    # preserved and the endpoint still returns 201.
    delivery = await employee_portal_delivery.send_credential_setup_email(
        db,
        staff_email=staff.email,
        org_name=org_name,
        set_password_url=set_password_url,
        org_id=org_id,
    )

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="staff.portal_access_issued",
        entity_type="staff_member",
        entity_id=staff_id,
        after_value={
            "portal_user_id": str(portal_user.id),
            "invite_sent": delivery.ok,
            "invite_error": delivery.error_code,
        },
        ip_address=ip_address,
    )

    return IssuePortalAccessResponse(
        portal_user_id=portal_user.id,
        email=portal_user.email,
        invite_sent=delivery.ok,
        invite_error=delivery.error_code,
    )


@router.delete(
    "/{staff_id}/portal-access",
    response_model=RevokePortalAccessResponse,
    status_code=200,
    summary="Revoke Employee Portal access for a staff member",
)
async def revoke_portal_access(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> RevokePortalAccessResponse:
    """Revoke Employee Portal access for a staff member (R5.10).

    Module-gated, org-scoped, audit-logged. Delegates to
    ``account_service.revoke_access`` which deactivates every active
    Portal_User for the staff member and deletes their sessions in the same
    transaction, so no prior session survives the revoke. The ``access_revoked``
    audit row is written inside the service against ``employee_portal_audit_log``;
    a mirror ``staff.portal_access_revoked`` row is written here.

    **Validates: Requirement 5.10.**
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    svc = StaffService(db)

    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    sessions_invalidated = await account_service.revoke_access(
        db,
        org_id,
        staff_id,
        actor_user_id=user_id,
        ip_address=ip_address,
    )

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="staff.portal_access_revoked",
        entity_type="staff_member",
        entity_id=staff_id,
        after_value={"sessions_invalidated": sessions_invalidated},
        ip_address=ip_address,
    )

    return RevokePortalAccessResponse(
        revoked=True,
        sessions_invalidated=sessions_invalidated,
    )


@router.get("/{staff_id}/deletion-check", status_code=200, summary="Check whether a staff member can be permanently deleted")
async def staff_deletion_check(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Preflight for a permanent delete.

    Returns ``{can_delete, blockers: [{label, count}]}`` so the UI can show
    exactly what (and how many) records prevent a hard delete and steer the
    admin to deactivate instead. Records like payslips/timesheets are retained
    by design (financial/legal history).
    """
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    blockers = await svc.deletion_blockers(staff_id)
    return {"can_delete": len(blockers) == 0, "blockers": blockers}


@router.delete("/{staff_id}/permanent", status_code=200, summary="Permanently delete staff member")
async def delete_staff_permanent(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete a staff member record.

    Refuses (409) with a clear, structured message naming the dependent records
    (payroll, timesheets, leave, etc.) when any exist — those are retained by
    design and the staff member should be deactivated instead.
    """
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    blockers = await svc.deletion_blockers(staff_id)
    if blockers:
        summary = ", ".join(f"{b['count']} {b['label'].lower()}" for b in blockers)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "staff_has_dependents",
                "message": (
                    f"{staff.first_name or 'This staff member'} can't be permanently "
                    f"deleted because they still have {summary}. These records are "
                    f"kept for your history — deactivate the staff member instead."
                ),
                "blockers": blockers,
            },
        )

    await db.delete(staff)
    await db.flush()
    return {"message": "Staff member permanently deleted", "id": str(staff_id)}


@router.post("/{staff_id}/activate", response_model=StaffMemberResponse, summary="Reactivate staff member")
async def activate_staff(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if staff.is_active:
        raise HTTPException(status_code=400, detail="Staff member is already active")
    staff.is_active = True
    await db.flush()
    await db.refresh(staff)
    enriched = await _enrich_reporting_to(db, staff)
    return StaffMemberResponse(**enriched)


@router.post("/{staff_id}/create-account", summary="Create org user account for staff member")
async def create_staff_account(
    staff_id: UUID,
    payload: CreateStaffAccountRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a user account (org_admin) linked to this staff member.

    Requires the staff member to have an email address and not already
    have a linked user account.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if staff.user_id is not None:
        raise HTTPException(status_code=400, detail="Staff member already has a user account")
    if not staff.email:
        raise HTTPException(status_code=400, detail="Staff member must have an email address to create an account")

    # Check email not already taken
    from app.modules.auth.models import User
    existing = (await db.execute(
        select(User).where(User.email == staff.email)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="A user with this email already exists")

    # Create user with password (bcrypt off the event loop)
    from app.modules.auth.password import hash_password
    new_user = User(
        org_id=org_id,
        email=staff.email,
        password_hash=await hash_password(payload.password),
        role="org_admin",
        is_active=True,
        is_email_verified=True,
    )
    db.add(new_user)
    await db.flush()

    # Link staff member to user
    staff.user_id = new_user.id
    await db.flush()
    await db.refresh(staff)

    enriched = await _enrich_reporting_to(db, staff)
    return {
        "message": "User account created successfully",
        "user_id": str(new_user.id),
        "email": new_user.email,
        "staff": StaffMemberResponse(**enriched),
    }


# ---------------------------------------------------------------------------
# Onboarding link management (R10)
# ---------------------------------------------------------------------------


async def _get_latest_onboarding_token(
    db: AsyncSession,
    *,
    org_id: UUID,
    staff_id: UUID,
) -> StaffOnboardingToken | None:
    """Return the most-recently-created onboarding token row for a staff member.

    Org-scoped (RLS plus the explicit ``org_id`` filter) and ordered by
    ``created_at DESC`` so the admin status / lifecycle reflects the live
    link, not a superseded one. Returns ``None`` when the staff member has
    never had an onboarding link minted.
    """
    result = await db.execute(
        select(StaffOnboardingToken)
        .where(
            StaffOnboardingToken.org_id == org_id,
            StaffOnboardingToken.staff_id == staff_id,
        )
        .order_by(StaffOnboardingToken.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get(
    "/{staff_id}/onboarding-link",
    response_model=OnboardingLinkStatusResponse,
    summary="Get onboarding link lifecycle status",
)
async def get_onboarding_link_status(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OnboardingLinkStatusResponse:
    """Return the admin lifecycle status of a staff member's onboarding link.

    Resolves the latest token row and derives ``state`` from the pure
    helper ``onboarding_lifecycle_label(row, now)``: ``none`` (no row),
    ``revoked``, ``completed`` (consumed), ``expired`` (pending past
    expiry), ``in_progress`` (pending with a saved draft), or
    ``not_started`` (pending, no draft). When ``state == "in_progress"``
    the body additionally carries the server-computed
    ``completion_percentage`` and ``last_saved_at`` (= ``draft_updated_at``).

    Module-gated (404 ``not_enabled`` when ``staff_management`` is off) and
    org-scoped — a missing or cross-org staff member surfaces as 404.

    **Validates: Requirements 10.1, 13.1, 13.2, 13.5.**
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    now = datetime.now(timezone.utc)
    row = await _get_latest_onboarding_token(db, org_id=org_id, staff_id=staff_id)
    state = onboarding_lifecycle_label(row, now)

    completion_percentage: int | None = None
    last_saved_at: datetime | None = None
    if state == "in_progress" and row is not None:
        # Decrypt the saved draft and score it (R13.2). Best-effort: a
        # decryption hiccup must not 500 the admin status card — fall back
        # to a 0% / last-saved-timestamp view rather than raising raw
        # exception text (R14.5).
        try:
            draft = onboarding_tokens.load_draft(row)
            completion_percentage = compute_completion_percentage(draft)
        except Exception:  # noqa: BLE001 - best-effort draft scoring
            completion_percentage = compute_completion_percentage(None)
        last_saved_at = row.draft_updated_at

    return OnboardingLinkStatusResponse(
        state=state,
        expires_at=getattr(row, "expires_at", None),
        created_at=getattr(row, "created_at", None),
        consumed_at=getattr(row, "consumed_at", None),
        completion_percentage=completion_percentage,
        last_saved_at=last_saved_at,
    )


@router.post(
    "/{staff_id}/onboarding-link/resend",
    summary="Resend (revoke + mint + email) a staff onboarding link",
)
async def resend_onboarding_link(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Revoke any active onboarding link, mint a fresh one, and email it.

    ``onboarding_tokens.revoke_active`` invalidates the prior pending token
    and purges its draft in the same write (R12.9), ``mint`` issues a new
    7-day link, and ``send_onboarding_email`` dispatches the invite — its
    failure is folded into the response (``onboarding_email_sent`` /
    ``onboarding_email_error``) and never raises, so a provider outage does
    not roll back the freshly minted link (R10.2).

    Returns ``422 onboarding_email_required`` (humanized ``{message, code}``)
    when the staff member has no email — no token is minted in that case.

    Module-gated, org-scoped, and audit-logged
    (``onboarding.link_resent``).

    **Validates: Requirements 10.2, 12.9, 14.2, 14.3, 14.5.**
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    # R10.2 — a link is useless without a destination. Block before any
    # revoke/mint so we neither purge the existing draft nor mint a
    # dangling token that can never be delivered.
    if not staff.email or not staff.email.strip():
        raise HTTPException(
            status_code=422,
            detail={
                "message": humanize_onboarding_error("onboarding_email_required"),
                "code": "onboarding_email_required",
            },
        )

    # Supersede the prior link (purging its draft, R12.9) and mint fresh.
    await onboarding_tokens.revoke_active(db, org_id=org_id, staff_id=staff_id)
    token_raw = await onboarding_tokens.mint(db, org_id=org_id, staff_id=staff_id)
    row = await _get_latest_onboarding_token(db, org_id=org_id, staff_id=staff_id)

    base_url = request.headers.get("origin")
    delivery = await send_onboarding_email(
        db,
        org_id=org_id,
        staff=staff,
        token=token_raw,
        base_url=base_url,
    )

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="onboarding.link_resent",
        entity_type="staff_member",
        entity_id=staff_id,
        after_value={
            "onboarding_email_sent": delivery.ok,
            "onboarding_email_error": delivery.error_code,
        },
        ip_address=ip_address,
    )

    return {
        "onboarding_email_sent": delivery.ok,
        "onboarding_email_error": delivery.error_code,
        "expires_at": getattr(row, "expires_at", None),
    }


@router.post(
    "/{staff_id}/onboarding-link/revoke",
    summary="Revoke a staff member's active onboarding link",
)
async def revoke_onboarding_link(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Revoke the active onboarding link and purge its draft (R10.3).

    Delegates to ``onboarding_tokens.revoke_active`` which sets
    ``status='revoked'`` and NULLs both draft columns in the same UPDATE
    (R12.9). Idempotent — when no pending token exists it is a 200 no-op.
    A single ``onboarding.link_revoked`` audit row is written only when at
    least one token was actually revoked (no audit noise for the no-op
    case).

    Module-gated, org-scoped, audit-logged.

    **Validates: Requirements 10.3, 12.9, 14.2, 14.3, 14.5.**
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    revoked_count = await onboarding_tokens.revoke_active(
        db, org_id=org_id, staff_id=staff_id
    )
    if revoked_count > 0:
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="onboarding.link_revoked",
            entity_type="staff_member",
            entity_id=staff_id,
            after_value={"tokens_revoked_count": revoked_count},
            ip_address=ip_address,
        )

    return {"status": "revoked"}


# ---------------------------------------------------------------------------
# Pay rate history (R3.5)
# ---------------------------------------------------------------------------


@router.get(
    "/{staff_id}/pay-rates",
    response_model=StaffPayRateListResponse,
    summary="Pay rate audit history",
)
async def get_pay_rate_history(
    staff_id: UUID,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the pay-rate audit ledger for a staff member.

    Responses are wrapped per the project-overview rule:
    ``{ items: [...], total: N }``. Pagination via ``?offset=&limit=``
    matches the existing list-endpoint convention. Ordered by
    ``effective_from DESC`` so the most recent change appears first.

    Module-gated (404 ``not_enabled`` when ``staff_management`` is off
    for the org), and 404 when the staff member doesn't exist or
    belongs to another org.

    **Validates: Requirement R3.5** (Phase 1 task C2).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    svc = StaffService(db)
    # Verify the staff exists + belongs to this org first; without
    # this check a 404 staff would still surface an empty history list
    # (because the audit-ledger query is filtered by both org + staff).
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    items, total = await svc.get_pay_rate_history(
        org_id, staff_id, offset=offset, limit=limit,
    )
    return StaffPayRateListResponse(items=items, total=total)


# ---------------------------------------------------------------------------
# Staff documents — onboarding / working-rights uploads (compliance docs
# linked to this staff member). Served through the staff router (gated by the
# staff-management module the org already has) rather than the compliance-docs
# module, which most orgs do NOT have enabled — so a staff member's submitted
# documents are always visible on their profile.
# ---------------------------------------------------------------------------


@router.get(
    "/{staff_id}/documents",
    response_model=StaffDocumentListResponse,
    summary="List documents uploaded for a staff member (onboarding / working-rights)",
)
async def list_staff_documents(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the documents linked to ``staff_id`` (onboarding working-rights
    uploads + any manually-attached files), wrapped as ``{ items, total }``.
    Each item carries the on-disk ``file_size`` (compliance files are stored
    unencrypted, so the stored size equals the original).

    Module-gated on ``staff_management`` (NOT ``compliance_docs``) and 404
    when the staff member doesn't exist or belongs to another org.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    compliance = ComplianceService(db)
    documents, total = await compliance.list_documents_filtered(
        org_id=org_id, staff_id=staff_id, sort_by="created_at", sort_dir="desc",
    )
    storage = ComplianceFileStorage()
    items: list[StaffDocumentItem] = []
    for d in documents:
        items.append(
            StaffDocumentItem(
                id=d.id,
                document_type=d.document_type,
                description=d.description,
                file_name=d.file_name,
                file_size=await storage.file_size(d.file_key),
                created_at=d.created_at,
                expiry_date=d.expiry_date,
            )
        )
    return StaffDocumentListResponse(items=items, total=total)


@router.post(
    "/{staff_id}/documents",
    response_model=StaffDocumentItem,
    status_code=201,
    summary="Upload a document for a staff member",
)
async def upload_staff_document(
    staff_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form("staff_document"),
    description: str | None = Form(None),
    expiry_date: date | None = Form(None),
    db: AsyncSession = Depends(get_db_session),
):
    """Attach a document (PDF / image / Word) to a staff member's profile.

    Stored as a compliance document linked to ``staff_id`` so it appears in the
    same Documents table as onboarding uploads. ``description`` carries the
    type-specific detail (e.g. "Passport", "First Aid"). Module-gated on
    ``staff_management``.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    raw_user_id = getattr(request.state, "user_id", None)
    uploaded_by: UUID | None = None
    if raw_user_id is not None:
        try:
            uploaded_by = UUID(str(raw_user_id))
        except (ValueError, TypeError):
            uploaded_by = None
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    compliance = ComplianceService(db)
    doc = await compliance.upload_document_with_file(
        org_id=org_id,
        file=file,
        metadata={
            "document_type": (document_type or "staff_document").strip()[:50] or "staff_document",
            "description": (description or "").strip()[:1000] or None,
            "staff_id": staff_id,
            "expiry_date": expiry_date,
        },
        uploaded_by=uploaded_by,
    )
    storage = ComplianceFileStorage()
    return StaffDocumentItem(
        id=doc.id,
        document_type=doc.document_type,
        description=doc.description,
        file_name=doc.file_name,
        file_size=await storage.file_size(doc.file_key),
        created_at=doc.created_at,
        expiry_date=doc.expiry_date,
    )


@router.delete(
    "/{staff_id}/documents/{doc_id}",
    status_code=204,
    summary="Delete a document attached to a staff member",
)
async def delete_staff_document(
    staff_id: UUID,
    doc_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete a staff member's document (record + stored file). Validates the
    document belongs to this org AND this staff member. Module-gated on
    ``staff_management``.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    compliance = ComplianceService(db)
    # Validates org ownership (403) + existence (404).
    doc = await compliance.get_document_for_download(org_id, doc_id)
    if doc.staff_id != staff_id:
        raise HTTPException(status_code=404, detail="Document not found")
    await compliance.delete_document(org_id, doc_id)
    return None


@router.get(
    "/{staff_id}/documents/{doc_id}/download",
    summary="Download a document uploaded for a staff member",
)
async def download_staff_document(
    staff_id: UUID,
    doc_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Stream a staff member's uploaded document.

    Validates the document belongs to this org AND this staff member before
    streaming. Module-gated on ``staff_management`` so it works for orgs
    without the compliance-docs module.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    compliance = ComplianceService(db)
    # Validates org ownership (403) + existence (404).
    doc = await compliance.get_document_for_download(org_id, doc_id)
    if doc.staff_id != staff_id:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = ComplianceFileStorage()
    stream, content_type = await storage.read_file(doc.file_key)
    return StreamingResponse(
        stream,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.file_name}"',
        },
    )


# ---------------------------------------------------------------------------
# Roster delivery — email (C3, R8)
# ---------------------------------------------------------------------------


@router.post(
    "/{staff_id}/email-roster",
    response_model=RosterSendResponse,
    summary="Email this week's roster to a staff member",
)
async def email_roster(
    staff_id: UUID,
    payload: RosterEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Email the named staff member their roster for the week starting
    ``payload.week_start``.

    Refusal cases (HTTP 422 with ``{ok=false, reason=...}``):

    - ``no_email`` — the staff member has no email address on file.
    - ``opt_out`` — ``weekly_roster_email_enabled`` is false (the staff
      asked not to receive these).
    - ``no_shifts_in_week`` — no ``schedule_entries`` rows fall within
      ``[week_start, week_start + 7 days)``.

    Success path (HTTP 200 with ``{ok=true, message_id=...}``):

    1. Load schedule entries for the week and render the
       ``app/templates/email/staff_roster.html`` Jinja template.
    2. Call the unified ``send_email`` with ``dlq_task_name='roster_email'``
       so a chain-exhausted send lands in the dead-letter queue for replay.
    3. Write an ``audit_log`` row with ``action='roster.emailed'`` and
       the message_id in ``after_value`` so admins can correlate the
       audit row with the provider's outbound log.

    Module-gated (R11.5): returns HTTP 404 ``not_enabled`` when the
    ``staff_management`` module is disabled for the org.

    **Validates: Requirement R8** (Phase 1 task C3).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    result = await send_roster_email(
        db,
        org_id=org_id,
        staff=staff,
        week_start=payload.week_start,
    )

    # Refusal cases must surface as HTTP 422 with an explicit machine-
    # readable ``reason`` so the frontend can render the right toast
    # (R8.2, R8.5).
    if not result.ok and result.reason in (
        REASON_NO_EMAIL,
        REASON_OPT_OUT,
        REASON_NO_SHIFTS_IN_WEEK,
    ):
        raise HTTPException(
            status_code=422,
            detail={"ok": False, "reason": result.reason},
        )

    # Success OR a downstream send-failure (provider chain exhausted) —
    # both surface as HTTP 200 with the result body. The DLQ already
    # captured the failed send for replay, so the API doesn't need to
    # bubble a 5xx here. The audit row is written for both outcomes so
    # ops can trace what happened (R8.4 — ``roster.emailed`` covers the
    # attempt, success or fail).
    audit_after: dict[str, object] = {
        "ok": result.ok,
        "week_start": payload.week_start.isoformat(),
    }
    if result.message_id:
        audit_after["message_id"] = result.message_id
    if result.reason:
        audit_after["reason"] = result.reason

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="roster.emailed",
        entity_type="staff_member",
        entity_id=staff_id,
        after_value=audit_after,
        ip_address=ip_address,
    )

    return RosterSendResponse(
        ok=result.ok,
        message_id=result.message_id,
        reason=result.reason,
    )


# ---------------------------------------------------------------------------
# Roster delivery — SMS (C6, R9)
# ---------------------------------------------------------------------------


@router.post(
    "/{staff_id}/sms-roster",
    response_model=RosterSendResponse,
    summary="SMS this week's roster to a staff member",
)
async def sms_roster(
    staff_id: UUID,
    payload: RosterSmsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """SMS the named staff member their roster for the week starting
    ``payload.week_start``.

    Refusal cases (HTTP 422 with ``{ok=false, reason=...}``):

    - ``no_phone`` — the staff member has no phone number on file.
    - ``opt_out`` — ``weekly_roster_sms_enabled`` is false.
    - ``no_shifts_in_week`` — no ``schedule_entries`` rows fall within
      ``[week_start, week_start + 7 days)``.

    Success path (HTTP 200 with ``{ok=true, message_id=...}``):

    1. Mint or reuse the public viewer token for ``(staff, week)``.
    2. Compose a 160-char body via ``compose_roster_sms_body`` —
       Māori macrons in the staff's first_name trigger UCS-2
       multi-part SMS (G7), never transliterated.
    3. Detect encoding + segment count for the audit row.
    4. Dispatch via the unified ``send_sms`` wrapper with
       ``dlq_task_name='roster_sms'`` so a chain-exhausted send lands
       in the dead-letter queue for replay.
    5. Write an ``audit_log`` row with ``action='roster.sms_sent'``
       and ``after_value`` carrying ``encoding``, ``segments``, and
       ``phone_number_masked`` for ops visibility (R9.3 / P1-N12).

    Module-gated (R11.5): returns HTTP 404 ``not_enabled`` when the
    ``staff_management`` module is disabled for the org.

    **Validates: Requirement R9** (Phase 1 task C6).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    # Build the public viewer base URL — prefer the request Origin
    # header (so the link in the SMS points at the same domain the
    # admin is currently on) and fall back to ``settings.frontend_base_url``
    # for callers without an Origin (e.g. server-to-server). The
    # frontend renders the public viewer at ``/public/staff-roster/:token``
    # (E9). Mirrors the pattern used by the customer portal token URLs.
    from app.config import settings as app_settings

    origin = request.headers.get("origin") or app_settings.frontend_base_url
    viewer_base_url = f"{(origin or 'http://localhost').rstrip('/')}/public/staff-roster"

    result = await send_roster_sms(
        db,
        org_id=org_id,
        staff=staff,
        week_start=payload.week_start,
        viewer_base_url=viewer_base_url,
    )

    # Refusal cases must surface as HTTP 422 with an explicit machine-
    # readable ``reason`` so the frontend can render the right toast
    # (R9.2).
    if not result.ok and result.reason in (
        REASON_NO_PHONE,
        REASON_OPT_OUT,
        REASON_NO_SHIFTS_IN_WEEK,
    ):
        raise HTTPException(
            status_code=422,
            detail={"ok": False, "reason": result.reason},
        )

    # Success OR a downstream send-failure (provider chain exhausted) —
    # both surface as HTTP 200 with the result body. The DLQ already
    # captured the failed send for replay, so the API doesn't need to
    # bubble a 5xx here. The audit row is written for both outcomes
    # (R9.6) so ops can trace what happened.
    audit_after: dict[str, object] = {
        "ok": result.ok,
        "week_start": payload.week_start.isoformat(),
    }
    if result.message_id:
        audit_after["message_id"] = result.message_id
    if result.reason:
        audit_after["reason"] = result.reason
    # Encoding + segments + masked phone for R9.3 / P1-N12.
    if result.audit_extras:
        audit_after.update(result.audit_extras)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="roster.sms_sent",
        entity_type="staff_member",
        entity_id=staff_id,
        after_value=audit_after,
        ip_address=ip_address,
    )

    return RosterSendResponse(
        ok=result.ok,
        message_id=result.message_id,
        reason=result.reason,
    )


# ---------------------------------------------------------------------------
# Employment agreement attach (C8, R5)
# ---------------------------------------------------------------------------


@router.post(
    "/{staff_id}/employment-agreement",
    response_model=StaffMemberResponse,
    summary="Attach employment agreement document",
)
async def attach_employment_agreement(
    staff_id: UUID,
    payload: EmploymentAgreementRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Attach a previously-uploaded document as the staff member's
    signed employment agreement (R5).

    Two-step flow:

    1. The Documents tab POSTs the binary to the existing
       ``POST /api/v2/uploads/attachments`` endpoint, which returns
       ``{file_key, file_name, file_size}``. The ``file_key`` follows
       the ``attachments/{org_id}/{uuid.hex}{ext}`` shape — the hex
       segment is the ``upload_id`` clients pass here.
    2. The frontend POSTs ``{ upload_id }`` to this endpoint, which
       validates the file lives under the requesting org's
       ``attachments/`` namespace, sets
       ``staff_members.employment_agreement_upload_id``, writes an
       ``audit_log`` row with ``action='staff.employment_agreement_uploaded'``,
       and returns the updated staff with masked PII.

    Validation rules:

    - 404 ``"Staff member not found"`` when the staff doesn't exist or
      belongs to another org (the existing org-isolation check via
      ``StaffService.get_staff``).
    - 404 ``"Upload not found"`` when no file exists on disk under
      ``attachments/{org_id}/{upload_id.hex}.*`` for the requesting
      org. This implicitly enforces org isolation: a file uploaded by
      org A is at ``attachments/<orgA>/...``, so org B looking under
      ``attachments/<orgB>/...`` will never find it.

    Org isolation note (gap-analysis P1-N16): the spec asks us to
    "validate the upload exists, belongs to the org" against an
    ``uploads`` table that doesn't exist in the codebase. The existing
    uploads pipeline is filesystem-only, but the file path is already
    org-scoped — checking for the file under the requesting org's
    folder achieves the same guarantee.

    Module-gated (R11.5): returns HTTP 404 ``not_enabled`` when the
    ``staff_management`` module is disabled for the org.

    **Validates: Requirement R5** (Phase 1 task C8).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")

    # Validate the upload exists on disk under the requesting org's
    # attachments namespace. The file_key shape is
    # ``attachments/{org_id}/{uuid.hex}{ext}`` — we glob by hex prefix
    # because the extension was inferred from the original filename
    # at upload time.
    import os
    from pathlib import Path as _Path

    upload_dir = _Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
    org_attachments = upload_dir / "attachments" / str(org_id)
    upload_hex = payload.upload_id.hex
    matches = (
        list(org_attachments.glob(f"{upload_hex}.*"))
        if org_attachments.is_dir()
        else []
    )
    if not matches:
        raise HTTPException(status_code=404, detail="Upload not found")

    # Capture the prior value so the audit row can record the swap
    # (replacing one agreement with another is a real workflow — the
    # frontend's "Replace" button drives this same endpoint).
    previous_upload_id = staff.employment_agreement_upload_id

    staff.employment_agreement_upload_id = payload.upload_id
    await db.flush()
    await db.refresh(staff)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="staff.employment_agreement_uploaded",
        entity_type="staff_member",
        entity_id=staff_id,
        before_value=(
            {"upload_id": str(previous_upload_id)}
            if previous_upload_id is not None
            else None
        ),
        after_value={"upload_id": str(payload.upload_id)},
        ip_address=ip_address,
    )

    enriched = await _enrich_reporting_to(db, staff)
    return StaffMemberResponse(**enriched)


# ---------------------------------------------------------------------------
# Location assignment
# ---------------------------------------------------------------------------

@router.post(
    "/{staff_id}/assign-location",
    response_model=LocationAssignmentResponse,
    status_code=201,
    summary="Assign staff to location",
)
async def assign_to_location(
    staff_id: UUID,
    payload: AssignToLocationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    try:
        assignment = await svc.assign_to_location(org_id, staff_id, payload.location_id)
        await db.flush()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return LocationAssignmentResponse.model_validate(assignment)


@router.delete(
    "/{staff_id}/locations/{location_id}",
    status_code=204,
    summary="Remove staff from location",
)
async def remove_from_location(
    staff_id: UUID,
    location_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    removed = await svc.remove_from_location(org_id, staff_id, location_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Assignment not found")
