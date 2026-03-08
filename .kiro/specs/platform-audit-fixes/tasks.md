# Implementation Plan

- [x] 1. Write bug condition exploration tests
  - **Property 1: Fault Condition** — Platform Audit Defects (Security, Architecture, Contract Mismatches)
  - **CRITICAL**: These tests MUST FAIL on unfixed code — failure confirms the bugs exist
  - **DO NOT attempt to fix the tests or the code when they fail**
  - **NOTE**: These tests encode the expected behavior — they will validate the fixes when they pass after implementation
  - **GOAL**: Surface counterexamples that demonstrate all 21 defects exist
  - **Scoped PBT Approach**: For deterministic bugs, scope properties to concrete failing cases
  - Security exploration tests:
    - Test `_set_rls_org_id` in `app/core/database.py` uses string interpolation (f-string) instead of parameterized query — generate random valid UUIDs and assert the SQL uses `set_config()` with bind params (will FAIL on unfixed code)
    - Test `Settings` in `app/config.py` allows startup with default `"change-me-in-production"` secrets in production mode — assert startup raises `ValueError` (will FAIL on unfixed code)
    - Test `frontend/src/api/client.ts` stores refresh token in localStorage — assert refresh token is NOT in localStorage (will FAIL on unfixed code)
    - Test `DatabaseSSLConfig` in `app/core/security.py` has `check_hostname=False` and `verify_mode=CERT_NONE` — assert `check_hostname=True` and `verify_mode=CERT_REQUIRED` (will FAIL on unfixed code)
  - Architecture exploration tests:
    - Test `app/main.py` has duplicate router registrations — assert no duplicate `include_router` calls for the same router (will FAIL on unfixed code)
    - Test service-layer files use `except Exception:` — assert specific exception types are caught (will FAIL on unfixed code)
    - Test rate limiter allows requests when Redis is unavailable — assert requests are denied or throttled (will FAIL on unfixed code)
  - Frontend contract exploration tests:
    - Test Integrations SMTP panel renders only 4 fields — assert all 10 `SmtpConfigRequest` fields are present (will FAIL on unfixed code)
    - Test OverdueRules sends bulk PUT — assert individual CRUD endpoints are used (will FAIL on unfixed code)
    - Test OverdueRules uses `channel` field — assert `send_email`/`send_sms` booleans are mapped (will FAIL on unfixed code)
    - Test NotificationPreferences expects flat response — assert grouped `{ categories }` response is consumed (will FAIL on unfixed code)
    - Test TemplateEditor PUT uses UUID — assert `template_type` string is used in PUT path (will FAIL on unfixed code)
    - Test TemplateEditor only fetches email templates — assert both email and SMS templates are fetched (will FAIL on unfixed code)
    - Test TemplateEditor uses `name` field — assert `template_type` field is used (will FAIL on unfixed code)
    - Test WofRegoReminders expects separate fields — assert combined `{ enabled, days_in_advance, channel }` is consumed (will FAIL on unfixed code)
    - Test NotificationLog reads `template_name` — assert `template_type` is read (will FAIL on unfixed code)
    - Test Settings page has no Notifications link — assert Notifications navigation entry exists (will FAIL on unfixed code)
  - Run all tests on UNFIXED code
  - **EXPECTED OUTCOME**: All tests FAIL (this is correct — it proves the bugs exist)
  - Document counterexamples found to understand root causes
  - Mark task complete when tests are written, run, and failures are documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18, 1.19, 1.20, 1.21_

