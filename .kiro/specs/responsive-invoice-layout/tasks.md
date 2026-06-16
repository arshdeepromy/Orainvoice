# Implementation Plan: Responsive Invoice Layout

## Overview

Frontend-only change in `frontend-v2/`. The work is sequenced so the pure layout-decision
logic and its property test land first, then the viewport-observation hook, then the
`InvoiceList` master/detail wiring, then POS container-query stacking, then the sidebar
Compact_Band CSS, then the no-clip safety net, and finally a manual/Playwright visual
verification pass plus a typecheck/test-suite run.

Stack: React 19 + TypeScript, Tailwind CSS v4 (`@container`), Vitest + React Testing
Library, fast-check for property tests. Test command: `npm run test` (`vitest --run`).
Typecheck: `tsc -b` (via `npm run build`). No backend, DB, or API tasks.

Property tests use fast-check with **≥100 iterations** and are tagged
`// Feature: responsive-invoice-layout, Property {n}: ...`. They mock `window.matchMedia`
where a tier needs simulating. Visual/breakpoint/container-query/print behavior has no
layout engine under jsdom and is verified manually/Playwright (task 7).

## Tasks

- [x] 1. Pure pane-resolution helper
  - [x] 1.1 Create `frontend-v2/src/pages/invoices/responsiveLayout.ts`
    - Export `NarrowPane` (`'list' | 'detail'`) and `PaneVisibility` (`showList`, `showDetail`, `showBackControl`)
    - Implement pure `resolvePaneVisibility(isWide, hasSelection, narrowPane, isCreating)` exactly per the design truth table
    - Encode the create-view rule: below Wide with `isCreating` ⇒ `showDetail && showBackControl && !showList` (Create_View is the sole pane); at/above Wide ⇒ both panes shown regardless of `isCreating`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 2.1, 2.2, 8.1, 8.2, 8.3_

  - [x] 1.2 Write property test for `resolvePaneVisibility` truth table
    - File `frontend-v2/src/pages/invoices/__tests__/responsiveLayout.property.test.ts`, fast-check, ≥100 iterations
    - **Property 1: Pane-resolution truth table** — over generated `(isWide, hasSelection, narrowPane, isCreating)` assert: wide ⇒ `showList && showDetail && !showBackControl`; not-wide ⇒ `showList !== showDetail`; not-wide & `isCreating` ⇒ `showDetail && showBackControl && !showList`; not-wide & not-creating & no selection ⇒ `showList`; not-wide & not-creating & selection & `narrowPane==='detail'` ⇒ `showDetail`; `showBackControl === (!isWide && showDetail)`
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.6, 2.1, 2.2, 6.3, 8.1, 8.2, 8.3**

- [x] 2. Viewport-observation hook
  - [x] 2.1 Add `useMediaQuery` hook backed by `window.matchMedia`
    - Create `frontend-v2/src/hooks/useMediaQuery.ts`; subscribe via `addEventListener('change', ...)` (not a resize listener), clean up on unmount
    - Guard missing `window.matchMedia` so unsupported environments default to the Wide tier (returns matched/`true` for the wide query) rather than throwing
    - _Requirements: 1.1, 1.2_

  - [x] 2.2 Write unit tests for `useMediaQuery`
    - File `frontend-v2/src/hooks/__tests__/useMediaQuery.test.ts`, mock `window.matchMedia`
    - Assert: returns current match, updates on a `change` event, removes its listener on unmount, and defaults to the Wide tier when `matchMedia` is absent
    - _Requirements: 1.1, 1.2_

