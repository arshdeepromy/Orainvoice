# Requirements Document — Security Remediation

## Introduction

This specification covers the remediation of 20 security vulnerabilities identified by the OWASP Top 10 Audit (18 findings) and Grey-Box Penetration Test (14 findings) for the WorkshopPro NZ (OraInvoice) platform. Two items — REM-05 (Nginx X-Forwarded-For spoofing) and REM-09 (CORS localhost origins) — are excluded because the domain-restricting reverse proxy already mitigates them at the network level.

The remediation is organised into four sprints by severity: S0 (Critical), S1 (High), S2 (Medium), S3 (Low/Backlog). After each sprint, automated end-to-end tests (Playwright for frontend, pytest for backend) validate that all application features remain functional and that each fix is effective.

The database is hosted in local Docker containers on the same machine, so SSL-based database connections are not applicable and are excluded from scope.

## Glossary

- **Auth_Router**: The FastAPI router at `app/modules/auth/router.py` handling authentication endpoints (login, MFA challenge, MFA enrolment, password reset).
- **MFA_Service**: The service at `app/modules/auth/mfa_service.py` managing multi-factor authentication logic.
- **Firebase_Verifier**: The utility at `app/core/firebase_token.py` that verifies Firebase ID tokens using Google's public signing keys.
- **Rate_Limiter**: The ASGI middleware at `app/middleware/rate_limit.py` that throttles requests using Redis counters.
- **Webhook_Verifier**: The utility at `app/core/webhook_security.py` that signs and verifies HMAC-SHA256 webhook payloads.
- **Webhook_Router**: The FastAPI router at `app/modules/sms_chat/router_webhooks.py` handling inbound Connexus SMS webhooks.
- **Admin_Router**: The FastAPI router at `app/modules/admin/router.py` handling global admin operations (integrations, backup, demo reset).
- **Admin_Service**: The service at `app/modules/admin/service.py` handling integration configuration and backup export logic.
- **DataIO_Router**: The FastAPI router at `app/modules/data_io/router.py` handling CSV data export endpoints.
- **Auth_Service**: The service at `app/modules/auth/service.py` handling login, lockout, and password reset logic.
- **Security_Headers_Middleware**: The middleware at `app/middleware/security_headers.py` that sets CSP, CSRF, and other security headers.
- **URL_Validator**: A new utility at `app/core/url_validation.py` that validates external URLs against SSRF by blocking private/internal IP ranges.
- **JWT_Module**: The module at `app/modules/auth/jwt.py` responsible for JWT encoding and decoding.
- **Auth_Middleware**: The middleware at `app/middleware/auth.py` that extracts and validates JWT tokens from requests.
- **App_Factory**: The FastAPI application creation logic in `app/main.py`.
- **Audit_Logger**: The `write_audit_log()` function used to record security-relevant events to the audit log table.
- **E2E_Backend_Suite**: The pytest-based automated end-to-end test suite for backend API endpoints.
- **E2E_Frontend_Suite**: The Playwright-based automated end-to-end test suite for frontend user flows.
- **Portal_Token**: A bearer token issued to customer portal users for accessing their invoices and account.
- **Session_Manager**: The component managing user session creation, limits, and lifecycle.
- **Encryption_Service**: The envelope encryption utilities at `app/core/encryption.py` used for encrypting integration credentials.

## Requirements

### Requirement 1: Firebase MFA Server-Side Verification (REM-01)

**User Story:** As a platform operator, I want the server to verify Firebase ID tokens during MFA challenge and enrolment flows, so that attackers cannot bypass MFA by forging client-side verification responses.

#### Acceptance Criteria

