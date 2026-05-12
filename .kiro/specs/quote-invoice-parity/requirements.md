# Requirements Document — Quote ↔ Invoice Parity (Phases 5 + 7)

**Status:** Draft — derived from `.kiro/specs/quote-invoice-parity/design.md`
**Authoritative background:** `docs/QUOTE_PREVIEW_PRINT_PLAN.md` (Phases 5 and 7)
**Open questions:** OQ-1 (multi-vehicle) and OQ-2 (quote attachments) are both resolved **YES**. Every design section previously marked "OQ-1 gated" or "OQ-2 gated" is therefore **in scope and unconditional** in this document.

---

## 1. Introduction

`QuoteCreate.tsx` was assumed to be the parity sibling of `InvoiceCreate.tsx`, but a field-by-field audit showed it was missing most of the invoice form's header, line-item, and post-header surface, and the quote backend schemas never persisted those fields. This spec closes that gap end-to-end. At the UI layer, `QuoteCreate.tsx` gains an order-number field, a salesperson dropdown, a read-only GST number display, a multi-vehicle section, an inventory picker for line items, three-way GST-inclusive line-item pricing, a fluid-usage section, a "save terms as default" checkbox, and a file-attachments section. At the Pydantic + ORM layer, `quotes` and `quote_line_items` gain matching columns, and a new `quote_attachments` table is introduced, all under a single reversible Alembic migration `0184`. At the read-side layer (Phase 7), `QuoteDetail.tsx` mounts a new `QuoteAttachmentList` component when the quote has attachments, and `QuoteList.tsx` gains a 📎 attachment-count badge plus a per-row PDF/Print dropdown. Every change is additive; no existing quote endpoint breaks, and every existing quote row continues to work after upgrade and after downgrade.

---

## 2. Glossary

- **Quote_Record** — A row in the `quotes` table, with all columns including the new `order_number`, `salesperson_id`, `additional_vehicles`, and `fluid_usage` columns introduced by migration 0184.
- **Quote_Line_Item** — A row in the `quote_line_items` table, with all columns including the new `catalogue_item_id`, `stock_item_id`, `gst_inclusive`, `inclusive_price`, and `tax_rate` columns introduced by migration 0184.
- **Quote_Attachment** — A row in the `quote_attachments` table introduced by migration 0184. Each attachment belongs to exactly one Quote_Record and exactly one organisation (`org_id`). Persisted via the storage namespace `"quote-attachments"`.
- **Additional_Vehicles** — The `additional_vehicles` JSONB column on `quotes`, containing a list of secondary vehicles (make, model, year, rego, odometer) attached to a Quote_Record beyond its primary vehicle. Matches the invoice-side multi-vehicle structure.
- **Fluid_Usage** — The `fluid_usage` JSONB column on `quotes`, containing a list of `{ stock_item_id, catalogue_item_id, litres, item_name }` entries. Fluid_Usage is tracked for inventory purposes only — it does not contribute to Quote_Record totals.
- **Inventory_Picker** — The new `InventoryPickerModal` component mounted in `QuoteCreate.tsx`. Fetches stock items from `GET /inventory/stock-items` and returns a selection that populates a Quote_Line_Item with `stock_item_id`, `catalogue_item_id`, `gst_inclusive`, and `inclusive_price`.
- **Salesperson_Dropdown** — The new header dropdown in `QuoteCreate.tsx` that loads the list of salespeople from `GET /org/salespeople`, auto-selects the current user, and writes its value to the Quote_Record's `salesperson_id` column.
- **GST_Inclusive_Line** — A Quote_Line_Item with `gst_inclusive = true`. The UI presents a price `P` that already includes GST; the server stores `unit_price = P / 1.15` ex-GST and `inclusive_price = P` verbatim for round-trip preservation. Total GST on the line equals `line_total * 0.15` where `line_total = quantity * unit_price`.
- **Attachment_Badge** — The `📎 N` visual element rendered in `QuoteList.tsx` next to `quote_number`, where `N` equals `Quote_Record.attachment_count`. Rendered if and only if `attachment_count > 0`.
- **PDF_Print_Dropdown** — The new per-row dropdown in `QuoteList.tsx` containing exactly two menu items: "Download PDF" and "Print Quote". "Print POS Receipt" is never rendered in this dropdown.
- **QuoteAttachmentList** — The new `frontend/src/components/quotes/QuoteAttachmentList.tsx` component mounted in `QuoteDetail.tsx` when `attachment_count > 0`. Renders each Quote_Attachment's filename, size, and upload date, and shows a delete button only when `isDraft === true`.
- **Save_Terms_As_Default** — A new checkbox under the Terms & Conditions textarea in `QuoteCreate.tsx`. When ticked at save time, causes the backend to persist the quote's terms text as the org-level default (`settings.terms_and_conditions`), identical to the invoice-side behaviour.
- **Multi_Vehicle_Section** — The new `QuoteMultiVehicleSection` component in `QuoteCreate.tsx` that lets a user attach additional vehicles to a Quote_Record beyond the primary vehicle. Gated on `isAutomotive && isEnabled('vehicles')`, matching invoice behaviour.
- **Migration_0184** — The single Alembic revision `0184_quote_invoice_parity.py` with down-revision `0183` that adds every new column and the new `quote_attachments` table. Every change is idempotent (`ADD COLUMN IF NOT EXISTS`, early-return on existing table) and fully reversible.
- **Attachment_MIME_Allow_List** — The closed set of accepted upload MIME types: `image/jpeg`, `image/png`, `image/webp`, `image/gif`, `application/pdf`. Identical to the invoice-attachment allow list.
- **Attachment_Size_Cap** — 20 MB per Quote_Attachment (`MAX_FILE_SIZE = 20 * 1024 * 1024`). Identical to the invoice-attachment cap.
- **Attachment_Count_Cap** — 5 Quote_Attachments per Quote_Record. Identical to the invoice-attachment cap.
- **RLS** — Row-Level Security policy scoped by `org_id = current_setting('app.current_org_id')::uuid`. Enabled on `quote_attachments` by Migration_0184.
- **HA_Publication** — The Postgres logical-replication publication `ora_publication`. Migration_0184 adds `quote_attachments` to this publication if it exists (no-op otherwise) so that the table replicates to the HA standby.
- **Content_Disposition_Formula** — For a download response, `inline; filename="<name>"` when the MIME type starts with `image/` or equals `application/pdf`, otherwise `attachment; filename="<name>"`. Identical to the invoice-attachment formula.
- **Draft_Only_Delete** — The rule that `DELETE /quotes/{id}/attachments/{aid}` returns 403 unless the Quote_Record is in `draft` status.
- **Safe_API_Consumption** — The mandatory frontend pattern set described in `.kiro/steering/safe-api-consumption.md` (typed generics, `?.` optional chaining, `?? []` / `?? 0` fallbacks, `AbortController` cleanup in every `useEffect`).

