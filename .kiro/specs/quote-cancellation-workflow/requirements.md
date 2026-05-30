# Requirements Document

## Introduction

This feature adds a "Cancel" workflow to quotes, allowing users to formally withdraw quotes that have been shared with customers (issued or sent status). The workflow mirrors the existing invoice void pattern: requiring a cancellation reason, recording who cancelled and when, and retaining the quote number. Cancelled quotes can subsequently be deleted.

## Glossary

- **Quote_Service**: The backend service layer responsible for quote business logic (`app/modules/quotes/service.py`)
- **Quote_Router**: The FastAPI router handling quote HTTP endpoints (`app/modules/quotes/router.py`)
- **Quote_Detail_Page**: The frontend page displaying a single quote's details and actions (`frontend/src/pages/quotes/QuoteDetail.tsx`)
- **Quote_List_Page**: The frontend page displaying the paginated list of quotes (`frontend/src/pages/quotes/QuoteList.tsx`)
- **Cancellation_Modal**: A confirmation dialog requiring a reason before cancelling a quote
- **Audit_Log**: The system's audit trail recording user actions with before/after values

## Requirements

### Requirement 1: Cancel Quote Status Transition

**User Story:** As a salesperson, I want to cancel a quote that has been issued or sent to a customer, so that I can formally withdraw it without losing the record.

#### Acceptance Criteria

1. WHEN a cancel request is received for a quote with status "issued", THE Quote_Service SHALL transition the quote status to "cancelled"
2. WHEN a cancel request is received for a quote with status "sent", THE Quote_Service SHALL transition the quote status to "cancelled"
3. IF a cancel request is received for a quote with status other than "issued" or "sent", THEN THE Quote_Service SHALL reject the request with a validation error
4. WHEN a quote is cancelled, THE Quote_Service SHALL retain the original quote number without reuse
5. WHEN a quote is cancelled, THE Quote_Service SHALL record the cancellation reason as provided by the user
6. WHEN a quote is cancelled, THE Quote_Service SHALL record the user ID of the person who performed the cancellation
7. WHEN a quote is cancelled, THE Quote_Service SHALL record the UTC timestamp of the cancellation

### Requirement 2: Cancel Quote API Endpoint

**User Story:** As a frontend client, I want a dedicated API endpoint to cancel a quote, so that the cancellation workflow is explicit and separate from general status updates.

#### Acceptance Criteria

1. THE Quote_Router SHALL expose a PUT endpoint at `/quotes/{quote_id}/cancel` accepting a JSON body with a required `reason` field (non-empty string)
2. WHEN the endpoint receives a valid request, THE Quote_Router SHALL invoke the Quote_Service cancel function and return the updated quote
3. IF the `reason` field is empty or missing, THEN THE Quote_Router SHALL return a 400 status with a descriptive error message
4. IF the quote is not found, THEN THE Quote_Router SHALL return a 404 status
5. IF the quote cannot be cancelled due to its current status, THEN THE Quote_Router SHALL return a 400 status with a message indicating the invalid transition

### Requirement 3: Database Schema for Cancellation Fields

**User Story:** As a system, I want to persist cancellation metadata on the quote record, so that the cancellation history is permanently recorded.

#### Acceptance Criteria

1. THE Quote model SHALL include a `cancel_reason` column of type Text, nullable
2. THE Quote model SHALL include a `cancelled_at` column of type DateTime with timezone, nullable
3. THE Quote model SHALL include a `cancelled_by` column of type UUID referencing the users table, nullable
4. THE database CHECK constraint on quote status SHALL be updated to include "cancelled" as a valid value
5. THE VALID_TRANSITIONS state machine SHALL include transitions from "issued" to "cancelled" and from "sent" to "cancelled"

### Requirement 4: Cancelled Quote Deletion

**User Story:** As a salesperson, I want to delete a cancelled quote, so that I can clean up quotes that are no longer relevant.

#### Acceptance Criteria

1. WHEN a delete request is received for a quote with status "cancelled", THE Quote_Service SHALL allow the deletion
2. THE Quote_Detail_Page SHALL display the Delete button for quotes with status "cancelled"

### Requirement 5: Audit Logging for Cancellation

**User Story:** As a business owner, I want cancellations recorded in the audit log, so that I have a complete trail of quote lifecycle changes.

#### Acceptance Criteria

1. WHEN a quote is cancelled, THE Quote_Service SHALL write an audit log entry with action "quote.cancelled"
2. THE audit log entry SHALL include before values: previous status, quote number, and total
3. THE audit log entry SHALL include after values: new status "cancelled", cancel reason, cancelled_at timestamp, and cancelled_by user ID

### Requirement 6: Cancellation Modal UI

**User Story:** As a salesperson, I want a confirmation dialog before cancelling a quote, so that I do not accidentally cancel a quote.

#### Acceptance Criteria

1. WHEN the user clicks the "Cancel Quote" button, THE Quote_Detail_Page SHALL display the Cancellation_Modal
2. THE Cancellation_Modal SHALL display the message: "Cancelling this quote will retain its number but mark it as withdrawn. This cannot be undone."
3. THE Cancellation_Modal SHALL include a textarea for the cancellation reason
4. THE Cancellation_Modal SHALL disable the confirm button until the reason textarea contains at least one non-whitespace character
5. THE Cancellation_Modal SHALL include a "Cancel Quote" danger-styled confirm button and a "Go Back" secondary button
6. WHEN the user confirms cancellation, THE Cancellation_Modal SHALL call the cancel API endpoint and refresh the quote detail on success

### Requirement 7: Cancel Button Visibility

**User Story:** As a salesperson, I want the Cancel button to appear only when cancellation is valid, so that the interface is clear about available actions.

#### Acceptance Criteria

1. THE Quote_Detail_Page SHALL display a "Cancel Quote" button when the quote status is "issued" or "sent"
2. THE Quote_Detail_Page SHALL NOT display the "Cancel Quote" button when the quote status is "draft", "accepted", "declined", "expired", "converted", or "cancelled"

### Requirement 8: Cancelled Quote Display

**User Story:** As a salesperson, I want to see that a quote has been cancelled and why, so that I have context when reviewing past quotes.

#### Acceptance Criteria

1. WHEN a quote has status "cancelled", THE Quote_Detail_Page SHALL display a "CANCELLED" badge styled with a red/danger colour
2. WHEN a quote has status "cancelled", THE Quote_Detail_Page SHALL display the cancellation reason text
3. WHEN a quote has status "cancelled", THE Quote_Detail_Page SHALL display the cancellation date and the name of the user who cancelled it
4. WHEN a quote has status "cancelled", THE Quote_List_Page SHALL display a "Cancelled" status badge with appropriate styling

### Requirement 9: QuoteStatus Enum Update

**User Story:** As a developer, I want the QuoteStatus enum to include "cancelled", so that the schema validation accepts the new status throughout the system.

#### Acceptance Criteria

1. THE QuoteStatus enum SHALL include a "cancelled" member with value "cancelled"
2. THE QuoteResponse schema SHALL include optional fields: cancel_reason (string, nullable), cancelled_at (datetime, nullable), cancelled_by (UUID, nullable)
