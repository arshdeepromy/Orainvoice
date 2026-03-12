# Tasks

## Task 1: Migration and model — add `catalogue_item_id` to `job_card_items`

Requirements: 1.1, 1.2, 1.3

Create Alembic migration `0085` that adds a nullable UUID column `catalogue_item_id` to `job_card_items` with a FK to `items_catalogue.id`. Update the `JobCardItem` ORM model to include the new column.

Files to change:
- `alembic/versions/2026_03_11_1400-0085_job_card_items_catalogue_ref.py` (new)
- `app/modules/job_cards/models.py`

- [x] Create migration file `alembic/versions/2026_03_11_1400-0085_job_card_items_catalogue_ref.py` with `op.add_column('job_card_items', sa.Column('catalogue_item_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('items_catalogue.id'), nullable=True))` and matching downgrade
- [x] Add `catalogue_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("items_catalogue.id"), nullable=True)` to `JobCardItem` in `app/modules/job_cards/models.py`

## Task 2: Serialiser and service — persist and expose `catalogue_item_id` on job card items

Requirements: 1.4, 4.1, 4.2, 5.1, 5.2

Update `_line_item_to_dict` to include `catalogue_item_id` in output. Update `create_job_card` and `update_job_card` to persist `catalogue_item_id` from `line_items_data`.

Files to change:
- `app/modules/job_cards/service.py`

- [x] Add `"catalogue_item_id": li.catalogue_item_id` to the dict returned by `_line_item_to_dict`
- [x] Add `catalogue_item_id=item_data.get("catalogue_item_id")` to the `JobCardItem(...)` constructor in `create_job_card`'s line item loop
- [x] Add `catalogue_item_id=item_data.get("catalogue_item_id")` to the `JobCardItem(...)` constructor in `update_job_card`'s line item replacement loop

## Task 3: Booking → Job Card — resolve catalogue and create line item

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6

Update `convert_booking_to_job_card` to look up the catalogue item by `service_catalogue_id`, build a `line_items_data` list with `catalogue_item_id`, description, and price resolved from the catalogue, and pass it to `create_job_card`. Fall back to booking snapshot if catalogue item is missing/inactive.

Files to change:
- `app/modules/bookings/service.py`

- [x] Add `from decimal import Decimal` to imports at top of file
- [x] Before the `create_job_card` call in `convert_booking_to_job_card`, add catalogue lookup: query `ItemsCatalogue` by `booking.service_catalogue_id`, build `line_items_data` with `catalogue_item_id`, `description` from `cat_item.name`, `unit_price` from `cat_item.default_price`, `item_type="service"`, `quantity=Decimal("1")`
- [x] Add fallback: if catalogue item not found or inactive, use `booking.service_type` / `booking.service_price` with `catalogue_item_id=None`
- [x] Pass `line_items_data=line_items_data` to the `create_job_card` call

## Task 4: Job Card → Invoice — propagate `catalogue_item_id`

Requirements: 3.1, 3.2, 3.3

Update `convert_job_card_to_invoice` and `combine_job_cards_to_invoice` to include `catalogue_item_id` when building invoice line items from job card items.

Files to change:
- `app/modules/job_cards/service.py`

- [x] Add `"catalogue_item_id": li.get("catalogue_item_id")` to each dict appended in `convert_job_card_to_invoice`'s `invoice_line_items` loop
- [x] Add `"catalogue_item_id": li.get("catalogue_item_id")` to each dict appended in `combine_job_cards_to_invoice`'s `invoice_line_items` loop
