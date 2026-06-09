"""Custom exception types for the customer reminder consent feature.

These exceptions are raised by the consent helpers and customer service
to signal consent-related preconditions that the router layer maps to
specific HTTP status codes:

* :class:`RemindersConsentRequiredError` -> HTTP 409 with body
  ``{"error": "consent_required", "missing": [...]}`` when an attempt to
  enable a ``(category, channel)`` reminder pair is made without a
  covering consent record.
* :class:`RemindersRevocationError` -> HTTP 422 when a revocation request
  references a ``(category, channel)`` pair that is not currently active.

Refs:
    Requirements 2.12, 2.13 (consent gate on PUT /customers/{id}/reminders)
    Requirement 3 (revocation guard)
"""

from __future__ import annotations

__all__ = [
    "RemindersConsentRequiredError",
    "RemindersRevocationError",
]


class RemindersConsentRequiredError(Exception):
    """Raised when enabling a reminder pair requires a covering consent record.

    The ``missing`` payload is the wire contract for the HTTP 409 response
    body produced by ``PUT /customers/{id}/reminders``. Each entry in the
    list is a dict with exactly two keys:

    * ``"category"`` - one of ``"service_due"``, ``"wof_expiry"``,
      ``"cof_expiry"``, ``"registration_expiry"``.
    * ``"channel"`` - one of ``"sms"`` or ``"email"``.

    Note that ``"both"`` is never carried directly in ``missing``: the
    ``coverage_for`` helper expands a ``"both"`` channel into two separate
    ``(category, "sms")`` and ``(category, "email")`` entries before this
    exception is constructed.
    """

    def __init__(self, *, missing: list[dict]) -> None:
        self.missing = missing
        super().__init__(f"Reminder consent required for {missing}")


class RemindersRevocationError(Exception):
    """Raised when a revocation references a non-active ``(category, channel)`` pair.

    Mapped to HTTP 422 by the customer router so the frontend can surface
    a "nothing to revoke" message to the operator without rolling back
    any other state.
    """
