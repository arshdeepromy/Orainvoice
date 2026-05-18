# Implementation Plan

- [x] 1. Write bug condition exploration test (RBAC + existing invoice endpoint)
  - **Property 1: Bug Condition** - Kiosk QR Session RBAC Denial & Missing Endpoint
  - **IMPORTANT**: Write this property-based test BEFORE implementing the fix
  - **GOAL**: Surface counterexamples that demonstrate both bugs exist on current code
  - **Scoped PBT Approach**: Scope the property to concrete failing cases:
    - `check_role_path_access("kiosk", "/api/v1/payments/qr-session/pending", "GET")` returns denial instead of None
    - `check_role_path_access("kiosk", "/api/v1/payments/qr-session/cs_abc123/status", "GET")` returns denial instead of None
    - `POST /api/v1/payments/qr-session/existing` route does not exist (404)
  - Test that for all kiosk GET requests to paths starting with `/api/v1/payments/qr-session`, `check_role_path_access()` returns None (from Bug Condition in design)
  - Test that `POST /api/v1/payments/qr-session/existing` endpoint exists and accepts `{invoice_id}` (from Bug Condition in design)
  - Run test on UNFIXED code - expect FAILURE (this confirms the bugs exist)
  - Document counterexamples found (e.g., "check_role_path_access returns 'Kiosk role can only access check-in and branding endpoints'")
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Kiosk RBAC Restrictions & Non-Kiosk Access Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: `check_role_path_access("kiosk", "/api/v1/invoices/123", "GET")` returns denial on unfixed code
  - Observe: `check_role_path_access("kiosk", "/api/v1/payments/qr-session/cs_123/expire", "POST")` returns denial on unfixed code
  - Observe: `check_role_path_access("org_admin", "/api/v1/payments/qr-session/pending", "GET")` returns None on unfixed code
  - Observe: `check_role_path_access("salesperson", "/api/v1/payments/qr-session/cs_123/status", "GET")` returns None on unfixed code
  - Observe: `check_role_path_access("kiosk", "/api/v1/kiosk/checkin", "GET")` returns None on unfixed code (existing allowlist)
  - Write property-based test: for all kiosk requests to paths NOT in KIOSK_ALLOWED_PREFIXES and NOT starting with `/api/v1/payments/qr-session`, result is a denial string (from Preservation Requirements in design)
  - Write property-based test: for all non-kiosk roles (org_admin, salesperson) accessing QR session endpoints, result is None (from Preservation Requirements in design)
  - Write property-based test: for all kiosk requests where method is NOT GET and path starts with `/api/v1/payments/qr-session`, result is a denial (kiosk read-only restriction)
  - Verify tests pass on UNFIXED code
  - _Requirements: 2.5, 3.1, 3.2, 3.5_

- [ ] 3. Fix Bug 3: Add QR session prefix to KIOSK_ALLOWED_PREFIXES with GET-only restriction

  - [x] 3.1 Add `/api/v1/payments/qr-session` to `KIOSK_ALLOWED_PREFIXES` tuple in `app/modules/auth/rbac.py`
    - Add entry after existing `/api/v2/modules` entry
    - _Bug_Condition: isBugCondition_Bug3(input) where input.jwt_role="kiosk" AND input.path STARTS WITH "/api/v1/payments/qr-session" AND input.method="GET"_
    - _Expected_Behavior: check_role_path_access() returns None for kiosk GET requests to QR session paths_
    - _Preservation: Kiosk remains blocked from all other non-allowlisted paths_
    - _Requirements: 2.1, 2.2_

  - [x] 3.2 Add method-level restriction for kiosk QR session access (GET only)
    - In `check_role_path_access()`, add check after existing kiosk method restrictions
    - If path matches `/api/v1/payments/qr-session` prefix AND method is NOT GET, return denial message "Kiosk role has read-only access to QR payment sessions"
    - This ensures kiosk cannot call POST /expire endpoint via the allowlist bypass
    - _Bug_Condition: Kiosk POST/PUT/DELETE to qr-session paths must still be denied_
    - _Expected_Behavior: Non-GET methods to qr-session paths return denial for kiosk_
    - _Preservation: Only GET is allowed; POST/expire remains restricted to org_admin/salesperson at route handler level_
    - _Requirements: 2.5, 3.1_

  - [x] 3.3 Verify bug condition exploration test (Property 1 - RBAC portion) now passes
    - **Property 1: Expected Behavior** - Kiosk QR Session GET Access Allowed
    - **IMPORTANT**: Re-run the SAME RBAC test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior for kiosk GET access
    - When this test passes, it confirms the RBAC bug is fixed
    - Run bug condition exploration test from step 1 (RBAC portion)
    - **EXPECTED OUTCOME**: Test PASSES (confirms Bug 3 is fixed)
    - _Requirements: 2.1, 2.2, 2.5_

  - [x] 3.4 Verify preservation tests still pass
    - **Property 2: Preservation** - Kiosk RBAC Restrictions Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions in RBAC behavior)
    - Confirm kiosk is still blocked from non-allowlisted paths
    - Confirm non-kiosk roles still have full access to QR session endpoints
    - Confirm kiosk POST to qr-session paths is denied

