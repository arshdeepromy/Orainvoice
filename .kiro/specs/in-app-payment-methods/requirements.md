# Requirements Document

## Introduction

This feature replaces the current Stripe Customer Portal redirect with a fully in-app payment method management experience. Org Admins will be able to add, view, set default, and remove credit/debit cards directly within the WorkshopPro NZ Billing page. Stripe remains the payment processor behind the scenes, but the user never leaves the app. The card form uses Stripe Elements (CardElement) with `hidePostalCode: true` since NZ customers do not use ZIP codes.

Additionally, card details entered during signup are persisted to the local database, a scheduled task monitors card expiry dates and sends advance notifications, card verification is enforced when updating payment methods, and the organisation must always have at least one valid payment method on file.

## Glossary

- **Billing_Page**: The existing settings page at `/settings/billing` where Org Admins manage their organisation's subscription, usage, and payment details.
- **Payment_Method_Manager**: The new in-app UI component that displays saved cards and provides actions to add, set default, and remove payment methods.
- **Card_Form**: A Stripe Elements CardElement embedded in the app for securely collecting card details without the card number touching the WorkshopPro server.
- **Setup_Intent**: A Stripe object used to collect and save card details for future payments without charging the customer immediately.
- **Default_Payment_Method**: The card Stripe uses to charge the organisation's subscription and one-off invoices.
- **Org_Admin**: A user with the organisation administrator role who is authorised to manage billing and payment methods.
- **Stripe_API**: The Stripe backend SDK used server-side to create SetupIntents, list payment methods, set defaults, and detach cards.
- **Publishable_Key**: The Stripe publishable API key used by the frontend to initialise Stripe.js, loaded from the existing `/auth/stripe-publishable-key` endpoint.
- **Payment_Methods_Table**: A local database table (`org_payment_methods`) that stores Stripe payment method metadata (ID, brand, last4, expiry, verification status) for each organisation.
- **Expiry_Notification**: An automated notification sent to the Org Admin when a saved card is approaching its expiry date.
- **Card_Verification**: The process of confirming a card is real and valid using Stripe's SetupIntent verification (which performs a micro-authorisation check), triggered when a payment method is added or updated.

## Requirements

### Requirement 1: List Saved Payment Methods

**User Story:** As an Org Admin, I want to see all saved cards for my organisation on the Billing page, so that I know which payment methods are available, which one is the default, and whether each card is verified.

#### Acceptance Criteria

1. WHEN the Org Admin opens the Billing_Page, THE Payment_Method_Manager SHALL display all payment methods from the Payment_Methods_Table for the organisation.
2. THE Payment_Method_Manager SHALL display for each card: the card brand (e.g. Visa, Mastercard), the last four digits, the expiry month/year, and a verification badge showing "Verified" or "Unverified".
3. THE Payment_Method_Manager SHALL visually indicate which card is the current Default_Payment_Method.
4. WHEN the organisation has no saved payment methods, THE Payment_Method_Manager SHALL display a message prompting the Org Admin to add a card.
5. IF the backend fails to retrieve payment methods, THEN THE Payment_Method_Manager SHALL display an error message to the Org Admin.
6. THE Payment_Method_Manager SHALL display a warning icon next to any card that is expiring within 2 months.

### Requirement 2: Add a New Payment Method

**User Story:** As an Org Admin, I want to add a new credit or debit card within the app, so that I can pay for my subscription without being redirected to an external site.

#### Acceptance Criteria

1. WHEN the Org Admin clicks the "Add card" button, THE Payment_Method_Manager SHALL display the Card_Form using Stripe Elements with `hidePostalCode` set to true.
2. WHEN the Card_Form is displayed, THE Backend SHALL create a Setup_Intent via the Stripe_API and return the client secret to the frontend.
3. WHEN the Org Admin submits valid card details, THE Card_Form SHALL confirm the Setup_Intent using Stripe.js `confirmCardSetup` with the client secret.
4. WHEN the Setup_Intent confirmation succeeds, THE Payment_Method_Manager SHALL add the new card to the displayed list without a full page reload.
5. WHEN the organisation has no existing Default_Payment_Method, THE Backend SHALL set the newly added card as the Default_Payment_Method automatically.
6. IF the Setup_Intent confirmation fails (e.g. card declined), THEN THE Card_Form SHALL display the error message returned by Stripe to the Org Admin.
7. WHILE the Setup_Intent confirmation is in progress, THE Card_Form SHALL disable the submit button and display a loading indicator.

