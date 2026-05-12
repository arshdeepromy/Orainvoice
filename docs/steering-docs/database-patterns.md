# Database Patterns — ORM, Migrations, RLS, and Common Pitfalls

This document covers database patterns for a multi-tenant SaaS application using an async ORM (SQLAlchemy), migration tool (Alembic), and PostgreSQL with Row-Level Security.

## Why This Matters

Database operations are the foundation of any SaaS application. Getting them wrong causes:
- Data leaks between tenants (RLS misconfiguration)
- Silent data loss (missing commits)
- Crashes on serialization (MissingGreenlet errors)
- Failed deployments (non-idempotent migrations)
- Performance degradation (missing indexes, N+1 queries)

---

## Pattern 1: flush() vs commit() — Know the Difference

In async SQLAlchemy with session context managers:

```python
# flush() — writes to DB but does NOT commit the transaction
await db.flush()
# Use when: you need server-generated values (IDs, timestamps) but want
# the transaction to remain open for more operations

# commit() — finalizes the transaction, makes changes permanent
await db.commit()
# Use when: the operation is complete and changes should persist

# refresh() — reloads the object from the database
await db.refresh(obj)
# Use when: you need to access lazy-loaded relationships or server-generated values
```

### The Convention

**Services use `flush()`. Route handlers manage the transaction.**

```python
# service.py — never commits, just flushes
async def create_order(db: AsyncSession, data: OrderCreate) -> Order:
    order = Order(**data.dict())
    db.add(order)
    await db.flush()
    await db.refresh(order)  # Load server-generated fields
    return order

# router.py — commits or rolls back
@router.post("/orders")
async def create_order_endpoint(data: OrderCreate, db: AsyncSession = Depends(get_db)):
    try:
        order = await service.create_order(db, data)
        await db.commit()
        return order
    except Exception:
        await db.rollback()
        raise
```

### With Auto-Commit Context Manager

If using `session.begin()` which auto-commits on successful exit:

```python
# get_db_session dependency
async def get_db_session():
    async with async_session() as session:
        async with session.begin():
            yield session
            # Auto-commits here if no exception
            # Auto-rolls-back if exception raised
```

**Critical:** With this pattern, do NOT call `db.commit()` manually — it closes the transaction prematurely. Use only `db.flush()` in services.

---

## Pattern 2: Preventing MissingGreenlet Errors

**Symptom:** `MissingGreenlet: greenlet_spawn has not been called` when accessing relationships on ORM objects.

**Root Cause:** Accessing a lazy-loaded relationship outside the async session context.

**Prevention:**

```python
# WRONG — accessing relationship after session closes
order = await service.get_order(db, order_id)
return {"order": order, "customer_name": order.customer.name}  # ← MissingGreenlet!

# CORRECT — refresh with relationships before returning
order = await service.get_order(db, order_id)
await db.refresh(order, ["customer"])  # Eagerly load the relationship
return {"order": order, "customer_name": order.customer.name}

# ALSO CORRECT — use joinedload in the query
from sqlalchemy.orm import joinedload
stmt = select(Order).options(joinedload(Order.customer)).where(Order.id == order_id)
result = await db.execute(stmt)
order = result.scalar_one()
```

**Rule:** After `db.flush()`, always `await db.refresh(obj)` before returning ORM objects for Pydantic serialization.

---

## Pattern 3: Row-Level Security (RLS) for Multi-Tenancy

RLS ensures tenants can only see their own data at the database level:

```sql
-- Enable RLS on a table
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

-- Create a policy
CREATE POLICY tenant_isolation ON orders
    USING (org_id = current_setting('app.current_org_id')::uuid);

-- Force RLS even for table owners
ALTER TABLE orders FORCE ROW LEVEL SECURITY;
```

### Setting the Tenant Context

Before any query, set the current tenant:

```python
async def set_rls_context(session: AsyncSession, org_id: str):
    # Validate as UUID to prevent SQL injection
    validated = str(uuid.UUID(org_id))
    await session.execute(text(f"SET LOCAL app.current_org_id = '{validated}'"))
```

**Critical:** `SET LOCAL` does NOT support parameterized queries. You must interpolate directly, but validate the input first (UUID format is safe).

### Tables to Exclude from RLS

Some tables are global (not tenant-scoped):
- `users` (platform-level)
- `subscription_plans`
- `feature_flags`
- `integration_configs`
- `ha_config` (HA replication config)

---

## Pattern 4: Idempotent Migrations

