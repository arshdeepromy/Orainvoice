# Requirements Document

## Introduction

This feature adds an "Online Payments" settings page to organisation settings, enabling org admins to connect their Stripe account via Stripe Connect OAuth and collect payments from customers on invoices. The platform uses Standard Connect — money flows directly to the org's connected Stripe account, with an optional platform application fee. Customers pay via a Stripe Checkout session linked from the invoice, and payments are automatically recorded via webhook when completed.

**Key context:** The backend already has a working Stripe Connect OAuth flow (`app/modules/billing/router.py`), payment link generation (`app/integrations/stripe_connect.py`), webhook handling (`app/modules/payments/service.py`), and customer portal payment support (`app/modules/portal/service.py`). The global admin has already configured the Stripe Connect client ID (`ca_...`) in the admin integrations page. This spec focuses on the **org-facing settings UI**, the **invoice "Pay Now" button**, and any gaps in the existing backend.

## Glossary

- **Online_Payments_Page**: The new settings section in org settings that displays Stripe Connect status and allows the org admin to initiate or manage the connection.
- **Stripe_Connect_OAuth**: The Stripe-hosted OAuth flow where an org admin authorises their Stripe account to receive payments through the platform.
- **Checkout_Session**: A Stripe-hosted payment page created on the connected account where the customer enters payment details.
- **Payment_Webhook_Handler**: The backend endpoint that receives Stripe webhook events (e.g. `checkout.session.completed`) and records payments against invoices.
- **Org_Admin**: A user with the `org_admin` role who manages organisation settings.
- **Connected_Account**: The org's Stripe account (identified by `acct_...`) linked via Stripe Connect OAuth.
- **Portal_Token**: A UUID token on each invoice that grants unauthenticated access to the customer portal for viewing and paying invoices.
- **Application_Fee**: An optional per-transaction fee the platform deducts from payments before they reach the connected account.
- **Settings_API**: The backend endpoint that returns the org's Stripe Connect status for the Online Payments settings page.

## Requirements

### Requirement 1: Online Payments Settings Page

**User Story:** As an Org Admin, I want to see an "Online Payments" section in my organisation settings, so that I can view and manage my Stripe Connect integration status.

#### Acceptance Criteria

1. THE Online_Payments_Page SHALL appear as a nav item labelled "Online Payments" in the org settings sidebar, visible only to users with the `org_admin` or `global_admin` role.
2. THE Online_Payments_Page SHALL display Stripe as the payment gateway with the gateway name, a description of the service, and the current connection status.
3. WHEN the organisation has no Connected_Account, THE Online_Payments_Page SHALL display a "Set Up Now" button and a status badge showing "Not Connected".
4. WHEN the organisation has a Connected_Account, THE Online_Payments_Page SHALL display a "Connected" status badge and the last 4 characters of the connected account ID (masked).
5. WHEN the organisation has a Connected_Account, THE Online_Payments_Page SHALL display a "Disconnect" button that allows the Org_Admin to remove the connection.
6. THE Settings_API SHALL return the Stripe Connect status for the authenticated org, including whether a Connected_Account exists and the masked account ID.
7. THE Settings_API SHALL NOT return the full Connected_Account ID in the response — only the last 4 characters.

### Requirement 2: Stripe Connect OAuth Flow

**User Story:** As an Org Admin, I want to connect my Stripe account via OAuth, so that my organisation can receive online payments from customers.

#### Acceptance Criteria

1. WHEN the Org_Admin clicks "Set Up Now", THE Online_Payments_Page SHALL redirect the browser to the Stripe_Connect_OAuth authorisation URL.
2. WHEN Stripe redirects back after successful authorisation, THE Stripe_Connect_OAuth callback endpoint SHALL exchange the authorisation code for a Connected_Account ID and store it on the organisation record.
3. WHEN the OAuth callback succeeds, THE Online_Payments_Page SHALL update to show the "Connected" status without requiring a full page reload.
4. IF the OAuth callback fails (invalid code, network error, or state mismatch), THEN THE Stripe_Connect_OAuth callback endpoint SHALL return a descriptive error and the Online_Payments_Page SHALL display the error message to the Org_Admin.
5. THE Stripe_Connect_OAuth flow SHALL include a CSRF state token containing the org ID, and the callback SHALL verify the state token matches the authenticated org.
6. IF the global admin has not configured the Stripe Connect client ID, THEN THE Online_Payments_Page SHALL display a message indicating that online payments are not available and hide the "Set Up Now" button.

### Requirement 3: Disconnect Stripe Account

**User Story:** As an Org Admin, I want to disconnect my Stripe account, so that I can stop receiving online payments or switch to a different Stripe account.

#### Acceptance Criteria

