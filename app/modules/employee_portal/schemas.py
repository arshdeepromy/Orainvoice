"""Organisation Employee Portal Pydantic request/response schemas.

Request/response contracts for the ``/e/api/*`` portal surface implemented in
``app/modules/employee_portal/router.py``. The portal is a cookie-authenticated
near-clone of the B2B Fleet Portal; these schemas mirror the structure of
``app/modules/fleet_portal/schemas.py`` (a strict request base that rejects
unknown fields, explicit response models) but cover only the employee-portal
endpoints.

Error envelope convention (matches the staff onboarding public API): rejecting
responses carry ``{"message": <human-readable>, "code": <machine code>}`` — for
``HTTPException`` this lands under ``detail``; for the login endpoint (which must
persist a failed-attempt increment / audit row before responding) the body is
returned directly as ``{"message", "code"}`` via ``JSONResponse`` so the request
transaction commits rather than rolling back on a raised exception.

Implements: Organisation Employee Portal task 10.1 — Requirements 6.1, 6.2,
6.3, 6.4.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _StrictBase(BaseModel):
    """Base for request bodies — rejects unknown fields with HTTP 422."""

    model_config = ConfigDict(extra="forbid")


class LoginRequest(_StrictBase):
    """``POST /e/api/auth/login`` body.

    ``slug`` selects the organisation whose branded portal is being logged into;
    ``email`` is normalised (trim + lowercase) server-side before lookup so the
    match is case-insensitive (mirrors the ``lower(email)`` partial unique index).
    ``email`` is a plain constrained string rather than ``EmailStr`` so a
    malformed address follows the same generic ``401 invalid_credentials`` path as
    a non-matching one (anti-enumeration, R6.4) instead of diverging to a 422.
    """

    slug: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class AcceptInviteRequest(_StrictBase):
    """``POST /e/api/auth/accept-invite/{token}`` body.

    ``new_password`` is deliberately an unconstrained string: the 8..128
    length rule is enforced by ``account_service.accept_invite`` so an invalid
    length surfaces as the documented ``422 password_length`` envelope (R5.6)
    rather than a generic Pydantic validation error with a different shape.
    """

    new_password: str


class PasswordResetRequest(_StrictBase):
    """``POST /e/api/auth/password/reset-request`` body.

    ``slug`` selects the organisation whose branded portal the reset is for;
    ``email`` is the address to look up. Both are plain constrained strings
    (``email`` is **not** ``EmailStr``) so a malformed address, an unknown slug,
    and a non-matching email all follow the single anti-enumeration path that
    returns the byte-for-byte identical ``200`` confirmation (R14.1) instead of
    diverging to a ``422`` that would reveal which field was wrong.
    """

    slug: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=1, max_length=320)


class PasswordResetCompleteRequest(_StrictBase):
    """``POST /e/api/auth/password/reset`` body.

    ``new_password`` is deliberately an unconstrained string: the 8..128
    length rule is enforced by ``account_service.complete_reset`` so an invalid
    length surfaces as the documented ``422 password_length`` envelope (R14.7)
    rather than a generic Pydantic validation error with a different shape.
    """

    token: str = Field(min_length=1)
    new_password: str


class LoginResponse(BaseModel):
    """``200`` body for a successful login (R6.3).

    Returns only the portal user's own identity — never any other org/staff
    data. ``first_name`` is sourced from the linked ``staff_members`` row.
    """

    portal_user_id: UUID
    email: str
    first_name: str | None = None
    staff_id: UUID


class BrandingResponse(BaseModel):
    """``200`` body for ``GET /e/api/branding/{slug}`` (R8.1, R13.1, R13.4).

    Backs the public, no-session branded login page. Returns ONLY the
    organisation's display name plus its Portal_Branding fields sourced from the
    existing Org_Settings (R13.4) — no other org data is exposed. The colour and
    logo fields are nullable: when an org has not configured them the portal
    renders a neutral default presentation (R13.2). This shape is only ever
    returned when the slug resolves AND the portal is enabled; an unknown slug or
    a disabled portal both yield a neutral ``404 portal_unavailable`` with no
    body fields, so org existence is never revealed (R8.3).
    """

    org_name: str | None = None
    logo_url: str | None = None
    primary_colour: str | None = None
    secondary_colour: str | None = None


class PortalBranding(BaseModel):
    """Portal_Branding fields needed to render a branded login (R9.5, R13.4).

    Only the logo + brand colours sourced from the existing Org_Settings — never
    any other organisation data. All fields are nullable: an org that has not
    configured them renders a neutral default (R13.2). The organisation name is
    carried alongside this object (on the match/candidate) rather than inside it.
    """

    logo_url: str | None = None
    primary_colour: str | None = None
    secondary_colour: str | None = None


class PortalResolveMatch(BaseModel):
    """A single resolved organisation for ``GET /api/v2/public/portal-resolve``.

    Returned (wrapped as ``{"match": ...}``) when the lookup resolves to exactly
    one organisation that has the requested portal type enabled (R9.1). Carries
    only the org id (needed by the mobile app to address the branded login), the
    display name, and the Portal_Branding — no other org data is exposed (R9.5).
    """

    org_id: UUID
    org_name: str
    branding: PortalBranding


class PortalResolveCandidate(BaseModel):
    """A disambiguation candidate for ``GET /api/v2/public/portal-resolve``.

    Returned (wrapped as ``{"candidates": [...]}``, max 10) when more than one
    organisation matches the supplied **name** for the requested portal type
    (R9.4). Deliberately carries ONLY the organisation name + Portal_Branding —
    not the org id — so an ambiguous name is never auto-resolved to a single
    identity and the response exposes nothing beyond what a branded picker needs.
    """

    org_name: str
    branding: PortalBranding


class ProfileResponse(BaseModel):
    """``200`` body for ``GET /e/api/profile`` (R7.1, R7.5).

    The authenticated Portal_User's **own** Staff_Member profile, sourced from
    the ``staff_members`` row for the session's ``staff_id`` (RLS-scoped to the
    session's ``org_id``). Carries only the staff member's own identity, contact
    details, and employment basics — never any other staff member's record, and
    never any cross-org data (own record only, R7.1/R7.5; R16.4 isolation).

    The PII fields ``ird_number`` and ``bank_account_number`` are returned in
    their **masked** display form (e.g. ``"***123"`` / ``"**-****-****12-**"``)
    produced by ``mask_ird`` / ``mask_bank_account`` — the plaintext is decrypted
    server-side only to mask it and is never placed on the wire. Both are
    nullable: ``None`` when no value is stored (or it could not be decrypted).
    """

    model_config = ConfigDict(from_attributes=True)

    staff_id: UUID
    first_name: str | None = None
    last_name: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    employee_id: str | None = None
    employment_basis: str | None = None
    employment_type: str | None = None
    working_arrangement: str | None = None
    employment_start_date: date | None = None
    tax_code: str | None = None
    kiwisaver_enrolled: bool | None = None
    ird_number: str | None = None
    bank_account_number: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class RosterEntry(BaseModel):
    """A single schedule entry in the authenticated staff member's roster.

    Mirrors the entry shape returned by the existing public staff roster viewer
    (``app/modules/staff/public_router.py`` ``view_staff_roster``) so the portal
    reuses that surface's contract rather than inventing a new one (R7.4). Only
    the display-relevant fields are exposed — never the owning ``staff_id`` /
    ``org_id`` (the request is already own-scoped) or internal linkage ids.
    """

    start_time: datetime | None = None
    end_time: datetime | None = None
    title: str | None = None
    notes: str | None = None
    entry_type: str | None = None


class RosterResponse(BaseModel):
    """``200`` body for ``GET /e/api/roster`` (R7.1, R7.2, R7.4).

    The authenticated Portal_User's **own** weekly roster, sourced from the same
    ``schedule_entries`` data path the public staff roster viewer uses
    (``app/modules/staff/public_router.py``) — no duplicate data store (R7.4).
    The entries are scoped to the session's ``staff_id`` + ``org_id`` (own roster
    only, R7.1) for the UTC week window ``week_start .. week_start + 7 days``,
    ordered by ``start_time``. ``week_start`` echoes the resolved week (the
    supplied query param, or the current week's Monday when omitted).
    """

    staff_id: UUID
    week_start: date
    week_end: date
    entries: list[RosterEntry] = Field(default_factory=list)


__all__ = [
    "LoginRequest",
    "LoginResponse",
    "AcceptInviteRequest",
    "PasswordResetRequest",
    "PasswordResetCompleteRequest",
    "BrandingResponse",
    "PortalBranding",
    "PortalResolveMatch",
    "PortalResolveCandidate",
    "ProfileResponse",
    "RosterEntry",
    "RosterResponse",
]
