# Implementation Plan: Multi-Step Signup Wizard

## Overview

Rebuild the signup flow to defer account creation for paid plans until after Stripe payment succeeds. The backend stores validated form data in Redis as a Pending_Signup, creates a Stripe PaymentIntent, and only creates Organisation/User records after payment confirmation. The frontend is refactored into a multi-step wizard (form → payment → confirmation) with animated transitions on a single page. Trial plans continue to create accounts immediately.

## Tasks

- [x] 1. Update backend schemas and types
  - [x] 1.1 Update `PublicSignupRequest` to add optional `coupon_code` field
    - Modify the Pydantic model in `app/modules/auth/router.py` (or its schema file) to add `coupon_code: str | None = None`
    - _Requirements: 5.1, 5.2_

  - [x] 1.2 Update `PublicSignupResponse` to include `pending_signup_id`, `stripe_client_secret`, and `plan_name`
    - Add `pending_signup_id: str | None = None`, `stripe_client_secret: str | None = None`, `plan_name: str | None = None` fields
    - Remove `organisation_id` from required fields (make optional) since paid plans won't have one yet
    - Ensure `requires_payment`, `payment_amount_cents`, `admin_email` are present
    - _Requirements: 1.1, 2.3_

  - [x] 1.3 Create `ConfirmPaymentRequest` schema with `payment_intent_id` and `pending_signup_id` fields
    - Replace the current `organisation_id` based lookup with `pending_signup_id`
    - _Requirements: 7.1_

- [x] 2. Implement Redis Pending Signup storage
  - [x] 2.1 Create a `pending_signup` service module (`app/modules/auth/pending_signup.py`)
    - Implement `create_pending_signup(data: dict) -> str` that generates a UUID, stores JSON in Redis key `pending_signup:{uuid}` with TTL 1800s, and creates the `pending_email:{sha256(email)}` index key
    - Implement `get_pending_signup(pending_signup_id: str) -> dict | None` that retrieves and parses the JSON
    - Implement `delete_pending_signup(pending_signup_id: str)` that deletes both the signup key and the email index key
    - Implement `replace_pending_signup_for_email(email: str, data: dict) -> str` that checks for existing pending signup via the email index, deletes it if found, and creates a new one
    - Hash the password with bcrypt before storing in Redis
    - _Requirements: 1.1, 6.1, 6.2, 6.3, 7.2_

  - [x] 2.2 Write property test: Paid plan pending signup (Property 1)
    - **Property 1: Paid plan signup creates pending signup with TTL and no database records**
    - Generate random valid form data with paid plans, verify Redis key exists with 1800s TTL and no DB records created
    - File: `tests/properties/test_signup_wizard_properties.py`
    - **Validates: Requirements 1.1, 6.1**

  - [x] 2.3 Write property test: Duplicate email replacement (Property 10)
    - **Property 10: Duplicate email replaces existing pending signup**
    - Submit two signups with the same email, verify only one pending signup exists in Redis
    - File: `tests/properties/test_signup_wizard_properties.py`
    - **Validates: Requirements 6.3**

