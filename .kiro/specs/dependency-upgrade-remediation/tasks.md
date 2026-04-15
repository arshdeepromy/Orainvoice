# Implementation Plan: Dependency Upgrade Remediation

## Overview

Phased implementation of dependency upgrades across the OraInvoice platform, organised by risk tier. Each phase is gated by a rollback checkpoint, encrypted settings verification, and E2E validation. Infrastructure scripts are built first, then each upgrade phase applies dependencies and validates with property tests and E2E tests.

## Tasks

- [x] 1. Create rollback checkpoint and encrypted settings verifier scripts
  - [x] 1.1 Create `scripts/verify_encrypted_settings.py` — async script that connects to the database, iterates `integration_configs.config_encrypted`, `sms_verification_providers.credentials_encrypted`, `email_providers.credentials_encrypted`, and `user_mfa_methods.secret_encrypted`, attempts decryption via `envelope_decrypt_str`, and outputs a JSON `VerificationReport` with `timestamp`, `phase`, `stage`, `results`, `total_checked`, `total_failed`, `passed` fields. Accept `--phase` and `--stage` CLI args. Exit code 1 if any decryption fails.
    - _Requirements: 1.2, 1.3, 10.2, 10.5, 11.2_

  - [x] 1.2 Create `scripts/create_rollback_checkpoint.sh` — accepts a phase name arg, runs `pg_dump -Fc` to `backups/pre_upgrade_<phase>_<date>.dump`, creates Git tag `pre-dependency-upgrade-<phase>-<date>`, tags Docker image `invoicing-app:pre-upgrade-<phase>`. Use `set -euo pipefail`.
    - _Requirements: 1.1, 1.4_

  - [x] 1.3 Create `scripts/rollback_upgrade.sh` — accepts a phase name arg, checks out the Git tag, rebuilds Docker via `docker compose up -d --build --force-recreate app`, runs `verify_encrypted_settings.py --stage rollback`, prints smoke test instructions.
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

- [x] 2. Write property-based tests for cryptographic and auth invariants
  - [x] 2.1 Write property test for envelope encryption round-trip (Property 1)
    - **Property 1: Envelope Encryption Round-Trip**
    - In `tests/test_dependency_upgrade_property.py`, use Hypothesis to generate arbitrary text (including empty, unicode, long strings). Assert `envelope_decrypt(envelope_encrypt(plaintext)) == plaintext.encode()` and `envelope_decrypt_str(envelope_encrypt(plaintext)) == plaintext`.
    - **Validates: Requirements 1.2, 2.3, 10.2, 10.5, 10.7, 11.2**

  - [x] 2.2 Write property test for bcrypt password hash verification round-trip (Property 2)
    - **Property 2: bcrypt Password Hash Verification Round-Trip**
    - In `tests/test_dependency_upgrade_property.py`, use Hypothesis to generate password strings (1–72 bytes). Assert `verify_password(pw, hash_password(pw)) is True` and `verify_password(different_pw, hash) is False`.
    - **Validates: Requirements 2.4, 10.1, 10.4**

  - [x] 2.3 Write property test for JWT access token encode/decode round-trip (Property 3)
    - **Property 3: JWT Access Token Encode/Decode Round-Trip**
    - In `tests/test_dependency_upgrade_property.py`, use Hypothesis to generate user_id (UUID), org_id (UUID or None), role (text), email (text). Assert `decode_access_token(create_access_token(...))` returns matching `user_id`, `org_id`, `role`, `email` claims. Test with HS256 config.
    - **Validates: Requirements 2.4, 3.2, 10.6**

  - [x] 2.4 Write property test for Redis OTP store/retrieve round-trip (Property 4)
    - **Property 4: Redis OTP Store/Retrieve Round-Trip**
    - In `tests/test_dependency_upgrade_property.py`, use Hypothesis with `fakeredis` to generate user_id, method ("sms"/"email"), and 6-digit OTP code. Assert storing via `setex` and retrieving via `get` returns the original code before TTL expiry.
    - **Validates: Requirements 5.3**

  - [x] 2.5 Write property test for Redis rate limit counter monotonic increment (Property 5)
    - **Property 5: Redis Rate Limit Counter Monotonic Increment**
    - In `tests/test_dependency_upgrade_property.py`, use Hypothesis with `fakeredis` to generate N (1–500) increments on a key. Assert final counter value equals N. Assert key no longer exists after TTL expiry.
    - **Validates: Requirements 5.4**

