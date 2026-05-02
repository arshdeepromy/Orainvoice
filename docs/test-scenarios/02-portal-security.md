# Test Scenarios: Portal Security

Covers Requirements 7-11 (security hardening) and 39-43 (advanced security).

---

## TS-2.1: Disabled portal blocks access

**Precondition:** Customer has `enable_portal = false` but a valid `portal_token`.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open `/portal/{token}` | Error: "Invalid or expired portal token" |
| 2 | Enable portal for the customer | Portal loads successfully |

**Req:** 7.1, 7.2, 7.3

---

## TS-2.2: Acceptance token not leaked in quotes response

**Precondition:** Customer has quotes with acceptance tokens.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal, click "Quotes" tab | Quotes load |
| 2 | Inspect Network response for `/portal/{token}/quotes` | No `acceptance_token` field in any quote object |
| 3 | Accept a quote via the portal | Quote acceptance works (server-side token lookup) |

**Req:** 8.1, 8.2, 8.3

---

## TS-2.3: Per-token rate limit (60/min)

**Precondition:** Valid portal token.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Send 60 requests to `/portal/{token}/invoices` within 1 minute | All 60 succeed (200) |
| 2 | Send the 61st request | Returns HTTP 429 with `Retry-After` header |
| 3 | Wait for the window to expire | Requests succeed again |

**Req:** 9.1, 9.3

---

## TS-2.4: Per-IP rate limit on token resolution (20/min)

**Precondition:** Multiple portal tokens.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Send 20 `GET /portal/{different-tokens}` from same IP within 1 minute | All succeed |
| 2 | Send the 21st token resolution request | Returns HTTP 429 |

**Req:** 9.2

---

## TS-2.5: Expired token rejected at service layer

**Precondition:** Customer has `portal_token_expires_at` set to yesterday.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open `/portal/{token}` | Error: "Invalid or expired portal token" |
| 2 | Update expiry to 30 days from now | Portal loads successfully |

**Req:** 10.1, 10.2, 10.3

---

## TS-2.6: Stripe Connect webhook processes payment

**Precondition:** Invoice with $230 balance, Stripe Connect configured.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Customer pays $230 via Stripe Checkout | Stripe sends `checkout.session.completed` webhook |
| 2 | Check invoice in admin panel | `amount_paid` = $230, `balance_due` = $0, `status` = "paid" |
| 3 | Check portal invoices tab | Invoice shows "Paid" badge |

**Req:** 11.1, 11.2, 11.3, 11.5

---

## TS-2.7: Partial payment via webhook

**Precondition:** Invoice with $500 balance.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Customer pays $200 via Stripe | Webhook received |
| 2 | Check invoice | `amount_paid` = $200, `balance_due` = $300, `status` = "partially_paid" |

**Req:** 11.4

---

## TS-2.8: Audit log records portal actions

**Precondition:** Valid portal session.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Accept a quote via portal | Audit log entry: `portal.quote_accepted` with customer ID and IP |
| 2 | Create a booking via portal | Audit log entry: `portal.booking_created` |
| 3 | Update profile via portal | Audit log entry: `portal.profile_updated` with before/after values |
| 4 | Cancel a booking via portal | Audit log entry: `portal.booking_cancelled` |
| 5 | Initiate a payment via portal | Audit log entry: `portal.payment_initiated` |

**Req:** 39.1, 39.2, 39.3, 39.4, 39.5

---

## TS-2.9: Portal session created on access

**Precondition:** Valid portal token.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal page | Page loads |
| 2 | Check cookies in dev tools | `portal_session` cookie exists (HttpOnly, Secure, SameSite=Lax) |
| 3 | Check `portal_csrf` cookie | Exists (non-HttpOnly, Secure) |

**Req:** 40.3, 40.4, 41.1

---

## TS-2.10: Sign Out clears session

**Precondition:** Active portal session.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Sign Out" button in portal header | Redirected to `/portal/signed-out` |
| 2 | Check confirmation page | Shows "You have been signed out" message |
| 3 | Check cookies | `portal_session` and `portal_csrf` cookies are cleared |
| 4 | Try to access portal endpoints | Requires re-authentication via token |