---

## 3. Requirements

### Requirement 1 — Create a quote with parity fields

**User Story:** As a salesperson or org_admin, I want to create a new quote carrying the same header, line-item, and post-header fields as an invoice, so that quotes I raise are informationally equivalent to the invoices they will eventually become.

#### Acceptance Criteria

1. WHEN a salesperson or org_admin submits `POST /api/v1/quotes`, THE Quote_Record SHALL persist the submitted `order_number`, `salesperson_id`, `additional_vehicles`, and `fluid_usage` fields verbatim.
2. WHEN a salesperson or org_admin submits `POST /api/v1/quotes` with one or more line items, THE Quote_Line_Item rows SHALL persist the submitted `catalogue_item_id`, `stock_item_id`, `gst_inclusive`, `inclusive_price`, and `tax_rate` fields verbatim for each line.
3. WHEN `QuoteCreate.tsx` mounts, THE Salesperson_Dropdown SHALL be populated from `GET /org/salespeople` and SHALL auto-select the currently-authenticated user.
4. WHEN `QuoteCreate.tsx` mounts, THE GST number display SHALL be populated read-only from `useTenant().settings.gst.gst_number`.
5. WHEN the Inventory_Picker returns a selection, THE added Quote_Line_Item SHALL carry the picked stock item's `stock_item_id`, `catalogue_item_id`, `gst_inclusive`, and `inclusive_price`.
6. WHEN the user saves a quote with a non-empty Multi_Vehicle_Section, THE Quote_Record's `additional_vehicles` column SHALL contain the submitted vehicle list.
7. WHEN the user saves a quote with a non-empty Fluid_Usage section, THE Quote_Record's `fluid_usage` column SHALL contain the submitted fluid entries.
8. THE Quote_Record totals SHALL treat Fluid_Usage entries as non-billable (Fluid_Usage SHALL NOT contribute to subtotal, GST, or total).
9. WHERE the caller is not `org_admin` and not `salesperson`, THE `POST /api/v1/quotes` endpoint SHALL return 403.
10. WHEN the user submits a quote containing a line item with `gst_inclusive = true` and `inclusive_price = P`, THE server SHALL persist `unit_price = P / 1.15` (rounded half-up to the nearest cent) and SHALL persist `inclusive_price = P` verbatim.

### Requirement 2 — Edit an existing quote with all new fields rehydrated

**User Story:** As a salesperson or org_admin, I want to edit an existing quote and see every new field (order number, salesperson, multi-vehicle, fluid usage, inventory-linked line items, GST-inclusive pricing) rehydrated exactly as I saved it, so that editing never silently drops data.

#### Acceptance Criteria

1. WHEN a salesperson or org_admin opens `/quotes/{id}/edit`, THE `QuoteCreate.tsx` form SHALL populate `order_number`, `salesperson_id`, `additional_vehicles`, and `fluid_usage` from the response of `GET /api/v1/quotes/{id}`.
2. WHEN a salesperson or org_admin opens `/quotes/{id}/edit`, THE `QuoteCreate.tsx` form SHALL populate each line item's `catalogue_item_id`, `stock_item_id`, `gst_inclusive`, `inclusive_price`, and `tax_rate` from the response of `GET /api/v1/quotes/{id}`.
3. WHEN a salesperson or org_admin submits `PUT /api/v1/quotes/{id}` on an existing draft quote, THE updated Quote_Record SHALL persist every new field from the payload unchanged on subsequent read.
4. WHEN a salesperson or org_admin submits `PUT /api/v1/quotes/{id}` on a non-draft quote, THE endpoint SHALL accept only notes-level updates (matching existing status-gated edit behaviour) and SHALL leave every other field unchanged.
5. WHERE the caller is not `org_admin` and not `salesperson`, THE `PUT /api/v1/quotes/{id}` endpoint SHALL return 403.
6. THE response of `GET /api/v1/quotes/{id}` SHALL include an enriched `salesperson_name` field derived by joining `users` on `salesperson_id` (using `first_name last_name`, falling back to email when names are blank).

### Requirement 3 — Attach files to a quote

**User Story:** As a salesperson or org_admin, I want to upload files to a quote so that supporting documents (photos, scanned PO, spec sheets) travel with the quote record.

#### Acceptance Criteria

1. WHEN a salesperson or org_admin uploads a file via `POST /api/v1/quotes/{quote_id}/attachments` with a MIME type in the Attachment_MIME_Allow_List and a size ≤ Attachment_Size_Cap and the existing attachment count < Attachment_Count_Cap, THE endpoint SHALL return 201 and persist a Quote_Attachment row.
2. IF a salesperson or org_admin uploads a file exceeding the Attachment_Size_Cap (> 20 MB), THEN THE `POST /api/v1/quotes/{quote_id}/attachments` endpoint SHALL return 413 and SHALL NOT persist a Quote_Attachment row.
3. IF a salesperson or org_admin uploads a file whose MIME type is not in the Attachment_MIME_Allow_List, THEN THE `POST /api/v1/quotes/{quote_id}/attachments` endpoint SHALL return 400 and SHALL NOT persist a Quote_Attachment row.
4. IF a salesperson or org_admin uploads a file when the Quote_Record already has 5 Quote_Attachments, THEN THE `POST /api/v1/quotes/{quote_id}/attachments` endpoint SHALL return 400 and SHALL NOT persist a Quote_Attachment row.
5. IF a salesperson or org_admin uploads a file when the organisation's storage quota is exhausted, THEN THE `POST /api/v1/quotes/{quote_id}/attachments` endpoint SHALL return 507 and SHALL NOT persist a Quote_Attachment row.
6. WHERE the caller is not `org_admin` and not `salesperson`, THE `POST /api/v1/quotes/{quote_id}/attachments` endpoint SHALL return 403.
7. WHEN the user picks one or more files in `QuoteCreate.tsx` before the quote is persisted, THE form SHALL save the quote as a draft first and SHALL then upload each file to the newly-created quote id.
8. WHEN `GET /api/v1/quotes/{quote_id}/attachments/{attachment_id}` is called on an image or PDF Quote_Attachment, THE response `Content-Disposition` header SHALL equal `inline; filename="<file_name>"`.
9. WHEN `GET /api/v1/quotes/{quote_id}/attachments/{attachment_id}` is called on any other allowed MIME type, THE response `Content-Disposition` header SHALL equal `attachment; filename="<file_name>"`.
10. THE `Content-Disposition` header formula for quote attachments SHALL equal the formula used by `GET /api/v1/invoices/{invoice_id}/attachments/{attachment_id}` for the same `(mime_type, file_name)` pair.

