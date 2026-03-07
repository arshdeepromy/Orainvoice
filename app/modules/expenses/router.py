"""Expense API router.

Endpoints:
- GET    /api/v2/expenses              — list (paginated/filterable)
- POST   /api/v2/expenses              — create
- GET    /api/v2/expenses/{id}         — get
- PUT    /api/v2/expenses/{id}         — update
- DELETE /api/v2/expenses/{id}         — delete
- GET    /api/v2/expenses/summary      — summary report
- POST   /api/v2/expenses/include-in-invoice — mark as invoiced

**Validates: Requirement — Expense Module**
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.expenses.schemas import (
    ExpenseCreate,
    ExpenseListResponse,
    ExpenseResponse,
    ExpenseSummaryReport,
    ExpenseUpdate,
    IncludeInInvoiceRequest,
)
from app.modules.expenses.service import ExpenseService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID | None:
    user_id = getattr(request.state, "user_id", None)
    return UUID(str(user_id)) if user_id else None


# ---------------------------------------------------------------------------
# Summary report (must be before /{expense_id} to avoid path conflict)
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=ExpenseSummaryReport, summary="Expense summary report")
async def get_summary_report(
    request: Request,
    job_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ExpenseService(db)
    data = await svc.get_summary_report(
        org_id, job_id=job_id, project_id=project_id,
        date_from=date_from, date_to=date_to,
    )
    return ExpenseSummaryReport(**data)


# ---------------------------------------------------------------------------
# Include in invoice
# ---------------------------------------------------------------------------

@router.post("/include-in-invoice", response_model=list[ExpenseResponse], summary="Mark expenses as invoiced")
async def include_in_invoice(
    payload: IncludeInInvoiceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ExpenseService(db)
    try:
        expenses = await svc.include_in_invoice(org_id, payload.expense_ids, payload.invoice_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return [ExpenseResponse.model_validate(e) for e in expenses]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=ExpenseListResponse, summary="List expenses")
async def list_expenses(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    job_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    category: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ExpenseService(db)
    expenses, total = await svc.list_expenses(
        org_id, page=page, page_size=page_size,
        job_id=job_id, project_id=project_id,
        category=category, date_from=date_from, date_to=date_to,
    )
    return ExpenseListResponse(
        expenses=[ExpenseResponse.model_validate(e) for e in expenses],
        total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=ExpenseResponse, status_code=201, summary="Create expense")
async def create_expense(
    payload: ExpenseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = ExpenseService(db)
    expense = await svc.create_expense(org_id, payload, created_by=user_id)
    return ExpenseResponse.model_validate(expense)


@router.get("/{expense_id}", response_model=ExpenseResponse, summary="Get expense")
async def get_expense(
    expense_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ExpenseService(db)
    expense = await svc.get_expense(org_id, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return ExpenseResponse.model_validate(expense)


@router.put("/{expense_id}", response_model=ExpenseResponse, summary="Update expense")
async def update_expense(
    expense_id: UUID,
    payload: ExpenseUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ExpenseService(db)
    try:
        expense = await svc.update_expense(org_id, expense_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return ExpenseResponse.model_validate(expense)


@router.delete("/{expense_id}", status_code=204, summary="Delete expense")
async def delete_expense(
    expense_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ExpenseService(db)
    try:
        deleted = await svc.delete_expense(org_id, expense_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="Expense not found")
