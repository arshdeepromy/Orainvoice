"""Persistence + audit service for the Payroll_Tax_Settings module.

This module holds the write/read services that sit between the routers and the
two stored rows (``platform_tax_default`` and ``org_tax_settings``). Each
mutating call follows the same shape:

    validate (pure)  →  on error: HTTPException(422), persist nothing
                     →  on success: apply change, flush + refresh,
                        write an Audit_Log entry with prior + new values

Validation is delegated to the pure
:func:`app.modules.payroll_tax.validation.validate_config_fragment`; a non-empty
error list is a **hard rejection** — no row is written (Req 7.x/8.x "SHALL NOT
persist"). Audit writes go through :func:`app.core.audit.write_audit_log`.

Session semantics: ``get_db_session`` uses ``session.begin()`` (autocommit), so
services here call ``await db.flush()`` (never ``commit()``) and
``await db.refresh(obj)`` before returning ORM objects for serialization.

This file currently implements the **platform tier** (Global_Admin) functions.
The org tier (Org_Admin) functions are added by a sibling task and reuse the
shared helpers below.

**Validates: Requirements 2.2, 2.4, 10.2 — Payroll Tax Settings (platform tier).**
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.payroll_tax.models import OrgTaxSettings, PlatformTaxDefault
from app.modules.payroll_tax.resolution import resolve_tax_config
from app.modules.payroll_tax.schemas import OrgTaxSettingsView
from app.modules.payroll_tax.validation import validate_config_fragment

__all__ = [
    "get_platform_default",
    "update_platform_default",
    "get_org_resolved_view",
    "set_org_overrides",
    "reset_org_field",
    "reset_org_all",
]


# ---------------------------------------------------------------------------
# Shared constants / helpers (used by both tiers).
# ---------------------------------------------------------------------------

#: Every Tax_Field that lives on the platform document. ``tax_year_label`` is
#: stored in its own column on ``platform_tax_default``; every other key is
#: folded into the JSONB ``config`` document.
PLATFORM_FIELD_KEYS: tuple[str, ...] = (
    "paye_brackets",
    "secondary_rates",
    "acc_levy_rate",
    "acc_max_liable_earnings",
    "student_loan_rate",
    "student_loan_threshold",
    "ietc",
    "default_kiwisaver_employee_rate",
    "default_kiwisaver_employer_rate",
    "tax_year_label",
)

#: The Tax_Fields an organisation may override. ``tax_year_label`` is
#: platform-only (display-only) and is therefore **not** org-overridable, so it
#: is excluded here even though it appears in :data:`PLATFORM_FIELD_KEYS`.
ORG_FIELD_KEYS: tuple[str, ...] = tuple(
    k for k in PLATFORM_FIELD_KEYS if k != "tax_year_label"
)


def _validation_error(errors: list) -> HTTPException:
    """Build a 422 ``HTTPException`` carrying per-field validation messages.

    The detail is a list of ``{"field", "message"}`` objects (Req 8.6), matching
    the shape the routers surface to the GUI.
    """
    return HTTPException(
        status_code=422,
        detail=[{"field": e.field, "message": e.message} for e in errors],
    )


def _jsonify(value: Any) -> Any:
    """Normalise a value to its JSON-native form for stable comparison/storage.

    Running both the stored value and the submitted value through a JSON
    round-trip means numeric forms (e.g. ``142283`` vs ``142283.0``) and nested
    structures compare on identical representations, so the audit diff records a
    field only when it genuinely changed.
    """
    return json.loads(json.dumps(value, default=str))


def _extract_request_audit_meta(request: Any) -> tuple[str | None, str | None]:
    """Pull ``(ip_address, device_info)`` from a request for the audit row.

    Defensive: a missing ``request`` (or missing attributes) yields ``None`` for
    both, so an absent request never breaks an otherwise-valid save.
    """
    if request is None:
        return None, None
    ip_address = getattr(getattr(request, "state", None), "client_ip", None)
    device_info = None
    headers = getattr(request, "headers", None)
    if headers is not None:
        try:
            device_info = headers.get("user-agent")
        except Exception:  # noqa: BLE001 - header access must never break a save
            device_info = None
    return ip_address, device_info


def _platform_document(row: PlatformTaxDefault | None) -> dict[str, Any]:
    """Reconstruct the full platform document (config + label) from a row.

    Returns the JSON-native document holding every key in
    :data:`PLATFORM_FIELD_KEYS`. ``None`` (no stored row) yields an empty dict so
    a first-time save records a creation diff.
    """
    if row is None:
        return {}
    document: dict[str, Any] = {}
    if isinstance(row.config, dict):
        document.update(row.config)
    # ``tax_year_label`` lives in its own column, not the JSONB config.
    document["tax_year_label"] = row.tax_year_label
    return _jsonify(document)


def _diff_document(
    before: dict[str, Any], after: dict[str, Any], keys: tuple[str, ...]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compute the per-field before/after diff over ``keys``.

    Only fields whose normalised value changed are included, so the Audit_Log
    records exactly the changed Tax_Fields with their prior and new values
    (Req 2.4, 10.2). Fields present only in ``before`` (cleared) record an
    ``after`` of ``None``; fields present only in ``after`` (added) record a
    ``before`` of ``None``.
    """
    before_diff: dict[str, Any] = {}
    after_diff: dict[str, Any] = {}
    for key in keys:
        had_before = key in before
        had_after = key in after
        if not had_before and not had_after:
            continue
        prior = _jsonify(before.get(key)) if had_before else None
        new = _jsonify(after.get(key)) if had_after else None
        if prior != new:
            before_diff[key] = prior
            after_diff[key] = new
    return before_diff, after_diff