1. WHEN the Org_Admin clicks "Disconnect", THE Online_Payments_Page SHALL display a confirmation dialog warning that existing payment links will stop working.
2. WHEN the Org_Admin confirms disconnection, THE Settings_API SHALL clear the Connected_Account ID from the organisation record.
3. WHEN disconnection succeeds, THE Online_Payments_Page SHALL update to show the "Not Connected" status and the "Set Up Now" button.
4. THE Settings_API SHALL write an audit log entry when a Connected_Account is disconnected, recording the previous account ID (masked) and the user who performed the action.

### Requirement 4: Invoice Payment Link Generation

**User Story:** As an Org Admin, I want to generate a payment link for an invoice, so that I can send it to my customer for online payment.

#### Acceptance Criteria

1. WHEN an invoice has status "issued", "partially_paid", or "overdue" and the org has a Connected_Account, THE Invoice detail page SHALL display a "Pay Now" or "Send Payment Link" action.
2. WHEN the Org_Admin triggers payment link generation, THE Payments service SHALL create a Checkout_Session on the Connected_Account for the invoice balance due (or a specified partial amount).
3. THE Checkout_Session SHALL include the invoice ID in its metadata so the webhook can match the payment to the correct invoice.
4. WHEN the Checkout_Session is created successfully, THE Invoice detail page SHALL display the payment URL and offer options to copy the link, send via email, or send via SMS.
5. IF the org has no Connected_Account, THEN THE Invoice detail page SHALL NOT display the payment link action.
6. THE Checkout_Session SHALL use the invoice currency and the org's Connected_Account for payment processing.

### Requirement 5: Customer Portal Pay Now Button

**User Story:** As a customer viewing my invoice in the portal, I want to click "Pay Now" to pay online, so that I can settle my invoice without contacting the business.

#### Acceptance Criteria

1. WHEN a customer views an invoice with status "issued", "partially_paid", or "overdue" in the customer portal, THE portal invoice page SHALL display a "Pay Now" button if the org has a Connected_Account.
2. WHEN the customer clicks "Pay Now", THE portal service SHALL create a Checkout_Session on the Connected_Account and redirect the customer to the Stripe-hosted payment page.
3. WHEN the payment succeeds, THE Checkout_Session success URL SHALL redirect the customer back to the portal with a payment confirmation message.
4. WHEN the customer cancels the payment, THE Checkout_Session cancel URL SHALL redirect the customer back to the portal invoice page.
5. IF the org has no Connected_Account, THEN THE portal invoice page SHALL NOT display the "Pay Now" button.

### Requirement 6: Automatic Payment Recording via Webhook

**User Story:** As an Org Admin, I want payments to be automatically recorded when customers pay via Stripe, so that I do not have to manually update invoice statuses.

#### Acceptance Criteria

1. WHEN a `checkout.session.completed` event is received, THE Payment_Webhook_Handler SHALL create a Payment record with method "stripe" and update the invoice's amount_paid, balance_due, and status.
2. WHEN the payment amount equals the invoice balance_due, THE Payment_Webhook_Handler SHALL set the invoice status to "paid".
3. WHEN the payment amount is less than the invoice balance_due, THE Payment_Webhook_Handler SHALL set the invoice status to "partially_paid".
4. THE Payment_Webhook_Handler SHALL verify the webhook signature using the signing secret before processing any event.
5. IF the webhook signature verification fails, THEN THE Payment_Webhook_Handler SHALL return HTTP 400 and not process the event.
6. THE Payment_Webhook_Handler SHALL be idempotent — processing the same event twice SHALL NOT create duplicate Payment records.
7. WHEN a payment is recorded, THE Payment_Webhook_Handler SHALL send a best-effort payment receipt email to the customer.
8. THE Payment_Webhook_Handler SHALL cap the payment amount at the invoice balance_due to prevent overpayment.

### Requirement 7: Application Fee Configuration

**User Story:** As a platform operator, I want to optionally charge an application fee on each transaction, so that the platform can generate revenue from payment processing.

#### Acceptance Criteria

1. WHERE the platform has configured an application fee percentage, THE Checkout_Session creation SHALL include a `payment_intent_data.application_fee_amount` calculated as the specified percentage of the payment amount.
2. WHERE no application fee is configured, THE Checkout_Session creation SHALL NOT include an application fee, and the full payment amount SHALL go to the Connected_Account.
3. THE application fee percentage SHALL be configurable in the global admin integrations page as part of the Stripe Connect settings.

### Requirement 8: Online Payments Status on Invoice List

**User Story:** As an Org Admin, I want to see which invoices have been paid online, so that I can track payment methods across my invoices.

#### Acceptance Criteria

1. WHEN an invoice has one or more Stripe payments, THE invoice list and detail pages SHALL display a visual indicator (badge or icon) showing that online payment was received.
2. THE payment history for an invoice SHALL distinguish between cash payments and Stripe payments, showing the payment method for each entry.
