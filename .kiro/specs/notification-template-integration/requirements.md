# Requirements Document

## Introduction

The notification template system (Settings → Notifications → Templates) allows organisations to customise email and SMS content for various notification types. However, the actual sending functions use hardcoded subject lines and body text instead of the org's configured templates. This feature wires up the existing template storage, rendering, and variable substitution system to the actual notification sending code paths, with a safe fallback to hardcoded content when templates are not enabled.

A full audit of all 23 email template types and 11 SMS template types has been conducted against the actual sending functions in the codebase. This document captures the complete mapping, identifies gaps, and defines requirements for wiring up all applicable templates.

## Template-to-Notification Mapping

### Email Template Types (23 defined in schemas.py)

| # | Template Type | Sending Function | Location | Status |
|---|---|---|---|---|
| 1 | `invoice_issued` | `email_invoice()` | `app/modules/invoices/service.py` | ✗ HARDCODED |
| 2 | `payment_received` | `_send_receipt_email()` | `app/modules/payments/service.py` | ✗ HARDCODED |
| 3 | `payment_overdue_reminder` | `send_payment_reminder()` | `app/modules/invoices/service.py` | ✗ HARDCODED |
| 4 | `invoice_voided` | — | — | NO SENDING FUNCTION |
| 5 | `storage_warning_80` | Platform/admin | — | OUT OF SCOPE |
| 6 | `storage_critical_90` | Platform/admin | — | OUT OF SCOPE |
| 7 | `storage_full_100` | Platform/admin | — | OUT OF SCOPE |
| 8 | `subscription_renewal_reminder` | `send_dunning_email_task()` | `app/tasks/subscriptions.py` | OUT OF SCOPE (platform billing) |
| 9 | `subscription_payment_failed` | `send_dunning_email_task()` | `app/tasks/subscriptions.py` | OUT OF SCOPE (platform billing) |
| 10 | `wof_expiry_reminder` | `_send_email_reminder()` | `app/modules/notifications/reminder_queue_service.py` | ✗ QUEUE BODY (not from templates table) |
| 11 | `cof_expiry_reminder` | `_send_email_reminder()` | `app/modules/notifications/reminder_queue_service.py` | ✗ QUEUE BODY (not from templates table) |
| 12 | `registration_expiry_reminder` | `_send_email_reminder()` | `app/modules/notifications/reminder_queue_service.py` | ✗ QUEUE BODY (not from templates table) |
| 13 | `service_due_reminder` | `_send_email_reminder()` | `app/modules/notifications/reminder_queue_service.py` | ✗ QUEUE BODY (not from templates table) |
| 14 | `booking_confirmation` | `_send_booking_confirmation_email()` | `app/modules/bookings/service.py` | ✗ HARDCODED |
| 15 | `booking_cancellation` | — | — | NO SENDING FUNCTION |
| 16 | `quote_sent` | `send_quote()` | `app/modules/quotes/service.py` | ✗ HARDCODED |
| 17 | `quote_accepted` | `_send_quote_acceptance_notification()` | `app/modules/portal/service.py` | INTERNAL (sends to org, not customer) |
| 18 | `quote_expired` | — | — | NO SENDING FUNCTION |
| 19 | `user_invitation` | `_send_invitation_email()` | `app/modules/auth/service.py` | ✗ HARDCODED |
| 20 | `password_reset` | `_send_password_reset_email()` | `app/modules/auth/service.py` | ✗ HARDCODED |
| 21 | `mfa_enrolment` | `_send_email_otp()` | `app/modules/auth/mfa_service.py` | OUT OF SCOPE (security) |
| 22 | `login_alert` | `_send_permanent_lockout_email()` / `_send_token_reuse_alert()` | `app/modules/auth/service.py` | OUT OF SCOPE (security) |
| 23 | `account_locked` | Same as login_alert | `app/modules/auth/service.py` | OUT OF SCOPE (security) |

### SMS Template Types (11 defined in schemas.py)

