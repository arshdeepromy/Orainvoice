# Invoice Edit Dirty State Fix — Bugfix Design

## Overview

Two related bugs in `InvoiceCreate.tsx` edit mode cause a degraded user experience: (1) the `isDirty` check compares form state against empty defaults rather than the loaded invoice state, triggering a false "Unsaved Changes" modal when navigating away from an unmodified edit form; (2) when the user clicks "Save as Draft" in the navigation guard modal, `handleSaveDraft` navigates to the invoice detail page internally, and OrgLayout does not navigate to the user's intended sidebar destination after save completes. The fix introduces an initial-state ref for edit mode comparison, separates the save-only concern from navigation in `handleSaveDraft`, and adds post-save navigation in OrgLayout's Save button handler.

## Glossary

- **Bug_Condition (C)**: The conditions that trigger the two bugs — (1) edit mode with no user modifications triggering false dirty state, (2) guard-initiated save navigating to the wrong destination
- **Property (P)**: The desired behavior — (1) `isDirty` returns false when form matches loaded state, (2) guard save navigates to `unsavedDestination`
- **Preservation**: Existing behaviors that must remain unchanged — new invoice dirty detection, toolbar Save as Draft navigation, Discard/Stay button behavior, Cancel button behavior
- **`isDirty`**: The computed boolean in `InvoiceCreate.tsx` (line 894) that determines whether the form has unsaved changes
- **`handleSaveDraft`**: The function in `InvoiceCreate.tsx` (line 1488) that saves the invoice and navigates to the detail page
- **`handleSaveDraftRef`**: A ref wired to `handleSaveDraft` so the navigation guard can call it without stale closures
- **`NavigationGuardDef`**: The interface in `navigationGuard.ts` defining `isDirty()` and `onSave()` callbacks
- **`unsavedDestination`**: State in `OrgLayout.tsx` storing the sidebar link the user clicked before the guard intercepted

## Bug Details

### Bug Condition

The bug manifests in two scenarios:

**Bug 1 — False Dirty State**: When a user opens an existing draft invoice in edit mode, the `loadInvoice` effect populates form state (customer, vehicles, line items, discount, notes). However, `isDirty` compares these populated values against empty defaults (no customer, no line items, empty strings, zero values). Since the loaded data differs from empty defaults, `isDirty` evaluates to `true` immediately, even though the user has made no modifications.

**Bug 2 — Incorrect Guard Save Navigation**: When the user clicks "Save as Draft" in OrgLayout's unsaved changes modal, `onSave()` resolves to `handleSaveDraft()`, which internally calls `navigate('/invoices/${editId}')`. Meanwhile, OrgLayout's Save button handler does not navigate to `unsavedDestination` after `onSave()` completes. The result is navigation to the invoice detail page instead of the user's intended sidebar destination.

**Formal Specification:**
```
FUNCTION isBugCondition_FalseDirty(input)
  INPUT: input of type InvoiceEditSession
  OUTPUT: boolean
  
  RETURN input.isEditMode = true
     AND input.loadCompleted = true
     AND input.userModifications = 0
     AND isDirty(input.formState) = true  // compares against empty defaults
END FUNCTION

FUNCTION isBugCondition_GuardSaveNav(input)
  INPUT: input of type GuardSaveAction
  OUTPUT: boolean
  
  RETURN input.calledFromGuardModal = true
     AND input.isEditMode = true
     AND input.unsavedDestination != null
END FUNCTION
```

### Examples

