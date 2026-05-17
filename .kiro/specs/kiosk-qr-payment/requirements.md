# Requirements Document

## Introduction

This feature adds QR code payment capability to the kiosk and invoice creation workflow. When a staff member clicks "QR Payment" on the InvoiceCreate page, the system simultaneously issues the invoice AND creates a Stripe Checkout Session. The org user's screen shows a "waiting for payment" popup (dismissible), while the kiosk screen — which polls for pending QR sessions — automatically detects and displays the QR code with the Stripe Checkout URL. The customer scans the QR code with their phone, pays via Stripe Checkout (card, Apple Pay, Google Pay, or Afterpay), and both screens update: the kiosk shows a success animation then returns to the check-in welcome screen, and the org user gets a green tick notification with the invoice status changing to "paid". This leverages the existing Stripe Connect integration — each organisation's connected account processes the payment with the platform collecting an application fee.

## Glossary

- **Kiosk_Screen**: The customer-facing kiosk display that shows the check-in welcome screen and auto-displays QR codes when a pending QR session is detected for the org
- **Org_User_Screen**: The staff member's screen (InvoiceCreate page) where the "QR Payment" button lives and a "waiting for payment" popup is shown
- **QR_Payment_Button**: The action button on InvoiceCreate that issues the invoice AND creates a Stripe Checkout Session in one action
- **Waiting_Popup**: A dismissible popup on the org user's screen showing a spinner/status while waiting for the customer to pay
- **Kiosk_QR_Popup**: The full-screen popup on the kiosk screen displaying the QR code, amount, and scan instructions
- **Pending_QR_Session**: A record (Redis key or DB row) scoped to an org containing session_id, checkout_url, amount, and invoice_number for the active QR payment
- **Checkout_Session_Service**: The backend service responsible for creating Stripe Checkout Sessions on the organisation's connected Stripe account and storing the pending session
- **Payment_Recorder**: The backend service that records payments in the payments table and updates invoice status
- **Stripe_Checkout_Page**: The Stripe-hosted payment page opened on the customer's phone after scanning the QR code
- **Platform_Fee**: The application fee collected by the OraInvoice platform on each payment processed through Stripe Connect
- **Connected_Account**: The organisation's Stripe account linked via Stripe Connect OAuth, identified by `stripe_connect_account_id` on the organisations table
- **Session_Expiry_Timer**: The countdown timer displayed on the Kiosk_QR_Popup indicating remaining time before the Checkout Session expires
- **Webhook_Handler**: The existing endpoint at `/api/v1/payments/stripe/webhook` that receives Stripe events for connected accounts

## Requirements

### Requirement 1: QR Payment Button on InvoiceCreate

**User Story:** As a staff member, I want a "QR Payment" button on the InvoiceCreate page alongside the other action buttons (Cancel, Save as Draft, Mark Paid & Email, Save and Send), so that I can issue an invoice and initiate a QR payment in one click.

#### Acceptance Criteria

1.1 THE Org_User_Screen SHALL display a "QR Payment" button on the InvoiceCreate page alongside the existing action buttons (Cancel, Save as Draft, Mark Paid & Email, Save and Send)
1.2 WHILE the organisation does not have a Connected_Account configured, THE Org_User_Screen SHALL hide the "QR Payment" button
1.3 WHEN the staff member clicks "QR Payment", THE system SHALL issue the invoice (save with status "sent") AND create a Stripe Checkout Session in one atomic action
1.4 WHEN the "QR Payment" action succeeds, THE Org_User_Screen SHALL display the Waiting_Popup showing a spinner and "Waiting for payment..." status
1.5 THE Waiting_Popup SHALL be dismissible — the staff member can close it manually without cancelling the payment session

### Requirement 2: Stripe Checkout Session Creation

**User Story:** As a staff member, I want the system to generate a Stripe Checkout Session for the invoice balance when I click "QR Payment", so that a payment link can be encoded as a QR code for the customer to scan on the kiosk.

#### Acceptance Criteria

