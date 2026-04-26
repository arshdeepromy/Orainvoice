# Tasks: Job Card Catalogue Line Items

## Tasks

- [x] 1. Rewrite JobCardCreate.tsx — replace Work Items with Line Item Table
  - [x] 1.1 Remove the `WorkItem` interface and `workItems` state array
  - [x] 1.2 Add `LineItem` interface with `key`, `catalogue_item_id`, `item_type`, `description`, `quantity`, `unit_price`, `is_gst_exempt`
  - [x] 1.3 Add `CatalogueItem` interface matching the backend catalogue response
  - [x] 1.4 Add `catalogueItems` state and fetch `GET /catalogue/items?active_only=true` on mount with AbortController cleanup
  - [x] 1.5 Add `lineItems` state initialized with one empty line item
  - [x] 1.6 Create `LineItemRow` sub-component with:
    - Description input with catalogue search dropdown (type-to-filter, top 10 results, z-50 positioning)
    - On catalogue item select: set `catalogue_item_id`, `description`, `unit_price` from catalogue
    - Quantity input (number, min 1, default 1)
    - Rate input (number, min 0, formatted as currency)
    - Amount display (quantity × rate, auto-calculated, read-only)
    - Remove button (trash icon)
  - [x] 1.7 Add "+ Add Row" button below the table
  - [x] 1.8 Add subtotal display below the table (sum of all line amounts)
  - [x] 1.9 Update form validation: require at least 1 line item with non-empty description
  - [x] 1.10 Update payload construction to send `line_items` array with `item_type`, `description`, `quantity`, `unit_price`, `is_gst_exempt`, `sort_order`, and optionally `catalogue_item_id`
  - [x] 1.11 Ensure table container uses `overflow-visible` (not `overflow-hidden` or `overflow-auto`) so dropdown isn't clipped
  - _Requirements: 1.1–1.10, 2.1–2.2, 3.1–3.3, 6.1–6.3, 7.1–7.4_

- [x] 2. Update JobCardDetail.tsx — show line items with pricing
  - [x] 2.1 Update the `JobCardItem` interface to include `quantity`, `unit_price`, `line_total`, `item_type`, `catalogue_item_id`
  - [x] 2.2 Replace the simple description list with a table showing: #, Description, Qty, Unit Price, Total
  - [x] 2.3 Add subtotal row at the bottom of the table
  - [x] 2.4 Use `?.` and `?? 0` on all numeric fields from the API response
  - [x] 2.5 Format currency values with `toLocaleString('en-NZ', { minimumFractionDigits: 2 })`
  - _Requirements: 4.1–4.3, 6.1_

- [ ] 3. Verify job-to-invoice conversion end-to-end
  - [ ] 3.1 Create a job card with catalogue-linked line items via the new form
  - [ ] 3.2 Progress the job card through Open → In Progress → Completed
  - [ ] 3.3 Click "Issue Invoice" and verify the draft invoice has all line items with correct descriptions, quantities, prices, and `catalogue_item_id` values
  - [ ] 3.4 Verify ad-hoc items (no catalogue link) also transfer correctly
  - _Requirements: 5.1–5.2_

- [x] 4. Build verification
  - [x] 4.1 Run TypeScript diagnostics on both changed files — zero errors
  - [x] 4.2 Rebuild frontend container and verify Vite build succeeds
  - _Requirements: 7.1–7.4_

## Notes

- No backend changes needed — the `create_job_card` service already accepts `catalogue_item_id`, `quantity`, `unit_price` in `line_items_data`
- No database migration needed — `job_card_items` table already has all required columns
- The catalogue search pattern is copied from `InvoiceCreate.tsx` `ItemTableRow` — same UX, same API endpoint
- The `convert_job_card_to_invoice` function in `app/modules/job_cards/service.py` already maps `catalogue_item_id` through to invoice line items
- All frontend code must follow safe-api-consumption.md patterns (optional chaining, nullish coalescing, AbortController)
