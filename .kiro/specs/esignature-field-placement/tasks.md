# Implementation Plan: E-Signature Field Placement

## Overview

This plan adds an in-app, drag-and-drop **field-placement editor** to the already-shipped `esignature-integration` send flow, replacing the single auto-placed signature (for sends that carry a Field_Set) with a sender-defined set of fields created on Documenso via `POST /api/v2/document/field/create-many` before distribute. It is an **extension**, not a redesign: the per-org token model, module gate, send RBAC, connection-verified gate, envelope recording, audit/notify, and the R17 "≥1 signature per signer" safety rule are all inherited unchanged.

The base feature (Requirements **R1–R12**, Properties **1–17**) is implemented in Tasks **1–14** and is **unchanged** by this revision. On top of it, this plan now delivers the five newly in-scope capabilities (Properties **18–26**):

- **R13 — Edit fields after send** (Tasks 16): a pure `editable_state` gate, `DocumensoClient.replace_fields` (delete + create-many), an atomic `replace_envelope_fields` service path with a `not_editable` 422 + audit, new `GET/PUT /api/v2/esign/envelopes/{id}/fields` endpoints, and an editor that accepts an `envelopeId` (seed from GET, submit via PUT) plus the Non_Editable_State banner and Void & recreate wiring.
- **R14 — Conditional / dependent fields** (Task 17): a pure `dependencyGraph.ts` + backend `dependency_graph.py` with cycle/self-loop detection, a `DependencyInspector` UI with the advisory notice, and `build_field_meta` degrading an advisory `require` effect to optional. Enforcement is **advisory** (the `enforced` branch is a documented forward-compat stub — Documenso has no cross-field conditional primitive).
- **R15 — Signing-order UI** (Task 19): a `SigningOrderControls` block (parallel/sequential + reorder), `RecipientSpec.signing_order` + `signing_order_mode`, and client create/distribute mapping to Documenso `signingOrder` + `PARALLEL`/`SEQUENTIAL`.
- **R17 — Saved field templates** (Tasks 20–21): the one new table `esign_field_templates` (Alembic migration **0234**, RLS `tenant_isolation` mirroring 0232; head is **0233**), an ORM model, `templates_service.py` CRUD, the `/api/v2/esign/field-templates` endpoints, and a client `applyTemplate.ts` role→recipient mapping.
- **R16 — Mobile field-placement editor** (Tasks 23–24): the pure core (`coordinateMapping` + `fieldValidation` + `dependencyGraph`) is extracted to a shared location (`@shared/esign/`) — or duplicated verbatim with a parity test — and the `mobile/` Capacitor surface (`EsignSendScreen`, `MobileFieldPlacementEditor`, `MobilePdfPage`, `TouchFieldOverlay`) is added per the mobile steering guide, using the **same** backend contract.

Backend is Python 3.11 / FastAPI / SQLAlchemy (async) / Alembic. Web frontend is React 18 + TypeScript + Vite + Tailwind in `frontend-v2/`; mobile is React 19 + Capacitor in `mobile/`. **The only new DB table is `esign_field_templates` (migration 0234, R17)** — the per-send Field_Set (R1–R12), edit-after-send (R13, re-reads the live set from Documenso), advisory dependencies (R14), and signing order (R15) all reflect into the existing `esign_envelopes` / `esign_recipients` rows. Property-based tests use **fast-check** (frontend + mobile pure core) and **Hypothesis** (backend), a minimum of **100 examples** each, one property → one test, tagged `// Feature: esignature-field-placement, Property {n}: {property_text}` (TS) / `# Feature: esignature-field-placement, Property {n}: {property_text}` (Python).

## Tasks

- [x] 1. Coordinate mapping pure core (`frontend-v2/src/components/esign/fieldplacement/lib/coordinateMapping.ts`)
  - [x] 1.1 Implement the pure overlay↔normalized transforms and clamping
    - Create `coordinateMapping.ts` exporting the `OverlayRect`, `NormalizedRect`, and `PageDims` interfaces and the pure functions `overlayToNormalized(rect, dims)`, `normalizedToOverlay(rect, dims)`, and `clampToPage(rect, dims, minWpx, minHpx)`.
    - `overlayToNormalized` divides out `dims.cssWidth`/`dims.cssHeight` to produce percent (0–100) with origin top-left, so the result is render-scale independent (precondition `cssWidth > 0 && cssHeight > 0`). `normalizedToOverlay` is its exact inverse at the same dims. `clampToPage` enforces `width/height ≥ min`, `x,y ≥ 0`, `x+w ≤ cssWidth`, `y+h ≤ cssHeight` in overlay space. No rounding inside the transforms; pure, no I/O.
    - _Requirements: 7.1, 7.2, 7.5, 3.5, 3.6, 6.3_

  - [x] 1.2 Write property test for coordinate round-trip (fast-check)
    - **Property 1: Coordinate round-trip is identity within 1 px (per page)** — generate strictly-positive (incl. non-square and differing) page dims and a fractional rect that fits in `[0,100]`; assert `normalizedToOverlay(overlayToNormalized(rect, dims), dims)` matches `rect` within ≤1 CSS px on `x`, `y`, `width`, `height`.
    - **Validates: Requirements 7.1, 7.3, 7.5**

  - [x] 1.3 Write property test for scale independence (fast-check)
    - **Property 2: Normalized coordinates are independent of render scale** — for a field expressed as a fixed page fraction and two strictly-positive render scales (≥320 px viewport range), assert `overlayToNormalized` yields the same NormalizedRect within floating-point epsilon at both scales.
    - **Validates: Requirements 7.2**

- [x] 2. Field_Set reducer and recipient colours (frontend pure core)
  - [x] 2.1 Implement the `useFieldSet` reducer (`fieldplacement/hooks/useFieldSet.ts`)
    - Define `FieldType`, `PlacedField` (`clientId`, `type`, `page`, `rect: NormalizedRect`, `recipientKey`, `required`, optional `label`/`placeholder`), and the `FieldSetAction` union (`add`/`move`/`resize`/`assign`/`setRequired`/`setTextMeta`/`delete`/`removeRecipient`/`reset`). Implement the pure reducer: `add` defaults `required = type !== 'text'` (R2.3) and grows the set by one; geometric actions (`move`/`resize`) run through `clampToPage` + min-size so every committed field stays in-bounds and ≥ min-size while page/type/recipient are unchanged; `assign` changes only the target field's `recipientKey`; `removeRecipient` cascades to drop that recipient's fields; `reset` empties the set. Fields are stored normalized (percent) so a viewport resize never mutates them.
    - _Requirements: 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.5, 5.1, 5.2, 11.1, 11.3_

  - [x] 2.2 Implement `fieldColors.ts` (`fieldplacement/lib/fieldColors.ts`)
    - Deterministic, high-contrast palette mapping a recipient index to a distinct colour; pairwise-distinct within the palette capacity. Pure, no I/O.
    - _Requirements: 4.4_

  - [x] 2.3 Write property test for add semantics (fast-check)
    - **Property 4: Add records the chosen type, page, and per-type default required flag** — adding grows the set by exactly one field carrying the chosen type/page, required iff type is not `text`.
    - **Validates: Requirements 2.2, 2.3**

  - [x] 2.4 Write property test for geometric invariant (fast-check)
    - **Property 3: Every geometric action leaves a field in-bounds and at least minimum size** — over generated action sequences and page dims, every committed field satisfies `x≥0, y≥0, x+w≤100, y+h≤100, w≥minWidth, h≥minHeight`, with page/type/recipient unchanged.
    - **Validates: Requirements 3.2, 3.3, 3.5, 3.6**

  - [x] 2.5 Write property test for assignment integrity (fast-check)
    - **Property 5: Every field references exactly one valid recipient** — over generated action sequences on a fixed recipient list, every field is assigned to exactly one existing recipient and re-assigning changes only that field's recipient.
    - **Validates: Requirements 4.1, 4.3**

  - [x] 2.6 Write property test for cascade delete (fast-check)
    - **Property 6: Removing a recipient removes exactly that recipient's fields** — `removeRecipient` leaves no field assigned to it and every other field unchanged.
    - **Validates: Requirements 4.5**

  - [x] 2.7 Write property test for distinct recipient colours (fast-check)
    - **Property 7: Recipients receive pairwise-distinct colours** — within palette capacity, each recipient's colour differs from every other recipient's.
    - **Validates: Requirements 4.4**

