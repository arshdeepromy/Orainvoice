# Bugfix Requirements Document

## Introduction

The kiosk QR payment feature (spec: kiosk-qr-payment) was implemented and all tasks marked complete, but manual testing revealed multiple critical bugs preventing the feature from working end-to-end. Two bugs have already been fixed (Bug 1: httpx async transport error — fixed by switching to `content=` with pre-encoded bytes + explicit Content-Type and Authorization headers; Bug 2: frontend amount type mismatch — fixed by adding `Number(session?.amount ?? 0)` in InvoiceCreate.tsx). Two bugs remain unfixed and are documented below.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the kiosk user (role="kiosk") polls `GET /api/v1/payments/qr-session/pending`, THEN the RBAC middleware (`app/middleware/rbac.py` → `check_role_path_access()` in `app/modules/auth/rbac.py`) returns 403 with message "Kiosk role can only access check-in and branding endpoints" because the path `/api/v1/payments/qr-session/pending` does not match any entry in `KIOSK_ALLOWED_PREFIXES` — the request never reaches the route handler's `require_role("org_admin", "salesperson", "kiosk")` dependency

1.2 WHEN the kiosk user (role="kiosk") polls `GET /api/v1/payments/qr-session/{session_id}/status`, THEN the RBAC middleware returns 403 for the same reason — `/api/v1/payments/qr-session/` is not in `KIOSK_ALLOWED_PREFIXES`

1.3 WHEN an invoice has already been issued (status "issued", "partially_paid", or "overdue") and the user views the Invoice Detail/List page, THEN there is no "QR Payment" button available to create a Stripe Checkout Session for that existing invoice's balance_due

1.4 WHEN a user wants to collect payment via QR for an existing unpaid invoice, THEN the only option is to create a brand new invoice via InvoiceCreate — there is no way to send an existing invoice to the kiosk for QR payment

### Expected Behavior (Correct)

2.1 WHEN the kiosk user (role="kiosk") polls `GET /api/v1/payments/qr-session/pending`, THEN the RBAC middleware SHALL allow the request through to the route handler (by including `/api/v1/payments/qr-session` in `KIOSK_ALLOWED_PREFIXES`), and the route handler's `require_role("org_admin", "salesperson", "kiosk")` dependency SHALL authorize the kiosk user

2.2 WHEN the kiosk user (role="kiosk") polls `GET /api/v1/payments/qr-session/{session_id}/status`, THEN the RBAC middleware SHALL allow the request through (same allowlist entry covers this path since it starts with `/api/v1/payments/qr-session`)

2.3 WHEN an invoice has status "issued", "partially_paid", or "overdue" AND the organisation has a non-null `stripe_connect_account_id`, THEN the Invoice Detail/List page SHALL display a "QR Payment" button that creates a Stripe Checkout Session for the invoice's current `balance_due` amount and stores it as a pending QR session for the kiosk to display

2.4 WHEN the "QR Payment" button on Invoice Detail/List is clicked for an existing invoice, THEN the system SHALL call a backend endpoint (e.g., `POST /api/v1/payments/qr-session/existing`) that accepts an `invoice_id`, retrieves the invoice's `balance_due`, creates a Stripe Checkout Session for that amount on the org's connected account, upserts a `pending_qr_sessions` row, and returns the session details — without re-issuing or modifying the invoice itself

2.5 WHEN the kiosk user (role="kiosk") attempts to access `POST /api/v1/payments/qr-session/{session_id}/expire`, THEN the RBAC middleware SHALL block the request because the kiosk role should only have read access to QR session data (GET endpoints), not the ability to expire sessions — the expire endpoint is restricted to org_admin and salesperson roles at the route handler level

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the kiosk user (role="kiosk") attempts to access any path NOT in the kiosk allowlist AND NOT starting with `/api/v1/payments/qr-session`, THEN the system SHALL CONTINUE TO return 403 Forbidden (kiosk remains restricted to its allowlist)

