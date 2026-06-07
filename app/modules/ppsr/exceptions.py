"""Exceptions raised by ``app/modules/ppsr/service.py``.

Lives in its own file so router code can import the classes without
pulling in the rest of the service surface (which imports CarJam, Redis,
SQLAlchemy update statements, etc.).

The router maps each exception to a specific HTTP status:

  - :class:`PpsrCarjamNotConfiguredError`  → ``HTTP 422`` ``carjam_not_configured`` (G28/G49).
  - :class:`PpsrQuotaExceededError`        → ``HTTP 402`` ``ppsr_quota_exceeded``.
  - :class:`PpsrS241PurposeRequiredError`  → ``HTTP 422`` ``s241_purpose_required``.
  - :class:`PpsrOwnerLookupsDisabledError` → ``HTTP 422`` ``s241_not_authorised``.
  - :class:`PpsrSearchNotFoundError`       → ``HTTP 404`` ``search_not_found``.
  - :class:`PpsrSearchForbiddenError`      → ``HTTP 403`` ``forbidden``.
  - :class:`PpsrSearchForgottenError`      → ``HTTP 410`` ``search_forgotten`` (G29).

Refs: design.md §5; tasks.md C3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = [
    "PpsrError",
    "PpsrCarjamNotConfiguredError",
    "PpsrQuotaExceededError",
    "PpsrS241PurposeRequiredError",
    "PpsrOwnerLookupsDisabledError",
    "PpsrOwnerCheckValidationError",
    "PpsrOwnerCheckNotAllowedError",
    "PpsrSearchNotFoundError",
    "PpsrSearchForbiddenError",
    "PpsrSearchForgottenError",
]


class PpsrError(Exception):
    """Base exception for the PPSR module."""


class PpsrCarjamNotConfiguredError(PpsrError):
    """CarJam integration not configured (or ``api_key`` empty).

    Raised by :class:`~app.modules.ppsr.service.PpsrService.search` when
    the ``integration_configs[name='carjam']`` row is missing or its
    encrypted JSON payload has no ``api_key`` (G28/G49). Router maps to
    HTTP 422 ``carjam_not_configured``.
    """


class PpsrQuotaExceededError(PpsrError):
    """Org has used up its monthly PPSR allowance.

    Carries the ``used`` / ``included`` counters so the router can
    surface them in the 402 response body.
    """

    def __init__(self, used: int, included: int) -> None:
        self.used = used
        self.included = included
        super().__init__(
            f"PPSR quota exceeded: used={used} included={included}",
        )


class PpsrS241PurposeRequiredError(PpsrError):
    """Owner-lookup requested without an ``s241_purpose``.

    Either no per-request value supplied AND no
    ``s241_purpose_default`` in the org's CarJam config. Router maps to
    HTTP 422 ``s241_purpose_required``.
    """


class PpsrOwnerLookupsDisabledError(PpsrError):
    """Owner-lookup requested while ``ppsr_owner_lookups_enabled`` is
    false on the org's CarJam config (R7.3). Router maps to HTTP 422
    ``s241_not_authorised``.
    """


class PpsrOwnerCheckValidationError(PpsrError):
    """Owner-check inputs failed validation.

    Raised when the per-type owner-check fields are incomplete /
    invalid — either caught locally by the request-schema validator or
    surfaced from CarJam's ``err-owner-check-validation``. Carries the
    upstream/validation message so the router can return it in the 422
    body. Router maps to HTTP 422 ``owner_check_validation``.
    """

    def __init__(self, message: str = "owner_check_validation") -> None:
        self.message = message
        super().__init__(message)


class PpsrOwnerCheckNotAllowedError(PpsrError):
    """CarJam account lacks the ``owner_check`` API product
    (``err-api-product-not-allowed``). Router maps to HTTP 422
    ``owner_check_not_allowed`` — this is a platform-config issue, not
    user input.
    """


class PpsrSearchNotFoundError(PpsrError):
    """No ``ppsr_searches`` row for the given id."""


class PpsrSearchForbiddenError(PpsrError):
    """Caller is neither an admin nor the original searcher."""


class PpsrSearchForgottenError(PpsrError):
    """Detail/export requested on a row whose payload was forgotten.

    Router maps to HTTP 410 with ``forgotten_at`` in the body so the
    UI can render "(payload forgotten)" without losing the audit trail
    (G26/G29).
    """

    def __init__(self, forgotten_at: datetime) -> None:
        self.forgotten_at = forgotten_at
        super().__init__(f"PPSR search payload forgotten at {forgotten_at.isoformat()}")