| # | Template Type | Sending Function | Location | Status |
|---|---|---|---|---|
| 1 | `invoice_issued` | — | — | NO SMS SENDING FUNCTION |
| 2 | `payment_overdue_reminder` | `send_payment_reminder()` SMS branch | `app/modules/invoices/service.py` | ✗ HARDCODED |
| 3 | `wof_expiry_reminder` | `_send_sms_reminder()` | `app/modules/notifications/reminder_queue_service.py` | ✗ QUEUE BODY (not from templates table) |
| 4 | `cof_expiry_reminder` | `_send_sms_reminder()` | `app/modules/notifications/reminder_queue_service.py` | ✗ QUEUE BODY (not from templates table) |
| 5 | `registration_expiry_reminder` | `_send_sms_reminder()` | `app/modules/notifications/reminder_queue_service.py` | ✗ QUEUE BODY (not from templates table) |
| 6 | `service_due_reminder` | `_send_sms_reminder()` | `app/modules/notifications/reminder_queue_service.py` | ✗ QUEUE BODY (not from templates table) |
| 7 | `booking_confirmation` | — | — | NO SMS SENDING FUNCTION |
| 8 | `booking_cancellation` | — | — | NO SMS SENDING FUNCTION |
| 9 | `quote_sent` | — | — | NO SMS SENDING FUNCTION |
| 10 | `quote_accepted` | — | — | NO SMS SENDING FUNCTION |
| 11 | `quote_expired` | — | — | NO SMS SENDING FUNCTION |

## Gap Analysis

### Gap Type A: Template + Sending Function Exist → NOT Wired Up (IN SCOPE — Priority)

These have both a template type defined and a sending function that currently uses hardcoded content. This feature wires them up.

| Template Type | Channel | Sending Function |
|---|---|---|
| `invoice_issued` | email | `email_invoice()` |
| `payment_received` | email | `_send_receipt_email()` |
| `payment_overdue_reminder` | email | `send_payment_reminder()` email branch |
| `payment_overdue_reminder` | SMS | `send_payment_reminder()` SMS branch |
| `booking_confirmation` | email | `_send_booking_confirmation_email()` |
| `quote_sent` | email | `send_quote()` |
| `wof_expiry_reminder` | email | `_send_email_reminder()` via queue |
| `wof_expiry_reminder` | SMS | `_send_sms_reminder()` via queue |
| `cof_expiry_reminder` | email | `_send_email_reminder()` via queue |
| `cof_expiry_reminder` | SMS | `_send_sms_reminder()` via queue |
| `registration_expiry_reminder` | email | `_send_email_reminder()` via queue |
| `registration_expiry_reminder` | SMS | `_send_sms_reminder()` via queue |
| `service_due_reminder` | email | `_send_email_reminder()` via queue |
| `service_due_reminder` | SMS | `_send_sms_reminder()` via queue |
| `user_invitation` | email | `_send_invitation_email()` |
| `password_reset` | email | `_send_password_reset_email()` |

### Gap Type B: Template Exists but NO Sending Function (Orphaned — Future Work)

These templates are defined in `schemas.py` but no code path currently sends this notification. Future work should create the sending functions.

| Template Type | Channel | Notes |
|---|---|---|
| `invoice_voided` | email | No email sent when an invoice is voided |
| `booking_cancellation` | email | No email sent when a booking is cancelled |
| `quote_expired` | email | No email sent when a quote expires |
| `invoice_issued` | SMS | No SMS sent when an invoice is issued |
| `booking_confirmation` | SMS | No SMS sending function for booking confirmation |
| `booking_cancellation` | SMS | No SMS sending function for booking cancellation |
| `quote_sent` | SMS | No SMS sending function for quote sent |
| `quote_accepted` | SMS | No SMS sending function for quote accepted |
| `quote_expired` | SMS | No SMS sending function for quote expired |

### Gap Type C: Sending Function Exists but NO Template Type (Non-Customisable — Excluded)

These notifications are sent but intentionally NOT customisable by orgs. They are platform-level or security-critical and should remain hardcoded.

| Sending Function | Reason for Exclusion |
|---|---|
| `_send_billing_receipt_email()` | Platform subscription billing receipt |
| `send_receipt_email()` | Signup payment receipt (platform-level) |
| `_send_email_otp()` | MFA OTP code (security — must not be customisable) |
| `_send_permanent_lockout_email()` | Account locked alert (security) |
| `_send_token_reuse_alert()` | Token theft alert (security) |
| `send_dunning_email_task()` | Platform subscription dunning (not org-customisable) |

## Glossary

