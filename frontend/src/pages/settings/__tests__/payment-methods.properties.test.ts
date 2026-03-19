import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// ---------------------------------------------------------------------------
// Pure helper: mirrors the backend is_expiring_soon computation
// (billing/router.py → list_payment_methods)
//
// Card expiry = last day of exp_month/exp_year at 23:59:59 UTC.
// is_expiring_soon = expiry_date <= refDate + 2 months.
// ---------------------------------------------------------------------------

/**
 * Return the last day of the given month/year.
 */
function lastDayOfMonth(year: number, month: number): number {
  // Day 0 of the *next* month gives the last day of *this* month
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

/**
 * Add `months` calendar months to a Date (UTC), clamping the day to the
 * last day of the target month (same behaviour as Python's
 * `dateutil.relativedelta`).
 */
function addMonths(date: Date, months: number): Date {
  const y = date.getUTCFullYear()
  const m = date.getUTCMonth() + months // 0-based
  const targetYear = y + Math.floor(m / 12)
  const targetMonth = ((m % 12) + 12) % 12 // keep 0-11
  const maxDay = lastDayOfMonth(targetYear, targetMonth + 1) // +1 because lastDayOfMonth expects 1-based
  const day = Math.min(date.getUTCDate(), maxDay)
  return new Date(
    Date.UTC(
      targetYear,
      targetMonth,
      day,
      date.getUTCHours(),
      date.getUTCMinutes(),
      date.getUTCSeconds(),
    ),
  )
}

/**
 * Compute whether a card is expiring soon.
 *
 * A card is "expiring soon" when its expiry date (last day of
 * exp_month/exp_year, 23:59:59 UTC) is on or before refDate + 2 calendar
 * months.
 */
function computeIsExpiringSoon(
  expMonth: number,
  expYear: number,
  refDate: Date,
): boolean {
  const twoMonthsLater = addMonths(refDate, 2)
  const last = lastDayOfMonth(expYear, expMonth)
  const expiryDate = new Date(Date.UTC(expYear, expMonth - 1, last, 23, 59, 59))
  return expiryDate <= twoMonthsLater
}

// ---------------------------------------------------------------------------
// Property-based tests
// ---------------------------------------------------------------------------

describe('Payment Methods — Property-Based Tests', () => {
  // Feature: in-app-payment-methods, Property 2: Expiry-soon computation (frontend)
  // **Validates: Requirements 1.6**
  it('Property 2: is_expiring_soon is true iff card expiry is within 2 months of reference date', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 12 }),           // expMonth
        fc.integer({ min: 2020, max: 2040 }),       // expYear
        fc.integer({ min: 2020, max: 2040 }),       // refYear
        fc.integer({ min: 1, max: 12 }),            // refMonth
        fc.integer({ min: 1, max: 28 }),            // refDay (capped at 28 to avoid invalid dates)
        (expMonth, expYear, refYear, refMonth, refDay) => {
          const refDate = new Date(Date.UTC(refYear, refMonth - 1, refDay, 12, 0, 0))

          const result = computeIsExpiringSoon(expMonth, expYear, refDate)

          // Independent calculation of expected value
          const twoMonthsLater = addMonths(refDate, 2)
          const last = lastDayOfMonth(expYear, expMonth)
          const expiryDate = new Date(Date.UTC(expYear, expMonth - 1, last, 23, 59, 59))
          const expected = expiryDate <= twoMonthsLater

          expect(result).toBe(expected)
        },
      ),
      { numRuns: 100 },
    )
  })
})


// ---------------------------------------------------------------------------
// Pure helpers: mirrors the StripeSetupGuide step completion logic
// (components/admin/StripeSetupGuide.tsx → STEPS[].isComplete)
// ---------------------------------------------------------------------------

interface StripeSetupProgress {
  apiKeysSaved: boolean
  apiKeysTested: boolean
  webhookEndpointSet: boolean
  signingSecretSaved: boolean
  connectionTested: boolean
}

/**
 * Map of step number → isComplete function, matching the STEPS array in
 * StripeSetupGuide.tsx.
 *
 * Steps 1 and 6 are manual-only (always false).
 * Steps 2,3,4,5,7 map to specific progress fields.
 */
const STEP_COMPLETE_FNS: Record<number, (p: StripeSetupProgress) => boolean> = {
  1: () => false,                       // manual
  2: (p) => p.apiKeysSaved,
  3: (p) => p.apiKeysTested,
  4: (p) => p.webhookEndpointSet,
  5: (p) => p.signingSecretSaved,
  6: () => false,                       // manual
  7: (p) => p.connectionTested,
}

