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


def filter_tables_for_truncation(all_table_names: list[str]) -> list[str]:
    """Return the subset of table names that should be truncated.

    Excludes ``ha_config`` — it stores per-node HA state and must survive
    truncation so the node can still identify itself after a data wipe.

    Note: ``dead_letter_queue`` is intentionally *not* excluded here.
    It is excluded from the *publication* (so it is not replicated) but
    it should still be truncated during standby init / re-sync so the
    standby starts clean.  Only ``ha_config`` needs to survive truncation.

    This is a pure function extracted for testability.
    """
    return [t for t in all_table_names if t != "ha_config"]


class ReplicationManager:
    """Manage PostgreSQL logical replication between HA nodes."""

    PUBLICATION_NAME = "orainvoice_ha_pub"
    SUBSCRIPTION_NAME = "orainvoice_ha_sub"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _escape_conn_str(conn_str: str) -> str:
        """Escape single quotes in a connection string for SQL interpolation."""
        return conn_str.replace("'", "''")

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
    # Truncation (standby initialization)
    # ------------------------------------------------------------------

    @staticmethod
    async def truncate_all_tables() -> dict:
        """Truncate all public tables except ha_config.

        Uses a raw asyncpg connection with a single transaction.
        Returns dict with status and count of truncated tables.

        Validates: Requirement 2.1, 2.2, 2.3
        """
        conn = await ReplicationManager._get_raw_conn()
        try:
            # Query all public schema tables
            rows = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            all_names = [r["tablename"] for r in rows]
            to_truncate = filter_tables_for_truncation(all_names)

            if not to_truncate:
                logger.info("No tables to truncate (only ha_config found)")
                return {"status": "ok", "tables_truncated": 0}

            table_list = ", ".join(to_truncate)
            async with conn.transaction():
                await conn.execute(f"TRUNCATE {table_list} CASCADE")

            logger.info(
                "Truncated %d tables before standby init (ha_config preserved)",
                len(to_truncate),
            )
            return {"status": "ok", "tables_truncated": len(to_truncate)}
        except Exception as exc:
            error_msg = str(exc)
            logger.error("Failed to truncate tables: %s", error_msg)
            raise RuntimeError(f"Failed to truncate tables: {error_msg}") from exc
        finally:
            await conn.close()

    # ------------------------------------------------------------------
    # Publication (primary node)
    # ------------------------------------------------------------------

    @staticmethod
    async def init_primary(db: AsyncSession) -> dict:
        """Create a publication for all tables on the primary node.

        Excludes ``ha_config`` (per-node HA state), ``dead_letter_queue``
        (node-local failed-task queue that should not be replicated), and
        ``ha_event_log`` (per-node event history).

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
                    # Check if excluded tables leaked into the publication (legacy fix)
                    excluded_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM pg_publication_tables "
                        "WHERE pubname = $1 AND tablename IN ('ha_config', 'dead_letter_queue', 'ha_event_log')",
                        ReplicationManager.PUBLICATION_NAME,
                    )
                    if not excluded_count:
                        logger.info("Publication '%s' already exists (ha_config, dead_letter_queue, ha_event_log excluded)", ReplicationManager.PUBLICATION_NAME)
                        return {
                            "status": "ok",
                            "publication": ReplicationManager.PUBLICATION_NAME,
                            "message": "Publication already exists",
                        }
                    # Excluded table(s) found in the publication — need to recreate
                    logger.info("Recreating publication to exclude ha_config, dead_letter_queue, and ha_event_log")
                    await conn.execute(
                        f"DROP PUBLICATION {ReplicationManager.PUBLICATION_NAME}",
                    )

                # Get all public tables except ha_config, dead_letter_queue, and ha_event_log.
                # dead_letter_queue is excluded so that after failover the new
                # primary starts with an empty dead-letter table, preventing
                # re-processing of partially-executed jobs from the old primary.
                # ha_event_log is excluded because it stores per-node event
                # history that should not be replicated between nodes.
                tbl_list = await conn.fetchval(
                    "SELECT string_agg(tablename, ', ') "
                    "FROM pg_tables "
                    "WHERE schemaname = 'public' "
                    "AND tablename NOT IN ('ha_config', 'dead_letter_queue', 'ha_event_log')",
                )
                if not tbl_list:
                    raise RuntimeError("No tables found in public schema")

                await conn.execute(
                    f"CREATE PUBLICATION {ReplicationManager.PUBLICATION_NAME} FOR TABLE {tbl_list}",
                )
            finally:
                await conn.close()

            logger.info("Publication '%s' created (ha_config, dead_letter_queue, ha_event_log excluded)", ReplicationManager.PUBLICATION_NAME)
            return {"status": "ok", "publication": ReplicationManager.PUBLICATION_NAME}
        except RuntimeError:
            raise
        except Exception as exc:
            error_msg = str(exc)
            logger.error("Failed to create publication: %s", error_msg)
            raise RuntimeError(f"Failed to create publication: {error_msg}") from exc

    @staticmethod
    async def sync_sequences_post_promotion() -> dict:
        """Advance all sequences to be at least max(existing_id) + 1.

        Safety net for post-promotion: ensures nextval() returns a value
        higher than any existing row, preventing duplicate key violations
        even if sequence replication had a gap.

        Validates: BUG-HA-01 fix (Phase 2)
        """
        conn = await ReplicationManager._get_raw_conn()
        try:
            rows = await conn.fetch(
                """
                SELECT s.relname AS seq_name,
                       t.relname AS table_name,
                       a.attname AS col_name
                FROM pg_class s
                JOIN pg_depend d ON d.objid = s.oid
                JOIN pg_class t ON t.oid = d.refobjid
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
                WHERE s.relkind = 'S' AND d.deptype = 'a'
                AND t.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
                """
            )
            synced = 0
            for row in rows:
                try:
                    max_val = await conn.fetchval(
                        f"SELECT COALESCE(MAX({row['col_name']}), 0) FROM {row['table_name']}"
                    )
                    await conn.execute(
                        f"SELECT setval('{row['seq_name']}', GREATEST($1 + 1, 1), false)",
                        max_val,
                    )
                    synced += 1
                except Exception as exc:
                    logger.warning("Could not sync sequence %s: %s", row["seq_name"], exc)
            logger.info("Post-promotion sequence sync: %d sequences advanced", synced)
            return {"status": "ok", "sequences_synced": synced}
        finally:
            await conn.close()

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
    async def init_standby(db: AsyncSession, primary_conn_str: str, truncate_first: bool = False) -> dict:
        """Create a subscription on the standby node to replicate from the primary.

        This method is designed to be **idempotent and self-healing**:

        1. If a local subscription already exists, returns success immediately.
        2. If an orphaned replication slot exists on the primary (from a
           previous failed attempt), it is cleaned up automatically before
           creating the subscription.
        3. After creating the subscription, verifies it actually exists in
           ``pg_subscription`` — never returns success without confirmation.

        When ``truncate_first`` is True, truncates all tables except ha_config
        before creating the subscription to avoid duplicate key conflicts
        during the initial data sync.

        Returns a dict with the operation result.
        """
        # --- Truncate tables before subscription if requested ---
        if truncate_first:
            truncate_result = await ReplicationManager.truncate_all_tables()
            logger.info(
                "Pre-subscription truncation complete: %d tables truncated",
                truncate_result.get("tables_truncated", 0),
            )

        # --- Check if subscription already exists locally ---
        try:
            conn = await ReplicationManager._get_raw_conn()
            try:
                existing = await conn.fetchval(
                    "SELECT subname FROM pg_subscription WHERE subname = $1",
                    ReplicationManager.SUBSCRIPTION_NAME,
                )
            finally:
                await conn.close()

            if existing:
                logger.info(
                    "Subscription '%s' already exists — skipping creation",
                    ReplicationManager.SUBSCRIPTION_NAME,
                )
                return {
                    "status": "ok",
                    "subscription": ReplicationManager.SUBSCRIPTION_NAME,
                    "message": "Subscription already exists",
                }
        except Exception as exc:
            logger.warning("Could not check for existing subscription: %s", exc)
            # Continue — the CREATE will fail if it exists, which we handle below

        # --- Proactively clean up orphaned replication slot on primary ---
        # This prevents the most common failure mode: a previous failed
        # subscription attempt left an orphaned slot on the primary.
        try:
            await ReplicationManager._cleanup_orphaned_slot_on_peer(primary_conn_str)
        except Exception as exc:
            logger.warning(
                "Pre-create orphaned slot cleanup failed (non-fatal): %s", exc
            )

        # --- Create the subscription ---
        async def _try_create() -> dict:
            escaped = ReplicationManager._escape_conn_str(primary_conn_str)
            sql = (
                f"CREATE SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} "
                f"CONNECTION '{escaped}' "
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

        try:
            result = await _try_create()
        except Exception as exc:
            error_msg = str(exc)

            # Orphaned replication slot on primary — cleanup and retry
            if "replication slot" in error_msg.lower() and "already exists" in error_msg.lower():
                logger.warning(
                    "Orphaned replication slot detected on primary — attempting cleanup and retry"
                )
                cleaned = await ReplicationManager._cleanup_orphaned_slot_on_peer(
                    primary_conn_str
                )
                if cleaned:
                    try:
                        result = await _try_create()
                    except Exception as retry_exc:
                        logger.error("Retry after slot cleanup failed: %s", retry_exc)
                        raise RuntimeError(
                            f"Failed to create subscription after cleaning up orphaned slot: {retry_exc}"
                        ) from retry_exc
                else:
                    raise RuntimeError(
                        "An orphaned replication slot exists on the primary but could not be "
                        "cleaned up automatically. Go to the primary node's HA page → "
                        "Replication Slots section and drop the inactive slot manually, "
                        "then retry Initialize Replication."
                    ) from exc

            # Subscription already exists locally (race condition or concurrent call)
            elif "already exists" in error_msg.lower():
                logger.info(
                    "Subscription '%s' already exists (concurrent creation)",
                    ReplicationManager.SUBSCRIPTION_NAME,
                )
                return {
                    "status": "ok",
                    "subscription": ReplicationManager.SUBSCRIPTION_NAME,
                    "message": "Subscription already exists",
                }
            else:
                logger.error("Failed to create subscription: %s", error_msg)
                raise RuntimeError(f"Failed to create subscription: {error_msg}") from exc

        # --- Verify the subscription actually exists ---
        try:
            conn = await ReplicationManager._get_raw_conn()
            try:
                verified = await conn.fetchval(
                    "SELECT subname FROM pg_subscription WHERE subname = $1",
                    ReplicationManager.SUBSCRIPTION_NAME,
                )
            finally:
                await conn.close()

            if not verified:
                raise RuntimeError(
                    f"Subscription '{ReplicationManager.SUBSCRIPTION_NAME}' was reported as "
                    f"created but does not exist in pg_subscription. This indicates a silent "
                    f"failure — check the PostgreSQL logs on this node."
                )
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("Could not verify subscription existence: %s", exc)
            # Non-fatal — the CREATE succeeded, verification is a safety check

        return result

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
            escaped = ReplicationManager._escape_conn_str(primary_conn_str)
            sql = (
                f"CREATE SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} "
                f"CONNECTION '{escaped}' "
                f"PUBLICATION {ReplicationManager.PUBLICATION_NAME} "
                f"WITH (copy_data = false)"
            )
            await ReplicationManager._exec_autocommit(db, sql)
            logger.info(
                "Subscription '%s' re-created after slot invalidation",
                ReplicationManager.SUBSCRIPTION_NAME,
            )

    @staticmethod
    async def trigger_resync(db: AsyncSession, primary_conn_str: str) -> None:
        """Truncate standby data, then drop and re-create the subscription for a full re-sync.

        This is the nuclear option when replication has become inconsistent
        and a differential catch-up is not possible.

        Truncation runs first so that ``copy_data=true`` does not hit
        duplicate-key conflicts from pre-existing rows.  If truncation
        fails, the error propagates and the subscription is left untouched.
        """
        logger.info("Triggering full re-sync — truncating standby data first")
        # Step 1: truncate all tables (raises RuntimeError on failure, aborts early)
        await ReplicationManager.truncate_all_tables()
        # Step 2: drop existing subscription
        await ReplicationManager.drop_subscription(db)
        # Step 3: clean up orphaned slot left on primary by SET (slot_name = NONE)
        await ReplicationManager._cleanup_orphaned_slot_on_peer(primary_conn_str)
        # Step 4: re-create subscription with full data copy
        escaped = ReplicationManager._escape_conn_str(primary_conn_str)
        sql = (
            f"CREATE SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} "
            f"CONNECTION '{escaped}' "
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
            # Use GREATEST of send and receipt times for more accurate lag
            # (last_msg_send_time updates on keepalives; last_msg_receipt_time
            # updates only when data arrives — GREATEST gives the most recent
            # meaningful activity timestamp)
            result = await db.execute(
                text(
                    "SELECT "
                    "  EXTRACT(EPOCH FROM (now() - GREATEST(last_msg_send_time, last_msg_receipt_time))) AS lag_seconds, "
                    "  GREATEST(last_msg_send_time, last_msg_receipt_time) "
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
            # Use GREATEST of send and receipt times for accurate lag measurement
            # (last_msg_send_time updates on keepalives even without data changes;
            # last_msg_receipt_time only updates when data arrives)
            result = await db.execute(
                text(
                    "SELECT EXTRACT(EPOCH FROM (now() - GREATEST(last_msg_send_time, last_msg_receipt_time))) "
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

    # ------------------------------------------------------------------
    # Replication Slots Management
    # ------------------------------------------------------------------

    @staticmethod
    async def list_replication_slots(db: AsyncSession) -> list[dict]:
        """List all replication slots on this PostgreSQL instance.

        Returns a list of dicts with slot details from ``pg_replication_slots``.
        """
        try:
            result = await db.execute(
                text(
                    "SELECT slot_name, slot_type, active, "
                    "  pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal, "
                    "  active_pid, "
                    "  EXTRACT(EPOCH FROM (now() - COALESCE("
                    "    (SELECT last_msg_send_time FROM pg_stat_subscription WHERE subname = slot_name), "
                    "    (SELECT stat_reset FROM pg_stat_replication_slots WHERE slot_name = rs.slot_name)"
                    "  ))) AS idle_seconds "
                    "FROM pg_replication_slots rs "
                    "ORDER BY slot_name"
                )
            )
            rows = result.fetchall()
            return [
                {
                    "slot_name": r[0],
                    "slot_type": r[1],
                    "active": r[2],
                    "retained_wal": r[3],
                    "active_pid": r[4],
                    "idle_seconds": float(r[5]) if r[5] is not None else None,
                }
                for r in rows
            ]
        except Exception as exc:
            logger.error("Failed to list replication slots: %s", exc)
            return []

    @staticmethod
    async def drop_replication_slot(db: AsyncSession, slot_name: str) -> dict:
        """Drop a replication slot by name.

        Only drops inactive slots. Returns a result dict.
        """
        # Validate slot_name to prevent SQL injection (alphanumeric + underscore only)
        import re
        if not re.match(r"^[a-zA-Z0-9_]+$", slot_name):
            raise ValueError(f"Invalid slot name: {slot_name}")

        try:
            # Check if slot exists and is inactive
            result = await db.execute(
                text("SELECT active FROM pg_replication_slots WHERE slot_name = :name"),
                {"name": slot_name},
            )
            row = result.fetchone()
            if row is None:
                return {"status": "not_found", "message": f"Slot '{slot_name}' does not exist"}
            if row[0]:
                return {"status": "error", "message": f"Slot '{slot_name}' is active — cannot drop while in use"}

            await ReplicationManager._exec_autocommit(
                db,
                f"SELECT pg_drop_replication_slot('{slot_name}')",
            )
            logger.info("Dropped replication slot '%s'", slot_name)
            return {"status": "ok", "message": f"Slot '{slot_name}' dropped successfully"}
        except Exception as exc:
            logger.error("Failed to drop replication slot '%s': %s", slot_name, exc)
            raise RuntimeError(f"Failed to drop slot: {exc}") from exc

    @staticmethod
    async def _cleanup_orphaned_slot_on_peer(primary_conn_str: str) -> bool:
        """Attempt to drop the orphaned replication slot on the primary.

        Connects directly to the primary using the provided connection string
        and drops the slot if it exists and is inactive. Returns True if
        cleanup was performed or slot didn't exist, False on failure.
        """
        import asyncpg

        slot_name = ReplicationManager.SUBSCRIPTION_NAME
        try:
            conn = await asyncpg.connect(primary_conn_str)
            try:
                row = await conn.fetchrow(
                    "SELECT active FROM pg_replication_slots WHERE slot_name = $1",
                    slot_name,
                )
                if row is None:
                    logger.info("No orphaned slot '%s' found on primary", slot_name)
                    return True
                if row["active"]:
                    logger.warning("Slot '%s' is active on primary — cannot clean up", slot_name)
                    return False
                await conn.execute(f"SELECT pg_drop_replication_slot('{slot_name}')")
                logger.info("Cleaned up orphaned slot '%s' on primary", slot_name)
                return True
            finally:
                await conn.close()
        except Exception as exc:
            logger.error("Failed to clean up orphaned slot on primary: %s", exc)
            return False
