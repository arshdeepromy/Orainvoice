"""HA Replication router — heartbeat, status, and cluster management endpoints.

Public endpoints (heartbeat, status) require no authentication.
All management endpoints require the ``global_admin`` role.

**Validates: Requirements 1.2, 1.5, 2.1, 4.1, 4.3, 7.1, 8.4, 11.1**
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session, async_session_factory
from app.core.audit import write_audit_log
from app.modules.auth.rbac import require_role
from app.modules.ha.hmac_utils import compute_hmac
from app.modules.ha.replication import ReplicationManager
from app.modules.ha.schemas import (
    CreateReplicationUserRequest,
    DemoteAndSyncRequest,
    DemoteRequest,
    FailoverStatusResponse,
    HAConfigRequest,
    HAConfigResponse,
    HAEventListResponse,
    HAEventResponse,
    HeartbeatHistoryEntry,
    HeartbeatResponse,
    PeerDBTestRequest,
    PromoteRequest,
    PublicStatusResponse,
    ReplicationStatusResponse,
    WizardAuthenticateRequest,
    WizardAuthenticateResponse,
    WizardCheckReachabilityRequest,
    WizardCheckReachabilityResponse,
    WizardHandshakeRequest,
    WizardHandshakeResponse,
    WizardReceiveHandshakeRequest,
    WizardReceiveHandshakeResponse,
    WizardSetupRequest,
    WizardSetupResponse,
    WizardSetupStepResult,
)
from app.modules.ha.service import HAService, get_heartbeat_service, get_peer_db_url
from app.modules.ha.utils import validate_confirmation_text

logger = logging.getLogger(__name__)


class _SubscriptionVerificationFailed(Exception):
    """Internal sentinel — subscription reported success but doesn't exist."""
    pass

# ---------------------------------------------------------------------------
# App start time for uptime calculation
# ---------------------------------------------------------------------------
_start_time = time.monotonic()

# ---------------------------------------------------------------------------
# Heartbeat config cache — avoids hitting the DB on every 10-second ping.
# Stores the raw HAConfig ORM-like snapshot and the decrypted HMAC secret.
# TTL: 10 seconds (matches default heartbeat interval).
# ---------------------------------------------------------------------------
_hb_cache: dict = {"config": None, "secret": "", "ts": 0.0}
_HB_CACHE_TTL = 10.0  # seconds


# ---------------------------------------------------------------------------
# Host LAN IP detection helper
# ---------------------------------------------------------------------------

def _detect_host_lan_ip() -> str:
    """Detect the host machine's LAN IP for peer connection info.

    Priority:
    1. ``HA_LOCAL_LAN_IP`` env var — explicit override, always wins.
    2. ``host.docker.internal`` — on Docker Desktop (Windows/Mac) this
       resolves to the Docker gateway, which works for local dev where
       both stacks run on the same host.  For production on Linux where
       Docker Desktop is not used, this DNS name won't resolve.
    3. UDP socket trick — on Linux production (bare metal / non-Desktop
       Docker), this returns the real host LAN IP.
    4. Fallback to ``127.0.0.1``.
    """
    import socket

    # 1. Explicit env var
    explicit = os.environ.get("HA_LOCAL_LAN_IP", "").strip()
    if explicit:
        return explicit

    # 2. host.docker.internal (Docker Desktop)
    try:
        resolved = socket.gethostbyname("host.docker.internal")
        if resolved:
            return "host.docker.internal"
    except socket.gaierror:
        pass

    # 3. UDP socket trick (Linux production)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass

    return "127.0.0.1"


# ---------------------------------------------------------------------------
# Public router — no authentication required
# ---------------------------------------------------------------------------

public_router = APIRouter()


@public_router.get(
    "/heartbeat",
    response_model=HeartbeatResponse,
    summary="Peer health check (HMAC-signed)",
    responses={
        503: {"description": "Database or node unhealthy"},
    },
)
async def heartbeat(db: AsyncSession = Depends(get_db_session)):
    """Return the node's health status with an HMAC signature.

    The peer node calls this endpoint every heartbeat interval to verify
    this node is alive.  The response payload is signed with the shared
    heartbeat secret so the caller can verify authenticity.

    Uses an in-memory cache (TTL 10s) to avoid querying the database on
    every ping — the config rarely changes.
    """
    try:
        now_mono = time.monotonic()

        # --- BUG-HA-06: Check Redis dirty-flag for cross-worker cache invalidation ---
        try:
            from app.core.redis import redis_pool as _redis
            if await _redis.get("ha:hb_cache_dirty"):
                _hb_cache["ts"] = 0  # force cache miss
                await _redis.delete("ha:hb_cache_dirty")
        except Exception:
            pass  # Redis unavailable — fall back to TTL-based expiry

        # --- Cached config lookup (avoids DB hit on every ping) ---
        cfg_row = None
        secret = ""
        if now_mono - _hb_cache["ts"] < _HB_CACHE_TTL and _hb_cache["config"] is not None:
            # Cache hit — use cached values
            cfg_row = _hb_cache["config"]
            secret = _hb_cache["secret"]
        else:
            # Cache miss — query DB and refresh cache
            from app.modules.ha.models import HAConfig
            from sqlalchemy import select

            result = await db.execute(select(HAConfig).limit(1))
            cfg_row = result.scalars().first()

            # Decrypt secret from DB — no env-var fallback
            secret = ""
            if cfg_row and cfg_row.heartbeat_secret:
                try:
                    from app.core.encryption import envelope_decrypt_str as _decrypt
                    secret = _decrypt(cfg_row.heartbeat_secret)
                except Exception:
                    pass

            # Store snapshot in cache (detached from session)
            _hb_cache["config"] = cfg_row
            _hb_cache["secret"] = secret
            _hb_cache["ts"] = now_mono

        # Read app version from GIT_SHA or BUILD_DATE env var
        app_version = os.environ.get("GIT_SHA") or os.environ.get("BUILD_DATE") or None

        if cfg_row is None:
            # Not configured — return minimal healthy response
            payload = {
                "node_id": "",
                "node_name": "unconfigured",
                "role": "standalone",
                "status": "healthy",
                "database_status": "connected",
                "replication_lag_seconds": None,
                "sync_status": "not_configured",
                "uptime_seconds": round(now_mono - _start_time, 1),
                "maintenance": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "app_version": app_version,
            }
        else:
            maintenance = cfg_row.maintenance_mode if cfg_row else False
            sync_status = cfg_row.sync_status if cfg_row else "not_configured"

            # Get replication lag if standby
            lag: float | None = None
            if cfg_row.role == "standby":
                try:
                    lag = await ReplicationManager.get_replication_lag(db)
                except Exception:
                    pass

            payload = {
                "node_id": str(cfg_row.node_id),
                "node_name": cfg_row.node_name,
                "role": cfg_row.role,
                "status": "healthy",
                "database_status": "connected",
                "replication_lag_seconds": lag,
                "sync_status": sync_status,
                "uptime_seconds": round(now_mono - _start_time, 1),
                "maintenance": maintenance,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "promoted_at": cfg_row.promoted_at.isoformat() if cfg_row.promoted_at else None,
                "app_version": app_version,
            }

        # Sign the payload
        import json as _json
        import hashlib as _hashlib
        import hmac as _hmac

        canonical = _json.dumps(payload, sort_keys=True, separators=(",", ":"))
        signature = _hmac.new(
            secret.encode(), canonical.encode(), _hashlib.sha256,
        ).hexdigest()

        response_data = _json.loads(canonical)
        response_data["hmac_signature"] = signature

        from starlette.responses import Response
        final_json = _json.dumps(response_data, sort_keys=True, separators=(",", ":"))
        return Response(content=final_json, media_type="application/json")

    except Exception as exc:
        logger.error("Heartbeat endpoint error: %s", exc)
        return JSONResponse(status_code=503, content={"detail": f"Node unhealthy: {exc}"})


@public_router.get(
    "/status",
    response_model=PublicStatusResponse,
    summary="Public node status (minimal info)",
)
async def status(db: AsyncSession = Depends(get_db_session)):
    """Return lightweight node status for the login page indicator.

    Only exposes: node_name, role, peer_status, sync_status.
    No sensitive information is included.
    """
    config = await HAService.get_config(db)
    if config is None:
        return PublicStatusResponse(
            node_name="unconfigured",
            role="standalone",
            peer_status="unknown",
            sync_status="not_configured",
        )

    # Get peer health from heartbeat service
    hb_service = get_heartbeat_service()
    peer_status = hb_service.get_peer_health() if hb_service else "unknown"

    # Get sync status from DB
    from app.modules.ha.models import HAConfig
    from sqlalchemy import select

    result = await db.execute(select(HAConfig).limit(1))
    cfg_row = result.scalars().first()
    sync_status = cfg_row.sync_status if cfg_row else "not_configured"

    return PublicStatusResponse(
        node_name=config.node_name,
        role=config.role,
        peer_status=peer_status,
        sync_status=sync_status,
    )


