# PostgreSQL HA Replication — Patterns and Procedures

This document covers high-availability (HA) patterns using PostgreSQL logical replication in an active-standby configuration. It's applicable to any application that needs disaster recovery with near-zero data loss.

## Why This Matters

For any production SaaS application, a single database server is a single point of failure. HA replication provides:
- **Disaster recovery:** If the primary goes down, the standby can take over
- **Near-zero RPO:** Logical replication streams changes in real-time (sub-second lag)
- **Rolling updates:** Deploy to standby first, promote it, then update the old primary
- **Geographic redundancy:** Primary and standby at different physical locations

---

## Architecture Overview

```
┌─────────────────────┐         Heartbeat (HTTP)        ┌─────────────────────┐
│   PRIMARY NODE      │◄──────────────────────────────►│   STANDBY NODE      │
│                     │                                 │                     │
│  App Server         │                                 │  App Server         │
│  PostgreSQL         │──── Logical Replication ──────►│  PostgreSQL         │
│  Redis              │                                 │  Redis              │
└─────────────────────┘                                 └─────────────────────┘
```

Key design decisions:
- **Logical replication** (not streaming) — allows selective table replication and schema differences
- **Heartbeat service** — each node pings the peer every N seconds to detect failures
- **HMAC-signed heartbeats** — prevents spoofing with a shared secret
- **Standby blocks writes** — except authentication endpoints (login, token refresh, logout)
- **Redis is NOT replicated** — each node has its own Redis for sessions/cache

---

## Prerequisites

### PostgreSQL Configuration

Both nodes must have `wal_level=logical` set:

```ini
# postgresql.conf
wal_level = logical
max_replication_slots = 4
max_wal_senders = 4
```

### SSL Certificates

Generate a private CA and server certificates for each node:

```bash
# Generate CA
openssl genrsa -out ca.key 4096
openssl req -new -x509 -key ca.key -out ca.crt -days 3650 -subj "/CN=MyApp-CA"

# Generate server cert for each node
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -subj "/CN=primary-node"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 3650
```

Share the CA cert between nodes. Server keys never leave their respective hosts.

### Dedicated Replication User

Create a user with minimal privileges:

```sql
CREATE USER replicator WITH REPLICATION LOGIN PASSWORD '<strong-random-password>';
GRANT USAGE ON SCHEMA public TO replicator;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO replicator;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO replicator;
```

---

## Setting Up Replication

### On the Primary

Create a publication for all tables:

```sql
CREATE PUBLICATION myapp_ha_pub FOR ALL TABLES;
```

### On the Standby

Create a subscription pointing to the primary:

```sql
CREATE SUBSCRIPTION myapp_ha_sub
    CONNECTION 'host=<primary_ip> port=5432 dbname=myapp user=replicator password=<password> sslmode=require'
    PUBLICATION myapp_ha_pub
    WITH (copy_data = true);  -- Initial data sync
```

### Verify Replication

```sql
-- On primary: check publication
SELECT * FROM pg_publication_tables WHERE pubname = 'myapp_ha_pub';

-- On standby: check subscription status
SELECT subname, subenabled, subconninfo FROM pg_subscription;

-- Check replication lag
SELECT slot_name, confirmed_flush_lsn, pg_current_wal_lsn(),
       pg_current_wal_lsn() - confirmed_flush_lsn AS lag_bytes
FROM pg_replication_slots;
```

---

## Heartbeat System

Each node runs a heartbeat service that pings the peer:

```python
# Heartbeat endpoint
@router.get("/ha/heartbeat")
async def heartbeat():
    return {
        "node_name": config.node_name,
        "role": config.role,  # "primary" or "standby"
        "timestamp": datetime.utcnow().isoformat(),
        "status": "healthy",
        "hmac": compute_hmac(payload, shared_secret)
    }
```

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Heartbeat interval | 10s | How often to ping the peer |
| Failover timeout | 90s | How long peer must be unreachable before auto-promote |
| Auto-promote | false | Whether standby auto-promotes on primary failure |

### HMAC Verification

Heartbeat responses are signed to prevent spoofing:

```python
import hmac, hashlib

def compute_hmac(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

def verify_hmac(payload: str, signature: str, secret: str) -> bool:
    expected = compute_hmac(payload, secret)
    return hmac.compare_digest(expected, signature)
```

---

## Failover Procedures

### Planned Failover (Rolling Update)

1. Put standby in maintenance mode
2. Update standby: deploy new code, run migrations, restart
3. Exit maintenance mode, verify standby is healthy
4. Promote standby to primary
5. Update DNS/load balancer to point to new primary
6. Demote old primary to standby
7. Update old primary, initialize reverse replication

### Unplanned Failover (Primary Down)

1. Standby detects primary unreachable (heartbeat timeout)
2. If auto-promote enabled: standby promotes automatically
3. If manual: admin promotes standby via admin UI
4. Update DNS/load balancer
5. When old primary recovers:
   - Change its role to standby
   - Point its replication to the new primary
   - Re-sync data

### Split-Brain Warning

> In a 2-node design without a quorum mechanism, a network partition where neither node can reach the other will result in both nodes thinking the other is down. If auto-promote is enabled, both become primaries with diverging data.
>
> **Mitigation:** Use a third-party witness node, or disable auto-promote and require manual intervention.

---

## Tables to Exclude from Replication

Some tables should NOT be replicated:

| Table | Reason |
|-------|--------|
| `ha_config` | Each node has its own HA configuration |
| `alembic_version` | Each node manages its own migration state |
| Session/cache tables | Ephemeral data, node-specific |

```sql
-- Exclude specific tables
CREATE PUBLICATION myapp_ha_pub FOR ALL TABLES
    EXCEPT TABLE ha_config, alembic_version;
```

---

## Shared Secrets Between Nodes

These must be identical on both nodes for cross-node authentication:

| Secret | Purpose |
|--------|---------|
| `JWT_SECRET` | So JWTs issued by one node are valid on the other |
| `ENCRYPTION_MASTER_KEY` | So encrypted data can be read by both nodes |
| `HA_HEARTBEAT_SECRET` | For heartbeat HMAC verification |

---

## Security Checklist

- [ ] Dedicated replication user with minimal privileges (not superuser)
- [ ] SSL enabled for replication connections (`sslmode=require` minimum)
- [ ] `pg_hba.conf` restricts replication to peer's specific IP
- [ ] Heartbeat secret is strong (32+ random characters)
- [ ] Server private keys never leave their respective hosts
- [ ] Environment files with secrets have restricted permissions (`chmod 600`)
- [ ] Shared secrets (JWT, encryption key, heartbeat) are identical on both nodes

---

## Monitoring

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| Replication lag | > 60 seconds | Investigate network/load |
| Heartbeat failures | 3 consecutive | Check network connectivity |
| Subscription status | Not "streaming" | Check pg_subscription, restart if needed |
| WAL accumulation | > 1 GB | Standby may be disconnected |

---

## Checklist

- [ ] `wal_level=logical` on both nodes
- [ ] SSL certificates generated and configured
- [ ] Dedicated replication user created with minimal privileges
- [ ] Publication created on primary
- [ ] Subscription created on standby with `copy_data=true`
- [ ] Heartbeat service running on both nodes
- [ ] HMAC secret shared between nodes
- [ ] Failover procedure documented and tested
- [ ] DNS/load balancer update procedure documented
- [ ] Monitoring alerts configured for replication lag and heartbeat failures
- [ ] Split-brain mitigation strategy decided (witness node or manual-only promotion)
