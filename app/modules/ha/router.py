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

from app.core.database import get_db_session
from app.core.audit import write_audit_log
from app.modules.auth.rbac import require_role
from app.modules.ha.hmac_utils import compute_hmac
from app.modules.ha.replication import ReplicationManager
from app.modules.ha.schemas import (
    CreateReplicationUserRequest,
    DemoteRequest,
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
    ``HA_HEARTBEAT_SECRET`` so the caller can verify authenticity.
    """
    try:
        config = await HAService.get_config(db)
        if config is None:
            # Not configured — return minimal healthy response
            payload = {
                "node_id": "",
                "node_name": "unconfigured",
                "role": "standalone",
                "status": "healthy",
                "database_status": "connected",
                "replication_lag_seconds": None,
                "sync_status": "not_configured",
                "uptime_seconds": round(time.monotonic() - _start_time, 1),
                "maintenance": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        else:
            # Fetch maintenance mode from DB
            from app.modules.ha.models import HAConfig
            from sqlalchemy import select

            result = await db.execute(select(HAConfig).limit(1))
            cfg_row = result.scalars().first()
            maintenance = cfg_row.maintenance_mode if cfg_row else False
            sync_status = cfg_row.sync_status if cfg_row else "not_configured"

            # Get replication lag if standby
            lag: float | None = None
            if config.role == "standby":
                try:
                    lag = await ReplicationManager.get_replication_lag(db)
                except Exception:
                    pass

            payload = {
                "node_id": config.node_id,
                "node_name": config.node_name,
                "role": config.role,
                "status": "healthy",
                "database_status": "connected",
                "replication_lag_seconds": lag,
                "sync_status": sync_status,
                "uptime_seconds": round(time.monotonic() - _start_time, 1),
                "maintenance": maintenance,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Sign the payload using the canonical JSON form.
        # We compute the HMAC on the exact JSON string, then embed the
        # signature into the response.  The caller strips hmac_signature,
        # re-serialises with the same sort_keys + compact separators, and
        # verifies.
        import json as _json
        import hashlib as _hashlib
        import hmac as _hmac

        secret = os.environ.get("HA_HEARTBEAT_SECRET", "")
        canonical = _json.dumps(payload, sort_keys=True, separators=(",", ":"))
        signature = _hmac.new(
            secret.encode(), canonical.encode(), _hashlib.sha256,
        ).hexdigest()

        # Return the response using the same canonical JSON + signature.
        # We build the final JSON string manually to guarantee byte-level
        # consistency with what the caller will re-compute.
        response_data = _json.loads(canonical)
        response_data["hmac_signature"] = signature

        # Use Response with the exact JSON we control
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
    db: AsyncSession = Depends(get_db_session),
):
    """Initialize PostgreSQL logical replication.

    On a primary node, creates the publication.
    On a standby node, creates the subscription using ``HA_PEER_DB_URL``.
    """
    config = await HAService.get_config(db)
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "HA is not configured. Use PUT /api/v1/ha/configure first."},
        )

    try:
        if config.role == "primary":
            result = await ReplicationManager.init_primary(db)
        elif config.role == "standby":
            peer_db_url = await get_peer_db_url(db)
            if not peer_db_url:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Peer database connection is not configured. Set peer DB settings in HA configuration or set HA_PEER_DB_URL environment variable."},
                )
            result = await ReplicationManager.init_standby(db, peer_db_url)
        else:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Cannot init replication in '{config.role}' role. Must be 'primary' or 'standby'."},
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
    db: AsyncSession = Depends(get_db_session),
):
    """Drop and re-create the subscription with ``copy_data=true`` for a full re-sync."""
    peer_db_url = await get_peer_db_url(db)
    if not peer_db_url:
        return JSONResponse(
            status_code=400,
            content={"detail": "Peer database connection is not configured. Set peer DB settings in HA configuration or set HA_PEER_DB_URL environment variable."},
        )

    try:
        await ReplicationManager.trigger_resync(db, peer_db_url)
        return {"status": "ok", "message": "Full re-sync initiated"}
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        logger.error("Replication resync error: %s", exc)
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

    dsn = f"postgresql://{payload.user}:{payload.password}@{payload.host}:{payload.port}/{payload.dbname}"

    # Map sslmode to asyncpg ssl parameter
    ssl_param: object = False
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
        conn = await asyncpg.connect(dsn, timeout=10, ssl=ssl_param)
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
async def local_db_info():
    """Return the host's LAN IP and the postgres port visible to external peers.

    The host LAN IP is read from ``HA_LOCAL_LAN_IP`` env var.  If not
    set, falls back to ``host.docker.internal`` (works for Docker Desktop
    on Windows/Mac where both stacks run on the same host).  On Linux
    production (no Docker Desktop), the UDP socket trick is used.
    """
    lan_ip = _detect_host_lan_ip()

    # Exposed postgres port — configurable via env var since the host
    # port mapping is defined in docker-compose, not visible from inside
    # the container.  Defaults to 5432.
    pg_port = int(os.environ.get("HA_LOCAL_PG_PORT", "5432"))

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
                # DDL doesn't support $1 params for PASSWORD — use quote_literal via PG
                await conn.execute(
                    f"ALTER USER {payload.username} WITH REPLICATION LOGIN PASSWORD '{payload.password.replace(chr(39), chr(39)+chr(39))}'"
                )
                msg = f"User '{payload.username}' already exists — password updated"
            else:
                await conn.execute(
                    f"CREATE USER {payload.username} WITH REPLICATION LOGIN PASSWORD '{payload.password.replace(chr(39), chr(39)+chr(39))}'"
                )
                msg = f"User '{payload.username}' created with REPLICATION privilege"

            # Grant SELECT on all tables
            await conn.execute(f"GRANT USAGE ON SCHEMA public TO {payload.username}")
            await conn.execute(
                f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {payload.username}"
            )
            await conn.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {payload.username}"
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
            await db.commit()

            # Build connection string for the peer node
            lan_ip = _detect_host_lan_ip()

            pg_port = int(os.environ.get("HA_LOCAL_PG_PORT", "5432"))
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


# ---------------------------------------------------------------------------
# Combined router — merges public + admin under a single export
# ---------------------------------------------------------------------------

router = APIRouter()
router.include_router(public_router)
router.include_router(admin_router)