1. WHEN a user submits an MFA challenge response, THE Auth_Router SHALL require a `firebase_id_token` field in the request body alongside the `mfa_token`.
2. WHEN a `firebase_id_token` is received, THE Auth_Router SHALL invoke the Firebase_Verifier to verify the token against Google's public signing keys with the correct Firebase project ID.
3. IF the Firebase_Verifier returns a verification failure, THEN THE Auth_Router SHALL respond with HTTP 401 and a descriptive error message.
4. WHEN the Firebase_Verifier returns valid claims, THE Auth_Router SHALL compare the `phone_number` claim from the token against the phone number stored in the MFA challenge session.
5. IF the phone number in the Firebase token does not match the enrolled phone number, THEN THE Auth_Router SHALL respond with HTTP 400 and reject the verification.
6. WHEN a user submits an MFA enrolment verification, THE Auth_Router SHALL apply the same Firebase ID token verification and phone number matching against the pending UserMfaMethod record.
7. THE Frontend MFA components SHALL send the Firebase ID token (obtained via `user.getIdToken()`) in all MFA challenge and enrolment verification requests.

### Requirement 2: Rate Limiter Fail-Closed for Auth Endpoints (REM-02, REM-08)

**User Story:** As a platform operator, I want the rate limiter to block authentication requests when Redis is unavailable, so that attackers cannot brute-force credentials or MFA codes during Redis outages.

#### Acceptance Criteria

1. WHEN Redis is unavailable and an authentication endpoint receives a request, THE Rate_Limiter SHALL respond with HTTP 503 and the message "Service temporarily unavailable. Please try again shortly."
2. WHEN Redis is unavailable and a non-authentication endpoint receives a request, THE Rate_Limiter SHALL allow the request through to maintain application availability.
3. WHEN a Redis error occurs during a rate limit check on an authentication endpoint, THE Rate_Limiter SHALL respond with HTTP 503 and log the error.
4. WHEN a Redis error occurs during a rate limit check on a non-authentication endpoint, THE Rate_Limiter SHALL allow the request through and log a warning.
5. THE Rate_Limiter SHALL classify endpoints under `/auth/`, `/login`, `/mfa/`, and `/password-reset/` as authentication endpoints.

### Requirement 3: CSP Firebase Domain Allowlisting (REM-19)

**User Story:** As a platform operator, I want the Content Security Policy to include Firebase domains, so that Firebase MFA flows are not blocked by the browser's CSP enforcement.

#### Acceptance Criteria

1. THE Security_Headers_Middleware SHALL include `https://identitytoolkit.googleapis.com`, `https://www.googleapis.com`, and `https://firebaseinstallations.googleapis.com` in the `connect-src` CSP directive.
2. WHEN a Firebase MFA verification request is made from the frontend, THE browser SHALL allow the connection without CSP violations.

### Requirement 4: Connexus Webhook HMAC Signature Verification (REM-03, REM-14)

**User Story:** As a platform operator, I want inbound Connexus webhooks to be verified using HMAC-SHA256 signatures, so that attackers cannot forge webhook payloads to inject fake SMS messages or status updates.

#### Acceptance Criteria

1. WHEN a Connexus webhook request is received and a webhook secret is configured, THE Webhook_Router SHALL extract the `x-connexus-signature` header and verify it using the Webhook_Verifier.
2. IF the HMAC signature verification fails, THEN THE Webhook_Router SHALL respond with HTTP 401 and log a warning.
3. WHEN no webhook secret is configured, THE Webhook_Router SHALL process the webhook without signature verification to support development environments.
4. THE Security_Headers_Middleware SHALL include Connexus webhook paths (`/api/webhooks/connexus/incoming` and `/api/webhooks/connexus/status`) in the CSRF exemption list.
5. THE application configuration SHALL support a `connexus_webhook_secret` setting for storing the HMAC shared secret.

### Requirement 5: Integration Backup Export Hardening (REM-04)

**User Story:** As a platform operator, I want integration backup exports to require password re-confirmation and to redact decrypted secrets, so that a compromised admin session cannot exfiltrate integration credentials.

#### Acceptance Criteria

