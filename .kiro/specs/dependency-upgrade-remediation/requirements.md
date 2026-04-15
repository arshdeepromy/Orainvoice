# Requirements Document

## Introduction

Safely upgrade all outdated dependencies across the OraInvoice platform (Python backend and React frontend) to their latest versions, organised into five risk-tiered phases. The upgrade must preserve zero impact on existing production data including user passwords (bcrypt hashes), MFA enrolments (TOTP secrets, SMS/email OTP), passkey credentials (WebAuthn public keys), backup codes, JWT sessions, encrypted API keys (AES-256-GCM envelope encryption), Xero OAuth tokens, and all third-party integration connectivity. The platform is in early production (1 org, 1 customer, 2 invoices) running Python 3.11/FastAPI on PostgreSQL 16 with RLS, and React 18/TypeScript/Vite 6 on the frontend.

## Glossary

- **Upgrade_Pipeline**: The phased execution process that applies dependency upgrades in risk-tiered order (security patches → safe minors → integration majors → frontend overhaul → cleanup).
- **Encrypted_Settings_Verifier**: The script that attempts to decrypt every encrypted field in `integration_configs`, `sms_verification_providers`, and `email_providers` tables to confirm encryption integrity before and after upgrades.
- **Rollback_Checkpoint**: A pre-upgrade snapshot consisting of a PostgreSQL dump, a Git tag, a Docker image tag, and a verified encrypted-settings report that enables full reversion.
- **E2E_Validation_Suite**: The Playwright end-to-end test suite executed after each phase to confirm all authentication flows, core workflows, integrations, and UI navigation remain functional.
- **Backend_Dependency_Set**: The Python packages defined in `pyproject.toml` and installed via pip.
- **Frontend_Dependency_Set**: The npm packages defined in `frontend/package.json`.
- **Envelope_Encryption**: The two-layer AES-256-GCM encryption scheme in `app/core/encryption.py` using a master key to encrypt per-record data encryption keys (DEKs).
- **Auth_Subsystem**: The authentication and session management layer comprising password verification (bcrypt), JWT token creation/validation (HS256/RS256), MFA (TOTP, SMS, email, passkeys), backup codes, and refresh token rotation.
- **Integration_Subsystem**: The set of outbound third-party connections including Stripe billing, Xero accounting sync, Connexus SMS, Firebase auth, and Carjam vehicle lookup.

## Requirements

### Requirement 1: Pre-Upgrade Rollback Checkpoint

**User Story:** As a platform operator, I want a verified rollback checkpoint created before any upgrade phase begins, so that the platform can be fully restored if an upgrade causes data corruption or service failure.

#### Acceptance Criteria

1. WHEN an upgrade phase is about to begin, THE Upgrade_Pipeline SHALL create a Rollback_Checkpoint consisting of a full PostgreSQL database dump (`pg_dump -Fc`), a Git tag (`pre-dependency-upgrade-{phase}-{date}`), and a Docker image tag (`invoicing-app:pre-upgrade-{phase}`).
2. WHEN a Rollback_Checkpoint is created, THE Encrypted_Settings_Verifier SHALL attempt to decrypt every encrypted field in `integration_configs.config_encrypted`, `sms_verification_providers.credentials_encrypted`, and `email_providers.credentials_encrypted` and report the result for each record.
3. IF the Encrypted_Settings_Verifier reports any decryption failure, THEN THE Upgrade_Pipeline SHALL abort the upgrade phase and report the failing records.
4. THE Rollback_Checkpoint SHALL be retained until the corresponding upgrade phase is verified in production and the next phase checkpoint is created.

### Requirement 2: Phase 1 — Security Patches

**User Story:** As a platform operator, I want to apply zero-risk security patches to cryptography, certifi, pydantic, SQLAlchemy, webauthn, and hypothesis, so that known vulnerabilities are resolved without any API or behaviour changes.

#### Acceptance Criteria

1. THE Upgrade_Pipeline SHALL upgrade the following Backend_Dependency_Set packages to their target patch versions: cryptography 46.0.4→46.0.7, certifi 2025.11.12→2026.2.25, pydantic 2.12.3→2.12.5, pydantic-settings 2.11.0→2.13.1, SQLAlchemy 2.0.42→2.0.49, hypothesis 6.151.6→6.151.12, webauthn 2.7.0→2.7.1.
2. THE Upgrade_Pipeline SHALL upgrade the following Frontend_Dependency_Set packages to their target patch versions: @headlessui/react→2.2.10, @types/node→25.6.0, axios→1.15.0, fast-check→4.6.0, postcss→8.5.9.
3. WHEN Phase 1 upgrades are applied, THE Envelope_Encryption module SHALL continue to decrypt all existing encrypted blobs in `integration_configs`, `sms_verification_providers`, and `email_providers` without re-encryption.
4. WHEN Phase 1 upgrades are applied, THE Auth_Subsystem SHALL continue to verify existing bcrypt password hashes, validate existing JWT tokens (HS256 and RS256), verify TOTP codes against encrypted secrets, and authenticate passkey credentials without any data migration.
5. WHEN Phase 1 upgrades are applied, THE E2E_Validation_Suite SHALL pass all authentication tests (email/password login, MFA TOTP, MFA SMS, passkey login), all integration status checks (Stripe configured, Xero connected, Connexus active, email provider active), and core workflow tests (create invoice, process payment, issue refund with Xero sync).

