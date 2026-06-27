---
inclusion: fileMatch
fileMatchPattern: "alembic/**,**/models.py,**/schemas.py"
---

# Database Migration Checklist

This file is loaded whenever Alembic migrations, SQLAlchemy models, or Pydantic schemas are read or edited. It prevents the recurring issue of creating migrations that never get applied to the running database.

## The Problem

Every time we add a new database constraint, column, table, or enum value via an Alembic migration, the migration file exists on disk but the live PostgreSQL database inside Docker still has the old schema. This causes `CheckViolationError`, `UndefinedColumnError`, or similar crashes at runtime.

## Mandatory Steps After Creating Any Alembic Migration

After creating or modifying any file in `alembic/versions/`, you MUST:

1. Run the migration against the dev database inside the Docker container:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head
   ```

2. Verify it succeeded (no errors in output, shows "Running upgrade X -> Y")

3. If the migration modifies a CHECK constraint (like `ck_users_role`), verify the new value is accepted:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python -c "
   from sqlalchemy import text
   from app.core.database import sync_engine
   with sync_engine.connect() as conn:
       result = conn.execute(text(\"SELECT conname, consrc FROM pg_constraint WHERE conname = 'ck_users_role'\"))
       for row in result:
           print(row)
   "
   ```

## Index Migrations Must Use `CREATE INDEX CONCURRENTLY`

**Never use `op.create_index(...)` for index DDL.** Always use raw SQL `CREATE INDEX CONCURRENTLY IF NOT EXISTS ...` inside an `op.get_context().autocommit_block()`.

This rule exists because of ISSUE-168 and PERFORMANCE_AUDIT.md §D-H3: every `op.create_index(...)` call takes an `ACCESS EXCLUSIVE` lock on the table for the entire build. On a 5M-row `invoices` table that blocks all reads and writes for tens of seconds — a release-blocking outage at scale. `CREATE INDEX CONCURRENTLY` only takes `SHARE UPDATE EXCLUSIVE`, so reads and writes continue uninterrupted while the index builds.

### Canonical template

The canonical example is `alembic/versions/2026_05_30_2300-0202_add_perf_indexes.py`. Copy its structure for any new index migration:

```python
from alembic import op

revision = "0XXX"
down_revision = "0YYY"

_UPGRADE_STATEMENTS: list[tuple[str, str]] = [
    (
        "Description of what this index covers",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_table_columns "
        "ON table_name (col_a, col_b DESC)",
    ),
    # ... more indexes
]

_DOWNGRADE_STATEMENTS: list[tuple[str, str]] = [
    ("Drop idx_table_columns", "DROP INDEX CONCURRENTLY IF EXISTS idx_table_columns"),
]


def _run_outside_tx(statements: list[tuple[str, str]]) -> None:
    with op.get_context().autocommit_block():
        for description, sql in statements:
            op.execute(sql)


def upgrade() -> None:
    _run_outside_tx(_UPGRADE_STATEMENTS)


def downgrade() -> None:
    _run_outside_tx(_DOWNGRADE_STATEMENTS)
```

### Why each piece matters

- **`autocommit_block()` is mandatory.** `CREATE/DROP INDEX CONCURRENTLY` is rejected by Postgres if executed inside a transaction. Alembic wraps every migration in a transaction by default; `autocommit_block()` commits the active transaction, runs the body in autocommit mode, then opens a fresh transaction for whatever follows.
- **`IF NOT EXISTS` / `IF EXISTS` guards are mandatory.** A failed CONCURRENTLY build leaves the index behind in an INVALID state — re-running the migration without guards will error on the duplicate name. With guards, the migration is safely re-runnable: drop the invalid index manually (or via the downgrade) and re-run.
- **Each statement runs independently.** A failure on one CONCURRENTLY index does not roll back the others. This is a Postgres limitation, not a bug. The other indexes will be live; only the failed one needs cleanup. Mention this in code review when migrations contain many indexes.
- **Extensions (e.g. `pg_trgm`) go in the same migration as the indexes that use them.** Use `CREATE EXTENSION IF NOT EXISTS pg_trgm` as the first statement.

### Banned patterns

| Pattern | Why banned | Use instead |
|---|---|---|
| `op.create_index("idx_x", "table", ["col"])` | Takes ACCESS EXCLUSIVE lock; blocks writes | Raw SQL `CREATE INDEX CONCURRENTLY IF NOT EXISTS ...` |
| `op.execute("CREATE INDEX ...")` (no CONCURRENTLY) | Same blocking lock | Add `CONCURRENTLY` |
| `CREATE INDEX CONCURRENTLY ...` outside `autocommit_block()` | Postgres rejects: cannot run in a transaction | Wrap in `with op.get_context().autocommit_block():` |
| `CREATE INDEX CONCURRENTLY ...` without `IF NOT EXISTS` | Migration fails on retry after a partial-build INVALID state | Add `IF NOT EXISTS` |
| Mixing CONCURRENTLY DDL with other migration ops in the same upgrade() | The autocommit boundary changes transaction semantics for the rest of the migration | Put index DDL in its own migration file |

