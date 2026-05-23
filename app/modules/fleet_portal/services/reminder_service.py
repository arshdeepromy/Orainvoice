"""Per-vehicle reminder preference service.

Implements: B2B Fleet Portal task 10.1 — Requirements 10.1, 10.2, 10.3,
10.6, 10.7, 10.8, 10.9.

Property 25 predicate: when ``enabled = true``, channels and recipients
must each be non-empty, lead_time_days ∈ {7,14,30}, and SMS channel
requires the org to have an SMS provider configured.

Property 27 service-due math: returns NULL when neither
service_interval_km nor service_interval_months is set; otherwise the
due date is the *earliest* of the two derived dates.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal.dependencies import FleetSessionCtx
from app.modules.fleet_portal.models import FleetReminderPreference


# ---------------------------------------------------------------------------
# Property 25 predicate (mirrors the schema layer)
# ---------------------------------------------------------------------------


_VALID_LEAD_TIMES = frozenset({7, 14, 30})
_VALID_CHANNELS = frozenset({"email", "sms"})
_VALID_RECIPIENTS = frozenset({"fleet_admin", "assigned_drivers"})


def validate_preference(
    *,
    enabled: bool,
    lead_time_days: int,
    channels: Sequence[str],
    recipients: Sequence[str],
    sms_provider_configured: bool,
) -> None:
    """Property 25 — raise ValueError on any rule violation."""
    if not enabled:
        return  # disabled: any other shape is fine
    if lead_time_days not in _VALID_LEAD_TIMES:
        raise ValueError("lead_time_days must be one of 7, 14, 30")
    if not channels:
        raise ValueError("channels must contain at least one of 'email' or 'sms'")
    if not recipients:
        raise ValueError(
            "recipients must contain at least one of 'fleet_admin' or 'assigned_drivers'"
        )
    bad_channels = [c for c in channels if c not in _VALID_CHANNELS]
    if bad_channels:
        raise ValueError(f"Unknown channels: {bad_channels!r}")
    bad_recipients = [r for r in recipients if r not in _VALID_RECIPIENTS]
    if bad_recipients:
        raise ValueError(f"Unknown recipients: {bad_recipients!r}")
    if "sms" in channels and not sms_provider_configured:
        raise ValueError(
            "SMS channel requires a configured SMS provider"
        )


# ---------------------------------------------------------------------------
# Property 27 — service-due math
# ---------------------------------------------------------------------------


def compute_service_due_date(
    *,
    last_service_at: date | None,
    last_odometer: int | None,
    current_odometer: int | None,
    interval_km: int | None,
    interval_months: int | None,
) -> date | None:
    """Property 27 — earliest of (km-derived, months-derived); None if neither."""
    candidates: list[date] = []

    if (
        interval_km is not None
        and interval_km > 0
        and last_service_at is not None
        and current_odometer is not None
        and last_odometer is not None
        and current_odometer > last_odometer
    ):
        # Estimate average km/day since last service; project to next interval.
        days_since_last = max(
            (date.today() - last_service_at).days, 1
        )
        kms_run = current_odometer - last_odometer
        if kms_run > 0:
            kms_per_day = kms_run / days_since_last
            kms_remaining = max(interval_km - kms_run, 0)
            if kms_per_day > 0:
                days_until = int(kms_remaining / kms_per_day)
                candidates.append(date.today() + timedelta(days=days_until))

    if interval_months is not None and interval_months > 0 and last_service_at is not None:
        # Approximate calendar math — months as 30-day buckets is fine for
        # a reminder horizon. Service due tooling accepts a few days of
        # slack.
        candidates.append(last_service_at + timedelta(days=interval_months * 30))

    if not candidates:
        return None
    return min(candidates)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def upsert_preference(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    customer_vehicle_id: uuid.UUID,
    reminder_type: str,
    enabled: bool,
    lead_time_days: int,
    channels: list[str],
    recipients: list[str],
    service_interval_km: int | None,
    service_interval_months: int | None,
    sms_provider_configured: bool,
) -> FleetReminderPreference:
    if ctx.fleet_account_id is None:
        raise ValueError("No fleet account context")

    validate_preference(
        enabled=enabled,
        lead_time_days=lead_time_days,
        channels=channels,
        recipients=recipients,
        sms_provider_configured=sms_provider_configured,
    )

    res = await db.execute(
        select(FleetReminderPreference).where(
            FleetReminderPreference.customer_vehicle_id == customer_vehicle_id,
            FleetReminderPreference.reminder_type == reminder_type,
        )
    )
    pref = res.scalars().first()
    if pref is None:
        pref = FleetReminderPreference(
            org_id=ctx.org_id,
            fleet_account_id=ctx.fleet_account_id,
            customer_vehicle_id=customer_vehicle_id,
            reminder_type=reminder_type,
        )
        db.add(pref)

    pref.enabled = enabled
    pref.lead_time_days = lead_time_days
    pref.channels = list(channels)
    pref.recipients = list(recipients)
    pref.service_interval_km = service_interval_km
    pref.service_interval_months = service_interval_months
    await db.flush()
    await db.refresh(pref)
    return pref


async def default_preferences_for_new_vehicle(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    customer_vehicle_id: uuid.UUID,
) -> None:
    """Create the three default-disabled rows for a freshly added vehicle (Req 10.9)."""
    if ctx.fleet_account_id is None:
        return
    for rt in (
        "wof_expiry_reminder",
        "cof_expiry_reminder",
        "service_due_reminder",
    ):
        existing = (
            await db.execute(
                select(FleetReminderPreference).where(
                    FleetReminderPreference.customer_vehicle_id == customer_vehicle_id,
                    FleetReminderPreference.reminder_type == rt,
                )
            )
        ).scalars().first()
        if existing is None:
            db.add(
                FleetReminderPreference(
                    org_id=ctx.org_id,
                    fleet_account_id=ctx.fleet_account_id,
                    customer_vehicle_id=customer_vehicle_id,
                    reminder_type=rt,
                    enabled=False,
                )
            )
    await db.flush()


__all__ = [
    "validate_preference",
    "compute_service_due_date",
    "upsert_preference",
    "default_preferences_for_new_vehicle",
]
