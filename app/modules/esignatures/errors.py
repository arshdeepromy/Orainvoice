"""Central error humanization for the esignatures module.

Every error returned from ``/api/v2/esign`` (and the admin Documenso
endpoints) uses one humanized shape (R16)::

    { "detail": { "message": "...human-readable...", "code": "optional_code" } }

``humanize_esign_error(exc) -> EsignError`` is the **central mapper** from an
internal exception to that ``{ message, code }`` shape. It mirrors the existing
``humanize_restore_db_error`` / ``humanize_onboarding_error`` precedent: the
returned message is **always** a non-empty, human-readable sentence and
**never** contains raw database text or raw exception text (R15.5). The mapper
is **total** — any unrecognised exception falls back to the generic
``server_error`` message so a safe message is always available.

The canonical ``code -> message`` and ``code -> HTTP status`` tables are taken
directly from the design's Error Handling table so the router/service can fold
a code straight into the response and pick the right status without
re-deriving either.

Pure logic (no I/O); directly unit/property testable (Property 24, task 7.2).

Refs: requirements 2.2, 12.1, 12.2, 12.3, 15.5, 16.1, 16.2, 16.3.
"""

from __future__ import annotations

from typing import Any

from app.integrations.documenso import (
    DocumensoApiError,
    DocumensoError,
    DocumensoNotConfiguredError,
)
from app.modules.esignatures.field_validation import (
    CODE_FIELD_OUT_OF_BOUNDS,
    CODE_FIELD_UNASSIGNED,
    CODE_INVALID_FIELD_TYPE,
    CODE_SIGNATURE_FIELD_MISSING,
)
from app.modules.esignatures.schemas import EsignError

# ---------------------------------------------------------------------------
# Machine-readable error codes (design "Error Handling" table)
# ---------------------------------------------------------------------------

CODE_MODULE_DISABLED = "module_disabled"
CODE_FORBIDDEN = "forbidden"
CODE_NO_RECIPIENTS = "no_recipients"
CODE_NOT_PDF = "not_pdf"
CODE_INVALID_RECIPIENT_EMAIL = "invalid_recipient_email"
CODE_NO_SIGNERS = "no_signers"
CODE_SIGNATURE_FIELD_FAILED = "signature_field_failed"
CODE_INTEGRATION_NOT_CONFIGURED = "integration_not_configured"
CODE_AUTO_PROVISION_FAILED = "auto_provision_failed"
CODE_AUTO_PROVISION_UNAVAILABLE = "auto_provision_unavailable"
CODE_DOCUMENSO_ERROR = "documenso_error"
CODE_NOT_VOIDABLE = "not_voidable"
CODE_NOT_FOUND = "not_found"
CODE_FILTER_UNAVAILABLE = "filter_unavailable"
CODE_SERVER_ERROR = "server_error"

# --- Expanded-contract codes (edit-after-send R13, dependencies R14,
# signing-order R15, templates R17). Registered in BOTH tables below so the
# edit, dependency, signing-order, and template paths reuse the humanized
# ``{ message, code }`` shape via ``esign_error`` / ``status_for_code``.
CODE_NOT_EDITABLE = "not_editable"
CODE_DEPENDENCY_CYCLE = "dependency_cycle"
CODE_DEPENDENCY_SELF = "dependency_self"
CODE_TEMPLATE_NOT_FOUND = "template_not_found"
CODE_TEMPLATE_ROLE_UNMAPPED = "template_role_unmapped"
CODE_INVALID_SIGNING_ORDER = "invalid_signing_order"

