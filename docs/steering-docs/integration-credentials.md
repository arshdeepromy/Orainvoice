# Integration Credentials — Secure Storage Architecture

This document defines how API keys, secrets, and credentials for third-party integrations should be stored, retrieved, and used in a multi-tenant SaaS application. It prevents the class of bugs where code reads credentials from environment variables instead of the database.

## Why This Matters

**Lesson learned:** A payment integration shipped with `create_payment_intent()` reading from an environment variable (`settings.stripe_secret_key`) which was empty in production. The actual key was stored in the database (configured via admin GUI). Invoices were issued without payment links because the API returned 401. This went undetected for days because the code path "worked" in development where the env var was set.

**Core principle:** In a multi-tenant SaaS, integration credentials are configured per-deployment (or per-tenant) through an admin GUI. They live in the database, not in environment variables.

---

## Core Rule: Credentials Live in the Database

All third-party integration credentials (API keys, secrets, tokens, webhook signing secrets) must be:

1. **Configured by an admin** via a GUI (Admin > Integrations)
2. **Stored encrypted** in a dedicated database table using envelope encryption
3. **Retrieved at runtime** via cached helper functions
4. **Never read from `.env` files or config objects for API calls**

The `.env` file contains only infrastructure config (database URLs, Redis URLs, ports, log levels). It does NOT contain integration API keys.

---

## Architecture

### Database Table: `integration_configs`

```sql
CREATE TABLE integration_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,  -- e.g., 'stripe', 'twilio', 'sendgrid'
    config_encrypted BYTEA NOT NULL,     -- envelope-encrypted JSON blob
    is_verified BOOLEAN DEFAULT FALSE,   -- tested and confirmed working
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    updated_by UUID REFERENCES users(id)
);
```

### Envelope Encryption

Each credential set is encrypted using envelope encryption:

1. Generate a random 256-bit Data Encryption Key (DEK)
2. Encrypt the credential JSON with the DEK using AES-256-GCM
3. Encrypt the DEK with a master Key Encryption Key (KEK) using AES-256-GCM
4. Store as: `[DEK_length][encrypted_DEK][encrypted_payload]`

```python
# Encrypt
from app.core.encryption import envelope_encrypt_str
encrypted = envelope_encrypt_str(json.dumps(credentials))

# Decrypt
from app.core.encryption import envelope_decrypt_str
credentials = json.loads(envelope_decrypt_str(encrypted_bytes))
```

**Key rotation:** To rotate the master key, only the DEKs need re-encryption — not every secret.

### Config JSON Structure Examples

```python
# Payment processor (e.g., Stripe)
{
    "secret_key": "sk_live_...",
    "publishable_key": "pk_live_...",
    "webhook_signing_secret": "whsec_...",
    "platform_account_id": "acct_...",
    "is_verified": True
}

# SMS provider (e.g., Twilio)
{
    "account_sid": "AC...",
    "auth_token": "...",
    "from_number": "+1234567890"
}

# OAuth integration (e.g., accounting software)
{
    "client_id": "...",
    "client_secret": "...",
    "access_token": "...",
    "refresh_token": "...",
    "token_expires_at": "2026-01-15T10:00:00Z"
}
```

---

## How to Retrieve Credentials in Code

### The Correct Pattern

```python
# CORRECT — always use the DB helper with caching
from app.integrations.payments import get_payment_secret_key

secret_key = await get_payment_secret_key()  # Loads from DB, caches for 5 min

# WRONG — never do this for API calls
from app.config import settings
settings.stripe_secret_key  # ← May be EMPTY in production
```

### Caching Strategy

Integration keys are cached in-memory with a TTL to avoid hitting the database on every API call:

```python
import time

_cached_secret: str = ""
_cache_ts: float = 0.0
_CACHE_TTL = 300  # 5 minutes

async def get_payment_secret_key() -> str:
    global _cached_secret, _cache_ts
    now = time.time()
    if _cached_secret and (now - _cache_ts) < _CACHE_TTL:
        return _cached_secret
    
    # Load from database
    config = await get_integration_config(name="stripe")
    _cached_secret = config["fields"]["secret_key"]
    _cache_ts = now
    return _cached_secret
```

**When adding a new integration**, follow this caching pattern:
1. Module-level cache variables
2. TTL-based expiry (5 minutes is a good default)
3. DB load function
4. Fallback to env var (for local dev convenience only)

---

## Admin GUI Flow

1. Admin navigates to **Admin > Integrations**
2. Selects the integration (Stripe, Twilio, SendGrid, etc.)
3. Enters credentials in the form
4. Backend encrypts the config JSON and stores in `integration_configs`
5. A "Test Connection" button verifies the credentials work before saving
6. Audit log entry is created

---

## What Goes in `.env` vs Database

| Category | Where | Examples |
|---|---|---|
| Infrastructure | `.env` file | `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `LOG_LEVEL` |
| Integration API keys | Database | Payment keys, SMS credentials, OAuth tokens |
| Email provider SMTP | Database | SMTP host, port, username, password |
| Feature flags | Database | Module toggles, plan features |

**Rule of thumb:** If a credential is entered by a user through the GUI, it lives in the database. If it's set once during deployment and never changes, it can be in `.env`.

---

## Security Requirements

### Masking in API Responses

Never return raw keys in API responses. Use a masking pattern:

```python
def mask_secret(value: str) -> str:
    if not value or len(value) < 8:
        return "****"
    return value[:4] + "****" + value[-4:]

# Returns: "sk_t****1234"
```

### Detecting Masked Values on Save

When the admin saves a form, the masked value might be sent back. Skip the update if the incoming value matches the mask pattern:

```python
def is_masked(value: str) -> bool:
    return "****" in value

# In the save handler
if not is_masked(incoming_secret_key):
    config["secret_key"] = incoming_secret_key
# else: keep the existing value unchanged
```

### Audit Logging

Every credential change must be audit-logged:
- Who changed it (user ID)
- When (timestamp)
- What integration was updated
- Never log the actual credential values

---

## Troubleshooting: Integration API Calls Failing

If an integration API call returns 401/403:

1. **Check the DB first**, not the `.env` file
2. **Verify the config exists** and `is_verified = true`
3. **Check the cache** — if keys were recently rotated, the TTL cache may hold old values. Restart the app to clear.
4. **Check the code path** — ensure it uses the DB helper, NOT `settings.<key>` from env vars
5. **Check app logs** for the specific error message

---

## Checklist for New Integrations

When adding a new third-party integration:

- [ ] Store credentials in the `integration_configs` table — never in `.env` or settings
- [ ] Create a `save_<name>_config()` function that encrypts and stores
- [ ] Create a `get_<name>_<key>()` helper with DB loading + caching + env fallback
- [ ] Add a GUI page in Admin > Integrations for configuring the credentials
- [ ] Add a "Test Connection" endpoint to verify credentials before saving
- [ ] Mask secrets in API responses — never return raw keys
- [ ] Detect masked values on save — skip update if value matches mask pattern
- [ ] Write an audit log entry on config create/update
- [ ] Never use `settings.<integration>_key` directly in API call auth
- [ ] Document the expected config JSON structure
- [ ] Handle the case where no config exists (graceful error, not crash)
