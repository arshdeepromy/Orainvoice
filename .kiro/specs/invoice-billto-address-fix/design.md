# Invoice/Quote Bill-To Address Fix — Bugfix Design

## Overview

The customer address shown in the "Bill To" block is resolved in several separate places. The two invoice paths (in-app preview via `get_invoice`, authenticated PDF via `generate_invoice_pdf`) already fall back from the empty plain-text `customers.address` column to the structured `customers.billing_address` JSONB; the public invoice and quote paths do not. The fix introduces one shared helper, `resolve_customer_display_address(customer)`, in the customers module and calls it from the rendering sites, removing the duplicated/inconsistent logic.

The large-invoice buyer-address compliance check (Req 80.2) is **out of scope** and left unchanged.

## Glossary

- **Bug_Condition (C)**: The conditions under which a "Bill To" address is incorrectly omitted — namely, the customer's address lives only in `billing_address` JSONB and the rendering surface only reads the plain `address` column.
- **Property (P)**: The desired correct behavior — every rendering surface resolves the address from plain `address` first, then the structured `billing_address` JSONB fallback, with identical results.
- **Preservation**: Behaviors that must remain unchanged — plain `address` precedence, the two already-correct invoice paths, name/company/email/phone rendering, and the Req 80.2 compliance check (out of scope).
- **Plain address**: `customers.address` — a nullable `Text` column (legacy).
- **Structured address**: `customers.billing_address` — a JSONB object with keys `street`, `city`, `state`, `postal_code`, `country`.
- **Surface**: A code path that builds a customer "address" string for output or validation.

## Bug Details

### Bug Condition

The bug manifests when a customer's address exists only in the structured `billing_address` JSONB (the plain `address` column is empty), and the surface rendering the "Bill To" block reads only the plain column.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type {
    surface: 'public_invoice' | 'quote_pdf' | 'public_quote'
             | 'invoice_preview' | 'invoice_pdf',
    customer: { address: string | null, billing_address: dict | null }
  }
  OUTPUT: boolean

  has_plain := input.customer.address IS NOT NULL AND trim(input.customer.address) != ""
  has_structured := input.customer.billing_address IS A DICT
                    AND ANY value in input.customer.billing_address is non-empty

  // Surfaces that currently lack the fallback only fail when the address is
  // ONLY in the structured JSONB.
  IF input.surface IN ('public_invoice', 'quote_pdf', 'public_quote') THEN
    RETURN (NOT has_plain) AND has_structured
  END IF

  // The two already-correct surfaces are never in the bug condition.
  IF input.surface IN ('invoice_preview', 'invoice_pdf') THEN
    RETURN FALSE
  END IF

  RETURN FALSE
