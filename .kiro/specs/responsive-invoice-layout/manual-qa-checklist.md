# Task 7 — Manual / Playwright Visual Verification Checklist

> **Status: NOT YET VISUALLY VERIFIED.** Automated Playwright verification could
> **not** be executed in the development environment (see "Why Playwright could
> not run here" below). The code backing every criterion was confirmed by
> inspection and the non-visual logic is green (14 unit/property tests pass), but
> the actual rendered layout/print behaviour still requires a **human pass** or a
> **CI run with the dev stack up + a supported browser**.

App under test: `frontend-v2/` invoice screen (`/invoices`, `/invoices/:id`,
`/invoices/new`). In local dev the SPA is served under base `/new/`
(e.g. `http://localhost/new/invoices`).

Breakpoints: **Wide ≥1280px**, **Compact_Band 861–1279px**, **Drawer ≤860px**,
**POS_Stack_Threshold = 900px of the detail region's own width** (not viewport).

---

## How to run each tier

- **Viewport width:** DevTools device toolbar (Cmd/Ctrl+Shift+M) or resize the
  window; type an exact width.
- **Print/PDF:** DevTools → Rendering → "Emulate CSS media type: print", or the
  browser Print preview (Cmd/Ctrl+P).
- **Detail-region width independent of viewport:** stay at a wide viewport but
  keep the list column shown so the detail region itself drops below 900px
  (e.g. ~1180px viewport with the list visible).

---

## Checklist

### 1. Wide tier ≥1280px — side-by-side, no clip  (Req 1.1, 6.3)
- [ ] At 1440px: invoice **list column AND detail region show simultaneously**.
- [ ] POS receipt panel sits **beside** the invoice preview.
- [ ] No region is clipped; **no horizontal scrollbar** on the invoice screen.
- [ ] Sidebar renders as the full labeled rail (unchanged from today).

### 2. Compact_Band 861–1279px — icon rail + single pane  (Req 4.2, 4.4, 1.2)
- [ ] At 1024px: sidebar collapses to an **icon-only rail (~72px)**, nav labels hidden.
- [ ] Content region visibly **reclaims** the freed width.
- [ ] Invoice screen shows **exactly one pane** (list OR detail), with the
      **"Back to invoices"** control visible when the detail pane is shown.

### 3. Compact_Band — header wordmark + footer OrgSwitcher do not overflow  (Req 4.9)
- [ ] At 1024px: the **"OraInvoice" wordmark is hidden**, only the 32px logo mark
      shows, centered.
- [ ] The footer **OrgSwitcher collapses to the avatar only** (org name/plan text
      and chevron hidden); nothing overflows the ~72px rail.
- [ ] (Optional) DevTools computed style: `.shell-sidebar` width ≈ **72px**.

### 4. Deep-link narrow load  (Req 1.7)
- [ ] Set viewport to 1024px, then load `/invoices/:id` for a known invoice
      (hard refresh).
- [ ] The **Invoice_Detail_Region for that invoice** is shown (not the list),
      with the Back control.

### 5. Create route on narrow  (Req 8.1, 8.2)
- [ ] At 1024px, load `/invoices/new` (hard refresh).
- [ ] The **Create_View is the sole full-width pane** — the list column is NOT
      beside it.
- [ ] The **"Back to invoices"** control is shown.

### 6. Back on narrow returns to list + updates URL + keeps highlight  (Req 2.7, 2.5)
- [ ] At 1024px, open an invoice (URL becomes `/invoices/:id`), then click
      **"Back to invoices"**.
- [ ] The **list is shown** and the **URL updates to `/invoices`**.
- [ ] The previously selected row **still shows its selected-state highlight**.
- [ ] Re-selecting that row navigates back to `/invoices/:id` and shows detail.

### 7. Detail-region width <900px — POS stacks below  (Req 3.1, 3.2, 3.4)
- [ ] Force the **detail region** below 900px (wide viewport with the list shown,
      or otherwise narrow the detail region).
- [ ] The **POS panel moves from beside to below** the invoice preview.
- [ ] When stacked, the **invoice preview spans the full width**; the POS block
      sits underneath at full/`max-w` width (not a narrow off-center column).
- [ ] Above 900px region width: POS returns to **beside**.

### 8. Drawer tier ≤860px — unchanged  (Req 6.4)
- [ ] At 600px: the **hamburger opens** the off-canvas drawer.
- [ ] Clicking the **scrim dismisses** it.
- [ ] Pressing **Escape dismisses** it.

### 9. ~970px no-clip safety net  (Req 5.1, 5.2, 5.3)
- [ ] At 970px: the invoice preview **stays within its bounds**; over-wide content
      (e.g. a wide line-item table) **scrolls horizontally within the preview**
      rather than overlapping neighbours.
- [ ] The list column stays within the screen bounds (no spill).

### 10. Print / PDF at any width  (Req 6.1, 6.2)
- [ ] Emulate print at 1440px AND at 1024px: the **POS receipt panel is hidden**.
- [ ] The **invoice preview prints at full page width**.

### 11. Keyboard accessibility at each tier  (Req 2.6, 7.2)
- [ ] At each tier, **Tab/Shift+Tab** moves through all visible controls with **no
      focus trap**.
- [ ] The **"Back to invoices"** control is reachable by Tab, shows a **visible
      focus ring**, and activates with **both Enter and Space**.
- [ ] After clicking Back (or a tier change that hides the focused region), focus
      lands on a visible control in the newly shown region (search input on the
      list; Back control on the detail).

---

## Code-to-criterion mapping (confirmed by inspection)

| # | Criterion | Implementing code |
|---|-----------|-------------------|
| 1 | ≥1280px side-by-side, no clip | `resolvePaneVisibility` returns `showList && showDetail` when `isWide`; `useMediaQuery('(min-width: 1280px)')` in `InvoiceList.tsx`; list `w-80 min-w-[320px]`, detail `flex-1 min-w-0` |
| 2 | 861–1279px icon rail + single pane | `shell.css` `@media (min-width:861px) and (max-width:1279px)` → `.app-shell .shell-sidebar { width: var(--rail-icon,72px) }`; sidebar is a `flex-shrink-0` flex child so freed width flows to `.shell-main`; `resolvePaneVisibility` shows one pane below Wide |
| 3 | Wordmark + OrgSwitcher collapse | Same media block hides `.shell-brand-wordmark`, collapses `.shell-foot`/`.shell-org-switch-btn` and hides `.shell-org-text` + `.shell-org-chevron` (classes confirmed present in `OrgSwitcher.tsx`) |
| 4 | Deep-link narrow → detail | `narrowPane` initialized `(routeId || isCreating) ? 'detail' : 'list'`; `selectedId`-keyed detail fetch unchanged |
| 5 | Create on narrow = sole pane + Back | `resolvePaneVisibility(..., isCreating:true)` → `showDetail && showBackControl && !showList`; initial `narrowPane='detail'` when `isCreating` |
| 6 | Back → list, URL `/invoices`, keep highlight | `handleBackToList`: `setNarrowPane('list')` + `navigate('/invoices')`, **does not clear `selectedId`** (row keeps highlight); row select navigates to `/invoices/:id` |
| 7 | Detail <900px → POS below | `@container/detail` (`container-type: inline-size`) on the `flex-1 overflow-y-auto` wrapper; `@max-[900px]/detail:flex-col` on the preview row; POS panel `@max-[900px]/detail:w-full max-w-3xl static` |
| 8 | ≤860px drawer unchanged | Existing `shell.css @media (max-width:860px)` drawer rules + `max-mobile:` close button; not touched by this feature |
| 9 | ~970px no-clip safety net | Detail wrapper `flex-1 min-w-0 overflow-y-auto overflow-x-auto`; preview row `min-w-0`; invoice column `flex-1 min-w-0`; list floor `w-80 min-w-[320px]` |
| 10 | Print: POS hidden, preview full width | `PRINT_STYLES`: `[data-preview="receipt"] { display:none !important }` and `[data-print-content] { display:block; width:100% !important }` |
| 11 | Keyboard a11y / focus | Native `<button>` Back control (`backButtonRef`); focus-transition `useEffect` moves focus to `backButtonRef`/`listFocusRef` (search input) when the focused region is hidden |

---

## Why Playwright could not run here

The repo has a working Playwright harness (`playwright.config.ts`, `tests/e2e/frontend/*.spec.ts`,
`@playwright/test` installed) that mocks `/api/v1/**` via `page.route` and injects a
fake JWT — so a backend is **not** required, and a Vite dev server **is** running at
`http://localhost:80` (base `/new/`).

The blocker is the **browser binary**: `npx playwright install chromium` fails with
`Playwright does not support chromium on ubuntu26.04-x64`, and there is no system
Chrome/Chromium to fall back to via `channel`. With no launchable browser, the
viewport + `emulateMedia({ media: 'print' })` checks above cannot be executed in
this environment. Run this checklist manually, or run a Playwright spec in CI on a
supported OS with the dev stack up.
