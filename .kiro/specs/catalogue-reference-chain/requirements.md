# Requirements Document

## Introduction

The Catalogue Reference Chain feature ensures that the `catalogue_item_id` foreign key is propagated through the entire Booking → Job Card → Invoice data flow. Currently, when a booking with a catalogue-linked service is converted to a job card, no line items are created. When a job card is converted to an invoice, the `catalogue_item_id` is not carried forward. This feature adds the missing `catalogue_item_id` column to `job_card_items`, updates the conversion functions to create and propagate line items with catalogue references, and ensures invoices generated from this chain have correct totals and traceability back to the catalogue.

## Glossary

- **Converter**: The set of service functions (`convert_booking_to_job_card`, `convert_job_card_to_invoice`, `complete_job`) that transform one entity into the next in the Booking → Job Card → Invoice chain.
- **JobCardItem**: A line item on a job card, stored in the `job_card_items` table.
- **LineItem**: A line item on an invoice, stored in the `line_items` table.
- **ItemsCatalogue**: The `items_catalogue` table, the single source of truth for service names, descriptions, and default prices.
- **CatalogueItemId**: A UUID foreign key column referencing `items_catalogue.id`, used to trace a line item back to its catalogue source.
- **Booking**: An appointment record that may reference a catalogue item via `service_catalogue_id`.
- **JobCard**: A work order created from a booking or manually, containing zero or more JobCardItems.
- **Invoice**: A financial document created from a completed job card, containing zero or more LineItems.

## Requirements

### Requirement 1: Add catalogue_item_id column to job_card_items

**User Story:** As a workshop manager, I want job card items to reference the items catalogue, so that I can trace every line item back to its catalogue source.

#### Acceptance Criteria

1. THE Migration SHALL add a nullable UUID column `catalogue_item_id` to the `job_card_items` table.
2. THE Migration SHALL create a foreign key constraint from `job_card_items.catalogue_item_id` to `items_catalogue.id`.
3. THE JobCardItem ORM model SHALL include a `catalogue_item_id` mapped column of type `UUID`, nullable, referencing `items_catalogue.id`.
4. WHEN a JobCardItem is serialised to a dict, THE Converter SHALL include the `catalogue_item_id` field in the output.

### Requirement 2: Propagate catalogue reference from Booking to Job Card

**User Story:** As a workshop manager, I want converting a booking to a job card to automatically create a line item with the catalogue reference, so that the job card reflects the booked service and its price.

#### Acceptance Criteria

1. WHEN `convert_booking_to_job_card` is called for a Booking that has a non-null `service_catalogue_id`, THE Converter SHALL pass a `line_items_data` list to `create_job_card` containing one item with `catalogue_item_id` set to the Booking's `service_catalogue_id`.
2. WHEN `convert_booking_to_job_card` creates a line item from a catalogue-linked Booking, THE Converter SHALL resolve the `description` from the ItemsCatalogue entry's `name` field.
3. WHEN `convert_booking_to_job_card` creates a line item from a catalogue-linked Booking, THE Converter SHALL resolve the `unit_price` from the ItemsCatalogue entry's `default_price` field.
4. WHEN `convert_booking_to_job_card` creates a line item from a catalogue-linked Booking, THE Converter SHALL set `item_type` to `"service"` and `quantity` to `1`.
5. IF the catalogue item referenced by `service_catalogue_id` is not found or is inactive, THEN THE Converter SHALL fall back to using the Booking's `service_type` as description and `service_price` as unit_price, and SHALL set `catalogue_item_id` to null.
6. WHEN `convert_booking_to_job_card` is called for a Booking that has a null `service_catalogue_id`, THE Converter SHALL NOT create any line items on the job card.

### Requirement 3: Propagate catalogue reference from Job Card to Invoice

**User Story:** As a workshop manager, I want converting a job card to an invoice to carry forward the catalogue reference on each line item, so that invoices maintain full traceability to the catalogue.

#### Acceptance Criteria

1. WHEN `convert_job_card_to_invoice` builds invoice line items from JobCardItems, THE Converter SHALL include `catalogue_item_id` from each JobCardItem in the corresponding invoice LineItem data.
2. WHEN `combine_job_cards_to_invoice` builds invoice line items from multiple job cards, THE Converter SHALL include `catalogue_item_id` from each JobCardItem in the corresponding invoice LineItem data.
3. WHEN `complete_job` triggers invoice creation, THE Converter SHALL propagate `catalogue_item_id` through the `convert_job_card_to_invoice` call.

### Requirement 4: create_job_card accepts catalogue_item_id on line items

**User Story:** As a developer, I want `create_job_card` to accept and persist `catalogue_item_id` on each line item, so that any caller can create catalogue-linked job card items.

#### Acceptance Criteria

1. WHEN `create_job_card` receives `line_items_data` entries containing a `catalogue_item_id` key, THE JobCard service SHALL persist the value in the `catalogue_item_id` column of the created JobCardItem.
2. WHEN `create_job_card` receives `line_items_data` entries without a `catalogue_item_id` key, THE JobCard service SHALL set `catalogue_item_id` to null on the created JobCardItem.

### Requirement 5: update_job_card preserves catalogue_item_id on line item replacement

**User Story:** As a workshop manager, I want editing job card line items to preserve catalogue references, so that traceability is not lost when items are modified.

#### Acceptance Criteria

1. WHEN `update_job_card` replaces line items and the replacement data includes `catalogue_item_id`, THE JobCard service SHALL persist the value on the new JobCardItem.
2. WHEN `update_job_card` replaces line items and the replacement data omits `catalogue_item_id`, THE JobCard service SHALL set `catalogue_item_id` to null on the new JobCardItem.

### Requirement 6: End-to-end catalogue reference chain integrity

**User Story:** As a workshop manager, I want the full Booking → Job Card → Invoice chain to preserve the catalogue reference, so that I can trace any invoice line item back to the original catalogue entry.

#### Acceptance Criteria

1. FOR ALL Bookings with a valid `service_catalogue_id`, converting to a job card and then to an invoice SHALL produce an invoice LineItem whose `catalogue_item_id` equals the original Booking's `service_catalogue_id` (round-trip property).
2. FOR ALL job cards created from catalogue-linked bookings, THE invoice total SHALL be greater than zero when at least one line item has a positive `unit_price`.
3. WHEN a Booking with `service_catalogue_id` is converted through the full chain, THE invoice SHALL contain at least one LineItem (line items are never silently dropped).
