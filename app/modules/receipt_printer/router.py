"""Receipt printer API router.

Endpoints:
- GET    /                — List printers
- POST   /                — Add printer
- PUT    /{printer_id}    — Update printer
- DELETE /{printer_id}    — Deactivate printer
- POST   /test            — Test print
- GET    /jobs            — List print jobs
- POST   /jobs            — Queue print job
- POST   /jobs/process    — Process pending queue

**Validates: Requirement 22 — POS Module (Receipt Printer Integration)**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.receipt_printer.schemas import (
    PrinterConfigCreate,
    PrinterConfigResponse,
    PrinterConfigUpdate,
    PrintJobCreate,
    PrintJobResponse,
    TestPrintRequest,
)
from app.modules.receipt_printer.service import PrinterService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.get(
    "",
    response_model=list[PrinterConfigResponse],
    summary="List printers",
)
async def list_printers(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PrinterService(db)
    printers = await svc.list_printers(org_id)
    return [PrinterConfigResponse.model_validate(p) for p in printers]


@router.post(
    "",
    response_model=PrinterConfigResponse,
    status_code=201,
    summary="Add printer",
)
async def add_printer(
    payload: PrinterConfigCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PrinterService(db)
    printer = await svc.configure_printer(org_id, payload)
    return PrinterConfigResponse.model_validate(printer)


@router.put(
    "/{printer_id}",
    response_model=PrinterConfigResponse,
    summary="Update printer",
)
async def update_printer(
    printer_id: UUID,
    payload: PrinterConfigUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PrinterService(db)
    try:
        printer = await svc.update_printer(org_id, printer_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return PrinterConfigResponse.model_validate(printer)


@router.delete(
    "/{printer_id}",
    status_code=204,
    summary="Deactivate printer",
)
async def delete_printer(
    printer_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PrinterService(db)
    try:
        await svc.delete_printer(org_id, printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/test",
    response_model=PrintJobResponse,
    status_code=201,
    summary="Test print",
)
async def test_print(
    payload: TestPrintRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PrinterService(db)
    try:
        job = await svc.test_print(org_id, payload.printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return PrintJobResponse.model_validate(job)


@router.get(
    "/jobs",
    response_model=list[PrintJobResponse],
    summary="List print jobs",
)
async def list_print_jobs(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PrinterService(db)
    jobs = await svc.get_print_jobs(org_id, status=status, limit=limit)
    return [PrintJobResponse.model_validate(j) for j in jobs]


@router.post(
    "/jobs",
    response_model=PrintJobResponse,
    status_code=201,
    summary="Queue print job",
)
async def queue_print_job(
    payload: PrintJobCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PrinterService(db)
    job = await svc.queue_print_job(org_id, payload)
    return PrintJobResponse.model_validate(job)


@router.post(
    "/jobs/process",
    response_model=list[PrintJobResponse],
    summary="Process pending print queue",
)
async def process_print_queue(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PrinterService(db)
    processed = await svc.process_print_queue(org_id)
    return [PrintJobResponse.model_validate(j) for j in processed]
