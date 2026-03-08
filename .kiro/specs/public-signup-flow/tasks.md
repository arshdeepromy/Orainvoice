# Implementation Plan: Public Signup Flow

## Overview

Implement the frontend public signup flow with two new pages (SignupPage, VerifyEmailPage), a new backend public plans endpoint, route registration, and a signup link on the Login page. Each task builds incrementally, starting with shared types and validation, then backend, then frontend components, then wiring routes together.

## Tasks

- [x] 1. Create TypeScript interfaces and validation functions
  - [x] 1.1 Create shared types file at `frontend/src/pages/auth/signup-types.ts`
    - Define `SignupFormData`, `SignupResponse`, `PublicPlan`, `PublicPlanListResponse`, `VerifyEmailRequest`, `VerifyEmailResponse` interfaces
    - _Requirements: 1.1, 2.1, 3.1, 6.1_

  - [x] 1.2 Create validation functions file at `frontend/src/pages/auth/signup-validation.ts`
    - Implement `validateSignupForm(data: SignupFormData): Record<string, string>` — validates org_name (1–255 chars), admin_email (email format), admin_first_name (1–100 chars), admin_last_name (1–100 chars), plan_id (non-empty)
    - Implement `validateVerifyEmailForm(password: string, confirmPassword: string): Record<string, string>` — validates password (≥10 chars) and confirm match
    - Export as pure functions for testability
    - _Requirements: 1.6, 1.7, 1.8, 3.7, 3.8_

  - [x] 1.3 Write property tests for signup form validation (fast-check)
    - **Property 1: Field length validation rejects out-of-bounds strings**
    - **Validates: Requirements 1.6, 1.8**

  - [x] 1.4 Write property tests for email validation (fast-check)
    - **Property 2: Email format validation rejects invalid emails**
    - **Validates: Requirements 1.7**

  - [x] 1.5 Write property tests for verify-email form validation (fast-check)
    - **Property 5: Password minimum length validation**
    - **Validates: Requirements 3.7**

  - [x] 1.6 Write property test for password confirmation match (fast-check)
    - **Property 6: Password confirmation match validation**
    - **Validates: Requirements 3.8**

- [x] 2. Add backend public plans endpoint
  - [x] 2.1 Add `PublicPlanResponse` and `PublicPlanListResponse` schemas to `app/modules/auth/schemas.py`
    - `PublicPlanResponse`: id (str), name (str), monthly_price_nzd (Decimal)
    - `PublicPlanListResponse`: plans (list[PublicPlanResponse])
    - _Requirements: 6.1, 6.2_

  - [x] 2.2 Add `GET /api/v1/auth/plans` endpoint to `app/modules/auth/router.py`
    - No authentication required
    - Query subscription plans where `is_public=True` and `is_archived=False`
    - Return `PublicPlanListResponse`
    - _Requirements: 6.1, 6.2_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement SignupPage component
  - [x] 4.1 Create `frontend/src/pages/auth/Signup.tsx`
    - Multi-step component with `step` state: `'form' | 'stripe' | 'done'`
    - **Form step**: Render form with org_name, admin_email, admin_first_name, admin_last_name fields and plan selector dropdown
    - Fetch plans from `GET /api/v1/auth/plans` on mount; show "Signup is temporarily unavailable" if empty list returned; show retry on fetch error
    - Use `validateSignupForm` for client-side validation before submission
    - On submit: POST to `/api/v1/auth/signup` with form data; disable submit button and show loading indicator while in progress
    - On success: store `signup_token` and `stripe_setup_intent_client_secret` in state, transition to `'stripe'` step
    - On 400 error: display `detail` from response in AlertBanner
    - **Stripe step**: Load Stripe.js with `loadStripe()` using env var publishable key; render `<Elements>` + `<CardElement>` from `@stripe/react-stripe-js`; call `stripe.confirmCardSetup(clientSecret)` on confirm
    - On Stripe success: transition to `'done'` step
    - On Stripe error: display `error.message` in AlertBanner, allow retry
    - **Done step**: Display confirmation message instructing user to check their email
    - Use existing `Button`, `Input`, `AlertBanner`, `Spinner` components
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 6.1, 6.2, 6.3, 6.4, 7.1_

  - [x] 4.2 Write unit tests for SignupPage in `frontend/src/__tests__/signup-flow.test.tsx`
    - Test form fields render correctly
    - Test plan selector renders fetched plans
    - Test form validation prevents submission with invalid data
    - Test API call on valid submission
    - Test transition to Stripe step on success
    - Test error display on API 400
    - Test loading state during submission
    - Test empty plans shows unavailable message
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 6.1, 6.2, 6.3, 6.4_

  - [x] 4.3 Write property test for signup error message passthrough (fast-check)
    - **Property 3: Signup page error message passthrough**
    - **Validates: Requirements 1.4, 2.4**

  - [x] 4.4 Write property test for plan display completeness (fast-check)
    - **Property 7: Plan display completeness**
    - **Validates: Requirements 6.2**

- [x] 5. Implement VerifyEmailPage component
  - [x] 5.1 Create `frontend/src/pages/auth/VerifyEmail.tsx`
    - Extract `token` from URL query params via `useSearchParams()`
    - If token missing: display "This verification link is invalid." error, no form shown
    - Render password and confirm-password fields
    - Use `validateVerifyEmailForm` for client-side validation
    - On submit: POST to `/api/v1/auth/verify-email` with `{ token, password }`
    - On success: store `access_token` and `refresh_token` via existing auth helpers, redirect to `/setup`
    - On 400 error: display `detail` from response in AlertBanner
    - Use existing `Button`, `Input`, `AlertBanner` components
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 7.2_

  - [x] 5.2 Write unit tests for VerifyEmailPage in `frontend/src/__tests__/signup-flow.test.tsx`
    - Test password fields render
    - Test missing token shows error
    - Test API call with token and password
    - Test token storage and redirect on success
    - Test error display on API 400
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 5.3 Write property test for verify-email error message passthrough (fast-check)
    - **Property 4: Verify page error message passthrough**
    - **Validates: Requirements 3.6**

- [x] 6. Wire routes and update existing components
  - [x] 6.1 Export new components from `frontend/src/pages/auth/index.ts`
    - Add `export { Signup } from './Signup'` and `export { VerifyEmail } from './VerifyEmail'`
    - _Requirements: 4.1, 4.2_

  - [x] 6.2 Add routes to `frontend/src/App.tsx`
    - Add `<Route path="/signup" element={<Signup />} />` and `<Route path="/verify-email" element={<VerifyEmail />} />` inside the existing `<Route element={<GuestOnly />}>` block
    - Add import for `Signup` and `VerifyEmail` from `@/pages/auth`
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 6.3 Add signup link to `frontend/src/pages/auth/Login.tsx`
    - Add "Don't have an account? Sign up" link below the sign-in form, using `<Link to="/signup">`
    - _Requirements: 5.1, 5.2_

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using fast-check
- Unit tests validate specific examples and edge cases using Vitest + React Testing Library
- Validation functions are extracted as pure functions to enable direct property-based testing without rendering React components
