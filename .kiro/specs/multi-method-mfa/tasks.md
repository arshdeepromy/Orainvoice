# Implementation Plan: Multi-Method MFA

## Overview

Implement multi-method MFA for BudgetFlow, migrating from JSONB columns to normalised tables, extending the backend service layer and API endpoints for TOTP/SMS/Email/Passkey enrolment, challenge, and management, building the frontend MFA settings panel and challenge page, and wiring everything together with rate limiting, audit logging, and backup codes.

## Tasks

- [x] 1. Database migration and SQLAlchemy models
  - [x] 1.1 Create Alembic migration for new MFA tables
    - Create migration file in `alembic/versions/` that creates `user_mfa_methods`, `user_passkey_credentials`, and `user_backup_codes` tables with all columns, constraints, and indexes as specified in the design
    - Add data migration logic to move existing data from `users.mfa_methods`, `users.passkey_credentials`, and `users.backup_codes_hash` JSONB columns into the new tables
    - Drop or deprecate the JSONB columns from the `users` table
    - _Requirements: 1.3, 2.3, 3.3, 5.2, 11.3_

  - [x] 1.2 Add SQLAlchemy models for the new tables
    - Create `UserMfaMethod`, `UserPasskeyCredential`, and `UserBackupCode` models in `app/modules/auth/models.py` (or a new `mfa_models.py`) matching the design schema
    - Add relationships to the existing `User` model
    - Include the unique constraint `(user_id, method)` and check constraint on `method`
    - _Requirements: 1.3, 4.1, 11.3, 11.6_

- [x] 2. Backend MFA service layer — enrolment and verification
  - [x] 2.1 Implement `enrol_mfa()` in `app/modules/auth/mfa_service.py`
    - TOTP: generate RFC 6238 secret (30s step, SHA-1), return provisioning URI with issuer "BudgetFlow" and QR code data, store pending record in `user_mfa_methods`
    - SMS: validate phone number, send 6-digit OTP via `ConnexusSmsClient.send()`, store OTP in Redis with 300s TTL
    - Email: send 6-digit OTP to registered email, store OTP in Redis with 600s TTL
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 3.1, 3.2_

  - [x] 2.2 Implement `verify_enrolment()` in `app/modules/auth/mfa_service.py`
    - TOTP: validate code against stored secret using `pyotp` with ±1 window tolerance, mark `verified=True`, persist encrypted secret
    - SMS/Email: validate code against Redis OTP, consume OTP, mark `verified=True`, persist phone number for SMS
    - Reject invalid/expired codes with descriptive errors
    - _Requirements: 1.3, 1.4, 2.3, 2.4, 3.3, 3.4_

  - [x] 2.3 Write property tests for TOTP enrolment (Properties 1–4)
    - **Property 1: TOTP secret conforms to RFC 6238** — verify base32 secret, 30s interval, SHA-1, valid 6-digit codes
    - **Validates: Requirements 1.1, 1.2**
    - **Property 2: TOTP provisioning URI correctness** — verify `otpauth://totp/` URI with issuer "BudgetFlow" and plain-text secret
    - **Validates: Requirements 1.2, 1.5**
    - **Property 3: TOTP enrolment round-trip** — generate code from secret, submit, verify method marked verified
    - **Validates: Requirements 1.3**
    - **Property 4: Invalid TOTP code rejection** — submit non-matching codes, verify rejection
    - **Validates: Requirements 1.4**

  - [x] 2.4 Write property tests for OTP enrolment (Properties 5–7)
    - **Property 5: OTP enrolment round-trip (SMS and Email)** — initiate enrolment, submit stored OTP, verify method activated
    - **Validates: Requirements 2.1, 2.3, 3.1, 3.3**
    - **Property 6: Invalid OTP rejection** — submit wrong code, verify rejection
    - **Validates: Requirements 2.4, 3.4**
    - **Property 7: OTP expiry matches method configuration** — verify Redis TTL is 300s for SMS, 600s for email
    - **Validates: Requirements 2.2, 3.2**

