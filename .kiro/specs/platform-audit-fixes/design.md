# Platform Audit Fixes — Bugfix Design

## Overview

This design addresses 21 defects identified across two independent audits of the OraInvoice Universal Platform. The bugs fall into three categories:

1. **Security vulnerabilities** (4 defects): SQL injection via string interpolation in RLS context, hardcoded secrets, localStorage refresh tokens, disabled SSL verification
2. **Architecture/code quality** (3 defects): Duplicate router registrations in main.py, blanket exception catching, rate limiter fail-open
3. **Frontend-backend contract mismatches** (14 defects): The backend notification endpoints are complete and correct; the frontend pages send wrong field names, expect wrong response shapes, or use wrong API paths

The fix strategy is: patch security/architecture issues in the backend, and realign all frontend notification pages to match the existing backend schemas. No backend notification API changes are needed except adding bounce webhook endpoints and i18n template rendering.

## Glossary

- **Bug_Condition (C)**: The set of conditions across 21 defects that trigger incorrect behavior — security vulnerabilities in backend code, and frontend-backend contract mismatches in the notifications subsystem
- **Property (P)**: The desired correct behavior — parameterized queries, validated secrets, correct API shapes, matching field names
- **Preservation**: All existing backend API contracts, non-notification frontend pages, and working functionality must remain unchanged
- **RLS**: Row-Level Security — PostgreSQL feature that scopes queries to the current organisation
- **SmtpConfigRequest**: Backend Pydantic schema in `app/modules/admin/schemas.py` defining the 10 fields for SMTP configuration
- **Contract mismatch**: Frontend sends/expects field names or response shapes that differ from the backend Pydantic schemas

## Bug Details

### Fault Condition

The bugs manifest across three domains. Security bugs are triggered by any request that exercises the vulnerable code paths. Contract mismatches are triggered whenever a user navigates to any of the 7 affected notification/settings frontend pages.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { category, defect_id, context }
  OUTPUT: boolean

  // Security bugs — triggered by specific backend code paths
  IF input.category == "security" THEN
    RETURN input.defect_id IN ["rls_interpolation", "hardcoded_secrets",
                                "localstorage_refresh", "ssl_disabled"]
  END IF

  // Architecture bugs — triggered by app startup or error/rate-limit paths
  IF input.category == "architecture" THEN
    RETURN input.defect_id IN ["router_duplication", "blanket_except",
                                "rate_limiter_fail_open"]
  END IF

  // Contract mismatches — triggered when user visits affected pages
  IF input.category == "contract_mismatch" THEN
    RETURN input.context.page IN ["Integrations/smtp", "OverdueRules",
           "NotificationPreferences", "TemplateEditor", "WofRegoReminders",
           "NotificationLog", "Settings"]
         OR input.defect_id IN ["missing_bounce_webhook", "missing_i18n_render"]
  END IF

  RETURN false
