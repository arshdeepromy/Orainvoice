# QR Payment Bugfixes Design

## Overview

Two bugs prevent the kiosk QR payment feature from working end-to-end. Bug 3: the kiosk role is blocked by RBAC middleware when polling QR session endpoints because `/api/v1/payments/qr-session` is not in `KIOSK_ALLOWED_PREFIXES`. Bug 4: there is no way to collect QR payment for an existing invoice — the only path creates a new invoice. The fix adds the QR session prefix to the kiosk allowlist (GET only) and introduces a new endpoint + frontend button for existing invoice QR payment.

## Glossary

- **Bug_Condition (C)**: For Bug 3 — kiosk user accessing QR session GET endpoints and being denied. For Bug 4 — user viewing an unpaid invoice with no QR payment option available.
- **Property (P)**: For Bug 3 — kiosk GET requests to `/api/v1/payments/qr-session/*` pass RBAC. For Bug 4 — "QR Payment" button visible on Invoice Detail, calling a new endpoint that creates a Checkout Session for the invoice's `balance_due`.
- **Preservation**: Kiosk remains restricted to its allowlist for all other paths. POST/expire endpoints remain restricted to org_admin/salesperson. InvoiceCreate QR button continues to work unchanged. Existing toolbar buttons on InvoiceDetail are unaffected.
- **`check_role_path_access()`**: The function in `app/modules/auth/rbac.py` (~line 380) that enforces path-based RBAC for all roles including kiosk.
- **`KIOSK_ALLOWED_PREFIXES`**: The tuple in `app/modules/auth/rbac.py` (~line 210) listing path prefixes the kiosk role can access.
- **`create_qr_payment_session()`**: The function in `app/modules/payments/service.py` that creates an invoice AND a Stripe Checkout Session in one call.
- **`pending_qr_sessions`**: The DB table storing active QR sessions scoped to org (one per org).

## Bug Details

### Bug Condition

**Bug 3 — Kiosk RBAC Path Restriction:**

The bug manifests when a kiosk user polls `GET /api/v1/payments/qr-session/pending` or `GET /api/v1/payments/qr-session/{session_id}/status`. The `check_role_path_access()` function checks `if not _matches_any_prefix(path, KIOSK_ALLOWED_PREFIXES)` and returns a denial because `/api/v1/payments/qr-session` is not in the tuple.

**Formal Specification:**
```
FUNCTION isBugCondition_Bug3(input)
  INPUT: input of type HttpRequest
  OUTPUT: boolean
  
  RETURN input.jwt_role = "kiosk"
         AND input.path STARTS WITH "/api/v1/payments/qr-session"
         AND input.method = "GET"
         AND NOT _matches_any_prefix(input.path, KIOSK_ALLOWED_PREFIXES)
END FUNCTION
```

**Bug 4 — Missing QR Payment on Invoice Detail:**

The bug manifests when a user views an existing unpaid invoice (status "issued", "partially_paid", or "overdue") with a positive `balance_due` and the org has Stripe Connect configured. There is no "QR Payment" button and no backend endpoint to create a Checkout Session for an existing invoice's balance.

**Formal Specification:**
```
FUNCTION isBugCondition_Bug4(input)
  INPUT: input of type InvoiceDetailView
  OUTPUT: boolean
  
  RETURN input.invoice.status IN {"issued", "partially_paid", "overdue"}
         AND input.invoice.balance_due > 0
         AND input.org.stripe_connect_account_id IS NOT NULL
         AND NOT exists_qr_payment_button(input.ui)
         AND NOT exists_endpoint("POST /api/v1/payments/qr-session/existing")
END FUNCTION
```

### Examples