- [ ] 4. Fix Bug 4: New backend endpoint + service function for existing invoice QR payment

  - [x] 4.1 Add `QrSessionExistingInvoiceRequest` schema to `app/modules/payments/schemas.py`
    - New Pydantic model with single field `invoice_id: UUID`
    - _Requirements: 2.4_

  - [x] 4.2 Create `create_qr_session_for_existing_invoice()` in `app/modules/payments/service.py`
    - Accepts `db`, `org_id`, `user_id`, `invoice_id`
    - Fetches invoice by ID scoped to org
    - Validates invoice status is in ("issued", "partially_paid", "overdue")
    - Validates `balance_due > 0`
    - Fetches org's `stripe_connect_account_id` (raises ValueError if not configured)
    - Retrieves Stripe secret key from encrypted storage
    - Calculates `amount_cents = int(balance_due * 100)` and application fee
    - Creates Stripe Checkout Session with metadata `{invoice_id, org_id, source: "kiosk_qr", platform: "orainvoice"}`
    - Upserts `pending_qr_sessions` row (delete existing for org, insert new)
    - Returns dict with `{session_id, invoice_id, invoice_number, amount, amount_cents, expires_at, currency}`
    - Does NOT modify the invoice (no status change, no re-issue)
    - After `db.flush()`, use `await db.refresh(obj)` before returning
    - _Bug_Condition: isBugCondition_Bug4(input) where invoice is unpaid with balance_due > 0 and Stripe connected_
    - _Expected_Behavior: Returns session details without modifying invoice_
    - _Preservation: Existing create_qr_payment_session() for InvoiceCreate flow unchanged_
    - _Requirements: 2.3, 2.4, 3.3_

  - [x] 4.3 Add `POST /api/v1/payments/qr-session/existing` route to `app/modules/payments/router.py`
    - Route with `require_role("org_admin", "salesperson")` dependency (NOT kiosk — kiosk only polls)
    - Accept `QrSessionExistingInvoiceRequest` body
    - Return `QrPaymentSessionResponse` (reuse existing schema)
    - Error handling: 400 for invalid invoice/status, 400 for Stripe not configured, 502 for Stripe API errors
    - Place route BEFORE the `/{session_id}/status` route to avoid path conflicts
    - _Bug_Condition: No endpoint existed for existing invoice QR payment_
    - _Expected_Behavior: Endpoint creates Checkout Session for invoice's balance_due_
    - _Preservation: Existing POST /qr-session route for InvoiceCreate unchanged_
    - _Requirements: 2.4, 3.3_

  - [x] 4.4 Verify bug condition exploration test (Property 1 - endpoint portion) now passes
    - **Property 1: Expected Behavior** - Existing Invoice QR Session Endpoint Works
    - **IMPORTANT**: Re-run the SAME endpoint test from task 1 - do NOT write a new test
    - When this test passes, it confirms the endpoint bug is fixed
    - **EXPECTED OUTCOME**: Test PASSES (confirms Bug 4 backend is fixed)
    - _Requirements: 2.4_

- [ ] 5. Fix Bug 4: Frontend QR Payment button on InvoiceDetail

  - [x] 5.1 Add "QR Payment" button to InvoiceDetail action toolbar
    - Add `qrPaymentLoading` state and `qrWaitingPopupOpen` state
    - Visibility logic: `canShowQrPayment = stripeStatus?.is_connected === true && ['issued', 'partially_paid', 'overdue'].includes(invoice?.status ?? '') && (invoice?.balance_due ?? 0) > 0`
    - Add button in action bar (after "Send Payment Link" or in appropriate position)
    - Use safe API consumption: `?.` and `?? []` / `?? 0` on all API data
    - _Bug_Condition: No QR Payment button existed on InvoiceDetail for unpaid invoices_
    - _Expected_Behavior: Button visible when invoice is unpaid, balance > 0, and Stripe connected_
    - _Preservation: Existing toolbar buttons (Edit, Duplicate, Void, Send Payment Link, etc.) unchanged_
    - _Requirements: 2.3, 3.4, 3.7_

  - [x] 5.2 Implement `handleQrPayment()` handler
    - Calls `POST /api/v1/payments/qr-session/existing` with `{invoice_id: invoice.id}`
    - On success: opens `QrPaymentWaitingPopup` (reuse existing component from InvoiceCreate flow)
    - On error: show toast notification with error message
    - On payment complete (popup callback): refresh invoice data to reflect updated payment status
    - _Requirements: 2.4, 3.3_

  - [x] 5.3 Hide QR Payment button when org has no Stripe Connect configured
    - Reuse `stripeStatus?.is_connected` check (same pattern as `canShowPaymentLink`)
    - Button hidden when `stripeStatus?.is_connected !== true`
    - _Requirements: 3.4_

- [x] 6. Verification checkpoint - Ensure all tests pass
  - Run RBAC property-based tests (exploration + preservation) — all should pass
  - Run backend unit tests for new service function
  - Verify kiosk GET to `/api/v1/payments/qr-session/pending` returns 200 (not 403)
  - Verify kiosk POST to `/api/v1/payments/qr-session/{id}/expire` returns 403
  - Verify org_admin/salesperson access to all QR session endpoints unchanged
  - Verify `POST /api/v1/payments/qr-session/existing` with valid invoice returns session details
  - Verify `POST /api/v1/payments/qr-session` (InvoiceCreate flow) still works unchanged
  - Verify InvoiceDetail renders QR Payment button when conditions met
  - Verify InvoiceDetail hides QR Payment button when Stripe not connected or invoice is draft/paid
  - Verify existing toolbar buttons on InvoiceDetail are unaffected
  - Ensure all tests pass, ask the user if questions arise
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_
