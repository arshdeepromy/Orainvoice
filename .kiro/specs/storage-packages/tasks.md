# Implementation Plan: Storage Packages

## Overview

Replaces the flat storage add-on pricing with a proper storage package system. Global Admins create named storage tiers. Org users purchase a single resizable add-on from the Billing page. Touches data layer (migration), backend (models, schemas, service, router), admin frontend (Storage tab), and org frontend (Billing page storage management).

## Tasks

- [x] 1. Create Alembic migration for storage package tables
  - [x] 1.1 Create `alembic/versions/2026_03_17_1100-0094_create_storage_package_tables.py`
    - Revision ID: `0094`, Revises: `0093`
    - Create `storage_packages` table: `id` (UUID PK, gen_random_uuid()), `name` (String(100), not null), `storage_gb` (Integer, not null), `price_nzd_per_month` (Numeric(10,2), not null), `description` (String(255), nullable), `is_active` (Boolean, not null, default true), `sort_order` (Integer, not null, default 0), `created_at` (DateTime(tz), not null, server_default now()), `updated_at` (DateTime(tz), not null, server_default now())
    - Add check constraint: `storage_gb > 0`
    - Do NOT enable RLS on `storage_packages` (global admin table)
    - Create `org_storage_addons` table: `id` (UUID PK, gen_random_uuid()), `org_id` (UUID FK → organisations.id, not null), `storage_package_id` (UUID FK → storage_packages.id, nullable), `quantity_gb` (Integer, not null), `price_nzd_per_month` (Numeric(10,2), not null), `is_custom` (Boolean, not null, default false), `purchased_at` (DateTime(tz), not null), `updated_at` (DateTime(tz), not null, server_default now())
    - Add unique constraint `uq_org_storage_addons_org_id` on `org_id`
    - Add check constraint: `quantity_gb > 0`
    - Enable RLS on `org_storage_addons`: `ALTER TABLE org_storage_addons ENABLE ROW LEVEL SECURITY`
    - Create tenant isolation policy: `CREATE POLICY tenant_isolation ON org_storage_addons USING (org_id = current_setting('app.current_org_id')::uuid)`
    - Implement `downgrade()`: drop RLS policy, disable RLS, drop `org_storage_addons`, drop `storage_packages`
    - _Requirements: 1.1–1.6_

- [x] 2. Create SQLAlchemy models
  - [x] 2.1 Add `StoragePackage` model to `app/modules/admin/models.py`
    - Follow existing model patterns (UUID PK, server_default gen_random_uuid(), DateTime with timezone)
    - All columns matching migration from Task 1.1
    - Add relationship: `org_storage_addons: Mapped[list[OrgStorageAddon]] = relationship(back_populates="storage_package")`
    - _Requirements: 1.1, 1.2_

  - [x] 2.2 Add `OrgStorageAddon` model to `app/modules/admin/models.py`
    - UUID PK, ForeignKey to `organisations.id` and `storage_packages.id` (nullable)
    - `UniqueConstraint("org_id", name="uq_org_storage_addons_org_id")` in `__table_args__`
    - Add relationships: `storage_package: Mapped[StoragePackage | None]` (back_populates), `organisation: Mapped[Organisation]`
    - Add `organisation_storage_addon` relationship on `Organisation` model (uselist=False since unique on org_id)
    - _Requirements: 1.3–1.5_

