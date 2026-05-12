# Feature Gating — By User Type, Plan, or Role

This document defines how to gate features in a multi-tenant SaaS application so that only the appropriate users, plans, or business types see specific functionality. It prevents the recurring bug where features intended for one user segment leak into others.

## Why This Matters

In a multi-tenant SaaS serving different business types (or different subscription plans), features must be conditionally shown. Without proper gating:
- Users see UI for features they can't use (confusing)
- Users can submit data for features they shouldn't have access to (security risk)
- Business-type-specific terminology leaks into unrelated contexts
- API payloads include fields the backend rejects or ignores

**Real-world lesson:** An automotive-specific vehicle selector kept appearing for non-automotive businesses because developers forgot to wrap it in a business-type check. This happened repeatedly across 15+ files until a steering doc enforced the pattern.

---

## Gating Strategies

### 1. Business Type / Vertical Gating

Gate features by the type of business the tenant operates (e.g., automotive, construction, healthcare).

```tsx
// Read the business type from tenant context
const { businessType } = useTenant()
const isAutomotive = (businessType ?? 'default') === 'automotive'

// Gate UI elements
{isAutomotive && (
  <VehicleSelector />
)}

// Gate API payload fields
const payload = {
  ...commonFields,
  ...(isAutomotive ? { vehicle_id: selectedVehicle } : {}),
}
```

### 2. Subscription Plan Gating

Gate features by the tenant's subscription tier.

```tsx
const { plan } = useTenant()
const hasPremiumFeature = ['pro', 'enterprise'].includes(plan?.slug ?? 'free')

{hasPremiumFeature && (
  <AdvancedReporting />
)}
```

### 3. Role-Based Gating

Gate features by the user's role within the organisation.

```tsx
const { user } = useAuth()
const isAdmin = user?.role === 'admin' || user?.role === 'owner'

{isAdmin && (
  <DangerZoneSettings />
)}
```

### 4. Module/Feature Flag Gating

Gate features by toggleable modules that admins can enable/disable.

```tsx
const { isModuleEnabled } = useModules()

{isModuleEnabled('inventory') && (
  <InventoryNavLink />
)}
```

---

## What Must Be Gated

Every one of these element types must be checked when adding a gated feature:

### Frontend JSX
- Table columns (`<th>` and corresponding `<td>`)
- Form sections and fields
- Sidebar navigation links
- Detail page info sections
- Modal content sections
- Picker/search components
- Action buttons

### Routes
- New routes for gated pages need a route guard component

```tsx
// Route guard pattern
function RequireFeature({ feature, children }) {
  const { isModuleEnabled } = useModules()
  if (!isModuleEnabled(feature)) return <Navigate to="/dashboard" />
  return children
}

// Usage in router
<Route path="/inventory/*" element={
  <RequireFeature feature="inventory">
    <InventoryLayout />
  </RequireFeature>
} />
```

### API Payloads
- Gated fields in POST/PUT payloads must be conditionally included
- Use the spread pattern: `...(isEnabled ? { field: value } : {})`

### Sidebar Navigation
- New nav items must be wrapped in the appropriate gate check

---

## Implementation Pattern

### Step 1: Determine the Gate Type

Before writing code, determine which gating strategy applies:

| Question | Gate Type |
|----------|-----------|
| Is this for a specific industry/vertical? | Business type gate |
| Is this a premium/paid feature? | Plan gate |
| Is this admin-only? | Role gate |
| Is this a toggleable module? | Module/feature flag gate |
| Combination? | Multiple gates (AND logic) |

### Step 2: Apply Gating Consistently

Every new UI element related to the gated feature must be wrapped:

```tsx
// Component level
const { businessType } = useTenant()
const isTargetType = (businessType ?? 'default') === 'target-type'

// JSX — gate every element
{isTargetType && <th>Type-Specific Column</th>}
{isTargetType && <td>{data.type_specific_field}</td>}

// Forms — gate fields
{isTargetType && (
  <FormField label="Type-Specific Field">
    <Input value={typeSpecificValue} onChange={...} />
  </FormField>
)}

// Payloads — gate data
const payload = {
  name: formData.name,
  email: formData.email,
  ...(isTargetType ? { type_specific_field: formData.typeSpecificField } : {}),
}
```

### Step 3: Handle Null/Default Values

When the gating value might be null (e.g., legacy tenants that haven't set their type):

```tsx
// Choose a sensible default for backward compatibility
const effectiveType = businessType ?? 'default-type'
const isTargetType = effectiveType === 'target-type'
```

---

## Multiple Business Types

When a feature applies to multiple (but not all) business types:

```tsx
const { businessType } = useTenant()
const effectiveType = businessType ?? 'default'
const supportsFeature = ['automotive', 'electrical', 'plumbing'].includes(effectiveType)
```

---

## Common Mistakes to Avoid

1. **Gating the `<th>` but not the `<td>`** (or vice versa) — causes column misalignment
2. **Gating the UI but not the API payload** — hidden fields still get sent to the backend
3. **Forgetting to adjust `colSpan`** on empty-state table rows when a column is conditional
4. **Using module gates for vertical features** — business type features are inherent to the business, not toggleable modules
5. **Not handling null gate values** — always provide a fallback default
6. **Hardcoding business-type-specific labels** — use a terminology/i18n system instead
7. **Gating only at the page level** — sub-sections within universal pages also need gating

---

## Checklist

Before any gated feature is complete:

- [ ] Determined which gate type applies (business type, plan, role, module)
- [ ] Every new JSX section is wrapped in the gate condition
- [ ] Every new table column (th + td) is conditionally rendered
- [ ] Every new form field is conditionally rendered
- [ ] API payloads conditionally include gated fields
- [ ] New routes have a route guard if they're gated pages
- [ ] New sidebar links are gated
- [ ] `colSpan` on empty-state rows accounts for conditional columns
- [ ] Null/undefined gate values are handled with a sensible default
- [ ] Labels use terminology context (not hardcoded business-specific terms)
