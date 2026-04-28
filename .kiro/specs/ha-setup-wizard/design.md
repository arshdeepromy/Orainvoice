# Design Document: HA Setup Wizard

## Overview

The HA Setup Wizard transforms OraInvoice's High Availability setup from a manual, multi-step process requiring SSH configuration, SQL commands, and config file editing into a guided, point-and-click wizard embedded in the existing HA Replication admin page. The feature spans four layers:

1. **Infrastructure** — Dockerfile installs `openssh-server` + `rsync`; entrypoint auto-generates SSH keys, detects host LAN IP, starts sshd; Docker Compose files add `ha_keys` volume and port 2222 mapping
2. **Backend API** — New wizard endpoints for reachability check, remote authentication, trust handshake (SSH key + HMAC exchange), and automated replication setup; new `ha_event_log` table for persistent event history
3. **Frontend Wizard UI** — 5-step guided flow (Enter Address → Verify Reachability → Authenticate → Trust Handshake → Automated Setup) integrated into `HAReplication.tsx` alongside the existing monitoring UI
4. **Bug verification** — Requirements 18–29 are already fixed in the current codebase; the design confirms their correctness and specifies tests

### Key Architectural Decisions

| Decision | Rationale |
|---|---|
| Bridge networking preserved | Docker DNS resolution and port isolation; host LAN IPs used for cross-node communication |
| SSH keypair in Docker volume | Survives container restarts; no host SSH dependency |
| sshd on port 2222 inside app container | Avoids conflict with host SSH; rsync uses this for volume sync |
| Trust handshake via authenticated API | No SSH needed for initial pairing; Global_Admin credentials prove ownership of both nodes |
| HMAC secret generated during handshake | Cryptographically random, stored encrypted in DB on both nodes |
| `ha_event_log` excluded from replication | Per-node event history, like `ha_config` |
| Non-blocking event writes | try/except around all event log writes; heartbeat loop never crashes from logging failures |
| Python+asyncpg for entrypoint role detection | `psql` is not installed in the slim image; asyncpg is already a dependency |
| Connection string single-quote escaping | Prevents SQL injection from passwords containing `'` in replication DDL |

## Architecture

### System Architecture

```mermaid
graph TB
    subgraph "Primary Node (Docker Host A)"
        subgraph "App Container"
            EP1[docker-entrypoint.sh]
            SSHD1[sshd :2222]
            APP1[FastAPI App :8000]
            HB1[HeartbeatService]
            VS1[VolumeSyncService]
        end
        subgraph "Volumes"
            HAK1[ha_keys volume]
            UPL1[uploads volume]
        end
        PG1[(PostgreSQL :5432)]
    end

    subgraph "Standby Node (Docker Host B)"
        subgraph "App Container "
            EP2[docker-entrypoint.sh]
            SSHD2[sshd :2222]
            APP2[FastAPI App :8000]
            HB2[HeartbeatService]
        end
        subgraph "Volumes "
            HAK2[ha_keys volume]
            UPL2[uploads volume]
        end
        PG2[(PostgreSQL :5432)]
    end

    subgraph "Admin Browser"
        WIZ[Wizard UI]
    end

    WIZ -->|"1. Enter standby address"| APP1
    APP1 -->|"2. Verify reachability"| APP2
    WIZ -->|"3. Auth against standby"| APP2
    APP1 -->|"4. Trust handshake"| APP2
    APP1 -->|"5. Configure replication"| PG1
    APP1 -->|"5. Configure subscription"| APP2
    APP2 --> PG2

    PG1 -.->|"Logical Replication"| PG2
    VS1 -->|"rsync over SSH"| SSHD2

    EP1 --> HAK1
    EP2 --> HAK2
    SSHD1 --> HAK1
    SSHD2 --> HAK2
```

### Wizard Flow Sequence