- [x] 3. Create Pydantic schemas
  - [x] 3.1 Add storage package schemas to `app/modules/admin/schemas.py`
    - `StoragePackageCreateRequest`: name (str, 1–100), storage_gb (int, > 0), price_nzd_per_month (float, >= 0), description (str|None, max 255), sort_order (int, default 0)
    - `StoragePackageUpdateRequest`: all fields optional
    - `StoragePackageResponse`: all fields including id, is_active, created_at, updated_at
    - `StoragePackageListResponse`: packages list + total count
    - _Requirements: 2.1–2.5_

  - [x] 3.2 Add storage add-on schemas to `app/modules/billing/schemas.py`
    - `StorageAddonPurchaseRequest`: package_id (str|None), custom_gb (int|None, > 0) — validator: exactly one must be provided
    - `StorageAddonResizeRequest`: package_id (str|None), custom_gb (int|None, > 0) — same validator
    - `StorageAddonResponse`: id, package_name (str|None), quantity_gb, price_nzd_per_month, is_custom, purchased_at
    - `StorageAddonStatusResponse`: current_addon (StorageAddonResponse|None), available_packages (list), fallback_price_per_gb_nzd (float), base_quota_gb (int), total_quota_gb (int), storage_used_gb (float)
    - _Requirements: 4.1–4.5, 5.1–5.2_

- [x] 4. Implement storage package CRUD service functions
  - [x] 4.1 Add to `app/modules/admin/service.py`:
    - `list_storage_packages(db, include_inactive)` → list of dicts
    - `create_storage_package(db, *, name, storage_gb, price_nzd_per_month, description, sort_order, created_by, ip_address)` → dict
    - `update_storage_package(db, package_id, *, updated_by, ip_address, **fields)` → dict
    - `deactivate_storage_package(db, package_id, *, deactivated_by, ip_address)` → dict
    - All functions write audit log entries
    - Deactivate checks for active org references before hard-deleting (always soft-delete)
    - _Requirements: 2.1–2.6, 7.1_

- [x] 5. Implement storage add-on service functions
  - [x] 5.1 Add to `app/modules/storage/service.py` (or `app/modules/billing/service.py` — new file if needed):
    - `get_storage_addon_status(db, org_id)` → dict with current addon, available packages, fallback price, quotas
    - `purchase_storage_addon_v2(db, org_id, *, package_id=None, custom_gb=None, user_id, ip_address)` → dict
      - Validates org has no existing add-on (409 if exists)
      - If package_id: loads package, validates active, creates addon record
      - If custom_gb: uses fallback price_per_gb_nzd, creates addon with is_custom=True
      - Updates org.storage_quota_gb += quantity_gb
      - Writes audit log
    - `resize_storage_addon(db, org_id, *, package_id=None, custom_gb=None, user_id, ip_address)` → dict
      - Validates org has existing add-on (404 if not)
      - Calculates new quantity, validates usage doesn't exceed new total on downgrade
      - Updates addon record and org.storage_quota_gb
      - Writes audit log with before/after
    - `remove_storage_addon(db, org_id, *, user_id, ip_address)` → dict
      - Validates usage doesn't exceed base quota
      - Deletes addon record, reduces org.storage_quota_gb
      - Writes audit log
    - _Requirements: 4.1–4.6, 5.1–5.7, 7.2_

- [x] 6. Add admin API endpoints for storage packages
  - [x] 6.1 Add to `app/modules/admin/router.py`:
    - `GET /admin/storage-packages` — list packages, query param `include_inactive`
    - `POST /admin/storage-packages` — create package, requires `global_admin` role
    - `PUT /admin/storage-packages/{package_id}` — update package
    - `DELETE /admin/storage-packages/{package_id}` — soft-delete (set is_active=false)
    - All endpoints require `global_admin` role
    - _Requirements: 2.1–2.6_

- [x] 7. Add org billing API endpoints for storage add-on management
  - [x] 7.1 Add to `app/modules/billing/router.py`:
    - `GET /billing/storage-addon` — returns current addon status + available packages
    - `POST /billing/storage-addon` — purchase new addon (package or custom)
    - `PUT /billing/storage-addon` — resize existing addon
    - `DELETE /billing/storage-addon` — remove addon
    - All endpoints require `org_admin` role
    - _Requirements: 4.1–4.7, 5.1–5.7_