# ---------------------------------------------------------------------------
# Platform tier (Global_Admin)
# ---------------------------------------------------------------------------


async def get_platform_default(db: AsyncSession) -> PlatformTaxDefault:
    """Return the single Platform_Tax_Default row (Req 2.1).

    Raises ``HTTPException(404)`` when no platform row exists — the row is
    created once by the seed migration, so its absence is a server
    misconfiguration rather than a client error.
    """
    row = (
        await db.execute(select(PlatformTaxDefault).limit(1))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Platform tax default has not been initialised.",
        )
    return row


async def update_platform_default(
    db: AsyncSession,
    *,
    fields: dict[str, Any],
    user_id: uuid.UUID | str | None,
    request: Any = None,
) -> PlatformTaxDefault:
    """Validate and persist a change to the Platform_Tax_Default (Req 2.2, 2.4).

    ``fields`` is the full platform document submitted by a Global_Admin. The
    flow is:

    1. **Validate first.** ``validate_config_fragment(fields)`` runs over the
       submitted document; a non-empty error list raises ``HTTPException(422)``
       with per-field messages and **no row is written** (Req 7.x/8.x "SHALL NOT
       persist").
    2. **Compute the diff.** The per-field before/after diff is taken against the
       currently stored document so the audit records prior and new values.
    3. **Persist.** ``config`` (every non-label key) and the ``tax_year_label``
       column are updated (the singleton row is created if it does not yet
       exist), then ``flush`` + ``refresh``.
    4. **Audit.** A ``payroll_tax.platform.update`` Audit_Log entry is written
       with ``org_id=None`` (a global, non-org-scoped action) capturing the
       acting Global_Admin and the changed Tax_Fields' prior/new values
       (Req 2.4, 10.2).

    Returns the refreshed ORM row.
    """
    if not isinstance(fields, dict):
        raise HTTPException(
            status_code=422,
            detail=[{"field": "config", "message": "Tax configuration must be an object."}],
        )

    # 1. Validate first — reject without writing on any error (Req 7.x/8.x).
    errors = validate_config_fragment(fields)
    if errors:
        raise _validation_error(errors)

    # 2. Load the current row (may be absent) and compute the before/after diff.
    row = (
        await db.execute(select(PlatformTaxDefault).limit(1))
    ).scalar_one_or_none()

    before_document = _platform_document(row)
    after_document = {k: fields[k] for k in PLATFORM_FIELD_KEYS if k in fields}
    before_diff, after_diff = _diff_document(
        before_document, after_document, PLATFORM_FIELD_KEYS
    )

    # 3. Persist: config holds every non-label key; the label has its own column.
    new_config = {
        k: _jsonify(fields[k])
        for k in PLATFORM_FIELD_KEYS
        if k != "tax_year_label" and k in fields
    }
    new_label = fields.get("tax_year_label")
    user_uuid = uuid.UUID(str(user_id)) if user_id is not None else None

    if row is None:
        row = PlatformTaxDefault(
            is_singleton=True,
            config=new_config,
            tax_year_label=new_label if new_label is not None else "",
            updated_by=user_uuid,
        )
        db.add(row)
    else:
        row.config = new_config
        if new_label is not None:
            row.tax_year_label = new_label
        row.updated_by = user_uuid

    await db.flush()
    await db.refresh(row)

    # 4. Audit the change with prior + new values (Req 2.4, 10.2). org_id=None
    #    marks this as a global (non-org) admin action.
    ip_address, device_info = _extract_request_audit_meta(request)
    await write_audit_log(
        session=db,
        action="payroll_tax.platform.update",
        entity_type="platform_tax_default",
        org_id=None,
        user_id=user_uuid,
        entity_id=row.id,
        before_value={"fields": before_diff} if before_diff else None,
        after_value={"fields": after_diff} if after_diff else None,
        ip_address=ip_address,
        device_info=device_info,
    )

    return row


