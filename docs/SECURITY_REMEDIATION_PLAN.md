# Security Remediation Plan

**Application:** WorkshopPro NZ (OraInvoice)  
**Date:** 20 March 2026  
**Source:** OWASP Top 10 Audit (18 findings) + Grey-Box Pen Test (14 findings)  
**Deduplicated Total:** 22 unique findings across both reports

---

## Consolidated Finding Map

Many findings appear in both reports. This table maps them to a single remediation item.

| ID | Description | OWASP | Pentest | Severity | Sprint |
|----|-------------|-------|---------|----------|--------|
| REM-01 | Firebase MFA bypass — no server-side ID token verification | FINDING-08 | PENTEST-01, PENTEST-06 | Critical | S0 |
| REM-02 | Rate limiter fails open when Redis is down | FINDING-09, FINDING-17 | PENTEST-02 | Critical | S0 |
| REM-03 | Connexus webhooks — no HMAC signature verification | FINDING-16 | PENTEST-03 | High | S1 |
| REM-04 | Integration backup exports decrypted secrets | FINDING-01 | PENTEST-04 | High | S1 |
| REM-05 | Nginx trusts all X-Forwarded-For sources | FINDING-11 | PENTEST-05 | Medium | S1 |
| REM-06 | Data export endpoints lack audit logging | FINDING-02 | PENTEST-08 | High | S1 |
| REM-07 | Account lockout email notification not implemented | FINDING-15 | PENTEST-09 | High | S2 |
| REM-08 | MFA brute-force when rate limiter is down | FINDING-14 | — | High | S0 (fixed by REM-02) |
| REM-09 | CORS allows localhost origins in production | FINDING-10 | — | Medium | S2 |
| REM-10 | Global admin bypasses all tenant isolation | FINDING-03 | — | Medium | S3 |
| REM-11 | No encryption key rotation mechanism | FINDING-04 | — | Medium | S3 |
| REM-12 | python-jose library unmaintained | FINDING-13 | — | Medium | S2 |
| REM-13 | SSRF via custom integration endpoint URLs | FINDING-18 | — | Medium | S2 |
| REM-14 | CSRF exemption gap on Connexus webhooks | — | PENTEST-07 | Low | S1 (with REM-03) |
| REM-15 | Portal token has no TTL | — | PENTEST-10 | Medium | S3 |
| REM-16 | Session limit enforcement race condition | — | PENTEST-11 | Low | S3 |
| REM-17 | Demo reset endpoint environment guard | — | PENTEST-12 | Low | S2 |
| REM-18 | Password reset timing side-channel | — | PENTEST-13 | Low | S3 |
| REM-19 | CSP missing Firebase domains | — | PENTEST-14 | Low | S0 (with REM-01) |
| REM-20 | Swagger UI accessible in production | FINDING-12 | — | Low | S2 |
| REM-21 | Dynamic SQL column name whitelist | FINDING-06 | — | Low | S3 |
| REM-22 | JWT HS256 → RS256 migration | FINDING-05 | — | Low | S3 |

---

## Sprint S0 — Immediate (This Week)

### REM-01: Firebase MFA Server-Side Verification

**Fixes:** FINDING-08, PENTEST-01, PENTEST-06  
**Effort:** Medium (4–6 hours)  
**Risk Reduction:** Critical → Resolved

The app already has `app/core/firebase_token.py` with a working `verify_firebase_id_token()` function. The fix wires it into both the challenge and enrolment flows.

**Files to modify:**

1. `app/modules/auth/router.py` — `mfa_firebase_verify()` and `mfa_enrol_firebase_verify()`
2. `app/modules/auth/mfa_service.py` — `verify_mfa()` firebase_verified path
3. `frontend/src/pages/auth/MfaVerify.tsx` — send Firebase ID token in request
4. `frontend/src/components/mfa/SmsEnrolWizard.tsx` — send Firebase ID token in request

**Implementation:**