### Requirement 3: Set Default Payment Method

**User Story:** As an Org Admin, I want to choose which saved card is used for future charges, so that I can control which card my subscription bills to.

#### Acceptance Criteria

1. WHEN the Org Admin selects "Set as default" on a non-default card, THE Backend SHALL update the Stripe customer's `invoice_settings.default_payment_method` to the selected card via the Stripe_API.
2. WHEN the default payment method is updated successfully, THE Payment_Method_Manager SHALL reflect the new default card in the UI without a full page reload.
3. IF the Stripe_API call to update the default payment method fails, THEN THE Payment_Method_Manager SHALL display an error message to the Org Admin.
4. THE Payment_Method_Manager SHALL hide the "Set as default" action on the card that is already the Default_Payment_Method.

### Requirement 4: Remove a Payment Method

**User Story:** As an Org Admin, I want to remove a saved card I no longer use, so that outdated payment methods do not clutter my billing settings.

#### Acceptance Criteria

1. WHEN the Org Admin clicks "Remove" on a saved card, THE Payment_Method_Manager SHALL display a confirmation prompt before proceeding.
2. WHEN the Org Admin confirms removal, THE Backend SHALL detach the payment method from the Stripe customer via the Stripe_API and remove the record from the Payment_Methods_Table.
3. WHEN the payment method is detached successfully, THE Payment_Method_Manager SHALL remove the card from the displayed list without a full page reload.
4. THE Backend SHALL prevent removal when the card is the only payment method on file, and SHALL return a 400 error with the message: "You must have at least one valid payment method. Please add a new card before removing this one."
5. THE Payment_Method_Manager SHALL disable the "Remove" button and display the above message when only one payment method exists.
6. IF the Stripe_API call to detach the payment method fails, THEN THE Payment_Method_Manager SHALL display an error message to the Org Admin.
7. THE Backend SHALL prevent removal of the Default_Payment_Method when it is the only card — the Org Admin must add another card and set it as default first.

### Requirement 5: Backend API Endpoints

**User Story:** As a developer, I want well-defined API endpoints for payment method operations, so that the frontend can manage cards through the WorkshopPro backend.

#### Acceptance Criteria

1. THE Backend SHALL expose a `GET /billing/payment-methods` endpoint that returns all payment methods from the Payment_Methods_Table for the organisation, including each card's brand, last four digits, expiry month, expiry year, verification status, and whether it is the default.
2. THE Backend SHALL expose a `POST /billing/setup-intent` endpoint that creates a Stripe Setup_Intent and returns the client secret to the frontend.
3. THE Backend SHALL expose a `POST /billing/payment-methods/{payment_method_id}/set-default` endpoint that sets the specified payment method as the Stripe customer's default and updates the Payment_Methods_Table.
4. THE Backend SHALL expose a `DELETE /billing/payment-methods/{payment_method_id}` endpoint that detaches the specified payment method from the Stripe customer and removes it from the Payment_Methods_Table.
5. THE Backend SHALL require Org_Admin authentication for all payment method endpoints.
6. IF the organisation does not have a `stripe_customer_id`, THEN THE Backend SHALL return a 400 error with a descriptive message for all payment method endpoints.

### Requirement 6: Replace Stripe Customer Portal

**User Story:** As an Org Admin, I want payment method management built into the Billing page, so that I do not need to leave the app to manage my cards.

#### Acceptance Criteria

1. THE Billing_Page SHALL replace the existing "Manage payment method" button (which opens the Stripe Customer Portal) with the in-app Payment_Method_Manager component.
2. THE Billing_Page SHALL remove the call to the `POST /billing/billing-portal` endpoint for payment method management.
3. THE Payment_Method_Manager SHALL load the Stripe publishable key from the existing `GET /auth/stripe-publishable-key` endpoint to initialise Stripe Elements.

