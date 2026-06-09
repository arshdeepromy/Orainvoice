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

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db_session
from app.core.encryption import envelope_decrypt_str
from app.modules.organisations.service import get_org_settings
from app.modules.staff.models import (
    StaffLocationAssignment,
    StaffMember,
    StaffRosterViewToken,
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
    StaffListKpisResponse,
    StaffMemberCreate,
    StaffMemberListResponse,
    StaffMemberResponse,
    StaffMemberUpdate,
    StaffMetricValue,
    StaffMonthStatsResponse,
    StaffPayRateListResponse,
    UtilisationReportResponse,
)
from app.modules.staff.security import mask_bank_account, mask_ird
from app.modules.staff.service import (
    _DEFAULT_MINIMUM_WAGE_THRESHOLD,
    MinimumWageBelowThresholdError,
    StaffService,
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
    inject the plaintext into the response dict. The schema's
    ``_mask_ird_field`` / ``_mask_bank_field`` ``mode='before'``
    validators then mask the plaintext on outbound serialisation so
    callers still receive ``"***1234"`` style display values, never
    the raw plaintext.
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

    # Re-mask through the response schema so the dict carries the
    # masked display value (e.g. "***123") rather than plaintext, and
    # to keep the wire shape identical to what callers got before.
    if data.get("ird_number") is not None:
        data["ird_number"] = mask_ird(data["ird_number"])
    if data.get("bank_account_number") is not None:
        data["bank_account_number"] = mask_bank_account(data["bank_account_number"])

    if staff.reporting_to:
        result = await db.execute(
            select(StaffMember.first_name, StaffMember.last_name)
            .where(StaffMember.id == staff.reporting_to)
        )
        row = result.first()
        if row:
            data["reporting_to_name"] = f"{row[0] or ''} {row[1] or ''}".strip()
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
    for s in staff_list:
        data = StaffMemberResponse.model_validate(s).model_dump()
        if s.reporting_to and s.reporting_to in manager_names:
            data["reporting_to_name"] = manager_names[s.reporting_to]
        # Decrypt + mask PII fields so the masked display value
        # ("***1234") shows in the list, not blank — same logic as
        # _enrich_reporting_to. Best-effort: a missing key or corrupt
        # envelope leaves the field as None.
        ird_ct = getattr(s, "ird_number_encrypted", None)
        if ird_ct:
            try:
                data["ird_number"] = mask_ird(envelope_decrypt_str(ird_ct))
            except Exception:  # noqa: BLE001
                data["ird_number"] = None
        bank_ct = getattr(s, "bank_account_number_encrypted", None)
        if bank_ct:
            try:
                data["bank_account_number"] = mask_bank_account(
                    envelope_decrypt_str(bank_ct)
                )
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
    return {"message": "Staff member deactivated", "id": str(staff_id)}


@router.delete("/{staff_id}/permanent", status_code=200, summary="Permanently delete staff member")
async def delete_staff_permanent(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete a staff member record."""
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
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