- [x] 3. Checkpoint — Ensure infrastructure scripts and property tests are solid
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Create per-phase upgrade execution scripts
  - [x] 4.1 Create `scripts/upgrade_phase1.sh` — calls `create_rollback_checkpoint.sh phase1`, runs `verify_encrypted_settings.py --phase phase1 --stage pre`, executes `pip install cryptography==46.0.7 certifi==2026.2.25 pydantic==2.12.5 pydantic-settings==2.13.1 SQLAlchemy==2.0.49 hypothesis==6.151.12 webauthn==2.7.1`, executes `cd frontend && npm install @headlessui/react@2.2.10 @types/node@25.6.0 axios@1.15.0 fast-check@4.6.0 postcss@8.5.9`, runs pytest, runs E2E Phase 1 tests, runs `verify_encrypted_settings.py --phase phase1 --stage post`.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 12.1_

  - [x] 4.2 Create `scripts/upgrade_phase2.sh` — same checkpoint/verify pattern, executes `pip install fastapi==0.135.3 uvicorn==0.44.0 alembic==1.18.4 PyJWT==2.12.1 pillow==12.2.0 reportlab==4.4.10 requests==2.33.1 httpx==0.28.1`, runs pytest, runs E2E Phase 1+2 tests, post-verifies.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 12.1_

  - [x] 4.3 Create `scripts/upgrade_phase3.sh` — same pattern, executes Stripe (`pip install stripe==15.0.1`, `cd frontend && npm install @stripe/react-stripe-js@6 @stripe/stripe-js@9`), Redis (`pip install redis==7.4.0`), Twilio (`pip install twilio==9.10.4`), Firebase (`cd frontend && npm install firebase@12.12.0`). Runs pytest, runs E2E Phase 1+2+3 tests, post-verifies.
    - _Requirements: 4.1, 4.2, 5.1, 6.1, 7.1, 12.1_

  - [x] 4.4 Create `scripts/upgrade_phase4.sh` — same pattern, executes `cd frontend && npm install react@19 react-dom@19 react-router-dom@7 tailwindcss@4 vite@8 vitest@4 typescript@6 jsdom@29 @types/react@19 @types/react-dom@19`. Runs `tsc -b && vite build` as gate. Runs full 40-test E2E suite, post-verifies.
    - _Requirements: 8.1, 8.6, 12.1_

  - [x] 4.5 Create `scripts/upgrade_phase5.sh` — removes `passlib` and `gunicorn` from `pyproject.toml`, evaluates `python-dateutil` and `email-validator` for removal. Runs `pip install .` to verify clean install, runs pytest, runs E2E Phase 1 regression tests.
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

- [x] 5. Checkpoint — Ensure all phase scripts are correct and runnable
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Create Playwright E2E validation suite
  - [x] 6.1 Create `tests/e2e/frontend/upgrade-validation.spec.ts` with Phase 1 test block — 11 tests: email/password login, MFA TOTP, MFA SMS, passkey login, Stripe integration status, Xero integration status, SMS provider status, email provider status, create invoice + Xero sync, process payment, issue refund + credit note.
    - _Requirements: 2.5_

  - [x] 6.2 Add Phase 2 test block — 9 additional tests: full signup flow, password reset flow, full invoice lifecycle (create→issue→pay), Xero sync verification, Stripe payment method operations, refresh token rotation, admin settings, audit log, SMS send verification.
    - _Requirements: 3.5_

  - [x] 6.3 Add Phase 3 test block — 6 additional tests: Stripe customer creation + PaymentIntent with test card, webhook delivery and parsing, billing portal session, MFA TOTP login (Redis-dependent), MFA SMS login (Redis-dependent), Firebase Google OAuth login.
    - _Requirements: 4.6, 5.6, 7.4_

  - [x] 6.4 Add Phase 4 comprehensive test block — full 40-test suite covering all authentication flows, core workflows, settings/integrations, admin pages, reports, and navigation paths including mobile responsive layout.
    - _Requirements: 8.5_

