"""Email compose service — Attachment_Token (HMAC) build/validate.

Implements the IDOR-defence attachment token described in the send-email-modal
design (Data Models §4 "Attachment_Token (HMAC) shape and signing key").

Token shape::

    payload = f"{org_id}:{entity_id}:{attachment_kind}:{expires_at_epoch}"
    sig      = HMAC_SHA256(signing_key, payload)        # hex
    token    = base64url( payload + "." + sig )
    signing_key = HKDF(settings.jwt_secret.encode(), info=b"email-attachment-token-v1")

The signing key is *derived* from ``settings.jwt_secret`` via HKDF/SHA-256 with
a fixed info string so this token's key material is isolated from JWT/session
signing. There is no ``SECRET_KEY`` setting in ``app/config.py``; ``jwt_secret``
is the correct source (verified to exist).

Requirements: 7.6
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

# --- Constants ---------------------------------------------------------------

#: The attachment kinds the send surfaces may offer (design §4 / R7.6, R7.7).
VALID_ATTACHMENT_KINDS: frozenset[str] = frozenset(
    {
        "invoice_pdf",
        "invoice_pdf_paid",
        "customer_statement_pdf",
        "quote_pdf",
    }
)

#: Token validity window: now + 30 minutes (longer than the preview->send
#: window, short enough to bound replay).
ATTACHMENT_TOKEN_TTL = timedelta(minutes=30)

#: Fixed HKDF info string — versioned so the derivation can be rotated.
_HKDF_INFO = b"email-attachment-token-v1"

#: Derived signing-key length in bytes.
_SIGNING_KEY_LENGTH = 32

#: Separator between the payload and its hex signature inside the token.
_SIG_SEPARATOR = "."


def _signing_key() -> bytes:
    """Derive the HMAC signing key from ``settings.jwt_secret`` via HKDF/SHA-256.

    Deriving (rather than using ``jwt_secret`` directly) isolates this token's
    key material from JWT/session signing.
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_SIGNING_KEY_LENGTH,
        salt=None,
        info=_HKDF_INFO,
    )
    return hkdf.derive(settings.jwt_secret.encode())


def _sign(payload: str) -> str:
    """Return the hex HMAC-SHA256 signature of ``payload``."""
    return hmac.new(_signing_key(), payload.encode(), hashlib.sha256).hexdigest()


def _to_epoch(expires_at: datetime) -> int:
    """Convert a datetime to an integer epoch (treating naive values as UTC)."""
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return int(expires_at.timestamp())


def build_attachment_token(
    org_id,
    entity_id,
    attachment_kind: str,
    expires_at: datetime,
) -> str:
    """Build a base64url HMAC attachment token.

    Args:
        org_id: The organisation that owns the entity (UUID/int/str).
        entity_id: The entity the attachment belongs to (UUID/int/str).
        attachment_kind: One of :data:`VALID_ATTACHMENT_KINDS`.
        expires_at: Absolute expiry; encoded as an integer epoch.

    Returns:
        The base64url-encoded token string.

    Raises:
        ValueError: If ``attachment_kind`` is not a recognised kind.
    """
    if attachment_kind not in VALID_ATTACHMENT_KINDS:
        raise ValueError(f"Unknown attachment_kind: {attachment_kind!r}")

    expires_at_epoch = _to_epoch(expires_at)
    payload = f"{org_id}:{entity_id}:{attachment_kind}:{expires_at_epoch}"
    sig = _sign(payload)
    raw = f"{payload}{_SIG_SEPARATOR}{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def mint_attachment_token(org_id, entity_id, attachment_kind: str) -> str:
    """Mint a token with the default 30-minute expiry window.

    Convenience wrapper over :func:`build_attachment_token`.
    """
    expires_at = datetime.now(timezone.utc) + ATTACHMENT_TOKEN_TTL
    return build_attachment_token(org_id, entity_id, attachment_kind, expires_at)


def validate_attachment_token(token: str, org_id, entity_id) -> str | None:
    """Validate an attachment token against the requesting org + entity.

    Performs a constant-time HMAC comparison, checks the embedded org/entity
    match the request, and checks the token has not expired. Returns the
    ``attachment_kind`` on success, or ``None`` on ANY failure (malformed,
    bad signature, wrong org/entity, expired, or unknown kind). Never raises.
    """
    try:
        # base64url-decode (re-pad defensively in case padding was stripped).
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()

        # Split payload from its hex signature on the LAST separator. The
        # signature is hex and the payload fields never contain a ".".
        payload, _, provided_sig = raw.rpartition(_SIG_SEPARATOR)
        if not payload or not provided_sig:
            return None

        # Recompute over the payload and compare in constant time.
        expected_sig = _sign(payload)
        if not hmac.compare_digest(expected_sig, provided_sig):
            return None

        # Parse the four payload fields. None of them contains a ":".
        parts = payload.split(":")
        if len(parts) != 4:
            return None
        token_org_id, token_entity_id, attachment_kind, expires_at_raw = parts

        # The embedded org/entity must match the request (string compare).
        if token_org_id != str(org_id) or token_entity_id != str(entity_id):
            return None

        # The kind must be a recognised one.
        if attachment_kind not in VALID_ATTACHMENT_KINDS:
            return None

        # The token must not be expired.
        expires_at_epoch = int(expires_at_raw)
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        if expires_at_epoch <= now_epoch:
            return None

        return attachment_kind
    except Exception:
        # Any malformed input (bad base64, decode error, bad int, etc.) -> None.
        return None


# ===========================================================================
# Preview service + helpers (task 6.2)
#
# These functions back ``GET /api/v2/email-preview`` (the Email_Preview_
# Endpoint). They resolve the same Default_Content the auto-send would have
# produced for a given (template_type, entity_type, entity_id), so that
# "send default" in the modal is byte-equivalent to the pre-modal auto-send
# path (Property P1). The per-template variable-context maps and hardcoded
# fallbacks deliberately mirror the existing send functions:
#   - invoice_issued / payment_received  -> invoices.service.email_invoice
#   - invoice_payment_link               -> payments.service._send_receipt_email
#   - quote_sent                         -> quotes.service.send_quote
#   - customer_statement                 -> reports.service.get_customer_statement
#   - portal_link                        -> customers.service.send_portal_link
#   - wof/cof/registration/service       -> notifications.reminder_queue_service
#
# Design ref: Backend Components -> service.py; Data Models §5 variable-context.
# Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.10, 7.5, 7.7, 9.2, 13.1,
#               16.4, 20.4, 20.5
# ===========================================================================


