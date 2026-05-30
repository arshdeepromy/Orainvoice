# Tasks

Implementation plan for `quote-settings-parity`. Convert the design into a series of incremental, code-only steps for a code-generation LLM. Each step builds on prior steps and ends with the wiring being live in both the API response and the PDF render path.

Implementation language: **Python 3.11** (backend, per design / project stack) and **TypeScript** (frontend, per design / project stack). No `*` optional sub-tasks — every item below is required for parity.

## Task 1: Backend resolution helper

- [x] 1.1 Add private helper `_resolve_document_settings(org_settings: Mapping[str, Any] | None, *, per_quote_terms: str | None) -> dict[str, object]` to `app/modules/quotes/service.py`. Returns a dict with keys `payment_terms_text` (`str | None`), `terms_and_conditions` (`str | None`), `terms_and_conditions_enabled` (`bool`). Mirrors the invoice resolution at `app/modules/invoices/service.py:1764-1775` and `app/modules/invoices/service.py:4153-4161`. Accept `None` for `org_settings` (treat as empty mapping). Treat whitespace-only strings as empty. Helper must be total over its declared input domain and must not raise. _Requirements: 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 8.4_

## Task 2: Wire helper into the quote response builder

- [x] 2.1 In `app/modules/quotes/service.py`, replace the existing inline `payment_terms_text` block at lines 493-497 with a single call to `_resolve_document_settings(org.settings, per_quote_terms=quote.terms)` and merge the returned triple into the response dict via `result.update(resolved)`. _Requirements: 3.4, 4.6, 5.6_
- [x] 2.2 In `app/modules/quotes/service.py`, audit `get_quote` and any list-quote response builder (e.g. `list_quotes` / `_quote_to_dict`) to ensure every code path that returns a quote dict goes through the helper, so single-quote and list responses agree on `payment_terms_text`, `terms_and_conditions`, and `terms_and_conditions_enabled`. _Requirements: 5.6_

## Task 3: Wire helper into `generate_quote_pdf`

- [x] 3.1 In `app/modules/quotes/service.py`, inside `generate_quote_pdf`, replace the direct `settings.get("terms_and_conditions", "")` and `settings.get("payment_terms_text", "")` (and the `payment_terms_enabled` gate) with a single `resolved = _resolve_document_settings(settings, per_quote_terms=quote_dict.get("terms"))` call. Set `payment_terms_text = resolved["payment_terms_text"] or ""` and `terms_and_conditions = resolved["terms_and_conditions"] or ""` for the Jinja context. Keep the Jinja variable name `payment_terms_text` (per design decision). _Requirements: 4.3, 8.1, 8.4_

## Task 4: Pydantic schema additions

- [x] 4.1 In `app/modules/quotes/schemas.py`, append three fields to `QuoteResponse`: `payment_terms_text: str | None = None`, `terms_and_conditions: str | None = None`, `terms_and_conditions_enabled: bool = False`. Field order and defaults mirror `app/modules/invoices/schemas.py:299-301`. _Requirements: 3.1, 6.1, 6.2, 6.4_

## Task 5: TypeScript interface additions

- [x] 5.1 In `frontend/src/pages/quotes/QuoteDetail.tsx`, extend the `QuoteData` interface with `payment_terms_text?: string | null`, `terms_and_conditions?: string | null`, and `terms_and_conditions_enabled?: boolean`. Do not change any other interface field. _Requirements: 3.2, 6.3_

## Task 6: Notes pre-fill on QuoteCreate

- [x] 6.1 In `frontend/src/pages/quotes/QuoteCreate.tsx`, add a `useEffect` immediately above the existing T&C pre-fill (around line 647) that mirrors `frontend/src/pages/invoices/InvoiceCreate.tsx:901-904`: when `!isEditMode && settings?.invoice?.default_notes_enabled && settings?.invoice?.default_notes`, call `setNotes(prev => prev || settings.invoice.default_notes || '')`. Dependency array: `[isEditMode, settings?.invoice?.default_notes_enabled, settings?.invoice?.default_notes]`. The `prev || ...` form preserves any user edit and satisfies "applied at most once per mount". _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

## Task 7: Detail page — Payment Terms typed access

