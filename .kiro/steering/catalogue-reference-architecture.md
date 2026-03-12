---
inclusion: auto
---

# Catalogue Reference Architecture — Single Source of Truth

## Principle

Data flows by **reference**, not by copying. When a booking, job card, or invoice involves a catalogue item, each entity stores a **foreign key** (`catalogue_item_id`) pointing to `items_catalogue.id`. The catalogue entry is the single source of truth for name, description, and default price.

## Data Flow

```
items_catalogue (source of truth)
       │
       ├── bookings.service_catalogue_id ──► FK to items_catalogue.id
       │
       ├── job_card_items.catalogue_item_id ──► FK to items_catalogue.id
       │
       └── line_items.catalogue_item_id ──► FK to items_catalogue.id
```

### Booking → Job Card → Invoice

1. **Booking created**: user picks a catalogue item → `bookings.service_catalogue_id` stores the FK. `service_price` is a snapshot for display but the FK is authoritative.
2. **Booking → Job Card**: `convert_booking_to_job_card` creates a `job_card_item` with `catalogue_item_id = booking.service_catalogue_id`. Price and description are resolved from the catalogue at creation time.
3. **Job Card → Invoice**: `convert_job_card_to_invoice` creates an invoice `line_item` with `catalogue_item_id = job_card_item.catalogue_item_id`. Price is carried forward from the job card item (which was resolved from catalogue).

At each conversion step, the catalogue FK is **propagated**, not lost. Name and price are snapshotted into the child record for immutability (invoices must not change if the catalogue price changes later), but the FK is always preserved for traceability and reporting.

## Rules for All Conversion Functions

- **Always propagate `catalogue_item_id`** through the chain.
- **Snapshot price at creation time** — the `unit_price` on job_card_items and line_items is the price at the moment of conversion, not a live lookup.
- **Never silently drop line items** — if a booking has a catalogue item, the resulting job card MUST have a corresponding job_card_item, and the resulting invoice MUST have a corresponding line_item.
- **Manual items** (no catalogue link) are allowed — `catalogue_item_id` can be NULL for ad-hoc items added directly to a job card or invoice.

## Schema Requirements

| Table | Column | Purpose |
|---|---|---|
| `bookings` | `service_catalogue_id` | FK to `items_catalogue.id` |
| `job_card_items` | `catalogue_item_id` | FK to `items_catalogue.id` (needs migration) |
| `line_items` | `catalogue_item_id` | FK to `items_catalogue.id` (already exists) |

## What NOT To Do

- Do not copy data without preserving the catalogue reference.
- Do not create conversion functions that skip line item creation.
- Do not rely on `description` text matching to trace items back to catalogue — use the FK.