- [x] 7. Checkpoint — Ensure E2E suite compiles and test structure is correct
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement Phase 1 — Security Patches
  - [x] 8.1 Update `pyproject.toml` dependency pins for Phase 1 packages: `cryptography>=46.0.7`, `certifi>=2026.2.25`, `pydantic>=2.12.5`, `pydantic-settings>=2.13.1`, `sqlalchemy[asyncio]>=2.0.49`, `webauthn>=2.7.1`, `hypothesis>=6.151.12`.
    - _Requirements: 2.1_

  - [x] 8.2 Update `frontend/package.json` dependency versions for Phase 1 packages: `@headlessui/react@2.2.10`, `@types/node@25.6.0`, `axios@1.15.0`, `fast-check@4.6.0`, `postcss@8.5.9`.
    - _Requirements: 2.2_

- [x] 9. Implement Phase 2 — Safe Minor Upgrades
  - [x] 9.1 Update `pyproject.toml` dependency pins for Phase 2 packages: `fastapi>=0.135.3`, `uvicorn[standard]>=0.44.0`, `alembic>=1.18.4`, `PyJWT[crypto]>=2.12.1`, `pillow>=12.2.0`, `reportlab>=4.4.10`, `requests>=2.33.1`, `httpx>=0.28.1`.
    - _Requirements: 3.1_

  - [x] 9.2 Verify `app/modules/auth/jwt.py` — confirm `jwt.encode()`, `jwt.decode()`, `jwt.get_unverified_header()` call signatures are compatible with PyJWT 2.12.1. Fix any deprecation warnings or parameter changes.
    - _Requirements: 3.2_

  - [x] 9.3 Verify all FastAPI routers — confirm `Depends`, `APIRouter`, response models, and middleware ordering are compatible with FastAPI 0.135.3. Fix any deprecation warnings.
    - _Requirements: 3.3_

  - [x] 9.4 Verify httpx usage in Xero, Connexus, Carjam, and Firebase integrations — confirm `httpx.AsyncClient` usage is compatible with the upgraded version. Fix any breaking changes.
    - _Requirements: 3.4_

