# OraInvoice Redesign — Implementation Checklist

A step-by-step task list for an AI coding agent (Kiro / Claude Code) to implement the app-shell
redesign in the **React 19 + Vite + Tailwind v4** codebase. Work top to bottom, committing
after each phase. Full specs (tokens, measurements, states) live in `README.md` — read it first.

> **Setup:** create a branch before starting → `git checkout -b redesign-app-shell`.
> Do **not** ship the raw HTML or `tweaks-panel.jsx` / `tweaks-app.jsx` — they are prototyping aids.

> **Before you start:** read the **⚠️ Guardrails — What NOT to Touch** and **Two Ways to Apply
> This Design** sections in `README.md`. This is a presentation-only redesign — preserve all
> calculations, permission/role gating, conditional rendering, data fetching, and routing.
> If you're doing **Option B (parallel build)**, this checklist applies to the new app; never
> modify the existing `frontend/`.

---

## Phase 0 — Read & orient
- [ ] Read `README.md` end to end (tokens, components, breakpoints, file mapping).
- [ ] Open `OraInvoice Redesign.html` in a browser to see the target behavior.
- [ ] Locate the files you'll touch:
  - [ ] `frontend/src/layouts/OrgLayout.tsx` (the shell)
  - [ ] `frontend/src/styles/themes.css` (theme tokens)
  - [ ] `frontend/src/themes/registry.ts` (theme registry)
  - [ ] the org Dashboard page component
- [ ] Confirm the icon library already in use; reuse it (don't paste the prototype's raw SVG paths).

## Phase 1 — Fonts & design tokens
- [ ] Add **IBM Plex Sans** + **IBM Plex Mono** to the font pipeline (self-host or Google Fonts).
- [ ] Set IBM Plex Sans as the UI font; create a `.mono` / `font-mono` utility using IBM Plex
      Mono with `font-feature-settings: "tnum" 1` (tabular figures).
- [ ] Add the color tokens from the README's **Colors** table into the Tailwind `@theme` block /
      `themes.css` (accent, accent-press, accent-soft, ink, canvas, card, border, border-strong,
      text, muted, muted-2, ok/ok-soft, warn/warn-soft, danger/danger-soft).
- [ ] Add spacing/radius/shadow tokens (`--pad`, `--gap`, rail width, `--r-card/-ctl/-chip`,
      `--shadow-card`, `--shadow-pop`).
- [ ] Register an **"ink" sidebar theme** (new `[data-theme]`/`data-sidebar` block) with the ink
      palette; keep a **"light" sidebar** variant. Wire into `registry.ts`.
- [ ] Verify tokens resolve (temporary swatch or devtools check).

## Phase 2 — Sidebar
- [ ] Rebuild the sidebar container: 264px wide, full-height flex (header / scroll / footer),
      ink background, right hairline border.
- [ ] **Header**: logo mark (32×32, accent bg, radius 9, soft shadow) + "Ora"/"Invoice" wordmark.
      *(Swap in the real logo if available.)*
- [ ] **Grouped nav**: render the 5 groups + Settings (see README table). Each group = mono
      uppercase label + items.
- [ ] **Nav item** component: 40px tall, icon + label, hover + **active** states (left 3px accent
      bar, accent-soft bg, tinted icon). Drive active state from `NavLink` `isActive` — single
      active route.
- [ ] Add **count pills** (Invoices 18, Quotes 7, Job Cards 14) and the **alert dot** (Bookings).
      Wire counts to real data where available; static is fine initially.
- [ ] **Footer**: org switcher row (gradient avatar, org name + plan line, chevron). Use Headless UI
      `Menu` for the dropdown.

## Phase 3 — Top bar
- [ ] 64px bar, white bg, bottom hairline, gap 14px.
- [ ] **Search field** (flex-grow, max 440px) with magnifier + placeholder + `⌘K` kbd hint;
      wire ⌘K to the existing global search / command palette.
- [ ] **Branch chip** (status dot + branch code, mono).
- [ ] **Notifications** icon button with red badge dot.
- [ ] **"New" primary button** (accent, `+` icon) — keep its existing quick-create menu (Headless UI).
- [ ] **Avatar** button (account menu).
- [ ] Standardize the **icon-button** style (40×40, bordered, hover states).

## Phase 4 — Responsive shell
- [ ] `≤860px`: sidebar → off-canvas drawer (`translateX(-100%)`), hamburger toggles `navOpen`,
      scrim overlay (`rgba(11,18,32,.5)`) fades in and closes on click; selecting a nav item closes it.
- [ ] `≤860px`: search → icon-only, branch chip hidden, "New" → icon-only.
- [ ] Confirm transitions: drawer `.26s cubic-bezier(.4,0,.2,1)`, scrim `opacity .26s`.
- [ ] Verify all touch targets ≥ 44px on mobile.

## Phase 5 — Dashboard content
- [ ] **Page header**: mono date eyebrow + greeting h1 + subtitle; right-aligned segmented control
      (7D/30D/QTR/YR) driving `dateRange` state.
- [ ] **KPI row**: 4 cards (Revenue MTD, Outstanding, Overdue, Jobs in progress) — label + tinted
      icon chip + mono value + delta line. Grid 4→2 (`≤1080px`) →1 (`≤520px`).
- [ ] **Main grid**: `1.7fr / 1fr`, collapses to 1 col `≤1080px`.
- [ ] **Revenue card**: implement with **Recharts `<AreaChart>`** — accent stroke, gradient fill
      (accent .20→0), `#EEF0F4` gridlines, end-point dot, mono axis labels. (Prototype uses raw SVG;
      use Recharts in production.)
- [ ] **Recent invoices table**: Invoice (mono id) / Customer / Status badge / Amount (mono, right).
      Row hover state.
- [ ] **Status badge** component: paid/sent/overdue/draft variants (dot + pill). Reuse app-wide.
- [ ] **Activity feed** + **Upcoming bookings** lists (right column).
- [ ] Replace all sample figures with real fetched data (per org + branch + dateRange).

## Phase 6 — Polish & verify
- [ ] All monetary values, IDs, codes, counts, timestamps use the **mono / tabular** font.
- [ ] Hover/active/focus states present on nav, buttons, rows, switcher.
- [ ] Keyboard focus rings + `aria-label`s on icon-only buttons; drawer is focus-trappable.
- [ ] Check breakpoints: 1280 / 1080 / 860 / 520 px.
- [ ] Cross-check against `README.md` token tables — colors, radii, spacing, shadows match.
- [ ] Confirm the prototype-only files (`tweaks-*.jsx`, the HTML) are **not** imported anywhere.
- [ ] Run the existing test/lint/typecheck suite; fix regressions.
- [ ] Open a PR for review.

---

### Suggested commit points
1. `feat(theme): IBM Plex fonts + redesign tokens + ink sidebar theme`
2. `feat(shell): grouped ink sidebar`
3. `feat(shell): redesigned top bar`
4. `feat(shell): responsive mobile drawer`
5. `feat(dashboard): KPIs, revenue chart, tables & feeds`
6. `chore: polish, a11y, cleanup`
