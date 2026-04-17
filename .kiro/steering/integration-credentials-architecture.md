---
inclusion: auto
---

# Integration Credentials Architecture

This document defines how API keys, secrets, and credentials for third-party integrations are stored, retrieved, and used in OraInvoice. It is loaded automatically for all interactions to prevent a class of bugs where code reads credentials from environment variables instead of the database.

**Lesson learned (2026-04-17):** The Stripe Invoice Payment Flow feature shipped with `create_payment_intent()` using `settings.stripe_secret_key` (empty env var) instead of the DB-stored key. Invoices were issued without payment links because the Stripe API returned 401. This steering doc exists to prevent that class of bug from recurring.

---

## Core Rule: Credentials Live in the Database, Not in Environment Variables

All third-party integration credentials (API keys, secrets, tokens, webhook signing secrets) are:

1. **Configured by the Global Admin** via the GUI at Admin > Integrations
2. **Stored encrypted** in the `integration_configs` database table using envelope encryption
3. **Retrieved at runtime** via cached helper functions in `app/integrations/`
4. **Never read from `.env` files or `settings.*` for API calls**

The `.env` file contains only infrastructure config (database URLs, Redis URLs, ports, log levels). It does NOT contain integration API keys.

---

## Integration Config Storage

### Database Table: `integration_configs`

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `name` | VARCHAR | Integration name (`stripe`, `carjam`, `xero`, `twilio`, `smtp`) |
| `config_encrypted` | BYTEA | Envelope-encrypted JSON blob containing all credentials |
| `is_verified` | BOOLEAN | Whether the integration has been tested and verified |
| `updated_at` | TIMESTAMPTZ | Last update timestamp |
| `updated_by` | UUID | User who last updated the config |

### Encryption

- **Envelope encryption**: Data is encrypted with a DEK (data encryption key), and the DEK is encrypted with a KEK (key encryption key)
- **Encrypt**: `app/core/encryption.py` → `envelope_encrypt_str(json_string) → bytes`
- **Decrypt**: `app/core/encryption.py` → `envelope_decrypt_str(encrypted_bytes) → json_string`
- **Never store raw keys** in any database column

### Config JSON Structure (per integration)

```python
# Stripe
{
    "platform_account_id": "acct_...",
    "secret_key": "sk_test_...",        # or sk_live_...
    "publishable_key": "pk_test_...",   # or pk_live_...
    "signing_secret": "whsec_...",      # webhook signing secret
    "is_verified": True
}

# CarJam
{
    "api_key": "...",
    "is_verified": True
}

# Xero
{
    "client_id": "...",
    "client_secret": "...",
    "tenant_id": "...",
    "access_token": "...",
    "refresh_token": "...",
    "token_expires_at": "..."
}

# SMTP (email providers are in a separate table: email_providers)
# Twilio/Connexus SMS
{
    "account_sid": "...",
    "auth_token": "...",
    "from_number": "..."
}
```

---

## How to Retrieve Credentials in Code

### Stripe Keys

```python
# CORRECT — always use these functions
from app.integrations.stripe_billing import get_stripe_secret_key, get_stripe_publishable_key

secret_key = await get_stripe_secret_key()       # Loads from DB, caches for 5 min, falls back to env
publishable_key = await get_stripe_publishable_key()  # Same pattern

# WRONG — never do this for API calls
from app.config import settings
settings.stripe_secret_key      # ← EMPTY in production, only for fallback
settings.stripe_publishable_key # ← EMPTY in production, only for fallback
```

### Stripe Webhook Signing Secret

```python
# CORRECT
from app.integrations.stripe_billing import get_stripe_webhook_secret
signing_secret = await get_stripe_webhook_secret()

# WRONG
settings.stripe_webhook_secret  # ← EMPTY
```

### CarJam API Key

```python
# CORRECT
from app.integrations.carjam import get_carjam_api_key
api_key = await get_carjam_api_key()
```

### Generic Pattern for Any Integration

```python
from app.modules.admin.service import get_integration_config

config = await get_integration_config(db, name="integration_name")
# config is a dict with "fields" key containing the decrypted config
# config["fields"]["api_key"], config["fields"]["secret"], etc.
```

---

## Caching Strategy

Integration keys are cached in-memory with a 5-minute TTL to avoid hitting the database on every API call:

```python
# In app/integrations/stripe_billing.py
_cached_stripe_secret: str = ""
_cached_stripe_publishable: str = ""
_cache_ts: float = 0.0
_CACHE_TTL = 300  # 5 minutes

async def get_stripe_secret_key() -> str:
    global _cached_stripe_secret, _cache_ts
    now = time.time()
    if _cached_stripe_secret and (now - _cache_ts) < _CACHE_TTL:
        return _cached_stripe_secret
    # Load from DB...
    # Fall back to settings.stripe_secret_key (env var) as last resort
```

**When adding a new integration**, follow this same caching pattern:
1. Module-level cache variables
2. TTL-based expiry (5 minutes)
3. DB load function
4. Fallback to env var (for local dev convenience only)

---

## Admin GUI Flow

1. Global Admin navigates to **Admin > Integrations**
2. Selects the integration (Stripe, CarJam, Xero, etc.)
3. Enters credentials in the form
4. Backend calls `save_stripe_config()` / `save_carjam_config()` / etc. in `app/modules/admin/service.py`
5. Service encrypts the config JSON via `envelope_encrypt_str()` and stores in `integration_configs`
6. A "Test Connection" button verifies the credentials work before saving
7. Audit log entry is created: `admin.stripe_config_updated`, `admin.carjam_config_updated`, etc.

---

## Checklist for New Integrations

When adding a new third-party integration:

- [ ] **Store credentials in `integration_configs`** — never in `.env` or `settings`
- [ ] **Create a `save_<name>_config()` function** in `app/modules/admin/service.py`
- [ ] **Create a `get_<name>_<key>()` helper** with DB loading + caching + env fallback
- [ ] **Add a GUI page** in Admin > Integrations for configuring the credentials
- [ ] **Add a "Test Connection" endpoint** to verify credentials before saving
- [ ] **Mask secrets in API responses** — never return raw keys (use `sk_****1234` pattern)
- [ ] **Detect masked values on save** — skip update if incoming value matches mask pattern
- [ ] **Write an audit log entry** on config create/update
- [ ] **Add the integration to `get_integration_config()`** if using the generic pattern
- [ ] **Never use `settings.<integration>_key`** directly in API call auth — always use the DB helper

---

## Troubleshooting: Integration API Calls Failing

If an integration API call returns 401/403 or similar auth errors:

1. **Check the DB first**, not the `.env` file:
   ```sql
   SELECT name, config_encrypted IS NOT NULL as has_config, is_verified, updated_at
   FROM integration_configs
   WHERE name = '<integration_name>';
   ```

2. **Decrypt and inspect** (in the container):
   ```python
   python -m scripts.check_integration_config <name>
   # Or manually:
   from app.core.encryption import envelope_decrypt_str
   import json
   data = json.loads(envelope_decrypt_str(config_row.config_encrypted))
   print(data.keys())  # Don't print values!
   ```

3. **Check the cache** — if keys were recently rotated, the 5-minute cache may still hold old values. Restart the app container to clear the cache.

4. **Check the code path** — ensure the function uses `get_<name>_secret_key()` from the DB helper, NOT `settings.<name>_key` from env vars.

5. **Check app logs** for the specific error:
   ```bash
   docker compose logs app --tail 200 | Select-String "401|403|Unauthorized|Failed to create"
   ```

---

## What Goes in `.env` vs Database

| Category | Where | Examples |
|---|---|---|
| Infrastructure | `.env` file | `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `LOG_LEVEL`, `FRONTEND_BASE_URL` |
| Integration API keys | Database (`integration_configs`) | Stripe keys, CarJam API key, Xero OAuth tokens, SMS provider credentials |
| Email provider SMTP | Database (`email_providers`) | SMTP host, port, username, password |
| Feature flags | Database (`feature_flags` or org settings) | Module toggles, trade family gating |

**Rule of thumb:** If a credential is entered by a user through the GUI, it lives in the database. If it's set once during deployment and never changes, it can be in `.env`.

---

## Known Integrations and Their Key Helpers

| Integration | Config Name | Key Helper Location | GUI Page |
|---|---|---|---|
| Stripe | `stripe` | `app/integrations/stripe_billing.py` → `get_stripe_secret_key()`, `get_stripe_publishable_key()` | Admin > Integrations > Stripe |
| CarJam | `carjam` | `app/integrations/carjam.py` → `get_carjam_api_key()` | Admin > Integrations > CarJam |
| Xero | `xero` | `app/integrations/xero.py` → OAuth token management | Admin > Integrations > Xero |
| SMS (Connexus) | `twilio` | `app/integrations/sms.py` | Admin > Integrations > SMS |
| Email (SMTP) | `email_providers` table | `app/modules/admin/service.py` | Admin > Email Providers |