Step 1 — Backend: Modify `/mfa/firebase-verify` (challenge flow):
```python
# app/modules/auth/router.py — mfa_firebase_verify()

body = await request.json()
mfa_token = body.get("mfa_token", "")
firebase_id_token = body.get("firebase_id_token", "")

if not mfa_token or not firebase_id_token:
    return JSONResponse(status_code=400, content={"detail": "Missing mfa_token or firebase_id_token"})

# ... existing session_data lookup ...

# Verify the Firebase ID token server-side
from app.core.firebase_token import verify_firebase_id_token
import json
from app.core.encryption import envelope_decrypt_str

# Get the Firebase project_id from the provider credentials
creds = json.loads(envelope_decrypt_str(provider.credentials_encrypted))
project_id = creds.get("project_id", "")

try:
    firebase_claims = await verify_firebase_id_token(firebase_id_token, project_id)
except ValueError as exc:
    return JSONResponse(status_code=401, content={"detail": f"Firebase verification failed: {exc}"})

# Confirm the phone number in the token matches the user's enrolled phone
firebase_phone = firebase_claims.get("phone_number")
if not firebase_phone:
    return JSONResponse(status_code=400, content={"detail": "Firebase token does not contain a phone number"})

# Compare with the phone number stored in the challenge session
session_phone = session_data.get("phone_number")
if session_phone and firebase_phone != session_phone:
    return JSONResponse(status_code=400, content={"detail": "Phone number mismatch"})
```

Step 2 — Backend: Modify `/mfa/enrol/firebase-verify` (enrolment flow):
```python
# Same pattern — require firebase_id_token, verify it, confirm phone matches
# the phone_number on the pending UserMfaMethod record
```

Step 3 — Frontend: Send the Firebase ID token after `confirm(code)`:
```typescript
// After successful Firebase confirm()
const idToken = await user.getIdToken();
await api.post('/auth/mfa/firebase-verify', {
  mfa_token: mfaToken,
  firebase_id_token: idToken,
});
```

Step 4 — Update CSP (REM-19) in `app/core/security.py`:
```python
"connect-src 'self' https://api.stripe.com "
"https://identitytoolkit.googleapis.com "
"https://www.googleapis.com "
"https://firebaseinstallations.googleapis.com; "
```

---

### REM-02: Rate Limiter Fail-Closed for Auth Endpoints

**Fixes:** FINDING-09, FINDING-14, FINDING-17, PENTEST-02  
**Effort:** Low (1–2 hours)  
**Risk Reduction:** Critical → Resolved

**Files to modify:**
1. `app/middleware/rate_limit.py`

**Implementation:**

```python
# app/middleware/rate_limit.py — _get_redis() and __call__()

# Fix 1: Update the docstring to match the NEW behavior (fail-closed)
"""When Redis is unavailable the middleware fails closed — returning
HTTP 503 (Service Unavailable) for authentication endpoints to prevent
unlimited unthrottled access. Non-auth endpoints fail open for availability."""

# Fix 2: In __call__(), differentiate auth vs non-auth endpoints
async def __call__(self, scope, receive, send):
    if scope["type"] != "http":
        await self.app(scope, receive, send)
        return

    request = Request(scope)
    redis = await self._get_redis()

    if not redis:
        path = request.url.path
        if is_auth_endpoint(path):
            # Fail CLOSED for auth endpoints — block the request
            logger.error("Rate limiter Redis unavailable — blocking auth request to %s", path)
            response = JSONResponse(
                status_code=503,
                content={"detail": "Service temporarily unavailable. Please try again shortly."},
            )
            await response(scope, receive, send)
            return
        else:
            # Fail open for non-auth endpoints to maintain availability
            logger.warning("Rate limiter Redis unavailable — allowing non-auth request through")
            await self.app(scope, receive, send)
            return

    # ... rest of rate limiting logic unchanged ...
```

```python
# Fix 3: Same pattern in the except block
except Exception:
    logger.warning("Rate limiter Redis error during check")
    self._redis = None
    path = request.url.path
    if is_auth_endpoint(path):
        response = JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})
        await response(scope, receive, send)
        return
    await self.app(scope, receive, send)
```

---

## Sprint S1 — This Sprint (Next 1–2 Weeks)

### REM-03: Connexus Webhook HMAC Signature Verification

