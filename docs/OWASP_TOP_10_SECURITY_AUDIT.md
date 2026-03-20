# OWASP Top 10 Security Audit Report

**Application:** WorkshopPro NZ (OraInvoice)  
**Type:** Multi-tenant SaaS — FastAPI backend, React frontend, PostgreSQL, Redis  
**Audit Date:** 20 March 2026  
**Auditor:** Automated code review (static analysis)  
**Scope:** Full codebase — backend, frontend, middleware, infrastructure config  

---

## Executive Summary

The application demonstrates strong security fundamentals: bcrypt password hashing, envelope encryption (AES-256-GCM) for secrets at rest, JWT with refresh token rotation and reuse detection, RBAC middleware, RLS-based tenant isolation, CSRF protection, comprehensive security headers, and rate limiting. However, several findings require attention, ranging from critical to low severity.

| Severity | Count |
|----------|-------|
| Critical | 2     |
| High     | 5     |
| Medium   | 6     |
| Low      | 4     |

---

## A01:2021 — Broken Access Control

### FINDING-01: Integration Backup Exports Decrypted Secrets (HIGH)

**Location:** `GET /admin/integrations/backup` → `app/modules/admin/service.py:export_integration_settings()`

**Description:** The backup endpoint decrypts all integration credentials (Stripe secret keys, SMTP passwords, Twilio auth tokens, SMS provider credentials) and returns them as plaintext JSON. While protected by `require_role("global_admin")`, a compromised global admin session or XSS on the admin panel would expose every integration secret in one request.

**Recommendation:**
- Require password re-confirmation before allowing backup export
- Encrypt the backup payload with a user-supplied passphrase
- Add audit logging specifically for backup downloads (currently missing)
- Consider excluding raw secrets and only exporting non-sensitive config

### FINDING-02: No Audit Logging on Data Exports (HIGH)

**Location:** `app/modules/data_io/router.py` — `/export/customers`, `/export/vehicles`, `/export/invoices`

**Description:** CSV export endpoints for customers, vehicles, and invoices have zero audit logging. An org admin or salesperson can export all customer PII (names, emails, phone numbers, addresses) without any record of the action.

**Recommendation:** Add `write_audit_log()` calls to all export endpoints recording who exported what, when, and how many records.

### FINDING-03: Global Admin Bypasses All Tenant Isolation (MEDIUM)

**Location:** `app/middleware/auth.py`, `app/middleware/rbac.py`

**Description:** Global admin users have `org_id = NULL` in their JWT, which means PostgreSQL RLS policies (based on `app.current_org_id`) do not apply. If a global admin account is compromised, the attacker has unrestricted access to all tenant data across the entire platform.

**Recommendation:**
- Implement session-scoped org context for global admins when accessing tenant data
- Add IP allowlist enforcement for global admin accounts (currently skipped)
- Consider requiring hardware MFA (passkey) for global admin accounts

---

## A02:2021 — Cryptographic Failures

### FINDING-04: No Encryption Key Rotation Mechanism (MEDIUM)

**Location:** `app/config.py` — `encryption_master_key`, `app/core/encryption.py`

**Description:** The envelope encryption master key is loaded from `.env` with no rotation mechanism. If the key is ever compromised, all encrypted data (integration credentials, SMS provider credentials, email provider credentials) is exposed. There is no way to re-encrypt data with a new key without manual intervention.

**Recommendation:**
- Implement a key rotation command that re-encrypts all `config_encrypted` and `credentials_encrypted` columns
- Support multiple active keys with a key ID prefix on encrypted blobs
- Consider using a KMS (AWS KMS, HashiCorp Vault) for key management in production

### FINDING-05: JWT Uses HS256 Symmetric Signing (LOW)

**Location:** `app/config.py` — `jwt_algorithm: str = "HS256"`

**Description:** HS256 uses a shared secret for both signing and verification. If the secret leaks, anyone can forge tokens. RS256 (asymmetric) would allow the backend to sign tokens with a private key while other services verify with a public key.

