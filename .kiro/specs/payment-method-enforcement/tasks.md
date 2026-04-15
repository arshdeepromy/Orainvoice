# Implementation Plan: Payment Method Enforcement

## Overview

Implement a post-login enforcement layer that checks whether an org_admin's organisation has a valid payment method. The backend provides a lightweight status endpoint (local DB only, no Stripe calls). The frontend hook fires after login for org_admin users and renders a blocking modal (no payment method) or a warning modal (card expiring within 30 days) at the OrgLayout level.

## Tasks

- [x] 1. Add backend Pydantic schemas and expiry logic
  - [x] 1.1 Add `ExpiringMethodDetail` and `PaymentMethodStatusResponse` schemas to `app/modules/billing/schemas.py`
    - `ExpiringMethodDetail`: `brand`, `last4`, `exp_month`, `exp_year`
    - `PaymentMethodStatusResponse`: `has_payment_method` (bool), `has_expiring_soon` (bool), `expiring_method` (ExpiringMethodDetail | None)
    - Field names must match exactly what the frontend will consume
    - _Requirements: 4.2, 4.7_

  - [x] 1.2 Implement `is_expiring_soon` pure function in `app/modules/billing/utils.py`
    - Accepts `exp_month: int`, `exp_year: int`, `reference_date: date | None = None`
    - Returns `True` when the last calendar day of `exp_month/exp_year` is ≤ `reference_date + 30 days`
    - Uses `calendar.monthrange` for correct last-day-of-month handling (28/29/30/31)
    - Must handle leap years and year boundaries correctly
    - _Requirements: 4.3_

  - [x] 1.3 Write property test for `is_expiring_soon` (Property 2: Expiry date boundary correctness)
    - **Property 2: Expiry date boundary correctness**
    - **Validates: Requirements 4.3**
    - Test file: `tests/test_payment_method_status_properties.py`
    - Use Hypothesis to generate arbitrary `(exp_month, exp_year, reference_date)` combinations
    - Assert: function returns `True` iff last calendar day of exp_month/exp_year ≤ reference_date + 30 days
    - Cover month boundaries, year boundaries, leap years
    - Minimum 100 iterations
    - Tag: `# Feature: payment-method-enforcement, Property 2: Expiry date boundary correctness`

- [x] 2. Implement the payment method status API endpoint
  - [x] 2.1 Add `GET /payment-method-status` endpoint to `app/modules/billing/router.py`
    - Add route with `response_model=PaymentMethodStatusResponse`
    - Allow all authenticated roles via `require_role` dependency
    - Extract `org_id` from `request.state.user`; if `org_id is None`, return safe defaults (`has_payment_method=True`, `has_expiring_soon=False`, `expiring_method=None`)
    - Query `org_payment_methods` table for the org (local DB only, no Stripe API calls)
    - Set `has_payment_method = True` if any rows exist
    - Use `is_expiring_soon` to check each method; find the soonest-expiring one
    - Return only `brand`, `last4`, `exp_month`, `exp_year` — never expose `stripe_payment_method_id` or internal IDs
    - Error responses must not leak stack traces, SQL, or file paths
    - Import the new schemas and `is_expiring_soon` utility
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [x] 2.2 Write property test for payment method status computation (Property 1)
    - **Property 1: Payment method status computation correctness**
    - **Validates: Requirements 1.3, 4.2**
    - Test file: `tests/test_payment_method_status_properties.py`
    - Use Hypothesis to generate sets of `(exp_month, exp_year)` pairs (0 to N methods)
    - Assert: `has_payment_method` is `True` iff set is non-empty
    - Assert: `has_expiring_soon` is `True` iff at least one method is expiring within 30 days
    - Assert: `expiring_method` is the soonest-expiring among those within 30 days, or `None`
    - Minimum 100 iterations
    - Tag: `# Feature: payment-method-enforcement, Property 1: Payment method status computation correctness`

  - [x] 2.3 Write unit tests for the status endpoint
    - Test file: `tests/test_payment_method_status.py`
    - Test: org with 0 payment methods → `has_payment_method=False`
    - Test: org with 1 non-expiring method → `has_payment_method=True`, `has_expiring_soon=False`
    - Test: org with multiple methods, one expiring → correct `expiring_method` returned
    - Test: `org_id=None` (global_admin) → safe defaults
    - Test: response contains only allowed fields (no `stripe_payment_method_id` leakage)
    - _Requirements: 1.3, 4.2, 4.4, 4.5, 4.7_

