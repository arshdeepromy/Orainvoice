---
inclusion: fileMatch
fileMatchPattern: '**/dashboard/widgets/**'
---

# Dashboard Widget Gating — How to Add New Widgets

This steering doc is loaded when editing files in the dashboard widgets directory. It documents the architecture and step-by-step process for adding new dashboard widgets, including module gating, backend data, and frontend rendering.

## Architecture Overview

The automotive dashboard uses a two-layer gating system:

1. **Trade-family gating** — The entire `WidgetGrid` only renders for `automotive-transport` orgs. This is handled in `OrgAdminDashboard.tsx` via `isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'`. You do NOT need to repeat this check inside individual widgets.

2. **Module gating** — Individual widgets are shown/hidden based on whether their associated backend module is enabled for the org. This is controlled by the `module` field in `WIDGET_DEFINITIONS` inside `WidgetGrid.tsx`. The grid filters widgets using `useModules().isEnabled(slug)`.

### Current Widget-to-Module Mapping

| Widget ID | Module Gate | Always Visible? |
|-----------|------------|-----------------|
| `recent-customers` | _(none)_ | Yes |
| `todays-bookings` | `bookings` | No |
| `public-holidays` | _(none)_ | Yes |
| `inventory-overview` | `inventory` | No |
| `cash-flow` | _(none)_ | Yes |
| `recent-claims` | `claims` | No |
| `active-staff` | _(none)_ | Yes |
| `expiry-reminders` | `vehicles` | No |
| `reminder-config` | `vehicles` | No |

Widgets with no module gate are always visible to all automotive orgs. Widgets with a module gate only appear when that module is enabled via `org_modules`.

## Step-by-Step: Adding a New Widget

### 1. Decide on module gating

Ask yourself: does this widget depend on a specific module being enabled?

- If the widget shows data from a module-specific table (e.g., `bookings`, `inventory`, `claims`, `vehicles`), gate it behind that module slug.
- If the widget shows core data available to all orgs (e.g., invoices, customers, staff, holidays), leave it ungated.
- If the widget is for a NEW module, make sure the module slug exists in the `module_registry` table first.

### 2. Backend — Add the data query

Create a new service function in `app/modules/organisations/dashboard_service.py`:

```python
async def get_your_widget_data(
    db: AsyncSession,
    org_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
) -> WidgetDataSection[YourWidgetItem]:
    """Query description here."""
    # Your query logic
    # Always branch-scope when branch_id is provided
    # Return WidgetDataSection(items=[...], total=len(items))
```

Key rules:
- Use `async def` with `AsyncSession`
- Accept `org_id` and `branch_id` (nullable) parameters
- Branch-scope queries with `if branch_id is not None: query = query.where(Model.branch_id == branch_id)`
- Return a `WidgetDataSection[YourItemType]` with `items` and `total`

### 3. Backend — Add the Pydantic schema

Add your item schema to `app/modules/organisations/schemas.py`:

```python
class YourWidgetItem(BaseModel):
    """Description of a single item."""
    id: UUID
    name: str
    # ... other fields matching what the frontend needs
```

### 4. Backend — Wire into the aggregator

Add your widget to `get_all_widget_data()` in `dashboard_service.py`:

```python
# In get_all_widget_data():
try:
    your_widget = await get_your_widget_data(db, org_id, branch_id)
except Exception:
    logger.exception("Failed to fetch your widget data")
    your_widget = _empty_section()
```

The per-widget try/except is mandatory — one widget failing must not break the others.

### 5. Backend — Add to the response schema

Add the new field to `DashboardWidgetsResponse` in `schemas.py`:

```python
class DashboardWidgetsResponse(BaseModel):
    # ... existing fields ...
    your_widget: WidgetDataSection[YourWidgetItem]
```

### 6. Frontend — Add the TypeScript type

Add the interface to `frontend/src/pages/dashboard/widgets/types.ts`:

```typescript
export interface YourWidgetItem {
  id: string
  name: string
  // ... fields matching backend schema exactly
}
```

Add the field to `DashboardWidgetData`:

```typescript
export interface DashboardWidgetData {
  // ... existing fields ...
  your_widget: WidgetDataSection<YourWidgetItem>
}
```

### 7. Frontend — Update the data hook

Add normalisation for the new field in `useDashboardWidgets.ts` inside `normaliseDashboardData()`:

```typescript
your_widget: {
  items: raw.your_widget?.items ?? [],
  total: raw.your_widget?.total ?? 0,
},
```

### 8. Frontend — Create the widget component

Create `frontend/src/pages/dashboard/widgets/YourWidget.tsx`:

```tsx
import { WidgetCard } from './WidgetCard'
import type { YourWidgetItem, WidgetDataSection } from './types'

interface YourWidgetProps {
  data: WidgetDataSection<YourWidgetItem> | undefined | null
  isLoading: boolean
  error: string | null
}

export function YourWidget({ data, isLoading, error }: YourWidgetProps) {
  const items = data?.items ?? []

  return (
    <WidgetCard
      title="Your Widget Title"
      icon={YourIcon}
      isLoading={isLoading}
      error={error}
    >
      {items.length === 0 ? (
        <p className="text-sm text-gray-500">No data available</p>
      ) : (
        // Render your items — always use ?. and ?? on data access
        <ul className="divide-y divide-gray-100">
          {items.map((item) => (
            <li key={item?.id ?? Math.random()}>
              {item?.name ?? 'Unknown'}
            </li>
          ))}
        </ul>
      )}
    </WidgetCard>
  )
}
```

Mandatory patterns:
- Use `WidgetCard` as the outer wrapper
- Accept `data`, `isLoading`, `error` props
- Guard all data access with `?.` and `?? []` / `?? 0` (see `safe-api-consumption.md`)
- Provide an empty state message when `items.length === 0`
- Use inline SVG icons (matching existing widget icon patterns) — do not add a heroicons dependency

### 9. Frontend — Register in WidgetGrid

In `WidgetGrid.tsx`, do three things:

**a)** Import your widget:
```typescript
import { YourWidget } from './YourWidget'
```

**b)** Add to `WIDGET_DEFINITIONS`:
```typescript
const WIDGET_DEFINITIONS: WidgetDef[] = [
  // ... existing widgets ...
  { id: 'your-widget', title: 'Your Widget Title', module: 'your-module-slug', defaultOrder: 10 },
]
```

- `id`: kebab-case unique identifier
- `title`: display title shown in the card header
- `module`: the module slug for gating, or omit for ungated widgets
- `defaultOrder`: position in the default layout (increment from the last widget)

**c)** Add a case to `renderWidget()`:
```typescript
case 'your-widget':
  return (
    <YourWidget
      data={data?.your_widget}
      isLoading={isLoading}
      error={error}
    />
  )
```

### 10. Tests

Add these tests for your new widget:

- **Backend property test** in `tests/test_dashboard_widgets.py` — test the pure logic of your data query (filtering, sorting, grouping)
- **Frontend empty state test** in `widgetEmptyStates.test.tsx` — verify the empty state message renders
- **Frontend property test** (if the widget has non-trivial logic like validation or filtering)
- Update `moduleGating.property.test.ts` if you added a new module-gated widget — add the module slug to the test's `WIDGET_DEFINITIONS` mirror

## Module Gating Checklist

Before considering a new widget complete:

- [ ] Widget component created with `WidgetCard` wrapper
- [ ] Backend service function with branch scoping and error handling
- [ ] Pydantic schema added and wired into `DashboardWidgetsResponse`
- [ ] TypeScript type added to `types.ts` and `DashboardWidgetData`
- [ ] Data hook normalisation updated in `useDashboardWidgets.ts`
- [ ] Widget registered in `WIDGET_DEFINITIONS` with correct `module` slug (or no slug if ungated)
- [ ] Widget case added to `renderWidget()` switch
- [ ] Empty state message defined and tested
- [ ] Safe API consumption patterns followed (`?.`, `?? []`, `?? 0`)
- [ ] Property test written for the widget's data logic
- [ ] `moduleGating.property.test.ts` updated if new module slug introduced

## Key Files Reference

| Purpose | File |
|---------|------|
| Widget grid + definitions | `frontend/src/pages/dashboard/widgets/WidgetGrid.tsx` |
| Widget card wrapper | `frontend/src/pages/dashboard/widgets/WidgetCard.tsx` |
| TypeScript types | `frontend/src/pages/dashboard/widgets/types.ts` |
| Data hook | `frontend/src/pages/dashboard/widgets/useDashboardWidgets.ts` |
| Backend service | `app/modules/organisations/dashboard_service.py` |
| Backend router | `app/modules/organisations/dashboard_router.py` |
| Backend schemas | `app/modules/organisations/schemas.py` |
| Dashboard integration | `frontend/src/pages/dashboard/OrgAdminDashboard.tsx` |
| Module context (frontend) | `frontend/src/contexts/ModuleContext.tsx` |
| Module service (backend) | `app/core/modules.py` |
| Module gating property test | `frontend/src/pages/dashboard/widgets/__tests__/moduleGating.property.test.ts` |
| Empty state unit tests | `frontend/src/pages/dashboard/widgets/__tests__/widgetEmptyStates.test.tsx` |
| Backend property tests | `tests/test_dashboard_widgets.py` |
