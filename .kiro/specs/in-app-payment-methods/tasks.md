# Implementation Plan: In-App Payment Methods

## Overview

Convert the external Stripe Customer Portal redirect into a fully in-app payment method management experience. Implementation proceeds bottom-up: database model → Stripe integration functions → billing API endpoints → signup card persistence → expiry monitoring → webhook handler → frontend components → admin tooling → wiring and integration.

## Tasks

- [x] 1. Create database model and migration
  - [x] 1.1 Create `OrgPaymentMethod` SQLAlchemy model in `app/modules/billing/models.py`
    - Define all columns: `id`, `org_id`, `stripe_payment_method_id`, `brand`, `last4`, `exp_month`, `exp_year`, `is_default`, `is_verified`, `expiry_notified_at`, `created_at`, `updated_at`
    - Add foreign key to `organisations.id` with `ON DELETE CASCADE`
    - Add unique constraint on `stripe_payment_method_id`
    - Add index on `org_id`
    - _Requirements: 5.1, 7.2, 9.4_

  - [x] 1.2 Create Alembic migration for `org_payment_methods` table
    - Generate migration file in `alembic/versions/` following existing naming convention
    - Include table creation, indexes, and unique constraints
    - _Requirements: 5.1_

  - [x] 1.3 Add Pydantic schemas to `app/modules/billing/schemas.py`
    - Add `PaymentMethodResponse` with computed `is_expiring_soon` field
    - Add `PaymentMethodListResponse`, `SetupIntentResponse`
    - Add `StripeTestResult`, `StripeTestAllResponse` schemas
    - _Requirements: 5.1, 12.3_

- [x] 2. Implement Stripe integration functions
  - [x] 2.1 Add new functions to `app/integrations/stripe_billing.py`
    - Implement `list_payment_methods(customer_id)` — calls `stripe.PaymentMethod.list`
    - Implement `set_default_payment_method(customer_id, payment_method_id)` — updates customer `invoice_settings.default_payment_method`
    - Implement `detach_payment_method(payment_method_id)` — calls `stripe.PaymentMethod.detach`
    - _Requirements: 5.1, 5.3, 5.4_

  - [x] 2.2 Modify `create_setup_intent` to pass `usage='off_session'`
    - Update existing function to include the `usage` parameter for micro-authorisation verification
    - _Requirements: 10.1_

  - [x] 2.3 Write property test for test results structure (Property 18)
    - **Property 18: Test results contain required fields**
    - Verify each test result has `test_name`, `category` (api_functions | webhook_handlers), `status` (passed | failed | skipped), and `error_message` is non-null when status is "failed"
    - **Validates: Requirements 12.2, 12.3**

  - [x] 2.4 Write property test for test summary computation (Property 19)
    - **Property 19: Test summary computation**
    - Verify `passed + failed + skipped == total` and each count matches the number of results with that status
    - **Validates: Requirements 12.6**

