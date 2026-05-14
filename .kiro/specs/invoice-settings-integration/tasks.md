# Implementation Plan: Invoice Settings Integration

## Overview

Wire four existing organisation settings fields (Email Signature, Default Invoice Notes, Payment Terms Statement, Terms & Conditions) to their intended output channels via enable/disable toggles. All new data is stored as JSONB keys on the existing `organisations.settings` column — no database migration required.

Tasks are ordered by layer: backend schema → backend service → backend API → frontend context → frontend settings UI → frontend invoice form → frontend invoice preview → PDF renderer → email dispatcher → property tests → version bump → git push.

## Tasks

- [x] 1. Backend — add toggle fields to organisation schemas
  - [x] 1.1 Add toggle fields to `OrgSettingsResponse` in `app/modules/organisations/schemas.py`
    - Add `email_signature_enabled: Optional[bool] = Field(None, description="Enable email signature on outgoing emails")`
    - Add `default_notes_enabled: Optional[bool] = Field(None, description="Pre-fill notes on new invoices")`
    - Add `payment_terms_enabled: Optional[bool] = Field(None, description="Show payment terms on invoices")`
    - Add `terms_and_conditions_enabled: Optional[bool] = Field(None, description="Show T&C on invoices")`
    - _Requirements: 1.1_

  - [x] 1.2 Add toggle fields to `OrgSettingsUpdateRequest` in `app/modules/organisations/schemas.py`
    - Add the same four `Optional[bool]` fields with identical names and descriptions
    - _Requirements: 1.2_

  - [x] 1.3 Verify syntax: `python3 -c "import ast; ast.parse(open('app/modules/organisations/schemas.py').read())"`
    - _Requirements: 1.1, 1.2_

- [x] 2. Backend — update organisation service for toggle persistence and defaults
  - [x] 2.1 Add toggle keys to `SETTINGS_JSONB_KEYS` in `app/modules/organisations/service.py`
    - Add `"email_signature_enabled"`, `"default_notes_enabled"`, `"payment_terms_enabled"`, `"terms_and_conditions_enabled"` to the set
    - _Requirements: 1.1, 1.2_

  - [x] 2.2 Apply defaults in `get_org_settings()` when keys are missing from JSONB
    - `email_signature_enabled` → `False`
    - `default_notes_enabled` → `False`
    - `payment_terms_enabled` → `True`
    - `terms_and_conditions_enabled` → `True`
    - _Requirements: 1.3, 1.4, 1.5, 1.6_

  - [x] 2.3 Verify syntax: `python3 -c "import ast; ast.parse(open('app/modules/organisations/service.py').read())"`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 3. Backend — invoice detail API adds payment_terms_text and toggle state
  - [x] 3.1 Update `get_invoice()` in `app/modules/invoices/service.py`
    - Fetch org settings for the invoice's org
    - When `payment_terms_enabled` is `true` and `payment_terms_text` content exists, include `payment_terms_text` in the response dict
    - When `payment_terms_enabled` is `false`, do NOT include `payment_terms_text` in the response dict
    - Always include `terms_and_conditions_enabled` boolean in the response dict
    - _Requirements: 9.3, 9.4, 9.5_

  - [x] 3.2 Verify syntax: `python3 -c "import ast; ast.parse(open('app/modules/invoices/service.py').read())"`
    - _Requirements: 9.3, 9.4, 9.5_

- [x] 4. Backend — PDF renderer passes toggle states to template context
  - [x] 4.1 Update `generate_invoice_pdf()` in `app/modules/invoices/service.py`
    - Read `payment_terms_enabled` and `terms_and_conditions_enabled` from org settings
    - Pass `payment_terms` as empty string when `payment_terms_enabled` is `false` (content suppressed)
    - Pass `terms_and_conditions` as empty string when `terms_and_conditions_enabled` is `false` (content suppressed)
    - Notes (`invoice.notes_customer`) always pass through — no toggle needed for display
    - Per-invoice stored `terms_and_conditions` (from `invoice_data_json`) always renders regardless of org toggle (backward compat)
    - _Requirements: 5.3, 5.4, 6.3, 6.4, 8.1, 8.2, 8.3, 10.1, 10.2_

  - [x] 4.2 Verify syntax: `python3 -c "import ast; ast.parse(open('app/modules/invoices/service.py').read())"`
    - _Requirements: 5.3, 5.4, 6.3, 6.4_

