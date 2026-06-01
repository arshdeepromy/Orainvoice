"""Pydantic v2 schemas for the PPSR module.

**Validates: Requirements R4, R5, R6, R8 — PPSR module Phase 1.**

Defines the request/response shapes for ``app/modules/ppsr/router.py``.
Strict separation between:

  - **Request** schemas (``PpsrSearchRequest``, ``PpsrLinkVehicleRequest``)
    — accept user input; ``PpsrSearchRequest`` validates the rego
    (uppercase / alphanumeric / 1-8 chars) so the service never sees
    a malformed plate.
  - **Response wrapper** schemas (``PpsrSearchResult``,
    ``PpsrSearchSummary``, ``PpsrSearchListResponse``,
    ``PpsrQuotaResponse``) — built from ORM rows via
    ``model_config = ConfigDict(from_attributes=True)``. Field-by-field
    population only — never ``model_dump(by_alias=...)`` or any
    automatic mapping that could splatter the encrypted blob into the
    response.

Encrypted-payload safety (G31): ``PpsrSearchSummary`` deliberately
omits ``response_encrypted`` and any decrypted owner / debtor strings.
The service builds the summary explicitly from denormalised columns
(``match``, ``statement_count``, ``has_warnings`` …) so the encrypted
bytes never leave the database. The unit tests in
``tests/unit/test_ppsr_schemas.py`` round-trip an ORM-style dict that
includes ``response_encrypted=b"secret"`` and assert the bytes are
absent from ``model_dump()``.

Refs: design.md §4 + §5; tasks.md C2; gap-analysis G29 / G30 / G44.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Rego validation
# ---------------------------------------------------------------------------

# NZ plates are 1-6 alphanumeric characters in practice; the spec allows up
# to 8 to leave headroom for personalised / historic plates and to match the
# CarJam upstream constraint. Whitespace inside the plate is rejected.
_REGO_PATTERN = re.compile(r"^[A-Z0-9]{1,8}$")


def _normalise_rego(value: str) -> str:
    """Strip + uppercase the rego before pattern-matching.

    Rejects ``None`` / empty / whitespace-only inputs. Used by
    ``PpsrSearchRequest`` validators; the service relies on the schema
    layer to guarantee well-formed regos so it can build cache keys
    safely (G30).
    """

    if value is None:
        raise ValueError("rego is required")
    cleaned = value.strip().upper()
    if not cleaned:
        raise ValueError("rego must not be empty")
    if not _REGO_PATTERN.match(cleaned):
        raise ValueError(
            "rego must be 1-8 alphanumeric characters (A-Z, 0-9) — "
            "no spaces, hyphens, or punctuation",
        )
    return cleaned


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class PpsrSearchOptions(BaseModel):
    """The toggle-flag input portion of a PPSR search.

    Kept as a separate model so it can round-trip through
    ``options.model_dump()`` in the service layer for the
    ``options_hash`` calculation (G30 — sha256 of canonical-JSON drives
    cache lookup).
    """

    include_ownership_history: bool = False
    include_current_owner: bool = False
    include_warnings: bool = True
    include_fws: bool = False
    check_hidden_plates: bool = False
    s241_purpose: str | None = None


class PpsrSearchRequest(BaseModel):
    """Body of ``POST /api/v2/ppsr/search``.

    Per design.md §5 the API takes the option flags **flattened** at
    the top level (rather than nested under an ``options`` key) so the
    JSON wire format matches the UI form 1:1. The service constructs a
    ``PpsrSearchOptions`` from these fields internally to compute the
    ``options_hash``.
    """

    rego: str = Field(..., description="NZ vehicle plate; 1-8 alphanumeric.")

    include_ownership_history: bool = False
    include_current_owner: bool = False
    include_warnings: bool = True
    include_fws: bool = False
    check_hidden_plates: bool = False
    s241_purpose: str | None = None

    force_refresh: bool = Field(
        default=False,
        description=(
            "Ignore the 5-minute cache and re-call CarJam. "
            "Counts against the org's monthly quota."
        ),
    )

    @field_validator("rego", mode="before")
    @classmethod
    def _validate_rego(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("rego must be a string")
        return _normalise_rego(value)

    def to_options(self) -> PpsrSearchOptions:
        """Project this request onto the canonical options model.

        The service uses the result for ``options_hash`` so cache hits
        survive JSON-key-order changes (G30).
        """

        return PpsrSearchOptions(
            include_ownership_history=self.include_ownership_history,
            include_current_owner=self.include_current_owner,
            include_warnings=self.include_warnings,
            include_fws=self.include_fws,
            check_hidden_plates=self.check_hidden_plates,
            s241_purpose=self.s241_purpose,
        )


class PpsrLinkVehicleRequest(BaseModel):
    """Body of ``POST /api/v2/ppsr/searches/:id/link-vehicle``.

    G23 closure — the search is bound to an existing ``OrgVehicle`` row
    so the vehicle profile can surface the saved PPSR check.
    """

    org_vehicle_id: UUID


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class PpsrSearchResult(BaseModel):
    """Response payload for ``POST /search`` and ``GET /searches/:id``.

    Carries the decrypted CarJam fields back to the caller. Construct
    this **field-by-field** in the service layer — never via
    ``model_dump(by_alias=...)`` or implicit attribute mapping that
    could leak ``response_encrypted`` into the response.

    ``cached`` + ``cached_at`` + ``source_search_id`` together let the
    UI render the "Cached at HH:MM" badge (design.md §6.0).
    """

    search_id: UUID
    rego: str
    cached: bool
    cached_at: datetime | None = None
    source_search_id: UUID | None = None

    match: str | None = None
    match_description: str | None = None
    statement_count: int = 0

    ppsr_details: list[dict] = Field(default_factory=list)
    ownership_history: list[dict] | None = None
    current_owner: dict | None = None
    warnings: list[dict] = Field(default_factory=list)
    basic: dict | None = None

    not_found: bool = False
    charges_cents: int | None = None
    carjam_request_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PpsrSearchSummary(BaseModel):
    """Row in the paginated search-history list.

    **Encrypted-payload safety (G31):** this model omits
    ``response_encrypted`` and every decrypted owner / debtor /
    statement field by design — the list endpoint MUST NOT leak
    plaintext PII or the encrypted blob. Only denormalised summary
    columns are exposed.

    Built from a ``PpsrSearch`` ORM row via
    ``model_config = ConfigDict(from_attributes=True)``; the encrypted
    bytes attribute on the ORM object is simply not declared here, so
    Pydantic ignores it during attribute mapping.
    """

    id: UUID
    rego: str
    match: str | None = None
    match_description: str | None = None
    statement_count: int = 0
    has_warnings: bool = False
    has_ownership_data: bool = False
    not_found: bool = False
    forgotten_at: datetime | None = None
    org_vehicle_id: UUID | None = None
    user_id: UUID
    user_display_name: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PpsrSearchListResponse(BaseModel):
    """``GET /api/v2/ppsr/searches`` — ``{ items, total }`` per project rule.

    Arrays are always wrapped in an envelope with a ``total`` count so
    the frontend can paginate without a second round-trip.
    """

    items: list[PpsrSearchSummary]
    total: int


class PpsrQuotaResponse(BaseModel):
    """``GET /api/v2/ppsr/quota``.

    Field naming follows G44 — the renamed columns are
    ``ppsr_hidden_plate_lookups_*`` (not ``money_owing_*``); the
    response surfaces them under ``hidden_plate_used`` /
    ``hidden_plate_included`` so the frontend speaks the same
    vocabulary end-to-end.

    ``resets_at`` is the org's next billing-cycle boundary (the same
    moment ``process_due_billings`` zeroes the counter); ``None`` when
    the org is not yet billable (e.g. trial without a billing date).
    """

    used: int = 0
    included: int = 0
    hidden_plate_used: int = 0
    hidden_plate_included: int = 0
    resets_at: datetime | None = None
    # Owner-lookup config flags — surfaced so the frontend can gate
    # the checkboxes without a separate admin-only config fetch.
    owner_lookups_enabled: bool = False
    s241_purpose_configured: bool = False

    model_config = ConfigDict(from_attributes=True)


__all__ = [
    "PpsrSearchOptions",
    "PpsrSearchRequest",
    "PpsrLinkVehicleRequest",
    "PpsrSearchResult",
    "PpsrSearchSummary",
    "PpsrSearchListResponse",
    "PpsrQuotaResponse",
]