- **Bug 3, Example 1**: Kiosk polls `GET /api/v1/payments/qr-session/pending` → receives 403 "Kiosk role can only access check-in and branding endpoints" instead of the pending session data
- **Bug 3, Example 2**: Kiosk polls `GET /api/v1/payments/qr-session/cs_abc123/status` → receives 403 instead of `{status: "open", payment_intent_id: null}`
- **Bug 3, Example 3**: Kiosk attempts `POST /api/v1/payments/qr-session/cs_abc123/expire` → should STILL receive 403 (kiosk should only have GET access, and the route handler restricts to org_admin/salesperson)
- **Bug 4, Example 1**: Invoice INV-2026-005 has status "issued", balance_due=$150.00, org has Stripe Connect → no QR Payment button visible on detail page
- **Bug 4, Example 2**: Invoice INV-2026-003 has status "partially_paid", balance_due=$75.50, org has Stripe Connect → no way to send this to kiosk for QR payment

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Kiosk remains blocked from all paths NOT in `KIOSK_ALLOWED_PREFIXES` (except the newly added QR session prefix for GET)
- Kiosk remains blocked from `POST /api/v1/payments/qr-session/{session_id}/expire` (write operation, not GET)
- org_admin and salesperson continue to access all QR session endpoints without change
- `POST /api/v1/payments/qr-session` (InvoiceCreate flow) continues to issue invoice + create session atomically
- The existing InvoiceDetail toolbar buttons (Edit, Duplicate, Void, Send Payment Link, Regenerate Payment Link, Create Credit Note, Process Refund) remain unchanged
- The webhook handler for `checkout.session.completed` with `source: "kiosk_qr"` continues to record payment and clear pending session
- Existing kiosk allowlist paths (`/api/v1/kiosk/`, `/api/v1/org/settings`, `/api/v1/customers`, `/api/v1/auth/me`, `/api/v1/auth/refresh`, `/api/v2/modules`) remain accessible

**Scope:**
All inputs that do NOT involve kiosk GET requests to `/api/v1/payments/qr-session` or the new "QR Payment" button on Invoice Detail should be completely unaffected by these fixes. This includes:
- All non-kiosk role access patterns
- All kiosk access to existing allowlisted paths
- Mouse clicks on existing InvoiceDetail buttons
- The InvoiceCreate QR Payment flow

## Hypothesized Root Cause

Based on the bug description and code analysis:

**Bug 3:**

1. **Missing Allowlist Entry**: `KIOSK_ALLOWED_PREFIXES` in `app/modules/auth/rbac.py` (line ~210) does not include `/api/v1/payments/qr-session`. The `_matches_any_prefix()` check fails, and `check_role_path_access()` returns the denial message before the request ever reaches the route handler's `require_role("org_admin", "salesperson", "kiosk")` dependency.

2. **No Method-Level Gating in Allowlist**: The current allowlist has method-specific checks for `/api/v1/org/settings` (GET only) and `/api/v1/customers` (POST only). The QR session prefix needs a similar GET-only restriction so kiosk cannot call the expire endpoint via the allowlist bypass.

**Bug 4:**

1. **No Backend Endpoint for Existing Invoices**: The only QR session creation endpoint (`POST /api/v1/payments/qr-session`) requires full invoice creation payload and creates a new invoice. There is no endpoint that accepts an `invoice_id` and creates a Checkout Session for the existing invoice's `balance_due`.

2. **No Frontend Button**: The InvoiceDetail page has no "QR Payment" button. The `canShowPaymentLink` pattern exists (checks `stripeStatus?.is_connected` and invoice status) and can be reused for the QR button visibility logic.

## Correctness Properties

Property 1: Bug Condition - Kiosk QR Session GET Access

_For any_ HTTP request where the user has role "kiosk" and the path starts with `/api/v1/payments/qr-session` and the method is GET, the fixed `check_role_path_access()` function SHALL return `None` (no denial), allowing the request to proceed to the route handler.

**Validates: Requirements 2.1, 2.2**

Property 2: Preservation - Kiosk Non-GET QR Session Blocked

_For any_ HTTP request where the user has role "kiosk" and the path starts with `/api/v1/payments/qr-session` and the method is NOT GET (e.g., POST), the fixed `check_role_path_access()` function SHALL return a denial message, preserving the restriction that kiosk cannot expire/modify sessions via the RBAC layer.

**Validates: Requirements 2.5, 3.1**

Property 3: Preservation - Kiosk Other Paths Still Blocked

_For any_ HTTP request where the user has role "kiosk" and the path does NOT start with any entry in `KIOSK_ALLOWED_PREFIXES` (including the new QR session entry) and the path does NOT match the new QR session prefix, the fixed code SHALL produce the same denial as the original code.

**Validates: Requirements 3.1, 3.5**

