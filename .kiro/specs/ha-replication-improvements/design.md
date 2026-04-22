# Design Document

## Overview

This design extends the existing OraInvoice HA replication module with five improvements: auto-truncate on standby initialization, auto-promote failover, role reversal after recovery, split-brain write protection, and a new standby setup wizard. The design builds on the existing architecture (HeartbeatService, ReplicationManager, HAService, StandbyWriteProtectionMiddleware) and adds new state tracking, background logic, API endpoints, and frontend UI components.

## Architecture

### System Context

```
┌─────────────────────────────────────────────────────────────┐
│                     Primary Node                             │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ HAService │  │ HeartbeatSvc │  │ ReplicationManager │    │
│  │           │  │  (pings peer)│  │  (publication)     │    │
│  └──────────┘  └──────┬───────┘  └────────────────────┘    │
│                        │                                     │
│  ┌─────────────────────┴──────────────────────────────────┐ │
│  │ StandbyWriteProtectionMiddleware                        │ │
│  │  (blocks writes if split-brain stale primary)           │ │
│  └─────────────────────────────────────────────────────────┘ │
│                        │ HTTP heartbeat                      │
└────────────────────────┼─────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                     Standby Node                             │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ HAService │  │ HeartbeatSvc │  │ ReplicationManager │    │
│  │           │  │  (pings peer)│  │  (subscription)    │    │
│  │           │  │  + auto-     │  │  + auto-truncate   │    │
│  │           │  │    promote   │  │                    │    │
│  └──────────┘  └──────────────┘  └────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ StandbyWriteProtectionMiddleware                        │ │
│  │  (blocks writes in standby mode)                        │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Auto-promote runs inside HeartbeatService** — The heartbeat loop already tracks peer health and runs continuously. Adding auto-promote logic here avoids a separate background task and keeps the failover detection + execution in one place.

2. **Split-brain write protection reuses the existing middleware** — Rather than adding a new middleware, the `StandbyWriteProtectionMiddleware` is extended with a module-level `_split_brain_blocked` flag. When set, it blocks writes the same way standby mode does.

3. **Promotion timestamp in heartbeat payload** — The `promoted_at` field is added to the heartbeat response and HMAC-signed. This allows each node to compare promotion recency without a separate API call.

4. **Stale primary determination is local** — Each node independently determines if it is the stale primary by comparing its own `promoted_at` with the peer's. No consensus protocol is needed.

5. **Auto-truncate is a new method on ReplicationManager** — The truncation logic is added as `truncate_all_tables()` and called from `init_standby()` when a `truncate_first=True` parameter is passed.

6. **New standby wizard is frontend-only** — The wizard reuses existing backend endpoints (save config, test connection, create replication user). No new backend endpoints are needed for the wizard itself.

## Database Changes

### New Column: `ha_config.promoted_at`

```sql
ALTER TABLE ha_config ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMPTZ;
```

- **Type**: `DateTime(timezone=True)`, nullable
- **Default**: `None` (null)
- **Set**: When node is promoted to primary (manual or auto)
- **Cleared**: When node is demoted to standby (set to null)
- **Purpose**: Split-brain resolution — the node with the older (or null) `promoted_at` is the stale primary

### Alembic Migration

A new migration file adds the `promoted_at` column. The migration uses `IF NOT EXISTS` guard via `op.execute()` with raw SQL for idempotency.

## API Changes

### New Endpoint: GET `/api/v1/ha/failover-status`

**Auth**: Requires `global_admin` role

**Response Schema** (`FailoverStatusResponse`):
```python
class FailoverStatusResponse(BaseModel):
    auto_promote_enabled: bool
    peer_unreachable_seconds: float | None = None
    failover_timeout_seconds: int
    seconds_until_auto_promote: float | None = None
    split_brain_detected: bool = False
    is_stale_primary: bool = False
    promoted_at: str | None = None  # ISO 8601