**Fixes:** FINDING-16, PENTEST-03, PENTEST-07 (REM-14)  
**Effort:** Medium (3–4 hours)  
**Risk Reduction:** High → Resolved

The app already has `app/core/webhook_security.py` with `verify_webhook_signature()`. It just needs to be wired into the webhook handlers.

**Files to modify:**
1. `app/modules/sms_chat/router_webhooks.py`
2. `app/config.py` — add `connexus_webhook_secret` setting
3. `app/middleware/security_headers.py` — add Connexus paths to CSRF exemptions

**Implementation:**

```python
# app/config.py — add setting
connexus_webhook_secret: str = ""

# app/modules/sms_chat/router_webhooks.py — incoming_sms()
from app.core.webhook_security import verify_webhook_signature
from app.config import settings

@router.post("/incoming")
async def incoming_sms(request: Request):
    raw_body = await request.body()

    # Verify HMAC signature if webhook secret is configured
    if settings.connexus_webhook_secret:
        signature = request.headers.get("x-connexus-signature", "")
        if not verify_webhook_signature(raw_body, signature, settings.connexus_webhook_secret):
            logger.warning("Incoming webhook: invalid HMAC signature")
            return JSONResponse(status_code=401, content={"detail": "Invalid signature"})

    try:
        body = json.loads(raw_body) if raw_body else {}
    except Exception:
        return {"status": "ok"}

    # ... rest of handler unchanged ...
```

```python
# app/middleware/security_headers.py — add to CSRF exemptions
_CSRF_EXEMPT_PATHS: set[str] = {
    "/api/v1/payments/stripe/webhook",
    "/api/v2/payments/stripe/webhook",
    "/api/webhooks/connexus/incoming",   # ADD
    "/api/webhooks/connexus/status",     # ADD
}
```

---

### REM-04: Harden Integration Backup Export

**Fixes:** FINDING-01, PENTEST-04  
**Effort:** Medium (3–4 hours)  
**Risk Reduction:** High → Resolved

**Files to modify:**
1. `app/modules/admin/router.py` — backup endpoint
2. `app/modules/admin/service.py` — `export_integration_settings()`

**Implementation:**

```python
# app/modules/admin/router.py — GET /admin/integrations/backup

@router.get("/integrations/backup", dependencies=[require_role("global_admin")])
async def backup_integrations(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    # Require password re-confirmation via header
    password = request.headers.get("x-confirm-password", "")
    if not password:
        return JSONResponse(status_code=400, content={"detail": "Password confirmation required"})

    user_id = getattr(request.state, "user_id", None)
    from app.modules.auth.models import User
    from app.modules.auth.password import verify_password
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return JSONResponse(status_code=401, content={"detail": "Invalid password"})

    data = await export_integration_settings(db)

    # Audit log the backup download
    ip_address = request.client.host if request.client else None
    await write_audit_log(
        session=db, org_id=None, user_id=uuid.UUID(user_id),
        action="admin.integration_backup_exported",
        entity_type="integration_backup", entity_id=None,
        after_value={"ip_address": ip_address},
        ip_address=ip_address,
    )

    return JSONResponse(content=data)
```

---

### REM-05: Restrict Nginx X-Forwarded-For Trust

**Fixes:** FINDING-11, PENTEST-05  
**Effort:** Low (30 minutes)  
**Risk Reduction:** Medium → Resolved

**Files to modify:**
1. `nginx/nginx.conf`

**Implementation:**

```nginx
# Replace:
#   set_real_ip_from 0.0.0.0/0;
# With your actual proxy/load balancer ranges:

# Docker internal network
set_real_ip_from 172.16.0.0/12;
set_real_ip_from 10.0.0.0/8;

# If behind Cloudflare, add their IP ranges:
# set_real_ip_from 173.245.48.0/20;
# set_real_ip_from 103.21.244.0/22;
# ... (full list at https://www.cloudflare.com/ips/)

# If behind AWS ALB:
# set_real_ip_from 10.0.0.0/8;  # VPC CIDR
```

---

### REM-06: Add Audit Logging to Data Export Endpoints

