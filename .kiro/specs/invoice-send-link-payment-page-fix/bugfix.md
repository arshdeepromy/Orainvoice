# Bugfix — "Send Invoice" email links to payment page instead of invoice view

## Summary

The "Send Invoice" action on the invoice detail page emails the customer a
"View Invoice" button that links to the **payment page** (`/pay/{token}`)
instead of the **public invoice HTML view** (`/api/v1/public/invoice/{token}`).
Once an invoice is settled, the payment page renders "Paid" / payment info, so
the customer sees a payment-status page rather than their invoice.

## Reported Condition

- Environment: Local Prod Standby (`invoicing-standby-prod`, port 8082, DB `workshoppro`).
- Customer: **Iqbal singh Pannu**, invoice **SPINV-0050**.
- DB state confirmed: `status = paid`, `payment_gateway = cash`, `balance_due = 0.00`,
  `payment_page_url` present, `share_token` present.
- The link sent to the customer rendered the payment page showing "Paid",
  not the invoice. The correct link is the one produced by the **Share** button.

## Bug Condition C(X)

For an invoice send email produced by `email_invoice`:

> **C(X): the "View Invoice" CTA URL points at the `/pay/{token}` payment page
> (derived from `invoice.payment_page_url`) rather than the public invoice
> view `/api/v1/public/invoice/{share_token}`.**

The bug is present whenever the email CTA URL contains `/pay/` (payment page)
for an invoice-send email. The fix must ensure the CTA URL is always the
invoice-view URL.

## Root Cause

In `app/modules/invoices/service.py :: email_invoice` the CTA was chosen as:

```python
# template path
_payment_cta_url = _rendered_template.cta_url or payment_page_url or ""
# hardcoded fallback path
_payment_cta_url = payment_page_url or ""
```

and the `invoice_issued` template variable was:

```python
"payment_link": payment_page_url or "",
```

The default `invoice_issued` email template's button is labelled
"View Invoice" but its URL is `{{payment_link}}` (see
`app/modules/notifications/schemas.py` DEFAULT_EMAIL_TEMPLATES). So both the
template path and the hardcoded fallback resolved the "View Invoice" button to
the payment page. The public invoice-view URL (`/api/v1/public/invoice/{token}`)
was only used as a last-resort fallback when no payment page URL existed.

Introduced in v1.9.2 (commit `5f770f1`, 2026-05-18, notification-template
integration).

## Fix

Build the public invoice-view URL up front in `email_invoice` (minting a
`share_token` on the invoice if one does not yet exist — the same token the
Share button uses), and use it:

1. as the `payment_link` template variable (so the default "View Invoice"
   button resolves to the invoice view), and
2. as the CTA URL for both the template path and the hardcoded fallback path.

The public invoice-view page (`app/modules/invoices/public_router.py`) still
renders its own "Pay Online" button while the invoice is payable (status in
issued / overdue / partially_paid AND a payment_page_url exists), so online
payment remains reachable for unpaid invoices. The stale-payment-link
regeneration block is retained because that page reads `invoice.payment_page_url`.

The dedicated **"Send Payment Link"** action
(`app/modules/payments/service.py :: send_invoice_payment_link_email`) is
intentionally **unchanged** — it builds its own variables and correctly sends
the payment page.

## Preservation (must NOT change)

- "Send Payment Link" flow still sends the `/pay/{token}` payment page.
- QR payment flow unchanged.
- "Share" button still produces `/api/v1/public/invoice/{token}`.
- Stale-link regeneration of `invoice.payment_page_url` still runs so the
  invoice-view page's "Pay Online" button keeps working.
- Email failover / notification-log / in-app-notification behaviour unchanged.

## Verification

- New regression test `tests/test_invoice_email_cta_link.py`:
  - paid cash invoice (the SPINV-0050 scenario) → CTA is invoice-view URL, not `/pay/`.
  - issued stripe invoice → CTA is invoice-view URL.
  - missing share_token → token minted, CTA is an invoice-view URL.
  - Confirmed the tests FAIL on the unfixed code and PASS with the fix.

## Files Changed

- `app/modules/invoices/service.py` (`email_invoice` CTA + template variable)
- `tests/test_invoice_email_cta_link.py` (new regression test)
- `docs/ISSUE_TRACKER.md` (ISSUE-169)