```

**Behavior**:
- Reads `auto_promote_enabled` and `failover_timeout_seconds` from HAConfig
- Reads `peer_unreachable_seconds` and `split_brain_detected` from HeartbeatService
- Computes `seconds_until_auto_promote` = max(0, failover_timeout - peer_unreachable_seconds) when peer is unreachable and auto_promote is enabled
- Reads `promoted_at` from HAConfig

### Modified Endpoint: GET `/api/v1/ha/heartbeat`

**Changes**:
- Add `promoted_at` field to the heartbeat response payload (ISO 8601 string or null)
- The field is included in the HMAC-signed portion of the payload

### Modified Endpoint: POST `/api/v1/ha/replication/init`

**Changes**:
- When role is "standby", the endpoint now accepts an optional `truncate_first` query parameter (default: `true`)
- When `truncate_first=true`, calls `ReplicationManager.truncate_all_tables()` before creating the subscription
- The frontend sends `truncate_first=true` after the user confirms the warning modal

### Modified Endpoint: POST `/api/v1/ha/demote-and-sync`

**New endpoint** for the role reversal guided flow:

**Auth**: Requires `global_admin` role

**Request Schema** (`DemoteAndSyncRequest`):
```python
class DemoteAndSyncRequest(BaseModel):
    confirmation_text: str = Field(description="Must be exactly 'CONFIRM'")
    reason: str
```

**Behavior**:
1. Validate confirmation text
2. Demote local node to standby (update role, clear promoted_at)
3. Truncate all tables except ha_config
4. Create subscription pointing to peer (using stored peer DB URL)
5. Clear split-brain flags
6. Log audit event "ha.role_reversal_completed"

## Component Changes

### 1. ReplicationManager — New Method: `truncate_all_tables()`

```python
@staticmethod
async def truncate_all_tables() -> dict:
    """Truncate all public tables except ha_config.
    
    Uses a raw asyncpg connection with a single transaction.
    Returns dict with status and count of truncated tables.
    """
```

**Implementation**:
- Opens a raw asyncpg connection (same pattern as `_get_raw_conn()`)
- Queries `pg_tables` for all public schema tables except `ha_config`
- Executes `TRUNCATE table1, table2, ... CASCADE` in a single statement
- Returns `{"status": "ok", "tables_truncated": N}`

### 2. ReplicationManager — Modified: `init_standby()`

Add `truncate_first: bool = False` parameter. When true, call `truncate_all_tables()` before creating the subscription.

### 3. HeartbeatService — New State Tracking

Add to `__init__`:
```python
self._peer_unreachable_since: float | None = None  # monotonic timestamp
self._auto_promote_attempted: bool = False
self._auto_promote_failed_permanently: bool = False
```

Add to `_ping_loop()` after health classification:
- When peer transitions to unreachable: record `_peer_unreachable_since = time.monotonic()`
- When peer becomes reachable: reset `_peer_unreachable_since = None`
- When unreachable duration > failover_timeout and auto_promote_enabled: trigger auto-promote

Add new methods:
```python
def get_peer_unreachable_seconds(self) -> float | None:
    """Return seconds since peer became unreachable, or None if reachable."""

def get_seconds_until_auto_promote(self, failover_timeout: int) -> float | None:
    """Return seconds until auto-promote triggers, or None."""

async def _execute_auto_promote(self) -> None:
    """Promote this node to primary. Uses dedicated DB session."""
```

### 4. HeartbeatService — Auto-Promote Execution

The `_execute_auto_promote()` method:
1. Creates a dedicated DB session via `async_session_factory()`
2. Loads HAConfig, verifies role is still "standby"
3. Stops the replication subscription
4. Updates role to "primary", sets `promoted_at` to now
5. Updates middleware cache via `set_node_role("primary", ...)`
6. Writes audit log with action "ha.auto_promoted" using a system UUID
7. Commits the session

On failure: logs error, waits 10 seconds, retries once. On second failure: sets `_auto_promote_failed_permanently = True`.

### 5. HeartbeatService — Split-Brain Stale Primary Detection

Extend the existing split-brain detection in `_ping_peer()`:
- Parse `promoted_at` from the peer's heartbeat response
- Store as `self._peer_promoted_at: datetime | None`
- Add method `is_stale_primary()` that compares local `promoted_at` with peer's:
  - If local `promoted_at` is None and peer's is not None → stale
  - If both are not None and local < peer → stale
  - Otherwise → not stale

### 6. StandbyWriteProtectionMiddleware — Split-Brain Blocking

Add module-level flag:
```python
_split_brain_blocked: bool = False