END FUNCTION
```

### Examples

- **Public invoice**: Customer "MUMA Whanau Services Ltd" has `address = NULL`, `billing_address = {"street": "842 Mahili Ave", "city": "Manukau", "state": "Auckland", "postal_code": "2104", "country": "NZ"}` → shared invoice "Bill To" shows name + company but no address (expected: shows "842 Mahili Ave, Manukau, Auckland, 2104, NZ").
- **Quote PDF**: Same customer → quote PDF "Bill To" shows no address (expected: shows the structured address).
- **Plain-address precedence (not a bug)**: Customer has `address = "12 Queen St"` and `billing_address = {"street": "99 Other Rd", ...}` → all surfaces show "12 Queen St" (plain wins).
- **Empty structured (not a bug)**: `address = NULL`, `billing_address = {"street": "", "city": "", ...}` → no address shown on any surface.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Plain `customers.address`, when populated, is shown verbatim (no reformatting) and takes precedence over the structured JSONB.
- The in-app invoice preview (`get_invoice`) and authenticated invoice PDF (`generate_invoice_pdf`) render the same address as today — after the change they call the shared helper, which must produce byte-identical output to their current inline logic.
- Customer name, company name, email, and phone in the "Bill To" block render unchanged.
- The large-invoice buyer-address compliance check (Req 80.2) is out of scope and unchanged.
- An all-empty-strings `billing_address` JSONB resolves to "no address", matching today's two-path behaviour.

**Scope:**
Any input where the customer has a populated plain `address`, or has no address at all, is unaffected by the fix (output is identical before and after). Only the case "address lives only in `billing_address` JSONB" changes — and only on the public invoice and quote rendering surfaces that lacked the fallback.

## Hypothesized Root Cause

Confirmed by code analysis:

1. The Edit Customer modal (`frontend-v2/src/components/customers/CustomerEditModal.tsx`) saves the address into `payload.billing_address` (structured JSONB). The plain `customers.address` column is not written by this modal, so it is empty for customers created/edited through it.

2. Address-string resolution was implemented independently in several places. The two invoice paths in `app/modules/invoices/service.py` (`get_invoice` ~line 1787, `generate_invoice_pdf` ~line 4329) were patched to add the `billing_address` JSONB fallback. The public invoice and quote paths (`app/modules/invoices/public_router.py` ~line 97, `app/modules/quotes/service.py` ~line 1120, `app/modules/quotes/public_router.py` ~line 72) were written earlier and only read `customer.address`, so they never received the fallback.

There is no shared helper, so the logic drifted.

## Correctness Properties

Property 1: Bug Condition — Structured Address Resolves on All Rendering Surfaces

_For any_ customer whose address exists only in `billing_address` JSONB (plain `address` empty), every rendering surface (public invoice, quote PDF, public quote, in-app preview, authenticated invoice PDF) SHALL resolve a non-empty address string built from the non-empty JSONB parts joined in order `street, city, state, postal_code, country`.

**Validates: Requirements 2.1, 2.3, 2.5**

Property 2: Preservation — Plain Address Precedence

_For any_ customer with a non-empty plain `customers.address`, the resolved address SHALL equal that exact plain value on every surface, regardless of `billing_address` content.

**Validates: Requirements 2.2, 3.1**

Property 3: Preservation — No Address Resolves to Empty

_For any_ customer with no address in either source (including an all-empty-strings `billing_address`), the resolved address SHALL be `None`/empty and the "Bill To" block SHALL omit the address line.

**Validates: Requirements 2.4, 3.4, 3.5**

Property 4: Preservation — Already-Correct Invoice Paths Unchanged

_For any_ customer/invoice, the address rendered by `get_invoice` and `generate_invoice_pdf` after the fix SHALL equal the address those functions render before the fix.

**Validates: Requirements 3.2**

Property 5: Preservation — Non-Address Bill-To Fields Unchanged

_For any_ customer, the name, company name, email, and phone fields in the "Bill To" block SHALL be unchanged by the fix.

**Validates: Requirements 3.3**

Property 6: Preservation — Compliance Check Unchanged

_For any_ invoice, the Req 80.2 buyer-address compliance check SHALL behave exactly as before this fix (it is out of scope).

**Validates: Requirements 3.6**

## Fix Implementation

### Changes Required

#### 1. New shared helper

**File**: `app/modules/customers/address_utils.py` (new)

A single pure function used by every surface:

```python
def resolve_customer_display_address(customer) -> str | None:
    """Resolve a customer's display address for Bill To rendering.

    Precedence:
      1. Plain-text ``customers.address`` column (verbatim) when non-empty.
      2. Structured ``customers.billing_address`` JSONB — comma-joins the
         non-empty parts in order: street, city, state, postal_code, country.
      3. None when neither source has content.
    """
    plain = (getattr(customer, "address", None) or "").strip()
    if plain:
        return plain
    ba = getattr(customer, "billing_address", None) or {}
    if isinstance(ba, dict):
        joined = ", ".join(
            str(ba.get(k)).strip()
            for k in ("street", "city", "state", "postal_code", "country")
            if ba.get(k) and str(ba.get(k)).strip()
        )
        return joined or None
    return None
