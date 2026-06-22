"""Side-effect-free validators and pure helpers for staff onboarding.

Every function in this module is **pure**: no I/O, no DB access, no network,
and no exceptions raised for ordinary (invalid) input — invalid input simply
yields ``False`` / a default. This makes the whole module property-testable
without a database and lets the same rules be mirrored client-side.

The functions here back the public onboarding submit/draft endpoints and the
admin onboarding-link status endpoint:

- ``validate_nz_bank_account`` / ``validate_ird_length`` / ``ird_mod11_ok``
  / ``validate_emergency_contact`` / ``validate_documents`` /
  ``validate_visa_expiry`` — field validators (R4–R8).
- ``compute_completion_percentage`` — deterministic, total, bounded,
  monotonic completion score (R13.3, R13.4).
- ``onboarding_lifecycle_label`` — pure admin lifecycle label (R13.1).
- ``classify_token_state`` / ``token_state_error_code`` — pure public
  token-state classifier and its error-code mapping, the single source of
  truth for prefill/draft/submit and the admin status endpoint (R2.4, R2.6,
  R10.1, R11.3, R11.4).
- ``admin_token_status_label`` — coarse admin status label (R10.1, R13.1).
- ``humanize_onboarding_error`` — total mapping from machine error code to a
  human-readable, stack-trace-free sentence (R14.1–R14.5).

Validates: Requirements 2.4, 2.6, 4.3, 5.2, 6.2, 6.3, 7.2, 7.3, 8.3, 10.1,
11.3, 11.4, 13.1, 13.3, 13.4, 14.1, 14.2, 14.3, 14.4, 14.5.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# NZ bank account: 2-4-7-2 or 2-4-7-3 (bank-branch-account-suffix).
_NZ_BANK_ACCOUNT_RE = re.compile(r"^\d{2}-\d{4}-\d{7}-\d{2,3}$")

# Residency types (mirrors schemas.ResidencyType) that require a visa expiry.
_VISA_RESIDENCY_TYPES = frozenset({"work_visa", "student_visa"})

# Document upload limits (R7.2, R7.3). Narrower allow-list than the shared
# ComplianceFileStorage (which also accepts GIF/Word); the onboarding form is
# restricted to PDF/JPEG/PNG only.
ACCEPTED_DOCUMENT_MIME_TYPES = frozenset(
    {"application/pdf", "image/jpeg", "image/png"}
)
MAX_DOCUMENT_COUNT = 3
MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

# Canonical onboarding error codes. ``humanize_onboarding_error`` returns a
# non-empty human-readable message for every one of these (and for any unknown
# code, falling back to the generic server-error message — so it is total).
ONBOARDING_ERROR_CODES: tuple[str, ...] = (
    # Token-state rejections (R14.4).
    "onboarding_token_not_found",
    "onboarding_token_expired",
    "onboarding_token_revoked",
    "onboarding_token_consumed",
    "onboarding_token_staff_inactive",
    # Admin send/resend gate (R1.2).
    "onboarding_email_required",
    # Validation failure (R9.1, R14.4).
    "validation_failed",
    # Draft guards (R12.5).
    "draft_too_large",
    # Encryption failure (R9.7, R14.4).
    "encryption_failed",
    # Email-send failure (R3.6, R14.4).
    "send_failed",
    # Unexpected server error (R14.5).
    "server_error",
)

_ERROR_MESSAGES: dict[str, str] = {
    "onboarding_token_not_found": (
        "This onboarding link is not valid. Please check the link in your "
        "email, or contact your employer for a new one."
    ),
    "onboarding_token_expired": (
        "This onboarding link has expired. Please contact your employer to "
        "have a new link sent to you."
    ),
    "onboarding_token_revoked": (
        "This onboarding link has been cancelled. Please contact your "
        "employer for a new link."
    ),
    "onboarding_token_consumed": (
        "This onboarding form has already been submitted. There is nothing "
        "more to do — contact your employer if you need to make changes."
    ),
    "onboarding_token_staff_inactive": (
        "This onboarding link is no longer active. Please contact your "
        "employer for assistance."
    ),
    "onboarding_email_required": (
        "An email address is required to send an onboarding link. Add an "
        "email address for this staff member and try again."
    ),
    "validation_failed": (
        "Some of the details you entered need attention. Please review the "
        "highlighted fields and try again."
    ),
    "draft_too_large": (
        "Your saved progress is too large to store. Please remove some "
        "information and try saving again."
    ),
    "encryption_failed": (
        "We could not securely save your details, so nothing was stored. "
        "Please try submitting the form again."
    ),
    "send_failed": (
        "The staff record was saved, but we could not send the onboarding "
        "email. You can resend the onboarding link from the staff member's "
        "page."
    ),
    "server_error": (
        "Something went wrong on our end. No changes were made — please try "
        "again in a moment."
    ),
}

# ---------------------------------------------------------------------------
# Public token-state classification (R2.4, R2.6, R10.1, R11.3, R11.4)
# ---------------------------------------------------------------------------

# The six mutually-exclusive outcomes of classifying an onboarding token for
# the PUBLIC surface (prefill / draft-save / submit). ``classify_token_state``
# is the single source of truth: every public response (and the admin status
# endpoint's underlying state) derives from exactly one of these.
TokenState = Literal[
    "not_found",      # no row for hash(token)               -> 404
    "revoked",        # status == "revoked"                  -> 410
    "consumed",       # status == "consumed"                 -> 410
    "expired",        # pending AND expires_at <= now        -> 410
    "staff_inactive", # pending, not expired, staff inactive -> 410
    "valid",          # pending, not expired, staff active   -> 200 / proceed
]

# Every non-"valid" TokenState maps to exactly one public error code (one of
# the ONBOARDING_ERROR_CODES). "valid" has no error code (the request proceeds).
_TOKEN_STATE_ERROR_CODES: dict[str, str] = {
    "not_found": "onboarding_token_not_found",
    "revoked": "onboarding_token_revoked",
    "consumed": "onboarding_token_consumed",
    "expired": "onboarding_token_expired",
    "staff_inactive": "onboarding_token_staff_inactive",
}


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def _get(source: Any, key: str) -> Any:
    """Read ``key`` from a Mapping or an attribute-bearing object (or None)."""
    if source is None:
        return None
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _text_present(value: Any) -> bool:
    """True when ``value`` is a non-empty (after-strip) textual value."""
    if value is None:
        return False
    return str(value).strip() != ""


def _truthy_flag(value: Any) -> bool:
    """Coerce a draft boolean-ish flag (e.g. ``has_ird``) to bool."""
    return bool(value)


# ---------------------------------------------------------------------------
# Field validators (R4–R8)
# ---------------------------------------------------------------------------

def validate_nz_bank_account(s: Any) -> bool:
    """True iff *s* matches the NZ bank account format (2-4-7-2 / 2-4-7-3).

    Validates: Requirements 5.2.
    """
    if not isinstance(s, str):
        return False
    return _NZ_BANK_ACCOUNT_RE.fullmatch(s.strip()) is not None


def validate_ird_length(s: Any) -> bool:
    """True iff *s* is exactly 8 or 9 digits after stripping separators.

    Hyphens and spaces are stripped; any remaining non-digit characters make
    the value invalid. This is the hard length gate (R6.2, R6.3); the mod-11
    checksum is only an advisory (see :func:`ird_mod11_ok`).

    Validates: Requirements 6.2, 6.3.
    """
    if not isinstance(s, str):
        return False
    stripped = s.replace("-", "").replace(" ", "").strip()
    return stripped.isdigit() and len(stripped) in (8, 9)


def ird_mod11_ok(s: Any) -> bool:
    """Advisory mod-11 IRD checksum check (non-blocking).

    Thin wrapper around ``app.modules.ledger.service.validate_ird_number``.
    Imported lazily so this module stays import-light and side-effect-free.
    Returns ``False`` for any input the checksum validator rejects (including
    non-string / empty input) without raising.

    Validates: Requirements 6.2, 6.3 (advisory).
    """
    if not isinstance(s, str) or s.strip() == "":
        return False
    try:
        from app.modules.ledger.service import validate_ird_number

        return bool(validate_ird_number(s))
    except Exception:
        # Advisory only — never let a checksum check break the flow.
        return False


def validate_emergency_contact(name: Any, phone: Any) -> bool:
    """True iff emergency contact name and phone are both present or both empty.

    Validates: Requirements 4.3.
    """
    return _text_present(name) == _text_present(phone)


def _document_mime_and_size(item: Any) -> tuple[Any, Any]:
    """Extract ``(mime_type, size_bytes)`` from a heterogeneous file descriptor.

    Supports dicts (``content_type``/``mime_type``/``mime`` + ``size``/
    ``size_bytes``), ``(mime, size)`` tuples/lists, and objects exposing
    ``content_type``/``mime_type`` and ``size``/``size_bytes`` attributes
    (e.g. an UploadFile-like wrapper).
    """
    if isinstance(item, Mapping):
        mime = item.get("content_type") or item.get("mime_type") or item.get("mime")
        size = item.get("size") if item.get("size") is not None else item.get("size_bytes")
        return mime, size
    if isinstance(item, (tuple, list)) and len(item) >= 2:
        return item[0], item[1]
    mime = getattr(item, "content_type", None) or getattr(item, "mime_type", None)
    size = getattr(item, "size", None)
    if size is None:
        size = getattr(item, "size_bytes", None)
    return mime, size


def validate_documents(files: Any) -> bool:
    """True iff the staged documents satisfy the onboarding upload constraints.

    Constraints (R7.2, R7.3): at most 3 files; each MIME type in
    {PDF, JPEG, PNG}; each at most 10 MB. An empty / omitted set is valid
    (documents are optional, R7.5).

    Validates: Requirements 7.2, 7.3.
    """
    if files is None:
        return True
    try:
        items = list(files)
    except TypeError:
        return False
    if len(items) > MAX_DOCUMENT_COUNT:
        return False
    for item in items:
        mime, size = _document_mime_and_size(item)
        if not isinstance(mime, str) or mime.lower() not in ACCEPTED_DOCUMENT_MIME_TYPES:
            return False
        if not isinstance(size, int) or isinstance(size, bool):
            return False
        if size < 0 or size > MAX_DOCUMENT_SIZE_BYTES:
            return False
    return True


def validate_visa_expiry(
    residency_type: Any,
    expiry_date: Any,
    today: date | None = None,
) -> bool:
    """True iff the visa-expiry field is acceptable for the given residency type.

    Visa residency types (``work_visa`` / ``student_visa``) **require** a valid
    expiry date: it must be present AND strictly after ``today``. A missing,
    past-dated, or current-dated value is **invalid** and blocks submission
    (R8.3). Any non-visa residency type is always valid regardless of the date
    field. ``today`` defaults to ``date.today()`` and may be injected for
    deterministic testing.

    Validates: Requirements 8.2, 8.3.
    """
    if residency_type not in _VISA_RESIDENCY_TYPES:
        return True
    if expiry_date is None:
        return False
    if isinstance(expiry_date, datetime):
        expiry_date = expiry_date.date()
    if not isinstance(expiry_date, date):
        return False
    ref = today if today is not None else date.today()
    return expiry_date > ref


# ---------------------------------------------------------------------------
# Completion percentage (R13.3, R13.4)
# ---------------------------------------------------------------------------

def is_personal_complete(draft: Any) -> bool:
    """Personal section complete: last name AND phone both present."""
    return _text_present(_get(draft, "last_name")) and _text_present(_get(draft, "phone"))


def is_bank_complete(draft: Any) -> bool:
    """Bank section complete: bank account present (or ``has_bank`` on resume)."""
    return _text_present(_get(draft, "bank_account_number")) or _truthy_flag(
        _get(draft, "has_bank")
    )


def is_ird_complete(draft: Any) -> bool:
    """IRD/Tax section complete: IRD present (or ``has_ird``) AND tax code set."""
    has_ird = _text_present(_get(draft, "ird_number")) or _truthy_flag(
        _get(draft, "has_ird")
    )
    return has_ird and _text_present(_get(draft, "tax_code"))


def is_residency_complete(draft: Any) -> bool:
    """Residency section complete: type set; visa types also need an expiry date."""
    residency_type = _get(draft, "residency_type")
    if not _text_present(residency_type):
        return False
    if residency_type in _VISA_RESIDENCY_TYPES:
        return _get(draft, "visa_expiry_date") is not None and _text_present(
            _get(draft, "visa_expiry_date")
        )
    return True


def is_documents_complete(draft: Any) -> bool:
    """Documents section complete: at least one document staged."""
    count = _get(draft, "documents_staged_count")
    if isinstance(count, bool) or not isinstance(count, int):
        return False
    return count > 0


def compute_completion_percentage(draft: Any) -> int:
    """Return a deterministic, section-weighted completion percentage in [0, 100].

    The five form sections (Personal, Bank, IRD/Tax, Residency, Documents) are
    each weighted equally at 20%. Each section predicate is a crisp boolean over
    the draft fields, so the result is:

    - **deterministic** — the same draft always yields the same integer;
    - **total** — defined for any draft, including ``None``, empty, or partial;
    - **bounded** — always in ``[0, 100]``;
    - **monotonic non-decreasing** — every section predicate is monotone in
      field *presence* (adding a value never flips a section from complete to
      incomplete), so filling additional fields can only raise or hold the
      percentage, never lower it.

    Validates: Requirements 13.3, 13.4.
    """
    sections_complete = (
        int(is_personal_complete(draft))
        + int(is_bank_complete(draft))
        + int(is_ird_complete(draft))
        + int(is_residency_complete(draft))
        + int(is_documents_complete(draft))
    )
    return sections_complete * 20


# ---------------------------------------------------------------------------
# Admin lifecycle label (R13.1)
# ---------------------------------------------------------------------------

def onboarding_lifecycle_label(row: Any, now: datetime) -> str:
    """Return the admin lifecycle label for an onboarding token row.

    Evaluated in strict precedence order so the result is **total** and
    **single-valued** (exactly one of six labels, never blank/ambiguous):

        row is None                       -> "none"
        status == "revoked"               -> "revoked"
        status == "consumed"              -> "completed"
        expires_at <= now (pending)       -> "expired"
        draft_updated_at is not None       -> "in_progress"
        otherwise                          -> "not_started"

    This is intentionally kept separate from ``classify_token_state`` (the
    public 404/410 helper): this label additionally factors in draft presence
    (``not_started`` vs ``in_progress``).

    Validates: Requirements 13.1.
    """
    if row is None:
        return "none"

    status = _get(row, "status")
    if status == "revoked":
        return "revoked"
    if status == "consumed":
        return "completed"

    expires_at = _get(row, "expires_at")
    if expires_at is not None and expires_at <= now:
        return "expired"

    if _get(row, "draft_updated_at") is not None:
        return "in_progress"

    return "not_started"


# ---------------------------------------------------------------------------
# Public token-state classification (R2.4, R2.6, R10.1, R11.3, R11.4)
# ---------------------------------------------------------------------------

def classify_token_state(
    row: Any,
    now: datetime,
    staff_is_active: bool,
) -> TokenState:
    """Classify an onboarding token row into exactly one public ``TokenState``.

    This is the **single source of truth** for both the public router
    (prefill / draft-save / submit) and the admin status endpoint. It is pure:
    no I/O, no DB access, no exceptions for ordinary input. Evaluated in strict
    precedence order so the result is **total** and **single-valued**:

        row is None                            -> "not_found"
        status == "revoked"                    -> "revoked"
        status == "consumed"                   -> "consumed"
        pending AND expires_at <= now          -> "expired"
        pending, not expired, staff inactive   -> "staff_inactive"
        pending, not expired, staff active     -> "valid"

    ``expires_at`` is normally NOT NULL; a missing/None ``expires_at`` is treated
    as "not expired" so the function stays total. ``staff_is_active`` is supplied
    by the caller (read from the staff record), keeping this helper DB-free.

    Use :func:`token_state_error_code` to map a non-"valid" state to its public
    error code (one of the ``ONBOARDING_ERROR_CODES``).

    Validates: Requirements 2.4, 2.6, 10.1, 11.3, 11.4.
    """
    if row is None:
        return "not_found"

    status = _get(row, "status")
    if status == "revoked":
        return "revoked"
    if status == "consumed":
        return "consumed"

    expires_at = _get(row, "expires_at")
    if expires_at is not None and expires_at <= now:
        return "expired"

    if not staff_is_active:
        return "staff_inactive"

    return "valid"


def token_state_error_code(state: TokenState) -> str | None:
    """Map a ``TokenState`` to its public error code, or ``None`` for "valid".

    Total over the six ``TokenState`` values: every rejecting state maps to one
    of the ``ONBOARDING_ERROR_CODES`` (``onboarding_token_not_found`` /
    ``_revoked`` / ``_consumed`` / ``_expired`` / ``_staff_inactive``); "valid"
    (and any unexpected value) yields ``None`` so the request proceeds.

    Validates: Requirements 2.4, 2.6, 11.3, 11.4.
    """
    return _TOKEN_STATE_ERROR_CODES.get(state)


def admin_token_status_label(row: Any, now: datetime) -> str:
    """Return the admin status-endpoint label for an onboarding token row.

    A coarser, draft-agnostic view than :func:`onboarding_lifecycle_label`:
    it reports the deliberate lifecycle plus computed expiry, without the
    ``not_started`` / ``in_progress`` draft-presence distinction. Evaluated in
    strict precedence order so it is **total** and **single-valued**:

        row is None                       -> "none"
        status == "revoked"               -> "revoked"
        status == "consumed"              -> "consumed"
        pending AND expires_at <= now     -> "expired"
        otherwise (pending, not expired)  -> "pending"

    Validates: Requirements 10.1, 13.1.
    """
    if row is None:
        return "none"

    status = _get(row, "status")
    if status == "revoked":
        return "revoked"
    if status == "consumed":
        return "consumed"

    expires_at = _get(row, "expires_at")
    if expires_at is not None and expires_at <= now:
        return "expired"

    return "pending"


# ---------------------------------------------------------------------------
# Humanized error mapping (R14.1–R14.5)
# ---------------------------------------------------------------------------

def humanize_onboarding_error(code: Any) -> str:
    """Map a machine error *code* to a non-empty human-readable sentence.

    Mirrors the ``humanize_restore_db_error`` precedent: the returned message
    never contains raw database or exception text (R14.5). The function is
    **total** — every known code in :data:`ONBOARDING_ERROR_CODES` maps to a
    distinct message, and any unrecognised / non-string code falls back to the
    generic ``server_error`` message so a message is always available.

    Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5.
    """
    if isinstance(code, str):
        message = _ERROR_MESSAGES.get(code)
        if message:
            return message
    return _ERROR_MESSAGES["server_error"]