class EntityNotFound(Exception):
    """The requested entity does not exist (or is not visible to this org).

    The router maps this to HTTP 404. RLS-scoped queries that come back
    empty raise this so a cross-org/missing entity never leaks as a 500.
    """


class InvalidAttachmentSelection(Exception):
    """An override-send attachment token failed validation (R7.6).

    Raised by the override send services when an ``attachments`` token is
    unknown, expired, tampered, or scoped to a different org/entity. The
    router maps this to HTTP 400 with detail "Invalid attachment selection.".
    """


class EmailSendFailure(Exception):
    """An override send failed at the unified sender (R8.5–R8.8).

    Carries the final ``failure_kind`` (and the attempt count) so the router
    can map it to the right HTTP status via :func:`failure_kind_to_http`.
    Raised by the override send services instead of a generic ``ValueError``
    so the modal surfaces the correct banner. ``failure_kind`` may be a
    ``FailureKind`` enum member, its string value, or ``None``.
    """

    def __init__(self, failure_kind=None, *, attempts: int = 0, error: str | None = None):
        self.failure_kind = failure_kind
        self.attempts = attempts
        self.error = error
        status, detail = failure_kind_to_http(failure_kind)
        self.status_code = status
        self.detail = detail
        super().__init__(error or detail)


#: Backend HTTP-detail strings for each ``FailureKind`` (R8.5–R8.8). The
#: tuple is ``(status_code, detail)``. ``SOFT_PROVIDER`` / ``BUDGET_EXCEEDED``
#: and any unrecognised kind fall through to the 503 "temporary" message so a
#: send that exhausts the provider chain always surfaces a retryable status.
_FAILURE_KIND_HTTP: dict[str, tuple[int, str]] = {
    "hard_recipient": (
        400,
        "Recipient address rejected. Check the To list and try again.",
    ),
    "hard_payload": (
        413,
        "Email too large. Reduce attachments and try again.",
    ),
    "soft_auth": (
        502,
        "Email provider authentication failed. Contact your platform admin.",
    ),
    "soft_provider": (
        503,
        "Delivery temporarily failed across all providers. "
        "Please try again in a few minutes.",
    ),
    "budget_exceeded": (
        503,
        "Delivery temporarily failed across all providers. "
        "Please try again in a few minutes.",
    ),
}

#: The default (503) mapping used when ``failure_kind`` is ``None`` or an
#: unrecognised value — treat it as a transient provider failure (R8.8).
_FAILURE_KIND_HTTP_DEFAULT: tuple[int, str] = (
    503,
    "Delivery temporarily failed across all providers. "
    "Please try again in a few minutes.",
)


def failure_kind_to_http(failure_kind) -> tuple[int, str]:
    """Map a ``FailureKind`` (or its string value) to ``(status_code, detail)``.

    Backend single source of truth for the R8 send-failure detail strings,
    reused by every override send router (tasks 8.1–8.7):

    - ``HARD_RECIPIENT`` → (400, recipient rejected) — R8.5
    - ``HARD_PAYLOAD``   → (413, email too large)    — R8.6
    - ``SOFT_AUTH``      → (502, provider auth failed) — R8.7
    - ``SOFT_PROVIDER`` / ``BUDGET_EXCEEDED`` / default → (503, temporary) — R8.8

    ``failure_kind`` may be a :class:`FailureKind` enum member, its ``.value``
    string, or ``None``; anything unrecognised maps to the 503 default.

    Requirements: 8.5, 8.6, 8.7, 8.8
    """
    if failure_kind is None:
        return _FAILURE_KIND_HTTP_DEFAULT
    key = getattr(failure_kind, "value", failure_kind)
    return _FAILURE_KIND_HTTP.get(str(key), _FAILURE_KIND_HTTP_DEFAULT)


#: Map each supported ``template_type`` to the ``entity_type`` the preview
#: endpoint expects. Used to validate the request and to drive entity loading.
TEMPLATE_ENTITY_TYPES: dict[str, str] = {
    "invoice_issued": "invoice",
    "invoice_payment_link": "invoice",
    "payment_received": "invoice",
    "quote_sent": "quote",
    "customer_statement": "customer",
    "portal_link": "customer",
    "wof_expiry_reminder": "customer_vehicle",
    "cof_expiry_reminder": "customer_vehicle",
    "registration_expiry_reminder": "customer_vehicle",
    "service_due_reminder": "customer_vehicle",
}

#: The reminder template types that share the customer_vehicle surface.
_REMINDER_TEMPLATE_TYPES: frozenset[str] = frozenset(
    {
        "wof_expiry_reminder",
        "cof_expiry_reminder",
        "registration_expiry_reminder",
        "service_due_reminder",
    }
)

#: Which vehicle field each reminder type reads its expiry date from, and the
#: variable key it exposes (mirrors reminder_queue_service).
_REMINDER_FIELD_MAP: dict[str, tuple[str, str]] = {
    "wof_expiry_reminder": ("wof_expiry", "expiry_date"),
    "cof_expiry_reminder": ("cof_expiry", "expiry_date"),
    "registration_expiry_reminder": ("registration_expiry", "expiry_date"),
    "service_due_reminder": ("service_due_date", "service_due_date"),
}


def compute_audit_hashes(subject: str, sanitised_body: str) -> dict[str, str]:
    """Return SHA-256 hex digests of the final subject and sanitised body.

    Pure helper consumed by the override send paths (task 8) to populate
    ``edited_subject_hash`` / ``edited_body_hash`` on ``notification_log``.
    The body hash MUST be computed over the **post-sanitisation** string
    (Property P4), so callers pass the already-sanitised body here.

    Returns a dict ``{"subject_hash": ..., "body_hash": ...}``.

    Requirements: 11.2, 11.3
    """
    subject_hash = hashlib.sha256((subject or "").encode("utf-8")).hexdigest()
    body_hash = hashlib.sha256((sanitised_body or "").encode("utf-8")).hexdigest()
    return {"subject_hash": subject_hash, "body_hash": body_hash}


