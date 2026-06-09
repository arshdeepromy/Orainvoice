# Feature: customer-reminder-consent
"""Consent helper module for customer reminder consent.

This module is the single source of truth for everything reminder-consent
related. It defines the Pydantic v2 wire/storage models, the pure helper
functions used by the manual-enable gate and the kiosk service, and the
side-effecting persistence helpers that write to
``customer.custom_fields`` and emit ``audit_log`` rows in one transaction.

Both the kiosk write path (``app.modules.kiosk.service.kiosk_check_in_v2``)
and the manual customer-profile write path
(``app.modules.customers.service.update_customer_reminder_config``) call
into ``record_consent_given`` so there is a single write site for the
``customer.reminder_consent.given`` audit row. Likewise
``record_consent_revoked`` is the single write site for
``customer.reminder_consent.revoked``.

Refs:
    Requirements 1.13, 1.14, 1.17, 2.2, 2.7, 2.9, 3.4, 3.7, 6.4, 7.1, 7.2, 7.3
    Design §3.1, §3.6
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import write_audit_log
from app.modules.customers.consent_text import (
    KIOSK_CONSENT_TEXT,
    KIOSK_CONSENT_TEXT_VERSION,
)
from app.modules.customers.models import Customer

__all__ = [
    "RemindersConsentEntry",
    "RemindersConsentRecord",
    "RemindersRevocationRecord",
    "coverage_for",
    "compute_missing_consent",
    "union_channel_for_category",
    "current_consent_text",
    "record_consent_given",
    "record_consent_revoked",
]


ReminderCategory = Literal[
    "service_due", "wof_expiry", "cof_expiry", "registration_expiry"
]
ReminderChannel = Literal["sms", "email", "both"]
EffectiveChannel = Literal["sms", "email"]


# ---------------------------------------------------------------------------
# Pydantic v2 wire/storage models (design §3.1)
# ---------------------------------------------------------------------------


class RemindersConsentEntry(BaseModel):
    """One ticked sub-checkbox on the kiosk OR one (category, channel) pair
    confirmed in the manual Consent Confirmation modal.

    ``vehicle_id`` is ``None`` for manual confirmations because manual
    consent is per-Customer, not per-vehicle.
    """

    vehicle_id: uuid.UUID | None
    category: ReminderCategory
    channel: ReminderChannel


class RemindersConsentRecord(BaseModel):
    """Wire shape mirroring ``customer.custom_fields["reminder_consent"]``.

    Fields with ``= None`` defaults are conditional on ``source``:
    ``kiosk_session_id``/``ip_address``/``user_agent`` are kiosk-only;
    ``recorded_by_user_id``/``recorded_by_user_email`` are manual-only;
    ``manual_note`` is manual + ``obtained_method == "other"`` only.
    """

    given_at: datetime  # UTC ISO 8601 (Pydantic v2 emits ISO format on model_dump(mode="json"))
    source: str  # "kiosk_self_checkin" OR "manually_recorded_by_staff:<obtained_method>"
    kiosk_session_id: uuid.UUID | None = None
    entries: list[RemindersConsentEntry]
    ip_address: str | None = None
    user_agent: str | None = None  # truncated to 500 by caller (B1/C3)
    recorded_by_user_id: uuid.UUID | None = None
    recorded_by_user_email: str | None = None
    consent_text_version: str
    manual_note: str | None = None


class RemindersRevocationRecord(BaseModel):
    """One entry appended to
    ``customer.custom_fields["reminder_consent_revocations"]``.
    """

    revoked_at: datetime
    source: str  # "manually_recorded_by_staff:<obtained_method>"
    recorded_by_user_id: uuid.UUID
    recorded_by_user_email: str
    channel: ReminderChannel
    categories_affected: list[ReminderCategory]
    reason_note: str


# ---------------------------------------------------------------------------
# Pure helpers (design §3.1)
# ---------------------------------------------------------------------------


def coverage_for(consent: dict | None) -> set[tuple[str, str]]:
    """Return the set of ``(category, effective_channel)`` pairs covered by
    an existing ``reminder_consent`` dict.

    A ``channel == "both"`` entry expands into two pairs:
    ``(cat, "sms")`` AND ``(cat, "email")``. The returned set never carries
    ``"both"`` directly so the consumer always operates on the simpler
    binary alphabet ``{"sms", "email"}``.

    Returns the empty set when ``consent`` is ``None``, falsy, or has no
    ``entries`` list.
    """
    if not consent:
        return set()

    entries = consent.get("entries") or []
    covered: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        category = entry.get("category")
        channel = entry.get("channel")
        if not category or not channel:
            continue
        if channel == "both":
            covered.add((category, "sms"))
            covered.add((category, "email"))
        elif channel in ("sms", "email"):
            covered.add((category, channel))
    return covered


def compute_missing_consent(
    existing_consent: dict | None,
    new_config: dict,
) -> list[dict]:
    """Return the list of ``{category, channel}`` pairs that the new config
    is enabling but the existing consent does not cover.

    For every key in ``new_config`` whose entry has ``enabled: True``,
    check whether ``(category, channel)`` is covered by ``existing_consent``.
    A ``channel == "both"`` requirement requires BOTH ``(cat, "sms")`` AND
    ``(cat, "email")`` to be covered; uncovered ``"both"`` is reported as
    two separate missing entries (sms + email) so the wire payload only
    ever contains the binary alphabet.

    An empty list means the consent gate is not triggered.
    """
    covered = coverage_for(existing_consent)
    missing: list[dict] = []

    for category, entry in (new_config or {}).items():
        if not isinstance(entry, dict):
            continue
        if not entry.get("enabled"):
            continue
        channel = entry.get("channel")
        if channel == "both":
            required_channels: tuple[str, ...] = ("sms", "email")
        elif channel in ("sms", "email"):
            required_channels = (channel,)
        else:
            continue

        for required in required_channels:
            if (category, required) not in covered:
                missing.append({"category": category, "channel": required})

    return missing


def union_channel_for_category(
    entries: list[RemindersConsentEntry],
    category: str,
) -> Literal["sms", "email", "both"]:
    """Compute the per-Customer union channel for ``category`` (Req 1.14).

    * If any matching entry chose ``"both"`` -> ``"both"``.
    * If matching entries chose multiple distinct channels -> ``"both"``.
    * Otherwise return the single shared channel.

    Raises :class:`ValueError` if ``entries`` contains no entry for
    ``category`` (caller is expected to filter first).
    """
    matching = [e for e in entries if e.category == category]
    if not matching:
        raise ValueError(f"No entries for category {category!r}")

    channels = {e.channel for e in matching}
    if "both" in channels:
        return "both"
    if len(channels) > 1:
        return "both"
    # Exactly one of "sms" or "email"
    only = next(iter(channels))
    return only  # type: ignore[return-value]


def current_consent_text() -> tuple[str, str]:
    """Return ``(text, version)`` for the kiosk consent banner.

    Source is the backend constant module
    :mod:`app.modules.customers.consent_text` (design §3.6 v1 decision).
    """
    return KIOSK_CONSENT_TEXT, KIOSK_CONSENT_TEXT_VERSION


# ---------------------------------------------------------------------------
# Side-effecting persistence helpers (design §3.1)
# ---------------------------------------------------------------------------


async def _load_customer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> Customer:
    """Load a customer scoped to ``org_id``. Raises ``ValueError`` if missing."""
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")
    return customer


async def record_consent_given(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    user_id: uuid.UUID | None,
    record: RemindersConsentRecord,
    ip_address: str | None = None,
    audit_device_info: str | None = None,
) -> None:
    """Replace ``customer.custom_fields["reminder_consent"]`` with ``record``
    and emit one ``audit_log`` row with action
    ``customer.reminder_consent.given``.

    The full ``ip_address`` and ``user_agent`` remain on the customer record
    (Req 7.3). The audit ``after_value`` is REDACTED to drop ``ip_address``
    and ``user_agent`` (Req 7.1) — the User-Agent is instead carried on the
    audit row's dedicated ``device_info`` column (passed via
    ``audit_device_info``), and the IP is carried on the dedicated
    ``ip_address`` column.

    Caller is expected to wrap this in ``session.begin()`` (which the
    ``get_db_session`` dependency already does). Do NOT call ``db.commit``
    or ``db.rollback`` here.
    """
    customer = await _load_customer(db, org_id=org_id, customer_id=customer_id)

    payload = record.model_dump(mode="json")

    custom_fields = dict(customer.custom_fields or {})
    custom_fields["reminder_consent"] = payload
    customer.custom_fields = custom_fields
    flag_modified(customer, "custom_fields")

    await db.flush()
    await db.refresh(customer)

    audit_after = dict(payload)
    audit_after.pop("ip_address", None)
    audit_after.pop("user_agent", None)

    await write_audit_log(
        db,
        action="customer.reminder_consent.given",
        entity_type="customer",
        org_id=org_id,
        user_id=user_id,
        entity_id=customer.id,
        before_value=None,
        after_value=audit_after,
        ip_address=ip_address,
        device_info=audit_device_info,
    )


async def record_consent_revoked(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    user_id: uuid.UUID,
    record: RemindersRevocationRecord,
) -> None:
    """Append ``record`` to ``customer.custom_fields["reminder_consent_revocations"]``,
    flip ``reminder_config[<cat>].enabled = False`` for every category in
    ``record.categories_affected``, and emit one ``audit_log`` row with
    action ``customer.reminder_consent.revoked``.

    The audit ``after_value`` is REDACTED to drop ``recorded_by_user_id``
    and ``recorded_by_user_email`` (Req 7.2) — the actor identity is
    captured by the audit row's own ``user_id`` column. The full actor
    identity remains on the revocation record inside ``custom_fields``
    (Req 3.9).

    Caller is expected to wrap this in ``session.begin()``.
    """
    customer = await _load_customer(db, org_id=org_id, customer_id=customer_id)

    payload = record.model_dump(mode="json")

    custom_fields = dict(customer.custom_fields or {})

    revocations = list(custom_fields.get("reminder_consent_revocations") or [])
    revocations.append(payload)
    custom_fields["reminder_consent_revocations"] = revocations

    config = dict(custom_fields.get("reminder_config") or {})
    for cat in record.categories_affected:
        cat_entry = dict(config.get(cat) or {})
        cat_entry["enabled"] = False
        config[cat] = cat_entry
    custom_fields["reminder_config"] = config

    customer.custom_fields = custom_fields
    flag_modified(customer, "custom_fields")

    await db.flush()
    await db.refresh(customer)

    audit_after = dict(payload)
    audit_after.pop("recorded_by_user_id", None)
    audit_after.pop("recorded_by_user_email", None)

    await write_audit_log(
        db,
        action="customer.reminder_consent.revoked",
        entity_type="customer",
        org_id=org_id,
        user_id=user_id,
        entity_id=customer.id,
        before_value=None,
        after_value=audit_after,
        ip_address=None,
        device_info=None,
    )
