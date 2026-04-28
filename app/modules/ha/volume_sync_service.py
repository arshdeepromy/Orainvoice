"""Service layer for rsync-based volume replication from primary to standby.

Manages configuration CRUD, manual/automatic sync execution, status
reporting, and sync history.  The periodic sync runs as a background
asyncio task following the same pattern as ``HeartbeatService``.

Requirements: 4.2, 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8,
              6.1, 6.3, 6.4
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ha.volume_sync_models import VolumeSyncConfig, VolumeSyncHistory
from app.modules.ha.volume_sync_schemas import (
    VolumeSyncConfigRequest,
    VolumeSyncStatusResponse,
)

logger = logging.getLogger(__name__)

# Default rsync subprocess timeout: 30 minutes
_RSYNC_TIMEOUT_SECONDS = 30 * 60

# Directories to sync
_UPLOAD_DIR = "/app/uploads/"
_COMPLIANCE_DIR = "/app/compliance_files/"


class VolumeSyncService:
    """Manages rsync-based volume replication from primary to standby."""

    # Class-level state shared across all instances (singleton-style)
    _task: asyncio.Task | None = None
    _running_sync: bool = False
    _last_sync_time: datetime | None = None
    _last_sync_result: str | None = None

    # ------------------------------------------------------------------
    # Configuration CRUD
    # ------------------------------------------------------------------

    async def get_config(self, db: AsyncSession) -> VolumeSyncConfig | None:
        """Load the singleton config row."""
        result = await db.execute(select(VolumeSyncConfig).limit(1))
        return result.scalars().first()

    async def save_config(
        self, db: AsyncSession, req: VolumeSyncConfigRequest,
    ) -> VolumeSyncConfig:
        """Upsert config. Validates SSH host not empty and interval in range.

        Raises ``ValueError`` if validation fails.
        """
        # Validation
        if not req.standby_ssh_host or not req.standby_ssh_host.strip():
            raise ValueError("standby_ssh_host must not be empty")

        if req.sync_interval_minutes < 1 or req.sync_interval_minutes > 1440:
            raise ValueError("sync_interval_minutes must be between 1 and 1440")

        cfg = await self.get_config(db)

        if cfg is None:
            cfg = VolumeSyncConfig(
                id=uuid.uuid4(),
                standby_ssh_host=req.standby_ssh_host.strip(),
                ssh_port=req.ssh_port,
                ssh_key_path=req.ssh_key_path,
                remote_upload_path=req.remote_upload_path,
                remote_compliance_path=req.remote_compliance_path,
                sync_interval_minutes=req.sync_interval_minutes,
                enabled=req.enabled,
            )
            db.add(cfg)
        else:
            cfg.standby_ssh_host = req.standby_ssh_host.strip()
            cfg.ssh_port = req.ssh_port
            cfg.ssh_key_path = req.ssh_key_path
            cfg.remote_upload_path = req.remote_upload_path
            cfg.remote_compliance_path = req.remote_compliance_path
            cfg.sync_interval_minutes = req.sync_interval_minutes
            cfg.enabled = req.enabled
            cfg.updated_at = datetime.now(timezone.utc)

        await db.flush()
        await db.refresh(cfg)
        return cfg

    # ------------------------------------------------------------------
    # Status & History
    # ------------------------------------------------------------------

    async def get_status(self, db: AsyncSession) -> VolumeSyncStatusResponse:
        """Return current sync status including directory scan results."""
        file_count, total_size = self._scan_directories()

        # Calculate next scheduled sync
        next_sync: datetime | None = None
        if self._last_sync_time is not None:
            cfg = await self.get_config(db)
            if cfg is not None and cfg.enabled:
                interval = timedelta(minutes=cfg.sync_interval_minutes)
                next_sync = self._last_sync_time + interval

        return VolumeSyncStatusResponse(
            last_sync_time=self._last_sync_time,
            last_sync_result=self._last_sync_result,
            next_scheduled_sync=next_sync,
            total_file_count=file_count,
            total_size_bytes=total_size,
            sync_in_progress=self._running_sync,
        )

    async def get_history(
        self, db: AsyncSession, limit: int = 20,
    ) -> list[VolumeSyncHistory]:
        """Return recent history entries ordered by ``started_at`` DESC."""
        result = await db.execute(
            select(VolumeSyncHistory)
            .order_by(VolumeSyncHistory.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Manual trigger
    # ------------------------------------------------------------------

    async def trigger_sync(self, db: AsyncSession) -> VolumeSyncHistory:
        """Execute an immediate manual sync.

        Raises ``HTTPException(409)`` if a sync is already running.
        """
        if self.__class__._running_sync:
            raise HTTPException(
                status_code=409, detail="Sync already in progress",
            )

        cfg = await self.get_config(db)
        if cfg is None:
            raise HTTPException(
                status_code=404,
                detail="Volume sync not configured",
            )

        history = await self._execute_rsync(db, cfg, sync_type="manual")
        return history

    # ------------------------------------------------------------------
    # Rsync command construction (pure function)
    # ------------------------------------------------------------------

    def build_rsync_command(
        self,
        config: VolumeSyncConfig,
        source_path: str,
        dest_path: str,
    ) -> list[str]:
        """Build the rsync command list. Pure function, easily testable."""
        return [
            "rsync",
            "--archive",
            "--compress",
            "--delete",
            "-e",
            f"ssh -i {config.ssh_key_path} -p {config.ssh_port} -o StrictHostKeyChecking=no",
            source_path,
            f"{config.standby_ssh_host}:{dest_path}",
        ]

    # ------------------------------------------------------------------
    # Rsync execution
    # ------------------------------------------------------------------

    async def _execute_rsync(
        self,
        db: AsyncSession,
        config: VolumeSyncConfig,
        sync_type: str,
    ) -> VolumeSyncHistory:
        """Run rsync subprocess for both upload and compliance directories.

        Records a ``VolumeSyncHistory`` entry with timing and status.
        """
        self.__class__._running_sync = True
        started_at = datetime.now(timezone.utc)

        history = VolumeSyncHistory(
            id=uuid.uuid4(),
            started_at=started_at,
            status="running",
            sync_type=sync_type,
        )
        db.add(history)
        await db.flush()
        await db.refresh(history)

        total_files = 0
        total_bytes = 0
        errors: list[str] = []

        try:
            # Sync uploads directory
            upload_cmd = self.build_rsync_command(
                config, _UPLOAD_DIR, config.remote_upload_path,
            )
            files, nbytes, err = await self._run_rsync_subprocess(upload_cmd)
            total_files += files
            total_bytes += nbytes
            if err:
                errors.append(f"uploads: {err}")

            # Sync compliance directory
            compliance_cmd = self.build_rsync_command(
                config, _COMPLIANCE_DIR, config.remote_compliance_path,
            )
            files, nbytes, err = await self._run_rsync_subprocess(compliance_cmd)
            total_files += files
            total_bytes += nbytes
            if err:
                errors.append(f"compliance: {err}")

            # Determine final status
            completed_at = datetime.now(timezone.utc)
            if errors:
                history.status = "failure"
                history.error_message = "; ".join(errors)
            else:
                history.status = "success"

            history.completed_at = completed_at
            history.files_transferred = total_files
            history.bytes_transferred = total_bytes

            await db.flush()
            await db.refresh(history)

            # Update class-level state
            self.__class__._last_sync_time = completed_at
            self.__class__._last_sync_result = history.status

            return history

        except Exception as exc:
            logger.error("Rsync execution failed: %s", exc)
            history.status = "failure"
            history.completed_at = datetime.now(timezone.utc)
            history.error_message = str(exc)

            await db.flush()
            await db.refresh(history)

            self.__class__._last_sync_time = history.completed_at
            self.__class__._last_sync_result = "failure"

            return history

        finally:
            self.__class__._running_sync = False

    async def _run_rsync_subprocess(
        self, cmd: list[str],
    ) -> tuple[int, int, str | None]:
        """Execute a single rsync command via ``asyncio.create_subprocess_exec``.

        Returns ``(files_transferred, bytes_transferred, error_or_none)``.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=_RSYNC_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return 0, 0, "rsync timed out after 30 minutes"

            if process.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                return 0, 0, err_msg or f"rsync exited with code {process.returncode}"

            # Parse rsync output for transfer stats
            files, nbytes = self._parse_rsync_output(
                stdout.decode("utf-8", errors="replace"),
            )
            return files, nbytes, None

        except FileNotFoundError:
            return 0, 0, "rsync binary not found"
        except Exception as exc:
            return 0, 0, str(exc)

    @staticmethod
    def _parse_rsync_output(output: str) -> tuple[int, int]:
        """Best-effort parse of rsync stdout for file/byte counts.

        Returns ``(files_transferred, bytes_transferred)``.
        """
        files = 0
        nbytes = 0
        for line in output.splitlines():
            lower = line.lower().strip()
            # Example: "Number of regular files transferred: 42"
            if "files transferred" in lower:
                parts = lower.split(":")
                if len(parts) >= 2:
                    try:
                        files = int(parts[-1].strip().replace(",", ""))
                    except ValueError:
                        pass
            # Example: "Total transferred file size: 1,234,567 bytes"
            if "total transferred file size" in lower:
                parts = lower.split(":")
                if len(parts) >= 2:
                    num_str = parts[-1].strip().split()[0].replace(",", "")
                    try:
                        nbytes = int(num_str)
                    except ValueError:
                        pass
        return files, nbytes

    # ------------------------------------------------------------------
    # Background periodic sync
    # ------------------------------------------------------------------

    async def start_periodic_sync(self, db: AsyncSession) -> None:
        """Start the background asyncio task for periodic sync.

        Only starts if config exists and is enabled.
        """
        cfg = await self.get_config(db)
        if cfg is None or not cfg.enabled:
            logger.info("Volume sync not configured or disabled — skipping periodic start")
            return

        if self.__class__._task is not None and not self.__class__._task.done():
            logger.warning("Volume sync periodic task already running — ignoring start()")
            return

        # Import here to avoid circular imports; the factory is needed
        # inside the loop to create fresh sessions per cycle.
        from app.core.database import async_session_factory

        self.__class__._task = asyncio.create_task(
            self._periodic_loop(async_session_factory),
        )
        logger.info(
            "Volume sync periodic task started — interval %d min",
            cfg.sync_interval_minutes,
        )

    async def stop_periodic_sync(self) -> None:
        """Stop the background periodic sync task."""
        if self.__class__._task is None or self.__class__._task.done():
            return
        self.__class__._task.cancel()
        try:
            await self.__class__._task
        except asyncio.CancelledError:
            pass
        self.__class__._task = None
        logger.info("Volume sync periodic task stopped")

    async def _periodic_loop(self, db_factory) -> None:
        """Sleep loop that calls ``_execute_rsync`` at the configured interval.

        All exceptions are caught and logged so the loop never crashes.
        ``asyncio.CancelledError`` is always re-raised for clean shutdown.
        """
        # Default interval in case config can't be read on first cycle
        interval_seconds = 300
        try:
            while True:
                try:
                    async with db_factory() as session:
                        async with session.begin():
                            cfg = await self.get_config(session)
                            if cfg is None or not cfg.enabled:
                                logger.info(
                                    "Volume sync disabled or config removed — "
                                    "stopping periodic loop",
                                )
                                return

                            interval_seconds = cfg.sync_interval_minutes * 60

                            await self._execute_rsync(
                                session, cfg, sync_type="automatic",
                            )

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Volume sync periodic cycle error: %s", exc)

                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            raise

    # ------------------------------------------------------------------
    # Directory scanning
    # ------------------------------------------------------------------

    def _scan_directories(self) -> tuple[int, int]:
        """Scan ``/app/uploads/`` and ``/app/compliance_files/`` for totals.

        Returns ``(total_file_count, total_size_bytes)``.
        """
        total_files = 0
        total_size = 0

        for directory in (_UPLOAD_DIR, _COMPLIANCE_DIR):
            if not os.path.isdir(directory):
                continue
            for root, _dirs, files in os.walk(directory):
                for fname in files:
                    total_files += 1
                    try:
                        fpath = os.path.join(root, fname)
                        total_size += os.path.getsize(fpath)
                    except OSError:
                        pass  # File may have been deleted between walk and stat

        return total_files, total_size