- [x] 3. Backend MFA service layer — multi-method support and method management
  - [x] 3.1 Implement `get_user_mfa_status()` and `disable_mfa_method()` in `mfa_service.py`
    - `get_user_mfa_status`: query `user_mfa_methods` for all 4 method types, return `MFAMethodStatus` list with masked phone number
    - `disable_mfa_method`: verify password, check last-method guard for MFA-mandatory orgs, delete method record and associated data (TOTP secret, SMS phone number)
    - _Requirements: 4.4, 4.5, 4.6, 7.1, 7.2, 7.3, 7.4_

  - [x] 3.2 Write property tests for multi-method and disable (Properties 8, 11, 12)
    - **Property 8: Multi-method concurrent enrolment** — enrol all 4 types, verify all returned, unique constraint prevents duplicates
    - **Validates: Requirements 4.1**
    - **Property 11: Method disable removes method and associated data** — disable each method type, verify data deleted
    - **Validates: Requirements 4.5, 7.2, 7.3, 7.4**
    - **Property 12: Last-method guard in MFA-mandatory organisations** — attempt to disable last method in mandatory org, verify rejection
    - **Validates: Requirements 4.6, 13.5**

- [x] 4. Backend MFA service layer — backup codes
  - [x] 4.1 Implement `generate_backup_codes()` in `mfa_service.py`
    - Generate exactly 10 alphanumeric codes, hash each with bcrypt, store in `user_backup_codes`
    - Invalidate (delete) all previous backup codes for the user before inserting new set
    - Return plain-text codes exactly once
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 4.2 Write property tests for backup codes (Properties 13–15)
    - **Property 13: Backup code generation produces exactly 10 hashed codes** — verify 10 codes returned, 10 DB entries, hashes differ from plain text
    - **Validates: Requirements 5.1, 5.2**
    - **Property 14: Backup code regeneration invalidates previous codes** — generate, regenerate, verify old codes fail
    - **Validates: Requirements 5.3**
    - **Property 15: Backup code single-use enforcement** — use code once succeeds, second use fails, `used_at` set
    - **Validates: Requirements 5.6**

- [x] 5. Checkpoint — Core service layer
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Backend MFA challenge and login flow
  - [x] 6.1 Implement MFA challenge flow in `mfa_service.py` and update login in `service.py`
    - Modify login endpoint: when user has verified MFA methods, return `MFAChallengeResponse` with `mfa_token` and methods list instead of JWT tokens
    - Store challenge session in Redis with 300s TTL keyed by hashed `mfa_token`
    - Implement `send_challenge_otp()`: send OTP for selected method (SMS via Connexus, email via email provider), enforce rate limit
    - Implement `verify_mfa()`: validate code for selected method, track failed attempts in Redis (max 5), issue JWT on success, lockout on 5 failures
    - Support backup code verification: check against `user_backup_codes`, mark as consumed
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [x] 6.2 Write property tests for MFA challenge flow (Properties 9, 10, 16–19)
    - **Property 9: MFA challenge lists all verified methods** — verify challenge response contains exactly the user's verified methods
    - **Validates: Requirements 4.2, 6.2**
    - **Property 10: MFA challenge method isolation** — valid code for method A does not satisfy method B
    - **Validates: Requirements 4.3**
    - **Property 16: MFA-enabled login returns challenge token, not access tokens** — verify no JWT tokens in login response when MFA enabled
    - **Validates: Requirements 6.1**
    - **Property 17: Successful MFA verification issues JWT tokens** — verify access_token and refresh_token returned
    - **Validates: Requirements 6.5**
    - **Property 18: MFA lockout after 5 consecutive failures** — 5 failures then lockout, even with correct code
    - **Validates: Requirements 6.6**
    - **Property 19: MFA challenge token expires after 5 minutes** — verify Redis TTL 300s, expired token rejected
    - **Validates: Requirements 6.7**

