# Requirements Document

## Introduction

Sync refunds and credit notes from OraInvoice to Xero as Credit Notes with Allocations. When a refund is processed locally (Payment record with `is_refund=True`), the system creates a Xero Credit Note (type ACCRECCREDIT) and allocates it against the original invoice. Credit notes created locally follow the same path. This approach maps cleanly to Xero's accounting model without changing the existing local refund/credit system.

## Glossary

- **Refund_Sync_Service**: The backend function in `xero.py` responsible for creating a Xero Credit Note from a local refund and allocating it to the original invoice.
- **Auto_Sync_Helper**: The background task helper in `auto_sync.py` that wraps sync calls with session management, connection checks, and error logging.
- **Xero_Credit_Note**: A Xero Accounting API entity of type ACCRECCREDIT that represents a credit applied to a customer account.
- **Allocation**: A Xero Accounting API sub-resource that links a Credit Note to a specific Invoice, reducing the invoice's outstanding amount.
- **Sync_Log**: The `accounting_sync_log` table entry that records the outcome (synced/failed) of each sync attempt.
- **Entity_Reconstructor**: The `_reconstruct_entity_data()` function in `accounting/service.py` that rebuilds sync payloads from the database for manual retry.
- **Rate_Limiter**: The per-tenant rate limiting mechanism in `xero.py` that enforces Xero's 60 requests/minute and 5 concurrent request limits.

## Requirements

### Requirement 1: Create Xero Credit Note from Refund

**User Story:** As a business owner, I want refunds processed in OraInvoice to automatically appear as Credit Notes in Xero, so that my Xero accounts stay in sync without manual data entry.

#### Acceptance Criteria

1. WHEN a refund is processed locally, THE Refund_Sync_Service SHALL create a Xero Credit Note of type ACCRECCREDIT with the refund amount, customer name, date, and a reference containing the invoice number.
2. WHEN the Xero Credit Note is created successfully, THE Refund_Sync_Service SHALL allocate the Credit Note to the original invoice using the Xero Allocations endpoint.
3. THE Refund_Sync_Service SHALL set the Credit Note status to AUTHORISED so that the allocation can be applied immediately.
4. THE Refund_Sync_Service SHALL use a single line item with the refund amount and a description indicating the refund reason.
5. THE Refund_Sync_Service SHALL return the CreditNoteID from the Xero response as the external ID for sync logging.

### Requirement 2: Background Task for Refund Sync

**User Story:** As a user, I want refund processing to remain fast and responsive, so that Xero sync does not block the refund API response.

#### Acceptance Criteria

1. THE Auto_Sync_Helper SHALL provide a `sync_refund_bg()` function that follows the same pattern as `sync_invoice_bg()`, `sync_payment_bg()`, and `sync_credit_note_bg()`.
2. WHEN `sync_refund_bg()` is called, THE Auto_Sync_Helper SHALL create its own database session, check for an active Xero connection, and call `sync_entity()` with entity_type "refund".
3. IF the background sync fails, THEN THE Auto_Sync_Helper SHALL log the failure to the Sync_Log with status "failed" and the error message truncated to 500 characters.
4. THE Auto_Sync_Helper SHALL not raise exceptions to the caller, ensuring the refund API response is never affected by sync failures.

### Requirement 3: Wire Refund Endpoint to Xero Sync

**User Story:** As a business owner, I want refunds to sync to Xero automatically when processed, so that I do not need to trigger sync manually.

#### Acceptance Criteria

1. WHEN a refund is successfully processed in `process_refund_endpoint()`, THE Payments_Router SHALL prepare the Xero sync payload containing the refund ID, invoice number, customer name, refund amount, date, and refund reason.
2. THE Payments_Router SHALL gather the invoice number and customer name from the database before the response is sent, while the session is still open.
3. WHEN the sync payload is prepared, THE Payments_Router SHALL dispatch `sync_refund_bg()` as a fire-and-forget background task using `asyncio.create_task()`.
4. THE Payments_Router SHALL not block the refund API response while waiting for Xero sync to complete.

### Requirement 4: Dispatch Refund Entity Type in Sync Service

**User Story:** As a developer, I want the sync dispatch layer to recognise the "refund" entity type, so that refund sync calls are routed to the correct Xero client function.

#### Acceptance Criteria

1. WHEN `_dispatch_sync()` receives entity_type "refund", THE Sync_Service SHALL call `sync_refund()` on the Xero client and return the CreditNoteID from the response.
2. THE Sync_Service SHALL resolve the Xero tenant ID using the same logic as other entity types (stored on connection, fallback to API call).

### Requirement 5: Refund Data Reconstruction for Manual Retry

**User Story:** As a business owner, I want to retry failed refund syncs from the sync log UI, so that transient Xero errors do not cause permanent data gaps.

#### Acceptance Criteria

1. WHEN `_reconstruct_entity_data()` is called with entity_type "refund", THE Entity_Reconstructor SHALL query the Payment record (where `is_refund=True`) and the associated Invoice to build the sync payload.
2. THE Entity_Reconstructor SHALL include the refund ID, invoice number, customer name, refund amount, date, and refund reason in the reconstructed payload.
3. IF the Payment record is not found, THEN THE Entity_Reconstructor SHALL return None.

### Requirement 6: Verify Existing Credit Note Sync

**User Story:** As a developer, I want to confirm that the existing credit note sync path works correctly end-to-end, so that both credit notes and refunds sync reliably.

#### Acceptance Criteria

1. THE Credit_Note_Sync_Endpoint SHALL include the customer name in the Xero sync payload instead of the hardcoded value "Unknown".
2. WHEN a credit note is created for an invoice, THE Credit_Note_Sync_Endpoint SHALL resolve the customer name from the invoice's associated customer record before dispatching the background sync task.

### Requirement 7: Rate Limiting and Error Handling

**User Story:** As a business owner, I want refund syncs to respect Xero's API rate limits and handle errors gracefully, so that sync failures do not disrupt other Xero operations.

#### Acceptance Criteria

1. THE Refund_Sync_Service SHALL use the existing Rate_Limiter (`_rate_limited_request`) for all Xero API calls, including Credit Note creation and Allocation.
2. IF the Xero API returns a 429 status, THEN THE Refund_Sync_Service SHALL retry after the Retry-After period specified in the response header.
3. IF the Credit Note creation succeeds but the Allocation fails, THEN THE Refund_Sync_Service SHALL log the partial failure with the CreditNoteID and the allocation error message.
4. THE Refund_Sync_Service SHALL use the existing `_xero_api_call` helper to ensure consistent Authorization headers, tenant ID headers, and error logging.

### Requirement 8: Sync Logging for Refunds

**User Story:** As a business owner, I want to see refund sync status in the accounting sync log, so that I can monitor and troubleshoot Xero synchronisation.

#### Acceptance Criteria

1. WHEN a refund sync succeeds, THE Sync_Service SHALL write a Sync_Log entry with entity_type "refund", status "synced", and the Xero CreditNoteID as external_id.
2. WHEN a refund sync fails, THE Sync_Service SHALL write a Sync_Log entry with entity_type "refund", status "failed", and the error message.
3. THE Sync_Log entries for refunds SHALL be visible in the existing sync log API endpoint alongside invoice, payment, and credit note entries.
