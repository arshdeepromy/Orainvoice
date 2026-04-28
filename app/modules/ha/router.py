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
    HeartbeatHistoryEntry,
    HeartbeatResponse,
    PeerDBTestRequest,
    PromoteRequest,
    PublicStatusResponse,
    ReplicationStatusResponse,
)
from app.modules.ha.service import HAService, get_heartbeat_service, get_peer_db_url
from app.modules.ha.utils import validate_confirmation_text

logger = logging.getLogger(__name__)

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