#: code -> human-readable message. Messages describe the problem and, where
#: helpful, the corrective action (R16.1). None contain raw DB/exception text.
ESIGN_ERROR_MESSAGES: dict[str, str] = {
    CODE_MODULE_DISABLED: "The Agreements module is not enabled for your organisation.",
    CODE_FORBIDDEN: "You don't have permission to send or void agreements.",
    CODE_NO_RECIPIENTS: "Add at least one recipient before sending.",
    CODE_NOT_PDF: "The document must be a PDF file.",
    CODE_INVALID_RECIPIENT_EMAIL: "One of the recipient email addresses is not valid.",
    CODE_NO_SIGNERS: (
        "Add at least one signer before sending. Viewers can't sign the "
        "document on their own."
    ),
    CODE_SIGNATURE_FIELD_FAILED: (
        "We couldn't add a signature field for one of the signers, so the "
        "agreement wasn't sent. Please try again."
    ),
    CODE_INTEGRATION_NOT_CONFIGURED: (
        "The e-signature integration hasn't been configured yet. "
        "Ask a platform admin to set it up."
    ),
    CODE_AUTO_PROVISION_FAILED: (
        "We couldn't finish setting up Documenso automatically. Any progress "
        "was saved — please complete the connection manually."
    ),
    CODE_AUTO_PROVISION_UNAVAILABLE: (
        "Automatic setup is turned off in this environment. Please configure "
        "the connection manually."
    ),
    CODE_DOCUMENSO_ERROR: (
        "We couldn't reach the signing service. The agreement was saved with "
        "an error status — please try again."
    ),
    CODE_NOT_VOIDABLE: "This agreement can no longer be voided.",
    CODE_NOT_FOUND: "Agreement not found.",
    CODE_FILTER_UNAVAILABLE: "We couldn't apply that status filter.",
    CODE_SERVER_ERROR: "Something went wrong handling your request.",
    # --- Field_Set validation codes (field placement, all HTTP 422) -------
    # Defined as constants in ``field_validation.py``; registered here so the
    # service can raise them via ``esign_error(code, message=...)`` /
    # ``status_for_code(code)``. The messages below are leak-free fallbacks —
    # ``validate_field_set`` supplies a more specific humanized message (naming
    # the offending field by page or the unsatisfied signer by name) which the
    # service passes through verbatim.
    CODE_FIELD_UNASSIGNED: (
        "One of the fields isn't assigned to a recipient. Assign it before sending."
    ),
    CODE_FIELD_OUT_OF_BOUNDS: (
        "One of the fields extends past the edge of the page. "
        "Move it fully onto the page."
    ),
    CODE_INVALID_FIELD_TYPE: "One of the fields has an unsupported type.",
    CODE_SIGNATURE_FIELD_MISSING: (
        "Add a signature field for each signer before sending."
    ),
    # --- Expanded-contract messages (R13/R14/R15/R17) --------------------
    CODE_NOT_EDITABLE: (
        "This agreement can no longer be edited because signing has begun or "
        "the document is finished. Void it and create a new one to change the "
        "fields."
    ),
    CODE_DEPENDENCY_CYCLE: (
        "Those field dependencies form a loop. Remove the conflicting "
        "dependency and try again."
    ),
    CODE_DEPENDENCY_SELF: (
        "That dependency would create a loop. A field can't ultimately depend "
        "on itself."
    ),
    CODE_TEMPLATE_NOT_FOUND: "Template not found.",
    CODE_TEMPLATE_ROLE_UNMAPPED: (
        "Assign every template role to a recipient before applying the template."
    ),
    CODE_INVALID_SIGNING_ORDER: (
        "The signing order is invalid. Give each signer a distinct position."
    ),
}

#: code -> HTTP status code (design "Error Handling" table). The esign module
#: gate deliberately uses 403 (not the staff module's 404).
ESIGN_ERROR_STATUS: dict[str, int] = {
    CODE_MODULE_DISABLED: 403,
    CODE_FORBIDDEN: 403,
    CODE_NO_RECIPIENTS: 422,
    CODE_NOT_PDF: 422,
    CODE_INVALID_RECIPIENT_EMAIL: 422,
    CODE_NO_SIGNERS: 422,
    CODE_SIGNATURE_FIELD_FAILED: 422,
    CODE_INTEGRATION_NOT_CONFIGURED: 503,
    CODE_AUTO_PROVISION_FAILED: 502,
    CODE_AUTO_PROVISION_UNAVAILABLE: 200,
    CODE_DOCUMENSO_ERROR: 502,
    CODE_NOT_VOIDABLE: 409,
    CODE_NOT_FOUND: 404,
    CODE_FILTER_UNAVAILABLE: 200,
    CODE_SERVER_ERROR: 500,
    # Field_Set validation codes — all HTTP 422 (R6.6).
    CODE_FIELD_UNASSIGNED: 422,
    CODE_FIELD_OUT_OF_BOUNDS: 422,
    CODE_INVALID_FIELD_TYPE: 422,
    CODE_SIGNATURE_FIELD_MISSING: 422,
    # Expanded-contract codes (R13/R14/R15/R17).
    CODE_NOT_EDITABLE: 422,
    CODE_DEPENDENCY_CYCLE: 422,
    CODE_DEPENDENCY_SELF: 422,
    CODE_TEMPLATE_NOT_FOUND: 404,
    CODE_TEMPLATE_ROLE_UNMAPPED: 422,
    CODE_INVALID_SIGNING_ORDER: 422,
}