- [x] 5. Backend — email dispatcher appends signature conditionally
  - [x] 5.1 Update `email_invoice` in `app/modules/invoices/service.py`
    - Read org settings: `email_signature_enabled` and `email_signature`
    - When `email_signature_enabled` is `true` and `email_signature` content is non-empty:
      - Append `<hr>` + signature HTML to `html_body`
    - When `email_signature_enabled` is `false` OR `email_signature` is empty/null: do not append
    - _Requirements: 3.1, 3.3, 3.4, 3.5_

  - [x] 5.2 Update `send_quote` in `app/modules/quotes/service.py`
    - Same signature append logic as 5.1 for quote emails
    - _Requirements: 3.2, 3.3, 3.4, 3.5_

  - [x] 5.3 Verify syntax for both files
    - `python3 -c "import ast; ast.parse(open('app/modules/invoices/service.py').read())"`
    - `python3 -c "import ast; ast.parse(open('app/modules/quotes/service.py').read())"`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 6. Backend checkpoint
  - Verify syntax of all modified backend files:
    - `python3 -c "import ast; ast.parse(open('app/modules/organisations/schemas.py').read())"`
    - `python3 -c "import ast; ast.parse(open('app/modules/organisations/service.py').read())"`
    - `python3 -c "import ast; ast.parse(open('app/modules/invoices/service.py').read())"`
    - `python3 -c "import ast; ast.parse(open('app/modules/quotes/service.py').read())"`
  - Do NOT run the full test suite — only syntax verification at this stage
  - Ensure all pass, ask the user if questions arise.

- [x] 7. Frontend — expand TenantContext with toggle states and default_notes
  - [x] 7.1 Extend `InvoiceSettings` interface in `frontend/src/contexts/TenantContext.tsx`
    - Add `default_notes: string | null`
    - Add `default_notes_enabled: boolean`
    - Add `payment_terms_enabled: boolean`
    - Add `terms_and_conditions_enabled: boolean`
    - _Requirements: 1.8, 9.1_

  - [x] 7.2 Map new fields from API response in `fetchSettings`
    - `default_notes: data?.default_notes ?? null`
    - `default_notes_enabled: data?.default_notes_enabled ?? false`
    - `payment_terms_enabled: data?.payment_terms_enabled ?? true`
    - `terms_and_conditions_enabled: data?.terms_and_conditions_enabled ?? true`
    - Follow safe-api-consumption patterns (`?.` and `??` fallbacks)
    - _Requirements: 1.8, 9.1_

