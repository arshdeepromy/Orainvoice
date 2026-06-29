"""Documenso auto-provisioning adapters — OPTIONAL, best-effort, isolated (R20).

OraInvoice can *optionally* auto-provision an organisation's Documenso Team,
its team-scoped API token, and its webhook subscription so a Global Admin does
not have to create them by hand in the Documenso UI. This is a **convenience
only** layered on top of the per-org **manual** connection model (R1, R19),
which remains the **guaranteed, supported fallback at all times** (R20.4).

WHY THIS IS UNSUPPORTED AND UPGRADE-FRAGILE
-------------------------------------------
Documenso's **public REST API exposes NO endpoints** for creating a Team,
minting a team API token, or creating a webhook subscription — those operations
live only behind Documenso's own UI/admin layer. Any automatic provisioning
must therefore drive Documenso's **unsupported internals**:

* :class:`TrpcProvisioningAdapter` calls Documenso's **internal admin tRPC**
  endpoints (the same ones its web UI calls); or
* :class:`DbProvisioningAdapter` writes **directly to Documenso's self-hosted
  PostgreSQL**.

Both approaches can break on a Documenso version bump (the tRPC contract or the
DB schema can change). The capability is gated behind the **platform-level**
flag ``ESIGN_PROVISIONING_MODE`` (``off | trpc | db``) so it can be disabled the
moment it stops working, with the manual path always available.

ISOLATION GUARANTEE
-------------------
Every adapter call is wrapped so that **any** exception (tRPC error, DB error,
schema mismatch, version drift) is caught and surfaced as a humanized
:class:`ProvisioningError`. An adapter failure **NEVER** corrupts or blocks the
manual path.

PLATFORM-LEVEL CREDENTIALS (NOT per-org)
----------------------------------------
The ``trpc`` adapter authenticates with a **platform-level** Documenso admin
session/credential and the ``db`` adapter uses a **platform-config** Documenso
DB URL. These are held by OraInvoice as **platform configuration**, are
**envelope-encrypted** at rest, are **NEVER** stored on any org's
``esign_org_connections`` row, and are used **only** for provisioning — never
for per-org Documenso API calls (those always use the org's own team-scoped
token, R13.7).

Refs: requirements 20.1, 20.4, 20.5; design §"Optional auto-provisioning".
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from app.config import settings
from app.core.encryption import envelope_decrypt_str

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Humanized, isolated error type
# ---------------------------------------------------------------------------


class ProvisioningError(Exception):
    """Any auto-provisioning failure surfaces as this — humanized and isolated.

    Carries a **human-readable message only** (never raw DB/tRPC/exception
    internals). Raising this type — and never letting a lower-level exception
    escape an adapter — is what keeps a provisioning failure from corrupting or
    blocking the manual connection path (R20.3/R20.4).
    """


# ---------------------------------------------------------------------------
# Result value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProvisionedTeam:
    """A Documenso Team created (or reused) by an adapter."""

    team_id: str


@dataclass(frozen=True)
class ProvisionedToken:
    """A freshly-minted team-scoped Documenso token.

    ``token`` is the **plaintext** team-scoped token, returned to OraInvoice
    **exactly once** so it can be persisted envelope-encrypted in
    ``esign_org_connections.service_token_encrypted``. Documenso stores only the
    token's *hash*, so the plaintext can never be recovered later — it must be
    captured here and is never logged.
    """

    token: str


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ProvisioningAdapter(Protocol):
    """Strategy interface for the optional Documenso auto-provisioning flow.

    Implementations are best-effort and **must** surface every failure as a
    :class:`ProvisioningError` (see module docstring). Each method is
    independently re-runnable so the orchestration can persist progress and
    recover-to-manual on any failure (R20.1, R20.3).
    """

    async def create_team(self, *, org: Any) -> ProvisionedTeam:
        """Create (or reuse) the organisation's Documenso Team."""
        ...

    async def mint_team_token(self, *, team_id: str) -> ProvisionedToken:
        """Mint a team-scoped API token; return its plaintext once."""
        ...

    async def ensure_webhook(
        self, *, team_id: str, routing_url: str, secret: str
    ) -> None:
        """Create (or confirm) the Team's webhook subscription."""
        ...


# ---------------------------------------------------------------------------
# Platform-credential loading (envelope-encrypted at rest)
# ---------------------------------------------------------------------------

#: Prefix marking a platform-config value that is stored envelope-encrypted
#: (base64 of the :func:`envelope_encrypt` blob). Values without this prefix are
#: treated as plaintext (acceptable for local dev).
_ENC_PREFIX = "enc:"