### Requirement 3: Phase 2 — Safe Minor Upgrades

**User Story:** As a platform operator, I want to apply backward-compatible minor version upgrades to FastAPI, uvicorn, alembic, PyJWT, pillow, reportlab, requests, and httpx, so that the platform benefits from bug fixes and performance improvements without breaking changes.

#### Acceptance Criteria

1. THE Upgrade_Pipeline SHALL upgrade the following Backend_Dependency_Set packages: fastapi 0.120.0→0.135.3, uvicorn 0.38.0→0.44.0, alembic 1.13.0→1.18.4, PyJWT 2.10.1→2.12.1, pillow 12.0.0→12.2.0, reportlab 4.4.3→4.4.10, requests 2.32.4→2.33.1, httpx to latest compatible minor.
2. WHEN PyJWT is upgraded, THE Auth_Subsystem SHALL continue to create and decode JWT access tokens using both HS256 and RS256 algorithms with identical claim structures and expiry behaviour.
3. WHEN FastAPI is upgraded, THE Backend_Dependency_Set SHALL maintain all existing API endpoint response models, dependency injection patterns (`Depends`, `APIRouter`), and middleware ordering without modification.
4. WHEN httpx is upgraded, THE Integration_Subsystem SHALL maintain all outbound API calls to Xero, Connexus, Carjam, and Firebase token verification endpoints without connection or serialisation failures.
5. WHEN Phase 2 upgrades are applied, THE E2E_Validation_Suite SHALL pass all Phase 1 tests plus: full signup flow, password reset flow, full invoice lifecycle (create→issue→pay), Xero sync verification, Stripe payment method operations, refresh token rotation, and admin settings/audit log verification.

### Requirement 4: Phase 3A — Stripe SDK Major Upgrade

**User Story:** As a platform operator, I want to upgrade the Stripe Python SDK from version 14 to 15 and the frontend Stripe packages to their latest majors, so that the platform uses a supported SDK version while maintaining all billing functionality.

#### Acceptance Criteria

1. THE Upgrade_Pipeline SHALL upgrade stripe from 14.3.0 to 15.0.1 in the Backend_Dependency_Set.
2. THE Upgrade_Pipeline SHALL upgrade @stripe/react-stripe-js to version 6 and @stripe/stripe-js to version 9 in the Frontend_Dependency_Set.
3. WHEN the Stripe SDK is upgraded, THE Integration_Subsystem SHALL continue to create Stripe Customers, create PaymentIntents, create and cancel Subscriptions, create billing portal Sessions, and construct webhook events using the same function signatures or their documented replacements.
4. WHEN the Stripe SDK is upgraded, THE Integration_Subsystem SHALL maintain backward compatibility with the Stripe API by preserving the existing API version header behaviour.
5. WHEN the frontend Stripe packages are upgraded, THE Frontend_Dependency_Set SHALL maintain the `Elements` component, `useStripe()` hook, `useElements()` hook, and `loadStripe()` initialisation in `PaymentStep.tsx`, `CardForm.tsx`, and `PaymentMethodManager.tsx`.
6. WHEN Phase 3A upgrades are applied, THE E2E_Validation_Suite SHALL verify Stripe customer creation, PaymentIntent with test card, webhook delivery and parsing, billing portal session creation, and subscription lifecycle.

### Requirement 5: Phase 3B — Redis Major Upgrade

**User Story:** As a platform operator, I want to upgrade the Redis Python client from version 6 to 7, so that the platform uses a supported client version while maintaining rate limiting, MFA OTP storage, and caching functionality.

#### Acceptance Criteria