- [x] 2. Write preservation property tests (BEFORE implementing fixes)
  - **Property 2: Preservation** — Existing Functionality Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - **GOAL**: Capture baseline behavior of all non-buggy code paths so regressions are detected after fixes
  - Observe and record behavior on UNFIXED code for non-buggy inputs:
    - Observe: `_set_rls_org_id` with valid UUIDs correctly scopes queries on unfixed code
    - Observe: JWT authentication/authorization flow works correctly on unfixed code
    - Observe: All existing API routes respond with expected status codes and response shapes on unfixed code
    - Observe: Backend notification CRUD endpoints accept correct request shapes and return correct responses on unfixed code
    - Observe: Rate limiter enforces limits correctly when Redis IS available on unfixed code
    - Observe: Service-layer functions that complete successfully return correct response shapes on unfixed code
    - Observe: Non-notification frontend pages (invoicing, inventory, POS, jobs, etc.) function correctly on unfixed code
  - Write property-based tests capturing observed behavior:
    - Property: For all valid UUIDs, `_set_rls_org_id` correctly scopes database queries to the specified org (from Preservation Req 3.1)
    - Property: For all valid JWT tokens, authentication and authorization continues to work correctly (from Preservation Req 3.2, 3.3)
    - Property: For all existing API routes, response status codes and shapes are unchanged after router deduplication (from Preservation Req 3.5)
    - Property: For all valid notification CRUD requests, backend endpoints return the same responses (from Preservation Req 3.10, 3.11, 3.12)
    - Property: For all rate-limited requests when Redis IS available, rate limits are enforced with same thresholds (from Preservation Req 3.7)
    - Property: For all SMTP config saves with valid fields, backend stores encrypted config and returns success (from Preservation Req 3.8, 3.9)
    - Property: For all notification log queries with valid filters, backend returns paginated entries with correct fields (from Preservation Req 3.12)
    - Property: For all integration config storage operations, envelope encryption is maintained (from Preservation Req 3.13)
  - Verify all tests PASS on UNFIXED code
  - **EXPECTED OUTCOME**: All tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14_

- [x] 3. Security fixes

  - [x] 3.1 Fix SQL injection in RLS context setter
    - In `app/core/database.py`, function `_set_rls_org_id`
    - Replace f-string interpolation `f"SET LOCAL app.current_org_id = '{validated}'"` with parameterized `set_config()` call
    - Use: `await session.execute(text("SELECT set_config('app.current_org_id', :org_id, true)"), {"org_id": validated})`
    - `set_config(name, value, is_local=true)` is equivalent to `SET LOCAL` but supports parameterized queries
    - _Bug_Condition: isBugCondition({ category: "security", defect_id: "rls_interpolation" })_
    - _Expected_Behavior: System uses parameterized queries for RLS context, eliminating SQL injection vector_
    - _Preservation: Valid UUID org_ids continue to correctly scope database queries (Req 3.1)_
    - _Requirements: 2.1_

  - [x] 3.2 Add startup validation for secrets
    - In `app/config.py`, add a `model_validator` or startup check on the `Settings` class
    - Raise `ValueError` if `jwt_secret` or `encryption_master_key` equals `"change-me-in-production"` when `environment` is `"production"` or `"staging"`
    - Allow default values in `"development"` and `"test"` environments for convenience
    - _Bug_Condition: isBugCondition({ category: "security", defect_id: "hardcoded_secrets" })_
    - _Expected_Behavior: Application refuses to start with default placeholder secrets in production/staging_
    - _Preservation: JWT authentication continues working with properly configured secrets (Req 3.2)_
    - _Requirements: 2.2_

  - [x] 3.3 Move refresh tokens from localStorage to httpOnly cookies
    - In `frontend/src/api/client.ts`:
      - Remove `localStorage.getItem('refresh_token')`, `localStorage.setItem`, `localStorage.removeItem` calls for refresh tokens
      - Remove `storedRefreshToken` variable and `getRefreshToken()`/`setRefreshToken()` exports
      - In `refreshAccessToken()`, send POST without body — refresh token comes from httpOnly cookie (`withCredentials: true` already set)
    - In backend auth endpoint (e.g., `app/modules/auth/router.py`):
      - Set refresh token as httpOnly, Secure, SameSite=Strict cookie in login/refresh responses
      - Read refresh token from cookie instead of request body on refresh
      - Clear cookie on logout
    - _Bug_Condition: isBugCondition({ category: "security", defect_id: "localstorage_refresh" })_
    - _Expected_Behavior: Refresh tokens stored in httpOnly cookies, inaccessible to XSS_
    - _Preservation: Login/logout/token-refresh cycle continues working (Req 3.2, 3.3)_
    - _Requirements: 2.3_

  - [x] 3.4 Enable SSL hostname checking and certificate verification
    - In `app/core/security.py`, function/class `DatabaseSSLConfig.to_connect_args`
    - Replace `check_hostname = False` with `check_hostname = True`
    - Replace `verify_mode = ssl.CERT_NONE` with `verify_mode = ssl.CERT_REQUIRED`
    - Remove the misleading "Use CERT_REQUIRED in production" comment
    - _Bug_Condition: isBugCondition({ category: "security", defect_id: "ssl_disabled" })_
    - _Expected_Behavior: SSL connections verify hostname and certificates, preventing MITM attacks_
    - _Preservation: Database SSL connections continue to establish successfully (Req 3.4)_
    - _Requirements: 2.4_

