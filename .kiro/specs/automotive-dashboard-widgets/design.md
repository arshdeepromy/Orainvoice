# Design Document: Automotive Dashboard Widgets

## Overview

This design transforms the existing `OrgAdminDashboard` into a widget-based dashboard for automotive trade organisations. The dashboard retains the existing KPI cards and branch metrics, and adds 9 new widgets arranged in a draggable CSS grid. The widget grid is trade-family gated (`automotive-transport` only) and individual widgets are module-gated where appropriate.

**Key design decisions:**

1. **@dnd-kit/core for drag-and-drop** — lightweight, accessible, React-first DnD library. The HTML5 Drag API has poor mobile support and accessibility gaps. `@dnd-kit/core` + `@dnd-kit/sortable` adds ~12 KB gzipped and provides keyboard navigation, screen reader announcements, and touch support out of the box.

2. **recharts for the cash flow chart** — already the most common lightweight React charting library. It's built on SVG, tree-shakeable, and integrates naturally with React state. At ~45 KB gzipped for a bar chart, it's significantly lighter than Chart.js or D3.

3. **New backend dashboard endpoints** — rather than having the frontend call 9 separate existing endpoints and stitch data together, we create a dedicated `GET /api/v1/dashboard/widgets` endpoint that returns all widget data in a single request. Individual widget endpoints are also available for refresh-on-demand. This reduces initial page load from 9+ round trips to 1.

4. **localStorage for layout persistence** — layout preferences (widget order) are stored in `localStorage` keyed by user ID. This avoids a backend migration for a UI preference and works offline. The key format is `dashboard_layout_{userId}`.

5. **No new database tables for reminders** — WOF/service reminder dismissals and configuration use a new `dashboard_reminder_dismissals` table and a `dashboard_reminder_config` table. These are lightweight and scoped to the dashboard feature.

## Architecture

```mermaid
graph TD
    subgraph Frontend
        D[Dashboard.tsx] --> OAD[OrgAdminDashboard.tsx]
        OAD -->|isAutomotive| WG[WidgetGrid]
        OAD -->|!isAutomotive| KPI[Existing KPI Cards]
        WG --> DnD[@dnd-kit/sortable]
        WG --> W1[RecentCustomersWidget]
        WG --> W2[TodaysBookingsWidget]
        WG --> W3[PublicHolidaysWidget]
        WG --> W4[InventoryOverviewWidget]
        WG --> W5[CashFlowChartWidget]
        WG --> W6[RecentClaimsWidget]
        WG --> W7[ActiveStaffWidget]
        WG --> W8[ExpiryRemindersWidget]
        WG --> W9[ReminderConfigWidget]
    end

    subgraph Backend
        DR[dashboard_router.py] --> DS[dashboard_service.py]
        DS --> DB[(PostgreSQL)]
        DS -->|invoices + customers| RecentCust
        DS -->|bookings| TodayBook
        DS -->|public_holidays| Holidays
        DS -->|products| Inventory
        DS -->|invoices + expenses| CashFlow
        DS -->|customer_claims| Claims
        DS -->|time_entries / users| Staff
        DS -->|vehicles + customer_vehicles| Expiry
        DS -->|dashboard_reminder_config| Config
    end

    WG -->|GET /dashboard/widgets| DR
    W8 -->|POST /dashboard/reminders/dismiss| DR
    W9 -->|GET/PUT /dashboard/reminder-config| DR
```

### Data Flow

1. `OrgAdminDashboard` checks `isAutomotive` from `useTenant().tradeFamily`
2. If automotive, renders `<WidgetGrid>` below the existing KPI cards
3. `WidgetGrid` loads layout from `localStorage`, determines visible widgets (filtering by module availability via `useModules().isEnabled()`)
4. A single `GET /api/v1/dashboard/widgets` call fetches all widget data, passing `branch_id` from the branch context header
5. Each widget receives its data slice as props and renders independently
6. Drag-and-drop reordering updates `localStorage` immediately
7. Widget-specific actions (dismiss reminder, update config) use dedicated endpoints