def _load_platform_secret(value: str) -> str:
    """Resolve a platform-config secret, decrypting it if envelope-encrypted.

    Platform provisioning credentials are held envelope-encrypted at rest. When
    the configured value carries the ``enc:`` prefix, the remainder is treated
    as base64 of an envelope-encryption blob and decrypted; otherwise the value
    is returned verbatim (plaintext, for local dev). Never logs the value.
    """
    if not value:
        return ""
    if value.startswith(_ENC_PREFIX):
        import base64

        try:
            blob = base64.b64decode(value[len(_ENC_PREFIX):])
            return envelope_decrypt_str(blob)
        except Exception as exc:  # pragma: no cover - defensive
            # Never leak the raw value or crypto internals.
            raise ProvisioningError(
                "The platform Documenso provisioning credential could not be "
                "decrypted; check the platform configuration."
            ) from exc
    return value


# ---------------------------------------------------------------------------
# tRPC adapter — drives Documenso's INTERNAL admin tRPC layer (UNSUPPORTED)
# ---------------------------------------------------------------------------


class TrpcProvisioningAdapter:
    """Provision via Documenso's **internal admin tRPC** layer.

    .. warning::

        **BEST-EFFORT, UNSUPPORTED, UPGRADE-FRAGILE.** This drives the tRPC
        endpoints Documenso's own web UI calls — **not** a public API. A
        Documenso version bump can change the tRPC contract and break this
        adapter without notice. It is gated behind ``ESIGN_PROVISIONING_MODE``
        so it can be disabled instantly; the manual path is the supported
        fallback at all times (R20.4).

    Authenticates with a **platform-level** Documenso admin session/credential
    held by OraInvoice as envelope-encrypted platform config (NOT a per-org
    credential, and never used for per-org Documenso API calls — R13.7).
    """

    #: Per-request timeout — never the unbounded httpx default.
    DEFAULT_TIMEOUT = 15.0

    def __init__(
        self,
        *,
        base_url: str,
        admin_token: str,
        http: httpx.AsyncClient | None = None,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._admin_token = admin_token or ""
        # An injected client is owned by the caller; otherwise one is created
        # per call inside ``async with`` so no connection pool is ever leaked.
        self._http = http
        self._timeout = httpx.Timeout(timeout or self.DEFAULT_TIMEOUT)

    # -- internals ----------------------------------------------------------

    def _trpc_url(self, procedure: str) -> str:
        # Documenso's web UI calls procedures under /api/trpc/<router.procedure>.
        return f"{self._base_url}/api/trpc/{procedure}"

    def _auth_headers(self) -> dict[str, str]:
        # The platform-level admin credential drives the admin tRPC layer. We
        # present it both as a session cookie (NextAuth-style) and bearer header
        # so the adapter works regardless of how the operator captured it. Never
        # logged.
        return {
            "Authorization": f"Bearer {self._admin_token}",
            "Cookie": self._admin_token,
            "Content-Type": "application/json",
        }

    async def _call(self, procedure: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Issue one tRPC mutation and return its parsed ``data`` object.

        All failures (transport, non-2xx, malformed payloads) raise plainly here
        and are converted to a humanized :class:`ProvisioningError` by the public
        method wrappers.
        """
        body = {"json": payload}
        if self._http is not None:
            resp = await self._http.post(
                self._trpc_url(procedure),
                json=body,
                headers=self._auth_headers(),
                timeout=self._timeout,
            )
        else:  # pragma: no cover - exercised via injected client in tests
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._trpc_url(procedure),
                    json=body,
                    headers=self._auth_headers(),
                )
        resp.raise_for_status()
        data = resp.json()
        # tRPC envelope: {"result": {"data": {"json": {...}}}} (single) — be
        # liberal about the exact nesting since the internal shape can drift.
        if isinstance(data, list):
            data = data[0] if data else {}
        result = (data or {}).get("result", {})
        inner = result.get("data", result)
        if isinstance(inner, dict) and "json" in inner:
            inner = inner["json"]
        if not isinstance(inner, dict):
            raise ValueError("unexpected tRPC response shape")
        return inner

    # -- ProvisioningAdapter ------------------------------------------------

    async def create_team(self, *, org: Any) -> ProvisionedTeam:
        """Create the org's Documenso Team via the admin tRPC layer."""
        try:
            name = getattr(org, "name", None) or getattr(org, "slug", None) or str(
                getattr(org, "id", "org")
            )
            slug = getattr(org, "slug", None) or _slugify(name)
            data = await self._call(
                "team.createTeam", {"name": name, "teamUrl": slug}
            )
            team_id = _first_str(data, "teamId", "id")
            if not team_id:
                raise ValueError("tRPC create_team returned no team id")
            return ProvisionedTeam(team_id=team_id)
        except ProvisioningError:
            raise
        except Exception as exc:
            raise ProvisioningError(
                "Auto-provisioning could not create the Documenso team. "
                "Please complete this organisation's connection manually."
            ) from exc

    async def mint_team_token(self, *, team_id: str) -> ProvisionedToken:
        """Mint a team-scoped API token via the admin tRPC layer."""
        try:
            data = await self._call(
                "apiToken.createTokenForTeam",
                {"teamId": team_id, "tokenName": "OraInvoice", "expirationDate": None},
            )
            token = _first_str(data, "token", "apiToken")
            if not token:
                raise ValueError("tRPC mint_team_token returned no token")
            return ProvisionedToken(token=token)
        except ProvisioningError:
            raise
        except Exception as exc:
            raise ProvisioningError(
                "Auto-provisioning could not mint the Documenso API token. "
                "Please complete this organisation's connection manually."
            ) from exc

    async def ensure_webhook(
        self, *, team_id: str, routing_url: str, secret: str
    ) -> None:
        """Create (or confirm) the Team's webhook subscription via tRPC."""
        try:
            await self._call(
                "webhook.createWebhook",
                {
                    "teamId": team_id,
                    "webhookUrl": routing_url,
                    "secret": secret,
                    "enabled": True,
                    "eventTriggers": [
                        "DOCUMENT_OPENED",
                        "DOCUMENT_SENT",
                        "DOCUMENT_SIGNED",
                        "DOCUMENT_COMPLETED",
                        "DOCUMENT_CANCELLED",
                    ],
                },
            )
        except ProvisioningError:
            raise
        except Exception as exc:
            raise ProvisioningError(
                "Auto-provisioning could not create the Documenso webhook. "
                "Please complete this organisation's connection manually."
            ) from exc


# ---------------------------------------------------------------------------
# DB adapter — writes DIRECTLY to Documenso's self-hosted PostgreSQL (UNSUPPORTED)
# ---------------------------------------------------------------------------


class DbProvisioningAdapter:
    """Provision by writing **directly to Documenso's PostgreSQL**.

    .. warning::

        **BEST-EFFORT, UNSUPPORTED, UPGRADE-FRAGILE.** This writes straight into
        Documenso's internal tables (``Team``, ``TeamMember``, ``ApiToken``,
        ``Webhook``). It depends on Documenso's internal DB schema and **will**
        break if a Documenso upgrade changes that schema. It is gated behind
        ``ESIGN_PROVISIONING_MODE`` so it can be disabled instantly; the manual
        path is the supported fallback at all times (R20.4).

    Documenso stores API tokens **hashed**, so this adapter (1) generates the
    token itself, (2) stores only its **hash**, and (3) returns the **plaintext
    once** so OraInvoice can persist it envelope-encrypted. The plaintext is
    never logged.

    Uses a **platform-config** Documenso DB URL (envelope-encrypted at rest,
    never a per-org credential). A ``connect`` factory may be injected for
    testing so no real Documenso database is required.
    """

    def __init__(
        self,
        *,
        db_url: str,
        connect: Any = None,
    ) -> None:
        self._db_url = db_url or ""
        # ``connect`` is an async callable returning a connection object exposing
        # asyncpg-style ``fetchval``/``fetchrow``/``execute``/``close``. Injectable
        # so tests can supply a fake — no real Documenso DB is required.
        self._connect = connect

    async def _acquire(self) -> Any:
        if self._connect is not None:
            return await self._connect()
        if not self._db_url:
            raise ValueError("no Documenso DB URL configured")
        import asyncpg  # lazy import — only needed for the real db adapter

        return await asyncpg.connect(self._db_url)

    @staticmethod
    def _hash_token(token: str) -> str:
        # Documenso stores API tokens as a SHA-256 hex digest of the plaintext.
        # (Mirroring Documenso internals — upgrade-fragile.)
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    # -- ProvisioningAdapter ------------------------------------------------

    async def create_team(self, *, org: Any) -> ProvisionedTeam:
        """Insert the Team + owner TeamMember directly into Documenso's DB."""
        conn = None
        try:
            name = getattr(org, "name", None) or getattr(org, "slug", None) or str(
                getattr(org, "id", "org")
            )
            slug = getattr(org, "slug", None) or _slugify(name)
            owner_user_id = getattr(org, "documenso_owner_user_id", None)
            conn = await self._acquire()
            team_id = await conn.fetchval(
                'INSERT INTO "Team" (name, url, "createdAt") '
                "VALUES ($1, $2, NOW()) RETURNING id",
                name,
                slug,
            )
            if team_id is None:
                raise ValueError("DB insert of Team returned no id")
            if owner_user_id is not None:
                await conn.execute(
                    'INSERT INTO "TeamMember" ("teamId", "userId", role, "createdAt") '
                    "VALUES ($1, $2, 'OWNER', NOW())",
                    team_id,
                    owner_user_id,
                )
            return ProvisionedTeam(team_id=str(team_id))
        except ProvisioningError:
            raise
        except Exception as exc:
            raise ProvisioningError(
                "Auto-provisioning could not create the Documenso team in the "
                "database. Please complete this organisation's connection "
                "manually."
            ) from exc
        finally:
            await _safe_close(conn)

    async def mint_team_token(self, *, team_id: str) -> ProvisionedToken:
        """Generate a token, store ONLY its hash, return the plaintext once."""
        conn = None
        try:
            # Generate the token ourselves so we can hand the plaintext back once.
            token = "api_" + secrets.token_hex(24)
            token_hash = self._hash_token(token)
            conn = await self._acquire()
            await conn.execute(
                'INSERT INTO "ApiToken" (name, token, "teamId", "createdAt") '
                "VALUES ($1, $2, $3, NOW())",
                "OraInvoice",
                token_hash,  # only the HASH is persisted — never the plaintext
                _maybe_int(team_id),
            )
            return ProvisionedToken(token=token)
        except ProvisioningError:
            raise
        except Exception as exc:
            raise ProvisioningError(
                "Auto-provisioning could not mint the Documenso API token in the "
                "database. Please complete this organisation's connection "
                "manually."
            ) from exc
        finally:
            await _safe_close(conn)

    async def ensure_webhook(
        self, *, team_id: str, routing_url: str, secret: str
    ) -> None:
        """Insert the Team's webhook-subscription row directly into Documenso's DB."""
        conn = None
        try:
            conn = await self._acquire()
            await conn.execute(
                'INSERT INTO "Webhook" '
                '("webhookUrl", secret, enabled, "eventTriggers", "teamId", "createdAt") '
                "VALUES ($1, $2, TRUE, $3, $4, NOW())",
                routing_url,
                secret,
                [
                    "DOCUMENT_OPENED",
                    "DOCUMENT_SENT",
                    "DOCUMENT_SIGNED",
                    "DOCUMENT_COMPLETED",
                    "DOCUMENT_CANCELLED",
                ],
                _maybe_int(team_id),
            )
        except ProvisioningError:
            raise
        except Exception as exc:
            raise ProvisioningError(
                "Auto-provisioning could not create the Documenso webhook in the "
                "database. Please complete this organisation's connection "
                "manually."
            ) from exc
        finally:
            await _safe_close(conn)


# ---------------------------------------------------------------------------
# Factory — selected by the PLATFORM-level ESIGN_PROVISIONING_MODE flag
# ---------------------------------------------------------------------------


def get_provisioning_adapter() -> ProvisioningAdapter | None:
    """Return the configured provisioning adapter, or ``None`` when disabled.

    Selected by the **platform-level** flag ``ESIGN_PROVISIONING_MODE``:

    * ``off`` (default) → returns ``None``; auto-provisioning is unavailable and
      only the manual per-org connection path is offered (R20.5).
    * ``trpc`` → :class:`TrpcProvisioningAdapter`.
    * ``db`` → :class:`DbProvisioningAdapter`.

    Platform credentials are loaded from envelope-encrypted platform config and
    are used **only** for provisioning — never for per-org Documenso API calls.

    Raises:
        ProvisioningError: When the flag holds an unrecognised value.
    """
    mode = (settings.esign_provisioning_mode or "off").strip().lower()
    if mode == "off":
        return None
    if mode == "trpc":
        return TrpcProvisioningAdapter(
            base_url=_load_platform_secret(settings.esign_documenso_admin_url),
            admin_token=_load_platform_secret(settings.esign_documenso_admin_token),
        )
    if mode == "db":
        return DbProvisioningAdapter(
            db_url=_load_platform_secret(settings.esign_documenso_db_url),
        )
    raise ProvisioningError(
        f"Unknown ESIGN_PROVISIONING_MODE {mode!r}; expected 'off', 'trpc', or 'db'."
    )


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in (value or "").lower())
    out = "-".join(part for part in out.split("-") if part)
    return out or "team"


def _first_str(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = data.get(key)
        if val:
            return str(val)
    return ""


def _maybe_int(value: str) -> Any:
    """Documenso team ids are integers; coerce when possible, else pass through."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


async def _safe_close(conn: Any) -> None:
    if conn is None:
        return
    try:
        await conn.close()
    except Exception:  # pragma: no cover - close failures are non-fatal
        logger.debug("Documenso provisioning DB connection close failed", exc_info=True)