- [x] 3. Checkpoint — Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Create the `usePaymentMethodEnforcement` hook
  - [x] 4.1 Create `frontend/src/hooks/usePaymentMethodEnforcement.ts`
    - Define `ExpiringMethod`, `PaymentMethodStatus`, and `EnforcementState` interfaces
    - Only fetch when `user.role === 'org_admin'` (from `useAuth()`) — all other roles skip entirely
    - Call `GET /api/v1/billing/payment-method-status` with `AbortController` cleanup in `useEffect`
    - Guard all response access: `res.data?.has_payment_method ?? true`, `res.data?.has_expiring_soon ?? false`, `res.data?.expiring_method ?? null`
    - On API error or non-200: fail-open (`showBlockingModal=false`, `showWarningModal=false`), log error to console
    - Expose `showBlockingModal`, `showWarningModal`, `expiringMethod`, `loading`, `dismissWarning()`, `refetchStatus()`
    - `dismissWarning()` sets `showWarningModal=false` for the current session
    - `refetchStatus()` re-calls the endpoint (used after adding a card)
    - Use typed API call with generic: `apiClient.get<PaymentMethodStatus>(...)` — no `as any`
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 5. Create modal components
  - [x] 5.1 Create `frontend/src/components/billing/BlockingPaymentModal.tsx`
    - Use existing `<Modal>` component without close button (no dismiss mechanism)
    - Display clear message: payment method required to continue
    - Embed Stripe `<Elements>` + `<CardElement>` flow (same pattern as `CardForm` in `Billing.tsx`)
    - On successful SetupIntent confirmation → call `refetchStatus()` via `onSuccess` prop
    - Modal auto-dismisses when `has_payment_method` becomes `true`
    - Never display Stripe secret keys, `stripe_payment_method_id`, or masked credentials in UI
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 5.2 Create `frontend/src/components/billing/ExpiringPaymentWarningModal.tsx`
    - Use existing `<Modal>` component with dismiss button
    - Display card brand, last 4 digits, and expiry month/year from `expiringMethod` prop
    - "Update Payment Method" button → `navigate('/settings?tab=billing')`
    - "Dismiss" button → calls `onDismiss` prop (which triggers `dismissWarning()`)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 6. Integrate enforcement into OrgLayout
  - [x] 6.1 Wire hook and modals into `frontend/src/layouts/OrgLayout.tsx`
    - Import and call `usePaymentMethodEnforcement()` inside `OrgLayout`
    - Render `<BlockingPaymentModal>` and `<ExpiringPaymentWarningModal>` at the top of the JSX, above `<Outlet />`
    - Pass `open={showBlockingModal}` and `onSuccess={refetchStatus}` to blocking modal
    - Pass `open={showWarningModal && !showBlockingModal}` to warning modal (blocking takes priority per requirement 3.6)
    - Pass `expiringMethod` and `onDismiss={dismissWarning}` to warning modal
    - _Requirements: 2.1, 3.1, 3.6_

- [x] 7. Checkpoint — Frontend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. End-to-end test script
  - [x] 8.1 Create `scripts/test_payment_method_enforcement_e2e.py`
    - Follow feature-testing-workflow steering pattern (httpx, asyncio, ok/fail helpers)
    - Login as org_admin, call status endpoint, verify response structure
    - Insert test payment methods via direct DB (asyncpg), verify status response correctness
    - Insert card expiring within 30 days, verify `has_expiring_soon=true` and correct `expiring_method`
    - Login as global_admin, verify safe default response (`has_payment_method=true`)
    - OWASP A1: unauthenticated access → 401
    - OWASP A1: cross-org access → returns only own org's data
    - OWASP A2: response contains no `stripe_payment_method_id` or secret keys
    - OWASP A5: error responses contain no stack traces or internal paths
    - Clean up all test payment method records after tests
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests validate the `is_expiring_soon` pure function and status computation logic using Hypothesis
- No database migrations are needed — the existing `org_payment_methods` table has all required fields
- The Stripe SetupIntent flow in the blocking modal reuses the existing `CardForm` pattern from `Billing.tsx`