- [x] 3. Implement billing API endpoints
  - [x] 3.1 Implement `GET /billing/payment-methods` endpoint in `app/modules/billing/router.py`
    - Query `org_payment_methods` for the authenticated user's org
    - Compute `is_expiring_soon` based on 2-month window from current date
    - Validate `stripe_customer_id` exists, return 400 if not
    - Require Org Admin auth
    - _Requirements: 1.1, 1.2, 1.6, 5.1, 5.5, 5.6_

  - [x] 3.2 Implement `POST /billing/setup-intent` endpoint
    - Create Stripe SetupIntent with `usage='off_session'`
    - Return `client_secret` and `setup_intent_id`
    - Validate `stripe_customer_id` exists
    - _Requirements: 2.2, 5.2, 5.6, 10.1_

  - [x] 3.3 Implement `POST /billing/payment-methods/{payment_method_id}/set-default` endpoint
    - Update Stripe customer `invoice_settings.default_payment_method`
    - Update `org_payment_methods` — set `is_default = true` for target, `false` for all others in org
    - Verify payment method belongs to requesting user's org
    - _Requirements: 3.1, 5.3, 7.3_

  - [x] 3.4 Implement `DELETE /billing/payment-methods/{payment_method_id}` endpoint
    - Return 400 if it's the only payment method on file with the specified error message
    - Detach from Stripe via `detach_payment_method`
    - Remove record from `org_payment_methods`
    - Verify payment method belongs to requesting user's org
    - _Requirements: 4.2, 4.4, 4.7, 5.4, 7.3_

  - [x] 3.5 Write property test for list endpoint (Property 1)
    - **Property 1: List endpoint returns all org payment methods**
    - For any org with N payment methods, GET returns exactly N items with all required fields
    - **Validates: Requirements 1.1, 1.2, 5.1**

  - [x] 3.6 Write property test for expiry-soon computation (Property 2)
    - **Property 2: Expiry-soon computation**
    - `is_expiring_soon` is true iff card expiry is within 2 months of current date
    - **Validates: Requirements 1.6**

  - [x] 3.7 Write property test for first card auto-default (Property 3)
    - **Property 3: First card becomes default automatically**
    - When org has zero cards and a new one is added, `is_default` is true
    - **Validates: Requirements 2.5**

  - [x] 3.8 Write property test for exactly one default (Property 4)
    - **Property 4: Exactly one default after set-default**
    - After set-default, exactly one card in the org has `is_default = true`
    - **Validates: Requirements 3.1, 5.3**

  - [x] 3.9 Write property test for deletion count (Property 5)
    - **Property 5: Deletion reduces payment method count**
    - Deleting a non-sole card reduces count from N to N-1
    - **Validates: Requirements 4.2, 5.4**

  - [x] 3.10 Write property test for sole card deletion prevention (Property 6)
    - **Property 6: Cannot delete sole payment method**
    - Deleting the only card returns 400 and count stays at 1
    - **Validates: Requirements 4.4, 4.7**

  - [x] 3.11 Write property test for no Stripe customer (Property 8)
    - **Property 8: No Stripe customer returns 400**
    - All payment method endpoints return 400 when org has no `stripe_customer_id`
    - **Validates: Requirements 5.6**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement signup card persistence and webhook handler
  - [x] 5.1 Persist card details during signup in `app/modules/auth/service.py`
    - After successful signup payment, save payment method metadata to `org_payment_methods`
    - Set `is_default = true` and `is_verified = true`
    - Wrap in try/except — log error but do not block signup on failure
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 5.2 Add `setup_intent.succeeded` webhook handler in `app/modules/billing/router.py`
    - Handle the `setup_intent.succeeded` event in the existing webhook handler
    - Create or update the payment method record in `org_payment_methods` with `is_verified = true`
    - If payment method doesn't exist locally, create the record (sync from Stripe)
    - Return 200 to Stripe even on internal errors to prevent retries
    - _Requirements: 10.2, 10.5_

  - [x] 5.3 Write property test for signup card (Property 11)
    - **Property 11: Signup card saved as default and verified**
    - After signup, org_payment_methods has a record with `is_default = true`, `is_verified = true`, and matching card metadata
    - **Validates: Requirements 8.1, 8.2, 8.3**

  - [x] 5.4 Write property test for verification on success (Property 15)
    - **Property 15: Verification status set on successful setup**
    - After successful SetupIntent confirmation or webhook, card has `is_verified = true`
    - **Validates: Requirements 10.2, 10.5**

  - [x] 5.5 Write property test for failed setup (Property 16)
    - **Property 16: Failed setup does not persist card**
    - Failed SetupIntent does not create a record in org_payment_methods
    - **Validates: Requirements 10.3**

- [x] 6. Implement expiry monitoring scheduled task
  - [x] 6.1 Add `check_card_expiry_task()` to `app/tasks/scheduled.py`
    - Query `org_payment_methods` for cards expiring within 2 months
    - Only select default cards or sole cards for their org
    - Skip cards where `expiry_notified_at` is already set
    - Send notification via `app/modules/notifications/service.py` with card brand, last4, expiry, and Billing page link
    - Set `expiry_notified_at` on successful notification send
    - Wrap each org's processing in try/except for isolation
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 6.2 Write property test for expiry monitoring selection (Property 12)
    - **Property 12: Expiry monitoring selects correct cards**
    - Task selects only cards expiring within 2 months that are default or sole card
    - **Validates: Requirements 9.1, 9.2, 9.5, 9.6**

  - [x] 6.3 Write property test for no duplicate notifications (Property 13)
    - **Property 13: No duplicate expiry notifications**
    - Cards with `expiry_notified_at` set are not re-notified
    - **Validates: Requirements 9.4**

  - [x] 6.4 Write property test for notification content (Property 14)
    - **Property 14: Expiry notification contains required fields**
    - Notification includes card brand, last4, expiry month/year, and Billing page link
    - **Validates: Requirements 9.3**