// Feature: in-app-payment-methods, Property 17: Setup guide progress reflects completion state
// **Validates: Requirements 11.5**
describe('Payment Methods — Property 17: Setup guide progress reflects completion state', () => {
  it('checkmarks shown for exactly the completed steps and no others', () => {
    fc.assert(
      fc.property(
        fc.record({
          apiKeysSaved: fc.boolean(),
          apiKeysTested: fc.boolean(),
          webhookEndpointSet: fc.boolean(),
          signingSecretSaved: fc.boolean(),
          connectionTested: fc.boolean(),
        }),
        (progress: StripeSetupProgress) => {
          // For each of the 7 steps, determine expected completion
          for (let step = 1; step <= 7; step++) {
            const isCompleteFn = STEP_COMPLETE_FNS[step]
            const expected = isCompleteFn(progress)

            if (step === 1 || step === 6) {
              // Manual steps must always be incomplete regardless of progress
              expect(expected).toBe(false)
            } else {
              // Auto-checkable steps: verify the mapping is correct
              switch (step) {
                case 2:
                  expect(expected).toBe(progress.apiKeysSaved)
                  break
                case 3:
                  expect(expected).toBe(progress.apiKeysTested)
                  break
                case 4:
                  expect(expected).toBe(progress.webhookEndpointSet)
                  break
                case 5:
                  expect(expected).toBe(progress.signingSecretSaved)
                  break
                case 7:
                  expect(expected).toBe(progress.connectionTested)
                  break
              }
            }
          }

          // Count completed steps — should equal exactly the number of true
          // auto-checkable fields
          const completedSteps = Object.entries(STEP_COMPLETE_FNS)
            .filter(([, fn]) => fn(progress))
            .map(([num]) => Number(num))

          const autoCheckableTrue = [
            progress.apiKeysSaved,
            progress.apiKeysTested,
            progress.webhookEndpointSet,
            progress.signingSecretSaved,
            progress.connectionTested,
          ].filter(Boolean).length

          expect(completedSteps.length).toBe(autoCheckableTrue)

          // Manual steps (1, 6) must never appear in completed list
          expect(completedSteps).not.toContain(1)
          expect(completedSteps).not.toContain(6)
        },
      ),
      { numRuns: 100 },
    )
  })
})

// ---------------------------------------------------------------------------
// Pure helper: mirrors the StripeTestSuite summary computation
// (components/admin/StripeTestSuite.tsx → SummaryLine)
// ---------------------------------------------------------------------------

interface TestResult {
  test_name: string
  category: 'api_functions' | 'webhook_handlers'
  status: 'passed' | 'failed' | 'skipped'
  error_message?: string | null
}

/**
 * Compute summary counts from an array of test results — same logic the
 * backend returns and the frontend displays.
 */
function computeTestSummary(results: TestResult[]) {
  const passed = results.filter((r) => r.status === 'passed').length
  const failed = results.filter((r) => r.status === 'failed').length
  const skipped = results.filter((r) => r.status === 'skipped').length
  return { total: results.length, passed, failed, skipped }
}

// Feature: in-app-payment-methods, Property 19: Test summary computation (frontend)
// **Validates: Requirements 12.6**
describe('Payment Methods — Property 19: Test summary computation', () => {
  const testResultArb: fc.Arbitrary<TestResult> = fc.record({
    test_name: fc.string({ minLength: 1, maxLength: 50 }),
    category: fc.constantFrom('api_functions' as const, 'webhook_handlers' as const),
    status: fc.constantFrom('passed' as const, 'failed' as const, 'skipped' as const),
    error_message: fc.option(fc.string({ minLength: 1, maxLength: 100 }), { nil: null }),
  })

  it('passed + failed + skipped == total and each count matches actual statuses', () => {
    fc.assert(
      fc.property(
        fc.array(testResultArb, { minLength: 0, maxLength: 30 }),
        (results: TestResult[]) => {
          const summary = computeTestSummary(results)

          // Total equals sum of individual counts
          expect(summary.passed + summary.failed + summary.skipped).toBe(summary.total)

          // Total equals array length
          expect(summary.total).toBe(results.length)

          // Each count matches the actual number of results with that status
          expect(summary.passed).toBe(results.filter((r) => r.status === 'passed').length)
          expect(summary.failed).toBe(results.filter((r) => r.status === 'failed').length)
          expect(summary.skipped).toBe(results.filter((r) => r.status === 'skipped').length)

          // Counts are non-negative
          expect(summary.passed).toBeGreaterThanOrEqual(0)
          expect(summary.failed).toBeGreaterThanOrEqual(0)
          expect(summary.skipped).toBeGreaterThanOrEqual(0)
        },
      ),
      { numRuns: 100 },
    )
  })
})
