---
inclusion: auto
---

# Security Hardening Checklist

Rules derived from real security bugs in this codebase (and applicable to any project). Each rule references the issue or pattern that motivated it. Cross-reference `#[[file:docs/ISSUE_TRACKER.md]]` for full details.

---

## 1. Authentication & Middleware Safety

**Every middleware MUST have a public-endpoint bypass.**
Middleware that assumes all requests are authenticated will block login, signup, password-reset, and health-check endpoints. Maintain an explicit allowlist of unauthenticated paths and check it before accessing `request.state.user`. *(ISSUE-097)*

**Every middleware MUST handle all role types — including roles with no org context.**
Platform-level roles like `global_admin` have no `org_id`. Any middleware or path guard that reads `org_id` from the token/session must handle `None` gracefully instead of raising 403/500. *(ISSUE-003, ISSUE-098)*

**Never assume `request.state` has user context — always check before accessing.**
If middleware runs before auth, or the request is unauthenticated, `request.state.user` won't exist. Guard with `hasattr(request.state, 'user')` or equivalent. *(ISSUE-097)*

**Stale headers from localStorage persist across sessions.**
After logout, `Authorization` and `X-Branch-Id` headers may remain in localStorage. Middleware must tolerate expired/invalid tokens without crashing — return 401, don't raise unhandled exceptions. Clear all auth-related localStorage keys on logout. *(ISSUE-001)*

---

## 2. Credential & Secret Handling

**Integration API keys are stored in the database, NOT in environment variables.**
All third-party credentials (Stripe, CarJam, Xero, SMS, etc.) are configured via the Global Admin GUI and stored encrypted in the `integration_configs` table. Code must use the DB-backed helper functions (e.g., `get_stripe_secret_key()`) to retrieve them — never `settings.stripe_secret_key` or similar env-based config. See #[[file:.kiro/steering/integration-credentials-architecture.md]] for the full pattern.

**Never store masked credential values back to the database.**
When a UI re-saves a form containing masked secrets (e.g., `sk_live_****`), the backend must detect the mask pattern and skip the update for that field. Otherwise the real credential is silently replaced with the mask string. *(ISSUE-062)*

```python
# Pattern: skip update if value matches mask
MASK_PATTERN = re.compile(r'^\*+$|^.{0,4}\*{4,}$')
if MASK_PATTERN.match(incoming_value):
    # Keep existing value — do not overwrite
    pass
```

**Use envelope encryption for stored credentials.**
Encrypt secrets at rest with a data-encryption key (DEK), and encrypt the DEK with a key-encryption key (KEK). Never store raw API keys, SMTP passwords, or webhook secrets in plaintext columns.

**Never return raw secrets in API responses.**
Always mask secrets before serialization. Return `sk_live_****1234` (last 4 chars), never the full value.

---

## 3. SQL Injection Prevention

**PostgreSQL `SET` / `SET LOCAL` commands do not support parameterized queries.**
Libraries like asyncpg will silently fail or error when you try `await conn.execute("SET LOCAL app.user_id = $1", user_id)`. You must validate the value and interpolate directly. *(ISSUE-007)*

```python
# WRONG — asyncpg doesn't support params in SET
await conn.execute("SET LOCAL app.user_id = $1", user_id)

# RIGHT — validate UUID format, then interpolate
import re
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
if not UUID_RE.match(str(user_id)):
    raise ValueError("Invalid UUID")
await conn.execute(f"SET LOCAL app.user_id = '{user_id}'")
```

**For all other queries, always use bound parameters.**
Use SQLAlchemy `text()` with `:param` syntax or ORM query builders. Never f-string user input into SELECT/INSERT/UPDATE/DELETE.

---

## 4. RBAC & Access Control

**When adding a new role, audit ALL middleware, path checks, and role lists.**
Every `require_role(...)` call, every `if user.role in [...]` check, every frontend route guard, and every CHECK constraint in the database must be updated. Missing one causes silent 403s for the new role. *(ISSUE-003, ISSUE-098)*

**Test every new role against these scenarios:**
1. Login and token generation
2. Public/unauthenticated endpoints (must still work)
3. Admin-only endpoints (must be blocked or allowed per design)
4. Org-scoped endpoints (must handle missing `org_id` for platform roles)
5. Middleware chain (every middleware must pass the role through)

**Platform-level roles have no `org_id` — every org-scoped check must handle this.**
```python
# WRONG — crashes for global_admin
org_id = current_user.org_id  # None for platform roles
query = select(Thing).where(Thing.org_id == org_id)

# RIGHT
if current_user.org_id:
    query = query.where(Thing.org_id == current_user.org_id)
# else: platform admin sees all, or return empty, per business rules
```

---

## 5. Session & Token Security

**Refresh token rotation must be atomic.**
If two tabs fire a refresh simultaneously, only one should succeed. Use a mutex (Redis lock or DB advisory lock) around the rotate-and-invalidate operation to prevent race conditions where both get new tokens but one is immediately invalid. *(Token refresh race pattern)*

**Account lockout counters must reset on successful login.**
If you increment a `failed_attempts` counter on bad password, reset it to 0 on successful auth. Otherwise users get locked out after N cumulative failures across days/weeks. *(Account lockout pattern)*

**MFA challenge sessions should expire.**
Store MFA challenge state in Redis with a TTL (e.g., 5 minutes), not in the database. This prevents stale challenges from being replayed hours later and avoids DB cleanup burden.

**Clear all auth state on logout.**
Remove from localStorage: access token, refresh token, branch selection, user preferences, any cached org context. Stale state causes ghost sessions and confusing 403s on next login. *(ISSUE-001)*

---

## 6. Rate Limiting

**Development rate limits should be 5× production limits.**
React StrictMode doubles all useEffect calls. Combined with hot-reload and rapid testing, production-level rate limits will block developers constantly. Use environment-based config. *(ISSUE-016)*

**Rate limit auth endpoints by both user identifier AND IP.**
Login, signup, password-reset, and MFA verify should be rate-limited per-IP to prevent brute force, and per-account to prevent credential stuffing across distributed IPs.

**Always return `Retry-After` header on 429 responses.**
Clients (and developers debugging) need to know when they can retry. Include the header in seconds.

```python
# FastAPI example
from fastapi.responses import JSONResponse
return JSONResponse(
    status_code=429,
    content={"detail": "Rate limit exceeded"},
    headers={"Retry-After": str(retry_after_seconds)}
)
```

---

## 7. CORS Configuration

**Allowlist origins explicitly — never use `*` in production.**
A wildcard CORS origin allows any site to make credentialed requests to your API. Maintain an explicit list of allowed origins from environment config. *(ISSUE-025)*

**Include the frontend dev server origin in development.**
If the frontend runs on `http://localhost:5173` (Vite default), that origin must be in the CORS allowlist during development or every request will fail silently.

---

## Quick Audit Checklist for New Features

Before shipping any new endpoint or middleware:

- [ ] Public endpoints are excluded from auth middleware
- [ ] All roles (including platform roles with no org_id) are tested
- [ ] Secrets are masked in responses and not overwritten by mask values on save
- [ ] Integration API keys are loaded from DB helpers, NOT from `settings.*` env vars
- [ ] SQL queries use bound parameters (except SET LOCAL with validated UUIDs)
- [ ] Rate limits are configured and return Retry-After
- [ ] CORS allows the frontend origin
- [ ] Logout clears all client-side auth state
- [ ] Token refresh is atomic (no race conditions)