## Components and Interfaces

### Frontend Components

#### WidgetGrid (`frontend/src/pages/dashboard/widgets/WidgetGrid.tsx`)

The main container that manages widget layout, ordering, and drag-and-drop.

```typescript
interface WidgetGridProps {
  userId: string
  branchId: string | null
}

interface WidgetDefinition {
  id: string                    // e.g. 'recent-customers', 'todays-bookings'
  title: string
  icon: React.ComponentType     // Heroicon component
  module?: string               // module slug for gating (undefined = always visible)
  component: React.ComponentType<WidgetComponentProps>
  defaultOrder: number
}

interface WidgetComponentProps {
  data: unknown                 // widget-specific data from API
  isLoading: boolean
  error: string | null
  branchId: string | null
}
```

**Responsibilities:**
- Reads/writes layout order from `localStorage` key `dashboard_layout_{userId}`
- Filters widgets by module availability using `useModules().isEnabled()`
- Wraps each widget in a `<SortableItem>` from `@dnd-kit/sortable`
- Applies CSS grid: `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4`
- Fetches all widget data via `useDashboardWidgets()` hook

#### WidgetCard (`frontend/src/pages/dashboard/widgets/WidgetCard.tsx`)

Presentational wrapper for each widget providing consistent card styling.

```typescript
interface WidgetCardProps {
  title: string
  icon: React.ComponentType<{ className?: string }>
  actionLink?: { label: string; to: string }
  children: React.ReactNode
  isLoading?: boolean
  error?: string | null
}
```

Renders: `rounded-lg border border-gray-200 bg-white` card with header (icon + title + optional action link), body content, loading spinner overlay, and error state.

#### Individual Widget Components

Each widget lives in `frontend/src/pages/dashboard/widgets/` and receives typed data:

| Widget | File | Data Type |
|--------|------|-----------|
| Recent Customers | `RecentCustomersWidget.tsx` | `RecentCustomer[]` |
| Today's Bookings | `TodaysBookingsWidget.tsx` | `TodayBooking[]` |
| Public Holidays | `PublicHolidaysWidget.tsx` | `PublicHoliday[]` |
| Inventory Overview | `InventoryOverviewWidget.tsx` | `InventoryCategory[]` |
| Cash Flow Chart | `CashFlowChartWidget.tsx` | `CashFlowMonth[]` |
| Recent Claims | `RecentClaimsWidget.tsx` | `RecentClaim[]` |
| Active Staff | `ActiveStaffWidget.tsx` | `ActiveStaffMember[]` |
| Expiry Reminders | `ExpiryRemindersWidget.tsx` | `ExpiryReminder[]` |
| Reminder Config | `ReminderConfigWidget.tsx` | `ReminderConfig` |

#### useDashboardWidgets Hook (`frontend/src/pages/dashboard/widgets/useDashboardWidgets.ts`)

```typescript
interface DashboardWidgetData {
  recent_customers: RecentCustomer[]
  todays_bookings: TodayBooking[]
  public_holidays: PublicHoliday[]
  inventory_overview: InventoryCategory[]
  cash_flow: CashFlowMonth[]
  recent_claims: RecentClaim[]
  active_staff: ActiveStaffMember[]
  expiry_reminders: ExpiryReminder[]
  reminder_config: ReminderConfig
}

function useDashboardWidgets(branchId: string | null): {
  data: DashboardWidgetData | null
  isLoading: boolean
  error: string | null
  refetch: () => void
}
```

Uses `AbortController` cleanup, typed generics on `apiClient.get()`, and `?.` / `?? []` on all response fields per safe API consumption rules.

### Backend Endpoints

All new endpoints are added to the existing `app/modules/organisations/dashboard_router.py`.

#### `GET /api/v1/dashboard/widgets`

