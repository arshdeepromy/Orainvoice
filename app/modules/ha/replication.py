"""PostgreSQL logical replication manager for HA.

Manages publication/subscription lifecycle, replication status monitoring,
and re-sync operations using raw SQL executed via SQLAlchemy async sessions.

PostgreSQL publication/subscription DDL commands cannot run inside a
transaction block, so each method commits any open transaction first and
then obtains a raw DBAPI connection in *autocommit* mode.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 6.1, 6.2
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ha.schemas import ReplicationStatusResponse

logger = logging.getLogger(__name__)


class ReplicationManager:
    """Manage PostgreSQL logical replication between HA nodes."""

    PUBLICATION_NAME = "orainvoice_ha_pub"
    SUBSCRIPTION_NAME = "orainvoice_ha_sub"

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_raw_conn():
        """Open a short-lived raw asyncpg connection using the app DSN.

        Disables statement_timeout so long-running replication DDL
        (CREATE PUBLICATION, CREATE SUBSCRIPTION) won't be killed by
        the server-level timeout configured in production postgres.
        """
        import asyncpg
        from app.config import settings

        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        conn = await asyncpg.connect(dsn)
        await conn.execute("SET statement_timeout = 0")
        await conn.execute("SET idle_in_transaction_session_timeout = 0")
        return conn

    @staticmethod
    async def _exec_autocommit(db: AsyncSession, sql: str) -> None:
        """Execute a DDL statement that cannot run inside a transaction.

        PostgreSQL publication/subscription DDL (CREATE PUBLICATION,
        CREATE SUBSCRIPTION, etc.) cannot run inside a transaction block.

        Uses a short-lived raw asyncpg connection in autocommit mode.
        The ``db`` parameter is kept for API compatibility but is not used.

        Disables statement_timeout so long-running DDL won't be killed
        by the server-level timeout configured in production postgres.
        """
        import asyncpg
        from app.config import settings

        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        conn: asyncpg.Connection = await asyncpg.connect(dsn)
        try:
            await conn.execute("SET statement_timeout = 0")
            await conn.execute("SET idle_in_transaction_session_timeout = 0")
            await conn.execute(sql)
        finally:
            await conn.close()



    # ------------------------------------------------------------------
    # Publication (primary node)
    # ------------------------------------------------------------------

    @staticmethod
    async def init_primary(db: AsyncSession) -> dict:
        """Create a publication for all tables on the primary node, excluding ha_config.

        Uses raw asyncpg connections for all queries to avoid SQLAlchemy
        session timeout issues during long-running DDL operations.

        Returns a dict with the operation result.
        """
        try:
            conn = await ReplicationManager._get_raw_conn()
            try:
                # Check if publication already exists
                existing = await conn.fetchval(
                    "SELECT pubname FROM pg_publication WHERE pubname = $1",
                    ReplicationManager.PUBLICATION_NAME,
                )

                if existing:
                    # Check if ha_config is in the publication (legacy fix)
                    ha_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM pg_publication_tables "
                        "WHERE pubname = $1 AND tablename = 'ha_config'",
                        ReplicationManager.PUBLICATION_NAME,
                    )
                    if not ha_count:
                        logger.info("Publication '%s' already exists (ha_config excluded)", ReplicationManager.PUBLICATION_NAME)
                        return {
                            "status": "ok",
                            "publication": ReplicationManager.PUBLICATION_NAME,
                            "message": "Publication already exists",
                        }
                    # ha_config is in the publication — need to recreate
                    logger.info("Recreating publication to exclude ha_config")
                    await conn.execute(
                        f"DROP PUBLICATION {ReplicationManager.PUBLICATION_NAME}",
                    )

                # Get all public tables except ha_config
                tbl_list = await conn.fetchval(
                    "SELECT string_agg(tablename, ', ') "
                    "FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename != 'ha_config'",
                )
                if not tbl_list:
                    raise RuntimeError("No tables found in public schema")

                await conn.execute(
                    f"CREATE PUBLICATION {ReplicationManager.PUBLICATION_NAME} FOR TABLE {tbl_list}",
                )
            finally:
                await conn.close()

            logger.info("Publication '%s' created (ha_config excluded)", ReplicationManager.PUBLICATION_NAME)
            return {"status": "ok", "publication": ReplicationManager.PUBLICATION_NAME}
        except RuntimeError:
            raise
        except Exception as exc:
            error_msg = str(exc)
            logger.error("Failed to create publication: %s", error_msg)
            raise RuntimeError(f"Failed to create publication: {error_msg}") from exc

    @staticmethod
    async def drop_publication(db: AsyncSession) -> None:
        """Drop the publication on the primary node.

        Executes::

            DROP PUBLICATION IF EXISTS orainvoice_ha_pub
        """
        try:
            await ReplicationManager._exec_autocommit(
                db,
                f"DROP PUBLICATION IF EXISTS {ReplicationManager.PUBLICATION_NAME}",
            )
            logger.info("Publication '%s' dropped", ReplicationManager.PUBLICATION_NAME)
        except Exception as exc:
            logger.error("Failed to drop publication: %s", exc)
            raise RuntimeError(f"Failed to drop publication: {exc}") from exc

    # ------------------------------------------------------------------
    # Subscription (standby node)
    # ------------------------------------------------------------------

    @staticmethod
    async def init_standby(db: AsyncSession, primary_conn_str: str) -> dict:
        """Create a subscription on the standby node to replicate from the primary.

        Executes::

            CREATE SUBSCRIPTION orainvoice_ha_sub
              CONNECTION '<primary_conn_str>'
              PUBLICATION orainvoice_ha_pub

        The initial ``copy_data=true`` (default) triggers a full data sync.

        Returns a dict with the operation result.
        """
        try:
            sql = (
                f"CREATE SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} "
                f"CONNECTION '{primary_conn_str}' "
                f"PUBLICATION {ReplicationManager.PUBLICATION_NAME}"
            )
            await ReplicationManager._exec_autocommit(db, sql)
            logger.info(
                "Subscription '%s' created — initial sync will begin",
                ReplicationManager.SUBSCRIPTION_NAME,
            )
            return {
                "status": "ok",
                "subscription": ReplicationManager.SUBSCRIPTION_NAME,
                "message": "Subscription created, initial data sync in progress",
            }
        except Exception as exc:
            error_msg = str(exc)
            if "already exists" in error_msg.lower():
                logger.info(
                    "Subscription '%s' already exists",
                    ReplicationManager.SUBSCRIPTION_NAME,
                )
                return {
                    "status": "ok",
                    "subscription": ReplicationManager.SUBSCRIPTION_NAME,
                    "message": "Subscription already exists",
                }
            logger.error("Failed to create subscription: %s", error_msg)
            raise RuntimeError(f"Failed to create subscription: {error_msg}") from exc

    @staticmethod
    async def drop_subscription(db: AsyncSession) -> None:
        """Drop the subscription on the standby node.

        Disables the subscription first (required before dropping), then drops it.
        """
        try:
            # Disable first to avoid errors if the slot is still active
            try:
                await ReplicationManager._exec_autocommit(
                    db,
                    f"ALTER SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} DISABLE",
                )
            except Exception:
                pass  # May already be disabled or not exist

            try:
                await ReplicationManager._exec_autocommit(
                    db,
                    f"ALTER SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} SET (slot_name = NONE)",
                )
            except Exception:
                pass  # May not exist

            await ReplicationManager._exec_autocommit(
                db,
                f"DROP SUBSCRIPTION IF EXISTS {ReplicationManager.SUBSCRIPTION_NAME}",
            )
            logger.info("Subscription '%s' dropped", ReplicationManager.SUBSCRIPTION_NAME)
        except Exception as exc:
            logger.error("Failed to drop subscription: %s", exc)
            raise RuntimeError(f"Failed to drop subscription: {exc}") from exc


    # ------------------------------------------------------------------
    # Subscription control
    # ------------------------------------------------------------------

    @staticmethod
    async def stop_subscription(db: AsyncSession) -> None:
        """Disable the replication subscription.

        Executes::

            ALTER SUBSCRIPTION orainvoice_ha_sub DISABLE
        """
        try:
            await ReplicationManager._exec_autocommit(
                db,
                f"ALTER SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} DISABLE",
            )
            logger.info("Subscription '%s' disabled", ReplicationManager.SUBSCRIPTION_NAME)
        except Exception as exc:
            logger.error("Failed to disable subscription: %s", exc)
            raise RuntimeError(f"Failed to disable subscription: {exc}") from exc

    @staticmethod
    async def resume_subscription(db: AsyncSession, primary_conn_str: str) -> None:
        """Re-enable the replication subscription, or re-create it if the slot is invalidated.

        First attempts ``ALTER SUBSCRIPTION ... ENABLE``. If that fails
        (e.g. because the replication slot was invalidated while the node
        was down), drops and re-creates the subscription.
        """
        try:
            await ReplicationManager._exec_autocommit(
                db,
                f"ALTER SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} ENABLE",
            )
            logger.info("Subscription '%s' re-enabled", ReplicationManager.SUBSCRIPTION_NAME)
        except Exception as enable_exc:
            logger.warning(
                "Could not re-enable subscription (slot may be invalidated): %s — "
                "dropping and re-creating",
                enable_exc,
            )
            # Drop and re-create
            await ReplicationManager.drop_subscription(db)
            sql = (
                f"CREATE SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} "
                f"CONNECTION '{primary_conn_str}' "
                f"PUBLICATION {ReplicationManager.PUBLICATION_NAME}"
            )
            await ReplicationManager._exec_autocommit(db, sql)
            logger.info(
                "Subscription '%s' re-created after slot invalidation",
                ReplicationManager.SUBSCRIPTION_NAME,
            )

    @staticmethod
    async def trigger_resync(db: AsyncSession, primary_conn_str: str) -> None:
        """Drop and re-create the subscription with ``copy_data=true`` for a full re-sync.

        This is the nuclear option when replication has become inconsistent
        and a differential catch-up is not possible.
        """
        logger.info("Triggering full re-sync — dropping and re-creating subscription")
        await ReplicationManager.drop_subscription(db)
        sql = (
            f"CREATE SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} "
            f"CONNECTION '{primary_conn_str}' "
            f"PUBLICATION {ReplicationManager.PUBLICATION_NAME} "
            f"WITH (copy_data = true)"
        )
        await ReplicationManager._exec_autocommit(db, sql)
        logger.info(
            "Subscription '%s' re-created with copy_data=true — full re-sync in progress",
            ReplicationManager.SUBSCRIPTION_NAME,
        )


    # ------------------------------------------------------------------
    # Status & monitoring
    # ------------------------------------------------------------------

    @staticmethod
    async def get_replication_status(db: AsyncSession) -> ReplicationStatusResponse:
        """Query PostgreSQL catalog tables for replication health.

        Checks ``pg_stat_subscription`` for subscription info and
        ``pg_publication_tables`` for the number of published tables.

        Returns a ``ReplicationStatusResponse``.
        """
        pub_name: str | None = None
        sub_name: str | None = None
        sub_status: str | None = None
        lag_seconds: float | None = None
        last_replicated: str | None = None
        tables_published: int = 0
        is_healthy: bool = False

        try:
            # Check publication (only exists on primary)
            result = await db.execute(
                text(
                    "SELECT pubname FROM pg_publication WHERE pubname = :name"
                ),
                {"name": ReplicationManager.PUBLICATION_NAME},
            )
            row = result.fetchone()
            if row:
                pub_name = row[0]

                # Count published tables
                count_result = await db.execute(
                    text(
                        "SELECT COUNT(*) FROM pg_publication_tables WHERE pubname = :name"
                    ),
                    {"name": ReplicationManager.PUBLICATION_NAME},
                )
                tables_published = count_result.scalar() or 0
        except Exception as exc:
            logger.debug("Could not query publication info: %s", exc)

        try:
            # Check subscription (only exists on standby)
            result = await db.execute(
                text(
                    "SELECT subname, subenabled "
                    "FROM pg_subscription WHERE subname = :name"
                ),
                {"name": ReplicationManager.SUBSCRIPTION_NAME},
            )
            row = result.fetchone()
            if row:
                sub_name = row[0]
                sub_status = "active" if row[1] else "disabled"
        except Exception as exc:
            logger.debug("Could not query subscription info: %s", exc)

        try:
            # Get lag and last message time from pg_stat_subscription
            result = await db.execute(
                text(
                    "SELECT "
                    "  EXTRACT(EPOCH FROM (now() - last_msg_send_time)) AS lag_seconds, "
                    "  last_msg_send_time "
                    "FROM pg_stat_subscription "
                    "WHERE subname = :name"
                ),
                {"name": ReplicationManager.SUBSCRIPTION_NAME},
            )
            row = result.fetchone()
            if row:
                lag_seconds = float(row[0]) if row[0] is not None else None
                last_replicated = row[1].isoformat() if row[1] is not None else None
        except Exception as exc:
            logger.debug("Could not query replication lag: %s", exc)

        # Determine overall health
        if pub_name or sub_name:
            if sub_status == "active" and (lag_seconds is None or lag_seconds < 60):
                is_healthy = True
            elif pub_name and not sub_name:
                # Primary with publication but no subscription — healthy from primary's perspective
                is_healthy = True

        return ReplicationStatusResponse(
            publication_name=pub_name,
            subscription_name=sub_name,
            subscription_status=sub_status,
            replication_lag_seconds=lag_seconds,
            last_replicated_at=last_replicated,
            tables_published=tables_published,
            is_healthy=is_healthy,
        )

    @staticmethod
    async def get_replication_lag(db: AsyncSession) -> float | None:
        """Query the current replication lag in seconds from ``pg_stat_subscription``.

        Returns ``None`` if no subscription exists or lag cannot be determined.
        """
        try:
            result = await db.execute(
                text(
                    "SELECT EXTRACT(EPOCH FROM (now() - last_msg_send_time)) "
                    "FROM pg_stat_subscription "
                    "WHERE subname = :name"
                ),
                {"name": ReplicationManager.SUBSCRIPTION_NAME},
            )
            row = result.fetchone()
            if row and row[0] is not None:
                return float(row[0])
        except Exception as exc:
            logger.debug("Could not query replication lag: %s", exc)
        return None
