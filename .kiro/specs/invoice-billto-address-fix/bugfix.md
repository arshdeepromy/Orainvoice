# Bugfix Requirements Document

## Introduction

The "Bill To" block on invoices and quotes does not display the customer's saved address across several rendering surfaces. The Edit Customer modal writes the address into the structured `customers.billing_address` JSONB column (`street`, `city`, `state`, `postal_code`, `country`), but the legacy plain-text `customers.address` column is almost always empty.

Three of the surfaces that build the customer "address" string for rendering already include a fallback that reads `billing_address` JSONB when the plain `address` column is empty (the in-app invoice preview via `get_invoice`, and the authenticated invoice PDF via `generate_invoice_pdf`). However, several other surfaces only read the plain `customers.address` column and therefore show **no address at all** when the customer's address was entered through the modal:

1. **Public / shared invoice view + public invoice PDF** (`app/modules/invoices/public_router.py`) — builds `customer_context` with an `address` key sourced from `customer.address` only (no `billing_address` fallback). Separately, this context omits `display_name` and `company_name` even though `invoice_share.html` renders them.
2. **Quote PDF (authenticated)** (`app/modules/quotes/service.py`) — builds `customer_context` with an `address` key sourced from `customer.address` only. The `quote.html` template already renders `customer.address`.
3. **Quote PDF / public quote view** (`app/modules/quotes/public_router.py`) — builds `customer_context` with **no `address` key at all**, and the `quote_share.html` template has **no address line** in its "Prepared For" block. Both the context AND the template must change for the address to appear.

The root issue is duplicated, inconsistent address-resolution logic spread across the customer-rendering call sites. The two invoice paths in `app/modules/invoices/service.py` have the `billing_address` JSONB fallback; the public invoice and quote paths do not. The fix centralises the resolution into one shared helper and calls it from every rendering site, plus a one-line template addition for `quote_share.html`.

**Out of scope:**
- The large-invoice buyer-address compliance check (Req 80.2) in `app/modules/invoices/service.py` is intentionally left unchanged in this bugfix.
- The in-app quote preview (`frontend-v2/src/pages/quotes/QuoteDetail.tsx`) renders only customer name + email client-side and shows no address today; surfacing an address there is a separate, pre-existing limitation and is not part of this fix (the quote PDF is the address-bearing artifact).

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a customer's address is saved via the Edit Customer modal THEN the system stores it in the structured `customers.billing_address` JSONB column and leaves the plain-text `customers.address` column empty

1.2 WHEN a shared/public invoice is viewed (HTML page or public PDF) AND the customer's address exists only in `billing_address` JSONB THEN the "Bill To" block displays no address

1.3 WHEN a quote PDF is generated (authenticated path) AND the customer's address exists only in `billing_address` JSONB THEN the "Bill To" block displays no address

1.4 WHEN a public quote is viewed/downloaded AND the customer's address exists only in `billing_address` JSONB THEN the "Bill To" block displays no address

1.5 WHEN the structured `billing_address` JSONB is the only address source THEN each of the rendering surfaces resolves the address independently, with inconsistent results (the two invoice-detail/PDF paths show it; the public invoice and quote paths do not)

### Expected Behavior (Correct)

2.1 WHEN any invoice or quote "Bill To" block is rendered (in-app preview, authenticated PDF, public/shared invoice, authenticated quote PDF, public quote) AND the customer has an address in EITHER the plain `customers.address` column OR the structured `customers.billing_address` JSONB THEN the system SHALL display that address in the "Bill To" block

2.2 WHEN both `customers.address` (plain text) and `customers.billing_address` (JSONB) are present THEN the system SHALL prefer the plain-text `customers.address` value (existing precedence preserved)

2.3 WHEN only `customers.billing_address` JSONB is present THEN the system SHALL build a single comma-separated address string from the non-empty parts in order: `street`, `city`, `state`, `postal_code`, `country`

2.4 WHEN neither address source has any content THEN the system SHALL resolve the address to `None`/empty and the "Bill To"/"Quote To"/"Prepared For" block SHALL omit the address line (no empty line, no placeholder)

2.5 WHEN the address is resolved for any surface THEN all rendering surfaces SHALL use a single shared helper so resolution is identical everywhere

2.6 WHEN the public quote (`quote_share.html`) "Prepared For" block is rendered AND the customer has a resolvable address THEN the template SHALL display the address (the template currently has no address line and SHALL be updated to add one)

2.7 WHEN the public invoice `customer_context` is built THEN it SHALL include `display_name` and `company_name` so `invoice_share.html` renders the customer's company name and preferred display name (matching the authenticated invoice surfaces)

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a customer has an address in the plain `customers.address` column THEN the system SHALL CONTINUE to display that exact value (no reformatting of an already-populated plain address)

3.2 WHEN the in-app invoice preview (`get_invoice`) and the authenticated invoice PDF (`generate_invoice_pdf`) render the "Bill To" block THEN the system SHALL CONTINUE to display the same address it does today (these two paths already have the fallback; behaviour must be identical after centralisation)

3.3 WHEN the "Bill To" block renders the customer name, company name, email, and phone THEN the system SHALL CONTINUE to render those fields exactly as today (only address resolution changes)

3.4 WHEN a customer has no address in either source THEN the system SHALL CONTINUE to render the rest of the "Bill To" block without error

3.5 WHEN the structured `billing_address` JSONB contains only empty-string values (`{"street": "", "city": "", ...}`) THEN the system SHALL treat it as no address (resolve to `None`), matching today's behaviour in the paths that already have the fallback

3.6 WHEN the large-invoice buyer-address compliance check (Req 80.2) evaluates an invoice THEN the system SHALL CONTINUE to behave exactly as today (this check is out of scope and intentionally unchanged)

3.7 WHEN the in-app quote preview (`QuoteDetail.tsx`) renders the "Quote To" block THEN it SHALL CONTINUE to behave as today (name + email only); surfacing an address in the on-screen quote preview is out of scope

3.8 WHEN the public-quote template change adds the address line THEN the existing name, email, and phone lines in the "Prepared For" block SHALL CONTINUE to render unchanged
