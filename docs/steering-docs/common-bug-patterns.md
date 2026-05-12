# Common Bug Patterns — Prevention Guide

This document catalogs recurring bug patterns observed across SaaS application development. Each pattern includes the root cause, how to detect it, and how to prevent it. Extracted from 100+ tracked issues in production.

## Why This Matters

The same categories of bugs recur across projects. By documenting patterns, teams can:
- Catch bugs during code review before they reach production
- Build automated checks (linters, tests) for known patterns
- Onboard new developers with awareness of common pitfalls

---

## Pattern 1: Frontend/Backend Field Name Mismatch

**Frequency:** Very common (appeared in 10+ issues)

**Symptoms:**
- 422 Unprocessable Entity errors
- Data silently not saving (field ignored by backend)
- Frontend shows `undefined` for fields that have data

**Root Cause:** Frontend sends `remember` but backend expects `remember_me`. Frontend reads `res.data.items` but backend returns `res.data.invoices`. Snake_case vs camelCase mismatches.

**Prevention:**
- Generate TypeScript types from backend schemas (OpenAPI → TypeScript)
- Use typed API client with generics: `apiClient.get<InvoiceListResponse>('/invoices')`
- Add integration tests that verify request/response shapes
- Document API response shapes in a shared location

**Detection:**
```typescript
// Add runtime validation in development mode
if (process.env.NODE_ENV === 'development') {
  if (!res.data?.items && !res.data?.invoices) {
    console.warn('Unexpected response shape from /invoices:', Object.keys(res.data))
  }
}
```

---

## Pattern 2: Missing Null/Undefined Guards on API Data

**Frequency:** Extremely common (60+ files affected in one audit)

**Symptoms:**
- White screen crashes: "Cannot read property 'map' of undefined"
- "undefined is not an object (evaluating 'data.items.length')"
- Crashes only happen with empty databases or error responses

**Root Cause:** Frontend calls `.map()`, `.filter()`, `.length`, `.toLocaleString()` on API response data without checking if it exists first.

**Prevention:**
- Enforce the `?? []` and `?? 0` pattern on all API data access
- Use ESLint rules to flag direct property access on untyped data
- See the [Safe API Consumption](./safe-api-consumption.md) guide for full patterns

---

## Pattern 3: URL Path Double-Prefixing

**Frequency:** Common in apps with versioned APIs

**Symptoms:**
- 404 errors on API calls
- URLs like `/api/v1/api/v2/endpoint` or `/api/v1/v2/endpoint` in network tab

**Root Cause:** The API client has a `baseURL` of `/api/v1`. When code calls `apiClient.get('/api/v2/endpoint')` or `apiClient.get('/v2/endpoint')`, the base URL is prepended, creating a double-versioned path.

**Prevention:**
- Add a request interceptor that detects and rewrites versioned URLs:
```typescript
apiClient.interceptors.request.use((config) => {
  if (config.url?.startsWith('/api/v2/') || config.url?.startsWith('/v2/')) {
    config.baseURL = '/api/v2'
    config.url = config.url.replace(/^\/(api\/)?v2\//, '/')
  }
  return config
})
```
- Or use explicit `baseURL` override: `apiClient.get('/endpoint', { baseURL: '/api/v2' })`

---

## Pattern 4: Missing Database Commit (flush vs commit)

**Frequency:** Common in async ORMs with context managers

**Symptoms:**
- API returns success but data isn't persisted
- Frontend shows loading spinner indefinitely
- Database logs show INSERT/UPDATE followed by ROLLBACK