- **Template_Resolver**: The service function that fetches an org's configured template for a given template type and channel, returning the rendered content or `None` if the template is not enabled
- **Sending_Function**: Any backend function that dispatches an email or SMS to a customer (e.g., `email_invoice`, `send_payment_reminder`, `_send_booking_confirmation_email`)
- **Template_Type**: A string identifier for a notification category (e.g., `invoice_issued`, `payment_overdue_reminder`, `booking_confirmation`)
- **Variable_Context**: A dictionary mapping template variable names (e.g., `customer_first_name`, `invoice_number`) to their actual runtime values for a specific notification
- **Body_Blocks**: A JSONB array of structured content blocks (header, text, button, image, divider, footer) that compose an email template body
- **Hardcoded_Fallback**: The existing inline subject/body text in each Sending_Function, preserved as the default when no enabled template is configured
- **Reminder_Queue**: The notification reminder queue system that pre-generates reminder body content at queue time; for vehicle reminders (WOF, COF, registration, service), the template should be applied when generating the queue item body rather than at send time
- **Queue_Body_Generation**: The process of rendering a template into the `body` field of a reminder queue item at the time the reminder is scheduled, so that `_send_email_reminder()` / `_send_sms_reminder()` can send the pre-rendered content directly

## Requirements

### Requirement 1: Template Resolution Service

**User Story:** As a developer, I want a reusable function that resolves and renders an org's configured template for a given type and channel, so that all sending functions can use templates consistently without duplicating lookup logic.

#### Acceptance Criteria

1. THE Template_Resolver SHALL accept an org_id, template_type, channel, and Variable_Context as inputs and return a rendered subject (for email) and rendered body string
2. WHEN the org has a template of the specified Template_Type with `is_enabled=true`, THE Template_Resolver SHALL render the template's subject and Body_Blocks using the provided Variable_Context
3. WHEN the org has no template for the specified Template_Type, THE Template_Resolver SHALL return `None` to signal that the Sending_Function should use its Hardcoded_Fallback
4. WHEN the org has a template for the specified Template_Type with `is_enabled=false`, THE Template_Resolver SHALL return `None` to signal fallback
5. THE Template_Resolver SHALL replace all `{{variable_name}}` placeholders in subject and body content with corresponding values from the Variable_Context
6. WHEN a `{{variable_name}}` placeholder has no corresponding value in the Variable_Context, THE Template_Resolver SHALL leave the placeholder as an empty string rather than rendering the raw placeholder text
7. THE Template_Resolver SHALL support locale-aware template selection by delegating to the existing `get_template_for_locale()` function

### Requirement 2: Email Invoice Template Integration

**User Story:** As an organisation owner, I want the invoice email to use my configured `invoice_issued` template, so that customers receive branded, customised invoice notifications.

#### Acceptance Criteria

1. WHEN `email_invoice()` is called and the org has an enabled `invoice_issued` email template, THE Sending_Function SHALL use the rendered template subject and body instead of the hardcoded content
2. WHEN `email_invoice()` is called and the org has no enabled `invoice_issued` email template, THE Sending_Function SHALL use the existing hardcoded subject and body text (no regression)
3. THE Sending_Function SHALL provide the following variables in the Variable_Context: `customer_first_name`, `customer_last_name`, `invoice_number`, `total_due`, `due_date`, `payment_link`, `org_name`, `org_email`, `org_phone`
4. THE Sending_Function SHALL format monetary values using the invoice's currency before passing them to the Variable_Context

### Requirement 3: Payment Received Email Template Integration

**User Story:** As an organisation owner, I want payment receipt emails to use my configured `payment_received` template, so that customers receive branded payment confirmations.

#### Acceptance Criteria

1. WHEN `_send_receipt_email()` is called and the org has an enabled `payment_received` email template, THE Sending_Function SHALL use the rendered template subject and body instead of the hardcoded content
2. WHEN `_send_receipt_email()` is called and the org has no enabled `payment_received` email template, THE Sending_Function SHALL use the existing hardcoded subject and body text
3. THE Sending_Function SHALL provide the following variables in the Variable_Context: `customer_first_name`, `customer_last_name`, `invoice_number`, `total_due`, `org_name`, `org_email`, `org_phone`
4. THE Sending_Function SHALL format monetary values using the payment's currency before passing them to the Variable_Context

### Requirement 4: Payment Reminder Email Template Integration

**User Story:** As an organisation owner, I want payment reminder emails to use my configured `payment_overdue_reminder` template, so that reminder tone and content match my brand.

#### Acceptance Criteria

1. WHEN `send_payment_reminder()` is called with `channel="email"` and the org has an enabled `payment_overdue_reminder` email template, THE Sending_Function SHALL use the rendered template subject and body instead of the hardcoded content
2. WHEN `send_payment_reminder()` is called with `channel="email"` and the org has no enabled `payment_overdue_reminder` email template, THE Sending_Function SHALL use the existing hardcoded subject and body text
3. THE Sending_Function SHALL provide the following variables in the Variable_Context: `customer_first_name`, `customer_last_name`, `invoice_number`, `total_due`, `due_date`, `payment_link`, `org_name`

