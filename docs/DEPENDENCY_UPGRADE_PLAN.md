# Dependency Upgrade Remediation Plan

**Created:** 2026-04-11
**Status:** Planning
**Goal:** Update all outdated dependencies to latest versions safely, with zero impact on existing customer data, logins, MFA, passkeys, API keys, and third-party integrations.

---

## Critical Context

### What Must NOT Break
- User passwords (bcrypt hashes in `users.password_hash`)
- MFA enrolments (TOTP secrets in `user_mfa_methods.secret_encrypted`, SMS/email OTP via Redis)
- Passkey credentials (WebAuthn public keys in `user_passkey_credentials`)
- Backup codes (bcrypt hashes in `user_backup_codes.code_hash`)
- JWT sessions (HS256/RS256 tokens, refresh token rotation)
- Encrypted API keys in `integration_configs.config_encrypted` (Stripe, Carjam, SMTP, Twilio)
- Encrypted SMS provider credentials in `sms_verification_providers.credentials_encrypted`
- Encrypted email provider credentials in `email_providers.credentials_encrypted`
- Xero OAuth tokens stored in DB
- Connexus SMS token cache and background refresher
- Firebase ID token verification (local, uses Google public keys)

### Encryption Architecture (No Changes Needed)
Our encryption uses `cryptography` library's `AESGCM` (AES-256-GCM) with envelope encryption. The `cryptography` upgrade from 46.0.4 → 46.0.7 is a **patch release** — same major version, same API, same cipher implementations. Encrypted data format is unchanged. No re-encryption needed.

### Password Hashing (No Changes Needed)
Passwords use `bcrypt` directly (not passlib). bcrypt hash format (`$2b$...`) is stable across versions. Existing hashes will continue to verify correctly.

---

## Phase 1: Security Patches (Zero Risk)

**Timeline:** Immediate
**Risk:** None — patch releases only, no API changes
**Rollback:** Revert pip install

| Package | Current | Target | Why |
|---|---|---|---|
| cryptography | 46.0.4 | 46.0.7 | Security patches for TLS/X.509 |
| certifi | 2025.11.12 | 2026.2.25 | Updated CA certificate bundle |
| pydantic | 2.12.3 | 2.12.5 | Bug fixes |
| pydantic-settings | 2.11.0 | 2.13.1 | Bug fixes |
| SQLAlchemy | 2.0.42 | 2.0.49 | Bug fixes, async improvements |
| hypothesis | 6.151.6 | 6.151.12 | Test-only, patch fixes |
| webauthn | 2.7.0 | 2.7.1 | Passkey library patch |

### Pre-upgrade Checks
- [ ] Backup the production database
- [ ] Export current `integration_configs` encrypted blobs (for rollback verification)

### Playwright E2E Tests Required
```
1. Login with email/password → verify dashboard loads
2. Login → MFA TOTP verification → verify access
3. Login → MFA SMS verification → verify access
4. Login with passkey → verify access
5. Navigate to Settings → Integrations → verify Stripe keys show as "configured"
6. Navigate to Settings → Integrations → verify Xero shows as "connected"
7. Navigate to Settings → SMS Providers → verify Connexus shows as "active"
8. Navigate to Settings → Email Providers → verify active provider shows credentials set
9. Create invoice → verify it saves and syncs to Xero
10. Process payment → verify it records and syncs
11. Issue refund → verify credit note created in Xero
```

### Upgrade Commands
```bash
pip install cryptography==46.0.7 certifi==2026.2.25 pydantic==2.12.5 pydantic-settings==2.13.1 SQLAlchemy==2.0.49 hypothesis==6.151.12 webauthn==2.7.1
```

### Frontend (safe patches)
```bash
cd frontend && npm install @headlessui/react@2.2.10 @types/node@25.6.0 axios@1.15.0 fast-check@4.6.0 postcss@8.5.9
```

---

## Phase 2: Safe Minor Upgrades (Low Risk)

**Timeline:** Week 1
**Risk:** Low — minor version bumps, backward compatible APIs

| Package | Current | Target | Impact Assessment |
|---|---|---|---|
| fastapi | 0.120.0 | 0.135.3 | Minor releases. Check: response model changes, middleware ordering. Our code uses standard patterns (Depends, APIRouter). Low risk. |
| uvicorn | 0.38.0 | 0.44.0 | ASGI server minor bumps. No code changes needed. |
| alembic | 1.13.0 | 1.18.4 | Migration tool. Our env.py is standard async pattern. Low risk. |
| PyJWT | 2.10.1 | 2.12.1 | JWT library. We use `jwt.encode()`, `jwt.decode()`, `jwt.get_unverified_header()`. Check: algorithm parameter handling, claim validation changes. **Test JWT creation and verification thoroughly.** |
| pillow | 12.0.0 | 12.2.0 | Image processing minor. Used for PDF/receipt generation. Low risk. |
| reportlab | 4.4.3 | 4.4.10 | PDF generation patches. Low risk. |
| requests | 2.32.4 | 2.33.1 | HTTP client minor. Low risk. |
| httpx | (check current) | latest minor | Used by Xero, Connexus, Carjam, Firebase token fetch. **Test all outbound API calls.** |

