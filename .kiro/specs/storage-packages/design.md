# Design Document: Storage Packages

## Overview

This feature replaces the flat storage add-on pricing with a proper storage package system. It introduces a `storage_packages` table for Global Admin-managed tiers, an `org_storage_addons` table for tracking the single active add-on per org, a "Storage" tab in the admin Subscription Management page, and an updated Billing page with package selection and resize flows.

The implementation touches four layers:

1. **Data layer** — Two new tables: `storage_packages` (no RLS, global admin) and `org_storage_addons` (RLS scoped to `org_id`). Alembic migration.
2. **Backend layer** — New SQLAlchemy models in `app/modules/admin/models.py`, Pydantic schemas in `app/modules/admin/schemas.py`, service functions in `app/modules/admin/service.py`, CRUD endpoints in `app/modules/admin/router.py`, and updated billing endpoint.
3. **Frontend admin layer** — New "Storage" tab in `SubscriptionPlans.tsx` with DataTable, create/edit modal, and deactivate actions.
4. **Frontend org layer** — Updated `Billing.tsx` with storage package selection modal and resize flow.

### Key Design Decisions

- **Single add-on per org**: `org_storage_addons` has a unique constraint on `org_id`. No stacking — resize replaces the existing add-on.
- **Package or custom**: `org_storage_addons.storage_package_id` is nullable. When null and `is_custom = true`, the add-on uses the fallback price-per-GB rate.
- **No Stripe initially**: Purchases are recorded internally and quota is increased immediately. Stripe charging is deferred to billing integration.
- **Soft delete only**: Deactivating a storage package sets `is_active = false`. Packages referenced by active add-ons cannot be hard-deleted.
- **Existing fallback pricing preserved**: The `platform_settings.storage_pricing` config (price_per_gb_nzd) remains as the fallback for custom amounts and is displayed in the admin UI.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend                              │
│                                                         │
│  SubscriptionPlans.tsx          Billing.tsx              │
│  ┌──────┬─────────┬─────────┐  ┌─────────────────────┐  │
│  │Plans │ Coupons │ Storage │  │ Storage card         │  │
│  └──────┴─────────┴─────────┘  │ + Manage storage btn │  │
│  Storage tab:                   │ + Package select     │  │
│  - Package DataTable            │ + Resize flow        │  │
│  - Create/Edit modal            └─────────────────────┘  │
│  - Global pricing card                                   │
└──────────────────────┬──────────────────┬────────────────┘
                       │                  │
                       ▼                  ▼
┌──────────────────────────────────────────────────────────┐
│                  FastAPI Backend                          │
│                                                          │
│  Admin Router                  Billing Router            │
│  GET  /admin/storage-packages  GET /billing              │
│  POST /admin/storage-packages  (includes addon fields)   │
│  PUT  /admin/storage-packages/{id}                       │
│  DELETE /admin/storage-packages/{id}                     │
│                                                          │
│  Org Billing Router                                      │
│  GET  /billing/storage-addon                             │
│  POST /billing/storage-addon                             │
│  PUT  /billing/storage-addon                             │
│  DELETE /billing/storage-addon                           │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│                   Data Layer                              │
│                                                          │
│  storage_packages (no RLS)    org_storage_addons (RLS)   │
│  - id, name, storage_gb      - id, org_id (unique)      │
│  - price_nzd_per_month       - storage_package_id (FK)   │
│  - description, sort_order   - quantity_gb, price        │
│  - is_active                 - is_custom, purchased_at   │
│                                                          │
│  platform_settings                                       │
│  - storage_pricing (fallback price_per_gb_nzd)           │
│                                                          │
│  organisations                                           │
│  - storage_quota_gb (base + addon)                       │
└──────────────────────────────────────────────────────────┘
```

## Data Models

### storage_packages table

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, gen_random_uuid() |
| name | String(100) | NOT NULL |
| storage_gb | Integer | NOT NULL, > 0 |
| price_nzd_per_month | Numeric(10,2) | NOT NULL, >= 0 |
| description | String(255) | nullable |
| is_active | Boolean | NOT NULL, default true |
| sort_order | Integer | NOT NULL, default 0 |
| created_at | DateTime(tz) | NOT NULL, server_default now() |
| updated_at | DateTime(tz) | NOT NULL, server_default now() |

No RLS. Global admin managed.

### org_storage_addons table

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, gen_random_uuid() |
| org_id | UUID | FK → organisations.id, NOT NULL, UNIQUE |
| storage_package_id | UUID | FK → storage_packages.id, nullable |
| quantity_gb | Integer | NOT NULL, > 0 |
| price_nzd_per_month | Numeric(10,2) | NOT NULL |
| is_custom | Boolean | NOT NULL, default false |
| purchased_at | DateTime(tz) | NOT NULL |
| updated_at | DateTime(tz) | NOT NULL, server_default now() |

RLS enabled, scoped to `org_id`. Unique constraint on `org_id` ensures one add-on per org.

## API Endpoints

### Global Admin — Storage Package CRUD

**GET /api/v1/admin/storage-packages**
- Query params: `include_inactive` (bool, default false)
- Response: `{ packages: StoragePackageResponse[], total: int }`

**POST /api/v1/admin/storage-packages**
- Body: `StoragePackageCreateRequest`
- Response: `StoragePackageResponse` (201)

**PUT /api/v1/admin/storage-packages/{id}**
- Body: `StoragePackageUpdateRequest`
- Response: `StoragePackageResponse`

**DELETE /api/v1/admin/storage-packages/{id}**
- Soft-delete (sets is_active = false)
- Response: `{ message: str }`

### Org Admin — Storage Add-on Management

**GET /api/v1/billing/storage-addon**
- Returns current active add-on for the org (or null)
- Also returns available packages for selection
- Response: `StorageAddonStatusResponse`

**POST /api/v1/billing/storage-addon**
- Purchase a new storage add-on (only if org has no active add-on)
- Body: `StorageAddonPurchaseRequest` — either `package_id` or `custom_gb`
- Response: `StorageAddonResponse`

**PUT /api/v1/billing/storage-addon**
- Resize existing add-on (upgrade or downgrade)
- Body: `StorageAddonResizeRequest` — either `package_id` or `custom_gb`
- Response: `StorageAddonResponse`

**DELETE /api/v1/billing/storage-addon**
- Remove the active add-on, revert to plan base quota
- Validates usage doesn't exceed base quota
- Response: `{ message: str }`

## Pydantic Schemas

```python
# Admin schemas
class StoragePackageCreateRequest(BaseModel):
    name: str  # min 1, max 100
    storage_gb: int  # > 0
    price_nzd_per_month: float  # >= 0
    description: str | None = None
    sort_order: int = 0