### Requirement 7: Security and Data Handling

**User Story:** As an Org Admin, I want my card details handled securely, so that sensitive payment information is protected.

#### Acceptance Criteria

1. THE Card_Form SHALL use Stripe Elements so that raw card numbers, CVVs, and expiry dates are collected by Stripe directly and do not pass through the WorkshopPro backend.
2. THE Backend SHALL only store and transmit Stripe payment method IDs, card brand, last four digits, and expiry date — THE Backend SHALL NOT store full card numbers or CVVs.
3. THE Backend SHALL verify that the requesting user belongs to the organisation whose payment methods are being managed, for every payment method endpoint.

### Requirement 8: Save Card Details During Signup

**User Story:** As an Org Admin, I want the card I enter during signup to be automatically saved to my organisation's payment methods, so that I don't have to re-enter it later.

#### Acceptance Criteria

1. WHEN a new user signs up and enters card details for their first subscription payment, THE Backend SHALL save the payment method metadata (Stripe payment method ID, card brand, last four digits, expiry month, expiry year) to the Payment_Methods_Table.
2. THE Backend SHALL set the signup card as the Default_Payment_Method for the new organisation.
3. THE Backend SHALL set the verification status of the signup card to "verified" since Stripe has already validated it during the payment.
4. IF the signup payment succeeds but saving to the Payment_Methods_Table fails, THE Backend SHALL log the error but SHALL NOT block the signup — the card can be synced later from Stripe.

### Requirement 9: Card Expiry Monitoring and Notifications

**User Story:** As an Org Admin, I want to be notified before my card expires, so that I can update my payment method and avoid failed charges.

#### Acceptance Criteria

1. THE Backend SHALL run a scheduled task (daily) that checks the Payment_Methods_Table for cards expiring within 2 months.
2. WHEN a card is found to be expiring within 2 months, THE scheduled task SHALL send an Expiry_Notification to the Org_Admin of the organisation.
3. THE Expiry_Notification SHALL include the card brand, last four digits, expiry month/year, and a link to the Billing_Page to update the card.
4. THE scheduled task SHALL NOT send duplicate notifications — it SHALL track that a notification has already been sent for a given card's expiry period (e.g. via a `expiry_notified_at` column).
5. THE scheduled task SHALL only check cards that are currently the Default_Payment_Method or the only card on file — it SHALL NOT notify about non-default cards when other valid cards exist.
6. THE scheduled task SHALL calculate the notification window based on the card's expiry month and year (e.g. a card expiring April 2028 triggers notification from February 2028 onwards).

### Requirement 10: Card Verification on Update

**User Story:** As an Org Admin, I want to know that any card I add is a real, valid card, so that I can trust my payment method will work when charged.

#### Acceptance Criteria

1. WHEN a new payment method is added via the Card_Form, THE Backend SHALL create the Setup_Intent with `usage: 'off_session'` so that Stripe performs a micro-authorisation check to verify the card is real.
2. WHEN the Setup_Intent confirmation succeeds (Stripe returns `succeeded` status), THE Backend SHALL set the card's verification status to "verified" in the Payment_Methods_Table.
3. IF the Setup_Intent confirmation fails (card declined, invalid, or insufficient funds for micro-auth), THE Card_Form SHALL display the Stripe error message and THE Backend SHALL NOT save the card to the Payment_Methods_Table.
4. THE Payment_Method_Manager SHALL display a "Verified" badge (green checkmark) next to cards with verification status "verified".
5. THE Backend SHALL handle the `setup_intent.succeeded` webhook event from Stripe to confirm verification and update the Payment_Methods_Table if the frontend confirmation callback was missed.
6. Card verification SHALL only be performed when adding or updating a payment method — existing verified cards SHALL NOT be re-verified.

### Requirement 11: Stripe Setup Guide on Integrations Page

**User Story:** As a Global Admin, I want a step-by-step guide on the Integrations page that walks me through configuring Stripe, so that I can set everything up correctly without needing external documentation.

