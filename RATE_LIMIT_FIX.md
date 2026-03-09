# Rate Limiting Fix for Signup Page

## Issue

The signup page was showing "Unable to load plans. Please try again later." on first load, requiring users to refresh the page. This was caused by rate limiting on the `/api/v1/auth/plans` endpoint.

## Root Cause

The `/api/v1/auth/plans` endpoint was being rate limited because:
1. It matches the auth endpoint prefix (`/api/v1/auth/`)
2. Auth endpoints have strict rate limiting (10 requests/minute per IP)
3. Multiple page loads or refreshes would quickly hit the limit
4. The endpoint is public and read-only, so strict rate limiting wasn't necessary

## Solution

Excluded public read-only endpoints from strict rate limiting:

### Changes Made

**File: `app/middleware/rate_limit.py`**

1. Added new constant for public read-only paths:
```python
_PUBLIC_READ_ONLY_PATHS: set[str] = {
    "/api/v1/auth/plans",
    "/api/v1/auth/captcha",
    "/api/v2/auth/plans",
    "/api/v2/auth/captcha",
}
```

2. Updated rate limit check to skip these endpoints:
```python
# Skip rate limiting for public read-only endpoints
if is_auth_endpoint(path) and path not in _PUBLIC_READ_ONLY_PATHS:
    # Apply rate limiting
```

**File: `frontend/src/pages/auth/Signup.tsx`**

Added better error handling for rate limit errors:
```typescript
if (response.status === 429) {
  setPlansError('Too many requests. Please wait a moment and try again.')
}
```

## Testing

Tested with 15 consecutive requests - all returned 200 OK:
```bash
for i in {1..15}; do 
  curl -s -o /dev/null -w "%{http_code} " http://localhost:8080/api/v1/auth/plans
done
# Result: 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200
```

## Impact

- ✅ Signup page loads correctly on first visit
- ✅ No more "Unable to load plans" error
- ✅ CAPTCHA image loads without rate limiting
- ✅ Users can refresh the page multiple times without issues
- ✅ Rate limiting still applies to other auth endpoints (login, signup, etc.)

## Rate Limiting Summary

### Endpoints WITH Rate Limiting (10 req/min per IP):
- `/api/v1/auth/login`
- `/api/v1/auth/signup`
- `/api/v1/auth/password/reset-request`
- All other `/api/v1/auth/*` endpoints

### Endpoints WITHOUT Rate Limiting:
- `/api/v1/auth/plans` (public read-only)
- `/api/v1/auth/captcha` (public read-only)
- `/api/v2/auth/plans` (public read-only)
- `/api/v2/auth/captcha` (public read-only)

### Stricter Rate Limiting (5 req/min per IP):
- `/api/v1/auth/password/reset-request`
- `/api/v1/auth/password/reset`

## User Experience

**Before:**
1. User visits `/signup`
2. Sees error: "Unable to load plans. Please try again later."
3. Must click "Retry" or refresh page
4. May hit rate limit again if refreshing too quickly

**After:**
1. User visits `/signup`
2. Page loads immediately with plans and CAPTCHA
3. Can refresh multiple times without issues
4. Smooth signup experience

## Security Considerations

- Public read-only endpoints don't need strict rate limiting
- They don't expose sensitive data or allow state changes
- Still protected by general application security measures
- Write operations (signup, login) remain rate limited