END FUNCTION
```

### Examples

- **1.1 SQL Injection**: `_set_rls_org_id(session, "'; DROP TABLE users; --")` — UUID validation catches this, but the f-string pattern is still a SQL injection vector if validation is ever bypassed
- **1.8 SMTP fields**: User opens Integrations → SMTP tab → sees only 4 fields (api_key, domain, from_name, reply_to) instead of 10 → cannot configure provider, host, port, username, password, from_email
- **1.9 OverdueRules API shape**: Page sends `PUT /notifications/overdue-rules { enabled, rules: [...] }` but backend expects individual `POST`, `PUT /{rule_id}`, `DELETE /{rule_id}` endpoints
- **1.11 NotificationPreferences response**: Page expects `{ preferences: [...] }` but backend returns `{ categories: [{ category, preferences: [...] }] }`
- **1.13 TemplateEditor PUT path**: Page sends `PUT /notifications/templates/{uuid}` but backend route expects `PUT /notifications/templates/{template_type}` (e.g., `"invoice_issued"`)
- **1.17 NotificationLog field**: Page reads `entry.template_name` but backend returns `template_type` — Template column shows `undefined`

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- All backend notification API contracts (schemas, endpoints, response shapes) remain exactly as-is
- All non-notification frontend pages (invoicing, inventory, POS, jobs, quotes, etc.) continue functioning identically
- JWT authentication and authorization flow continues working (only storage mechanism for refresh tokens changes)
- All existing API routes continue responding at the same URL paths with the same HTTP methods
- Rate limiting behavior when Redis IS available remains unchanged
- Service-layer functions that complete successfully continue returning the same response shapes

**Scope:**
All inputs that do NOT involve the 21 identified defects should be completely unaffected. This includes:
- All backend CRUD operations on notifications, templates, overdue rules, preferences
- Mouse/keyboard interactions on unaffected frontend pages
- Database queries that don't go through the RLS context setter
- API requests to endpoints not listed in the defect inventory

## Hypothesized Root Cause

Based on the two audit reports, the root causes are well-understood:

1. **SQL Injection (1.1)**: The developer added a comment explaining that PostgreSQL `SET` commands don't support `$1` placeholders via asyncpg, so they used f-string interpolation. The fix is to use SQLAlchemy's `text().bindparams()` which handles this correctly, or use the `set_config()` function which does accept parameters.

2. **Hardcoded Secrets (1.2)**: Default placeholder values were set for `jwt_secret` and `encryption_master_key` in `app/config.py` for development convenience, but no startup validation ensures they're overridden in production.

3. **localStorage Refresh Tokens (1.3)**: The `frontend/src/api/client.ts` stores refresh tokens in `localStorage` for simplicity. The `withCredentials: true` is already set on the axios client, indicating httpOnly cookie support was intended but not completed.

4. **Disabled SSL (1.4)**: `app/core/security.py` line 90-91 explicitly sets `check_hostname = False` and `verify_mode = ssl.CERT_NONE` with a comment "Use CERT_REQUIRED in production with proper CA" — this was a development shortcut never updated.

5. **Router Duplication (1.5)**: V1 routers are re-registered under `/api/v2/` prefixes for "continuity", duplicating ~16 router registrations. This was likely a migration convenience that should be replaced with a version-prefix loop or removed.

6. **Blanket Exception Catching (1.6)**: Service-layer functions use `except Exception:` as a catch-all pattern, likely from early development when error handling wasn't refined.

7. **Rate Limiter Fail-Open (1.7)**: When Redis is unavailable, the rate limiter allows all requests through rather than denying them — a design choice that prioritized availability over security.

8. **Frontend Contract Mismatches (1.8–1.19)**: The frontend notification pages were built against assumed API shapes before the backend was finalized. The backend schemas are correct and complete; the frontend simply never updated to match them.

9. **Missing Bounce Webhooks (1.20)**: The service function `flag_bounced_email_on_customer()` exists but no router endpoint exposes it to external webhook providers.

10. **Missing i18n Rendering (1.21)**: Template rendering always uses the default English templates without checking the organisation's configured locale.

## Correctness Properties

Property 1: Fault Condition — Security Vulnerabilities Fixed

_For any_ input that exercises the security-vulnerable code paths (RLS context setting, application startup with default secrets, user authentication token storage, SSL connection establishment), the fixed code SHALL use parameterized queries for RLS, reject default secret values at startup, store refresh tokens in httpOnly cookies, and enable SSL hostname verification and certificate validation.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Fault Condition — Frontend-Backend Contracts Aligned

_For any_ navigation to a notification-related frontend page (Integrations/SMTP, OverdueRules, NotificationPreferences, TemplateEditor, WofRegoReminders, NotificationLog, Settings), the fixed frontend SHALL send requests matching the backend Pydantic schemas and correctly consume the backend response shapes, displaying all fields with correct names.

**Validates: Requirements 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15, 2.16, 2.17, 2.18, 2.19**

Property 3: Fault Condition — Architecture Issues Resolved

_For any_ application startup, error handling path, or rate-limiting invocation with Redis unavailable, the fixed code SHALL have deduplicated router registrations, catch specific exception types with meaningful logging, and fail closed on rate limiting.

**Validates: Requirements 2.5, 2.6, 2.7**

Property 4: Fault Condition — Missing Backend Features Added

_For any_ email bounce event from Brevo or SendGrid, the fixed system SHALL expose webhook receiver endpoints that verify signatures and flag customer emails as bounced. _For any_ notification sent to an organisation with a non-English locale, the system SHALL render templates in the configured locale with English fallback.

**Validates: Requirements 2.20, 2.21**

Property 5: Preservation — Existing Functionality Unchanged

_For any_ input that does NOT involve the 21 identified defects (all existing backend API contracts, non-notification frontend pages, successful service-layer operations, rate limiting with Redis available), the fixed system SHALL produce exactly the same behavior as the original system.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

#### Security Fixes

**File**: `app/core/database.py`
**Function**: `_set_rls_org_id`
**Change**: Replace f-string interpolation with PostgreSQL `set_config()` function call that accepts parameterized values:
```python
await session.execute(
    text("SELECT set_config('app.current_org_id', :org_id, true)"),
    {"org_id": validated}
)
```
The `set_config(name, value, is_local)` function with `is_local=true` is equivalent to `SET LOCAL` but supports parameterized queries.

**File**: `app/config.py`
**Function**: Module-level / add validator
**Change**: Add a `model_validator` or startup check that raises `ValueError` if `jwt_secret` or `encryption_master_key` equals `"change-me-in-production"` when `environment` is `"production"` or `"staging"`.

**File**: `frontend/src/api/client.ts`
**Change**:
1. Remove `localStorage.getItem('refresh_token')` and `localStorage.setItem/removeItem` calls
2. Remove `storedRefreshToken` variable and `getRefreshToken()`/`setRefreshToken()` exports
3. In `refreshAccessToken()`, send POST without a body — the refresh token comes from the httpOnly cookie (already configured with `withCredentials: true`)
4. Backend auth endpoint must be updated to set refresh token as httpOnly cookie in the response instead of returning it in the JSON body

**File**: `app/core/security.py`
**Function**: `DatabaseSSLConfig.to_connect_args`
**Change**: Replace `check_hostname = False` and `verify_mode = ssl.CERT_NONE` with `check_hostname = True` and `verify_mode = ssl.CERT_REQUIRED`. Remove the misleading comment.

#### Architecture Fixes

**File**: `app/main.py`
**Function**: `create_app`
**Change**: Remove the duplicate V1-under-V2 router registrations (the block that re-registers `auth_router`, `admin_router`, etc. under `/api/v2/` prefixes). If V2 compatibility is needed, use a loop:
```python
V1_ROUTERS_FOR_V2 = [
    (auth_router, "auth"), (admin_router, "admin"), ...
]
for router, tag in V1_ROUTERS_FOR_V2:
    app.include_router(router, prefix=f"/api/v2/{tag}", tags=[f"v2-{tag}"])
