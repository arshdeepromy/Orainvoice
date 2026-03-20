# Implementation Plan: Security Remediation

## Overview

Implement 20 security remediations (REM-01 through REM-22, excluding REM-05/REM-09) organised by sprint priority. Each remediation includes backend implementation, frontend changes where applicable, property-based tests, and E2E test scripts. The database runs in local Docker containers — no SSL DB connections. Python (FastAPI) backend, TypeScript (React) frontend.

## Tasks

### Sprint S0 — Critical

- [x] 1. Firebase MFA server-side verification (REM-01) and CSP Firebase domains (REM-19)
  - [x] 1.1 Add Firebase project ID config and wire Firebase token verification into MFA challenge endpoint
    - Add `firebase_project_id: str = ""` to `app/config.py` Settings class
    - In `app/modules/auth/router.py` `mfa_firebase_verify()`: require `firebase_id_token` in request body, call `verify_firebase_id_token()` from `app/core/firebase_token.py`, compare `phone_number` claim against challenge session phone, return 401 on invalid token, 400 on phone mismatch
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 1.2 Wire Firebase token verification into MFA enrolment verify endpoint
    - In `app/modules/auth/router.py` `mfa_enrol_firebase_verify()`: same Firebase ID token verification pattern, compare phone against pending `UserMfaMethod.phone_number`
    - _Requirements: 1.6_

  - [x] 1.3 Update frontend MFA components to send Firebase ID token
    - In `frontend/src/pages/auth/MfaVerify.tsx`: after `confirm(code)`, call `user.getIdToken()` and include `firebase_id_token` in the API request body
    - In `frontend/src/components/mfa/SmsEnrolWizard.tsx`: same pattern for enrolment verification
    - _Requirements: 1.7_

  - [x] 1.4 Add Firebase domains to CSP connect-src directive (REM-19)
    - In `app/core/security.py`: add `https://identitytoolkit.googleapis.com`, `https://www.googleapis.com`, `https://firebaseinstallations.googleapis.com` to `connect-src`
    - _Requirements: 3.1, 3.2_

  - [ ]* 1.5 Write property test for Firebase token verification (Property 1)
    - **Property 1: Firebase token verification gates MFA completion**
    - Test that valid tokens with matching phone pass, invalid tokens return 401, mismatched phones return 400
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**

- [x] 2. Rate limiter fail-closed for auth endpoints (REM-02, REM-08)
  - [x] 2.1 Implement bifurcated fail-closed/fail-open strategy in rate limiter
    - In `app/middleware/rate_limit.py` `__call__()`: when Redis is unavailable, return HTTP 503 for auth endpoints (`/auth/`, `/login`, `/mfa/`, `/password-reset/`), allow through for non-auth endpoints
    - Apply same bifurcation in the `except Exception` handler
    - Log errors for auth blocks, warnings for non-auth pass-through
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ]* 2.2 Write property tests for rate limiter fail-closed (Properties 2, 3)
    - **Property 2: Rate limiter fail-closed bifurcation** — for any path and Redis state, auth endpoints get 503 when Redis down, non-auth pass through
    - **Validates: Requirements 2.1, 2.2**
    - **Property 3: Auth endpoint classification** — `is_auth_endpoint()` returns True iff path starts with auth prefixes
    - **Validates: Requirements 2.5**

- [x] 3. Connexus webhook HMAC signature verification (REM-03, REM-14)
  - [x] 3.1 Add webhook secret config and wire HMAC verification into webhook handlers
    - Add `connexus_webhook_secret: str = ""` to `app/config.py` Settings
    - In `app/modules/sms_chat/router_webhooks.py`: read raw body first, verify HMAC via `verify_webhook_signature()` from `app/core/webhook_security.py` when secret is configured, return 401 on failure, skip verification when no secret (dev mode)
    - Apply to both `incoming_sms` and `delivery_status` handlers
    - _Requirements: 4.1, 4.2, 4.3, 4.5_

  - [x] 3.2 Add Connexus webhook paths to CSRF exemption list
    - In `app/middleware/security_headers.py`: add `/api/webhooks/connexus/incoming` and `/api/webhooks/connexus/status` to `_CSRF_EXEMPT_PATHS`
    - _Requirements: 4.4_

  - [ ]* 3.3 Write property test for webhook HMAC round-trip (Property 4)
    - **Property 4: Webhook HMAC round-trip** — signing then verifying with same secret returns True, different secret returns False
    - **Validates: Requirements 4.1**