# ---------------------------------------------------------------------------
# Admin router — requires global_admin role
# ---------------------------------------------------------------------------

admin_router = APIRouter(dependencies=[require_role("global_admin")])


@admin_router.get(
    "/identity",
    response_model=HAConfigResponse,
    summary="Full node identity and config",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "HA not configured"},
    },
)
async def identity(db: AsyncSession = Depends(get_db_session)):
    """Return the full node identity, role, and peer configuration."""
    try:
        return await HAService.get_identity(db)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})


@admin_router.put(
    "/configure",
    response_model=HAConfigResponse,
    summary="Set/update HA configuration",
    responses={
        400: {"description": "Invalid configuration"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def configure(
    payload: HAConfigRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create or update the HA configuration for this node."""
    user_id = uuid.UUID(request.state.user_id)
    try:
        return await HAService.save_config(db, payload, user_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        logger.error("Configure error: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@admin_router.post(
    "/promote",
    summary="Promote standby to primary",
    responses={
        400: {"description": "Invalid state or confirmation"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "HA not configured"},
    },
)
async def promote(
    payload: PromoteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Promote the current standby node to primary.

    Requires ``confirmation_text == "CONFIRM"`` and validates replication
    lag (< 5 s unless ``force=true``).
    """
    if not validate_confirmation_text(payload.confirmation_text):
        return JSONResponse(
            status_code=400,
            content={"detail": "Confirmation text must be exactly 'CONFIRM'"},
        )

    user_id = uuid.UUID(request.state.user_id)
    try:
        result = await HAService.promote(
            db, user_id=user_id, reason=payload.reason, force=payload.force,
        )
        return result
    except ValueError as exc:
        msg = str(exc)
        if "not configured" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})


@admin_router.post(
    "/demote",
    summary="Demote primary to standby",
    responses={
        400: {"description": "Invalid state or confirmation"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "HA not configured"},
    },
)
async def demote(
    payload: DemoteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Demote the current primary node to standby.

    Requires ``confirmation_text == "CONFIRM"``.
    """
    if not validate_confirmation_text(payload.confirmation_text):
        return JSONResponse(
            status_code=400,
            content={"detail": "Confirmation text must be exactly 'CONFIRM'"},
        )

    user_id = uuid.UUID(request.state.user_id)
    try:
        result = await HAService.demote(db, user_id=user_id, reason=payload.reason)
        return result
    except ValueError as exc:
        msg = str(exc)
        if "not configured" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})


@admin_router.post(
    "/replication/init",
    summary="Initialize replication",
    responses={
        400: {"description": "Replication init failed"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "HA not configured"},
    },
)
async def replication_init(
    request: Request,
):
    """Initialize PostgreSQL logical replication.

    On a primary node, creates the publication.
    On a standby node, creates the subscription using the peer DB URL from GUI config.

    This endpoint manages its own DB session because the DDL operations
    (CREATE PUBLICATION / CREATE SUBSCRIPTION) can take longer than the
    ``idle_in_transaction_session_timeout`` configured on production
    postgres (30s).  Using ``Depends(get_db_session)`` would leave the
    session idle inside a transaction while the DDL runs on a separate
    raw asyncpg connection, causing postgres to kill the idle session
    and the subsequent cleanup to fail with "underlying connection is
    closed".
    """
    # --- Phase 1: read config using a short-lived session ----------------
    role = None
    peer_db_url = None
    try:
        async with async_session_factory() as db:
            async with db.begin():
                config = await HAService.get_config(db)
                if config is None:
                    return JSONResponse(
                        status_code=404,
                        content={"detail": "HA is not configured. Use PUT /api/v1/ha/configure first."},
                    )
                role = config.role
                if role == "standby":
                    peer_db_url = await get_peer_db_url(db)
    except Exception as exc:
        logger.error("Failed to read HA config: %s", exc)
        return JSONResponse(status_code=500, content={"detail": f"Failed to read HA config: {exc}"})

    if role == "standby" and not peer_db_url:
        return JSONResponse(
            status_code=400,
            content={"detail": "Peer database connection is not configured. Set peer DB settings in HA configuration."},
        )

    # --- Phase 2: run DDL (no SQLAlchemy session open) -------------------
    try:
        if role == "primary":
            result = await ReplicationManager.init_primary(None)
        elif role == "standby":
            result = await ReplicationManager.init_standby(None, peer_db_url, truncate_first=True)
        else:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Cannot init replication in '{role}' role. Must be 'primary' or 'standby'."},
            )
        return result
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        logger.error("Replication init error: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})



@admin_router.get(
    "/replication/status",
    response_model=ReplicationStatusResponse,
    summary="Replication health details",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        503: {"description": "Could not query replication status"},
    },
)
async def replication_status(db: AsyncSession = Depends(get_db_session)):
    """Return detailed replication health: publication, subscription, lag, etc."""
    try:
        return await ReplicationManager.get_replication_status(db)
    except Exception as exc:
        logger.error("Replication status error: %s", exc)
        return JSONResponse(status_code=503, content={"detail": str(exc)})


@admin_router.post(
    "/replication/resync",
    summary="Trigger full re-sync",
    responses={
        400: {"description": "Re-sync failed or not applicable"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def replication_resync(
    request: Request,
):
    """Drop and re-create the subscription with ``copy_data=true`` for a full re-sync.

    Uses the same session-free pattern as replication_init to avoid
    idle_in_transaction_session_timeout killing the connection.
    """
    # --- Phase 1: read peer_db_url using a short-lived session -----------
    peer_db_url = None
    try:
        async with async_session_factory() as db:
            async with db.begin():
                peer_db_url = await get_peer_db_url(db)
    except Exception as exc:
        logger.error("Failed to read peer DB URL: %s", exc)
        return JSONResponse(status_code=500, content={"detail": f"Failed to read HA config: {exc}"})

    if not peer_db_url:
        return JSONResponse(
            status_code=400,
            content={"detail": "Peer database connection is not configured. Set peer DB settings in HA configuration."},
        )

    # --- Phase 2: run DDL (no SQLAlchemy session open) -------------------
    try:
        await ReplicationManager.trigger_resync(None, peer_db_url)
        return {"status": "ok", "message": "Full re-sync initiated"}
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        logger.error("Replication resync error: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@admin_router.post(
    "/replication/stop",
    summary="Stop replication (drop publication or subscription)",
    responses={
        200: {"description": "Replication stopped"},
        400: {"description": "Stop failed"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "HA not configured"},
    },
)
async def replication_stop(request: Request):
    """Stop replication by dropping the publication (primary) or subscription (standby).

    Uses the same session-free pattern as replication_init.
    """
    role = None
    try:
        async with async_session_factory() as db:
            async with db.begin():
                config = await HAService.get_config(db)
                if config is None:
                    return JSONResponse(
                        status_code=404,
                        content={"detail": "HA is not configured."},
                    )
                role = config.role
    except Exception as exc:
        logger.error("Failed to read HA config: %s", exc)
        return JSONResponse(status_code=500, content={"detail": f"Failed to read HA config: {exc}"})

    try:
        if role == "primary":
            await ReplicationManager.drop_publication(None)
            return {"status": "ok", "message": "Publication dropped"}
        elif role == "standby":
            await ReplicationManager.drop_subscription(None)
            return {"status": "ok", "message": "Subscription dropped"}
        else:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Cannot stop replication in '{role}' role."},
            )
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        logger.error("Replication stop error: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@admin_router.post(
    "/test-db-connection",
    summary="Test peer database connection",
    responses={
        200: {"description": "Connection successful"},
        400: {"description": "Connection failed"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def test_db_connection(payload: PeerDBTestRequest):
    """Test connectivity to a peer PostgreSQL database using the provided credentials.

    Opens a short-lived asyncpg connection and runs a simple query.
    Supports SSL mode configuration.
    """
    import asyncpg
    from urllib.parse import quote_plus

    # Defensive: strip port from host if user accidentally included it (e.g. "192.168.1.90:8999")
    host = payload.host.strip()
    if ":" in host:
        host = host.split(":")[0]

    dsn = f"postgresql://{quote_plus(payload.user)}:{quote_plus(payload.password)}@{host}:{payload.port}/{payload.dbname}"

    # Map sslmode to asyncpg ssl parameter
    # IMPORTANT: asyncpg defaults to attempting SSL negotiation. We must
    # pass ssl=False explicitly when the user chose "disable".
    ssl_param: object = False  # False = no SSL at all
    if payload.sslmode == "require":
        import ssl as _ssl
        # require = encrypted but don't verify cert
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        ssl_param = ctx
    elif payload.sslmode in ("verify-ca", "verify-full"):
        import ssl as _ssl
        ssl_param = _ssl.create_default_context()
        # For verify-full, hostname checking is on by default

    try:
        conn = await asyncpg.connect(dsn, timeout=10, ssl=ssl_param, server_settings={"search_path": "public"})
        try:
            version = await conn.fetchval("SELECT version()")
            wal_level = await conn.fetchval("SHOW wal_level")
            # Check if SSL is active on this connection
            ssl_in_use = await conn.fetchval("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
            return {
                "status": "ok",
                "message": "Connection successful",
                "server_version": version,
                "wal_level": wal_level,
                "replication_ready": wal_level == "logical",
                "ssl_active": bool(ssl_in_use),
            }
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning("Peer DB connection test failed: %s", exc)
        return JSONResponse(
            status_code=400,
            content={"detail": f"Connection failed: {exc}"},
        )


@admin_router.get(
    "/local-db-info",
    summary="Detect local host LAN IP and exposed postgres port",
    responses={
        200: {"description": "Local database connection info for peer configuration"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def local_db_info(db: AsyncSession = Depends(get_db_session)):
    """Return the host's LAN IP and the postgres port visible to external peers.

    Priority: DB-stored field > env var > auto-detect for LAN IP,
    and DB-stored field > env var > 5432 for PG port.
    """
    from app.modules.ha.models import HAConfig
    from sqlalchemy import select as _select

    result = await db.execute(_select(HAConfig).limit(1))
    cfg = result.scalars().first()

    # LAN IP: DB field > env var > auto-detect
    lan_ip = (cfg.local_lan_ip if cfg and cfg.local_lan_ip else None) or _detect_host_lan_ip()

    # PG port: DB field > env var > 5432
    pg_port = (cfg.local_pg_port if cfg and cfg.local_pg_port else None) or int(os.environ.get("HA_LOCAL_PG_PORT", "5432"))

    # Database name from the current connection
    from app.config import settings as app_settings
    # Parse dbname from DATABASE_URL: ...@host:port/dbname
    db_name = "workshoppro"
    try:
        db_name = app_settings.database_url.rsplit("/", 1)[-1].split("?")[0]
    except Exception:
        pass

    # Check if SSL is enabled on the local postgres
    ssl_enabled = False
    try:
        import asyncpg
        dsn = app_settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        conn = await asyncpg.connect(dsn, timeout=5)
        try:
            ssl_val = await conn.fetchval("SHOW ssl")
            ssl_enabled = ssl_val == "on"
        finally:
            await conn.close()
    except Exception:
        pass

    return {
        "lan_ip": lan_ip,
        "pg_port": pg_port,
        "db_name": db_name,
        "ssl_enabled": ssl_enabled,
        "ssh_port": int(os.environ.get("HA_LOCAL_SSH_PORT", "2222")),
    }


@admin_router.post(
    "/create-replication-user",
    summary="Create a dedicated replication user on the local database",
    responses={
        200: {"description": "User created or updated"},
        400: {"description": "Failed to create user"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def create_replication_user(
    payload: CreateReplicationUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a dedicated PostgreSQL user with REPLICATION and SELECT privileges.

    This user should be used for peer DB connections instead of the superuser.
    Runs on the LOCAL database — the peer node then connects using these credentials.

    Returns the connection string that the peer node should use.
    """
    import asyncpg
    from app.config import settings

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    try:
        conn = await asyncpg.connect(dsn, timeout=10)
        try:
            # Check if user exists
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_roles WHERE rolname = $1", payload.username,
            )
            # Sanitize username — only allow alphanumeric and underscores
            import re
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', payload.username):
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid username. Use only letters, numbers, and underscores."},
                )

            if exists:
                # Use PostgreSQL's quote_literal for safe password escaping
                escaped_pw = await conn.fetchval("SELECT quote_literal($1)", payload.password)
                escaped_user = await conn.fetchval("SELECT quote_ident($1)", payload.username)
                await conn.execute(
                    f"ALTER USER {escaped_user} WITH REPLICATION BYPASSRLS LOGIN PASSWORD {escaped_pw}"
                )
                msg = f"User '{payload.username}' already exists — password updated"
            else:
                escaped_pw = await conn.fetchval("SELECT quote_literal($1)", payload.password)
                escaped_user = await conn.fetchval("SELECT quote_ident($1)", payload.username)
                await conn.execute(
                    f"CREATE USER {escaped_user} WITH REPLICATION BYPASSRLS LOGIN PASSWORD {escaped_pw}"
                )
                msg = f"User '{payload.username}' created with REPLICATION + BYPASSRLS privilege"

            # Grant SELECT on all tables (username already validated by regex above)
            await conn.execute(f"GRANT USAGE ON SCHEMA public TO {escaped_user}")
            await conn.execute(
                f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {escaped_user}"
            )
            await conn.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {escaped_user}"
            )

            # Audit log
            user_id = uuid.UUID(request.state.user_id)
            await write_audit_log(
                session=db,
                action="ha.replication_user_created",
                entity_type="ha_config",
                user_id=user_id,
                after_value={"username": payload.username},
            )

            # Build connection string for the peer node
            # Priority: DB field > env var > auto-detect
            # NOTE: Query HAConfig BEFORE the transaction closes
            from app.modules.ha.models import HAConfig as _HAConfig
            from sqlalchemy import select as _sel

            _cfg_result = await db.execute(_sel(_HAConfig).limit(1))
            _cfg = _cfg_result.scalars().first()

            lan_ip = (_cfg.local_lan_ip if _cfg and _cfg.local_lan_ip else None) or _detect_host_lan_ip()
            pg_port = (_cfg.local_pg_port if _cfg and _cfg.local_pg_port else None) or int(os.environ.get("HA_LOCAL_PG_PORT", "5432"))
            db_name = "workshoppro"
            try:
                db_name = settings.database_url.rsplit("/", 1)[-1].split("?")[0]
            except Exception:
                pass

            # Check SSL
            ssl_on = False
            try:
                ssl_val = await conn.fetchval("SHOW ssl")
                ssl_on = ssl_val == "on"
            except Exception:
                pass

            sslmode_suffix = "?sslmode=require" if ssl_on else ""
            connection_string = (
                f"postgresql://{payload.username}:<password>@{lan_ip}:{pg_port}/{db_name}{sslmode_suffix}"
            )

            return {
                "status": "ok",
                "message": msg,
                "username": payload.username,
                "connection_info": {
                    "host": lan_ip,
                    "port": pg_port,
                    "dbname": db_name,
                    "user": payload.username,
                    "ssl_enabled": ssl_on,
                    "connection_string": connection_string,
                },
            }
        finally:
            await conn.close()
    except Exception as exc:
        logger.error("Failed to create replication user: %s", exc)
        return JSONResponse(
            status_code=400,
            content={"detail": f"Failed to create replication user: {exc}"},
        )


