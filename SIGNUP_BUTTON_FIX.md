# Signup Button Loading Issue - Fix

## Problem
Signup button gets stuck in loading state when user tries to sign up. Backend logs showed:
- Organisation INSERT succeeds
- Transaction ROLLBACK occurs
- User INSERT never happens
- "Rate limiter Redis error during check" message appears

## Root Cause
The `public_signup()` function in `app/modules/organisations/service.py` was not committing the database transaction. It only used `await db.flush()` which writes to the database but doesn't commit.

When any error occurred after the organisation was created (like a Redis connection issue in the rate limiter), the entire transaction would roll back, leaving no organisation or user in the database. The signup endpoint would fail with a 500 error, causing the frontend button to stay in loading state indefinitely.

## Solution
Added proper transaction management and error handling to the signup endpoint in `app/modules/auth/router.py`:

1. **Added explicit commit**: After `public_signup()` succeeds, explicitly call `await db.commit()` to commit the transaction
2. **Added rollback on error**: If any exception occurs, call `await db.rollback()` to clean up
3. **Added comprehensive error handling**: Catch both `ValueError` (validation errors) and generic `Exception` (unexpected errors)
4. **Added logging**: Log unexpected errors with full traceback for debugging

## Changes Made

### File: `app/modules/auth/router.py`

1. Added `import logging` at the top
2. Added `logger = logging.getLogger(__name__)` after router initialization
3. Updated signup endpoint error handling:

```python
try:
    result = await public_signup(...)
    # Commit the transaction after successful signup
    await db.commit()
except ValueError as exc:
    await db.rollback()
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )
except Exception as exc:
    await db.rollback()
    logger.exception("Unexpected error during signup")
    return JSONResponse(
        status_code=500,
        content={"detail": "An error occurred during signup. Please try again."},
    )
```

## Testing
After this fix:
1. User should be able to complete signup successfully
2. If any error occurs, the transaction will be rolled back cleanly
3. Frontend will receive a proper error response instead of hanging
4. Backend logs will show detailed error information for debugging

## CAPTCHA Flow (Confirmed Working)
1. User loads signup page → CAPTCHA image generated and stored in Redis (5 min TTL)
2. User enters code and clicks "Verify" → `/verify-captcha` endpoint verifies with `delete_after=False` → CAPTCHA stays in Redis
3. User clicks "Sign Up" → `/signup` endpoint verifies CAPTCHA again with `delete_after=True` → CAPTCHA deleted after successful verification
4. This double verification is intentional for security (prevents replay attacks)

## Related Files
- `app/modules/auth/router.py` - Signup endpoint with transaction management
- `app/modules/organisations/service.py` - public_signup function (no changes needed)
- `app/core/captcha.py` - CAPTCHA verification logic (working correctly)