2.1 WHEN the QR payment flow is initiated, THE Checkout_Session_Service SHALL create a Stripe Checkout Session using the organisation's Connected_Account
2.2 THE Checkout_Session_Service SHALL set the Checkout Session payment amount to the invoice's total value in NZD cents
2.3 THE Checkout_Session_Service SHALL configure the Checkout Session with payment method types: "card" (which auto-enables Apple Pay and Google Pay) and "afterpay_clearpay"
2.4 THE Checkout_Session_Service SHALL set an application_fee_amount on the Checkout Session based on the platform's configured fee percentage
2.5 THE Checkout_Session_Service SHALL set the Checkout Session success_url to a confirmation page URL that includes the invoice ID and session ID as query parameters
2.6 THE Checkout_Session_Service SHALL set the Checkout Session cancel_url to a cancellation page URL that includes the invoice ID
2.7 THE Checkout_Session_Service SHALL set the Checkout Session expiry to 30 minutes (Stripe minimum)
2.8 THE Checkout_Session_Service SHALL include the invoice ID, organisation ID, and `source: "kiosk_qr"` as metadata on the Checkout Session for webhook reconciliation
2.9 IF the Stripe API returns an error during session creation, THEN THE Checkout_Session_Service SHALL return a descriptive error message to the frontend
2.10 THE Checkout_Session_Service SHALL retrieve the Stripe secret key from the database using the existing `get_stripe_secret_key()` helper function

### Requirement 3: Pending QR Session Storage

**User Story:** As a system, I need to store the active QR session details scoped to the org so that the kiosk can discover and display it.

#### Acceptance Criteria

3.1 WHEN a QR Checkout Session is created, THE Checkout_Session_Service SHALL store a Pending_QR_Session record containing: session_id, checkout_url, amount, invoice_number, and created_at
3.2 THE Pending_QR_Session SHALL be scoped to the organisation (one active session per org at a time)
3.3 WHEN a payment completes or the session expires, THE system SHALL clear the Pending_QR_Session for that org
3.4 THE Pending_QR_Session storage SHALL use either a Redis key with TTL or a database row (implementation choice)

### Requirement 4: Kiosk Polls for Pending QR Sessions

**User Story:** As a kiosk operator, I want the kiosk screen to automatically detect when a QR payment session has been created for my org, so that it displays the QR code without any manual action on the kiosk.

#### Acceptance Criteria

4.1 THE Kiosk_Screen SHALL poll a lightweight endpoint every 2-3 seconds to check for a Pending_QR_Session for its org: `GET /api/v1/payments/qr-session/pending`
4.2 WHEN the poll detects a Pending_QR_Session, THE Kiosk_Screen SHALL display the Kiosk_QR_Popup with the QR code, amount, and scan instructions
4.3 WHEN no Pending_QR_Session exists, THE endpoint SHALL return null/empty and the kiosk continues polling silently
4.4 THE polling endpoint SHALL require authentication (kiosk user role or org_admin/salesperson)

### Requirement 5: QR Code Display on Kiosk

**User Story:** As a customer at the counter, I want to see a large, clear QR code on the kiosk screen, so that I can easily scan it with my phone to pay.

#### Acceptance Criteria

5.1 WHEN a Pending_QR_Session is detected, THE Kiosk_QR_Popup SHALL display a QR code encoding the Checkout Session URL
5.2 THE Kiosk_QR_Popup SHALL render the QR code at a minimum size of 280×280 CSS pixels for reliable scanning from arm's length
5.3 THE Kiosk_QR_Popup SHALL display the payment amount formatted as NZD currency (e.g. "$125.50") prominently above the QR code
5.4 THE Kiosk_QR_Popup SHALL display the invoice number for reference
5.5 THE Kiosk_QR_Popup SHALL display instructional text (e.g. "Scan with your phone camera to pay")
5.6 THE Kiosk_QR_Popup SHALL occupy the full viewport as a modal overlay

### Requirement 6: Countdown Timer and Expiry

**User Story:** As a customer or staff member viewing the kiosk, I want to see how much time remains before the QR code expires.

#### Acceptance Criteria

6.1 THE Kiosk_QR_Popup SHALL display a Session_Expiry_Timer showing the remaining time in minutes and seconds (e.g. "14:32 remaining")
6.2 WHEN the Session_Expiry_Timer reaches zero, THE Kiosk_QR_Popup SHALL dismiss and the kiosk returns to its normal state (check-in welcome screen)
6.3 WHILE the Session_Expiry_Timer has less than 2 minutes remaining, THE Kiosk_QR_Popup SHALL display the timer in a warning colour (orange or red)

### Requirement 7: Payment Detection and Success Flow

**User Story:** As a staff member, I want both the kiosk and my screen to automatically detect when the customer has paid, so that I do not have to manually check or refresh.

#### Acceptance Criteria