### Requirement 4 — Delete an attachment from a draft quote

**User Story:** As a salesperson or org_admin, I want to remove an attachment from a quote while the quote is still a draft, so that I can correct mistakes before sending.

#### Acceptance Criteria

1. WHEN a salesperson or org_admin calls `DELETE /api/v1/quotes/{quote_id}/attachments/{attachment_id}` and the Quote_Record is in `draft` status, THE endpoint SHALL return 200 and SHALL remove the Quote_Attachment row.
2. IF a salesperson or org_admin calls `DELETE /api/v1/quotes/{quote_id}/attachments/{attachment_id}` and the Quote_Record is not in `draft` status, THEN THE endpoint SHALL return 403 and SHALL NOT remove the Quote_Attachment row.
3. WHERE the caller is not `org_admin` and not `salesperson`, THE `DELETE /api/v1/quotes/{quote_id}/attachments/{attachment_id}` endpoint SHALL return 403.
4. WHEN `QuoteAttachmentList` is mounted with `isDraft = true`, THE component SHALL render a delete affordance for each Quote_Attachment.
5. WHEN `QuoteAttachmentList` is mounted with `isDraft = false`, THE component SHALL NOT render a delete affordance for any Quote_Attachment.

### Requirement 5 — View attachments on a sent or accepted quote detail page

**User Story:** As a salesperson or org_admin, I want to see the files I attached to a quote after it has been sent or accepted, so that I can reference the supporting material during customer conversations.

#### Acceptance Criteria

1. WHEN a salesperson or org_admin opens `/quotes/{id}` and the Quote_Record's `attachment_count > 0`, THE `QuoteDetail.tsx` page SHALL mount `QuoteAttachmentList` with props `{ quoteId: id, isDraft: quote.status === 'draft' }`.
2. WHEN a salesperson or org_admin opens `/quotes/{id}` and the Quote_Record's `attachment_count === 0`, THE `QuoteDetail.tsx` page SHALL NOT mount `QuoteAttachmentList` and SHALL NOT issue a `GET /api/v1/quotes/{id}/attachments` request.
3. WHEN `QuoteAttachmentList` mounts, THE component SHALL fetch `GET /api/v1/quotes/{quoteId}/attachments` and SHALL render one row per Quote_Attachment showing file-type icon, filename, size, upload date, and — when `isDraft === true` — a delete button.
4. WHEN the user clicks a Quote_Attachment filename in `QuoteAttachmentList`, THE browser SHALL open `/api/v1/quotes/{quoteId}/attachments/{attachmentId}` in a new tab.
5. THE response body of `GET /api/v1/quotes/{quoteId}/attachments` SHALL have shape `{ attachments: [...], total: N }`.

### Requirement 6 — See the attachment-count badge on the quote list

**User Story:** As a salesperson or org_admin, I want to see at a glance which quotes have attachments in the quote list, so that I can identify quotes with supporting documents without opening each one.

#### Acceptance Criteria

1. WHEN `QuoteList.tsx` renders a row whose Quote_Record has `attachment_count > 0`, THE row SHALL display an Attachment_Badge showing `📎 N` next to `quote_number`, where N equals `attachment_count`.
2. WHEN `QuoteList.tsx` renders a row whose Quote_Record has `attachment_count === 0` or `attachment_count === null`, THE row SHALL NOT display an Attachment_Badge.
3. THE response body of `GET /api/v1/quotes` SHALL include `attachment_count` on every `QuoteSearchResult` entry.
4. THE `attachment_count` value returned for a Quote_Record SHALL equal the number of Quote_Attachment rows where `quote_id = Quote_Record.id AND org_id = Quote_Record.org_id`.

### Requirement 7 — Download or Print a quote from the list's PDF/Print dropdown

**User Story:** As a salesperson or org_admin, I want to download or print any quote directly from the quote list, so that I can produce a branded document without opening the detail page.

#### Acceptance Criteria

1. WHEN `QuoteList.tsx` renders any row, THE PDF_Print_Dropdown SHALL be available on that row.
2. WHEN a salesperson or org_admin opens the PDF_Print_Dropdown on any row, THE dropdown SHALL contain exactly two menu items: "Download PDF" and "Print Quote".
3. THE PDF_Print_Dropdown SHALL NOT contain a menu item matching "Print POS Receipt" (case-insensitive) regardless of trade family, active modules, or Quote_Record status.
4. WHEN a salesperson or org_admin selects "Download PDF" on a row, THE frontend SHALL issue `GET /api/v1/quotes/{id}/pdf` and SHALL trigger a browser download of the returned `application/pdf` body.
5. WHEN a salesperson or org_admin selects "Print Quote" on a row, THE frontend SHALL navigate to `/quotes/{id}` and invoke `window.print()` on load.

### Requirement 8 — Save terms and conditions as the default for future quotes

**User Story:** As a salesperson or org_admin, I want to tick a "Save as default for all future quotes" checkbox when saving a quote, so that the terms I am typing become the organisation's default for every subsequent new quote.

#### Acceptance Criteria