- [x] 7. Backend rate limiting and security
  - [x] 7.1 Implement OTP rate limiting and authentication guards
    - Implement `check_otp_rate_limit()` in `mfa_service.py`: Redis sliding window counter, 5 sends per method per 15 min, independent tracking per method type
    - Add `Retry-After` header to 429 responses
    - Ensure all MFA enrolment/management endpoints require valid JWT access token (HTTP 401 without)
    - Add audit logging for all MFA operations (enrolment, verification success/failure, removal, backup code generation, passkey registration/removal) to `audit_log` table
    - _Requirements: 9.1, 9.2, 9.3, 10.1, 10.2, 10.3_

  - [x] 7.2 Write property tests for rate limiting and security (Properties 20–23)
    - **Property 20: Destructive MFA operations require password confirmation** — verify rejection without valid password
    - **Validates: Requirements 7.1, 13.3**
    - **Property 21: OTP rate limiting (5 per method per 15 minutes)** — 5 sends succeed, 6th rejected, SMS/email independent
    - **Validates: Requirements 9.1, 9.2, 9.3**
    - **Property 22: MFA endpoints require authenticated session** — requests without JWT get 401
    - **Validates: Requirements 10.1, 10.2**
    - **Property 23: Audit logging for all MFA operations** — verify audit_log entries for each operation type
    - **Validates: Requirements 10.3**

- [x] 8. Backend passkey (WebAuthn) service layer
  - [x] 8.1 Implement passkey registration in `app/modules/auth/service.py`
    - `generate_passkey_register_options()`: generate WebAuthn registration challenge via `py_webauthn`, set RP ID to BudgetFlow domain, 60s timeout, exclude existing credential IDs, enforce max 10 credentials
    - `verify_passkey_registration()`: verify attestation response, extract public key and credential ID, store in `user_passkey_credentials` with user-provided `device_name`, ensure `passkey` entry in `user_mfa_methods`
    - Store registration challenge in Redis with 60s TTL
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [x] 8.2 Implement passkey authentication in `app/modules/auth/service.py`
    - `generate_passkey_login_options()`: generate WebAuthn assertion challenge with user's non-flagged credential IDs, 60s timeout
    - `verify_passkey_login()`: verify assertion signature against stored public key, update sign count if S' > S, flag credential and reject if S' ≤ S (clone detection), issue JWT tokens on success
    - Store assertion challenge in Redis with 60s TTL
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 8.3 Implement passkey management in `app/modules/auth/service.py`
    - `list_passkey_credentials()`: return all credentials with `credential_id`, `device_name`, `created_at`, `last_used_at`
    - `rename_passkey()`: update `device_name` (max 50 chars)
    - `remove_passkey()`: verify password, check last-method guard, delete credential from `user_passkey_credentials`
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [x] 8.4 Write property tests for passkey operations (Properties 24–31)
    - **Property 24: WebAuthn registration options correctness** — verify RP ID, 60s timeout, exclude list contains existing credentials
    - **Validates: Requirements 11.1, 11.2**
    - **Property 25: Passkey friendly name persistence** — verify name stored on registration, updated on rename
    - **Validates: Requirements 11.4, 13.2**
    - **Property 26: Passkey credential limit enforcement** — 10 credentials registered, 11th rejected
    - **Validates: Requirements 11.6**
    - **Property 27: WebAuthn assertion options contain user credentials** — verify allow list with non-flagged credential IDs, 60s timeout
    - **Validates: Requirements 12.1**
    - **Property 28: Sign count monotonic update** — verify sign count updated when S' > S
    - **Validates: Requirements 12.3**
    - **Property 29: Clone detection via sign count** — verify rejection and flagging when S' ≤ S
    - **Validates: Requirements 12.5**
    - **Property 30: Passkey list returns complete credential info** — verify all fields present for each credential
    - **Validates: Requirements 13.1**
    - **Property 31: Passkey removal deletes credential** — verify credential gone after password-confirmed removal
    - **Validates: Requirements 13.4**

