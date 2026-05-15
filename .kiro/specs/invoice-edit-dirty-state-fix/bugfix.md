# Bugfix Requirements Document

## Introduction

Two related bugs exist in the InvoiceCreate edit mode that degrade the user experience when editing existing draft invoices. Bug 1 causes a false "Unsaved Changes" popup when navigating away from an unmodified edit form. Bug 2 causes the "Save as Draft" action triggered from the navigation guard modal to navigate incorrectly (to the invoice detail page instead of the user's intended sidebar destination), and in some cases creates navigation conflicts. Both bugs stem from the `isDirty` logic comparing form state against empty defaults rather than the loaded invoice state, and from `handleSaveDraft` performing its own navigation when called from the guard context.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a user opens an existing draft invoice in edit mode and navigates away without making any changes THEN the system incorrectly displays the "Unsaved Changes" modal because `isDirty` compares form state against empty defaults (no customer, no line items, no vehicles) rather than the initial loaded state

1.2 WHEN a user clicks "Save as Draft" in the navigation guard's "Unsaved Changes" modal while editing an existing invoice THEN the system navigates to the invoice detail page (`/invoices/{id}`) instead of the sidebar destination the user originally clicked, because `handleSaveDraft` calls `navigate()` internally and the OrgLayout modal does not navigate to `unsavedDestination` after `onSave()` completes

1.3 WHEN the OrgLayout's "Save as Draft" button calls `onSave()` (which resolves to `handleSaveDraft`) THEN the system does not navigate to the user's intended destination (`unsavedDestination`) after the save completes, leaving the user on the wrong page

### Expected Behavior (Correct)

2.1 WHEN a user opens an existing draft invoice in edit mode and navigates away without making any changes THEN the system SHALL allow navigation without showing the "Unsaved Changes" modal because no modifications have been made relative to the loaded invoice data

2.2 WHEN a user clicks "Save as Draft" in the navigation guard's "Unsaved Changes" modal while editing an existing invoice THEN the system SHALL save the invoice (PUT to existing ID) and then navigate to the user's originally intended sidebar destination, not to the invoice detail page

2.3 WHEN the OrgLayout's "Save as Draft" button calls `onSave()` THEN the system SHALL navigate to `unsavedDestination` after the save completes successfully, consistent with how the "Discard" button navigates to the destination

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a user opens an existing draft invoice in edit mode, makes actual changes (modifies customer, line items, vehicles, notes, etc.), and navigates away THEN the system SHALL CONTINUE TO display the "Unsaved Changes" modal

3.2 WHEN a user creates a new invoice (not edit mode) and has entered any data, then navigates away THEN the system SHALL CONTINUE TO display the "Unsaved Changes" modal using the existing empty-defaults comparison

3.3 WHEN a user clicks "Save as Draft" directly from the invoice form toolbar (not from the navigation guard modal) THEN the system SHALL CONTINUE TO save and navigate to the invoice detail page as it does today

3.4 WHEN a user clicks "Discard" in the "Unsaved Changes" modal THEN the system SHALL CONTINUE TO navigate to the intended sidebar destination without saving

3.5 WHEN a user clicks "Stay" in the "Unsaved Changes" modal THEN the system SHALL CONTINUE TO close the modal and remain on the edit form

3.6 WHEN a user clicks "Cancel" on the invoice edit form THEN the system SHALL CONTINUE TO trigger the local unsaved changes guard and navigate back to the invoice detail page

---

## Bug Condition (Formal)

### Bug 1: False Dirty State

```pascal
FUNCTION isBugCondition_FalseDirty(X)
  INPUT: X of type InvoiceEditSession
  OUTPUT: boolean
  
  // Bug triggers when in edit mode with pre-filled data and no user modifications
  RETURN X.isEditMode = true
     AND X.formState = X.loadedInvoiceState
     AND X.userModifications = 0
END FUNCTION
```

```pascal
// Property: Fix Checking — No false dirty flag in edit mode without changes
FOR ALL X WHERE isBugCondition_FalseDirty(X) DO
  result ← isDirty'(X)
  ASSERT result = false
END FOR
```

### Bug 2: Incorrect Navigation After Guard Save

```pascal
FUNCTION isBugCondition_GuardSaveNav(X)
  INPUT: X of type GuardSaveAction
  OUTPUT: boolean
  
  // Bug triggers when onSave is called from the OrgLayout navigation guard modal
  RETURN X.saveCalledFromGuardModal = true
     AND X.isEditMode = true
END FUNCTION
```

```pascal
// Property: Fix Checking — Guard save navigates to intended destination
FOR ALL X WHERE isBugCondition_GuardSaveNav(X) DO
  result ← onSave'(X)
  ASSERT result.navigatedTo = X.unsavedDestination
     AND result.invoiceSaved = true
     AND result.httpMethod = "PUT"
END FOR
```

### Preservation

```pascal
// Property: Preservation Checking — Non-buggy inputs behave identically
FOR ALL X WHERE NOT isBugCondition_FalseDirty(X) DO
  ASSERT isDirty(X) = isDirty'(X)
END FOR

FOR ALL X WHERE NOT isBugCondition_GuardSaveNav(X) DO
  ASSERT handleSaveDraft(X) = handleSaveDraft'(X)
END FOR
```
