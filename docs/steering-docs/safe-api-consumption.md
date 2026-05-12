# Safe API Consumption — Frontend Patterns

This document defines mandatory patterns for safely consuming REST API responses in frontend code. These patterns prevent an entire class of runtime crashes caused by undefined/null data from API responses.

## Why This Matters

In any SaaS application, the frontend makes dozens of API calls per page load. Backend responses can be incomplete, malformed, or return unexpected shapes due to:
- Network errors returning partial responses
- Backend bugs returning `null` instead of an array
- Schema changes where a field is removed or renamed
- Empty database states (new tenants, fresh environments)
- Race conditions between multiple concurrent requests

Without defensive coding, a single missing field crashes the entire page with errors like `Cannot read property 'map' of undefined` or `undefined is not an object`.

**Real-world impact:** In one project, 60+ frontend files had unsafe API access patterns. A single backend change caused cascading white-screen crashes across the entire application.

---

## Pattern 1: Array State from API Response

When setting state from an API response property that should be an array:

```typescript
// NEVER do this
setItems(res.data.items)
setTotal(res.data.total)

// ALWAYS do this
setItems(res.data?.items ?? [])
setTotal(res.data?.total ?? 0)
```

**Why:** Most backends wrap arrays in objects (`{ items: [...], total: N }`). If the property is missing, state becomes `undefined` and any `.map()`, `.filter()`, or `.length` in the render will crash.

---

## Pattern 2: Array Methods on API Response

When calling `.map()`, `.filter()`, `.find()`, or `.length` on data from an API response:

```typescript
// NEVER do this
res.data.rules.map(fn)
res.data.errors.filter(fn)
res.data.plans.length

// ALWAYS do this
(res.data?.rules ?? []).map(fn)
(res.data?.errors ?? []).filter(fn)
(res.data?.plans ?? []).length
```

---

## Pattern 3: Number Formatting

When calling `.toLocaleString()`, `.toFixed()`, or any number method on a value from API data:

```typescript
// NEVER do this
data.total_records.toLocaleString()
financials.margin.toFixed(2)

// ALWAYS do this
(data.total_records ?? 0).toLocaleString()
(financials.margin ?? 0).toFixed(2)
```

**Exception:** Values computed locally from already-guarded inputs (e.g., `(duration_minutes ?? 0) / 60`) are safe and don't need an extra guard.

---

## Pattern 4: Full Response Object to State

When assigning the entire `res.data` to state (common in report pages, detail pages):

```typescript
// This is OK if the render path guards every nested access
setData(res.data)

// But the render MUST guard every property access
{data?.services?.map(...)}
{(data?.total ?? 0).toLocaleString()}
{data?.monthly_breakdown?.length > 0 ? ... : <EmptyState />}
```

If you use `setData(res.data)`, every render access to `data.something` must use `?.` or a prior null check.

---

## Pattern 5: Type-Safe API Calls (No `as any`)

```typescript
// NEVER do this
const data = res.data as any
setRecords(data.usage || [])

// ALWAYS do this — use a type generic on the API call
const res = await apiClient.get<{ usage: UsageRecord[] }>('/endpoint')
setRecords(res.data?.usage ?? [])
```

The `as any` pattern bypasses TypeScript's compile-time safety. Use generics on the API call instead.

---

## Pattern 6: Conditional Rendering with API Data

When rendering sections that depend on API data existing:

```typescript
// Guard the entire section, not just individual fields
{data && (
  <div>
    <p>{(data.count ?? 0).toLocaleString()}</p>
    {(data.items ?? []).map(item => ...)}
  </div>
)}
```

The outer `data &&` prevents rendering when data is null, but you still need `?? []` and `?? 0` inside because `data` could be `{}` (empty object from a malformed response).

---

## Pattern 7: useEffect Cleanup with AbortController

Every API call in a useEffect must have cleanup to prevent race conditions:

```typescript
useEffect(() => {
  const controller = new AbortController()
  const fetchData = async () => {
    try {
      const res = await apiClient.get('/endpoint', { signal: controller.signal })
      setData(res.data?.items ?? [])
    } catch (err) {
      if (!controller.signal.aborted) setError('Failed to load')
    }
  }
  fetchData()
  return () => controller.abort()
}, [dependency])
```

**Why:** React Strict Mode (development) double-mounts components, causing duplicate requests. Without abort cleanup, the first request's response can overwrite the second request's response with stale data. In production, rapid navigation between pages causes the same issue.

---

## Pattern 8: Handling Both Wrapped and Bare Responses

Some APIs return bare arrays while others wrap them. Handle both:

```typescript
const rawData = res.data
const items = Array.isArray(rawData) ? rawData : (rawData?.items ?? [])
```

---

## Common Backend Response Shapes

Most well-designed APIs return wrapped objects, not bare arrays:

| Pattern | Response Shape |
|---------|----------------|
| Paginated list | `{ items: [...], total: N }` |
| Named list | `{ orders: [...] }` |
| Named list + total | `{ orders: [...], total: N }` |
| Settings object | `{ enabled: bool, rules: [...] }` |
| Report data | `{ monthly_breakdown: [...], totals: {...} }` |
| Bare array | `[...]` (avoid this pattern in new APIs) |

When in doubt, read the backend endpoint to check the actual return shape.

---

## Checklist

Before considering any frontend code complete:

- [ ] Every `set*(res.data.property)` uses `res.data?.property ?? fallback`
- [ ] Every `.map()`, `.filter()`, `.find()` on API data has `?? []` fallback
- [ ] Every `.toLocaleString()`, `.toFixed()` on API data has `?? 0` fallback
- [ ] Every `useEffect` with API calls has `AbortController` cleanup
- [ ] No `as any` type assertions on API responses
- [ ] Field names match the backend schema exactly (check for snake_case vs camelCase mismatches)
- [ ] Nested property access uses optional chaining (`data?.nested?.field`)
- [ ] Empty states are handled gracefully (show placeholder UI, not blank space)