- [x] 9. Checkpoint — Backend service layer complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Backend API endpoints (router)
  - [x] 10.1 Add MFA enrolment and management endpoints to `app/modules/auth/router.py`
    - `POST /mfa/enrol` — call `enrol_mfa()`, return `MFAEnrolResponse`
    - `POST /mfa/enrol/verify` — call `verify_enrolment()`, return success
    - `GET /mfa/methods` — call `get_user_mfa_status()`, return list of `MFAMethodStatus`
    - `DELETE /mfa/methods/{method}` — call `disable_mfa_method()`, accept `MFADisableRequest` body
    - `POST /mfa/backup-codes` — call `generate_backup_codes()`, return `MFABackupCodesResponse`
    - _Requirements: 1.1–1.4, 2.1–2.4, 3.1–3.4, 4.4, 4.5, 5.1–5.3, 7.1–7.4_

  - [x] 10.2 Add MFA challenge endpoints to `app/modules/auth/router.py`
    - `POST /mfa/challenge/send` — call `send_challenge_otp()`, accept `MFAChallengeSendRequest`
    - `POST /mfa/verify` — call `verify_mfa()`, accept `MFAVerifyRequest`, return JWT tokens on success
    - Update existing `POST /auth/login` to return `MFAChallengeResponse` when user has MFA methods
    - _Requirements: 6.1–6.7_

  - [x] 10.3 Add passkey endpoints to `app/modules/auth/router.py`
    - `POST /passkey/register/options` — call `generate_passkey_register_options()`
    - `POST /passkey/register/verify` — call `verify_passkey_registration()`
    - `POST /passkey/login/options` — call `generate_passkey_login_options()`
    - `POST /passkey/login/verify` — call `verify_passkey_login()`
    - `GET /passkey/credentials` — call `list_passkey_credentials()`
    - `PATCH /passkey/credentials/{credential_id}` — call `rename_passkey()`, accept `PasskeyRenameRequest`
    - `DELETE /passkey/credentials/{credential_id}` — call `remove_passkey()`, accept `PasskeyRemoveRequest`
    - _Requirements: 11.1–11.6, 12.1–12.5, 13.1–13.5_

  - [x] 10.4 Add Pydantic request/response schemas to `app/modules/auth/schemas.py`
    - Add all schemas from the design: `MFAEnrolRequest`, `MFAEnrolResponse`, `MFAEnrolVerifyRequest`, `MFAChallengeResponse`, `MFAChallengeSendRequest`, `MFAVerifyRequest`, `MFAMethodStatus`, `MFADisableRequest`, `PasskeyCredentialInfo`, `PasskeyRenameRequest`, `PasskeyRemoveRequest`, `MFABackupCodesResponse`
    - _Requirements: 1.1–14.3_

- [x] 11. Checkpoint — Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Frontend MFA settings components
  - [x] 12.1 Create `MfaSettings` panel at `frontend/src/pages/settings/MfaSettings.tsx`
    - Fetch MFA method statuses via `GET /mfa/methods`
    - Render method cards for TOTP, SMS, Email, Passkey with enabled/disabled status
    - Include backup codes section showing generation status and generate/regenerate button
    - Display success confirmations after enrolment or disable actions
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7_

  - [x] 12.2 Create `MfaMethodCard` component at `frontend/src/components/mfa/MfaMethodCard.tsx`
    - Display method name, status (enabled/disabled), and enable/disable action button
    - "Enable" opens the enrolment wizard for that method
    - "Disable" triggers `PasswordConfirmModal` before calling `DELETE /mfa/methods/{method}`
    - _Requirements: 8.2, 8.3, 8.4_

  - [x] 12.3 Create `TotpEnrolWizard` at `frontend/src/components/mfa/TotpEnrolWizard.tsx`
    - Step 1: Call `POST /mfa/enrol` with `method: "totp"`, display QR code and plain-text secret for manual entry
    - Step 2: Code input field, submit to `POST /mfa/enrol/verify`
    - Show success or error feedback
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 8.6_

  - [x] 12.4 Create `SmsEnrolWizard` at `frontend/src/components/mfa/SmsEnrolWizard.tsx`
    - Phone number input with international format validation
    - Call `POST /mfa/enrol` with `method: "sms"` and `phone_number`
    - OTP code input, submit to `POST /mfa/enrol/verify`
    - Handle SMS delivery failure with retry option
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 2.6, 8.6_

  - [x] 12.5 Create `EmailEnrolWizard` at `frontend/src/components/mfa/EmailEnrolWizard.tsx`
    - Call `POST /mfa/enrol` with `method: "email"` to send OTP
    - OTP code input, submit to `POST /mfa/enrol/verify`
    - Handle email delivery failure with retry option
    - _Requirements: 3.1, 3.3, 3.4, 3.5, 8.6_

  - [x] 12.6 Create `BackupCodesPanel` at `frontend/src/components/mfa/BackupCodesPanel.tsx`
    - Show whether backup codes have been generated
    - Generate/regenerate button calls `POST /mfa/backup-codes`
    - Display codes with warning they are shown only once
    - Copy-to-clipboard and download-as-text-file options
    - _Requirements: 5.4, 5.5, 8.5_

  - [x] 12.7 Create `PasswordConfirmModal` at `frontend/src/components/mfa/PasswordConfirmModal.tsx`
    - Reusable modal prompting for current password before destructive actions
    - Returns password to caller on confirm, cancels on dismiss
    - _Requirements: 7.1, 8.4, 13.3_

