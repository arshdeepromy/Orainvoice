# High Availability (HA) Replication Guide

OraInvoice supports active-standby HA using PostgreSQL logical replication. The primary node handles all read/write traffic while the standby receives real-time data replication. If the primary goes down, the standby can be promoted to primary.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Local Dev Environment Setup](#local-dev-environment-setup)
3. [PostgreSQL SSL Configuration](#postgresql-ssl-configuration)
4. [Replication User Management](#replication-user-management)
5. [Production Deployment Guide](#production-deployment-guide)
6. [Frontend Admin Guide](#frontend-admin-guide)
7. [Network and VPN Requirements](#network-and-vpn-requirements)
8. [Database Password and Security Considerations](#database-password-and-security-considerations)
9. [Failover and Recovery Procedures](#failover-and-recovery-procedures)
10. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────┐         Heartbeat (HTTP)        ┌─────────────────────┐
│   PRIMARY NODE      │◄──────────────────────────────►│   STANDBY NODE      │
│                     │                                 │                     │
│  nginx (:80/8999)   │                                 │  nginx (:80/8999)   │
│  app (FastAPI)      │                                 │  app (FastAPI)      │
│  postgres           │──── Logical Replication ──────►│  postgres           │
│  redis              │                                 │  redis              │
└─────────────────────┘                                 └─────────────────────┘
```

- PostgreSQL logical replication streams changes from primary to standby in real-time
- Heartbeat service on each node pings the peer every N seconds (configurable, default 10s)
- Heartbeat responses are HMAC-signed with a shared secret to prevent spoofing
- Standby node blocks all write operations except authentication (login, token refresh, logout) and HA management endpoints
- Redis is NOT replicated — each node has its own Redis instance for sessions/cache

---

## Local Dev Environment Setup

The local dev setup runs two complete stacks on the same machine using Docker Compose with separate project names, ports, and volumes.

### Stack Layout

| Component | Primary | Standby |
|-----------|---------|---------|
| Project name | `invoicing` | `invoicing-standby` |
| Compose files | `docker-compose.yml` + `docker-compose.dev.yml` | `docker-compose.ha-standby.yml` |
| Env file | `.env` | `.env.ha-standby` |
| Nginx port | 80 | 8081 |
| Postgres port | 5434 (host) | 5433 (host) |
| Redis port | 6379 | 6380 |
| URL | `http://localhost` | `http://localhost:8081` |

### Important: Postgres Port Conflict

The primary dev postgres is mapped to host port **5434** (not 5432) in `docker-compose.dev.yml` to avoid conflicts with any local PostgreSQL installation on the host machine. If you have a local PostgreSQL running on port 5432, connections via `host.docker.internal:5432` would hit the local instance instead of the Docker container.

### Step-by-Step Dev Setup

#### 1. Start the Primary Stack

```bash
docker compose -p invoicing up --build -d
```

#### 2. Run Migrations on Primary

```bash
docker exec invoicing-app-1 alembic upgrade head
```

#### 3. Seed Primary Database

```bash
docker exec invoicing-app-1 python scripts/seed_all_dev.py
```

#### 4. Start the Standby Stack

```bash
docker compose -p invoicing-standby -f docker-compose.ha-standby.yml up --build -d
```

#### 5. Run Migrations on Standby

```bash
docker exec invoicing-standby-app-1 alembic upgrade head
```

**Do NOT seed the standby database.** All data will come from the primary via replication. Seeding the standby creates duplicate rows that conflict with replicated data.

#### 6. Configure HA via the Frontend

1. Open the primary at `http://localhost` and log in as `admin@orainvoice.com`
2. Go to Admin > HA Replication
3. Configure:
   - Node Name: `Primary-Local`
   - Role: `Primary`
   - Peer Endpoint: `http://host.docker.internal:8081`
   - Heartbeat Interval: 10s
   - Failover Timeout: 30s
4. Click "Save Configuration"
5. Click "Initialize Replication" (creates the publication)

6. Open the standby at `http://localhost:8081` and log in as `admin@orainvoice.com`
7. Go to Admin > HA Replication
8. Configure:
   - Node Name: `Standby-Local`
   - Role: `Standby`
   - Peer Endpoint: `http://host.docker.internal:80`
   - Heartbeat Interval: 10s
   - Failover Timeout: 30s
   - Auto-promote: enabled (optional)
9. Click "Save Configuration"
10. Click "Initialize Replication" (creates the subscription, starts data sync)

#### 7. Verify Replication

- Check the Replication Details section on both nodes
- Primary should show: Publication = `orainvoice_ha_pub`, Tables Published > 0
- Standby should show: Subscription = `orainvoice_ha_sub`, Status = active
- Heartbeat history should show green/healthy on both nodes
- Verify data: org users, plans, and all other data should match between nodes

### Dev Environment Variables

**Primary `.env`** — add these:
```env
HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing
HA_PEER_DB_URL=postgresql://postgres:postgres@host.docker.internal:5433/workshoppro
```

**Standby `.env.ha-standby`** — already configured:
```env
HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing
HA_PEER_DB_URL=postgresql://postgres:postgres@host.docker.internal:5434/workshoppro
```

### Rebuilding Dev Environment from Scratch

If you need to tear down and rebuild:

```bash
# Stop and remove everything
docker compose -p invoicing down -v
docker compose -p invoicing-standby -f docker-compose.ha-standby.yml down -v

# Rebuild primary
docker compose -p invoicing up --build -d
docker exec invoicing-app-1 alembic upgrade head
docker exec invoicing-app-1 python scripts/seed_all_dev.py

# Rebuild standby (NO seeding)
docker compose -p invoicing-standby -f docker-compose.ha-standby.yml up --build -d
docker exec invoicing-standby-app-1 alembic upgrade head

# Then configure HA via the frontend (steps 6-10 above)
```

### Known Dev Gotchas

- **Do not seed the standby.** Replication copies all data from primary. Seeding creates duplicates.
- **Use `host.docker.internal`** for peer endpoints and `HA_PEER_DB_URL`, not `localhost`. Inside a Docker container, `localhost` refers to the container itself.
- **Primary postgres is on port 5434** (not 5432) to avoid conflicts with local PostgreSQL installations.
- **Containers must be recreated** after adding new env vars (e.g. `HA_HEARTBEAT_SECRET`). A simple restart won't pick up new `.env` values — use `docker compose up -d` to recreate.
- **PostgreSQL `wal_level=logical`** is required on both nodes. This is already set in both compose files.

---

## PostgreSQL SSL Configuration

Both primary and standby PostgreSQL instances support SSL encryption for replication and client connections. Self-signed certificates are sufficient for database-to-database communication over a VPN.

### How SSL Works in This Setup

- A private Certificate Authority (CA) is generated locally
- Each node (primary and standby) gets its own server certificate signed by the CA
- The CA cert is shared between nodes so they can verify each other
- Docker containers copy certs at startup via `pg-ssl-entrypoint.sh` (needed because Windows Docker mounts don't preserve Unix file permissions)

### Generating Certificates

Run the cert generation script from the project root:

```bash
bash scripts/generate_pg_certs.sh
```

This creates:

```
certs/pg/
  ca.crt              — CA certificate (shared between nodes)
  ca.key              — CA private key (keep secure)
  primary/
    server.crt        — Primary server certificate
    server.key        — Primary server private key
  standby/
    server.crt        — Standby server certificate
    server.key        — Standby server private key
```

Certificates are valid for 10 years (dev). Use shorter validity for production.

The `certs/` directory is gitignored — each deployment generates its own certs.

### Docker Compose SSL Integration

Both `docker-compose.yml` and `docker-compose.ha-standby.yml` are pre-configured to:

1. Mount certs at `/pg-certs/` (read-only) in the postgres container
2. Run `pg-ssl-entrypoint.sh` as the container entrypoint, which copies certs to `/var/lib/postgresql/ssl/` with correct ownership and permissions
3. Pass postgres flags: `ssl=on`, `ssl_cert_file`, `ssl_key_file`, `ssl_ca_file`

After generating certs, recreate the postgres containers:

```bash
# Primary
docker compose -p invoicing up -d postgres

# Standby
docker compose -p invoicing-standby -f docker-compose.ha-standby.yml up -d postgres
```

Verify SSL is enabled:

```bash
# Primary
docker exec invoicing-postgres-1 psql -U postgres -c "SHOW ssl;"
# Should return: on

# Standby
docker exec invoicing-standby-postgres-1 psql -U postgres -c "SHOW ssl;"
# Should return: on
```

### SSL Mode Options

The peer database connection supports four SSL modes, configurable in the HA admin UI under "Peer Database Settings":

| Mode | Encryption | Cert Verification | When to Use |
|------|-----------|-------------------|-------------|
| `disable` | No | No | Local dev without certs |
| `require` | Yes | No | Dev with certs, or production over VPN |
| `verify-ca` | Yes | CA only | Production — verifies server cert is signed by trusted CA |
| `verify-full` | Yes | CA + hostname | Strictest — also verifies server hostname matches cert CN/SAN |

For local dev, `require` is recommended once certs are generated. For production over a VPN, `verify-ca` provides a good balance of security and simplicity.

### Production SSL Notes

- For production, generate certs on each server independently or distribute from a central CA
- The CA cert (`ca.crt`) must be available on both nodes
- Server keys (`server.key`) should never leave their respective servers
- Consider using shorter certificate validity (1-2 years) and rotating before expiry
- If using `verify-full`, ensure the server certificate CN or SAN matches the hostname/IP used in the connection string

---

## Replication User Management

For production, use a dedicated PostgreSQL user with minimal privileges instead of the superuser.

### Creating a Replication User via the UI

1. Open the HA Replication page on the node whose database the peer will connect to
2. In the "Replication User" section, enter a username (default: `replicator`) and a strong password
3. Click "Create / Update User"
4. The user is created with `REPLICATION` + `LOGIN` privileges and `SELECT` on all public tables
5. Use this username and password in the peer node's "Peer Database Settings"

### Creating a Replication User via SQL

Alternatively, run the provided SQL script on the primary:

```bash
docker exec -i invoicing-postgres-1 psql -U postgres -d workshoppro -f /app/scripts/create_replication_user.sql
```

Or use the script directly:

```sql
CREATE USER replicator WITH REPLICATION LOGIN PASSWORD '<strong-password>';
GRANT USAGE ON SCHEMA public TO replicator;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO replicator;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO replicator;
```

### Privileges Explained

| Privilege | Why |
|-----------|-----|
| `REPLICATION` | Required for PostgreSQL logical replication subscriptions |
| `LOGIN` | Allows the user to authenticate |
| `SELECT ON ALL TABLES` | Logical replication reads table data for initial copy and ongoing changes |
| `DEFAULT PRIVILEGES` | Ensures future tables are also readable by the replication user |

### Using the Replication User

After creating the user on the primary, configure the standby's peer DB settings:

1. On the standby's HA Replication page, go to "Peer Database Settings"
2. Set Host, Port, Database Name to the primary's PostgreSQL
3. Set User to `replicator` (or whatever username you chose)
4. Set Password to the replication user's password
5. Set SSL Mode to `require` (or higher for production)
6. Click "Test Connection" to verify
7. Click "Update Configuration" to save

The stored credentials are encrypted at rest using the application's envelope encryption. The password is never returned by the API — only a `peer_db_configured: true` flag indicates credentials are stored.

### Peer DB Settings Storage

Peer database connection details are stored in the `ha_config` table, which is excluded from replication. This means each node maintains its own independent peer connection settings — the primary stores how to reach the standby's database, and vice versa. Fields stored:

- `peer_db_host`, `peer_db_port`, `peer_db_name`, `peer_db_user` — stored as plaintext
- `peer_db_password` — encrypted via `envelope_encrypt` (AES-256)
- `peer_db_sslmode` — stored as plaintext (default: `disable`)

If no peer DB settings are stored, the system falls back to the `HA_PEER_DB_URL` environment variable.

---

## Production Deployment Guide

Production HA involves two separate physical machines (e.g. Raspberry Pi nodes) deployed at different physical locations, connected via VPN. Each node runs its own independent Docker stack. The standby is never co-located with the primary — that defeats the purpose of disaster recovery.

> **Important:** Do NOT run the standby stack on the same host as the primary. The `docker-compose.ha-standby.yml` file is for local dev testing only. In production, each node is a separate machine at a separate location, each running the standard `docker-compose.yml` + its own Pi override file.

### Architecture

```
Location A (e.g. Office)              Location B (e.g. DR site)
┌──────────────────────┐              ┌──────────────────────┐
│  PRIMARY Pi          │    VPN       │  STANDBY Pi          │
│  192.168.1.90        │◄────────────►│  192.168.x.x         │
│                      │              │                      │
│  docker-compose.yml  │  Logical     │  docker-compose.yml  │
│  + pi.yml override   │  Replication │  + pi.yml override   │
│                      │──────────────►                      │
│  SSL certs (server)  │  (replicator │  SSL certs (server)  │
│  + CA cert           │   account)   │  + CA cert           │
└──────────────────────┘              └──────────────────────┘
```

- SSL certificates secure the replicator DB connection between locations
- Each node has its own server cert; both share the same CA cert for mutual trust
- The replicator PostgreSQL user has minimal privileges (REPLICATION + SELECT)

### Prerequisites

- Two servers at different physical locations with Docker and Docker Compose installed
- VPN connection between both servers (both must be reachable via LAN IPs)
- Same codebase deployed on both servers
- Same database schema (alembic migrations) on both servers
- Unique strong passwords for PostgreSQL on each server
- SSL certificates generated on each server (shared CA cert)

### Step 0: Generate SSL Certificates

On each server, generate SSL certificates:

```bash
bash scripts/generate_pg_certs.sh
```

Copy the `ca.crt` from one server to the other so both have the same CA. Each server keeps its own `server.crt` and `server.key` — these never leave their respective hosts.

### Step 1: Deploy the Primary Node

The primary node is your existing production server. It should already be running.

1. Ensure `wal_level=logical` and SSL flags are set in the postgres command in your compose file
2. Add HA environment variables to the primary's `.env`:
   ```env
   HA_HEARTBEAT_SECRET=<generate-a-strong-random-secret>
   HA_PEER_DB_URL=postgresql://<standby_pg_user>:<standby_pg_password>@<standby_lan_ip>:<standby_pg_port>/<db_name>?sslmode=require
   ```
3. Rebuild and restart the primary:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.pi.yml up --build -d
   ```
4. Create a dedicated replication user via the HA admin UI or SQL (see [Replication User Management](#replication-user-management))

### Step 2: Deploy the Standby Node (Separate Server at a Different Location)

The standby runs on a completely separate machine at a different physical location. It uses the same `docker-compose.yml` + a Pi override — NOT the `docker-compose.ha-standby.yml` (that file is for local dev only).

1. Set up the new server with Docker and Docker Compose
2. Clone/copy the codebase to the new server
3. Create the standby's `.env` file with:
   - Same `JWT_SECRET`, `JWT_ALGORITHM`, `ENCRYPTION_MASTER_KEY` as primary (so tokens work across nodes)
   - Same `HA_HEARTBEAT_SECRET` as primary
   - `HA_PEER_DB_URL` pointing to the primary's PostgreSQL (using the replicator account over SSL):
     ```env
     HA_PEER_DB_URL=postgresql://replicator:<replicator_password>@<primary_lan_ip>:<primary_pg_port>/<db_name>?sslmode=require
     ```
   - Unique `POSTGRES_PASSWORD` for this server's local PostgreSQL
4. Use the standard compose files with a Pi override:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.pi.yml up --build -d
   ```
5. Run migrations:
   ```bash
   docker exec <standby-app-container> alembic upgrade head
   ```
6. **Do NOT seed the standby database.** All data comes from replication.

### Step 3: Configure HA via the Frontend

1. Log in to the **primary** as a Global Admin
2. Navigate to Admin > HA Replication
3. Configure the primary node (name, role=Primary, peer endpoint = standby's URL)
4. Click "Initialize Replication" to create the publication

5. Log in to the **standby** as a Global Admin
6. Navigate to Admin > HA Replication
7. Configure the standby node (name, role=Standby, peer endpoint = primary's URL)
8. Configure Peer Database Settings with the replicator credentials and SSL mode
9. Click "Initialize Replication" to create the subscription and start data sync

### Step 4: Verify

- Check Replication Details on both nodes
- Verify heartbeat is healthy (green) on both nodes
- Create a test record on the primary and verify it appears on the standby within seconds
- Check replication lag is < 1s under normal conditions

---

## Frontend Admin Guide

The HA Replication page is accessible to Global Admin users at **Admin > HA Replication**.

### Configuration Section

| Field | Description |
|-------|-------------|
| Node Name | A friendly name for this node (e.g. "Pi-Main", "Pi-DR") |
| Role | `Primary` (accepts writes), `Standby` (read-only replica), or `Standalone` (no HA) |
| Peer Endpoint | The HTTP URL of the other node's API (e.g. `http://192.168.1.91:8999`) |
| Heartbeat Interval | How often to ping the peer (seconds). Default: 10 |
| Failover Timeout | How long the peer must be unreachable before auto-promote triggers (seconds). Default: 90 |
| Auto-promote | If enabled on a standby, it will automatically promote to primary when the peer is unreachable for longer than the failover timeout |

### Peer Database Settings Section

| Field | Description |
|-------|-------------|
| Host | Peer PostgreSQL hostname or IP (e.g. `host.docker.internal` for dev, LAN IP for production) |
| Port | Peer PostgreSQL port (default: 5432) |
| Database Name | Peer database name (e.g. `workshoppro`) |
| User | Database user for replication (e.g. `replicator`) |
| Password | Database password (encrypted at rest, never returned by API) |
| SSL Mode | `disable`, `require`, `verify-ca`, or `verify-full` |
| Test Connection | Verifies connectivity, checks `wal_level`, and reports SSL status |

Credentials are saved when you click "Update Configuration" in the main config section above. Test the connection first, then save.

### Replication User Section

| Field | Description |
|-------|-------------|
| Username | PostgreSQL username to create (default: `replicator`) |
| Password | Password for the new user |
| Create / Update User | Creates the user on the local database with REPLICATION + SELECT privileges |

Run this on the node whose database the peer will connect to. Then use the created credentials in the peer node's "Peer Database Settings".

### Actions

| Action | When to Use |
|--------|-------------|
| Initialize Replication | After configuring both nodes. Run on primary first (creates publication), then on standby (creates subscription). |
| Promote to Primary | On the standby node when you want it to become the new primary. Requires typing "CONFIRM" and a reason. |
| Demote to Standby | On the primary node when you want it to become a standby. Requires typing "CONFIRM" and a reason. |
| Trigger Re-sync | When replication is broken or data is inconsistent. Drops and re-creates the subscription with a full data copy. |
| Enter Maintenance Mode | Before updating the node. The heartbeat will report maintenance status to the peer. |
| Exit Maintenance Mode | After updating the node. Resumes normal heartbeat reporting. |

### What the Admin Must Verify Before Setup

1. **Network connectivity**: Both nodes must be able to reach each other via HTTP (for heartbeat) and PostgreSQL (for replication). Use LAN IPs through VPN.
2. **PostgreSQL port accessibility**: The PostgreSQL port on each node must be accessible from the other node. Verify with `psql` or `pg_isready` from the peer.
3. **SSL certificates**: Generate certs with `scripts/generate_pg_certs.sh` and verify SSL is enabled (`SHOW ssl;` returns `on`).
4. **Matching secrets**: `JWT_SECRET`, `ENCRYPTION_MASTER_KEY`, and `HA_HEARTBEAT_SECRET` must be identical on both nodes.
5. **Database schema**: Both nodes must be on the same alembic migration revision before initializing replication.
6. **Empty standby**: The standby database should have the schema (migrations) but NO seed data. All data comes from replication.
7. **Replication user**: Create a dedicated replication user on each node via the UI or SQL before configuring peer DB settings.

---

## Network and VPN Requirements

### Why VPN is Required

PostgreSQL replication streams data over a direct TCP connection between the two database servers. This connection must be:
- Reliable (low latency, stable)
- Secure (encrypted, not exposed to the public internet)
- Directly routable (no NAT traversal issues)

A site-to-site VPN (e.g. WireGuard, Tailscale, OpenVPN) provides all of these.

### Network Checklist

1. **VPN is active** between both servers
2. **LAN IPs are reachable**: From each server, you can ping the other's VPN/LAN IP
   ```bash
   ping 192.168.1.91  # from primary to standby
   ping 192.168.1.90  # from standby to primary
   ```
3. **PostgreSQL port is open**: The PostgreSQL port (default 5432, or whatever is mapped) must be accessible through the VPN
   ```bash
   # From standby, test connection to primary's postgres
   pg_isready -h 192.168.1.90 -p 5432
   # Or from inside the Docker container
   docker exec <app-container> python -c "import asyncio, asyncpg; asyncio.run(asyncpg.connect('postgresql://user:pass@192.168.1.90:5432/workshoppro'))"
   ```
4. **HTTP port is open**: The app's HTTP port (e.g. 8999) must be accessible for heartbeat
   ```bash
   curl http://192.168.1.91:8999/api/v1/ha/heartbeat
   ```
5. **Firewall rules**: Ensure firewall on both servers allows inbound connections on the PostgreSQL and HTTP ports from the peer's IP
6. **No NAT issues**: If using Docker, ensure the PostgreSQL port is mapped to the host (e.g. `ports: - "5432:5432"` in docker-compose). The peer connects to the host IP, not the container IP.

### Peer Endpoint Format

- For heartbeat (HTTP): `http://<peer_lan_ip>:<peer_http_port>` (e.g. `http://192.168.1.91:8999`)
- For replication (PostgreSQL): `postgresql://<pg_user>:<pg_password>@<peer_lan_ip>:<peer_pg_port>/<db_name>`

---

## Database Password and Security Considerations

### How Passwords Are Used in Replication

PostgreSQL logical replication requires the standby to connect to the primary's PostgreSQL server using a standard PostgreSQL connection string. This means:

1. The `HA_PEER_DB_URL` environment variable contains the **peer's** PostgreSQL username and password in plaintext
2. PostgreSQL uses this connection string to establish a persistent replication connection
3. The connection stays open as long as the subscription is active

### Security Requirements

#### 1. Use Dedicated Replication Users (Recommended for Production)

Do not use the `postgres` superuser for replication. Create a dedicated user via the HA admin UI (see [Replication User Management](#replication-user-management)) or manually:

```sql
-- On the PRIMARY node
CREATE USER replicator WITH REPLICATION LOGIN PASSWORD '<strong-random-password>';
GRANT USAGE ON SCHEMA public TO replicator;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO replicator;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO replicator;
```

Then use this user in the standby's peer DB settings (via the UI or env var):
```env
HA_PEER_DB_URL=postgresql://replicator:<password>@<primary_ip>:5432/workshoppro?sslmode=require
```

#### 2. Use Strong, Unique Passwords

- Generate passwords with at least 32 characters using a password manager or `openssl rand -base64 32`
- Each node's local PostgreSQL should have a different password
- The replication user password should be different from the superuser password

#### 3. Enforce Encrypted Connections (Production)

SSL is pre-configured in both Docker Compose files. Generate certificates with:

```bash
bash scripts/generate_pg_certs.sh
```

Then set the SSL mode in the HA admin UI under "Peer Database Settings" to `require` (or `verify-ca` / `verify-full` for stricter verification).

For additional security, configure PostgreSQL to require SSL for replication connections in `pg_hba.conf`:

```
# In pg_hba.conf on the primary
hostssl replication replicator <standby_ip>/32 scram-sha-256
hostssl all         replicator <standby_ip>/32 scram-sha-256
```

Or via the env var:
```env
HA_PEER_DB_URL=postgresql://replicator:<password>@<primary_ip>:5432/workshoppro?sslmode=require
```

See [PostgreSQL SSL Configuration](#postgresql-ssl-configuration) for full details on cert generation and SSL modes.

#### 4. Restrict pg_hba.conf Access

Only allow the peer's specific IP address to connect for replication:

```
# On PRIMARY — only allow standby's IP
host    replication  replicator  192.168.1.91/32  scram-sha-256
host    all          replicator  192.168.1.91/32  scram-sha-256

# On STANDBY — only allow primary's IP (for reverse replication after failover)
host    replication  replicator  192.168.1.90/32  scram-sha-256
host    all          replicator  192.168.1.90/32  scram-sha-256
```

**Automated script:** Use `scripts/configure_pg_hba.sh` to append these rules and reload the configuration automatically:

```bash
# On PRIMARY — restrict replicator to standby's IP
bash scripts/configure_pg_hba.sh invoicing-postgres-1 192.168.1.91

# On STANDBY — restrict replicator to primary's IP (for reverse replication after failover)
bash scripts/configure_pg_hba.sh invoicing-standby-postgres-1 192.168.1.90
```

The script appends `hostssl` rules (SSL-enforced) for both `replication` and `all` connection types, then reloads `pg_hba.conf` via `pg_reload_conf()`. Run it on each node after creating the replicator user and generating SSL certificates.

#### 5. Protect Environment Files

- `.env` files containing `HA_PEER_DB_URL` and `HA_HEARTBEAT_SECRET` must not be committed to git
- Set file permissions: `chmod 600 .env`
- Use Docker secrets or a vault in production if possible

#### 6. HMAC Heartbeat Secret

- `HA_HEARTBEAT_SECRET` must be identical on both nodes
- Use a strong random value: `openssl rand -base64 32`
- This secret signs heartbeat responses to prevent spoofing
- Rotate periodically by updating both nodes simultaneously

#### 7. Shared Application Secrets

These must be identical on both nodes for cross-node authentication to work:
- `JWT_SECRET` — so JWTs issued by one node are valid on the other
- `ENCRYPTION_MASTER_KEY` — so encrypted data can be read by both nodes
- `HA_HEARTBEAT_SECRET` — for heartbeat HMAC verification

---

## Failover and Recovery Procedures

### Planned Failover (Rolling Update)

1. Put standby in maintenance mode (Admin > HA Replication > Enter Maintenance Mode)
2. Update standby: deploy new code, run migrations, restart containers
3. Exit maintenance mode on standby
4. Verify standby is healthy (heartbeat green, replication active)
5. Promote standby to primary (Admin > HA Replication > Promote to Primary)
6. Update DNS/reverse proxy to point traffic to the new primary
7. Demote old primary to standby
8. Update old primary: deploy new code, run migrations, restart containers
9. Initialize replication on the new standby (old primary) to start syncing from the new primary
10. Verify both nodes healthy

### Unplanned Failover (Primary Down)

> **Warning — Network Partition (Full Isolation):** During a network partition where
> neither node can reach the other, split-brain detection is inactive because it relies
> on successful heartbeat communication. If auto-promote is enabled, the standby will
> promote after the failover timeout, resulting in two independent primaries with diverging
> data. This is an inherent limitation of a 2-node design without a quorum mechanism.
>
> To recover: identify which node served customer traffic after the split, use
> "Demote and Sync" on the stale primary once connectivity is restored. Any data written
> to the stale primary since the split will be lost.

1. If auto-promote is enabled, the standby will automatically promote after the failover timeout
2. If auto-promote is disabled, manually promote the standby: Admin > HA Replication > Promote to Primary
3. Update DNS/reverse proxy to point traffic to the new primary
4. When the old primary comes back online:
   a. It will still think it's primary — update its role to Standby via the HA config page
   b. Drop any stale publication: the new primary doesn't need the old publication
   c. Set `HA_PEER_DB_URL` on the old primary to point to the new primary's PostgreSQL
   d. Initialize replication on the old primary (now standby) to start syncing from the new primary
   e. Verify data consistency

### Reverse Sync (Bringing Old Primary Back as Standby)

After a failover, the old primary may have stale data. To bring it back as a standby:

1. On the new primary: ensure the publication exists (Initialize Replication if needed)
2. On the old primary (now standby):
   a. Truncate all data tables (keep schema and `alembic_version`):
      ```bash
      docker cp scripts/truncate_standby.sql <postgres-container>:/tmp/truncate.sql
      docker exec <postgres-container> psql -U postgres -d workshoppro -f /tmp/truncate.sql
      ```
   b. Configure as Standby via the HA page
   c. Click Initialize Replication to create the subscription and do a full data copy
3. Verify data matches between both nodes

---

## Troubleshooting

### "password authentication failed" During Replication Init

The standby's PostgreSQL is trying to connect to the primary's PostgreSQL but the password doesn't match. Causes:
- The primary's PostgreSQL was initialized without a password (Docker `trust` auth) but `pg_hba.conf` requires `scram-sha-256` for external connections
- Fix: Set the password explicitly: `ALTER USER postgres WITH PASSWORD '<password>';` then `SELECT pg_reload_conf();`
- Or change `pg_hba.conf` to use `trust` for the peer's IP (dev only)

### Duplicate Data on Standby

The standby was seeded before replication was set up. Fix:
1. Drop the subscription on standby
2. Drop the replication slot on primary: `SELECT pg_drop_replication_slot('orainvoice_ha_sub');`
3. Truncate all tables on standby (except `alembic_version` and `ha_config`)
4. Re-create the subscription

### "AsyncAdapt_asyncpg_connection has no attribute set_autocommit"

This was a bug in the initial implementation. The `_exec_autocommit` method now uses a direct `asyncpg.connect()` connection instead of trying to use SQLAlchemy's async wrapper for DDL commands.

### Standby Blocks Login (503 "Writes only accepted on primary")

The standby write-protection middleware blocks POST requests. Authentication endpoints (login, token refresh, logout, MFA) are explicitly allowed on standby nodes.

### Session Lost on Page Refresh (Standby)

The token refresh endpoint (`POST /api/v1/auth/token/refresh`) must be in the standby-allowed paths. This is configured in `app/modules/ha/utils.py`.

### Heartbeat Shows "Invalid HMAC Signature"

- Ensure `HA_HEARTBEAT_SECRET` is identical on both nodes
- Ensure the env var is loaded in the container (recreate containers after adding new env vars)
- The HMAC is computed on canonical JSON (sorted keys, compact separators) — this is handled automatically

### Cannot Connect to Peer via host.docker.internal (Dev)

- `host.docker.internal` resolves to the Docker Desktop VM gateway, not `localhost`
- If you have a local PostgreSQL on the host, it may intercept connections on port 5432
- The primary dev postgres is mapped to port 5434 to avoid this conflict
