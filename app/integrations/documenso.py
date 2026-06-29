"""Documenso integration — per-organisation connection loader and errors.

OraInvoice integrates a **self-hosted Documenso** instance as its e-signature
engine. Unlike a single global integration credential, each organisation has its
**own Documenso Team** with its **own team-scoped API token** and **own webhook
secret**, stored envelope-encrypted in that organisation's
``esign_org_connections`` row (one row per org). This module provides the
**per-organisation** connection loader and the exception hierarchy the service
layer maps to human-readable errors.

This file deliberately contains **no global** ``get_documenso_base_url()`` /
``get_documenso_service_token()`` / ``get_documenso_webhook_secret()`` helpers:
credentials are per-tenant and are loaded only via
:func:`get_documenso_connection` (never from ``.env`` for API calls, R1.3).

The :class:`DocumensoClient` (constructed per organisation from a
:class:`DocumensoConnection`) lives alongside these definitions and speaks
**Documenso's v2 RPC API** (``/api/v2/document/*``, ``/api/v2/envelope/*``).
This is the *real* shape of self-hosted Documenso's v2 surface — an RPC-style
API where the document is created (with the PDF uploaded inline as
``multipart/form-data``) via ``POST /api/v2/document/create``, fields are added
via ``POST /api/v2/document/field/create-many``, the document is sent via
``POST /api/v2/document/distribute`` and voided via
``POST /api/v2/envelope/cancel``. (It is **not** the RESTful
``/api/v2/documents`` collection shape, which does not exist on Documenso.)
Every request the client issues carries the organisation's own raw team-scoped
token in the ``Authorization`` header (no ``Bearer`` prefix); the call is scoped
to the organisation's Documenso Team **by the token itself** (v2 derives the
team from the team-scoped token, so no separate ``teamId`` is sent on the wire),
runs over HTTPS only (internal HTTP allowed for private hosts via the dev flag),
uses an explicit timeout, and retries transient failures with exponential
backoff.

Refs: requirements 1.3, 1.9, 13.7, 15.1; design §"DocumensoClient",
§"Per-org connection config and lifecycle".
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.encryption import envelope_decrypt_str
from app.modules.esignatures.models import EsignOrgConnection

logger = logging.getLogger(__name__)


def _is_private_host(host: str | None) -> bool:
    """True when ``host`` is a private / loopback / internal-DNS name.

    Covers the trusted-network cases where a Documenso API call never leaves
    the host or a private network: loopback (``localhost``/127.0.0.0/8/::1),
    RFC1918 + link-local + unique-local IPs, Docker service names (a single
    label with no dot, e.g. ``documenso``), and the conventional internal
    suffixes ``.internal`` / ``.local`` / ``.docker``. Any public, routable
    host returns ``False`` so it still requires HTTPS.
    """
    if not host:
        return False
    host = host.strip().lower()
    if host == "localhost":
        return True
    # IP literal? classify by address scope.
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        pass
    # Hostname: single-label (Docker service / short name) or internal suffix.
    if "." not in host:
        return True
    return host.endswith((".internal", ".local", ".docker"))


def _validate_documenso_url(url: str, *, what: str) -> None:
    """Enforce the transport policy for a Documenso URL.

    HTTPS is always accepted. Plain HTTP is rejected (R15.4) **unless** the
    host is private/internal AND ``esign_allow_insecure_internal_base_url`` is
    enabled — the trusted-network escape hatch for container-to-container
    calls. A public HTTP host is always rejected.
    """
    parsed = urlparse(url or "")
    scheme = parsed.scheme.lower()
    if scheme == "https":
        return
    if (
        scheme == "http"
        and settings.esign_allow_insecure_internal_base_url
        and _is_private_host(parsed.hostname)
    ):
        logger.warning(
            "Using plaintext HTTP for Documenso %s to internal host %r "
            "(esign_allow_insecure_internal_base_url is enabled).",
            what,
            parsed.hostname,
        )
        return
    raise DocumensoError(
        f"Documenso {what} must use HTTPS; "
        f"refusing to use a {scheme or 'schemeless'} URL."
    )


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class DocumensoError(Exception):
    """Base class for all Documenso integration failures."""


class DocumensoNotConfiguredError(DocumensoError):
    """Raised when the requesting organisation has no Documenso connection.

    The service layer maps this to a human-readable "integration not
    configured" error for **every** Documenso operation (R1.9) and for the
    connection test specifically (R1.10).
    """


class DocumensoApiError(DocumensoError):
    """Raised when Documenso returns a non-2xx response or an invalid payload.

    ``status`` carries the upstream HTTP status code where one is available
    (``None`` for transport-level failures such as timeouts).
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Per-org connection value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumensoConnection:
    """A decrypted, ready-to-use Documenso connection for a single organisation.

    Carries everything a per-org :class:`DocumensoClient` needs to call that
    organisation's own Documenso Team plus the webhook secret used to
    authenticate inbound webhooks. The two secret fields hold **decrypted**
    plaintext and must never be logged or returned in an API response.
    """

    base_url: str
    service_token: str  # decrypted team-scoped token (raw, NO "Bearer" prefix)
    webhook_secret: str  # decrypted per-org webhook secret
    documenso_team_id: str | None
    webhook_routing_id: str
    is_verified: bool