### Requirement 5: Payment Reminder SMS Template Integration

**User Story:** As an organisation owner, I want payment reminder SMS messages to use my configured `payment_overdue_reminder` SMS template, so that SMS content is customisable.

#### Acceptance Criteria

1. WHEN `send_payment_reminder()` is called with `channel="sms"` and the org has an enabled `payment_overdue_reminder` SMS template, THE Sending_Function SHALL use the rendered SMS template body instead of the hardcoded SMS content
2. WHEN `send_payment_reminder()` is called with `channel="sms"` and the org has no enabled `payment_overdue_reminder` SMS template, THE Sending_Function SHALL use the existing hardcoded SMS body text
3. THE Sending_Function SHALL provide the same Variable_Context as the email channel for consistency

### Requirement 6: Booking Confirmation Email Template Integration

**User Story:** As an organisation owner, I want booking confirmation emails to use my configured `booking_confirmation` template, so that booking notifications reflect my business branding.

#### Acceptance Criteria

1. WHEN `_send_booking_confirmation_email()` is called and the org has an enabled `booking_confirmation` email template, THE Sending_Function SHALL use the rendered template subject and body instead of the hardcoded content
2. WHEN `_send_booking_confirmation_email()` is called and the org has no enabled `booking_confirmation` email template, THE Sending_Function SHALL use the existing hardcoded subject and body text
3. THE Sending_Function SHALL provide the following variables in the Variable_Context: `customer_first_name`, `booking_service`, `booking_date`, `org_name`, `org_phone`, `vehicle_rego`

### Requirement 7: Quote Sent Email Template Integration

**User Story:** As an organisation owner, I want quote emails to use my configured `quote_sent` template, so that quotes sent to customers reflect my brand voice and formatting.

#### Acceptance Criteria

1. WHEN `send_quote()` is called and the org has an enabled `quote_sent` email template, THE Sending_Function SHALL use the rendered template subject and body instead of the hardcoded content
2. WHEN `send_quote()` is called and the org has no enabled `quote_sent` email template, THE Sending_Function SHALL use the existing hardcoded subject and body text
3. THE Sending_Function SHALL provide the following variables in the Variable_Context: `customer_first_name`, `customer_last_name`, `quote_number`, `quote_total`, `quote_valid_until`, `org_name`, `org_email`, `org_phone`
4. THE Sending_Function SHALL format monetary values using the quote's currency before passing them to the Variable_Context

### Requirement 8: Vehicle Reminder Template Integration (WOF, COF, Registration, Service)

**User Story:** As an organisation owner, I want vehicle expiry and service reminders to use my configured templates, so that reminder content is customisable per reminder type.

**Architecture Note:** The vehicle reminder system uses a queue-based approach. The `reminder_queue_service` pre-generates reminder body content into the queue item's `body` field at scheduling time, and `_send_email_reminder()` / `_send_sms_reminder()` send that pre-rendered content. Therefore, the template must be applied at **queue body generation time** (when the reminder is enqueued), NOT at send time.

#### Acceptance Criteria

1. WHEN a vehicle reminder is enqueued and the org has an enabled template for the corresponding Template_Type (one of `wof_expiry_reminder`, `cof_expiry_reminder`, `registration_expiry_reminder`, `service_due_reminder`) and channel, THE Queue_Body_Generation process SHALL render the template and store the result as the queue item's body content
2. WHEN a vehicle reminder is enqueued and the org has no enabled template for the corresponding Template_Type and channel, THE Queue_Body_Generation process SHALL use the existing hardcoded body content generation logic
3. THE Queue_Body_Generation process SHALL provide the following variables in the Variable_Context: `customer_first_name`, `customer_last_name`, `vehicle_rego`, `vehicle_make`, `vehicle_model`, `expiry_date` (for WOF/COF/registration) or `service_due_date` (for service), `org_name`, `org_phone`, `org_email`
4. THE `_send_email_reminder()` and `_send_sms_reminder()` functions SHALL continue to send the queue item's `body` field as-is (no change to send-time behaviour)
5. WHEN the template is applied at queue time for email reminders, THE Queue_Body_Generation process SHALL also store the rendered subject in the queue item for use by `_send_email_reminder()`
6. THE Queue_Body_Generation process SHALL apply the same template resolution logic for both email and SMS channels, using the appropriate template for each channel

### Requirement 9: User Invitation Email Template Integration

