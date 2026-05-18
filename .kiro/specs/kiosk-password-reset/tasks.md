# Implementation Plan: Kiosk User Password Reset by Org Admin

## Overview

This plan implements the ability for an org admin to reset a kiosk user's password from the User Management page. The feature adds a backend endpoint to the existing organisations router, a service function, Pydantic schemas, and a frontend modal with a "Reset Password" button in the user table.

## Tasks

- [x] 1. Add backend schema, service function, and endpoint
  - [x] 1.1 Add `KioskPasswordResetRequest` and `KioskPasswordResetResponse` schemas in `app/modules/organisations/schemas.py`
    - `KioskPasswordResetRequest`: new_password (str, min_length=8, max_length=128)
    - `KioskPasswordResetResponse`: message (str), user_id (str), sessions_invalidated (int)
    - _Requirements: 4.3, 4.4, 4.5_
  - [x] 1.2 Add `reset_kiosk_user_password()` function in `app/modules/organisations/service.py`
    - Accept org_id, acting_user_id, target_user_id, new_password, ip_address
    - Query target user: verify exists, belongs to org, role == "kiosk", is_active == True
    - Hash new password using `hash_password()` from `app/modules/auth/password.py`
    - Update user.password_hash, flush
    - Delete all sessions for target user (from `app.modules.auth.models.Session`)
    - Write audit log with action `auth.kiosk_password_reset`
    - Return dict with user_id and sessions_invalidated count
    - Raise ValueError for validation failures (not found, wrong role, inactive)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 7.1, 7.2, 8.1, 8.2, 8.3, 8.4_
  - [x] 1.3 Add `POST /users/{target_user_id}/reset-password` endpoint in `app/modules/organisations/router.py`
    - Use `dependencies=[require_role("org_admin")]`
    - Set `response_model=KioskPasswordResetResponse`
    - Parse UUIDs, call `reset_kiosk_user_password()`, handle ValueError → 400/404
    - Return 200 with success message
    - _Requirements: 4.1, 4.2, 4.4, 4.5_

- [x] 2. Add backend tests
  - [x] 2.1 Write unit tests for `reset_kiosk_user_password()` service function
    - Test successful reset: password hash updated, sessions deleted, audit log written
    - Test failure: target not found → ValueError
    - Test failure: target not kiosk role → ValueError
    - Test failure: target inactive → ValueError
    - Test failure: target in different org → ValueError
    - _Requirements: 5.1–5.6, 6.1, 6.2, 7.1, 8.1_
  - [x] 2.2 Write property test for password hash roundtrip (Property 2 from design)
    - Generate random passwords (8–128 chars), verify hash_password → verify_password roundtrip
    - _Requirements: 6.1_
  - [x] 2.3 Write property test for role restriction (Property 1 from design)
    - Generate random role strings, verify only "kiosk" passes the role check
    - _Requirements: 5.3, 5.4_

- [x] 3. Add frontend Reset Password modal and button
  - [x] 3.1 Add "Reset Password" button to the actions column in `UserManagement.tsx`
    - Only render for users where `row.role === 'kiosk' && row.is_active`
    - Use `variant="secondary"` and `size="sm"`
    - On click: open reset password modal with user id and email
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [x] 3.2 Add ResetPasswordModal (inline in `UserManagement.tsx` or as state-driven modal)
    - Modal title: "Reset Kiosk Password"
    - Display target user email for confirmation
    - Two password inputs: "New Password" and "Confirm Password"
    - Client-side validation: min 8 chars, passwords match
    - Submit button disabled until validation passes
    - On submit: POST `/org/users/${userId}/reset-password` with `{ new_password }`
    - On success: close modal, show success toast, refresh user list
    - On error: show error toast, keep modal open
    - _Requirements: 2.1–2.7, 3.1–3.4, 9.1–9.3, 10.1–10.3_

- [x] 4. Write e2e test script (per feature-testing-workflow steering doc)
  - [x] 4.1 Create `scripts/test_kiosk_password_reset_e2e.py`
    - Login as org_admin
    - Call POST `/org/users/{kiosk_user_id}/reset-password` with valid new password
    - Verify 200 response with `sessions_invalidated` count
    - Verify kiosk user can login with new password
    - Verify kiosk user CANNOT login with old password
    - OWASP A1 (Broken Access Control): Try without token → expect 401
    - OWASP A1: Try with salesperson token → expect 403
    - OWASP A1: Try targeting a non-kiosk user → expect 400
    - OWASP A1: Try targeting a user in a different org → expect 404
    - OWASP A3 (Injection): Send SQL injection payload in password field → expect normal 200 (stored as hash)
    - Cleanup: Reset kiosk user password back to original after test
    - _Requirements: 4.1, 4.2, 5.1–5.6, 6.1, 7.1_

- [x] 5. Verify and deploy
  - [x] 5.1 Run backend property tests (only this feature): `pytest tests/test_kiosk_password_reset_properties.py --no-header -q`
  - [x] 5.2 Run frontend TypeScript check on changed file only: `npx tsc --noEmit` in frontend/ (verify zero errors in `UserManagement.tsx`)
  - [x] 5.3 Run e2e test: `docker exec invoicing-app-1 python scripts/test_kiosk_password_reset_e2e.py`
  - [x] 5.4 Verify the endpoint is accessible via the existing org router registration (no new router registration needed since it's added to the existing organisations router)
    - Do NOT run the full test suite — only tests relevant to this feature
    - _Requirements: 4.1_

## Notes

- The endpoint is added to the existing `app/modules/organisations/router.py` which is already registered in `app/main.py` — no new router registration needed.
- Uses `flush()` not `commit()` in the service function (auto-commit via session.begin() context manager).
- No HIBP check on the new password — kiosk passwords are admin-set, not user-chosen, and the kiosk is a shared device.
- No password policy enforcement beyond min 8 chars — kiosk accounts are simpler than regular user accounts.
- **Read `revoke_user_sessions()` in `app/modules/organisations/service.py` FIRST** before implementing session deletion — match the existing pattern exactly (per no-shortcut-implementations steering doc).
- The frontend follows safe API consumption patterns: `?.` and `?? fallback` on all API response data, typed generics on the API call, AbortController cleanup if any useEffect is added (per safe-api-consumption steering doc).
- The modal is kept simple (inline state in UserManagement.tsx) to match the existing pattern for the invite modal.
- The modal's submit handler should use typed generic: `apiClient.post<KioskPasswordResetResponse>(...)` and guard response with `res.data?.message ?? ''` (per frontend-backend-contract Rule 5).
- OWASP security checks are covered in the e2e test script (per feature-testing-workflow steering doc).
