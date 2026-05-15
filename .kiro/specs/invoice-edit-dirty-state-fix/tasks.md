# Implementation Plan

- [x] 1. Fix isDirty false positive in edit mode (InvoiceCreate.tsx)
  - [x] 1.1 Add initialStateRef to capture loaded invoice state
    - Add a `useRef` (`initialStateRef`) to store a snapshot of form-relevant fields after `loadInvoice` completes
    - Snapshot should include: customer, subject, orderNumber, customerNotes, lineItems, vehicles, discountValue, shippingCharges, adjustment, attachments count
    - Set the ref at the end of the `loadInvoice` effect, after all form state has been populated
    - _Requirements: 2.1_
  - [x] 1.2 Update isDirty logic to compare against initial state in edit mode
    - Branch the `isDirty` computation: if `isEditMode && initialStateRef.current`, compare current form state against `initialStateRef.current`
    - Otherwise (new invoice), keep the existing empty-defaults comparison unchanged
    - Use field-by-field comparison (customer ID, trimmed strings, JSON-stringified arrays, numeric values, attachment count)
    - _Bug_Condition: isEditMode=true AND formState matches loadedInvoiceState AND userModifications=0_
    - _Expected_Behavior: isDirty returns false when form matches loaded state_
    - _Preservation: New invoice dirty detection unchanged (Requirements 3.2); edit mode with actual changes still shows modal (Requirements 3.1)_
    - _Requirements: 2.1, 3.1, 3.2_

- [x] 2. Fix handleSaveDraft navigation when called from guard modal (InvoiceCreate.tsx)
  - [x] 2.1 Add skipNavigation option to handleSaveDraft
    - Add optional `options?: { skipNavigation?: boolean }` parameter to `handleSaveDraft`
    - Wrap the existing `navigate('/invoices/${editId}')` call in a `if (!options?.skipNavigation)` guard
    - _Preservation: Toolbar "Save as Draft" (no options) continues to navigate to detail page (Requirements 3.3)_
    - _Requirements: 2.2, 3.3_
  - [x] 2.2 Update handleSaveDraftRef to pass skipNavigation: true
    - Change the `handleSaveDraftRef.current` assignment so the navigation guard's `onSave` calls `handleSaveDraft({ skipNavigation: true })`
    - This prevents the internal navigation from conflicting with OrgLayout's post-save navigation
    - _Requirements: 2.2_

- [x] 3. Fix OrgLayout Save button to navigate to intended destination (OrgLayout.tsx)
  - [x] 3.1 Add post-save navigation to unsavedDestination
    - In the Save button's `onClick` handler, capture `unsavedDestination` before clearing state
    - After `await unsavedGuardRef.current.onSave()` completes, navigate to the captured destination
    - Clear modal state (`setUnsavedModalOpen(false)`, `setUnsavedDestination(null)`, `unsavedGuardRef.current = null`) before navigating
    - _Bug_Condition: saveCalledFromGuardModal=true AND isEditMode=true AND unsavedDestination != null_
    - _Expected_Behavior: navigates to unsavedDestination after save completes_
    - _Preservation: Discard button behavior unchanged (Requirements 3.4); Stay button behavior unchanged (Requirements 3.5)_
    - _Requirements: 2.2, 2.3, 3.4, 3.5_

- [x] 4. Verify frontend build passes
  - Run `npm run build` (or equivalent) in the `frontend/` directory
  - Confirm no TypeScript errors or build failures from the changes
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 5. Manual verification checkpoint
  - Verify: Open edit invoice with no changes → navigate away → no modal appears (Bug 1 fix)
  - Verify: Open edit invoice → make changes → navigate away → modal appears → click "Save as Draft" → navigates to intended sidebar destination (Bug 2 fix)
  - Verify: Open NEW invoice → add data → navigate away → modal still appears (Preservation 3.2)
  - Verify: Open edit invoice → make changes → click toolbar "Save as Draft" → navigates to invoice detail page (Preservation 3.3)
  - Verify: Discard button still navigates to intended destination (Preservation 3.4)
  - Verify: Stay button still closes modal and remains on form (Preservation 3.5)
  - Ask the user if any questions arise
