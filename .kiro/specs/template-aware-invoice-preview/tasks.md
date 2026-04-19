# Implementation Plan: Template-Aware Invoice Preview

## Overview

This plan implements template-aware styling for the in-browser invoice preview in `InvoiceList.tsx`. The implementation is minimal and surgical: 2 new fields on the backend response (reading from existing org settings JSONB), a new frontend style map module (`invoiceTemplateStyles.ts`), and inline style/className changes in the existing JSX. No new API calls, no new state management, no JSX restructuring.

The backend is Python 3.11/FastAPI; the frontend is TypeScript/React. Property tests use fast-check (frontend) and Hypothesis (backend) with `@settings(max_examples=100)`. E2E tests follow the `scripts/test_*_e2e.py` pattern.

## Tasks

- [x] 1. Backend — Add template fields to invoice detail response
  - [x] 1.1 Add `invoice_template_id` and `invoice_template_colours` fields to `InvoiceResponse` schema
    - Add to `app/modules/invoices/schemas.py` in the `InvoiceResponse` class:
      - `invoice_template_id: str | None = None`
      - `invoice_template_colours: dict | None = None`
    - Place after the existing `org_website` field for logical grouping with org-related fields
    - _Requirements: 1.1, 1.2_

  - [x] 1.2 Add template field population in `get_invoice()` service function
    - In `app/modules/invoices/service.py`, locate the `get_invoice()` function where `org.settings` is read
    - After the existing `result["org_website"] = settings.get("org_website")` line, add:
      - `result["invoice_template_id"] = settings.get("invoice_template_id")`
      - `result["invoice_template_colours"] = settings.get("invoice_template_colours")`
    - No new database queries — reads from the same `settings` dict already loaded
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Frontend — Create template style map module
  - [x] 2.1 Create `frontend/src/utils/invoiceTemplateStyles.ts` with interfaces, registry, and resolver
    - Define `TemplateStyle` interface: `primaryColour`, `accentColour`, `headerBgColour`, `logoPosition`, `layoutType`
    - Define `ColourOverrides` interface: `primary_colour?`, `accent_colour?`, `header_bg_colour?` (snake_case matching backend)
    - Define `ResolvedInvoiceStyles` interface: all `TemplateStyle` fields + `isHeaderDark: boolean`
    - Define `TEMPLATE_STYLES` record with all 13 template entries matching `template_registry.py` exactly (default, classic, modern-dark, compact-blue, bold-header, minimal, trade-pro, corporate, compact-green, elegant, compact-mono, sunrise, ocean)
    - Implement `isDarkColour(hex: string): boolean` — sRGB relative luminance formula, returns true when luminance < 0.5, returns false for invalid hex (safe fallback)
    - Implement `resolveTemplateStyles(templateId, colourOverrides): ResolvedInvoiceStyles` — lookup template (fallback to default), merge overrides (non-empty string overrides template default), compute `isHeaderDark`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 6.3_

  - [x] 2.2 Write property test: Template style map completeness and backend consistency (Property 1)
    - **Property 1: Template style map completeness and backend consistency**
    - **Validates: Requirements 2.2, 2.3, 7.1, 7.3**
    - Test file: `tests/properties/test_template_preview_properties.py`
    - Use Hypothesis: `st.sampled_from(list(TEMPLATES.keys()))` — for each backend template, verify frontend `TEMPLATE_STYLES` has matching entry with identical `primaryColour`, `accentColour`, `headerBgColour`, `logoPosition`, `layoutType`. Also verify ID sets are equal.
    - `@settings(max_examples=100)`

  - [x] 2.3 Write property test: Colour override precedence (Property 2)
    - **Property 2: Colour override precedence**
    - **Validates: Requirements 2.4, 3.5, 7.2**
    - Test file: `frontend/src/utils/__tests__/invoiceTemplateStyles.test.ts`
    - Use fast-check: `fc.record({ templateId: fc.constantFrom(...ids), overrides: fc.record({ primary_colour: fc.option(hexArb), accent_colour: fc.option(hexArb), header_bg_colour: fc.option(hexArb) }) })` — verify override value used when non-empty string, template default used when null/undefined/empty
    - Minimum 100 iterations

  - [x] 2.4 Write property test: Fallback to default for unknown template IDs (Property 3)
    - **Property 3: Fallback to default for unknown template IDs**
    - **Validates: Requirements 2.5, 3.6**
    - Test file: `frontend/src/utils/__tests__/invoiceTemplateStyles.test.ts`
    - Use fast-check: `fc.string()` filtered to exclude valid template IDs, plus `fc.constant(null)` and `fc.constant(undefined)` — verify returned styles equal default template (#3b5bdb primary, #3b5bdb accent, #ffffff header bg)
    - Minimum 100 iterations

  - [x] 2.5 Write property test: Dark colour detection correctness (Property 4)
    - **Property 4: Dark colour detection correctness**
    - **Validates: Requirements 6.1, 6.2, 6.3**
    - Test file: `frontend/src/utils/__tests__/invoiceTemplateStyles.test.ts`
    - Use fast-check: generate valid 6-digit hex strings, compute expected luminance independently, verify `isDarkColour` output matches expected (true when luminance < 0.5, false otherwise)
    - Minimum 100 iterations

- [x] 3. Checkpoint — Backend and style module complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Frontend — Apply template styles to InvoiceList.tsx
  - [x] 4.1 Add template fields to `InvoiceDetailData` interface and add `useMemo` style resolution
    - In `InvoiceList.tsx`, add to the `InvoiceDetailData` interface (or equivalent type):
      - `invoice_template_id?: string | null`
      - `invoice_template_colours?: { primary_colour?: string; accent_colour?: string; header_bg_colour?: string } | null`
    - Import `resolveTemplateStyles` from `@/utils/invoiceTemplateStyles`
    - Add `useMemo` that calls `resolveTemplateStyles(invoice?.invoice_template_id, invoice?.invoice_template_colours)` with deps `[invoice?.invoice_template_id, invoice?.invoice_template_colours]`
    - Use `?.` on all invoice data access per safe-api-consumption steering
    - _Requirements: 3.1, 3.6, 5.7, 5.8_

  - [x] 4.2 Apply template colours to invoice preview elements
    - **Table header** (`<thead>`): Change `style={{ background: '#3b5bdb', color: '#fff' }}` → `style={{ background: templateStyles.primaryColour, color: '#fff', WebkitPrintColorAdjust: 'exact', printColorAdjust: 'exact' }}`
    - **Balance due bar**: Change `style={{ background: '#3b5bdb', color: '#fff' }}` → `style={{ background: templateStyles.primaryColour, color: '#fff', WebkitPrintColorAdjust: 'exact', printColorAdjust: 'exact' }}`
    - **Invoice header section**: Add `style={{ backgroundColor: templateStyles.headerBgColour }}`
    - **Bill To section**: Replace `bg-blue-50/50 border-blue-100` classes with `style={{ backgroundColor: templateStyles.accentColour + '10', borderColor: templateStyles.accentColour + '30' }}`; replace `text-blue-600` on label with `style={{ color: templateStyles.accentColour }}`
    - **Org logo fallback gradient**: Replace `from-blue-500 to-indigo-600` with `style={{ background: templateStyles.primaryColour }}`
    - Preserve `print-table-header` and `print-balance-bar` CSS classes on their elements
    - Only modify `style` attributes and `className` strings — do NOT restructure JSX
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 5.1, 5.2, 5.5, 5.6_

  - [x] 4.3 Apply dark header text contrast
    - When `templateStyles.isHeaderDark` is true, apply `color: '#ffffff'` to all text elements in the header section (org name, address, phone, email, invoice title, balance amount)
    - When `templateStyles.isHeaderDark` is false, keep existing dark text classes (`text-gray-900`, `text-gray-500`)
    - Use conditional className or inline style — do NOT add new state
    - _Requirements: 6.1, 6.2_

  - [x] 4.4 Apply compact layout adjustments
    - When `templateStyles.layoutType === 'compact'`:
      - Line item `<td>` elements: change `py-3` → `py-1.5` (≤6px vertical padding)
      - Section containers: change `px-8 pb-6` → `px-6 pb-4`
    - When `templateStyles.layoutType === 'standard'`: keep existing padding classes
    - Use conditional className strings (ternary in className)
    - _Requirements: 4.1, 4.2_

  - [x] 4.5 Apply logo position layout variants
    - **Left** (default): No changes to current layout (org info left, invoice title right)
    - **Center**: Change header flex container to `flex-col items-center text-center`, move invoice title/balance to a separate row below the org info
    - **Side**: Swap positions — invoice title + balance on left, org info + logo on right
    - Implement with conditional flex direction and order properties on the existing container — do NOT restructure JSX children or add/remove elements
    - _Requirements: 4.3, 4.4, 4.5_

- [x] 5. Checkpoint — Preview styling complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Testing — E2E and unit tests
  - [x] 6.1 Create `scripts/test_template_preview_e2e.py` end-to-end test script
    - Follow feature-testing-workflow steering pattern (httpx, asyncio, ok/fail helpers)
    - Login as org_admin (demo@orainvoice.com / demo123)
    - PUT `/org/settings` with `invoice_template_id: "modern-dark"` and `invoice_template_colours: { primary_colour: "#8b5cf6" }` → verify 200
    - GET an existing invoice via `GET /invoices/{id}` → verify response includes `invoice_template_id: "modern-dark"` and `invoice_template_colours` with the override
    - PUT `/org/settings` with `invoice_template_id: null` → verify 200
    - GET the same invoice → verify `invoice_template_id` is null and `invoice_template_colours` is null
    - Test backward compatibility: org with no template settings returns null fields
    - Security: try accessing without token → 401; try accessing other org's invoice → 403/404
    - Clean up: reset org settings to original state
    - _Requirements: 1.1, 1.2, 1.3, 3.5, 3.6_

  - [x] 6.2 Write unit tests for `resolveTemplateStyles` and `isDarkColour`
    - Test file: `frontend/src/utils/__tests__/invoiceTemplateStyles.test.ts`
    - `resolveTemplateStyles(null)` → returns default blue styles (#3b5bdb)
    - `resolveTemplateStyles('modern-dark')` → returns correct indigo colours
    - `resolveTemplateStyles('modern-dark', { primary_colour: '#ff0000' })` → override applied, others use template defaults
    - `resolveTemplateStyles('unknown-id')` → falls back to default
    - `isDarkColour('#1e1b4b')` → true (dark indigo)
    - `isDarkColour('#ffffff')` → false (white)
    - `isDarkColour('#808080')` → boundary test
    - `isDarkColour('invalid')` → false (safe fallback)
    - Compact templates return `layoutType: 'compact'`
    - Each logo position value correctly returned
    - _Requirements: 2.4, 2.5, 6.1, 6.2, 6.3_

- [x] 7. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at backend, style module, and frontend milestones
- Property tests validate the 4 correctness properties defined in the design document
- The existing JSX structure in `InvoiceList.tsx` MUST remain intact — only `style` attributes and `className` strings change (no-shortcut-implementations steering)
- All frontend API data access must use `?.` and `?? []` / `?? 0` (safe-api-consumption steering)
- E2E test script goes in `scripts/` following the feature-testing-workflow steering pattern
- Backend changes are minimal: 2 lines in service + 2 fields on schema — no new queries, no new endpoints