1. THE Upgrade_Pipeline SHALL upgrade redis from 6.3.0 to 7.4.0 in the Backend_Dependency_Set.
2. WHEN the Redis client is upgraded, THE `app/core/redis.py` module SHALL maintain the `redis.asyncio.from_url()` connection pool creation with `decode_responses=True`, `max_connections=200`, `socket_timeout=3`, `socket_connect_timeout=1`, and `retry_on_timeout=True` parameters.
3. WHEN the Redis client is upgraded, THE Auth_Subsystem SHALL continue to store and retrieve MFA OTP codes, maintain attempt counters, and expire keys using `get`, `set`, `setex`, `incr`, `expire`, and `delete` operations without data loss.
4. WHEN the Redis client is upgraded, THE rate limiting middleware SHALL continue to enforce per-user, per-org, and per-IP rate limits using Redis atomic increment and expiry operations.
5. WHEN the Redis client is upgraded, THE Connexus SMS token cache SHALL continue to store and refresh access tokens without connectivity failures.
6. WHEN Phase 3B upgrades are applied, THE E2E_Validation_Suite SHALL verify MFA TOTP login, MFA SMS login, rate limiting behaviour, and Connexus SMS delivery.

### Requirement 6: Phase 3C — Twilio Major Upgrade

**User Story:** As a platform operator, I want to upgrade the Twilio Python SDK from version 8 to 9, so that the dependency is current even if Connexus is the primary SMS provider.

#### Acceptance Criteria

1. THE Upgrade_Pipeline SHALL upgrade twilio from 8.12.0 to 9.10.4 in the Backend_Dependency_Set.
2. WHEN the Twilio SDK is upgraded, THE Integration_Subsystem SHALL maintain the `Client(account_sid, auth_token)` constructor and `client.messages.create()` call signature, or apply the documented migration changes.
3. IF Twilio is not actively used as an SMS provider (Connexus is primary), THEN THE Upgrade_Pipeline SHALL verify that the Twilio SDK upgrade does not affect Connexus SMS operations or any shared SMS routing logic.

### Requirement 7: Phase 3D — Firebase Frontend Major Upgrade

**User Story:** As a platform operator, I want to upgrade the Firebase frontend SDK from version 11 to 12, so that the platform uses a supported SDK version while maintaining Google OAuth and Firebase auth token flows.

#### Acceptance Criteria

1. THE Upgrade_Pipeline SHALL upgrade firebase from 11.10.0 to 12.12.0 in the Frontend_Dependency_Set.
2. WHEN the Firebase SDK is upgraded, THE Frontend_Dependency_Set SHALL maintain `initializeApp` configuration, `signInWithEmailAndPassword`, `signInWithPopup`, and `onAuthStateChanged` function calls in `AuthContext.tsx`.
3. WHEN the Firebase SDK is upgraded, THE Auth_Subsystem backend SHALL continue to verify Firebase ID tokens without modification, as token verification uses Google public keys and is independent of the frontend SDK version.
4. WHEN Phase 3D upgrades are applied, THE E2E_Validation_Suite SHALL verify Google OAuth login flow and Firebase-authenticated session creation.

### Requirement 8: Phase 4 — Major Frontend Overhaul

**User Story:** As a platform operator, I want to upgrade React 18→19, React Router 6→7, Tailwind CSS 3→4, Vite 6→8, Vitest 2→4, TypeScript 5→6, and jsdom 25→29 together as a coordinated frontend sprint, so that the frontend stack is fully current.

#### Acceptance Criteria

1. THE Upgrade_Pipeline SHALL upgrade the following Frontend_Dependency_Set packages together: react and react-dom 18→19, react-router-dom 6→7, tailwindcss 3→4, vite 6→8, vitest 2→4, typescript 5→6, jsdom 25→29.
2. WHEN React 19 is applied, THE Frontend_Dependency_Set SHALL remove `forwardRef` wrappers (ref becomes a regular prop), replace `useContext` calls with `use(Context)` where applicable, and verify that `createRoot` is used for app mounting (not the removed `ReactDOM.render`).
3. WHEN React Router 7 is applied, THE Frontend_Dependency_Set SHALL update route definitions in `App.tsx`, and verify that `useNavigate`, `useParams`, and `useSearchParams` hooks function correctly with the new API.
4. WHEN Tailwind CSS 4 is applied, THE Frontend_Dependency_Set SHALL migrate from `tailwind.config.js` to the CSS-first configuration approach, update any renamed utility classes, and update PostCSS plugin configuration.
5. WHEN Phase 4 upgrades are applied, THE E2E_Validation_Suite SHALL pass the comprehensive 40-test suite covering: all authentication flows (email/password, Google OAuth, passkey, MFA TOTP/SMS/email, backup codes, password reset, session refresh, logout), all core workflows (customer creation, invoice lifecycle, payments, refunds, credit notes, quotes, job cards), all settings and integration pages, all admin pages, all reports, and all navigation paths including mobile responsive layout.
6. WHEN Phase 4 upgrades are applied, THE Frontend_Dependency_Set SHALL produce a successful `tsc -b && vite build` with zero type errors and zero build warnings.

### Requirement 9: Phase 5 — Dependency Elimination