**Recommendation:** Consider migrating to RS256 for JWT signing, especially if the platform grows to include microservices that need to verify tokens without holding the signing key.

---

## A03:2021 — Injection

### FINDING-06: Dynamic SQL Column Names in Setup Wizard (LOW)

**Location:** `app/modules/setup_wizard/service.py:546`

```python
set_clauses = ", ".join(f"{k} = :{k}" for k in fields)
text(f"UPDATE organisations SET {set_clauses} WHERE id = :oid")
```

**Description:** Column names are interpolated into SQL via f-string. While the field names are currently hardcoded by the developer (not from user input), this pattern is fragile. A future code change could inadvertently pass user-controlled keys.

**Recommendation:** Add a whitelist check: `assert all(k in ALLOWED_ORG_COLUMNS for k in fields)` before constructing the query.

### FINDING-07: Dynamic Table Names in Hard Delete (LOW)

**Location:** `app/modules/admin/service.py:2853`

```python
text(f'DELETE FROM "{tbl_name}" WHERE "{col_name}" = :oid')
```

**Description:** Table and column names come from `information_schema` (database metadata), not user input. This is safe in practice, but the pattern should be documented to prevent future misuse.

**Recommendation:** Add a comment explaining the source of `tbl_name`/`col_name` and consider validating them against a known set of application tables.

---

## A04:2021 — Insecure Design

### FINDING-08: Firebase Phone Auth — No Server-Side Verification (CRITICAL)

**Location:** `app/modules/auth/router.py:1192` — `mfa_firebase_verify()`

**Description:** When Firebase is the MFA SMS provider, the entire phone verification happens client-side (frontend calls `signInWithPhoneNumber` + `confirm(code)`). The backend endpoint `/mfa/firebase-verify` only checks that:
1. A valid `mfa_token` exists (proving login started)
2. Firebase is the configured provider

It does NOT verify that Firebase actually confirmed the phone number. A malicious client could skip the Firebase verification step entirely and call `/mfa/firebase-verify` directly with just the `mfa_token`, bypassing MFA completely.

**Recommendation:**
- Require the frontend to send the Firebase ID token after phone verification
- Verify the Firebase ID token server-side using `firebase-admin` SDK
- Confirm the phone number in the token matches the user's registered MFA phone
- This is the single most critical finding in this audit

### FINDING-09: Rate Limiter Fails Open When Redis Is Down (CRITICAL)

**Location:** `app/middleware/rate_limit.py:115-140`

**Description:** The docstring claims "fails closed — returning HTTP 503" but the actual implementation fails open:

```python
# Line 128: "Fail open — allow the request through when Redis is unavailable."
logger.warning("Rate limiter Redis unavailable — allowing request through")
await self.app(scope, receive, send)
return
```

If Redis goes down (crash, network partition, OOM), all rate limiting is disabled. An attacker who can cause Redis to become unavailable (e.g., by flooding it) can then brute-force login, MFA codes, or password reset tokens without any throttling.

**Recommendation:**
- Change to fail-closed behavior (return 503) for authentication endpoints at minimum
- Keep fail-open only for non-sensitive read endpoints to maintain availability
- Add monitoring/alerting for Redis unavailability
- Fix the misleading docstring

---

## A05:2021 — Security Misconfiguration

### FINDING-10: CORS Allows Localhost Origins (MEDIUM)

**Location:** `app/config.py:92`

```python
cors_origins: list[str] = [
    "http://localhost:5173", "http://localhost:3000",
    "http://localhost:80", "http://localhost",
    "https://invoice.oraflows.co.nz"
]
```

**Description:** Multiple localhost origins are included in the default CORS configuration. If this default is used in production (i.e., `CORS_ORIGINS` env var is not set), an attacker running a local server could make cross-origin requests to the production API using a victim's browser session.

**Recommendation:**
- Add a `model_validator` that rejects localhost origins in production/staging environments
- Or split the config: only include the production origin by default, add localhost via env var in development