1. WHEN a salesperson or org_admin submits `POST /api/v1/quotes` with `save_terms_as_default = true` and a non-empty `terms` value, THE backend SHALL update the organisation's `settings.terms_and_conditions` default to the submitted `terms`.
2. WHEN a salesperson or org_admin submits `POST /api/v1/quotes` with `save_terms_as_default = false`, THE backend SHALL NOT modify the organisation's `settings.terms_and_conditions`.
3. WHEN `QuoteCreate.tsx` mounts for a new quote, THE terms-and-conditions textarea SHALL pre-fill from `useTenant().settings.terms_and_conditions`.
4. WHEN the "Save as default for all future quotes" checkbox has been used successfully, THE frontend SHALL refetch tenant settings so that subsequent new-quote loads reflect the updated default.

### Requirement 9 — GST-inclusive line items round-trip correctly

**User Story:** As a salesperson or org_admin, I want GST-inclusive line-item prices to round-trip through create and read without drift, so that what I type is what is persisted and what I see back is what I typed.

#### Acceptance Criteria

1. WHEN a salesperson or org_admin submits a line item with `gst_inclusive = true`, `inclusive_price = P`, and `quantity = q`, THE persisted `line_total` SHALL equal `q * (P / 1.15)` rounded half-up to the nearest cent, with a tolerance of ±0.01.
2. WHEN a salesperson or org_admin submits a line item with `gst_inclusive = true` and `inclusive_price = P`, THE response of `GET /api/v1/quotes/{id}` SHALL return `inclusive_price = P` with exact decimal equality.
3. WHEN a salesperson or org_admin submits a line item with `gst_inclusive = true`, THE response of `GET /api/v1/quotes/{id}` SHALL return `gst_inclusive = true`.
4. WHEN the Quote_Record is recomputed, THE GST share of a GST_Inclusive_Line SHALL equal `line_total * 0.15` rounded half-up to the nearest cent, with a tolerance of ±0.01.
5. THE Quote_Record total calculation for a GST_Inclusive_Line SHALL match the invoice-side calculation for the same `(quantity, inclusive_price, tax_rate)` triple.

### Requirement 10 — Clear errors when attachment upload fails

**User Story:** As a salesperson or org_admin, I want a specific error message when an attachment upload fails, so that I know whether to shrink the file, change the file type, free up storage, or retry.

#### Acceptance Criteria

1. IF an attachment upload returns 413, THEN THE `QuoteCreate.tsx` UI SHALL display `"File exceeds 20 MB"` (or an equivalent message referencing the 20 MB cap) inline on the attachments section and SHALL NOT add the file to the list.
2. IF an attachment upload returns 400 because of an unsupported MIME type, THEN THE `QuoteCreate.tsx` UI SHALL display `"Only JPEG, PNG, WebP, GIF, and PDF files are allowed"` and SHALL NOT add the file to the list.
3. IF an attachment upload returns 400 because the Quote_Record already has 5 Quote_Attachments, THEN THE `QuoteCreate.tsx` UI SHALL display a message indicating the 5-attachment cap has been reached and SHALL NOT add the file to the list.
4. IF an attachment upload returns 507, THEN THE `QuoteCreate.tsx` UI SHALL display `"Storage quota exceeded for this org"` (or an equivalent quota message) and SHALL NOT add the file to the list.
5. IF an attachment upload fails with a network error or a 500-class response, THEN THE `QuoteCreate.tsx` UI SHALL display `"Upload failed — please retry"` (or an equivalent retry message) and SHALL offer a retry affordance.
6. IF a `DELETE /api/v1/quotes/{quote_id}/attachments/{attachment_id}` call returns 403, THEN THE UI SHALL display a message indicating that attachments can only be removed while the quote is a draft.

### Requirement 11 — Clear errors when quote creation fails validation

**User Story:** As a salesperson or org_admin, I want a clear error message when quote creation fails validation, so that I can correct the input and retry.

#### Acceptance Criteria

1. IF `POST /api/v1/quotes` returns 400 or 422 because of a missing customer or empty line-item list, THEN THE `QuoteCreate.tsx` UI SHALL display inline field errors plus a top-of-form banner and SHALL preserve the user's current draft input.
2. IF `POST /api/v1/quotes` returns 500, THEN THE `QuoteCreate.tsx` UI SHALL display a top-of-form banner with the server-returned detail and SHALL preserve the user's current draft input.
3. IF `POST /api/v1/quotes` fails with a network error, THEN THE `QuoteCreate.tsx` UI SHALL display a retry affordance and SHALL preserve the user's current draft input.
4. WHEN `QuoteCreate.tsx` detects that the user is attempting to save with fewer than one non-empty line-item description, THE form SHALL block the submission and surface an inline validation message.

### Requirement 12 — Cross-org isolation on every attachment endpoint

**User Story:** As an org_admin, I want quote attachments to be strictly scoped to my organisation, so that no user from another organisation can read, list, upload, or delete my quote's attachments.

#### Acceptance Criteria

1. WHEN `GET /api/v1/quotes/{quote_id}/attachments` is called with a token whose `org_id` does not match the Quote_Record's `org_id`, THE endpoint SHALL return 404.
2. WHEN `GET /api/v1/quotes/{quote_id}/attachments/{attachment_id}` is called with a token whose `org_id` does not match the Quote_Record's `org_id`, THE endpoint SHALL return 404.
3. WHEN `POST /api/v1/quotes/{quote_id}/attachments` is called with a token whose `org_id` does not match the Quote_Record's `org_id`, THE endpoint SHALL return 404.
4. WHEN `DELETE /api/v1/quotes/{quote_id}/attachments/{attachment_id}` is called with a token whose `org_id` does not match the Quote_Record's `org_id`, THE endpoint SHALL return 404.
5. THE 404 responses for cross-org access SHALL NOT leak any information about the existence of the Quote_Record or Quote_Attachment in the other organisation (identical payload shape to a non-existent-id 404).
6. THE `quote_attachments` table SHALL have RLS enabled with policy `quote_attachments_org_isolation USING (org_id = current_setting('app.current_org_id')::uuid)`.

### Requirement 13 — Migration 0184 is idempotent, reversible, and HA-safe

**User Story:** As a platform operator, I want the Alembic migration for this feature to be a single idempotent, reversible revision that adds the replication-publication membership safely, so that I can apply it on dev, HA standby, and Pi prod without manual intervention or drift.

