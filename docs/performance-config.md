# Performance Configuration — WorkshopPro NZ

This document describes the caching strategy, connection pooling, performance
targets, and concurrency configuration for the WorkshopPro NZ platform.

## Performance Targets (Requirement 81)

| Metric | Target | Requirement |
|--------|--------|-------------|
| Page render time | < 2 seconds (10 Mbps broadband) | 81.1 |
| API response (standard CRUD) | < 200 ms | 81.2 |
| Concurrent users | ≥ 500 | 81.3 |

## Redis Caching Strategy (Requirement 81.4)

Redis is used to cache frequently accessed data and reduce PostgreSQL load.

### Cache TTLs

| Data Type | TTL | Rationale |
|-----------|-----|-----------|
| Vehicle lookups | 24 hours | Carjam data changes infrequently; API calls are expensive |
| Service catalogues | 1 hour | Org admins may update pricing during the day |
| Session data | 30 minutes | Aligned with access token lifecycle |
| Default (other) | 5 minutes | Safe fallback for miscellaneous cached data |

### Cache Key Format

All keys follow the pattern: `workshoppro:<namespace>:<identifier>`

Examples:
- `workshoppro:vehicle:ABC123`
- `workshoppro:catalogue:<org-uuid>`
- `workshoppro:session:<session-uuid>`

### Invalidation Strategy

- **Vehicle cache**: Invalidated on manual refresh (Carjam re-fetch).
- **Catalogue cache**: Invalidated when an org admin updates services/parts/labour rates.
  Uses pattern-based invalidation: `workshoppro:catalogue:<org-id>:*`.
- **Session cache**: Invalidated on logout, session termination, or token rotation.

## Database Connection Pooling (Requirement 81.5)

SQLAlchemy async engine is configured with connection pooling to maintain
response times as data volume grows.

| Setting | Value | Purpose |
|---------|-------|---------|
| `pool_size` | 20 | Steady-state connections per worker |
| `max_overflow` | 10 | Burst connections above pool_size |
| `pool_pre_ping` | True | Verify connections are alive before use |
| `pool_recycle` | 1800 s (30 min) | Prevent server-side connection timeouts |
| `pool_timeout` | 30 s | Max wait for a connection from the pool |

With 4 workers, the effective connection range is:
- Steady state: 4 × 20 = 80 connections
- Peak burst: 4 × (20 + 10) = 120 connections

PostgreSQL `max_connections` should be set to at least 150 to accommodate
workers plus Celery and admin connections.

## Concurrency Configuration (Requirement 81.3)

The platform is deployed with Gunicorn + Uvicorn workers behind a load
balancer to support 500+ concurrent users.

| Setting | Value | Purpose |
|---------|-------|---------|
| `worker_count` | 4 | Uvicorn worker processes (tune to 2 × CPU cores) |
| `worker_connections` | 1000 | Max simultaneous connections per worker (async) |
| `keepalive` | 5 s | HTTP keep-alive timeout |
| `graceful_timeout` | 30 s | Shutdown grace period for in-flight requests |
| `max_requests` | 10000 | Restart worker after N requests (memory leak prevention) |
| `max_requests_jitter` | 1000 | Stagger worker restarts |

### Capacity Calculation

Each async Uvicorn worker can handle hundreds of concurrent connections.
With 4 workers × 1000 connections = 4000 theoretical concurrent connections,
well above the 500-user target. In practice, each user generates ~2-3
concurrent requests at peak, so 500 users ≈ 1500 concurrent requests.

### Scaling Beyond 500 Users

- Increase `worker_count` (horizontal scaling per node)
- Add application nodes behind the load balancer
- Add PostgreSQL read replicas for reporting queries (Req 82.4)
- Increase Redis `max_connections` proportionally

## Monitoring

The `ResponseTimer` utility in `app/core/performance.py` provides simple
elapsed-time measurement for API endpoints:

```python
from app.core.performance import ResponseTimer, API_RESPONSE_TARGET_MS

timer = ResponseTimer()
with timer:
    result = await service.get_items(db)

if not timer.within_target():
    logger.warning("Slow response: %d ms", timer.elapsed_ms)
```

For production monitoring, integrate with an APM tool (e.g. Datadog, New Relic)
to track p50/p95/p99 response times and alert on degradation.
