# Rate Limiting Issue in Development

## Problem

During development, the signup page was hitting rate limits even with a single developer testing, causing "Unable to load plans" errors.

## Root Causes

### 1. React Strict Mode (Development Only)
React Strict Mode intentionally **doubles all effect calls** in development to help detect side effects:

```tsx
// In frontend/src/main.tsx
<React.StrictMode>
  <App />
</React.StrictMode>
```

**Impact:**
- Each page load triggers `useEffect` twice
- `fetchPlans()` called 2x per page load
- `loadCaptcha()` called 2x per page load
- 5 page refreshes = 10 requests (hits the limit!)

### 2. Low Rate Limit for Development
The default rate limit was **10 requests per minute per IP** - too low for development with React Strict Mode.

**Calculation:**
- 1 page load = 2 requests (Strict Mode)
- 5 page loads = 10 requests
- Rate limit hit immediately!

## Solutions Implemented

### Solution 1: Exclude Public Read-Only Endpoints
**File:** `app/middleware/rate_limit.py`

Excluded public endpoints that don't need strict rate limiting:
```python
_PUBLIC_READ_ONLY_PATHS: set[str] = {
    "/api/v1/auth/plans",
    "/api/v1/auth/captcha",
    "/api/v2/auth/plans",
    "/api/v2/auth/captcha",
}
```

### Solution 2: Increase Rate Limit for Development
**Files:** `app/config.py`, `.env`

Increased auth endpoint rate limit from 10 to 100 requests/minute:

```python
# app/config.py
rate_limit_auth_per_ip_per_minute: int = Field(
    default=10,
    description="Rate limit for auth endpoints per IP per minute"
)
```

```bash
# .env
RATE_LIMIT_AUTH_PER_IP_PER_MINUTE=100
```

## Why React Strict Mode?

React Strict Mode is **intentional** and **beneficial** for development:
- Helps detect side effects and bugs
- Ensures components are resilient to re-mounting
- Only runs in development (disabled in production)
- Should NOT be removed

## Rate Limit Configuration

### Development (.env)
```bash
RATE_LIMIT_PER_USER_PER_MINUTE=100
RATE_LIMIT_PER_ORG_PER_MINUTE=1000
RATE_LIMIT_AUTH_PER_IP_PER_MINUTE=100  # Increased for development
```

### Production (Recommended)
```bash
RATE_LIMIT_PER_USER_PER_MINUTE=100
RATE_LIMIT_PER_ORG_PER_MINUTE=1000
RATE_LIMIT_AUTH_PER_IP_PER_MINUTE=20   # Lower for production security
```

## Current Rate Limits

### Public Read-Only (No Rate Limit)
- `/api/v1/auth/plans`
- `/api/v1/auth/captcha`

### Auth Endpoints (100 req/min in dev)
- `/api/v1/auth/login`
- `/api/v1/auth/signup`
- `/api/v1/auth/token/refresh`
- Other auth endpoints

### Password Reset (5 req/min - Strict)
- `/api/v1/auth/password/reset-request`
- `/api/v1/auth/password/reset`

### Per-User (100 req/min)
- All authenticated requests

### Per-Org (1000 req/min)
- All requests within an organization

## Testing

With the new configuration:
- React Strict Mode: 2 requests per page load
- 50 page loads = 100 requests
- No rate limiting issues during development

## Best Practices

### For Development
1. Keep React Strict Mode enabled
2. Use higher rate limits (100+ req/min)
3. Exclude public read-only endpoints from rate limiting
4. Monitor logs for unexpected request patterns

### For Production
1. Lower rate limits for security (10-20 req/min for auth)
2. Keep public read-only endpoints excluded
3. Monitor rate limit hits in logs
4. Adjust based on actual usage patterns

## Impact

✅ No more rate limit errors during development
✅ React Strict Mode remains enabled for better development experience
✅ Public endpoints load without restrictions
✅ Security maintained for write operations
✅ Easy to adjust for production deployment