- [x] 4. S0 Checkpoint
  - Ensure all tests pass, ask the user if questions arise.


### Sprint S1 — High Severity

- [x] 5. Integration backup export hardening (REM-04)
  - [x] 5.1 Add password re-confirmation and secret redaction to backup export
    - In `app/modules/admin/router.py` backup endpoint: require `x-confirm-password` header, verify against user's password hash, return 401 if missing, 400 if wrong
    - In `app/modules/admin/service.py`: implement `_redact_config()` to mask sensitive fields (`api_key`, `auth_token`, `password`, `secret`, `token`, `credentials`) with `***REDACTED***`
    - Add `write_audit_log()` call with action `admin.integration_backup_exported`, user ID, and source IP
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 5.2 Write property test for secret redaction (Property 5)
    - **Property 5: Integration backup secret redaction** — for any dict with sensitive keys, redaction replaces sensitive values while preserving non-sensitive pairs
    - **Validates: Requirements 5.3**

- [x] 6. Data export audit logging (REM-06)
  - [x] 6.1 Add audit log entries to all data export endpoints
    - In `app/modules/data_io/router.py`: add `write_audit_log()` calls to `export_customers`, `export_vehicles`, and `export_invoices` with actions `data_io.customers_exported`, `data_io.vehicles_exported`, `data_io.invoices_exported` respectively
    - Include org_id, user_id, source IP, and export format in each audit entry
    - Ensure audit log is written before the response is returned
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [ ]* 6.2 Write property test for data export audit logging (Property 6)
    - **Property 6: Data export audit logging** — for any export operation, an audit log entry is created with correct action name, user ID, org ID, and IP
    - **Validates: Requirements 6.1, 6.2, 6.3**

- [x] 7. Account lockout email notification (REM-07)
  - [x] 7.1 Implement lockout email sending in auth service
    - In `app/modules/auth/service.py`: implement `_send_permanent_lockout_email()` using the existing SMTP/email infrastructure
    - Email must include platform name ("WorkshopPro NZ"), lockout reason, and support contact URL
    - Wrap in try/except so email failure does not block the lockout process
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 7.2 Write property test for lockout email content (Property 7)
    - **Property 7: Lockout email content** — for any email address, lockout email includes platform name, reason, and support URL; send failure does not prevent lockout
    - **Validates: Requirements 7.1, 7.2**

- [x] 8. Replace python-jose with PyJWT (REM-12)
  - [x] 8.1 Swap dependency and migrate JWT module
    - Update `pyproject.toml` (or `requirements.txt`): replace `python-jose[cryptography]` with `PyJWT[crypto]>=2.8.0`
    - In `app/modules/auth/jwt.py`: change `from jose import jwt, JWTError` to `import jwt` and `from jwt.exceptions import InvalidTokenError`
    - In `app/middleware/auth.py`: update JWT imports to use PyJWT API
    - In `app/core/firebase_token.py`: update JWT imports to use PyJWT API
    - Ensure `encode()` and `decode()` calls use PyJWT signatures (compatible API)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ]* 8.2 Write property tests for JWT encode/decode round-trip (Properties 8, 9)
    - **Property 8: JWT encode/decode round-trip (PyJWT)** — for any valid payload with user_id, org_id, role, email, encode then decode returns identical values
    - **Validates: Requirements 8.5**
    - **Property 9: Invalid JWT rejection** — malformed or expired tokens raise InvalidTokenError
    - **Validates: Requirements 8.6**

