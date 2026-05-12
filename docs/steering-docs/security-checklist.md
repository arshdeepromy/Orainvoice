# Security Checklist — Patterns for SaaS Applications

This document provides a comprehensive security checklist and implementation patterns for multi-tenant SaaS applications. It covers encryption, transport security, authentication, authorization, and common security pitfalls.

## Why This Matters

Security breaches in SaaS applications can expose data from ALL tenants simultaneously. A single vulnerability in a multi-tenant system has amplified impact compared to single-tenant applications. The patterns here represent defense-in-depth — multiple layers of protection so that a failure in one layer doesn't compromise the system.

---

## 1. Data Encryption at Rest

### Full-Disk Encryption

The database data directory must reside on an encrypted volume:

- **Cloud:** Use provider-managed encryption (AWS EBS encryption, Azure Disk Encryption)
- **On-premise:** Use LUKS/dm-crypt with AES-256-XTS
- **Docker:** Ensure the host volume backing PostgreSQL data is on an encrypted filesystem

### Application-Level Envelope Encryption

Sensitive fields (API keys, MFA secrets, webhook signing keys) use envelope encryption:

```python
# Architecture:
# 1. Generate random 256-bit Data Encryption Key (DEK)
# 2. Encrypt plaintext with DEK using AES-256-GCM
# 3. Encrypt DEK with master Key Encryption Key (KEK) using AES-256-GCM
# 4. Store: [DEK_length][encrypted_DEK][encrypted_payload]

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os

def envelope_encrypt(plaintext: bytes, master_key: bytes) -> bytes:
    # Generate DEK
    dek = os.urandom(32)  # 256-bit
    
    # Encrypt data with DEK
    dek_cipher = AESGCM(dek)
    data_nonce = os.urandom(12)
    encrypted_data = dek_cipher.encrypt(data_nonce, plaintext, None)
    
    # Encrypt DEK with master key
    kek_cipher = AESGCM(master_key)
    kek_nonce = os.urandom(12)
    encrypted_dek = kek_cipher.encrypt(kek_nonce, dek, None)
    
    # Pack: [dek_len(2)][kek_nonce(12)][encrypted_dek][data_nonce(12)][encrypted_data]
    return (len(encrypted_dek).to_bytes(2, 'big') + 
            kek_nonce + encrypted_dek + 
            data_nonce + encrypted_data)
```

**Key rotation:** Only re-encrypt the DEKs with the new master key — not every secret.

### Backup Encryption

All database backups must be encrypted at rest using AES-256:

```bash
# Encrypted backup
pg_dump -U postgres myapp | gpg --symmetric --cipher-algo AES256 > backup.sql.gpg

# Or use pgBackRest with built-in encryption
# repo1-cipher-type=aes-256-cbc
```

---

## 2. Transport Security (TLS)

### Application Layer

All client connections must use TLS 1.2+ (prefer 1.3):

```nginx
# Nginx configuration
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;
ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256;
```

### Database Connections

```ini
# postgresql.conf
ssl = on
ssl_min_protocol_version = 'TLSv1.2'
ssl_cert_file = '/path/to/server.crt'
ssl_key_file = '/path/to/server.key'
```

Application connection strings should use `sslmode=require` in production.

### Redis Connections

For production Redis with sensitive data:

```ini
tls-port 6380
tls-cert-file /path/to/redis.crt
tls-key-file /path/to/redis.key
tls-protocols "TLSv1.2 TLSv1.3"
```

---

## 3. Security Headers

All API responses should include these headers:

| Header | Value | Purpose |
|--------|-------|---------|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Forces HTTPS |
| `X-Frame-Options` | `DENY` | Prevents clickjacking |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type sniffing |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Controls referrer leakage |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'` | Prevents XSS |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Restricts browser features |

```python
# FastAPI middleware example
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response
```

---

## 4. Authentication

### JWT Best Practices

```python
# Token configuration
ACCESS_TOKEN_EXPIRE = 15  # minutes (short-lived)
REFRESH_TOKEN_EXPIRE = 7  # days (longer-lived, stored securely)

# Claims to include
{
    "sub": user_id,        # Subject (user identifier)
    "org_id": org_id,      # Tenant identifier
    "role": role,          # User role
    "exp": expiry,         # Expiration timestamp
    "iat": issued_at,      # Issued at timestamp
    "jti": unique_id,      # JWT ID (for revocation)
}
```

### Token Storage (Frontend)

- **Access token:** In-memory only (JavaScript variable). Never localStorage.
- **Refresh token:** HttpOnly, Secure, SameSite=Strict cookie. Or localStorage if cookies aren't feasible (mobile apps).

### MFA (Multi-Factor Authentication)

Support multiple MFA methods for different user needs:
- TOTP (authenticator apps) — most common
- SMS codes — fallback for users without authenticator apps
- Passkeys/WebAuthn — strongest, phishing-resistant
- Backup codes — recovery when primary method unavailable

---

## 5. Authorization

### Row-Level Security (RLS)

The strongest multi-tenant isolation — enforced at the database level:

```sql
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON orders
    USING (org_id = current_setting('app.current_org_id')::uuid);
```

**Why RLS matters:** Even if application code has a bug that forgets a WHERE clause, the database itself prevents cross-tenant data access.

### Role-Based Access Control (RBAC)

