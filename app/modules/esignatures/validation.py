"""Pure validators for the esignatures module.

Everything in this module is a **pure function**: no DB, no network, no other
I/O and no global state. That keeps the send-validation rules (≥1 recipient,
PDF magic bytes, syntactic email validity) and the webhook shared-secret
comparison directly property-testable in-memory and lets the service layer
compose them without side effects.

These helpers anchor Property 8 ("Send validation is atomic and
side-effect-free") — the pure-core portion exercised by the property test in
task 4.2.

Requirements: 3.3, 3.4, 4.2, 4.3, 4.6, 8.1
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# PDF detection (R3.4)
# ---------------------------------------------------------------------------

#: Every conforming PDF file begins with the magic byte marker ``%PDF`` (the
#: full header is ``%PDF-<version>``). We check only the leading marker so the
#: function is version-agnostic. See ISO 32000 / the project's own renderers
#: which document that rendered PDFs always start with ``b"%PDF"``.
_PDF_MAGIC = b"%PDF"


def is_pdf(data: bytes | bytearray | memoryview | None) -> bool:
    """Return ``True`` when ``data`` starts with the PDF magic bytes (``%PDF``).

    This is a content sniff on the leading bytes rather than a trust of the
    filename/MIME type (R3.4). It is deliberately tolerant of leading-byte
    slices: any byte-like input that begins with ``%PDF`` is accepted.

    Pure function — never raises, never performs I/O. ``None`` and non
    byte-like inputs return ``False``.
    """
    if data is None:
        return False
    if isinstance(data, (bytearray, memoryview)):
        data = bytes(data)
    if not isinstance(data, bytes):
        return False
    return data[: len(_PDF_MAGIC)] == _PDF_MAGIC


# ---------------------------------------------------------------------------
# PDF page count (R17 — last-page signature-field placement)
# ---------------------------------------------------------------------------

#: Matches a PDF *page* object marker (``/Type /Page``) while EXCLUDING the
#: page-tree container (``/Type /Pages``) and any other ``/Page…`` key via a
#: negative lookahead on a trailing letter. PDF permits arbitrary whitespace
#: between the ``/Type`` key and its ``/Page`` value, so ``\s*`` is tolerant of
#: both ``/Type /Page`` and ``/Type/Page``.
_PAGE_OBJ_RE = re.compile(rb"/Type\s*/Page(?![a-zA-Z])")


def pdf_page_count(data: bytes | bytearray | memoryview | None) -> int | None:
    """Best-effort count of the pages in a PDF by counting page objects.

    Scans the raw bytes for ``/Type /Page`` page-object markers (excluding the
    ``/Type /Pages`` page-tree container). This is a deliberately conservative
    heuristic, not a full PDF parse: a PDF whose page objects live inside
    compressed object streams exposes no plaintext markers, so the count cannot
    be determined and ``None`` is returned.

    Callers MUST treat ``None`` (or any non-positive result) as "page count
    unknown" and fall back to a safe default page rather than guessing an
    out-of-range page number.

    Pure function — never raises, never performs I/O. ``None`` / non byte-like
    inputs return ``None``.
    """
    if data is None:
        return None
    if isinstance(data, (bytearray, memoryview)):
        data = bytes(data)
    if not isinstance(data, bytes):
        return None
    count = len(_PAGE_OBJ_RE.findall(data))
    return count if count > 0 else None


# ---------------------------------------------------------------------------
# Email validation (R4.2, R4.3, R4.6)
# ---------------------------------------------------------------------------

#: Syntactic email check, consistent with the project's other *syntactic*
#: email gates (``app/modules/portal/service.py`` and
#: ``app/modules/vehicles/report_service.py`` use the identical pattern).
#: Pydantic ``EmailStr`` remains the schema-level validator on the API
#: boundary; this pure helper performs an equivalent syntactic check WITHOUT
#: raising, so the service layer can identify the *first* offending recipient
#: and reject the whole send atomically.
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def is_valid_email(email: Any) -> bool:
    """Return ``True`` when ``email`` is a syntactically valid address.

    Pure function — never raises. Non-string / empty / whitespace-only inputs
    return ``False``.
    """
    if not isinstance(email, str):
        return False
    candidate = email.strip()
    if not candidate:
        return False
    return _EMAIL_RE.match(candidate) is not None


# ---------------------------------------------------------------------------
# Recipient validation (R3.3, R4.2, R4.3, R4.6)
# ---------------------------------------------------------------------------

# Machine-readable codes — mirror the design's Error Handling table so the
# service/router can fold them straight into the humanized ``{message, code}``
# response shape (R16) without re-deriving them.
CODE_NO_RECIPIENTS = "no_recipients"
CODE_INVALID_RECIPIENT_EMAIL = "invalid_recipient_email"


@dataclass(frozen=True)
class RecipientValidationResult:
    """Outcome of :func:`validate_recipients`.

    ``ok`` is ``True`` only when there is at least one recipient and every
    recipient email is syntactically valid. When ``ok`` is ``False`` the
    remaining fields describe the **first** offending recipient (or the
    empty-list condition) so the caller can reject the entire send atomically
    and surface a humanized message.
    """

    ok: bool
    code: str | None = None
    message: str | None = None
    #: Zero-based index of the first invalid recipient (``None`` for the
    #: empty-list case).
    index: int | None = None
    #: Best-effort display name of the first invalid recipient, used to build
    #: the "The email address for '{name}' is not valid." message.
    name: str | None = None


def _extract(item: Any, field: str) -> Any:
    """Pull ``field`` from a recipient-like item (mapping or attribute object).

    Defensive: returns ``None`` when the field is absent. Pure, never raises.
    """
    if isinstance(item, Mapping):
        return item.get(field)
    return getattr(item, field, None)


def validate_recipients(
    recipients: Sequence[Any] | None,
) -> RecipientValidationResult:
    """Atomically validate a send's recipient list.

    Enforces, in order:

    1. **At least one recipient** (R3.3) — an empty/``None`` list is rejected
       with code ``no_recipients``.
    2. **Every recipient email is syntactically valid** (R4.2, R4.3, R4.6) —
       the list is scanned in order and the **first** recipient with an
       invalid email is identified. Because ANY invalid email rejects the
       WHOLE send, the caller must make no Documenso call and persist no rows
       when ``ok`` is ``False`` (atomic, all-or-nothing).

    Each recipient may be a mapping with ``name``/``email`` keys or an object
    exposing ``name``/``email`` attributes (e.g. a ``RecipientIn`` schema).

    Pure function — no I/O, never raises.
    """
    if not recipients:
        return RecipientValidationResult(
            ok=False,
            code=CODE_NO_RECIPIENTS,
            message="Add at least one recipient before sending.",
        )

    for index, item in enumerate(recipients):
        email = _extract(item, "email")
        if not is_valid_email(email):
            name = _extract(item, "name")
            display = name if isinstance(name, str) and name.strip() else (
                email if isinstance(email, str) and email.strip() else "this recipient"
            )
            return RecipientValidationResult(
                ok=False,
                code=CODE_INVALID_RECIPIENT_EMAIL,
                message=f"The email address for '{display}' is not valid.",
                index=index,
                name=name if isinstance(name, str) else None,
            )

    return RecipientValidationResult(ok=True)


# ---------------------------------------------------------------------------
# Constant-time secret comparison (R8.1)
# ---------------------------------------------------------------------------


def secret_compare(expected: Any, provided: Any) -> bool:
    """Constant-time equality of the shared-secret STRING, verbatim.

    Documenso sends the configured webhook secret **as-is** in the
    ``X-Documenso-Secret`` header — it does **not** HMAC the request body — so
    this compares the two secret strings directly (NOT a computed signature)
    using :func:`hmac.compare_digest` to avoid leaking length/content via
    timing.

    Both values are encoded to UTF-8 bytes before comparison so the digest
    compare operates on a stable representation. Any ``None`` or non-string
    input returns ``False`` (a missing/garbled secret never matches).

    Pure function — no I/O, never raises.
    """
    if not isinstance(expected, str) or not isinstance(provided, str):
        return False
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))