def esign_error(code: str, *, message: str | None = None) -> EsignError:
    """Build an :class:`EsignError` for a known ``code``.

    ``message`` overrides the canonical message for the code when the caller
    has a more specific (already-humanized, leak-free) sentence — e.g. the
    recipient validators identify the offending recipient by name. When
    ``message`` is omitted (or ``code`` is unknown) the canonical message is
    used, falling back to the generic ``server_error`` message so a non-empty
    human-readable message is always returned.
    """
    canonical = ESIGN_ERROR_MESSAGES.get(code)
    if canonical is None:
        # Unknown code — never echo it as a message; use the safe fallback.
        return EsignError(message=ESIGN_ERROR_MESSAGES[CODE_SERVER_ERROR], code=CODE_SERVER_ERROR)
    return EsignError(message=message or canonical, code=code)


def status_for_code(code: str | None) -> int:
    """Return the HTTP status code for an esign error ``code``.

    Unknown / ``None`` codes map to ``500`` so an unexpected code can never
    accidentally produce a success status.
    """
    if code is None:
        return ESIGN_ERROR_STATUS[CODE_SERVER_ERROR]
    return ESIGN_ERROR_STATUS.get(code, ESIGN_ERROR_STATUS[CODE_SERVER_ERROR])


def humanize_esign_error(exc: Any) -> EsignError:
    """Map an internal exception to the humanized ``{ message, code }`` shape.

    Total mapper — for **any** input it returns an :class:`EsignError` whose
    ``message`` is a non-empty, human-readable sentence drawn from
    :data:`ESIGN_ERROR_MESSAGES`. Raw database text and raw exception text are
    **never** embedded in the returned message (R15.5); ``str(exc)`` is never
    interpolated into the message.

    Recognised inputs, in priority order:

    * an :class:`EsignError` (or anything carrying a known ``code`` attribute)
      is honoured as-is so already-humanized errors round-trip unchanged;
    * :class:`~app.integrations.documenso.DocumensoNotConfiguredError` ->
      ``integration_not_configured`` (R1.9/1.10, R19.3/19.4);
    * :class:`~app.integrations.documenso.DocumensoApiError` and any other
      :class:`~app.integrations.documenso.DocumensoError` -> ``documenso_error``
      (R3.5) — the upstream status on ``DocumensoApiError`` is for logging
      only and is never surfaced to the user;
    * a provisioning failure (duck-typed by class name to avoid importing the
      optional adapter module) -> ``auto_provision_failed`` (R20.3);
    * everything else (including ``ValueError`` / Pydantic ``ValidationError``
      and bare DB exceptions) -> ``server_error`` (R16.3).
    """
    # Already humanized — honour it verbatim (round-trips unchanged).
    if isinstance(exc, EsignError):
        return exc

    # An exception that carries an explicit, known esign code.
    code_attr = getattr(exc, "code", None)
    if isinstance(code_attr, str) and code_attr in ESIGN_ERROR_MESSAGES:
        return esign_error(code_attr)

    if isinstance(exc, DocumensoNotConfiguredError):
        return esign_error(CODE_INTEGRATION_NOT_CONFIGURED)

    if isinstance(exc, (DocumensoApiError, DocumensoError)):
        return esign_error(CODE_DOCUMENSO_ERROR)

    # Optional provisioning adapter (app/integrations/documenso_provisioning.py)
    # may not be importable yet; match by class name to stay decoupled.
    if type(exc).__name__ == "ProvisioningError":
        return esign_error(CODE_AUTO_PROVISION_FAILED)

    # Catch-all — never leak the raw exception text.
    return esign_error(CODE_SERVER_ERROR)