Property 4: Bug Condition - QR Payment for Existing Invoice

_For any_ existing invoice with status in {"issued", "partially_paid", "overdue"} and `balance_due > 0`, when `POST /api/v1/payments/qr-session/existing` is called with `{invoice_id}`, the endpoint SHALL create a Stripe Checkout Session for the invoice's current `balance_due`, upsert a `pending_qr_sessions` row, and return `{session_id, invoice_id, invoice_number, amount, amount_cents, expires_at}` without modifying the invoice itself.

**Validates: Requirements 2.3, 2.4**

Property 5: Preservation - InvoiceCreate QR Flow Unchanged

_For any_ call to `POST /api/v1/payments/qr-session` with full invoice payload, the fixed code SHALL continue to issue the invoice AND create the Checkout Session in one atomic action, producing the same response as before.

**Validates: Requirements 3.3**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `app/modules/auth/rbac.py`

**Change**: Add QR session prefix to `KIOSK_ALLOWED_PREFIXES` and add method-level restriction

**Specific Changes**:
1. **Add Allowlist Entry**: Add `"/api/v1/payments/qr-session"` to the `KIOSK_ALLOWED_PREFIXES` tuple (after the existing `/api/v2/modules` entry)
2. **Add Method Restriction**: In `check_role_path_access()`, after the existing kiosk method checks, add a check that restricts `/api/v1/payments/qr-session` to GET only:
   ```python
   # Kiosk can only GET qr-session endpoints (poll pending/status), not POST (expire)
   if _matches_any_prefix(path, ("/api/v1/payments/qr-session",)) and method.upper() != "GET":
       return "Kiosk role has read-only access to QR payment sessions"
   ```

---

**File**: `app/modules/payments/service.py`

**Function**: New function `create_qr_session_for_existing_invoice()`

**Specific Changes**:
1. **New Service Function**: Create `create_qr_session_for_existing_invoice(db, org_id, user_id, invoice_id)` that:
   - Fetches the invoice by ID scoped to org
   - Validates invoice status is in ("issued", "partially_paid", "overdue")
   - Validates `balance_due > 0`
   - Fetches org's `stripe_connect_account_id` (raises ValueError if not configured)
   - Retrieves Stripe secret key
   - Calculates `amount_cents = int(balance_due * 100)` and application fee
   - Creates Stripe Checkout Session with metadata `{invoice_id, org_id, source: "kiosk_qr", platform: "orainvoice"}`
   - Upserts `pending_qr_sessions` row (delete existing for org, insert new)
   - Returns `{session_id, invoice_id, invoice_number, amount, amount_cents, expires_at, currency}`
   - Does NOT modify the invoice (no status change, no re-issue)

---

**File**: `app/modules/payments/router.py`

**Endpoint**: New `POST /api/v1/payments/qr-session/existing`

**Specific Changes**:
1. **New Route**: Add endpoint with `require_role("org_admin", "salesperson")` dependency
2. **Request Schema**: Accept `{invoice_id: UUID}` body
3. **Response**: Return `QrPaymentSessionResponse` (same schema as existing QR session creation)
4. **Error Handling**: 400 for invalid invoice/status, 400 for Stripe not configured, 502 for Stripe API errors

---

**File**: `app/modules/payments/schemas.py`

**Schema**: New request schema `QrSessionExistingInvoiceRequest`

**Specific Changes**:
1. **New Schema**: `QrSessionExistingInvoiceRequest` with single field `invoice_id: UUID`

---

**File**: `frontend/src/pages/invoices/InvoiceDetail.tsx`

**Component**: Add "QR Payment" button to action toolbar

**Specific Changes**:
1. **New State**: Add `qrPaymentLoading` state and `qrWaitingPopupOpen` state
2. **Visibility Logic**: `canShowQrPayment = stripeStatus?.is_connected === true && ['issued', 'partially_paid', 'overdue'].includes(invoice?.status ?? '') && (invoice?.balance_due ?? 0) > 0`
3. **Handler**: `handleQrPayment()` calls `POST /api/v1/payments/qr-session/existing` with `{invoice_id: invoice.id}`
4. **Button**: Add "QR Payment" button in the action bar (after "Send Payment Link", before "Duplicate")
5. **Waiting Popup**: Reuse existing `QrPaymentWaitingPopup` component (already built for InvoiceCreate flow) to show spinner while waiting for kiosk payment
6. **On Complete**: Refresh invoice data to reflect updated payment status

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that simulate kiosk-role requests to QR session endpoints and assert the RBAC response. Run these tests on the UNFIXED code to observe 403 failures.

