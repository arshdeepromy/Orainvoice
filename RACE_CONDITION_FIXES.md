# Race Condition Fixes

## Problem

Multiple contexts were vulnerable to race conditions, especially with React Strict Mode enabled in development. This caused:

1. **Duplicate API calls** - Each context fetched data twice on mount
2. **Stale data** - First request could complete after second, setting old data
3. **Rate limit hits** - Too many simultaneous requests
4. **Inconsistent state** - State updates from cancelled requests

## Root Cause

React Strict Mode (development only) intentionally double-mounts components to help detect side effects. Without proper cleanup, this causes:

```
1. Component mounts → API call #1 starts
2. Component unmounts (Strict Mode)
3. Component remounts → API call #2 starts
4. API call #1 completes → Updates state (wrong!)
5. API call #2 completes → Updates state (correct)
```

## Solution

Added **AbortController** cleanup to all context fetch functions:

### Pattern Applied

```typescript
const fetchData = useCallback(async (signal?: AbortSignal) => {
  setIsLoading(true)
  try {
    const res = await apiClient.get('/endpoint', { signal })
    setData(res.data)
  } catch (err: any) {
    // Ignore cancelled requests
    if (err.name !== 'CanceledError') {
      setError('Failed to load data')
    }
  } finally {
    setIsLoading(false)
  }
}, [])

useEffect(() => {
  const controller = new AbortController()
  fetchData(controller.signal)
  return () => controller.abort() // Cleanup!
}, [dependencies])
```

## Contexts Fixed

### 1. FeatureFlagContext ✅
**File:** `frontend/src/contexts/FeatureFlagContext.tsx`

**Changes:**
- Added `signal` parameter to `fetchFlags()`
- Created AbortController in useEffect
- Return cleanup function that aborts request
- Ignore CanceledError in catch block

---

### 2. ModuleContext ✅
**File:** `frontend/src/contexts/ModuleContext.tsx`

**Changes:**
- Added `signal` parameter to `fetchModules()`
- Created AbortController in useEffect
- Return cleanup function that aborts request
- Ignore CanceledError in catch block

---

### 3. TerminologyContext ✅
**File:** `frontend/src/contexts/TerminologyContext.tsx`

**Changes:**
- Added `signal` parameter to `fetchTerminology()`
- Created AbortController in useEffect
- Return cleanup function that aborts request
- Ignore CanceledError in catch block

---

### 4. TenantContext ✅
**File:** `frontend/src/contexts/TenantContext.tsx`

**Changes:**
- Added `signal` parameter to `fetchSettings()`
- Created AbortController in useEffect
- Return cleanup function that aborts request
- Ignore CanceledError in catch block

---

### 5. AuthContext ✅ (Already Protected)
**File:** `frontend/src/contexts/AuthContext.tsx`

**Status:** Already had protection using `cancelled` flag pattern

---

## Benefits

### Before Fix
- 8+ API calls on login (4 contexts × 2 mounts)
- Potential stale data
- Rate limit hits
- Wasted bandwidth

### After Fix
- 4 API calls on login (4 contexts × 1 successful call)
- First mount's request is cancelled
- No stale data
- No rate limit issues
- Cleaner network tab

## Testing

### How to Verify

1. Open browser DevTools → Network tab
2. Clear network log
3. Log in as org user
4. Watch network requests

**Expected behavior:**
- Each endpoint called once (not twice)
- Some requests show as "cancelled" (from first mount)
- No duplicate successful requests

### Endpoints to Watch
- `/api/v2/flags` - Feature flags
- `/api/v2/modules` - Module list
- `/api/v2/terminology` - Terminology overrides
- `/api/v1/org/settings` - Organization settings

## React Strict Mode

### What is it?
React Strict Mode is a development-only feature that helps find bugs by:
- Intentionally double-invoking functions
- Intentionally double-mounting components
- Detecting unsafe lifecycle methods

### Should we disable it?
**NO!** Strict Mode helps catch bugs early. The proper solution is to handle cleanup correctly (which we now do).

### Production
Strict Mode is automatically disabled in production builds, so users never experience double-mounting.

## Related Issues Fixed

This also resolves:
- 429 Too Many Requests errors
- "modules.filter is not a function" (partially)
- Inconsistent data loading
- Race conditions between contexts

## Files Modified

1. `frontend/src/contexts/FeatureFlagContext.tsx`
2. `frontend/src/contexts/ModuleContext.tsx`
3. `frontend/src/contexts/TerminologyContext.tsx`
4. `frontend/src/contexts/TenantContext.tsx`

## Best Practices Going Forward

### Always use AbortController for API calls in useEffect:

```typescript
useEffect(() => {
  const controller = new AbortController()
  
  async function fetchData() {
    try {
      const res = await apiClient.get('/endpoint', {
        signal: controller.signal
      })
      setData(res.data)
    } catch (err: any) {
      if (err.name !== 'CanceledError') {
        setError('Failed to load')
      }
    }
  }
  
  fetchData()
  return () => controller.abort()
}, [dependencies])
```

### Key Points:
1. Create AbortController inside useEffect
2. Pass signal to API call
3. Return cleanup function that aborts
4. Ignore CanceledError in catch block
5. Test with React Strict Mode enabled