### FINDING-11: Nginx Trusts All X-Forwarded-For Sources (MEDIUM)

**Location:** `nginx/nginx.conf`

```nginx
real_ip_header X-Forwarded-For;
set_real_ip_from 0.0.0.0/0;
```

**Description:** `set_real_ip_from 0.0.0.0/0` trusts X-Forwarded-For headers from ANY source. An attacker can spoof their IP address by setting a fake `X-Forwarded-For` header, bypassing IP-based rate limiting and IP allowlists.

**Recommendation:** Restrict `set_real_ip_from` to your actual reverse proxy/load balancer IP ranges (e.g., Cloudflare IPs, AWS ALB subnets).

### FINDING-12: Swagger UI Accessible in Production (LOW)

**Location:** `nginx/nginx.conf` — `/docs` and `/redoc` routes, `app/middleware/auth.py` — PUBLIC_PATHS includes `/docs`, `/redoc`, `/openapi.json`

**Description:** API documentation endpoints are always public. While FastAPI can conditionally disable them, the nginx config always proxies them and the auth middleware always exempts them.

**Recommendation:** Conditionally block `/docs`, `/redoc`, `/openapi.json` in production via nginx or by removing them from PUBLIC_PATHS when `environment != "development"`.

---

## A06:2021 — Vulnerable and Outdated Components

### FINDING-13: python-jose Library Has Known Issues (MEDIUM)

**Location:** `pyproject.toml` — `python-jose[cryptography]>=3.3.0`

**Description:** `python-jose` is no longer actively maintained and has had security advisories. The recommended replacement is `PyJWT` or `joserfc`.

**Recommendation:** Migrate from `python-jose` to `PyJWT>=2.8.0` which is actively maintained and has better security track record.

---

## A07:2021 — Identification and Authentication Failures

### FINDING-14: No Rate Limiting on MFA Code Verification (HIGH)

**Location:** `app/modules/auth/mfa_service.py`

**Description:** MFA attempt counting exists (`_increment_mfa_attempts` with max 5 attempts per 15 minutes), but this is per-user across all methods. The 6-digit OTP code has only 1,000,000 possible values. With 5 attempts per 15 minutes and a 5-minute OTP expiry, brute force is impractical. However, the rate limiter failing open (FINDING-09) means that if Redis is down, the MFA attempt counter also stops working, making brute force feasible.

**Recommendation:** This finding is mitigated IF FINDING-09 is fixed. Ensure MFA attempt counting works independently of the rate limiter middleware.

### FINDING-15: No Email Notification on Permanent Account Lockout (HIGH)

**Location:** `app/modules/auth/service.py` — account lockout logic

**Description:** After 10 failed login attempts, the account is permanently deactivated. However, there is no email notification sent to the account owner. A legitimate user whose account is being attacked would not know their account has been locked until they try to log in.

**Recommendation:** Send an email notification when an account is permanently locked, including the IP addresses of the failed attempts and instructions for contacting support.

---

## A08:2021 — Software and Data Integrity Failures

### FINDING-16: Connexus Webhooks Have No Signature Verification (HIGH)

**Location:** `app/modules/sms_chat/router_webhooks.py`

**Description:** The Connexus SMS webhook endpoints (`/api/webhooks/connexus/incoming` and `/api/webhooks/connexus/status`) accept any POST request without verifying the sender's identity. The codebase has a `webhook_security.py` module with `verify_webhook_signature()` but it is NOT used in the webhook handlers. An attacker could forge incoming SMS messages or delivery status updates.

**Recommendation:**
- Implement HMAC signature verification using `verify_webhook_signature()` from `app/core/webhook_security.py`
- If Connexus doesn't support HMAC signing, implement IP allowlisting for their webhook source IPs
- At minimum, add a shared secret header check

---

## A09:2021 — Security Logging and Monitoring Failures