1. WHEN a global admin requests an integration backup export, THE Admin_Router SHALL require a password re-confirmation via the `x-confirm-password` header.
2. IF the password re-confirmation fails or is missing, THEN THE Admin_Router SHALL respond with HTTP 400 or HTTP 401 respectively.
3. WHEN an integration backup is exported, THE Admin_Service SHALL redact or mask sensitive credential fields (API keys, secrets, tokens) in the export payload.
4. WHEN an integration backup is successfully exported, THE Audit_Logger SHALL record the event with the action `admin.integration_backup_exported`, the requesting user ID, and the source IP address.

### Requirement 6: Data Export Audit Logging (REM-06)

**User Story:** As a platform operator, I want all data export operations to be recorded in the audit log, so that I can track who exported what data and when for compliance and incident response.

#### Acceptance Criteria

1. WHEN a customer data export is completed, THE DataIO_Router SHALL write an audit log entry with action `data_io.customers_exported`, the organisation ID, user ID, source IP, and export format.
2. WHEN a vehicle data export is completed, THE DataIO_Router SHALL write an audit log entry with action `data_io.vehicles_exported`, the organisation ID, user ID, source IP, and export format.
3. WHEN an invoice data export is completed, THE DataIO_Router SHALL write an audit log entry with action `data_io.invoices_exported`, the organisation ID, user ID, source IP, and export format.
4. THE Audit_Logger SHALL record all data export events before the response is returned to the client.

### Requirement 7: Account Lockout Email Notification (REM-07)

**User Story:** As a user, I want to receive an email notification when my account is permanently locked due to repeated failed login attempts, so that I am aware of potential unauthorized access attempts.

#### Acceptance Criteria

1. WHEN an account is permanently locked, THE Auth_Service SHALL send an email notification to the locked account's email address.
2. THE lockout email SHALL include the platform name, a description of why the account was locked, and a support contact link.
3. IF the lockout email fails to send, THEN THE Auth_Service SHALL log the failure and continue the lockout process without blocking.

### Requirement 8: Replace python-jose with PyJWT (REM-12)

**User Story:** As a platform operator, I want the application to use the actively maintained PyJWT library instead of the unmaintained python-jose library, so that JWT handling receives ongoing security patches.

#### Acceptance Criteria

1. THE application dependencies SHALL include `PyJWT[crypto]>=2.8.0` instead of `python-jose[cryptography]`.
2. THE JWT_Module SHALL use `import jwt` and `jwt.exceptions.InvalidTokenError` instead of `from jose import jwt, JWTError`.
3. THE Auth_Middleware SHALL use the PyJWT API for token decoding and validation.
4. THE Firebase_Verifier SHALL use the PyJWT API for Firebase ID token verification.
5. WHEN a valid JWT is decoded, THE JWT_Module SHALL return the same payload structure as before the migration.
6. WHEN an invalid or expired JWT is decoded, THE JWT_Module SHALL raise an appropriate error that is caught by existing error handlers.

### Requirement 9: SSRF Protection on Integration Endpoint URLs (REM-13)

**User Story:** As a platform operator, I want integration endpoint URLs to be validated against SSRF attacks, so that attackers cannot use the server to probe internal network resources.

#### Acceptance Criteria

1. WHEN an integration endpoint URL is saved or updated, THE Admin_Service SHALL invoke the URL_Validator to check the URL.
2. THE URL_Validator SHALL reject URLs that resolve to private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), link-local addresses (169.254.0.0/16), and loopback addresses (127.0.0.0/8).
3. THE URL_Validator SHALL reject URLs that do not use the `http` or `https` scheme.
4. THE URL_Validator SHALL reject URLs with no hostname or with hostnames that cannot be resolved via DNS.
5. IF the URL_Validator rejects a URL, THEN THE Admin_Service SHALL return a descriptive error message to the client.

### Requirement 10: Demo Reset Endpoint Environment Guard (REM-17)

**User Story:** As a platform operator, I want the demo reset endpoint to be strictly restricted to development environments, so that it cannot be accidentally or maliciously triggered in production.

#### Acceptance Criteria