```mermaid
sequenceDiagram
    participant Admin as Admin Browser
    participant Primary as Primary Node API
    participant Standby as Standby Node API
    participant PrimaryDB as Primary PostgreSQL
    participant StandbyDB as Standby PostgreSQL

    Note over Admin,Standby: Step 1: Enter Standby Address
    Admin->>Primary: POST /ha/wizard/check-reachability {address}

    Note over Admin,Standby: Step 2: Verify Reachability
    Primary->>Standby: GET /api/v1/ha/heartbeat
    Standby-->>Primary: HeartbeatResponse
    Primary-->>Admin: {reachable: true, node_name, role}

    Note over Admin,Standby: Step 3: Authenticate Against Standby
    Admin->>Primary: POST /ha/wizard/authenticate {address, email, password}
    Primary->>Standby: POST /api/v1/auth/login {email, password}
    Standby-->>Primary: {access_token}
    Primary-->>Admin: {authenticated: true}

    Note over Admin,Standby: Step 4: Trust Handshake
    Admin->>Primary: POST /ha/wizard/handshake {address, standby_token}
    Primary->>Primary: Read local SSH public key from /ha_keys/
    Primary->>Primary: Read local_lan_ip, local_pg_port from DB/env/auto-detect
    Primary->>Primary: Generate HMAC secret (32 bytes)
    Primary->>Standby: POST /api/v1/ha/wizard/receive-handshake {ssh_pub_key, lan_ip, pg_port, hmac_secret}
    Note over Standby: Store primary's SSH key in authorized_keys<br/>Store HMAC secret in ha_config<br/>Return own SSH key, LAN IP, PG port
    Standby-->>Primary: {ssh_pub_key, lan_ip, pg_port}
    Primary->>Primary: Store standby's SSH key in authorized_keys
    Primary->>Primary: Store HMAC secret in ha_config
    Primary-->>Admin: {success: true, primary_ip, standby_ip, ...}

    Note over Admin,Standby: Step 5: Automated Replication Setup
    Admin->>Primary: POST /ha/wizard/setup {address, standby_token}
    Primary->>Standby: PUT /api/v1/ha/configure (role=standby, peer details)
    Primary->>Primary: Save own config (role=primary, peer details)
    Primary->>PrimaryDB: CREATE PUBLICATION orainvoice_ha_pub
    Primary->>Standby: POST /api/v1/ha/replication/init
    Standby->>StandbyDB: CREATE SUBSCRIPTION orainvoice_ha_sub
    Primary->>Primary: Configure volume sync (SSH keys, IPs, ports)
    Primary-->>Admin: {success: true, steps: [...]}
```

## Components and Interfaces

### 1. Dockerfile Changes

**File:** `Dockerfile`

Add `openssh-server` and `rsync` to the existing `apt-get install` step. Create `/run/sshd` directory required by OpenSSH daemon.

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libcairo2 \
    shared-mime-info \
    openssh-server \
    rsync \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd
