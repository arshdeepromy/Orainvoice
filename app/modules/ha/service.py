"""Core business logic for HA node management.

Provides configuration CRUD, role transitions (promote/demote),
cluster status aggregation, and maintenance mode toggling.

Requirements: 1.1, 1.2, 1.5, 4.1–4.7, 5.1–5.5, 10.1–10.5, 12.2–12.4
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.modules.ha.heartbeat import HeartbeatService
from app.modules.ha.middleware import set_node_role, set_split_brain_blocked
from app.modules.ha.models import HAConfig
from app.modules.ha.replication import ReplicationManager
from app.modules.ha.schemas import (
    HAConfigRequest,
    HAConfigResponse,
    HANodeStatusForDashboard,
)
from app.modules.ha.utils import is_valid_role_transition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level heartbeat singleton
# ---------------------------------------------------------------------------

_heartbeat_service: HeartbeatService | None = None


def get_heartbeat_service() -> HeartbeatService | None:
    """Return the current heartbeat service singleton (if running)."""
    return _heartbeat_service


def _get_heartbeat_secret() -> str:
    """Retrieve the HMAC shared secret from the environment.

    .. warning::
       Logs a warning at startup if the secret is empty — HMAC verification
       becomes trivially forgeable with an empty key.
    """
    secret = os.environ.get("HA_HEARTBEAT_SECRET", "")
    if not secret:
        logger.warning(
            "HA_HEARTBEAT_SECRET is empty — heartbeat HMAC verification is effectively disabled. "
            "Set it via the GUI (Node Configuration → Heartbeat Secret) or the HA_HEARTBEAT_SECRET env var."
        )
    return secret


def _get_heartbeat_secret_from_config(cfg: HAConfig | None) -> str:
    """Retrieve the HMAC shared secret, preferring DB-stored value over env var.

    Priority: encrypted DB column > HA_HEARTBEAT_SECRET env var > empty string.
    """
    if cfg is not None and cfg.heartbeat_secret:
        try:
            return envelope_decrypt_str(cfg.heartbeat_secret)
        except Exception:
            logger.error("Failed to decrypt heartbeat_secret from DB — falling back to env var")
    return os.environ.get("HA_HEARTBEAT_SECRET", "")


def _config_to_response(cfg: HAConfig) -> HAConfigResponse:
    """Convert an ORM ``HAConfig`` to an ``HAConfigResponse`` schema.

    UUID fields are cast to strings because the schema expects ``str``.
    """
    return HAConfigResponse(
        node_id=str(cfg.node_id),
        node_name=cfg.node_name,
        role=cfg.role,
        peer_endpoint=cfg.peer_endpoint or "",
        auto_promote_enabled=cfg.auto_promote_enabled,
        heartbeat_interval_seconds=cfg.heartbeat_interval_seconds,
        failover_timeout_seconds=cfg.failover_timeout_seconds,
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
        peer_db_host=cfg.peer_db_host,
        peer_db_port=cfg.peer_db_port,
        peer_db_name=cfg.peer_db_name,
        peer_db_user=cfg.peer_db_user,
        peer_db_configured=cfg.peer_db_password is not None and len(cfg.peer_db_password) > 0,
        peer_db_sslmode=cfg.peer_db_sslmode,
        heartbeat_secret_configured=cfg.heartbeat_secret is not None and len(cfg.heartbeat_secret) > 0,
    )


async def _load_config(db: AsyncSession) -> HAConfig | None:
    """Load the single HAConfig row from the database (or ``None``)."""
    result = await db.execute(select(HAConfig).limit(1))
    return result.scalars().first()


def _build_peer_db_url(cfg: HAConfig) -> str | None:
    """Build a PostgreSQL connection string from stored peer DB fields.

    Returns ``None`` if the required fields are not all populated.
    """
    from urllib.parse import quote_plus

    if not all([cfg.peer_db_host, cfg.peer_db_name, cfg.peer_db_user, cfg.peer_db_password]):
        return None
    try:
        password = envelope_decrypt_str(cfg.peer_db_password)
    except Exception:
        logger.error("Failed to decrypt peer DB password")
        return None
    # Defensive: strip port from host if accidentally included
    host = cfg.peer_db_host.strip()
    if ":" in host:
        host = host.split(":")[0]
    port = cfg.peer_db_port or 5432
    sslmode = cfg.peer_db_sslmode or "disable"
    base = f"postgresql://{quote_plus(cfg.peer_db_user)}:{quote_plus(password)}@{host}:{port}/{cfg.peer_db_name}"
    if sslmode and sslmode != "disable":
        base += f"?sslmode={sslmode}"
    return base


async def get_peer_db_url(db: AsyncSession) -> str | None:
    """Return the peer DB URL from stored config, falling back to env var.

    Priority: DB-stored fields > HA_PEER_DB_URL env var.
    """
    cfg = await _load_config(db)
    if cfg is not None:
        url = _build_peer_db_url(cfg)
        if url:
            return url
    return os.environ.get("HA_PEER_DB_URL") or None


class HAService:
    """Static service methods for HA node management."""

    # ------------------------------------------------------------------
    # Configuration CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def get_config(db: AsyncSession) -> HAConfigResponse | None:
        """Load HA configuration from the database.

        Returns ``None`` when no configuration exists (standalone mode).
        """
        cfg = await _load_config(db)
        if cfg is None:
            return None
        return _config_to_response(cfg)

    @staticmethod
    async def save_config(
        db: AsyncSession,
        config: HAConfigRequest,
        user_id: UUID,
    ) -> HAConfigResponse:
        """Upsert HA configuration, log an audit event, and hot-reload the heartbeat service.

        If a config row already exists it is updated; otherwise a new row
        is inserted.  After persisting, the middleware role cache is
        refreshed and the heartbeat service is (re)started if the peer
        endpoint changed.
        """
        global _heartbeat_service

        cfg = await _load_config(db)
        old_peer = cfg.peer_endpoint if cfg else None

        if cfg is None:
            # Insert new config
            cfg = HAConfig(
                node_name=config.node_name,
                role=config.role,
                peer_endpoint=config.peer_endpoint,
                auto_promote_enabled=config.auto_promote_enabled,
                heartbeat_interval_seconds=config.heartbeat_interval_seconds,
                failover_timeout_seconds=config.failover_timeout_seconds,
            )
            # Peer DB fields
            if config.peer_db_host:
                cfg.peer_db_host = config.peer_db_host
                cfg.peer_db_port = config.peer_db_port or 5432
                cfg.peer_db_name = config.peer_db_name
                cfg.peer_db_user = config.peer_db_user
                cfg.peer_db_sslmode = config.peer_db_sslmode or "disable"
                if config.peer_db_password:
                    cfg.peer_db_password = envelope_encrypt(config.peer_db_password)
            # Heartbeat secret — only store if provided
            if config.heartbeat_secret:
                cfg.heartbeat_secret = envelope_encrypt(config.heartbeat_secret)
            db.add(cfg)
        else:
            # Update existing config
            cfg.node_name = config.node_name
            cfg.role = config.role
            cfg.peer_endpoint = config.peer_endpoint
            cfg.auto_promote_enabled = config.auto_promote_enabled
            cfg.heartbeat_interval_seconds = config.heartbeat_interval_seconds
            cfg.failover_timeout_seconds = config.failover_timeout_seconds
            cfg.updated_at = datetime.now(timezone.utc)
            # Peer DB fields — only update if provided
            if config.peer_db_host is not None:
                cfg.peer_db_host = config.peer_db_host
                cfg.peer_db_port = config.peer_db_port or 5432
                cfg.peer_db_name = config.peer_db_name
                cfg.peer_db_user = config.peer_db_user
                cfg.peer_db_sslmode = config.peer_db_sslmode or "disable"
                if config.peer_db_password:
                    cfg.peer_db_password = envelope_encrypt(config.peer_db_password)
            # Heartbeat secret — only update if provided
            if config.heartbeat_secret:
                cfg.heartbeat_secret = envelope_encrypt(config.heartbeat_secret)

        await db.flush()
        await db.refresh(cfg)

        # Update middleware role cache
        set_node_role(cfg.role, cfg.peer_endpoint)

        # Audit log
        await write_audit_log(
            session=db,
            action="ha.config_saved",
            entity_type="ha_config",
            user_id=user_id,
            entity_id=cfg.id,
            after_value={
                "node_name": cfg.node_name,
                "role": cfg.role,
                "peer_endpoint": cfg.peer_endpoint,
                "auto_promote_enabled": cfg.auto_promote_enabled,
            },
        )

        await db.commit()

        # Hot-reload heartbeat service when config changes
        secret = _get_heartbeat_secret_from_config(cfg)
        if cfg.peer_endpoint:
            needs_restart = (
                _heartbeat_service is None
                or old_peer != cfg.peer_endpoint
                or (config.heartbeat_secret and _heartbeat_service is not None)
                or (_heartbeat_service is not None and _heartbeat_service.secret != secret)
            )
            if needs_restart:
                if _heartbeat_service is not None:
                    await _heartbeat_service.stop()
                _heartbeat_service = HeartbeatService(
                    peer_endpoint=cfg.peer_endpoint,
                    interval=cfg.heartbeat_interval_seconds,
                    secret=secret,
                    local_role=cfg.role,
                )
                await _heartbeat_service.start()
                logger.info("Heartbeat service (re)started for peer %s", cfg.peer_endpoint)

        # Also invalidate the heartbeat response cache so the responding
        # side picks up the new secret immediately
        try:
            from app.modules.ha import router as _ha_router
            _ha_router._hb_cache["ts"] = 0
        except Exception:
            pass  # Non-critical — cache will expire naturally in 10s

        return _config_to_response(cfg)

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @staticmethod
    async def get_identity(db: AsyncSession) -> HAConfigResponse:
        """Return the full node identity and configuration.

        Raises ``ValueError`` if HA is not configured.
        """
        cfg = await _load_config(db)
        if cfg is None:
            raise ValueError("HA is not configured. Use PUT /api/v1/ha/configure first.")
        return _config_to_response(cfg)

    # ------------------------------------------------------------------
    # Promote / Demote
    # ------------------------------------------------------------------

    @staticmethod
    async def promote(
        db: AsyncSession,
        user_id: UUID,
        reason: str,
        force: bool = False,
    ) -> dict:
        """Promote the current standby node to primary.

        Steps:
        1. Validate current role is standby.
        2. Check replication lag (< 5 s or ``force=True``).
        3. Stop the replication subscription.
        4. Update role to primary.
        5. Update middleware cache.
        6. Log audit event.
        """
        cfg = await _load_config(db)
        if cfg is None:
            raise ValueError("HA is not configured.")

        if not is_valid_role_transition(cfg.role, "primary"):
            raise ValueError(f"Cannot promote: node is currently '{cfg.role}', must be 'standby'.")

        # Check replication lag (Req 4.5)
        lag = await ReplicationManager.get_replication_lag(db)
        if lag is not None and lag > 5.0 and not force:
            raise ValueError(
                f"Replication lag is {lag:.1f}s (> 5s). "
                "Set force=true to proceed with potential data loss."
            )

        # Stop subscription
        try:
            await ReplicationManager.stop_subscription(db)
        except Exception as exc:
            logger.warning("Could not stop subscription during promote: %s", exc)

        # Update role
        cfg.role = "primary"
        cfg.promoted_at = datetime.now(timezone.utc)
        cfg.updated_at = datetime.now(timezone.utc)
        await db.flush()

        # Update middleware
        set_node_role("primary", cfg.peer_endpoint)

        # Audit
        await write_audit_log(
            session=db,
            action="ha.promoted",
            entity_type="ha_config",
            user_id=user_id,
            entity_id=cfg.id,
            after_value={
                "role": "primary",
                "reason": reason,
                "force": force,
                "replication_lag": lag,
            },
        )

        await db.commit()

        logger.info("Node promoted to PRIMARY (reason: %s, force: %s)", reason, force)
        return {
            "status": "ok",
            "role": "primary",
            "reason": reason,
            "replication_lag_at_promotion": lag,
        }

    @staticmethod
    async def demote(
        db: AsyncSession,
        user_id: UUID,
        reason: str,
    ) -> dict:
        """Demote the current primary node to standby.

        Steps:
        1. Validate current role is primary.
        2. Update role to standby.
        3. Create/resume the replication subscription.
        4. Update middleware cache.
        5. Log audit event.
        """
        cfg = await _load_config(db)
        if cfg is None:
            raise ValueError("HA is not configured.")

        if not is_valid_role_transition(cfg.role, "standby"):
            raise ValueError(f"Cannot demote: node is currently '{cfg.role}', must be 'primary'.")

        # Update role
        cfg.role = "standby"
        cfg.promoted_at = None
        cfg.updated_at = datetime.now(timezone.utc)
        await db.flush()

        # Resume subscription from the new primary
        peer_db_url = await get_peer_db_url(db)
        if peer_db_url:
            try:
                await ReplicationManager.resume_subscription(db, peer_db_url)
            except Exception as exc:
                logger.warning("Could not resume subscription during demote: %s", exc)

        # Update middleware
        set_node_role("standby", cfg.peer_endpoint)

        # Audit
        await write_audit_log(
            session=db,
            action="ha.demoted",
            entity_type="ha_config",
            user_id=user_id,
            entity_id=cfg.id,
            after_value={
                "role": "standby",
                "reason": reason,
            },
        )

        await db.commit()

        logger.info("Node demoted to STANDBY (reason: %s)", reason)
        return {
            "status": "ok",
            "role": "standby",
            "reason": reason,
        }

    # ------------------------------------------------------------------
    # Demote and Sync (role reversal guided flow)
    # ------------------------------------------------------------------

    @staticmethod
    async def demote_and_sync(
        db: AsyncSession,
        user_id: UUID,
        reason: str,
    ) -> dict:
        """Demote this primary to standby, truncate data, and subscribe to the new primary.

        Used during the guided role-reversal recovery flow after a split-brain
        condition is detected and this node is the stale primary.

        Steps:
        1. Load config, verify role is "primary".
        2. Update role to "standby", clear ``promoted_at``.
        3. Flush to DB.
        4. Truncate all tables except ha_config.
        5. Create subscription to peer (using stored peer DB URL).
        6. Update middleware cache.
        7. Clear split-brain flags.
        8. Write audit log with action "ha.role_reversal_completed".

        Requirements: 7.3, 7.4, 7.5, 7.6
        """
        cfg = await _load_config(db)
        if cfg is None:
            raise ValueError("HA is not configured.")

        if cfg.role != "primary":
            raise ValueError(
                f"Cannot demote-and-sync: node is currently '{cfg.role}', must be 'primary'."
            )

        # Update role to standby and clear promoted_at
        cfg.role = "standby"
        cfg.promoted_at = None
        cfg.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(cfg)

        # Truncate all tables except ha_config
        try:
            await ReplicationManager.truncate_all_tables()
        except Exception as exc:
            logger.error("Truncation failed during demote-and-sync: %s", exc)
            raise ValueError(f"Truncation failed: {exc}") from exc

        # Create subscription to peer
        peer_db_url = await get_peer_db_url(db)
        if peer_db_url:
            try:
                await ReplicationManager.init_standby(None, peer_db_url, truncate_first=False)
            except Exception as exc:
                logger.warning("Could not create subscription during demote-and-sync: %s", exc)
        else:
            logger.warning(
                "No peer DB URL configured — subscription not created. "
                "Configure peer DB settings and run Initialize Replication manually."
            )

        # Update middleware cache
        set_node_role("standby", cfg.peer_endpoint)

        # Clear split-brain flags
        set_split_brain_blocked(False)

        # Audit log
        await write_audit_log(
            session=db,
            action="ha.role_reversal_completed",
            entity_type="ha_config",
            user_id=user_id,
            entity_id=cfg.id,
            after_value={
                "role": "standby",
                "reason": reason,
                "peer_endpoint": cfg.peer_endpoint,
            },
        )

        logger.info("Demote-and-sync completed: node is now STANDBY (reason: %s)", reason)
        return {
            "status": "ok",
            "role": "standby",
            "reason": reason,
            "message": "Node demoted to standby and re-syncing from new primary.",
        }

    # ------------------------------------------------------------------
    # Cluster status
    # ------------------------------------------------------------------

    @staticmethod
    async def get_cluster_status(db: AsyncSession) -> list[HANodeStatusForDashboard]:
        """Return a list of two ``HANodeStatusForDashboard`` entries: local + peer.

        If the heartbeat service is not running, the peer entry shows
        ``health="unreachable"`` with ``is_local=False``.
        """
        cfg = await _load_config(db)
        if cfg is None:
            return []

        # Local node entry
        local_entry = HANodeStatusForDashboard(
            node_name=cfg.node_name,
            role=cfg.role,
            health="healthy",
            sync_status=cfg.sync_status,
            replication_lag_seconds=None,
            last_heartbeat=None,
            maintenance=cfg.maintenance_mode,
            is_local=True,
        )

        # Peer node entry — derived from heartbeat service
        global _heartbeat_service
        peer_health = "unreachable"
        peer_lag: float | None = None
        peer_last_hb: str | None = None
        peer_sync = "unknown"
        peer_maintenance = False

        if _heartbeat_service is not None:
            peer_health = _heartbeat_service.get_peer_health()
            history = _heartbeat_service.get_history()
            if history:
                latest = history[-1]
                peer_last_hb = latest.timestamp
                peer_lag = latest.replication_lag_seconds

        # Infer peer role (opposite of local)
        peer_role = "standby" if cfg.role == "primary" else "primary"

        peer_entry = HANodeStatusForDashboard(
            node_name=f"Peer ({cfg.peer_endpoint or 'unknown'})",
            role=peer_role,
            health=peer_health,
            sync_status=peer_sync,
            replication_lag_seconds=peer_lag,
            last_heartbeat=peer_last_hb,
            maintenance=peer_maintenance,
            is_local=False,
        )

        return [local_entry, peer_entry]

    # ------------------------------------------------------------------
    # Maintenance mode
    # ------------------------------------------------------------------

    @staticmethod
    async def enter_maintenance_mode(db: AsyncSession, user_id: UUID) -> dict:
        """Put the current node into maintenance mode.

        The node continues serving existing requests but the heartbeat
        response will include ``maintenance: true`` so the peer knows.
        """
        cfg = await _load_config(db)
        if cfg is None:
            raise ValueError("HA is not configured.")

        cfg.maintenance_mode = True
        cfg.updated_at = datetime.now(timezone.utc)
        await db.flush()

        await write_audit_log(
            session=db,
            action="ha.maintenance_entered",
            entity_type="ha_config",
            user_id=user_id,
            entity_id=cfg.id,
            after_value={"maintenance_mode": True},
        )

        await db.commit()

        logger.info("Node entered maintenance mode")
        return {"status": "ok", "maintenance_mode": True}

    @staticmethod
    async def exit_maintenance_mode(db: AsyncSession, user_id: UUID) -> dict:
        """Take the current node out of maintenance mode.

        Signals that the node has been updated and is ready to resume
        normal operation.
        """
        cfg = await _load_config(db)
        if cfg is None:
            raise ValueError("HA is not configured.")

        cfg.maintenance_mode = False
        cfg.updated_at = datetime.now(timezone.utc)
        await db.flush()

        await write_audit_log(
            session=db,
            action="ha.maintenance_exited",
            entity_type="ha_config",
            user_id=user_id,
            entity_id=cfg.id,
            after_value={"maintenance_mode": False},
        )

        await db.commit()

        logger.info("Node exited maintenance mode")
        return {"status": "ok", "maintenance_mode": False}