**Test Cases**:
1. **Kiosk GET /qr-session/pending**: Simulate kiosk request → expect 403 on unfixed code (will fail)
2. **Kiosk GET /qr-session/{id}/status**: Simulate kiosk request → expect 403 on unfixed code (will fail)
3. **POST /qr-session/existing with valid invoice**: Call endpoint → expect 404 (route doesn't exist on unfixed code)
4. **InvoiceDetail QR button visibility**: Render InvoiceDetail with Stripe connected and unpaid invoice → expect no QR Payment button (will fail)

**Expected Counterexamples**:
- `check_role_path_access("kiosk", "/api/v1/payments/qr-session/pending", "GET")` returns "Kiosk role can only access check-in and branding endpoints"
- No route registered at `POST /api/v1/payments/qr-session/existing`

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition_Bug3(input) DO
  result := check_role_path_access_fixed(input.role, input.path, input.method)
  ASSERT result = None  // no denial
END FOR

FOR ALL input WHERE isBugCondition_Bug4(input) DO
  result := create_qr_session_for_existing_invoice(input.invoice_id)
  ASSERT result.session_id IS NOT NULL
  ASSERT result.amount = input.invoice.balance_due
  ASSERT invoice_status_unchanged(input.invoice_id)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE input.role = "kiosk"
  AND input.path STARTS WITH "/api/v1/payments/qr-session"
  AND input.method != "GET" DO
  ASSERT check_role_path_access_fixed(input.role, input.path, input.method) != None
END FOR

FOR ALL input WHERE input.role = "kiosk"
  AND NOT _matches_any_prefix(input.path, KIOSK_ALLOWED_PREFIXES_NEW) DO
  ASSERT check_role_path_access_original(input) = check_role_path_access_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain (random paths, methods, roles)
- It catches edge cases that manual unit tests might miss (e.g., paths that partially match the prefix)
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for non-kiosk roles and kiosk non-QR paths, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Kiosk Other Paths Preservation**: Generate random paths NOT starting with `/api/v1/payments/qr-session` and not in allowlist → verify same denial on fixed code
2. **Non-Kiosk Role Preservation**: Generate requests with org_admin/salesperson roles to QR session endpoints → verify no change in access
3. **InvoiceCreate QR Flow Preservation**: Call `POST /api/v1/payments/qr-session` with full payload → verify same behavior
4. **Existing Toolbar Preservation**: Render InvoiceDetail → verify all existing buttons still present

### Unit Tests

- `check_role_path_access("kiosk", "/api/v1/payments/qr-session/pending", "GET")` returns None
- `check_role_path_access("kiosk", "/api/v1/payments/qr-session/cs_123/status", "GET")` returns None
- `check_role_path_access("kiosk", "/api/v1/payments/qr-session/cs_123/expire", "POST")` returns denial
- `create_qr_session_for_existing_invoice()` with valid issued invoice returns session details
- `create_qr_session_for_existing_invoice()` with draft invoice raises ValueError
- `create_qr_session_for_existing_invoice()` with zero balance_due raises ValueError
- `create_qr_session_for_existing_invoice()` does not modify invoice status or amount_paid

### Property-Based Tests

- Generate random (role, path, method) tuples and verify RBAC decisions match expected behavior for kiosk QR session access
- Generate random invoice states (status, balance_due, stripe_connected) and verify QR button visibility logic
- Generate random Decimal amounts and verify amount_cents conversion accuracy (`int(balance_due * 100)`)

### Integration Tests

- Full flow: create existing-invoice QR session → kiosk polls pending → kiosk polls status → webhook completes payment
- RBAC integration: kiosk token + GET /qr-session/pending returns 200 (not 403)
- RBAC integration: kiosk token + POST /qr-session/{id}/expire returns 403
- InvoiceDetail renders QR Payment button when conditions met, hides when not