- [x] 7.1 In `frontend/src/pages/quotes/QuoteDetail.tsx`, replace every `(quote as any).payment_terms_text` access with the typed `quote.payment_terms_text` access. The Payment Terms tile renders only when `quote.payment_terms_text` is a non-empty string. _Requirements: 3.3, 4.1, 4.2_

## Task 8: Detail page — Terms & Conditions toggle gate

- [x] 8.1 In `frontend/src/pages/quotes/QuoteDetail.tsx`, restructure the existing Notes / Terms grid block at approximately lines 816-829 so that:
  - The outer wrapper renders when `quote.notes || (quote.terms_and_conditions_enabled && quote.terms_and_conditions)`.
  - The left-hand Notes tile renders only when `quote.notes` is a non-empty string (content-only gate, no toggle).
  - The right-hand Terms & Conditions tile renders only when `quote.terms_and_conditions_enabled && quote.terms_and_conditions` (mirror of `frontend/src/pages/invoices/InvoiceDetail.tsx:1242-1250`).
  - `quote.terms` is no longer used to render the long-form T&C section. It continues to feed the meta panel "Terms : <first line>" summary only.
  _Requirements: 7.1, 7.2, 7.3, 7.4_

## Task 9: PBT — `_resolve_document_settings` precedence and purity

- [x] 9.1 Create `tests/quotes/test_resolve_document_settings.py` using pytest + Hypothesis. Add a leading comment `# Feature: quote-settings-parity, Property 1: Resolution precedence` for Property 1 tests and `# Feature: quote-settings-parity, Property 2: Helper purity and API/PDF non-divergence` for Property 2 tests.
  - Property 1 (precedence): generate `(payment_terms_enabled, payment_terms_text, terms_and_conditions_enabled, terms_and_conditions, per_quote_terms)` covering empty, whitespace-only, and non-empty strings plus both boolean values; assert each component of the returned triple matches the rules in the design's "Resolution helper" section.
  - Property 2a (purity): for any input, two consecutive calls to `_resolve_document_settings` return equal dicts.
  - Property 2b (API/PDF non-divergence): build the API-side resolved dict via the response builder code path and the PDF-side resolved dict via the PDF code path (monkeypatch `HTML.write_pdf` to a no-op); assert the three values are equal for the same `(org_settings, per_quote_terms)` inputs.
  - Configure each Hypothesis test with `@settings(max_examples=100)` minimum.
  _Requirements: 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 8.1, 8.4 — Validates Property 1, Property 2_

## Task 10: PBT — Notes pre-fill semantics

- [x] 10.1 Create `frontend/src/pages/quotes/__tests__/QuoteCreate.notes-prefill.test.tsx` using vitest + fast-check + React Testing Library. Add a leading comment `// Feature: quote-settings-parity, Property 3: Notes pre-fill semantics`. Generate `(default_notes_enabled: boolean, default_notes: string, prior_user_value: string)` tuples; mount `QuoteCreate` in create mode (`!isEditMode`) with a stub TenantContext / settings provider; assert the resulting Notes input value equals:
  - `prior_user_value` when `prior_user_value` is non-empty,
  - else `default_notes` when `default_notes_enabled && default_notes` non-empty,
  - else the empty string.
  Also assert that re-rendering with stable `settings` does not overwrite a user-edited value (effect runs at most once per mount). Run with `fc.assert(..., { numRuns: 100 })` minimum. _Requirements: 1.1, 1.2, 1.3, 1.5 — Validates Property 3_

## Task 11: PBT — QuoteDetail rendering gates

- [x] 11.1 Create `frontend/src/pages/quotes/__tests__/QuoteDetail.settings-rendering.test.tsx` using vitest + fast-check + React Testing Library. Add a leading comment `// Feature: quote-settings-parity, Property 4: Detail-page rendering gates`. Generate `(notes: string | null, payment_terms_text: string | null, terms_and_conditions_enabled: boolean, terms_and_conditions: string | null)` tuples; render `QuoteDetail` with a mocked API client returning a quote shaped from those values; assert exactly:
  - Notes section visible iff `notes` is a non-empty string.
  - Payment Terms section visible iff `payment_terms_text` is a non-empty string.
  - Terms & Conditions section visible iff `terms_and_conditions_enabled && terms_and_conditions` non-empty.
  Run with `fc.assert(..., { numRuns: 100 })` minimum. _Requirements: 2.1, 2.2, 4.1, 4.2, 7.1, 7.2, 7.3 — Validates Property 4_