**Fixes:** FINDING-02, PENTEST-08  
**Effort:** Low (1–2 hours)  
**Risk Reduction:** High → Resolved

**Files to modify:**
1. `app/modules/data_io/router.py` — all 3 export endpoints

**Implementation:**

Add to each export endpoint (`export_customers`, `export_vehicles`, `export_invoices`):

```python
# After generating csv_content, before returning:
user_id_str = getattr(request.state, "user_id", None)
user_uuid = uuid.UUID(user_id_str) if user_id_str else None
ip_address = request.client.host if request.client else None

await write_audit_log(
    session=db,
    org_id=org_id,
    user_id=user_uuid,
    action="data_io.customers_exported",  # or vehicles_exported, invoices_exported
    entity_type="export",
    entity_id=None,
    after_value={"ip_address": ip_address, "format": "csv"},
    ip_address=ip_address,
)
```

---

## Sprint S2 — Next Sprint (Weeks 3–4)

### REM-07: Implement Account Lockout Email Notification

**Fixes:** FINDING-15, PENTEST-09  
**Effort:** Medium (2–3 hours)  
**Risk Reduction:** High → Resolved

**Files to modify:**
1. `app/modules/auth/service.py` — `_send_permanent_lockout_email()`

**Implementation:**

Replace the TODO stub with actual email sending using the same SMTP infrastructure as `_send_email_otp()` in `mfa_service.py`:

```python
async def _send_permanent_lockout_email(email: str) -> None:
    """Send an email alert when an account is permanently locked."""
    from app.core.database import async_session_factory
    from app.modules.auth.mfa_service import _get_platform_name

    try:
        async with async_session_factory() as db:
            async with db.begin():
                platform_name = await _get_platform_name(db)
                # Use the same email provider resolution as _send_email_otp
                # Send email with:
                # - Subject: "Your {platform_name} account has been locked"
                # - Body: explains the lockout, lists recent failed IPs,
                #   provides a support contact link
    except Exception:
        logger.exception("Failed to send lockout email to %s", email)
```

---

### REM-09: Block Localhost CORS Origins in Production

**Fixes:** FINDING-10  
**Effort:** Low (30 minutes)

**Files to modify:**
1. `app/config.py`

**Implementation:**

```python
@model_validator(mode="after")
def _validate_secrets_not_default(self) -> "Settings":
    if self.environment in ("production", "staging"):
        # Existing secret checks ...

        # Reject localhost CORS origins in production
        localhost_origins = [o for o in self.cors_origins if "localhost" in o]
        if localhost_origins:
            raise ValueError(
                f"CORS origins contain localhost entries in {self.environment}: {localhost_origins}"
            )
    return self
```

---

### REM-12: Replace python-jose with PyJWT

**Fixes:** FINDING-13  
**Effort:** Medium (3–4 hours)

**Files to modify:**
1. `pyproject.toml` — replace `python-jose[cryptography]` with `PyJWT[crypto]>=2.8.0`
2. `app/modules/auth/jwt.py` — update import from `jose` to `jwt`
3. `app/middleware/auth.py` — update import
4. `app/core/firebase_token.py` — update import

**Key API differences:**
```python
# python-jose:
from jose import jwt, JWTError
payload = jwt.decode(token, secret, algorithms=["HS256"])

# PyJWT:
import jwt
from jwt.exceptions import InvalidTokenError
payload = jwt.decode(token, secret, algorithms=["HS256"])
```

---

### REM-13: SSRF Protection on Integration Endpoint URLs

**Fixes:** FINDING-18  
**Effort:** Medium (2–3 hours)

**Files to modify:**
1. `app/modules/admin/service.py` — `save_carjam_config()` and similar
2. New utility: `app/core/url_validation.py`

**Implementation:**

```python
# app/core/url_validation.py
import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / AWS metadata
    ipaddress.ip_network("127.0.0.0/8"),
]

def validate_external_url(url: str) -> None:
    """Raise ValueError if URL resolves to a private/internal IP."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must have a hostname")
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(hostname))
    except (socket.gaierror, ValueError):
        raise ValueError(f"Cannot resolve hostname: {hostname}")
    for network in _BLOCKED_RANGES:
        if ip in network:
            raise ValueError(f"URL resolves to a blocked IP range: {ip}")
```