- [x] 8. Frontend — settings page toggle UI controls
  - [x] 8.1 Add Email Signature toggle to Branding tab in `frontend/src/pages/settings/OrgSettings.tsx`
    - Toggle switch with label "Enable email signature on outgoing emails"
    - When toggle is off, apply `opacity-50 pointer-events-none` to the email signature textarea container
    - Bind to `email_signature_enabled` field in settings state
    - _Requirements: 2.1, 2.5, 2.6_

  - [x] 8.2 Add Default Notes toggle to Invoice tab
    - Toggle switch with label "Pre-fill notes on new invoices"
    - When toggle is off, dim the default notes textarea
    - Bind to `default_notes_enabled` field
    - _Requirements: 2.2, 2.5, 2.6_

  - [x] 8.3 Add Payment Terms toggle to Invoice tab
    - Toggle switch with label "Show payment terms on invoices"
    - When toggle is off, dim the payment terms textarea
    - Bind to `payment_terms_enabled` field
    - _Requirements: 2.3, 2.5, 2.6_

  - [x] 8.4 Add Terms & Conditions toggle to Terms tab
    - Toggle switch with label "Show terms & conditions on invoices"
    - When toggle is off, dim the T&C rich text editor container
    - Bind to `terms_and_conditions_enabled` field
    - _Requirements: 2.4, 2.5, 2.6_

  - [x] 8.5 Verify frontend build: `docker compose exec frontend sh -c "rm -rf /app/dist/assets/* && npx vite build"`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [x] 9. Frontend — invoice form conditional pre-fill and rich text T&C
  - [x] 9.1 Conditional notes pre-fill in `frontend/src/pages/invoices/InvoiceCreate.tsx`
    - On create (no existing invoice): read `settings?.invoice?.default_notes_enabled`
    - If `true`, initialize Customer Notes with `settings?.invoice?.default_notes ?? ''`
    - If `false`, initialize Customer Notes as empty string
    - On edit (existing invoice): use stored `notes_customer` regardless of toggle
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 9.2 Conditional T&C pre-fill in `InvoiceCreate.tsx`
    - On create: read `settings?.invoice?.terms_and_conditions_enabled`
    - If `true`, initialize T&C with `settings?.invoice?.terms_and_conditions ?? ''`
    - If `false`, initialize T&C as empty string
    - On edit: use stored `terms_and_conditions` from invoice record
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 9.3 Replace plain textarea with rich text area for T&C field
    - Use a contentEditable div that preserves HTML formatting (bold, italic, lists, links, headings)
    - Render existing HTML content without stripping tags
    - Preserve HTML on form submission
    - _Requirements: 7.4, 7.5_

  - [x] 9.4 Verify "Use this in future" checkbox is unaffected
    - Confirm the existing checkbox continues to save `terms_and_conditions` only
    - It must NOT be affected by `default_notes_enabled` toggle
    - _Requirements: 4.5, 10.3_

  - [x] 9.5 Verify frontend build: `docker compose exec frontend sh -c "rm -rf /app/dist/assets/* && npx vite build"`
    - _Requirements: 4.1, 4.2, 4.3, 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 10. Frontend — invoice web preview adds payment terms and T&C sections
  - [x] 10.1 Add Payment Terms section to `frontend/src/pages/invoices/InvoiceDetail.tsx`
    - Render below the existing Notes section
    - Guard: `{invoice?.payment_terms_text && (...)}`
    - Heading: "Payment Terms" with `text-sm font-medium text-gray-500 uppercase tracking-wider mb-2`
    - Content in `rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700`
    - No `print:hidden` CSS — must appear in browser print output
    - _Requirements: 5.1, 5.2, 5.5, 5.6_

  - [x] 10.2 Add Terms & Conditions section to `InvoiceDetail.tsx`
    - Render below Payment Terms section
    - Guard: `{invoice?.terms_and_conditions_enabled && invoice?.terms_and_conditions && (...)}`
    - Heading: "Terms & Conditions" with same styling as Payment Terms heading
    - Content rendered via `dangerouslySetInnerHTML={{ __html: invoice.terms_and_conditions }}` with `prose prose-sm` classes
    - No `print:hidden` CSS — must appear in browser print output
    - _Requirements: 6.1, 6.2, 6.5, 6.6_

  - [x] 10.3 Verify frontend build: `docker compose exec frontend sh -c "rm -rf /app/dist/assets/* && npx vite build"`
    - _Requirements: 5.1, 5.2, 6.1, 6.2_