- [x] 9. SSRF protection on integration endpoint URLs (REM-13)
  - [x] 9.1 Create URL validation utility and wire into admin service
    - Create `app/core/url_validation.py` with `validate_url_for_ssrf()` function
    - Block private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), link-local (169.254.0.0/16), loopback (127.0.0.0/8), IPv6 private ranges
    - Reject non-http/https schemes, empty hostnames, unresolvable hostnames
    - In `app/modules/admin/service.py`: call `validate_url_for_ssrf()` in `save_smtp_config`, `save_twilio_config`, `save_stripe_config`, `save_carjam_config` before persisting URLs
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 9.2 Write property test for SSRF URL validation (Property 10)
    - **Property 10: SSRF URL validation** — for any URL, reject private IPs, non-http schemes, empty hostnames, unresolvable hosts; accept valid public URLs
    - **Validates: Requirements 9.2, 9.3, 9.4**

- [x] 10. S1 Checkpoint
  - Ensure all tests pass, ask the user if questions arise.


### Sprint S2 — Medium Severity

- [x] 11. Session-scoped org context for global admins (REM-10)
  - [x] 11.1 Add org context set endpoint and auth middleware enforcement
    - In `app/modules/admin/router.py`: add `POST /admin/org-context/{org_id}` endpoint for global admins to set active org context, validate org exists, store `org_id` in Redis keyed by session/user_id
    - In `app/middleware/auth.py`: for global_admin users on tenant-scoped endpoints, check Redis for active org context, return 403 if none set
    - Add `write_audit_log()` with action `admin.org_context_switched`
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [ ]* 11.2 Write property tests for org context enforcement (Properties 11, 12)
    - **Property 11: Global admin org context enforcement** — tenant-scoped access returns 403 without org context, succeeds with valid org context
    - **Validates: Requirements 12.1**
    - **Property 12: Org context round-trip** — setting org context then retrieving it returns the same org ID
    - **Validates: Requirements 12.3**

- [x] 12. Encryption key rotation mechanism (REM-11)
  - [x] 12.1 Create CLI management command for key rotation
    - Create `app/cli/rotate_keys.py` with CLI command accepting `--old-key` and `--new-key` parameters
    - Query all `IntegrationConfig` rows with `config_encrypted` and `credentials_encrypted` columns
    - Use `rotate_master_key()` from `app/core/encryption.py` to re-encrypt each value
    - Execute all operations within a single database transaction, rollback on any failure
    - Report number of records re-encrypted on success
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [ ]* 12.2 Write property test for encryption key rotation (Property 13)
    - **Property 13: Encryption key rotation round-trip** — encrypt with key A, rotate to key B, decrypt with key B yields original plaintext
    - **Validates: Requirements 13.2**

- [x] 13. Portal token TTL and rotation (REM-15)
  - [x] 13.1 Add portal token expiry column and auth middleware check
    - Create Alembic migration adding `portal_token_expires_at: DateTime` to customers table with default `now() + interval '90 days'`
    - Add `portal_token_ttl_days: int = 90` to `app/config.py` Settings
    - In `app/middleware/auth.py`: when authenticating portal tokens, check `portal_token_expires_at`, return 401 if expired
    - In `app/modules/admin/router.py`: add `POST /admin/customers/{id}/regenerate-portal-token` endpoint to generate new token and reset expiry
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [ ]* 13.2 Write property test for expired portal token rejection (Property 14)
    - **Property 14: Expired portal token rejection** — any portal token with expiry in the past is rejected with 401
    - **Validates: Requirements 14.3**

- [x] 14. Session limit race condition fix (REM-16)
  - [x] 14.1 Add Redis distributed lock to session creation
    - In `app/modules/auth/service.py` `enforce_session_limit()`: acquire Redis lock keyed on `session_lock:{user_id}` with 5s timeout before checking session count
    - Reject login with appropriate error if lock cannot be acquired within 5 seconds
    - Release lock in `finally` block after session creation or rejection
    - _Requirements: 15.1, 15.2, 15.3_

  - [ ]* 14.2 Write property test for session lock lifecycle (Property 15)
    - **Property 15: Session lock lifecycle** — lock is acquired before session count check and released after operation completes; concurrent attempts are serialised
    - **Validates: Requirements 15.1, 15.3**

