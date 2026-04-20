# Implementation Plan: Organisation Detail Dashboard

## Overview

This plan implements a single-page Organisation Detail Dashboard for Global Admins, accessed by clicking an organisation name on the existing Organisations list page. The backend adds one new endpoint (`GET /admin/organisations/{org_id}/detail`) with a service function that aggregates data from 10+ existing tables. The frontend adds one new page (`OrganisationDetail.tsx`) with sectioned card layout, health indicators, and quick actions that reuse existing modals. No new database tables or migrations are needed.

The implementation language is Python (backend) and TypeScript/React (frontend).

## Tasks

- [x] 1. Add backend Pydantic schemas for organisation detail response
  - [x] 1.1 Create all Pydantic response schemas in `app/modules/admin/schemas.py`
    - Add `OrgDetailPaymentMethod`, `OrgDetailCoupon`, `OrgDetailStorageAddon`, `OrgDetailBilling`, `OrgDetailUsage`, `OrgDetailUser`, `OrgDetailUserSection`, `OrgDetailLoginAttempt`, `OrgDetailAdminAction`, `OrgDetailSecurity`, `OrgDetailHealth`, `OrgDetailOverview`, and `OrgDetailResponse` models
    - All count fields must use `int` with default `0`; all optional fields use `| None = None`
    - Payment method schema must contain ONLY `brand`, `last4`, `exp_month`, `exp_year` — no `stripe_payment_method_id`
    - _Requirements: 9.1, 9.3, 9.4, 9.5, 3.3, 3.4, 8.2, 8.3_
  - [x] 1.2 Write property tests for schema validation (Properties 1, 2, 6)
    - **Property 1: Payment method masking invariant** — serialised `OrgDetailResponse` with payment_method present contains only `brand`, `last4`, `exp_month`, `exp_year` keys; `last4` is exactly 4 chars; no forbidden keys (`stripe_payment_method_id`, `cvv`, `card_number`, `full_number`) appear in JSON
    - **Validates: Requirements 3.3, 3.4, 8.2, 9.3**
    - **Property 2: Aggregate counts are non-negative integers** — all count fields in generated `OrgDetailResponse` dicts are non-negative integers
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 5.1, 6.7**
    - **Property 6: No sensitive data leakage in response** — serialised JSON of `OrgDetailResponse` does not contain keys `password_hash`, `secret_encrypted`, `stripe_payment_method_id`, `before_value`, `after_value`, `authentication_token`, `refresh_token`, `line_items`, `customer_address`, `customer_phone`, `invoice_content`
    - **Validates: Requirements 4.10, 6.5, 8.3, 9.4, 9.5**

- [x] 2. Implement `compute_health_indicators` pure function
  - [x] 2.1 Add `compute_health_indicators` function in `app/modules/admin/service.py`
    - Accept keyword arguments: `status`, `receipts_failed_90d`, `storage_used_bytes`, `storage_quota_gb`, `active_user_count`, `seat_limit`, `mfa_enrolled_count`, `total_users`
    - Return dict with `billing_ok`, `storage_ok`, `storage_warning`, `seats_ok`, `mfa_ok`, `status_ok` following the derivation rules in the design
    - `billing_ok = receipts_failed_90d == 0`
    - `storage_ok = storage_ratio <= 0.9` where `storage_ratio = storage_used_bytes / max(storage_quota_gb * 1_073_741_824, 1)`
    - `storage_warning = 0.8 < storage_ratio <= 0.9`
    - `seats_ok = active_user_count < seat_limit`
    - `mfa_ok = mfa_enrolled_count / max(total_users, 1) >= 0.5`
    - `status_ok = status not in ("suspended", "payment_pending")`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_
  - [x] 2.2 Write property test for health indicator derivation (Property 4)
    - **Property 4: Health indicator derivation consistency** — for random metric inputs, each health flag matches its derivation formula exactly
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6**