- [x] 11. Frontend checkpoint
  - Run frontend build ONLY: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend sh -c "rm -rf /app/dist/assets/* && npx vite build"`
  - Verify no TypeScript errors in modified files
  - Do NOT run the full test suite — only build verification at this stage
  - Ensure build passes, ask the user if questions arise.

- [x] 12. Property-based tests — `tests/test_invoice_settings_integration_properties.py`
  - [x] 12.1 Property 1: Toggle persistence round-trip
    - **Property 1: Toggle persistence round-trip**
    - Strategy: generate all 4 boolean toggle values using `st.booleans()`
    - Simulate PUT with generated values, then GET, assert returned values match
    - Use `@settings(max_examples=30)`
    - **Validates: Requirements 1.1, 1.2**

  - [x] 12.2 Property 2: Content independence from toggle state
    - **Property 2: Content independence from toggle state**
    - Strategy: generate random text content (`st.text(min_size=0, max_size=500)`) and random toggle bool (`st.booleans()`)
    - PUT both content and toggle, GET, assert text content unchanged regardless of toggle
    - Use `@settings(max_examples=30)`
    - **Validates: Requirements 1.7**

  - [x] 12.3 Property 3: Email signature conditional append
    - **Property 3: Email signature conditional append**
    - Strategy: generate body (`st.text(min_size=1, max_size=200)`), signature (`st.text(min_size=1, max_size=200)`), enabled (`st.booleans()`)
    - Call email body builder logic, assert signature present iff enabled=True and signature non-empty
    - Assert `<hr>` separator present when signature appended
    - Use `@settings(max_examples=30)`
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [x] 12.4 Property 4: Notes pre-fill conditional on toggle
    - **Property 4: Notes pre-fill conditional on toggle**
    - Strategy: generate notes (`st.text(min_size=0, max_size=500)`), enabled (`st.booleans()`)
    - Call pre-fill logic, assert result equals notes when enabled=True and notes non-empty, else empty string
    - Use `@settings(max_examples=30)`
    - **Validates: Requirements 4.1, 4.2**

  - [x] 12.5 Property 5: Edit mode uses stored invoice values
    - **Property 5: Edit mode uses stored invoice values**
    - Strategy: generate stored_notes (`st.text()`), stored_tc (`st.text()`), org_notes (`st.text()`), org_tc (`st.text()`), toggle_notes (`st.booleans()`), toggle_tc (`st.booleans()`)
    - Call edit-mode init logic, assert stored values used regardless of org defaults or toggle state
    - Use `@settings(max_examples=30)`
    - **Validates: Requirements 4.3, 7.2**

  - [x] 12.6 Property 6: Web preview conditional section rendering
    - **Property 6: Web preview conditional section rendering**
    - Strategy: generate payment_terms content (`st.text(min_size=0, max_size=200)`), tc content (`st.text(min_size=0, max_size=200)`), payment_terms_enabled (`st.booleans()`), tc_enabled (`st.booleans()`)
    - Assert payment terms section present iff enabled=True AND content non-empty
    - Assert T&C section present iff enabled=True AND content non-empty
    - Use `@settings(max_examples=30)`
    - **Validates: Requirements 5.1, 5.2, 6.1, 6.2**

  - [x] 12.7 Property 7: PDF template toggle-aware rendering
    - **Property 7: PDF template toggle-aware rendering**
    - Strategy: generate content (`st.text(min_size=0, max_size=200)`), payment_terms_enabled (`st.booleans()`), tc_enabled (`st.booleans()`)
    - Call PDF context builder, assert payment_terms passed as empty when disabled, content when enabled
    - Assert terms_and_conditions passed as empty when disabled, content when enabled
    - Notes always pass through
    - Use `@settings(max_examples=30)`
    - **Validates: Requirements 5.3, 5.4, 6.3, 6.4, 8.1, 8.2, 8.3**

  - [x] 12.8 Property 8: HTML content preservation in T&C
    - **Property 8: HTML content preservation in T&C**
    - Strategy: generate HTML strings with formatting tags using `st.sampled_from(["<b>bold</b>", "<ul><li>item</li></ul>", "<a href='#'>link</a>", "<h2>heading</h2>", "<em>italic</em>"])` combined with `st.text()`
    - Round-trip through store/retrieve, assert HTML tags preserved without stripping
    - Use `@settings(max_examples=30)`
    - **Validates: Requirements 6.5, 7.1, 7.5**

  - [x] 12.9 Property 9: Invoice detail API conditional payment_terms_text
    - **Property 9: Invoice detail API conditional payment_terms_text**
    - Strategy: generate payment_terms_text (`st.text(min_size=1, max_size=200)`), enabled (`st.booleans()`)
    - Call invoice detail builder logic, assert `payment_terms_text` present in response iff enabled=True
    - Assert `payment_terms_text` absent from response when enabled=False
    - Use `@settings(max_examples=30)`
    - **Validates: Requirements 9.3, 9.4**

  - [x] 12.10 Property 10: Backward compatibility — existing invoice content always renders
    - **Property 10: Backward compatibility — existing invoice content always renders**
    - Strategy: generate stored notes_customer (`st.text(min_size=1, max_size=200)`), stored tc (`st.text(min_size=1, max_size=200)`), org toggle states (`st.booleans()`)
    - Call PDF render context builder with per-invoice stored data, assert stored content always present in output regardless of org toggle
    - Use `@settings(max_examples=30)`
    - **Validates: Requirements 10.1, 10.2**

- [x] 13. Frontend property tests — `frontend/src/pages/invoices/__tests__/InvoiceSettings.property.test.tsx`
  - [x] 13.1 Property 4 (frontend): Notes pre-fill conditional on toggle
    - **Property 4: Notes pre-fill conditional on toggle**
    - Use `fc.property` with `fc.boolean()` for enabled and `fc.string({ minLength: 0, maxLength: 200 })` for notes
    - Assert pre-fill result matches: enabled && notes.length > 0 → notes, else empty string
    - Use `{ numRuns: 30 }`
    - **Validates: Requirements 4.1, 4.2**

  - [x] 13.2 Property 5 (frontend): Edit mode uses stored invoice values
    - **Property 5: Edit mode uses stored invoice values**
    - Use `fc.property` with `fc.record({ storedNotes: fc.string(), storedTC: fc.string(), orgNotes: fc.string(), orgTC: fc.string(), notesEnabled: fc.boolean(), tcEnabled: fc.boolean() })`
    - Assert edit-mode init always uses stored values, never org defaults
    - Use `{ numRuns: 30 }`
    - **Validates: Requirements 4.3, 7.2**

  - [x] 13.3 Property 6 (frontend): Preview section visibility
    - **Property 6: Web preview conditional section rendering**
    - Use `fc.property` with `fc.record({ paymentTerms: fc.string(), tc: fc.string(), ptEnabled: fc.boolean(), tcEnabled: fc.boolean() })`
    - Assert payment terms section visible iff ptEnabled && paymentTerms.length > 0
    - Assert T&C section visible iff tcEnabled && tc.length > 0
    - Use `{ numRuns: 30 }`
    - **Validates: Requirements 5.1, 5.2, 6.1, 6.2**

- [x] 14. Test checkpoint
  - Run ONLY the new property tests: `pytest tests/test_invoice_settings_integration_properties.py -v --no-header`
  - Verify syntax of all modified backend files
  - Run frontend build: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend sh -c "rm -rf /app/dist/assets/* && npx vite build"`
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Version bump and CHANGELOG entry
  - [x] 15.1 Bump `pyproject.toml` version
    - Update the `version` field to the next minor version
    - _Requirements: (release discipline)_

  - [x] 15.2 Bump `frontend/package.json` version
    - Update the `version` field to match backend
    - _Requirements: (release discipline)_

  - [x] 15.3 Add CHANGELOG entry
    - Added: Invoice settings enable/disable toggles (email signature, default notes, payment terms, T&C)
    - Added: Email signature append on invoice and quote emails
    - Added: Default notes pre-fill on new invoices
    - Added: Payment terms and T&C sections in invoice web preview
    - Added: Toggle-aware PDF rendering for payment terms and T&C
    - Added: Rich text T&C field in invoice form (HTML preserved)
    - _Requirements: (release discipline)_