- [x] 15. Demo reset endpoint environment guard (REM-17)
  - [x] 15.1 Restrict demo reset to development environment allowlist
    - In `app/modules/admin/router.py` `reset_demo_account()`: change environment check to use explicit allowlist `{"development"}`, return 403 for any other environment
    - _Requirements: 10.1, 10.2_

  - [ ]* 15.2 Write property test for demo reset environment restriction (Property 16)
    - **Property 16: Demo reset environment restriction** — any environment string not "development" returns 403
    - **Validates: Requirements 14.1**

- [x] 16. Password reset timing side-channel mitigation (REM-18)
  - [x] 16.1 Add random delay for non-existent email password resets
    - In `app/modules/auth/service.py` `request_password_reset()`: add `asyncio.sleep(random.uniform(0.5, 1.5))` for non-existent emails
    - Return identical HTTP status and response body for both existent and non-existent emails
    - _Requirements: 16.1, 16.2_

  - [ ]* 16.2 Write property test for password reset response indistinguishability (Property 17)
    - **Property 17: Password reset response indistinguishability** — same status code and body for any email; non-existent emails include 0.5–1.5s delay
    - **Validates: Requirements 16.1, 16.2**

- [x] 17. S2 Checkpoint
  - Ensure all tests pass, ask the user if questions arise.


### Sprint S3 — Low/Backlog

- [x] 18. Disable Swagger UI in production (REM-20)
  - [x] 18.1 Gate docs/redoc/openapi on environment setting
    - In `app/main.py`: set `docs_url`, `redoc_url`, `openapi_url` to `None` when `settings.environment != "development"`, serve at `/docs`, `/redoc`, `/openapi.json` when in development
    - _Requirements: 11.1, 11.2_

  - [ ]* 18.2 Write unit test for Swagger disable by environment
    - Test that docs endpoints return 404 in non-development environments and 200 in development
    - _Requirements: 11.1, 11.2_

- [x] 19. Dynamic SQL column name whitelist (REM-21)
  - [x] 19.1 Implement column name validation in admin service
    - In `app/modules/admin/service.py`: define `_ALLOWED_SORT_COLUMNS` dict mapping table names to allowed column sets
    - Create `validate_column_name(table, column)` function that raises `ValueError` for invalid columns and logs a warning
    - Wire validation into all dynamic column name usage points
    - _Requirements: 17.1, 17.2_

  - [ ]* 19.2 Write property test for column name whitelist (Property 18)
    - **Property 18: Dynamic column name whitelist** — allowed columns pass through unchanged, non-allowed columns raise ValueError
    - **Validates: Requirements 17.1**

- [x] 20. JWT HS256 to RS256 migration (REM-22)
  - [x] 20.1 Add RS256 key configuration and dual-algorithm JWT support
    - Add `jwt_rs256_private_key_path: str = ""` and `jwt_rs256_public_key_path: str = ""` to `app/config.py` Settings
    - In `app/modules/auth/jwt.py`: implement `_get_signing_key_and_algorithm()` that uses RS256 when keys configured, HS256 otherwise
    - Implement `_get_verification_keys()` returning list of (key, algorithms) tuples — always include HS256, add RS256 when public key configured
    - Update `decode_access_token()` to try RS256 first, fall back to HS256 during migration period
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5_

  - [ ]* 20.2 Write property tests for RS256 JWT (Properties 19, 20, 21)
    - **Property 19: RS256 JWT round-trip** — sign with private key, verify with public key returns original claims
    - **Validates: Requirements 18.1**
    - **Property 20: JWT algorithm selection by configuration** — RS256 keys configured → RS256 header; no keys → HS256 header
    - **Validates: Requirements 18.3, 18.4**
    - **Property 21: Dual-algorithm JWT acceptance during migration** — both HS256 and RS256 tokens decode successfully when both configured
    - **Validates: Requirements 18.5**