- **Bug 1**: User opens `/invoices/edit/abc123` (draft with customer "John Smith", 2 line items). Without changing anything, clicks "Customers" in sidebar → "Unsaved Changes" modal appears incorrectly. Expected: navigation proceeds without modal.
- **Bug 1**: User opens `/invoices/edit/abc123` (draft with discount 10%). Without changing anything, clicks "Dashboard" → modal appears. Expected: no modal.
- **Bug 2**: User is editing invoice, changes the subject line, clicks "Vehicles" in sidebar → modal appears → clicks "Save as Draft" → navigates to `/invoices/abc123` (detail page). Expected: navigates to `/vehicles`.
- **Bug 2**: Same scenario but user clicks "Customers" → "Save as Draft" → navigates to `/invoices/abc123`. Expected: navigates to `/customers`.
- **Edge case (correct behavior)**: User opens a NEW invoice (`/invoices/new`), types a customer name, clicks sidebar → modal appears correctly because form differs from empty defaults.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- New invoice creation (`/invoices/new`) dirty detection must continue comparing against empty defaults
- Toolbar "Save as Draft" button (not from guard modal) must continue saving and navigating to the invoice detail page
- "Discard" button in the unsaved changes modal must continue navigating to `unsavedDestination` without saving
- "Stay" button must continue closing the modal and remaining on the edit form
- "Cancel" button on the invoice form must continue triggering the local guard and navigating back to the invoice detail page
- Edit mode with actual user modifications must continue showing the "Unsaved Changes" modal
- The `NavigationGuardDef` interface must remain backward-compatible for any other forms using it

**Scope:**
All inputs that do NOT involve (1) edit mode with no modifications or (2) guard-modal-initiated saves should be completely unaffected by this fix. This includes:
- All new invoice creation flows
- Direct toolbar save actions
- Mouse clicks on Discard/Stay buttons
- Cancel button behavior
- Edit mode where the user has actually modified fields

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **isDirty compares against empty defaults, not loaded state**: The `isDirty` computation (line 894) checks `Boolean(customer || subject.trim() || ...)` — it returns true if ANY field has a value. In edit mode, `loadInvoice` populates `customer`, `lineItems`, `vehicles`, etc., so `isDirty` is immediately true. There is no reference to the initial loaded state to compare against.

2. **handleSaveDraft always navigates internally**: `handleSaveDraft` (line 1488) unconditionally calls `navigate('/invoices/${editId}')` after a successful PUT. When called from the guard modal context, this navigation conflicts with the intended destination. The function has no awareness of whether it was called from the toolbar or from the guard.

3. **OrgLayout Save button does not navigate to unsavedDestination**: The Save button's `onClick` handler (line 535-543) calls `await unsavedGuardRef.current.onSave()`, then clears state, but never calls `navigate(unsavedDestination)`. Compare with the Discard button which explicitly navigates to `dest`.

4. **No mechanism to suppress handleSaveDraft's internal navigation**: The `NavigationGuardDef.onSave` signature is `() => Promise<void>` — there's no parameter to indicate "save only, don't navigate" vs "save and navigate to detail page".

## Correctness Properties

Property 1: Bug Condition - False Dirty State in Edit Mode

_For any_ invoice edit session where the form has been loaded from an existing invoice and the user has made zero modifications to any field, the fixed `isDirty` computation SHALL return `false`, preventing the "Unsaved Changes" modal from appearing on navigation.

**Validates: Requirements 2.1**

Property 2: Bug Condition - Guard Save Navigates to Intended Destination

_For any_ guard-initiated save action where `onSave()` is called from OrgLayout's "Save as Draft" button with a non-null `unsavedDestination`, the system SHALL save the invoice successfully AND navigate to `unsavedDestination` (not to the invoice detail page).

**Validates: Requirements 2.2, 2.3**

Property 3: Preservation - New Invoice Dirty Detection

_For any_ new invoice creation session (not edit mode) where the user has entered any data (customer, line items, notes, etc.), the fixed `isDirty` computation SHALL return `true`, preserving the existing "Unsaved Changes" modal behavior.

**Validates: Requirements 3.2**

Property 4: Preservation - Toolbar Save Navigation

_For any_ direct toolbar "Save as Draft" action (not from the guard modal), the fixed `handleSaveDraft` function SHALL continue to save the invoice AND navigate to the invoice detail page, preserving existing behavior.

**Validates: Requirements 3.3**

Property 5: Preservation - Edit Mode With Actual Changes