# ---------------------------------------------------------------------------
# Org tier (Org_Admin) — shared helpers
# ---------------------------------------------------------------------------


async def _load_org_state(
    db: AsyncSession, org_id: uuid.UUID | str
) -> tuple[
    PlatformTaxDefault | None, dict[str, Any], OrgTaxSettings | None, dict[str, Any]
]:
    """Load the platform row + the org's overrides row for the given org.

    Returns ``(platform_row, platform_config, org_row, org_overrides)`` where:

    * ``platform_config`` is the full platform document with ``tax_year_label``
      folded in from its dedicated column (so the per-field status check can
      treat every key uniformly), or ``{}`` when no platform row exists;
    * ``org_overrides`` is the sparse override map (a copy), or ``{}`` when the
      org has no row yet.
    """
    platform_row = (
        await db.execute(select(PlatformTaxDefault).limit(1))
    ).scalar_one_or_none()

    platform_config: dict[str, Any] = {}
    if platform_row is not None and isinstance(platform_row.config, dict):
        platform_config = dict(platform_row.config)
    if platform_row is not None and platform_row.tax_year_label is not None:
        platform_config["tax_year_label"] = platform_row.tax_year_label

    org_row = (
        await db.execute(
            select(OrgTaxSettings).where(OrgTaxSettings.org_id == org_id)
        )
    ).scalar_one_or_none()

    org_overrides: dict[str, Any] = {}
    if org_row is not None and isinstance(org_row.overrides, dict):
        org_overrides = dict(org_row.overrides)

    return platform_row, platform_config, org_row, org_overrides


def _resolved_to_view_fields(config: Any) -> dict[str, Any]:
    """Project a :class:`ResolvedTaxConfig` into the view's effective fields.

    The returned dict carries the fully-resolved (effective) value for every
    Tax_Field; ``Decimal`` values pass straight through ``OrgTaxSettingsView``'s
    ``TaxDecimal`` (which rehydrates/serializes exactly), and the bracket / IETC
    dataclasses are projected to the schema's nested shapes.
    """
    return {
        "paye_brackets": [
            {"upper_limit": b.upper_limit, "rate": b.rate}
            for b in config.paye_brackets
        ],
        "secondary_rates": dict(config.secondary_rates),
        "acc_levy_rate": config.acc_levy_rate,
        "acc_max_liable_earnings": config.acc_max_liable_earnings,
        "student_loan_rate": config.student_loan_rate,
        "student_loan_threshold": config.student_loan_threshold,
        "ietc": {
            "amount": config.ietc.amount,
            "lower": config.ietc.lower,
            "abatement_start": config.ietc.abatement_start,
            "abatement_rate": config.ietc.abatement_rate,
            "upper": config.ietc.upper,
        },
        "default_kiwisaver_employee_rate": config.default_kiwisaver_employee_rate,
        "default_kiwisaver_employer_rate": config.default_kiwisaver_employer_rate,
        "tax_year_label": config.tax_year_label,
    }