- [x] 10. Implement Phase 3 — Third-Party Integration Majors
  - [x] 10.1 Update `pyproject.toml` for `stripe>=15.0.1`. Review `app/integrations/stripe_billing.py` for Stripe SDK v15 breaking changes — update `stripe.PaymentIntent.create()`, `stripe.Customer.create()`, `stripe.Subscription.create()`, `stripe.billing_portal.Session.create()`, `stripe.Webhook.construct_event()` calls as needed.
    - _Requirements: 4.1, 4.3, 4.4_

  - [x] 10.2 Update `frontend/package.json` for `@stripe/react-stripe-js@6` and `@stripe/stripe-js@9`. Review `PaymentStep.tsx`, `CardForm.tsx`, `PaymentMethodManager.tsx` for breaking changes in `Elements`, `useStripe()`, `useElements()`, `loadStripe()`.
    - _Requirements: 4.2, 4.5_

  - [x] 10.3 Update `pyproject.toml` for `redis>=7.4.0`. Review `app/core/redis.py` — confirm `redis.asyncio.from_url()` parameters (`decode_responses`, `max_connections`, `socket_timeout`, `socket_connect_timeout`, `retry_on_timeout`) are compatible. Review MFA service, rate limiting middleware, and Connexus token cache for any Redis client API changes.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 10.4 Update `pyproject.toml` for `twilio>=9.10.4`. Review Twilio usage — confirm `Client(account_sid, auth_token)` and `client.messages.create()` are compatible or apply documented migration. Verify no impact on Connexus SMS operations.
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 10.5 Update `frontend/package.json` for `firebase@12.12.0`. Review `AuthContext.tsx` — confirm `initializeApp`, `signInWithEmailAndPassword`, `signInWithPopup`, `onAuthStateChanged` are compatible with Firebase 12.
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 11. Checkpoint — Ensure Phases 1–3 pass all property tests and E2E tests
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implement Phase 4 — Major Frontend Overhaul
  - [x] 12.1 Update `frontend/package.json` for React 19 (`react@19`, `react-dom@19`, `@types/react@19`, `@types/react-dom@19`). Remove `forwardRef` wrappers across all components (ref becomes a regular prop). Replace `useContext` calls with `use(Context)` where applicable. Verify `createRoot` is used for app mounting.
    - _Requirements: 8.1, 8.2_

  - [x] 12.2 Update `frontend/package.json` for React Router 7 (`react-router-dom@7`). Update route definitions in `App.tsx`. Verify `useNavigate`, `useParams`, `useSearchParams` hooks work with the new API.
    - _Requirements: 8.1, 8.3_

  - [x] 12.3 Update `frontend/package.json` for Tailwind CSS 4 (`tailwindcss@4`). Migrate from `tailwind.config.js` to CSS-first configuration. Update renamed utility classes. Update PostCSS plugin configuration.
    - _Requirements: 8.1, 8.4_

  - [x] 12.4 Update `frontend/package.json` for Vite 8 (`vite@8`), Vitest 4 (`vitest@4`), TypeScript 6 (`typescript@6`), jsdom 29 (`jsdom@29`). Fix any build or test configuration changes.
    - _Requirements: 8.1_

  - [x] 12.5 Run `tsc -b && vite build` and fix all TypeScript errors and build warnings until the build succeeds with zero errors.
    - _Requirements: 8.6_

  - [x] 12.6 Run the full 40-test Playwright E2E suite and fix any failures from the frontend overhaul.
    - _Requirements: 8.5_

- [x] 13. Checkpoint — Ensure Phase 4 build and full E2E suite pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Implement Phase 5 — Dependency Elimination
  - [x] 14.1 Remove `passlib[bcrypt]>=1.7.4` from `pyproject.toml`. Verify with `grep -r "passlib" app/` that no application code imports passlib.
    - _Requirements: 9.1_

  - [x] 14.2 Remove `gunicorn>=22.0.0` from `pyproject.toml`. Verify with `grep -r "gunicorn" Dockerfile docker-compose*` that no entrypoint references gunicorn.
    - _Requirements: 9.2_

  - [x] 14.3 Evaluate `python-dateutil` — search all usages with `grep -r "dateutil" app/`. Replace with `datetime.fromisoformat()` (Python 3.11+ native) where possible. Remove `python-dateutil>=2.8.0` from `pyproject.toml` if all usages are replaced.
    - _Requirements: 9.3_

  - [x] 14.4 Evaluate `email-validator` — search all usages with `grep -r "email.validator\|email_validator" app/`. Replace with a regex-based validator if feasible. Remove `email-validator>=2.1.0` from `pyproject.toml` if all usages are replaced.
    - _Requirements: 9.4_

  - [x] 14.5 Run `pip install .` to verify clean install with no missing dependencies. Run pytest to confirm no import errors or test failures.
    - _Requirements: 9.5_

- [x] 15. Final checkpoint — Ensure all phases pass, run Phase 1 E2E regression
  - Run the Phase 1 E2E regression tests to confirm no functional regression from dependency removal. Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 9.6, 10.1–10.7_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation between phases
- Property tests (Properties 1–5) validate cryptographic and auth invariants that must hold across all upgrade phases
- The E2E suite grows incrementally: Phase 1 (11 tests) → Phase 2 (+9) → Phase 3 (+6) → Phase 4 (full 40-test suite)
- Phase 3 sub-phases (Stripe, Redis, Twilio, Firebase) can be applied in any order but all must complete before Phase 4
