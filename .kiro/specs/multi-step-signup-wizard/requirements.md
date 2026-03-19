# Requirements Document

## Introduction

The current signup flow contains a critical payment bypass vulnerability: users can select a paid plan, have their account created immediately at `/auth/signup`, skip the payment step, verify their email directly via the verification link, and log in without ever paying. This happens because the backend creates the organisation and user record before payment is confirmed.

This feature rebuilds the signup flow as a secure multi-step wizard that defers account creation until after payment succeeds for paid plans. Free-trial plans continue to create accounts immediately. The frontend presents a smooth single-page wizard with animated step transitions, and the backend enforces that no account exists until Stripe confirms payment for non-trial plans.

## Glossary

- **Signup_Wizard**: The single-page frontend component that guides users through the signup steps (form → payment → confirmation) with animated transitions
- **Signup_Form**: Step 1 of the Signup_Wizard where the user enters organisation name, name, email, password, plan selection, coupon code, and CAPTCHA
- **Payment_Step**: Step 2 of the Signup_Wizard where the user enters card details and submits payment via Stripe
- **Signup_API**: The backend endpoint (`POST /auth/signup`) that handles signup requests
- **Payment_Confirmation_API**: The backend endpoint (`POST /auth/signup/confirm-payment`) that verifies Stripe payment and creates the account
- **Pending_Signup**: A temporary server-side record (stored in Redis) holding validated form data before payment is completed; not a database record
- **Receipt_Email**: An email sent after successful payment containing a verification/activation link
- **Verification_Link**: A tokenised URL in the Receipt_Email that activates the account and verifies the user's email
- **Trial_Plan**: A subscription plan where `trial_duration > 0`, which does not require upfront payment
- **Paid_Plan**: A subscription plan where `trial_duration == 0`, which requires successful payment before account creation
- **Coupon**: A discount code that can be applied during signup to reduce the payment amount or extend a trial

## Requirements

### Requirement 1: Deferred Account Creation for Paid Plans

**User Story:** As a platform operator, I want accounts on paid plans to be created only after payment succeeds, so that users cannot bypass payment and access the system for free.

#### Acceptance Criteria

1. WHEN a user submits the Signup_Form with a Paid_Plan selected, THE Signup_API SHALL validate the form data, create a Pending_Signup in Redis, create a Stripe PaymentIntent, and return the Stripe client secret without creating any Organisation or User database records
2. WHEN the Payment_Confirmation_API receives a confirmed payment_intent_id, THE Payment_Confirmation_API SHALL verify the PaymentIntent status with Stripe, retrieve the Pending_Signup from Redis, create the Organisation and User records in the database, and return a success response
3. IF the Stripe PaymentIntent status is not "succeeded" when the Payment_Confirmation_API is called, THEN THE Payment_Confirmation_API SHALL reject the request and return a "Payment not completed" error without creating any database records
4. IF the Pending_Signup referenced by the payment confirmation does not exist in Redis, THEN THE Payment_Confirmation_API SHALL reject the request and return an "Invalid or expired signup session" error
5. WHEN a user submits the Signup_Form with a Trial_Plan selected, THE Signup_API SHALL create the Organisation and User records immediately in the database with "trial" status and send a Verification_Link email

### Requirement 2: Multi-Step Wizard Frontend

**User Story:** As a new user, I want a smooth multi-step signup experience on a single page, so that I can complete registration and payment without navigating to separate pages.

#### Acceptance Criteria

1. THE Signup_Wizard SHALL render all steps (Signup_Form, Payment_Step, confirmation) within a single page without changing the browser URL
2. WHEN the user completes the Signup_Form and clicks submit, THE Signup_Wizard SHALL validate all fields client-side before sending the request to the Signup_API
3. WHEN the Signup_API returns a successful response with `requires_payment: true`, THE Signup_Wizard SHALL transition to the Payment_Step with a smooth horizontal slide animation
4. WHEN the Signup_API returns a successful response with `requires_payment: false` (Trial_Plan), THE Signup_Wizard SHALL transition directly to the confirmation step
5. THE Signup_Wizard SHALL display a step indicator showing the current step and total steps so the user knows their progress
6. WHILE the Signup_Wizard is on the Payment_Step, THE Signup_Wizard SHALL display the selected plan name and the amount to be charged

