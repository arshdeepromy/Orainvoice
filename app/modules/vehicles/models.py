"""SQLAlchemy ORM models for vehicle-scoped tables.

Tables:
- org_vehicles: manually-entered vehicles per organisation (RLS enabled)
- customer_vehicles: link table connecting customers to vehicles (RLS enabled)
- odometer_readings: odometer reading history per global vehicle
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class OrgVehicle(Base):
    """Organisation-scoped manually-entered vehicle record."""

    __tablename__ = "org_vehicles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    rego: Mapped[str] = mapped_column(String(20), nullable=False)
    make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    colour: Mapped[str | None] = mapped_column(String(50), nullable=True)
    body_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    engine_size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    num_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_manual_entry: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    organisation = relationship("Organisation", backref="org_vehicles")
    customer_vehicles: Mapped[list[CustomerVehicle]] = relationship(
        back_populates="org_vehicle"
    )


class CustomerVehicle(Base):
    """Link table connecting customers to vehicles (global or org-scoped).

    Exactly one of ``global_vehicle_id`` or ``org_vehicle_id`` must be set,
    enforced by the ``vehicle_link_check`` CHECK constraint.
    """

    __tablename__ = "customer_vehicles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    global_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("global_vehicles.id"), nullable=True
    )
    org_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_vehicles.id"), nullable=True
    )
    odometer_at_link: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "(global_vehicle_id IS NOT NULL AND org_vehicle_id IS NULL) OR "
            "(global_vehicle_id IS NULL AND org_vehicle_id IS NOT NULL)",
            name="vehicle_link_check",
        ),
    )

    # Relationships
    organisation = relationship("Organisation", backref="customer_vehicles")
    customer = relationship("Customer", backref="customer_vehicles")
    global_vehicle = relationship("GlobalVehicle", backref="customer_vehicles")
    org_vehicle: Mapped[OrgVehicle | None] = relationship(
        back_populates="customer_vehicles"
    )


class OdometerReading(Base):
    """Odometer reading history for a global vehicle."""

    __tablename__ = "odometer_readings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    global_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("global_vehicles.id"), nullable=False
    )
    reading_km: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # carjam, manual, invoice
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('carjam','manual','invoice')",
            name="ck_odometer_readings_source",
        ),
        Index("idx_odometer_readings_vehicle", "global_vehicle_id", "recorded_at"),
    )

    # Relationships
    global_vehicle = relationship("GlobalVehicle", backref="odometer_readings")