### Pre-upgrade: Global Settings Backup Script
Before upgrading anything that touches encryption or auth, run this backup:

```python
# scripts/backup_encrypted_settings.py
"""
Export all encrypted settings to a JSON file for rollback verification.
Does NOT export decrypted values — only metadata to verify they can still be decrypted after upgrade.
"""
import asyncio, json
from app.core.database import async_session_factory
from app.core.encryption import envelope_decrypt_str
from sqlalchemy import select

async def verify_all_encrypted_fields():
    """Attempt to decrypt every encrypted field and log success/failure."""
    from app.modules.admin.models import IntegrationConfig, SmsVerificationProvider, EmailProvider
    
    results = {"integration_configs": [], "sms_providers": [], "email_providers": []}
    
    async with async_session_factory() as session:
        # Integration configs
        rows = (await session.execute(select(IntegrationConfig))).scalars().all()
        for row in rows:
            try:
                envelope_decrypt_str(row.config_encrypted)
                results["integration_configs"].append({"name": row.name, "status": "OK"})
            except Exception as e:
                results["integration_configs"].append({"name": row.name, "status": f"FAIL: {e}"})
        
        # SMS providers
        rows = (await session.execute(select(SmsVerificationProvider).where(SmsVerificationProvider.credentials_encrypted.isnot(None)))).scalars().all()
        for row in rows:
            try:
                envelope_decrypt_str(row.credentials_encrypted)
                results["sms_providers"].append({"key": row.provider_key, "status": "OK"})
            except Exception as e:
                results["sms_providers"].append({"key": row.provider_key, "status": f"FAIL: {e}"})
        
        # Email providers
        rows = (await session.execute(select(EmailProvider).where(EmailProvider.credentials_encrypted.isnot(None)))).scalars().all()
        for row in rows:
            try:
                envelope_decrypt_str(row.credentials_encrypted)
                results["email_providers"].append({"key": row.provider_key, "status": "OK"})
            except Exception as e:
                results["email_providers"].append({"key": row.provider_key, "status": f"FAIL: {e}"})
    
    print(json.dumps(results, indent=2))
    failed = sum(1 for cat in results.values() for item in cat if "FAIL" in item["status"])
    print(f"\n{'ALL OK' if failed == 0 else f'{failed} FAILURES'}")

asyncio.run(verify_all_encrypted_fields())
```

### Playwright E2E Tests Required
All Phase 1 tests PLUS:
```
12. Full signup flow → verify new org created, user can login
13. Password reset flow → verify email sent, new password works
14. Create customer → create invoice → issue invoice → record payment → full cycle
15. Xero sync → verify invoice appears in Xero
16. Stripe payment method → verify card saved and charges work
17. SMS send → verify Connexus delivers (or mock endpoint responds)
18. Admin → Global Settings → verify all integration statuses show correctly
19. Admin → Audit Log → verify entries appear
20. Refresh token rotation → login, wait, verify token refresh works
```

---

## Phase 3: Third-Party Integration Majors (Medium Risk)

**Timeline:** Week 2-3
**Risk:** Medium — major version bumps on integration SDKs

### 3A: Stripe 14.3.0 → 15.0.1

**Migration Guide:** https://github.com/stripe/stripe-python/blob/master/CHANGELOG.md

**What to check:**
- [ ] `stripe.PaymentIntent.create()` — parameter changes?
- [ ] `stripe.Customer.create()` — parameter changes?
- [ ] `stripe.Subscription.create()` — parameter changes?
- [ ] `stripe.billing_portal.Session.create()` — still exists?
- [ ] Webhook event parsing — `stripe.Webhook.construct_event()` signature changes?
- [ ] Our code in `app/integrations/stripe_billing.py` uses `stripe.api_key` global — still supported?

**Backward compatibility for outbound:** Stripe API versioning is header-based. Our SDK calls go to Stripe's API which is versioned. The SDK upgrade changes the client library, not the API version we call. Stripe maintains backward compatibility on their API.

**Test plan:**
```
- Create a test Stripe customer
- Create a PaymentIntent with test card
- Verify webhook delivery and parsing
- Verify billing portal session creation
- Verify subscription creation/cancellation
```

### 3B: Redis 6.3.0 → 7.4.0

**Migration Guide:** https://github.com/redis/redis-py/blob/master/CHANGES