#### Acceptance Criteria

1. THE single Alembic revision `0184` SHALL have `down_revision = "0183"` and SHALL bump the head to `0184`.
2. WHEN `alembic upgrade head` is run against a database already at `0184`, THE migration SHALL complete with no errors and no schema changes (idempotent re-run via `ADD COLUMN IF NOT EXISTS` and the `information_schema` early-return for `quote_attachments`).
3. THE upgrade path SHALL add `order_number`, `salesperson_id`, `additional_vehicles`, and `fluid_usage` to `quotes`, all nullable with no server default (except JSONB columns which default to NULL).
4. THE upgrade path SHALL add `catalogue_item_id`, `stock_item_id`, `inclusive_price`, `gst_inclusive` (default `false`), and `tax_rate` (default `15`) to `quote_line_items`.
5. THE upgrade path SHALL create the `quote_attachments` table with all columns, foreign keys, the composite `ix_quote_attachments_quote_org` index, RLS enabled, the `quote_attachments_org_isolation` policy, and HA_Publication membership via the `DO $ha_block$` guard.
6. THE HA_Publication `ALTER PUBLICATION` statement SHALL be guarded so that it no-ops when `ora_publication` does not exist, allowing the migration to run unchanged on dev, HA standby, and Pi prod.
7. WHEN `alembic downgrade -1` is run from `0184`, THE downgrade path SHALL drop every column, index, policy, and table that the upgrade created, in reverse order, leaving the schema bit-for-bit identical to the pre-upgrade state.
8. THE upgrade path SHALL leave every existing row in `quotes` and `quote_line_items` untouched (no backfill, no data transform).
9. THE downgrade path SHALL leave every existing row in `quotes` and `quote_line_items` untouched (only the new columns and the `quote_attachments` table disappear).

### Requirement 14 — Auth on every new endpoint

**User Story:** As an org_admin, I want every new quote-parity endpoint to require an org-scoped role, so that no unauthenticated caller can read, write, or delete quote attachments.

#### Acceptance Criteria

1. WHERE the caller has no authentication, THE `POST /api/v1/quotes/{quote_id}/attachments` endpoint SHALL return 401.
2. WHERE the caller has no authentication, THE `GET /api/v1/quotes/{quote_id}/attachments` endpoint SHALL return 401.
3. WHERE the caller has no authentication, THE `GET /api/v1/quotes/{quote_id}/attachments/{attachment_id}` endpoint SHALL return 401.
4. WHERE the caller has no authentication, THE `DELETE /api/v1/quotes/{quote_id}/attachments/{attachment_id}` endpoint SHALL return 401.
5. WHERE the caller is authenticated but is not `org_admin` and not `salesperson`, THE four attachment endpoints above SHALL return 403.
6. WHERE the caller has no authentication, THE `POST /api/v1/quotes` and `PUT /api/v1/quotes/{id}` endpoints SHALL return 401.
7. WHERE the caller is authenticated but is not `org_admin` and not `salesperson`, THE `POST /api/v1/quotes` and `PUT /api/v1/quotes/{id}` endpoints SHALL return 403.

### Requirement 15 — No breaking changes to existing quote endpoints

**User Story:** As a consumer of the existing quote API, I want every new field to be additive and optional on requests, so that clients predating this spec keep working without change.

#### Acceptance Criteria

1. THE `POST /api/v1/quotes` endpoint SHALL accept payloads that omit every field added by this spec, and SHALL return 201 with `order_number = null`, `salesperson_id = null`, `additional_vehicles = []`, `fluid_usage = []`, and default per-line `gst_inclusive = false`, `tax_rate = 15`.
2. THE `PUT /api/v1/quotes/{id}` endpoint SHALL accept payloads that omit every field added by this spec, and SHALL preserve existing values rather than overwriting them to null.
3. THE `GET /api/v1/quotes` and `GET /api/v1/quotes/{id}` endpoints SHALL return every existing field with the same name, shape, and semantics as before this spec.
4. THE existing `QuoteResponse` and `QuoteSearchResult` schemas SHALL be extended additively with `order_number`, `salesperson_id`, `salesperson_name`, `additional_vehicles`, `fluid_usage`, and `attachment_count` — no existing field is renamed, removed, or re-typed.

### Requirement 16 — Safe API consumption on every new frontend touchpoint

**User Story:** As a frontend developer, I want every new `apiClient` call in `QuoteCreate.tsx`, `QuoteDetail.tsx`, `QuoteList.tsx`, and `QuoteAttachmentList.tsx` to follow Safe_API_Consumption, so that a malformed or slow response never crashes the page.

#### Acceptance Criteria

1. THE new `apiClient` calls in `QuoteCreate.tsx`, `QuoteDetail.tsx`, `QuoteList.tsx`, and `QuoteAttachmentList.tsx` SHALL use typed generics and SHALL NOT use `as any` on response bodies.
2. THE new state assignments from API responses SHALL use `res.data?.<field> ?? <fallback>` (`?? []` for arrays, `?? 0` for numbers, `?? null` for objects).
3. THE new array operations (`.map`, `.filter`, `.find`, `.length`) on API response data SHALL be applied to `(res.data?.<field> ?? [])`.
4. THE new number-formatting operations (`.toFixed`, `.toLocaleString`) on API response data SHALL be applied to `(<value> ?? 0)`.
5. WHEN a new component issues an API call inside `useEffect`, THE effect SHALL create an `AbortController`, SHALL pass its signal to the request, and SHALL call `controller.abort()` in the cleanup returned from the effect.

### Requirement 17 — RLS + HA publication membership for quote_attachments

**User Story:** As a platform operator, I want the new `quote_attachments` table to be automatically protected by RLS and included in the HA logical-replication publication, so that cross-org isolation and HA failover both work out of the box.

#### Acceptance Criteria

1. WHEN Migration_0184 upgrades successfully, THE `quote_attachments` table SHALL have `ROW LEVEL SECURITY` enabled.
2. WHEN Migration_0184 upgrades successfully, THE `quote_attachments` table SHALL have policy `quote_attachments_org_isolation` with `USING (org_id = current_setting('app.current_org_id')::uuid)`.
3. WHEN Migration_0184 upgrades on a database where `ora_publication` exists, THE `quote_attachments` table SHALL be added to that publication.
4. WHEN Migration_0184 upgrades on a database where `ora_publication` does not exist, THE publication membership step SHALL be a no-op and SHALL NOT raise an error.
5. WHEN Migration_0184 downgrades on a database where `ora_publication` exists, THE `quote_attachments` table SHALL be removed from that publication before the table itself is dropped.