- [x] 8. Update billing dashboard to include storage add-on data
  - [x] 8.1 Add fields to `BillingDashboardResponse` in `app/modules/billing/schemas.py`:
    - `storage_addon_gb: int | None` — current add-on GB (null if no add-on)
    - `storage_addon_price_nzd: float | None` — add-on monthly price
    - `storage_addon_package_name: str | None` — package name (null for custom)
  - [x] 8.2 Update `get_billing_dashboard` in `app/modules/billing/router.py`:
    - Query `org_storage_addons` for the org
    - If found, join with `storage_packages` for the name
    - Include add-on charge in estimated total
    - Replace the old `storage_addon_charge_nzd` calculation (which was based on extra GB beyond plan) with the actual add-on price
    - _Requirements: 6.1–6.4_

- [x] 9. Build admin Storage tab in SubscriptionPlans.tsx
  - [x] 9.1 Add `'storage'` to `activeMainTab` union type
  - [x] 9.2 Add "Storage" tab button in the tab bar
  - [x] 9.3 Create `StoragePackagesContent` component:
    - State: packages list, loading, error, form modal open, edit package
    - Fetch from `GET /admin/storage-packages?include_inactive=<showDeactivated>`
    - DataTable columns: Name, Storage (GB), Price/mo (NZD), Description, Sort Order, Status, Actions
    - "Create package" button → opens modal
    - Edit button per row → opens modal with pre-filled data
    - Deactivate/Reactivate button per row
    - "Show deactivated" checkbox
  - [x] 9.4 Create `StoragePackageFormModal` component:
    - Fields: name, storage_gb, price_nzd_per_month, description, sort_order
    - Validation: name required, storage_gb > 0, price >= 0
    - POST for create, PUT for edit
    - Toast on success/error
  - [x] 9.5 Move the existing `GlobalStoragePricing` card into the Storage tab (above the packages table) instead of the Plans tab
    - _Requirements: 3.1–3.6_

- [x] 10. Update Billing.tsx storage section for org users
  - [x] 10.1 Replace disabled "Buy more storage" button with functional "Manage storage" button
  - [x] 10.2 Create `StorageManageModal` component:
    - Fetches from `GET /billing/storage-addon` on open
    - If no active add-on: shows package selection cards + custom GB input → purchase flow
    - If active add-on: shows current add-on details + resize options → resize flow
    - Package cards: name, GB, price/mo, select button
    - Custom option: GB input field, shows calculated price using fallback rate
    - Confirmation step before purchase/resize
    - "Remove add-on" option when active add-on exists (with usage validation warning)
  - [x] 10.3 Update `StorageUsage` component:
    - Show total quota breakdown: "X GB (plan) + Y GB (add-on)" when add-on exists
    - Show add-on package name and monthly price
  - [x] 10.4 Update `NextBillEstimate` component:
    - Add storage add-on as separate line item: "Storage add-on (10 GB): $4.00"
    - Use actual add-on price instead of calculated storage_addon_charge
    - _Requirements: 4.1–4.7, 5.1–5.7, 6.1–6.4_

- [x] 11. Run migration on local containers
  - [x] 11.1 Run `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
  - [x] 11.2 Verify tables created: `storage_packages`, `org_storage_addons`
  - [x] 11.3 Verify RLS enabled on `org_storage_addons`

- [x] 12. End-to-end verification
  - [x] 12.1 As Global Admin: create 3–4 storage packages (5 GB/$2.50, 10 GB/$4, 25 GB/$8, 50 GB/$12)
  - [x] 12.2 As Global Admin: verify packages appear in Storage tab, edit one, deactivate one
  - [x] 12.3 As Org Admin: open Billing → Manage storage → verify packages shown
  - [x] 12.4 As Org Admin: purchase a 10 GB package → verify quota increased, add-on shown in billing
  - [x] 12.5 As Org Admin: resize to 25 GB → verify quota updated, price updated
  - [x] 12.6 As Org Admin: try custom 15 GB → verify fallback pricing used
  - [x] 12.7 As Org Admin: remove add-on → verify quota reverts to plan base
  - [x] 12.8 Verify billing dashboard shows add-on in next bill estimate