class StoragePackageUpdateRequest(BaseModel):
    name: str | None = None
    storage_gb: int | None = None  # > 0
    price_nzd_per_month: float | None = None  # >= 0
    description: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None

class StoragePackageResponse(BaseModel):
    id: str
    name: str
    storage_gb: int
    price_nzd_per_month: float
    description: str | None
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

# Org billing schemas
class StorageAddonPurchaseRequest(BaseModel):
    package_id: str | None = None  # mutually exclusive with custom_gb
    custom_gb: int | None = None   # > 0, used when package_id is None

class StorageAddonResizeRequest(BaseModel):
    package_id: str | None = None
    custom_gb: int | None = None

class StorageAddonResponse(BaseModel):
    id: str
    package_name: str | None  # null for custom
    quantity_gb: int
    price_nzd_per_month: float
    is_custom: bool
    purchased_at: datetime

class StorageAddonStatusResponse(BaseModel):
    current_addon: StorageAddonResponse | None
    available_packages: list[StoragePackageResponse]
    fallback_price_per_gb_nzd: float
    base_quota_gb: int
    total_quota_gb: int
    storage_used_gb: float
```

## Frontend Components

### Admin — Storage Tab (SubscriptionPlans.tsx)

- Add `'storage'` to `activeMainTab` union type
- New tab button in tab bar
- `StoragePackagesContent` component:
  - Fetches from `GET /admin/storage-packages`
  - DataTable with columns: Name, GB, Price/mo, Description, Sort, Status, Actions
  - Create/Edit modal with form fields
  - Deactivate button per row
  - "Show deactivated" checkbox
- Retains existing `GlobalStoragePricing` card above the table

### Org — Storage Management (Billing.tsx)

- Replace disabled "Buy more storage" button with "Manage storage"
- `StorageManageModal` component:
  - If no active add-on: shows package cards + custom option → purchase flow
  - If active add-on: shows current add-on + resize options → resize flow
  - Confirmation step before action
  - Remove add-on option (with usage validation)

## Error Handling

| Scenario | HTTP Status | Message |
|----------|-------------|---------|
| Package not found | 404 | "Storage package not found" |
| Package inactive | 400 | "This storage package is no longer available" |
| Org already has add-on (on POST) | 409 | "Organisation already has a storage add-on. Use resize instead." |
| No active add-on (on PUT/DELETE) | 404 | "No active storage add-on found" |
| Downgrade blocked by usage | 400 | "Current storage usage (X GB) exceeds the new quota (Y GB). Free up space first." |
| Custom GB < 1 | 422 | Validation error |
| Neither package_id nor custom_gb | 422 | "Provide either package_id or custom_gb" |

## Migration Strategy

- New migration creates `storage_packages` and `org_storage_addons` tables
- Existing `platform_settings.storage_pricing` (price_per_gb_nzd) is preserved as fallback for custom amounts
- Existing `storage_tier_pricing` JSONB on `subscription_plans` is left in place but no longer used for the purchase flow — it can be deprecated later
- The old `purchase_storage_addon` function in `app/modules/storage/service.py` is kept but marked as deprecated