3.2 WHEN the org_admin or salesperson user polls the QR session endpoints (`/payments/qr-session/pending`, `/payments/qr-session/{id}/status`, `/payments/qr-session/{id}/expire`), THEN the system SHALL CONTINUE TO allow access as before (no regression for non-kiosk roles)

3.3 WHEN the "QR Payment" button on InvoiceCreate is clicked, THEN the system SHALL CONTINUE TO issue the invoice AND create the Checkout Session in one atomic action via `POST /api/v1/payments/qr-session` (existing behavior unchanged)

3.4 WHEN the organisation does not have a `stripe_connect_account_id` configured, THEN the "QR Payment" button SHALL CONTINUE TO be hidden on both InvoiceCreate and Invoice Detail/List pages

3.5 WHEN the kiosk user accesses `/api/v1/kiosk/`, `/api/v1/org/settings` (GET), `/api/v1/customers` (POST), `/api/v1/auth/me`, `/api/v1/auth/refresh`, or `/api/v2/modules`, THEN the system SHALL CONTINUE TO allow access (existing kiosk allowlist paths unchanged)

3.6 WHEN the webhook handler receives a `checkout.session.completed` event with `source: "kiosk_qr"` metadata, THEN the system SHALL CONTINUE TO record the payment and clear the pending QR session (webhook path unaffected by these fixes)

3.7 WHEN the InvoiceList split-panel page renders with its existing toolbar (Edit, Send, Share, PDF/Print, Record Payment, More menu), THEN the system SHALL CONTINUE TO display all existing buttons and functionality without regression — the new QR Payment button is additive only

---

## Bug Condition Derivation

### Bug 3: Kiosk RBAC Path Restriction

**Root Cause (verified by reading code):** `KIOSK_ALLOWED_PREFIXES` in `app/modules/auth/rbac.py` (line ~210) is a tuple of path prefixes. The `check_role_path_access()` function (line ~380) checks `if not _matches_any_prefix(path, KIOSK_ALLOWED_PREFIXES)` for the kiosk role and returns a denial message. The QR payment endpoints at `/api/v1/payments/qr-session/...` are not in this tuple.

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type HttpRequest
  OUTPUT: boolean
  
  RETURN X.jwt_role = "kiosk" 
    AND X.path STARTS WITH "/api/v1/payments/qr-session"
    AND X.method = "GET"
END FUNCTION
```

```pascal
// Property: Fix Checking — Kiosk QR Payment Polling Access
FOR ALL X WHERE isBugCondition(X) DO
  result ← RBACMiddleware'(X)
  ASSERT result.denial_reason = None
  ASSERT request proceeds to route handler
END FOR
```

```pascal
// Property: Preservation Checking — Kiosk Still Restricted Elsewhere
FOR ALL X WHERE X.jwt_role = "kiosk" 
  AND NOT (X.path STARTS WITH "/api/v1/payments/qr-session" AND X.method = "GET")
  AND X.path NOT IN KIOSK_ALLOWED_PREFIXES DO
  ASSERT RBACMiddleware(X).denial_reason = RBACMiddleware'(X).denial_reason
END FOR
```

### Bug 4: Missing QR Payment on Invoice Detail

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type InvoiceDetailView
  OUTPUT: boolean
  
  RETURN X.invoice.status IN {"issued", "partially_paid", "overdue"}
    AND X.invoice.balance_due > 0
    AND X.org.stripe_connect_account_id IS NOT NULL
END FUNCTION
```

```pascal
// Property: Fix Checking — QR Payment Button Visible on Invoice Detail
FOR ALL X WHERE isBugCondition(X) DO
  ui ← InvoiceDetailPage'(X)
  ASSERT ui CONTAINS "QR Payment" button
  ASSERT clicking button calls POST /payments/qr-session/existing with {invoice_id: X.invoice.id}
  ASSERT response contains {session_id, amount, invoice_number, expires_at}
END FOR
```

```pascal
// Property: Preservation Checking — InvoiceCreate QR Button Unchanged
FOR ALL X DO
  ASSERT InvoiceCreatePage(X) = InvoiceCreatePage'(X)
END FOR
```
