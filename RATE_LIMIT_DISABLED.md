# Rate Limiting Disabled for Development Mode

## Issue

User getting 429 (Too Many Requests) errors when trying to login in development mode. Unable to access the application.

```
✕Request failed with status code 429
```

## Root Cause

Rate limiting was still enabled in development mode. While previous fix (ISSUE-016) increased limits from 100 to 500 req/min, this is still too restrictive for development where:

1. React Strict Mode doubles all requests (development best practice)
2. Multiple contexts fetch data on component mount
3. Developers frequently refresh pages and test different flows
4. No rate limiting should exist in development mode at all

## Solution

Completely disabled rate limiting for development by setting all limits to 0.

### Changes Made

**File: `.env`**

Set all rate limit environment variables to 0:
```bash
# --- Rate Limiting ---
# Set to 0 to disable rate limiting in development
RATE_LIMIT_PER_USER_PER_MINUTE=0
RATE_LIMIT_PER_ORG_PER_MINUTE=0
RATE_LIMIT_AUTH_PER_IP_PER_MINUTE=0
```

**File: `app/middleware/rate_limit.py`**

Added check to skip rate limiting when limit is 0 or negative:
```python
async def _check_rate_limit(
    redis: Redis,
    key: str,
    limit: int,
    now: float,
) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds) using a sorted-set sliding window.
    
    If limit is 0, rate limiting is disabled and always returns allowed=True.
    """
    # If limit is 0, rate limiting is disabled
    if limit <= 0:
        return True, 0
    
    # ... rest of rate limiting logic
```

## Backend Restart Required

The backend must be restarted for the `.env` changes to take effect:

```bash
# Restart just the backend
docker-compose restart app

# Or restart all services
docker-compose down
docker-compose up -d
```

## Verification

After restarting the backend, verify rate limiting is disabled:

1. Login at http://localhost:3000
2. Refresh the page multiple times rapidly
3. Navigate between different pages
4. Should see no 429 errors in browser console or network tab

## Rate Limiting Summary

### Development Mode (Current)
- Per-user: DISABLED (0 req/min)
- Per-org: DISABLED (0 req/min)
- Auth endpoints: DISABLED (0 req/min)
- Password reset: DISABLED (0 req/min)

### Production Mode (Recommended)
- Per-user: 100-200 req/min
- Per-org: 1000-2000 req/min
- Auth endpoints: 10-20 req/min
- Password reset: 5 req/min

## Production Deployment

When deploying to production, set appropriate rate limits in the production `.env` file:

```bash
# Production rate limits
RATE_LIMIT_PER_USER_PER_MINUTE=100
RATE_LIMIT_PER_ORG_PER_MINUTE=1000
RATE_LIMIT_AUTH_PER_IP_PER_MINUTE=10
```

The middleware will automatically enforce these limits when they are greater than 0.

## Related Issues

- **ISSUE-016**: Previous fix that increased rate limits to 500 req/min (still too restrictive)
- **ISSUE-021**: This fix - completely disabled rate limiting for development

## Files Modified

- `.env` - Set all rate limits to 0
- `app/middleware/rate_limit.py` - Added limit <= 0 check
- `docs/ISSUE_TRACKER.md` - Logged as ISSUE-021
- `DEV_ENVIRONMENT_STATUS.md` - Updated status

## Status

✅ IMPLEMENTED - Backend restart required

After restarting the backend, development mode will have zero rate limiting and login should work without 429 errors.
