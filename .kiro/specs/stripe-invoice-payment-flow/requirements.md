# Requirements Document

## Introduction

This feature enhances the invoice payment flow when "Stripe" is selected as the payment method. Currently, selecting Stripe on an invoice and clicking "Save and Send" issues the invoice and emails the customer, but does not generate a Stripe payment link or provide a custom payment experience. This spec adds:

1. **Automatic Stripe payment link generation** when an invoice with `payment_gateway: "stripe"` is issued via "Save and Send"
2. **Payment link inclusion in the invoice email** so the customer receives a clickable "Pay Now" link
3. **A custom payment page** (not Stripe's hosted checkout) that shows an invoice preview alongside a Stripe Elements payment form
4. **Payment processing via Stripe Connect** so funds go to the org's connected Stripe account, not the platform's own account
5. **Webhook-driven payment recording** reusing the existing `checkout.session.completed` handler

**Key context:** The project already has Stripe Connect integration (OAuth, connected accounts), a `create_payment_link()` function that creates Checkout Sessions on connected accounts, an `email_invoice()` function that sends invoice emails via SMTP, a `payment_gateway` field saved on invoices, and a signup payment UI using `@stripe/react-stripe-js` with `CardElement` that can be referenced. The customer portal already exists at `frontend/src/pages/portal/` with invoice viewing. The existing payment flow uses Stripe's hosted Checkout page — this spec replaces that with a custom payment page using Stripe Elements for invoice payments.

## Glossary

- **Invoice_Email_Service**: The `email_invoice()` function in `app/modules/invoices/service.py` that generates the invoice PDF and sends it to the customer via SMTP.
- **Payment_Link_Service**: The backend service that creates a Stripe PaymentIntent on the org's connected Stripe account and generates a URL to the custom payment page.
- **Custom_Payment_Page**: A public-facing React page that displays an invoice preview on one side and a Stripe Elements payment form on the other side, accessible via a secure token without authentication.
- **Stripe_Elements_Form**: The payment form component using `@stripe/react-stripe-js` (`PaymentElement` or `CardElement`) that collects card details client-side and confirms the PaymentIntent.
- **Connected_Account**: The org's Stripe account (identified by `acct_...`) linked via Stripe Connect OAuth, which receives the payment funds.
- **Payment_Token**: A short-lived, single-use or time-limited token embedded in the payment URL that grants access to the custom payment page for a specific invoice without requiring authentication.
- **PaymentIntent**: A Stripe API object representing a payment to be collected, created on the Connected_Account using the platform's secret key with the `Stripe-Account` header.
- **Application_Fee**: An optional per-transaction fee the platform deducts from payments before they reach the Connected_Account, configured via `payment_intent_data[application_fee_amount]`.
- **Invoice_Create_Page**: The frontend page at `frontend/src/pages/invoices/InvoiceCreate.tsx` where users create and send invoices.
- **Org_Admin**: A user with the `org_admin` role who manages organisation settings and invoices.
- **Salesperson**: A user with the `salesperson` role who can create and send invoices.

## Requirements

### Requirement 1: Stripe Payment Link Generation on Invoice Issue

**User Story:** As an Org Admin or Salesperson, I want a Stripe payment link to be automatically generated when I issue an invoice with Stripe as the payment method, so that my customer receives a way to pay online without me having to manually create a payment link.

#### Acceptance Criteria

1. WHEN an invoice with `payment_gateway` set to "stripe" is issued via "Save and Send", THE Payment_Link_Service SHALL create a PaymentIntent on the Connected_Account for the invoice's `balance_due` amount.
2. THE Payment_Link_Service SHALL store the PaymentIntent ID and the payment page URL on the invoice record so the link can be retrieved later.
3. THE PaymentIntent SHALL include the invoice ID in its metadata so the webhook handler can match the payment to the correct invoice.
4. THE PaymentIntent SHALL use the invoice's currency and the org's Connected_Account for payment processing.
5. IF the org has no Connected_Account, THEN THE Invoice_Create_Page SHALL disable the Stripe payment gateway option (existing behaviour — no change needed).
6. WHERE the platform has configured an application fee percentage, THE PaymentIntent creation SHALL include a `payment_intent_data[application_fee_amount]` calculated as the specified percentage of the payment amount.
7. IF PaymentIntent creation fails (Stripe API error, network timeout), THEN THE Payment_Link_Service SHALL still issue the invoice and send the email without the payment link, and SHALL log the error for investigation.

### Requirement 2: Payment Link in Invoice Email

**User Story:** As a customer, I want to receive a "Pay Now" link in my invoice email, so that I can pay the invoice online with one click.

#### Acceptance Criteria

1. WHEN an invoice email is sent and the invoice has a Stripe payment link stored, THE Invoice_Email_Service SHALL include a "Pay Now" button or link in the email body that opens the Custom_Payment_Page.
2. THE Invoice_Email_Service SHALL include the payment link in both the plain-text and HTML versions of the email.
3. WHEN an invoice email is sent and the invoice has no Stripe payment link (payment_gateway is not "stripe" or link generation failed), THE Invoice_Email_Service SHALL send the email in its current format without a payment link.
4. THE payment link in the email SHALL open in a new browser tab when clicked.

### Requirement 3: Payment Token Generation and Validation

**User Story:** As a platform operator, I want payment page access to be secured with a token, so that only intended recipients can view invoice details and make payments.

#### Acceptance Criteria

1. WHEN a payment link is generated, THE Payment_Link_Service SHALL create a Payment_Token that is unique, cryptographically random, and associated with the specific invoice.
2. THE Payment_Token SHALL expire after 72 hours from creation to limit the window of exposure.
3. WHEN a request is made to the Custom_Payment_Page with a valid, non-expired Payment_Token, THE backend SHALL return the invoice details and Stripe client secret needed to render the page.
4. IF a request is made with an expired Payment_Token, THEN THE backend SHALL return an error indicating the link has expired and suggest the customer contact the business for a new link.
5. IF a request is made with an invalid Payment_Token, THEN THE backend SHALL return a generic "invalid link" error without revealing whether the token existed.
6. THE Payment_Token SHALL be a UUID or URL-safe random string of at least 32 characters to prevent guessing.

### Requirement 4: Custom Payment Page — Invoice Preview

**User Story:** As a customer, I want to see my invoice details before paying, so that I can verify the amount and line items before entering my card details.

#### Acceptance Criteria

1. THE Custom_Payment_Page SHALL display the invoice preview on the left side (desktop) or top section (mobile) showing: org name, invoice number, issue date, due date, line items with descriptions and amounts, subtotal, GST amount, total, amount already paid, and balance due.
2. THE Custom_Payment_Page SHALL display the org's branding (logo and primary colour) if configured in the org settings.
3. THE Custom_Payment_Page SHALL be responsive, stacking the invoice preview above the payment form on screens narrower than 768px.
4. WHEN the invoice has status "paid", THE Custom_Payment_Page SHALL display a "This invoice has been paid" message instead of the payment form.
5. WHEN the invoice has status "voided" or "draft", THE Custom_Payment_Page SHALL display an appropriate message indicating the invoice is not payable.

### Requirement 5: Custom Payment Page — Stripe Elements Payment Form

**User Story:** As a customer, I want to enter my card details on a branded payment form embedded in the invoice page, so that I can pay without being redirected to a separate Stripe checkout page.

#### Acceptance Criteria

1. THE Stripe_Elements_Form SHALL be rendered on the right side (desktop) or bottom section (mobile) of the Custom_Payment_Page using `@stripe/react-stripe-js` components.
2. THE Stripe_Elements_Form SHALL use the PaymentIntent client secret from the backend to initialise Stripe Elements, with the `Stripe-Account` header set to the org's Connected_Account ID so the payment form renders in the context of the connected account.
3. THE Stripe_Elements_Form SHALL display the amount to be charged and a "Pay Now" button.
4. WHEN the customer submits the form, THE Stripe_Elements_Form SHALL call `stripe.confirmPayment()` with the PaymentElement and handle the result.
5. WHEN the payment succeeds, THE Custom_Payment_Page SHALL display a success confirmation message with the amount paid and invoice number.
6. IF the payment fails (card declined, insufficient funds, authentication required), THEN THE Stripe_Elements_Form SHALL display the Stripe error message and allow the customer to retry.
7. THE Stripe_Elements_Form SHALL disable the "Pay Now" button while payment is processing to prevent double submissions.
8. THE Custom_Payment_Page SHALL load the Stripe.js library using the platform's publishable key but initialise Elements with the Connected_Account's account ID so the payment is processed on the connected account.

### Requirement 6: Backend Payment Page API

**User Story:** As a frontend developer, I want a backend API that returns invoice details and Stripe configuration for the payment page, so that the custom payment page can render correctly.

#### Acceptance Criteria

1. THE backend SHALL expose a public endpoint (no authentication required) that accepts a Payment_Token and returns the invoice preview data, the PaymentIntent client secret, and the Connected_Account ID.
2. THE endpoint SHALL NOT return sensitive data such as the org's Stripe secret key, full Connected_Account ID, or internal user information.
3. THE endpoint SHALL return the org's branding information (name, logo URL, primary colour) for the payment page header.
4. WHEN the invoice associated with the Payment_Token has already been fully paid, THE endpoint SHALL return the invoice data with a flag indicating payment is complete, and SHALL NOT return a client secret.
5. THE endpoint SHALL return the Stripe publishable key so the frontend can initialise Stripe.js.

### Requirement 7: Payment Confirmation via Webhook

**User Story:** As an Org Admin, I want payments made through the custom payment page to be automatically recorded on the invoice, so that I do not have to manually update invoice statuses.

#### Acceptance Criteria

1. WHEN a `payment_intent.succeeded` event is received for a PaymentIntent created by the Payment_Link_Service, THE existing webhook handler SHALL create a Payment record with method "stripe" and update the invoice's amount_paid, balance_due, and status.
2. WHEN the payment amount equals the invoice balance_due, THE webhook handler SHALL set the invoice status to "paid".
3. WHEN the payment amount is less than the invoice balance_due, THE webhook handler SHALL set the invoice status to "partially_paid".
4. THE webhook handler SHALL be idempotent — processing the same event twice SHALL NOT create duplicate Payment records.
5. THE webhook handler SHALL send a best-effort payment receipt email to the customer after recording the payment.
6. THE webhook handler SHALL cap the payment amount at the invoice balance_due to prevent overpayment.

### Requirement 8: Payment Link Regeneration

**User Story:** As an Org Admin, I want to regenerate a payment link for an invoice if the original link has expired, so that I can resend it to the customer.

#### Acceptance Criteria

1. WHEN an invoice has status "issued", "partially_paid", or "overdue" and the org has a Connected_Account, THE invoice detail page SHALL display a "Regenerate Payment Link" action if the existing payment link has expired.
2. WHEN the Org Admin triggers payment link regeneration, THE Payment_Link_Service SHALL create a new PaymentIntent and Payment_Token, replacing the previous ones on the invoice record.
3. WHEN regeneration succeeds, THE invoice detail page SHALL offer options to copy the new link or resend the invoice email with the updated link.
4. THE previous Payment_Token SHALL be invalidated when a new one is generated to prevent use of stale links.

### Requirement 9: Custom Payment Page — Security and Access Control

**User Story:** As a platform operator, I want the custom payment page to be secure against common web attacks, so that customer payment data is protected.

#### Acceptance Criteria

1. THE Custom_Payment_Page SHALL be served over HTTPS only.
2. THE Custom_Payment_Page SHALL NOT store or transmit card details through the platform's servers — all card data SHALL be handled exclusively by Stripe.js and Stripe Elements.
3. THE backend payment page API SHALL rate-limit requests by IP address to prevent brute-force token guessing (maximum 20 requests per minute per IP).
4. THE Payment_Token SHALL NOT be logged in application logs or included in error messages returned to the client.
5. THE Custom_Payment_Page SHALL include appropriate Content Security Policy headers allowing only Stripe.js domains for script sources.