---

### REM-17: Demo Reset Endpoint — Strict Environment Guard

**Fixes:** PENTEST-12  
**Effort:** Low (15 minutes)

**Files to modify:**
1. `app/modules/admin/router.py` — `reset_demo_account()`

```python
# Change from:
if app_settings.environment != "development":
# To allowlist:
if app_settings.environment not in ("development",):
```

---

### REM-20: Disable Swagger UI in Production

**Fixes:** FINDING-12  
**Effort:** Low (30 minutes)

**Files to modify:**
1. `app/main.py` (or wherever FastAPI app is created)

```python
from app.config import settings

app = FastAPI(
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url="/redoc" if settings.environment == "development" else None,
    openapi_url="/openapi.json" if settings.environment == "development" else None,
)
```

---

## Sprint S3 — Backlog (Weeks 5+)

### REM-10: Session-Scoped Org Context for Global Admins

**Fixes:** FINDING-03  
**Effort:** High (8–12 hours)

Implement a mechanism where global admins must explicitly select an org context before accessing tenant data. Store the selected org_id in the session and apply RLS accordingly.

---

### REM-11: Encryption Key Rotation Command

**Fixes:** FINDING-04  
**Effort:** High (6–8 hours)

Create a management command that:
1. Accepts the old key and new key
2. Iterates all `config_encrypted` and `credentials_encrypted` columns
3. Decrypts with old key, re-encrypts with new key
4. Updates rows in a transaction

---

### REM-15: Portal Token TTL and Rotation

**Fixes:** PENTEST-10  
**Effort:** Low (2–3 hours)

Add `portal_token_expires_at` column to the customers table. Set a configurable TTL (default 90 days). Add a regeneration endpoint.

---

### REM-16: Session Limit Race Condition

**Fixes:** PENTEST-11  
**Effort:** Low (1 hour)

Use a Redis `SETNX`-based lock around session creation:
```python
lock_key = f"session_lock:{user_id}"
acquired = await redis_pool.set(lock_key, "1", nx=True, ex=5)
if not acquired:
    # Another login is in progress, retry briefly
```

---

### REM-18: Password Reset Timing Side-Channel

**Fixes:** PENTEST-13  
**Effort:** Low (30 minutes)

```python
# In request_password_reset(), after the early return for non-existent emails:
import asyncio, random
await asyncio.sleep(random.uniform(0.5, 1.5))
```

---

### REM-21: SQL Column Name Whitelist

**Fixes:** FINDING-06  
**Effort:** Low (30 minutes)

```python
ALLOWED_ORG_COLUMNS = {"name", "logo_url", "primary_colour", ...}
assert all(k in ALLOWED_ORG_COLUMNS for k in fields), f"Invalid column: {set(fields) - ALLOWED_ORG_COLUMNS}"
```

---

### REM-22: JWT HS256 → RS256 Migration

**Fixes:** FINDING-05  
**Effort:** Medium (4–6 hours)

Only needed if the platform grows to microservices. Current single-backend architecture is fine with HS256 as long as `jwt_secret` is strong and not shared.

---

## Summary Timeline

| Sprint | Items | Critical/High Fixed | Effort |
|--------|-------|-------------------|--------|
| S0 (This week) | REM-01, REM-02, REM-19 | 2 Critical | ~8 hours |
| S1 (Weeks 1–2) | REM-03, REM-04, REM-05, REM-06, REM-14 | 3 High | ~10 hours |
| S2 (Weeks 3–4) | REM-07, REM-09, REM-12, REM-13, REM-17, REM-20 | 1 High | ~10 hours |
| S3 (Weeks 5+) | REM-10, REM-11, REM-15, REM-16, REM-18, REM-21, REM-22 | 0 | ~20 hours |

**Total estimated effort:** ~48 hours across 4 sprints

After S0 and S1 are complete, all Critical and High severity findings will be resolved. The remaining Medium and Low items in S2/S3 are hardening measures that reduce attack surface but don't represent actively exploitable vulnerabilities.