@admin_router.post(
    "/maintenance-mode",
    summary="Enter maintenance mode",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "HA not configured"},
    },
)
async def maintenance_mode(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Put the current node into maintenance mode.

    The node continues serving requests but the heartbeat response will
    include ``maintenance: true`` so the peer knows.
    """
    user_id = uuid.UUID(request.state.user_id)
    try:
        return await HAService.enter_maintenance_mode(db, user_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})


@admin_router.post(
    "/ready",
    summary="Exit maintenance mode",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "HA not configured"},
    },
)
async def ready(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Signal that the node has been updated and is ready to resume normal operation."""
    user_id = uuid.UUID(request.state.user_id)
    try:
        return await HAService.exit_maintenance_mode(db, user_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})


@admin_router.get(
    "/history",
    response_model=list[HeartbeatHistoryEntry],
    summary="Heartbeat history (last 100)",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def history():
    """Return the last 100 heartbeat results from the in-memory ring buffer."""
    hb_service = get_heartbeat_service()
    if hb_service is None:
        return []
    return hb_service.get_history()


@admin_router.get(
    "/failover-status",
    response_model=FailoverStatusResponse,
    summary="Auto-promote countdown and split-brain status",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "HA not configured"},
    },
)
async def failover_status(db: AsyncSession = Depends(get_db_session)):
    """Return the current failover state for the frontend to poll.

    Includes auto-promote countdown, split-brain detection, and stale
    primary determination.

    Requirements: 5.5, 12.1, 12.2
    """
    from app.modules.ha.models import HAConfig
    from sqlalchemy import select

    result = await db.execute(select(HAConfig).limit(1))
    cfg = result.scalars().first()
    if cfg is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "HA is not configured."},
        )

    hb_service = get_heartbeat_service()

    peer_unreachable_seconds: float | None = None
    split_brain_detected = False
    is_stale = False
    seconds_until_auto_promote: float | None = None
    peer_role = hb_service.peer_role if hb_service is not None else "unknown"

    if hb_service is not None:
        peer_unreachable_seconds = hb_service.get_peer_unreachable_seconds()
        split_brain_detected = hb_service.split_brain_detected
        is_stale = hb_service.is_stale_primary(cfg.promoted_at)

        if (
            peer_unreachable_seconds is not None
            and cfg.auto_promote_enabled
        ):
            seconds_until_auto_promote = hb_service.get_seconds_until_auto_promote(
                cfg.failover_timeout_seconds,
            )

    return FailoverStatusResponse(
        auto_promote_enabled=cfg.auto_promote_enabled,
        peer_unreachable_seconds=peer_unreachable_seconds,
        failover_timeout_seconds=cfg.failover_timeout_seconds,
        seconds_until_auto_promote=seconds_until_auto_promote,
        split_brain_detected=split_brain_detected,
        is_stale_primary=is_stale,
        promoted_at=cfg.promoted_at.isoformat() if cfg.promoted_at else None,
        peer_role=peer_role,
    )