- [x] 3. InvoiceList master/detail wiring + Back-to-list control
  - [x] 3.1 Wire conditional master/detail rendering into `InvoiceList.tsx`
    - Add `isWide` via `useMediaQuery('(min-width: 1280px)')` and `narrowPane` state (`'list' | 'detail'`), initializing `narrowPane` from the route at mount: `(routeId || isCreating) ? 'detail' : 'list'`
    - Render list/detail/back from `resolvePaneVisibility`; keep `selectedId`/`selectedIdRef`/`invoice`/the `selectedId`-keyed `fetchDetail` effect unchanged so crossing the threshold never refetches
    - The auto-select effect (`setSelectedId(invoices[0].id)`) MUST NOT set `narrowPane`, so a bare narrow load without a `routeId` stays on the list even when an invoice auto-selects
    - Selecting a row while narrow sets `narrowPane = 'detail'` AND navigates to `/invoices/:id`; the selected list row keeps its existing persistent selected-state styling
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.4, 2.5, 2.8_

  - [x] 3.2 Add the `Back_To_List_Control` and focus management
    - Native `<button>` at the top of the detail region, rendered only when `showBackControl`; on activate set `narrowPane = 'list'`, call `navigate('/invoices')` (Invoices_List_Path) WITHOUT clearing `selectedId` (so the list row keeps its highlight), and move focus into the list region
    - On a responsive transition that hides the focused region, move focus to a visible interactive element in the newly shown region (guarded `ref.current?.focus()`)
    - _Requirements: 2.1, 2.2, 2.3, 2.6, 2.7, 7.1, 7.3_

  - [x] 3.3 Write property test for selection-identity preservation
    - File `frontend-v2/src/pages/invoices/__tests__/selection.property.test.ts`, fast-check, ≥100 iterations
    - **Property 2: Selection identity preserved across tier and back transitions** — generate a `selectedId` and a random sequence of `toggleTier`/`back` operations; assert `selectedId` is invariant under them (never cleared/mutated/refetched), and that `back` navigates the route to `/invoices` without mutating `selectedId`
    - **Validates: Requirements 1.5, 2.5, 2.7**

  - [x] 3.4 Write unit tests for master/detail + Back control (RTL, mocked `matchMedia`)
    - Back control is a native `<button>`, Tab-reachable, activates on Enter **and** Space, and moves focus to the list region (Req 2.6, 7.3)
    - Narrow screen: selecting a row shows the detail region; activating Back shows the list region with the previously selected row still carrying its selected-state styling/`aria` (Req 2.3, 2.4, 2.5)
    - Deep-link mount: mounting below the Wide_Threshold with a `routeId` initializes `narrowPane = 'detail'` and renders the Invoice_Detail_Region for that invoice (Req 1.7)
    - Bare mount: mounting below the Wide_Threshold with no `routeId` renders the Invoice_List_Column and stays on the list even after the auto-select effect sets a `selectedId` (Req 1.8, 1.9)
    - Back navigates and keeps highlight: activating Back below the Wide_Threshold calls `navigate('/invoices')` while `selectedId` is unchanged (row keeps its selected-state indicator); reselecting that row navigates to `/invoices/:id` and shows detail (Req 2.7, 2.8)
    - Create route on narrow: with `isCreating` true (route `/invoices/new`) below the Wide_Threshold, the Create_View (`InvoiceCreate`) is the sole visible pane and the Back_To_List_Control is shown (Req 8.1, 8.2)
    - A simulated `matchMedia` `change` moves focus into the newly shown region and triggers no settings-mutation API call (Req 7.1, 4.6)
    - _Requirements: 1.7, 1.8, 1.9, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 4.6, 7.1, 7.3, 8.1, 8.2_

  - [x] 3.5 Wire Create_View single-pane behavior in `InvoiceList.tsx`
    - Below the Wide_Threshold, the `/invoices/new` (`isCreating`) Create_View is the sole visible pane (no Invoice_List_Column beside it) with the Back_To_List_Control shown; because initial `narrowPane` is `'detail'` when `isCreating`, a narrow mount on `/invoices/new` shows the Create_View immediately
    - At/above the Wide_Threshold, the existing side-by-side arrangement of the Invoice_List_Column and the Create_View is unchanged
    - The Edit_Route (`/invoices/:id/edit`) remains a separate full-page route outside the single-pane logic (out of scope)
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 4. Checkpoint - master/detail
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. POS receipt panel responsive stacking
  - [x] 5.1 Make the detail scroll region a container and stack POS below at <900px
    - Add `container-type: inline-size` (Tailwind v4 `@container`, named e.g. `@container/detail`) to the `flex-1 overflow-y-auto` detail wrapper in `InvoiceList.tsx`
    - Switch the preview row from row to column when the container is `<900px` (`@max-[900px]/detail:flex-col`); when stacked, the invoice column spans full width and the POS panel drops underneath at full/`max-w` width instead of `w-[280px]`
    - Keep `posPreviewEnabled` gating and `selectedPreview` click-to-highlight unchanged
    - _Requirements: 3.1, 3.2, 3.4, 3.5_

  - [x] 5.2 Write property test for POS enablement gating
    - File `frontend-v2/src/pages/invoices/__tests__/posGating.property.test.ts`, fast-check, ≥100 iterations
    - **Property 3: POS preview enablement gates panel and print action together** — over `posPreviewEnabled ∈ {true,false}` assert the POS_Receipt_Panel is present iff the flag is true AND the "Print POS Receipt" action is present iff the flag is true (both equal the flag)
    - **Validates: Requirements 3.3, 6.5**

  - [x] 5.3 Write unit tests for POS gating and print rule (RTL, mocked `matchMedia`)
    - `posPreviewEnabled = false` removes both the POS panel and the Print POS Receipt menu item; `selectedPreview` toggling still works irrespective of layout (Req 3.3, 3.5)
    - The in-file `PRINT_STYLES` block still contains the `[data-preview="receipt"] { display: none }` rule (print regression guard) (Req 6.1, 6.2)
    - _Requirements: 3.3, 3.5, 6.1, 6.2, 6.5_