async def resolve_locale(db: AsyncSession, *, org_id, customer) -> str:
    """Resolve the recipient locale via the Locale_Resolution_Chain.

    Precedence (R3.10): the customer's ``language`` field if set, otherwise
    the org's ``locale`` (``default_locale``), otherwise ``"en"``. The
    language code is normalised to the part before any hyphen
    (``"en-NZ"`` -> ``"en"``) to match ``get_template_for_locale()``.

    ``customer`` may be ``None`` (e.g. a surface with no customer on file),
    in which case the chain falls back to the org locale then ``"en"``.

    Requirements: 3.10
    """
    # 1. Customer language.
    cust_lang = getattr(customer, "language", None) if customer is not None else None
    if cust_lang and str(cust_lang).strip():
        return str(cust_lang).split("-")[0].lower()

    # 2. Org default locale.
    from app.modules.admin.models import Organisation

    org_locale = (
        await db.execute(select(Organisation.locale).where(Organisation.id == org_id))
    ).scalar_one_or_none()
    if org_locale and str(org_locale).strip():
        return str(org_locale).split("-")[0].lower()

    # 3. Final fallback.
    return "en"


def build_variable_context(
    template_type: str,
    *,
    entity,
    org,
    customer=None,
    vehicle=None,
    extra: dict | None = None,
) -> dict[str, str]:
    """Build the per-``template_type`` variable context for ``resolve_template()``.

    The keys here mirror exactly what the existing send functions pass to
    ``resolve_template()`` (Data Models §5), so the preview render is
    byte-identical to the auto-send render (Property P1).

    ``entity`` / ``org`` / ``customer`` / ``vehicle`` are plain dicts or ORM
    objects depending on the surface; ``extra`` carries surface-specific
    pre-computed values (formatted totals, links, statement period, etc.)
    that the caller resolved exactly as the send function does.

    Requirements: 20.4, 20.5
    """
    extra = extra or {}

    def _cust(attr: str) -> str:
        if customer is None:
            return ""
        if isinstance(customer, dict):
            return customer.get(attr) or ""
        return getattr(customer, attr, None) or ""

    def _org_name() -> str:
        if org is None:
            return ""
        if isinstance(org, dict):
            return org.get("name") or org.get("org_name") or ""
        return getattr(org, "name", None) or ""

    org_email = extra.get("org_email", "") or ""
    org_phone = extra.get("org_phone", "") or ""
    org_name = extra.get("org_name") or _org_name()

    if template_type in ("invoice_issued", "payment_received"):
        return {
            "customer_first_name": _cust("first_name"),
            "customer_last_name": _cust("last_name"),
            "customer_email": extra.get("customer_email", "") or _cust("email"),
            "invoice_number": extra.get("invoice_number", "") or "",
            "total_due": extra.get("total_due", "") or "",
            "due_date": extra.get("due_date", "") or "",
            "payment_link": extra.get("payment_link", "") or "",
            "org_name": org_name,
            "org_email": org_email,
            "org_phone": org_phone,
        }

    if template_type == "invoice_payment_link":
        return {
            "customer_first_name": _cust("first_name"),
            "customer_last_name": _cust("last_name"),
            "customer_email": extra.get("customer_email", "") or _cust("email"),
            "invoice_number": extra.get("invoice_number", "") or "",
            "total_due": extra.get("total_due", "") or "",
            "due_date": extra.get("due_date", "") or "",
            "payment_link": extra.get("payment_link", "") or "",
            "org_name": org_name,
            "org_email": org_email,
            "org_phone": org_phone,
        }

    if template_type == "quote_sent":
        return {
            "customer_first_name": _cust("first_name"),
            "customer_last_name": _cust("last_name"),
            "quote_number": extra.get("quote_number", "") or "",
            "quote_total": extra.get("quote_total", "") or "",
            "quote_valid_until": extra.get("quote_valid_until", "") or "",
            "org_name": org_name,
            "org_email": org_email,
            "org_phone": org_phone,
        }

    if template_type == "customer_statement":
        return {
            "customer_first_name": _cust("first_name"),
            "customer_last_name": _cust("last_name"),
            "statement_period_start": extra.get("statement_period_start", "") or "",
            "statement_period_end": extra.get("statement_period_end", "") or "",
            "total_outstanding": extra.get("total_outstanding", "") or "",
            "statement_link": extra.get("statement_link", "") or "",
            "org_name": org_name,
            "org_email": org_email,
            "org_phone": org_phone,
        }

    if template_type == "portal_link":
        return {
            "customer_first_name": _cust("first_name"),
            "customer_last_name": _cust("last_name"),
            "portal_link": extra.get("portal_link", "") or "",
            "org_name": org_name,
            "org_email": org_email,
            "org_phone": org_phone,
        }

    if template_type in _REMINDER_TEMPLATE_TYPES:
        _date_field, date_variable = _REMINDER_FIELD_MAP[template_type]

        def _veh(attr: str) -> str:
            if vehicle is None:
                return ""
            if isinstance(vehicle, dict):
                return vehicle.get(attr) or ""
            return getattr(vehicle, attr, None) or ""

        ctx = {
            "customer_first_name": _cust("first_name"),
            "customer_last_name": _cust("last_name"),
            "customer_email": _cust("email"),
            "vehicle_rego": extra.get("vehicle_rego", "") or _veh("rego"),
            "vehicle_make": extra.get("vehicle_make", "") or _veh("make"),
            "vehicle_model": extra.get("vehicle_model", "") or _veh("model"),
            "org_name": org_name,
            "org_phone": org_phone,
            "org_email": org_email,
        }
        ctx[date_variable] = extra.get(date_variable, "") or ""
        return ctx

    raise ValueError(f"Unsupported template_type: {template_type!r}")