### Requirement 3: Payment Processing

**User Story:** As a new user on a paid plan, I want to enter my card details and pay securely, so that my account is activated immediately after payment.

#### Acceptance Criteria

1. WHEN the user enters valid card details and clicks "Pay and activate", THE Payment_Step SHALL submit the payment to Stripe using the client secret from the Signup_API response
2. WHEN Stripe confirms the PaymentIntent as succeeded, THE Payment_Step SHALL call the Payment_Confirmation_API with the payment_intent_id and the pending signup identifier
3. WHEN the Payment_Confirmation_API returns success, THE Signup_Wizard SHALL transition to the confirmation step showing a "Check your email" message
4. IF Stripe returns a card error or the payment is declined, THEN THE Payment_Step SHALL display "Payment declined" (or the Stripe error message) on the same screen without navigating away
5. IF the Payment_Confirmation_API returns an error after Stripe payment succeeded, THEN THE Payment_Step SHALL display the error message and allow the user to retry the confirmation call

### Requirement 4: Receipt Email and Account Activation

**User Story:** As a new user who has paid, I want to receive a receipt email with an activation link, so that I can verify my email and start using the system.

#### Acceptance Criteria

1. WHEN the Payment_Confirmation_API successfully creates the account after payment, THE Payment_Confirmation_API SHALL send a Receipt_Email to the user's email address
2. THE Receipt_Email SHALL contain a summary of the payment (plan name, amount charged) and a Verification_Link to activate the account
3. WHEN the user clicks the Verification_Link, THE system SHALL mark the user's email as verified, activate the account, and redirect the user to the login page
4. IF the Verification_Link token has expired, THEN THE system SHALL display an error message and offer the option to request a new verification email

### Requirement 5: Coupon Support in Payment Flow

**User Story:** As a new user with a coupon code, I want to apply my coupon during signup, so that I receive the discount on my first payment.

#### Acceptance Criteria

1. WHEN a user enters a coupon code on the Signup_Form, THE Signup_Wizard SHALL validate the coupon via the existing coupon validation endpoint and display the discount
2. WHEN a valid Coupon is applied and the user submits the Signup_Form for a Paid_Plan, THE Signup_API SHALL include the coupon discount when calculating the Stripe PaymentIntent amount
3. IF a percentage or fixed-amount Coupon reduces the effective price to zero for a Paid_Plan, THEN THE Signup_API SHALL skip creating a PaymentIntent, create the account immediately, and return `requires_payment: false`
4. WHEN a trial-extension Coupon is applied to a Paid_Plan, THE Signup_API SHALL convert the plan to trial status with the extended trial duration and skip the Payment_Step

### Requirement 6: Pending Signup Expiry and Cleanup

**User Story:** As a platform operator, I want pending signups to expire automatically, so that stale data does not accumulate and abandoned Stripe PaymentIntents are handled.

#### Acceptance Criteria

1. THE Signup_API SHALL store each Pending_Signup in Redis with a time-to-live of 30 minutes
2. WHEN a Pending_Signup expires in Redis, THE system SHALL treat any subsequent payment confirmation attempt for that signup as invalid
3. WHEN a user submits the Signup_Form with an email that already has a valid Pending_Signup in Redis, THE Signup_API SHALL replace the existing Pending_Signup with the new one

### Requirement 7: Security Hardening

**User Story:** As a platform operator, I want the signup flow to be resistant to tampering and replay attacks, so that the payment bypass vulnerability is fully closed.

#### Acceptance Criteria

1. THE Payment_Confirmation_API SHALL accept only a pending_signup_id (not an organisation_id) to look up the Pending_Signup from Redis, preventing callers from referencing arbitrary organisations
2. WHEN the Payment_Confirmation_API successfully creates an account, THE Payment_Confirmation_API SHALL delete the Pending_Signup from Redis so the same signup cannot be replayed
3. THE Signup_API SHALL verify CAPTCHA before creating a Pending_Signup or account, consistent with the existing CAPTCHA verification flow
4. THE Signup_API SHALL verify that the submitted email address is not already registered to an existing User before creating a Pending_Signup