---

## 4. Non-Functional Requirements

### NFR-1 — Authentication and authorisation

Every new endpoint introduced by this spec (`POST/GET/DELETE /api/v1/quotes/{quote_id}/attachments`, plus the extensions to `POST /api/v1/quotes`, `PUT /api/v1/quotes/{id}`, and `GET /api/v1/quotes/{id}`) requires a valid JWT and the `org_admin` or `salesperson` role (see Requirement 14).

### NFR-2 — Organisation isolation

Every new quote-attachment endpoint scopes all database access by `org_id`, using the existing `Quote.id == quote_id AND Quote.org_id == org_id` pattern (Requirement 12). The `quote_attachments` table additionally has RLS enabled with an `org_id`-based policy (Requirement 17).

### NFR-3 — Migration discipline

All schema changes ship as a single Alembic revision `0184` with `down_revision = "0183"`. Every column addition uses `ADD COLUMN IF NOT EXISTS`; the `quote_attachments` creation early-returns when the table exists. Every new column is nullable or has a server default. The migration is fully reversible — `alembic downgrade -1` restores the schema bit-for-bit. HA publication membership is guarded by `DO $ha_block$` so the same migration runs unchanged on dev, HA standby, and Pi prod (Requirement 13).

### NFR-4 — Row-level security and HA membership

The `quote_attachments` table has RLS enabled with policy `quote_attachments_org_isolation USING (org_id = current_setting('app.current_org_id')::uuid)`. The table is a member of `ora_publication` wherever that publication exists, and the membership step is a no-op where it does not (Requirement 17).

### NFR-5 — File limits and allow-list

- Attachment_Size_Cap: 20 MB per file (`MAX_FILE_SIZE = 20 * 1024 * 1024`).
- Attachment_Count_Cap: 5 Quote_Attachments per Quote_Record.
- Attachment_MIME_Allow_List: `image/jpeg`, `image/png`, `image/webp`, `image/gif`, `application/pdf`.
- These limits are identical to the invoice-attachment limits and are enforced server-side before any Quote_Attachment row is written (Requirement 3).

### NFR-6 — Safe API consumption on every frontend touchpoint

Every new `apiClient` call and every new state assignment in `QuoteCreate.tsx`, `QuoteDetail.tsx`, `QuoteList.tsx`, and `QuoteAttachmentList.tsx` MUST follow `.kiro/steering/safe-api-consumption.md`: typed generics on every call, `res.data?.<field> ?? <fallback>` on every assignment, `?? []` before every `.map/.filter/.length`, `?? 0` before every `.toFixed/.toLocaleString`, and `AbortController` cleanup in every `useEffect` (Requirement 16).

### NFR-7 — No breaking changes to existing quote endpoints

Every field introduced by this spec is additive and optional on request. Every existing response field keeps its name, shape, and semantics. A client predating this spec continues to work without change (Requirement 15).

### NFR-8 — Content-Disposition parity with invoice attachments

The `Content-Disposition` header returned by `GET /api/v1/quotes/{quote_id}/attachments/{attachment_id}` uses the Content_Disposition_Formula and equals the header returned by the invoice-attachment endpoint for the same `(mime_type, file_name)` pair (Requirement 3, property CP-1).

---

## 5. Out of Scope

The following items from `design.md` §12 are explicitly excluded. Each would expand scope beyond Phases 5 + 7; none may be quietly folded into this spec.

| Feature | Rationale |
|---------|-----------|
| Make Recurring toggle on quotes | Recurring is a billing-cadence concept; a quote is a one-time document that either accepts or expires. |
| Mark Paid & Email on quotes | Quotes have not been paid by definition; the action is conceptually incoherent on a quote. |
| Payment gateway selector (Cash / EFTPOS / Bank Transfer / Stripe) on quotes | Quotes do not take payment; payment preference carries over at convert-to-invoice time. |
| Stripe Connect status indicator on quotes | No direct payment on quotes, so the indicator is irrelevant on this surface. |
| Payment reminder SMS/email for quotes | Quotes use `auto_expire_quotes()` instead; reminders are an invoice-lifecycle concept. |
| Bulk delete endpoint for quotes (`POST /quotes/bulk-delete`) | Not currently requested; single-quote delete is sufficient. |
| POS receipt (`/quotes/:id/pos-receipt`, `POSReceiptPreview`, "Print POS Receipt" action) | A receipt implies a completed transaction; quotes are not transactions. Property CP-7 enforces the absence of this menu item in the PDF_Print_Dropdown. |

---

## 6. Traceability Matrix

Every acceptance criterion is mapped to the design section(s) it derives from, the correctness property it is validated by (if any), and the e2e test case in `scripts/test_quote_parity_e2e.py` that exercises it. E2E test case identifiers used below:

- **TC-AU-HAPPY** — Attachment upload happy path (JPEG ≤ 20 MB).
- **TC-AU-SIZE** — Upload > 20 MB returns 413 and does not persist.
- **TC-AU-MIME** — Upload with disallowed MIME returns 400 and does not persist.
- **TC-AU-COUNT** — 6th upload on a quote returns 400 and does not persist.
- **TC-AU-QUOTA** — Upload with org storage quota exceeded returns 507.
- **TC-AU-NETWORK** — Upload rejected by network/500; UI surfaces retry.
- **TC-AU-ORG404** — Cross-org attachment endpoints all return 404 (CP-2).
- **TC-AU-DISPOS** — Content-Disposition parity with invoice attachments (CP-1).
- **TC-AU-DELETE-DRAFT** — Delete succeeds on draft.
- **TC-AU-DELETE-SENT** — Delete returns 403 on non-draft.
- **TC-GST-ROUND** — GST-inclusive line round-trip (CP-3).
- **TC-MIG-ROUND** — Migration upgrade/downgrade roundtrip leaves schema bit-for-bit identical (CP-4).
- **TC-PAY-FIDELITY** — QuoteCreate payload fidelity: every new field survives create → get (CP-5).
- **TC-LIST-BADGE** — Attachment_Badge renders iff `attachment_count > 0` (CP-6).
- **TC-LIST-NO-POS** — PDF_Print_Dropdown never contains "Print POS Receipt" (CP-7).
- **TC-CREATE-400** — `POST /quotes` with missing customer or empty line items returns 4xx with inline errors.
- **TC-EDIT-REHYDRATE** — `GET /quotes/{id}` returns every new field after create; edit form pre-fills every new field.
- **TC-SAVE-TERMS** — `save_terms_as_default = true` updates org settings; `false` does not.
- **TC-AUTH-401** — Unauthenticated calls to any new endpoint return 401.
- **TC-AUTH-403** — Authenticated non-(org_admin/salesperson) calls return 403.
- **TC-LIST-DOWNLOAD** — "Download PDF" from the list fetches `/quotes/{id}/pdf`.
- **TC-LIST-PRINT** — "Print Quote" from the list navigates and invokes `window.print()`.