**What to check:**
- [ ] `redis.asyncio.from_url()` — still same API?
- [ ] `redis.asyncio.Redis` — method signatures for `get`, `set`, `setex`, `incr`, `expire`, `delete`
- [ ] Connection pool parameters — `max_connections`, `socket_timeout`, `retry_on_timeout`
- [ ] `decode_responses=True` — still supported?

**Impact on our code:**
- `app/core/redis.py` — connection pool creation
- `app/modules/auth/mfa_service.py` — OTP storage, attempt counters
- Rate limiting middleware
- Connexus token cache

**Critical:** Redis stores MFA OTP codes. If the upgrade breaks Redis connectivity, users can't complete MFA. Test on standby first.

### 3C: Twilio 8.12.0 → 9.10.4

**Migration Guide:** https://github.com/twilio/twilio-python/blob/main/UPGRADE.md

**What to check:**
- [ ] `Client(account_sid, auth_token)` constructor — still same?
- [ ] `client.messages.create()` — parameter changes?
- [ ] We may not actively use Twilio (Connexus is primary SMS). Check if Twilio is actually called anywhere.

**Note:** If Twilio is only configured but not actively used (Connexus is the active SMS provider), this upgrade is lower priority.

### 3D: Firebase 11.10.0 → 12.12.0 (Frontend)

**Migration Guide:** https://firebase.google.com/docs/web/modular-upgrade

**What to check:**
- [ ] `firebase/auth` — `signInWithEmailAndPassword`, `signInWithPopup`, `onAuthStateChanged`
- [ ] `firebase/app` — `initializeApp` configuration
- [ ] Our backend verifies Firebase tokens locally (no SDK dependency) — backend is NOT affected
- [ ] Frontend `AuthContext.tsx` uses Firebase auth — check all auth method calls

**Backward compatibility:** Firebase maintains backward compatibility for auth tokens. Existing user sessions will continue to work. The token format doesn't change between SDK versions.

### 3E: Stripe Frontend @stripe/react-stripe-js 5→6, @stripe/stripe-js 8→9

**What to check:**
- [ ] `Elements` component — prop changes?
- [ ] `CardElement` — still exists or replaced by `PaymentElement`?
- [ ] `useStripe()`, `useElements()` hooks — API changes?
- [ ] `loadStripe()` — initialization changes?
- [ ] Our `PaymentStep.tsx`, `CardForm.tsx`, `PaymentMethodManager.tsx` — all Stripe component usage

---

## Phase 4: Major Frontend Overhaul (High Risk)

**Timeline:** Week 4-6 (dedicated sprint)
**Risk:** High — touching most frontend files

### 4A: React 18 → 19

**Migration Guide:** https://react.dev/blog/2024/12/05/react-19

**Breaking changes that affect us:**
- `forwardRef` no longer needed (ref is a regular prop)
- `useContext` replaced by `use(Context)`
- `ReactDOM.render` removed (we use `createRoot` already — verify)
- Strict mode changes
- New `use()` hook for promises and context

**Impact:** Every component file potentially affected. Do this with Tailwind 4 and Vite 8 together.

### 4B: React Router 6 → 7

**Migration Guide:** https://reactrouter.com/upgrading/v6

**Breaking changes:**
- Loader/action pattern changes
- Route definition syntax changes
- `useNavigate`, `useParams`, `useSearchParams` — check for API changes
- Our `App.tsx` route definitions need review

### 4C: Tailwind CSS 3 → 4

**Migration Guide:** https://tailwindcss.com/docs/upgrade-guide

**Breaking changes:**
- Config file format changes (CSS-first approach)
- `tailwind.config.js` → CSS-based configuration
- Some utility class renames
- PostCSS plugin changes

### 4D: Vite 6 → 8, Vitest 2 → 4, TypeScript 5 → 6

**Do together with React 19.** These are tightly coupled.

### 4E: jsdom 25 → 29

**Test-only dependency.** Update alongside Vitest.