Returns all widget data in a single response. Branch-scoped via `X-Branch-Id` header.

```python
@router.get("/widgets", summary="Get all dashboard widget data")
async def get_dashboard_widgets(request: Request, db: AsyncSession = Depends(get_db_session)):
    # Returns DashboardWidgetsResponse
```

**Response shape:**
```json
{
  "recent_customers": { "items": [...], "total": 10 },
  "todays_bookings": { "items": [...], "total": 5 },
  "public_holidays": { "items": [...], "total": 5 },
  "inventory_overview": { "items": [...], "total": 4 },
  "cash_flow": { "items": [...], "total": 6 },
  "recent_claims": { "items": [...], "total": 10 },
  "active_staff": { "items": [...], "total": 3 },
  "expiry_reminders": { "items": [...], "total": 8 },
  "reminder_config": { "wof_days": 30, "service_days": 30 }
}
```

#### `POST /api/v1/dashboard/reminders/{reminder_type}/dismiss`

Dismisses or marks a reminder as sent.

```python
@router.post("/reminders/{reminder_type}/dismiss", summary="Dismiss or mark reminder sent")
async def dismiss_reminder(
    reminder_type: str,  # "wof" or "service"
    body: ReminderDismissRequest,  # { vehicle_id, action: "dismiss" | "mark_sent" }
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
```

#### `GET /api/v1/dashboard/reminder-config`

Returns the current reminder threshold configuration.

```python
@router.get("/reminder-config", summary="Get reminder thresholds")
async def get_reminder_config(request: Request, db: AsyncSession = Depends(get_db_session)):
    # Returns { wof_days: int, service_days: int }
```

#### `PUT /api/v1/dashboard/reminder-config`

Updates reminder threshold configuration.

```python
@router.put("/reminder-config", summary="Update reminder thresholds")
async def update_reminder_config(
    body: ReminderConfigUpdate,  # { wof_days: int, service_days: int }
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
```

## Data Models

### New Database Tables

#### `dashboard_reminder_dismissals`

Tracks which WOF/service expiry reminders have been dismissed or marked as sent.

```python
class DashboardReminderDismissal(Base):
    __tablename__ = "dashboard_reminder_dismissals"

    id: Mapped[uuid.UUID]           # PK
    org_id: Mapped[uuid.UUID]       # FK -> organisations.id
    vehicle_id: Mapped[uuid.UUID]   # FK -> org_vehicles.id or global_vehicles.id
    reminder_type: Mapped[str]      # "wof" or "service"
    action: Mapped[str]             # "dismissed" or "reminder_sent"
    expiry_date: Mapped[date]       # the expiry date this dismissal applies to
    dismissed_by: Mapped[uuid.UUID] # FK -> users.id
    dismissed_at: Mapped[datetime]  # timestamp
```

**Unique constraint:** `(org_id, vehicle_id, reminder_type, expiry_date)` — one dismissal per vehicle per expiry type per expiry date.

#### `dashboard_reminder_config`

Stores per-org reminder threshold configuration.

```python
class DashboardReminderConfig(Base):
    __tablename__ = "dashboard_reminder_config"

    id: Mapped[uuid.UUID]           # PK
    org_id: Mapped[uuid.UUID]       # FK -> organisations.id, UNIQUE
    wof_days: Mapped[int]           # default 30, CHECK 1-365
    service_days: Mapped[int]       # default 30, CHECK 1-365
    updated_by: Mapped[uuid.UUID]   # FK -> users.id
    updated_at: Mapped[datetime]    # timestamp
```

### Pydantic Schemas (Backend)

