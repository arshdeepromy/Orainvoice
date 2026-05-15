# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Hardcoded Footer Text in PDF Templates
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate hardcoded footer text appears regardless of org settings
  - **Scoped PBT Approach**: Use Hypothesis to generate random `invoice_footer_text` values (including empty/None) and render the `_invoice_base.html` template; assert output does NOT contain "Thank you for your business." or "Payments can be paid by direct bank transfer"
  - Test file: `tests/test_invoice_footer_bug_condition.py`
  - Strategy: Use Jinja2 to render the base template with generated org context values
  - For any `invoice_footer_text` value (custom text, empty, None): assert rendered footer does NOT contain hardcoded strings
  - For non-empty `invoice_footer_text`: assert rendered footer CONTAINS the custom text
  - For empty/None `invoice_footer_text`: assert rendered footer contains NO text content
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists because hardcoded text is always present)
  - Document counterexamples found (e.g., "Template always outputs 'Thank you for your business.' regardless of invoice_footer_text value")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-Footer Sections and Custom Footer Rendering Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Test file: `tests/test_invoice_footer_preservation.py`
  - Observe: Render `_invoice_base.html` with `org.invoice_footer = "Custom text"` on unfixed code → confirm custom text appears in output
  - Observe: Render template with `notes_customer = "Some notes"` on unfixed code → confirm notes section renders
  - Observe: Render template with payment_terms and T&C sections → confirm they render above footer
  - Write property-based test (Hypothesis): for all non-empty `invoice_footer_text` strings, the `{% if org.invoice_footer %}` conditional renders the custom text in the footer area
  - Write property-based test: for all invoice data with `notes_customer` content, the notes section renders unchanged
  - Write property-based test: for all invoice data with `payment_terms_text` content, the payment terms section above footer renders unchanged
  - Verify tests PASS on UNFIXED code (these capture existing correct behavior that must be preserved)
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.5, 3.6_