### Phase 4 Playwright E2E Test Suite (Comprehensive)
```
AUTHENTICATION:
1. Login with email/password (existing user)
2. Login with Google OAuth
3. Login with passkey
4. MFA TOTP flow
5. MFA SMS flow
6. MFA email flow
7. Backup code recovery
8. Password reset (request + complete)
9. Session timeout and refresh
10. Logout and session cleanup

CORE WORKFLOWS:
11. Create customer (minimal: first name only)
12. Create invoice with line items
13. Issue invoice (draft → sent)
14. Record cash payment
15. Record Stripe payment
16. Issue refund (cash)
17. Issue refund (Stripe)
18. Create credit note
19. Create quote → convert to invoice
20. Create job card → complete → invoice

SETTINGS & INTEGRATIONS:
21. Navigate to all settings pages — verify they load
22. Verify Stripe integration status shows "configured"
23. Verify Xero integration status shows "connected"
24. Verify SMS provider status shows "active"
25. Verify email provider status shows "active"
26. Change org settings (name, address) → verify saved
27. User management → invite user → verify email sent
28. Branch management → create branch → verify appears

ADMIN:
29. Global admin dashboard loads
30. Audit log displays entries
31. Error log displays entries
32. Subscription plans page loads
33. Organisation list loads

REPORTS:
34. Revenue summary loads with data
35. Outstanding invoices report loads
36. GST return summary loads
37. Customer statement generates

NAVIGATION:
38. All sidebar links navigate correctly
39. Mobile responsive — hamburger menu works
40. Breadcrumbs navigate correctly
```

---

## Phase 5: Dependencies to Eliminate (Future Development)

These dependencies can be replaced with custom code to reduce external surface area:

| Dependency | Current Use | Replacement Strategy | Effort |
|---|---|---|---|
| `passlib` | Listed in pyproject.toml but NOT used (we use `bcrypt` directly) | Remove from pyproject.toml | 5 min |
| `python-dateutil` | Date parsing utilities | Replace with `datetime.fromisoformat()` (Python 3.11+) | 2 hours |
| `email-validator` | Email format validation | Write a simple regex validator (we already have one in frontend) | 1 hour |
| `gunicorn` | WSGI server (not used — we use uvicorn) | Remove if not used in production Docker CMD | 5 min |
| `jinja2` | Template rendering for emails/PDFs | Keep — too much effort to replace, well-maintained |
| `Faker` | Test data generation | Keep — dev-only, no security concern |
| `selenium` | Not in pyproject.toml — likely a global pip install | Uninstall globally if not needed | 5 min |
| `pandas` | Data processing (if used) | Check usage — may be replaceable with stdlib `csv` | Varies |
| `numpy` | Likely a pandas dependency | Removes with pandas if unused directly | Auto |
| `opencv-python` | Image processing (if used) | Check usage — may be unnecessary | Varies |
| `Flask` | Not in pyproject.toml — likely a global pip install | Uninstall globally | 5 min |
| `celery` | Task queue (if used) | Check if actually used — we use `asyncio.create_task()` for background work | Varies |
| `google-generativeai` | AI features (if used) | Check usage — may be a dev experiment | Varies |
| `spotipy` / `yt-dlp` / `ytmusicapi` | Not project-related | Global pip installs — not our concern | N/A |

### Immediate Cleanup (No Risk)
```bash
# Remove passlib from pyproject.toml (we use bcrypt directly)
# Remove gunicorn if Docker CMD uses uvicorn
# Verify: grep -r "passlib" app/  → should return nothing
# Verify: grep -r "gunicorn" Dockerfile  → check if used
```

---

## Rollback Strategy

### Before Any Upgrade
1. Full database backup: `pg_dump -Fc invoicing > pre_upgrade_$(date +%Y%m%d).dump`
2. Run `scripts/backup_encrypted_settings.py` to verify all encrypted fields decrypt
3. Git tag: `git tag pre-dependency-upgrade-$(date +%Y%m%d)`
4. Docker image tag: `docker tag invoicing-app:latest invoicing-app:pre-upgrade`

### If Upgrade Breaks Something
1. `git checkout pre-dependency-upgrade-YYYYMMDD`
2. `docker compose up -d --build --force-recreate app`
3. Verify encrypted settings still decrypt (run backup script)
4. Verify user login works

### If Encryption Breaks (Nuclear Option)
The `encryption_master_key` in `.env` is the root of all encryption. As long as this key is unchanged, all encrypted data can be recovered. The `cryptography` library upgrade (46.0.4 → 46.0.7) is a patch release — the AES-256-GCM implementation is identical. No re-encryption needed.

---

## Execution Order Summary

```
Phase 1 (Day 1):     Security patches — cryptography, certifi, pydantic, SQLAlchemy, webauthn
Phase 2 (Week 1):    Safe minors — fastapi, uvicorn, alembic, PyJWT, pillow, httpx
Phase 3A (Week 2):   Stripe SDK 14→15 (backend + frontend)
Phase 3B (Week 2):   Redis 6→7
Phase 3C (Week 2):   Twilio 8→9 (if actively used)
Phase 3D (Week 3):   Firebase 11→12 (frontend only)
Phase 4 (Week 4-6):  React 19 + Router 7 + Tailwind 4 + Vite 8 + TS 6 (big bang frontend)
Phase 5 (Ongoing):   Eliminate unnecessary dependencies
```

Each phase: upgrade on local → run Playwright E2E suite → deploy to HA standby → verify → deploy to prod.