```python
# --- Widget data item schemas ---

class RecentCustomerItem(BaseModel):
    customer_id: UUID
    customer_name: str
    invoice_date: str          # ISO date
    vehicle_rego: str | None

class TodayBookingItem(BaseModel):
    booking_id: UUID
    scheduled_time: str        # ISO datetime
    customer_name: str
    vehicle_rego: str | None

class PublicHolidayItem(BaseModel):
    name: str
    holiday_date: str          # ISO date

class InventoryCategoryItem(BaseModel):
    category: str              # "tyres", "parts", "fluids", "other"
    total_count: int
    low_stock_count: int

class CashFlowMonthItem(BaseModel):
    month: str                 # "2025-01", "2025-02", etc.
    month_label: str           # "Jan 2025", "Feb 2025", etc.
    revenue: float
    expenses: float

class RecentClaimItem(BaseModel):
    claim_id: UUID
    reference: str             # claim reference number
    customer_name: str
    claim_date: str            # ISO date
    status: str                # "open", "investigating", "approved", "rejected", "resolved"

class ActiveStaffItem(BaseModel):
    staff_id: UUID
    name: str
    clock_in_time: str         # ISO datetime

class ExpiryReminderItem(BaseModel):
    vehicle_id: UUID
    vehicle_rego: str
    vehicle_make: str | None
    vehicle_model: str | None
    expiry_type: str           # "wof" or "service"
    expiry_date: str           # ISO date
    customer_name: str
    customer_id: UUID

class ReminderConfigResponse(BaseModel):
    wof_days: int = 30
    service_days: int = 30

# --- Aggregated response ---

class WidgetDataSection(BaseModel, Generic[T]):
    items: list[T]
    total: int

class DashboardWidgetsResponse(BaseModel):
    recent_customers: WidgetDataSection[RecentCustomerItem]
    todays_bookings: WidgetDataSection[TodayBookingItem]
    public_holidays: WidgetDataSection[PublicHolidayItem]
    inventory_overview: WidgetDataSection[InventoryCategoryItem]
    cash_flow: WidgetDataSection[CashFlowMonthItem]
    recent_claims: WidgetDataSection[RecentClaimItem]
    active_staff: WidgetDataSection[ActiveStaffItem]
    expiry_reminders: WidgetDataSection[ExpiryReminderItem]
    reminder_config: ReminderConfigResponse

# --- Request schemas ---

class ReminderDismissRequest(BaseModel):
    vehicle_id: UUID
    expiry_date: str           # ISO date
    action: str                # "dismiss" or "mark_sent"

class ReminderConfigUpdate(BaseModel):
    wof_days: int = Field(..., ge=1, le=365)
    service_days: int = Field(..., ge=1, le=365)
```

### TypeScript Types (Frontend)

```typescript
// frontend/src/pages/dashboard/widgets/types.ts

interface RecentCustomer {
  customer_id: string
  customer_name: string
  invoice_date: string
  vehicle_rego: string | null
}

interface TodayBooking {
  booking_id: string
  scheduled_time: string
  customer_name: string
  vehicle_rego: string | null
}

interface PublicHoliday {
  name: string
  holiday_date: string
}

interface InventoryCategory {
  category: string
  total_count: number
  low_stock_count: number
}

interface CashFlowMonth {
  month: string
  month_label: string
  revenue: number
  expenses: number
}

interface RecentClaim {
  claim_id: string
  reference: string
  customer_name: string
  claim_date: string
  status: 'open' | 'investigating' | 'approved' | 'rejected' | 'resolved'
}

interface ActiveStaffMember {
  staff_id: string
  name: string
  clock_in_time: string
}

interface ExpiryReminder {
  vehicle_id: string
  vehicle_rego: string
  vehicle_make: string | null
  vehicle_model: string | null
  expiry_type: 'wof' | 'service'
  expiry_date: string
  customer_name: string
  customer_id: string
}

interface ReminderConfig {
  wof_days: number
  service_days: number
}

interface WidgetDataSection<T> {
  items: T[]
  total: number
}

interface DashboardWidgetData {
  recent_customers: WidgetDataSection<RecentCustomer>
  todays_bookings: WidgetDataSection<TodayBooking>
  public_holidays: WidgetDataSection<PublicHoliday>
  inventory_overview: WidgetDataSection<InventoryCategory>
  cash_flow: WidgetDataSection<CashFlowMonth>
  recent_claims: WidgetDataSection<RecentClaim>
  active_staff: WidgetDataSection<ActiveStaffMember>
  expiry_reminders: WidgetDataSection<ExpiryReminder>
  reminder_config: ReminderConfig
}
```

