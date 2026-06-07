"""Business logic for the PPSR module.

Implements :class:`PpsrService` per ``.kiro/specs/ppsr-module/design.md``
§4.2. The service owns:

- module-gate + CarJam-config check (G28/G49)
- monthly quota check + atomic increment (G44 — separate hidden-plate
  counter)
- Redis in-flight lock to stop double-billing on rapid double-clicks
  (G27)
- options-hash cache lookup (G30) + forgotten-row skip (G26)
- vehicle-link resolution via :class:`OrgVehicle` / :class:`GlobalVehicle`
  (G13/G23/G39)
- envelope-encrypted persistence (G31)
- :func:`write_audit_log` rows for ``ppsr.search``, ``ppsr.search.cached``,
  ``ppsr.forgotten``, ``ppsr.search.linked`` — all on the ``audit_log``
  singular table (G33/G45).

The HTTP-shaped exceptions live in
:mod:`app.modules.ppsr.exceptions`; the router maps each to the agreed
status code per design.md §5.

Refs: tasks.md C3; requirements.md R4 / R5 / R6.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import secrets
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.core.modules import ModuleService
from app.integrations.carjam import (
    CarjamNotFoundError,
    CarjamOwnerCheckNotAllowedError,
    CarjamOwnerCheckResponse,
    CarjamOwnerCheckValidationError,
    CarjamPpsrResponse,
    CarjamRateLimitError,
)
from app.modules.admin.models import GlobalVehicle, IntegrationConfig, Organisation
from app.modules.ppsr.exceptions import (
    PpsrCarjamNotConfiguredError,
    PpsrOwnerCheckNotAllowedError,
    PpsrOwnerCheckValidationError,
    PpsrOwnerLookupsDisabledError,
    PpsrS241PurposeRequiredError,
    PpsrSearchForbiddenError,
    PpsrSearchForgottenError,
    PpsrSearchNotFoundError,
)
from app.modules.ppsr.models import PpsrSearch
from app.modules.ppsr.schemas import (
    PpsrQuotaResponse,
    PpsrSearchListResponse,
    PpsrSearchOptions,
    PpsrSearchResult,
    PpsrSearchSummary,
)
from app.modules.vehicles.models import OrgVehicle
from app.modules.vehicles.service import _load_carjam_client

logger = logging.getLogger(__name__)


__all__ = ["PpsrService", "redis_lock"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_serialisable(resp: CarjamPpsrResponse) -> dict[str, Any]:
    """Convert a :class:`CarjamPpsrResponse` to a JSON-serialisable dict.

    The dataclass holds ``list[dict]`` / ``dict`` / scalar fields only —
    direct ``asdict`` works. Any nested non-serialisable value is
    collapsed via ``default=str`` at JSON-encode time.
    """

    if is_dataclass(resp):
        return asdict(resp)
    # Fallback for test doubles that pass plain dicts.
    return dict(resp)  # type: ignore[arg-type]


def _hash_options_payload(payload: dict[str, Any]) -> str:
    """sha256 hex digest of canonical-JSON serialisation (G30).

    Used by both the request-side ``_hash_options`` and the cache
    lookup so JSON-key-order changes never break cache hits.
    """

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_request_id(raw_body: str | None) -> str | None:
    """Best-effort pull of CarJam's request id from the response body.

    CarJam embeds an id under various keys depending on call shape.
    Returns ``None`` if nothing recognisable is present — never
    raises.
    """

    if not raw_body:
        return None
    try:
        body = json.loads(raw_body)
    except (ValueError, TypeError):
        return None
    if not isinstance(body, dict):
        return None
    candidate = body.get("request_id") or body.get("requestId")
    if candidate:
        return str(candidate)
    msg = body.get("message")
    if isinstance(msg, dict):
        candidate = msg.get("request_id") or msg.get("requestId")
        if candidate:
            return str(candidate)
    return None


# ---------------------------------------------------------------------------
# Redis lock (G27)
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def redis_lock(
    redis: Redis,
    key: str,
    *,
    ttl: int = 30,
    wait_timeout: float = 5.0,
    poll_interval: float = 0.1,
):
    """In-flight ``SET NX EX`` lock (G27).

    Mirrors the simple Redis locking pattern used elsewhere in the
    codebase: try ``SET NX EX``; on contention, poll until either the
    key disappears or ``wait_timeout`` elapses. If we acquired the
    lock we release it on exit; if we timed out waiting, we yield
    anyway (best-effort) so the caller can fall through to the cache
    check — the design explicitly accepts this rather than blocking
    forever (design.md §1a).

    Yields ``True`` when the lock was acquired, ``False`` otherwise.
    """

    token = secrets.token_hex(16)
    deadline = asyncio.get_event_loop().time() + wait_timeout
    acquired = False
    try:
        while True:
            try:
                ok = await redis.set(key, token, nx=True, ex=ttl)
            except Exception as exc:  # pragma: no cover — best-effort
                logger.warning("Redis lock SET failed for %s: %s", key, exc)
                ok = False
            if ok:
                acquired = True
                break
            if asyncio.get_event_loop().time() >= deadline:
                logger.info(
                    "Redis lock %s wait-timeout (%.2fs) — proceeding without lock",
                    key,
                    wait_timeout,
                )
                break
            await asyncio.sleep(poll_interval)
        yield acquired
    finally:
        if acquired:
            # Best-effort token-checked release. Redis lua would be ideal
            # but the existing codebase doesn't ship a SCRIPT helper —
            # check-then-delete is fine here because the TTL guards the
            # rare race window.
            try:
                stored = await redis.get(key)
                if stored is not None:
                    if isinstance(stored, bytes):
                        stored = stored.decode("utf-8", errors="ignore")
                    if stored == token:
                        await redis.delete(key)
            except Exception as exc:  # pragma: no cover
                logger.warning("Redis lock release failed for %s: %s", key, exc)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PpsrService:
    """Service layer for PPSR search / history / quota endpoints.

    Uses a request-scoped ``AsyncSession`` (auto-committed by
    ``get_db_session``) and a shared :class:`Redis` connection. No
    ``db.commit()`` calls — only ``flush`` + ``refresh`` per the
    project-overview MissingGreenlet note.
    """

    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    # ------------------------------------------------------------------
    # Public API — search
    # ------------------------------------------------------------------

    async def search(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        current_user: Any,  # noqa: ARG002 — reserved for future role-aware logic
        rego: str,
        options: PpsrSearchOptions,
        force_refresh: bool = False,
    ) -> PpsrSearchResult:
        """Run (or cache-hit) a PPSR search per design §4.2.

        See module docstring + :class:`PpsrSearchResult` for the
        response contract. Raises a typed exception per design §5
        which the router maps to the appropriate HTTP status.
        """

        # 1. Module gate (defence-in-depth — middleware already gated).
        if not await ModuleService(self.db).is_enabled(str(org_id), "ppsr"):
            raise HTTPException(403, "module_not_enabled")

        # 2. CarJam configuration gate (G28/G49).
        cfg_fields = await self._load_carjam_config_fields()
        s241_default = cfg_fields.get("s241_purpose_default") or None
        try:
            cache_ttl_minutes = int(cfg_fields.get("ppsr_cache_ttl_minutes") or 5)
        except (TypeError, ValueError):
            cache_ttl_minutes = 5
        owner_enabled = bool(cfg_fields.get("ppsr_owner_lookups_enabled") or False)

        # 3. Quota check — load the counters for informational use. PPSR
        # mirrors CarJam billing: we do NOT hard-block when the plan's
        # included quota is 0 or exhausted. The lookup proceeds and the
        # monthly counter (incremented in step 10) drives usage-based overage
        # billing in ``process_due_billings`` (per ``ppsr_per_check_cost_nzd``).
        # The counter is still loaded so the response/quota endpoint stays
        # consistent, but exhaustion no longer raises.
        quota = await self._load_quota(org_id)

        # 4. Owner-lookup gating.
        wants_owner = bool(
            options.include_current_owner or options.include_ownership_history,
        )
        if wants_owner:
            if not owner_enabled:
                raise PpsrOwnerLookupsDisabledError()
            effective_s241 = options.s241_purpose or s241_default
            if not effective_s241:
                raise PpsrS241PurposeRequiredError()
        else:
            effective_s241 = None

        rego_norm = rego.strip().upper()
        options_hash = self._hash_options(options)

        # 5. Redis in-flight lock — best-effort (G27).
        lock_key = f"ppsr:lock:{org_id}:{rego_norm}:{options_hash}"
        async with redis_lock(self.redis, lock_key, ttl=30, wait_timeout=5):
            # 6. Cache lookup (skip when force_refresh requested).
            if not force_refresh:
                cached = await self._find_recent_match(
                    org_id=org_id,
                    rego=rego_norm,
                    options_hash=options_hash,
                    ttl_minutes=cache_ttl_minutes,
                )
                if cached is not None:
                    await write_audit_log(
                        session=self.db,
                        action="ppsr.search.cached",
                        entity_type="ppsr_search",
                        entity_id=cached.id,
                        org_id=org_id,
                        user_id=user_id,
                        after_value={
                            "source_search_id": str(cached.id),
                            "rego": rego_norm,
                        },
                    )
                    return self._build_cached_result(cached)

            # 7. Call CarJam — map known errors into PPSR-typed outcomes.
            # 7. Call CarJam — map known errors into PPSR-typed outcomes.
            #
            # The PPSR (money-owing / vehicle) lookup is OPTIONAL: it only
            # fires when the request actually wants PPSR data (money owing,
            # warnings, FWS, hidden-plate, or owner-reveal). An ownership-check
            # ONLY search skips ``lookup_ppsr`` entirely so it never consumes
            # the PPSR budget / hits the PPSR cap (the ``owner_check`` product
            # is billed and capped separately by CarJam).
            client = await _load_carjam_client(self.db, self.redis)

            wants_ppsr = bool(
                options.include_money_owing
                or options.include_warnings
                or options.include_fws
                or options.check_hidden_plates
                or options.include_ownership_history
                or options.include_current_owner
            )
            # If the caller asked for nothing PPSR-related and no owner check,
            # default to a money-owing PPSR lookup (back-compat with the
            # original "blank options = PPSR check" behaviour).
            if not wants_ppsr and not options.owner_check_type:
                wants_ppsr = True

            carjam_resp: CarjamPpsrResponse | None = None
            if wants_ppsr:
                try:
                    carjam_resp = await client.lookup_ppsr(
                        rego_norm,
                        include_owners=options.include_ownership_history,
                        include_owner=options.include_current_owner,
                        include_warnings=options.include_warnings,
                        include_fws=options.include_fws,
                        check_hidden_plates=options.check_hidden_plates,
                        s241_purpose=effective_s241,
                    )
                except CarjamNotFoundError:
                    # Persist the not-found row so the audit trail is intact and
                    # the quota is still consumed (the upstream call happened).
                    return await self._persist_not_found(
                        org_id=org_id,
                        user_id=user_id,
                        rego=rego_norm,
                        options=options,
                        options_hash=options_hash,
                    )
                except CarjamRateLimitError:
                    # Router maps this to HTTP 429 with Retry-After.
                    raise

            # 7b. Optional ownership check (CarJam ``owner_check`` product).
            #     Runs as its own upstream call when the request asked for it.
            #     Charges are folded into the persisted ``charges_cents`` so
            #     overage billing captures the full cost of the search.
            owner_check_resp: CarjamOwnerCheckResponse | None = None
            if options.owner_check_type:
                try:
                    owner_check_resp = await client.lookup_owner_check(
                        rego_norm,
                        check_type=options.owner_check_type,
                        last_name=options.owner_last_name,
                        first_name=options.owner_first_name,
                        dob=options.owner_dob,
                        driver_licence=options.owner_driver_licence,
                        company_name=options.owner_company_name,
                    )
                except ValueError as exc:
                    # Pre-flight per-type field validation failed.
                    raise PpsrOwnerCheckValidationError(str(exc)) from exc
                except CarjamOwnerCheckValidationError as exc:
                    raise PpsrOwnerCheckValidationError(str(exc)) from exc
                except CarjamOwnerCheckNotAllowedError as exc:
                    raise PpsrOwnerCheckNotAllowedError(str(exc)) from exc
                except CarjamRateLimitError:
                    raise

            # 8. Resolve vehicle link (read-only — G23).
            ov_id, gv_id = await self._resolve_vehicle_link(org_id, rego_norm)

            # 9. Persist (encrypted). When only an ownership check ran there is
            #    no PPSR payload, so the encrypted blob holds just the
            #    owner-check result and PPSR summary columns stay empty.
            if carjam_resp is not None:
                payload_obj = _to_serialisable(carjam_resp)
            else:
                payload_obj = {}
            if owner_check_resp is not None:
                payload_obj["owner_check"] = {
                    "type": owner_check_resp.check_type,
                    "match": owner_check_resp.match,
                    "ref": owner_check_resp.ref,
                }
            payload_json = json.dumps(payload_obj, default=str)
            encrypted = envelope_encrypt(payload_json)

            money_owing = (carjam_resp.money_owing if carjam_resp else None) or {}
            ppsr_summary = (carjam_resp.ppsr_summary if carjam_resp else None) or {}
            # CarJam nests the count at ppsr_summary.search_result.@attributes.fs_count
            # OR at ppsr_summary.count (test fixtures). Handle both.
            statement_count = self._safe_int(ppsr_summary.get("count"))
            if statement_count is None:
                sr = ppsr_summary.get("search_result")
                if isinstance(sr, dict):
                    attrs = sr.get("@attributes") or sr
                    statement_count = self._safe_int(attrs.get("fs_count"))
            statement_count = statement_count or len(
                (carjam_resp.ppsr_details if carjam_resp else None) or [],
            )

            # Fold the owner-check charge into the total charge for the search.
            total_charges = carjam_resp.charges_cents if carjam_resp else None
            if owner_check_resp is not None and owner_check_resp.charges_cents:
                total_charges = (total_charges or 0) + owner_check_resp.charges_cents

            search = PpsrSearch(
                org_id=org_id,
                user_id=user_id,
                rego=rego_norm,
                options_json=options.model_dump(),
                options_hash=options_hash,
                org_vehicle_id=ov_id,
                global_vehicle_id=gv_id,
                match=money_owing.get("match"),
                match_description=money_owing.get("match_description"),
                statement_count=statement_count,
                has_warnings=bool(carjam_resp.warnings) if carjam_resp else False,
                has_ownership_data=bool(
                    carjam_resp.ownership_history or carjam_resp.current_owner,
                ) if carjam_resp else False,
                response_encrypted=encrypted,
                charges_cents=total_charges,
                not_found=bool(carjam_resp.not_found) if carjam_resp else False,
                carjam_request_id=_extract_request_id(
                    carjam_resp.raw_xml if carjam_resp else None,
                ),
                owner_check_type=(
                    owner_check_resp.check_type if owner_check_resp else None
                ),
                owner_check_match=(
                    owner_check_resp.match if owner_check_resp else None
                ),
                owner_check_ref=(
                    owner_check_resp.ref if owner_check_resp else None
                ),
            )
            self.db.add(search)

            # 10. Increment quota counters atomically (G44). Only bump the PPSR
            #     counter when a PPSR lookup actually ran.
            update_values: dict[str, Any] = {}
            if carjam_resp is not None:
                update_values["ppsr_lookups_this_month"] = (
                    Organisation.ppsr_lookups_this_month + 1
                )
                if options.check_hidden_plates:
                    update_values["ppsr_hidden_plate_lookups_this_month"] = (
                        Organisation.ppsr_hidden_plate_lookups_this_month + 1
                    )
            # Owner-check is a separately-billed CarJam product — count it on
            # its own monthly counter when the search ran one.
            if owner_check_resp is not None:
                update_values["owner_check_lookups_this_month"] = (
                    Organisation.owner_check_lookups_this_month + 1
                )
            if update_values:
                await self.db.execute(
                    update(Organisation)
                    .where(Organisation.id == org_id)
                    .values(**update_values),
                )

            await self.db.flush()
            await self.db.refresh(search)

            # 11. Audit (summary fields only — never decrypted PII).
            await write_audit_log(
                session=self.db,
                action="ppsr.search",
                entity_type="ppsr_search",
                entity_id=search.id,
                org_id=org_id,
                user_id=user_id,
                after_value={
                    "rego": rego_norm,
                    "options": options.model_dump(),
                    "match": search.match,
                    "statement_count": search.statement_count,
                    "charges_cents": search.charges_cents,
                    "owner_check_match": search.owner_check_match,
                },
            )

            return self._build_fresh_result(search, carjam_resp)

    # ------------------------------------------------------------------
    # History + detail + admin
    # ------------------------------------------------------------------

    async def list_searches(
        self,
        *,
        org_id: UUID,
        current_user: Any,
        rego: str | None = None,
        match: str | None = None,
        user_id: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> PpsrSearchListResponse:
        """G5 history list — paginated, ``{ items, total }`` shape.

        Non-admins are force-filtered to their own searches regardless
        of the ``user_id`` query-string parameter.
        """

        # Bound the limits to the documented range (1..100).
        limit = max(1, min(100, int(limit)))
        offset = max(0, int(offset))

        is_admin = self._is_admin(current_user)
        if not is_admin:
            user_id = getattr(current_user, "id", None)

        base = select(PpsrSearch).where(PpsrSearch.org_id == org_id)
        count_base = select(func.count(PpsrSearch.id)).where(
            PpsrSearch.org_id == org_id,
        )

        if rego:
            rego_norm = rego.strip().upper()
            base = base.where(PpsrSearch.rego == rego_norm)
            count_base = count_base.where(PpsrSearch.rego == rego_norm)
        if match:
            base = base.where(PpsrSearch.match == match)
            count_base = count_base.where(PpsrSearch.match == match)
        if user_id:
            base = base.where(PpsrSearch.user_id == user_id)
            count_base = count_base.where(PpsrSearch.user_id == user_id)
        if date_from:
            base = base.where(PpsrSearch.created_at >= date_from)
            count_base = count_base.where(PpsrSearch.created_at >= date_from)
        if date_to:
            base = base.where(PpsrSearch.created_at <= date_to)
            count_base = count_base.where(PpsrSearch.created_at <= date_to)

        rows_q = base.order_by(PpsrSearch.created_at.desc()).offset(offset).limit(limit)
        rows = (await self.db.execute(rows_q)).scalars().all()
        total = (await self.db.execute(count_base)).scalar_one() or 0

        # Resolve user emails for the "By" column display.
        from app.modules.auth.models import User
        user_ids = list({r.user_id for r in rows if r.user_id})
        user_map: dict[UUID, str] = {}
        if user_ids:
            user_q = await self.db.execute(
                select(User.id, User.first_name, User.last_name, User.email)
                .where(User.id.in_(user_ids))
            )
            for uid, first, last, email in user_q.all():
                name = f"{first or ''} {last or ''}".strip()
                user_map[uid] = name or email or str(uid)

        items = []
        for r in rows:
            summary = PpsrSearchSummary.model_validate(r)
            summary.user_display_name = user_map.get(r.user_id)
            items.append(summary)
        return PpsrSearchListResponse(items=items, total=int(total))

    async def get_search(
        self,
        search_id: UUID,
        current_user: Any,
    ) -> PpsrSearchResult:
        """Decrypt + return the full PPSR detail (R6.2).

        Raises:
          - :class:`PpsrSearchNotFoundError` when the row doesn't exist.
          - :class:`PpsrSearchForbiddenError` when caller is neither admin
            nor the original searcher.
          - :class:`PpsrSearchForgottenError` when ``forgotten_at`` is
            populated (G29).
        """

        row = await self._get_search_or_raise(search_id)
        self._enforce_ownership(row, current_user)

        if row.forgotten_at is not None:
            raise PpsrSearchForgottenError(forgotten_at=row.forgotten_at)

        decrypted: dict[str, Any] = {}
        if row.response_encrypted:
            try:
                decrypted = json.loads(envelope_decrypt_str(row.response_encrypted))
            except Exception as exc:  # pragma: no cover — guards against blob corruption
                logger.warning(
                    "Failed to decrypt PPSR payload for search %s: %s",
                    row.id,
                    exc,
                )
                decrypted = {}

        return PpsrSearchResult(
            search_id=row.id,
            rego=row.rego,
            cached=True,
            cached_at=row.created_at,
            source_search_id=row.id,
            match=row.match,
            match_description=row.match_description,
            statement_count=row.statement_count,
            ppsr_details=list(decrypted.get("ppsr_details") or []),
            ownership_history=decrypted.get("ownership_history"),
            current_owner=decrypted.get("current_owner"),
            warnings=list(decrypted.get("warnings") or []),
            basic=decrypted.get("basic"),
            not_found=row.not_found,
            charges_cents=row.charges_cents,
            carjam_request_id=row.carjam_request_id,
            owner_check_type=row.owner_check_type,
            owner_check_match=row.owner_check_match,
            owner_check_ref=row.owner_check_ref,
        )

    async def forget_search(
        self,
        search_id: UUID,
        current_user: Any,
    ) -> None:
        """Admin-only payload wipe (R6.4 / G26 / G29).

        Sets ``response_encrypted=NULL``, ``forgotten_at=now()`` and
        marks the row's error message; the summary + audit row stay.
        """

        if not self._is_admin(current_user):
            raise PpsrSearchForbiddenError()

        row = await self._get_search_or_raise(search_id)

        await self.db.execute(
            update(PpsrSearch)
            .where(PpsrSearch.id == row.id)
            .values(
                response_encrypted=None,
                forgotten_at=func.now(),
                error_message="forgotten by admin",
            ),
        )
        await self.db.flush()

        await write_audit_log(
            session=self.db,
            action="ppsr.forgotten",
            entity_type="ppsr_search",
            entity_id=row.id,
            org_id=getattr(current_user, "org_id", None) or row.org_id,
            user_id=getattr(current_user, "id", None),
            after_value={"search_id": str(row.id)},
        )

    async def link_vehicle(
        self,
        search_id: UUID,
        org_vehicle_id: UUID,
        current_user: Any,
    ) -> None:
        """Bind a saved search to an :class:`OrgVehicle` row (G23)."""

        row = await self._get_search_or_raise(search_id)
        self._enforce_ownership(row, current_user)

        await self.db.execute(
            update(PpsrSearch)
            .where(PpsrSearch.id == row.id)
            .values(org_vehicle_id=org_vehicle_id),
        )
        await self.db.flush()

        await write_audit_log(
            session=self.db,
            action="ppsr.search.linked",
            entity_type="ppsr_search",
            entity_id=row.id,
            org_id=getattr(current_user, "org_id", None) or row.org_id,
            user_id=getattr(current_user, "id", None),
            after_value={
                "search_id": str(row.id),
                "org_vehicle_id": str(org_vehicle_id),
            },
        )

    async def render_pdf(
        self,
        search_id: UUID,
        current_user: Any,
    ) -> bytes:
        """PDF export — delegates to :mod:`app.modules.ppsr.pdf` (task C4).

        Loads + decrypts the saved CarJam payload, then hands the row +
        plaintext dict to the renderer along with the active session
        so the renderer can pull the org branding (logo, address) and
        searcher details for the header.
        """

        row = await self._get_search_or_raise(search_id)
        self._enforce_ownership(row, current_user)
        if row.forgotten_at is not None:
            raise PpsrSearchForgottenError(forgotten_at=row.forgotten_at)

        from app.modules.ppsr import pdf as ppsr_pdf

        decrypted: dict[str, Any] = {}
        if row.response_encrypted:
            try:
                decrypted = json.loads(envelope_decrypt_str(row.response_encrypted))
            except Exception:  # pragma: no cover
                decrypted = {}

        return await ppsr_pdf.render_pdf(row, decrypted, self.db)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _hash_options(self, options: PpsrSearchOptions) -> str:
        """sha256 hex digest of canonical-JSON ``options.model_dump()`` (G30)."""

        return _hash_options_payload(options.model_dump())

    async def _find_recent_match(
        self,
        *,
        org_id: UUID,
        rego: str,
        options_hash: str,
        ttl_minutes: int,
    ) -> PpsrSearch | None:
        """Most-recent cache-eligible row (G26 / G29 / G30)."""

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, ttl_minutes))
        stmt = (
            select(PpsrSearch)
            .where(
                PpsrSearch.org_id == org_id,
                PpsrSearch.rego == rego,
                PpsrSearch.options_hash == options_hash,
                PpsrSearch.created_at >= cutoff,
                PpsrSearch.response_encrypted.isnot(None),
                PpsrSearch.error_message.is_(None),
                PpsrSearch.not_found.is_(False),
                PpsrSearch.forgotten_at.is_(None),
            )
            .order_by(PpsrSearch.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _resolve_vehicle_link(
        self,
        org_id: UUID,
        rego: str,
    ) -> tuple[UUID | None, UUID | None]:
        """Read-only vehicle-link resolution (G23)."""

        ov = await self.db.execute(
            select(OrgVehicle.id)
            .where(OrgVehicle.org_id == org_id, OrgVehicle.rego == rego)
            .limit(1),
        )
        ov_id = ov.scalar_one_or_none()
        if ov_id:
            return ov_id, None

        gv = await self.db.execute(
            select(GlobalVehicle.id)
            .where(GlobalVehicle.rego == rego)
            .limit(1),
        )
        return None, gv.scalar_one_or_none()

    async def _load_quota(self, org_id: UUID) -> PpsrQuotaResponse:
        """Pull the current org's PPSR quota counters (G44)."""

        stmt = (
            select(
                Organisation.ppsr_lookups_this_month,
                Organisation.ppsr_hidden_plate_lookups_this_month,
                Organisation.next_billing_date,
                _SubscriptionPlan.ppsr_lookups_included,
                _SubscriptionPlan.ppsr_hidden_plate_lookups_included,
            )
            .join(
                _SubscriptionPlan,
                Organisation.plan_id == _SubscriptionPlan.id,
            )
            .where(Organisation.id == org_id)
        )
        row = (await self.db.execute(stmt)).first()
        if row is None:
            # No org / plan resolution — report zero quota. Lookups are no
            # longer hard-blocked on exhaustion (CarJam-parity overage
            # billing), so this just yields a 0/0 quota strip.
            return PpsrQuotaResponse(used=0, included=0)
        used, hidden_used, resets_at, included, hidden_included = row
        return PpsrQuotaResponse(
            used=int(used or 0),
            included=int(included or 0),
            hidden_plate_used=int(hidden_used or 0),
            hidden_plate_included=int(hidden_included or 0),
            resets_at=resets_at,
        )

    async def get_quota(self, org_id: UUID) -> PpsrQuotaResponse:
        """Public alias used by the router.

        Also surfaces the owner-lookup config flags so the frontend can
        gate the checkboxes without a separate admin-only fetch.
        """

        quota = await self._load_quota(org_id)

        # Surface the owner-lookup config flags for the frontend form gating.
        try:
            cfg = await self._load_carjam_config_fields()
            quota.owner_lookups_enabled = bool(cfg.get("ppsr_owner_lookups_enabled") or False)
            quota.s241_purpose_configured = bool((cfg.get("s241_purpose_default") or "").strip())
        except Exception:
            # If CarJam isn't configured at all, leave defaults (False/False).
            quota.owner_lookups_enabled = False
            quota.s241_purpose_configured = False

        return quota

    async def _load_carjam_config_fields(self) -> dict[str, Any]:
        """Decrypt ``integration_configs[name='carjam']`` fields (G28/G49).

        Uses the raw ``IntegrationConfig`` row + ``envelope_decrypt_str``
        rather than ``get_integration_config`` (which masks secrets).
        Raises :class:`PpsrCarjamNotConfiguredError` when the row is
        missing / can't decrypt / has no ``api_key``.
        """

        result = await self.db.execute(
            select(IntegrationConfig).where(IntegrationConfig.name == "carjam"),
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise PpsrCarjamNotConfiguredError()
        try:
            fields = json.loads(envelope_decrypt_str(row.config_encrypted))
        except Exception as exc:
            logger.warning("Failed to decrypt CarJam config: %s", exc)
            raise PpsrCarjamNotConfiguredError() from exc
        if not isinstance(fields, dict):
            raise PpsrCarjamNotConfiguredError()
        if not (fields.get("api_key") or "").strip():
            raise PpsrCarjamNotConfiguredError()
        return fields

    async def _persist_not_found(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        rego: str,
        options: PpsrSearchOptions,
        options_hash: str,
    ) -> PpsrSearchResult:
        """Store a ``not_found=True`` row + audit + quota increment.

        CarJam still consumed budget on a 404 so we still bump the
        counter — same as the kiosk-vehicle-not-found path.
        """

        search = PpsrSearch(
            org_id=org_id,
            user_id=user_id,
            rego=rego,
            options_json=options.model_dump(),
            options_hash=options_hash,
            match=None,
            match_description=None,
            statement_count=0,
            has_warnings=False,
            has_ownership_data=False,
            response_encrypted=None,
            charges_cents=None,
            not_found=True,
            error_message="not_found",
        )
        self.db.add(search)

        update_values: dict[str, Any] = {
            "ppsr_lookups_this_month": Organisation.ppsr_lookups_this_month + 1,
        }
        if options.check_hidden_plates:
            update_values["ppsr_hidden_plate_lookups_this_month"] = (
                Organisation.ppsr_hidden_plate_lookups_this_month + 1
            )
        await self.db.execute(
            update(Organisation)
            .where(Organisation.id == org_id)
            .values(**update_values),
        )

        await self.db.flush()
        await self.db.refresh(search)

        await write_audit_log(
            session=self.db,
            action="ppsr.search",
            entity_type="ppsr_search",
            entity_id=search.id,
            org_id=org_id,
            user_id=user_id,
            after_value={
                "rego": rego,
                "options": options.model_dump(),
                "match": None,
                "statement_count": 0,
                "charges_cents": None,
                "not_found": True,
            },
        )

        return PpsrSearchResult(
            search_id=search.id,
            rego=rego,
            cached=False,
            not_found=True,
        )

    async def _get_search_or_raise(self, search_id: UUID) -> PpsrSearch:
        result = await self.db.execute(
            select(PpsrSearch).where(PpsrSearch.id == search_id),
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise PpsrSearchNotFoundError()
        return row

    @staticmethod
    def _is_admin(current_user: Any) -> bool:
        return getattr(current_user, "role", None) == "org_admin"

    @classmethod
    def _enforce_ownership(cls, row: PpsrSearch, current_user: Any) -> None:
        """Admin OR original searcher; otherwise 403."""

        if cls._is_admin(current_user):
            return
        user_id = getattr(current_user, "id", None)
        if user_id is not None and row.user_id == user_id:
            return
        raise PpsrSearchForbiddenError()

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _build_cached_result(row: PpsrSearch) -> PpsrSearchResult:
        """Build a ``PpsrSearchResult`` from a cached ORM row.

        We don't decrypt the payload here — the response shape is
        intentionally light because the UI already has the data from
        the original search. Callers that need full detail go through
        :meth:`get_search` instead.
        """

        return PpsrSearchResult(
            search_id=row.id,
            rego=row.rego,
            cached=True,
            cached_at=row.created_at,
            source_search_id=row.id,
            match=row.match,
            match_description=row.match_description,
            statement_count=row.statement_count,
            not_found=row.not_found,
            charges_cents=row.charges_cents,
            carjam_request_id=row.carjam_request_id,
            owner_check_type=row.owner_check_type,
            owner_check_match=row.owner_check_match,
            owner_check_ref=row.owner_check_ref,
        )

    @staticmethod
    def _build_fresh_result(
        row: PpsrSearch,
        carjam_resp: CarjamPpsrResponse | None,
    ) -> PpsrSearchResult:
        return PpsrSearchResult(
            search_id=row.id,
            rego=row.rego,
            cached=False,
            cached_at=None,
            source_search_id=None,
            match=row.match,
            match_description=row.match_description,
            statement_count=row.statement_count,
            ppsr_details=list(carjam_resp.ppsr_details or []) if carjam_resp else [],
            ownership_history=carjam_resp.ownership_history if carjam_resp else None,
            current_owner=carjam_resp.current_owner if carjam_resp else None,
            warnings=list(carjam_resp.warnings or []) if carjam_resp else [],
            basic=carjam_resp.basic if carjam_resp else None,
            not_found=row.not_found,
            charges_cents=row.charges_cents,
            carjam_request_id=row.carjam_request_id,
            owner_check_type=row.owner_check_type,
            owner_check_match=row.owner_check_match,
            owner_check_ref=row.owner_check_ref,
        )


# ---------------------------------------------------------------------------
# Lazy import target for SubscriptionPlan
# ---------------------------------------------------------------------------
# Import at module bottom to avoid circular import on app startup — the
# admin module imports from a number of other modules and is happiest
# when imported once everything else has resolved.

from app.modules.admin.models import SubscriptionPlan as _SubscriptionPlan  # noqa: E402