def set_split_brain_blocked(blocked: bool) -> None:
    global _split_brain_blocked
    _split_brain_blocked = blocked
```

Modify `__call__()`:
- If `_split_brain_blocked` is True, apply the same write-blocking logic as standby mode
- The response message changes to indicate split-brain condition

### 7. HAConfig Model — New Column

```python
promoted_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True, default=None,
)
```

### 8. Schemas — New Response Models

```python
class FailoverStatusResponse(BaseModel):
    auto_promote_enabled: bool
    peer_unreachable_seconds: float | None = None
    failover_timeout_seconds: int
    seconds_until_auto_promote: float | None = None
    split_brain_detected: bool = False
    is_stale_primary: bool = False
    promoted_at: str | None = None

class DemoteAndSyncRequest(BaseModel):
    confirmation_text: str = Field(description="Must be exactly 'CONFIRM'")
    reason: str
```

### 9. HAService — New Method: `demote_and_sync()`

Combines demote + truncate + subscribe in one operation:
1. Load config, verify role is "primary"
2. Update role to "standby", clear `promoted_at`
3. Flush to DB
4. Truncate all tables except ha_config
5. Create subscription to peer
6. Update middleware cache
7. Clear split-brain flags
8. Write audit log
9. Commit

### 10. HAService — Modified: `promote()`

After updating role to "primary":
- Set `cfg.promoted_at = datetime.now(timezone.utc)`

### 11. HAService — Modified: `demote()`

After updating role to "standby":
- Set `cfg.promoted_at = None`

### 12. Router — New Endpoints

- `GET /api/v1/ha/failover-status` — Returns `FailoverStatusResponse`
- `POST /api/v1/ha/demote-and-sync` — Executes role reversal guided flow

### 13. Heartbeat Response — Modified

Add `promoted_at` to the heartbeat payload dict before HMAC signing:
```python
payload["promoted_at"] = cfg_row.promoted_at.isoformat() if cfg_row.promoted_at else None
```

## Frontend Changes

### HAReplication.tsx — New State

```typescript
// Failover status polling
const [failoverStatus, setFailoverStatus] = useState<FailoverStatus | null>(null)

