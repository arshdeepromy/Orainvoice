"""NZ Privacy Act data-residency notice derivation + acknowledgement (Req 20).

This module derives, for any configured :class:`BackupDestination`, whether its
encrypted backups are stored **offshore**, **onshore** (in New Zealand), or at a
location that **cannot be reliably determined** (``unknown``). From that derived
residency it builds the data-residency *disclosure notice* shown on the
Cloud_Provider configuration screen, and it gates the **first** upload to a
destination on a persisted Global_Admin acknowledgement.

Derivation (Req 20.8 / 20.9)
----------------------------
``derive_residency(provider_type, config)`` is a pure function over the
provider type and the (already-decrypted, non-secret) destination config:

* ``google_drive`` / ``onedrive`` — offshore OAuth cloud drives (US-based
  providers) → **offshore**.
* ``s3`` — onshore when the resolved region is a New Zealand region (or the
  config explicitly declares an onshore/self-hosted NZ endpoint), offshore when
  a non-NZ region is declared, and **unknown** when the physical region cannot
  be determined (e.g. a self-hosted S3-compatible endpoint whose region is not
  declared — Req 20.9).
* ``nas`` — onshore only when the operator has declared the share is physically
  located in New Zealand; otherwise the physical location cannot be determined
  → **unknown**.

An explicit operator declaration in the config (``residency`` /
``data_residency`` set to one of :data:`RESIDENCY_VALUES`, an ``onshore``
boolean, or a ``country`` / ``location`` value) always takes precedence so a
self-hosted onshore endpoint or an NZ-sited NAS can be marked onshore.

Notice + acknowledgement (Req 20.2-20.9)
----------------------------------------
A destination whose residency is ``offshore`` **or** ``unknown`` shows the
offshore-disclosure warning and requires acknowledgement before its first
upload (``unknown`` is treated as offshore for the notice — Req 20.9); an
``onshore`` destination shows the onshore notice and requires no acknowledgement
(Req 20.7 / 20.8). Every notice also states that kiosk clock-in photos
(``clock_photos``) are likely biometric information, are included in the backup
set, and are encrypted client-side (Req 20.6).

``ResidencyService`` persists the acknowledgement in ``backup_residency_ack``
with the acting Global_Admin id and a UTC timestamp (Req 20.3), writes a durable
Audit_Log entry for it (Req 20.5), and exposes
:meth:`require_acknowledgement_before_upload`, which raises
:class:`ResidencyAcknowledgementRequiredError` when an offshore/undeterminable
destination has no persisted acknowledgement (Req 20.2 / 20.4). Per the
``get_db_session`` ``session.begin()`` auto-commit pattern the service uses
``flush()`` / ``refresh()`` (never ``commit()``).

Requirements: 20.2, 20.3, 20.5, 20.8, 20.9
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import envelope_decrypt_str
from app.modules.backup_restore.audit import AuditWriter
from app.modules.backup_restore.models import (
    RESIDENCY_VALUES,
    BackupDestination,
    BackupResidencyAck,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Residency values (mirror models.RESIDENCY_VALUES) (Req 20.8 / 20.9)
# ---------------------------------------------------------------------------
OFFSHORE = "offshore"
ONSHORE = "onshore"
UNKNOWN = "unknown"

#: Residency values that surface the offshore-disclosure warning and require a
#: first-upload acknowledgement. ``unknown`` is treated as offshore (Req 20.9).
_ACK_REQUIRED_RESIDENCIES = frozenset({OFFSHORE, UNKNOWN})

#: Provider types that are always offshore OAuth cloud drives (Req 20.1 / 20.8).
_OFFSHORE_OAUTH_PROVIDERS = frozenset({"google_drive", "onedrive"})

#: Audit action recorded when a residency notice is acknowledged (Req 20.5).
ACTION_RESIDENCY_ACKNOWLEDGED = "cloud_provider.residency_acknowledged"

#: Human label of the statute referenced throughout the notice text.
NZ_PRIVACY_ACT = "New Zealand Privacy Act 2020"

# ---------------------------------------------------------------------------
# New-Zealand location recognition
# ---------------------------------------------------------------------------
#: Region/country codes that resolve a destination to New Zealand. Matched after
#: normalising (lower-cased, spaces/underscores -> hyphens). ``ap-southeast-6``
#: is the AWS Auckland (New Zealand) region.
_NZ_EXACT_TOKENS = frozenset(
    {"nz", "nzl", "ap-southeast-6"},
)
#: Distinctive multi-character substrings that mark a free-text region/country
#: value as New Zealand. (A bare "nz" is intentionally NOT a substring token —
#: it would false-match words like "tanzania".)
_NZ_SUBSTRING_TOKENS = (
    "new zealand",
    "new-zealand",
    "newzealand",
    "auckland",
    "aotearoa",
)

# A decryptor turns a destination's ``config_encrypted`` blob into a config dict.
ConfigDecryptor = Callable[[bytes | None], Mapping[str, Any]]


def _is_nz_location(value: Any) -> bool:
    """Return ``True`` when ``value`` names a New Zealand region/country.

    Recognises NZ region/country codes (``nz``, ``nzl``, the AWS Auckland region
    ``ap-southeast-6``, or any ``nz-*`` region code) and distinctive place
    substrings (``new zealand``, ``auckland``, ``aotearoa``). Matching is
    case-insensitive and tolerant of spaces vs underscores vs hyphens.
    """
    if value is None:
        return False
    raw = str(value).strip().lower()
    if not raw:
        return False
    normalised = raw.replace("_", "-").replace(" ", "-")
    if normalised in _NZ_EXACT_TOKENS:
        return True
    if normalised.startswith("nz-"):
        return True
    return any(token in raw for token in _NZ_SUBSTRING_TOKENS)


def _explicit_residency(config: Mapping[str, Any]) -> str | None:
    """Resolve an operator-declared residency from the config, or ``None``.

    Honours, in order: a direct ``residency`` / ``data_residency`` value (one of
    :data:`RESIDENCY_VALUES`), an ``onshore`` boolean, and a ``country`` /
    ``location`` value (a New Zealand value → onshore, any other declared value
    → offshore). Returns ``None`` when no explicit declaration is present so the
    provider-specific derivation can run.
    """
    for key in ("residency", "data_residency"):
        value = config.get(key)
        if isinstance(value, str) and value.strip().lower() in RESIDENCY_VALUES:
            return value.strip().lower()

    onshore_flag = config.get("onshore")
    if isinstance(onshore_flag, bool):
        return ONSHORE if onshore_flag else OFFSHORE

    for key in ("country", "location"):
        value = config.get(key)
        if value not in (None, ""):
            return ONSHORE if _is_nz_location(value) else OFFSHORE

    return None


def derive_residency(
    provider_type: str | None,
    config: Mapping[str, Any] | None = None,
) -> str:
    """Derive ``offshore`` / ``onshore`` / ``unknown`` for a destination (Req 20.8/20.9).

    Pure function over the provider type and the already-decrypted, non-secret
    destination config. An explicit operator declaration in the config always
    wins; otherwise residency is derived per provider:

    * ``google_drive`` / ``onedrive`` → ``offshore``;
    * ``s3`` → ``onshore`` for an NZ region, ``offshore`` for a declared non-NZ
      region, ``unknown`` when the region cannot be determined (Req 20.9);
    * ``nas`` → ``unknown`` unless declared onshore;
    * anything else → ``unknown``.
    """
    cfg: Mapping[str, Any] = config or {}

    explicit = _explicit_residency(cfg)
    if explicit is not None:
        return explicit

    provider = (provider_type or "").strip().lower()

    if provider in _OFFSHORE_OAUTH_PROVIDERS:
        return OFFSHORE

    if provider == "s3":
        region = cfg.get("region")
        if region not in (None, ""):
            # A declared region is determinable: NZ → onshore, else offshore.
            return ONSHORE if _is_nz_location(region) else OFFSHORE
        # No region declared (e.g. a self-hosted S3-compatible endpoint whose
        # physical region is not declared) — cannot be determined (Req 20.9).
        return UNKNOWN

    if provider == "nas":
        # A NAS's physical location is only known if the operator declared it
        # (handled by _explicit_residency above); otherwise undeterminable.
        return UNKNOWN

    return UNKNOWN


# ---------------------------------------------------------------------------
# Disclosure notice
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ResidencyNotice:
    """The derived data-residency disclosure notice for a destination (Req 20).

    ``offshore_warning`` and ``requires_acknowledgement`` are both true exactly
    when the residency is ``offshore`` or ``unknown`` (``unknown`` is treated as
    offshore — Req 20.9) and false for an ``onshore`` destination (Req 20.7/20.8).
    ``text`` is the full human-readable notice (headline + body + the biometric
    clock-in-photo statement required by Req 20.6).
    """

    residency: str
    destination_label: str
    offshore_warning: bool
    requires_acknowledgement: bool
    headline: str
    body: str
    biometric_notice: str
    text: str


def _destination_label(provider_type: str | None, config: Mapping[str, Any]) -> str:
    """Build a human label naming the selected destination (Req 20.1).

    Names the provider (and, for S3, the region/endpoint/bucket) without
    surfacing any credential. Used in the notice so the Global_Admin sees
    exactly where data will reside.
    """
    provider = (provider_type or "").strip().lower()
    if provider == "google_drive":
        return "Google Drive (Google, United States)"
    if provider == "onedrive":
        return "Microsoft OneDrive (Microsoft, United States)"
    if provider == "s3":
        region = config.get("region")
        endpoint = config.get("endpoint_url") or config.get("endpoint")
        bucket = config.get("bucket")
        parts: list[str] = ["an S3-compatible bucket"]
        if bucket:
            parts.append(f"'{bucket}'")
        if region:
            parts.append(f"in region '{region}'")
        elif endpoint:
            parts.append(f"at endpoint '{endpoint}'")
        return " ".join(parts)
    if provider == "nas":
        return "a network-attached storage (NAS) destination"
    return provider_type or "the selected destination"


def _biometric_notice(offshore: bool) -> str:
    """The clock-in-photo biometric statement required on every notice (Req 20.6)."""
    location = (
        "the selected destination (offshore, with a US-based provider)"
        if offshore
        else "the selected destination"
    )
    return (
        f"Kiosk clock-in photos (clock_photos) are likely biometric information "
        f"under the {NZ_PRIVACY_ACT}. They are included in the backup set, are "
        f"encrypted client-side, and will be stored at {location}."
    )


def build_disclosure_notice(
    provider_type: str | None,
    config: Mapping[str, Any] | None = None,
    *,
    residency: str | None = None,
) -> ResidencyNotice:
    """Build the data-residency disclosure notice for a destination (Req 20.1-20.9).

    ``residency`` may be supplied when already derived; otherwise it is derived
    from ``provider_type`` / ``config``. The notice content is derived from the
    destination's actual residency (Req 20.8): an offshore/undeterminable
    destination shows the offshore-disclosure warning and requires
    acknowledgement (Req 20.9), while an onshore destination states the warning
    does not apply (Req 20.7).
    """
    cfg: Mapping[str, Any] = config or {}
    resolved = residency or derive_residency(provider_type, cfg)
    label = _destination_label(provider_type, cfg)
    offshore_warning = resolved in _ACK_REQUIRED_RESIDENCIES
    biometric = _biometric_notice(offshore_warning)

    if resolved == ONSHORE:
        headline = "Onshore (New Zealand) data-residency notice"
        body = (
            f"Encrypted backups are retained onshore in New Zealand at {label}. "
            f"The {NZ_PRIVACY_ACT} offshore-disclosure warning does not apply to "
            f"this destination."
        )
    else:
        headline = "Offshore data-residency notice"
        prefix = ""
        if resolved == UNKNOWN:
            prefix = (
                "The data residency of this destination could not be reliably "
                "determined, so it is treated as offshore. "
            )
        body = (
            f"{prefix}Encrypted backups containing customer data will be stored "
            f"offshore at {label}. Under the {NZ_PRIVACY_ACT}, disclosing "
            f"personal information to an overseas destination carries "
            f"offshore-disclosure obligations that should be reviewed before "
            f"the first backup is uploaded to this destination."
        )

    text = f"{headline}\n\n{body}\n\n{biometric}"
    return ResidencyNotice(
        residency=resolved,
        destination_label=label,
        offshore_warning=offshore_warning,
        requires_acknowledgement=offshore_warning,
        headline=headline,
        body=body,
        biometric_notice=biometric,
        text=text,
    )


def requires_acknowledgement(residency: str) -> bool:
    """``True`` when a destination of this residency needs first-upload ack (Req 20.2/20.9)."""
    return residency in _ACK_REQUIRED_RESIDENCIES


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class DestinationNotFoundError(Exception):
    """Raised when a destination id does not correspond to a known destination."""

    def __init__(self, destination_id: uuid.UUID | str) -> None:
        self.destination_id = destination_id
        super().__init__(f"Backup destination not found: {destination_id}")


class ResidencyAcknowledgementRequiredError(Exception):
    """Raised when a first upload is attempted without a residency acknowledgement.

    The caller MUST reject the upload, retain the unsent backup data, and return
    an error indicating that data-residency acknowledgement is required
    (Req 20.2 / 20.4).
    """

    def __init__(self, destination_id: uuid.UUID | str, residency: str) -> None:
        self.destination_id = destination_id
        self.residency = residency
        super().__init__(
            "Data-residency acknowledgement is required before the first backup "
            f"can be uploaded to destination {destination_id} (residency: {residency})."
        )


def _default_decrypt_config(blob: bytes | None) -> Mapping[str, Any]:
    """Decrypt a destination's ``config_encrypted`` blob into a config mapping.

    Returns an empty mapping when there is no stored config. The decrypted JSON
    holds the (non-secret) region/endpoint plus provider credentials; only the
    non-secret residency-relevant keys are read by the derivation.
    """
    if not blob:
        return {}
    try:
        decoded = json.loads(envelope_decrypt_str(blob))
    except (ValueError, TypeError) as exc:  # malformed/legacy config
        logger.warning("Could not decode destination config for residency derivation: %s", exc)
        return {}
    return decoded if isinstance(decoded, Mapping) else {}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class ResidencyService:
    """Derive + persist data-residency acknowledgement for backup destinations (Req 20).

    The config decryptor and audit writer are injected so derivation, notice
    building, and the acknowledgement audit are testable without real
    encryption keys or audit I/O. Per the project session pattern the service
    uses ``flush()`` / ``refresh()`` (never ``commit()``).
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        decrypt_config: ConfigDecryptor | None = None,
        audit_writer: AuditWriter | None = None,
    ) -> None:
        self._db = db
        self._decrypt_config = decrypt_config or _default_decrypt_config
        self._audit = audit_writer or AuditWriter()

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    async def _get_destination(self, destination_id: uuid.UUID | str) -> BackupDestination:
        result = await self._db.execute(
            select(BackupDestination).where(BackupDestination.id == destination_id),
        )
        destination = result.scalars().first()
        if destination is None:
            raise DestinationNotFoundError(destination_id)
        return destination

    def _config_of(self, destination: BackupDestination) -> Mapping[str, Any]:
        return self._decrypt_config(destination.config_encrypted)

    # ------------------------------------------------------------------
    # Derivation + notice (Req 20.8, 20.9 / 20.1-20.7)
    # ------------------------------------------------------------------
    def derive_residency(self, destination: BackupDestination) -> str:
        """Derive a destination's residency from its provider type + config (Req 20.8/20.9)."""
        return derive_residency(destination.provider_type, self._config_of(destination))

    def disclosure_notice(self, destination: BackupDestination) -> ResidencyNotice:
        """Build the data-residency disclosure notice for a destination (Req 20.1-20.9)."""
        config = self._config_of(destination)
        residency = derive_residency(destination.provider_type, config)
        return build_disclosure_notice(
            destination.provider_type, config, residency=residency,
        )

    # ------------------------------------------------------------------
    # Acknowledgement (Req 20.2, 20.3, 20.4, 20.5)
    # ------------------------------------------------------------------
    async def is_acknowledged(self, destination_id: uuid.UUID | str) -> bool:
        """Return ``True`` when a residency acknowledgement is persisted for a destination."""
        result = await self._db.execute(
            select(BackupResidencyAck.id)
            .where(BackupResidencyAck.destination_id == destination_id)
            .limit(1),
        )
        return result.scalars().first() is not None

    async def record_acknowledgement(
        self,
        destination_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> BackupResidencyAck:
        """Persist a Global_Admin acknowledgement of a destination's residency (Req 20.3).

        Records the acting Global_Admin id and a UTC ``acknowledged_at`` (server
        default), then writes a durable Audit_Log entry containing the actor,
        the UTC acknowledgement timestamp, and the destination id (Req 20.5).
        Uses ``flush()`` / ``refresh()`` (never ``commit()``).
        """
        destination = await self._get_destination(destination_id)

        ack = BackupResidencyAck(
            destination_id=destination.id,
            acknowledged_by=_coerce_uuid(user_id),
        )
        self._db.add(ack)
        await self._db.flush()
        await self._db.refresh(ack)

        # Durable audit entry (independent of this request transaction) — Req 20.5.
        acknowledged_at = ack.acknowledged_at
        await self._audit.write_completion(
            action=ACTION_RESIDENCY_ACKNOWLEDGED,
            actor_id=user_id,
            target_id=destination.id,
            entity_type="cloud_provider",
            outcome="acknowledged",
            after_value={
                "destination_id": str(destination.id),
                "provider_type": destination.provider_type,
                "residency": destination.residency,
                "acknowledged_at": acknowledged_at.isoformat() if acknowledged_at else None,
            },
        )
        return ack

    async def require_acknowledgement_before_upload(
        self,
        destination_id: uuid.UUID | str,
    ) -> None:
        """Gate the first upload to a destination on a persisted acknowledgement.

        An onshore destination needs no acknowledgement (Req 20.7/20.8). For an
        offshore or undeterminable destination (Req 20.9), this raises
        :class:`ResidencyAcknowledgementRequiredError` when no acknowledgement is
        persisted, so the caller rejects the upload and retains the unsent data
        (Req 20.2 / 20.4). Once an acknowledgement exists, subsequent uploads
        proceed.
        """
        destination = await self._get_destination(destination_id)
        residency = self.derive_residency(destination)
        if not requires_acknowledgement(residency):
            return
        if await self.is_acknowledged(destination.id):
            return
        raise ResidencyAcknowledgementRequiredError(destination.id, residency)


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a uuid-or-str into a ``uuid.UUID`` (the ack columns are typed UUID)."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