- [x] 3. Client-side send validation (`fieldplacement/lib/fieldValidation.ts`)
  - [x] 3.1 Implement pure client-side `validateFieldSet`
    - Mirror the server rules so the send control can be gated client-side: every field references an existing recipient, every field in-bounds (`x≥0, y≥0, x+w≤100, y+h≤100, w>0, h>0`), every field carries a supported type, every signer (role `signer`) recipient has ≥1 signature field; viewers may have zero fields. Return a structured pass/fail result with the offending field/signer so the editor can keep send disabled until valid (R6.4) and re-enable on correction (R6.5). Pure, no I/O.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 4.6, 2.4_

  - [x] 3.2 Write example tests for send-control enablement (Vitest + RTL)
    - An invalid Field_Set keeps the send control disabled (R6.4); correcting every failure enables it (R6.5).
    - _Requirements: 6.4, 6.5_

- [x] 4. Checkpoint - Ensure all frontend pure-core tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. PDF renderer (`fieldplacement/hooks/usePdfDocument.ts`, `PdfPageCanvas.tsx`)
  - [x] 5.1 Add `pdfjs-dist` (pinned exact) and implement `usePdfDocument`
    - Add `pdfjs-dist` to `frontend-v2/package.json` pinned to an **exact** version; bundle the worker via Vite. Implement `usePdfDocument` to load the selected `File` as an `ArrayBuffer` into a `PDFDocumentProxy`, expose page count and per-page `getViewport({ scale })` CSS dimensions, choose a responsive `renderScale` (fits available width, ≥320 px, capped for many-page docs), and support progressive/lazy rendering (defer `page.render()` until near the viewport, reserve space via cheap `getViewport` dims). Surface a `RenderedPage` per page (`pageNumber`, `cssWidth`, `cssHeight`, `renderScale`, `status`). All rendering client-side; never transmits the PDF (R1.6).
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6, 7.2, 10.5_

  - [x] 5.2 Implement `PdfPageCanvas.tsx`
    - Render one page to a `<canvas>` sized to its viewport; show a per-page loading indicator while `status === 'rendering'` (R1.3) and clear it on completion; rasterise image-only/scanned pages like any other page so fields can be placed on them (R1.5). On a `getDocument` reject or page-render throw, set `status: 'error'` so the editor can surface the `render_failed` message and block send (R1.4).
    - _Requirements: 1.1, 1.3, 1.4, 1.5_

  - [x] 5.3 Write example/integration tests for PDF rendering (Vitest + RTL, mocked `pdfjs-dist`)
    - A multi-page doc renders one page surface per page (R1.1, R1.2); a page in `rendering` shows a loading indicator (R1.3); a `getDocument`/render rejection surfaces `render_failed` and keeps send disabled (R1.4); an image-only sample renders and accepts a placed field (R1.5); no API/Documenso call is made during rendering (R1.6).
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 6. Editor component tree (`FieldPlacementEditor`, `FieldOverlay`, `FieldPalette`, `RecipientLegend`, `FieldInspector`)
  - [x] 6.1 Implement `FieldPalette.tsx` and `RecipientLegend.tsx`
    - `FieldPalette` offers all six field-type sources (`signature`, `initials`, `name`, `date`, `email`, `text`) as drag-to-add / tap-to-arm controls (R2.1), each with a ≥44×44 px hit target. `RecipientLegend` shows per-recipient colour swatches (from `fieldColors.ts`) and the active-recipient picker that drives which recipient a newly placed field is assigned to (R4.2).
    - _Requirements: 2.1, 4.2, 4.4, 10.1_

  - [x] 6.2 Implement `FieldOverlay.tsx` (drag / resize / keyboard / touch)
    - One absolutely-positioned, draggable/resizable field box rendered in its recipient's colour, converting between stored `NormalizedRect` and overlay px via `normalizedToOverlay`/`overlayToNormalized` against the page's `PageDims`. Drag/resize on **Pointer Events** (unifying mouse + touch, ≥320 px, R10.5); every geometric commit passes through `clampToPage` + min-size. Selected field is keyboard-movable (arrow keys; Shift = larger step, R10.2) and deletable (Delete/Backspace, R10.3); resize handle and box meet the 44×44 px minimum (R10.1); exposes an accessible name conveying type + assigned recipient, e.g. `aria-label="Signature field for Alex Tran"` (R10.4); renders a visible required/optional indicator (R5.5).
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.4, 5.5, 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 6.3 Implement `FieldInspector.tsx`
    - For the selected field: recipient re-assignment (`assign`, R4.3), required/optional toggle (`setRequired`, R5.1), and — for `text` fields only — label + placeholder inputs (`setTextMeta`, R5.2), plus a delete control (R3.4). All controls ≥44×44 px.
    - _Requirements: 4.3, 5.1, 5.2, 3.4, 10.1_

  - [x] 6.4 Implement `FieldPlacementEditor.tsx` (orchestrator)
    - Compose the page list (`PdfPageCanvas` per page), palette, legend, inspector, and the `useFieldSet` reducer; place a dragged palette item via `add` at the drop point on the targeted page (R3.1); retain the Field_Set across in-editor page navigation (R11.1); drive send-control enabled/disabled from the client `validateFieldSet` result (R6.4/R6.5); surface the `render_failed` error and keep send disabled when any page failed to render (R1.4). Cancel dispatches `reset` and aborts any in-flight send (R11.2); a failed send retains the set for retry (R11.4).
    - _Requirements: 1.4, 3.1, 6.4, 6.5, 11.1, 11.2, 11.4_

  - [x] 6.5 Write example tests for palette and required indicator (Vitest + RTL)
    - The palette offers all six types (R2.1); each placed field shows a visible required/optional indicator (R5.5).
    - _Requirements: 2.1, 5.5_

  - [x] 6.6 Write example tests for drag / keyboard / touch wiring (Vitest + RTL, synthetic Pointer events)
    - Dragging a palette item adds a field at the drop point (R3.1); a selected field moves via arrow keys (R10.2) and deletes via Delete/Backspace (R10.3); placement works via pointer events at a 320 px viewport (R10.5).
    - _Requirements: 3.1, 10.2, 10.3, 10.5_

  - [x] 6.7 Write example tests for assignment wiring (Vitest + RTL)
    - Placing uses the currently-selected recipient (R4.2); a field renders in its recipient's colour (R4.4 render binding).
    - _Requirements: 4.2, 4.4_

  - [x] 6.8 Write accessibility tests (Vitest + RTL + axe)
    - Interactive controls meet the 44×44 px minimum (R10.1); a selected field's accessible name conveys its type and assigned recipient (R10.4).
    - _Requirements: 10.1, 10.4_