### Backend Service Queries (Summary)

Each widget's data is fetched by a dedicated function in `dashboard_service.py`:

| Widget | Query Source | Key Logic |
|--------|-------------|-----------|
| Recent Customers | `invoices` JOIN `customers` | Last 10 invoices by `created_at DESC`, branch-scoped, extract `customer_name`, `vehicle_rego` |
| Today's Bookings | `bookings` | `start_time` between today 00:00 and 23:59, branch-scoped, ordered by `start_time ASC` |
| Public Holidays | `public_holidays` | `holiday_date >= today`, filtered by org's country (from org settings), limit 5, ordered by `holiday_date ASC` |
| Inventory Overview | `products` | Group by `category_name` (mapped to tyres/parts/fluids/other), count total and count where `stock_quantity <= low_stock_threshold` |
| Cash Flow | `invoices` + `expenses` | Group by month for last 6 months, sum `subtotal` for revenue, sum `amount` for expenses |
| Recent Claims | `customer_claims` JOIN `customers` | Last 10 by `created_at DESC`, branch-scoped |
| Active Staff | `time_entries` (v2) or `users` | Users with active (unclosed) time entries for today, branch-scoped |
| Expiry Reminders | `org_vehicles` + `global_vehicles` JOIN `customer_vehicles` JOIN `customers` | `wof_expiry` or `service_due_date` within threshold days, excluding dismissed, branch-scoped |
| Reminder Config | `dashboard_reminder_config` | Single row per org, defaults to 30/30 |


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Trade Family Derivation

*For any* `tradeFamily` value (including `null`), the `isAutomotive` boolean SHALL be `true` if and only if `(tradeFamily ?? 'automotive-transport') === 'automotive-transport'`. Specifically: `null` → `true`, `'automotive-transport'` → `true`, any other string → `false`.

**Validates: Requirements 1.1, 1.4**

### Property 2: Module Gating Determines Widget Visibility

*For any* combination of enabled/disabled module slugs (`inventory`, `claims`, `bookings`, `vehicles`), the set of visible widgets SHALL equal the union of: (a) the 4 ungated widgets (Recent Customers, Public Holidays, Cash Flow Chart, Active Staff) which are always visible, and (b) each module-gated widget whose corresponding module is enabled. No module-gated widget SHALL be visible when its module is disabled.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.7**

### Property 3: Layout Persistence Round-Trip

*For any* valid widget order array and user ID, saving the layout to `localStorage` and then reading it back SHALL produce an identical widget order array. `saveLayout(userId, order); loadLayout(userId) === order`.

**Validates: Requirements 3.2, 3.3**

### Property 4: Stale Widget Filtering Preserves Available Widget Order

*For any* saved widget order array and *any* set of currently available widget IDs, filtering the saved order to only include available widgets SHALL: (a) contain only IDs present in the available set, (b) preserve the relative order of those IDs from the saved array, and (c) append any new available widgets not in the saved order at the end.

**Validates: Requirements 3.5**

### Property 5: Recent List Endpoints Return Bounded Ordered Results

*For any* set of invoices (or claims), the recent customers (or recent claims) query SHALL return at most 10 items, and the items SHALL be ordered by date descending (most recent first). The returned customer names and dates SHALL correspond to actual records in the input set.

**Validates: Requirements 4.1, 9.1**

### Property 6: Today's Bookings Filter

*For any* set of bookings with various dates, the today's bookings query SHALL return only bookings whose `start_time` falls within the current calendar date, and SHALL return them sorted by `start_time` ascending.