- [x] 6. Responsive icon-only sidebar (Compact_Band) and no-clip safety net
  - [x] 6.1 Add Compact_Band icon-only rail CSS in `shell.css` and accessible labels in `Sidebar.tsx`
    - In `frontend-v2/src/styles/shell.css`, add a `@media (min-width: 861px) and (max-width: 1279px)` block scoped to `.shell-sidebar`: narrow the rail (264px → ~72px), hide nav label/group-heading text visually, center icons; the reclaimed width flows to `.shell-main` via the existing flex layout
    - Collapse the header wordmark and the footer OrgSwitcher (not just nav labels) into an icon-only/collapsed treatment so they remain usable and do NOT overflow the ~72px rail (Req 4.9)
    - Author the Compact_Band rules in `frontend-v2/src/styles/shell.css` (which is intentionally unlayered and `@import`ed after Tailwind), inside `@media (min-width: 861px) and (max-width: 1279px)`, scoped with the selector `.app-shell .shell-sidebar` — the SAME selector/layering the existing ≤860px drawer rule already uses; set the rail width via `.app-shell .shell-sidebar { width: var(--rail-icon, 72px); }`
    - This beats the Tailwind `.w-rail` utility on both counts (unlayered-beats-layered AND specificity (0,2,0) > (0,1,0)); no `!important`, no double-class hack, no `aside` qualifier needed
    - Scope the label / group-heading / header wordmark / footer OrgSwitcher collapse rules under `.app-shell .shell-sidebar …` in the same media block (unlayered) so they reliably override Tailwind utilities
    - Sanity check: confirm the computed rail width ≈72px at a ~1024px viewport (routine wiring check, not a cascade risk)
    - Keep label text in the DOM (visually hidden, not removed) so each nav item's accessible name is exposed; add `aria-label` on `Sidebar.tsx` nav items as a belt-and-braces measure
    - The wide rail (`≥1280px`) is unchanged from its current appearance; the Compact_Band treatment is presentation-only and MUST NOT persist or write `sidebar_display_mode`; the `≤860px` drawer tier is untouched
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9_

  - [x] 6.2 Write unit tests for icon-only nav accessibility and no-persistence
    - File `frontend-v2/src/components/shell/__tests__/Sidebar.compactBand.test.tsx`, RTL
    - Assert each nav item still exposes an accessible name (label text / `aria-label`) under the icon-only treatment (Req 4.8); assert no settings-mutation API call fires on a `matchMedia` `change` (Req 4.6)
    - _Requirements: 4.6, 4.8_

  - [x] 6.3 Add the no-clip safety net in `InvoiceList.tsx`
    - Ensure the detail region and preview row carry `min-w-0`; add `overflow-x-auto` to the preview card's scroll container so over-wide content scrolls within its own bounds instead of overlapping neighbors; retain the list column `w-80 min-w-[320px]` floor
    - _Requirements: 5.1, 5.2, 5.3_

- [x] 7. Manual / Playwright visual verification (not unit-testable in jsdom)
  - Breakpoint, container-query, and print VISUAL behavior has no layout engine under jsdom and must be verified manually or with Playwright (`page.setViewportSize` + `emulateMedia({ media: 'print' })`). Verify each tier:
    - ≥1280px: list + detail side-by-side, POS beside the preview, no clip, no horizontal scroll, sidebar as today (Req 1.1, 6.3)
    - 861–1279px: sidebar collapses to icon-only rail, content reclaims width, single pane with Back control (Req 4.2, 4.4, 1.2)
    - 861–1279px: the header wordmark and footer OrgSwitcher collapse to an icon-only/collapsed treatment and do NOT overflow the ~72px rail (Req 4.9)
    - Deep-link narrow load: mounting below 1280px on `/invoices/:id` shows the Invoice_Detail_Region for that invoice (Req 1.7)
    - Create route on narrow: below 1280px on `/invoices/new` the Create_View is the sole full-width pane with the Back control (Req 8.1, 8.2)
    - Back on narrow returns to the list and updates the URL to `/invoices`, keeping the row highlighted (Req 2.7, 2.5)
    - Detail-region width <900px (e.g. wide viewport but list shown): POS moves from beside to below, preview spans full width when stacked (Req 3.1, 3.2, 3.4)
    - ≤860px: drawer unchanged — hamburger opens, scrim and Escape dismiss (Req 6.4)
    - ~970px: no-clip safety net — preview scrolls within bounds, never overlaps; list column stays within bounds (Req 5.1, 5.2, 5.3)
    - Print/PDF at any width: POS panel hidden, preview prints full page width (Req 6.1, 6.2)
    - Keyboard a11y: Tab through all visible controls at each tier with no focus trap; visible focus on Back control (Req 2.6, 7.2)

- [x] 8. Final checkpoint - typecheck and run changed-file tests
  - Run `npm run test` (`vitest --run`) for the new/changed test files and `tsc -b` (typecheck) over the changed `frontend-v2` files; fix any failures
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (tests) and can be skipped for a faster MVP, but they encode the design's correctness properties and regression guards.
- Property tests use fast-check (≥100 iterations) and cover the only property-testable surface: the pure pane-resolution logic, selection-identity invariance, and POS gating consistency.
- Visual/responsive behavior (media queries, container query, print) is verified in task 7, not in jsdom unit tests.
- Each task references the specific requirement clauses it satisfies; no backend, DB, or API work is in scope.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3"] },
    { "id": 3, "tasks": ["3.4", "3.5"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "6.3"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["6.2"] }
  ]
}
```