@admin_router.post(
    "/demote-and-sync",
    summary="Demote stale primary to standby and re-sync from new primary",
    responses={
        200: {"description": "Role reversal completed"},
        400: {"description": "Invalid state or confirmation"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "HA not configured"},
    },
)
async def demote_and_sync(
    payload: DemoteAndSyncRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Demote this node to standby, truncate local data, and subscribe to the new primary.

    Used during the guided role-reversal recovery flow after a split-brain
    condition is detected and this node is the stale primary.

    Requirements: 7.3, 7.4, 7.5, 7.6
    """
    if not validate_confirmation_text(payload.confirmation_text):
        return JSONResponse(
            status_code=400,
            content={"detail": "Confirmation text must be exactly 'CONFIRM'"},
        )

    user_id = uuid.UUID(request.state.user_id)
    try:
        result = await HAService.demote_and_sync(db, user_id=user_id, reason=payload.reason)
        return result
    except ValueError as exc:
        msg = str(exc)
        if "not configured" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception as exc:
        logger.error("Demote-and-sync error: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Wizard — Setup Flow Endpoints
# ---------------------------------------------------------------------------


@admin_router.post(
    "/wizard/check-reachability",
    response_model=WizardCheckReachabilityResponse,
    summary="Check if a remote node is reachable and running OraInvoice",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def wizard_check_reachability(
    payload: WizardCheckReachabilityRequest,
):
    """Verify that a remote node is reachable and running OraInvoice.

    Sends an HTTP GET to ``{address}/api/v1/ha/heartbeat`` with a 10-second
    timeout.  Parses the response to determine if the remote host is a valid
    OraInvoice node.  Compares the local ``GIT_SHA`` env var with the peer's
    ``app_version`` field (if present) and includes a version mismatch warning
    when they differ.

    **Validates: Requirements 4.1, 4.2, 5.1, 5.2, 5.3, 5.4, 37.1, 37.2, 37.3**
    """
    import httpx

    address = payload.address.strip().rstrip("/")
    if not address:
        return WizardCheckReachabilityResponse(
            reachable=False,
            error="Address cannot be empty",
        )

    heartbeat_url = f"{address}/api/v1/ha/heartbeat"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(heartbeat_url)

        if resp.status_code != 200:
            return WizardCheckReachabilityResponse(
                reachable=False,
                error=f"Remote node returned HTTP {resp.status_code}",
            )

        data = resp.json()

        # Validate this is an OraInvoice heartbeat response by checking
        # for expected fields (node_name, role, status are always present).
        is_orainvoice = all(
            k in data for k in ("node_name", "role", "status")
        )

        if not is_orainvoice:
            return WizardCheckReachabilityResponse(
                reachable=True,
                is_orainvoice=False,
                error="Remote host responded but does not appear to be an OraInvoice node",
            )

        # Version comparison — compare local GIT_SHA with peer's app_version
        version_warning: str | None = None
        local_version = os.environ.get("GIT_SHA", "").strip()
        peer_version = (data.get("app_version") or "").strip()

        if local_version and peer_version and local_version != peer_version:
            version_warning = (
                f"Version mismatch: local={local_version}, "
                f"peer={peer_version}. This may be expected during "
                f"rolling updates."
            )

        return WizardCheckReachabilityResponse(
            reachable=True,
            node_name=data.get("node_name"),
            role=data.get("role"),
            is_orainvoice=True,
            version_warning=version_warning,
        )

    except httpx.TimeoutException:
        return WizardCheckReachabilityResponse(
            reachable=False,
            error=f"Connection to {address} timed out after 10 seconds",
        )
    except httpx.ConnectError:
        return WizardCheckReachabilityResponse(
            reachable=False,
            error=f"Could not connect to {address} — verify the address and that the node is running",
        )
    except Exception as exc:
        logger.error("Reachability check failed for %s: %s", address, exc)
        return WizardCheckReachabilityResponse(
            reachable=False,
            error=f"Reachability check failed: {exc}",
        )


@admin_router.post(
    "/wizard/authenticate",
    response_model=WizardAuthenticateResponse,
    summary="Authenticate against a remote OraInvoice node",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def wizard_authenticate(
    payload: WizardAuthenticateRequest,
):
    """Proxy a login request to the remote node and verify Global_Admin role.

    Sends a POST to ``{address}/api/v1/auth/login`` with the provided email
    and password.  On success, decodes the returned JWT access token to check
    for the ``global_admin`` role in the claims.  Returns the token only if
    the user is a Global_Admin on the remote node.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
    """
    import httpx
    import json as _json
    import base64

    address = payload.address.strip().rstrip("/")
    if not address:
        return WizardAuthenticateResponse(
            authenticated=False,
            error="Address cannot be empty",
        )

    login_url = f"{address}/api/v1/auth/login"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.post(
                login_url,
                json={"email": payload.email, "password": payload.password},
            )

        # Handle authentication failure
        if resp.status_code == 401:
            return WizardAuthenticateResponse(
                authenticated=False,
                error="Invalid credentials — check email and password",
            )

        if resp.status_code != 200:
            return WizardAuthenticateResponse(
                authenticated=False,
                error=f"Remote node returned HTTP {resp.status_code}",
            )

        data = resp.json()

        # Handle MFA required — the wizard does not support MFA flow
        if data.get("mfa_required"):
            return WizardAuthenticateResponse(
                authenticated=False,
                error="MFA is required on the remote node. Please disable MFA temporarily or use an account without MFA for the wizard setup.",
            )

        access_token = data.get("access_token")
        if not access_token:
            return WizardAuthenticateResponse(
                authenticated=False,
                error="Remote node did not return an access token",
            )

        # Decode JWT claims (without verification — we trust the remote
        # node issued it; we only need to read the role claim).
        try:
            # JWT structure: header.payload.signature
            parts = access_token.split(".")
            if len(parts) < 2:
                return WizardAuthenticateResponse(
                    authenticated=False,
                    error="Invalid token format received from remote node",
                )

            # Decode the payload (second part), adding padding if needed
            payload_b64 = parts[1]
            # Add padding for base64 decoding
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding

            claims_bytes = base64.urlsafe_b64decode(payload_b64)
            claims = _json.loads(claims_bytes)
        except Exception as exc:
            logger.error("Failed to decode JWT from remote node: %s", exc)
            return WizardAuthenticateResponse(
                authenticated=False,
                error="Failed to decode authentication token from remote node",
            )

        # Check for global_admin role in the JWT claims
        role = claims.get("role", "")
        is_global_admin = role == "global_admin"

        if not is_global_admin:
            return WizardAuthenticateResponse(
                authenticated=True,
                is_global_admin=False,
                error="The authenticated user does not have the Global_Admin role on the remote node. Global_Admin privileges are required on both nodes for HA setup.",
            )

        return WizardAuthenticateResponse(
            authenticated=True,
            is_global_admin=True,
            token=access_token,
        )

    except httpx.TimeoutException:
        return WizardAuthenticateResponse(
            authenticated=False,
            error=f"Connection to {address} timed out",
        )
    except httpx.ConnectError:
        return WizardAuthenticateResponse(
            authenticated=False,
            error=f"Could not connect to {address} — verify the address and that the node is running",
        )
    except Exception as exc:
        logger.error("Authentication proxy failed for %s: %s", address, exc)
        return WizardAuthenticateResponse(
            authenticated=False,
            error=f"Authentication failed: {exc}",
        )


# ---------------------------------------------------------------------------
# Helper — read local SSH public key
# ---------------------------------------------------------------------------

def _read_local_ssh_pub_key() -> str:
    """Read the local SSH public key from ``/ha_keys/id_ed25519.pub``.

    Returns the key contents stripped of trailing whitespace, or raises
    ``FileNotFoundError`` if the key file does not exist.
    """
    with open("/ha_keys/id_ed25519.pub", "r") as f:
        return f.read().strip()


# ---------------------------------------------------------------------------
# Helper — read local LAN IP and PG port (DB > env/file > auto-detect)
# ---------------------------------------------------------------------------

async def _get_local_lan_ip_and_pg_port(
    db: AsyncSession,
) -> tuple[str, int]:
    """Return ``(lan_ip, pg_port)`` using the priority chain:

    **LAN IP:**  DB ``ha_config.local_lan_ip`` → ``/tmp/host_lan_ip`` file
    (written by entrypoint) → env ``HA_LOCAL_LAN_IP`` → ``_detect_host_lan_ip()``

    **PG port:** DB ``ha_config.local_pg_port`` → env ``HA_LOCAL_PG_PORT`` → 5432
    """
    from app.modules.ha.models import HAConfig
    from sqlalchemy import select as _select

    result = await db.execute(_select(HAConfig).limit(1))
    cfg = result.scalars().first()

    # --- LAN IP ---
    lan_ip: str | None = None
    if cfg and cfg.local_lan_ip:
        lan_ip = cfg.local_lan_ip

    if not lan_ip:
        # Try /tmp/host_lan_ip (written by entrypoint)
        try:
            with open("/tmp/host_lan_ip", "r") as f:
                val = f.read().strip()
                if val:
                    lan_ip = val
        except Exception:
            pass

    if not lan_ip:
        lan_ip = _detect_host_lan_ip()

    # --- PG port ---
    pg_port: int | None = None
    if cfg and cfg.local_pg_port:
        pg_port = cfg.local_pg_port

    if pg_port is None:
        pg_port = int(os.environ.get("HA_LOCAL_PG_PORT", "5432"))

    return lan_ip, pg_port


# ---------------------------------------------------------------------------
# Helper — append SSH public key to authorized_keys (idempotent)
# ---------------------------------------------------------------------------

def _append_ssh_key_to_authorized_keys(ssh_pub_key: str) -> None:
    """Append *ssh_pub_key* to ``/ha_keys/authorized_keys`` if not already present.

    Idempotent — compares the key content (ignoring trailing whitespace)
    against every existing line.  No duplicates are created.
    """
    auth_keys_path = "/ha_keys/authorized_keys"
    key_stripped = ssh_pub_key.strip()

    # Read existing keys
    existing_keys: list[str] = []
    try:
        with open(auth_keys_path, "r") as f:
            existing_keys = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        pass  # File will be created below

    # Check for duplicate
    if key_stripped in existing_keys:
        return  # Already present — nothing to do

    # Append
    with open(auth_keys_path, "a") as f:
        f.write(key_stripped + "\n")


@admin_router.post(
    "/wizard/handshake",
    response_model=WizardHandshakeResponse,
    summary="Trust handshake — exchange SSH keys, IPs, ports, and HMAC secret with standby",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def wizard_handshake(
    payload: WizardHandshakeRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Perform the trust handshake between the primary and standby nodes.

    1. Read local SSH public key from ``/ha_keys/id_ed25519.pub``
    2. Read local LAN IP and PG port (DB > env/file > auto-detect)
    3. Generate a 32-byte cryptographically random HMAC secret
    4. POST to ``{address}/api/v1/ha/wizard/receive-handshake`` with the
       standby's auth token, sending: ssh_pub_key, lan_ip, pg_port, hmac_secret
    5. Receive standby's SSH public key, LAN IP, PG port in response
    6. Append standby's SSH public key to local ``/ha_keys/authorized_keys``
       (idempotent — no duplicates)
    7. Store HMAC secret in local ``ha_config`` (encrypted via ``envelope_encrypt``)
    8. Log event to ``ha_event_log``
    9. Return both IPs, both PG ports, and hmac_secret_set flag

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9,
    14.1, 14.2, 15.2, 16.1, 16.2, 16.4, 30.1**
    """
    import httpx
    import secrets

    address = payload.address.strip().rstrip("/")
    if not address:
        return WizardHandshakeResponse(
            success=False,
            error="Address cannot be empty",
        )

    # --- Step 1: Read local SSH public key ---
    try:
        local_ssh_pub_key = _read_local_ssh_pub_key()
    except FileNotFoundError:
        return WizardHandshakeResponse(
            success=False,
            error="Local SSH public key not found at /ha_keys/id_ed25519.pub — "
                  "ensure the container started correctly and generated SSH keys",
        )
    except Exception as exc:
        return WizardHandshakeResponse(
            success=False,
            error=f"Failed to read local SSH public key: {exc}",
        )

    # --- Step 2: Read local LAN IP and PG port ---
    try:
        local_lan_ip, local_pg_port = await _get_local_lan_ip_and_pg_port(db)
    except Exception as exc:
        return WizardHandshakeResponse(
            success=False,
            error=f"Failed to detect local network info: {exc}",
        )

    # --- Step 3: Generate HMAC secret ---
    hmac_secret = secrets.token_hex(32)  # 32 bytes = 64 hex chars

    # --- Step 4: POST to standby's receive-handshake endpoint ---
    receive_url = f"{address}/api/v1/ha/wizard/receive-handshake"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.post(
                receive_url,
                json={
                    "ssh_pub_key": local_ssh_pub_key,
                    "lan_ip": local_lan_ip,
                    "pg_port": local_pg_port,
                    "hmac_secret": hmac_secret,
                },
                headers={"Authorization": f"Bearer {payload.standby_token}"},
            )

        if resp.status_code == 401 or resp.status_code == 403:
            return WizardHandshakeResponse(
                success=False,
                error="Authentication failed on standby node — the token may have expired. "
                      "Please re-authenticate and try again.",
            )

        if resp.status_code != 200:
            detail = ""
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            return WizardHandshakeResponse(
                success=False,
                error=f"Standby node returned HTTP {resp.status_code}: {detail}",
            )

        standby_data = resp.json()
    except httpx.TimeoutException:
        return WizardHandshakeResponse(
            success=False,
            error=f"Connection to {address} timed out during handshake",
        )
    except httpx.ConnectError:
        return WizardHandshakeResponse(
            success=False,
            error=f"Could not connect to {address} — verify the address and that the node is running",
        )
    except Exception as exc:
        logger.error("Handshake POST to %s failed: %s", address, exc)
        return WizardHandshakeResponse(
            success=False,
            error=f"Handshake failed: {exc}",
        )

    # --- Step 5: Extract standby's response ---
    standby_ssh_pub_key = standby_data.get("ssh_pub_key", "")
    standby_lan_ip = standby_data.get("lan_ip", "")
    standby_pg_port = standby_data.get("pg_port", 5432)

    if not standby_ssh_pub_key:
        return WizardHandshakeResponse(
            success=False,
            error="Standby node did not return its SSH public key",
        )

    # --- Step 6: Append standby's SSH public key to local authorized_keys ---
    try:
        _append_ssh_key_to_authorized_keys(standby_ssh_pub_key)
    except Exception as exc:
        logger.error("Failed to append standby SSH key to authorized_keys: %s", exc)
        return WizardHandshakeResponse(
            success=False,
            error=f"Failed to update local authorized_keys: {exc}",
        )

    # --- Step 7: Store HMAC secret in local ha_config (encrypted) ---
    try:
        from app.core.encryption import envelope_encrypt
        from app.modules.ha.models import HAConfig
        from sqlalchemy import select as _select

        result = await db.execute(_select(HAConfig).limit(1))
        cfg = result.scalars().first()

        encrypted_secret = envelope_encrypt(hmac_secret)

        if cfg is not None:
            cfg.heartbeat_secret = encrypted_secret
            cfg.updated_at = datetime.now(timezone.utc)
        else:
            # No config row yet — create a minimal one to store the secret
            cfg = HAConfig(
                node_name=f"node-{uuid.uuid4().hex[:8]}",
                role="standalone",
                heartbeat_secret=encrypted_secret,
            )
            db.add(cfg)

        await db.flush()
    except Exception as exc:
        logger.error("Failed to store HMAC secret in ha_config: %s", exc)
        return WizardHandshakeResponse(
            success=False,
            error=f"Failed to store HMAC secret: {exc}",
        )

    # --- Step 8: Log event to ha_event_log ---
    try:
        from app.modules.ha.event_log import log_ha_event
        await log_ha_event(
            event_type="config_change",
            severity="info",
            message="Trust handshake completed — SSH keys exchanged, HMAC secret stored",
            details={
                "primary_ip": local_lan_ip,
                "primary_pg_port": local_pg_port,
                "standby_ip": standby_lan_ip,
                "standby_pg_port": standby_pg_port,
                "hmac_secret_set": True,
            },
        )
    except Exception:
        pass  # Non-critical — event log failure should not block handshake

    # --- Step 9: Return response ---
    return WizardHandshakeResponse(
        success=True,
        primary_ip=local_lan_ip,
        primary_pg_port=local_pg_port,
        standby_ip=standby_lan_ip,
        standby_pg_port=standby_pg_port,
        hmac_secret_set=True,
    )


@admin_router.post(
    "/wizard/receive-handshake",
    response_model=WizardReceiveHandshakeResponse,
    summary="Receive trust handshake from peer (standby-side endpoint)",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def wizard_receive_handshake(
    payload: WizardReceiveHandshakeRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Receive the trust handshake data from the primary node.

    Called by the primary node during the wizard handshake step.  This
    endpoint:

    1. Appends the received SSH public key to ``/ha_keys/authorized_keys``
       (idempotent — no duplicates)
    2. Stores the HMAC secret in local ``ha_config`` (encrypted via
       ``envelope_encrypt``)
    3. Reads the local SSH public key from ``/ha_keys/id_ed25519.pub``
    4. Reads the local LAN IP and PG port (DB > env/file > auto-detect)
    5. Returns own SSH public key, LAN IP, and PG port

    **Validates: Requirements 10.1, 10.2, 10.3, 10.6, 30.2**
    """
    # --- Step 1: Append received SSH public key to authorized_keys ---
    try:
        _append_ssh_key_to_authorized_keys(payload.ssh_pub_key)
    except Exception as exc:
        logger.error("Failed to append peer SSH key to authorized_keys: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Failed to update authorized_keys: {exc}"},
        )

    # --- Step 2: Store HMAC secret in local ha_config (encrypted) ---
    try:
        from app.core.encryption import envelope_encrypt
        from app.modules.ha.models import HAConfig
        from sqlalchemy import select as _select

        result = await db.execute(_select(HAConfig).limit(1))
        cfg = result.scalars().first()

        encrypted_secret = envelope_encrypt(payload.hmac_secret)

        if cfg is not None:
            cfg.heartbeat_secret = encrypted_secret
            cfg.updated_at = datetime.now(timezone.utc)
        else:
            # No config row yet — create a minimal one to store the secret
            cfg = HAConfig(
                node_name=f"node-{uuid.uuid4().hex[:8]}",
                role="standalone",
                heartbeat_secret=encrypted_secret,
            )
            db.add(cfg)

        await db.flush()
    except Exception as exc:
        logger.error("Failed to store HMAC secret in ha_config: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Failed to store HMAC secret: {exc}"},
        )

    # --- Step 3: Read local SSH public key ---
    try:
        local_ssh_pub_key = _read_local_ssh_pub_key()
    except FileNotFoundError:
        return JSONResponse(
            status_code=500,
            content={"detail": "Local SSH public key not found at /ha_keys/id_ed25519.pub"},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Failed to read local SSH public key: {exc}"},
        )

    # --- Step 4: Read local LAN IP and PG port ---
    try:
        local_lan_ip, local_pg_port = await _get_local_lan_ip_and_pg_port(db)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Failed to detect local network info: {exc}"},
        )

    # --- Step 5: Log event ---
    try:
        from app.modules.ha.event_log import log_ha_event
        await log_ha_event(
            event_type="config_change",
            severity="info",
            message="Received trust handshake from peer — SSH key stored, HMAC secret saved",
            details={
                "peer_ip": payload.lan_ip,
                "peer_pg_port": payload.pg_port,
                "local_ip": local_lan_ip,
                "local_pg_port": local_pg_port,
            },
        )
    except Exception:
        pass  # Non-critical

    # --- Step 6: Return own details ---
    return WizardReceiveHandshakeResponse(
        ssh_pub_key=local_ssh_pub_key,
        lan_ip=local_lan_ip,
        pg_port=local_pg_port,
    )


@admin_router.post(
    "/wizard/setup",
    response_model=WizardSetupResponse,
    summary="Execute the full automated HA replication setup",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def wizard_setup(
    payload: WizardSetupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Execute the full automated HA replication setup sequence.

    Runs five steps in order, building a step log.  If any step fails,
    subsequent steps are marked as 'skipped' and the response is returned
    immediately.

    Steps:
    1. Configure standby node — PUT ``{address}/api/v1/ha/configure``
    2. Configure primary node — ``HAService.save_config()`` locally
    3. Create publication — ``ReplicationManager.init_primary()``
    4. Create subscription on standby — POST ``{address}/api/v1/ha/replication/init``
    5. Configure volume sync on both nodes

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8,
    10.4, 10.5, 14.1, 14.2, 14.3**
    """
    import httpx
    from app.modules.ha.event_log import log_ha_event
    from urllib.parse import urlparse

    address = payload.address.strip().rstrip("/")
    standby_token = payload.standby_token
    user_id = uuid.UUID(request.state.user_id)

    steps: list[WizardSetupStepResult] = []
    step_names = [
        "configure_standby",
        "configure_primary",
        "create_publication",
        "create_subscription",
        "configure_volume_sync",
    ]
    failed = False

    # --- Read handshake data (LAN IPs, PG ports) from ha_config / detection ---
    try:
        primary_lan_ip, primary_pg_port = await _get_local_lan_ip_and_pg_port(db)
    except Exception as exc:
        logger.error("Failed to read local network info for wizard setup: %s", exc)
        return WizardSetupResponse(
            success=False,
            steps=[],
            error=f"Failed to read local network info: {exc}",
        )

    # Read the handshake data stored during the handshake step to get standby info.
    # The handshake endpoint stored the HMAC secret but the standby IP/port are
    # not persisted in ha_config — we need to query the standby's local-db-info.
    standby_lan_ip: str | None = None
    standby_pg_port: int = 5432
    standby_ssh_port: int = 2222
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(
                f"{address}/api/v1/ha/local-db-info",
                headers={"Authorization": f"Bearer {standby_token}"},
            )
        if resp.status_code == 200:
            info = resp.json()
            standby_lan_ip = info.get("lan_ip")
            standby_pg_port = info.get("pg_port", 5432)
            standby_ssh_port = info.get("ssh_port", 2222)
    except Exception as exc:
        logger.warning("Could not fetch standby local-db-info: %s", exc)

    if not standby_lan_ip:
        # Fallback: parse the address to extract the host
        parsed = urlparse(address)
        standby_lan_ip = parsed.hostname or address

    # =====================================================================
    # Step 1: Configure standby node
    # =====================================================================
    if not failed:
        step_name = "configure_standby"
        try:
            await log_ha_event(
                event_type="config_change",
                severity="info",
                message="Wizard setup: configuring standby node",
                details={"address": address},
            )

            # Determine the primary's externally-visible API port.
            # Use the Host header from the current request (the admin is
            # connected to the primary), falling back to the standby's port
            # (same-environment assumption), then 8999.
            primary_api_port = 8999
            host_header = request.headers.get("host", "")
            if ":" in host_header:
                try:
                    primary_api_port = int(host_header.rsplit(":", 1)[1])
                except (ValueError, IndexError):
                    pass
            elif host_header:
                # No port in Host header — likely port 80 behind a proxy
                primary_api_port = 80

            # The standby's peer_endpoint should point to the primary
            # The standby's peer_db_url should point to the primary's database
            standby_config_body = {
                "node_name": "Standby",
                "role": "standby",
                "peer_endpoint": f"http://{primary_lan_ip}:{primary_api_port}",
                "auto_promote_enabled": False,
                "heartbeat_interval_seconds": 10,
                "failover_timeout_seconds": 90,
                "peer_db_host": primary_lan_ip,
                "peer_db_port": primary_pg_port,
                "peer_db_name": "workshoppro",
                "peer_db_user": "postgres",
                "peer_db_password": "postgres",
                "peer_db_sslmode": "disable",
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.put(
                    f"{address}/api/v1/ha/configure",
                    json=standby_config_body,
                    headers={"Authorization": f"Bearer {standby_token}"},
                )

            if resp.status_code == 200:
                steps.append(WizardSetupStepResult(
                    step=step_name,
                    status="completed",
                    message="Standby node configured with role=standby, peer pointing to primary",
                ))
                await log_ha_event(
                    event_type="config_change",
                    severity="info",
                    message="Wizard setup: standby node configured successfully",
                )
            else:
                detail = ""
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                steps.append(WizardSetupStepResult(
                    step=step_name,
                    status="failed",
                    error=f"Standby returned HTTP {resp.status_code}: {detail}",
                ))
                failed = True
                await log_ha_event(
                    event_type="config_change",
                    severity="error",
                    message=f"Wizard setup: failed to configure standby — HTTP {resp.status_code}",
                    details={"error": detail},
                )
        except Exception as exc:
            logger.error("Wizard setup step 1 (configure_standby) failed: %s", exc)
            steps.append(WizardSetupStepResult(
                step=step_name,
                status="failed",
                error=str(exc),
            ))
            failed = True
            await log_ha_event(
                event_type="config_change",
                severity="error",
                message=f"Wizard setup: failed to configure standby — {exc}",
            )

    # =====================================================================
    # Step 2: Configure primary node locally
    # =====================================================================
    if not failed:
        step_name = "configure_primary"
        try:
            await log_ha_event(
                event_type="config_change",
                severity="info",
                message="Wizard setup: configuring primary node locally",
            )

            # Read existing config to preserve node_name and other settings
            from app.modules.ha.models import HAConfig
            from sqlalchemy import select as _sel

            result = await db.execute(_sel(HAConfig).limit(1))
            existing_cfg = result.scalars().first()
            node_name = existing_cfg.node_name if existing_cfg else "Primary"

            # Determine the standby's API port from the address
            standby_parsed = urlparse(address)
            standby_api_port = standby_parsed.port or 8999

            primary_config = HAConfigRequest(
                node_name=node_name,
                role="primary",
                peer_endpoint=f"http://{standby_lan_ip}:{standby_api_port}",
                auto_promote_enabled=False,
                heartbeat_interval_seconds=10,
                failover_timeout_seconds=90,
                peer_db_host=standby_lan_ip,
                peer_db_port=standby_pg_port,
                peer_db_name="workshoppro",
                peer_db_user="postgres",
                peer_db_password="postgres",
                peer_db_sslmode="disable",
            )

            await HAService.save_config(db, primary_config, user_id)

            steps.append(WizardSetupStepResult(
                step=step_name,
                status="completed",
                message="Primary node configured with role=primary, peer pointing to standby",
            ))
            await log_ha_event(
                event_type="config_change",
                severity="info",
                message="Wizard setup: primary node configured successfully",
            )
        except Exception as exc:
            logger.error("Wizard setup step 2 (configure_primary) failed: %s", exc)
            steps.append(WizardSetupStepResult(
                step=step_name,
                status="failed",
                error=str(exc),
            ))
            failed = True
            await log_ha_event(
                event_type="config_change",
                severity="error",
                message=f"Wizard setup: failed to configure primary — {exc}",
            )

    # =====================================================================
    # Step 3: Create publication on primary
    # =====================================================================
    if not failed:
        step_name = "create_publication"
        try:
            await log_ha_event(
                event_type="config_change",
                severity="info",
                message="Wizard setup: creating replication publication on primary",
            )

            pub_result = await ReplicationManager.init_primary(db)

            steps.append(WizardSetupStepResult(
                step=step_name,
                status="completed",
                message=pub_result.get("message", "Publication created"),
            ))
            await log_ha_event(
                event_type="config_change",
                severity="info",
                message="Wizard setup: publication created successfully",
                details=pub_result,
            )
        except Exception as exc:
            logger.error("Wizard setup step 3 (create_publication) failed: %s", exc)
            steps.append(WizardSetupStepResult(
                step=step_name,
                status="failed",
                error=str(exc),
            ))
            failed = True
            await log_ha_event(
                event_type="config_change",
                severity="error",
                message=f"Wizard setup: failed to create publication — {exc}",
            )

    # =====================================================================
    # Step 4: Create subscription on standby
    # =====================================================================
    if not failed:
        step_name = "create_subscription"
        try:
            await log_ha_event(
                event_type="config_change",
                severity="info",
                message="Wizard setup: creating replication subscription on standby",
            )

            # --- Pre-cleanup: drop any orphaned replication slot on the primary ---
            # This is the most common failure mode when re-running the wizard.
            try:
                from app.core.database import async_session_factory
                async with async_session_factory() as cleanup_session:
                    async with cleanup_session.begin():
                        conn = await ReplicationManager._get_raw_conn()
                        try:
                            orphaned = await conn.fetchrow(
                                "SELECT slot_name, active FROM pg_replication_slots "
                                "WHERE slot_name = $1",
                                ReplicationManager.SUBSCRIPTION_NAME,
                            )
                            if orphaned and not orphaned["active"]:
                                await conn.execute(
                                    f"SELECT pg_drop_replication_slot('{ReplicationManager.SUBSCRIPTION_NAME}')"
                                )
                                logger.info(
                                    "Wizard: cleaned up orphaned replication slot '%s' on primary before subscription creation",
                                    ReplicationManager.SUBSCRIPTION_NAME,
                                )
                        finally:
                            await conn.close()
            except Exception as cleanup_exc:
                logger.warning("Wizard: pre-cleanup of orphaned slot failed (non-fatal): %s", cleanup_exc)

            # --- Create subscription on standby via API ---
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                resp = await client.post(
                    f"{address}/api/v1/ha/replication/init",
                    headers={"Authorization": f"Bearer {standby_token}"},
                )

            if resp.status_code == 200:
                sub_data = resp.json()

                # --- Post-verification: confirm the subscription actually exists ---
                # The init endpoint may return 200 but silently fail to create
                # the subscription (e.g., orphaned slot swallowed as "already exists").
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                        verify_resp = await client.get(
                            f"{address}/api/v1/ha/replication/status",
                            headers={"Authorization": f"Bearer {standby_token}"},
                        )
                    if verify_resp.status_code == 200:
                        verify_data = verify_resp.json()
                        sub_status = verify_data.get("subscription_status")
                        sub_name = verify_data.get("subscription_name")
                        if sub_name and sub_status:
                            logger.info(
                                "Wizard: verified subscription '%s' exists on standby (status=%s)",
                                sub_name, sub_status,
                            )
                        else:
                            # Subscription doesn't actually exist — report failure
                            logger.error(
                                "Wizard: subscription creation returned 200 but subscription does not exist on standby"
                            )
                            steps.append(WizardSetupStepResult(
                                step=step_name,
                                status="failed",
                                error="Subscription creation reported success but the subscription does not exist. "
                                      "Check the standby node's PostgreSQL logs. Common cause: orphaned replication "
                                      "slot on the primary. Try clicking 'Retry Setup' to auto-clean and retry.",
                            ))
                            failed = True
                            await log_ha_event(
                                event_type="replication_error",
                                severity="error",
                                message="Wizard: subscription phantom success — reported created but does not exist",
                                details={"verify_data": verify_data},
                            )
                            # Skip the success path below
                            raise _SubscriptionVerificationFailed()
                except _SubscriptionVerificationFailed:
                    raise
                except Exception as verify_exc:
                    logger.warning("Wizard: could not verify subscription (non-fatal): %s", verify_exc)

                steps.append(WizardSetupStepResult(
                    step=step_name,
                    status="completed",
                    message=sub_data.get("message", "Subscription created on standby"),
                ))
                await log_ha_event(
                    event_type="config_change",
                    severity="info",
                    message="Wizard setup: subscription created on standby successfully",
                    details=sub_data,
                )
            else:
                detail = ""
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                steps.append(WizardSetupStepResult(
                    step=step_name,
                    status="failed",
                    error=f"Standby returned HTTP {resp.status_code}: {detail}",
                ))
                failed = True
                await log_ha_event(
                    event_type="config_change",
                    severity="error",
                    message=f"Wizard setup: failed to create subscription on standby — HTTP {resp.status_code}",
                    details={"error": detail},
                )
        except _SubscriptionVerificationFailed:
            pass  # Already handled above — steps and failed flag already set
        except Exception as exc:
            logger.error("Wizard setup step 4 (create_subscription) failed: %s", exc)
            steps.append(WizardSetupStepResult(
                step=step_name,
                status="failed",
                error=str(exc),
            ))
            failed = True
            await log_ha_event(
                event_type="config_change",
                severity="error",
                message=f"Wizard setup: failed to create subscription on standby — {exc}",
            )

    # =====================================================================
    # Step 5: Configure volume sync on both nodes
    # =====================================================================
    if not failed:
        step_name = "configure_volume_sync"
        try:
            await log_ha_event(
                event_type="config_change",
                severity="info",
                message="Wizard setup: configuring volume sync on both nodes",
            )

            # Read the primary's SSH port from env
            primary_ssh_port = int(os.environ.get("HA_LOCAL_SSH_PORT", "2222"))

            # Primary's volume sync config: sync TO the standby
            primary_vs_body = {
                "standby_ssh_host": standby_lan_ip,
                "ssh_port": standby_ssh_port,
                "ssh_key_path": "/ha_keys/id_ed25519",
                "remote_upload_path": "/app/uploads/",
                "remote_compliance_path": "/app/compliance_files/",
                "sync_interval_minutes": 5,
                "enabled": True,
            }

            # Standby's volume sync config: sync TO the primary (for reverse sync if promoted)
            standby_vs_body = {
                "standby_ssh_host": primary_lan_ip,
                "ssh_port": primary_ssh_port,
                "ssh_key_path": "/ha_keys/id_ed25519",
                "remote_upload_path": "/app/uploads/",
                "remote_compliance_path": "/app/compliance_files/",
                "sync_interval_minutes": 5,
                "enabled": False,  # Disabled on standby — only primary syncs actively
            }

            # Configure volume sync on standby first
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                standby_vs_resp = await client.put(
                    f"{address}/api/v1/ha/volume-sync/config",
                    json=standby_vs_body,
                    headers={"Authorization": f"Bearer {standby_token}"},
                )

            if standby_vs_resp.status_code != 200:
                detail = ""
                try:
                    detail = standby_vs_resp.json().get("detail", standby_vs_resp.text)
                except Exception:
                    detail = standby_vs_resp.text
                steps.append(WizardSetupStepResult(
                    step=step_name,
                    status="failed",
                    error=f"Failed to configure volume sync on standby — HTTP {standby_vs_resp.status_code}: {detail}",
                ))
                failed = True
                await log_ha_event(
                    event_type="volume_sync_error",
                    severity="error",
                    message=f"Wizard setup: failed to configure volume sync on standby — HTTP {standby_vs_resp.status_code}",
                    details={"error": detail},
                )
            else:
                # Configure volume sync on primary locally.
                # Use a fresh session because HAService.save_config() committed
                # the earlier transaction, leaving `db` in a closed state.
                from app.modules.ha.volume_sync_schemas import VolumeSyncConfigRequest
                from app.modules.ha.volume_sync_service import VolumeSyncService
                from app.core.database import async_session_factory

                vs_svc = VolumeSyncService()
                vs_request = VolumeSyncConfigRequest(**primary_vs_body)
                async with async_session_factory() as vs_session:
                    async with vs_session.begin():
                        await vs_svc.save_config(vs_session, vs_request)

                steps.append(WizardSetupStepResult(
                    step=step_name,
                    status="completed",
                    message="Volume sync configured on both nodes",
                ))
                await log_ha_event(
                    event_type="config_change",
                    severity="info",
                    message="Wizard setup: volume sync configured on both nodes",
                    details={
                        "primary_ssh_target": standby_lan_ip,
                        "standby_ssh_target": primary_lan_ip,
                        "ssh_port": 2222,
                    },
                )
        except Exception as exc:
            logger.error("Wizard setup step 5 (configure_volume_sync) failed: %s", exc)
            steps.append(WizardSetupStepResult(
                step=step_name,
                status="failed",
                error=str(exc),
            ))
            failed = True
            await log_ha_event(
                event_type="volume_sync_error",
                severity="error",
                message=f"Wizard setup: failed to configure volume sync — {exc}",
            )

    # =====================================================================
    # Mark remaining steps as skipped if we failed early
    # =====================================================================
    completed_step_names = {s.step for s in steps}
    for sn in step_names:
        if sn not in completed_step_names:
            steps.append(WizardSetupStepResult(
                step=sn,
                status="skipped",
                message="Skipped due to previous step failure",
            ))

    # --- Final event log ---
    if not failed:
        await log_ha_event(
            event_type="config_change",
            severity="info",
            message="Wizard setup completed successfully — HA replication is active",
            details={"steps_completed": len([s for s in steps if s.status == "completed"])},
        )
    else:
        await log_ha_event(
            event_type="config_change",
            severity="error",
            message="Wizard setup failed — see step log for details",
            details={
                "steps_completed": len([s for s in steps if s.status == "completed"]),
                "steps_failed": len([s for s in steps if s.status == "failed"]),
                "steps_skipped": len([s for s in steps if s.status == "skipped"]),
            },
        )

    return WizardSetupResponse(
        success=not failed,
        steps=steps,
    )


# ---------------------------------------------------------------------------
# HA Event Log — query endpoint
# ---------------------------------------------------------------------------


@admin_router.get(
    "/events",
    response_model=HAEventListResponse,
    summary="List HA events from the persistent event log",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def list_ha_events(
    limit: int = 50,
    severity: str | None = None,
    event_type: str | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Return recent HA events from ``ha_event_log``, ordered by timestamp DESC.

    Supports optional filtering by severity and event_type.
    Returns the matching events plus a total count (without limit) for
    pagination support.

    **Validates: Requirements 34.6, 34.7**
    """
    from sqlalchemy import select, func as sa_func
    from app.modules.ha.models import HAEventLog

    # --- Build base filter conditions ---
    conditions = []
    if severity:
        conditions.append(HAEventLog.severity == severity)
    if event_type:
        conditions.append(HAEventLog.event_type == event_type)

    # --- Total count (without limit) ---
    count_stmt = select(sa_func.count()).select_from(HAEventLog)
    for cond in conditions:
        count_stmt = count_stmt.where(cond)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # --- Fetch events with limit ---
    query = (
        select(HAEventLog)
        .order_by(HAEventLog.timestamp.desc())
        .limit(limit)
    )
    for cond in conditions:
        query = query.where(cond)

    result = await db.execute(query)
    rows = result.scalars().all()

    events = [
        HAEventResponse(
            id=str(row.id),
            timestamp=row.timestamp.isoformat() if row.timestamp else "",
            event_type=row.event_type,
            severity=row.severity,
            message=row.message,
            details=row.details,
            node_name=row.node_name,
        )
        for row in rows
    ]

    return HAEventListResponse(events=events, total=total)


# ---------------------------------------------------------------------------
# Combined router — merges public + admin under a single export
# ---------------------------------------------------------------------------

# Include volume sync sub-router in admin_router so it inherits global_admin
from app.modules.ha.volume_sync_router import router as volume_sync_router

admin_router.include_router(volume_sync_router)

router = APIRouter()
router.include_router(public_router)
router.include_router(admin_router)

# ---------------------------------------------------------------------------
# Replication Slots Management
# ---------------------------------------------------------------------------


@admin_router.get(
    "/replication/slots",
    summary="List all replication slots on this node",
    dependencies=[require_role("global_admin")],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def list_replication_slots(db: AsyncSession = Depends(get_db_session)):
    """List all PostgreSQL replication slots on this node.

    Shows slot name, type, active status, retained WAL size, and idle time.
    Useful for identifying orphaned slots that need cleanup.
    """
    slots = await ReplicationManager.list_replication_slots(db)
    return {"slots": slots}


@admin_router.delete(
    "/replication/slots/{slot_name}",
    summary="Drop a replication slot",
    dependencies=[require_role("global_admin")],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        400: {"description": "Slot is active or invalid name"},
        404: {"description": "Slot not found"},
    },
)
async def drop_replication_slot(slot_name: str, db: AsyncSession = Depends(get_db_session)):
    """Drop an inactive replication slot.

    Only inactive (orphaned) slots can be dropped. Active slots must be
    disconnected first by stopping the subscription on the standby.
    """
    try:
        result = await ReplicationManager.drop_replication_slot(db, slot_name)
        if result["status"] == "not_found":
            return JSONResponse(status_code=404, content={"detail": result["message"]})
        if result["status"] == "error":
            return JSONResponse(status_code=400, content={"detail": result["message"]})
        return result
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
