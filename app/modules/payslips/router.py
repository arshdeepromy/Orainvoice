"""Payslips API router (Phase 4 task B7).

Endpoints (per design §5):

| Path                                                                    | Method        |
|-------------------------------------------------------------------------|---------------|
| /api/v2/pay-periods                                                     | GET, POST     |
| /api/v2/pay-periods/{id}                                                | GET, PATCH    |
| /api/v2/pay-periods/{id}/payslips                                       | GET, POST     |
| /api/v2/pay-periods/{id}/finalise                                       | POST          |
| /api/v2/pay-periods/{id}/reopen                                         | POST          |
| /api/v2/payslips/{id}                                                   | GET, PATCH    |
| /api/v2/payslips/{id}/finalise                                          | POST          |
| /api/v2/payslips/{id}/email                                             | POST          |
| /api/v2/payslips/{id}/pdf                                               | GET           |
| /api/v2/payslips/{id}/void                                              | POST          |
| /api/v2/staff/{id}/payslips                                             | GET           |
| /api/v2/staff/{id}/payslips/recurring-allowances                        | GET, POST     |
| /api/v2/staff/{id}/payslips/recurring-allowances/{rule_id}              | PATCH, DELETE |
| /api/v2/staff/{id}/terminate                                            | POST          |
| /api/v2/staff/me/payslips                                               | GET           |
| /api/v2/staff/me/payslips/{id}                                          | GET           |
| /api/v2/staff/me/payslips/{id}/pdf                                      | GET           |
| /api/v2/allowance-types                                                 | GET, POST     |
| /api/v2/allowance-types/{id}                                            | PATCH, DELETE |
| /api/v2/reports/wage-variance                                           | GET           |

All list responses return ``{ items, total }`` per project rule.

Module gating (B11 — N8): the path-prefix middleware
(``app/middleware/modules.py::MODULE_ENDPOINT_MAP``) gates the
``/api/v2/pay-periods``, ``/api/v2/payslips``, and
``/api/v2/allowance-types`` prefixes against the ``payroll`` module
slug. The self-service ``/api/v2/staff/me/payslips`` endpoints share
the ``/api/v2/staff`` prefix so they inherit the ``staff`` module
gate; the additional ``payroll`` enforcement is service-layer (in
:func:`_require_payroll_module`).

**Validates: Requirements R1, R1a, R3, R4, R6, R7, R8, R8a, R9,
R10, R12 — Staff Management Phase 4 task B7.**
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db_session
from app.modules.auth.rbac import (
    BRANCH_ADMIN,
    GLOBAL_ADMIN,
    LOCATION_MANAGER,
    ORG_ADMIN,
)
from app.modules.payslips import service as payslips_service
from app.modules.payslips import termination as termination_service
from app.modules.payslips.calc import _resolve_allowance_quantity
from app.modules.payslips.models import (
    AllowanceType,
    PayPeriod,
    Payslip,
    PayslipAllowance,
    PayslipDeduction,
    PayslipLeaveLine,
    PayslipReimbursement,
    StaffRecurringAllowance,
)
from app.modules.payslips.pdf_storage import read_payslip_pdf
from app.modules.payslips.schemas import (
    AllowanceTypeCreate,
    AllowanceTypeListResponse,
    AllowanceTypeResponse,
    AllowanceTypeUpdate,
    MyPayslipDetailResponse,
    MyPayslipResponse,
    MyPayslipsListResponse,
    PayPeriodCreate,
    PayPeriodListResponse,
    PayPeriodReopenRequest,
    PayPeriodResponse,
    PayPeriodUpdate,
    PayslipAllowanceResponse,
    PayslipDeductionResponse,
    PayslipDetailResponse,
    PayslipLeaveLineResponse,
    PayslipListResponse,
    PayslipReimbursementResponse,
    PayslipResponse,
    PayslipUpdate,
    RecurringAllowanceListResponse,
    StaffRecurringAllowanceCreate,
    StaffRecurringAllowanceResponse,
    StaffRecurringAllowanceUpdate,
    TerminationRequest,
)
from app.modules.staff.models import StaffMember

logger = logging.getLogger(__name__)


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth + module gating helpers (mirrors leave/time_clock pattern)
# ---------------------------------------------------------------------------


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=401, detail="Organisation context required",
        )
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="User context required")
    return UUID(str(user_id))


def _get_user_role(request: Request) -> str:
    return str(getattr(request.state, "role", "") or "")


def _get_client_ip(request: Request) -> str | None:
    return getattr(request.state, "client_ip", None)


async def _require_payroll_module(
    request: Request, db: AsyncSession,
) -> None:
    """Service-layer ``payroll`` module gate (N8).

    The path-prefix middleware (``MODULE_ENDPOINT_MAP``) already gates
    the three top-level prefixes (``/api/v2/pay-periods``,
    ``/api/v2/payslips``, ``/api/v2/allowance-types``). This helper
    enforces the same gate inside ``/api/v2/staff/me/payslips`` and
    ``/api/v2/staff/{id}/terminate`` — endpoints that share the
    ``/api/v2/staff`` prefix and therefore inherit only the ``staff``
    middleware gate.
    """
    from app.core.modules import ModuleService

    org_id = _get_org_id(request)
    service = ModuleService(db)
    if not await service.is_enabled(str(org_id), "payroll"):
        raise HTTPException(
            status_code=403,
            detail={
                "detail": "Module 'payroll' is not enabled for your organisation.",
                "module": "payroll",
            },
        )


def _require_org_admin(request: Request) -> None:
    role = _get_user_role(request)
    if role not in (ORG_ADMIN, GLOBAL_ADMIN):
        raise HTTPException(status_code=403, detail="org_admin role required")


def _require_admin_or_manager(request: Request) -> None:
    role = _get_user_role(request)
    if role not in (
        ORG_ADMIN,
        GLOBAL_ADMIN,
        BRANCH_ADMIN,
        LOCATION_MANAGER,
    ):
        raise HTTPException(
            status_code=403, detail="admin role required",
        )


async def _resolve_self_staff(
    db: AsyncSession, *, org_id: UUID, user_id: UUID,
) -> StaffMember:
    """G9 / N1 — resolve the staff record linked to ``user_id``.

    The ``is_active`` filter is intentionally OMITTED so terminated
    staff retain access to their own historical payslips per
    Wages Protection Act s4 / Holidays Act s81 record-retention
    rules (N2). The migration 0209 partial-UNIQUE index
    ``ux_staff_members_user_id`` guarantees determinism.
    """
    stmt = (
        select(StaffMember)
        .where(
            and_(
                StaffMember.org_id == org_id,
                StaffMember.user_id == user_id,
            ),
        )
        .limit(1)
    )
    staff = (await db.execute(stmt)).scalar_one_or_none()
    if staff is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": "no_staff_for_user"},
        )
    return staff


# ---------------------------------------------------------------------------
# Service-error → HTTP translation
# ---------------------------------------------------------------------------


def _raise_payslip_service_error(
    exc: payslips_service.PayslipServiceError,
) -> None:
    """Map :mod:`app.modules.payslips.service` errors to HTTP."""
    if isinstance(exc, payslips_service.PayslipNotFoundError):
        raise HTTPException(status_code=404, detail="Payslip not found")
    if isinstance(exc, payslips_service.PayPeriodNotFoundError):
        raise HTTPException(status_code=404, detail="Pay period not found")
    if isinstance(exc, payslips_service.PayslipImmutableError):
        raise HTTPException(
            status_code=409,
            detail={"detail": "payslip_immutable", "message": str(exc)},
        )
    if isinstance(exc, payslips_service.PeriodAlreadyPaidError):
        raise HTTPException(
            status_code=409, detail={"detail": "period_already_paid"},
        )
    if isinstance(exc, payslips_service.PeriodAlreadyOpenError):
        raise HTTPException(
            status_code=422, detail={"detail": "period_already_open"},
        )
    if isinstance(exc, payslips_service.PeriodFinalisedError):
        raise HTTPException(
            status_code=409, detail={"detail": "period_finalised"},
        )
    if isinstance(exc, payslips_service.StaffEmailMissingError):
        raise HTTPException(
            status_code=422, detail={"detail": "staff_email_missing"},
        )
    if isinstance(exc, payslips_service.PayslipNotFinalisedError):
        raise HTTPException(
            status_code=422, detail={"detail": "payslip_not_finalised"},
        )
    raise HTTPException(
        status_code=500,
        detail={"detail": "payslip_service_error", "message": str(exc)},
    )


def _raise_termination_service_error(
    exc: termination_service.TerminationServiceError,
) -> None:
    if isinstance(exc, termination_service.AlreadyTerminatedError):
        raise HTTPException(
            status_code=409, detail={"detail": "already_terminated"},
        )
    if isinstance(exc, termination_service.PayPeriodAlreadyPaidError):
        raise HTTPException(
            status_code=409,
            detail={"detail": "pay_period_already_paid"},
        )
    if isinstance(exc, payslips_service.PayslipServiceError):
        _raise_payslip_service_error(exc)
    raise HTTPException(
        status_code=500,
        detail={"detail": "termination_service_error", "message": str(exc)},
    )


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------


async def _serialise_payslip_detail(
    db: AsyncSession, payslip: Payslip, *, self_service: bool = False,
) -> PayslipDetailResponse | MyPayslipDetailResponse:
    """Hydrate a payslip with its four nested line lists."""
    allowances = list(
        (
            await db.execute(
                select(PayslipAllowance).where(
                    PayslipAllowance.payslip_id == payslip.id,
                )
            )
        )
        .scalars()
        .all()
    )
    deductions = list(
        (
            await db.execute(
                select(PayslipDeduction).where(
                    PayslipDeduction.payslip_id == payslip.id,
                )
            )
        )
        .scalars()
        .all()
    )
    reimbursements = list(
        (
            await db.execute(
                select(PayslipReimbursement).where(
                    PayslipReimbursement.payslip_id == payslip.id,
                )
            )
        )
        .scalars()
        .all()
    )
    leave_lines = list(
        (
            await db.execute(
                select(PayslipLeaveLine).where(
                    PayslipLeaveLine.payslip_id == payslip.id,
                )
            )
        )
        .scalars()
        .all()
    )
    period = await db.get(PayPeriod, payslip.pay_period_id)
    period_resp = (
        PayPeriodResponse.model_validate(period) if period else None
    )

    a_resp = [PayslipAllowanceResponse.model_validate(a) for a in allowances]
    d_resp = [PayslipDeductionResponse.model_validate(d) for d in deductions]
    r_resp = [
        PayslipReimbursementResponse.model_validate(r) for r in reimbursements
    ]
    l_resp = [PayslipLeaveLineResponse.model_validate(l) for l in leave_lines]

    if self_service:
        base = MyPayslipResponse.model_validate(payslip).model_dump()
        base["pay_period"] = period_resp.model_dump() if period_resp else None
        base["pdf_url"] = (
            f"/api/v2/staff/me/payslips/{payslip.id}/pdf"
            if payslip.status == "finalised"
            else None
        )
        return MyPayslipDetailResponse(
            **base,
            allowances=a_resp,
            deductions=d_resp,
            reimbursements=r_resp,
            leave_lines=l_resp,
        )

    base = PayslipResponse.model_validate(payslip).model_dump()
    base["pay_period"] = period_resp.model_dump() if period_resp else None
    return PayslipDetailResponse(
        **base,
        allowances=a_resp,
        deductions=d_resp,
        reimbursements=r_resp,
        leave_lines=l_resp,
    )


# ===========================================================================
# Pay-periods CRUD (R1, R1a)
# ===========================================================================


@router.get(
    "/pay-periods",
    response_model=PayPeriodListResponse,
    summary="List pay periods",
)
async def list_pay_periods(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
) -> PayPeriodListResponse:
    org_id = _get_org_id(request)
    base = select(PayPeriod).where(PayPeriod.org_id == org_id)
    if status:
        base = base.where(PayPeriod.status == status)
    total = (
        await db.execute(
            select(func.count(PayPeriod.id)).where(PayPeriod.org_id == org_id).where(
                PayPeriod.status == status if status else True
            )
        )
    ).scalar() or 0
    rows = (
        await db.execute(
            base.order_by(PayPeriod.start_date.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()
    return PayPeriodListResponse(
        items=[PayPeriodResponse.model_validate(r) for r in rows],
        total=int(total),
    )


@router.post(
    "/pay-periods",
    response_model=PayPeriodResponse,
    status_code=201,
    summary="Create pay period (admin)",
)
async def create_pay_period(
    payload: PayPeriodCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PayPeriodResponse:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    period = PayPeriod(
        org_id=org_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        pay_date=payload.pay_date,
        status="open",
    )
    db.add(period)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail={"detail": "pay_period_exists"},
        )
    await db.refresh(period)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="pay_period.created",
        entity_type="pay_period",
        entity_id=period.id,
        after_value={
            "pay_period_id": str(period.id),
            "start_date": period.start_date.isoformat(),
            "end_date": period.end_date.isoformat(),
        },
        ip_address=ip_address,
    )
    return PayPeriodResponse.model_validate(period)


@router.get(
    "/pay-periods/{period_id}",
    response_model=PayPeriodResponse,
    summary="Get pay period",
)
async def get_pay_period(
    period_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PayPeriodResponse:
    org_id = _get_org_id(request)
    period = await db.get(PayPeriod, period_id)
    if period is None or period.org_id != org_id:
        raise HTTPException(status_code=404, detail="Pay period not found")
    return PayPeriodResponse.model_validate(period)


@router.patch(
    "/pay-periods/{period_id}",
    response_model=PayPeriodResponse,
    summary="Update pay period (admin)",
)
async def update_pay_period(
    period_id: UUID,
    payload: PayPeriodUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PayPeriodResponse:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    period = await db.get(PayPeriod, period_id)
    if period is None or period.org_id != org_id:
        raise HTTPException(status_code=404, detail="Pay period not found")

    fields = payload.model_dump(exclude_unset=True)
    for k, v in fields.items():
        setattr(period, k, v)
    await db.flush()
    await db.refresh(period)

    if "status" in fields and fields["status"] == "paid":
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="pay_period.paid",
            entity_type="pay_period",
            entity_id=period.id,
            after_value={
                "pay_period_id": str(period.id),
                "paid_at": (
                    period.paid_at.isoformat() if period.paid_at else None
                ),
            },
            ip_address=ip_address,
        )

    return PayPeriodResponse.model_validate(period)


@router.post(
    "/pay-periods/{period_id}/reopen",
    response_model=PayPeriodResponse,
    summary="Reopen a finalised pay period (G21)",
)
async def reopen_pay_period_endpoint(
    period_id: UUID,
    payload: PayPeriodReopenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PayPeriodResponse:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        period = await payslips_service.reopen_pay_period(
            db,
            org_id=org_id,
            period_id=period_id,
            reason=payload.reason,
            user_id=user_id,
            ip_address=ip_address,
        )
    except payslips_service.PayslipServiceError as exc:
        _raise_payslip_service_error(exc)

    return PayPeriodResponse.model_validate(period)


# ---------------------------------------------------------------------------
# Pay-period payslip operations
# ---------------------------------------------------------------------------


@router.get(
    "/pay-periods/{period_id}/payslips",
    response_model=PayslipListResponse,
    summary="List payslips in a pay period",
)
async def list_period_payslips(
    period_id: UUID,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> PayslipListResponse:
    org_id = _get_org_id(request)
    base_where = and_(
        Payslip.org_id == org_id,
        Payslip.pay_period_id == period_id,
    )
    total = (
        await db.execute(
            select(func.count(Payslip.id)).where(base_where)
        )
    ).scalar() or 0
    rows = (
        await db.execute(
            select(Payslip)
            .where(base_where)
            .order_by(Payslip.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return PayslipListResponse(
        items=[PayslipResponse.model_validate(r) for r in rows],
        total=int(total),
    )


@router.post(
    "/pay-periods/{period_id}/payslips",
    response_model=PayslipListResponse,
    status_code=201,
    summary="Generate draft payslips for a period (admin)",
)
async def generate_period_payslips(
    period_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PayslipListResponse:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        created = await payslips_service.generate_for_period(
            db,
            org_id=org_id,
            period_id=period_id,
            user_id=user_id,
            ip_address=ip_address,
        )
    except payslips_service.PayslipServiceError as exc:
        _raise_payslip_service_error(exc)

    return PayslipListResponse(
        items=[PayslipResponse.model_validate(p) for p in created],
        total=len(created),
    )


@router.post(
    "/pay-periods/{period_id}/finalise",
    summary="Bulk finalise (and optionally email) every draft (admin)",
)
async def bulk_finalise_period(
    period_id: UUID,
    request: Request,
    email_all: bool = Query(False),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        result = await payslips_service.bulk_finalise_period(
            db,
            org_id=org_id,
            period_id=period_id,
            email_all=email_all,
            user_id=user_id,
            ip_address=ip_address,
        )
    except payslips_service.PayslipServiceError as exc:
        _raise_payslip_service_error(exc)
    return result


# ===========================================================================
# Payslip CRUD (admin view)
# ===========================================================================


@router.get(
    "/payslips/{payslip_id}",
    response_model=PayslipDetailResponse,
    summary="Get payslip detail (admin)",
)
async def get_payslip(
    payslip_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PayslipDetailResponse:
    org_id = _get_org_id(request)
    payslip = await db.get(Payslip, payslip_id)
    if payslip is None or payslip.org_id != org_id:
        raise HTTPException(status_code=404, detail="Payslip not found")
    return await _serialise_payslip_detail(db, payslip)  # type: ignore[return-value]


@router.patch(
    "/payslips/{payslip_id}",
    response_model=PayslipResponse,
    summary="Update draft payslip (admin)",
)
async def update_payslip(
    payslip_id: UUID,
    payload: PayslipUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PayslipResponse:
    _require_admin_or_manager(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    fields = payload.model_dump(exclude_unset=True)
    try:
        payslip = await payslips_service.update_payslip_fields(
            db,
            org_id=org_id,
            payslip_id=payslip_id,
            fields=fields,
            user_id=user_id,
            ip_address=ip_address,
        )
    except payslips_service.PayslipServiceError as exc:
        _raise_payslip_service_error(exc)

    # Recompute totals for the draft after admin edits.
    if payslip.status == "draft":
        staff = await db.get(StaffMember, payslip.staff_id)
        period = await db.get(PayPeriod, payslip.pay_period_id)
        if staff is not None and period is not None:
            try:
                await payslips_service.recompute_payslip(
                    db, payslip=payslip, staff=staff, period=period,
                )
            except payslips_service.PayslipServiceError as exc:
                _raise_payslip_service_error(exc)

    return PayslipResponse.model_validate(payslip)


@router.post(
    "/payslips/{payslip_id}/finalise",
    response_model=PayslipResponse,
    summary="Finalise a single draft (admin)",
)
async def finalise_payslip_endpoint(
    payslip_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PayslipResponse:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        payslip = await payslips_service.finalise_payslip(
            db,
            org_id=org_id,
            payslip_id=payslip_id,
            user_id=user_id,
            ip_address=ip_address,
        )
    except payslips_service.PayslipServiceError as exc:
        _raise_payslip_service_error(exc)
    return PayslipResponse.model_validate(payslip)


@router.post(
    "/payslips/{payslip_id}/email",
    response_model=PayslipResponse,
    summary="Email payslip PDF to staff (admin)",
)
async def email_payslip_endpoint(
    payslip_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PayslipResponse:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        payslip = await payslips_service.email_payslip(
            db,
            org_id=org_id,
            payslip_id=payslip_id,
            user_id=user_id,
            ip_address=ip_address,
        )
    except payslips_service.PayslipServiceError as exc:
        _raise_payslip_service_error(exc)
    return PayslipResponse.model_validate(payslip)


@router.get(
    "/payslips/{payslip_id}/pdf",
    summary="Download payslip PDF (admin)",
)
async def download_payslip_pdf(
    payslip_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    org_id = _get_org_id(request)
    payslip = await db.get(Payslip, payslip_id)
    if payslip is None or payslip.org_id != org_id:
        raise HTTPException(status_code=404, detail="Payslip not found")
    if payslip.status != "finalised" or not payslip.pdf_file_key:
        raise HTTPException(
            status_code=422,
            detail={"detail": "payslip_not_finalised"},
        )
    try:
        pdf_bytes = read_payslip_pdf(payslip.pdf_file_key, org_id=str(org_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=payslip-{payslip.id}.pdf",
        },
    )


@router.post(
    "/payslips/{payslip_id}/void",
    response_model=PayslipResponse,
    summary="Void a payslip (admin)",
)
async def void_payslip_endpoint(
    payslip_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    reason: str = Query("voided"),
) -> PayslipResponse:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        payslip = await payslips_service.void_payslip(
            db,
            org_id=org_id,
            payslip_id=payslip_id,
            reason=reason,
            user_id=user_id,
            ip_address=ip_address,
        )
    except payslips_service.PayslipServiceError as exc:
        _raise_payslip_service_error(exc)
    return PayslipResponse.model_validate(payslip)


# ===========================================================================
# Per-staff history (admin view) — declared BEFORE the /staff/me/* routes
# is unnecessary because FastAPI prefers static paths over dynamic ones,
# but the admin endpoint deliberately uses the {staff_id} dynamic path.
# We declare /staff/me/* AFTER the {staff_id} block — FastAPI router
# scoring picks the static "me" path first.
# ===========================================================================


@router.get(
    "/staff/{staff_id}/payslips",
    response_model=PayslipListResponse,
    summary="List payslips for a staff (admin view)",
)
async def list_staff_payslips(
    staff_id: UUID,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> PayslipListResponse:
    org_id = _get_org_id(request)
    base_where = and_(
        Payslip.org_id == org_id,
        Payslip.staff_id == staff_id,
    )
    total = (
        await db.execute(
            select(func.count(Payslip.id)).where(base_where)
        )
    ).scalar() or 0
    rows = (
        await db.execute(
            select(Payslip)
            .where(base_where)
            .order_by(Payslip.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return PayslipListResponse(
        items=[PayslipResponse.model_validate(r) for r in rows],
        total=int(total),
    )


# ---------------------------------------------------------------------------
# Recurring allowance rules (G4)
# ---------------------------------------------------------------------------


@router.get(
    "/staff/{staff_id}/payslips/recurring-allowances",
    response_model=RecurringAllowanceListResponse,
    summary="List recurring allowance rules (admin)",
)
async def list_recurring_allowances(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> RecurringAllowanceListResponse:
    org_id = _get_org_id(request)
    rows = list(
        (
            await db.execute(
                select(StaffRecurringAllowance).where(
                    StaffRecurringAllowance.org_id == org_id,
                    StaffRecurringAllowance.staff_id == staff_id,
                )
            )
        )
        .scalars()
        .all()
    )
    items: list[StaffRecurringAllowanceResponse] = []
    for r in rows:
        atype = await db.get(AllowanceType, r.allowance_type_id)
        item_dict = StaffRecurringAllowanceResponse.model_validate(r).model_dump()
        item_dict["allowance_type"] = (
            AllowanceTypeResponse.model_validate(atype).model_dump()
            if atype is not None
            else None
        )
        items.append(StaffRecurringAllowanceResponse(**item_dict))
    return RecurringAllowanceListResponse(items=items, total=len(items))


@router.post(
    "/staff/{staff_id}/payslips/recurring-allowances",
    response_model=StaffRecurringAllowanceResponse,
    status_code=201,
    summary="Create a recurring allowance rule (admin)",
)
async def create_recurring_allowance(
    staff_id: UUID,
    payload: StaffRecurringAllowanceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> StaffRecurringAllowanceResponse:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    rule = StaffRecurringAllowance(
        org_id=org_id,
        staff_id=staff_id,
        allowance_type_id=payload.allowance_type_id,
        amount=payload.amount,
        quantity=payload.quantity,
        active=payload.active,
        notes=payload.notes,
    )
    db.add(rule)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail={"detail": "recurring_allowance_exists"},
        )
    await db.refresh(rule)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="staff_recurring_allowance.added",
        entity_type="staff_recurring_allowance",
        entity_id=rule.id,
        after_value={
            "rule_id": str(rule.id),
            "staff_id": str(staff_id),
            "allowance_type_id": str(rule.allowance_type_id),
            "active": rule.active,
        },
        ip_address=ip_address,
    )
    return StaffRecurringAllowanceResponse.model_validate(rule)


@router.patch(
    "/staff/{staff_id}/payslips/recurring-allowances/{rule_id}",
    response_model=StaffRecurringAllowanceResponse,
    summary="Update a recurring allowance rule (admin)",
)
async def update_recurring_allowance(
    staff_id: UUID,
    rule_id: UUID,
    payload: StaffRecurringAllowanceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> StaffRecurringAllowanceResponse:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    rule = await db.get(StaffRecurringAllowance, rule_id)
    if rule is None or rule.org_id != org_id or rule.staff_id != staff_id:
        raise HTTPException(status_code=404, detail="Rule not found")

    fields = payload.model_dump(exclude_unset=True)
    for k, v in fields.items():
        setattr(rule, k, v)
    await db.flush()
    await db.refresh(rule)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="staff_recurring_allowance.updated",
        entity_type="staff_recurring_allowance",
        entity_id=rule.id,
        after_value={
            "rule_id": str(rule.id),
            "staff_id": str(staff_id),
            "fields_changed": sorted(fields.keys()),
        },
        ip_address=ip_address,
    )
    return StaffRecurringAllowanceResponse.model_validate(rule)


@router.delete(
    "/staff/{staff_id}/payslips/recurring-allowances/{rule_id}",
    status_code=200,
    summary="Deactivate a recurring allowance rule (admin)",
)
async def deactivate_recurring_allowance(
    staff_id: UUID,
    rule_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    rule = await db.get(StaffRecurringAllowance, rule_id)
    if rule is None or rule.org_id != org_id or rule.staff_id != staff_id:
        raise HTTPException(status_code=404, detail="Rule not found")

    rule.active = False
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="staff_recurring_allowance.deactivated",
        entity_type="staff_recurring_allowance",
        entity_id=rule.id,
        after_value={
            "rule_id": str(rule.id),
            "staff_id": str(staff_id),
        },
        ip_address=ip_address,
    )
    return {"id": str(rule.id), "active": False}


# ---------------------------------------------------------------------------
# Termination
# ---------------------------------------------------------------------------


@router.post(
    "/staff/{staff_id}/terminate",
    summary="Terminate employment with s27 final payslip",
)
async def terminate_endpoint(
    staff_id: UUID,
    payload: TerminationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    _require_org_admin(request)
    await _require_payroll_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        result = await termination_service.terminate_employment(
            db,
            org_id=org_id,
            staff_id=staff_id,
            end_date=payload.end_date,
            reason=payload.reason,
            pay_annual_leave=payload.final_pay_options.pay_annual_leave,
            pay_alt_days=payload.final_pay_options.pay_alt_days,
            pay_casual_8pct_remainder=payload.final_pay_options.pay_casual_8pct_remainder,
            user_id=user_id,
            ip_address=ip_address,
        )
    except termination_service.TerminationServiceError as exc:
        _raise_termination_service_error(exc)
    except payslips_service.PayslipServiceError as exc:
        _raise_payslip_service_error(exc)
    return dict(result)


# ===========================================================================
# Self-service /staff/me/payslips (G9 — N1 + N2 + N8)
# ===========================================================================


@router.get(
    "/staff/me/payslips",
    response_model=MyPayslipsListResponse,
    summary="Self-service: own finalised payslips",
)
async def my_payslips_list(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> MyPayslipsListResponse:
    await _require_payroll_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    staff = await _resolve_self_staff(db, org_id=org_id, user_id=user_id)

    base_where = and_(
        Payslip.org_id == org_id,
        Payslip.staff_id == staff.id,
        Payslip.status == "finalised",
    )
    total = (
        await db.execute(
            select(func.count(Payslip.id)).where(base_where)
        )
    ).scalar() or 0
    rows = list(
        (
            await db.execute(
                select(Payslip)
                .where(base_where)
                .order_by(Payslip.finalised_at.desc().nullslast())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    items: list[MyPayslipResponse] = []
    for p in rows:
        period = await db.get(PayPeriod, p.pay_period_id)
        item = MyPayslipResponse.model_validate(p).model_dump()
        item["pay_period"] = (
            PayPeriodResponse.model_validate(period).model_dump()
            if period is not None
            else None
        )
        item["pdf_url"] = f"/api/v2/staff/me/payslips/{p.id}/pdf"
        items.append(MyPayslipResponse(**item))
    return MyPayslipsListResponse(items=items, total=int(total))


@router.get(
    "/staff/me/payslips/{payslip_id}",
    response_model=MyPayslipDetailResponse,
    summary="Self-service: own payslip detail",
)
async def my_payslip_detail(
    payslip_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> MyPayslipDetailResponse:
    await _require_payroll_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    staff = await _resolve_self_staff(db, org_id=org_id, user_id=user_id)

    payslip = await db.get(Payslip, payslip_id)
    # 404 not 403 — don't leak existence (R8a.3 / N8).
    if (
        payslip is None
        or payslip.org_id != org_id
        or payslip.staff_id != staff.id
        or payslip.status != "finalised"
    ):
        raise HTTPException(status_code=404, detail="Payslip not found")
    return await _serialise_payslip_detail(db, payslip, self_service=True)  # type: ignore[return-value]


@router.get(
    "/staff/me/payslips/{payslip_id}/pdf",
    summary="Self-service: own payslip PDF",
)
async def my_payslip_pdf(
    payslip_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    await _require_payroll_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    staff = await _resolve_self_staff(db, org_id=org_id, user_id=user_id)

    payslip = await db.get(Payslip, payslip_id)
    if (
        payslip is None
        or payslip.org_id != org_id
        or payslip.staff_id != staff.id
        or payslip.status != "finalised"
        or not payslip.pdf_file_key
    ):
        raise HTTPException(status_code=404, detail="Payslip not found")
    try:
        pdf_bytes = read_payslip_pdf(payslip.pdf_file_key, org_id=str(org_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Payslip not found")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=payslip-{payslip.id}.pdf",
        },
    )


# ===========================================================================
# Allowance types (CRUD)
# ===========================================================================


@router.get(
    "/allowance-types",
    response_model=AllowanceTypeListResponse,
    summary="List allowance types",
)
async def list_allowance_types(
    request: Request,
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db_session),
) -> AllowanceTypeListResponse:
    org_id = _get_org_id(request)
    stmt = select(AllowanceType).where(AllowanceType.org_id == org_id)
    if not include_inactive:
        stmt = stmt.where(AllowanceType.active.is_(True))
    rows = list(
        (
            await db.execute(stmt.order_by(AllowanceType.display_order, AllowanceType.name))
        )
        .scalars()
        .all()
    )
    return AllowanceTypeListResponse(
        items=[AllowanceTypeResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.post(
    "/allowance-types",
    response_model=AllowanceTypeResponse,
    status_code=201,
    summary="Create allowance type (admin)",
)
async def create_allowance_type(
    payload: AllowanceTypeCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> AllowanceTypeResponse:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    atype = AllowanceType(
        org_id=org_id,
        code=payload.code,
        name=payload.name,
        taxable=payload.taxable,
        default_amount=payload.default_amount,
        unit=payload.unit,
        active=payload.active,
        display_order=payload.display_order,
    )
    db.add(atype)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=409, detail={"detail": "allowance_type_code_in_use"},
        )
    await db.refresh(atype)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="allowance_type.created",
        entity_type="allowance_type",
        entity_id=atype.id,
        after_value={
            "allowance_type_id": str(atype.id),
            "code": atype.code,
            "unit": atype.unit,
        },
        ip_address=ip_address,
    )
    return AllowanceTypeResponse.model_validate(atype)


@router.patch(
    "/allowance-types/{type_id}",
    response_model=AllowanceTypeResponse,
    summary="Update allowance type (admin)",
)
async def update_allowance_type(
    type_id: UUID,
    payload: AllowanceTypeUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> AllowanceTypeResponse:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    atype = await db.get(AllowanceType, type_id)
    if atype is None or atype.org_id != org_id:
        raise HTTPException(status_code=404, detail="Allowance type not found")
    fields = payload.model_dump(exclude_unset=True)
    for k, v in fields.items():
        setattr(atype, k, v)
    await db.flush()
    await db.refresh(atype)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="allowance_type.updated",
        entity_type="allowance_type",
        entity_id=atype.id,
        after_value={
            "allowance_type_id": str(atype.id),
            "fields_changed": sorted(fields.keys()),
        },
        ip_address=ip_address,
    )
    return AllowanceTypeResponse.model_validate(atype)


@router.delete(
    "/allowance-types/{type_id}",
    status_code=200,
    summary="Deactivate allowance type (admin)",
)
async def deactivate_allowance_type(
    type_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    atype = await db.get(AllowanceType, type_id)
    if atype is None or atype.org_id != org_id:
        raise HTTPException(status_code=404, detail="Allowance type not found")
    atype.active = False
    await db.flush()
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="allowance_type.deactivated",
        entity_type="allowance_type",
        entity_id=atype.id,
        after_value={"allowance_type_id": str(atype.id)},
        ip_address=ip_address,
    )
    return {"id": str(atype.id), "active": False}


# ===========================================================================
# Wage variance report (R12)
# ===========================================================================


@router.get(
    "/reports/wage-variance",
    summary="Per-staff wage variance — current vs previous period",
)
async def wage_variance_report(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    threshold_pct: Decimal = Query(
        Decimal("10"),
        description="Highlight rows where |delta_pct| >= threshold (default 10%).",
    ),
) -> dict:
    """Per-staff wage variance — current finalised period vs previous
    finalised period, sorted by absolute change.

    Surfaces unexplained jumps (e.g. someone got 20h extra without
    comment). Returns ``{ items, total }`` per project rule.
    """
    _require_admin_or_manager(request)
    org_id = _get_org_id(request)

    # Find the two most recent finalised periods.
    period_rows = list(
        (
            await db.execute(
                select(PayPeriod)
                .where(
                    PayPeriod.org_id == org_id,
                    PayPeriod.status.in_(("finalised", "paid")),
                )
                .order_by(PayPeriod.start_date.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if len(period_rows) < 1:
        return {"items": [], "total": 0, "threshold_pct": str(threshold_pct)}

    current = period_rows[0]
    previous = period_rows[1] if len(period_rows) > 1 else None

    # Pull all finalised payslips in those two periods, indexed by staff.
    period_ids = [current.id]
    if previous is not None:
        period_ids.append(previous.id)
    rows = list(
        (
            await db.execute(
                select(Payslip).where(
                    Payslip.org_id == org_id,
                    Payslip.pay_period_id.in_(period_ids),
                    Payslip.status == "finalised",
                )
            )
        )
        .scalars()
        .all()
    )
    by_staff: dict[UUID, dict[str, Decimal]] = {}
    for r in rows:
        bucket = by_staff.setdefault(r.staff_id, {})
        if r.pay_period_id == current.id:
            bucket["current"] = Decimal(r.gross_pay or 0)
        elif previous is not None and r.pay_period_id == previous.id:
            bucket["previous"] = Decimal(r.gross_pay or 0)

    items: list[dict] = []
    for staff_id, bucket in by_staff.items():
        cur = bucket.get("current", Decimal("0"))
        prev = bucket.get("previous", Decimal("0"))
        delta = cur - prev
        if prev > 0:
            delta_pct = (delta / prev * Decimal(100)).quantize(Decimal("0.01"))
        else:
            delta_pct = Decimal("0.00") if cur == 0 else Decimal("999.99")
        items.append(
            {
                "staff_id": str(staff_id),
                "current_gross": str(cur),
                "previous_gross": str(prev),
                "delta": str(delta),
                "delta_pct": str(delta_pct),
                "above_threshold": abs(delta_pct) >= threshold_pct,
            }
        )
    items.sort(key=lambda x: abs(Decimal(x["delta_pct"])), reverse=True)
    return {
        "items": items,
        "total": len(items),
        "threshold_pct": str(threshold_pct),
        "current_period_id": str(current.id),
        "previous_period_id": str(previous.id) if previous is not None else None,
    }


# Suppress "imported but unused" — kept on the public surface for
# call sites that may want them in future extensions.
_ = (date, _resolve_allowance_quantity)