- [x] 21. S3 Checkpoint
  - Ensure all tests pass, ask the user if questions arise.


### E2E Test Suites

- [x] 22. Backend E2E test suite
  - [x] 22.1 Create E2E test for authentication flows
    - Create `tests/e2e/test_e2e_auth.py` using `httpx.AsyncClient` with FastAPI test client
    - Cover login, MFA challenge with Firebase token, MFA enrolment, password reset, session management
    - _Requirements: 19.1_

  - [x] 22.2 Create E2E test for data export and audit logging
    - Create `tests/e2e/test_e2e_data_export.py`
    - Test customers, vehicles, invoices export endpoints and verify audit log entries are created with correct actions
    - _Requirements: 19.2_

  - [x] 22.3 Create E2E test for admin operations
    - Create `tests/e2e/test_e2e_admin.py`
    - Test integration backup with password re-confirmation, demo reset environment guard, integration URL SSRF validation
    - _Requirements: 19.3_

  - [x] 22.4 Create E2E test for webhook endpoints
    - Create `tests/e2e/test_e2e_webhooks.py`
    - Test Connexus incoming SMS and status update webhooks with valid and invalid HMAC signatures
    - _Requirements: 19.4_

  - [x] 22.5 Create E2E test for rate limiter behaviour
    - Create `tests/e2e/test_e2e_rate_limiter.py`
    - Test auth endpoint blocking when Redis unavailable, non-auth endpoint pass-through when Redis unavailable
    - _Requirements: 19.5_

  - [x] 22.6 Create E2E test for Swagger UI disable
    - Create `tests/e2e/test_e2e_swagger.py`
    - Verify `/docs`, `/redoc`, `/openapi.json` return 404 in non-development environments
    - _Requirements: 19.6_

  - [x] 22.7 Create E2E test for portal token TTL
    - Create `tests/e2e/test_e2e_portal_token.py`
    - Test valid portal token access, expired portal token rejection (401), token regeneration
    - _Requirements: 19.1_

  - [x] 22.8 Create E2E test for session lock
    - Create `tests/e2e/test_e2e_session_lock.py`
    - Test concurrent session creation is serialised, lock timeout returns appropriate error
    - _Requirements: 19.1_

- [x] 23. Frontend E2E test suite (Playwright)
  - [x] 23.1 Create Playwright test for auth flows
    - Create `tests/e2e/frontend/auth.spec.ts`
    - Simulate login, MFA challenge, MFA enrolment including Firebase ID token submission
    - _Requirements: 20.1_

  - [x] 23.2 Create Playwright test for data export flows
    - Create `tests/e2e/frontend/data-export.spec.ts`
    - Simulate clicking export buttons, verify file downloads
    - _Requirements: 20.2_

  - [x] 23.3 Create Playwright test for admin operations
    - Create `tests/e2e/frontend/admin.spec.ts`
    - Simulate integration management, backup export with password confirmation modal
    - _Requirements: 20.3_

  - [x] 23.4 Create Playwright test for portal token access
    - Create `tests/e2e/frontend/portal.spec.ts`
    - Simulate customer portal access with valid and expired portal tokens
    - _Requirements: 20.4_

  - [x] 23.5 Create Playwright test for CSP header verification
    - Create `tests/e2e/frontend/csp.spec.ts`
    - Verify no CSP violations during Firebase MFA flows
    - _Requirements: 20.5_

- [x] 24. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints after each sprint ensure incremental validation
- Property tests validate universal correctness properties from the design document (21 properties total)
- The database is in local Docker containers — no SSL DB connections needed
- REM-05 (X-Forwarded-For) and REM-09 (CORS localhost) are excluded — mitigated by reverse proxy
- Sprint organisation follows the Security Remediation Plan: S0 Critical → S1 High → S2 Medium → S3 Low/Backlog
