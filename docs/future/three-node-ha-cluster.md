# Three-Node HA Cluster with Quorum Failover

**Status**: Future / Planning
**Estimated effort**: ~2-3 weeks
**Dependencies**: Current 2-node HA must be fully tested first
**Date**: 2026-04-30

---

## Overview

Extend the current 2-node PostgreSQL logical replication HA setup to a 3-node triangle cluster with quorum-based failover. Any node that loses contact with both peers self-demotes to read-only (isolated). The remaining two nodes continue operating — if the primary was the one isolated, the standby with the lowest node_id auto-promotes.

An external health check enhancement detects internet outages on the primary and triggers proactive handoff before the timeout expires.

## Current State (2-Node)

- Primary: Local dev (192.168.1.168:80, DB port 5434)
- Standby: Pi (192.168.1.90:8081, DB port 5433)
- PostgreSQL logical replication (publication/subscription)
- Single peer_endpoint in ha_config
- Heartbeat every 10s, failover timeout 90s
- Manual or auto-promote (currently auto-promote disabled)
- Volume sync via rsync over SSH

## Target State (3-Node)

```
         ┌──────────────┐
         │   Node A      │
         │   (Primary)   │
         │   Desktop     │
         └──┬────────┬───┘
    heartbeat│        │heartbeat
   + repl    │        │+ repl
             │        │
   ┌─────────▼─┐  ┌───▼──────────┐
   │  Node B    │  │  Node C       │
   │ (Standby-1)│  │ (Standby-2)  │
   │  Pi 5      │  │  Pi 4 / VPS  │
   └─────┬──────┘  └──────┬───────┘
         │    heartbeat    │
         └────────────────-┘
```

Each node:
- Knows about both peers (not just one)
- Sends heartbeats to both peers every 10s
- Receives replication from the current primary
- Can be promoted to primary if quorum agrees

---

## Quorum Rules

With 3 nodes, quorum = 2. The rules:

| Scenario | Node A sees | Node B sees | Node C sees | Result |
|----------|-------------|-------------|-------------|--------|
| Normal operation | B, C | A, C | A, B | A stays primary |
| A isolated | neither | C only | B only | A self-demotes (read-only). B or C promotes (lowest node_id wins) |
| B isolated | C only | neither | A only | B self-demotes. A stays primary (still has quorum with C) |
| A + B isolated from C | B only | A only | neither | C self-demotes. A stays primary (has quorum with B) |
| All isolated | neither | neither | neither | All go read-only. Manual intervention needed |
| A crashes | — | C only | B only | B and C detect A down. Lowest node_id promotes after timeout |

### Key principle
A node stays primary only if it can reach at least 1 other node. If it can reach 0 peers for 90 seconds, it self-demotes to `isolated` (read-only).

### Promotion priority
When the primary is unreachable and two standbys can see each other, the one with the **lower `node_id`** promotes. This is deterministic — no voting protocol needed, both nodes independently reach the same conclusion.

---

## Isolated Node Behavior