**User Story:** As an organisation owner, I want user invitation emails to use my configured `user_invitation` template, so that new team members receive a branded onboarding experience.

#### Acceptance Criteria

1. WHEN `_send_invitation_email()` is called and the org has an enabled `user_invitation` email template, THE Sending_Function SHALL use the rendered template subject and body instead of the hardcoded content
2. WHEN `_send_invitation_email()` is called and the org has no enabled `user_invitation` email template, THE Sending_Function SHALL use the existing hardcoded subject and body text
3. THE Sending_Function SHALL provide the following variables in the Variable_Context: `user_name`, `org_name`, `signup_link`

### Requirement 10: Password Reset Email Template Integration

**User Story:** As an organisation owner, I want password reset emails to use my configured `password_reset` template, so that the reset experience is consistent with my brand.

#### Acceptance Criteria

1. WHEN `_send_password_reset_email()` is called and the org has an enabled `password_reset` email template, THE Sending_Function SHALL use the rendered template subject and body instead of the hardcoded content
2. WHEN `_send_password_reset_email()` is called and the org has no enabled `password_reset` email template, THE Sending_Function SHALL use the existing hardcoded subject and body text
3. THE Sending_Function SHALL provide the following variables in the Variable_Context: `user_name`, `reset_link`, `org_name`

### Requirement 11: Body Block Rendering for Email

**User Story:** As a developer, I want Body_Blocks to be rendered into plain text (and optionally HTML) for email sending, so that the block-based template editor content translates into actual email content.

#### Acceptance Criteria

1. THE Template_Resolver SHALL render Body_Blocks into a plain-text string suitable for email body content
2. WHEN a Body_Block has type `header`, THE Template_Resolver SHALL render the content as a line followed by a blank line
3. WHEN a Body_Block has type `text`, THE Template_Resolver SHALL render the content as a paragraph followed by a blank line
4. WHEN a Body_Block has type `button`, THE Template_Resolver SHALL render the content as the button label followed by the URL on the next line
5. WHEN a Body_Block has type `divider`, THE Template_Resolver SHALL render a separator line
6. WHEN a Body_Block has type `footer`, THE Template_Resolver SHALL render the content as a line at the end

### Requirement 12: Error Handling and Resilience

**User Story:** As a system operator, I want template resolution failures to fall back gracefully to hardcoded content, so that notification delivery is never blocked by template issues.

#### Acceptance Criteria

1. IF the Template_Resolver raises an exception during template fetch or rendering, THEN THE Sending_Function SHALL log the error and fall back to the Hardcoded_Fallback content
2. IF the database is unreachable during template resolution, THEN THE Sending_Function SHALL proceed with the Hardcoded_Fallback content without raising an error to the caller
3. THE Sending_Function SHALL log at `warning` level when falling back due to a template resolution error, including the org_id and template_type for debugging

### Requirement 13: Orphaned Templates — Future Sending Functions (Gap Type B)

**User Story:** As a product owner, I want to track which templates exist without corresponding sending functions, so that future work can implement the missing notification paths.

**Note:** This requirement documents future work. No implementation is required in this feature.

#### Acceptance Criteria

1. THE system SHALL retain the following Template_Types in `schemas.py` for future implementation: `invoice_voided` (email), `booking_cancellation` (email/SMS), `quote_expired` (email/SMS), `invoice_issued` (SMS), `quote_sent` (SMS), `quote_accepted` (SMS), `booking_confirmation` (SMS)
2. WHEN a future feature implements a sending function for any orphaned Template_Type, THE new Sending_Function SHALL follow the same Template_Resolver integration pattern established by this feature

### Requirement 14: Scope Exclusions (Gap Type C)

**User Story:** As a security engineer, I want security-critical and platform-level notifications to remain hardcoded, so that org customisation cannot compromise security messaging or platform operations.

#### Acceptance Criteria

1. THE system SHALL NOT allow org-level template customisation for the following notification functions: `_send_email_otp()`, `_send_permanent_lockout_email()`, `_send_token_reuse_alert()`, `_send_billing_receipt_email()`, `send_receipt_email()` (signup), `send_dunning_email_task()`
2. THE Template_Types `mfa_enrolment`, `login_alert`, and `account_locked` SHALL remain in `schemas.py` but SHALL NOT be wired to the Template_Resolver (these are reserved for potential future platform-admin-level customisation only)
3. THE Template_Types `storage_warning_80`, `storage_critical_90`, `storage_full_100`, `subscription_renewal_reminder`, and `subscription_payment_failed` SHALL remain excluded from org-level template resolution as they are platform/admin notifications