- [-] 16. Git push and update local dev environment
  - [-] 16.1 Commit all changes and push to GitHub
    - `git add -A`
    - `git commit -m "feat: invoice settings integration — enable/disable toggles for email signature, notes, payment terms, T&C"`
    - `git push origin main`
    - _Requirements: (release discipline)_

  - [~] 16.2 Rebuild local dev backend (picks up new code + auto-reloads)
    - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --force-recreate app`
    - Confirm app starts and no migration is needed (JSONB keys only)
    - _Requirements: (release discipline)_

## Notes

- No database migration is required — all new fields are JSONB keys on the existing `organisations.settings` column.
- Tasks marked with `*` are optional property-based test sub-tasks and can be skipped for faster MVP.
- Each property test uses `@settings(max_examples=30)` (backend, Hypothesis) or `{ numRuns: 30 }` (frontend, fast-check).
- Backend syntax verification uses `python3 -c "import ast; ast.parse(open('file').read())"` after each file modification.
- Frontend build verification uses `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend sh -c "rm -rf /app/dist/assets/* && npx vite build"` after each UI change.
- Backward compatibility: per-invoice stored `notes_customer` and `terms_and_conditions` always render regardless of org-level toggle state.
- The "Use this in future" checkbox behaviour is unchanged — it saves T&C only.
- Checkpoints run ONLY relevant tests — `pytest tests/test_invoice_settings_integration_properties.py` for backend, frontend build for frontend. No full test suite runs.
- Last task pushes to main and rebuilds the local dev environment (backend auto-reloads, frontend hot-reloads).
