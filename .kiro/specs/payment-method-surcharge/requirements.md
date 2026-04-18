# Requirements Document

## Introduction

Payment Method Surcharge allows organisation admins to pass Stripe processing fees to customers at payment time. When enabled, the surcharge is calculated dynamically based on the customer's selected payment method and displayed transparently on the public payment page (`/pay/{token}`) before the customer confirms payment. The invoice amount itself remains unchanged — the surcharge is a payment-time addition. This feature must comply with NZ consumer law, which requires surcharges to be disclosed before payment and not exceed actual merchant cost.

## Glossary

- **Surcharge_Engine**: The backend service module responsible for computing surcharge amounts based on payment method type and configured fee rates.
- **Payment_Page**: The public-facing invoice payment page at `/pay/{token}` that displays invoice details and collects payment via Stripe PaymentElement.
- **Surcharge_Settings_Panel**: The UI section within the Online Payments settings page where org admins configure surcharge enablement and fee rates per payment method.
- **Org_Admin**: A user with the `admin` role within an organisation who can modify org-level settings.
- **Fee_Rate**: A configured surcharge rate for a specific payment method, consisting of a percentage component and/or a fixed-amount component (in the invoice currency).
- **PaymentIntent**: A Stripe API object representing a payment attempt; its `amount` field must be updated to include the surcharge before confirmation.
- **Payment_Record**: A row in the `payments` table that records a completed payment, including both the invoice amount and the surcharge amount separately.
- **Connected_Account**: The organisation's Stripe account connected via Stripe Connect OAuth, used for Direct Charges with the `Stripe-Account` header.

## Requirements

### Requirement 1: Surcharge Master Toggle

**User Story:** As an Org_Admin, I want to enable or disable surcharging globally for my organisation, so that I can choose whether to pass processing fees to customers.

#### Acceptance Criteria

1. THE Surcharge_Settings_Panel SHALL display a toggle to enable or disable surcharging for the organisation.
2. WHEN the Org_Admin enables surcharging, THE Surcharge_Settings_Panel SHALL persist the `surcharge_enabled` flag as `true` in the organisation's `settings` JSONB column.
3. WHEN the Org_Admin disables surcharging, THE Surcharge_Settings_Panel SHALL persist the `surcharge_enabled` flag as `false` in the organisation's `settings` JSONB column.
4. WHEN surcharging is disabled, THE Payment_Page SHALL display the original invoice balance due with no surcharge line item.
5. THE Surcharge_Settings_Panel SHALL default the `surcharge_enabled` flag to `false` for organisations that have not configured surcharging.

### Requirement 2: Per-Method Fee Rate Configuration

**User Story:** As an Org_Admin, I want to configure surcharge fee rates per payment method, so that each method's surcharge reflects its actual processing cost.

#### Acceptance Criteria

1. WHEN surcharging is enabled, THE Surcharge_Settings_Panel SHALL display a fee rate configuration row for each enabled payment method (card, Afterpay, Klarna, bank transfer).
2. THE Surcharge_Settings_Panel SHALL allow the Org_Admin to set a percentage fee (0.00%–10.00%) and a fixed fee ($0.00–$5.00) for each payment method.
3. THE Surcharge_Settings_Panel SHALL pre-populate default NZ Stripe Connect fee rates: card 2.9% + $0.30, Afterpay 6% + $0.30, Klarna 5.99% + $0.00, bank transfer 1% + $0.00.
4. WHEN the Org_Admin saves fee rate configuration, THE Surcharge_Settings_Panel SHALL persist the rates in the organisation's `settings` JSONB column under a `surcharge_rates` key.
5. THE Surcharge_Settings_Panel SHALL allow the Org_Admin to enable or disable surcharging per individual payment method while the master toggle is on.
6. IF the Org_Admin enters a percentage fee greater than 10.00% or a fixed fee greater than $5.00, THEN THE Surcharge_Settings_Panel SHALL display a validation error and reject the save.
7. IF the Org_Admin enters a negative percentage fee or a negative fixed fee, THEN THE Surcharge_Settings_Panel SHALL display a validation error and reject the save.

### Requirement 3: Dynamic Surcharge Calculation

**User Story:** As a customer, I want to see the surcharge amount update when I select a different payment method, so that I know the total cost before confirming payment.

#### Acceptance Criteria

1. WHEN the Payment_Page loads for an invoice where surcharging is enabled, THE Payment_Page SHALL fetch the surcharge rates for the organisation's enabled payment methods.
2. WHEN the customer selects a payment method on the Payment_Page, THE Surcharge_Engine SHALL compute the surcharge as: `surcharge = (balance_due × percentage_rate / 100) + fixed_fee`, rounded to 2 decimal places using banker's rounding.
3. WHEN the customer selects a payment method that has surcharging disabled, THE Payment_Page SHALL display no surcharge for that method.
4. THE Surcharge_Engine SHALL compute the surcharge on the original invoice `balance_due`, not on a previously surcharged amount (no compounding).
5. FOR ALL valid balance_due values and fee rate combinations, computing the surcharge then adding it to the balance_due SHALL produce a total equal to `balance_due + surcharge` (no rounding drift across the addition).

### Requirement 4: Transparent Surcharge Display