```

**File**: Service-layer files (multiple)
**Change**: Audit `except Exception:` patterns and replace with specific exception types (`ValueError`, `KeyError`, `SQLAlchemyError`, etc.) with meaningful error logging. This is a targeted refactor — only change patterns identified in the audit.

**File**: Rate limiter middleware
**Change**: When Redis connection fails, return HTTP 503 (Service Unavailable) or apply a conservative in-memory fallback limit instead of allowing unlimited requests.

#### Frontend Contract Fixes

**File**: `frontend/src/pages/admin/Integrations.tsx`
**Change**: Update `INTEGRATION_FIELDS.smtp` to include all 10 fields from `SmtpConfigRequest`:
- Add `provider` (dropdown: brevo/sendgrid/smtp), `from_email`, `host`, `port`, `username`, `password`
- Make `host`, `port`, `username`, `password` conditionally visible when `provider === 'smtp'`
- Make `api_key` conditionally visible when `provider === 'brevo' || provider === 'sendgrid'`

**File**: `frontend/src/pages/notifications/OverdueRules.tsx`
**Change**:
1. Change `fetchRules` to consume `{ rules, total, reminders_enabled }` response shape — map `reminders_enabled` to `enabled` state
2. Replace bulk `PUT /notifications/overdue-rules` with individual CRUD: `POST` for new rules, `PUT /{rule_id}` for updates, `DELETE /{rule_id}` for removals
3. Replace `toggleEnabled` to use `PUT /notifications/overdue-rules-toggle?enabled=`
4. Map between UI `channel` field and backend `send_email`/`send_sms` booleans:
   - `'email'` → `{ send_email: true, send_sms: false }`
   - `'sms'` → `{ send_email: false, send_sms: true }`
   - `'both'` → `{ send_email: true, send_sms: true }`
   - Reverse mapping on load

**File**: `frontend/src/pages/notifications/NotificationPreferences.tsx`
**Change**:
1. Update `PreferencesResponse` type to `{ categories: [{ category, preferences: [{ notification_type, is_enabled, channel }] }] }`
2. Remove the `CATEGORIES` constant with snake_case keys — use the backend's display-name category strings directly from the response
3. Update `fetchPrefs` to consume grouped response and flatten for state, or restructure state to match grouped shape
4. Update `updatePref` to send `{ notification_type, is_enabled, channel }` instead of `{ type, enabled, channels: { email, sms } }`

**File**: `frontend/src/pages/notifications/TemplateEditor.tsx`
**Change**:
1. Update `NotificationTemplate` interface: add `template_type` field, remove reliance on `name`
2. Change `handleSave` to use `template_type` in PUT path: `PUT /notifications/templates/${selected.template_type}` for email, `PUT /notifications/sms-templates/${selected.template_type}` for SMS
3. In `fetchTemplates`, also fetch `GET /notifications/sms-templates` and merge into unified list
4. Display `template_type` (formatted) instead of `name` in the template list

**File**: `frontend/src/pages/notifications/WofRegoReminders.tsx`
**Change**:
1. Update `WofRegoSettings` interface to match backend: `{ enabled, days_in_advance, channel }` (single combined setting)
2. Remove separate `wof_enabled`/`wof_days_in_advance`/`rego_enabled`/`rego_days_in_advance` fields
3. Simplify UI to single enabled toggle, single days_in_advance input, single channel selector — matching the backend's combined setting

**File**: `frontend/src/pages/notifications/NotificationLog.tsx`
**Change**:
1. Update `LogEntry` interface: rename `template_name` to `template_type`
2. Update table cell to render `entry.template_type` instead of `entry.template_name`
3. Remove the search input (backend doesn't support `search` parameter) or add a note that search filters client-side only

**File**: `frontend/src/pages/settings/Settings.tsx`
**Change**: Add a `notifications` entry to `NAV_ITEMS` and `SECTION_COMPONENTS` that links/navigates to the notifications configuration pages.

#### Backend Additions

**File**: `app/modules/notifications/router.py`
**Change**: Add two new endpoints:
- `POST /notifications/webhooks/brevo-bounce` — verify Brevo webhook signature, extract bounced email, call `flag_bounced_email_on_customer()`
- `POST /notifications/webhooks/sendgrid-bounce` — verify SendGrid webhook signature, extract bounced email, call `flag_bounced_email_on_customer()`

**File**: `app/modules/notifications/service.py`
**Change**: Add locale-aware template rendering:
- Before rendering a template, check the organisation's configured locale
- Look for a locale-specific template variant (e.g., `invoice_issued_fr`)
- Fall back to the default English template if no translation exists

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bugs on unfixed code, then verify the fixes work correctly and preserve existing behavior. Given the breadth of 21 defects across security, architecture, and frontend contracts, testing is organized by category.

### Exploratory Fault Condition Checking

**Goal**: Surface counterexamples that demonstrate the bugs BEFORE implementing the fixes. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that exercise each defective code path and assert the expected (currently broken) behavior. Run these tests on the UNFIXED code to observe failures.

**Test Cases**:
1. **RLS SQL Injection Test**: Call `_set_rls_org_id` with a valid UUID and verify the SQL uses string interpolation (will confirm vulnerability on unfixed code)
2. **Hardcoded Secrets Test**: Instantiate `Settings` with default values in production mode and verify no error is raised (will confirm vulnerability on unfixed code)
3. **localStorage Token Test**: Verify `client.ts` calls `localStorage.setItem('refresh_token', ...)` on login (will confirm vulnerability on unfixed code)
4. **SSL Verification Test**: Instantiate `DatabaseSSLConfig` and verify `check_hostname` is False (will confirm vulnerability on unfixed code)
5. **SMTP Fields Test**: Render Integrations SMTP panel and verify only 4 fields are shown (will confirm mismatch on unfixed code)
6. **OverdueRules API Test**: Verify OverdueRules sends bulk PUT instead of individual CRUD (will confirm mismatch on unfixed code)
7. **NotificationPreferences Response Test**: Verify page expects flat `{ preferences }` instead of grouped `{ categories }` (will confirm mismatch on unfixed code)
8. **TemplateEditor PUT Path Test**: Verify save uses UUID in path instead of template_type (will confirm mismatch on unfixed code)
9. **NotificationLog Field Test**: Verify page reads `template_name` instead of `template_type` (will confirm mismatch on unfixed code)

**Expected Counterexamples**:
- Security tests will show vulnerable patterns are present in the code
- Frontend tests will show mismatched field names and API shapes
- Possible causes confirmed: development shortcuts, frontend built against assumed API shapes

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed functions produce the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := fixedSystem(input)
  ASSERT expectedBehavior(result)
END FOR
```