**Validates: Requirements 5.1, 5.3**

### Property 7: Public Holidays Country and Date Filter

*For any* set of public holidays with various countries and dates, the public holidays query for a given country SHALL return only holidays where `country_code` matches the org's country AND `holiday_date >= today`, limited to 5 results, sorted by `holiday_date` ascending.

**Validates: Requirements 6.1, 6.3**

### Property 8: Inventory Category Grouping Correctness

*For any* set of products with categories and stock quantities, the inventory overview query SHALL produce category groups where: (a) `total_count` for each category equals the number of products in that category, and (b) `low_stock_count` equals the number of products where `stock_quantity <= low_stock_threshold`.

**Validates: Requirements 7.1, 7.2**

### Property 9: Cash Flow Monthly Aggregation

*For any* set of invoices and expenses over the last 6 months, the cash flow query SHALL produce exactly 6 monthly entries where: (a) `revenue` for each month equals the sum of invoice subtotals in that month, and (b) `expenses` for each month equals the sum of expense amounts in that month.

**Validates: Requirements 8.1**

### Property 10: Active Staff Returns Only Clocked-In Staff

*For any* set of time entries (some with `end_time` null, some completed), the active staff query SHALL return only staff members who have at least one time entry with `end_time IS NULL` for the current date.

**Validates: Requirements 10.1**

### Property 11: Expiry Reminders Exclude Dismissed and Filter by Threshold

*For any* set of vehicles with WOF/service expiry dates and *any* set of reminder dismissals, the expiry reminders query SHALL return only vehicles where: (a) the expiry date is within the configured threshold days from today, (b) the expiry date is in the future (not past), and (c) no matching dismissal record exists for that vehicle + expiry type + expiry date combination.

**Validates: Requirements 11.1, 11.8**

### Property 12: Reminder Config Validation Range

*For any* integer value, the reminder config validation SHALL accept the value if and only if it is between 1 and 365 inclusive. Values outside this range (0, negative, >365, non-integer) SHALL be rejected.

**Validates: Requirements 12.6**

### Property 13: Widget Error Isolation

*For any* single widget whose data fetch fails, the dashboard SHALL continue to render all other widgets normally. The failed widget SHALL display an error message within its card boundary without propagating the error to the parent grid or sibling widgets.

**Validates: Requirements 15.5**

## Error Handling

### Frontend Error Handling

| Scenario | Handling |
|----------|----------|
| `GET /dashboard/widgets` returns 500 | Show a top-level error banner within the widget grid area. Individual widgets show "Unable to load" state. Existing KPI cards above remain unaffected. |
| `GET /dashboard/widgets` returns partial data (some fields null) | Each widget independently checks its data slice with `?? []` fallback. Widgets with null data show empty state, not error state. |
| Individual widget action fails (dismiss reminder, save config) | Show inline error toast within the widget card. Do not affect other widgets. |
| `localStorage` read/write fails (private browsing, quota exceeded) | Catch the error silently. Fall back to default widget order. Log warning to console. |
| Network timeout | `AbortController` cancels in-flight requests on unmount. Retry button available in error state. |
| `useTenant()` or `useModules()` not yet loaded | Show loading spinner for the widget grid until both contexts are ready. |

### Backend Error Handling

| Scenario | Handling |
|----------|----------|
| Database query fails for one widget's data | Catch the exception, return `{ items: [], total: 0 }` for that widget section. Log the error server-side. Do not fail the entire `/dashboard/widgets` response. |
| Org has no country set (public holidays) | Default to "NZ" for the country filter. |
| No `dashboard_reminder_config` row exists | Return default `{ wof_days: 30, service_days: 30 }`. |
| Invalid `vehicle_id` in dismiss request | Return 404 with `{ detail: "Vehicle not found" }`. |
| Duplicate dismissal (already dismissed) | Idempotent — return 200 with existing dismissal. Do not create duplicate. |
| `reminder_config` update with invalid values | Pydantic validation rejects at the schema level. Return 422 with field-level errors. |

