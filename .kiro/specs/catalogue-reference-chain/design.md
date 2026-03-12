# Design Document

## Overview

This design adds `catalogue_item_id` to `job_card_items` and wires the full Booking → Job Card → Invoice conversion chain to propagate catalogue references. The key changes are: one Alembic migration, one model column addition, and updates to four service functions (`convert_booking_to_job_card`, `create_job_card`, `update_job_card`, `convert_job_card_to_invoice`, `combine_job_cards_to_invoice`).

## Architecture

```
┌──────────────┐      ┌──────────────────┐      ┌──────────────────┐
│   Booking    │      │   JobCardItem    │      │   LineItem       │
│              │      │                  │      │   (invoice)      │
│ service_     │─────▶│ catalogue_       │─────▶│ catalogue_       │
│ catalogue_id │ (1)  │ item_id [NEW]    │ (2)  │ item_id [EXISTS] │
│              │      │                  │      │                  │
│ service_     │      │ description      │      │ description      │
│ price        │      │ unit_price       │      │ unit_price       │
└──────────────┘      └──────────────────┘      └──────────────────┘
        │                      │                         │
        └──────────────────────┴─────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  items_catalogue    │
                    │  (source of truth)  │
                    │  .name             │
                    │  .default_price    │
                    │  .is_gst_exempt    │
                    └─────────────────────┘

(1) convert_booking_to_job_card: resolves catalogue → creates job_card_item with FK
(2) convert_job_card_to_invoice: copies catalogue_item_id into invoice line_item
```

## Database Changes

### Migration 0085: Add `catalogue_item_id` to `job_card_items`

File: `alembic/versions/2026_03_11_1400-0085_job_card_items_catalogue_ref.py`

```sql
ALTER TABLE job_card_items
  ADD COLUMN catalogue_item_id UUID REFERENCES items_catalogue(id);
```

- Nullable — existing job card items and manually-added items have no catalogue link.
- No index needed (not queried by this column in hot paths).
- Revises: `0084_job_cards_assigned_to_staff`

## Component Changes

### 1. Model: `JobCardItem` — add `catalogue_item_id`

File: `app/modules/job_cards/models.py`

Add after `description`:

```python
catalogue_item_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True), ForeignKey("items_catalogue.id"), nullable=True
)
```

No relationship needed — we only store the FK for traceability, not for eager loading.

### 2. Serialiser: `_line_item_to_dict` — include `catalogue_item_id`

File: `app/modules/job_cards/service.py`, function `_line_item_to_dict`

Current output dict is missing `catalogue_item_id`. Add it:

```python
def _line_item_to_dict(li: JobCardItem) -> dict:
    line_total = _calculate_line_total(li.quantity, li.unit_price)
    return {
        "id": li.id,
        "catalogue_item_id": li.catalogue_item_id,  # NEW
        "item_type": li.item_type,
        "description": li.description,
        "quantity": li.quantity,
        "unit_price": li.unit_price,
        "is_completed": li.is_completed,
        "line_total": line_total,
        "sort_order": li.sort_order,
    }
```

### 3. `create_job_card` — persist `catalogue_item_id` from `line_items_data`

File: `app/modules/job_cards/service.py`, function `create_job_card`

In the line item creation loop, add `catalogue_item_id`:

```python
li = JobCardItem(
    job_card_id=job_card.id,
    org_id=org_id,
    item_type=item_data["item_type"],
    description=item_data["description"],
    quantity=item_data["quantity"],
    unit_price=item_data["unit_price"],
    catalogue_item_id=item_data.get("catalogue_item_id"),  # NEW
    sort_order=item_data.get("sort_order", i),
)
```

### 4. `update_job_card` — persist `catalogue_item_id` on replacement items

File: `app/modules/job_cards/service.py`, function `update_job_card`

In the line item replacement loop, add `catalogue_item_id`:

```python
li = JobCardItem(
    job_card_id=job_card.id,
    org_id=org_id,
    item_type=item_data["item_type"],
    description=item_data["description"],
    quantity=item_data["quantity"],
    unit_price=item_data["unit_price"],
    catalogue_item_id=item_data.get("catalogue_item_id"),  # NEW
    sort_order=item_data.get("sort_order", i),
)
```

