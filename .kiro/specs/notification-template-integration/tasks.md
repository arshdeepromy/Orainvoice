# Implementation Plan: Notification Template Integration

## Overview

Wire the existing notification template storage and rendering system to all applicable email/SMS sending functions. The core approach: create a reusable `resolve_template()` function in the notifications service, then integrate it into each sending function with a try-template-then-fallback pattern. Vehicle reminders apply templates at queue time, not send time.

## Tasks

- [x] 1. Implement core template resolution infrastructure
  - [x] 1.1 Add `RenderedTemplate` dataclass, `_render_blocks_to_text()`, and `_substitute_variables()` to `app/modules/notifications/service.py`
    - Create `RenderedTemplate` dataclass with `subject: str` and `body: str` fields
    - Implement `_render_blocks_to_text(body_blocks)` converting JSONB block array to plain text per block type rules (header, text, button, divider, footer, image skipped)
    - Implement `_substitute_variables(text, variables)` using regex `r"\{\{(\w+)\}\}"` replacing unmatched placeholders with empty string
    - _Requirements: 1.5, 1.6, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [x] 1.2 Add `resolve_template()` async function to `app/modules/notifications/service.py`
    - Accept `db`, `org_id`, `template_type`, `channel`, and `variables` parameters
    - Call `get_template_for_locale()` to fetch the template
    - Return `None` if template not found or `is_enabled=False`
    - For email: render `body_blocks` via `_render_blocks_to_text()`, substitute variables in both subject and body
    - For SMS: use template body directly, substitute variables
    - Wrap entire function in try/except, log warning on error, return `None`
    - MUST be READ-ONLY — no `db.commit()`, `db.rollback()`, or `db.flush()`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 12.1, 12.2, 12.3_

  - [ ]* 1.3 Write property test: Enabled template resolution produces output
    - **Property 1: Enabled template resolution produces output**
    - Generate random enabled templates with non-empty body_blocks, call `resolve_template` with mocked DB, verify non-None result with non-empty subject and body
    - **Validates: Requirements 1.2**

  - [ ]* 1.4 Write property test: Complete placeholder substitution
    - **Property 2: Complete placeholder substitution (no raw placeholders in output)**
    - Generate random template strings with `{{var}}` placeholders and random variable dicts, call `_substitute_variables`, verify no `{{...}}` pattern in output
    - **Validates: Requirements 1.5, 1.6**

  - [ ]* 1.5 Write property test: Body block content preservation
    - **Property 3: Body block content preservation**
    - Generate random body_blocks arrays with non-empty content, call `_render_blocks_to_text`, verify each block's content appears in output in order
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.6**

  - [ ]* 1.6 Write unit tests for `resolve_template()` edge cases
    - Test returns `None` when template not found
    - Test returns `None` when template is disabled (`is_enabled=False`)
    - Test returns `None` on DB error (catches exception)
    - Test logs warning at `warning` level on error with org_id and template_type
    - Test delegates to `get_template_for_locale()`
    - _Requirements: 1.3, 1.4, 12.1, 12.2, 12.3_

- [x] 2. Checkpoint — Verify core infrastructure
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Integrate templates into invoice and payment sending functions
  - [x] 3.1 Modify `email_invoice()` in `app/modules/invoices/service.py` to use template resolution
    - Build variable context: `customer_first_name`, `customer_last_name`, `invoice_number`, `total_due`, `due_date`, `payment_link`, `org_name`, `org_email`, `org_phone`
    - Format monetary values using invoice currency before passing to context
    - Call `resolve_template(db, org_id=..., template_type="invoice_issued", channel="email", variables=...)`
    - If rendered: use `rendered.subject` and `rendered.body`; else: keep existing hardcoded content
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.2 Modify `send_payment_reminder()` email branch in `app/modules/invoices/service.py` to use template resolution
    - Build variable context: `customer_first_name`, `customer_last_name`, `invoice_number`, `total_due`, `due_date`, `payment_link`, `org_name`
    - Call `resolve_template(db, org_id=..., template_type="payment_overdue_reminder", channel="email", variables=...)`
    - If rendered: use template content; else: keep existing hardcoded content
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 3.3 Modify `send_payment_reminder()` SMS branch in `app/modules/invoices/service.py` to use template resolution
    - Build variable context same as email branch (for consistency) minus `payment_link`
    - Call `resolve_template(db, org_id=..., template_type="payment_overdue_reminder", channel="sms", variables=...)`
    - If rendered: use `rendered.body` for SMS content; else: keep existing hardcoded SMS text
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 3.4 Modify `_send_receipt_email()` in `app/modules/payments/service.py` to use template resolution
    - Build variable context: `customer_first_name`, `customer_last_name`, `invoice_number`, `total_due`, `org_name`, `org_email`, `org_phone`
    - Format monetary values using payment currency
    - Call `resolve_template(db, org_id=..., template_type="payment_received", channel="email", variables=...)`
    - If rendered: use template content; else: keep existing hardcoded content
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [ ]* 3.5 Write unit tests for invoice and payment template integrations
    - Test `email_invoice` uses template when enabled
    - Test `email_invoice` uses hardcoded fallback when template disabled
    - Test `email_invoice` passes correct variable context
    - Test `send_payment_reminder` email uses template when enabled
    - Test `send_payment_reminder` email uses hardcoded fallback
    - Test `send_payment_reminder` SMS uses template when enabled
    - Test `send_payment_reminder` SMS uses hardcoded fallback
    - Test `_send_receipt_email` uses template when enabled
    - Test `_send_receipt_email` uses hardcoded fallback
    - _Requirements: 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 5.1, 5.2_