- [x] 3. Fix for hardcoded footer text in PDF templates

  - [x] 3.1 Remove hardcoded footer text from `_invoice_base.html`
    - Remove the `<p class="footer-text">Thank you for your business.</p>` line
    - Remove the `{% if org.gst_number %}...<p class="footer-text">Payments can be paid by direct bank transfer...</p>...{% endif %}` block
    - Keep only the `{% if org.invoice_footer %}<p class="footer-text">{{ org.invoice_footer }}</p>{% endif %}` conditional
    - Keep the wrapping `<div>` with border-top styling
    - _Bug_Condition: isBugCondition(input) where input.context == 'pdf'_
    - _Expected_Behavior: Footer contains only org.invoice_footer text when set, nothing when empty_
    - _Preservation: org.invoice_footer conditional rendering preserved_
    - _Requirements: 2.1, 2.2, 2.3, 3.1_

  - [x] 3.2 Remove hardcoded footer text from all 12 child templates that override `{% block footer %}`
    - Apply same pattern: remove "Thank you for your business." and bank transfer text
    - Keep each template's unique styling (border, colours, layout)
    - Keep only the `{% if org.invoice_footer %}` conditional in each
    - Templates to update: all child templates in `app/templates/pdf/` that extend `_invoice_base.html` and override `{% block footer %}`
    - _Bug_Condition: isBugCondition(input) where input.context == 'pdf'_
    - _Expected_Behavior: No hardcoded text in any child template footer_
    - _Preservation: Visual styling of each template preserved_
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.3 Remove hardcoded footer text from standalone templates (`invoice.html`, `invoice_share.html`)
    - These 2 templates don't extend the base template but have the same hardcoded footer pattern
    - Apply same fix: remove hardcoded text, keep only `{% if org.invoice_footer %}` conditional
    - _Bug_Condition: isBugCondition(input) where input.context == 'pdf'_
    - _Expected_Behavior: Standalone templates use configurable footer only_
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.4 Add `org_invoice_footer_text` to invoice detail API response
    - File: `app/modules/invoices/service.py`
    - In the invoice detail response builder, add `org_invoice_footer_text` sourced from org settings `invoice_footer_text`
    - This makes the footer text available to the split-panel without requiring a separate settings fetch
    - _Requirements: 2.4_

  - [x] 3.5 Update `InvoiceDetailData` interface in `InvoiceList.tsx`
    - Add `payment_terms_text?: string | null`
    - Add `terms_and_conditions_enabled?: boolean`
    - Add `terms_and_conditions?: string | null`
    - Add `org_invoice_footer_text?: string | null`
    - _Bug_Condition: isBugCondition(input) where input.context == 'interface'_
    - _Expected_Behavior: Interface includes all fields from API response_
    - _Requirements: 2.7_

  - [x] 3.6 Add Payment Terms and T&C sections to InvoiceList.tsx split-panel
    - Add Payment Terms section: render `invoice.payment_terms_text` when present, with "Payment Terms" label
    - Add Terms & Conditions section: render `invoice.terms_and_conditions` with `dangerouslySetInnerHTML` when `terms_and_conditions_enabled` is true and content exists
    - Match styling pattern from InvoiceDetail.tsx (border-t, uppercase label, prose content)
    - _Bug_Condition: isBugCondition(input) where input.context == 'split-panel'_
    - _Expected_Behavior: Split-panel renders Payment Terms and T&C sections matching InvoiceDetail.tsx_
    - _Preservation: Notes section continues rendering unchanged_
    - _Requirements: 2.5, 2.6, 3.2_

  - [x] 3.7 Replace hardcoded footer in InvoiceList.tsx split-panel with configurable text
    - Remove hardcoded "Thank you for your business." and bank transfer text from split-panel footer
    - Replace with `invoice.org_invoice_footer_text` — show when present, show nothing when absent
    - _Bug_Condition: isBugCondition(input) where input.context == 'split-panel'_
    - _Expected_Behavior: Split-panel footer uses org_invoice_footer_text from API, no hardcoded text_
    - _Requirements: 2.4_

  - [x] 3.8 Fix T&C pre-fill timing in InvoiceCreate.tsx
    - Replace `useState` initializer for T&C with empty string default
    - Add `useEffect` that watches `settings?.invoice?.terms_and_conditions_enabled` and `settings?.invoice?.terms_and_conditions`
    - Only pre-fill on create (not edit): guard with `!editId`
    - Use `prev || settings.invoice.terms_and_conditions` to avoid overwriting user input
    - _Bug_Condition: isBugCondition(input) where input.context == 'create-form' AND settingsLoaded == false_
    - _Expected_Behavior: T&C pre-fills once settings load, regardless of mount timing_
    - _Preservation: Edit mode continues using stored invoice terms_and_conditions_
    - _Requirements: 2.8, 3.4_

  - [x] 3.9 Fix notes pre-fill timing in InvoiceCreate.tsx (same pattern for consistency)
    - Apply same `useEffect` pattern to `customerNotes` for consistency
    - Watch `settings?.invoice?.default_notes_enabled` and `settings?.invoice?.default_notes`
    - Only pre-fill on create (not edit): guard with `!editId`
    - Use `prev || settings.invoice.default_notes` to avoid overwriting user input
    - _Preservation: Existing notes pre-fill behavior maintained, timing issue resolved_
    - _Requirements: 3.7_

  - [x] 3.10 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Hardcoded Footer Text Removed
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior (no hardcoded text, only configurable text)
    - When this test passes, it confirms the expected behavior is satisfied
    - Run: `python -m pytest tests/test_invoice_footer_bug_condition.py -v`
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.11 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-Footer Sections and Custom Footer Rendering Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run: `python -m pytest tests/test_invoice_footer_preservation.py -v`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all preservation tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.5, 3.6_

  - [x] 3.12 Backend syntax verification
    - Run: `python -c "import app.modules.invoices.service"` to verify no import/syntax errors
    - Run: `python -c "import app.main"` to verify full app loads without errors
    - Verify all modified Python files pass syntax check
    - _Requirements: All_

  - [x] 3.13 Frontend build verification
    - Run: `npm run build` in `frontend/` directory to verify TypeScript compilation succeeds
    - Verify no type errors from InvoiceDetailData interface changes
    - Verify no type errors from InvoiceCreate.tsx useEffect changes
    - Verify no type errors from InvoiceList.tsx split-panel changes
    - _Requirements: All_

- [x] 4. Checkpoint - Ensure all tests pass
  - Run full test suite: `python -m pytest tests/test_invoice_footer_bug_condition.py tests/test_invoice_footer_preservation.py -v`
  - Verify bug condition test passes (confirms fix works)
  - Verify preservation tests pass (confirms no regressions)
  - Verify backend syntax check passes
  - Verify frontend build succeeds
  - Bump version in relevant config if applicable
  - Git commit and push to feature branch
  - Ask the user if questions arise
