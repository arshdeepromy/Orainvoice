# Development Environment Status

## Last Updated
2026-03-09 05:30 UTC

## Current Status: ⚠️ BACKEND RESTART REQUIRED

Rate limiting has been disabled for development mode. Backend restart required for changes to take effect.

**Action Required:**
```bash
docker-compose restart app
```

---

## Services Status

### Docker Services
- ✅ PostgreSQL (orainvoice-postgres-1) - Running
- ✅ Redis (orainvoice-redis-1) - Running  
- ✅ FastAPI Backend (orainvoice-app-1) - Running on http://localhost:8080
- ✅ Celery Worker (orainvoice-celery-worker-1) - Running
- ✅ Celery Beat (orainvoice-celery-beat-1) - Running
- ✅ React Frontend (orainvoice-frontend-1) - Running on http://localhost:3000

### Database
- ✅ Database: workshoppro
- ✅ All migrations applied (including extended vehicle fields and lookup_type)
- ✅ Default admin user created: admin@orainvoice.com / admin123

---

## Recent Fixes

### ✅ Accounting Integrations Page Implemented (2026-03-09 06:15) - RESTART REQUIRED

**Problem:** Accounting settings page showing "We couldn't load your accounting integration settings" error.

**Root Cause:** Frontend calling wrong endpoint path (`/org/integrations/accounting` vs `/org/accounting`) and expecting consolidated response that didn't exist.

**Solution:**
- Created new `GET /org/accounting/` dashboard endpoint returning xero, myob, and sync_log data
- Added AccountingDashboardResponse, AccountingConnectionDetail, SyncLogEntryDashboard schemas
- Added `POST /org/accounting/sync/{entry_id}/retry` endpoint
- Updated frontend to use correct endpoint paths
- Updated _connection_to_dict to include account_name, sync_status, error_message fields

**Files Modified:**
- `app/modules/accounting/router.py` - Added dashboard and retry endpoints
- `app/modules/accounting/schemas.py` - Added dashboard schemas
- `app/modules/accounting/service.py` - Updated connection dict
- `frontend/src/pages/settings/AccountingIntegrations.tsx` - Fixed API paths

**Status:** ⚠️ BACKEND RESTART REQUIRED
```bash
docker-compose restart app
```

**Issue Logged:** ISSUE-023 in docs/ISSUE_TRACKER.md

### ✅ OrgAdminDashboard API Mismatch Fixed (2026-03-09 05:45)

**Problem:** Dashboard showing "Failed to load dashboard data" error. No data displayed on org user dashboard.

**Root Cause:** Frontend was calling correct endpoints but expecting wrong data structure. The OrgAdminData interface didn't match the actual backend API schemas.

**Solution:**
- Updated OrgAdminData interface to match backend RevenueSummaryResponse, OutstandingInvoicesResponse, StorageUsageResponse
- Removed call to non-existent `/reports/activity` endpoint
- Fixed field name mismatches (total_inclusive vs current_period, total_outstanding vs total, storage_used_bytes vs used_bytes)
- Added outstanding invoices table showing top 10 with overdue highlighting
- Added storage alert banner for high usage
- Calculate overdue count from invoices array

**Files Modified:**
- `frontend/src/pages/dashboard/OrgAdminDashboard.tsx` - Fixed API data structure

**Status:** ✅ FIXED - Dashboard now loads with real data

**Issue Logged:** ISSUE-022 in docs/ISSUE_TRACKER.md

### ⚠️ Rate Limiting Disabled for Development (2026-03-09 05:30) - RESTART REQUIRED

**Problem:** 429 (Too Many Requests) errors on login in development mode

**Root Cause:** Rate limiting was still enabled in development. Even with increased limits (500 req/min), this is too restrictive for development where React Strict Mode doubles requests and developers frequently test flows.

**Solution:** 
- Set all rate limits to 0 in `.env` to completely disable rate limiting
- Updated `app/middleware/rate_limit.py` to skip rate limiting when limit <= 0
- Development mode now has zero rate limiting
- Production can still set appropriate limits via environment variables

**Files Modified:**
- `.env` - Set RATE_LIMIT_PER_USER_PER_MINUTE=0, RATE_LIMIT_PER_ORG_PER_MINUTE=0, RATE_LIMIT_AUTH_PER_IP_PER_MINUTE=0
- `app/middleware/rate_limit.py` - Added limit <= 0 check

**Status:** ⚠️ BACKEND RESTART REQUIRED
```bash
docker-compose restart app
```

**Issue Logged:** ISSUE-021 in docs/ISSUE_TRACKER.md

### ✅ Organization Management - Hard Delete & Activate/Deactivate (2026-03-09 04:15)