Specifically:
- For security fixes: verify parameterized queries, startup validation, httpOnly cookies, SSL verification
- For architecture fixes: verify deduplicated routers, specific exception handling, fail-closed rate limiting
- For contract fixes: verify frontend sends correct field names and consumes correct response shapes

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed system produces the same result as the original system.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT originalSystem(input) = fixedSystem(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for non-affected operations, then write property-based tests capturing that behavior.

**Test Cases**:
1. **API Route Preservation**: Verify all existing API routes continue responding with the same status codes and response shapes after router deduplication
2. **RLS Scoping Preservation**: Verify valid UUID org_ids continue to correctly scope database queries after switching to parameterized queries
3. **Auth Flow Preservation**: Verify login/logout/token-refresh cycle continues working after moving refresh tokens to httpOnly cookies
4. **Notification CRUD Preservation**: Verify backend notification endpoints continue accepting the same request shapes and returning the same responses
5. **Non-Notification Page Preservation**: Verify invoicing, inventory, POS, and other frontend pages continue functioning identically

### Unit Tests

- Test `_set_rls_org_id` uses parameterized query with valid UUIDs
- Test `_set_rls_org_id` resets context for invalid/None org_ids
- Test `Settings` validator rejects default secrets in production/staging
- Test `Settings` validator allows default secrets in development
- Test `DatabaseSSLConfig.to_connect_args` returns context with `check_hostname=True` and `CERT_REQUIRED`
- Test rate limiter returns 503 when Redis is unavailable
- Test SMTP panel renders all 10 fields with provider-conditional display
- Test OverdueRules maps `send_email`/`send_sms` to/from `channel` correctly
- Test NotificationPreferences consumes grouped `{ categories }` response
- Test TemplateEditor uses `template_type` in PUT path
- Test TemplateEditor fetches and merges both email and SMS templates
- Test WofRegoReminders consumes combined `{ enabled, days_in_advance, channel }` setting
- Test NotificationLog displays `template_type` field
- Test Settings page includes Notifications navigation link
- Test bounce webhook endpoints verify signatures and call `flag_bounced_email_on_customer()`
- Test i18n template rendering selects locale-specific templates with English fallback

### Property-Based Tests

- Generate random valid UUIDs and verify `_set_rls_org_id` always uses parameterized queries (never string interpolation)
- Generate random `Settings` configurations and verify startup validation correctly accepts/rejects based on environment and secret values
- Generate random overdue rule configurations and verify bidirectional mapping between `channel` and `send_email`/`send_sms` is lossless
- Generate random notification preference updates and verify the frontend request shape always matches `NotificationPreferenceUpdateRequest` schema
- Generate random template types and verify PUT path always uses `template_type` string (not UUID)
- Generate random API requests to existing endpoints and verify response shapes are unchanged after router deduplication

### Integration Tests

- End-to-end test: configure SMTP via Integrations page with all 10 fields, verify backend receives correct `SmtpConfigRequest`
- End-to-end test: create, update, and delete overdue rules via OverdueRules page using individual CRUD endpoints
- End-to-end test: toggle notification preferences via NotificationPreferences page with grouped category response
- End-to-end test: edit and save email and SMS templates via TemplateEditor with correct PUT paths
- End-to-end test: verify bounce webhook receives Brevo/SendGrid payloads and flags customer emails
- End-to-end test: verify notification log displays `template_type` correctly with pagination and filters
- End-to-end test: verify Settings page Notifications link navigates to notification configuration
