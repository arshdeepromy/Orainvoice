"""Table module API router — floor plans, tables, and reservations.

Endpoints (all under /api/v2/tables):
- Floor plans: GET /, POST /, GET /{id}, PUT /{id}, DELETE /{id}, GET /{id}/state
- Tables: GET /tables, POST /tables, GET /tables/{id}, PUT /tables/{id},
          DELETE /tables/{id}, PUT /tables/{id}/status, POST /tables/merge, POST /tables/split
- Reservations: GET /reservations, POST /reservations, GET /reservations/{id},
                PUT /reservations/{id}, PUT /reservations/{id}/cancel

**Validates: Requirement — Table Module**
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.tables.schemas import (
    FloorPlanCreate,
    FloorPlanListResponse,
    FloorPlanResponse,
    FloorPlanStateResponse,
    FloorPlanUpdate,
    MergeTablesRequest,
    ReservationCreate,
    ReservationListResponse,
    ReservationResponse,
    ReservationUpdate,
    SplitTableRequest,
    TableCreate,
    TableListResponse,
    TableResponse,
    TableStatusUpdate,
    TableUpdate,
)
from app.modules.tables.service import TableService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


# ======================================================================
# Floor Plan endpoints
# ======================================================================


@router.get("/floor-plans", response_model=FloorPlanListResponse, summary="List floor plans")
async def list_floor_plans(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    plans, total = await svc.list_floor_plans(org_id, skip=skip, limit=limit)
    return FloorPlanListResponse(
        floor_plans=[FloorPlanResponse.model_validate(p) for p in plans],
        total=total,
    )


@router.post("/floor-plans", response_model=FloorPlanResponse, status_code=201, summary="Create floor plan")
async def create_floor_plan(
    payload: FloorPlanCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    fp = await svc.create_floor_plan(org_id, payload)
    return FloorPlanResponse.model_validate(fp)


@router.get("/floor-plans/{floor_plan_id}", response_model=FloorPlanResponse, summary="Get floor plan")
async def get_floor_plan(
    floor_plan_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    fp = await svc.get_floor_plan(org_id, floor_plan_id)
    if fp is None:
        raise HTTPException(status_code=404, detail="Floor plan not found")
    return FloorPlanResponse.model_validate(fp)


@router.put("/floor-plans/{floor_plan_id}", response_model=FloorPlanResponse, summary="Update floor plan")
async def update_floor_plan(
    floor_plan_id: UUID,
    payload: FloorPlanUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    fp = await svc.update_floor_plan(org_id, floor_plan_id, payload)
    if fp is None:
        raise HTTPException(status_code=404, detail="Floor plan not found")
    return FloorPlanResponse.model_validate(fp)


@router.delete("/floor-plans/{floor_plan_id}", status_code=204, summary="Delete floor plan")
async def delete_floor_plan(
    floor_plan_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    deleted = await svc.delete_floor_plan(org_id, floor_plan_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Floor plan not found")


@router.get(
    "/floor-plans/{floor_plan_id}/state",
    response_model=FloorPlanStateResponse,
    summary="Get floor plan state with tables and reservations",
)
async def get_floor_plan_state(
    floor_plan_id: UUID,
    request: Request,
    target_date: date | None = Query(None, alias="date"),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    try:
        state = await svc.get_floor_plan_state(org_id, floor_plan_id, target_date=target_date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FloorPlanStateResponse(
        floor_plan=FloorPlanResponse.model_validate(state["floor_plan"]),
        tables=[TableResponse.model_validate(t) for t in state["tables"]],
        reservations=[ReservationResponse.model_validate(r) for r in state["reservations"]],
    )


# ======================================================================
# Table endpoints
# ======================================================================


@router.get("/tables", response_model=TableListResponse, summary="List tables")
async def list_tables(
    request: Request,
    floor_plan_id: UUID | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    tables, total = await svc.list_tables(
        org_id, floor_plan_id=floor_plan_id, status=status, skip=skip, limit=limit,
    )
    return TableListResponse(
        tables=[TableResponse.model_validate(t) for t in tables],
        total=total,
    )


@router.post("/tables", response_model=TableResponse, status_code=201, summary="Create table")
async def create_table(
    payload: TableCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    tbl = await svc.create_table(org_id, payload)
    return TableResponse.model_validate(tbl)


@router.get("/tables/{table_id}", response_model=TableResponse, summary="Get table")
async def get_table(
    table_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    tbl = await svc.get_table(org_id, table_id)
    if tbl is None:
        raise HTTPException(status_code=404, detail="Table not found")
    return TableResponse.model_validate(tbl)


@router.put("/tables/{table_id}", response_model=TableResponse, summary="Update table")
async def update_table(
    table_id: UUID,
    payload: TableUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    tbl = await svc.update_table(org_id, table_id, payload)
    if tbl is None:
        raise HTTPException(status_code=404, detail="Table not found")
    return TableResponse.model_validate(tbl)


@router.delete("/tables/{table_id}", status_code=204, summary="Delete table")
async def delete_table(
    table_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    deleted = await svc.delete_table(org_id, table_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Table not found")


@router.put("/tables/{table_id}/status", response_model=TableResponse, summary="Update table status")
async def update_table_status(
    table_id: UUID,
    payload: TableStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    try:
        tbl = await svc.update_status(org_id, table_id, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return TableResponse.model_validate(tbl)


@router.post("/tables/merge", response_model=list[TableResponse], summary="Merge tables")
async def merge_tables(
    payload: MergeTablesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    try:
        tables = await svc.merge_tables(org_id, payload.table_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return [TableResponse.model_validate(t) for t in tables]


@router.post("/tables/split", response_model=list[TableResponse], summary="Split merged tables")
async def split_tables(
    payload: SplitTableRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    try:
        tables = await svc.split_tables(org_id, payload.table_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return [TableResponse.model_validate(t) for t in tables]


# ======================================================================
# Reservation endpoints
# ======================================================================


@router.get("/reservations", response_model=ReservationListResponse, summary="List reservations")
async def list_reservations(
    request: Request,
    target_date: date | None = Query(None, alias="date"),
    table_id: UUID | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    reservations, total = await svc.list_reservations(
        org_id, target_date=target_date, table_id=table_id, status=status,
        skip=skip, limit=limit,
    )
    return ReservationListResponse(
        reservations=[ReservationResponse.model_validate(r) for r in reservations],
        total=total,
    )


@router.post("/reservations", response_model=ReservationResponse, status_code=201, summary="Create reservation")
async def create_reservation(
    payload: ReservationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    try:
        res = await svc.create_reservation(org_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ReservationResponse.model_validate(res)


@router.get("/reservations/{reservation_id}", response_model=ReservationResponse, summary="Get reservation")
async def get_reservation(
    reservation_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    res = await svc.get_reservation(org_id, reservation_id)
    if res is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return ReservationResponse.model_validate(res)


@router.put("/reservations/{reservation_id}", response_model=ReservationResponse, summary="Update reservation")
async def update_reservation(
    reservation_id: UUID,
    payload: ReservationUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    res = await svc.update_reservation(org_id, reservation_id, payload)
    if res is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return ReservationResponse.model_validate(res)


@router.put(
    "/reservations/{reservation_id}/cancel",
    response_model=ReservationResponse,
    summary="Cancel reservation",
)
async def cancel_reservation(
    reservation_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TableService(db)
    try:
        res = await svc.cancel_reservation(org_id, reservation_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if res is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return ReservationResponse.model_validate(res)
