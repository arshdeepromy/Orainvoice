# Kiro Agent Prompt — OraInvoice Mobile Redesign

Paste this into the Kiro IDE agent (or Claude Code) to kick off the mobile redesign. It assumes
the repo `arshdeepromy/Orainvoice` is open and the design package is in `OraInvoice_Handoff/`.

---

## Copy-paste prompt

```
You are restyling the OraInvoice MOBILE app (the `mobile/` folder — React 19 + Vite +
Capacitor 7 + Tailwind) to match a new high-fidelity design. This is a PRESENTATION-ONLY
redesign of an EXISTING app. Do not build a new app and do not touch `frontend/` or the
backend `app/`.

READ FIRST (in this order), and follow them as hard rules:
1. OraInvoice_Handoff/MOBILE_HANDOFF.md         (scope, tokens, full screen→route→endpoint map)
2. OraInvoice_Handoff/MOBILE_IMPLEMENTATION_CHECKLIST.md   (phased plan — work through it)
3. .kiro/steering/mobile-app.md                 (mobile scope, API conventions, gating, touch)
4. .kiro/steering/safe-api-consumption.md
5. .kiro/steering/project-overview.md
6. .kiro/steering/trade-family-gating-for-new-features.md
Design source of truth: OraInvoice Mobile Redesign.html + the mobile-v2/ folder
(design tokens in mobile-v2/ds-mobile.css). The prototype is a reference, NOT code to copy.

GUARDRAILS — never alter, only reskin:
- Calculations: GST/tax, invoice/quote totals, discounts, rounding, currency
  (Intl.NumberFormat — never hardcode "$"), progress-claim/retention/variation math,
  payslip/PAYE math.
- Gating: every ModuleGate, moduleSlug, tradeFamily, allowedRoles, plan/quota gate
  (e.g. PPSR 402 quota). Tab bar + More menu must hide EXACTLY what they hid before.
- Conditional rendering, loading/empty/error states (never a blank screen on error).
- Data fetching: keep each screen's api/* calls, queries, mutations, AbortController
  cleanup, validation, and save paths verbatim.
- Routing: StackRoutes paths/params, AuthGuard/GuestOnly, deep links, scroll preservation.
- Capacitor native flows behind isNativePlatform() + try/catch.
- aria-*, role, data-testid hooks.
If a styling change requires touching any of the above, STOP and flag it in the PR — don't guess.

BACKEND WIRING (use the existing client, don't reinvent):
- mobile/src/api/client.ts (axios, /api/v1 base; v2 endpoints use absolute /api/v2/...).
  Prefer v2 endpoints where they exist.
- Lists return { items, total }; consume safely: res.data?.items ?? [], res.data?.total ?? 0.
- Pagination is offset + limit (NEVER skip). Typed generics, never `as any`.
- Every useEffect API call uses AbortController and returns () => controller.abort().
- Keep X-Branch-Id, JWT refresh, and portal CSRF behaviour as-is.

KONSTA: the redesign drops Konsta. Migrate components/konsta/* usages to the new
components/ui/* equivalents incrementally (screen-by-screen so the app keeps building),
then remove the Konsta dependency and folder in a final cleanup commit. Keep the gating /
tab-resolution logic in navigation/TabConfig.ts (buildTabs, resolveFourthTab,
isNavigationItemVisible) intact.

SCOPE: mobile is a companion app for ORG users only. Never add global-admin/platform screens,
org-destructive ops, or deep settings panels. global_admin must never see org settings on mobile.
Accounting/Banking/Tax/Reports are VIEW-ONLY on mobile.

CONFIRM BEFORE BUILDING (these are in the prototype but have NO existing mobile route —
ask me and check app/main.py before adding): PPSR search, Leave, Roster/shift swaps, Loyalty,
insurance/warranty Claims, Setup wizard, Booking detail, Expense detail.

WORKFLOW:
- Branch: redesign-mobile-app. Small diffs, commit per phase/module, open PRs for review.
- After every phase run lint + typecheck + the mobile Vitest/RTL suite; fix any new failure.
- Verify per screen: totals/GST identical, gates correct, create/edit saves work,
  loading/empty/error render, touch targets >= 44x44, safe-area insets, dark mode.

START with Phase 0 (orient + run the test suite green), then Phase 1 (tokens), and report back
your plan for Phase 2 before mass-editing screens.
```

---

## Notes for whoever runs this
- The `.kiro/steering/*.md` files are auto-loaded by Kiro (most are `inclusion: always`), so the
  agent already has the project rules in context — the prompt just points at the specifics.
- If you'd rather the agent **not** introduce bottom-sheet create forms (and instead just restyle
  the existing full-screen create routes), say so explicitly — the handoff lists both as valid.
- Keep an eye on the Konsta removal: insist replacements land **before** the dependency is deleted,
  or the app won't build mid-migration.