## Task 12: Integration — `GET /quotes/{id}` response shape

- [x] 12.1 Create `tests/quotes/test_quote_response_shape.py` using pytest + the existing test client / fixtures. POST a quote, GET it via `GET /quotes/{id}`, and assert the response body contains `payment_terms_text`, `terms_and_conditions`, and `terms_and_conditions_enabled` and that each value equals `_resolve_document_settings(org.settings, per_quote_terms=quote.terms)` for the same inputs. Cover at least:
  - org with payment terms enabled + non-empty text → `payment_terms_text` populated.
  - org with payment terms disabled → `payment_terms_text` is `None`.
  - org with T&C enabled + non-empty text + no per-quote terms → `terms_and_conditions` equals org value.
  - quote with non-empty `quote.terms` and org T&C disabled → `terms_and_conditions` equals per-quote value.
  - quote with empty `quote.terms` and org T&C disabled → `terms_and_conditions` is `None`, `terms_and_conditions_enabled` is `False`.
  _Requirements: 5.6_

## Task 13: Integration — quote PDF Jinja render

- [x] 13.1 Create `tests/quotes/test_quote_pdf_render.py` using pytest. Render `app/templates/pdf/quote.html` directly with the project's Jinja `Environment` (skip WeasyPrint). Six small example-based render tests covering:
  - Notes present (`quote.notes = "hello"`) → output contains the Notes label and value.
  - Notes absent (`quote.notes = ""`) → output does not contain the Notes label.
  - Payment Terms present (`payment_terms_text = "Net 7"`) → output contains the Payment Terms label and `"Net 7"`.
  - Payment Terms absent (`payment_terms_text = ""`) → output does not contain the Payment Terms label.
  - Terms & Conditions present (`terms_and_conditions = "T&C body"`) → output contains the T&C label and body.
  - Terms & Conditions absent (`terms_and_conditions = ""`) → output does not contain the T&C label.
  _Requirements: 2.3, 2.4, 4.4, 4.5, 8.2, 8.3_

## Task 14: Smoke / non-regression checks

- [x] 14.1 Add a single pytest module `tests/quotes/test_quote_settings_parity_nonregression.py` that asserts the following at test time:
  - `QuoteResponse.model_fields` contains `payment_terms_text`, `terms_and_conditions`, and `terms_and_conditions_enabled`.
  - `frontend/src/pages/quotes/QuoteDetail.tsx` (read as text) contains zero occurrences of `as any` within the lines that reference `payment_terms_text` or `terms_and_conditions` (regex check on the file contents).
  - The files `frontend/src/pages/settings/OrgSettings.tsx`, every file under `app/modules/organisations/`, and every file under `alembic/versions/` are present but the test only checks they are not added/altered by this feature via a snapshot of the file paths involved (e.g. the test asserts no migration file matches `*quote*settings*parity*` and that `OrgSettings.tsx` has not gained any of the three new field names). Implement as straightforward string / glob checks against the working tree.
  _Requirements: 3.3, 10.2, 10.3, 10.4, 10.5_

## Task 15: Final checkpoint — Ensure all tests pass

- [x] 15.1 Run the full backend test suite (`pytest tests/quotes/`) and the affected frontend tests (`vitest --run frontend/src/pages/quotes/__tests__/`) and ensure every test added in Tasks 9-14 passes alongside the pre-existing suite. Ensure all tests pass, ask the user if questions arise.

## Notes

- Every task above is required for parity; none are marked optional.
- Each task references specific requirements for traceability and names exact files / line anchors from the design.
- The single-helper rule (`_resolve_document_settings`) is the contract that keeps the API response and the PDF in lock-step. Tasks 1-3 establish it; Task 9 (Property 2b) verifies the non-divergence at test time.
- No Alembic migration, no new endpoints, no `OrgSettings.tsx` edits — Task 14 enforces those constraints automatically.