1. THE Admin_Router SHALL restrict the demo reset endpoint to an explicit allowlist of environments containing only `"development"`.
2. WHEN the demo reset endpoint is called in any environment not in the allowlist, THE Admin_Router SHALL respond with HTTP 403.

### Requirement 11: Disable Swagger UI in Production (REM-20)

**User Story:** As a platform operator, I want Swagger UI, ReDoc, and the OpenAPI schema to be disabled in production, so that attackers cannot use API documentation to discover endpoints.

#### Acceptance Criteria

1. WHEN the application environment is not `"development"`, THE App_Factory SHALL set `docs_url`, `redoc_url`, and `openapi_url` to `None`.
2. WHEN the application environment is `"development"`, THE App_Factory SHALL serve Swagger UI at `/docs`, ReDoc at `/redoc`, and the OpenAPI schema at `/openapi.json`.

### Requirement 12: Session-Scoped Org Context for Global Admins (REM-10)

**User Story:** As a platform operator, I want global admins to explicitly select an organisation context before accessing tenant data, so that accidental cross-tenant data access is prevented.

#### Acceptance Criteria

1. WHEN a global admin accesses a tenant-scoped endpoint without an active org context, THE Auth_Middleware SHALL respond with HTTP 403 and a message indicating that an org context must be selected.
2. THE Admin_Router SHALL provide an endpoint for global admins to set their active org context for the current session.
3. WHEN a global admin sets an org context, THE Session_Manager SHALL store the selected `org_id` in the session and apply it to all subsequent tenant-scoped queries.
4. THE Audit_Logger SHALL record org context switches by global admins with the action `admin.org_context_switched`.

### Requirement 13: Encryption Key Rotation Mechanism (REM-11)

**User Story:** As a platform operator, I want a management command to rotate encryption keys, so that I can periodically rotate keys without data loss as part of security best practices.

#### Acceptance Criteria

1. THE Encryption_Service SHALL provide a CLI management command that accepts an old key and a new key as parameters.
2. WHEN the rotation command is executed, THE Encryption_Service SHALL decrypt all `config_encrypted` and `credentials_encrypted` column values using the old key and re-encrypt them using the new key.
3. THE rotation command SHALL execute all re-encryption operations within a single database transaction.
4. IF any decryption or re-encryption operation fails, THEN THE rotation command SHALL roll back the entire transaction and report the error.
5. WHEN the rotation completes successfully, THE rotation command SHALL report the number of records re-encrypted.

### Requirement 14: Portal Token TTL and Rotation (REM-15)

**User Story:** As a platform operator, I want portal tokens to have a configurable time-to-live and a regeneration mechanism, so that compromised tokens expire automatically and can be rotated.

#### Acceptance Criteria

1. THE Portal_Token SHALL have a `portal_token_expires_at` timestamp column on the customers table.
2. THE Portal_Token SHALL have a configurable default TTL of 90 days.
3. WHEN a portal token is used after its expiry timestamp, THE Auth_Middleware SHALL reject the request with HTTP 401.
4. THE Admin_Router SHALL provide an endpoint to regenerate a customer's portal token, which sets a new token value and resets the expiry timestamp.

### Requirement 15: Session Limit Race Condition Fix (REM-16)

**User Story:** As a platform operator, I want session creation to be protected against race conditions, so that concurrent login attempts cannot exceed the configured session limit.

#### Acceptance Criteria

1. WHEN a new session is created, THE Session_Manager SHALL acquire a Redis-based distributed lock keyed on the user ID before checking the session count.
2. IF the lock cannot be acquired within 5 seconds, THEN THE Session_Manager SHALL reject the login attempt with an appropriate error.
3. THE Session_Manager SHALL release the lock after the session creation or rejection is complete.

### Requirement 16: Password Reset Timing Side-Channel Mitigation (REM-18)

**User Story:** As a platform operator, I want password reset requests to have consistent response times regardless of whether the email exists, so that attackers cannot enumerate valid email addresses via timing analysis.