- [x] 7. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement frontend PaymentMethodManager and CardForm
  - [x] 8.1 Create `PaymentMethodManager` component at `frontend/src/components/billing/PaymentMethodManager.tsx`
    - Fetch payment methods from `GET /billing/payment-methods` on mount
    - Display each card with brand, last4, expiry, verification badge, and expiry warning icon
    - Visually indicate the default card
    - Show empty state message when no cards exist
    - Show error state with retry button on fetch failure
    - Show "Set as default" action on non-default cards (hidden on default)
    - Show "Remove" button — disabled with message when only one card exists
    - Show confirmation prompt before removal
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.2, 3.4, 4.1, 4.3, 4.5, 4.6, 10.4_

  - [x] 8.2 Create `CardForm` component at `frontend/src/components/billing/CardForm.tsx`
    - Use `@stripe/react-stripe-js` Elements provider with `CardElement` and `hidePostalCode: true`
    - On submit: call `POST /billing/setup-intent` to get client secret, then `confirmCardSetup`
    - On success: call parent callback to refresh payment methods list (no full page reload)
    - On error: display Stripe error message inline below the form
    - Disable submit button and show loading indicator while confirmation is in progress
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 2.7, 7.1_

  - [x] 8.3 Integrate `PaymentMethodManager` into `frontend/src/pages/settings/Billing.tsx`
    - Replace the existing "Manage payment method" button (Stripe Customer Portal redirect) with `PaymentMethodManager`
    - Remove the call to `POST /billing/billing-portal` for payment method management
    - Load Stripe publishable key from `GET /auth/stripe-publishable-key`
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 8.4 Write frontend property test for expiry-soon computation (Property 2)
    - **Property 2: Expiry-soon computation (frontend)**
    - Test the frontend utility that computes `is_expiring_soon` from exp_month/exp_year
    - **Validates: Requirements 1.6**

- [x] 9. Implement admin tooling — Setup Guide and Test Suite
  - [x] 9.1 Create `StripeSetupGuide` component at `frontend/src/components/admin/StripeSetupGuide.tsx`
    - Render 7 numbered steps with explanations as specified in Requirement 11.2
    - Show progress checkmarks for completed steps (API keys saved, webhook secret saved, etc.)
    - Collapsible/dismissible with localStorage persistence
    - Render above API Keys section on Stripe tab
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 9.2 Create `StripeTestSuite` component at `frontend/src/components/admin/StripeTestSuite.tsx`
    - "Run All Tests" button triggers `POST /admin/integrations/stripe/test-all`
    - Display results in grouped table/cards: API Functions and Webhook Handlers
    - Show status badges: Passed (green), Failed (red), Skipped (yellow) with error messages
    - Show summary line: "X of Y tests passed" with overall status
    - _Requirements: 12.1, 12.3, 12.5, 12.6_

  - [x] 9.3 Implement `POST /admin/integrations/stripe/test-all` endpoint in `app/modules/admin/router.py`
    - Run all 15 Stripe function and webhook handler tests sequentially
    - Test: Create Customer, Create SetupIntent, List Payment Methods, Set Default Payment Method, Create Subscription, Create Invoice Item, Webhook Signature Verification, and all 7 webhook handlers
    - Use mock event payloads for webhook handler tests
    - Clean up test resources (delete test customer) after completion
    - Return array of results with test_name, category, status, error_message
    - _Requirements: 12.2, 12.4, 12.7, 12.8_

  - [x] 9.4 Integrate `StripeSetupGuide` and `StripeTestSuite` into `frontend/src/pages/admin/Integrations.tsx`
    - Add `StripeSetupGuide` above the API Keys section on the Stripe tab
    - Add `StripeTestSuite` below the existing Stripe configuration sections
    - _Requirements: 11.1, 12.1_

  - [x] 9.5 Write frontend property test for setup guide progress (Property 17)
    - **Property 17: Setup guide progress reflects completion state**
    - Checkmarks shown for exactly the completed steps and no others
    - **Validates: Requirements 11.5**

  - [x] 9.6 Write frontend property test for test summary computation (Property 19)
    - **Property 19: Test summary computation (frontend)**
    - Verify summary counts match the actual result statuses
    - **Validates: Requirements 12.6**

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Backend uses Python (FastAPI + SQLAlchemy async + hypothesis for property tests)
- Frontend uses TypeScript (React + Tailwind + fast-check for property tests)