**Features Added:**
- Hard delete: Permanently remove organization and ALL data from database
- Activate: Activate organization from any non-deleted state
- Deactivate: Deactivate organization with reason
- Frontend UI: Separate "Soft Delete" and "Hard Delete" buttons
- Immediate UI update: Hard deleted orgs removed from table instantly

**Backend Implementation:**
- `PUT /api/v1/admin/organisations/{id}` - Added actions: activate, deactivate, hard_delete_request
- `DELETE /api/v1/admin/organisations/{id}/hard` - New endpoint for hard delete confirmation
- Multi-step confirmation with token + "PERMANENTLY DELETE" text
- Audit logs kept for compliance even after hard delete

**Frontend Implementation:**
- HardDeleteModal with two-step confirmation
- Immediate UI update without refetching data
- Clear warnings about irreversible action
- Lists all data that will be deleted

**Files Modified:**
- `app/modules/admin/schemas.py` - Added OrgHardDeleteRequest, OrgHardDeleteResponse
- `app/modules/admin/service.py` - Added activate, deactivate, hard_delete_organisation
- `app/modules/admin/router.py` - Added hard delete endpoint
- `frontend/src/pages/admin/Organisations.tsx` - Added hard delete UI
- `ORGANIZATION_MANAGEMENT.md` - Complete documentation
- `HARD_DELETE_UI_IMPLEMENTATION.md` - Frontend implementation details

**Status:** ✅ IMPLEMENTED - Ready for testing

### ✅ Signup Button Loading Issue (2026-03-09 04:00)

**Problem:** Signup button stuck in loading state, transaction rollback after organisation creation

**Root Cause:** The `public_signup()` function was not committing the database transaction. It only used `await db.flush()` which writes to the database but doesn't commit. When any error occurred (like Redis connection issues), the entire transaction would roll back.

**Solution:** Added proper transaction management to signup endpoint
- Added explicit `await db.commit()` after successful signup
- Added `await db.rollback()` on errors
- Added comprehensive error handling for both validation and unexpected errors
- Added logging for debugging

**Files Modified:**
- `app/modules/auth/router.py` - Added transaction management and error handling

**Status:** ✅ FIXED - Backend restarted, ready for testing

### ✅ Rate Limiting Issues (2026-03-09)

**Problem:** "Unable to load plans" error on first page load, requiring refresh

**Root Cause:** React Strict Mode doubles all effect calls in development (2x API calls per page load). Auth endpoints had rate limit of 10 req/min per IP - too low for development.

**Solution:** 
- Excluded public read-only endpoints (`/auth/plans`, `/auth/captcha`, `/auth/verify-captcha`) from strict rate limiting
- Increased auth endpoint rate limit from 10 to 100 req/min for development
- React Strict Mode kept enabled (beneficial for development)

**Files Modified:**
- `app/middleware/rate_limit.py` - Added `_PUBLIC_READ_ONLY_PATHS` set
- `app/config.py` - Updated rate limit settings
- `.env` - Increased RATE_LIMIT_AUTH_PER_IP_PER_MINUTE to 100

**Status:** ✅ FIXED

### ✅ CAPTCHA Verification with Verify Button (2026-03-09)

**Problem:** User requested verify button with animated success message

**Solution:**
- Added "Verify" button next to CAPTCHA input
- Created `/api/v1/auth/verify-captcha` endpoint for pre-verification
- Added animated green success message with fadeIn animation
- Signup button only enabled after CAPTCHA verified
- CAPTCHA verified twice for security (once on verify button, once on signup)

**CAPTCHA Flow:**
1. User loads signup page → CAPTCHA image generated and stored in Redis (5 min TTL)
2. User enters code and clicks "Verify" → `/verify-captcha` endpoint verifies with `delete_after=False` → CAPTCHA stays in Redis
3. User clicks "Sign Up" → `/signup` endpoint verifies CAPTCHA again with `delete_after=True` → CAPTCHA deleted after successful verification
4. Double verification is intentional for security (prevents replay attacks)

**Files Modified:**
- `app/core/captcha.py` - Added `delete_after` parameter to `verify_captcha()`
- `app/modules/auth/router.py` - Added verify-captcha endpoint
- `app/middleware/auth.py` - Added to public paths
- `app/middleware/rate_limit.py` - Added to rate limit exclusions
- `frontend/src/pages/auth/Signup.tsx` - Added verify button and success message
- `frontend/src/index.css` - Added fadeIn animation

**Status:** ✅ IMPLEMENTED

### ✅ Signup Password Field and Dynamic Trial Period (2026-03-09)

**Problem:** Signup wasn't asking for password and trial period was hardcoded

