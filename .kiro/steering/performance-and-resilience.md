---
inclusion: auto
---

# Performance & Resilience Patterns

Rules derived from real performance bugs and crash patterns. Each rule references the issue that motivated it. Cross-reference `#[[file:docs/ISSUE_TRACKER.md]]` for full details.

Frontend API call safety (null guards, optional chaining, AbortController) is covered in `#[[file:.kiro/steering/safe-api-consumption.md]]`. This file covers backend, infrastructure, and architectural patterns.

---

## 1. SQLAlchemy Transaction Management

**NEVER call `db.rollback()` inside a try/except within a session context manager.**
The context manager (`async with get_session() as db`) owns the transaction. Calling `db.rollback()` manually inside it kills the transaction, and subsequent operations raise `InvalidRequestError: Can't operate on closed transaction`. *(ISSUE-044, ISSUE-102)*

```python
# WRONG — kills the transaction for everything after the except block
async with get_session() as db:
    for item in items:
        try:
            db.add(Thing(data=item))
            await db.flush()
        except IntegrityError:
            await db.rollback()  # ← kills the whole session
            continue  # next iteration fails

# RIGHT — use SAVEPOINTs for partial rollback
async with get_session() as db:
    for item in items:
        savepoint = await db.begin_nested()  # SAVEPOINT
        try:
            db.add(Thing(data=item))
            await db.flush()
        except IntegrityError:
            await savepoint.rollback()  # rolls back only this item
            continue
    await db.commit()  # commit everything that succeeded
```

**Let the context manager handle commit/rollback.**
Don't mix explicit `db.commit()` / `db.rollback()` with implicit context-manager transaction management unless you understand the interaction. If you need fine-grained control, use `begin_nested()` (SAVEPOINTs).

---

## 2. Connection Pool Management

**Set `pool_size + max_overflow` < PostgreSQL `max_connections`.**
If your pool can open 90 connections but PostgreSQL allows 50, you get `too many connections` errors under load. Leave headroom for admin connections, migrations, and monitoring. *(ISSUE-086)*

```python
# Example: PostgreSQL max_connections = 50
engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,        # persistent connections
    max_overflow=20,     # burst connections
    pool_pre_ping=True,  # detect stale connections
    pool_recycle=3600,   # recycle after 1 hour
)
# Total possible: 30, well under 50
```

**Use `pool_pre_ping=True` to detect stale connections.**
Without it, a connection that was closed by PostgreSQL (idle timeout, restart) will cause the first query to fail. Pre-ping tests the connection before use.

**Close external HTTP clients after use.**
`httpx.AsyncClient` and `aiohttp.ClientSession` hold connection pools. If you create them per-request without closing, you leak file descriptors and sockets. Use context managers or a shared singleton. *(ISSUE-066)*

```python
# WRONG — leaks connections
async def call_api():
    client = httpx.AsyncClient()
    resp = await client.get(url)
    return resp  # client never closed

# RIGHT — context manager
async def call_api():
    async with httpx.AsyncClient() as client:
        return await client.get(url)

# RIGHT — shared singleton (for high-frequency calls)
# Initialize once at app startup, close on shutdown
```

---

## 3. Async Operation Patterns

**Never do synchronous I/O in async request handlers.**
Synchronous SMTP, file I/O, or HTTP calls block the entire event loop, causing 5-6 second response times for all concurrent requests. *(ISSUE-094)*

```python
# WRONG — blocks the event loop for 3-5 seconds
@router.post("/send-notification")
async def send_notification(data: NotificationRequest):
    smtplib.SMTP('smtp.example.com').send_message(msg)  # synchronous!
    return {"status": "sent"}

# RIGHT — background task
from fastapi import BackgroundTasks

@router.post("/send-notification")
async def send_notification(data: NotificationRequest, bg: BackgroundTasks):
    bg.add_task(send_email_async, data)
    return {"status": "queued"}
```

**For heavy async work, use task queues (Celery, arq) instead of `asyncio.create_task`.**
`create_task` is fine for fire-and-forget within a request, but tasks die if the process restarts. Use a proper queue for email delivery, webhook dispatch, report generation, and anything that must complete reliably.