### FINDING-17: Rate Limiter Docstring Contradicts Implementation (MEDIUM)

**Location:** `app/middleware/rate_limit.py:11-12`

**Description:** The module docstring states "fails closed — returning HTTP 503" but the implementation fails open. This is dangerous because security reviewers reading the docstring would incorrectly believe the system is protected during Redis outages.

**Recommendation:** Fix the docstring to match the actual behavior, then fix the behavior per FINDING-09.

---

## A10:2021 — Server-Side Request Forgery (SSRF)

### FINDING-18: No URL Validation on Integration Endpoints (MEDIUM)

**Location:** `app/modules/admin/service.py` — `save_carjam_config()` accepts `endpoint_url`

**Description:** The Carjam integration allows a global admin to configure a custom `endpoint_url`. If an attacker gains global admin access, they could set this to an internal service URL (e.g., `http://169.254.169.254/latest/meta-data/` on AWS) to perform SSRF attacks.

**Recommendation:**
- Validate that configured URLs resolve to public IP addresses
- Block RFC 1918 private ranges, link-local (169.254.x.x), and loopback addresses
- Implement a URL allowlist for known integration endpoints

---

## What's Done Well

These security controls are properly implemented and deserve recognition:

1. **Password hashing:** bcrypt with default cost factor
2. **Token storage:** Access token in memory (not localStorage), refresh token as httpOnly/Secure/SameSite=Strict cookie
3. **Refresh token rotation:** Family-based rotation with reuse detection and session revocation
4. **Envelope encryption:** AES-256-GCM for secrets at rest with separate data keys
5. **CSRF protection:** SecurityHeadersMiddleware enforces X-CSRF-Token for cookie-authenticated state-changing requests
6. **Security headers:** HSTS, X-Frame-Options DENY, X-Content-Type-Options nosniff, strict CSP, Referrer-Policy, Permissions-Policy
7. **RLS tenant isolation:** PostgreSQL Row-Level Security with `app.current_org_id` session variable
8. **RBAC middleware:** Path-based + role-based access control with permission overrides
9. **Rate limiting:** Sliding-window per-user, per-org, and per-IP on auth endpoints
10. **Account lockout:** Progressive lockout (5 failures → 15min temp lock, 10 → permanent deactivation)
11. **Startup validation:** Rejects default placeholder secrets in production/staging
12. **Stripe webhook:** Proper signature verification using `stripe.Webhook.construct_event()`
13. **TLS enforcement:** TLS 1.3 minimum in production, database SSL mode configurable
14. **Audit logging:** Comprehensive append-only audit trail for admin actions
15. **HIBP integration:** Password breach checking during password set/reset

---

## Remediation Priority

| Priority | Finding | Effort |
|----------|---------|--------|
| 1 | FINDING-08: Firebase MFA server-side verification | Medium |
| 2 | FINDING-09: Rate limiter fail-closed for auth endpoints | Low |
| 3 | FINDING-16: Connexus webhook signature verification | Low |
| 4 | FINDING-11: Nginx X-Forwarded-For trust restriction | Low |
| 5 | FINDING-01: Backup endpoint security hardening | Medium |
| 6 | FINDING-02: Data export audit logging | Low |
| 7 | FINDING-14: MFA brute-force (dependent on #2) | Low |
| 8 | FINDING-15: Account lockout email notification | Low |
| 9 | FINDING-10: CORS localhost in production | Low |
| 10 | FINDING-13: python-jose replacement | Medium |
| 11 | FINDING-04: Encryption key rotation | High |
| 12 | FINDING-18: SSRF URL validation | Medium |
| 13 | FINDING-03: Global admin tenant scoping | High |
| 14 | FINDING-12: Swagger UI in production | Low |
| 15 | FINDING-17: Docstring correction | Trivial |
| 16 | FINDING-06: SQL column whitelist | Low |
| 17 | FINDING-07: SQL table name documentation | Trivial |
| 18 | FINDING-05: JWT algorithm upgrade | Medium |