Migrations should be safe to run multiple times without error:

```python
# GOOD — idempotent
def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL,
            total NUMERIC(12, 2) NOT NULL DEFAULT 0
        )
    """)
    
    # For adding columns
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE orders ADD COLUMN status VARCHAR(20) DEFAULT 'draft';
        EXCEPTION
            WHEN duplicate_column THEN NULL;
        END $$;
    """)

# BAD — will fail on second run
def upgrade():
    op.create_table('orders', ...)  # Raises if table exists
    op.add_column('orders', Column('status', ...))  # Raises if column exists
```

### Migration Best Practices

1. **Test on staging with production-like data** before deploying
2. **Never modify a migration that's been deployed** — create a new one
3. **Keep migrations small** — one logical change per migration
4. **Include both upgrade and downgrade** functions
5. **Use raw SQL for complex operations** (DDL in transactions, data migrations)

---

## Pattern 5: Connection Pooling Configuration

```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,          # Steady-state connections per worker
    max_overflow=10,       # Burst connections above pool_size
    pool_pre_ping=True,    # Verify connections are alive before use
    pool_recycle=1800,     # Recycle connections every 30 min
    pool_timeout=30,       # Max wait for a connection from the pool
)
```

**Capacity planning:**
- With 4 workers: steady state = 4 × 20 = 80 connections
- Peak burst: 4 × (20 + 10) = 120 connections
- Set PostgreSQL `max_connections` to at least 150

---

## Pattern 6: Audit Logging with Serialization Safety

When logging changes to an audit table, handle non-serializable types:

```python
import decimal
import datetime
import json

def serialize_for_audit(obj):
    """Make any value JSON-serializable for audit logging."""
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, bytes):
        return "<binary>"
    raise TypeError(f"Cannot serialize {type(obj)}")

# Usage
audit_data = json.dumps(changes, default=serialize_for_audit)
```

---

## Pattern 7: Proper Index Strategy

```sql
-- Always index foreign keys
CREATE INDEX idx_orders_org_id ON orders(org_id);
CREATE INDEX idx_orders_customer_id ON orders(customer_id);

-- Index columns used in WHERE clauses
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at);

-- Composite indexes for common query patterns
CREATE INDEX idx_orders_org_status ON orders(org_id, status);

-- Partial indexes for common filters
CREATE INDEX idx_orders_active ON orders(org_id) WHERE status NOT IN ('voided', 'deleted');
```

---

## Pattern 8: Handling the "Closed Transaction" Error

**Symptom:** `Can't operate on closed transaction inside context manager`

**Root Cause:** Calling `db.commit()` inside a `session.begin()` context manager closes the transaction. Any subsequent database operation fails.

**Prevention:**
```python
# WRONG — commit closes the transaction, refresh fails
async with session.begin():
    db.add(item)
    await db.commit()        # ← closes transaction
    await db.refresh(item)   # ← ERROR: closed transaction

# CORRECT — use flush, let context manager commit
async with session.begin():
    db.add(item)
    await db.flush()         # ← writes but keeps transaction open
    await db.refresh(item)   # ← works fine
    # Transaction commits automatically when block exits
```

---

## Pattern 9: Soft Deletes vs Hard Deletes

For multi-tenant SaaS, prefer soft deletes for user-facing data:

```python
class Order(Base):
    __tablename__ = "orders"
    
    id = Column(UUID, primary_key=True)
    deleted_at = Column(DateTime, nullable=True)  # NULL = active
    
    @hybrid_property
    def is_deleted(self):
        return self.deleted_at is not None
```

Add a default filter to exclude soft-deleted records:

```python
# In queries
stmt = select(Order).where(Order.deleted_at.is_(None))
```

**Hard delete** only for:
- Draft records that were never finalized
- Temporary/staging data
- GDPR/privacy compliance (after soft-delete grace period)

---

## Checklist

- [ ] Services use `flush()`, route handlers manage commit/rollback
- [ ] After `flush()`, always `refresh()` before returning ORM objects
- [ ] RLS policies exist on all tenant-scoped tables
- [ ] `SET LOCAL` uses validated literal values (not parameterized queries)
- [ ] Migrations are idempotent (safe to run multiple times)
- [ ] Connection pool is sized for the number of workers
- [ ] Foreign keys have indexes
- [ ] Audit logging handles Decimal, datetime, UUID serialization
- [ ] No `db.commit()` inside `session.begin()` context managers
- [ ] Soft deletes used for user-facing data, hard deletes only for drafts/temp data