**User Story:** As a platform operator, I want to remove unused and replaceable dependencies from the project, so that the external dependency surface area is minimised and maintenance burden is reduced.

#### Acceptance Criteria

1. THE Upgrade_Pipeline SHALL remove `passlib` from `pyproject.toml` after verifying that no application code imports or references passlib (the platform uses bcrypt directly via `app/modules/auth/password.py`).
2. THE Upgrade_Pipeline SHALL remove `gunicorn` from `pyproject.toml` after verifying that no Dockerfile CMD or entrypoint script references gunicorn (the platform uses uvicorn).
3. THE Upgrade_Pipeline SHALL evaluate `python-dateutil` for replacement with `datetime.fromisoformat()` (Python 3.11+ native) and remove the dependency if all usages are replaced.
4. THE Upgrade_Pipeline SHALL evaluate `email-validator` for replacement with a regex-based validator and remove the dependency if all usages are replaced.
5. WHEN any dependency is removed, THE Upgrade_Pipeline SHALL verify that `pip install` completes without errors and that the existing test suite passes.
6. WHEN Phase 5 cleanup is complete, THE E2E_Validation_Suite SHALL pass all Phase 1 tests to confirm no functional regression from dependency removal.

### Requirement 10: Cross-Phase Data Integrity Invariant

**User Story:** As a platform operator, I want a guarantee that no upgrade phase alters, corrupts, or invalidates any existing production data, so that the single production customer's data remains fully intact throughout the upgrade process.

#### Acceptance Criteria

1. FOR ALL upgrade phases, THE Upgrade_Pipeline SHALL preserve the ability to verify existing bcrypt password hashes in `users.password_hash` without re-hashing.
2. FOR ALL upgrade phases, THE Upgrade_Pipeline SHALL preserve the ability to decrypt existing TOTP secrets in `user_mfa_methods.secret_encrypted` using the unchanged Envelope_Encryption module.
3. FOR ALL upgrade phases, THE Upgrade_Pipeline SHALL preserve the ability to authenticate existing passkey credentials in `user_passkey_credentials` using the WebAuthn library without credential re-registration.
4. FOR ALL upgrade phases, THE Upgrade_Pipeline SHALL preserve the ability to verify existing backup code hashes in `user_backup_codes.code_hash` without re-hashing.
5. FOR ALL upgrade phases, THE Upgrade_Pipeline SHALL preserve the ability to decrypt existing API keys and secrets in `integration_configs.config_encrypted`, `sms_verification_providers.credentials_encrypted`, and `email_providers.credentials_encrypted` using the unchanged Envelope_Encryption module.
6. FOR ALL upgrade phases, THE Upgrade_Pipeline SHALL preserve all existing JWT sessions (both HS256 and RS256 tokens) so that logged-in users are not forcibly logged out.
7. FOR ALL upgrade phases, THE Upgrade_Pipeline SHALL preserve all existing Xero OAuth tokens stored in the database so that the Xero connection remains active without re-authentication.

### Requirement 11: Rollback Execution

**User Story:** As a platform operator, I want a documented and tested rollback procedure for each upgrade phase, so that a failed upgrade can be fully reverted within minutes.

#### Acceptance Criteria

1. IF an upgrade phase causes any E2E_Validation_Suite test failure, THEN THE Upgrade_Pipeline SHALL revert to the Rollback_Checkpoint by restoring the Git tag, rebuilding the Docker image from the tagged code, and optionally restoring the database dump.
2. WHEN a rollback is executed, THE Encrypted_Settings_Verifier SHALL confirm that all encrypted fields still decrypt correctly after reversion.
3. WHEN a rollback is executed, THE Auth_Subsystem SHALL confirm that user login with email/password succeeds after reversion.
4. THE Rollback_Checkpoint SHALL support rollback of each phase independently without requiring rollback of subsequent phases.

### Requirement 12: Per-Phase Deployment Sequence

**User Story:** As a platform operator, I want each upgrade phase to follow a consistent deployment sequence (local → HA standby → production), so that upgrades are validated in lower environments before reaching production.

#### Acceptance Criteria

1. FOR ALL upgrade phases, THE Upgrade_Pipeline SHALL apply the upgrade on the local development environment first and run the E2E_Validation_Suite.
2. WHEN the local E2E_Validation_Suite passes, THE Upgrade_Pipeline SHALL deploy the upgrade to the HA standby environment and run the E2E_Validation_Suite again.
3. WHEN the HA standby E2E_Validation_Suite passes, THE Upgrade_Pipeline SHALL deploy the upgrade to the production Raspberry Pi environment via the standard tar+SSH sync and Docker rebuild process.
4. WHEN the production deployment is complete, THE Upgrade_Pipeline SHALL run the Encrypted_Settings_Verifier and a smoke test (login + view dashboard) to confirm production health.
