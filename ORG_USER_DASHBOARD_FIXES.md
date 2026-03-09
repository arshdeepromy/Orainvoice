# Org User Dashboard Fixes

## Issues Fixed

### 1. ModuleContext - modules.filter is not a function
**Problem:** API returns `{ modules: [...], total: number }` but frontend expected array directly

**Fix:**
- Updated `fetchModules` to access `res.data.modules` instead of `res.data`
- Added safety check: `(modules || []).filter(...)` in useMemo
- Added fallback to empty array on error

**File:** `frontend/src/contexts/ModuleContext.tsx`

---

### 2. Rate Limiting - 429 Too Many Requests
**Problem:** Rate limits too strict for development with React Strict Mode (doubles requests)

**Fix:**
- Increased `RATE_LIMIT_PER_USER_PER_MINUTE` from 100 to 500
- Increased `RATE_LIMIT_PER_ORG_PER_MINUTE` from 1000 to 5000
- Increased `RATE_LIMIT_AUTH_PER_IP_PER_MINUTE` from 100 to 500

**File:** `.env`

**Note:** Production should use lower limits (100-200 per user, 1000-2000 per org)

---

### 3. InvoiceList - data.items is undefined
**Problem:** Accessing `data.items` when `data` is null or API returns error

**Fixes:**
1. Added safety check in `toggleSelectAll`: `if (!data || !data.items) return`
2. Added safety check in `allSelected`: `data && data.items ? ...`
3. Added safety check in table rendering: `!data || !data.items || data.items.length === 0`
4. Added fallback data structure on API error
5. Validated response structure before setting data

**File:** `frontend/src/pages/invoices/InvoiceList.tsx`

---

### 4. Missing /activity endpoint (404)
**Status:** Not fixed yet - endpoint doesn't exist

**Recommendation:** Either:
- Implement the `/activity` endpoint
- Remove the component that's calling it
- Add error handling to gracefully handle 404

---

## Testing

1. Log in as org user (not global_admin)
2. Navigate to dashboard
3. Verify no console errors
4. Check that modules load correctly
5. Navigate to Invoices page
6. Verify invoices list loads without errors

---

## Files Modified

- `frontend/src/contexts/ModuleContext.tsx` - Fixed modules API response handling
- `frontend/src/pages/invoices/InvoiceList.tsx` - Added safety checks for data.items
- `.env` - Increased rate limits for development

---

## Rate Limit Settings

### Development (.env)
```
RATE_LIMIT_PER_USER_PER_MINUTE=500
RATE_LIMIT_PER_ORG_PER_MINUTE=5000
RATE_LIMIT_AUTH_PER_IP_PER_MINUTE=500
```

### Recommended Production
```
RATE_LIMIT_PER_USER_PER_MINUTE=100
RATE_LIMIT_PER_ORG_PER_MINUTE=1000
RATE_LIMIT_AUTH_PER_IP_PER_MINUTE=20
```