- [x] 7. Checkpoint - Ensure all editor/renderer tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Backend pure cores (`app/modules/esignatures/field_mapping.py`, `field_validation.py`)
  - [x] 8.1 Implement `field_mapping.py` (`map_field_type`, `build_field_meta`)
    - `map_field_type(t)` maps the six lowercase types to their UPPERCASE Documenso types (`signature`→`SIGNATURE`, `initials`→`INITIALS`, `name`→`NAME`, `date`→`DATE`, `email`→`EMAIL`, `text`→`TEXT`) and raises on an unsupported type (R2.4). `build_field_meta(field)` always carries `required` and, only for TEXT fields, includes `label`/`placeholder` when present (R5.3, R5.4). Pure, no I/O. **Note (capability assumption #2):** the working `DocumensoClient` never sends `fieldMeta` today. Whether `field/create-many` accepts and honours `fieldMeta` (`required`/`label`/`placeholder`) MUST be confirmed by the capability probe (Task 9.2). If unsupported, `build_field_meta` is a **no-op on the wire** (the field is created without `fieldMeta`) and `required`/`label`/`placeholder` become advisory / OraInvoice-only — R14.8's "advisory require ⇒ optional at signing" degrade then holds trivially because nothing is engine-enforced.
    - _Requirements: 2.4, 5.3, 5.4_

  - [x] 8.2 Implement `field_validation.py` (`validate_field_set`, pure)
    - Define the `FieldIn` value (type, page, `recipient_index`, normalized `position_x`/`position_y`/`width`/`height`, `required`, optional `label`/`placeholder`) and `validate_field_set(fields, recipients, signer_indices) -> ValidationResult`. Enforce: every field's `recipient_index` in range (R6.2); every field in-bounds `x≥0, y≥0, x+w≤100, y+h≤100, w>0, h>0` (R6.3); every type maps to a Documenso type (R2.4); every signer recipient has ≥1 signature-type field (R6.1, the re-expressed R17 rule); viewers exempt (R4.6). Return humanized, leak-free messages naming the offending field (by page) or signer(s) (by name). Pure, no I/O.
    - _Requirements: 2.4, 4.6, 6.1, 6.2, 6.3_

  - [x] 8.3 Write property test for field-type mapping (Hypothesis)
    - **Property 9: Field type maps totally to the documented Documenso type** — each of the six types returns its documented Documenso type; any unsupported type string is rejected.
    - **Validates: Requirements 2.4**

  - [x] 8.4 Write property test for fieldMeta (Hypothesis)
    - **Property 8: Field meta carries required always, and text label/placeholder only for text fields** — built `fieldMeta` always includes `required`, and includes `label`/`placeholder` iff the type is `text` and that value is present.
    - **Validates: Requirements 5.3, 5.4**

  - [x] 8.5 Write property test for server-side validation (Hypothesis)
    - **Property 10: Server-side Field_Set validation is correct and names offenders** — over recipient lists mixing signer/viewer and mixed Field_Sets (in/out-of-bounds, valid/invalid `recipient_index`, supported/unsupported types, signers with/without a signature field), validation succeeds iff all rules hold; on failure the error is human-readable and names the offending field or unsatisfied signer(s); viewers with no fields never fail.
    - **Validates: Requirements 2.4, 4.6, 6.1, 6.2, 6.3**

- [x] 9. Schemas: extend `EnvelopeCreate` with optional `fields[]` (`app/modules/esignatures/schemas.py`)
  - [x] 9.1 Add `FieldIn` and `EnvelopeCreate.fields`
    - Add the `FieldIn` Pydantic model (`type` Literal of the six values, `page` ge=1, `recipient_index` ge=0, `position_x`/`position_y` ge=0 le=100, `width`/`height` gt=0 le=100, `required` default True, optional `label`/`placeholder`) and extend `EnvelopeCreate` with `fields: list[FieldIn] | None = None` (additive, backward-compatible). Pydantic constraints are a first-pass guard; authoritative cross-field rules live in `validate_field_set`.
    - _Requirements: 2.1, 5.1, 5.2, 8.3_

  - [x] 9.2 Verify Documenso v2 field/distribute capabilities (de-risk assumptions)
    - Author a throwaway probe script (`scripts/probe_documenso_capabilities.py`) that, against the **running per-org Documenso build**, exercises the v2 surface beyond the proven single-`SIGNATURE` slice and **records the pass/fail outcome** for each of the four design "Documenso capability assumptions" (see design's *Documenso capability assumptions* subsection): (a) `field/create-many` accepts non-`SIGNATURE` types — issue one field each of `INITIALS`/`NAME`/`DATE`/`EMAIL`/`TEXT` on a throwaway document and confirm each is accepted and renders at signing; (b) `fieldMeta` (`required`/`label`/`placeholder`) is accepted per field and honoured by the signing engine; (c) a document's fields can be **deleted/replaced** while it is `sent` and unsigned, and re-running `field/create-many` yields exactly the new set; (d) per-recipient `signingOrder` positions + a `SEQUENTIAL`/`PARALLEL` distribution mode are accepted and **enforced** (recipient N+1 cannot sign before N). For each capability found unsupported, apply the documented fallback: (a) restrict the editor palette to the supported subset; (b) `fieldMeta` becomes a no-op on the wire + advisory (Tasks 8.1/17.6); (c) edit-after-send degrades to **Void_And_Recreate only** and the in-place `PUT …/fields` replace path is not shipped (Task 16.3); (d) sequential **degrades to parallel** with an advisory note (Tasks 19.2/19.3). Record the outcomes (e.g. a short capability matrix committed under `docs/`) so the conditional tasks can read them. This task is **mandatory** — its outcome gates Tasks 16.3, 19.2/19.3, and the `fieldMeta` behaviour in 8.1/17.6. Use a `TEST_PROBE_` prefix for any created data and clean it up in a `finally` block.
    - _Requirements: 2.4, 5.3, 13.3, 15.4_

- [x] 10. DocumensoClient: multi-field create (`app/integrations/documenso.py`)
  - [x] 10.1 Implement `create_fields(document_id, fields)`
    - Add `async def create_fields(self, document_id, fields: list[DocumensoFieldSpec]) -> None` issuing `POST /api/v2/document/field/create-many`. The payload MUST mirror the PROVEN `place_signature_field` shape **exactly** — same keys, just N fields instead of one: `{ "documentId": int(document_id), "fields": [ ... ] }`, where each spec → `{ recipientId: int, type: <UPPERCASE>, pageNumber: <1-based>, pageX, pageY, width, height, fieldMeta? }`. Carry the already-mapped UPPERCASE type and the resolved integer `recipientId`. The internal `NormalizedRect` maps `positionX → pageX`, `positionY → pageY`, and `page → pageNumber` (1-based) so the wire keys match `place_signature_field` precisely; do **not** send `positionX`/`positionY`/`page` keys. `fieldMeta` is sent per field only when the capability probe (Task 9.2) confirms `field/create-many` honours it — otherwise it is omitted (see Task 8.1/17.6). Reuse the existing per-org client construction (`for_org`), raw-token `Authorization` header, explicit timeouts, and transient-failure retry. **Keep** the existing single-field `place_signature_field` method for the auto-placement fallback path.
    - _Requirements: 8.1, 8.2_

- [x] 11. Service: field-set send branch in `create_and_send_envelope` (`app/modules/esignatures/service.py`)
  - [x] 11.1 Add the Field_Set branch and recipientId reconciliation
    - Keep step 0 (connection gate → 503 when missing/unverified, no Documenso call) and the pure PDF/recipient validation unchanged. Then branch: **if `fields` is non-empty**, run `validate_field_set` server-side **before any Documenso call** (R6.6 → 422 on failure, nothing created); on success run `create_document` (PDF uploaded inline as multipart; recipients read back via GET) → **reconcile** each field's `recipient_index` to the Documenso `recipientId` by **email** against `create_result.recipients` (the existing `created_by_email` mapping the service already uses, R8.2) → `create_fields(documentId, mappedSpecs)` (full set, via `field_mapping`) → `distribute`; the legacy single auto-placement is **skipped** (R8.3). The ordering is create (PDF inline) → field/create-many → distribute. **If `fields` is empty/omitted**, run the existing auto-placement path unchanged (backward-compat fallback). On `field/create-many` error: do **not** distribute, record an `error`-status envelope (fresh-session pattern), return humanized 502 (R8.4). On success persist the envelope (`sent`) + recipient rows as today and run best-effort audit + notify (R8.5).
    - _Requirements: 6.6, 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 11.2 Write property test for faithful in-order creation (Hypothesis, spy client)
    - **Property 11: A valid Field_Set is created faithfully, in order, before distribute** — calls occur create→upload→`field/create-many`→distribute; the payload has exactly one field per placed field with the mapped type, page, normalized coords, `fieldMeta`, and `recipientId` equal to the Documenso id of the recipient at that field's `recipient_index`; legacy single placement is not used; the persisted envelope carries `org_id`, agreement type, originating-entity ref, mapped document id, and status `sent`.
    - **Validates: Requirements 7.4, 8.1, 8.2, 8.3, 8.5**

  - [x] 11.3 Write property test for atomic pre-Documenso rejection (Hypothesis, spy client)
    - **Property 12: An invalid Field_Set is rejected before any Documenso call** — a Field_Set failing server validation is rejected with a human-readable error; no document/recipient/field is created and no `sent` envelope persisted.
    - **Validates: Requirements 6.6**

  - [x] 11.4 Write property test for field-create failure handling (Hypothesis, spy client)
    - **Property 13: A field-creation failure blocks distribute and records an error envelope** — a simulated `field/create-many` failure means no distribute call, an `error`-status envelope is persisted, and a human-readable error is returned.
    - **Validates: Requirements 8.4**

  - [x] 11.5 Write property test for connection gate (Hypothesis, spy client + real test DB)
    - **Property 14: Sends are blocked unless the org's connection is present and verified** — a send for an org whose connection is missing or `is_verified = false` is blocked with a human-readable error and no Documenso call; it proceeds only when present and verified.
    - **Validates: Requirements 9.6**

  - [x] 11.6 Write property test for per-org token scoping (Hypothesis, spy client, multi-org)
    - **Property 15: Field-placement sends use only the calling org's team-scoped token** — across orgs with distinct base URL / token / Team id, every Documenso call for a given org uses that org's own token scoped to its own Team, never another's.
    - **Validates: Requirements 9.3**

  - [x] 11.7 Write example test for backward-compat fallback (pytest)
    - A send with **no** `fields` runs the existing single-signature auto-placement path unchanged (R8.3 fallback); a send **with** `fields` uses `field/create-many` and not the single placement.
    - _Requirements: 8.3_

- [x] 12. Checkpoint - Ensure all backend send-path tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Wire the frontend send contract and the two-step modal
  - [x] 13.1 Extend `api/esign.ts` with `FieldIn` and optional `fields[]`
    - Add the `FieldType` and `FieldIn` types (normalized percent coords, `recipient_index`) and extend `EnvelopeCreate` with optional `fields?: FieldIn[]` (additive). The create call uses typed generics, `?.` / `?? []`, no `as any`, and binds the in-flight request to the existing `AbortController` (R9.5). Map each `PlacedField.recipientKey` to its recipient's array index at submit time.
    - _Requirements: 8.1, 9.5_

  - [x] 13.2 Convert `SendForSignatureModal.tsx` to a two-step flow
    - Step 1 is the existing PDF + agreement-type + recipients composer; step 2 mounts `FieldPlacementEditor` with the selected PDF and recipient list. The send call moves to the end of step 2 so the Field_Set travels with it; on cancel, discard the in-progress set and abort any in-flight send (R11.2); reopening starts from an empty set (R11.3); a failed send retains the set for retry (R11.4). Never expose the Documenso UI (R9.4).
    - _Requirements: 9.4, 11.2, 11.3, 11.4_

  - [x] 13.3 Write example tests for autosave / cancel / retry (Vitest + RTL)
    - The Field_Set survives in-editor page navigation (R11.1); cancel discards the set and calls `AbortController.abort` (R11.2); reopening starts empty (R11.3); a failed send retains the set for retry (R11.4).
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 13.4 Write example test for safe consumption (Vitest + RTL / static)
    - The create call uses typed generics, `?.` / `?? []`, and binds the in-flight request to an `AbortController` aborted on unmount/cancel (R9.5).
    - _Requirements: 9.5_

- [x] 14. Server-side guarantees: RBAC, module gate, and error shape (verify + cover)
  - [x] 14.1 Confirm the field-placement send inherits RBAC, module gate, connection gate, and humanized errors
    - The `POST /api/v2/esign/envelopes` route already applies `require_esign_sender` (403), the module gate (403 when disabled), the connection gate (503), and the `esign_error(code)` / `status_for_code(code)` humanized `{ message, code }` shape. Confirm the field-set path reuses these unchanged. Register the new field-set validation codes `field_unassigned`, `field_out_of_bounds`, `invalid_field_type`, and `signature_field_missing` (all HTTP 422) in **BOTH** `ESIGN_ERROR_MESSAGES` and `ESIGN_ERROR_STATUS` in `app/modules/esignatures/errors.py` (the real central tables), and raise them via `esign_error(code, message=...)` / `status_for_code(code)`. Note `signature_field_missing` (a signer carries no signature-type field in the sender Field_Set) is **distinct** from the existing `no_signers` (no signer recipients at all) and `signature_field_failed` (Documenso rejected the auto-placed signature) codes — add it as a new code, do not reuse either.
    - _Requirements: 9.1, 9.2, 9.6, 12.1, 12.2, 12.3_

  - [x] 14.2 Write property test for RBAC (Hypothesis)
    - **Property 16: Role-based access control for field-placement send, edit, and templates** (send portion) — a field-placement send is permitted iff the user holds `org_admin`, `branch_admin`, or `location_manager`; all other roles → HTTP 403. (Edit + template portions are covered in Task 21.7.)
    - **Validates: Requirements 9.2**

  - [x] 14.3 Write property test for error shape (Hypothesis)
    - **Property 17: Error responses are human-readable and leak nothing** — every error path (client/server validation, Documenso failure, connection/config, access control) returns a non-empty `message`, may include a `code`, and contains no raw DB or exception/stack-trace text.
    - **Validates: Requirements 12.1, 12.2, 12.3**

  - [x] 14.4 Write example tests for module gate and no-Documenso-UI smoke (pytest)
    - A field-placement send under `/api/v2/esign` while the module is disabled returns 403 (R9.1, reuses existing gate); no route or link exposes the Documenso admin/org UI to org users (R9.4 smoke).
    - _Requirements: 9.1, 9.4_

- [x] 15. Expanded wire contracts (backend schemas + frontend API)
  - [x] 15.1 Extend `schemas.py` for edit / dependencies / signing-order / templates
    - Extend `app/modules/esignatures/schemas.py` (additive, backward-compatible): add `DependencyIn` (`dependent_client_id`, `trigger_client_id`, `condition` Literal of the six conditions, optional `value`, `effect` Literal `show`/`require`, R14.1/R14.3); add an optional `client_id` to `FieldIn` (stable key for dependency refs, R14); add `order: int | None = Field(default=None, ge=1)` to `RecipientIn` (R15.3/R15.6) and `signing_order_mode: Literal["parallel","sequential"] = "parallel"` + optional `dependencies: list[DependencyIn] | None = None` to `EnvelopeCreate` (R15.2, R14); add `FieldSetReplace` (`fields: list[FieldIn]` min_length=1, optional `dependencies`) for `PUT /envelopes/{id}/fields` (R13); add `TemplateFieldIn` (geometry/type/required/label/placeholder + `template_role`), `FieldTemplateCreate` (`name` min_length=1, optional `agreement_type`, `fields` min_length=1, `roles` min_length=1), and the response models `FieldOut`, `EnvelopeFieldsOut` (`{ fields, recipients, editable }`), `FieldTemplateOut`, `FieldTemplateListResponse` (`{ items, total }`). Pydantic constraints are first-pass guards; cross-field rules stay in the pure validators. Also register the new expanded-contract error codes — `not_editable` (422), `dependency_cycle` (422), `template_not_found` (404), `template_role_unmapped` (422), and `invalid_signing_order` (422) — in **BOTH** `ESIGN_ERROR_MESSAGES` and `ESIGN_ERROR_STATUS` in `app/modules/esignatures/errors.py` (the real central tables), raised via `esign_error(code, message=...)` / `status_for_code(code)` so the edit (Tasks 16.4/16.6), dependency (17.3), signing-order (19.3), and template (20.4/21.1) paths reuse the humanized `{ message, code }` shape.
    - _Requirements: 13.1, 14.1, 14.3, 15.1, 15.3, 15.6, 17.1, 17.2_

  - [x] 15.2 Extend `frontend-v2/src/api/esign.ts` for the expanded contract
    - Add the `DependencyIn`, `TemplateField`, `FieldTemplate` types and extend `EnvelopeCreate` with optional `dependencies?: DependencyIn[]` and `signing_order_mode?: 'parallel' | 'sequential'`, plus the per-recipient `order?` field (R14, R15). Add the API functions `getEnvelopeFields(envelopeId, signal)` → `EnvelopeFieldsOut` and `replaceEnvelopeFields(envelopeId, body, signal)` (`PUT …/fields`, R13), and the template CRUD calls `listFieldTemplates`, `createFieldTemplate`, `getFieldTemplate`, `deleteFieldTemplate` against `/api/v2/esign/field-templates` (R17). All calls use typed generics, `?.` / `?? []`, no `as any`, and bind the in-flight request to an `AbortController` (R9.5).
    - _Requirements: 9.5, 13.1, 14.1, 15.1, 17.3, 17.4_

- [x] 16. Edit fields after send (R13)
  - [x] 16.1 Implement the pure `editable_state` predicate (`field_validation.py`)
    - Add `editable_state(status: str, recipients: list[RecipientState]) -> bool` to the existing pure module: returns True iff `status == "sent"` AND no recipient has signed (`not any(r.signed for r in recipients)`); every other condition (`viewed`-with-signing, `partially_signed`, `completed`, `declined`, `voided`, `error`, or any signed recipient) is a Non_Editable_State (R13.1, R13.4, R13.6). Each recipient's `signed` flag is **not** derived from any `_recipient_status_from_payload` helper (no such helper exists); it is derived from the persisted `esign_recipients.recipient_status` column (server default `"pending"`), which the Documenso webhook handler maintains via the pure `status.py` reducer (`RecipientState(signed: bool)`, `next_status`, and the Documenso event constants including `DOCUMENT_RECIPIENT_COMPLETED`). The implementer MUST align the set of `recipient_status` values treated as "signed" by `editable_state` with exactly the values the webhook handler writes, and reuse `status.py`'s existing `RecipientState`/status vocabulary rather than inventing a parallel type. Pure, no I/O.
    - _Requirements: 13.1, 13.4, 13.6_

  - [x] 16.2 Write property test for the Editable_State gate (Hypothesis)
    - **Property 18: Editable_State gate is exactly "sent and unsigned"** — over the full status set × recipient lists with arbitrary signed/unsigned states, the predicate is true iff status is `sent` AND no recipient has signed; and for any edit attempt outside the Editable_State the service rejects with `not_editable` and makes no Documenso field mutation (no delete, no create-many).
    - **Validates: Requirements 13.1, 13.4, 13.6**

  - [x] 16.3 Implement `DocumensoClient.replace_fields` (`app/integrations/documenso.py`)
    - Add `async def replace_fields(self, document_id, specs: list[DocumensoFieldSpec]) -> None`: read the document's current fields (`GET /document/{id}`), delete them, then `field/create-many` the new set — an **atomic replace** so only the edited set remains. Reuse the per-org `for_org` construction, raw-token header, explicit timeouts, and transient-failure retry. If either the delete or the create step fails, raise so the service leaves the prior set in effect (R13.3, R13.8). **This in-place delete + create-many replace path is CONDITIONAL on the capability probe (Task 9.2):** the `DocumensoClient` has **no** delete-field method today and no proven Documenso field-deletion/replacement endpoint exists (design capability assumption #3). It MUST first verify that Documenso supports deleting/replacing fields on a `sent`, unsigned document. If supported, ship this atomic/no-partial replace as described (only the edited set remains; either-step failure leaves the prior set intact). **If NOT supported, do not ship the in-place `PUT …/fields` path — edit-after-send degrades to Void_And_Recreate only** (proven via `cancel_document`); the Editable_State gate and re-validation are unchanged, only the persistence verb changes.
    - _Requirements: 13.3, 13.8_

  - [x] 16.4 Implement `get_envelope_fields` / `replace_envelope_fields` (`service.py`)
    - `get_envelope_fields(db, *, org_id, envelope_id)` loads the org-scoped envelope + recipients, reads the current Documenso fields, and returns `EnvelopeFieldsOut { fields, recipients, editable }` where `editable = editable_state(status, recipients)` (R13.1). `replace_envelope_fields(db, *, org_id, user_id, envelope_id, fields, dependencies)`: re-check `editable_state` (guarding a race where someone signed meanwhile) → Non_Editable_State → humanized **422 `not_editable`** offering Void_And_Recreate, no Documenso call (R13.4, R13.6); else re-validate with `validate_field_set` (same rules as send, R13.3) → on failure 422, no mutation → on success `DocumensoClient.replace_fields` (atomic) → on replace failure leave prior set intact + humanized **502**, no partial apply (R13.8) → on success write a best-effort `esign.envelope.fields_edited` audit entry (R13.7).
    - _Requirements: 13.1, 13.3, 13.4, 13.6, 13.7, 13.8_

  - [x] 16.5 Write property test for atomic field replace (Hypothesis, spy client + real test DB)
    - **Property 19: Editing replaces the Documenso field set atomically** — for any envelope in the Editable_State and any valid edited Field_Set, a successful edit issues a delete of existing fields followed by a single `field/create-many` of exactly the edited set (each field carrying its mapped type, page, Normalized_Coordinates, and `fieldMeta`), so only the edited set remains; and for any simulated replacement failure, no partial set is applied — the prior set is left in effect and a human-readable error is returned.
    - **Validates: Requirements 13.3, 13.8**

  - [x] 16.6 Add the `GET`/`PUT /envelopes/{id}/fields` endpoints (`router.py`)
    - Add `GET /api/v2/esign/envelopes/{id}/fields` → `EnvelopeFieldsOut` and `PUT /api/v2/esign/envelopes/{id}/fields` (body `FieldSetReplace`) → `{ fields }`, both behind the module gate + `require_esign_sender` (non-sender roles → 403, R13.2) and org-scoped. Map the Non_Editable_State path to the humanized **422 `not_editable`** code and a replace failure to **502 `documenso_error`** via the existing `esign_error` / `status_for_code` helpers.
    - _Requirements: 13.2, 13.4, 13.8, 12.1_

  - [x] 16.7 Wire the editor for edit-after-send (`FieldPlacementEditor.tsx`, `SendForSignatureModal.tsx`)
    - Give `FieldPlacementEditor` an optional `envelopeId` prop: when present it seeds the Field_Set from `getEnvelopeFields` (GET) and submits via `replaceEnvelopeFields` (PUT) instead of the create endpoint, reusing the whole editor + client validation unchanged (R13.1, R13.3). On a Non_Editable_State `not_editable` response, render a humanized banner offering **Void & recreate**, which calls the existing void endpoint then opens a fresh send pre-populated with a copy of the (read) Field_Set for editing before confirmation (R13.5). All consumption stays safe + AbortController-bound (R9.5).
    - _Requirements: 13.1, 13.3, 13.4, 13.5_

  - [x] 16.8 Write example tests for the edit flow (Vitest + RTL)
    - Opening the editor on an editable envelope seeds from GET and submits via PUT (R13.1, R13.3); a `not_editable` response renders the banner and the Void & recreate action opens a pre-populated fresh send (R13.4, R13.5).
    - _Requirements: 13.1, 13.4, 13.5_

- [x] 17. Conditional / dependent fields (R14) — advisory
  - [x] 17.1 Implement the pure `dependencyGraph.ts` (`frontend-v2/src/components/esign/lib/dependencyGraph.ts`)
    - Define `DependencyCondition`, `FieldDependency` (`dependentClientId`, `triggerClientId`, `condition`, `effect: 'show' | 'require'`) and the pure `addDependency(deps, edge) -> { ok: true; deps } | { ok: false; reason: 'self' | 'cycle' }`: reject a self-loop (`trigger === dependent`, R14.2) and reject an edge that would close a cycle over the dependent→trigger edges (R14.4); a rejected dependency is never added. Pure, no I/O. (This module is extracted to the shared core in Task 23.)
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [x] 17.2 Write property test for the dependency graph (fast-check)
    - **Property 20: The stored dependency graph is always acyclic and rejects self-loops** — over any sequence of dependency-add operations on a fixed Field_Set, the graph is acyclic at every step, an add is rejected iff its trigger equals its dependent (self-loop) or it would close a cycle, and a rejected dependency is never stored.
    - **Validates: Requirements 14.2, 14.4**

  - [x] 17.3 Implement the backend mirror `dependency_graph.py` (`app/modules/esignatures/dependency_graph.py`)
    - Pure server-side re-check of acyclicity + self-loop over the submitted `dependencies[]` (byte-for-byte the same rule set as `dependencyGraph.ts`): reject a self-loop or a cycle-closing edge with a humanized `dependency_cycle` / `dependency_self` error so a crafted payload cannot bypass the client check (R14.2, R14.4). Pure, no I/O.
    - _Requirements: 14.2, 14.4_

  - [x] 17.4 Write unit test for the backend dependency-graph mirror (pytest)
    - Assert `dependency_graph.py` rejects a self-loop and a cycle-closing edge and accepts an acyclic set, matching `dependencyGraph.ts` (parity with the Property 20 cases; not a separate property).
    - _Requirements: 14.2, 14.4_

  - [x] 17.5 Implement `DependencyInspector.tsx` + advisory notice
    - For the selected field, define/edit a Field_Dependency (pick a Trigger_Field from the other fields in the set, a Dependency_Condition, and an effect of `show`/`require`), routing every add through `addDependency` and surfacing the `self`/`cycle` rejection inline (R14.1–R14.4). Display a human-readable **advisory notice** that the dependency is recorded but not enforced during signing (R14.7). All controls ≥44×44 px.
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.7_

  - [x] 17.6 Resolve advisory enforcement: degrade require→optional + thread `dependencies[]` (`field_mapping.py`, `service.py`)
    - In `field_mapping.py`, extend `build_field_meta` so a field that is the dependent of a `require`-effect **advisory** dependency is emitted with `required = false` so an unmet advisory condition can never block a recipient (R14.8). In `service.py`, on send/edit re-run `dependency_graph` (reject cycles/self-loops), then resolve the Dependency_Enforcement_Mode to **`advisory`** for every dependency (Documenso has no cross-field conditional primitive), present **every** field on Documenso unconditionally (no field suppressed), and pass the advisory require-dependents into `build_field_meta`. Encode the `enforced` branch as a **documented forward-compat no-op stub** (R14.5) that is not wired today (R14.6). **Note (capability assumption #2):** whether `field/create-many` accepts/honours `fieldMeta` (`required`/`label`/`placeholder`) at all must be confirmed by the capability probe (Task 9.2). If `fieldMeta` is unsupported, `build_field_meta` is a no-op on the wire and the `required = false` degrade is OraInvoice-advisory only — R14.8 still holds trivially since nothing is engine-enforced.
    - _Requirements: 14.5, 14.6, 14.8_

  - [x] 17.7 Write property test for advisory dependencies (Hypothesis)
    - **Property 21: Advisory dependencies present every field and degrade require-effects to optional** — for any Field_Set and any acyclic set of advisory dependencies, the field set created on Documenso contains every placed field (none suppressed), and any field that is the dependent of a `require`-effect advisory dependency is created with `required = false` in its `fieldMeta`.
    - **Validates: Requirements 14.6, 14.8**

  - [x] 17.8 Wire the dependency model into the editor (`FieldPlacementEditor.tsx`)
    - Mount `DependencyInspector` for the selected field, hold the `FieldDependency[]` in editor state (via `addDependency`), and thread it onto the wire as `dependencies[]` on create and `PUT …/fields` (using the `api/esign.ts` additions from Task 15.2). Render the advisory notice whenever any dependency exists (R14.7).
    - _Requirements: 14.1, 14.7_

  - [x] 17.9 Write example test for the advisory notice (Vitest + RTL)
    - Defining a dependency shows the advisory "recorded but not enforced" notice (R14.7); a self-loop / cycle add is rejected in the UI (R14.2, R14.4).
    - _Requirements: 14.2, 14.4, 14.7_

- [x] 18. Checkpoint - Ensure all edit-after-send and conditional-field tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 19. Signing-order UI (R15)
  - [x] 19.1 Implement `SigningOrderControls.tsx` and wire it into the modal
    - Add a `SigningOrderControls` block to `SendForSignatureModal.tsx` step 1: a parallel/sequential toggle defaulting to **parallel** (R15.1, R15.2) and, when sequential, a drag-to-reorder list of the **signing** recipients assigning distinct 1-based positions (R15.3); viewers are listed as "on document, not in signing order" (R15.6). The chosen `signing_order_mode` and per-recipient `order` travel on the send payload (`api/esign.ts` additions from Task 15.2). All controls ≥44×44 px.
    - _Requirements: 15.1, 15.2, 15.3, 15.6_

  - [x] 19.2 Add signing-order to `DocumensoClient` (`app/integrations/documenso.py`)
    - Extend `RecipientSpec` with `signing_order: int | None = None` (1-based; None for parallel/viewers) and thread a `distribution_mode` (`"SEQUENTIAL"` | `"PARALLEL"`) through `create_document` / `send_document` so each recipient's `signingOrder` position and the distribution mode reach Documenso (R15.4, R15.5). Additive; the create→upload→fields→distribute ordering is unchanged. **Gated behind the capability probe (Task 9.2):** `send_document` today sends only `meta.distributionMethod: "EMAIL"`, so per-recipient `signingOrder` + `SEQUENTIAL`/`PARALLEL` are unverified (design capability assumption #4). If the probe confirms create/distribute accept and enforce signing order, ship enforcement; **if unsupported, sequential degrades to parallel** with a clear advisory note that order is recorded but not enforced — the additive schema fields (`signing_order_mode`, per-recipient `order`) are still accepted and stored regardless.
    - _Requirements: 15.4, 15.5_

  - [x] 19.3 Thread `signing_order_mode` + per-recipient `order` through the service (`service.py`)
    - In `create_and_send_envelope`, map `signing_order_mode` to the Documenso distribution mode (`sequential`→`SEQUENTIAL`, else `PARALLEL`, R15.4/R15.5) and assign each signing recipient its 1-based `signingOrder` position while excluding viewers from positions but keeping them as recipients on the document (R15.6).
    - _Requirements: 15.4, 15.5, 15.6_

  - [x] 19.4 Write property test for signing-order mapping (Hypothesis, spy client)
    - **Property 22: Signing-order positions and distribution mode map faithfully** — for any recipient list mixing signers/viewers and any mode, the distribution mode is `SEQUENTIAL` when sequential and `PARALLEL` otherwise; in sequential mode the `signingOrder` positions over signing recipients are pairwise distinct, 1-based, and contiguous (a permutation of `1..N`), while viewers receive no position yet still appear as recipients.
    - **Validates: Requirements 15.3, 15.4, 15.5, 15.6**

- [x] 20. Saved field templates — store + service (R17 backend)
  - [x] 20.1 Alembic migration 0234: `esign_field_templates` table + RLS
    - Confirm `alembic current` head is **0233** (`2026_06_28_0003-0233_esign_perf_indexes.py`) on each node before authoring. Create a new revision `0234` parented on `0233`, idempotent throughout. `CREATE TABLE IF NOT EXISTS esign_field_templates` with columns `id` (UUID PK, `gen_random_uuid()`), `org_id` (UUID NOT NULL), `name` (Text NOT NULL), `agreement_type` (Text NULL, R17.2), `fields` (JSONB NOT NULL — `TemplateField[]`), `roles` (JSONB NOT NULL — distinct Template_Recipient_Role slots, R17.1), `created_at`/`updated_at` (timestamptz, server default now), `created_by` (UUID NULL). Enable RLS + a `tenant_isolation` policy using `current_setting('app.current_org_id', true)::uuid` with `USING` + `WITH CHECK`, mirroring `esign_envelopes` (migration 0232). The `CREATE TABLE` + RLS-policy statements run in the **normal transactional body** of the migration; the two indexes run in the **autocommit block** of the same migration (because `CREATE INDEX CONCURRENTLY` cannot run inside a transaction). Create the `org_id` and `(org_id, agreement_type)` indexes with raw `CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_esign_field_templates_org ON esign_field_templates (org_id)` and `CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_esign_field_templates_org_agreement ON esign_field_templates (org_id, agreement_type)` inside `op.get_context().autocommit_block()` — **NOT** `op.create_index`, which is BANNED per `database-migration-checklist`. `downgrade()` drops the policy and the table (transactional body) and drops both indexes with matching `DROP INDEX CONCURRENTLY IF EXISTS ix_esign_field_templates_org` / `DROP INDEX CONCURRENTLY IF EXISTS ix_esign_field_templates_org_agreement` inside an `op.get_context().autocommit_block()`. Follow the canonical template `alembic/versions/2026_05_30_2300-0202_add_perf_indexes.py`.
    - _Requirements: 17.1, 17.2, 17.3, 17.4_

  - [x] 20.2 Add the `EsignFieldTemplate` ORM model (`app/modules/esignatures/models.py`)
    - Define `EsignFieldTemplate` mapped to the migration table: `id`, `org_id`, `name`, `agreement_type` (nullable), `fields` (JSONB list), `roles` (JSONB list), `created_at`/`updated_at`/`created_by`.
    - _Requirements: 17.1, 17.2_

  - [x] 20.3 Write migration + RLS smoke test (pytest)
    - Assert migration 0234 applies, reverts, and is idempotent on re-run against head 0233; assert RLS isolation — with `app.current_org_id` = org A, org B's `esign_field_templates` rows are invisible.
    - _Requirements: 17.3, 17.4_

  - [x] 20.4 Implement `templates_service.py` CRUD (`app/modules/esignatures/templates_service.py`)
    - Implement org-scoped CRUD over `EsignFieldTemplate`: `create_template` (stores `name`, optional `agreement_type`, `fields` JSONB, `roles` JSONB — **never** any recipient name/email, R17.1/R17.2), `list_templates` (org-scoped `{ items, total }`, RLS-enforced, R17.3), `get_template` (org-scoped fetch to apply), `delete_template` (removes only the caller-org's template, R17.4). Use `flush()` + `await db.refresh()` before serialising.
    - _Requirements: 17.1, 17.2, 17.3, 17.4_

  - [x] 20.5 Apply and verify migration 0234 against the running dev database
    - Per `database-migration-checklist`, applying the migration in the container is **mandatory** (not optional). Run `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head` in the dev container. Confirm `alembic current` reports head **0234**. Verify the `esign_field_templates` table exists with its `tenant_isolation` RLS policy enabled and **both** CONCURRENTLY indexes present (`ix_esign_field_templates_org`, `ix_esign_field_templates_org_agreement`). This must be done before the feature is considered complete.
    - _Requirements: 17.3, 17.4_

- [x] 21. Saved field templates — endpoints + client apply (R17)
  - [x] 21.1 Add the `/api/v2/esign/field-templates` endpoints (`router.py`)
    - Add `POST /field-templates` (body `FieldTemplateCreate`) → `FieldTemplateOut`, `GET /field-templates` → `{ items, total }`, `GET /field-templates/{id}` → `FieldTemplateOut`, and `DELETE /field-templates/{id}` → 204, all behind the module gate + `require_esign_sender` (non-sender roles → 403, R17.7) and org-scoped under RLS (R17.3, R17.4). Reuse the humanized `{ message, code }` error shape.
    - _Requirements: 17.3, 17.4, 17.7_

  - [x] 21.2 Write property test for template org-isolation (Hypothesis, real test Postgres)
    - **Property 25: Templates are isolated per organisation** — for any two organisations each owning templates, listing while scoped to one org returns only that org's templates and never the other's, and a delete scoped to one org cannot remove another org's template — enforced by the `tenant_isolation` RLS policy on `esign_field_templates`.
    - **Validates: Requirements 17.3, 17.4**

  - [x] 21.3 Implement the pure `applyTemplate.ts` (`frontend-v2/src/components/esign/fieldplacement/lib/applyTemplate.ts`)
    - Define `TemplateField` (`type`, `page`, `rect: NormalizedRect`, `required`, optional `label`/`placeholder`, `templateRole`) and the pure `applyTemplate(fields, roleMap) -> { ok: true; placed: PlacedField[] } | { ok: false; unmappedRoles: string[] }`: map each distinct `templateRole` to a current-send `recipientKey`, producing exactly one `PlacedField` per template field (preserving type/page/coords/required/text meta); fail — naming the unmapped roles and producing no placed fields — when any role is unmapped, so no applied field is ever left unassigned (R17.5, R17.6). Pure, no I/O.
    - _Requirements: 17.5, 17.6_

  - [x] 21.4 Write property test for template apply (fast-check)
    - **Property 26: Applying a template is faithful and total over roles** — for any template and any role-to-recipient mapping, applying succeeds only when every Template_Recipient_Role is mapped — yielding exactly one placed field per template field, each preserving the stored type, page, Normalized_Coordinates, required flag, and text metadata and assigned to the mapped recipient — and otherwise fails, naming the unmapped roles and producing no placed fields.
    - **Validates: Requirements 17.5, 17.6**

  - [x] 21.5 Wire save-current-set and apply-into-editor (`FieldPlacementEditor.tsx` + template UI)
    - Add a pure `buildTemplate(fields, recipientKeyToRole)` helper that serialises the current Field_Set into a `FieldTemplateCreate` storing per-field `templateRole` + the distinct `roles[]` and **no** recipient name/email (R17.1), plus a "Save as template" control calling `createFieldTemplate`. Add a template picker that fetches a template (`getFieldTemplate`), shows a **role→recipient mapping UI** that prompts until every role resolves (refusing to apply while any role is unmapped, R17.6), runs `applyTemplate`, and feeds the resulting `PlacedField[]` into the editor — which then goes through the same `validateFieldSet` as any other set before send (R17.8). All consumption safe + AbortController-bound.
    - _Requirements: 17.1, 17.5, 17.6, 17.8_

  - [x] 21.6 Write property test for template serialization (fast-check)
    - **Property 24: Saved templates store roles, never people** — for any Field_Set and any assignment of its fields to recipients, the template produced by `buildTemplate` stores, per field, the type, page, Normalized_Coordinates, required flag, and (for text) label/placeholder together with a Template_Recipient_Role slot, and its serialized form contains no recipient name and no recipient email anywhere.
    - **Validates: Requirements 17.1**

  - [x] 21.7 Write property test for edit + template RBAC (Hypothesis)
    - **Property 16: Role-based access control for field-placement send, edit, and templates** (edit + template portion) — a post-send Field_Set edit (`PUT …/fields`, R13) and a template create/apply/delete (R17) are each permitted iff the user holds `org_admin`, `branch_admin`, or `location_manager`; all other roles → HTTP 403. (Send portion is covered in Task 14.2.)
    - **Validates: Requirements 13.2, 17.7**

- [x] 22. Checkpoint - Ensure all signing-order and template tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 23. Shared pure core for web + mobile (R16 prep)
  - [x] 23.1 Extract the pure core to `@shared/esign/` and update `frontend-v2` imports
    - Move the framework-agnostic pure modules — `coordinateMapping.ts`, `fieldValidation.ts`, and `dependencyGraph.ts` — to a shared location consumable by both apps (`@shared/esign/`, per the repo's `@shared/` convention) and update every `frontend-v2/` import to the shared path. If a shared package proves impractical, **duplicate the three modules verbatim** into `mobile/` and rely on the parity test (23.2) to prove byte-for-byte identical behaviour. No logic change — pure relocation.
    - _Requirements: 16.9_

  - [x] 23.2 Write parity test for the shared core (fast-check)
    - If the modules are duplicated rather than shared, assert the web and mobile copies of `validateFieldSet` (and `coordinateMapping`/`dependencyGraph`) produce identical results over generated inputs; if truly shared via `@shared/esign/`, assert both apps import the same module instance (no divergent copy).
    - _Requirements: 16.9_

- [x] 24. Mobile field-placement editor (R16)
  - [x] 24.1 Add `pdfjs-dist` to `mobile/` and implement `mobile/src/api/esign.ts`
    - Add `pdfjs-dist` to `mobile/package.json` pinned to the **exact** same version as `frontend-v2/`; bundle the worker via Vite. Implement `mobile/src/api/esign.ts` issuing the identical multipart `POST /api/v2/esign/envelopes` contract (`fields[]`, `dependencies[]`, `signing_order_mode`) against the v2 absolute path, consuming responses with typed generics + `?.` / `?? []` and binding every in-flight request to an `AbortController` aborted on unmount/cancel (R16.7, R16.8).
    - _Requirements: 16.7, 16.8_

  - [x] 24.2 Implement the mobile editor screens (`mobile/src/screens/esign/`)
    - Implement `EsignSendScreen` (step 1 composer + step 2 editor), `MobileFieldPlacementEditor` (orchestrator), `MobilePdfPage` (one page via `pdfjs-dist`), and `TouchFieldOverlay` (selected-field nudge/resize controls, each ≥44×44 px). Support **Touch_Place**: select a Field_Type then tap a page position to place a field; adjust a selected field with on-screen nudge/resize controls (R16.4, R16.5). Placement/adjustment go through the same shared `clampToPage` + coordinate mapping so geometry invariants hold identically; support the 320–430 px viewport (R16.6). Use the shared `validateFieldSet` to gate the send control (R16.9). Safe consumption + AbortController throughout (R16.8).
    - _Requirements: 16.4, 16.5, 16.6, 16.7, 16.9_

  - [x] 24.3 Add the More-menu entry + `ModuleGate` (`mobile/src/navigation/MoreMenuConfig.ts`, `mobile/src/navigation/StackRoutes.tsx`, `mobile/src/screens/more/MoreMenuScreen.tsx`)
    - Add the More-menu entry `{ moduleSlug: 'esignatures', roles: ['org_admin','branch_admin','location_manager'] }` to the menu config in `mobile/src/navigation/MoreMenuConfig.ts` (NOT `screens/MoreMenuScreen.tsx`), add the lazy route to `mobile/src/navigation/StackRoutes.tsx`, and let `mobile/src/screens/more/MoreMenuScreen.tsx` render the configured entries. The screen itself lives under `mobile/src/screens/esign/`. Wrap `EsignSendScreen` content in `ModuleGate moduleSlug="esignatures"` so the editor is withheld when the module is disabled (R16.1) or the user lacks an org-sender role (R16.2, R16.3).
    - _Requirements: 16.1, 16.2, 16.3_

  - [x] 24.4 Write property test for validation parity (fast-check, mobile)
    - **Property 23: Mobile and web editors reach identical validation verdicts** — for any Field_Set and recipient list, the mobile editor and the `frontend-v2/` editor produce the same send-validation verdict (both run the shared pure validation core), and each enables its send control iff that verdict is valid — including the rule that every signing recipient has ≥1 signature-type field.
    - **Validates: Requirements 16.9**

  - [x] 24.5 Write example tests for the mobile editor (Vitest + RTL)
    - The More-menu entry is gated by the `esignatures` module and org-sender roles (R16.1–R16.3); Touch_Place places a field on tap and nudge/resize controls meet the 44×44 px minimum across the 320–430 px range (R16.4, R16.5, R16.6); the send call uses the same contract, typed generics, and AbortController (R16.7, R16.8).
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8_

- [x] 25. Checkpoint - Ensure all mobile tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 28. End-to-end Org_Sender flow test (per `feature-testing-workflow`)
  - [x] 28.1 Author `scripts/test_esign_field_placement_e2e.py` emulating a real Org_Sender flow
    - Per `feature-testing-workflow` (which requires a `scripts/test_*_e2e.py` for every new feature), write `scripts/test_esign_field_placement_e2e.py` that drives the running app as a real Org_Sender against live HTTP endpoints (not unit-mocked). Flow: **log in as an org sender** to obtain a token; **module-gated `POST /api/v2/esign/envelopes`** with a sender-defined `fields[]` set, asserting the create→fields→distribute sequence happened and the envelope persisted with status `sent`; an **edit-after-send `GET …/fields` then `PUT …/fields` round-trip** on an editable (sent/unsigned) envelope; a **template create/list/apply/delete round-trip** against `/api/v2/esign/field-templates`. Include the OWASP/access-control checks the steering requires: **401** without a token, **403** for a non-sender role, **403** when the `esignatures` module is disabled, and **org-isolation/IDOR** checks on templates and envelopes (another org's ids return not-found/forbidden, never leaked). **Mandatory cleanup:** all created data uses a `TEST_E2E_` prefix and is deleted in reverse-dependency order inside a `finally` block (so a mid-run failure still cleans up). Print a pass/fail summary at the end.
    - _Requirements: 9.1, 9.2, 9.3, 13.1, 13.3, 13.4, 17.3, 17.4, 17.7_

- [x] 26. Version bump and changelog
  - [x] 26.1 Bump versions, pin `pdfjs-dist` in both apps, note migration 0234, add changelog entry
    - Bump the MINOR version in `pyproject.toml`, `frontend-v2/package.json`, **and** `mobile/package.json` (verify mobile version per `versioning-and-changelog.md`), confirm `pdfjs-dist` is pinned to the **same exact** version in both `frontend-v2/package.json` and `mobile/package.json`, and add a top `CHANGELOG.md` entry describing the e-signature field-placement editor plus the expanded capabilities (edit-after-send, advisory conditional fields, signing-order UI, mobile editor, saved templates) and the new **migration 0234** (`esign_field_templates`).
    - _Requirements: (release hygiene per `versioning-and-changelog`)_

- [ ] 27. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation sub-tasks are never optional.
- Each task references specific requirement sub-clauses and, for property test tasks, the exact design property number for traceability.
- **Base feature (R1–R12, Tasks 1–14) is unchanged.** The expansion (R13–R17, Tasks 15–24) builds on it: edit-after-send reuses the same editor + `validate_field_set`; conditional fields, signing order, and the mobile editor all reuse the same pure cores and (except templates) the same backend contract.
- **One new table only: `esign_field_templates` (migration 0234, R17).** Confirm `alembic current` head is **0233** before authoring 0234; the RLS `tenant_isolation` policy mirrors `esign_envelopes` (migration 0232). The per-send Field_Set (R1–R12), edit-after-send (R13, re-reads the live set from Documenso), advisory dependencies (R14), and signing order (R15) all reflect into the existing `esign_envelopes` / `esign_recipients` rows.
- **Conditional logic is advisory, not enforced (R14).** Documenso has no cross-field conditional primitive, so the Dependency_Enforcement_Mode is `advisory` for every dependency: all fields are presented unconditionally, a `require`-effect advisory dependent is emitted `required = false` (Property 21), and the editor shows the advisory notice. The `enforced` branch is a documented forward-compat no-op stub (R14.5), not wired today.
- **Edit-after-send is an atomic replace (R13).** The `editable_state` gate is a pure predicate (`status == 'sent'` AND nobody signed — Property 18); a successful edit deletes the existing Documenso fields and `field/create-many`s the edited set (Property 19); a Non_Editable_State returns 422 `not_editable` and offers Void & recreate; a replace failure leaves the prior set intact with no partial apply.
- **Mobile is IN scope (R16).** The pure core (`coordinateMapping` + `fieldValidation` + `dependencyGraph`) is shared (or duplicated verbatim with a parity test, Task 23) so the mobile and web editors reach identical validation verdicts (Property 23). The mobile editor honours the mobile steering guide: org-sender roles only, v2 absolute paths, safe consumption + `AbortController`, 44 px touch targets, the 320–430 px viewport, the `esignatures` `ModuleGate`, and Touch_Place.
- Property-based tests use **fast-check** (frontend + mobile pure core — Properties 1–10, 20, 23, 24, 26) and **Hypothesis** (backend — Properties 8–22, 25), a minimum of 100 examples each, one property → one test, tagged `// Feature: esignature-field-placement, Property {n}: {property_text}` (TS) / `# Feature: esignature-field-placement, Property {n}: {property_text}` (Python). Service-level properties use a real test Postgres plus a spy/mock `DocumensoClient` — no real Documenso call is ever made, the per-org token is asserted on each call, and nothing is created/mutated on rejection paths.
- All 26 correctness properties are covered: base P1–P17 (Tasks 1–14), plus P18 (16.2), P19 (16.5), P20 (17.2), P21 (17.7), P22 (19.4), P23 (24.4), P24 (21.6), P25 (21.2), P26 (21.4); Property 16 is split into a send portion (14.2) and an edit + template portion (21.7). Example/integration/smoke tests cover the EXAMPLE/INTEGRATION/SMOKE-classified criteria.
- Checkpoints provide incremental validation at the boundaries of the frontend pure core, the editor/renderer, the backend send path, edit-after-send + conditional fields, signing-order + templates, and the mobile editor.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.2", "5.1", "8.1", "8.2", "9.1", "9.2"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1", "2.7", "5.2", "8.3", "8.4", "8.5", "10.1"] },
    { "id": 2, "tasks": ["2.3", "2.4", "2.5", "2.6", "3.1", "5.3", "11.1"] },
    { "id": 3, "tasks": ["3.2", "6.1", "6.2", "6.3", "11.2", "11.3", "11.4", "11.5", "11.6", "11.7"] },
    { "id": 4, "tasks": ["6.4", "6.5", "6.6", "6.7", "6.8", "13.1", "14.1"] },
    { "id": 5, "tasks": ["13.2", "14.2", "14.3", "14.4"] },
    { "id": 6, "tasks": ["13.3", "13.4", "15.1", "15.2", "16.1", "17.1", "17.3", "20.1", "20.2"] },
    { "id": 7, "tasks": ["16.2", "17.2", "17.4", "16.3", "17.5", "20.3", "20.4", "20.5"] },
    { "id": 8, "tasks": ["16.4", "16.7", "19.2", "21.1", "21.3"] },
    { "id": 9, "tasks": ["16.5", "16.6", "16.8", "17.6", "17.8", "21.2", "21.4"] },
    { "id": 10, "tasks": ["17.7", "17.9", "19.1", "19.3", "21.7"] },
    { "id": 11, "tasks": ["19.4", "21.5"] },
    { "id": 12, "tasks": ["21.6", "23.1"] },
    { "id": 13, "tasks": ["23.2", "24.1"] },
    { "id": 14, "tasks": ["24.2", "24.3"] },
    { "id": 15, "tasks": ["24.4", "24.5"] },
    { "id": 16, "tasks": ["28.1"] },
    { "id": 17, "tasks": ["26.1"] }
  ]
}
```