#### Acceptance Criteria

1. WHEN a password reset is requested for a non-existent email, THE Auth_Service SHALL introduce a random delay between 0.5 and 1.5 seconds before responding.
2. THE Auth_Service SHALL return the same HTTP status code and response body for both existent and non-existent email addresses on password reset requests.

### Requirement 17: Dynamic SQL Column Name Whitelist (REM-21)

**User Story:** As a platform operator, I want dynamic SQL column names to be validated against an explicit allowlist, so that SQL injection via column name manipulation is prevented.

#### Acceptance Criteria

1. WHEN a dynamic column name is used in a query, THE Admin_Service SHALL validate the column name against an explicit allowlist of permitted column names.
2. IF a column name is not in the allowlist, THEN THE Admin_Service SHALL reject the request with a descriptive error and log a warning.

### Requirement 18: JWT HS256 to RS256 Migration (REM-22)

**User Story:** As a platform operator, I want the application to support RS256 JWT signing, so that token verification can be decoupled from the signing secret in preparation for future microservice architecture.

#### Acceptance Criteria

1. THE JWT_Module SHALL support RS256 algorithm for signing and verifying JWTs using an RSA key pair.
2. THE JWT_Module SHALL accept configuration for RSA private key (signing) and public key (verification) paths.
3. WHEN an RS256 key pair is configured, THE JWT_Module SHALL sign new tokens with RS256.
4. WHEN no RS256 key pair is configured, THE JWT_Module SHALL fall back to HS256 signing for backward compatibility.
5. THE JWT_Module SHALL accept tokens signed with either HS256 or RS256 during a migration period to avoid invalidating existing sessions.

### Requirement 19: Automated Backend E2E Testing

**User Story:** As a developer, I want automated pytest-based end-to-end test scripts that exercise all backend API features, so that I can verify no functionality is broken after each security remediation.

#### Acceptance Criteria

1. THE E2E_Backend_Suite SHALL include test scripts covering authentication flows (login, MFA challenge, MFA enrolment, password reset, session management).
2. THE E2E_Backend_Suite SHALL include test scripts covering data export endpoints (customers, vehicles, invoices) and verifying audit log entries are created.
3. THE E2E_Backend_Suite SHALL include test scripts covering admin operations (integration backup, demo reset, integration URL saving).
4. THE E2E_Backend_Suite SHALL include test scripts covering webhook endpoints (Connexus incoming SMS, status updates) with valid and invalid HMAC signatures.
5. THE E2E_Backend_Suite SHALL include test scripts covering rate limiter behaviour when Redis is available and when Redis is unavailable.
6. THE E2E_Backend_Suite SHALL include test scripts verifying that Swagger UI, ReDoc, and OpenAPI schema are inaccessible in non-development environments.
7. WHEN a test script is executed, THE E2E_Backend_Suite SHALL report pass/fail status for each test case with descriptive output.

### Requirement 20: Automated Frontend E2E Testing

**User Story:** As a developer, I want automated Playwright-based end-to-end test scripts that simulate real user interactions across all frontend features, so that I can verify no UI functionality is broken after each security remediation.

#### Acceptance Criteria

1. THE E2E_Frontend_Suite SHALL include Playwright test scripts simulating user login, MFA challenge, and MFA enrolment flows including Firebase ID token submission.
2. THE E2E_Frontend_Suite SHALL include Playwright test scripts simulating data export operations (clicking export buttons, verifying downloads).
3. THE E2E_Frontend_Suite SHALL include Playwright test scripts simulating admin operations (integration management, backup export with password confirmation).
4. THE E2E_Frontend_Suite SHALL include Playwright test scripts simulating customer portal access with valid and expired portal tokens.
5. THE E2E_Frontend_Suite SHALL include Playwright test scripts verifying that CSP headers do not block Firebase MFA flows.
6. WHEN a Playwright test script is executed, THE E2E_Frontend_Suite SHALL report pass/fail status for each test case with screenshots on failure.
