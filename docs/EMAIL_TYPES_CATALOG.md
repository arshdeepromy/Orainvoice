# Email Types Catalog

**Generated:** 2026-05-27 — exhaustive audit of every outbound email the application sends.

This document enumerates every email type the system produces, whether it is **automatic** (fired by a schedule or a system event) or **user-initiated** (a person clicks a button), who receives it, and exactly where in the code it originates.

## Delivery architecture (how every email is sent)

Every outbound email — without exception — funnels through the unified sender:

- **`app/integrations/email_sender.py::send_email(db, message, ...)`** — the single dispatch point. Reads the `email_providers` table, attempts each active provider in priority order, and fails over on error. `smtplib` is imported in **this file only**; no module rolls its own SMTP loop anymore.
- **`app/tasks/notifications.py::send_email_task(...)`** → `_send_email_async` → `send_email(...)`. A thin wrapper used by sites that also want a `notification_log` row written. Not a Celery task (the decorator was removed); it's a plain async function.

Two send styles therefore exist:
1. **Direct** — caller builds an `EmailMessage` and calls `send_email(db, message)` itself (used by invoice/quote/payment/auth/booking/vehicle-report paths that need attachments or bespoke failure handling).
2. **Via `send_email_task`** — caller passes `template_type`, `to_email`, `subject`, `html_body`; the task logs to `notification_log` and dispatches (used by portal, subscription, reminder, and notification-rule paths).

Every send records a `notification_log` row (channel `email`) with a `status` of `queued`/`sent`/`failed` and the `template_type` below.

---

## 1. Transactional document delivery (USER-INITIATED)

A person clicks "Send" / "Email" in the UI. Usually carries a PDF.

