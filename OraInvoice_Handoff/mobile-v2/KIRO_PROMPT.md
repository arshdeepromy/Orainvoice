# Paste this into Kiro (steering / first prompt)

> Drop this in as a Kiro **steering doc** (`.kiro/steering/mobile-redesign.md`) or paste as the
> opening message. It points Kiro at the full spec in `mobile-v2/HANDOFF.md`.

---

You are implementing the **OraInvoice mobile app** in our existing **React 19 + Vite + Tailwind v4**
codebase. The design is fully specified in `mobile-v2/` (the phone prototype) and
**`mobile-v2/HANDOFF.md`** — read `HANDOFF.md` first, end to end, then `mobile-v2/SCREENS.md` and
`mobile-v2/ds-mobile.css`.

**Non-negotiable rules:**
1. **Design exactly.** Reproduce the prototype's layout, tokens, type (IBM Plex Sans + Mono tabular
   numbers), spacing, radii, shadows, components, and interactions from `mobile-v2/ds-mobile.css`.
   Map tokens onto our existing Tailwind `@theme` — don't fork a new token set. The Tweaks panel and
   the raw HTML/JSX prototype files are **references, not shippable code**.
2. **Real backend only.** Every screen calls the **same endpoints the desktop frontend-v2 already
   calls**, through the existing `frontend-v2/src/api/client.ts` axios instance and the existing
   React Query hooks / typed api modules (`api/leave.ts`, `api/payslips.ts`, `api/ppsr.ts`,
   `api/schedule.ts`, …). **No new base URLs, no hard-coded links, no re-implemented auth.** Inherit
   the existing Bearer-token + httpOnly-refresh + `X-Branch-Id` + portal-CSRF behavior unchanged.
   Branch switcher writes the same `localStorage('selected_branch_id')` key. If a screen has no
   existing endpoint/hook, **stop and flag it** — do not fabricate a URL.
3. **Port logic, never re-derive it.** GST/tax math, line totals, rounding, due-dates, payroll
   (PAYE/KiwiSaver/ACC/withholding), GST101 boxes, construction progress-claim %/retentions,
   inventory margins/reorder, WOF/service status — all come from the **same desktop util/hook**.
   Add unit tests asserting identical output to desktop. Prototype numbers are placeholders.
4. **Mirror module gating exactly.** Reuse desktop's role / plan / feature-flag / trade-family guards
   so the modules and fields visible on mobile (tab bar + "Browse all screens" directory + deep
   links) match what desktop shows for the same user. Don't build a second gating table. Pay rate,
   payroll, admin-only data stay gated. Customer-portal screens use the portal/CSRF session, never
   org-internal data.
5. **Guardrails.** This is presentation work: change markup + styling, keep props/hooks/handlers/
   guards/conditionals/validation/routing intact. If a style change forces a logic change, **stop and
   flag it.**

**Workflow:** small diffs, screen-by-screen, on a branch; run lint + typecheck + tests after each
phase; open PRs for review; cut screens over behind a feature flag once at parity. Follow the build
order and per-screen "definition of done" in `HANDOFF.md` §6–§7. Platform/global-admin pages are
out of scope for mobile.

**Start by** reading `HANDOFF.md` (incl. **Appendix A — Real repo symbols**, which lists the exact
hooks, contexts, endpoints and calc functions to reuse), listing the screens from `SCREENS.md`,
locating the existing API hooks + permission guards for the first module (Invoices — reuse
`computeTotals`/`calcLineAmount` from `pages/invoices/InvoiceCreate.tsx` and its
`InvoiceCreate.calculations.test.tsx`), and proposing a plan before writing code.
