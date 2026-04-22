# Stripe Implementation Reference

Status: **Pending full implementation** — Stripe features are disabled in the org-facing UI.

---

## What Exists (Backend — DO NOT MODIFY)

### Stripe Connect OAuth (`app/integrations/stripe_connect.py`)
- `generate_connect_url(org_id)` — builds Stripe Connect OAuth authorisation URL
- `handle_connect_callback(code, state)` — exchanges auth code for connected account ID
- `create_payment_link(amount, currency, invoice_id, stripe_account_id, ...)` — creates Stripe Checkout Session
- `create_stripe_refund(payment_intent_id, amount, stripe_account_id)` — processes refund via Stripe API
- `verify_webhook_signature(payload, sig_header, webhook_secret)` — HMAC-SHA256 webhook verification

### Payments Service (`app/modules/payments/service.py`)
- `generate_stripe_payment_link(db, invoice_id, org_id)` — looks up org's Stripe account, creates checkout session, stores payment link
- `handle_stripe_webhook(db, event)` — processes `checkout.session.completed` and `payment_intent.succeeded` events
- `process_refund(db, payment_id, amount, reason, refunded_by, org_id)` — handles both Stripe and cash refunds
- `get_payment_history(db, invoice_id, org_id)` — returns payment records including refunds

### Payments Router (`app/modules/payments/router.py`)
- `POST /payments/cash` — record cash payment
- `POST /payments/stripe-link` — generate Stripe payment link for invoice
- `POST /payments/webhook/stripe` — Stripe webhook endpoint (no auth, signature-verified)
- `GET /payments/history/{invoice_id}` — payment history
- `POST /payments/refund` — process refund (Stripe or cash)

### Invoices Service (`app/modules/invoices/service.py`)
- `create_credit_note(db, invoice_id, ...)` — has `process_stripe_refund` flag for triggering Stripe refund from credit note

### Config (`app/config.py`)
- `stripe_secret_key` — Stripe API secret key (env fallback only; use DB helper)
- `stripe_connect_client_id` — Stripe Connect platform client ID (env fallback only; use DB helper)
- `stripe_webhook_secret` — webhook signing secret (env fallback only; use DB helper)

### Redirect URI
The Stripe Connect OAuth redirect URI is built dynamically from `FRONTEND_BASE_URL`:
`{FRONTEND_BASE_URL}/settings/online-payments`

This must match one of the URIs registered in Stripe Dashboard → Settings → Connect → OAuth → Redirects.

### Environment Variables (`.env`)
- `STRIPE_SECRET_KEY` — fallback only; credentials should be configured via Global Admin > Integrations
- `STRIPE_CONNECT_CLIENT_ID` — fallback only
- `STRIPE_WEBHOOK_SECRET` — fallback only

---

## What Exists (Frontend — Currently Disabled)

### Invoice Create (`frontend/src/pages/invoices/InvoiceCreate.tsx`)
- Stripe radio button in payment gateway selector — **disabled with "Coming soon" label**

### POS Payment Panel (`frontend/src/pages/pos/PaymentPanel.tsx`)
- Card payment tab text referenced Stripe terminal — **updated to generic "card terminal" text**

### Customer Portal Payment (`frontend/src/pages/portal/PaymentPage.tsx`)
- Full Stripe Checkout redirect page — **disabled with "Online payments coming soon" message**

### Template Editor (`frontend/src/pages/notifications/TemplateEditor.tsx`)
- `{{payment_link}}` variable described as "Stripe payment link" — **updated to "Online payment link (coming soon)"**

### Billing Settings (`frontend/src/pages/settings/Billing.tsx`)
- "Update payment method" button opens Stripe billing portal — **disabled with tooltip**
- Upgrade/downgrade plan buttons — **disabled with tooltip**

### Invoice List/Detail (`frontend/src/pages/invoices/InvoiceList.tsx`, `InvoiceDetail.tsx`)
- Payment method type includes `'stripe'` — **expanded to include all payment methods**

### Signup Types (`frontend/src/pages/auth/signup-types.ts`)
- `stripe_setup_intent_client_secret` in signup response — left as-is (backend contract)

---

## What Needs to Happen for Full Implementation

### Phase 1: Stripe Connect Onboarding
1. Build org settings page for Stripe Connect — "Connect your Stripe account" button
2. Implement OAuth callback handler page (`/settings/stripe/callback`)
3. Store connected account ID in `organisations.settings` JSONB
4. Show connection status (connected/disconnected) in org settings
5. Add ability to disconnect Stripe account

### Phase 2: Payment Collection
1. Re-enable Stripe radio button in InvoiceCreate when org has connected Stripe account
2. Re-enable portal PaymentPage — redirect to Stripe Checkout
3. Generate and store payment links on invoice creation when Stripe is selected
4. Populate `{{payment_link}}` template variable with actual Stripe checkout URL
5. Handle Stripe webhook events (payment success → mark invoice paid)

### Phase 3: Refunds
1. Build "Issue Refund" button on InvoiceDetail page
2. Build refund form/modal (amount, reason, full/partial)
3. Wire refund form to `POST /payments/refund` endpoint
4. Build "Issue Credit Note" button and form on InvoiceDetail
5. Wire credit note creation to trigger Stripe refund when applicable

### Phase 4: Billing & Subscriptions
1. Re-enable "Update payment method" button in Billing settings
2. Re-enable upgrade/downgrade buttons
3. Implement Stripe Customer Portal session creation on backend
4. Wire billing page to actual Stripe subscription data

### Phase 5: POS Integration
1. Integrate Stripe Terminal SDK for in-person card payments
2. Update POS PaymentPanel card tab to use Stripe Terminal
3. Handle terminal connection, payment processing, and receipts

---

## Files Reference

| Area | File | Notes |
|------|------|-------|
| Stripe Connect | `app/integrations/stripe_connect.py` | Core Stripe API integration |
| Payments Service | `app/modules/payments/service.py` | Business logic for payments + refunds |
| Payments Router | `app/modules/payments/router.py` | API endpoints |
| Invoices Service | `app/modules/invoices/service.py` | Credit note with Stripe refund flag |
| Config | `app/config.py` | Stripe env var bindings |
| Invoice Create | `frontend/src/pages/invoices/InvoiceCreate.tsx` | Payment gateway selector |
| POS Panel | `frontend/src/pages/pos/PaymentPanel.tsx` | Card payment UI |
| Portal Payment | `frontend/src/pages/portal/PaymentPage.tsx` | Customer-facing payment page |
| Template Editor | `frontend/src/pages/notifications/TemplateEditor.tsx` | Email/SMS template variables |
| Billing | `frontend/src/pages/settings/Billing.tsx` | Subscription billing page |
| Settings Nav | `frontend/src/pages/settings/Settings.tsx` | Settings sidebar (Billing tab) |