**Root Cause:** Service functions use `db.flush()` (writes to DB but doesn't commit). If the session context manager auto-commits on exit, but the response is sent before exit, the transaction rolls back.

**Prevention:**
- Establish a clear convention: services use `flush()`, routers handle commit/rollback
- If using `session.begin()` context manager (auto-commit on exit), ensure the response isn't sent before the context exits
- If NOT using auto-commit, add explicit `await db.commit()` in route handlers
- Add integration tests that verify data persists after API calls

```python
# Pattern: session.begin() auto-commits
async with session.begin():
    result = await service.create_item(session, data)
    # Transaction commits when this block exits
    return result  # Return AFTER the block, not inside it

# Pattern: explicit commit in router
result = await service.create_item(db, data)
await db.commit()
return result
```

---

## Pattern 5: Race Conditions in React useEffect

**Frequency:** Common (causes duplicate API calls, stale data)

**Symptoms:**
- Duplicate API calls on page load (especially in React Strict Mode)
- Rate limit (429) errors during development
- Stale data displayed after rapid navigation

**Root Cause:** React Strict Mode double-mounts components in development. Without AbortController cleanup, both requests complete and the first (stale) response can overwrite the second.

**Prevention:**
```typescript
useEffect(() => {
  const controller = new AbortController()
  const fetchData = async () => {
    try {
      const res = await api.get('/endpoint', { signal: controller.signal })
      setData(res.data)
    } catch (err) {
      if (!controller.signal.aborted) setError('Failed')
    }
  }
  fetchData()
  return () => controller.abort()
}, [deps])
```

---

## Pattern 6: PostgreSQL SET Commands with Parameterized Queries

**Frequency:** Rare but catastrophic (breaks entire application)

**Symptoms:**
- Every single API endpoint returns 503
- Error: `syntax error at or near "$1"` for `SET LOCAL`

**Root Cause:** PostgreSQL `SET` and `SET LOCAL` commands do not support parameterized queries (`$1` placeholders). The async database driver translates bound parameters to `$1` format, but SET requires literal values.

**Prevention:**
```python
# WRONG — will fail with syntax error
await session.execute(text("SET LOCAL app.current_tenant = :tenant_id"), {"tenant_id": tid})

# CORRECT — validate and interpolate directly
import uuid
validated = str(uuid.UUID(tenant_id))  # Validates format, prevents injection
await session.execute(text(f"SET LOCAL app.current_tenant = '{validated}'"))
```

**Key insight:** This is safe because UUIDs have a fixed format that cannot contain SQL injection. For non-UUID values, use a strict allowlist.

---

## Pattern 7: Route Order Conflicts in API Frameworks

**Frequency:** Occasional

**Symptoms:**
- 422 validation errors on endpoints that should work
- "value is not a valid uuid" when calling `/items/search`

**Root Cause:** Dynamic route `/{item_id}` is defined before static route `/search`. The framework matches "search" as an item_id, which fails UUID validation.

**Prevention:**
```python
# CORRECT — static routes BEFORE dynamic routes
@router.get("/search")
async def search_items(): ...

@router.get("/lookup")
async def lookup_item(): ...

@router.get("/{item_id}")
async def get_item(item_id: UUID): ...
```

---

## Pattern 8: State Machine Missing Valid Transitions

**Frequency:** Occasional (causes 400 errors on valid operations)

**Symptoms:**
- Second partial payment fails with "Invalid status transition"
- Valid user actions rejected by the backend

**Root Cause:** State machine doesn't include self-transitions (e.g., `partially_paid → partially_paid`) or all valid paths.

**Prevention:**
- Map out ALL valid transitions, including self-transitions
- Write property-based tests that exercise all transition paths
- Include the transition map in documentation

```python
VALID_TRANSITIONS = {
    "draft": ["sent", "voided"],
    "sent": ["paid", "partially_paid", "overdue", "voided"],
    "partially_paid": ["paid", "partially_paid", "overdue", "voided"],  # ← self-transition!
    "overdue": ["paid", "partially_paid", "voided"],
    "paid": ["refunded"],
}
```

---

## Pattern 9: CSS Overflow Clipping in Nested Layouts

**Frequency:** Common in apps with fixed layouts + scrollable content

**Symptoms:**
- Content cut off at bottom of viewport
- Dropdowns hidden/clipped inside tables or containers
- Pages can't scroll despite having more content

**Root Cause:** Parent layout uses `h-screen overflow-hidden` with a scrollable `<main>`. Child pages set their own `min-h-screen` or `h-screen`, conflicting with the parent's scroll container.

**Prevention:**
- Pages inside a layout should NEVER use viewport-relative heights (`h-screen`, `min-h-screen`, `100vh`)
- Use `h-full` to fill the parent container, or let content flow naturally
- For edge-to-edge layouts (split panes, POS), use negative margins to cancel parent padding
- For dropdowns inside tables, use `overflow-visible` on the table container or portal the dropdown

---

## Pattern 10: CORS Configuration Mismatch

**Frequency:** Common during development with Docker

**Symptoms:**
- "Disallowed CORS origin" errors in browser console
- API calls work via curl but fail from the browser
- Preflight OPTIONS requests return 403

**Root Cause:** Frontend is accessed on a different port than what's configured in CORS_ORIGINS. Docker port mapping (e.g., 3000:5173) means the browser sees port 3000 but CORS only allows port 5173.

**Prevention:**
- Include ALL ports the frontend might be accessed on in CORS_ORIGINS
- In development, consider allowing `localhost` on any port
- Remember that CORS is enforced by the browser, not the server — curl always works

---

## Pattern 11: Decimal/Float Serialization Errors

**Frequency:** Occasional

**Symptoms:**
- `TypeError: Object of type Decimal is not JSON serializable`
- Crashes in audit logging, API responses, or webhook payloads

**Root Cause:** Database returns `Decimal` types for numeric columns. JSON serialization doesn't handle `Decimal` by default.

**Prevention:**
```python
import decimal

def json_serializable(obj):
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

# Use in json.dumps
json.dumps(data, default=json_serializable)
```

---

## Pattern 12: Search Dropdown Reopening After Selection

**Frequency:** Common in autocomplete/search components

**Symptoms:**
- User selects an item from dropdown, dropdown closes then immediately reopens
- Requires clicking away to dismiss

**Root Cause:** Selection handler sets the search text to the selected item's name. The search `useEffect` fires on text change, fetches results, and reopens the dropdown.

**Prevention:**
```typescript
// Use a flag to suppress the search after selection
const [justSelected, setJustSelected] = useState(false)

const handleSelect = (item) => {
  setJustSelected(true)
  setSearchText(item.name)
  setShowDropdown(false)
  onSelect(item)
}

useEffect(() => {
  if (justSelected) {
    setJustSelected(false)
    return  // Skip search after selection
  }
  // ... perform search
}, [searchText])
```

---

## Checklist: Code Review for Common Bugs

- [ ] All API response data accessed with `?.` and `?? fallback`
- [ ] Field names match between frontend and backend exactly
- [ ] No `as any` type assertions on API responses
- [ ] useEffect hooks have AbortController cleanup
- [ ] Static routes defined before dynamic routes
- [ ] State machine includes all valid transitions (including self-transitions)
- [ ] Database operations have proper commit/rollback handling
- [ ] No viewport-relative heights inside layout scroll containers
- [ ] CORS origins include all access ports
- [ ] Decimal/datetime types handled in JSON serialization
- [ ] Search/autocomplete components suppress search after selection
