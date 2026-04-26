# Design: Job Card Catalogue Line Items

## Architecture Overview

This feature is **frontend-only** — the backend already supports all required fields on `job_card_items` (`catalogue_item_id`, `item_type`, `quantity`, `unit_price`, `sort_order`). The `create_job_card` service already accepts these in `line_items_data`. The `convert_job_card_to_invoice` service already propagates `catalogue_item_id` through to invoice line items.

The work is:
1. Rewrite the "Work to be Performed" section in `JobCardCreate.tsx` to use a line item table with catalogue search
2. Update `JobCardDetail.tsx` to show line items with pricing
3. Verify the job-to-invoice conversion works end-to-end

## Data Flow

```
items_catalogue (source of truth)
       │
       ├── User selects item in JobCardCreate
       │   → catalogue_item_id + description + unit_price stored on job_card_items
       │
       ├── Job card completed → "Issue Invoice" clicked
       │   → convert_job_card_to_invoice() maps job_card_items → invoice line_items
       │   → catalogue_item_id preserved (per catalogue-reference-architecture.md)
       │   → unit_price snapshot preserved (price at time of job creation)
       │
       └── Invoice created in draft status → user reviews and adjusts → issues
```

## Component Design

### JobCardCreate.tsx — Line Item Table

Replace the `WorkItem[]` array (text-only) with a `LineItem[]` array matching this interface:

```typescript
interface LineItem {
  key: string              // unique key for React rendering
  catalogue_item_id: string | null  // FK to items_catalogue, null for ad-hoc
  item_type: 'service' | 'part' | 'labour'
  description: string
  quantity: number
  unit_price: number
  is_gst_exempt: boolean
}
```

The line item table renders as:

| Item Details | Qty | Rate | Amount | × |
|---|---|---|---|---|
| [Search/type item name] | [1] | [$0.00] | $0.00 | 🗑 |
| [Search/type item name] | [1] | [$0.00] | $0.00 | 🗑 |
| **+ Add Row** | | | **Subtotal: $X.XX** | |

### Catalogue Search Dropdown

Reuse the same pattern from `InvoiceCreate.tsx` `ItemTableRow`:
- On focus/type in the description field, fetch `GET /catalogue/items?active_only=true`
- Filter locally by typed text (case-insensitive substring match on name)
- Show top 10 results in an absolutely-positioned dropdown with `z-50`
- Each result shows: item name, default price
- On select: set `catalogue_item_id`, `description` (from item name), `unit_price` (from default_price)
- User can still type freely without selecting — this creates an ad-hoc item with `catalogue_item_id = null`

### Catalogue Data Loading

Fetch catalogue items once on component mount:
```typescript
useEffect(() => {
  const controller = new AbortController()
  apiClient.get<{ items: CatalogueItem[] }>('/catalogue/items', {
    params: { active_only: true },
    signal: controller.signal,
  })
    .then(res => setCatalogueItems(res.data?.items ?? []))
    .catch(err => { if (!controller.signal.aborted) setCatalogueItems([]) })
  return () => controller.abort()
}, [])
```

### Payload Construction

When submitting the form, build `line_items` array:
```typescript
const line_items = lineItems
  .filter(li => li.description.trim())
  .map((li, i) => ({
    item_type: li.item_type,
    description: li.description,
    quantity: li.quantity,
    unit_price: li.unit_price,
    is_gst_exempt: li.is_gst_exempt,
    sort_order: i,
    ...(li.catalogue_item_id ? { catalogue_item_id: li.catalogue_item_id } : {}),
  }))
```

### JobCardDetail.tsx — Line Items Display

Currently shows items as a simple list of descriptions. Update to show a table:

| # | Description | Qty | Unit Price | Total |
|---|---|---|---|---|
| 1 | Oil change service | 1 | $85.00 | $85.00 |
| 2 | Oil filter | 1 | $25.00 | $25.00 |
| | | | **Subtotal** | **$110.00** |

### Existing Features Preserved

- Customer search with create modal — unchanged
- Vehicle rego lookup (automotive) — unchanged, stays gated behind `isAutomotive`
- Job description field — unchanged
- Notes field — unchanged
- Staff assignment — unchanged (if present)

## Files Changed

| File | Change |
|---|---|
| `frontend/src/pages/job-cards/JobCardCreate.tsx` | Replace WorkItem section with line item table + catalogue search |
| `frontend/src/pages/job-cards/JobCardDetail.tsx` | Update items display to show pricing table |

## Files NOT Changed

| File | Reason |
|---|---|
| `app/modules/job_cards/models.py` | Already has `catalogue_item_id`, `quantity`, `unit_price` on JobCardItem |
| `app/modules/job_cards/schemas.py` | `JobCardItemCreate` already accepts all needed fields |
| `app/modules/job_cards/service.py` | `create_job_card` already handles `catalogue_item_id` in `line_items_data` |
| `app/modules/job_cards/router.py` | Already passes `line_items_data` correctly |
| `app/modules/invoices/service.py` | `convert_job_card_to_invoice` already preserves `catalogue_item_id` |

## Key Patterns to Follow

1. **Catalogue reference architecture** — always store `catalogue_item_id` FK, snapshot price at creation time
2. **Safe API consumption** — `?.` and `?? []` on all API responses, AbortController cleanup
3. **Frontend-backend contract** — field names must match `JobCardItemCreate` schema exactly
4. **No viewport heights** — page must scroll naturally within OrgLayout's `<main>` container
5. **Overflow visible** — table container must use `overflow-visible` so catalogue dropdown isn't clipped (ISSUE-031)