interface FailoverStatus {
  auto_promote_enabled: boolean
  peer_unreachable_seconds: number | null
  failover_timeout_seconds: number
  seconds_until_auto_promote: number | null
  split_brain_detected: boolean
  is_stale_primary: boolean
  promoted_at: string | null
}
```

### HAReplication.tsx — Failover Status Polling

Add to `fetchData()`:
```typescript
const failover = await safeFetch<FailoverStatus | null>('/ha/failover-status', null)
setFailoverStatus(failover)
```

### HAReplication.tsx — Auto-Promote Countdown Banner

Display above the Cluster Status section when peer is unreachable:
- If `auto_promote_enabled` and `seconds_until_auto_promote != null`: amber banner with countdown
- If `!auto_promote_enabled` and `peer_unreachable_seconds != null`: gray banner with disabled message
- After auto-promotion (role changed to primary): green success banner

### HAReplication.tsx — Split-Brain Alert Banner

Display a critical red banner when `split_brain_detected` is true:
- "SPLIT-BRAIN DETECTED: This node's data may be stale. Writes are blocked until the conflict is resolved."
- If `is_stale_primary`: show "Demote and Sync" button that opens the guided recovery modal

### HAReplication.tsx — Guided Recovery Modal

New modal triggered by split-brain detection on stale primary:
- Title: "Role Conflict Detected"
- Message explaining the situation
- Data loss acknowledgment text
- "CONFIRM" text input
- "Demote and Sync" button → calls `POST /api/v1/ha/demote-and-sync`
- "Dismiss" button → closes modal (manual resolution)

### HAReplication.tsx — Standby Init Warning Modal

Modify the existing `init-replication` modal action:
- When role is "standby", show the enhanced warning text
- Require "CONFIRM" text input (currently init-replication doesn't require confirmation)
- Add the warning message about data replacement and credential loss

### HAReplication.tsx — New Standby Setup Wizard

New component (or section) that appears when:
- Role is "primary"
- Peer has been unreachable for > 5 minutes (from failover status)

Four-step wizard using existing form components:
1. Peer DB connection form (reuse existing)
2. Test connection button (reuse existing)
3. Create replication user (reuse existing)
4. Summary with instructions

## Correctness Properties

### Property 1: Auto-Promote Decision Consistency
**Criteria**: 3.4, 4.1
**Type**: Property-based test

For all combinations of `auto_promote_enabled` (bool), `peer_unreachable_seconds` (float >= 0), and `failover_timeout` (int > 0):
- `should_auto_promote(enabled, seconds, timeout)` returns True if and only if `enabled` is True AND `seconds > timeout`
- The existing `should_auto_promote` function in `utils.py` already implements this. The property verifies it holds for all inputs.

### Property 2: Stale Primary Determination
**Criteria**: 6.2, 6.3
**Type**: Property-based test

For all combinations of `local_promoted_at` (datetime or None) and `peer_promoted_at` (datetime or None):
- If `local_promoted_at` is None and `peer_promoted_at` is not None → local is stale
- If both are not None and `local_promoted_at < peer_promoted_at` → local is stale
- If both are None → neither is stale (manual resolution needed)
- If `peer_promoted_at` is None and `local_promoted_at` is not None → local is NOT stale
- The determination is antisymmetric: if A is stale relative to B, then B is not stale relative to A (when both have timestamps)

### Property 3: Failover Countdown Arithmetic
**Criteria**: 3.3, 3.4
**Type**: Property-based test

For all `failover_timeout` (int > 0) and `elapsed` (float >= 0):
- `remaining = max(0, failover_timeout - elapsed)`
- When `elapsed < failover_timeout`: `remaining > 0`
- When `elapsed >= failover_timeout`: `remaining == 0`
- Invariant: `elapsed + remaining >= failover_timeout`

### Property 4: Split-Brain Write Blocking Consistency
**Criteria**: 8.1, 8.3, 8.4
**Type**: Property-based test

For all HTTP methods, paths, and split-brain states:
- GET, HEAD, OPTIONS requests are NEVER blocked regardless of split-brain state
- Paths starting with `/api/v1/ha/` are NEVER blocked regardless of method or state
- Auth paths (`/api/v1/auth/login`, etc.) are NEVER blocked regardless of method or state
- Write requests (POST, PUT, DELETE, PATCH) to non-exempt paths ARE blocked when split-brain blocking is active

### Property 5: Truncation Table Set Correctness
**Criteria**: 2.1
**Type**: Property-based test

For any set of public schema table names:
- The set of tables to truncate equals the full set minus `ha_config`
- `ha_config` is never in the truncation set
- All other public tables are in the truncation set

## Error Handling

### Auto-Promote Failures
- First failure: log error, wait 10 seconds, retry
- Second failure: log critical, set `_auto_promote_failed_permanently = True`, stop attempting
- The HeartbeatService continues running (monitoring) even if auto-promote fails
- Admin can manually promote via the UI at any time

### Truncation Failures
- If truncation fails (e.g., permission error, table lock), return error to frontend
- Do not proceed with subscription creation
- The error message includes the PostgreSQL error detail

### Split-Brain Resolution Failures
- If demote-and-sync fails at any step, return the error to the frontend
- The admin can retry or choose manual resolution
- Write protection remains active until the split-brain is resolved

### Heartbeat Service Resilience
- The auto-promote logic is wrapped in try/except so a failure doesn't crash the heartbeat loop
- The heartbeat service continues monitoring even after auto-promote failure
- Session management uses `async_session_factory()` context manager to ensure cleanup

## Testing Strategy

### Unit Tests (Property-Based)
- `should_auto_promote()` — already exists, extend with more edge cases
- `determine_stale_primary()` — new pure function
- `calculate_failover_countdown()` — new pure function
- Split-brain write blocking — extend existing `should_block_request()` tests

### Integration Tests
- Auto-truncate: verify all tables except ha_config are empty after truncation
- Auto-promote: mock heartbeat to simulate unreachable peer, verify role change
- Demote-and-sync: verify full flow from primary to standby with data replacement
- Failover status endpoint: verify response shape and values

### E2E Test Script
- `scripts/test_ha_improvements_e2e.py` — tests the full flow against running containers
- Covers: init with truncation, failover status API, demote-and-sync API


## Additional Components (Gap Analysis Additions)

### 14. Task Scheduler — Standby Role Guard

**File**: `app/tasks/scheduled.py`

Add at the top of the task execution loop:

```python
from app.modules.ha.middleware import get_node_role

