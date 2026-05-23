"""SQLAlchemy async engine, session factory, and RLS session setup.

Provides:
- ``engine``: the global async engine (created lazily via ``get_engine``).
- ``get_db_session``: FastAPI dependency that yields an ``AsyncSession``
  with ``app.current_org_id`` set for PostgreSQL RLS policies.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.config import settings
from app.core.security import get_database_ssl_config

# Context variable holding the current org_id for the request.
# Set by TenantMiddleware; read by the session factory.
_current_org_id: ContextVar[str | None] = ContextVar("_current_org_id", default=None)

# Context variable holding the current fleet_account_id for fleet portal
# requests. Set by the require_fleet_portal_session FastAPI dependency
# (in app/modules/fleet_portal/dependencies.py); read by callers that need
# to set the matching Postgres GUC for RLS defence-in-depth on
# fleet-scoped tables. The standard get_db_session dependency does NOT
# read this — it stays org-only so staff request paths are unchanged.
_current_fleet_account_id: ContextVar[str | None] = ContextVar(
    "_current_fleet_account_id", default=None
)

# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------

# Enforce SSL for PostgreSQL connections in production/staging (Req 52.1, 52.2)
_ssl_config = get_database_ssl_config(settings.environment)
import os as _os

_pool_size = int(_os.environ.get("DB_POOL_SIZE", "30"))
_max_overflow = int(_os.environ.get("DB_MAX_OVERFLOW", "15"))

_engine_kwargs: dict = {
    "echo": False,            # NEVER echo SQL — massive perf hit
    "pool_size": _pool_size,  # default 30; override via DB_POOL_SIZE env var
    "max_overflow": _max_overflow,  # default 15; override via DB_MAX_OVERFLOW
    "pool_recycle": 1800,     # recycle connections after 30 min
    "pool_pre_ping": True,    # verify connections before checkout
    "pool_timeout": 5,        # fail fast — 5s max wait for a conn
}
if settings.environment in ("production", "staging"):
    _engine_kwargs.update(_ssl_config.to_engine_kwargs())

engine = create_async_engine(
    settings.database_url,
    **_engine_kwargs,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Declarative base for ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Shared declarative base for all SQLAlchemy ORM models."""


# ---------------------------------------------------------------------------
# RLS helper
# ---------------------------------------------------------------------------

async def _set_rls_org_id(session: AsyncSession, org_id: str | None) -> None:
    """Execute ``SET app.current_org_id`` so RLS policies filter correctly.
    Uses PostgreSQL's set_config(name, value, is_local) function which
    is equivalent to SET LOCAL but supports parameterized queries,
    eliminating any SQL injection risk.
    """
    if org_id is not None:
        # Validate that org_id is a real UUID
        import uuid as _uuid
        try:
            validated = str(_uuid.UUID(str(org_id)))
        except (ValueError, AttributeError):
            validated = ""
        if validated:
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": validated},
            )
        else:
            await session.execute(text("RESET app.current_org_id"))
    else:
        # Reset so RLS policies deny all tenant rows
        # (global admin requests should not see tenant data).
        await session.execute(text("RESET app.current_org_id"))


async def _set_rls_fleet_account_id(
    session: AsyncSession, fleet_account_id: str | None
) -> None:
    """Execute ``SET app.current_fleet_account_id`` so fleet-scoped RLS
    policies on B2B Fleet Portal tables can match the second predicate.

    Mirrors :func:`_set_rls_org_id` exactly: uses ``set_config(name, value,
    is_local=true)`` so the value is bound parametrically (no SQL
    injection risk) and is automatically reset at transaction end.

    This helper is called by ``require_fleet_portal_session`` (the fleet
    portal FastAPI dependency) AFTER it has validated the session and
    looked up the portal account's ``fleet_account_id``. It is NOT called
    by ``get_db_session`` — staff request paths don't use this GUC.
    """
    if fleet_account_id is not None:
        # Validate that fleet_account_id is a real UUID before binding it
        # into set_config — keeps a defence-in-depth check even though
        # set_config() already binds parameters safely.
        import uuid as _uuid
        try:
            validated = str(_uuid.UUID(str(fleet_account_id)))
        except (ValueError, AttributeError):
            validated = ""
        if validated:
            await session.execute(
                text(
                    "SELECT set_config('app.current_fleet_account_id', "
                    ":fid, true)"
                ),
                {"fid": validated},
            )
        else:
            await session.execute(
                text("RESET app.current_fleet_account_id")
            )
    else:
        # Reset so the OR predicate evaluates to NULL → false on every
        # row. Combined with the org_id predicate this means a request
        # with no fleet_account context still cannot read fleet-scoped
        # rows from a different org.
        await session.execute(text("RESET app.current_fleet_account_id"))


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session with RLS org_id set.

    Usage in a FastAPI route::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db_session)):
            ...

    The session automatically sets ``app.current_org_id`` from the
    request-scoped context variable before yielding, and rolls back /
    closes on exit.
    """
    async with async_session_factory() as session:
        async with session.begin():
            org_id = _current_org_id.get()
            await _set_rls_org_id(session, org_id)
            yield session


def set_current_org_id(org_id: str | None) -> None:
    """Store the org_id in the request-scoped context variable.

    Called by TenantMiddleware so that ``get_db_session`` can read it.
    """
    _current_org_id.set(org_id)


def set_current_fleet_account_id(fleet_account_id: str | None) -> None:
    """Store the fleet_account_id in the request-scoped context variable.

    Called by the ``require_fleet_portal_session`` fleet portal
    dependency so subsequent calls within the same request can read it
    (e.g. for re-applying the GUC if the session is rebuilt mid-request).
    The standard ``get_db_session`` dependency does NOT read this —
    fleet portal handlers explicitly set the GUC via
    :func:`_set_rls_fleet_account_id` after acquiring the session.
    """
    _current_fleet_account_id.set(fleet_account_id)