```

This matches the existing inline logic in `get_invoice` / `generate_invoice_pdf` exactly (plain-first, then the same five JSONB keys in the same order), so Property 5 holds.

#### 2. Wire the helper into the rendering surfaces

Each surface builds a `customer_context` dict that is passed to a Jinja2 template. The exact change differs per site because the surfaces are not uniform (verified against current code):

- **`app/modules/invoices/service.py` — `get_invoice` (~line 1787)**: replace the inline `cust_address` fallback block with `resolve_customer_display_address(customer)`. The `customer` dict already includes `company_name` and `display_name`. (Preservation: identical output — `get_invoice` already had the fallback.)

- **`app/modules/invoices/service.py` — `generate_invoice_pdf` (~line 4329)**: replace the inline `_cust_addr` / `_cust_billing_addr` block; set `customer_context["address"]` from the helper. Keep the existing `customer_context["billing_address"]` key (the base PDF templates check `customer.billing_address` first, then `customer.address` — both should resolve to the same string so either branch renders correctly). (Preservation: identical output — already had the fallback.)

- **`app/modules/invoices/public_router.py` (~line 97)**: `customer_context` currently has `first_name, last_name, email, phone, address`. Set `address` from the helper. **Also note (pre-existing gap):** `invoice_share.html` renders `customer.display_name` and `customer.company_name`, but this context omits both — so the public invoice shows the raw `first_name last_name` and never the company name. Adding `display_name` and `company_name` to this context is a small, in-scope improvement to make the public invoice match the authenticated one. (If we add them, the template already supports them — no template change needed.)

- **`app/modules/quotes/service.py` (~line 1120)**: `customer_context` has `first_name, last_name, email, phone, address`. Set `address` from the helper. The `quote.html` template already renders `{% if customer.address %}`, so no template change is needed here.

- **`app/modules/quotes/public_router.py` (~line 72)**: `customer_context` currently has **only** `first_name, last_name, email, phone` — there is **no `address` key at all**. Add `"address": resolve_customer_display_address(customer)`. **In addition, the `quote_share.html` template does NOT render an address line** (it only shows name, email, phone). A template change is required here to add the address line, or the value will never display.

The large-invoice compliance check (~line 1649 in `service.py`) is **not** modified.

#### 3. Template change required for the public quote (`quote_share.html`)

Unlike the invoice templates and `quote.html` (which already render `customer.address`), `app/templates/pdf/quote_share.html` has no address line in its "Prepared For" block. Add an address line after the phone line, gated on presence:

```html
<strong>{{ customer.first_name }} {{ customer.last_name }}</strong><br>
{% if customer.email %}{{ customer.email }}<br>{% endif %}
{% if customer.phone %}{{ customer.phone }}<br>{% endif %}
{% if customer.address %}{{ customer.address }}{% endif %}
```

(Note the `<br>` added after phone so the address sits on its own line.)

#### 4. Frontend (in-app previews) — no change needed for this fix's goal

- **In-app invoice preview** (`frontend-v2/src/pages/invoices/InvoiceList.tsx`) already reads `invoice.customer.address`, populated by `get_invoice` — so once the backend resolves the structured address, the on-screen invoice preview shows it with no frontend change.
- **In-app quote preview** (`frontend-v2/src/pages/quotes/QuoteDetail.tsx`) renders only `customer_name` and `customer_email` client-side — it does **not** render any address today. This is a separate, pre-existing limitation of the on-screen quote preview and is **out of scope** for this bugfix (the quote PDF is the address-bearing artifact). Documented here so it is a conscious decision, not an oversight.

## Testing Strategy

### Validation Approach

Two phases: first surface counterexamples on unfixed code (the three broken surfaces + compliance check omit the structured address), then verify the fix and confirm preservation on the already-correct paths.

### Exploratory Bug Condition Checking

**Goal**: Demonstrate the bug before the fix.

**Test Plan**: Unit-test the address resolution at each rendering surface with a customer whose address is only in `billing_address` JSONB.

**Test Cases (expected to FAIL on unfixed code for the broken surfaces):**
1. Public invoice `customer_context` — assert `address` is the joined structured string (fails: it's `None`).
2. Quote service `customer_context` — same assertion (fails).
3. Public quote `customer_context` — same assertion (fails).

**Expected Counterexamples**: structured-only addresses resolve to `None` on the three rendering surfaces.

### Fix Checking

```
FOR ALL input WHERE isBugCondition(input) DO
  resolved := resolve_customer_display_address(input.customer)
  ASSERT resolved == join_nonempty(billing_address, [street, city, state, postal_code, country])
END FOR
```

### Preservation Checking

```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT resolve_customer_display_address(input.customer)
         == legacy_resolution(input.customer)   // plain-first, same JSONB keys
END FOR
```

Specifically:
- Plain address populated → helper returns it verbatim (Property 3).
- No address anywhere / all-empty JSONB → helper returns `None` (Property 4).
- `get_invoice` / `generate_invoice_pdf` output identical before and after (Property 5).

### Unit Tests

- `resolve_customer_display_address`: plain-only, structured-only, both (plain wins), neither, all-empty-strings JSONB, partial JSONB (e.g., only `city`), non-dict `billing_address`.
- Each of the three rendering surfaces resolves the structured-only address.

### Property-Based Tests

- Generate random combinations of plain `address` (empty/non-empty) and `billing_address` JSONB (subsets of the five keys, empty strings) and assert: plain wins when present; otherwise the join of non-empty parts in fixed order; otherwise `None`.

### Integration Tests

- Full flow: create a customer with a structured-only address → view shared invoice → assert address appears in "Bill To".
- Full flow: same customer → generate quote PDF → assert address appears.
- Regression: customer with plain `address` → all surfaces show the plain value unchanged.