```python
# Dependency injection pattern
def require_role(*allowed_roles):
    async def dependency(user: User = Depends(get_current_user)):
        if user.role not in allowed_roles:
            raise HTTPException(403, "Insufficient permissions")
        return user
    return Depends(dependency)

# Usage
@router.delete("/users/{id}", dependencies=[require_role("admin", "owner")])
async def delete_user(id: UUID): ...
```

---

## 6. Input Validation

### API Input

```python
from pydantic import BaseModel, Field, validator

class CreateOrderRequest(BaseModel):
    customer_id: UUID
    amount: Decimal = Field(gt=0, le=1_000_000)  # Bounded
    notes: str = Field(max_length=5000)           # Length-limited
    
    @validator('notes')
    def sanitize_notes(cls, v):
        # Strip potential XSS if notes are rendered as HTML
        return bleach.clean(v) if v else v
```

### SQL Injection Prevention

- Always use parameterized queries (ORM handles this)
- Exception: `SET LOCAL` commands require literal values — validate format strictly

```python
# Safe: parameterized query (ORM)
stmt = select(Order).where(Order.id == order_id)

# Safe: validated literal for SET LOCAL
validated_uuid = str(uuid.UUID(org_id))  # Raises if not valid UUID
await session.execute(text(f"SET LOCAL app.current_org_id = '{validated_uuid}'"))

# UNSAFE: string interpolation
await session.execute(text(f"SELECT * FROM orders WHERE id = '{user_input}'"))  # ← SQL injection!
```

---

## 7. Rate Limiting

```python
# Per-user rate limiting
RATE_LIMITS = {
    "default": "200/minute",      # Standard API calls
    "auth": "10/minute",          # Login attempts (prevent brute force)
    "password_reset": "3/hour",   # Password reset requests
    "file_upload": "20/minute",   # File uploads
}
```

### Implementation

```python
import time
from collections import defaultdict

class RateLimiter:
    def __init__(self):
        self.requests = defaultdict(list)
    
    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        # Remove expired entries
        self.requests[key] = [t for t in self.requests[key] if now - t < window_seconds]
        if len(self.requests[key]) >= limit:
            return False
        self.requests[key].append(now)
        return True
```

---

## 8. CSRF Protection

State-changing requests (POST/PUT/PATCH/DELETE) with cookie-based auth require CSRF protection:

```python
# Double-submit cookie pattern
@app.middleware("http")
async def csrf_protection(request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if uses_cookie_auth(request):
            csrf_header = request.headers.get("X-CSRF-Token")
            csrf_cookie = request.cookies.get("csrf_token")
            if not csrf_header or csrf_header != csrf_cookie:
                raise HTTPException(403, "CSRF token mismatch")
    return await call_next(request)
```

**Bearer token requests are exempt** — tokens cannot be sent automatically by browser forms.

---

## 9. Secrets Management

### What Goes Where

| Category | Storage | Examples |
|---|---|---|
| Infrastructure secrets | `.env` file (never committed) | `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET` |
| Integration credentials | Database (encrypted) | Stripe keys, SMS tokens, OAuth secrets |
| User secrets | Database (hashed/encrypted) | Passwords (hashed), MFA seeds (encrypted) |

### Password Hashing

```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
```

---

## 10. Logging and Audit

### What to Log

- Authentication events (login, logout, failed attempts, MFA)
- Authorization failures (403 responses)
- Data access patterns (who accessed what, when)
- Configuration changes (settings, integrations, user management)
- Security events (password changes, MFA enrollment, API key rotation)

### What NOT to Log

- Passwords (even failed ones)
- Full credit card numbers
- API keys or secrets
- Personal health information
- Session tokens

```python
# Good audit log entry
audit_log.info("user.login", extra={
    "user_id": user.id,
    "ip": request.client.host,
    "user_agent": request.headers.get("user-agent"),
    "mfa_used": True,
})

# Bad — leaks sensitive data
audit_log.info(f"Login attempt with password: {password}")  # ← NEVER
```

---

## Security Checklist

### Infrastructure
- [ ] Database on encrypted volume (AES-256)
- [ ] TLS 1.2+ enforced on all connections (app, database, Redis)
- [ ] Security headers set on all responses
- [ ] CORS configured with explicit allowed origins (not `*`)
- [ ] Rate limiting enabled on auth endpoints
- [ ] Secrets not committed to version control
- [ ] `.env` files have restricted permissions (`chmod 600`)

### Authentication & Authorization
- [ ] JWT access tokens are short-lived (15 min)
- [ ] Refresh tokens stored securely (HttpOnly cookie or encrypted storage)
- [ ] MFA available and enforced for admin roles
- [ ] Password hashing uses bcrypt/argon2 (not MD5/SHA)
- [ ] Account lockout after N failed login attempts
- [ ] RLS enabled on all tenant-scoped tables
- [ ] Role checks on every protected endpoint

### Application
- [ ] All user input validated with strict schemas (Pydantic, Zod, etc.)
- [ ] No SQL string interpolation (use parameterized queries)
- [ ] File uploads validated (type, size, content)
- [ ] CSRF protection on cookie-authenticated state-changing requests
- [ ] API keys masked in responses (never return full keys)
- [ ] Error messages don't leak internal details to users
- [ ] Sensitive data encrypted at the application level (envelope encryption)

### Monitoring
- [ ] Authentication events logged (success and failure)
- [ ] Authorization failures logged
- [ ] Configuration changes audit-logged
- [ ] Alerts on unusual patterns (brute force, data exfiltration)
- [ ] No secrets in log output