**External API calls need timeouts and retry logic.**
A third-party API hanging for 30 seconds will cascade into your response times. Set explicit timeouts and implement retry with exponential backoff.

```python
async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
    for attempt in range(3):
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
```

---

## 4. Caching & Token Management

**Cache tokens and config — don't fetch fresh on every request.**
If every API call to an external service starts with "get a new auth token," you're adding latency and hammering the auth provider. Cache tokens in Redis with a TTL slightly shorter than their expiry. *(ISSUE-066)*

```python
import redis.asyncio as redis

async def get_cached_token(redis_client: redis.Redis) -> str:
    token = await redis_client.get("external_api_token")
    if token:
        return token.decode()
    token = await fetch_new_token()
    await redis_client.setex("external_api_token", 3500, token)  # expires before the token does
    return token
```

**Cache frequently-read, rarely-changed data.**
Org settings, feature flags, subscription plan details — these change rarely but are read on every request. Cache in Redis with TTL and invalidate on write.

---

## 5. Frontend Re-render & Effect Optimization

**React StrictMode doubles all effects in development.**
Every `useEffect` fires twice. If your effect isn't idempotent (e.g., it POSTs data or increments a counter), you'll see double submissions in dev. Design effects to be safe to re-run. *(ISSUE-014)*

**Include all reactive dependencies in useEffect dependency arrays.**
Missing dependencies (especially `selectedBranchId`, user context, or filter state) cause stale closures — the effect runs with old values and fetches wrong data. ESLint's `exhaustive-deps` rule catches this; don't suppress it.

**Debounce search inputs.**
Typing "hello" fires 5 API calls without debouncing. Use 300ms debounce for search/filter inputs to avoid hammering the backend and hitting rate limits.

```typescript
const [search, setSearch] = useState('')
const debouncedSearch = useDebouncedValue(search, 300)

useEffect(() => {
  // Only fires 300ms after user stops typing
  fetchResults(debouncedSearch)
}, [debouncedSearch])
```

**Use `useMemo` / `useCallback` for expensive computations and stable references.**
If a computation runs on every render (sorting a large list, computing totals), wrap it in `useMemo`. If a callback is passed as a prop or dependency, wrap it in `useCallback` to prevent unnecessary child re-renders.

---

## 6. API Response Contract

**Backend MUST return consistent response shapes.**
Paginated lists always return `{ items: [...], total: N }`. Named lists always return `{ key: [...] }`. Never return a bare array for a list endpoint — it prevents adding metadata later without breaking clients. *(ISSUE-012, ISSUE-013, ISSUE-017, ISSUE-018, ISSUE-020)*

**Frontend MUST handle both wrapped and bare responses defensively.**
Even with a consistent backend, handle the edge case:
```typescript
const items = Array.isArray(res.data) ? res.data : (res.data?.items ?? [])
```

**Error responses MUST NOT leak internals.**
No stack traces, no file paths, no SQL queries, no internal IPs in error responses. Use a global exception handler that returns generic messages and logs details server-side.

```python
# FastAPI global handler
@app.exception_handler(Exception)
async def generic_handler(request, exc):
    logger.error(f"Unhandled: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```

**Use typed generics on API calls — no `as any`.**
```typescript
// WRONG
const data = res.data as any

// RIGHT
const res = await apiClient.get<PaginatedResponse<Vehicle>>('/vehicles')
```

---

## 7. Resource Cleanup Checklist

Before shipping any feature that uses external resources:

- [ ] HTTP clients are closed after use (or shared as singletons)
- [ ] Database sessions are managed by context managers (no manual commit/rollback mixing)
- [ ] `pool_size + max_overflow` < PostgreSQL `max_connections`
- [ ] Synchronous I/O is offloaded to background tasks
- [ ] External API calls have timeouts and retry logic
- [ ] Tokens and config are cached with TTL (not fetched per-request)
- [ ] useEffect hooks have AbortController cleanup
- [ ] useEffect dependency arrays are complete (no missing deps)
- [ ] Search inputs are debounced
- [ ] Error responses don't leak stack traces or SQL