#### Acceptance Criteria

1. THE Integrations page Stripe tab SHALL display a collapsible "Setup Guide" section above the API Keys and Platform & Webhooks sections.
2. THE Setup Guide SHALL include numbered steps covering:
   - Step 1: Create a Stripe account (with link to Stripe Dashboard).
   - Step 2: Copy the Publishable key and Secret key from the Stripe Dashboard → Developers → API keys, and paste them into the API Keys section.
   - Step 3: Test the API keys using the "Test API keys" button — guide explains what a successful test means.
   - Step 4: Set up the webhook endpoint in Stripe Dashboard → Developers → Webhooks → Add endpoint, using the Webhook endpoint URL shown on this page.
   - Step 5: Copy the Webhook signing secret (`whsec_...`) from Stripe and paste it into the Signing secret field.
   - Step 6: List the required webhook events to subscribe to: `invoice.created`, `invoice.payment_succeeded`, `invoice.payment_failed`, `customer.subscription.updated`, `customer.subscription.deleted`, `customer.updated`, `setup_intent.succeeded`.
   - Step 7: Save the Platform & Webhooks configuration and run the connection test.
3. EACH step SHALL include a brief explanation of why it is needed (e.g. "The signing secret lets us verify that webhook calls are genuinely from Stripe").
4. THE Setup Guide SHALL be dismissible — once the admin has completed setup, they can collapse or hide it, and the preference SHALL persist.
5. THE Setup Guide SHALL show a progress indicator (e.g. checkmarks) for steps that are already completed (e.g. API keys saved, webhook secret saved).

### Requirement 12: Automated Stripe Function and Webhook Testing

**User Story:** As a Global Admin, I want to run automated tests for all Stripe functions and webhooks from the Integrations page, so that I can verify everything is working and see clear pass/fail results.

#### Acceptance Criteria

1. THE Integrations page Stripe tab SHALL include a "Run All Tests" button that triggers automated testing of all Stripe functions and webhook handlers.
2. THE automated test suite SHALL test the following functions and display individual pass/fail results for each:
   - **Create Customer**: Test creating a Stripe customer with a test email.
   - **Create SetupIntent**: Test creating a SetupIntent for the test customer.
   - **List Payment Methods**: Test listing payment methods for the test customer.
   - **Set Default Payment Method**: Test setting a default payment method (skipped if no payment methods exist, with a "skipped" status and reason).
   - **Create Subscription**: Test creating a subscription with a test price.
   - **Create Invoice Item**: Test creating an invoice item for overage charges.
   - **Webhook Signature Verification**: Test that the webhook signing secret can verify a test payload signature.
   - **Webhook: invoice.created**: Test the handler processes the event correctly.
   - **Webhook: invoice.payment_succeeded**: Test the handler processes the event correctly.
   - **Webhook: invoice.payment_failed**: Test the handler processes the event correctly.
   - **Webhook: customer.subscription.updated**: Test the handler processes the event correctly.
   - **Webhook: customer.subscription.deleted**: Test the handler processes the event correctly.
   - **Webhook: customer.updated**: Test the handler processes the event correctly.
   - **Webhook: setup_intent.succeeded**: Test the handler processes the event correctly.
   - **Billing Portal Session**: Test creating a billing portal session.
3. FOR each test, THE UI SHALL display: the test name, a status badge ("Passed" in green, "Failed" in red, "Skipped" in yellow), and the error message if failed.
4. THE Backend SHALL expose a `POST /admin/integrations/stripe/test-all` endpoint that runs all tests sequentially and returns an array of results.
5. THE test results SHALL be displayed in a table or card layout, grouped by category (API Functions, Webhook Handlers).
6. AFTER all tests complete, THE UI SHALL display a summary line: "X of Y tests passed" with an overall status.
7. THE webhook handler tests SHALL use mock event payloads (not real Stripe webhooks) to verify the handler logic processes each event type correctly.
8. THE automated tests SHALL clean up any test resources created in Stripe (e.g. delete the test customer) after the test run completes.
