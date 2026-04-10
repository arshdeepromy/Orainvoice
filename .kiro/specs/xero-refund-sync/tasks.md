# Implementation Plan: Xero Refund Sync

## Overview

Implement Xero synchronisation for refunds by adding `sync_refund()` to the Xero client, wiring it through the existing sync dispatch and background task infrastructure, and fixing the credit note endpoint's hardcoded customer name. Each task builds incrementally: Xero client → dispatch routing → background helper → endpoint wiring → credit note fix → retry support.

## Tasks

- [x] 1. Add `sync_refund()` to the Xero client
  - [x] 1.1 Implement `sync_refund()` in `app/integrations/xero.py`
    - Add `async def sync_refund(access_token, tenant_id, refund_data)` following the pattern of `sync_invoice()`, `sync_payment()`, `sync_credit_note()`
    - Build Xero Credit Note payload: `Type: ACCRECCREDIT`, `Status: AUTHORISED`, `Contact.Name` from `refund_data["customer_name"]`, `Reference: "Refund for {invoice_number}"`, single `LineItem` with `UnitAmount` = refund amount, `Description: "Refund: {reason}"`, `AccountCode: "200"`, `TaxType: "OUTPUT2"`, `CurrencyCode: "NZD"`
    - POST to `/CreditNotes` via `_xero_api_call`
    - Extract `CreditNoteID` from response
    - PUT to `/CreditNotes/{CreditNoteID}/Allocations` with `Invoice.InvoiceNumber` and `Amount` from refund data
    - If allocation fails after credit note creation, log partial failure with CreditNoteID and re-raise
    - Return the full Xero Credit Note response dict
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 7.1, 7.3, 7.4_

  - [x] 1.2 Write property test: Credit Note payload construction (Property 1)
    - **Property 1: Credit Note payload construction invariant**
    - Generate random valid refund data dicts (non-empty customer name, positive amount, valid YYYY-MM-DD date, non-empty invoice number, non-empty reason) using Hypothesis
    - Extract the payload-building logic into a testable helper or test the payload dict directly
    - Assert: `Type == "ACCRECCREDIT"`, `Status == "AUTHORISED"`, `Contact.Name == customer_name`, `Date == date`, `Reference` contains invoice number, exactly one LineItem with `UnitAmount == amount` and `Description` containing reason, `CurrencyCode == "NZD"`
    - **Validates: Requirements 1.1, 1.3, 1.4**

  - [x] 1.3 Write property test: Allocation payload matches refund data (Property 2)
    - **Property 2: Allocation payload matches refund data**
    - Generate random valid refund data and a mock CreditNoteID string
    - Verify the allocation payload contains `Invoice.InvoiceNumber` matching the invoice number and `Amount` matching the refund amount
    - **Validates: Requirements 1.2**

  - [x] 1.4 Write property test: CreditNoteID extraction from response (Property 3)
    - **Property 3: CreditNoteID extraction from response**
    - Generate random Xero response dicts with `CreditNotes` array containing a `CreditNoteID`
    - Verify `sync_refund()` returns a dict where `CreditNotes[0]["CreditNoteID"]` matches the expected ID
    - **Validates: Requirements 1.5, 4.1**

- [x] 2. Checkpoint - Ensure Xero client tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Add refund dispatch and background sync
  - [x] 3.1 Add `"refund"` branch to `_dispatch_sync()` in `app/modules/accounting/service.py`
    - Add `elif entity_type == "refund":` that calls `xero_client.sync_refund(access_token, tenant_id, entity_data)`
    - Extract `CreditNoteID` from `resp.get("CreditNotes", [])[0].get("CreditNoteID")` and return it
    - Follow the same tenant ID resolution pattern as other entity types
    - _Requirements: 4.1, 4.2_

  - [x] 3.2 Add `sync_refund_bg()` to `app/modules/accounting/auto_sync.py`
    - Follow the exact pattern of `sync_payment_bg()` and `sync_credit_note_bg()`
    - Create own DB session via `async_session_factory()`
    - Check `_has_active_xero_connection()` — return silently if no connection
    - Call `sync_entity()` with `entity_type="refund"`
    - Outer `except Exception` catches all errors, logs to sync log with `status="failed"` and error message truncated to 500 chars
    - Never propagate exceptions to caller
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.3 Write property test: Background task error containment (Property 4)
    - **Property 4: Background task error containment**
    - Generate random exception messages (including strings longer than 500 chars) using Hypothesis
    - Verify `sync_refund_bg()` does not propagate exceptions and that the logged error message is truncated to at most 500 characters
    - **Validates: Requirements 2.3, 2.4**

  - [x] 3.4 Write property test: Sync log records correct entity type and status (Property 8)
    - **Property 8: Sync log records correct entity type and status**
    - Generate random sync outcomes (success with random CreditNoteID, failure with random error message)
    - Verify sync log entry has `entity_type == "refund"`, correct `status` ("synced"/"failed"), and correct `external_id`/`error_message`
    - **Validates: Requirements 8.1, 8.2**