- [x] 3. Implement `get_org_detail` service function
  - [x] 3.1 Add `get_org_detail` async function in `app/modules/admin/service.py`
    - Accept `db: AsyncSession`, `org_id: uuid.UUID`, `admin_user_id: uuid.UUID`, `ip_address: str | None`, `device_info: str | None`
    - Query organisation with JOIN on `subscription_plans` and LEFT JOIN on `trade_categories`
    - Return `None` if org not found
    - Query default payment method from `org_payment_methods` (brand, last4, exp_month, exp_year only — never select `stripe_payment_method_id`)
    - Query aggregate counts using raw SQL `text()` with bound params (invoices, quotes, customers, org_vehicles) — same pattern as existing `list_organisations`
    - Query users with MFA enrollment status via correlated subquery on `user_mfa_methods` (verified=true)
    - Query billing receipts from last 90 days partitioned by status (paid vs failed), get most recent failure date
    - Query active organisation coupons with coupon details (JOIN `coupons` WHERE `is_expired=false`)
    - Query storage add-on from `org_storage_addons`
    - Query `audit_log` for login attempts (action IN login_success/login_failed, last 30 days, limit 50, ORDER BY created_at DESC)
    - Query `audit_log` for admin actions on this org (action IN org_suspended/org_reinstated/org_plan_changed/org_coupon_applied/org_deleted/org_detail_viewed, last 90 days, limit 50)
    - Insert audit log entry: `action="org_detail_viewed"`, `entity_type="organisation"`, `entity_id=org_id`
    - Call `compute_health_indicators` with the aggregated metrics
    - Return structured dict matching `OrgDetailResponse` schema
    - Use `try/except` around each sub-query section with logging so a failure in one section doesn't block others
    - _Requirements: 9.1, 9.3, 9.4, 9.5, 8.1, 8.2, 8.3, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.10, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4, 6.5, 6.7_
  - [x] 3.2 Write property test for audit log creation (Property 5)
    - **Property 5: Audit log entry creation on access** — for random valid UUIDs, calling `get_org_detail` with a mocked DB session adds exactly one `AuditLog` record with `action="org_detail_viewed"`, `entity_type="organisation"`, `entity_id=org_id`
    - **Validates: Requirements 8.1, 9.7**
  - [x] 3.3 Write property tests for bounded lists (Properties 7, 8)
    - **Property 7: Login attempts bounded by time window and count limit** — all entries in `security.login_attempts` have timestamps within last 30 days and list length <= 50
    - **Validates: Requirements 6.1, 6.2**
    - **Property 8: Admin actions bounded by time window and count limit** — all entries in `security.admin_actions` have timestamps within last 90 days and list length <= 50
    - **Validates: Requirements 6.3, 6.4**

- [x] 4. Add the API endpoint and wire to service
  - [x] 4.1 Add `GET /organisations/{org_id}/detail` endpoint in `app/modules/admin/router.py`
    - Decorate with `@router.get("/organisations/{org_id}/detail", response_model=OrgDetailResponse)`
    - Depend on `get_db_session`, `require_role("global_admin")`, extract `request.client.host` and `user-agent`
    - Call `get_org_detail` service function
    - Return 404 if service returns `None`
    - _Requirements: 9.1, 9.2, 9.6, 9.7, 8.1, 8.4_
  - [x] 4.2 Write unit tests for the endpoint
    - Test 404 for non-existent org UUID
    - Test 403 for non-global-admin user
    - Test 200 with correct response shape for valid org
    - Test payment method masking (no `stripe_payment_method_id` in response)
    - Test empty org returns zero counts
    - Test audit log entry created on access
    - _Requirements: 9.1, 9.2, 9.3, 9.6, 8.1, 8.4_