- [x] 3. Modify `POST /auth/signup` endpoint for deferred account creation
  - [x] 3.1 Implement paid plan flow in the signup endpoint
    - When `trial_duration == 0` on the selected plan: validate CAPTCHA, check email not registered, hash password, apply coupon if provided, store Pending_Signup in Redis, create Stripe PaymentIntent (without Stripe Customer), return `{requires_payment: true, pending_signup_id, stripe_client_secret, payment_amount_cents, plan_name}`
    - Do NOT create Organisation or User records for paid plans
    - Use `replace_pending_signup_for_email()` to handle duplicate emails
    - Modify `app/modules/auth/router.py` function `signup()` and the underlying service function
    - _Requirements: 1.1, 6.3, 7.3, 7.4_

  - [x] 3.2 Implement coupon discount calculation in signup
    - Validate coupon via existing coupon validation logic
    - For percentage coupons: `amount = round(price * (1 - discount/100))`
    - For fixed-amount coupons: `amount = max(0, price - discount)`
    - If effective price is zero: skip PaymentIntent, create account immediately, return `requires_payment: false`
    - For trial-extension coupons on paid plans: convert to trial flow with extended duration
    - _Requirements: 5.2, 5.3, 5.4_

  - [x] 3.3 Keep trial plan flow unchanged
    - When `trial_duration > 0`: create Organisation + User immediately (existing logic), send verification email, return `{requires_payment: false}`
    - Ensure the response includes `organisation_id` and `trial_ends_at` for trial plans
    - _Requirements: 1.5_

  - [x] 3.4 Write property test: Trial plan immediate creation (Property 4)
    - **Property 4: Trial plan creates account immediately**
    - Generate random valid form data with trial plans, verify DB records created and `requires_payment: false`
    - File: `tests/properties/test_signup_wizard_properties.py`
    - **Validates: Requirements 1.5**

  - [x] 3.5 Write property test: Coupon discount calculation (Property 8)
    - **Property 8: Coupon discount correctly applied to PaymentIntent amount**
    - Generate random prices and coupon values, verify `round(P * (1 - D/100))` for percentage and `max(0, P - F)` for fixed
    - File: `tests/properties/test_signup_wizard_properties.py`
    - **Validates: Requirements 5.2**

  - [x] 3.6 Write property test: Trial-extension coupon (Property 9)
    - **Property 9: Trial-extension coupon converts paid plan to trial**
    - Generate random paid plans + trial-extension coupons, verify trial conversion with correct `trial_ends_at`
    - File: `tests/properties/test_signup_wizard_properties.py`
    - **Validates: Requirements 5.4**

  - [x] 3.7 Write property test: CAPTCHA/email rejection (Property 11)
    - **Property 11: Signup rejects invalid CAPTCHA or already-registered email**
    - Generate invalid CAPTCHAs and existing emails, verify rejection without creating pending signup or DB records
    - File: `tests/properties/test_signup_wizard_properties.py`
    - **Validates: Requirements 7.3, 7.4**

- [x] 4. Checkpoint - Ensure all backend signup tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Rewrite `POST /auth/signup/confirm-payment` endpoint
  - [x] 5.1 Refactor confirm-payment to use `pending_signup_id` instead of `organisation_id`
    - Accept `ConfirmPaymentRequest` with `payment_intent_id` and `pending_signup_id`
    - Retrieve Pending_Signup from Redis — return 400 "Invalid or expired signup session" if not found
    - Verify PaymentIntent status with Stripe — return 400 "Payment not completed" if not `succeeded`
    - Create Stripe Customer (now that payment is confirmed)
    - Create Organisation (status=`active`) and User in DB using data from Pending_Signup
    - Save payment method to `org_payment_methods`
    - Delete Pending_Signup from Redis (prevent replay)
    - _Requirements: 1.2, 1.3, 1.4, 7.1, 7.2_

  - [x] 5.2 Send receipt email with verification link after payment confirmation
    - Generate a receipt email containing plan name, amount charged, and a verification link
    - Use the existing email service infrastructure (custom_smtp via `email_providers` table)
    - _Requirements: 4.1, 4.2_

  - [x] 5.3 Write property test: Payment confirmation creates account (Property 2)
    - **Property 2: Valid payment confirmation creates account, sends email, and deletes pending signup**
    - Generate random pending signups + succeeded PaymentIntents, verify DB records created and Redis key deleted
    - File: `tests/properties/test_signup_wizard_properties.py`
    - **Validates: Requirements 1.2, 4.1, 7.2**

  - [x] 5.4 Write property test: Non-succeeded PaymentIntent rejection (Property 3)
    - **Property 3: Non-succeeded PaymentIntent statuses are rejected**
    - Generate random non-succeeded statuses, verify rejection with no DB records
    - File: `tests/properties/test_signup_wizard_properties.py`
    - **Validates: Requirements 1.3**

  - [x] 5.5 Write property test: Receipt email content (Property 6)
    - **Property 6: Receipt email contains payment summary and verification link**
    - Generate random plan names and amounts, verify email contains plan name, formatted amount, and verification URL
    - File: `tests/properties/test_signup_wizard_properties.py`
    - **Validates: Requirements 4.2**

  - [x] 5.6 Write property test: Verification link activates account (Property 7)
    - **Property 7: Verification link activates account**
    - Generate random valid tokens for unverified users, verify `is_email_verified=True` after calling verify endpoint
    - File: `tests/properties/test_signup_wizard_properties.py`
    - **Validates: Requirements 4.3**

- [x] 6. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Update frontend types and validation
  - [x] 7.1 Update `SignupResponse` interface in `frontend/src/pages/auth/signup-types.ts`
    - Add `pending_signup_id?: string`, `plan_name?: string` fields
    - Make `organisation_id` optional (only present for trial flow)
    - Remove `signup_token` if no longer needed
    - _Requirements: 2.3, 2.4_

  - [x] 7.2 Add `coupon_code` to `SignupFormData` interface
    - Add `coupon_code: string` field to the form data type
    - _Requirements: 5.1_

  - [x] 7.3 Write property test: Client-side validation (Property 5)
    - **Property 5: Client-side validation rejects invalid form data**
    - Generate random invalid form data combinations using `fast-check`, verify `validateSignupForm` returns non-empty errors
    - File: `frontend/src/pages/auth/__tests__/signup-wizard.properties.test.ts`
    - **Validates: Requirements 2.2**

