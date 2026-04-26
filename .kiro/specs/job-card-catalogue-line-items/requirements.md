# Requirements: Job Card Catalogue Line Items

## Problem Statement

The Create Job Card form currently uses text-only "Work Items" — free-text descriptions with no link to the catalogue, no pricing, no quantities. When a job card is converted to an invoice, these text items become invoice line items with $0 prices that the user must manually fill in. This defeats the purpose of the catalogue system and creates extra work.

The invoice creation page already has a rich item picker with catalogue search, quantity, rate, tax, and line totals. The job card form needs the same capability so that:
1. Items and parts from the catalogue can be selected during job creation
2. Prices are pre-filled from the catalogue
3. When the job is marked complete and "Issue Invoice" is clicked, all line items flow through to the invoice with correct pricing
4. The user can still make adjustments on the invoice before issuing

## Trade Family Applicability

This feature is for **all trades** — every business type uses job cards with chargeable items. The vehicle section on the job card form is already gated behind `isAutomotive` and stays unchanged.

## Requirements

### 1. Job Card Create — Line Item Table

- **1.1** Replace the "Work to be Performed" text-only section with a line item table matching the InvoiceCreate pattern
- **1.2** Each line item row must have: Item Details (with catalogue search dropdown), Quantity, Rate (unit price), Amount (auto-calculated)
- **1.3** The catalogue search dropdown must search `items_catalogue` by name, showing top 10 results with name and default price
- **1.4** When a catalogue item is selected, auto-fill description and rate from the catalogue entry
- **1.5** Users must be able to add ad-hoc items (no catalogue link) by typing a description directly
- **1.6** Each line item must store `catalogue_item_id` (nullable FK) per the catalogue reference architecture
- **1.7** "+ Add Row" button to add new empty line items
- **1.8** Remove button (trash icon) on each row to delete a line item
- **1.9** Minimum 1 line item required to create a job card
- **1.10** Line item `item_type` defaults to `service` but can be changed to `part` or `labour`

### 2. Job Card Create — Totals Display

- **2.1** Show a subtotal below the line item table (sum of all line amounts)
- **2.2** Subtotal is display-only — no discount/shipping/adjustment fields (those are on the invoice)

### 3. Backend Contract

- **3.1** The backend `POST /job-cards` endpoint already accepts `line_items` with `item_type`, `description`, `quantity`, `unit_price`, `catalogue_item_id`, `sort_order` — no backend changes needed
- **3.2** The frontend payload must match the `JobCardItemCreate` Pydantic schema exactly: `item_type` (enum: service/part/labour), `description` (string, 1-500 chars), `quantity` (Decimal, >0), `unit_price` (Decimal, >=0), `is_gst_exempt` (bool), `sort_order` (int)
- **3.3** `catalogue_item_id` is passed through `line_items_data` in the service layer (already supported)

### 4. Job Card Detail — Line Items Display

- **4.1** The job card detail page must show line items with description, quantity, unit price, and line total
- **4.2** Show a subtotal at the bottom of the line items section
- **4.3** The "Issue Invoice" button (on completed job cards) must pass all line items to the invoice creation

### 5. Job-to-Invoice Conversion

- **5.1** The existing `convert_job_card_to_invoice` service function already maps job card items to invoice line items with `catalogue_item_id` preserved — verify this works correctly with the new data
- **5.2** When the invoice is created from a job card, it should be in `draft` status so the user can review and adjust before issuing

### 6. Safe API Consumption

- **6.1** All catalogue API responses must use `?.` and `?? []` patterns per safe-api-consumption.md
- **6.2** Catalogue fetch must use AbortController cleanup in useEffect
- **6.3** No `as any` type assertions on API responses

### 7. Existing Functionality Preservation

- **7.1** Customer search with create modal must continue working
- **7.2** Vehicle registration lookup (automotive only) must continue working
- **7.3** Job description and notes fields must continue working
- **7.4** The form must not use viewport-relative heights (per ISSUE-039)
