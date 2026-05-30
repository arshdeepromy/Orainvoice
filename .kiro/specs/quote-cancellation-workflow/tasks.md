# Tasks

## Task 1: Database Migration — Add Cancellation Columns and Update CHECK Constraint

- [x] 1.1 Create Alembic migration `0201_add_quote_cancellation_fields.py` that adds `cancel_reason` (Text, nullable), `cancelled_at` (DateTime with timezone, nullable), and `cancelled_by` (UUID FK to users.id, nullable) columns to the `quotes` table
- [x] 1.2 In the same migration, drop the existing `ck_quotes_status` CHECK constraint and recreate it with the value list: `('draft', 'issued', 'sent', 'accepted', 'declined', 'expired', 'converted', 'cancelled')`
- [x] 1.3 Add downgrade logic that drops the three columns and restores the original CHECK constraint

## Task 2: Backend Model and Schema Updates

- [x] 2.1 Add `cancel_reason`, `cancelled_at`, `cancelled_by` mapped columns to the `Quote` class in `app/modules/quotes/models.py` and update the `CheckConstraint` string to include `'cancelled'`
- [x] 2.2 Add `cancelled = "cancelled"` member to the `QuoteStatus` enum in `app/modules/quotes/schemas.py`
- [x] 2.3 Add `cancel_reason: str | None = None`, `cancelled_at: datetime | None = None`, `cancelled_by: uuid.UUID | None = None` fields to `QuoteResponse` in `app/modules/quotes/schemas.py`
- [x] 2.4 Create a `QuoteCancelRequest` Pydantic model in `app/modules/quotes/schemas.py` with a `reason: str = Field(..., min_length=1)` field

## Task 3: Backend Service — cancel_quote Function

- [x] 3.1 Update `VALID_TRANSITIONS` in `app/modules/quotes/service.py` to add `"cancelled"` to the target sets for `"issued"` and `"sent"`, and add `"cancelled": set()` as a terminal state
- [x] 3.2 Update the `delete_quote` function to allow deletion of quotes with status `"cancelled"` (add "cancelled" to the deletable set or remove it from the non-deletable set)
- [x] 3.3 Update `_quote_to_dict` to include `cancel_reason`, `cancelled_at`, and `cancelled_by` fields in the returned dict
- [x] 3.4 Implement `cancel_quote()` async function: validate quote exists and belongs to org, call `_validate_status_transition(current, "cancelled")`, set status/cancel_reason/cancelled_at/cancelled_by, flush, write audit log with before/after values, refresh, return `_quote_to_dict` result

## Task 4: Backend Router — Cancel Endpoint

- [x] 4.1 Add `PUT /{quote_id}/cancel` endpoint to `app/modules/quotes/router.py` that accepts `QuoteCancelRequest` body, calls `cancel_quote()`, handles ValueError (404 for "not found", 400 otherwise), and returns `QuoteResponse`
- [x] 4.2 Import `cancel_quote` from service and `QuoteCancelRequest` from schemas in the router

## Task 5: Frontend — CancelQuoteModal Component

- [x] 5.1 Create `frontend/src/components/quotes/CancelQuoteModal.tsx` with a modal dialog containing: warning message text, textarea for reason, disabled confirm button until reason has non-whitespace content, "Cancel Quote" danger button, and "Go Back" secondary button
- [x] 5.2 The modal must call `onConfirm(reason)` when the user clicks the confirm button and show loading state while the API call is in progress

## Task 6: Frontend — QuoteDetail Integration

- [x] 6.1 Add a "Cancel Quote" button (red/danger outline style) to the QuoteDetail action toolbar, visible only when `quote.status === 'issued' || quote.status === 'sent'`
- [x] 6.2 Add state and handler for the CancelQuoteModal: open/close state, API call to `PUT /quotes/{id}/cancel` with reason, refresh quote on success, show error toast on failure
- [x] 6.3 Update the `canDelete` logic to include `'cancelled'` in the deletable statuses array
- [x] 6.4 Add a cancellation info banner below the action toolbar when `quote.status === 'cancelled'`: display red "CANCELLED" badge, cancellation reason, date (formatted), and cancelled-by user name

## Task 7: Frontend — QuoteList Status Display

- [x] 7.1 Add `cancelled: 'text-red-600'` to the `STATUS_COLOR` map in `QuoteList.tsx`
- [x] 7.2 Add `{ value: 'cancelled', label: 'Cancelled' }` to the `STATUS_OPTIONS` array in `QuoteList.tsx`

## Task 8: Property-Based Tests

- [x] 8.1 Write a Hypothesis property test verifying Property 1: for any quote with status in {"issued", "sent"} and any non-empty reason string, `cancel_quote` transitions the status to "cancelled"
- [x] 8.2 Write a Hypothesis property test verifying Property 2: for any quote with status in {"draft", "accepted", "declined", "expired", "cancelled"} and any reason string, `cancel_quote` raises ValueError
- [x] 8.3 Write a Hypothesis property test verifying Property 3: after cancellation, quote_number is unchanged, cancel_reason equals the provided reason, and cancelled_by equals the provided user_id
- [x] 8.4 Write a Hypothesis property test verifying Property 4: for any quote with status "cancelled", `delete_quote` succeeds without raising ValueError

## Task 9: Unit and Integration Tests

- [x] 9.1 Write pytest unit tests for the cancel endpoint: valid cancel (200), empty reason (400/422), not found (404), invalid status (400)
- [x] 9.2 Write pytest unit test verifying audit log entry is written with action "quote.cancelled" and correct before/after values
- [x] 9.3 Write Vitest tests for CancelQuoteModal: renders message, button disabled for whitespace, button enabled for valid input, calls onConfirm
- [x] 9.4 Write Vitest tests for QuoteDetail cancel integration: Cancel button visibility by status, cancelled state display (badge, reason, date)