async def get_attachments_for_surface(
    db: AsyncSession,
    *,
    template_type: str,
    entity_id,
    org_id,
) -> list[dict]:
    """Return the per-surface attachment specs with HMAC-tokenised keys (R7.7).

    Documented surface defaults:
      - ``invoice_issued``: invoice PDF (required); customer-statement PDF
        (optional, offered only when the customer has multiple open invoices)
      - ``invoice_payment_link``: invoice PDF (optional, default off)
      - ``payment_received``: invoice PDF showing PAID status (required)
      - ``quote_sent``: quote PDF (required)
      - ``customer_statement``: customer statement PDF (required)
      - ``portal_link`` / vehicle reminders: no attachments

    Each returned dict matches ``AttachmentSpec``:
    ``{key, label, size_bytes, default_attached, required}`` where ``key`` is
    an HMAC token minted via :func:`mint_attachment_token` for the matching
    ``attachment_kind``. ``size_bytes`` is the real PDF size when cheap to
    compute; the preview endpoint avoids generating PDFs purely for sizing
    (performance §1) so we estimate when generation would be expensive.

    Requirements: 7.5, 7.7
    """
    specs: list[dict] = []

    def _spec(kind: str, label: str, size_bytes: int, default_attached: bool, required: bool) -> dict:
        return {
            "key": mint_attachment_token(org_id, entity_id, kind),
            "label": label,
            "size_bytes": int(size_bytes),
            "default_attached": default_attached,
            "required": required,
        }

    # Rough per-document size estimate (KB) used where generating the real
    # PDF just to size it would be wasteful. The modal only uses this to drive
    # the client-side size budget; the server re-resolves real bytes at send.
    _PDF_SIZE_ESTIMATE = 120 * 1024  # ~120 KB

    if template_type == "invoice_issued":
        specs.append(
            _spec("invoice_pdf", "Invoice PDF", _PDF_SIZE_ESTIMATE, True, True)
        )
        # Optional customer-statement PDF, only when the customer has more
        # than one open invoice (R7.7).
        try:
            from app.modules.invoices.models import Invoice

            inv = (
                await db.execute(
                    select(Invoice.customer_id).where(
                        Invoice.id == entity_id, Invoice.org_id == org_id
                    )
                )
            ).scalar_one_or_none()
            if inv is not None:
                open_count = (
                    await db.execute(
                        select(func.count(Invoice.id)).where(
                            Invoice.org_id == org_id,
                            Invoice.customer_id == inv,
                            Invoice.status.in_(
                                ["issued", "partially_paid", "overdue"]
                            ),
                            Invoice.balance_due > 0,
                        )
                    )
                ).scalar() or 0
                if open_count > 1:
                    specs.append(
                        _spec(
                            "customer_statement_pdf",
                            "Customer Statement PDF",
                            _PDF_SIZE_ESTIMATE,
                            False,
                            False,
                        )
                    )
        except Exception:
            logger.warning(
                "Failed to evaluate optional statement attachment for invoice %s",
                entity_id,
            )

    elif template_type == "invoice_payment_link":
        specs.append(
            _spec("invoice_pdf", "Invoice PDF", _PDF_SIZE_ESTIMATE, False, False)
        )

    elif template_type == "payment_received":
        specs.append(
            _spec(
                "invoice_pdf_paid",
                "Invoice PDF (Paid)",
                _PDF_SIZE_ESTIMATE,
                True,
                True,
            )
        )

    elif template_type == "quote_sent":
        # Quote PDF is OFF by default and user-toggleable (not required). The
        # default send path attaches no PDF (byte-equivalence); ticking the box
        # makes the modal send ``attachments=['quote_pdf']`` so send_quote
        # attaches the generated PDF. (A required+default-on spec would render
        # the checkbox locked AND be omitted from the payload as "unchanged",
        # so no PDF would ever attach — the bug this fixes.)
        specs.append(
            _spec("quote_pdf", "Quote PDF", _PDF_SIZE_ESTIMATE, False, False)
        )

    elif template_type == "customer_statement":
        specs.append(
            _spec(
                "customer_statement_pdf",
                "Customer Statement PDF",
                _PDF_SIZE_ESTIMATE,
                True,
                True,
            )
        )

    # portal_link and the vehicle reminders intentionally have no attachments.
    return specs


async def _resolve_sender_preview(db: AsyncSession, *, org_id) -> dict:
    """Resolve the read-only Sender_Identity for the preview (R9.2).

    Mirrors how ``email_sender`` resolves the From identity: the highest-
    priority active provider's ``config.from_email`` / ``from_name`` with the
    org name preferred as the friendly name and the org's reply-to override.
    Never editable in the modal; the override endpoints ignore any client
    from_*/reply_to.
    """
    from app.modules.admin.models import EmailProvider, Organisation

    org = (
        await db.execute(select(Organisation).where(Organisation.id == org_id))
    ).scalar_one_or_none()
    org_settings = (org.settings or {}) if org else {}
    org_name = org.name if org else ""
    org_reply_to = (
        org_settings.get("email_reply_to")
        or org_settings.get("reply_to")
        or None
    )

    provider = (
        await db.execute(
            select(EmailProvider)
            .where(
                EmailProvider.is_active.is_(True),
                EmailProvider.credentials_set.is_(True),
            )
            .order_by(EmailProvider.priority.asc())
        )
    ).scalars().first()

    config = (provider.config or {}) if provider else {}
    from_email = config.get("from_email") or ""
    from_name = (
        org_settings.get("email_sender_name")
        or org_name
        or config.get("from_name")
        or ""
    )
    reply_to = org_reply_to or config.get("reply_to")

    return {
        "from_email": from_email,
        "from_name": from_name,
        "reply_to": reply_to,
    }


async def _build_blocklist(db: AsyncSession, *, org_id, emails: list[str]) -> list[dict]:
    """Return Bounce_Blocklist entries for the given recipient addresses (R13.1).

    Queries ``bounced_addresses`` (the same table ``_check_bounce_blocklist``
    uses) for every default recipient/cc/bcc, returning
    ``{email, kind, reason, bounced_at}``. ``kind`` is normalised to
    ``'hard'`` / ``'soft'`` (the table's ``'blocked'`` maps to ``'hard'``).
    Expired soft rows are filtered out.
    """
    from app.modules.notifications.models import BouncedAddress

    unique = [e for e in {(e or "").strip().lower() for e in emails} if e]
    if not unique:
        return []

    stmt = select(BouncedAddress).where(
        func.lower(BouncedAddress.email_address).in_(unique),
        or_(
            BouncedAddress.org_id == org_id,
            BouncedAddress.org_id.is_(None),
        ),
        or_(
            BouncedAddress.expires_at.is_(None),
            BouncedAddress.expires_at > func.now(),
        ),
    )
    rows = list((await db.execute(stmt)).scalars().all())

    # Collapse to one entry per address, hard takes precedence over soft.
    by_email: dict[str, dict] = {}
    for row in rows:
        kind = "hard" if row.bounce_kind in ("hard", "blocked") else "soft"
        addr = row.email_address.lower()
        existing = by_email.get(addr)
        if existing is None or (kind == "hard" and existing["kind"] != "hard"):
            by_email[addr] = {
                "email": row.email_address,
                "kind": kind,
                "reason": row.reason,
                "bounced_at": row.last_seen_at.isoformat()
                if row.last_seen_at
                else None,
            }
    return list(by_email.values())


def _resolve_base_origin(base_url: str | None, fallback_url: str | None = None) -> str:
    """Resolve the public origin used to build links, mirroring the senders."""
    candidate = base_url or fallback_url or settings.frontend_base_url or "http://localhost"
    return candidate.rstrip("/")