- [x] 8. Build the SignupWizard frontend component
  - [x] 8.1 Create `SignupWizard` component to replace `Signup`
    - Create `frontend/src/pages/auth/SignupWizard.tsx` as the top-level wizard component
    - Manage `step` state (`'form' | 'payment' | 'done'`)
    - Render all three step containers in a flex row, control visibility with CSS `transform: translateX()` and `transition: transform 300ms ease-in-out`
    - Include a step indicator bar showing current step (1–3 for paid, 1–2 for trial)
    - Wire up the existing route to use `SignupWizard` instead of `Signup`
    - _Requirements: 2.1, 2.5_

  - [x] 8.2 Extract `SignupForm` as Step 1
    - Extract the form rendering from the current `Signup` component into `frontend/src/pages/auth/SignupForm.tsx`
    - Include all existing fields plus a coupon code input
    - On submit: validate client-side, call `POST /auth/signup`, pass result up to `SignupWizard`
    - Display coupon validation result (discount amount) when a coupon is entered
    - _Requirements: 2.2, 2.3, 2.4, 5.1_

  - [x] 8.3 Refactor `PaymentStep` as Step 2
    - Create `frontend/src/pages/auth/PaymentStep.tsx` (refactored from existing `PaymentForm`)
    - Receive `pending_signup_id`, `stripe_client_secret`, `plan_name`, `payment_amount_cents` as props
    - Display plan name and amount to be charged
    - On Stripe `confirmCardPayment` success: call `POST /auth/signup/confirm-payment` with `{payment_intent_id, pending_signup_id}`
    - Handle Stripe card errors inline without navigating away
    - Handle confirm-payment backend errors with a "Retry" button
    - Disable pay button during processing to prevent double-clicks
    - _Requirements: 2.6, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 8.4 Create `ConfirmationStep` as Step 3
    - Create `frontend/src/pages/auth/ConfirmationStep.tsx`
    - Display "Check your email" message with the user's email address
    - _Requirements: 3.3_

  - [x] 8.5 Write unit tests for SignupWizard
    - Test step indicator renders correctly for paid vs trial plans
    - Test step transitions (form → payment → done, form → done for trial)
    - Test payment step displays plan name and amount
    - Test error messages display on payment failure
    - Test retry button appears when confirm-payment fails
    - File: `frontend/src/pages/auth/__tests__/signup-wizard.test.tsx`
    - _Requirements: 2.1, 2.3, 2.5, 2.6, 3.4, 3.5_

- [x] 9. Checkpoint - Ensure all frontend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Wire everything together and handle edge cases
  - [x] 10.1 Update frontend route to use `SignupWizard`
    - Replace the `Signup` component import/usage in the router with `SignupWizard`
    - Ensure the browser URL does not change between wizard steps
    - _Requirements: 2.1_

  - [x] 10.2 Handle session expiry on payment step
    - If `confirm-payment` returns "Invalid or expired signup session", reset wizard to step 1 with an explanatory message
    - _Requirements: 6.2_

  - [x] 10.3 Handle verification link expiry
    - Ensure the existing `verify-signup-email` endpoint returns an appropriate error for expired tokens
    - Ensure the `VerifyEmail.tsx` page offers a "resend verification email" option on expiry
    - _Requirements: 4.4_

  - [x] 10.4 Write backend unit tests for edge cases
    - Test expired pending signup returns correct error
    - Test confirm-payment with non-existent `pending_signup_id` returns 400
    - Test confirm-payment deletes Redis key after success (replay prevention)
    - Test email already registered returns 400 without creating pending signup
    - Test coupon reducing price to zero skips PaymentIntent
    - File: `tests/test_signup_wizard.py`
    - _Requirements: 1.3, 1.4, 5.3, 6.2, 7.2, 7.4_

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests validate universal correctness properties from the design document
- The backend auto-restarts with uvicorn --reload; frontend requires `docker exec invoicing-frontend-1 npx vite build`
- SMTP email is configured via the `email_providers` table, not env variables
- Redis is already available in the stack (`invoicing-redis-1`)
- No database migrations are needed — existing tables are sufficient
