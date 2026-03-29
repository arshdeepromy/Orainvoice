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

## Mandatory Steps After Modifying Frontend Code

After modifying any `.tsx` or `.ts` file in `frontend/src/`, you MUST rebuild the frontend inside the Docker container:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx vite build
```

The `watch-build.sh` watcher inside the container may not reliably detect changes on Windows Docker volume mounts. Always trigger a manual build after making changes.

## Common Pitfalls

- Creating a migration file but forgetting to run `alembic upgrade head` in the container
- Adding a new enum/role value in Python code but the database CHECK constraint still has the old list
- Adding a new column in a migration but the SQLAlchemy model references it before the migration runs
- Modifying frontend source files but not rebuilding — the browser serves the old cached bundle from nginx

## When Creating New Roles, Enum Values, or Constraints

1. Create the Alembic migration
2. Run `alembic upgrade head` in the container immediately
3. Update the Python code (models, schemas, RBAC, etc.)
4. Test the full flow end-to-end against the running container
