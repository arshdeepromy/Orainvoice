# Implementation Plan

- [x] 1. Write bug condition exploration tests
  - **Property 1: Bug Condition** — structured-only address omitted on broken rendering surfaces
  - **CRITICAL**: These tests MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **GOAL**: Surface counterexamples where a customer whose address is only in `billing_address` JSONB gets no address
  - Test file: `tests/test_billto_address_bug_condition.py`
  - Build a fake/ORM customer with `address=None` and `billing_address={"street": "842 Mahili Ave", "city": "Manukau", "state": "Auckland", "postal_code": "2104", "country": "NZ"}`
  - Assert the public-invoice customer context address == the joined structured string (FAILS today)
  - Assert the authenticated quote-service customer context address == the joined string (FAILS today)
  - Assert the public-quote customer context CONTAINS an `address` key equal to the joined string (FAILS today — the key does not exist at all)
  - Run on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (proves the bug)
  - Document counterexamples
  - _Requirements: 1.2, 1.3, 1.4, 2.1, 2.3_

- [x] 2. Write preservation tests (BEFORE implementing fix)
  - **Properties 2–6: Preservation** — plain precedence, no-address→empty, already-correct invoice paths, non-address fields, compliance check unchanged
  - **IMPORTANT**: Observation-first — capture current correct behavior on UNFIXED code
  - Test file: `tests/test_billto_address_preservation.py`
  - Observe + assert (PASS on unfixed code):
    - Customer with non-empty plain `address` → `get_invoice` / `generate_invoice_pdf` render that exact value
    - Customer with structured-only address → `get_invoice` / `generate_invoice_pdf` already render the joined string (these two paths have the fallback)
    - Customer with no address / all-empty-strings JSONB → resolved address is `None`, "Bill To" omits the line
    - Name / company / email / phone render unchanged
    - The Req 80.2 compliance check behaves identically (out of scope, must not change)
  - **EXPECTED OUTCOME**: Tests PASS (baseline to preserve)
  - _Requirements: 2.2, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. Implement the fix

  - [x] 3.1 Create shared helper `resolve_customer_display_address`
    - File: `app/modules/customers/address_utils.py` (new)
    - Plain `address` (verbatim) first; else join non-empty `billing_address` parts in order `street, city, state, postal_code, country`; else `None`
    - Guard non-dict `billing_address` and all-empty-strings JSONB → `None`
    - _Expected_Behavior: single source of truth matching existing inline logic_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.5_

  - [x] 3.2 Wire helper into `get_invoice`
    - File: `app/modules/invoices/service.py` (~line 1787)
    - Replace the inline `cust_address` fallback with `resolve_customer_display_address(customer)`
    - _Preservation: identical output to today_
    - _Requirements: 3.2_

  - [x] 3.3 Wire helper into `generate_invoice_pdf`
    - File: `app/modules/invoices/service.py` (~line 4329)
    - Replace the inline `_cust_addr` / `_cust_billing_addr` block; set `customer_context["address"]` from the helper (keep `billing_address` key behaviour as-is)
    - _Preservation: identical output to today_
    - _Requirements: 3.2_

  - [x] 3.4 Wire helper into the public/shared invoice path
    - File: `app/modules/invoices/public_router.py` (~line 97)
    - Set the existing `address` key from the helper instead of `customer.address`
    - Also add `display_name` and `company_name` to `customer_context` (the `invoice_share.html` template already renders both; the context currently omits them)
    - _Bug_Condition: surface == 'public_invoice'_
    - _Requirements: 2.1, 2.3, 2.7_

  - [x] 3.5 Wire helper into the authenticated quote PDF path
    - File: `app/modules/quotes/service.py` (~line 1120)
    - Set the existing `address` key from the helper
    - No template change needed — `quote.html` already renders `{% if customer.address %}`
    - _Bug_Condition: surface == 'quote_pdf'_
    - _Requirements: 2.1, 2.3_

  - [x] 3.6 Wire helper into the public quote path AND update its template
    - File: `app/modules/quotes/public_router.py` (~line 72)
    - The `customer_context` currently has NO `address` key — ADD `"address": resolve_customer_display_address(customer)`
    - File: `app/templates/pdf/quote_share.html` (~line 124-129, "Prepared For" block)
    - The template has NO address line — add `{% if customer.address %}{{ customer.address }}{% endif %}` after the phone line, with a `<br>` after phone so the address sits on its own line
    - _Bug_Condition: surface == 'public_quote'_
    - _Expected_Behavior: public quote renders the resolved address_
    - _Preservation: name/email/phone lines unchanged_
    - _Requirements: 2.1, 2.3, 2.6, 3.8_

  - [x] 3.7 Verify bug condition tests now pass
    - Re-run the SAME tests from task 1 (do NOT write new tests)
    - Run: `docker compose -p invoicing exec -T app python -m pytest tests/test_billto_address_bug_condition.py -v`
    - **EXPECTED OUTCOME**: Tests PASS (bug fixed)
    - _Requirements: 2.1, 2.3_

  - [x] 3.8 Verify preservation tests still pass
    - Re-run the SAME tests from task 2 (do NOT write new tests)
    - Run: `docker compose -p invoicing exec -T app python -m pytest tests/test_billto_address_preservation.py -v`
    - **EXPECTED OUTCOME**: Tests PASS (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.8_

  - [x] 3.9 Backend syntax/import + template-render verification
    - Run: `docker compose -p invoicing exec -T app python -c "import app.modules.customers.address_utils"`
    - Run: `docker compose -p invoicing exec -T app python -c "import app.modules.invoices.service, app.modules.invoices.public_router, app.modules.quotes.service, app.modules.quotes.public_router"`
    - Run: `docker compose -p invoicing exec -T app python -c "import app.main"`
    - Render `quote_share.html` with a sample context to confirm the new address line parses (no Jinja syntax error)
    - _Requirements: All_

- [x] 4. Checkpoint — manual verification on local dev
  - Find/create a customer with an address only in `billing_address` JSONB (e.g., the existing "Nolin Devi" / a new test business customer)
  - View the in-app invoice preview → address shows (regression check, already worked via `get_invoice`)
  - Open the shared/public invoice link → address now shows; company name now shows for business customers
  - Generate an authenticated quote PDF → address now shows
  - Open the public quote share link → address now shows (template + context change)
  - Confirm the in-app quote preview is unchanged (name + email only — documented out of scope)
  - Regression: a customer with a plain `address` still shows that value everywhere
  - _Requirements: 2.1, 2.6, 2.7, 3.1, 3.2, 3.7_

- [-] 5. Update issue tracker + commit
  - Add an entry to `docs/ISSUE_TRACKER.md` for this fix
  - Git commit to a feature branch and push (do not deploy to Pi PROD until approved)
  - _Requirements: All_

## Affected Files (reference)

- `app/modules/customers/address_utils.py` — **new** shared helper
- `app/modules/invoices/service.py` — `get_invoice`, `generate_invoice_pdf` (compliance check NOT touched)
- `app/modules/invoices/public_router.py` — public/shared invoice (address fallback + add `display_name`/`company_name`)
- `app/modules/quotes/service.py` — authenticated quote PDF (address fallback)
- `app/modules/quotes/public_router.py` — public quote (ADD `address` key)
- `app/templates/pdf/quote_share.html` — **template change**: add the address line to the "Prepared For" block
- `tests/test_billto_address_bug_condition.py` — **new**
- `tests/test_billto_address_preservation.py` — **new**

## Notes

- The large-invoice buyer-address compliance check (Req 80.2) is intentionally **out of scope** and left unchanged.
- **In-app invoice preview**: no frontend change needed — `InvoiceList.tsx` already reads `invoice.customer.address`, populated by `get_invoice`.
- **In-app quote preview** (`QuoteDetail.tsx`): renders only name + email client-side; surfacing an address there is **out of scope** (pre-existing limitation; the quote PDF carries the address).
- **Template facts verified against code**: `_invoice_base.html`, `invoice.html`, `invoice_share.html`, and `quote.html` already render `customer.address`; only `quote_share.html` lacks an address line and needs the template change.
- `invoice_share.html` already references `customer.display_name` and `customer.company_name`, but the public-invoice context omits them — task 3.4 adds them (small in-scope fix; no template change needed).
- No DB migration required: this is purely a read/serialisation fix; the data already exists in `billing_address`.
- Transaction discipline: helper is pure (no DB writes); all call sites are read paths.