### 5. `convert_booking_to_job_card` — resolve catalogue and create line item

File: `app/modules/bookings/service.py`, function `convert_booking_to_job_card`

Before calling `create_job_card`, build `line_items_data` from the booking's catalogue reference:

```python
# Build line_items_data from booking's catalogue reference
line_items_data: list[dict] = []
if booking.service_catalogue_id is not None:
    from app.modules.catalogue.models import ItemsCatalogue
    cat_result = await db.execute(
        select(ItemsCatalogue).where(
            ItemsCatalogue.id == booking.service_catalogue_id
        )
    )
    cat_item = cat_result.scalar_one_or_none()
    if cat_item is not None and cat_item.is_active:
        line_items_data.append({
            "item_type": "service",
            "catalogue_item_id": cat_item.id,
            "description": cat_item.name,
            "quantity": Decimal("1"),
            "unit_price": cat_item.default_price,
        })
    else:
        # Catalogue item missing or inactive — fall back to booking snapshot
        if booking.service_price is not None:
            line_items_data.append({
                "item_type": "service",
                "catalogue_item_id": None,
                "description": booking.service_type or "Service",
                "quantity": Decimal("1"),
                "unit_price": booking.service_price,
            })

job_card = await create_job_card(
    db, org_id=org_id, user_id=user_id,
    customer_id=customer_id,
    vehicle_rego=booking.vehicle_rego,
    description=booking.service_type,
    notes=booking.notes,
    assigned_to=assigned_to,
    line_items_data=line_items_data,  # NEW
    ip_address=ip_address,
)
```

Requires adding `from decimal import Decimal` at the top of the file.

### 6. `convert_job_card_to_invoice` — propagate `catalogue_item_id`

File: `app/modules/job_cards/service.py`, function `convert_job_card_to_invoice`

In the loop that builds `invoice_line_items`, add `catalogue_item_id`:

```python
invoice_line_items.append({
    "item_type": li["item_type"],
    "description": li["description"],
    "quantity": li["quantity"],
    "unit_price": li["unit_price"],
    "catalogue_item_id": li.get("catalogue_item_id"),  # NEW
    "is_gst_exempt": li.get("is_gst_exempt", False),
    "sort_order": li.get("sort_order", 0),
})
```

### 7. `combine_job_cards_to_invoice` — propagate `catalogue_item_id`

File: `app/modules/job_cards/service.py`, function `combine_job_cards_to_invoice`

Same change as above in the line item loop:

```python
invoice_line_items.append({
    "item_type": li["item_type"],
    "description": li["description"],
    "quantity": li["quantity"],
    "unit_price": li["unit_price"],
    "catalogue_item_id": li.get("catalogue_item_id"),  # NEW
    "is_gst_exempt": li.get("is_gst_exempt", False),
    "sort_order": sort_offset + li.get("sort_order", 0),
})
```

## Files Changed

| File | Change |
|---|---|
| `alembic/versions/2026_03_11_1400-0085_job_card_items_catalogue_ref.py` | New migration: add `catalogue_item_id` column |
| `app/modules/job_cards/models.py` | Add `catalogue_item_id` to `JobCardItem` |
| `app/modules/job_cards/service.py` | Update `_line_item_to_dict`, `create_job_card`, `update_job_card`, `convert_job_card_to_invoice`, `combine_job_cards_to_invoice` |
| `app/modules/bookings/service.py` | Update `convert_booking_to_job_card` to resolve catalogue and pass `line_items_data` |

## What Does NOT Change

- `items_catalogue` schema — no changes.
- `bookings` schema — `service_catalogue_id` already exists.
- `line_items` (invoice) schema — `catalogue_item_id` already exists.
- `create_invoice` — already accepts `catalogue_item_id` in `line_items_data`.
- Frontend — no changes needed for this backend-only chain fix. The invoice will now have line items with correct prices, which the existing frontend already renders.

## Risk & Rollback

- Migration is additive (nullable column) — safe to deploy, no data loss on rollback.
- Existing job card items get `catalogue_item_id = NULL` — correct, they were created without catalogue links.
- No breaking API changes — `catalogue_item_id` is optional everywhere.