_For any_ invoice edit session where the user has modified at least one field relative to the loaded state, the fixed `isDirty` computation SHALL return `true`, preserving the "Unsaved Changes" modal behavior for genuine modifications.

**Validates: Requirements 3.1**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `frontend/src/pages/invoices/InvoiceCreate.tsx`

**Change 1: Store initial loaded state in a ref**

After `loadInvoice` populates all form fields, capture a snapshot of the relevant dirty-check fields into a ref (`initialStateRef`). This ref represents the "clean" baseline for edit mode.

```typescript
const initialStateRef = useRef<{
  customer: Customer | null
  subject: string
  orderNumber: string
  customerNotes: string
  lineItems: LineItem[]
  vehicles: Vehicle[]
  discountValue: number
  shippingCharges: number
  adjustment: number
  attachments: number  // count of attachments at load time
} | null>(null)
```

At the end of `loadInvoice`, set:
```typescript
initialStateRef.current = {
  customer: inv.customer || null,
  subject: inv.subject || '',
  orderNumber: inv.order_number || '',
  customerNotes: inv.notes_customer || '',
  lineItems: /* the transformed line items */,
  vehicles: /* the transformed vehicles */,
  discountValue: Number(inv.discount_value || 0),
  shippingCharges: Number(inv.shipping_charges || 0),
  adjustment: Number(inv.adjustment || 0),
  attachments: (inv.attachments || []).length,
}
```

**Change 2: Update isDirty to compare against initial state in edit mode**

Replace the current `isDirty` logic with a branching check:
- If `isEditMode && initialStateRef.current` → compare current form state against `initialStateRef.current`
- Otherwise (new invoice) → use existing empty-defaults comparison

```typescript
const isDirty = isEditMode && initialStateRef.current
  ? Boolean(
      customer?.id !== initialStateRef.current.customer?.id ||
      subject.trim() !== initialStateRef.current.subject ||
      orderNumber.trim() !== initialStateRef.current.orderNumber ||
      customerNotes.trim() !== initialStateRef.current.customerNotes ||
      JSON.stringify(lineItems) !== JSON.stringify(initialStateRef.current.lineItems) ||
      JSON.stringify(vehicles) !== JSON.stringify(initialStateRef.current.vehicles) ||
      discountValue !== initialStateRef.current.discountValue ||
      shippingCharges !== initialStateRef.current.shippingCharges ||
      adjustment !== initialStateRef.current.adjustment ||
      attachments.length !== initialStateRef.current.attachments
    )
  : Boolean(
      customer ||
      subject.trim() ||
      orderNumber.trim() ||
      customerNotes.trim() ||
      lineItems.some(li => li.description.trim() || li.quantity !== 1 || li.rate !== 0) ||
      vehicles.length > 0 ||
      discountValue > 0 ||
      shippingCharges > 0 ||
      adjustment !== 0 ||
      attachments.length > 0
    )
```

**Change 3: Add `skipNavigation` parameter to handleSaveDraft**

Modify `handleSaveDraft` to accept an optional `options` object with a `skipNavigation` flag:

```typescript
const handleSaveDraft = async (options?: { skipNavigation?: boolean }) => {
  // ... existing validation and save logic ...
  if (!options?.skipNavigation) {
    navigate(`/invoices/${editId}`, { state: { invoice: inv } })
  }
}
```

**Change 4: Wire navigation guard's onSave to skip navigation**

Update `handleSaveDraftRef` assignment so the guard calls `handleSaveDraft({ skipNavigation: true })`:

```typescript
handleSaveDraftRef.current = () => handleSaveDraft({ skipNavigation: true })
```

**File**: `frontend/src/layouts/OrgLayout.tsx`

**Change 5: Navigate to unsavedDestination after onSave completes**

Update the Save button's `onClick` handler to navigate to `unsavedDestination` after `onSave()` resolves:

```typescript
onClick={async () => {
  const dest = unsavedDestination
  if (unsavedGuardRef.current) {
    await unsavedGuardRef.current.onSave()
  }
  setUnsavedModalOpen(false)
  setUnsavedDestination(null)
  unsavedGuardRef.current = null
  if (dest) navigate(dest)
}}
```

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that render `InvoiceCreate` in edit mode with mocked API responses, verify `isDirty` evaluates to true without user interaction, and verify that `handleSaveDraft` navigates to the detail page when called from the guard context. Run these tests on the UNFIXED code to observe failures.

**Test Cases**:
1. **Edit Mode False Dirty**: Load invoice in edit mode, assert navigation guard `isDirty()` returns true immediately (will demonstrate bug on unfixed code)
2. **Guard Save Wrong Navigation**: Trigger `onSave()` from guard context, assert navigation goes to detail page instead of intended destination (will demonstrate bug on unfixed code)
3. **OrgLayout No Post-Save Navigation**: Click "Save as Draft" in modal, assert `navigate` is NOT called with `unsavedDestination` (will demonstrate bug on unfixed code)

**Expected Counterexamples**:
- `isDirty` returns `true` for an unmodified edit form because customer is non-null
- `handleSaveDraft` calls `navigate('/invoices/abc123')` when called from guard, overriding intended destination
- OrgLayout Save button never calls `navigate(unsavedDestination)`

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition_FalseDirty(input) DO
  result := isDirty'(input.formState, input.initialState)
  ASSERT result = false
END FOR

FOR ALL input WHERE isBugCondition_GuardSaveNav(input) DO
  result := onSave'(input)
  ASSERT result.navigatedTo = input.unsavedDestination
  ASSERT result.invoiceSaved = true
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition_FalseDirty(input) DO
  ASSERT isDirty(input) = isDirty'(input)
END FOR

FOR ALL input WHERE NOT isBugCondition_GuardSaveNav(input) DO
  ASSERT handleSaveDraft(input) = handleSaveDraft'(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many form state combinations automatically across the input domain
- It catches edge cases in dirty comparison logic (e.g., whitespace differences, numeric precision)
- It provides strong guarantees that new invoice creation behavior is unchanged

**Test Plan**: Observe behavior on UNFIXED code first for new invoice creation and toolbar saves, then write property-based tests capturing that behavior.

**Test Cases**:
1. **New Invoice Dirty Detection Preservation**: Generate random form states for new invoices, verify `isDirty` returns the same result before and after fix
2. **Toolbar Save Navigation Preservation**: Verify that calling `handleSaveDraft()` without `skipNavigation` continues to navigate to detail page
3. **Discard Button Preservation**: Verify clicking Discard still navigates to `unsavedDestination`
4. **Stay Button Preservation**: Verify clicking Stay still closes modal without navigation
5. **Cancel Button Preservation**: Verify Cancel on edit form still triggers local guard

### Unit Tests

- Test `isDirty` returns false in edit mode when form matches loaded state
- Test `isDirty` returns true in edit mode when any field differs from loaded state
- Test `isDirty` returns true for new invoice with any non-empty field (existing behavior)
- Test `handleSaveDraft({ skipNavigation: true })` saves but does not navigate
- Test `handleSaveDraft()` (no options) saves and navigates to detail page
- Test OrgLayout Save button navigates to `unsavedDestination` after `onSave()` resolves

### Property-Based Tests

- Generate random invoice data (customer, line items, vehicles, discounts), load into edit mode, verify `isDirty` is false when form matches loaded state
- Generate random modifications to a loaded invoice, verify `isDirty` is true when any field differs
- Generate random form states for new invoices, verify `isDirty` matches the original empty-defaults logic exactly
- Generate random `unsavedDestination` paths, verify OrgLayout Save button navigates to the correct destination

### Integration Tests

- Full flow: open edit invoice → make no changes → click sidebar link → verify no modal appears
- Full flow: open edit invoice → modify subject → click sidebar link → modal appears → click "Save as Draft" → verify navigation to sidebar destination
- Full flow: open new invoice → add customer → click sidebar link → modal appears → verify modal behavior unchanged
- Full flow: open edit invoice → modify line item → click toolbar "Save as Draft" → verify navigation to detail page