# ---------------------------------------------------------------------------
# Short-TTL in-memory cache — keyed BY org_id (NOT a global singleton)
# ---------------------------------------------------------------------------

_CACHE_TTL = 300  # 5 minutes
_connection_cache: dict[uuid.UUID, tuple[float, DocumensoConnection]] = {}


def invalidate_documenso_connection_cache(org_id: uuid.UUID | str | None = None) -> None:
    """Invalidate cached connection(s).

    Call this whenever an organisation's ``esign_org_connections`` row is saved
    or its verification flag changes so the next :func:`get_documenso_connection`
    re-reads from the database. With no argument, clears the entire cache.
    """
    if org_id is None:
        _connection_cache.clear()
        return
    key = org_id if isinstance(org_id, uuid.UUID) else uuid.UUID(str(org_id))
    _connection_cache.pop(key, None)


# ---------------------------------------------------------------------------
# Per-org connection loader
# ---------------------------------------------------------------------------


async def get_documenso_connection(
    db: AsyncSession, org_id: uuid.UUID | str
) -> DocumensoConnection:
    """Load and decrypt the calling organisation's Documenso connection.

    Reads the organisation's ``esign_org_connections`` row (org-scoped under
    RLS via the caller's ``db`` session), decrypts the team-scoped service token
    and webhook secret **at call time** with
    :func:`~app.core.encryption.envelope_decrypt_str`, and returns a
    :class:`DocumensoConnection`. Results are cached per ``org_id`` for
    ``_CACHE_TTL`` seconds.

    Args:
        db: An async session whose RLS context is already scoped to ``org_id``.
        org_id: The organisation whose connection to load.

    Returns:
        The decrypted :class:`DocumensoConnection` for the organisation.

    Raises:
        DocumensoNotConfiguredError: When the organisation has no connection
            row (R1.9). Credentials are **never** read from ``.env`` (R1.3).
    """
    key = org_id if isinstance(org_id, uuid.UUID) else uuid.UUID(str(org_id))

    cached = _connection_cache.get(key)
    if cached is not None:
        ts, conn = cached
        if (time.monotonic() - ts) < _CACHE_TTL:
            return conn
        # Expired — drop it and fall through to a fresh load.
        _connection_cache.pop(key, None)

    result = await db.execute(
        select(EsignOrgConnection).where(EsignOrgConnection.org_id == key)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise DocumensoNotConfiguredError(
            "This organisation's Documenso integration is not configured."
        )

    service_token = (
        envelope_decrypt_str(row.service_token_encrypted)
        if row.service_token_encrypted
        else ""
    )
    webhook_secret = (
        envelope_decrypt_str(row.webhook_secret_encrypted)
        if row.webhook_secret_encrypted
        else ""
    )

    conn = DocumensoConnection(
        base_url=row.base_url,
        service_token=service_token,
        webhook_secret=webhook_secret,
        documenso_team_id=row.documenso_team_id,
        webhook_routing_id=row.webhook_routing_id,
        is_verified=row.is_verified,
    )

    _connection_cache[key] = (time.monotonic(), conn)
    return conn


# ---------------------------------------------------------------------------
# Recipient roles — OraInvoice (lowercase) → Documenso (UPPERCASE)
# ---------------------------------------------------------------------------

# Documenso recipient roles are UPPERCASE. The OraInvoice API accepts the
# lowercase variants and maps them here when building the wire payload.
_ROLE_MAP: dict[str, str] = {
    "signer": "SIGNER",
    "viewer": "VIEWER",
    "cc": "CC",
    "approver": "APPROVER",
    "assistant": "ASSISTANT",
}


def map_recipient_role(role: str) -> str:
    """Map an OraInvoice recipient role to its UPPERCASE Documenso role.

    Accepts the lowercase OraInvoice values (e.g. ``signer``/``viewer``) and
    returns the UPPERCASE Documenso role (``SIGNER``/``VIEWER``). Matching is
    case-insensitive so an already-uppercase value also resolves.

    Raises:
        DocumensoError: When ``role`` is not a recognised Documenso role.
    """
    key = (role or "").strip().lower()
    try:
        return _ROLE_MAP[key]
    except KeyError:
        raise DocumensoError(
            f"Unsupported recipient role {role!r}; expected one of "
            f"{', '.join(sorted(_ROLE_MAP))}."
        ) from None


# ---------------------------------------------------------------------------
# Value objects for the multi-step create flow
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecipientSpec:
    """A recipient to register on a Documenso document.

    ``role`` is the OraInvoice-level role (lowercase ``signer``/``viewer``); it is
    mapped to the UPPERCASE Documenso role when the wire payload is built.

    ``signing_order`` is the optional **1-based** position this recipient holds
    in a sequential signing order (R15). It is send-time input: when present and
    the signing-order capability is enabled, it is emitted as the per-recipient
    ``signingOrder`` key on ``POST /api/v2/document/create``. ``None`` means the
    recipient carries no explicit position (the parallel/backward-compatible
    default). **CRITICAL — capability gated (capability assumption #4,
    docs/documenso-capability-matrix.md capability (d) is UNVERIFIED):** the
    position is only placed on the wire when
    :data:`settings.esign_signing_order_supported` is ``True``. While the flag
    is ``False`` (the conservative default) the value is still accepted and
    stored on the spec but is **omitted** from the create payload, so sequential
    degrades to parallel and no sequential enforcement is claimed.
    """

    name: str
    email: str
    role: str = "signer"
    signing_order: int | None = None


@dataclass(frozen=True)
class CreatedRecipient:
    """A recipient as returned by Documenso after document creation.

    ``signing_url`` is the one-time signing link (R5.1) captured onto the
    corresponding ``esign_recipients`` row, built as ``{public}/sign/{token}``
    from the recipient's per-recipient ``token``; ``token`` is Documenso's
    per-recipient token. ``recipient_id`` is the recipient's numeric Documenso
    id (stringified) used to bind signature fields.
    """

    recipient_id: str
    email: str
    role: str
    token: str | None = None
    signing_url: str | None = None


@dataclass(frozen=True)
class DocumensoFieldSpec:
    """A single wire-ready field for ``POST /api/v2/document/field/create-many``.

    This is the **multi-field** analogue of the arguments
    :meth:`DocumensoClient.place_signature_field` takes for a single field. It
    carries values **already mapped to the Documenso wire shape** so that
    :meth:`DocumensoClient.create_fields` can emit exactly the proven payload —
    the same keys ``place_signature_field`` sends, just N fields instead of one:

    * ``recipient_id`` — the **resolved integer** Documenso recipient id this
      field is bound to (reconciled upstream by email against the created
      recipients), serialised to the wire key ``recipientId``.
    * ``type`` — the **already-mapped UPPERCASE** Documenso field type
      (``SIGNATURE`` / ``INITIALS`` / ``NAME`` / ``DATE`` / ``EMAIL`` / ``TEXT``).
      Mapping from the lowercase OraInvoice type happens upstream
      (``field_mapping.map_field_type``); this value goes on the wire verbatim.
    * ``page_number`` — the **1-based** page number → wire key ``pageNumber``.
    * ``page_x`` / ``page_y`` — the normalized top-left position → wire keys
      ``pageX`` / ``pageY``. OraInvoice's internal ``NormalizedRect`` names these
      ``positionX`` / ``positionY`` (and ``page`` for the page); they are renamed
      here so the wire keys match ``place_signature_field`` precisely. The raw
      ``positionX`` / ``positionY`` / ``page`` keys are **never** sent.
    * ``width`` / ``height`` — the normalized size → wire keys ``width`` /
      ``height``.
    * ``field_meta`` — the optional Documenso ``fieldMeta`` object
      (``required`` / ``label`` / ``placeholder``), built upstream by
      ``field_mapping.build_field_meta``. It is only emitted on the wire when the
      target build is known to honour it (see :meth:`DocumensoClient.create_fields`).
    """

    recipient_id: int
    type: str
    page_number: int
    page_x: float
    page_y: float
    width: float
    height: float
    field_meta: dict[str, Any] | None = None


@dataclass(frozen=True)
class DocumensoCreateResult:
    """The result of creating a Documenso document (``POST /api/v2/document/create``).

    Carries the Documenso ``document_id`` (the **numeric** id, stringified —
    used by the field / distribute / download / status calls), the
    ``envelope_id`` (the **string** envelope id — used by the void/cancel call),
    and the created recipients (each with its token + signing URL). ``upload_url``
    is retained for backwards compatibility but is unused under the v2 RPC flow,
    where the PDF is uploaded inline with the create request (no presigned PUT).
    """

    document_id: str
    upload_url: str = ""
    recipients: list[CreatedRecipient] = field(default_factory=list)
    envelope_id: str | None = None


# ---------------------------------------------------------------------------
# DocumensoClient — per-organisation async httpx client (Documenso v2 RPC API)
# ---------------------------------------------------------------------------


class DocumensoClient:
    """Async ``httpx`` client over **Documenso's v2 RPC API**, per organisation.

    The client is constructed per organisation (via :meth:`for_org`) with that
    organisation's ``base_url`` and raw team-scoped token. It speaks the *real*
    Documenso v2 RPC surface:

    * ``POST /api/v2/document/create`` — multipart create (PDF uploaded inline);
    * ``GET  /api/v2/document/{id}`` — fetch the document incl. recipients;
    * ``POST /api/v2/document/field/create-many`` — add SIGNATURE fields;
    * ``POST /api/v2/document/distribute`` — send the document for signature;
    * ``GET  /api/v2/document/{id}/download?version=signed`` — signed PDF bytes;
    * ``POST /api/v2/envelope/cancel`` — void the document.

    Every request it issues:

    * goes over **HTTPS** only — a non-HTTPS ``base_url`` is rejected at
      construction time (R15.4), except internal/private hosts when the
      trusted-network escape hatch is enabled;
    * carries that organisation's own raw token in ``Authorization`` with **no**
      ``Bearer`` prefix (R13.7);
    * is scoped to that organisation's Documenso Team **by the token** (the v2
      RPC API derives the team from the team-scoped token; no ``teamId`` is sent
      on the wire);
    * uses an explicit :class:`httpx.Timeout` (never the unbounded default);
    * retries transient failures (timeouts, 5xx) up to 3 attempts with
      exponential backoff (1s / 2s / 4s), while non-transient failures (4xx,
      invalid payloads) raise :class:`DocumensoApiError` immediately.

    The injected :class:`httpx.AsyncClient` is owned and closed by the caller —
    the client never instantiates a per-request pool and leaves it unclosed.
    """

    #: Maximum number of attempts (1 initial + 2 retries) for a transient call.
    MAX_ATTEMPTS = 3
    #: Backoff delays (seconds) applied before each retry: 1s, 2s, 4s.
    BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 4.0)
    #: Default per-request timeout — never the unbounded httpx default.
    DEFAULT_TIMEOUT = 10.0

    def __init__(
        self,
        base_url: str,
        token: str,
        http: httpx.AsyncClient,
        *,
        team_id: str | None = None,
        public_base_url: str | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> None:
        # HTTPS always; plain HTTP only for private/internal hosts when the
        # trusted-network escape hatch is enabled (R15.4).
        _validate_documenso_url(base_url, what="base URL")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._http = http
        # Retained for reference/diagnostics; NOT sent on the wire (the v2 RPC
        # API scopes calls by the team-scoped token, not a teamId param).
        self._team_id = team_id
        # Public origin used to build signer links; falls back to the (possibly
        # internal) base URL when no dedicated public URL is configured.
        self._public_base_url = (public_base_url or base_url).rstrip("/")
        if isinstance(timeout, httpx.Timeout):
            self._timeout: httpx.Timeout = timeout
        else:
            self._timeout = httpx.Timeout(timeout or self.DEFAULT_TIMEOUT)

    @classmethod
    def for_org(
        cls, conn: DocumensoConnection, http: httpx.AsyncClient
    ) -> "DocumensoClient":
        """Build a client for a single organisation from its connection.

        Uses the organisation's ``base_url`` and raw team-scoped ``service_token``
        so the whole flow is scoped to that organisation's own Documenso Team via
        the token (R13.7). The public signer origin is taken from
        ``settings.esign_public_documenso_url`` when set, else the connection's
        own ``base_url``.
        """
        return cls(
            conn.base_url,
            conn.service_token,
            http,
            team_id=conn.documenso_team_id,
            public_base_url=(settings.esign_public_documenso_url or conn.base_url),
        )

    # -- internals ----------------------------------------------------------

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._base_url}{path}"

    def _auth_headers(self) -> dict[str, str]:
        # Raw team-scoped token — NO "Bearer" prefix (Documenso convention).
        return {"Authorization": self._token}

    @staticmethod
    def _is_transient_status(status: int) -> bool:
        return status >= 500

    async def _send(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue a request with explicit timeout + transient-failure retry.

        Retries ``httpx.TimeoutException`` and 5xx responses up to
        :attr:`MAX_ATTEMPTS` with exponential backoff. 4xx responses raise
        :class:`DocumensoApiError` immediately (no retry).
        """
        url = self._url(path)
        req_headers: dict[str, str] = {}
        if auth:
            req_headers.update(self._auth_headers())
        if headers:
            req_headers.update(headers)

        for attempt in range(self.MAX_ATTEMPTS):
            is_last = attempt == self.MAX_ATTEMPTS - 1
            try:
                resp = await self._http.request(
                    method,
                    url,
                    headers=req_headers,
                    timeout=self._timeout,
                    **kwargs,
                )
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if self._is_transient_status(status) and not is_last:
                    await asyncio.sleep(self.BACKOFF_SCHEDULE[attempt])
                    continue
                # Non-transient (4xx) or exhausted retries on 5xx.
                raise DocumensoApiError(
                    f"Documenso returned HTTP {status} for {method} {path}.",
                    status=status,
                ) from exc
            except httpx.TimeoutException as exc:
                if not is_last:
                    await asyncio.sleep(self.BACKOFF_SCHEDULE[attempt])
                    continue
                raise DocumensoApiError(
                    f"Documenso request timed out for {method} {path}.",
                    status=None,
                ) from exc
            except httpx.HTTPError as exc:
                # Other transport-level errors (connection, protocol) — treat as
                # transient and retry, else surface as a humanized API error.
                if not is_last:
                    await asyncio.sleep(self.BACKOFF_SCHEDULE[attempt])
                    continue
                raise DocumensoApiError(
                    f"Documenso request failed for {method} {path}.",
                    status=None,
                ) from exc

        # Unreachable — the loop always returns or raises.
        raise DocumensoApiError(  # pragma: no cover
            f"Documenso request exhausted retries for {method} {path}."
        )

    @staticmethod
    def _parse_json(resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError as exc:
            raise DocumensoApiError(
                "Documenso returned an invalid (non-JSON) response."
            ) from exc
        if not isinstance(data, dict):
            raise DocumensoApiError("Documenso returned an unexpected response shape.")
        return data

    def _signing_url_for(self, token: str | None) -> str | None:
        """Build the one-time signer link ``{public}/sign/{token}`` (R5.1).

        Returns ``None`` when there is no token. Uses the configured public
        origin (``settings.esign_public_documenso_url``) so the link is one a
        signer's browser can open, even when the API ``base_url`` is an internal
        host.
        """
        if not token:
            return None
        return f"{self._public_base_url}/sign/{token}"

    # -- multi-step create flow (Documenso v2 RPC) -------------------------

    async def create_document(
        self,
        *,
        title: str,
        recipients: list[RecipientSpec],
        pdf_bytes: bytes,
    ) -> DocumensoCreateResult:
        """Create a Documenso document with the PDF uploaded inline.

        Performs ``POST /api/v2/document/create`` as ``multipart/form-data`` — a
        JSON ``payload`` part (title + recipients, each role mapped to its
        UPPERCASE Documenso role) plus the raw PDF ``file`` part. Documenso's v2
        RPC create returns only ``{ id, envelopeId }`` (no recipients), so this
        then issues ``GET /api/v2/document/{id}`` to read back the created
        recipients with their per-recipient ``token`` (used to build the signing
        URL) and numeric recipient id (used to bind signature fields).

        Returns the numeric ``document_id`` (stringified), the string
        ``envelope_id`` (used by the void/cancel call), and the created
        recipients (each with a ``token`` + ``signing_url``).

        **Signing order (R15) — capability gated (capability assumption #4,
        docs/documenso-capability-matrix.md capability (d) is UNVERIFIED):** a
        recipient's optional 1-based :attr:`RecipientSpec.signing_order` is
        emitted as a per-recipient ``signingOrder`` key **only** when
        :data:`settings.esign_signing_order_supported` is ``True``. While the
        flag is ``False`` (the conservative default) every ``signingOrder``
        position is omitted from the wire — sequential degrades to parallel and
        no sequential enforcement is claimed. The schema field is still accepted
        and carried on each :class:`RecipientSpec` regardless.
        """
        send_signing_order = settings.esign_signing_order_supported
        wire_recipients: list[dict[str, Any]] = []
        for r in recipients:
            wire_r: dict[str, Any] = {
                "name": r.name,
                "email": r.email,
                "role": map_recipient_role(r.role),
            }
            if send_signing_order and r.signing_order is not None:
                wire_r["signingOrder"] = int(r.signing_order)
            wire_recipients.append(wire_r)
        payload: dict[str, Any] = {
            "title": title,
            "recipients": wire_recipients,
        }
        resp = await self._send(
            "POST",
            "/api/v2/document/create",
            data={"payload": json.dumps(payload)},
            files={"file": ("document.pdf", pdf_bytes, "application/pdf")},
        )
        created_data = self._parse_json(resp)
        document_id = created_data.get("id")
        envelope_id = created_data.get("envelopeId")
        if document_id is None:
            raise DocumensoApiError(
                "Documenso create-document response was missing the document id."
            )
        document_id = str(document_id)

        # Read back recipients (with tokens + numeric ids) — the create response
        # does not include them.
        doc = await self._get_document(document_id)
        created = self._recipients_from_document(doc)

        return DocumensoCreateResult(
            document_id=document_id,
            envelope_id=str(envelope_id) if envelope_id is not None else None,
            recipients=created,
        )

    async def _get_document(self, document_id: str) -> dict[str, Any]:
        """Fetch a document (incl. recipients + fields) via ``GET /document/{id}``."""
        resp = await self._send("GET", f"/api/v2/document/{int(document_id)}")
        return self._parse_json(resp)

    def _recipients_from_document(
        self, doc: dict[str, Any]
    ) -> list[CreatedRecipient]:
        """Map a document's ``recipients[...]`` array to :class:`CreatedRecipient`."""
        created: list[CreatedRecipient] = []
        for rr in doc.get("recipients") or []:
            if not isinstance(rr, dict):
                continue
            token = rr.get("token")
            created.append(
                CreatedRecipient(
                    recipient_id=str(rr.get("id") or ""),
                    email=rr.get("email") or "",
                    role=rr.get("role") or "",
                    token=token,
                    signing_url=self._signing_url_for(token),
                )
            )
        return created

    async def place_signature_field(
        self,
        document_id: str,
        *,
        recipient_id: str,
        page_number: int,
        page_x: float,
        page_y: float,
        page_width: float,
        page_height: float,
    ) -> None:
        """Place a SIGNATURE field for a signer.

        ``POST /api/v2/document/field/create-many`` with a single SIGNATURE
        field bound to the signer's numeric recipient id. ``page_width`` /
        ``page_height`` map to the v2 ``width`` / ``height`` field keys.
        """
        payload: dict[str, Any] = {
            "documentId": int(document_id),
            "fields": [
                {
                    "recipientId": int(recipient_id),
                    "type": "SIGNATURE",
                    "pageNumber": page_number,
                    "pageX": page_x,
                    "pageY": page_y,
                    "width": page_width,
                    "height": page_height,
                }
            ],
        }
        await self._send(
            "POST", "/api/v2/document/field/create-many", json=payload
        )

    async def create_fields(
        self, document_id: str | int, fields: list[DocumensoFieldSpec]
    ) -> None:
        """Create a sender-defined Field_Set on a document (R8.1, R8.2).

        ``POST /api/v2/document/field/create-many`` with the **full** Field_Set —
        the multi-field generalisation of :meth:`place_signature_field`. The
        payload mirrors the proven single-field shape **exactly**: the same
        envelope ``{ "documentId": int, "fields": [ ... ] }`` and the same
        per-field keys (``recipientId``, ``type``, ``pageNumber``, ``pageX``,
        ``pageY``, ``width``, ``height``, and optionally ``fieldMeta``), just N
        fields instead of one. The OraInvoice-internal coordinate names
        (``positionX`` / ``positionY`` / ``page``) are already renamed to the wire
        keys (``pageX`` / ``pageY`` / ``pageNumber``) on each
        :class:`DocumensoFieldSpec`, so no ``positionX`` / ``positionY`` / ``page``
        key is ever sent.

        Each spec carries its **already-mapped UPPERCASE** ``type`` and its
        **resolved integer** ``recipient_id`` (reconciled upstream), so this
        method performs no type mapping or recipient reconciliation itself.

        ``fieldMeta`` is included per field **only** when
        ``settings.esign_field_create_many_honours_field_meta`` is enabled — i.e.
        when a live capability probe (spec task 9.2) has confirmed the target
        Documenso build accepts and honours it. Per
        ``docs/documenso-capability-matrix.md`` this is currently UNVERIFIED, so
        the conservative default OMITS ``fieldMeta`` on the wire (a no-op);
        ``required`` / ``label`` / ``placeholder`` then stay advisory /
        OraInvoice-only. The spec still carries the built ``field_meta`` so the
        behaviour flips on with the flag and no further wiring.

        Reuses the same per-org client construction (:meth:`for_org`), raw
        team-scoped ``Authorization`` header, explicit timeout, and
        transient-failure retry as every other call. The single-field
        :meth:`place_signature_field` is retained unchanged for the
        auto-placement fallback path.
        """
        send_field_meta = settings.esign_field_create_many_honours_field_meta
        wire_fields: list[dict[str, Any]] = []
        for spec in fields:
            wire: dict[str, Any] = {
                "recipientId": int(spec.recipient_id),
                "type": spec.type,
                "pageNumber": spec.page_number,
                "pageX": spec.page_x,
                "pageY": spec.page_y,
                "width": spec.width,
                "height": spec.height,
            }
            if send_field_meta and spec.field_meta is not None:
                wire["fieldMeta"] = spec.field_meta
            wire_fields.append(wire)

        payload: dict[str, Any] = {
            "documentId": int(document_id),
            "fields": wire_fields,
        }
        await self._send(
            "POST", "/api/v2/document/field/create-many", json=payload
        )

    def _field_ids_from_document(self, doc: dict[str, Any]) -> list[int]:
        """Extract the numeric ids of a document's existing fields.

        Reads the ``fields[...]`` array returned by ``GET /document/{id}`` and
        returns each field's numeric ``id``. Used by :meth:`replace_fields` to
        know which fields to delete before re-creating the edited set. Entries
        without a usable integer id are skipped.
        """
        field_ids: list[int] = []
        for ff in doc.get("fields") or []:
            if not isinstance(ff, dict):
                continue
            raw_id = ff.get("id")
            if raw_id is None:
                continue
            try:
                field_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        return field_ids

    async def replace_fields(
        self, document_id: str | int, specs: list[DocumensoFieldSpec]
    ) -> None:
        """Atomically replace a document's whole Field_Set (R13.3, R13.8).

        The edit-after-send persistence verb: read the document's current
        fields (``GET /document/{id}``), delete them, then re-create the edited
        set via :meth:`create_fields` so **only** the edited set remains. The
        replace is all-or-nothing — if either the delete step or the
        create-many step fails, this raises (the failure propagates as a
        :class:`DocumensoApiError` / :class:`DocumensoError`) so the service
        leaves the prior field set in effect and returns a humanized error with
        **no partial apply** (R13.8). It reuses the same per-org client
        (:meth:`for_org`), raw team-scoped ``Authorization`` header, explicit
        timeout, and transient-failure retry as every other call, and delegates
        the create step to :meth:`create_fields` (so ``fieldMeta`` gating is
        identical to a fresh send).

        **CRITICAL — capability gated (capability assumption #3,
        docs/documenso-capability-matrix.md capability (c)).** The in-place
        delete-then-recreate path is **UNVERIFIED**: the client has no proven
        Documenso field-deletion/replacement endpoint. It is therefore gated
        behind :data:`settings.esign_field_replace_supported` (default
        ``False``, mirroring ``esign_field_create_many_honours_field_meta``).
        When the flag is ``False`` this method does **not** mutate anything and
        immediately raises a clear :class:`DocumensoError` signalling that
        in-place replace is unsupported, so edit-after-send degrades to
        Void_And_Recreate only (proven via :meth:`cancel_document` — Task 16.4
        handles that degrade). Flip the flag to ``True`` only once a live
        capability probe (Task 9.2) confirms the target build supports
        deleting/replacing fields on a ``sent``, unsigned document; the
        delete-then-create-many body below then takes effect with no further
        wiring.
        """
        if not settings.esign_field_replace_supported:
            raise DocumensoError(
                "In-place field replacement is not supported by this Documenso "
                "build (capability unverified); edit-after-send must degrade to "
                "Void_And_Recreate. Set esign_field_replace_supported=True only "
                "once a live capability probe confirms the delete/replace-field "
                "capability."
            )

        # --- delete the existing fields, then re-create the edited set -------
        # Resolve the current field ids and delete each one. Any failure here
        # (or in the create-many below) raises, leaving the prior set in effect
        # — the atomic, no-partial-apply contract (R13.8).
        doc = await self._get_document(str(document_id))
        for field_id in self._field_ids_from_document(doc):
            await self._send(
                "POST",
                "/api/v2/document/field/delete",
                json={"documentId": int(document_id), "fieldId": field_id},
            )

        await self.create_fields(document_id, specs)

    async def send_document(
        self, document_id: str, *, signing_order_mode: str = "parallel"
    ) -> None:
        """Send the document for signature (``POST /api/v2/document/distribute``).

        Distributes by email (Documenso emails each recipient their signing
        link); OraInvoice also surfaces the captured per-recipient signing URLs
        in its own UI.

        ``signing_order_mode`` selects the Documenso distribution mode (R15):
        ``"parallel"`` (the default and backward-compatible behaviour — all
        signers may sign at once) or ``"sequential"`` (each signer is invited
        only after the previous one signs). The mode maps to Documenso's
        ``distributionMode`` of ``PARALLEL`` / ``SEQUENTIAL``.

        **CRITICAL — capability gated (capability assumption #4,
        docs/documenso-capability-matrix.md capability (d) is UNVERIFIED):** the
        ``SEQUENTIAL`` mode is only placed on the wire when
        :data:`settings.esign_signing_order_supported` is ``True``. While the
        flag is ``False`` (the conservative default) a ``"sequential"`` request
        DEGRADES to ``PARALLEL`` — the distribution is always ``PARALLEL`` and no
        sequential enforcement is claimed (consistent with
        :meth:`create_document` omitting the per-recipient ``signingOrder``
        positions under the same flag). Backward compatibility: a caller that
        passes no ``signing_order_mode`` distributes ``PARALLEL`` exactly as
        before.
        """
        mode = (signing_order_mode or "parallel").strip().lower()
        if mode == "sequential" and settings.esign_signing_order_supported:
            distribution_mode = "SEQUENTIAL"
        else:
            # Default, unknown, or sequential-while-unsupported all degrade to
            # PARALLEL (no sequential enforcement claimed).
            distribution_mode = "PARALLEL"
        payload: dict[str, Any] = {
            "documentId": int(document_id),
            "meta": {
                "distributionMethod": "EMAIL",
                "distributionMode": distribution_mode,
            },
        }
        await self._send("POST", "/api/v2/document/distribute", json=payload)

    async def download_signed(self, document_id: str) -> bytes:
        """Retrieve the completed, fully-signed PDF as raw bytes (R9.1).

        ``GET /api/v2/document/{id}/download?version=signed`` returns the signed
        PDF bytes directly (this works regardless of the Documenso object-storage
        transport; the ``download-beta`` presigned-URL variant requires S3).
        """
        resp = await self._send(
            "GET",
            f"/api/v2/document/{int(document_id)}/download",
            params={"version": "signed"},
        )
        return resp.content

    async def cancel_document(self, document_id: str) -> None:
        """Void the document in Documenso, issuing ``DOCUMENT_CANCELLED`` (R7.2).

        The v2 cancel endpoint (``POST /api/v2/envelope/cancel``) is keyed on the
        **string** ``envelopeId``, while OraInvoice stores the **numeric**
        document id. The envelope id is resolved on demand via
        ``GET /api/v2/document/{id}``; a document that no longer exists (404) is
        treated as already-gone and the cancel is a no-op.
        """
        try:
            doc = await self._get_document(document_id)
        except DocumensoApiError as exc:
            if exc.status == 404:
                return
            raise
        envelope_id = doc.get("envelopeId")
        if not envelope_id:
            raise DocumensoApiError(
                "Documenso document is missing its envelope id; cannot cancel."
            )
        await self._send(
            "POST",
            "/api/v2/envelope/cancel",
            json={"envelopeId": str(envelope_id), "reason": "Voided in OraInvoice"},
        )

    async def test_connection(self) -> bool:
        """Perform an authenticated request to verify the org's credentials (R1.6).

        Probes ``GET /api/v2/document/{id}`` for an id that does not exist: a
        **valid** team-scoped token authenticates and gets ``404`` (the document
        is simply not found), while an **invalid** token is rejected with
        ``401``/``403`` *before* any lookup. So ``2xx`` or ``404`` → verified;
        ``401``/``403`` → not verified; any other failure (5xx, timeout) surfaces
        as :class:`DocumensoApiError` for the service to humanize.
        """
        try:
            await self._send("GET", "/api/v2/document/999999999")
        except DocumensoApiError as exc:
            if exc.status in (401, 403):
                return False
            if exc.status == 404:
                # Token authenticated; the probe document just doesn't exist.
                return True
            raise
        return True