### Code review

Reject any new migration that contains `op.create_index(` in `upgrade()` or `downgrade()`. The only acceptable index DDL is raw SQL inside `autocommit_block()`. (CI lint is future work — until then this is a manual review gate.)

## Mandatory Steps After Modifying Frontend Code

The active web app is **`frontend-v2/`** (`frontend/` is archived — see `frontend-redesign.md`). In local dev, `frontend-v2` runs a Vite dev server with HMR, so source edits are normally picked up automatically.

If a change does not appear after editing, rebuild/restart the active frontend container:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart frontend-v2
```

After a TypeScript change, confirm the build is clean (the dev server keeps serving the last good bundle if a build fails):

```bash
docker logs invoicing-frontend-v2-1 --tail 30
```

Do NOT rebuild the archived `frontend/` container — it is stopped and out of scope.

## Common Pitfalls

- Creating a migration file but forgetting to run `alembic upgrade head` in the container
- Adding a new enum/role value in Python code but the database CHECK constraint still has the old list
- Adding a new column in a migration but the SQLAlchemy model references it before the migration runs
- Modifying frontend source files but not rebuilding — the browser serves the old cached bundle from nginx
- **Deploying code to Pi prod without syncing `alembic/versions/`** — the model references a column that doesn't exist in the prod DB, causing `AttributeError` at runtime. Always sync migrations when deploying to Pi.
- **Syncing only the changed `.py` files to Pi but missing the migration** — even if the code change is "just a bugfix", check if any migration was created since the last deploy. The entrypoint runs `alembic upgrade head` automatically, but only if the migration files are present on disk.

## PostgreSQL Logical Replication Pitfalls

- **PostgreSQL 16 does not support sequence replication via `ALTER PUBLICATION ADD ALL SEQUENCES`.** This syntax does not exist. Sequences are not replicated by logical replication — they must be synced manually (e.g., `setval()` after promotion). Do not attempt to add sequences to a publication.
- **After calling `save_config()` (or any service method that calls `db.commit()`), the current SQLAlchemy session's transaction is closed.** Subsequent DB operations on the same session will fail. Create a fresh session via `async_session_factory()` for any DB work that follows a commit in the same request handler.

## When Writing Raw SQL Queries (sa_text / text())

**ALWAYS verify column names against the actual database schema before writing raw SQL.**

This rule exists because of ISSUE-107: the dashboard widgets feature used `category` and `current_stock` in raw SQL queries against the `products` table, but the actual columns are `category_id` and `stock_quantity`. Similarly, `expense_date` was used but the actual column is `date`. These mismatches caused `InFailedSQLTransactionError` cascades in production.

Raw SQL bypasses SQLAlchemy's model validation — typos in column names compile fine but crash at runtime. ORM queries (`select(Model.column)`) catch this at import time.

**Before writing any `sa_text()` or `text()` query:**

1. Check the actual column names by reading the model file or running:
   ```bash
   docker compose exec postgres psql -U postgres -d workshoppro -c \
     "SELECT column_name FROM information_schema.columns WHERE table_name = 'your_table' ORDER BY ordinal_position;"
   ```

2. If the query references columns from multiple tables, check ALL of them.

3. Prefer ORM queries (`select(Model.column)`) over raw SQL. ORM queries validate column names at import time. Only use raw SQL when the ORM can't express the query (e.g., complex CTEs, window functions).

4. When raw SQL is unavoidable, add a comment with the actual column names:
   ```python
   # products columns: category_id (not category), stock_quantity (not current_stock)
   sql = sa_text("SELECT category_id, stock_quantity FROM products WHERE ...")
   ```

## When Writing Multi-Query Functions with Savepoints

**Every sub-query inside a savepoint-protected function must itself be inside a savepoint.**

This rule exists because of ISSUE-107: the `get_cash_flow` widget function had a main revenue query (inside a savepoint via `_safe_call`) and an expenses sub-query inside a bare `try/except`. When the expenses query failed (wrong column name), it poisoned the parent transaction because the error occurred outside any savepoint. The savepoint from `_safe_call` only protected the revenue query, not the expenses sub-query.

```python
# WRONG — inner query failure poisons the transaction
async def get_data(db):
    # This is inside a savepoint from the caller
    revenue = await db.execute(revenue_query)  # protected
    try:
        expenses = await db.execute(expenses_query)  # NOT protected — bare try/except
    except Exception:
        expenses = []  # catches Python exception but transaction is already poisoned

# RIGHT — inner query has its own savepoint
async def get_data(db):
    revenue = await db.execute(revenue_query)
    try:
        sp = await db.begin_nested()
        try:
            expenses = await db.execute(expenses_query)
        except Exception:
            await sp.rollback()
            expenses = []
    except Exception:
        expenses = []
```

## When Creating New Roles, Enum Values, or Constraints

1. Create the Alembic migration
2. Run `alembic upgrade head` in the container immediately
3. Update the Python code (models, schemas, RBAC, etc.)
4. Test the full flow end-to-end against the running container