When a node is isolated (can't reach either peer for 90s):

1. Role changes to `isolated` (new role, distinct from `standby`)
2. `StandbyWriteProtectionMiddleware` activates — all writes blocked
3. App continues serving read-only requests
4. Node keeps trying to reach peers every 10s
5. When connectivity restores:
   - Node discovers who the current primary is via heartbeat response
   - If a different node is now primary, the isolated node becomes standby to that new primary
   - Subscription is reconfigured to point to the new primary
   - No data merge needed because the node was read-only during isolation

### Why read-only during isolation (no buffered writes)

Accepting writes during isolation creates conflict resolution problems that are extremely hard to solve correctly for an invoicing system:
- Duplicate invoice numbers from diverged sequences
- Conflicting customer edits
- Payment records that don't match

Read-only isolation is the safe choice. Users see a "System is in read-only mode" banner and can still view all data. Writes resume within seconds of connectivity restoring.

---

## Database Changes

### ha_config table changes

```sql
-- Add support for multiple peers
ALTER TABLE ha_config ADD COLUMN peer2_endpoint VARCHAR(500);
ALTER TABLE ha_config ADD COLUMN peer2_db_host VARCHAR(255);
ALTER TABLE ha_config ADD COLUMN peer2_db_port INTEGER;
ALTER TABLE ha_config ADD COLUMN peer2_db_name VARCHAR(255);
ALTER TABLE ha_config ADD COLUMN peer2_db_user VARCHAR(255);
ALTER TABLE ha_config ADD COLUMN peer2_db_password TEXT;  -- encrypted
ALTER TABLE ha_config ADD COLUMN peer2_db_sslmode VARCHAR(50) DEFAULT 'prefer';

-- Add node priority for deterministic promotion
ALTER TABLE ha_config ADD COLUMN node_priority INTEGER DEFAULT 0;
-- Lower number = higher priority for promotion

-- Add isolated role support
-- role enum: 'primary', 'standby', 'isolated'

-- Track health of both peers separately
ALTER TABLE ha_config ADD COLUMN last_peer2_health VARCHAR(50);
ALTER TABLE ha_config ADD COLUMN last_peer2_heartbeat TIMESTAMPTZ;

-- External health check
ALTER TABLE ha_config ADD COLUMN external_health_url VARCHAR(500) DEFAULT 'https://1.1.1.1';
ALTER TABLE ha_config ADD COLUMN last_external_health TIMESTAMPTZ;
ALTER TABLE ha_config ADD COLUMN internet_reachable BOOLEAN DEFAULT true;
```

### ha_event_log additions

New event types:
- `node_isolated` — node lost contact with both peers
- `node_rejoined` — isolated node restored connectivity
- `quorum_lost` — all nodes isolated (critical alert)
- `internet_down_detected` — external health check failed
- `proactive_handoff` — primary handed off due to internet loss

---

## Heartbeat Changes

### Current heartbeat (2-node)
- Ping single peer every 10s
- 5 consecutive failures = peer unreachable
- After failover_timeout_seconds (90s), auto-promote if enabled

### New heartbeat (3-node)

Each node maintains two heartbeat loops:

```python
# Pseudo-code for 3-node heartbeat
async def heartbeat_loop():
    while True:
        peer1_ok = await ping_peer(config.peer_endpoint)
        peer2_ok = await ping_peer(config.peer2_endpoint)
        internet_ok = await ping_external(config.external_health_url)

        reachable_peers = sum([peer1_ok, peer2_ok])

        if my_role == 'primary':
            if reachable_peers == 0:
                # Can't reach anyone — start isolation countdown
                if isolation_timer_exceeded(90s):
                    self_demote_to_isolated()
            elif not internet_ok and reachable_peers > 0:
                # Internet down but can reach peers — proactive handoff
                trigger_proactive_handoff()
            else:
                # Reset isolation timer
                reset_isolation_timer()

        elif my_role == 'standby':
            primary_reachable = is_primary_reachable(peer1_ok, peer2_ok)
            if not primary_reachable:
                # Primary is down
                other_standby_reachable = is_other_standby_reachable(peer1_ok, peer2_ok)
                if other_standby_reachable:
                    # We have quorum (me + other standby)
                    if i_should_promote():  # lowest node_id wins
                        if promotion_timer_exceeded(90s):
                            promote_to_primary()
                    # else: other standby will promote, I wait
                else:
                    # Can't reach anyone
                    if isolation_timer_exceeded(90s):
                        self_demote_to_isolated()

        elif my_role == 'isolated':
            if reachable_peers > 0:
                # Connectivity restored
                discover_current_primary()
                reconfigure_as_standby()

        await asyncio.sleep(10)
```

### Heartbeat response changes

Current response includes: `role`, `peer_health`, `replication_lag`

New response adds:
```json
{
  "role": "primary",
  "node_id": "node-a",
  "node_priority": 0,
  "peers": {
    "node-b": { "health": "healthy", "last_seen": "2026-04-30T10:00:00Z" },
    "node-c": { "health": "healthy", "last_seen": "2026-04-30T10:00:00Z" }
  },
  "internet_reachable": true,
  "replication_lag_bytes": 0
}
```

This lets each node build a complete picture of the cluster state.

---

## Replication Changes

### Current (2-node)
- Primary has 1 publication, 1 replication slot
- Standby has 1 subscription

### New (3-node)
- Primary has 1 publication, 2 replication slots (one per standby)
- Each standby has 1 subscription pointing to the current primary

### On promotion (standby becomes primary)
1. Stop subscription (was receiving from old primary)
2. Create publication (if not exists)
3. Sync sequences from the other reachable standby
4. The other standby reconfigures its subscription to point to the new primary
5. When the old primary rejoins, it creates a subscription to the new primary

### On demotion (primary becomes standby/isolated)
1. Drop publication and replication slots
2. Create subscription pointing to the new primary
3. Wait for initial sync to complete

### Replication slot cleanup
With 3 nodes, orphaned slots are more likely (a standby goes down, its slot accumulates WAL). The existing orphaned slot cleanup logic needs to handle 2 slots instead of 1, with configurable retention before cleanup.

---

## External Health Check (Path C Enhancement)

### Purpose
Detect when the primary has lost internet connectivity but can still reach peers on LAN. In this case, the primary should proactively hand off to a standby that has internet, because an invoicing app without internet can't send emails, process Stripe payments, or sync with Xero.

### Implementation

```python
async def check_external_health():
    """Ping an external endpoint to verify internet connectivity."""
    urls = [
        config.external_health_url,  # Default: https://1.1.1.1
        "https://8.8.8.8",           # Fallback
    ]
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url)
                if resp.status_code < 500:
                    return True
        except Exception:
            continue
    return False
```

### Proactive handoff flow

1. Primary detects internet is down (external health check fails 3 times in a row)
2. Primary can still reach Standby-1 on LAN
3. Primary sends a `handoff_request` to Standby-1 via heartbeat
4. Standby-1 verifies it has internet connectivity
5. If yes, Standby-1 promotes immediately (no 90s wait)
6. Primary demotes to standby
7. Event logged: `proactive_handoff`

### What this covers
- Pi loses WiFi/ethernet but desktop is on wired connection
- ISP outage at one location but not the other
- Router failure at primary's location

### What this doesn't cover
- Both locations lose internet simultaneously (all nodes go read-only)
- LAN partition between nodes (handled by quorum rules above)

---

## Volume Sync Changes

### Current (2-node)
- Primary rsyncs uploads to single standby
- SSH on port 2222

### New (3-node)
- Primary rsyncs to both standbys
- Each standby has SSH access to both peers
- On promotion, new primary starts syncing to both standbys
- Sync interval configurable per-peer (default: 30 minutes)

### File conflict handling
Since only the primary accepts writes, file conflicts shouldn't occur. But as a safety measure:
- rsync uses `--update` flag (skip files newer on destination)
- Log any skipped files for manual review

---

## HA Admin GUI Changes

### Current
- Shows 2 nodes (primary + standby)
- Single peer health indicator
- Promote/demote buttons

### New
- Shows 3 nodes in a triangle diagram
- Health indicator for each peer
- Internet connectivity indicator per node
- Cluster status: "Healthy (3/3)", "Degraded (2/3)", "Critical (1/3)"
- Promote/demote buttons per node
- Event log shows all 3 nodes' events
- "Add Node" wizard for adding the third node to existing 2-node cluster

---

## HA Setup Wizard Changes

### Option 1: Extend existing wizard
Add a step after the initial 2-node setup: "Add a third node"
- Enter third node's address
- Verify reachability
- Authenticate
- Exchange SSH keys with both existing nodes
- Create subscription on the new node
- Create additional replication slot on primary

### Option 2: New 3-node wizard
Fresh setup that configures all 3 nodes at once. More complex but cleaner.

Recommendation: Option 1 — incremental. Users set up 2 nodes first (already working), then add a third.

---

## Docker Compose Changes

No new compose files needed. The third node would use one of:
- `docker-compose.ha-standby.yml` (if on the same desktop, different ports)
- `docker-compose.standby-prod.yml` (if a second standby on desktop)
- `docker-compose.yml` + `docker-compose.pi.yml` (if on a second Pi)

The node's role is determined by `ha_config` in the database, not by the compose file.

---

## Implementation Plan

### Phase 1: Multi-peer heartbeat (~3-4 days)
- [ ] Add peer2 columns to ha_config
- [ ] Modify heartbeat.py to ping 2 peers
- [ ] Implement quorum logic (need 1+ peer to stay primary)
- [ ] Add `isolated` role with read-only enforcement
- [ ] Add node_priority for deterministic promotion
- [ ] Update heartbeat response to include multi-peer status
- [ ] Update HA status API to return 3-node cluster state

### Phase 2: Multi-peer replication (~3-4 days)
- [ ] Modify replication.py to manage 2 replication slots on primary
- [ ] Modify subscription management for 3-node topology
- [ ] Handle promotion: reconfigure subscriptions on all reachable nodes
- [ ] Handle demotion: create subscription to new primary
- [ ] Handle rejoin: isolated node discovers primary and subscribes
- [ ] Sequence sync across 3 nodes (find max across reachable peers)
- [ ] Orphaned slot cleanup for 2 slots

### Phase 3: External health check (~2-3 days)
- [ ] Add external_health_url to ha_config
- [ ] Implement external health check in heartbeat loop
- [ ] Implement proactive handoff protocol
- [ ] Add internet_reachable to heartbeat response
- [ ] Log proactive handoff events

### Phase 4: Volume sync for 3 nodes (~1-2 days)
- [ ] Extend volume sync to rsync to 2 peers
- [ ] SSH key exchange with both peers during setup
- [ ] Handle sync direction changes on promotion

### Phase 5: Admin GUI updates (~2-3 days)
- [ ] 3-node cluster visualization
- [ ] Per-node health indicators
- [ ] Internet connectivity indicator
- [ ] "Add Third Node" wizard step
- [ ] Updated event log with 3-node events

### Phase 6: Testing (~2-3 days)
- [ ] Scenario: Primary isolated, standby-1 promotes
- [ ] Scenario: Standby-1 isolated, primary + standby-2 continue
- [ ] Scenario: Primary crashes, instant detection and promotion
- [ ] Scenario: Primary loses internet, proactive handoff
- [ ] Scenario: Isolated node rejoins, becomes standby
- [ ] Scenario: All nodes isolated, all go read-only
- [ ] Scenario: Two nodes isolated from each other but both reach third
- [ ] Sequence integrity after multiple failovers
- [ ] Volume sync after promotion chain

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Split-brain (two primaries) | Data corruption | Quorum rule: need 1+ peer. Isolated node goes read-only immediately |
| Sequence collision after promotion | Duplicate invoice numbers | Sync sequences from all reachable peers before accepting writes |
| Replication slot bloat | Disk full on primary | Aggressive orphaned slot cleanup (existing logic, extended to 2 slots) |
| Network flapping (brief disconnects) | Unnecessary failovers | Require 5 consecutive failed heartbeats (50s) before starting isolation timer |
| Third node adds latency to writes | Slower transactions | Logical replication is async — no write latency impact |
| Complexity of 3-node debugging | Harder to troubleshoot | Comprehensive event logging on all nodes, cluster status dashboard |

---

## What We Don't Need

- **etcd / Patroni / Raft**: Overkill for 3 nodes. Deterministic promotion (lowest node_id) eliminates the need for a consensus protocol.
- **Cloudflare services**: Not needed for node coordination. The external health check just pings any public IP to verify internet connectivity.
- **Streaming replication**: Logical replication works fine for this. Each node runs its own migrations independently, which is a feature we want to keep.
- **Buffered writes during isolation**: Too dangerous for an invoicing system. Read-only isolation is the safe choice.
- **Load balancer**: Not needed at this scale. DNS or reverse proxy handles routing to the primary.

---

## Hardware Options for Third Node

| Option | Cost | Pros | Cons |
|--------|------|------|------|
| Raspberry Pi 4/5 on same LAN | ~$100-150 | Low cost, same network, easy setup | Same location as desktop (not geographic redundancy) |
| Old laptop/desktop | Free | Already have it | Power consumption, noise |
| VPS (Hetzner, DigitalOcean) | ~$5-10/mo | Geographic redundancy, always-on | Latency for replication, internet dependency |
| Second location Pi (family/friend's house) | ~$100-150 + VPN | True geographic redundancy | VPN setup complexity, depends on their internet |

Recommendation: Start with a Pi on the same LAN for testing. Add a VPS or remote Pi later for geographic redundancy.