- [x] 4. Architecture and code quality fixes

  - [x] 4.1 Deduplicate router registrations in main.py
    - In `app/main.py`, function `create_app`
    - Remove the duplicate V1-under-V2 router registration block (~393 lines of repeated `include_router` calls)
    - If V2 compatibility is needed, replace with a loop over `V1_ROUTERS_FOR_V2` list
    - Verify all existing API routes still respond at the same URL paths
    - _Bug_Condition: isBugCondition({ category: "architecture", defect_id: "router_duplication" })_
    - _Expected_Behavior: Single deduplicated set of router registrations, no repeated include_router calls_
    - _Preservation: All existing API routes continue responding with same URL paths and HTTP methods (Req 3.5)_
    - _Requirements: 2.5_

  - [x] 4.2 Replace blanket exception catching with specific types
    - Audit service-layer files identified in the developer audit
    - Replace `except Exception:` with specific exception types (`ValueError`, `KeyError`, `SQLAlchemyError`, `HTTPException`, etc.)
    - Add meaningful error logging with context (e.g., `logger.error(f"Failed to create overdue rule: {e}", exc_info=True)`)
    - Only change patterns explicitly identified in the audit — do not refactor unrelated code
    - _Bug_Condition: isBugCondition({ category: "architecture", defect_id: "blanket_except" })_
    - _Expected_Behavior: Specific exception types caught with meaningful error details logged_
    - _Preservation: Service-layer functions that complete successfully return same response shapes (Req 3.6)_
    - _Requirements: 2.6_

  - [x] 4.3 Make rate limiter fail-closed when Redis is unavailable
    - In the rate limiter middleware
    - When Redis connection fails, return HTTP 503 (Service Unavailable) instead of allowing unlimited requests
    - Optionally implement a conservative in-memory fallback limit
    - When Redis IS available, rate limiting behavior remains unchanged
    - _Bug_Condition: isBugCondition({ category: "architecture", defect_id: "rate_limiter_fail_open" })_
    - _Expected_Behavior: Rate limiter denies requests when Redis is unavailable (fail-closed)_
    - _Preservation: Rate limits enforced with same thresholds when Redis IS available (Req 3.7)_
    - _Requirements: 2.7_