| Requirement | Design section(s) | Correctness property | E2E test case(s) |
|---|---|---|---|
| 1.1 — Header fields persisted | §5.2, §5.5, §5.7 | CP-5 | TC-PAY-FIDELITY |
| 1.2 — Line-item fields persisted | §5.1, §5.2, §5.5 | CP-5 | TC-PAY-FIDELITY |
| 1.3 — Salesperson_Dropdown auto-select | §3.1, §4.1 | — | TC-PAY-FIDELITY |
| 1.4 — GST number display | §3.1, §4.1 | — | TC-PAY-FIDELITY |
| 1.5 — Inventory_Picker populates stock link | §3.2, §4.1, §5.7 | CP-5 | TC-PAY-FIDELITY |
| 1.6 — Multi_Vehicle_Section persists | §3.1, §5.1, §5.2 | CP-5 | TC-PAY-FIDELITY |
| 1.7 — Fluid_Usage persists | §3.1, §5.1, §5.2 | CP-5 | TC-PAY-FIDELITY |
| 1.8 — Fluid_Usage non-billable | §5.5 | — | TC-PAY-FIDELITY |
| 1.9 — Auth on POST | §2, §5.6 | — | TC-AUTH-401, TC-AUTH-403 |
| 1.10 — GST-inclusive persistence | §5.5 | CP-3 | TC-GST-ROUND |
| 2.1 — Edit form rehydrates header | §4.1, §5.5, §5.7, §8.2 | CP-5 | TC-EDIT-REHYDRATE |
| 2.2 — Edit form rehydrates line items | §4.1, §5.5, §5.7, §8.2 | CP-5 | TC-EDIT-REHYDRATE |
| 2.3 — PUT persists new fields | §5.5 | CP-5 | TC-EDIT-REHYDRATE |
| 2.4 — PUT on non-draft restricted | §5.5 | — | TC-EDIT-REHYDRATE |
| 2.5 — Auth on PUT | §2, §5.6 | — | TC-AUTH-401, TC-AUTH-403 |
| 2.6 — salesperson_name enrichment | §5.2, §5.5 | CP-5 | TC-EDIT-REHYDRATE |
| 3.1 — Happy path upload | §4.2, §5.4, §5.6 | — | TC-AU-HAPPY |
| 3.2 — Size cap 413 | §4.2, §5.4, §9 | — | TC-AU-SIZE |
| 3.3 — MIME rejection 400 | §4.2, §5.4, §9 | — | TC-AU-MIME |
| 3.4 — Count cap 400 | §4.2, §5.4, §9 | — | TC-AU-COUNT |
| 3.5 — Storage quota 507 | §4.2, §9 | — | TC-AU-QUOTA |
| 3.6 — Auth on upload | §2, §5.6 | — | TC-AUTH-401, TC-AUTH-403 |
| 3.7 — Save draft before upload | §4.2, §8.1 | — | TC-AU-HAPPY |
| 3.8 — Inline disposition image/PDF | §5.6 | CP-1 | TC-AU-DISPOS |
| 3.9 — Attachment disposition otherwise | §5.6 | CP-1 | TC-AU-DISPOS |
| 3.10 — Parity with invoice formula | §5.6 | CP-1 | TC-AU-DISPOS |
| 4.1 — Delete allowed on draft | §4.2, §5.6, §8.4 | — | TC-AU-DELETE-DRAFT |
| 4.2 — Delete blocked on non-draft | §5.6, §8.4, §9 | — | TC-AU-DELETE-SENT |
| 4.3 — Auth on delete | §2, §5.6 | — | TC-AUTH-401, TC-AUTH-403 |
| 4.4 — Delete UI on draft | §3.2, §7.4 | — | TC-AU-DELETE-DRAFT |
| 4.5 — No delete UI on non-draft | §3.2, §7.4 | — | TC-AU-DELETE-SENT |
| 5.1 — Mount QuoteAttachmentList when count > 0 | §3.1, §4.3, §8.5 | — | TC-PAY-FIDELITY, TC-AU-HAPPY |
| 5.2 — No mount when count === 0 | §3.1, §4.3, §8.5 | — | TC-PAY-FIDELITY |
| 5.3 — Attachment row rendering | §3.2, §4.3, §8.5 | — | TC-AU-HAPPY |
| 5.4 — Click opens in new tab | §3.2, §4.3, §8.5 | CP-1 | TC-AU-DISPOS |
| 5.5 — List response shape | §5.2, §5.6 | — | TC-AU-HAPPY |
| 6.1 — Badge renders when count > 0 | §3.1, §4.4, §7.3 | CP-6 | TC-LIST-BADGE |
| 6.2 — Badge omitted when count 0/null | §4.4, §7.3 | CP-6 | TC-LIST-BADGE |
| 6.3 — attachment_count in list response | §5.2, §5.5 | CP-6 | TC-LIST-BADGE |
| 6.4 — count = row count in quote_attachments | §5.5 | CP-6 | TC-LIST-BADGE |
| 7.1 — Dropdown on every row | §3.1, §4.4, §7.3 | CP-7 | TC-LIST-NO-POS |
| 7.2 — Exactly two menu items | §4.4, §7.3 | CP-7 | TC-LIST-NO-POS |
| 7.3 — No "Print POS Receipt" | §4.4, §7.3 | CP-7 | TC-LIST-NO-POS |
| 7.4 — Download fetches /quotes/{id}/pdf | §4.4, §7.3 | — | TC-LIST-DOWNLOAD |
| 7.5 — Print navigates + window.print | §4.4, §7.3 | — | TC-LIST-PRINT |
| 8.1 — Save-as-default writes settings | §3.1, §5.2 | — | TC-SAVE-TERMS |
| 8.2 — Unticked does not write settings | §3.1, §5.2 | — | TC-SAVE-TERMS |
| 8.3 — Terms pre-fill from tenant | §3.3, §4.1 | — | TC-SAVE-TERMS |
| 8.4 — Refetch tenant after save | §3.3 | — | TC-SAVE-TERMS |
| 9.1 — line_total formula | §5.5 | CP-3 | TC-GST-ROUND |
| 9.2 — inclusive_price exact round-trip | §5.5, §5.7 | CP-3 | TC-GST-ROUND |
| 9.3 — gst_inclusive true round-trip | §5.5, §5.7 | CP-3 | TC-GST-ROUND |
| 9.4 — GST share formula | §5.5 | CP-3 | TC-GST-ROUND |
| 9.5 — Parity with invoice calculation | §5.5 | CP-3 | TC-GST-ROUND |
| 10.1 — 413 UI message | §4.2, §9 | — | TC-AU-SIZE |
| 10.2 — MIME UI message | §4.2, §9 | — | TC-AU-MIME |
| 10.3 — Count-cap UI message | §9 | — | TC-AU-COUNT |
| 10.4 — 507 UI message | §4.2, §9 | — | TC-AU-QUOTA |
| 10.5 — Network UI message | §4.2, §9 | — | TC-AU-NETWORK |
| 10.6 — 403 delete UI message | §8.4, §9 | — | TC-AU-DELETE-SENT |
| 11.1 — 400/422 creation errors | §9 | — | TC-CREATE-400 |
| 11.2 — 500 creation errors | §9 | — | TC-CREATE-400 |
| 11.3 — Network error on create | §9 | — | TC-CREATE-400 |
| 11.4 — Client-side empty-line block | §8.1 | — | TC-CREATE-400 |
| 12.1 — Cross-org GET list 404 | §5.6, §9 | CP-2 | TC-AU-ORG404 |
| 12.2 — Cross-org GET file 404 | §5.6, §9 | CP-2 | TC-AU-ORG404 |
| 12.3 — Cross-org POST 404 | §5.6, §9 | CP-2 | TC-AU-ORG404 |
| 12.4 — Cross-org DELETE 404 | §5.6, §9 | CP-2 | TC-AU-ORG404 |
| 12.5 — No information leak in 404 | §9 | CP-2 | TC-AU-ORG404 |
| 12.6 — RLS policy on quote_attachments | §5.3, §6.1 | — | TC-MIG-ROUND |
| 13.1 — Single revision 0184 | §5.3, §6.1 | CP-4 | TC-MIG-ROUND |
| 13.2 — Idempotent re-run | §5.3, §6.4 | CP-4 | TC-MIG-ROUND |
| 13.3 — New columns on quotes | §5.3, §6.3 | CP-4 | TC-MIG-ROUND |
| 13.4 — New columns on quote_line_items | §5.3, §6.3 | CP-4 | TC-MIG-ROUND |
| 13.5 — quote_attachments table created | §5.3 | CP-4 | TC-MIG-ROUND |
| 13.6 — HA publication guard | §5.3, §6.1 | CP-4 | TC-MIG-ROUND |
| 13.7 — Reversible downgrade | §5.3, §6.2 | CP-4 | TC-MIG-ROUND |
| 13.8 — Existing rows preserved on upgrade | §6.1, §6.3 | CP-4 | TC-MIG-ROUND |
| 13.9 — Existing rows preserved on downgrade | §6.2 | CP-4 | TC-MIG-ROUND |
| 14.1–14.4 — 401 on attachment endpoints | §2, §5.6 | — | TC-AUTH-401 |
| 14.5 — 403 for non-(admin/salesperson) | §2, §5.6 | — | TC-AUTH-403 |
| 14.6 — 401 on POST/PUT quote | §2 | — | TC-AUTH-401 |
| 14.7 — 403 on POST/PUT quote for wrong role | §2 | — | TC-AUTH-403 |
| 15.1 — Additive POST | §5.2, §6.3 | — | TC-PAY-FIDELITY |
| 15.2 — Additive PUT | §5.2, §5.5 | — | TC-EDIT-REHYDRATE |
| 15.3 — GET endpoints unchanged | §5.2 | — | TC-PAY-FIDELITY |
| 15.4 — Schema additions are additive | §5.2 | — | TC-PAY-FIDELITY |
| 16.1 — Typed generics on apiClient | §5.7 | — | (frontend lint) |
| 16.2 — Safe state assignments | §5.7 | — | (frontend lint) |
| 16.3 — Guarded array ops | §5.7 | — | (frontend lint) |
| 16.4 — Guarded number formatters | §5.7 | — | (frontend lint) |
| 16.5 — AbortController in useEffect | §5.7 | — | (frontend lint) |
| 17.1 — RLS enabled | §5.3 | CP-4 | TC-MIG-ROUND |
| 17.2 — org_id isolation policy | §5.3 | CP-2 | TC-AU-ORG404, TC-MIG-ROUND |
| 17.3 — HA publication membership added | §5.3, §6.1 | CP-4 | TC-MIG-ROUND |
| 17.4 — Guard is no-op without publication | §5.3, §6.1 | CP-4 | TC-MIG-ROUND |
| 17.5 — Publication membership dropped on downgrade | §5.3, §6.2 | CP-4 | TC-MIG-ROUND |

---

## 7. Document Status

- Derived directly from `.kiro/specs/quote-invoice-parity/design.md`.
- No expansion of scope: OQ-1 and OQ-2 resolved YES, so every previously "OQ-gated" surface is required unconditionally.
- No new open questions introduced.
- Next phase: property mapping / `Correctness Properties` update inside `design.md`, then `tasks.md`.
