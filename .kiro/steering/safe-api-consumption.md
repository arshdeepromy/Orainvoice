---
inclusion: fileMatch
fileMatchPattern: 'frontend/src/**/*.tsx'
---

# Safe API Consumption — Mandatory Patterns for Frontend Code

This file is loaded whenever a `.tsx` file is read or edited. It enforces the patterns that prevent the class of crash bugs documented in `#[[file:docs/API_RESPONSE_SAFETY_AUDIT.md]]` (60+ files affected, ISSUE-006/012/013/017/018/020).

Every API call in this codebase MUST follow these patterns. No exceptions.

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

This applies to every `set*()` call that reads from `res.data.something`. The backend wraps arrays in objects (`{ items: [...], total: N }`), and if the property is missing, state becomes `undefined` and any `.map()`, `.filter()`, or `.length` in the render will crash.

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

## Pattern 3: Number Formatting

When calling `.toLocaleString()`, `.toFixed()`, or any number method on a value from API data or computed from API data:

```typescript
// NEVER do this
data.total_records.toLocaleString()
financials.margin.toFixed(2)

// ALWAYS do this
(data.total_records ?? 0).toLocaleString()
(financials.margin ?? 0).toFixed(2)
```

Exception: values computed locally from already-guarded inputs (e.g., `(duration_minutes ?? 0) / 60`) are safe and don't need an extra guard.

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

## Pattern 7: useEffect Cleanup with AbortController

Every API call in a useEffect must have cleanup to prevent race conditions (ISSUE-014):

```typescript
useEffect(() => {
  const controller = new AbortController()
  const fetch = async () => {
    try {
      const res = await apiClient.get('/endpoint', { signal: controller.signal })
      setData(res.data?.items ?? [])
    } catch (err) {
      if (!controller.signal.aborted) setError('Failed to load')
    }
  }
  fetch()
  return () => controller.abort()
}, [dependency])
```

## Quick Reference: Common Backend Response Shapes

Most endpoints in this app return wrapped objects, not bare arrays:

| Pattern | Example Endpoint | Response Shape |
|---------|-----------------|----------------|
| Paginated list | `GET /vehicles` | `{ items: [...], total: N }` |
| Named list | `GET /job-cards` | `{ job_cards: [...] }` |
| Named list + total | `GET /api/v2/jobs` | `{ jobs: [...], total: N }` |
| Settings object | `GET /notifications/overdue-rules` | `{ reminders_enabled: bool, rules: [...] }` |
| Report data | `GET /reports/revenue` | `{ monthly_breakdown: [...], totals: {...} }` |
| Bare array | `GET /auth/mfa/methods` | `[...]` (rare) |

When in doubt, read the backend router function to check the actual return shape.

## Checklist Before Submitting Frontend Code

Before considering any frontend code complete:

- [ ] Every `set*(res.data.property)` uses `res.data?.property ?? fallback`
- [ ] Every `.map()`, `.filter()`, `.find()` on API data has `?? []` fallback
- [ ] Every `.toLocaleString()`, `.toFixed()` on API data has `?? 0` fallback
- [ ] Every `useEffect` with API calls has `AbortController` cleanup
- [ ] No `as any` type assertions on API responses
- [ ] Field names match the backend Pydantic schema exactly
