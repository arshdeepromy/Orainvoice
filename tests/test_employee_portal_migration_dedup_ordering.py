"""Integration test (task 17.7): migration 0224 dedup ordering + idempotency.

Drives the **actual** de-duplication and pre-constraint-guard helpers of
``alembic/versions/2026_06_13_0001-0224_employee_portal.py`` against the
configured Postgres test database, exercising the same code path the real
migration runs (alembic itself runs this migration over an **asyncpg** engine
via ``connection.run_sync(do_run_migrations)`` — see ``alembic/env.py`` — so
driving the helpers through the same ``run_sync`` bridge faithfully reproduces
the production driver, including the ``id = ANY(:ids)`` UPDATE and the
``audit_log`` INSERT).

**Validates: Requirements 1.7, 1.8, 17.5, 17.6, 17.7**

What this asserts (mirrors the migration's Step 3 → Step 4 → Step 5 ordering):

  * **Dedup-before-constraint ordering (R1.7, R17.5)** — over seeded active
    duplicates the staff partial unique index *cannot* be created (it raises a
    unique violation); only after :func:`_deduplicate_active_staff` resolves the
    groups does creating the index succeed. This is exactly why the migration
    deduplicates first and builds the unique indexes last.
  * **Halt-on-remaining-duplicates guard (R17.7)** — :func:`_assert_no_active_
    duplicates` ``raise``s while any active duplicate group remains (including a
    simulated *interrupted* dedup that resolved only part of a group), halting
    the migration before the unique indexes are ever attempted, leaving data
    unchanged.
  * **Per-group audit record (R1.8)** — one ``audit_log`` row per resolved group
    (``action = 'staff.deduplicated'``), capturing the survivor id and each
    de-duplicated id; the survivor matches the pure
    :func:`app.modules.staff.dedup.select_dedup_survivor` ordering rule
    (earliest ``created_at``; tie → smallest ``id``). Already-inactive rows are
    never touched and never audited.
  * **Idempotent / safe to re-run (R17.6)** — a second dedup pass over the
    now-clean data finds no groups, writes no new audit rows, and deactivates
    nothing.

Safety: every scenario runs inside a single transaction that is **always rolled
back** in a ``finally``. The two production staff unique indexes are dropped only
transaction-locally to allow active duplicates to be seeded; because the
transaction never commits, the indexes (and all seeded rows) are reverted and
remain intact for any other consumer of the shared dev database. A defensive
module teardown re-verifies the indexes exist and rebuilds them if a bug ever
let a commit through.

A real Postgres test environment is required
(``DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``);
when the DB is unreachable the tests skip rather than fail red.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings as app_settings
from app.modules.staff.dedup import select_dedup_survivor

# Filename of the migration under test inside ``alembic/versions/``.
MIGRATION_FILENAME = "2026_06_13_0001-0224_employee_portal.py"

# Marker baked into seeded org/plan names so an unexpected leak is identifiable
# (the transaction-rollback design means nothing should ever actually commit).
_MARKER = "TEST_T17_7_migration_dedup_ordering"

# Exact index definitions the migration creates in its autocommit phase, but
# WITHOUT ``CONCURRENTLY`` so they can be built/rolled back inside the test
# transaction. The predicate/columns are byte-for-byte the migration's.
_EMAIL_IDX_SQL = (
    "CREATE UNIQUE INDEX uq_staff_active_email_per_org "
    "ON staff_members (org_id, lower(btrim(email))) "
    "WHERE is_active AND email IS NOT NULL AND btrim(email) <> ''"
)
_EMPID_IDX_SQL = (
    "CREATE UNIQUE INDEX uq_staff_active_employee_id_per_org "
    "ON staff_members (org_id, employee_id) "
    "WHERE is_active AND employee_id IS NOT NULL AND btrim(employee_id) <> ''"
)
_DROP_EMAIL_IDX = "DROP INDEX IF EXISTS uq_staff_active_email_per_org"
_DROP_EMPID_IDX = "DROP INDEX IF EXISTS uq_staff_active_employee_id_per_org"


# ---------------------------------------------------------------------------
# Migration module loading + engine helpers
# ---------------------------------------------------------------------------


def _load_migration_module() -> ModuleType:
    """Load the 0224 migration via importlib (fresh module each call)."""
    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / MIGRATION_FILENAME
    )
    if not path.exists():  # pragma: no cover — defensive
        raise FileNotFoundError(f"Migration not found at {path}")
    module_name = f"_mig_0224_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise RuntimeError(f"Could not build importlib spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _build_engine() -> AsyncEngine:
    return create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )


async def _skip_if_db_unreachable(engine: AsyncEngine) -> None:
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — any connect failure means skip
        await engine.dispose()
        pytest.skip(f"Postgres not reachable for migration test: {exc}")


async def _run_in_rolledback_tx(scenario, *args) -> None:
    """Run ``scenario(sync_conn, *args)`` inside an always-rolled-back tx.

    The scenario receives a *synchronous* SQLAlchemy ``Connection`` (the same
    object type the migration's ``op.get_bind()`` yields under alembic's
    ``run_sync`` bridge), so the migration helpers run unmodified. The outer
    async transaction is rolled back unconditionally so no seeded rows and no
    transaction-local index drop ever persist.
    """
    engine = _build_engine()
    try:
        await _skip_if_db_unreachable(engine)
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                await conn.run_sync(scenario, *args)
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Seeding helpers (operate on the synchronous bridged connection)
# ---------------------------------------------------------------------------


def _seed_org(sync_conn) -> uuid.UUID:
    plan_id = sync_conn.execute(
        sa.text(
            "INSERT INTO subscription_plans "
            "(name, monthly_price_nzd, user_seats, storage_quota_gb, carjam_lookups_included) "
            "VALUES (:n, 0, 5, 1, 0) RETURNING id"
        ),
        {"n": f"{_MARKER}_plan_{uuid.uuid4().hex[:8]}"},
    ).scalar()
    org_id = sync_conn.execute(
        sa.text(
            "INSERT INTO organisations (name, plan_id, storage_quota_gb, slug) "
            "VALUES (:n, :p, 1, :slug) RETURNING id"
        ),
        {
            "n": f"{_MARKER}_org_{uuid.uuid4().hex[:8]}",
            "p": plan_id,
            "slug": f"t177-{uuid.uuid4().hex[:12]}",
        },
    ).scalar()
    return org_id


def _seed_staff(
    sync_conn,
    org_id: uuid.UUID,
    *,
    name: str,
    email: str | None,
    employee_id: str | None,
    is_active: bool,
    created_at: datetime,
) -> uuid.UUID:
    return sync_conn.execute(
        sa.text(
            "INSERT INTO staff_members "
            "(org_id, name, first_name, email, employee_id, is_active, created_at, updated_at) "
            "VALUES (:org_id, :name, :first_name, :email, :employee_id, :is_active, :ts, :ts) "
            "RETURNING id"
        ),
        {
            "org_id": org_id,
            "name": name,
            "first_name": name.split()[0],
            "email": email,
            "employee_id": employee_id,
            "is_active": is_active,
            "ts": created_at,
        },
    ).scalar()


def _active_ids(sync_conn, org_id: uuid.UUID) -> set[uuid.UUID]:
    rows = sync_conn.execute(
        sa.text(
            "SELECT id FROM staff_members WHERE org_id = :o AND is_active = true"
        ),
        {"o": org_id},
    ).fetchall()
    return {r[0] for r in rows}


def _is_active(sync_conn, staff_id: uuid.UUID) -> bool:
    return bool(
        sync_conn.execute(
            sa.text("SELECT is_active FROM staff_members WHERE id = :i"),
            {"i": staff_id},
        ).scalar()
    )


def _dedup_audit_rows(sync_conn, org_id: uuid.UUID) -> list[dict]:
    rows = sync_conn.execute(
        sa.text(
            "SELECT entity_id, entity_type, action, after_value "
            "FROM audit_log "
            "WHERE org_id = :o AND action = 'staff.deduplicated' "
            "ORDER BY created_at ASC"
        ),
        {"o": org_id},
    ).fetchall()
    out: list[dict] = []
    for entity_id, entity_type, action, after_value in rows:
        payload = after_value if isinstance(after_value, dict) else json.loads(after_value)
        out.append(
            {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "action": action,
                "after": payload,
            }
        )
    return out


def _expected_survivor(group: list[tuple[uuid.UUID, datetime]]) -> uuid.UUID:
    """Survivor per the pure rule: earliest created_at, tie → smallest id."""
    records = [SimpleNamespace(id=i, created_at=ts) for i, ts in group]
    return select_dedup_survivor(records).id


# ===========================================================================
# Scenario 1 — ordering + audit + idempotency (R1.7, R1.8, R17.5, R17.6)
# ===========================================================================


def _scenario_ordering(sync_conn, migration: ModuleType) -> None:
    # Drop the production staff unique indexes transaction-locally so active
    # duplicates can be seeded (they are restored on rollback).
    sync_conn.execute(sa.text(_DROP_EMAIL_IDX))
    sync_conn.execute(sa.text(_DROP_EMPID_IDX))

    org_id = _seed_org(sync_conn)
    base = datetime(2021, 1, 1, 9, 0, tzinfo=timezone.utc)

    # --- Email duplicate group: 3 active rows whose emails all normalise to
    #     'dup@example.com' (mixed case + surrounding whitespace exercises
    #     lower(btrim(...))). Distinct created_at → survivor is the earliest. ---
    email_survivor = _seed_staff(
        sync_conn, org_id, name="Email Survivor",
        email="Dup@Example.com", employee_id=None,
        is_active=True, created_at=base,
    )
    email_mid = _seed_staff(
        sync_conn, org_id, name="Email Mid",
        email="dup@example.com", employee_id=None,
        is_active=True, created_at=base + timedelta(days=1),
    )
    email_late = _seed_staff(
        sync_conn, org_id, name="Email Late",
        email="  dup@example.com  ", employee_id=None,
        is_active=True, created_at=base + timedelta(days=2),
    )
    # An ALREADY-INACTIVE duplicate (earliest of all) — must never be touched
    # nor audited (R1.7: flip is_active only, never re-activate / re-touch).
    email_inactive = _seed_staff(
        sync_conn, org_id, name="Email Inactive",
        email="dup@example.com", employee_id=None,
        is_active=False, created_at=base - timedelta(days=5),
    )

    # --- Employee-id duplicate group: 2 active rows sharing employee_id
    #     'EMP-9', with DISTINCT emails so they collide only on the
    #     employee_id key (disjoint from the email group → 2 groups total). ---
    empid_survivor = _seed_staff(
        sync_conn, org_id, name="Empid Survivor",
        email="e1@example.com", employee_id="EMP-9",
        is_active=True, created_at=base,
    )
    empid_late = _seed_staff(
        sync_conn, org_id, name="Empid Late",
        email="e2@example.com", employee_id="EMP-9",
        is_active=True, created_at=base + timedelta(days=3),
    )

    # --- Ordering proof, part 1: the unique index CANNOT be built over the
    #     dirty (duplicate) data. A savepoint isolates the expected failure so
    #     the surrounding transaction stays usable. ---
    sp = sync_conn.begin_nested()
    raised = False
    try:
        sync_conn.execute(sa.text(_EMAIL_IDX_SQL))
    except IntegrityError:
        raised = True
        sp.rollback()
    else:  # pragma: no cover — a pass here is a property violation
        sp.rollback()
    assert raised, (
        "unique index unexpectedly built over active-duplicate data — the "
        "migration's dedup-before-constraint ordering would be unnecessary"
    )

    assert _dedup_audit_rows(sync_conn, org_id) == [], "no audit before dedup"

    # --- Step 3: run the migration's own dedup routine. ---
    migration._deduplicate_active_staff(sync_conn)

    # Survivors stay active; later duplicates flipped inactive; the
    # pre-existing inactive row is left exactly as it was.
    assert _is_active(sync_conn, email_survivor) is True
    assert _is_active(sync_conn, email_mid) is False
    assert _is_active(sync_conn, email_late) is False
    assert _is_active(sync_conn, email_inactive) is False
    assert _is_active(sync_conn, empid_survivor) is True
    assert _is_active(sync_conn, empid_late) is False

    active_after = _active_ids(sync_conn, org_id)
    assert active_after == {email_survivor, empid_survivor}, active_after

    # Survivor selection matches the pure ordering rule the migration claims.
    assert email_survivor == _expected_survivor(
        [
            (email_survivor, base),
            (email_mid, base + timedelta(days=1)),
            (email_late, base + timedelta(days=2)),
        ]
    )
    assert empid_survivor == _expected_survivor(
        [(empid_survivor, base), (empid_late, base + timedelta(days=3))]
    )

    # --- R1.8: exactly one audit row per resolved group. ---
    audit = _dedup_audit_rows(sync_conn, org_id)
    assert len(audit) == 2, audit
    by_key = {row["after"]["key_type"]: row for row in audit}
    assert set(by_key) == {"email", "employee_id"}, by_key

    email_row = by_key["email"]
    assert email_row["entity_type"] == "staff_member"
    assert email_row["entity_id"] == email_survivor
    assert email_row["after"]["survivor_id"] == str(email_survivor)
    assert set(email_row["after"]["deduplicated_ids"]) == {
        str(email_mid),
        str(email_late),
    }
    # The already-inactive row is NOT part of the resolved group (R1.7).
    assert str(email_inactive) not in email_row["after"]["deduplicated_ids"]

    empid_row = by_key["employee_id"]
    assert empid_row["entity_id"] == empid_survivor
    assert empid_row["after"]["survivor_id"] == str(empid_survivor)
    assert set(empid_row["after"]["deduplicated_ids"]) == {str(empid_late)}

    # --- Step 4: the guard now passes (no active duplicates remain). ---
    migration._assert_no_active_duplicates(sync_conn)

    # --- Ordering proof, part 2 (Step 5): with the data clean, both unique
    #     indexes now build successfully — the dedup-before-constraint
    #     ordering is what makes the constraint enforceable. ---
    sync_conn.execute(sa.text(_EMAIL_IDX_SQL))
    sync_conn.execute(sa.text(_EMPID_IDX_SQL))

    # --- R17.6: a second dedup pass is a no-op — no new audit rows, no further
    #     deactivations. ---
    migration._deduplicate_active_staff(sync_conn)
    assert _active_ids(sync_conn, org_id) == {email_survivor, empid_survivor}
    audit_after_rerun = _dedup_audit_rows(sync_conn, org_id)
    assert len(audit_after_rerun) == 2, audit_after_rerun


# ===========================================================================
# Scenario 2 — halt-on-remaining-duplicates guard (R17.7)
# ===========================================================================


def _scenario_guard(sync_conn, migration: ModuleType) -> None:
    sync_conn.execute(sa.text(_DROP_EMAIL_IDX))
    sync_conn.execute(sa.text(_DROP_EMPID_IDX))

    org_id = _seed_org(sync_conn)
    base = datetime(2022, 6, 1, 9, 0, tzinfo=timezone.utc)

    a = _seed_staff(
        sync_conn, org_id, name="Guard A",
        email="halt@example.com", employee_id=None,
        is_active=True, created_at=base,
    )
    b = _seed_staff(
        sync_conn, org_id, name="Guard B",
        email="halt@example.com", employee_id=None,
        is_active=True, created_at=base + timedelta(days=1),
    )
    c = _seed_staff(
        sync_conn, org_id, name="Guard C",
        email="halt@example.com", employee_id=None,
        is_active=True, created_at=base + timedelta(days=2),
    )

    # The guard must halt while a full active duplicate group exists, BEFORE any
    # unique index is created over dirty data.
    with pytest.raises(RuntimeError, match="Pre-constraint guard failed"):
        migration._assert_no_active_duplicates(sync_conn)

    # The guard is a read-only check — it must not have mutated anything.
    assert _is_active(sync_conn, a) is True
    assert _is_active(sync_conn, b) is True
    assert _is_active(sync_conn, c) is True
    assert _dedup_audit_rows(sync_conn, org_id) == []

    # Simulate an INTERRUPTED dedup that resolved only part of the group (one
    # non-survivor flipped, one still active). Duplicates REMAIN, so the guard
    # must still halt (R17.7).
    sync_conn.execute(
        sa.text("UPDATE staff_members SET is_active = false WHERE id = :i"),
        {"i": c},
    )
    with pytest.raises(RuntimeError, match="Pre-constraint guard failed"):
        migration._assert_no_active_duplicates(sync_conn)

    # Only once the group is fully resolved does the guard pass — proving the
    # halt is specifically about *remaining* active duplicates.
    sync_conn.execute(
        sa.text("UPDATE staff_members SET is_active = false WHERE id = :i"),
        {"i": b},
    )
    migration._assert_no_active_duplicates(sync_conn)  # no raise


# ===========================================================================
# Tests
# ===========================================================================


def test_dedup_before_constraint_ordering_audit_and_idempotency() -> None:
    """Dedup → guard → constraint ordering, per-group audit, and re-run no-op.

    **Validates: Requirements 1.7, 1.8, 17.5, 17.6**
    """
    migration = _load_migration_module()
    asyncio.run(_run_in_rolledback_tx(_scenario_ordering, migration))


def test_guard_halts_on_remaining_active_duplicates() -> None:
    """The pre-constraint guard halts while any active duplicate group remains.

    **Validates: Requirements 17.7**
    """
    migration = _load_migration_module()
    asyncio.run(_run_in_rolledback_tx(_scenario_guard, migration))


# ---------------------------------------------------------------------------
# Defensive teardown — verify the production indexes are intact.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _verify_indexes_intact():
    """Belt-and-braces: confirm (and, if ever needed, rebuild) the staff unique
    indexes after the suite. The transaction-rollback design means they should
    never have been dropped for real; this only triggers if a bug let a commit
    through."""
    yield

    async def _do():
        engine = _build_engine()
        try:
            try:
                async with engine.connect() as conn:
                    await conn.execute(sa.text("SELECT 1"))
            except Exception:  # noqa: BLE001 — DB unreachable; nothing to verify
                return
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        sa.text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE tablename = 'staff_members' "
                            "AND indexname IN "
                            "('uq_staff_active_email_per_org', "
                            " 'uq_staff_active_employee_id_per_org')"
                        )
                    )
                ).fetchall()
                present = {r[0] for r in rows}
                # Rebuild defensively (CONCURRENTLY, autocommit) only if missing.
                if "uq_staff_active_email_per_org" not in present:
                    await conn.execution_options(isolation_level="AUTOCOMMIT")
                    await conn.execute(sa.text("CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS " + _EMAIL_IDX_SQL.split("CREATE UNIQUE INDEX ", 1)[1]))
                if "uq_staff_active_employee_id_per_org" not in present:
                    await conn.execution_options(isolation_level="AUTOCOMMIT")
                    await conn.execute(sa.text("CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS " + _EMPID_IDX_SQL.split("CREATE UNIQUE INDEX ", 1)[1]))
                assert "uq_staff_active_email_per_org" in present, (
                    "staff email unique index missing after test run"
                )
                assert "uq_staff_active_employee_id_per_org" in present, (
                    "staff employee_id unique index missing after test run"
                )
        finally:
            await engine.dispose()

    asyncio.run(_do())