7.1 WHILE the Kiosk_QR_Popup is displayed, THE Kiosk_Screen SHALL poll the Checkout Session status every 3 seconds to detect payment completion
7.2 WHEN payment is detected as complete on the kiosk, THE Kiosk_Screen SHALL show a green tick + "Thank you" + paid amount for 3-5 seconds, then auto-dismiss and return to the check-in welcome screen
7.3 WHEN payment is detected as complete on the org user's screen (if Waiting_Popup is still open), THE Org_User_Screen SHALL show a green tick notification and update the invoice status to "paid"
7.4 IF the Waiting_Popup was already dismissed, THE invoice status SHALL still update to "paid" when the page is refreshed or the invoice is next viewed
7.5 IF the polling request fails due to a network error, THEN THE Kiosk_Screen SHALL continue polling without displaying an error to the user (silent retry)

### Requirement 8: Webhook-Based Payment Recording

**User Story:** As a system operator, I want payments to be recorded via webhook even if the kiosk screen is closed or loses connection, so that no payments are lost.

#### Acceptance Criteria

8.1 WHEN the Webhook_Handler receives a `checkout.session.completed` event with metadata containing an invoice_id and `source: "kiosk_qr"`, THE Payment_Recorder SHALL record the payment against that invoice
8.2 THE Payment_Recorder SHALL verify the payment has not already been recorded for the same Checkout Session ID before creating a duplicate payment record (idempotent processing)
8.3 WHEN the webhook records a payment, THE Payment_Recorder SHALL update the invoice status based on whether the balance_due is now zero (paid) or still positive (partially_paid)
8.4 THE Webhook_Handler SHALL process `checkout.session.completed` events for QR payments using the same endpoint and signature verification as existing Stripe webhooks
8.5 WHEN the webhook records a payment, THE system SHALL clear the Pending_QR_Session for that org
8.6 WHEN payment completes, THE customer SHALL receive an email invoice (existing webhook email behaviour)

### Requirement 9: Org User Waiting Popup

**User Story:** As a staff member, I want to see a "waiting for payment" indicator after clicking QR Payment, so I know the system is working and can optionally wait for confirmation.

#### Acceptance Criteria

9.1 WHEN the QR Payment action succeeds, THE Waiting_Popup SHALL display with a spinner/loading animation and text "Waiting for payment..."
9.2 THE Waiting_Popup SHALL NOT display the QR code (QR is only on the kiosk)
9.3 THE Waiting_Popup SHALL have a "Close" or "×" button to dismiss it without cancelling the payment
9.4 WHEN payment completes while the Waiting_Popup is open, THE popup SHALL show a green tick + "Payment received — $X.XX" for 3 seconds then auto-close
9.5 WHEN the Waiting_Popup is closed manually, THE payment session remains active — the kiosk continues showing the QR code

### Requirement 10: Multi-Organisation Support

**User Story:** As a platform operator, I want QR payments to work for any organisation with Stripe Connect active, so that all connected organisations can use this feature.

#### Acceptance Criteria

10.1 THE Checkout_Session_Service SHALL use the requesting organisation's `stripe_connect_account_id` from the organisations table when creating the Checkout Session
10.2 IF the organisation does not have a `stripe_connect_account_id` set, THEN THE Checkout_Session_Service SHALL return an error indicating Stripe Connect is not configured
10.3 THE Checkout_Session_Service SHALL pass the `stripe_account` parameter (connected account ID) to all Stripe API calls for the session

### Requirement 11: Checkout Session Status Endpoint

**User Story:** As a frontend developer, I want a backend endpoint to check the status of a Checkout Session, so that the kiosk can poll for payment completion.

#### Acceptance Criteria

11.1 THE Checkout_Session_Service SHALL expose a GET endpoint that accepts a Checkout Session ID and returns the session status (open, complete, expired)
11.2 THE status endpoint SHALL verify the Checkout Session belongs to the requesting organisation's connected account
11.3 THE status endpoint SHALL require authentication (org_admin, salesperson, or kiosk role)
11.4 WHEN the session status is "complete", THE status endpoint SHALL include the payment_intent ID in the response for reference

### Requirement 12: No External Configuration Required

**User Story:** As an organisation admin, I want QR payments to work without any additional Stripe configuration, so that I can start using the feature immediately after connecting my Stripe account.

#### Acceptance Criteria

12.1 THE Checkout_Session_Service SHALL rely solely on the existing Stripe Connect integration (connected account ID and platform secret key) without requiring additional API keys or configuration from the organisation
12.2 THE Stripe_Checkout_Page SHALL automatically detect and offer Apple Pay on iOS Safari and Google Pay on Android Chrome based on the customer's device capabilities (handled by Stripe Checkout natively)
12.3 WHERE the organisation has enabled Afterpay in their Stripe Dashboard, THE Stripe_Checkout_Page SHALL display Afterpay as a payment option for eligible amounts ($1–$2000 NZD)