- [x] 4. Wire refund endpoint to Xero sync
  - [x] 4.1 Update `process_refund_endpoint()` in `app/modules/payments/router.py`
    - After `process_refund()` returns and before the response is sent (session still open):
      - Query the invoice number from the Invoice table using `payload.invoice_id`
      - Query the customer name from the Customer table via the invoice's `customer_id` (same pattern as `create_invoice_endpoint()`)
      - Fall back to `"Unknown"` if customer query fails
    - Build the Xero sync payload dict with keys: `id`, `invoice_number`, `customer_name`, `amount`, `date`, `reason`
    - Dispatch `sync_refund_bg(org_uuid, refund_sync_data)` via `asyncio.create_task()`
    - Import `sync_refund_bg` from `app.modules.accounting.auto_sync`
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 4.2 Write property test: Refund sync payload completeness (Property 5)
    - **Property 5: Refund sync payload completeness**
    - Generate random refund results (with id, amount, date, reason) and invoice data (with invoice_number and customer name)
    - Verify the assembled payload contains all 6 required fields (`id`, `invoice_number`, `customer_name`, `amount`, `date`, `reason`) and none are None
    - **Validates: Requirements 3.1**

- [x] 5. Fix credit note endpoint customer name resolution
  - [x] 5.1 Update `create_credit_note_endpoint()` in `app/modules/invoices/router.py`
    - Replace the hardcoded `"customer_name": "Unknown"` in the Xero sync payload
    - Query the customer name from the Customer table via the invoice's `customer_id` (same pattern as `create_invoice_endpoint()` and `issue_invoice_endpoint()`)
    - Use `display_name` with fallback to `first_name + last_name`, then `"Unknown"`
    - _Requirements: 6.1, 6.2_

  - [x] 5.2 Write property test: Credit note sync resolves customer name (Property 7)
    - **Property 7: Credit note sync resolves customer name**
    - Generate random non-empty customer display names using Hypothesis
    - Verify the Xero sync payload contains the actual customer name, not `"Unknown"`
    - **Validates: Requirements 6.1, 6.2**

- [x] 6. Checkpoint - Ensure endpoint wiring and credit note fix tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Add refund data reconstruction for manual retry
  - [x] 7.1 Add `"refund"` branch to `_reconstruct_entity_data()` in `app/modules/accounting/service.py`
    - Add `elif entity_type == "refund":` branch
    - Query `Payment` where `id == entity_id`, `org_id == org_id`, and `is_refund == True`
    - If not found, return `None`
    - Query the associated `Invoice` via `payment.invoice_id` to get `invoice_number`
    - Query the `Customer` via `invoice.customer_id` to get the display name (with fallback)
    - Return dict with: `id` (str), `invoice_number`, `customer_name`, `amount` (float), `date` (YYYY-MM-DD from `payment.created_at`), `reason` (from `payment.refund_note` or `"Refund"`)
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 7.2 Write property test: Refund data reconstruction round-trip (Property 6)
    - **Property 6: Refund data reconstruction round-trip**
    - Generate random Payment records (with `is_refund=True`, random amounts, dates, refund notes) and associated Invoice records (with invoice numbers and customer names)
    - Verify reconstructed payload contains all required fields, amount matches Payment amount, invoice_number matches Invoice's invoice_number
    - **Validates: Requirements 5.1, 5.2**

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use Hypothesis (already installed — see `.hypothesis/` directory)
- Test files go in `tests/` following existing naming: `tests/test_xero_refund_sync.py` for unit tests, `tests/test_xero_refund_sync_property.py` for property tests
- All new code follows existing patterns exactly — `sync_refund()` mirrors `sync_credit_note()`, `sync_refund_bg()` mirrors `sync_credit_note_bg()`, etc.
- The `get_db_session` dependency uses `session.begin()` which auto-commits — use `flush()` not `commit()` in services
- Checkpoints ensure incremental validation