## Testing Strategy

### Property-Based Tests (Frontend — fast-check)

Property-based tests use `fast-check` (already in `devDependencies`) with minimum 100 iterations per property. Each test references its design document property.

| Property | Test File | What's Generated |
|----------|-----------|-----------------|
| P1: Trade family derivation | `widgets/__tests__/tradeFamily.property.test.ts` | Random strings + null |
| P2: Module gating | `widgets/__tests__/moduleGating.property.test.ts` | Random boolean combos for 4 module slugs |
| P3: Layout round-trip | `widgets/__tests__/layoutPersistence.property.test.ts` | Random widget ID arrays + user IDs |
| P4: Stale widget filtering | `widgets/__tests__/layoutPersistence.property.test.ts` | Random saved orders + available sets |
| P12: Config validation | `widgets/__tests__/reminderConfig.property.test.ts` | Random integers (negative, 0, 1-365, >365) |

### Property-Based Tests (Backend — Hypothesis)

Backend property tests use `Hypothesis` (already in the project) with minimum 100 examples.

| Property | Test File | What's Generated |
|----------|-----------|-----------------|
| P5: Recent list bounded order | `tests/test_dashboard_widgets.py` | Random invoice/claim lists |
| P6: Today's bookings filter | `tests/test_dashboard_widgets.py` | Random booking sets with various dates |
| P7: Public holidays filter | `tests/test_dashboard_widgets.py` | Random holiday sets with various countries/dates |
| P8: Inventory grouping | `tests/test_dashboard_widgets.py` | Random product sets with categories and stock levels |
| P9: Cash flow aggregation | `tests/test_dashboard_widgets.py` | Random invoice/expense sets over 6 months |
| P10: Active staff filter | `tests/test_dashboard_widgets.py` | Random time entries (open/closed) |
| P11: Expiry reminders filter | `tests/test_dashboard_widgets.py` | Random vehicles + dismissals + threshold days |

### Unit Tests (Example-Based)

| Test | What's Verified |
|------|----------------|
| Dashboard renders WidgetGrid when isAutomotive=true | Component rendering |
| Dashboard hides WidgetGrid when isAutomotive=false | Component rendering |
| WidgetCard renders header with icon, title, action link | Component structure |
| WidgetCard shows loading spinner when isLoading=true | Loading state |
| WidgetCard shows error message when error is set | Error state |
| Each widget shows empty state message when data is empty | Empty states (Req 4.4, 5.5, 6.4, 7.6, 8.5, 9.6, 10.4, 11.10) |
| Claim status badge uses correct colour per status | Colour coding (Req 9.3) |
| Inventory low-stock count uses warning colour | Colour coding (Req 7.3) |
| Cash flow chart renders with green revenue and red expenses | Chart config (Req 8.2) |
| Default layout order when no localStorage entry | Default order (Req 3.4) |

### Integration Tests

| Test | What's Verified |
|------|----------------|
| `GET /dashboard/widgets` returns correct shape with all sections | API contract |
| `POST /dashboard/reminders/wof/dismiss` creates dismissal record | Dismissal persistence |
| `PUT /dashboard/reminder-config` updates config and returns new values | Config persistence |
| Dismissed reminders don't appear in subsequent widget fetch | End-to-end dismissal flow |
| Widget grid drag-and-drop persists to localStorage (Playwright) | DnD integration |

### Test Configuration

- **fast-check**: `{ numRuns: 100 }` per property test
- **Hypothesis**: `@settings(max_examples=100)` per property test
- **Tag format**: `Feature: automotive-dashboard-widgets, Property {N}: {title}`
- **Frontend tests**: `vitest --run` (no watch mode)
- **Backend tests**: `pytest tests/test_dashboard_widgets.py -v`