**Solution:**
- Removed all Stripe integration from trial signup (no payment collection during trial)
- Added password field to signup form (8-128 characters)
- User account created with hashed password and `is_email_verified=True`
- User can immediately login after signup without email verification
- Trial period now pulled from subscription plan's `trial_duration` and `trial_duration_unit` fields
- Frontend displays dynamic trial period (e.g., "Start your 30-day free trial")

**Files Modified:**
- `app/modules/organisations/schemas.py` - Added password field
- `app/modules/organisations/service.py` - Updated public_signup to hash password
- `app/modules/auth/router.py` - Updated signup endpoint
- `frontend/src/pages/auth/signup-types.ts` - Added password field
- `frontend/src/pages/auth/signup-validation.ts` - Added password validation
- `frontend/src/pages/auth/Signup.tsx` - Added password input and dynamic trial display

**Status:** ✅ IMPLEMENTED

### ✅ Carjam ABCD API Integration (2026-03-09)

**Features:**
1. ABCD API support with automatic retry logic (3 attempts, 1s delays)
2. Created ABCD test endpoint `POST /api/v1/admin/integrations/carjam/lookup-test-abcd`
3. Added lookup_type tracking to distinguish between 'basic' and 'abcd' lookups
4. ABCD data stored in global_vehicles table
5. Extended vehicle fields (15 new columns: VIN, chassis, engine_no, transmission, etc.)

**Files Modified:**
- `app/integrations/carjam.py` - Added ABCD API support with retry logic
- `app/modules/admin/router.py` - Added ABCD test endpoint
- `app/modules/admin/service.py` - Added ABCD lookup service
- `app/modules/vehicles/service.py` - Updated to track lookup_type
- `alembic/versions/2026_03_09_1536-202603091536_add_extended_vehicle_fields.py` - Extended fields migration
- `alembic/versions/2026_03_09_1600-add_lookup_type_field.py` - Lookup type tracking migration

**Status:** ✅ IMPLEMENTED

---

## Quick Start Commands

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f app

# Restart backend
docker-compose restart app

# Stop all services
docker-compose down
```

---

## API Endpoints

### Authentication
- POST /api/v1/auth/login - Login with email/password
- POST /api/v1/auth/signup - Public signup (requires CAPTCHA)
- POST /api/v1/auth/refresh - Refresh access token
- GET /api/v1/auth/captcha - Get CAPTCHA image
- POST /api/v1/auth/verify-captcha - Verify CAPTCHA code
- GET /api/v1/auth/plans - List public subscription plans

### Admin
- GET /api/v1/admin/subscription-plans - List subscription plans
- POST /api/v1/admin/subscription-plans - Create subscription plan
- POST /api/v1/admin/integrations/carjam/lookup-test - Test Carjam lookup
- POST /api/v1/admin/integrations/carjam/lookup-test-abcd - Test Carjam ABCD lookup

### Vehicles
- POST /api/v1/vehicles/lookup - Look up vehicle by rego (cache-first)
- POST /api/v1/vehicles/{vehicle_id}/refresh - Force Carjam re-fetch

---

## Default Credentials

**Global Admin:**
- Email: admin@orainvoice.com
- Password: admin123
- Role: global_admin
- JWT: org_id = null (not tied to specific organization)

---

## Known Issues

None currently.

---

## Documentation

- `QUICKSTART.md` - Quick start guide
- `DOCKER_SETUP.md` - Detailed Docker setup
- `DOCKER_README.md` - Docker overview
- `ARCHITECTURE.md` - System architecture
- `DEV_CREDENTIALS.md` - Development credentials
- `SIGNUP_BUTTON_FIX.md` - Signup button loading issue fix
- `RATE_LIMIT_FIX.md` - Rate limiting fix details
- `CAPTCHA_VERIFY_BUTTON.md` - CAPTCHA verification implementation
- `SIGNUP_IMPROVEMENTS.md` - Signup flow improvements
- `CARJAM_ABCD_IMPLEMENTATION.md` - Carjam ABCD API integration
- `ABCD_RETRY_LOGIC.md` - ABCD retry logic details
- `LOOKUP_TYPE_TRACKING.md` - Lookup type tracking implementation
- `ABCD_DATABASE_STORAGE.md` - ABCD data storage details

---

## Next Steps

**Ready for Testing:**
1. Test signup flow with CAPTCHA verification
2. Verify transaction commits properly
3. Check error handling and logging
4. Test with various error scenarios (invalid email, duplicate email, etc.)

**Potential Future Enhancements:**
- Email verification flow (currently bypassed for trial signups)
- Payment method collection when trial ends
- Vehicle profile page showing all extended data
- VIN-based vehicle lookup
- Vehicle history tracking
- Bulk vehicle import/export
