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
| Stripe | `stripe` | `app/integrations/stripe_billing.py` → `get_stripe_secret_key()`, `get_stripe_publishable_key()`, `get_stripe_webhook_secret()` | Admin > Integrations > Stripe |
| CarJam | `carjam` | `app/integrations/carjam.py` → `get_carjam_api_key()` | Admin > Integrations > CarJam |
| Xero | `xero` | `app/integrations/xero.py` → OAuth token management | Admin > Integrations > Xero |
| SMS (Connexus) | `twilio` | `app/integrations/sms.py` | Admin > Integrations > SMS |
| Email (SMTP) | `email_providers` table | `app/modules/admin/service.py` | Admin > Email Providers |

---

## Stripe Connect — Full Setup Guide

Stripe Connect is used for processing invoice payments on behalf of organisations (connected accounts). The platform (OraInvoice) acts as the intermediary. This section documents every step needed to configure Stripe Connect from scratch.

### Prerequisites

- A Stripe account (platform account) with Connect enabled
- Access to the Stripe Dashboard as an admin
- A publicly accessible URL for your app (for webhooks and OAuth redirects)

### Step 1: Enable Stripe Connect

1. Go to **Stripe Dashboard** → **Settings** → **Connect**
2. Enable Connect and choose **Platform** business model
3. Note your **Platform account ID** (`acct_...`) — visible at the top of the dashboard or in Settings → Business settings

### Step 2: Configure OAuth for Connected Accounts

1. In Stripe Dashboard → **Settings** → **Connect** → **OAuth** tab
2. Enable **OAuth for Stripe Dashboard accounts**
3. Copy the **Test client ID** (starts with `ca_`) — this is the Connect client ID
4. Under **Redirects**, add your app's OAuth callback URL:
   - Dev: `https://<your-dev-domain>/settings/online-payments`
   - Prod: `https://<your-prod-domain>/settings/online-payments`

### Step 3: Get API Keys

1. Go to **Stripe Dashboard** → **Developers** → **API keys**
2. Copy the **Secret key** (`sk_test_...` for sandbox, `sk_live_...` for production)
3. Copy the **Publishable key** (`pk_test_...` for sandbox, `pk_live_...` for production)

### Step 4: Configure Webhook for Connect Events

This is critical for recording payments made on connected accounts.

1. Go to **Stripe Dashboard** → **Developers** → **Webhooks**
2. Click **Add endpoint** (or **Add destination** in newer UI)
3. Under **Events from**, select **"Connected and v2 accounts"** (NOT "Your account")
4. In the events search box, find and select:
   - `payment_intent.succeeded`
   - `checkout.session.completed`
5. Click **Continue**
6. Set the **Endpoint URL**: `https://<your-domain>/api/v1/payments/stripe/webhook`
7. Give it a name (e.g., "OraInvoice Dev" or "OraInvoice Prod")
8. Click **Create destination**
9. On the endpoint detail page, click **Reveal** under Signing secret
10. Copy the `whsec_...` value

### Step 5: Save Everything in OraInvoice

Go to **Global Admin → Integrations → Stripe** and fill in:

| Field | Value | Where to find it |
|---|---|---|
| **Secret Key** | `sk_test_...` or `sk_live_...` | Stripe Dashboard → Developers → API keys |
| **Publishable Key** | `pk_test_...` or `pk_live_...` | Stripe Dashboard → Developers → API keys |
| **Connect Client ID** | `ca_...` | Stripe Dashboard → Settings → Connect → OAuth tab |
| **Platform Account ID** | `acct_...` | Stripe Dashboard → Settings → Business settings (or top of dashboard) |
| **Webhook Endpoint URL** | `https://<domain>/api/v1/payments/stripe/webhook` | The URL you entered in Step 4 (for reference only) |
| **Webhook Signing Secret** | `whsec_...` | From Step 4.10 above |

Click **Save configuration**, then **Test connection** to verify.

### Step 6: Org Connects Their Stripe Account

Once the platform is configured, each organisation connects their own Stripe account:

1. Org admin goes to **Settings → Online Payments**
2. Clicks **Connect with Stripe**
3. Redirected to Stripe OAuth flow → authorises the connection
4. Redirected back to the app with an auth code
5. Backend exchanges the code for the connected account ID (`acct_...`)
6. Connected account ID is stored on the `organisations` table (`stripe_connect_account_id`)

### Environment-Specific Webhook URLs

| Environment | Webhook URL |
|---|---|
| Dev (local via tunnel) | `https://devin.oraflows.co.nz/api/v1/payments/stripe/webhook` |
| Production (Pi) | `https://<prod-domain>/api/v1/payments/stripe/webhook` |

Each environment needs its own webhook endpoint in Stripe with its own signing secret. The signing secret for each environment is saved in that environment's database via Global Admin.

### Troubleshooting Webhooks

If payments succeed on the frontend but the invoice doesn't update:

1. **Check Stripe Dashboard → Developers → Webhooks → your endpoint** — look for failed deliveries
2. **Check the endpoint status** — is it showing errors (4xx, 5xx)?
3. **Verify the signing secret** matches what's in Global Admin → Integrations → Stripe
4. **Check app logs**: `docker compose logs app --tail 200 | Select-String "webhook|signature"`
5. **Verify the endpoint is reachable** — try `curl -X POST https://<your-domain>/api/v1/payments/stripe/webhook` (should return 400 "Missing Stripe-Signature header")
6. **For local dev without public URL**: The confirm endpoint (`POST /api/v1/public/pay/{token}/confirm`) acts as a fallback — the frontend calls it after payment success to record the payment synchronously

### Payment Flow Summary

```
Customer pays → stripe.confirmCardPayment() → Stripe processes payment
                                                    ↓
                                            Two paths to record:
                                                    ↓
                    ┌───────────────────────────────────────────────────┐
                    │                                                   │
            Path A (async):                                    Path B (sync):
            Stripe sends webhook                        Frontend calls confirm
            payment_intent.succeeded                    POST /public/pay/{token}/confirm
            → Backend records payment                   → Backend verifies PI with Stripe
            → Updates invoice status                    → Records payment (idempotent)
            → Sends receipt email                       → Updates invoice status
                    │                                   → Sends receipt email
                    └───────────────────────────────────────────────────┘
                                    Both paths are idempotent
```