- [x] 5. Checkpoint — Backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Create OrganisationDetail page with all sections
  - [x] 6.1 Create `OrganisationDetail.tsx` at `frontend/src/pages/admin/OrganisationDetail.tsx`
    - Use the large-file-generation steering pattern (Python script) if the file exceeds ~50 lines
    - Define all TypeScript interfaces inline: `OrgDetailPaymentMethod`, `OrgDetailCoupon`, `OrgDetailStorageAddon`, `OrgDetailBilling`, `OrgDetailUsage`, `OrgDetailUser`, `OrgDetailUserSection`, `OrgDetailLoginAttempt`, `OrgDetailAdminAction`, `OrgDetailSecurity`, `OrgDetailHealth`, `OrgDetailOverview`, `OrgDetailData`
    - Implement data fetching with `useEffect` + `AbortController` + `apiClient.get<OrgDetailData>` following safe-api-consumption patterns
    - Handle loading state (Spinner), 404 error (AlertBanner + back link), and generic error (AlertBanner + retry button)
    - Implement breadcrumb: "Organisations > {org.name}" with clickable "Organisations" link back to `/admin/organisations`
    - Implement back button navigating to `/admin/organisations`
    - Use `max-w-7xl mx-auto` container, `space-y-6` between sections, `p-4`/`p-6` within cards
    - Use responsive grid: single column below 1024px, two-column grid on wider screens
    - All text content uses `truncate` class with `title` attribute for tooltip on hover
    - All numeric values right-aligned
    - All tables horizontally scrollable within their card (`overflow-x-auto`)
    - Use existing project UI components only: Badge, Button, Spinner, AlertBanner, DataTable, Modal, Input, Select, Toast
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9_
  - [x] 6.2 Implement `HealthIndicatorRow` local component
    - Compact summary row at top of page with icon + label + colour for each health flag
    - `billing_ok`: green check / red warning; `storage_ok`/`storage_warning`: green/amber/red; `seats_ok`: green/amber; `mfa_ok`: green/amber; `status_ok`: green/red
    - Use `?.` on all health data access with sensible defaults
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 12.11_
  - [x] 6.3 Implement `OverviewCard` local component
    - Display org name, status badge (colour-coded: active=green, trial=blue, payment_pending=amber, suspended=red, deleted=neutral), plan name
    - Display signup date formatted in org locale, business type, trade category name
    - Display billing interval, trial end date (if present), timezone, locale
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_
  - [x] 6.4 Implement `BillingCard` local component
    - Display plan name, monthly price, billing interval, next billing date
    - Display payment method (brand + last4 + expiry) or "No payment method" with warning indicator
    - Display active coupons list (code, discount type, value, remaining months) or "No active coupons" empty state
    - Display storage add-on details or empty state
    - Display billing receipt summary (success/failed counts for last 90 days), most recent failure date if any
    - Use `?.` and `?? []` / `?? 0` on all data access
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 3.7, 3.8, 3.9, 12.12_
  - [x] 6.5 Implement `UsageMetricsCard` local component
    - Display invoice, quote, customer, vehicle counts
    - Display storage progress bar with numeric label (e.g. "2.5 / 10 GB"), amber at >80%, red at >95%
    - Display Carjam lookups used vs included allowance
    - Display SMS sent vs included quota
    - All progress bars show both visual bar and numeric label
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 12.10_
  - [x] 6.6 Implement `UserManagementCard` local component
    - Display active users vs seat limit (e.g. "3 / 5 seats") with warning indicator when at limit
    - Display user table: name, email, role (display name), last login date, MFA status (Enabled/Not enrolled)
    - Highlight users with no login in last 90 days
    - Table is horizontally scrollable within card
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  - [x] 6.7 Implement `SecurityAuditCard` local component
    - Display login attempts table: user email, success/failure badge, IP address, device info, timestamp
    - Display admin actions table: action type, admin email, IP address, timestamp
    - Display MFA enrollment summary (e.g. "3 of 5 users have MFA enabled")
    - Display failed payments count for last 90 days
    - Show empty state messages when lists are empty
    - Never display `before_value` or `after_value` from audit log
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 12.12_
  - [x] 6.8 Implement `QuickActionsBar` local component
    - Show "Suspend" button when status is "active" or "trial"
    - Show "Reinstate" button when status is "suspended"
    - Show "Change Plan" and "Apply Coupon" buttons always
    - Show "Send Notification" button always
    - Each button opens the corresponding modal
    - _Requirements: 11.1, 11.2, 11.3_
  - [x] 6.9 Implement `SendNotificationModal` local component
    - Form with title, message (textarea), severity (info/warning/critical select), type (maintenance/alert/feature/info select)
    - Pre-fill target org (display org name, not editable)
    - On submit: POST to platform notification endpoint with `target_type="specific_orgs"`, `target_value=orgId`
    - On success: Toast success, close modal
    - On failure: Toast error, keep modal open
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_
  - [x] 6.10 Wire quick action modals (Suspend, Delete, PlanChange, ApplyCoupon)
    - Import and reuse existing modal components from the Organisations list page
    - Pass current org data as props
    - On action completion: re-fetch organisation detail data to refresh the page
    - _Requirements: 11.4, 11.5_

