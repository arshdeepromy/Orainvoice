# Gap analysis — customer-reminder-consent

## I5 — Playwright e2e (optional, blocked on environment)

**Task:** `tests/e2e/.../customer-reminder-consent.spec.ts` — full happy path
(consent gate → confirm → profile → revoke).

**Status:** `[~]` — spec written and committed at
`tests/e2e/frontend/customer-reminder-consent.spec.ts` (the configured
Playwright `testDir`), using the same `page.route()` API-mock pattern as the
other specs in that directory. It is **ready to run on a supported host**.

**Why it cannot run here:** `npx playwright install chromium` fails with
`Playwright does not support chromium on ubuntu26.04-x64`. No chromium build is
available for this OS, so the e2e runner cannot launch a browser. This is an
environment limitation, not a code defect — the spec itself is complete.

**Coverage compensation:** the same UI behaviours are covered by passing vitest
suites:
- kiosk capture: `ReminderConsentStep.{render,gating,a11y,default}.test.tsx`,
  `KioskPage.{consent-text-fetch,submit}.test.tsx`
- admin gate + modals: `ConfigureRemindersModal.{indicators,gate}.test.tsx`,
  `ConsentConfirmationModal.test.tsx`, `RevocationModal.test.tsx`,
  `ReminderConsentSection.test.tsx`

**To run when on a supported host:**
`BASE_URL=<served-app-url> npx playwright test tests/e2e/frontend/customer-reminder-consent.spec.ts`