async def build_email_preview(
    db: AsyncSession,
    *,
    org_id,
    template_type: str,
    entity_type: str,
    entity_id,
    base_url: str | None = None,
) -> dict:
    """Build the complete Email_Preview_Endpoint payload (R3.1–3.6, R3.10).

    Loads the entity RLS-scoped (``EntityNotFound`` -> 404, ``PermissionError``
    -> 403), resolves the customer + locale, builds the variable context, calls
    ``resolve_template()`` (``default_was_template=True``) or computes the
    surface's hardcoded fallback (``False``), passes the body through
    :func:`sanitise_email_html`, builds the attachment list (HMAC tokens) and
    the ``blocklisted`` array, and assembles ``sender_preview``,
    ``email_size_limit_bytes`` and ``total_budget_seconds``.

    Returns a dict matching ``EmailPreviewResponse`` exactly.

    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.10, 7.5, 7.7, 9.2, 13.1,
                  16.4, 20.4, 20.5
    """
    from app.integrations.email_sender import (
        EMAIL_SIZE_LIMIT,
        EMAIL_TOTAL_BUDGET_SECONDS,
    )
    from app.integrations.html_sanitise import sanitise_email_html
    from app.modules.notifications.service import resolve_template

    expected_entity = TEMPLATE_ENTITY_TYPES.get(template_type)
    if expected_entity is None:
        raise EntityNotFound(f"Unsupported template_type: {template_type}")
    if entity_type != expected_entity:
        raise EntityNotFound(
            f"template_type {template_type!r} expects entity_type "
            f"{expected_entity!r}, got {entity_type!r}"
        )

    # Dispatch to the per-surface builder. Each returns:
    #   (subject, body_text, cta_url, cta_label, signature_html,
    #    recipients, variables, customer)
    if template_type in ("invoice_issued", "payment_received", "invoice_payment_link"):
        built = await _build_invoice_surface(
            db,
            org_id=org_id,
            template_type=template_type,
            invoice_id=entity_id,
            base_url=base_url,
        )
    elif template_type == "quote_sent":
        built = await _build_quote_surface(
            db, org_id=org_id, quote_id=entity_id, base_url=base_url
        )
    elif template_type == "customer_statement":
        built = await _build_statement_surface(
            db, org_id=org_id, customer_id=entity_id, base_url=base_url
        )
    elif template_type == "portal_link":
        built = await _build_portal_surface(
            db, org_id=org_id, customer_id=entity_id, base_url=base_url
        )
    elif template_type in _REMINDER_TEMPLATE_TYPES:
        built = await _build_reminder_surface(
            db,
            org_id=org_id,
            template_type=template_type,
            customer_vehicle_id=entity_id,
        )
    else:  # pragma: no cover - guarded above
        raise EntityNotFound(f"Unsupported template_type: {template_type}")

    variables = built["variables"]

    # Resolve the org's configured template (R3.3) or use the surface's
    # hardcoded fallback (R3.4). default_was_template reflects which path ran.
    rendered = await resolve_template(
        db,
        org_id=org_id,
        template_type=template_type,
        channel="email",
        variables=variables,
    )

    if rendered is not None:
        default_was_template = True
        subject = rendered.subject
        body_text = rendered.body
        cta_url = rendered.cta_url or built.get("cta_url")
        cta_label = rendered.cta_label or built.get("cta_label")
    else:
        default_was_template = False
        subject = built["subject"]
        body_text = built["body_text"]
        cta_url = built.get("cta_url")
        cta_label = built.get("cta_label")

    # Render to the same well-formed HTML document the send path produces,
    # then sanitise (R3.5). Reminders already produce HTML bodies, so they
    # carry their pre-rendered HTML through when no template resolved.
    #
    # ``body_html`` is the full transactional document (UNCHANGED — it backs
    # the byte-equivalence guarantee in Property 1 and the faithful "this is
    # the whole email" representation). ``body_editable_html`` is the inner
    # editable fragment the rich-text editor binds to: the body paragraphs +
    # signature only, with no document chrome (``<!DOCTYPE>``/``<head>``/
    # ``<title>``) and no generated CTA button — so the subject can no longer
    # leak into the editor (Requirement 2.1).
    if built.get("body_is_html") and rendered is None:
        raw_html = body_text
        # The reminder/portal surfaces already produce an inner-body HTML
        # fragment, so the editable fragment is just the sanitised body.
        body_editable_html = sanitise_email_html(body_text)
    else:
        from app.integrations.email_sender import (
            render_body_fragment_html,
            render_transactional_html,
        )

        raw_html = render_transactional_html(
            body_text,
            subject=subject,
            signature_html=built.get("signature_html"),
            cta_url=cta_url or None,
            cta_label=cta_label or None,
        )
        body_editable_html = sanitise_email_html(
            render_body_fragment_html(
                body_text,
                signature_html=built.get("signature_html"),
                cta_url=cta_url or None,
                cta_label=cta_label or None,
            )
        )
    body_html = sanitise_email_html(raw_html)

    locale = await resolve_locale(db, org_id=org_id, customer=built.get("customer"))

    recipients = built.get("recipients") or []
    cc = built.get("cc") or []
    bcc = built.get("bcc") or []

    attachments = await get_attachments_for_surface(
        db, template_type=template_type, entity_id=entity_id, org_id=org_id
    )

    blocklisted = await _build_blocklist(
        db, org_id=org_id, emails=[*recipients, *cc, *bcc]
    )

    sender_preview = await _resolve_sender_preview(db, org_id=org_id)

    return {
        "subject": subject,
        "body_html": body_html,
        "body_editable_html": body_editable_html,
        "recipients": recipients,
        "cc": cc,
        "bcc": bcc,
        "variable_context": variables,
        "attachments": attachments,
        "default_was_template": default_was_template,
        "sender_preview": sender_preview,
        "blocklisted": blocklisted,
        "locale": locale,
        "email_size_limit_bytes": EMAIL_SIZE_LIMIT,
        "total_budget_seconds": EMAIL_TOTAL_BUDGET_SECONDS,
    }


# ---------------------------------------------------------------------------
# Per-surface default-content builders
#
# Each mirrors the variable context + hardcoded fallback subject/body of the
# corresponding send function so the preview is byte-equivalent (Property P1).
# ---------------------------------------------------------------------------