def _org_field_status(
    org_overrides: dict[str, Any], platform_config: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Compute the per-field inherited/override status for the org view.

    A field is an **override** exactly when its key is present in the org
    ``overrides`` JSONB (Req 4.3, 9.4). Otherwise it is **inherited**, and its
    ``source`` distinguishes whether the effective value came from the platform
    default (key present on the platform document) or fell all the way through
    to the Safety_Net. ``tax_year_label`` is platform-only and therefore never
    reports as an override.
    """
    status: dict[str, dict[str, Any]] = {}
    for key in PLATFORM_FIELD_KEYS:
        is_override = key in ORG_FIELD_KEYS and key in org_overrides
        if is_override:
            status[key] = {
                "inherited": False,
                "override": True,
                "source": "override",
            }
        elif key in platform_config:
            status[key] = {
                "inherited": True,
                "override": False,
                "source": "platform",
            }
        else:
            status[key] = {
                "inherited": True,
                "override": False,
                "source": "safety_net",
            }
    return status


async def _build_org_view(
    db: AsyncSession, org_id: uuid.UUID | str
) -> OrgTaxSettingsView:
    """Assemble the :class:`OrgTaxSettingsView` for ``org_id``.

    Combines the fully-resolved effective values (via
    :func:`resolve_tax_config`) with the per-field inherited/override status
    derived from the stored override keys.
    """
    _, platform_config, _, org_overrides = await _load_org_state(db, org_id)
    resolved = await resolve_tax_config(db, uuid.UUID(str(org_id)))
    fields = _resolved_to_view_fields(resolved)
    fields["field_status"] = _org_field_status(org_overrides, platform_config)
    return OrgTaxSettingsView.model_validate(fields)


# ---------------------------------------------------------------------------
# Org tier (Org_Admin) — public service functions
# ---------------------------------------------------------------------------


async def get_org_resolved_view(
    db: AsyncSession, *, org_id: uuid.UUID | str
) -> OrgTaxSettingsView:
    """Return the org's effective tax view with inherited/override flags (Req 4.3).

    For each Tax_Field the view carries the value currently in effect for the
    organisation (resolved override → platform → Safety_Net) and, in
    ``field_status``, whether that value is an organisation override or
    inherited from the platform default (Req 4.3). Read-only: no row is created.
    """
    return await _build_org_view(db, org_id)


async def set_org_overrides(
    db: AsyncSession,
    *,
    org_id: uuid.UUID | str,
    fields: dict[str, Any],
    user_id: uuid.UUID | str | None,
    request: Any = None,
) -> OrgTaxSettingsView:
    """Validate and persist a sparse set of Org_Tax_Settings overrides (Req 3.2, 3.3, 10.1).

    ``fields`` is the sparse set of Tax_Fields the org wishes to override. The
    flow mirrors the platform tier:

    1. **Validate first.** ``validate_config_fragment(fields)`` runs over the
       submitted fragment; a non-empty error list raises ``HTTPException(422)``
       with per-field messages and **no row is written** (Req 7.x/8.x).
    2. **Merge.** The submitted overridable keys are merged into (replacing) the
       org's existing ``overrides`` JSONB. ``tax_year_label`` is platform-only
       and silently ignored if present.
    3. **Persist.** The org row is created if absent, then ``flush`` + ``refresh``.
    4. **Audit.** A ``payroll_tax.org.update`` Audit_Log entry records the acting
       Org_Admin, the organisation, and the changed Tax_Fields' prior/new values
       (Req 10.1).

    Returns the refreshed org view.
    """
    if not isinstance(fields, dict):
        raise HTTPException(
            status_code=422,
            detail=[{"field": "overrides", "message": "Overrides must be an object."}],
        )

    # 1. Validate first — reject without writing on any error (Req 7.x/8.x).
    errors = validate_config_fragment(fields)
    if errors:
        raise _validation_error(errors)

    # 2. Load current state and merge the incoming overridable keys.
    _, _, org_row, before_overrides = await _load_org_state(db, org_id)
    incoming = {k: _jsonify(fields[k]) for k in ORG_FIELD_KEYS if k in fields}
    after_overrides = {**before_overrides, **incoming}

    before_diff, after_diff = _diff_document(
        before_overrides, after_overrides, ORG_FIELD_KEYS
    )

    # 3. Persist (create row if absent), then flush + refresh.
    org_uuid = uuid.UUID(str(org_id))
    user_uuid = uuid.UUID(str(user_id)) if user_id is not None else None
    if org_row is None:
        org_row = OrgTaxSettings(
            org_id=org_uuid,
            overrides=after_overrides,
            updated_by=user_uuid,
        )
        db.add(org_row)
    else:
        org_row.overrides = after_overrides
        org_row.updated_by = user_uuid

    await db.flush()
    await db.refresh(org_row)

    # 4. Audit the change with prior + new values (Req 10.1).
    ip_address, device_info = _extract_request_audit_meta(request)
    await write_audit_log(
        session=db,
        action="payroll_tax.org.update",
        entity_type="org_tax_settings",
        org_id=org_uuid,
        user_id=user_uuid,
        entity_id=org_row.id,
        before_value={"fields": before_diff} if before_diff else None,
        after_value={"fields": after_diff} if after_diff else None,
        ip_address=ip_address,
        device_info=device_info,
    )

    return await _build_org_view(db, org_id)


async def reset_org_field(
    db: AsyncSession,
    *,
    org_id: uuid.UUID | str,
    field: str,
    user_id: uuid.UUID | str | None,
    request: Any = None,
) -> OrgTaxSettingsView:
    """Reset a single Tax_Field to inherit the platform default (Req 9.1, 9.3).

    Removes ``field``'s key from the org ``overrides`` JSONB so the field
    resolves to the Platform_Tax_Default. The Audit_Log entry
    (``payroll_tax.org.reset_field``) records the acting Org_Admin, the
    organisation, the reset Tax_Field, the **prior override value**, and that the
    field now **inherits** (Req 9.3). Resetting an already-inherited field is a
    no-op that is still audited.
    """
    if field not in ORG_FIELD_KEYS:
        raise HTTPException(
            status_code=422,
            detail=[{"field": field, "message": f"{field!r} is not an overridable tax field."}],
        )

    _, _, org_row, before_overrides = await _load_org_state(db, org_id)
    prior_value = before_overrides.get(field)
    had_override = field in before_overrides

    org_uuid = uuid.UUID(str(org_id))
    user_uuid = uuid.UUID(str(user_id)) if user_id is not None else None

    if had_override and org_row is not None:
        new_overrides = {k: v for k, v in before_overrides.items() if k != field}
        org_row.overrides = new_overrides
        org_row.updated_by = user_uuid
        await db.flush()
        await db.refresh(org_row)

    # Audit the reset: prior override value + that the field now inherits (Req 9.3).
    ip_address, device_info = _extract_request_audit_meta(request)
    await write_audit_log(
        session=db,
        action="payroll_tax.org.reset_field",
        entity_type="org_tax_settings",
        org_id=org_uuid,
        user_id=user_uuid,
        entity_id=org_row.id if org_row is not None else None,
        before_value={"fields": {field: _jsonify(prior_value)}},
        after_value={"fields": {field: None}, "inherited_fields": [field]},
        ip_address=ip_address,
        device_info=device_info,
    )

    return await _build_org_view(db, org_id)


async def reset_org_all(
    db: AsyncSession,
    *,
    org_id: uuid.UUID | str,
    user_id: uuid.UUID | str | None,
    request: Any = None,
) -> OrgTaxSettingsView:
    """Reset every Tax_Field to inherit the platform default (Req 9.2).

    Sets the org ``overrides`` JSONB to ``{}`` so all fields resolve to the
    Platform_Tax_Default. The Audit_Log entry (``payroll_tax.org.reset_all``)
    records the acting Org_Admin, the organisation, the prior override values,
    and that those fields now inherit (Req 9.3). Resetting an org with no
    overrides is a no-op that is still audited.
    """
    _, _, org_row, before_overrides = await _load_org_state(db, org_id)

    org_uuid = uuid.UUID(str(org_id))
    user_uuid = uuid.UUID(str(user_id)) if user_id is not None else None

    if before_overrides and org_row is not None:
        org_row.overrides = {}
        org_row.updated_by = user_uuid
        await db.flush()
        await db.refresh(org_row)

    prior_fields = {
        k: _jsonify(v) for k, v in before_overrides.items() if k in ORG_FIELD_KEYS
    }

    # Audit the reset-all: prior override values + that the fields now inherit.
    ip_address, device_info = _extract_request_audit_meta(request)
    await write_audit_log(
        session=db,
        action="payroll_tax.org.reset_all",
        entity_type="org_tax_settings",
        org_id=org_uuid,
        user_id=user_uuid,
        entity_id=org_row.id if org_row is not None else None,
        before_value={"fields": prior_fields} if prior_fields else None,
        after_value={"fields": {}, "inherited_fields": list(prior_fields.keys())},
        ip_address=ip_address,
        device_info=device_info,
    )

    return await _build_org_view(db, org_id)