- [x] 4. Integrate templates into booking and quote sending functions
  - [x] 4.1 Modify `_send_booking_confirmation_email()` in `app/modules/bookings/service.py` to use template resolution
    - Build variable context: `customer_first_name`, `booking_service`, `booking_date`, `org_name`, `org_phone`, `vehicle_rego`
    - Call `resolve_template(db, org_id=..., template_type="booking_confirmation", channel="email", variables=...)`
    - If rendered: use template content; else: keep existing hardcoded content
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 4.2 Modify `send_quote()` in `app/modules/quotes/service.py` to use template resolution
    - Build variable context: `customer_first_name`, `customer_last_name`, `quote_number`, `quote_total`, `quote_valid_until`, `org_name`, `org_email`, `org_phone`
    - Format monetary values using quote currency
    - Call `resolve_template(db, org_id=..., template_type="quote_sent", channel="email", variables=...)`
    - If rendered: use template content; else: keep existing hardcoded content
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 4.3 Write unit tests for booking and quote template integrations
    - Test `_send_booking_confirmation_email` uses template when enabled
    - Test `_send_booking_confirmation_email` uses hardcoded fallback
    - Test `_send_booking_confirmation_email` passes correct variable context
    - Test `send_quote` uses template when enabled
    - Test `send_quote` uses hardcoded fallback
    - Test `send_quote` passes correct variable context
    - _Requirements: 6.1, 6.2, 6.3, 7.1, 7.2, 7.3_

- [x] 5. Integrate templates into auth sending functions
  - [x] 5.1 Modify `_send_invitation_email()` in `app/modules/auth/service.py` to use template resolution
    - Build variable context: `user_name`, `org_name`, `signup_link`
    - Call `resolve_template(db, org_id=..., template_type="user_invitation", channel="email", variables=...)`
    - If rendered: use template content; else: keep existing hardcoded content
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 5.2 Modify `_send_password_reset_email()` in `app/modules/auth/service.py` to use template resolution
    - Add `db: AsyncSession | None = None` as an optional parameter
    - Update caller `request_password_reset()` to pass `db` through
    - Build variable context: `user_name`, `reset_link`, `org_name`
    - When `db` is provided: call `resolve_template(db, org_id=..., template_type="password_reset", channel="email", variables=...)`
    - When `db` is `None`: fall back to hardcoded content (backward compat)
    - If rendered: use template content; else: keep existing hardcoded content
    - _Requirements: 10.1, 10.2, 10.3_

  - [ ]* 5.3 Write unit tests for auth template integrations
    - Test `_send_invitation_email` uses template when enabled
    - Test `_send_invitation_email` uses hardcoded fallback
    - Test `_send_password_reset_email` uses template when `db` provided and template enabled
    - Test `_send_password_reset_email` uses hardcoded fallback when `db` is `None`
    - Test `_send_password_reset_email` uses hardcoded fallback when template disabled
    - _Requirements: 9.1, 9.2, 10.1, 10.2_

- [x] 6. Checkpoint — Verify direct-send integrations
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Integrate templates into vehicle reminder queue body generation
  - [x] 7.1 Modify `enqueue_customer_reminders()` in `app/modules/notifications/reminder_queue_service.py` to apply templates at queue time
    - For each reminder type (`wof_expiry_reminder`, `cof_expiry_reminder`, `registration_expiry_reminder`, `service_due_reminder`):
    - Build variable context: `customer_first_name`, `customer_last_name`, `vehicle_rego`, `vehicle_make`, `vehicle_model`, `expiry_date` or `service_due_date`, `org_name`, `org_phone`, `org_email`
    - Call `resolve_template(db, org_id=..., template_type=..., channel="email", variables=...)` for email reminders
    - Call `resolve_template(db, org_id=..., template_type=..., channel="sms", variables=...)` for SMS reminders
    - If rendered: store `rendered.subject` and `rendered.body` in the queue item
    - If not rendered: use existing hardcoded queue body generation logic
    - `_send_email_reminder()` and `_send_sms_reminder()` remain unchanged (send queue body as-is)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ]* 7.2 Write unit tests for vehicle reminder queue-time template integration
    - Test `enqueue_customer_reminders` uses template for email body when enabled
    - Test `enqueue_customer_reminders` uses hardcoded body when no template
    - Test `enqueue_customer_reminders` stores rendered subject in queue item
    - Test `enqueue_customer_reminders` uses template for SMS body when enabled
    - Test `_send_email_reminder` sends queue body unchanged (no template logic at send time)
    - Test vehicle reminder passes correct variable context
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 8. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific integration scenarios and edge cases
- No database migrations needed — all tables already exist
- No frontend changes — template management UI already works
- `resolve_template()` is READ-ONLY (no commit/rollback) per transaction safety requirements
- Vehicle reminders apply templates at queue time (in `enqueue_customer_reminders`), not at send time
