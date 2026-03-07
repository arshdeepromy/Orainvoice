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

# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------

# Enforce SSL for PostgreSQL connections in production/staging (Req 52.1, 52.2)
_ssl_config = get_database_ssl_config(settings.environment)
_engine_kwargs: dict = {
    "echo": settings.debug,
    "pool_size": 20,          # max connections per worker (Req 43.6)
    "max_overflow": 10,       # overflow connections beyond pool_size
    "pool_recycle": 3600,     # recycle connections after 1 hour
    "pool_pre_ping": True,    # verify connections before checkout
    "pool_timeout": 30,       # wait up to 30s for a connection
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
    """Execute ``SET app.current_org_id`` so RLS policies filter correctly."""
    if org_id is not None:
        await session.execute(
            text("SET LOCAL app.current_org_id = :org_id"),
            {"org_id": str(org_id)},
        )
    else:
        # Reset to empty string so RLS policies deny all tenant rows
        # (global admin requests should not see tenant data).
        await session.execute(text("RESET app.current_org_id"))


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