```

### 2. Container Entrypoint Changes

**File:** `scripts/docker-entrypoint.sh`

The entrypoint gains three new responsibilities before the existing migration logic:

**a) Role detection via Python+asyncpg** (replaces broken `psql` command):
```bash
ROLE=$(python -c "
import asyncio, os
async def detect():
    import asyncpg
    url = os.environ.get('DATABASE_URL','').replace('+asyncpg','').replace('postgresql+asyncpg','postgresql')
    if not url: url = 'postgresql://postgres:postgres@postgres:5432/workshoppro'
    try:
        conn = await asyncpg.connect(url.replace('postgresql+asyncpg://','postgresql://'), timeout=5)
        role = await conn.fetchval('SELECT role FROM ha_config LIMIT 1')
        await conn.close()
        print(role or 'standalone')
    except Exception:
        print('standalone')
asyncio.run(detect())
" 2>/dev/null || echo "standalone")
```

**b) SSH keypair auto-generation:**
```bash
if [ ! -f /ha_keys/id_ed25519 ]; then
    ssh-keygen -t ed25519 -f /ha_keys/id_ed25519 -N "" -q
    echo "  SSH keypair generated at /ha_keys/"
fi
chmod 600 /ha_keys/id_ed25519
chmod 644 /ha_keys/id_ed25519.pub
[ -f /ha_keys/authorized_keys ] || touch /ha_keys/authorized_keys
chmod 600 /ha_keys/authorized_keys
```

**c) Host LAN IP auto-detection:**
```bash
if [ -n "$HA_LOCAL_LAN_IP" ]; then
    HOST_LAN_IP="$HA_LOCAL_LAN_IP"
else
    HOST_LAN_IP=$(ip route | awk '/default/ {print $3}' 2>/dev/null || echo "127.0.0.1")
fi
echo "$HOST_LAN_IP" > /tmp/host_lan_ip
echo "  Host LAN IP: $HOST_LAN_IP"
```

**d) Start sshd:**
```bash
cat > /etc/ssh/sshd_config.d/ha.conf <<EOF
Port 2222
AuthorizedKeysFile /ha_keys/authorized_keys
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
EOF
/usr/sbin/sshd 2>/dev/null || echo "  WARNING: sshd failed to start (non-fatal)"
```

### 3. Docker Compose Changes

**Files:** `docker-compose.yml`, `docker-compose.pi.yml`, `docker-compose.ha-standby.yml`, `docker-compose.standby-prod.yml`

All HA-capable environments get:
- Named volume `ha_keys` mounted at `/ha_keys` in the app service
- Port mapping `2222:2222` on the app service

Example addition to `docker-compose.yml` app service:
```yaml
volumes:
  - ha_keys:/ha_keys
ports:
  - "2222:2222"
```

And in the top-level volumes:
```yaml
volumes:
  ha_keys:
```

### 4. Backend API — Wizard Endpoints

**File:** `app/modules/ha/router.py` (new endpoints on `admin_router`)

All wizard endpoints require `Global_Admin` authentication.

#### `POST /ha/wizard/check-reachability`

**Request:** `{ "address": "http://192.168.1.91:8999" }`
**Response:** `{ "reachable": true, "node_name": "Standby-Pi", "role": "standalone", "is_orainvoice": true }`

Sends HTTP GET to `{address}/api/v1/ha/heartbeat` with 10s timeout. Validates the response contains expected OraInvoice heartbeat fields.

#### `POST /ha/wizard/authenticate`

**Request:** `{ "address": "http://192.168.1.91:8999", "email": "admin@example.com", "password": "..." }`
**Response:** `{ "authenticated": true, "is_global_admin": true, "token": "<jwt>" }`

Proxies login to `{address}/api/v1/auth/login`. Verifies the returned token has `global_admin` role by decoding the JWT claims. Returns the token to the frontend (held in memory only).

#### `POST /ha/wizard/handshake`

**Request:** `{ "address": "http://192.168.1.91:8999", "standby_token": "<jwt>" }`
**Response:**
```json
{
  "success": true,
  "primary_ip": "192.168.1.90",
  "primary_pg_port": 5432,
  "standby_ip": "192.168.1.91",
  "standby_pg_port": 5432,
  "hmac_secret_set": true
}
```

Steps:
1. Read local SSH public key from `/ha_keys/id_ed25519.pub`
2. Read `local_lan_ip` and `local_pg_port` from DB > env > auto-detect (existing `_detect_host_lan_ip()` + `local-db-info` logic)
3. Generate 32-byte cryptographically random HMAC secret via `secrets.token_hex(32)`
4. POST to `{address}/api/v1/ha/wizard/receive-handshake` with auth header `Bearer {standby_token}`:
   - `ssh_pub_key`, `lan_ip`, `pg_port`, `hmac_secret`
5. Receive standby's SSH public key, LAN IP, PG port in response
6. Append standby's SSH public key to local `/ha_keys/authorized_keys`
7. Store HMAC secret in local `ha_config` (encrypted via `envelope_encrypt`)
8. Log event to `ha_event_log`

#### `POST /ha/wizard/receive-handshake` (called by peer, not by browser)

**Request:** `{ "ssh_pub_key": "ssh-ed25519 AAAA...", "lan_ip": "192.168.1.90", "pg_port": 5432, "hmac_secret": "abc123..." }`
**Response:** `{ "ssh_pub_key": "ssh-ed25519 BBBB...", "lan_ip": "192.168.1.91", "pg_port": 5432 }`

Steps:
1. Append received SSH public key to `/ha_keys/authorized_keys`
2. Store HMAC secret in local `ha_config` (encrypted)
3. Read local SSH public key from `/ha_keys/id_ed25519.pub`
4. Read local LAN IP and PG port (DB > env > auto-detect)
5. Return own SSH public key, LAN IP, PG port

#### `POST /ha/wizard/setup`

**Request:** `{ "address": "http://192.168.1.91:8999", "standby_token": "<jwt>" }`
**Response:** `{ "success": true, "steps": [{"step": "configure_standby", "status": "completed"}, ...] }`

Executes the full automated setup sequence, building a step log:

1. **Configure standby node** — PUT `{address}/api/v1/ha/configure` with role=standby, peer_endpoint pointing to primary, peer DB credentials for primary's database
2. **Configure primary node** — Call `HAService.save_config()` locally with role=primary, peer_endpoint pointing to standby, peer DB credentials for standby's database
3. **Create publication** — Call `ReplicationManager.init_primary()`
4. **Create subscription on standby** — POST `{address}/api/v1/ha/replication/init?truncate_first=true`
5. **Configure volume sync** — PUT `{address}/api/v1/ha/volume-sync/config` and local volume sync config with SSH key paths, IPs, ports from handshake
6. **Start heartbeat** — Both nodes' `save_config` calls trigger heartbeat service restart

Each step returns status (completed/failed) and error message if failed. If a step fails, subsequent steps are skipped.

#### `GET /ha/events`

**Request:** Query params: `limit` (default 50), `severity` (optional filter), `event_type` (optional filter)
**Response:** `{ "events": [...], "total": N }`

Returns recent events from `ha_event_log` ordered by timestamp DESC.

### 5. Backend — HA Event Log Service

**New file:** `app/modules/ha/event_log.py`

A lightweight helper module for writing events to the `ha_event_log` table. All writes are non-blocking (wrapped in try/except).

```python
async def log_ha_event(
    event_type: str,
    severity: str,  # 'info' | 'warning' | 'error' | 'critical'
    message: str,
    details: dict | None = None,
    node_name: str | None = None,
) -> None:
    """Write an event to ha_event_log. Non-blocking — never raises."""
    try:
        from app.core.database import async_session_factory
        async with async_session_factory() as session:
            async with session.begin():
                # ... insert HAEventLog row
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Failed to write HA event: %s", exc)
```

The function uses its own short-lived session (not the request session) so it can be called from background tasks (heartbeat loop) without transaction conflicts.

### 6. Backend — Connection String Escaping

**File:** `app/modules/ha/replication.py`

New static helper method on `ReplicationManager`:

```python
@staticmethod
def _escape_conn_str(conn_str: str) -> str:
    """Escape single quotes in a connection string for SQL interpolation."""
    return conn_str.replace("'", "''")
```

Applied in `init_standby`, `trigger_resync`, and `resume_subscription` wherever `CONNECTION '{primary_conn_str}'` is used.

### 7. Frontend — Wizard UI Component

**File:** `frontend/src/pages/admin/HAReplication.tsx`

The wizard is integrated into the existing `HAReplication` component, not a separate page. It renders conditionally based on HA configuration state:

- **No HA config exists** → Show wizard as primary content
- **HA config exists but broken** → Show warning banner + "Resume" / "Fresh Setup" buttons
- **HA fully configured and healthy** → Show existing monitoring UI

#### Wizard Steps Component

```typescript
interface WizardStep {
  id: number
  title: string
  status: 'pending' | 'active' | 'completed' | 'failed'
}

const WIZARD_STEPS: WizardStep[] = [
  { id: 1, title: 'Enter Standby Address', status: 'pending' },
  { id: 2, title: 'Verify Reachability', status: 'pending' },
  { id: 3, title: 'Authenticate', status: 'pending' },
  { id: 4, title: 'Trust Handshake', status: 'pending' },
  { id: 5, title: 'Setup Replication', status: 'pending' },
]
```

Each step renders its own form/status UI. The step indicator shows all 5 steps with checkmarks for completed, spinner for active, and dimmed for pending.

#### Event Log Table Component

A new section below the existing monitoring UI showing recent HA events:

```typescript
interface HAEvent {
  id: string
  timestamp: string
  event_type: string
  severity: 'info' | 'warning' | 'error' | 'critical'
  message: string
  details: Record<string, unknown> | null
  node_name: string
}
```

Filterable by severity and event type. Color-coded severity badges (green=info, yellow=warning, red=error, purple=critical). Default shows last 50 events, with "Load More" pagination.

### 8. Pydantic Schemas

**File:** `app/modules/ha/schemas.py` (additions)

```python
class WizardCheckReachabilityRequest(BaseModel):
    address: str

class WizardCheckReachabilityResponse(BaseModel):
    reachable: bool
    node_name: str | None = None
    role: str | None = None
    is_orainvoice: bool = False
    error: str | None = None

class WizardAuthenticateRequest(BaseModel):
    address: str
    email: str
    password: str

class WizardAuthenticateResponse(BaseModel):
    authenticated: bool
    is_global_admin: bool = False
    token: str | None = None
    error: str | None = None

class WizardHandshakeRequest(BaseModel):
    address: str
    standby_token: str

class WizardHandshakeResponse(BaseModel):
    success: bool
    primary_ip: str | None = None
    primary_pg_port: int | None = None
    standby_ip: str | None = None
    standby_pg_port: int | None = None
    hmac_secret_set: bool = False
    error: str | None = None

class WizardReceiveHandshakeRequest(BaseModel):
    ssh_pub_key: str
    lan_ip: str
    pg_port: int = 5432
    hmac_secret: str

class WizardReceiveHandshakeResponse(BaseModel):
    ssh_pub_key: str
    lan_ip: str
    pg_port: int

class WizardSetupRequest(BaseModel):
    address: str
    standby_token: str

class WizardSetupStepResult(BaseModel):
    step: str
    status: str  # 'completed' | 'failed' | 'skipped'
    message: str | None = None
    error: str | None = None

class WizardSetupResponse(BaseModel):
    success: bool
    steps: list[WizardSetupStepResult] = []
    error: str | None = None

class HAEventResponse(BaseModel):
    id: str
    timestamp: str
    event_type: str
    severity: str
    message: str
    details: dict | None = None
    node_name: str

class HAEventListResponse(BaseModel):
    events: list[HAEventResponse] = []
    total: int = 0
```

## Data Models

### New Table: `ha_event_log`

**File:** New model in `app/modules/ha/models.py`

```python
class HAEventLog(Base):
    __tablename__ = "ha_event_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # heartbeat_failure, role_change, replication_error, split_brain, auto_promote, volume_sync_error, config_change, recovery
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # info, warning, error, critical
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
```

**Indexes:**
- `ix_ha_event_log_timestamp` on `timestamp DESC` for efficient recent-first queries
- `ix_ha_event_log_event_type` on `event_type` for filtered queries
- `ix_ha_event_log_severity` on `severity` for filtered queries

**Migration notes:**
- Table must be excluded from the replication publication (add to the exclusion list alongside `ha_config` and `dead_letter_queue` in `ReplicationManager.init_primary()`)
- 30-day auto-prune: a cleanup query runs in the heartbeat loop every ~24 hours (tracked by a monotonic timestamp), deleting rows where `timestamp < now() - interval '30 days'`

### Existing Table Modifications

No new columns are added to `ha_config`. The existing `local_lan_ip` and `local_pg_port` columns (from the ha-gui-config-cleanup spec) are used by the wizard's trust handshake.


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Address validation accepts valid addresses and rejects invalid ones

*For any* string input to the wizard address validator, the function SHALL return `true` if and only if the input is a non-empty string containing a valid IPv4 address, IPv6 address, hostname, or URL with a hostname component; and SHALL return `false` for empty strings, whitespace-only strings, and strings that do not contain a valid network address.

**Validates: Requirements 4.2**

### Property 2: HMAC secret generation produces cryptographically strong secrets

*For any* invocation of the HMAC secret generator, the resulting secret SHALL be at least 32 bytes (64 hex characters) in length, and for any two independent invocations, the generated secrets SHALL be distinct (with overwhelming probability).

**Validates: Requirements 7.6, 16.2**

### Property 3: All wizard endpoints reject unauthenticated requests

*For any* wizard API endpoint (check-reachability, authenticate, handshake, receive-handshake, setup, events), calling the endpoint without a valid Global_Admin authentication token SHALL return HTTP 401 or 403.

**Validates: Requirements 10.6, 16.1**

### Property 4: Trust handshake is idempotent for authorized_keys

*For any* SSH public key and any number of repeated trust handshake executions with that same key, the `/ha_keys/authorized_keys` file SHALL contain exactly one entry for that key (no duplicates), and the file SHALL remain a valid OpenSSH authorized_keys format.

**Validates: Requirements 15.2**

### Property 5: Role transitions update heartbeat service local_role

*For any* valid role transition (standby→primary via promote, primary→standby via demote, primary→standby via demote_and_sync), after the transition completes, the HeartbeatService's `local_role` attribute SHALL equal the new role string.

**Validates: Requirements 19.1, 19.2, 19.3**

### Property 6: Auto-promote flag resets when peer recovers

*For any* sequence where the peer transitions from unreachable to reachable in the heartbeat loop, `_auto_promote_attempted` SHALL be reset to `False`, while `_auto_promote_failed_permanently` SHALL remain unchanged.

**Validates: Requirements 23.1, 23.2, 23.3**

### Property 7: HA secret functions have no environment variable fallback

*For any* call to `_get_heartbeat_secret_from_config()` with a `None` or invalid DB secret, the function SHALL return an empty string regardless of the value of the `HA_HEARTBEAT_SECRET` environment variable. Similarly, `get_peer_db_url()` SHALL return `None` when DB peer config is empty, regardless of the `HA_PEER_DB_URL` environment variable.

**Validates: Requirements 26.1, 26.2**

### Property 8: Connection string escaping produces valid SQL

*For any* connection string containing single quotes, backslashes, or other SQL-special characters, the `_escape_conn_str()` function SHALL produce a string that, when wrapped in single quotes in a SQL `CONNECTION` clause, results in syntactically valid SQL. Specifically, every single quote in the input SHALL be doubled (`'` → `''`).

**Validates: Requirements 33.1, 33.2, 33.3**

### Property 9: ha_event_log is excluded from replication publication

*For any* publication created by `ReplicationManager.init_primary()`, the set of published tables SHALL NOT include `ha_event_log`, `ha_config`, or `dead_letter_queue`.

**Validates: Requirements 34.2**

### Property 10: Event pruning removes only events older than 30 days

*For any* set of `ha_event_log` rows with varying timestamps, after the pruning operation executes, no rows with `timestamp` older than 30 days from the current time SHALL remain, and all rows with `timestamp` within the last 30 days SHALL be preserved.

**Validates: Requirements 34.9**

## Error Handling

### Infrastructure Layer

| Error | Handling | Requirement |
|---|---|---|
| SSH keygen fails | Log error, continue startup — sshd won't work but app runs | 1.1 |
| sshd fails to start | Log warning, continue — volume sync unavailable but app runs | 3.4 |
| LAN IP detection fails | Fall back to `127.0.0.1`, log warning | 2.4 |
| Role detection DB unreachable | Fall back to "standalone", run migrations (safe default) | 32.4 |

### Wizard Flow

| Error | Handling | Requirement |
|---|---|---|
| Standby unreachable (timeout) | Display "Node unreachable" error, allow retry/edit address | 5.3 |
| Standby not OraInvoice | Display "Not an OraInvoice node" error | 5.4 |
| Auth fails (401) | Display "Invalid credentials" error, allow retry | 6.4 |
| Auth succeeds but not Global_Admin | Display "Global_Admin required" error | 6.5 |
| Handshake step fails | Display which step failed, allow retry | 7.9 |
| Setup step fails | Display error in setup log, stop further steps, allow retry from failed step | 8.8 |
| Connection string has special chars | `_escape_conn_str()` doubles single quotes before SQL interpolation | 33.1 |

### Event Log

| Error | Handling | Requirement |
|---|---|---|
| Event write fails | try/except, log to stderr, never crash the calling operation | 34.10 |
| Event log DB unavailable | Same as above — silent fallback to stderr logging | 34.10 |
| Event log table full (>30 days) | Periodic prune in heartbeat loop deletes old rows | 34.9 |

### Existing HA Operations (Bug Fixes — Already Fixed)

| Error | Handling | Requirement |
|---|---|---|
| Orphaned replication slot on resync | `_cleanup_orphaned_slot_on_peer()` called between drop and create | 18.1 |
| Heartbeat local_role stale after promote/demote | `_heartbeat_service.local_role` updated in promote/demote/demote_and_sync | 19.1-19.3 |
| drop_replication_slot missing DB session | `db: AsyncSession = Depends(get_db_session)` added | 20.1 |
| HeartbeatService restart without Redis lock | Redis lock fields wired to new instance in save_config | 21.1 |
| demote() copy_data=true on full dataset | `copy_data = false` in resume_subscription fallback; publication dropped | 22.1-22.3 |
| _auto_promote_attempted stuck True | Reset to False when peer recovers | 23.1 |

## Testing Strategy

### Property-Based Tests (Hypothesis)

The project already uses Hypothesis for property-based testing. Each correctness property maps to a Hypothesis test with minimum 100 iterations.

**Library:** `hypothesis` (already installed)
**Location:** `tests/properties/test_ha_wizard_properties.py`
**Configuration:** `@settings(max_examples=100)`

| Property | Test Function | What It Generates |
|---|---|---|
| 1: Address validation | `test_address_validation_property` | Random strings, valid IPs, valid hostnames, empty strings, whitespace |
| 2: HMAC secret generation | `test_hmac_secret_generation_property` | N/A (tests output of generator) |
| 3: Auth requirement | `test_wizard_endpoints_require_auth` | List of wizard endpoint paths |
| 4: Handshake idempotency | `test_handshake_idempotent_authorized_keys` | Random SSH public keys, random repeat counts (1-10) |
| 5: Role transition updates local_role | `test_role_transition_updates_heartbeat` | Random role transitions from valid set |
| 6: Auto-promote flag reset | `test_auto_promote_flag_reset_on_recovery` | Random sequences of unreachable/reachable transitions |
| 7: No env fallback | `test_no_env_fallback_for_secrets` | Random env var values |
| 8: Connection string escaping | `test_conn_str_escaping_produces_valid_sql` | Random strings with single quotes, backslashes, special chars |
| 9: Publication excludes ha_event_log | `test_publication_excludes_event_log` | N/A (tests actual publication table list) |
| 10: Event pruning | `test_event_pruning_preserves_recent` | Random event timestamps spanning 0-60 days ago |

**Tag format:** Each test includes a docstring comment:
```python
# Feature: ha-setup-wizard, Property 1: Address validation accepts valid addresses and rejects invalid ones
```

### Unit Tests (pytest)

**Location:** `tests/unit/test_ha_wizard.py`

- Address validation edge cases (empty, whitespace, localhost, IPv6, URLs with ports)
- HMAC secret length and hex format
- Connection string escaping with known inputs (`O'Brien`, `back\\slash`, `semi;colon`)
- Event log helper non-blocking behavior (mock DB failure, verify no exception propagates)
- Wizard step state machine transitions

### E2E Test Script

**Location:** `scripts/test_ha_wizard_e2e.py`

Per the feature-testing-workflow steering doc, a comprehensive E2E script that:

1. Logs in as Global_Admin
2. Calls check-reachability (mock or real standby)
3. Calls authenticate against standby
4. Calls handshake
5. Calls setup
6. Verifies ha_config on both nodes
7. Verifies replication publication exists
8. Verifies ha_event_log has entries
9. Verifies event log API returns events
10. Tests auth rejection (no token → 401/403)
11. Cleans up test data

### Integration Tests

- Docker Compose validation: parse all compose files, verify `ha_keys` volume and port 2222 mapping
- Dockerfile validation: verify `openssh-server` and `rsync` in apt-get install
- Entrypoint role detection: test with standby ha_config row, verify migrations skipped
- Replication publication exclusion: after init_primary, verify ha_event_log not in pg_publication_tables

### Verification Tests (Requirements 18-29)

These requirements are already fixed. Tests confirm the fixes remain correct:

| Requirement | Test | Type |
|---|---|---|
| 18: trigger_resync orphaned slot | Verify `_cleanup_orphaned_slot_on_peer` is called in trigger_resync | Unit (mock) |
| 19: promote/demote local_role | Verify heartbeat local_role updated after each transition | Unit |
| 20: drop_replication_slot DB session | Verify endpoint has `Depends(get_db_session)` | Unit (inspect) |
| 21: save_config Redis lock wiring | Verify new HeartbeatService has Redis lock fields | Unit (mock) |
| 22: demote copy_data + publication | Verify resume_subscription uses `copy_data = false` | Unit (mock) |
| 23: _auto_promote_attempted reset | Verify flag reset on peer recovery | Unit |
| 24: Dev standby compose settings | Parse compose file, verify settings present | Unit |
| 25: Leaked credentials | Read env files, verify empty values | Unit |
| 26: No env fallback | Call functions with env set, verify no fallback | Unit |
| 27: Peer role display | Verify schema has peer_role field | Unit |
| 28: stop-replication confirm | Verify needsConfirmText includes stop-replication | Unit |
| 29: Setup guide text | Verify no .env references in setup guide | Unit |


### Local Two-Stack Integration Test (Requirements 35-37)

The integration test uses two Docker Compose stacks running simultaneously on the same host:

**Primary stack** (existing dev):
- Project: `orainvoice` (default)
- Ports: 80 (nginx), 5434 (postgres), 6379 (redis), 2222 (sshd)
- Compose: `docker-compose.yml` + `docker-compose.dev.yml`

**Standby stack** (existing ha-standby):
- Project: `invoicing-standby`
- Ports: 8081 (nginx), 5433 (postgres), 6380 (redis), 2223 (sshd)
- Compose: `docker-compose.ha-standby.yml`

**Port mapping for standby sshd**: The `docker-compose.ha-standby.yml` maps `2223:2222` (host port 2223 → container port 2222) to avoid conflict with the primary's `2222:2222`.

**Test procedure:**

1. Rebuild both stacks from scratch:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --force-recreate
   docker compose -p invoicing-standby -f docker-compose.ha-standby.yml up -d --build --force-recreate
   ```

2. Verify startup logs on both stacks:
   ```bash
   docker logs invoicing-app-1 --tail 20  # Primary
   docker logs invoicing-standby-app-1 --tail 20  # Standby
   ```
   Expected: SSH keypair generated, host LAN IP detected, sshd started, migrations run.

3. Navigate to `http://localhost/admin/ha-replication` (primary) and complete the wizard:
   - Step 1: Enter standby address `http://{host_lan_ip}:8081`
   - Step 2: Verify reachability (should show standby node info)
   - Step 3: Authenticate with standby's Global_Admin credentials
   - Step 4: Trust handshake (SSH keys + HMAC exchanged)
   - Step 5: Start automated setup (publication, subscription, volume sync)

4. Verify replication works:
   - Create a test customer on the primary
   - Check the standby's database for the replicated customer (within 10 seconds)
   - Verify heartbeat history shows successful pings on both nodes
   - Verify `ha_event_log` has wizard setup events

5. Verify recovery options:
   - Stop the standby stack
   - Verify the primary shows "Standby unreachable" warning
   - Restart the standby stack
   - Verify heartbeat recovers and replication resumes

**Bug fix loop**: Any error encountered during steps 1-5 is fixed immediately, the full test is re-run from step 1, and the root cause is documented in the appropriate steering doc.

**Version check**: During step 2, the wizard displays both nodes' versions. If they differ, a warning is shown but setup proceeds.

### Steering Doc Update Protocol

When a bug is found and fixed during integration testing, the fix is documented in the appropriate steering file:

| Bug Category | Steering File | Example Rule |
|---|---|---|
| Docker port conflict | `.kiro/steering/deployment-environments.md` | "HA standby sshd must use port 2223 to avoid conflict with primary's 2222" |
| Entrypoint failure | `.kiro/steering/deployment-environments.md` | "Use Python+asyncpg for DB queries in entrypoint, not psql" |
| Frontend API mismatch | `.kiro/steering/frontend-backend-contract-alignment.md` | "Wizard endpoints return {success, error} — always check success before proceeding" |
| Migration not applied | `.kiro/steering/database-migration-checklist.md` | "After adding ha_event_log migration, run on BOTH dev and standby stacks" |
| SSH key permission | New `.kiro/steering/ha-infrastructure.md` | "SSH keys must be 600 (private) and 644 (public) — sshd refuses to start otherwise" |
| Replication DDL timeout | `.kiro/steering/performance-and-resilience.md` | "Replication DDL disables statement_timeout — never run inside a timed session" |