WRITE_TASKS = {
    "process_recurring_billing_task",
    "check_trial_expiry_task",
    "check_grace_period_task",
    "check_suspension_retention_task",
    "reset_sms_quotas_task",
    "reset_carjam_quotas_task",
}

# Inside the loop, before each task:
role = get_node_role()
if role == "standby" and task_name in WRITE_TASKS:
    logger.debug("Skipping task %s on standby node", task_name)
    continue
```

Also add `get_node_role()` function to `app/modules/ha/middleware.py`:
```python
def get_node_role() -> str:
    return _node_role
```

### 15. Docker Entrypoint — Standby Detection

**File**: `scripts/docker-entrypoint.sh`

Add before the migration step:

```bash
# Check if this is a standby node (skip migrations — data comes from replication)
ROLE=$(psql -U "$POSTGRES_USER" -h postgres -d "$POSTGRES_DB" -tAc \
  "SELECT role FROM ha_config LIMIT 1" 2>/dev/null || echo "standalone")
ROLE=$(echo "$ROLE" | tr -d '[:space:]')

if [ "$ROLE" = "standby" ]; then
    echo "Standby node detected — skipping migrations (data comes from replication)"
else
    echo "Running database migrations..."
    alembic upgrade head
fi
```

The `2>/dev/null || echo "standalone"` handles the case where `ha_config` doesn't exist yet (first deployment).

### 16. HeartbeatService — Crash Recovery

**File**: `app/modules/ha/heartbeat.py`

Modify `_ping_loop()`:

```python
async def _ping_loop(self) -> None:
    _consecutive_failures = 0
    try:
        while True:
            try:
                entry = await self._ping_peer()
                self.history.append(entry)
                # ... existing health classification ...
                # ... auto-promote logic ...
                _consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _consecutive_failures += 1
                logger.error("Heartbeat ping cycle error (%d consecutive): %s", _consecutive_failures, exc)
                if _consecutive_failures >= 5:
                    logger.warning("HeartbeatService: 5+ consecutive failures — service may be degraded")
            await asyncio.sleep(self.interval)
    except asyncio.CancelledError:
        raise
```

### 17. Sync Status Updates

**File**: `app/modules/ha/heartbeat.py`

Add to `_ping_loop()` after health classification, throttled to every 30 seconds:

```python
# Update sync_status in DB (throttled to every 30s)
if now_mono - self._last_sync_status_update > 30:
    self._last_sync_status_update = now_mono
    try:
        async with async_session_factory() as db:
            async with db.begin():
                from sqlalchemy import update, select
                from app.modules.ha.models import HAConfig
                result = await db.execute(select(HAConfig).limit(1))
                cfg = result.scalars().first()
                if cfg:
                    cfg.sync_status = self._determine_sync_status()
                    cfg.last_peer_health = self.peer_health
                    cfg.last_peer_heartbeat = datetime.now(timezone.utc)
    except Exception:
        pass  # Non-critical — don't crash heartbeat for status updates
```

## Additional Correctness Properties

### Property 6: Task Scheduler Standby Guard
For all combinations of node_role ("standalone", "primary", "standby") and task_name (from the full task list):
- When role is "standby" and task is in WRITE_TASKS → task is skipped
- When role is "primary" or "standalone" → task is executed regardless of name
- When role is "standby" and task is NOT in WRITE_TASKS → task is executed (read-only tasks still run)

### Property 7: Entrypoint Role Detection
For all possible `ha_config.role` values and the case where `ha_config` doesn't exist:
- "standby" → migrations skipped
- "primary" → migrations run
- "standalone" → migrations run
- table doesn't exist → migrations run (first deployment)
- empty string → migrations run (treat as standalone)