- [x] 13. Frontend passkey components
  - [x] 13.1 Create `PasskeyManager` at `frontend/src/components/mfa/PasskeyManager.tsx`
    - Check WebAuthn API availability via `window.PublicKeyCredential`; disable passkey features and show message if unsupported
    - List registered passkeys via `GET /passkey/credentials` showing friendly name, registration date, last used date
    - "Register new passkey" button: call `POST /passkey/register/options`, invoke `navigator.credentials.create()`, send attestation to `POST /passkey/register/verify`
    - Prompt for device name during registration
    - "Rename" action per passkey: call `PATCH /passkey/credentials/{id}`
    - "Remove" action per passkey: trigger `PasswordConfirmModal`, call `DELETE /passkey/credentials/{id}`
    - _Requirements: 11.7, 13.1, 13.2, 13.3, 13.4, 13.6, 14.1, 14.2, 14.3_

- [x] 14. Frontend MFA challenge page
  - [x] 14.1 Create `MfaChallengePage` at `frontend/src/pages/auth/MfaChallenge.tsx`
    - Receive `mfa_token` and `methods` list from login response
    - Display method selection buttons for each available method
    - For SMS/email: call `POST /mfa/challenge/send`, show code input, submit to `POST /mfa/verify`
    - For TOTP: show code input directly, submit to `POST /mfa/verify`
    - For backup code: show code input, submit to `POST /mfa/verify` with `method: "backup"`
    - For passkey: call `POST /passkey/login/options`, invoke `navigator.credentials.get()`, send assertion to `POST /passkey/login/verify`
    - Handle lockout (429) and expired token (401) errors with appropriate messages
    - On success, store JWT tokens and redirect to dashboard
    - _Requirements: 4.2, 4.3, 6.1–6.7, 12.1, 12.2, 12.4_

- [x] 15. Wire frontend into existing app
  - [x] 15.1 Integrate MFA settings into Profile page and update login flow
    - Replace the read-only MFA section in `frontend/src/pages/settings/Profile.tsx` with the new `MfaSettings` component
    - Update the login page/flow to redirect to `MfaChallengePage` when the login response contains `mfa_required: true`
    - Add routes for the MFA challenge page
    - _Requirements: 8.1, 6.1_

- [x] 16. Checkpoint — Frontend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Frontend property and unit tests
  - [x] 17.1 Write frontend property tests using fast-check
    - MFA method status display logic: method card renders correct state for all combinations of enabled/disabled methods
    - Backup code formatting: codes display correctly, copy/download produce valid output
    - WebAuthn API detection: passkey features enabled/disabled based on browser support
    - Test file: `frontend/src/pages/settings/__tests__/mfa-settings.properties.test.ts`
    - _Requirements: 8.2, 5.4, 5.5, 14.1, 14.2, 14.3_

  - [x] 17.2 Write frontend unit tests using Vitest and React Testing Library
    - Test each enrolment wizard renders steps correctly and handles success/error states
    - Test `MfaChallengePage` method selection and code submission flows
    - Test `PasskeyManager` list, register, rename, remove interactions
    - Test `PasswordConfirmModal` confirm and cancel behavior
    - Test file: `frontend/src/pages/settings/__tests__/mfa-settings.test.tsx`
    - _Requirements: 8.2–8.7, 11.7, 13.1, 13.6_

- [x] 18. Final checkpoint — All tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use Hypothesis (Python backend) and fast-check (TypeScript frontend)
- Checkpoints ensure incremental validation at service layer, full backend, and frontend milestones
- All 31 correctness properties from the design are covered across tasks 2.3, 2.4, 3.2, 4.2, 6.2, 7.2, and 8.4
