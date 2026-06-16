"""Smoke tests for cloud-backup-restore scheduler + middleware wiring (Task 15.5).

These are lightweight **smoke tests** (explicitly NOT property-based tests).
They assert that the cloud-backup-restore subsystem is correctly *wired into the
running application*, without exercising any backup/restore behaviour:

1. **Scheduler wiring (Req 8.8).** The three scheduled entry points
   ``run_scheduled_backup_task`` / ``run_blob_gc_task`` / ``run_rehearsal_task``
   from ``app.modules.backup_restore.service`` are registered in
   ``app.tasks.scheduled._DAILY_TASKS`` (as ``(fn, interval, name)`` tuples)
   under the names ``backup_scheduled`` / ``backup_blob_gc`` /
   ``backup_rehearsal``, and those same names appear in ``WRITE_TASKS`` so the
   scheduler skips them on standby HA nodes (primary-only — Req 8.8 / ISSUE-147).
   ``app.tasks.scheduled`` imports cleanly in this environment, so the
   collections are asserted directly.

2. **Middleware wiring (Req 12.1).** ``RestoreMaintenanceMiddleware`` is
   registered in the app middleware stack alongside
   ``StandbyWriteProtectionMiddleware``. ``app.main.create_app()`` cannot be
   fully invoked here because of a pre-existing, unrelated missing ``stripe``
   dependency, so the registration is verified two ways that do not require
   building the app:
     * the middleware class is importable and is a valid ASGI middleware
       (constructible with an ``app`` and callable as ``(scope, receive, send)``);
     * ``app/main.py`` source imports ``RestoreMaintenanceMiddleware`` and adds
       it via ``app.add_middleware(RestoreMaintenanceMiddleware)`` next to the
       ``StandbyWriteProtectionMiddleware`` registration.

_Requirements: 8.8, 12.1_
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

# app.tasks.scheduled imports cleanly in this environment (verified), so we can
# import the live collections and the service-facade callables directly and
# assert on object identity rather than parsing source.
from app.tasks.scheduled import _DAILY_TASKS, WRITE_TASKS
from app.modules.backup_restore.service import (
    run_blob_gc_task,
    run_rehearsal_task,
    run_scheduled_backup_task,
)

# The three scheduled tasks: registered name -> expected callable.
_EXPECTED_BACKUP_TASKS = {
    "backup_scheduled": run_scheduled_backup_task,
    "backup_blob_gc": run_blob_gc_task,
    "backup_rehearsal": run_rehearsal_task,
}

_MAIN_PY = Path(__file__).resolve().parents[1] / "app" / "main.py"


def _daily_tasks_by_name() -> dict:
    """Map registered task name -> callable from the ``_DAILY_TASKS`` tuples.

    Each entry is a ``(task_fn, interval_seconds, name)`` tuple.
    """
    by_name = {}
    for entry in _DAILY_TASKS:
        assert isinstance(entry, tuple) and len(entry) == 3, (
            f"_DAILY_TASKS entries must be (fn, interval, name) tuples; got {entry!r}"
        )
        fn, interval, name = entry
        by_name[name] = fn
    return by_name


# ---------------------------------------------------------------------------
# 1. Scheduler wiring (Req 8.8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task_name", sorted(_EXPECTED_BACKUP_TASKS))
def test_backup_task_registered_in_daily_tasks(task_name: str) -> None:
    """Each backup task name is present in _DAILY_TASKS as a (fn, interval, name)."""
    by_name = _daily_tasks_by_name()
    assert task_name in by_name, (
        f"{task_name!r} is not registered in _DAILY_TASKS"
    )


@pytest.mark.parametrize("task_name", sorted(_EXPECTED_BACKUP_TASKS))
def test_backup_task_callable_matches_service_facade(task_name: str) -> None:
    """The registered callable is the service-facade function it should be."""
    by_name = _daily_tasks_by_name()
    expected_fn = _EXPECTED_BACKUP_TASKS[task_name]
    assert by_name[task_name] is expected_fn, (
        f"{task_name!r} should be wired to "
        f"{expected_fn.__module__}.{expected_fn.__name__}"
    )


@pytest.mark.parametrize("task_name", sorted(_EXPECTED_BACKUP_TASKS))
def test_backup_task_is_write_task(task_name: str) -> None:
    """Each backup task is in WRITE_TASKS so it runs on the primary node only (Req 8.8)."""
    assert task_name in WRITE_TASKS, (
        f"{task_name!r} must be in WRITE_TASKS so the scheduler skips it on "
        f"standby nodes (primary-only, Req 8.8)"
    )


def test_backup_task_callables_come_from_service_module() -> None:
    """All three callables originate in the backup_restore service facade."""
    for fn in _EXPECTED_BACKUP_TASKS.values():
        assert fn.__module__ == "app.modules.backup_restore.service", (
            f"{fn.__name__} should be defined in the backup_restore service "
            f"facade, not {fn.__module__}"
        )


def test_backup_task_intervals_are_positive_ints() -> None:
    """The three backup tasks tick on a positive interval (sanity on the tuple shape)."""
    intervals = {
        name: interval
        for fn, interval, name in _DAILY_TASKS
        if name in _EXPECTED_BACKUP_TASKS
    }
    assert set(intervals) == set(_EXPECTED_BACKUP_TASKS), (
        "all three backup tasks must appear exactly once in _DAILY_TASKS"
    )
    for name, interval in intervals.items():
        assert isinstance(interval, int) and interval > 0, (
            f"{name!r} interval must be a positive int; got {interval!r}"
        )


# ---------------------------------------------------------------------------
# 2. Middleware wiring (Req 12.1)
# ---------------------------------------------------------------------------


def test_restore_maintenance_middleware_is_importable_asgi_middleware() -> None:
    """RestoreMaintenanceMiddleware exists and is a valid ASGI middleware.

    A Starlette/ASGI ``add_middleware`` class wraps the downstream app: it is
    constructed with ``app`` and is callable as ``(scope, receive, send)``.
    """
    from app.modules.backup_restore.middleware import RestoreMaintenanceMiddleware

    # Constructible with a downstream ASGI app.
    async def _dummy_app(scope, receive, send):  # pragma: no cover - never called
        return None

    instance = RestoreMaintenanceMiddleware(_dummy_app)
    assert instance.app is _dummy_app

    # ASGI contract: __call__(self, scope, receive, send), async.
    call = RestoreMaintenanceMiddleware.__call__
    assert inspect.iscoroutinefunction(call), "ASGI __call__ must be async"
    params = list(inspect.signature(call).parameters)
    assert params == ["self", "scope", "receive", "send"], (
        f"ASGI middleware __call__ signature unexpected: {params}"
    )


def test_main_py_registers_restore_maintenance_middleware() -> None:
    """app/main.py imports and adds RestoreMaintenanceMiddleware.

    Source-level assertion: create_app() cannot be fully invoked in this
    environment due to a pre-existing unrelated missing ``stripe`` dependency,
    so for this wiring smoke test we assert main.py references the import and
    the ``app.add_middleware(...)`` registration.
    """
    source = _MAIN_PY.read_text()
    assert (
        "from app.modules.backup_restore.middleware import "
        "RestoreMaintenanceMiddleware" in source
    ), "main.py must import RestoreMaintenanceMiddleware"
    assert "app.add_middleware(RestoreMaintenanceMiddleware)" in source, (
        "main.py must register RestoreMaintenanceMiddleware via add_middleware"
    )


def test_restore_maintenance_registered_alongside_standby_protection() -> None:
    """The restore-maintenance gate is registered next to the standby write guard.

    Both ``add_middleware`` calls must be present so the restore-maintenance gate
    sits in the same part of the stack as ``StandbyWriteProtectionMiddleware``
    (design: "registered alongside StandbyWriteProtectionMiddleware").
    """
    source = _MAIN_PY.read_text()
    assert "app.add_middleware(StandbyWriteProtectionMiddleware)" in source, (
        "main.py must register StandbyWriteProtectionMiddleware"
    )
    assert "app.add_middleware(RestoreMaintenanceMiddleware)" in source, (
        "main.py must register RestoreMaintenanceMiddleware"
    )