- [x] 7. Register route and add navigation link
  - [x] 7.1 Register the detail page route in `frontend/src/App.tsx`
    - Import `OrganisationDetail` component
    - Add `<Route path="organisations/:orgId" element={<SafePage name="admin-org-detail"><OrganisationDetail /></SafePage>} />` inside the admin route group
    - Place BEFORE the existing `organisations` route so React Router matches the more specific path first
    - _Requirements: 1.1, 1.6, 8.4, 8.5_
  - [x] 7.2 Make organisation names clickable on the Organisations list page
    - In `frontend/src/pages/admin/Organisations.tsx`, update the name column in the DataTable to render a `<Link to={\`/admin/organisations/\${org.id}\`}>` with blue hover styling
    - _Requirements: 1.1_

- [x] 8. Checkpoint — Frontend compiles and renders
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Write E2E test script
  - [x] 9.1 Create `scripts/test_org_detail_dashboard_e2e.py` following the feature-testing-workflow steering pattern
    - Login as global_admin
    - Call `GET /admin/organisations/{org_id}/detail` and verify 200 response with correct shape
    - Verify payment method masking (no `stripe_payment_method_id` in response JSON)
    - Verify aggregate counts are non-negative integers
    - Verify user data has no `password_hash` field
    - Verify admin actions have no `before_value`/`after_value` fields
    - Verify audit log entry created (query DB directly via asyncpg)
    - Test 404 for non-existent org UUID
    - Test 403 for non-admin user (login as demo user)
    - Test OWASP A1: access org detail without token → 401/403
    - Test OWASP A3: SQL injection in org_id path param
    - Cleanup test data
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_
  - [x] 9.2 Write property test for user section seat count consistency (Property 3)
    - **Property 3: User section seat count consistency** — `active_count` equals the count of users where `is_active` is true, and `active_count <= seat_limit`
    - **Validates: Requirements 5.1, 5.6**

- [x] 10. Final checkpoint — Full integration verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The backend uses Python/FastAPI; the frontend uses TypeScript/React
- All frontend API calls must follow the safe-api-consumption steering patterns (optional chaining, nullish coalescing, AbortController cleanup, typed generics)
- The large-file-generation steering rule applies to `OrganisationDetail.tsx` — use a Python script to generate the file if it exceeds ~50 lines
- No new database tables or migrations are needed — all data comes from existing models
- Property tests use Hypothesis with `@settings(max_examples=100)` and are placed in `tests/property/test_org_detail_properties.py`
- The E2E test script follows the feature-testing-workflow steering pattern with ok/fail helpers
- Existing modals (Suspend, Delete, PlanChange, ApplyCoupon) are reused per the no-shortcut-implementations rule
- Checkpoints ensure incremental validation at backend and frontend milestones