**User Story:** As a customer, I want to see the surcharge as a separate line item on the payment page, so that I understand exactly what I am paying.

#### Acceptance Criteria

1. WHEN a surcharge applies, THE Payment_Page SHALL display the surcharge as a separate line item labelled "Payment method surcharge ({method_name})" between the balance due and the total to pay.
2. WHEN a surcharge applies, THE Payment_Page SHALL display the total to pay as `balance_due + surcharge`.
3. WHEN no surcharge applies (surcharging disabled or method not surcharged), THE Payment_Page SHALL display only the balance due as the total to pay.
4. THE Payment_Page SHALL display a disclosure notice stating "A surcharge is applied to cover payment processing fees" when surcharging is active for the selected method.
5. WHEN the customer changes the selected payment method, THE Payment_Page SHALL update the surcharge line item and total to pay within the same render cycle (no page reload).

### Requirement 5: PaymentIntent Amount Update

**User Story:** As a system operator, I want the Stripe PaymentIntent amount to include the surcharge, so that the correct total is charged to the customer.

#### Acceptance Criteria

1. WHEN the customer selects a payment method with a surcharge on the Payment_Page, THE Payment_Page SHALL call a backend endpoint to update the PaymentIntent amount to `balance_due + surcharge` (in cents).
2. WHEN the customer switches to a different payment method, THE Payment_Page SHALL call the backend endpoint to update the PaymentIntent amount to reflect the new surcharge (or remove it if the new method has no surcharge).
3. THE Surcharge_Engine SHALL validate that the requested surcharge matches the server-side calculation before updating the PaymentIntent, to prevent client-side tampering.
4. IF the PaymentIntent update fails, THEN THE Payment_Page SHALL display an error message and prevent payment confirmation.
5. THE Surcharge_Engine SHALL store the surcharge amount and payment method type in the PaymentIntent metadata as `surcharge_amount` and `surcharge_method`.

### Requirement 6: Payment Record with Surcharge Breakdown

**User Story:** As an Org_Admin, I want payment records to store the surcharge separately from the invoice amount, so that I can reconcile fees accurately.

#### Acceptance Criteria

1. WHEN a payment with a surcharge is recorded (via webhook or confirm endpoint), THE Payment_Record SHALL store the surcharge amount in a `surcharge_amount` column (Numeric 12,2, default 0.00).
2. WHEN a payment with a surcharge is recorded, THE Payment_Record SHALL store the payment method type used in a `payment_method_type` column (e.g. "card", "afterpay_clearpay", "klarna").
3. THE Payment_Record `amount` column SHALL continue to represent the invoice payment amount (excluding surcharge).
4. WHEN the webhook or confirm endpoint processes a surcharged payment, THE Surcharge_Engine SHALL extract the surcharge amount from the PaymentIntent metadata and store it on the Payment_Record.
5. THE Payment_Record SHALL allow querying total surcharges collected per organisation for reporting purposes.

### Requirement 7: Receipt Email with Surcharge Breakdown

**User Story:** As a customer, I want the payment receipt email to show the surcharge breakdown, so that I have a clear record of what I paid.

#### Acceptance Criteria

1. WHEN a payment receipt email is sent for a surcharged payment, THE receipt email SHALL display the invoice amount, surcharge amount, and total paid as separate line items.
2. WHEN a payment receipt email is sent for a non-surcharged payment, THE receipt email SHALL display only the payment amount with no surcharge line.
3. THE receipt email SHALL label the surcharge line as "Payment method surcharge" followed by the payment method name in parentheses.

### Requirement 8: NZ Compliance Safeguards

**User Story:** As a platform operator, I want surcharges to comply with NZ consumer law, so that organisations using the platform do not inadvertently breach regulations.

#### Acceptance Criteria

1. THE Surcharge_Settings_Panel SHALL display a compliance notice informing the Org_Admin that surcharges must not exceed actual merchant processing costs under NZ law.
2. IF the Org_Admin configures a percentage fee that exceeds the default Stripe rate for that payment method by more than 0.5 percentage points, THEN THE Surcharge_Settings_Panel SHALL display a warning that the configured rate may exceed actual costs.
3. THE Payment_Page SHALL disclose the surcharge amount to the customer before the payment confirmation button is enabled.
4. WHEN surcharging is enabled, THE Surcharge_Settings_Panel SHALL require the Org_Admin to acknowledge the NZ compliance notice before saving for the first time.

### Requirement 9: Surcharge Rate Serialisation

**User Story:** As a developer, I want surcharge rate configuration to be serialised and deserialised reliably, so that rates are never corrupted during storage or retrieval.

#### Acceptance Criteria

1. THE Surcharge_Engine SHALL serialise surcharge rates to JSON with percentage as a string with 2 decimal places and fixed fee as a string with 2 decimal places, to avoid floating-point precision loss.
2. THE Surcharge_Engine SHALL deserialise surcharge rate JSON strings back into Decimal objects for computation.
3. FOR ALL valid surcharge rate configurations, serialising then deserialising then serialising again SHALL produce an identical JSON string (round-trip property).
4. IF the Surcharge_Engine encounters a malformed surcharge rate entry during deserialisation, THEN THE Surcharge_Engine SHALL use the default rate for that payment method and log a warning.