| # | Email | `template_type` | Recipient | PDF? | Trigger | Source |
|---|---|---|---|---|---|---|
| 1 | **Invoice** | `invoice_send` / `invoice_issued` | Customer | ✅ Invoice PDF | User clicks "Save & Send" on an invoice | [invoices/service.py:4046 `email_invoice`](app/modules/invoices/service.py#L4046), send at [L4610](app/modules/invoices/service.py#L4610). Subject: `Invoice {n} from {org}` |
| 2 | **Payment-link request** | `invoice_issued` | Customer | ❌ | User clicks "Send Payment Link" on an issued invoice | [payments/service.py:349 `send_invoice_payment_link_email`](app/modules/payments/service.py#L349), send at [L719](app/modules/payments/service.py#L719). Subject: `Payment link for invoice {n} from {org}` |
| 3 | **Quote** | `quote_send` / `quote_sent` | Customer | ✅ Quote PDF | User clicks "Save & Send" on a quote | [quotes/service.py:1123](app/modules/quotes/service.py#L1123). Subject: `Quote {n} from {org}` |
| 4 | **Payment receipt** | `payment_receipt` / `payment_received` | Customer | ✅ Receipt PDF | Auto after a payment is recorded, or user re-sends | [payments/service.py:497 `_send_receipt_email`](app/modules/payments/service.py#L497), send at [L719](app/modules/payments/service.py#L719). Subject: `Payment receipt for invoice {n}` |
| 5 | **Vehicle service-history report** | `vehicle_report_send` | Customer | ✅ Report PDF | User emails a vehicle's service history | [vehicles/report_service.py:293 `email_service_history_report`](app/modules/vehicles/report_service.py#L293), send at [L455](app/modules/vehicles/report_service.py#L455). Subject: `{rego} - Service History Report` |
| 6 | **Booking confirmation** | `booking_confirmation` | Customer | ❌ | Auto when a booking is created/confirmed | [bookings/service.py:1099 `_send_booking_confirmation_email`](app/modules/bookings/service.py#L1099), send at [L1272](app/modules/bookings/service.py#L1272). Subject: `Booking Confirmation — {service} on {date}` |

---

## 2. Authentication & security (MIXED)

| # | Email | `template_type` | Recipient | Trigger | Auto/User | Source |
|---|---|---|---|---|---|---|
| 7 | **MFA / email OTP** | (logged ad-hoc) | The signing-in user | User triggers an MFA email-OTP challenge during login or email change | **User-initiated** | [auth/mfa_service.py:370 `_send_email_otp`](app/modules/auth/mfa_service.py#L370), send at [L439](app/modules/auth/mfa_service.py#L439). Subject: `Your {platform} verification code`. **Raises `RuntimeError` on total failure** (the MFA contract requires the OTP to be delivered). `org_id=None` (user-scoped). |
| 8 | **Password reset** | `password_reset` | The requesting user | User clicks "Forgot password?" | **User-initiated** | [auth/service.py:2172 `_send_password_reset_email`](app/modules/auth/service.py#L2172), send at [L2325](app/modules/auth/service.py#L2325). Subject: `Reset your {org} password` |
| 9 | **User / staff invitation** | `user_invitation` | Invited staff member | An admin invites a user to the org | **User-initiated** | [auth/service.py:2939 `_send_invitation_email`](app/modules/auth/service.py#L2939), send at [L3086](app/modules/auth/service.py#L3086). Subject: `You've been invited to join {org} on OraInvoice`. Dev fallback logs the invite URL when no provider is configured. |
| 10 | **Org-admin invitation** | `org_admin_invitation` | New org admin | Platform admin provisions a new organisation/admin | **User-initiated** (platform admin) | [admin/service.py:476](app/modules/admin/service.py#L476) via `send_email_task` |
| 11 | **Email verification (signup)** | `user_invitation` (logged) | New signup user | User signs up → verify-email link | **User-initiated** | [auth/service.py:3258 `send_verification_email`](app/modules/auth/service.py#L3258), send at [L3377](app/modules/auth/service.py#L3377). Subject: `Welcome to OraInvoice — Verify your email` |
| 12 | **Paid-plan signup receipt + verify** | (logged) | New paid signup user | After a paid-plan signup payment succeeds | **Auto** (post-payment) | [auth/service.py:3467 `send_receipt_email`](app/modules/auth/service.py#L3467), send at [L3657](app/modules/auth/service.py#L3657). Subject: `OraInvoice — Payment receipt & email verification` |
| 13 | **Account-lockout notice** | (logged) | Locked-out user | Account hits the permanent-lockout threshold | **Auto** (security event) | [auth/service.py:363 `_send_permanent_lockout_email`](app/modules/auth/service.py#L363), send at [L478](app/modules/auth/service.py#L478). Subject: `Your {platform} account has been locked`. `async_session_factory` (runs outside request). |
| 14 | **Anomalous-login alert** | (logged) | Affected user | Login detected from an unusual device/location | **Auto** (security event) | [auth/service.py:640 `_send_anomalous_login_alert`](app/modules/auth/service.py#L640), send at [L799](app/modules/auth/service.py#L799). Subject: `Security alert: unusual sign-in to your OraInvoice account` |
| 15 | **Token-reuse / replay alert** | (logged) | Affected user | A refresh-token replay is detected | **Auto** (security event) | [auth/service.py:1029 `_send_token_reuse_alert`](app/modules/auth/service.py#L1029), send at [L1137](app/modules/auth/service.py#L1137). Subject: `Security alert: refresh token replay detected` |
| 16 | **Fleet-portal invitation** | `fleet_portal_invite` | Fleet operator contact | Workshop admin invites a B2B fleet operator | **User-initiated** | [fleet_portal/admin_router.py:1231](app/modules/fleet_portal/admin_router.py#L1231) via `send_email_task` |

---

## 3. Customer engagement (USER-INITIATED)

| # | Email | `template_type` | Recipient | Trigger | Source |
|---|---|---|---|---|---|
| 17 | **Ad-hoc customer message** | `customer_notify` | Customer | User sends a custom message from the customer record (email channel) | [customers/service.py:652 `notify_customer`](app/modules/customers/service.py#L652), send at [L762](app/modules/customers/service.py#L762). Uses `org_name` as the from-name override. |
| 18 | **Customer portal access link** | `portal_link` | Customer | User issues / re-issues a customer-portal login link | [customers/service.py:2294 `send_portal_link`](app/modules/customers/service.py#L2294), send at [L2321](app/modules/customers/service.py#L2321). Subject: `Your Portal Access Link — {org}` |

---

## 4. Portal-originated notifications (AUTO — fired by a customer action on the public portal)

These notify the **workshop**, triggered when a customer does something on the public portal.

| # | Email | `template_type` | Recipient | Trigger | Source |
|---|---|---|---|---|---|
| 19 | **Quote accepted** | `quote_accepted` | Workshop | Customer accepts a quote via the portal | [portal/service.py:1397](app/modules/portal/service.py#L1397) |
| 20 | **Portal booking created** | `portal_booking_created` | Workshop | Customer books via the portal | [portal/service.py:1496](app/modules/portal/service.py#L1496) |
| 21 | **DSAR request** | `dsar_request` | Workshop / DPO | Customer submits a data-subject-access request | [portal/service.py:2160](app/modules/portal/service.py#L2160) |
| 22 | **Portal link recovery** | `portal_recovery` | Customer | Customer requests recovery of a lost portal link | [portal/service.py:2276](app/modules/portal/service.py#L2276) |

---

## 5. Scheduled reminders (AUTO — Celery Beat / scheduled tasks)

Fired on a recurring schedule (typically daily). No human in the loop.

| # | Email | `template_type` | Recipient | Trigger | Source |
|---|---|---|---|---|---|
| 23 | **Overdue-payment reminder** | `payment_overdue_reminder` | Customer | Invoice is N days past due (per org rule) | [notifications/service.py:1159 `process_overdue_reminders`](app/modules/notifications/service.py#L1159), send at [L1268](app/modules/notifications/service.py#L1268) |
| 24 | **WOF expiry reminder** | `wof_expiry_reminder` | Customer | Vehicle WOF expires within the configured window | [notifications/service.py:1431 `process_wof_rego_reminders`](app/modules/notifications/service.py#L1431), send at [L1596](app/modules/notifications/service.py#L1596) |
| 25 | **COF expiry reminder** | `cof_expiry_reminder` | Customer | Vehicle COF expires within the window | same function as #24 |
| 26 | **Registration (rego) expiry reminder** | `registration_expiry_reminder` | Customer | Vehicle registration expires within the window | same function as #24 |
| 27 | **Customer-configured reminders** | `customer_{reminder_type}_reminder` | Customer | Per-customer reminder config (service-due / WOF / COF) reaches its target date | [notifications/service.py:2028 `process_customer_reminders`](app/modules/notifications/service.py#L2028), send at [L2304](app/modules/notifications/service.py#L2304); also [reminder_queue_service.py:643](app/modules/notifications/reminder_queue_service.py#L643) |
| 28 | **Scheduled-entry reminder** | `schedule_reminder` | Org user / staff | A calendar/scheduled entry is starting soon | [tasks/scheduled.py:268](app/tasks/scheduled.py#L268). Subject: `Reminder: {title} starting soon` |
| 29 | **Compliance-document expiry** | `compliance_expiry_{threshold}` | Org admin | A compliance document nears its expiry threshold | [compliance_docs/notification_service.py:243 `_dispatch_email`](app/modules/compliance_docs/notification_service.py#L243). Subject: `Compliance Document {urgency}: {doc_type}` |
| 30 | **Generic notification-rule dispatch** | `notif.template_type` (dynamic) | Varies | A queued in-app notification rule is flushed to email | [tasks/scheduled.py:97](app/tasks/scheduled.py#L97); rule engine at [notifications/service.py:1268, 1596](app/modules/notifications/service.py#L1268) |

---

## 6. Recurring / automation (AUTO)

| # | Email | `template_type` | Recipient | Trigger | Source |
|---|---|---|---|---|---|
| 31 | **Recurring-invoice generated** | `recurring_invoice_generated` | Org user (and/or customer) | A recurring-invoice schedule auto-generates a new invoice | [invoices/service.py:3708, 3847](app/modules/invoices/service.py#L3708). Subject: `Recurring invoice generated: {n}` |

---

## 7. Platform billing / subscription (AUTO — platform → org admin)

These are OraInvoice-the-platform emailing the workshop's billing admin about their **subscription** (distinct from the workshop's own customer invoices).

| # | Email | `template_type` | Recipient | Trigger | Source |
|---|---|---|---|---|---|
| 32 | **Subscription payment receipt** | `billing_receipt` | Org billing admin | A recurring subscription charge succeeds | [tasks/subscriptions.py:404 `_send_billing_receipt_email`](app/tasks/subscriptions.py#L404), send at [L489](app/tasks/subscriptions.py#L489). Subject: `Your OraInvoice subscription payment receipt — ${amt} NZD` |
| 33 | **Subscription invoice** | `subscription_invoice` | Org billing admin | A subscription invoice is issued | [tasks/subscriptions.py:736 `send_invoice_email_task`](app/tasks/subscriptions.py#L736), send at [L760](app/tasks/subscriptions.py#L760). Subject: `Your WorkshopPro NZ invoice — ${amt} NZD` |
| 34 | **Trial-expiry reminder** | `trial_expiry_reminder` | Org billing admin | Free trial ends in N days | [tasks/subscriptions.py:552 `_send_trial_reminder`](app/tasks/subscriptions.py#L552), send at [L567](app/tasks/subscriptions.py#L567). Subject: `Your WorkshopPro NZ trial ends in N day(s)` |
| 35 | **Dunning — payment failed** | `dunning_payment_failed` | Org billing admin | A subscription charge fails (per attempt) | [tasks/subscriptions.py:768 `send_dunning_email_task`](app/tasks/subscriptions.py#L768), send at [L793](app/tasks/subscriptions.py#L793). Subject: `Payment failed for {org} — action required` |
| 36 | **Suspension warning / notice** | `suspension_{email_type}` | Org billing admin | Account approaches or enters suspension | [tasks/subscriptions.py:902 `send_suspension_email_task`](app/tasks/subscriptions.py#L902), send at [L929](app/tasks/subscriptions.py#L929) |
| 37 | **Saved-card expiry warning** | `card_expiry_warning` | Org billing admin | A saved payment card is expiring | [tasks/scheduled.py:731](app/tasks/scheduled.py#L731) |

---

## 8. Franchise / multi-branch (AUTO — fired by a stock-transfer action)

| # | Email | `template_type` | Recipient | Trigger | Source |
|---|---|---|---|---|---|
| 38 | **Stock-transfer event** | `transfer_{action}` | Source/destination branch admins | A stock transfer is created/approved/rejected/executed/received | [franchise/service.py:132 `_notify_transfer_event`](app/modules/franchise/service.py#L132), send at [L247](app/modules/franchise/service.py#L247). Subject: `{action_label}: {source} → {dest} (qty {n})`. `{action}` ∈ approve / reject / execute / receive. |

---

## 9. Internal / platform operations

| # | Email | `template_type` | Recipient | Trigger | Source |
|---|---|---|---|---|---|
| 39 | **Demo request notification** | (none — direct send) | Internal sales inbox (`DEMO_REQUEST_RECIPIENT`) | Visitor submits the public landing-page demo form | [landing/router.py:57 `submit_demo_request`](app/modules/landing/router.py#L57), send at [L146](app/modules/landing/router.py#L146). Subject: `New Demo Request from {name} — {business}`. `org_id=None` (no tenant context). |

---

## Summary counts

| Category | Count | Trigger profile |
|---|---|---|
| Transactional document delivery | 6 | User-initiated (one auto: receipt) |
| Authentication & security | 10 | Mixed — 6 user-initiated, 4 automatic (lockout, anomalous login, token-reuse, paid receipt) |
| Customer engagement | 2 | User-initiated |
| Portal-originated notifications | 4 | Automatic (customer action) |
| Scheduled reminders | 8 | Automatic (Celery Beat) |
| Recurring / automation | 1 | Automatic |
| Platform billing / subscription | 6 | Automatic (platform → org admin) |
| Franchise / multi-branch | 1 | Automatic (transfer action) |
| Internal / platform ops | 1 | Automatic (visitor action) |
| **Total distinct email types** | **~39** | |

### Trigger breakdown

- **User-initiated** (a person clicks something): invoice, payment-link, quote, vehicle report, MFA OTP, password reset, user invite, org-admin invite, email verification, fleet-portal invite, ad-hoc customer message, customer portal link. **(~12)**
- **Automatic — system/scheduled**: payment receipt, booking confirmation, recurring-invoice, all 8 scheduled reminders, all portal-originated notifications, all 6 subscription/billing emails, transfer events, lockout/anomalous-login/token-reuse security alerts, paid-signup receipt, demo-request. **(~27)**

---

## Notes & observations

1. **Single dispatch point.** Every email — transactional, security, scheduled, billing — resolves through `email_sender.py::send_email()`. Multi-provider failover therefore applies uniformly to all 39 types. (This is the completed state of the `email-provider-unification` spec.)
2. **MFA OTP is the only type that hard-fails the caller.** `_send_email_otp` raises `RuntimeError` on total send failure because the MFA challenge contract depends on delivery. Every other path degrades gracefully (logs failure, returns a `SendResult` with `success=False`).
3. **Three emails have no org context** (`org_id=None`): MFA OTP (user-scoped), the demo-request notification (public form), and the auth security alerts that run outside a request. These cannot raise an in-app "email failed" notification — failure is log-only.
4. **`template_type` is the canonical key** stored on each `notification_log` row and used for template lookup/override and dedup. Reminder paths dedup on a composite subject key (e.g. `overdue_rule_{rule_id}_{invoice_id}`, `{template_type}_{org_id}_{cv_id}_{expiry_date}`) to avoid resending.
5. **Two billing brand names appear** in subject lines: "OraInvoice" and "WorkshopPro NZ" (subscription/trial/dunning emails). Worth confirming this is intentional and not stale copy.
6. **Platform-billing emails (#32–37) target the org's billing admin, not customers** — they're about the workshop's own subscription to the platform, a separate concern from the workshop's customer-facing invoices (#1).