- [x] 5. Frontend contract fixes — Notification pages realigned to backend schemas

  - [x] 5.1 Fix SMTP configuration panel in Integrations page
    - In `frontend/src/pages/admin/Integrations.tsx`
    - Update `INTEGRATION_FIELDS.smtp` to include all 10 fields from backend `SmtpConfigRequest`
    - Add `provider` dropdown (brevo/sendgrid/smtp), `from_email`, `host`, `port`, `username`, `password`
    - Make `host`/`port`/`username`/`password` conditionally visible when `provider === 'smtp'`
    - Make `api_key` conditionally visible when `provider === 'brevo' || provider === 'sendgrid'`
    - _Bug_Condition: isBugCondition({ category: "contract_mismatch", context: { page: "Integrations/smtp" } })_
    - _Expected_Behavior: SMTP panel displays all 10 fields with provider-conditional visibility_
    - _Preservation: SMTP config save and test endpoints continue working (Req 3.8, 3.9)_
    - _Requirements: 2.8_

  - [x] 5.2 Fix OverdueRules page API shape and field mapping
    - In `frontend/src/pages/notifications/OverdueRules.tsx`
    - Change `fetchRules` to consume `{ rules, total, reminders_enabled }` response — map `reminders_enabled` to enabled state
    - Replace bulk `PUT /notifications/overdue-rules` with individual CRUD: `POST` for create, `PUT /{rule_id}` for update, `DELETE /{rule_id}` for delete
    - Replace `toggleEnabled` to use `PUT /notifications/overdue-rules-toggle?enabled=`
    - Map between UI `channel` and backend `send_email`/`send_sms` booleans bidirectionally
    - _Bug_Condition: isBugCondition({ category: "contract_mismatch", context: { page: "OverdueRules" } })_
    - _Expected_Behavior: Page uses individual CRUD endpoints and correctly maps channel ↔ send_email/send_sms_
    - _Preservation: Backend overdue rules CRUD endpoints unchanged (Req 3.10)_
    - _Requirements: 2.9, 2.10_

  - [x] 5.3 Fix NotificationPreferences page response consumption
    - In `frontend/src/pages/notifications/NotificationPreferences.tsx`
    - Update `PreferencesResponse` type to `{ categories: [{ category, preferences: [{ notification_type, is_enabled, channel }] }] }`
    - Remove `CATEGORIES` constant with snake_case keys — use backend's display-name category strings directly
    - Update `fetchPrefs` to consume grouped response
    - Update `updatePref` to send `{ notification_type, is_enabled, channel }` instead of `{ type, enabled, channels: { email, sms } }`
    - _Bug_Condition: isBugCondition({ category: "contract_mismatch", context: { page: "NotificationPreferences" } })_
    - _Expected_Behavior: Page consumes grouped { categories } response and sends correct update shape_
    - _Preservation: Backend notification preferences endpoints unchanged (Req 3.10)_
    - _Requirements: 2.11, 2.12_

  - [x] 5.4 Fix TemplateEditor PUT path, SMS fetching, and field names
    - In `frontend/src/pages/notifications/TemplateEditor.tsx`
    - Update `NotificationTemplate` interface: add `template_type` field, remove reliance on `name`
    - Change `handleSave` to use `template_type` in PUT path: `PUT /notifications/templates/${selected.template_type}` for email, `PUT /notifications/sms-templates/${selected.template_type}` for SMS
    - In `fetchTemplates`, also fetch `GET /notifications/sms-templates` and merge into unified list
    - Display `template_type` (formatted) instead of `name` in the template list
    - _Bug_Condition: isBugCondition({ category: "contract_mismatch", context: { page: "TemplateEditor" } })_
    - _Expected_Behavior: PUT uses template_type in path, both email and SMS templates fetched, template_type displayed_
    - _Preservation: Backend template endpoints unchanged (Req 3.10)_
    - _Requirements: 2.13, 2.14, 2.15_

  - [x] 5.5 Fix WofRegoReminders page to match backend combined setting
    - In `frontend/src/pages/notifications/WofRegoReminders.tsx`
    - Update `WofRegoSettings` interface to match backend: `{ enabled, days_in_advance, channel }`
    - Remove separate `wof_enabled`/`wof_days_in_advance`/`rego_enabled`/`rego_days_in_advance` fields
    - Simplify UI to single enabled toggle, single days_in_advance input, single channel selector
    - _Bug_Condition: isBugCondition({ category: "contract_mismatch", context: { page: "WofRegoReminders" } })_
    - _Expected_Behavior: Page consumes combined { enabled, days_in_advance, channel } setting_
    - _Preservation: Backend WOF/rego settings endpoint unchanged (Req 3.10)_
    - _Requirements: 2.16_

  - [x] 5.6 Fix NotificationLog field name and remove non-functional search
    - In `frontend/src/pages/notifications/NotificationLog.tsx`
    - Update `LogEntry` interface: rename `template_name` to `template_type`
    - Update table cell to render `entry.template_type` instead of `entry.template_name`
    - Remove the search input (backend doesn't support `search` parameter) or convert to client-side filter
    - _Bug_Condition: isBugCondition({ category: "contract_mismatch", context: { page: "NotificationLog" } })_
    - _Expected_Behavior: Template column displays template_type, search removed or made client-side_
    - _Preservation: Backend notification log endpoint unchanged (Req 3.12)_
    - _Requirements: 2.17, 2.18_

  - [x] 5.7 Add Notifications link to Settings page
    - In `frontend/src/pages/settings/Settings.tsx`
    - Add a `notifications` entry to `NAV_ITEMS` and `SECTION_COMPONENTS`
    - Link/navigate to the notifications configuration pages
    - _Bug_Condition: isBugCondition({ category: "contract_mismatch", context: { page: "Settings" } })_
    - _Expected_Behavior: Settings page includes Notifications navigation entry_
    - _Preservation: All other Settings tabs/links unchanged (Req 3.14)_
    - _Requirements: 2.19_

- [x] 6. Backend additions — Bounce webhooks and i18n template rendering

  - [x] 6.1 Add bounce webhook endpoints
    - In `app/modules/notifications/router.py`
    - Add `POST /notifications/webhooks/brevo-bounce` — verify Brevo webhook signature, extract bounced email, call `flag_bounced_email_on_customer()`
    - Add `POST /notifications/webhooks/sendgrid-bounce` — verify SendGrid webhook signature, extract bounced email, call `flag_bounced_email_on_customer()`
    - Add Pydantic request schemas for Brevo and SendGrid bounce payloads
    - Return 200 on success, 401 on invalid signature
    - _Bug_Condition: isBugCondition({ category: "contract_mismatch", defect_id: "missing_bounce_webhook" })_
    - _Expected_Behavior: Webhook endpoints receive bounce events, verify signatures, flag customer emails_
    - _Preservation: Existing notification dispatch and logging unchanged (Req 3.11, 3.12)_
    - _Requirements: 2.20_

  - [x] 6.2 Add locale-aware template rendering
    - In `app/modules/notifications/service.py`
    - Before rendering a template, check the organisation's configured locale
    - Look for a locale-specific template variant (e.g., `invoice_issued_fr`)
    - Fall back to the default English template if no translation exists
    - _Bug_Condition: isBugCondition({ category: "contract_mismatch", defect_id: "missing_i18n_render" })_
    - _Expected_Behavior: Templates rendered in org's configured locale with English fallback_
    - _Preservation: English template rendering unchanged for orgs without locale config (Req 3.11)_
    - _Requirements: 2.21_

- [x] 7. Verify bug condition exploration tests now pass

  - [x] 7.1 Re-run security exploration tests
    - **Property 1: Expected Behavior** — Security Vulnerabilities Fixed
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - The tests from task 1 encode the expected behavior for security fixes
    - Verify: RLS uses parameterized queries, secrets validated at startup, refresh tokens in httpOnly cookies, SSL verification enabled
    - **EXPECTED OUTCOME**: All security tests PASS (confirms security bugs are fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 7.2 Re-run architecture exploration tests
    - **Property 1: Expected Behavior** — Architecture Issues Resolved
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Verify: Routers deduplicated, specific exceptions caught, rate limiter fails closed
    - **EXPECTED OUTCOME**: All architecture tests PASS (confirms architecture bugs are fixed)
    - _Requirements: 2.5, 2.6, 2.7_

  - [x] 7.3 Re-run frontend contract exploration tests
    - **Property 1: Expected Behavior** — Frontend-Backend Contracts Aligned
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Verify: All 7 notification pages send correct field names and consume correct response shapes
    - **EXPECTED OUTCOME**: All contract tests PASS (confirms contract mismatches are fixed)
    - _Requirements: 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15, 2.16, 2.17, 2.18, 2.19_

  - [x] 7.4 Re-run backend addition tests
    - **Property 1: Expected Behavior** — Missing Backend Features Added
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Verify: Bounce webhooks receive events and flag emails, i18n templates render in correct locale
    - **EXPECTED OUTCOME**: All backend addition tests PASS (confirms missing features are implemented)
    - _Requirements: 2.20, 2.21_

- [x] 8. Verify preservation tests still pass

  - [x] 8.1 Re-run all preservation property tests
    - **Property 2: Preservation** — Existing Functionality Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Verify: RLS scoping, JWT auth, API routes, notification CRUD, rate limiting, SMTP config, notification log, encryption — all unchanged
    - **EXPECTED OUTCOME**: All preservation tests PASS (confirms no regressions)
    - Confirm all tests still pass after all fixes (no regressions introduced)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14_

- [x] 9. Checkpoint — Ensure all tests pass
  - Run the full test suite (exploration tests, preservation tests, unit tests, integration tests)
  - Verify all exploration tests from task 1 now PASS (bugs are fixed)
  - Verify all preservation tests from task 2 still PASS (no regressions)
  - Ensure no new lint, type, or build errors introduced
  - Ask the user if questions arise