async def _load_customer(db: AsyncSession, *, org_id, customer_id):
    """RLS-scoped customer load; raises EntityNotFound when missing."""
    from app.modules.customers.models import Customer

    customer = (
        await db.execute(
            select(Customer).where(
                Customer.id == customer_id, Customer.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    if customer is None:
        raise EntityNotFound("Customer not found in this organisation")
    return customer


async def _build_invoice_surface(
    db: AsyncSession,
    *,
    org_id,
    template_type: str,
    invoice_id,
    base_url: str | None,
) -> dict:
    """Default content for invoice_issued / payment_received / payment_link."""
    from app.modules.invoices.models import Invoice
    from app.modules.invoices.service import get_currency_symbol

    invoice = (
        await db.execute(
            select(Invoice).where(
                Invoice.id == invoice_id, Invoice.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise EntityNotFound("Invoice not found in this organisation")

    customer = None
    if invoice.customer_id:
        from app.modules.customers.models import Customer

        customer = (
            await db.execute(
                select(Customer).where(Customer.id == invoice.customer_id)
            )
        ).scalar_one_or_none()

    from app.modules.admin.models import Organisation

    org = (
        await db.execute(select(Organisation).where(Organisation.id == org_id))
    ).scalar_one_or_none()
    org_settings = (org.settings or {}) if org else {}
    org_name = org.name if org else "Your Company"
    org_email = org_settings.get("email") or org_settings.get("business_email") or ""
    org_phone = org_settings.get("phone") or org_settings.get("business_phone") or ""

    inv_number = invoice.invoice_number or "DRAFT"
    currency = invoice.currency or "NZD"
    currency_symbol = get_currency_symbol(currency)
    balance_due = invoice.balance_due if invoice.balance_due is not None else 0
    total_due_formatted = (
        f"{currency_symbol}{balance_due:.2f}"
        if isinstance(balance_due, (int, float))
        else f"{currency_symbol}{balance_due}"
    )
    due_date_str = str(invoice.due_date) if invoice.due_date else ""
    payment_page_url = invoice.payment_page_url or ""

    recipient = customer.email if customer and customer.email else None
    recipients = [recipient] if recipient else []

    # The invoice_issued surface links its CTA to the PUBLIC INVOICE-VIEW URL
    # (``/api/v1/public/invoice/{share_token}``), NOT the payment page —
    # mirroring ``invoices.service.email_invoice`` (ISSUE-169). This must be
    # byte-identical to the send path (Property P1 / R3.6), so we replicate
    # email_invoice's share-token + CTA-base resolution exactly. The payment-
    # link / receipt surfaces keep using the payment-page URL.
    invoice_view_url = ""
    if template_type == "invoice_issued":
        from urllib.parse import urlsplit as _urlsplit

        inv_data = invoice.invoice_data_json or {}
        share_token = inv_data.get("share_token")
        if not share_token:
            import secrets as _secrets

            from sqlalchemy.orm.attributes import flag_modified as _flag_modified

            share_token = _secrets.token_urlsafe(32)
            inv_data = dict(inv_data)
            inv_data["share_token"] = share_token
            invoice.invoice_data_json = inv_data
            _flag_modified(invoice, "invoice_data_json")
            await db.flush()

        payment_origin = None
        if payment_page_url:
            _parts = _urlsplit(payment_page_url)
            if _parts.scheme and _parts.netloc:
                payment_origin = f"{_parts.scheme}://{_parts.netloc}"
        cta_base = (
            base_url
            or payment_origin
            or settings.frontend_base_url
            or "http://localhost"
        ).rstrip("/")
        invoice_view_url = f"{cta_base}/api/v1/public/invoice/{share_token}"

    # The ``payment_link`` template variable carries the surface's CTA target:
    # the invoice-view URL for invoice_issued (ISSUE-169), the payment-page URL
    # for the payment-link / receipt surfaces — matching each send function's
    # ``_template_variables``.
    link_variable = (
        invoice_view_url if template_type == "invoice_issued" else payment_page_url
    )

    extra = {
        "invoice_number": inv_number,
        "total_due": total_due_formatted,
        "due_date": due_date_str,
        "payment_link": link_variable,
        "customer_email": (customer.email if customer else "") or "",
        "org_name": org_name,
        "org_email": org_email,
        "org_phone": org_phone,
    }
    variables = build_variable_context(
        template_type, entity=invoice, org=org, customer=customer, extra=extra
    )

    # Whether this surface's send function renders the org email signature.
    # ``email_invoice`` (invoice_issued) does; ``payments._send_receipt_email``
    # (payment_received / invoice_payment_link) does NOT — so the preview must
    # only attach the signature for invoice_issued to stay byte-equivalent.
    surface_uses_signature = template_type == "invoice_issued"

    # Hardcoded fallbacks mirroring the send functions.
    if template_type == "invoice_payment_link":
        subject = f"Payment link for invoice {inv_number} from {org_name}"
        body_text = (
            f"Hi,\n\n"
            f"Here is the secure online payment link for invoice {inv_number}.\n\n"
            f"Amount due: {currency} {balance_due}\n\n"
            f"You can pay securely online using the button below.\n\n"
            f"If you have any questions, please don't hesitate to contact us.\n\n"
            f"Kind regards,\n"
            f"{org_name}\n"
        )
        cta_url = payment_page_url or None
        cta_label = "Pay Now" if cta_url else None
    elif template_type == "payment_received":
        # Mirror ``payments._send_receipt_email`` (no-surcharge receipt). The
        # receipt amount defaults to the invoice's ``amount_paid`` — the value
        # the receipt surface (task 8.3) passes as ``pay_amount``. ``inv_number``
        # falls back to the invoice id, exactly as _send_receipt_email does.
        receipt_inv_number = invoice.invoice_number or str(invoice.id)
        pay_amount = invoice.amount_paid if invoice.amount_paid is not None else 0
        subject = f"Payment receipt for invoice {receipt_inv_number}"
        body_text = (
            f"Hi,\n\n"
            f"Thank you for your payment of {currency} {pay_amount}.\n\n"
            f"Invoice: {receipt_inv_number}\n"
            f"Amount paid: {currency} {pay_amount}\n"
            f"Remaining balance: {currency} {invoice.balance_due}\n\n"
            f"Thank you for your business.\n\n"
            f"{org_name}\n"
        )
        cta_url = None
        cta_label = None
    else:  # invoice_issued
        customer_first_name = (customer.first_name if customer else "") or ""
        subject = f"Invoice {inv_number} from {org_name}"
        body_text = (
            f"Hi {customer_first_name or 'there'},\n\n"
            f"Your invoice is ready. You can view it online using the button below.\n\n"
            f"If you have any questions, please contact us.\n\n"
            f"Kind regards,\n"
            f"{org_name}\n"
        )
        # email_invoice always sets the CTA to the invoice-view URL and labels
        # it "View Invoice".
        cta_url = invoice_view_url or None
        cta_label = "View Invoice"

    signature_html = None
    if (
        surface_uses_signature
        and org_settings.get("email_signature_enabled")
        and (org_settings.get("email_signature") or "").strip()
    ):
        signature_html = org_settings.get("email_signature")

    return {
        "subject": subject,
        "body_text": body_text,
        "cta_url": cta_url,
        "cta_label": cta_label,
        "signature_html": signature_html,
        "recipients": recipients,
        "variables": variables,
        "customer": customer,
    }


async def _build_quote_surface(
    db: AsyncSession, *, org_id, quote_id, base_url: str | None
) -> dict:
    """Default content for quote_sent."""
    from app.modules.invoices.service import get_currency_symbol
    from app.modules.quotes.models import Quote

    quote = (
        await db.execute(
            select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id)
        )
    ).scalar_one_or_none()
    if quote is None:
        raise EntityNotFound("Quote not found in this organisation")

    customer = None
    if quote.customer_id:
        from app.modules.customers.models import Customer

        customer = (
            await db.execute(
                select(Customer).where(Customer.id == quote.customer_id)
            )
        ).scalar_one_or_none()

    from app.modules.admin.models import Organisation

    org = (
        await db.execute(select(Organisation).where(Organisation.id == org_id))
    ).scalar_one_or_none()
    org_settings = (org.settings or {}) if org else {}
    org_name = org.name if org else "Company"
    org_email = org_settings.get("email") or org_settings.get("business_email") or ""
    org_phone = org_settings.get("phone") or org_settings.get("business_phone") or ""

    currency = getattr(org, "base_currency", None) or "NZD"
    currency_symbol = get_currency_symbol(currency)
    quote_total_raw = quote.total if quote.total is not None else 0
    quote_total_formatted = (
        f"{currency_symbol}{quote_total_raw:.2f}"
        if isinstance(quote_total_raw, (int, float))
        else f"{currency_symbol}{quote_total_raw}"
    )
    valid_until_str = str(quote.valid_until) if quote.valid_until else ""

    recipient = customer.email if customer and customer.email else None
    recipients = [recipient] if recipient else []

    extra = {
        "quote_number": quote.quote_number or "",
        "quote_total": quote_total_formatted,
        "quote_valid_until": valid_until_str,
        "org_name": org_name,
        "org_email": org_email,
        "org_phone": org_phone,
    }
    variables = build_variable_context(
        "quote_sent", entity=quote, org=org, customer=customer, extra=extra
    )

    # The send path (``quotes.service.send_quote``) mints an
    # ``acceptance_token`` at send time and ALWAYS appends the "view and accept
    # online" link. To keep the preview byte-equivalent to the sent email
    # (Property P1 / R3.6) we mint the token here too when it is absent —
    # mirroring how ``_build_invoice_surface`` mints the invoice ``share_token``
    # during preview. The token is stable, so previewing then sending reuses
    # the same value and the same link.
    if not quote.acceptance_token:
        import secrets as _secrets

        quote.acceptance_token = _secrets.token_urlsafe(32)
        await db.flush()

    origin = _resolve_base_origin(base_url)
    view_link_text = (
        f"\nYou can also view and accept this quote online at:\n"
        f"{origin}/api/v1/public/quotes/view/{quote.acceptance_token}\n"
    )

    subject = f"Quote {quote.quote_number} from {org_name}"
    body_text = (
        f"Hi,\n\n"
        f"Please find attached quote {quote.quote_number} from {org_name}.\n\n"
        f"Total: ${quote.total:.2f} (incl. GST)\n"
        f"This quote is valid until {quote.valid_until or 'N/A'}.\n"
        f"{view_link_text}\n"
        f"If you have any questions, please don't hesitate to contact us.\n\n"
        f"Kind regards,\n{org_name}\n"
    )

    signature_html = None
    if org_settings.get("email_signature_enabled") and (
        org_settings.get("email_signature") or ""
    ).strip():
        signature_html = org_settings.get("email_signature")

    return {
        "subject": subject,
        "body_text": body_text,
        "cta_url": None,
        "cta_label": None,
        "signature_html": signature_html,
        "recipients": recipients,
        "variables": variables,
        "customer": customer,
    }


async def _build_statement_surface(
    db: AsyncSession, *, org_id, customer_id, base_url: str | None
) -> dict:
    """Default content for customer_statement."""
    from datetime import date as _date

    from app.modules.invoices.service import get_currency_symbol
    from app.modules.reports.service import get_customer_statement

    customer = await _load_customer(db, org_id=org_id, customer_id=customer_id)

    from app.modules.admin.models import Organisation

    org = (
        await db.execute(select(Organisation).where(Organisation.id == org_id))
    ).scalar_one_or_none()
    org_settings = (org.settings or {}) if org else {}
    org_name = org.name if org else "Your Company"
    org_email = org_settings.get("email") or org_settings.get("business_email") or ""
    org_phone = org_settings.get("phone") or org_settings.get("business_phone") or ""

    # Default the statement period to the last 12 months ending today.
    today = _date.today()
    period_start = today.replace(year=today.year - 1)
    period_end = today

    statement = await get_customer_statement(
        db, org_id, customer_id, period_start, period_end
    )
    closing_balance = (
        statement.get("closing_balance") if statement else None
    ) or 0
    currency = getattr(org, "base_currency", None) or "NZD"
    currency_symbol = get_currency_symbol(currency)
    total_outstanding = (
        f"{currency_symbol}{closing_balance:.2f}"
        if isinstance(closing_balance, (int, float))
        else f"{currency_symbol}{closing_balance}"
    )

    origin = _resolve_base_origin(base_url)
    statement_link = (
        f"{origin}/portal/{customer.portal_token}"
        if customer.portal_token
        else ""
    )

    recipient = customer.email if customer.email else None
    recipients = [recipient] if recipient else []

    extra = {
        "statement_period_start": str(period_start),
        "statement_period_end": str(period_end),
        "total_outstanding": total_outstanding,
        "statement_link": statement_link,
        "org_name": org_name,
        "org_email": org_email,
        "org_phone": org_phone,
    }
    variables = build_variable_context(
        "customer_statement", entity=customer, org=org, customer=customer, extra=extra
    )

    customer_first_name = customer.first_name or ""
    subject = f"Your account statement from {org_name}"
    body_text = (
        f"Hi {customer_first_name or 'there'},\n\n"
        f"Please find your account statement for the period "
        f"{period_start} to {period_end}.\n\n"
        f"Total outstanding: {total_outstanding}\n\n"
        f"If you have any questions, please contact us.\n\n"
        f"Kind regards,\n{org_name}\n"
    )

    signature_html = None
    if org_settings.get("email_signature_enabled") and (
        org_settings.get("email_signature") or ""
    ).strip():
        signature_html = org_settings.get("email_signature")

    return {
        "subject": subject,
        "body_text": body_text,
        "cta_url": None,
        "cta_label": None,
        "signature_html": signature_html,
        "recipients": recipients,
        "variables": variables,
        "customer": customer,
    }


async def _build_portal_surface(
    db: AsyncSession, *, org_id, customer_id, base_url: str | None
) -> dict:
    """Default content for portal_link (mirrors customers.service.send_portal_link)."""
    customer = await _load_customer(db, org_id=org_id, customer_id=customer_id)

    from app.modules.admin.models import Organisation

    org = (
        await db.execute(select(Organisation).where(Organisation.id == org_id))
    ).scalar_one_or_none()
    org_settings = (org.settings or {}) if org else {}
    org_name = org.name if org else "Workshop"
    org_email = org_settings.get("email") or org_settings.get("business_email") or ""
    org_phone = org_settings.get("phone") or org_settings.get("business_phone") or ""

    origin = _resolve_base_origin(base_url)
    portal_url = (
        f"{origin}/portal/{customer.portal_token}" if customer.portal_token else ""
    )

    customer_name = f"{customer.first_name or ''} {customer.last_name or ''}".strip()
    recipient = customer.email if customer.email else None
    recipients = [recipient] if recipient else []

    extra = {
        "portal_link": portal_url,
        "org_name": org_name,
        "org_email": org_email,
        "org_phone": org_phone,
    }
    variables = build_variable_context(
        "portal_link", entity=customer, org=org, customer=customer, extra=extra
    )

    subject = f"Your Portal Access Link — {org_name}"
    # send_portal_link builds an HTML body directly (not via the text renderer).
    body_html = (
        f"<p>Hi {customer_name or 'there'},</p>\n"
        f"<p>You can access your customer portal using the link below:</p>\n"
        f'<p><a href="{portal_url}" style="display:inline-block;padding:12px 24px;'
        f"background-color:#2563eb;color:#ffffff;text-decoration:none;"
        f'border-radius:6px;font-weight:600;">Open Your Portal</a></p>\n'
        f'<p>Or copy this link: <a href="{portal_url}">{portal_url}</a></p>\n'
        f"<p>From your portal you can view invoices, quotes, bookings, and more.</p>\n"
        f"<p>Kind regards,<br/>{org_name}</p>"
    )

    return {
        "subject": subject,
        "body_text": body_html,
        "body_is_html": True,
        "cta_url": None,
        "cta_label": None,
        "signature_html": None,
        "recipients": recipients,
        "variables": variables,
        "customer": customer,
    }


async def _build_reminder_surface(
    db: AsyncSession, *, org_id, template_type: str, customer_vehicle_id
) -> dict:
    """Default content for the vehicle expiry reminders.

    Mirrors reminder_queue_service: variable context + hardcoded HTML body.
    ``entity_id`` is the ``customer_vehicles`` link-row id.
    """
    from app.modules.admin.models import GlobalVehicle, Organisation
    from app.modules.customers.models import Customer
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle

    cv = (
        await db.execute(
            select(CustomerVehicle).where(
                CustomerVehicle.id == customer_vehicle_id,
                CustomerVehicle.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if cv is None:
        raise EntityNotFound("Vehicle link not found in this organisation")

    customer = (
        await db.execute(select(Customer).where(Customer.id == cv.customer_id))
    ).scalar_one_or_none()

    # Resolve the underlying vehicle (org-scoped first, then global).
    vehicle = None
    if cv.org_vehicle_id:
        vehicle = (
            await db.execute(
                select(OrgVehicle).where(OrgVehicle.id == cv.org_vehicle_id)
            )
        ).scalar_one_or_none()
    elif cv.global_vehicle_id:
        vehicle = (
            await db.execute(
                select(GlobalVehicle).where(
                    GlobalVehicle.id == cv.global_vehicle_id
                )
            )
        ).scalar_one_or_none()

    org = (
        await db.execute(select(Organisation).where(Organisation.id == org_id))
    ).scalar_one_or_none()
    org_settings = (org.settings or {}) if org else {}
    org_name = org.name if org else ""
    org_email = org_settings.get("email") or org_settings.get("business_email") or ""
    org_phone = org_settings.get("phone") or org_settings.get("business_phone") or ""

    date_field, date_variable = _REMINDER_FIELD_MAP[template_type]
    expiry_value = getattr(vehicle, date_field, None) if vehicle else None
    rego = getattr(vehicle, "rego", "") or "" if vehicle else ""
    make = getattr(vehicle, "make", "") or "" if vehicle else ""
    model = getattr(vehicle, "model", "") or "" if vehicle else ""

    _reminder_labels = {
        "wof_expiry_reminder": "WOF Expiry",
        "cof_expiry_reminder": "COF Expiry",
        "registration_expiry_reminder": "Registration Expiry",
        "service_due_reminder": "Service Due",
    }
    reminder_label = _reminder_labels[template_type]

    extra = {
        "vehicle_rego": rego,
        "vehicle_make": make,
        "vehicle_model": model,
        date_variable: str(expiry_value) if expiry_value else "",
        "org_name": org_name,
        "org_email": org_email,
        "org_phone": org_phone,
    }
    variables = build_variable_context(
        template_type,
        entity=cv,
        org=org,
        customer=customer,
        vehicle=vehicle,
        extra=extra,
    )

    recipient = customer.email if customer and customer.email else None
    recipients = [recipient] if recipient else []

    customer_first_name = (customer.first_name if customer else "") or ""
    vehicle_desc = " ".join(filter(None, [make, model])).strip()
    subject = f"{reminder_label} reminder for {rego}"
    body_html = (
        f"<p>Hi {customer_first_name},</p>"
        f"<p>{reminder_label} for your vehicle <strong>{rego}</strong>"
        f"{(' (' + vehicle_desc + ')') if vehicle_desc else ''}"
        f" is coming up on <strong>{expiry_value}</strong>.</p>"
        f"<p>Please contact {org_name}"
        f"{(' on ' + org_phone) if org_phone else ''}"
        f" to book your appointment.</p>"
    )

    return {
        "subject": subject,
        "body_text": body_html,
        "body_is_html": True,
        "cta_url": None,
        "cta_label": None,
        "signature_html": None,
        "recipients": recipients,
        "variables": variables,
        "customer": customer,
    }
