"""Pydantic v2 schemas for the tables module.

**Validates: Requirement — Table Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ------------------------------------------------------------------
# Floor Plan schemas
# ------------------------------------------------------------------

class FloorPlanCreate(BaseModel):
    name: str = Field(default="Main Floor", max_length=100)
    location_id: uuid.UUID | None = None
    width: Decimal = Field(default=Decimal("800"))
    height: Decimal = Field(default=Decimal("600"))


class FloorPlanUpdate(BaseModel):
    name: str | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    is_active: bool | None = None


class FloorPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    location_id: uuid.UUID | None = None
    name: str
    width: Decimal
    height: Decimal
    is_active: bool
    created_at: datetime


# ------------------------------------------------------------------
# Restaurant Table schemas
# ------------------------------------------------------------------

class TableCreate(BaseModel):
    table_number: str = Field(max_length=20)
    seat_count: int = Field(default=4, ge=1)
    position_x: Decimal = Field(default=Decimal("0"))
    position_y: Decimal = Field(default=Decimal("0"))
    width: Decimal = Field(default=Decimal("100"))
    height: Decimal = Field(default=Decimal("100"))
    floor_plan_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None


class TableUpdate(BaseModel):
    table_number: str | None = None
    seat_count: int | None = Field(default=None, ge=1)
    position_x: Decimal | None = None
    position_y: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    floor_plan_id: uuid.UUID | None = None


class TableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    location_id: uuid.UUID | None = None
    table_number: str
    seat_count: int
    position_x: Decimal
    position_y: Decimal
    width: Decimal
    height: Decimal
    status: str
    merged_with_id: uuid.UUID | None = None
    floor_plan_id: uuid.UUID | None = None
    created_at: datetime


class TableStatusUpdate(BaseModel):
    status: str = Field(description="New status: available, occupied, needs_cleaning, reserved")


class MergeTablesRequest(BaseModel):
    table_ids: list[uuid.UUID] = Field(min_length=2, description="IDs of tables to merge")


class SplitTableRequest(BaseModel):
    table_id: uuid.UUID = Field(description="ID of the primary merged table to split")


# ------------------------------------------------------------------
# Reservation schemas
# ------------------------------------------------------------------

class ReservationCreate(BaseModel):
    table_id: uuid.UUID
    customer_name: str = Field(max_length=255)
    party_size: int = Field(ge=1)
    reservation_date: date
    reservation_time: time
    duration_minutes: int = Field(default=90, ge=15)
    notes: str | None = None


class ReservationUpdate(BaseModel):
    customer_name: str | None = None
    party_size: int | None = Field(default=None, ge=1)
    reservation_date: date | None = None
    reservation_time: time | None = None
    duration_minutes: int | None = Field(default=None, ge=15)
    notes: str | None = None
    status: str | None = None


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    table_id: uuid.UUID
    customer_name: str
    party_size: int
    reservation_date: date
    reservation_time: time
    duration_minutes: int
    notes: str | None = None
    status: str
    created_at: datetime


# ------------------------------------------------------------------
# Floor plan state (composite response)
# ------------------------------------------------------------------

class FloorPlanStateResponse(BaseModel):
    floor_plan: FloorPlanResponse
    tables: list[TableResponse]
    reservations: list[ReservationResponse]


# ------------------------------------------------------------------
# List responses
# ------------------------------------------------------------------

class FloorPlanListResponse(BaseModel):
    floor_plans: list[FloorPlanResponse]
    total: int


class TableListResponse(BaseModel):
    tables: list[TableResponse]
    total: int


class ReservationListResponse(BaseModel):
    reservations: list[ReservationResponse]
    total: int