**Req:** 40.1, 40.2

---

## TS-2.11: Session inactivity timeout (4 hours)

**Precondition:** Active portal session.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Access portal | Session is active |
| 2 | Wait 4+ hours without activity | Next request fails (session expired) |
| 3 | Access portal via token link again | New session created |

**Req:** 40.3

---

## TS-2.12: CSRF protection on state-changing requests

**Precondition:** Active portal session with CSRF cookie.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Submit a booking via portal UI | Request includes `X-CSRF-Token` header matching cookie — succeeds |
| 2 | Use curl to POST without CSRF header | Returns HTTP 403: "Missing CSRF token" |
| 3 | Use curl with wrong CSRF token | Returns HTTP 403: "CSRF token mismatch" |

**Req:** 41.1, 41.2, 41.3

---

## TS-2.13: CSRF not required on webhook and logout

**Precondition:** Stripe webhook secret configured.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Send Stripe webhook POST (no CSRF header) | Processes normally (webhook exempt) |
| 2 | Call POST `/portal/logout` (no CSRF header) | Succeeds (logout exempt) |

**Req:** 41.3

---

## TS-2.14: Portal tokens use strong format

**Precondition:** Customer with portal disabled.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Enable portal for the customer | Token is generated |
| 2 | Check the token format | URL-safe string (~43 chars), not a UUID format |
| 3 | Existing UUID tokens still work | Old tokens resolve correctly until expiry |

**Req:** 42.1, 42.2, 42.3

---

## TS-2.15: Webhook signature validation

**Precondition:** Stripe Connect webhook secret configured.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Send webhook with valid signature | Processes successfully |
| 2 | Send webhook with invalid signature | Returns 400: signature verification failed |
| 3 | Send webhook without `Stripe-Signature` header | Returns 400: Missing Stripe-Signature |

**Req:** 11.1, 11.5

---

## TS-2.16: Webhook with unconfigured secret

**Precondition:** `stripe_connect_webhook_secret` is empty in settings.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Send webhook request | Returns 500: "Webhook verification not configured" |

**Req:** 11.5

---

## TS-2.17: Replay attack prevention

**Precondition:** Valid webhook signature.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Send webhook with timestamp older than 5 minutes | Returns 400: "too old" |

**Req:** 11.5

---

## TS-2.18: Portal audit log includes IP address

**Precondition:** Portal action performed from known IP.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Perform any portal action (e.g., update profile) | Check audit log |
| 2 | Verify `ip_address` field | Contains the client's IP address |

**Req:** 39.5

---

## TS-2.19: CSRF cookie is non-HttpOnly

**Precondition:** Active portal session.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open browser console | Run `document.cookie` |
| 2 | Check output | `portal_csrf` value is readable (non-HttpOnly) |
| 3 | Check `portal_session` | NOT readable (HttpOnly) |

**Req:** 41.1

---

## TS-2.20: GET endpoints don't require CSRF

**Precondition:** Active portal session.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Call GET `/portal/{token}/invoices` without CSRF header | Succeeds (200) |
| 2 | Call GET `/portal/{token}/jobs` without CSRF header | Succeeds (200) |

**Req:** 41.3

---

## TS-2.21: Org-level portal disable blocks all customers

**Precondition:** Org has `portal_enabled: false` in settings.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open any customer's portal link | Returns 403: "Customer portal is not available for this organisation" |
| 2 | Re-enable portal in org settings | Portal links work again |

**Req:** 46.1, 46.2

---

## TS-2.22: Multiple portal actions in sequence

**Precondition:** Active portal session.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Update profile email | Succeeds, audit logged |
| 2 | Accept a quote | Succeeds, audit logged, notification sent |
| 3 | Create a booking | Succeeds, audit logged, status = confirmed |
| 4 | Cancel the booking | Succeeds, audit logged |
| 5 | Check audit log | All 4 actions recorded with timestamps and IPs |

**Req:** 39.1-39.5
