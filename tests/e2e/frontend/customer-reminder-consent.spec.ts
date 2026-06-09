/**
 * E2E Playwright — customer reminder consent (I5).
 *
 * Feature: customer-reminder-consent
 *
 * Drives the admin-side consent gate end-to-end with all backend calls mocked
 * via page.route() (the harness pattern used by the other specs in this dir):
 *   1. Open a customer profile.
 *   2. Configure Reminders → enable a category not covered by consent.
 *   3. Save → the Consent Confirmation modal opens (the gate fires).
 *   4. Choose an obtained method → Confirm → a PUT with `consent_record` fires.
 *   5. The Reminder Consent tab shows the recorded consent.
 *   6. Revoke an active entry → a POST /reminders/revoke fires.
 *
 * The kiosk capture path (Req 1) is covered by the vitest suites
 * (ReminderConsentStep.*.test.tsx, KioskPage.submit.test.tsx).
 *
 * NOTE: requires Playwright browsers + the app served at BASE_URL. It is an
 * OPTIONAL (live-harness) task; on hosts where Playwright's chromium build is
 * unavailable it is skipped at the runner level.
 *
 * Validates: Requirements 2, 3, 5.
 */
import { test, expect, type Route } from '@playwright/test'

const CUSTOMER_ID = 'cust-e2e-1'

const FAKE_TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  Buffer.from(
    JSON.stringify({
      sub: 'u-1',
      role: 'org_admin',
      org_id: 'org-1',
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  ).toString('base64') +
  '.sig'

let consentWritten = false
let revokeWritten = false

function customerBody() {
  return {
    id: CUSTOMER_ID,
    first_name: 'Jane',
    last_name: 'Smith',
    display_name: 'Jane Smith',
    email: 'jane@example.com',
    phone: '0211234567',
    address: null,
    notes: null,
    is_anonymised: false,
    enable_portal: false,
    portal_token: null,
    portal_token_expires_at: null,
    last_portal_access_at: null,
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
    vehicles: [],
    invoices: [],
    total_spend: '0.00',
    outstanding_balance: '0.00',
    custom_fields: consentWritten
      ? {
          reminder_consent: {
            given_at: '2026-06-09T00:00:00Z',
            source: 'manually_recorded_by_staff:phone',
            recorded_by_user_email: 'admin@workshop.co.nz',
            consent_text_version: '2026-06-08-v1',
            entries: [{ vehicle_id: null, category: 'service_due', channel: 'email' }],
          },
        }
      : {},
  }
}

test.beforeEach(async ({ page }) => {
  consentWritten = false
  revokeWritten = false

  await page.addInitScript((token) => {
    window.localStorage.setItem('access_token', token as string)
  }, FAKE_TOKEN)

  await page.route('**/api/v1/**', async (route: Route) => {
    const url = route.request().url()
    const method = route.request().method()

    if (url.includes('/org/settings')) {
      return route.fulfill({
        json: {
          org_name: 'Workshop', name: 'Workshop', trade_family: 'automotive-transport',
          trade_category: 'general-automotive', sidebar_display_mode: 'icon_and_name',
          gst_percentage: 15, gst_inclusive: true,
        },
      })
    }
    if (url.endsWith('/modules')) return route.fulfill({ json: { modules: [], total: 0 } })
    if (url.includes('/customers/consent-text')) {
      return route.fulfill({ json: { text: 'I agree to reminders.', version: '2026-06-08-v1' } })
    }
    if (url.match(/\/customers\/[^/]+\/reminders$/) && method === 'GET') {
      return route.fulfill({
        json: {
          service_due: { enabled: consentWritten, days_before: 30, channel: 'email' },
          wof_expiry: { enabled: false, days_before: 30, channel: 'email' },
          cof_expiry: { enabled: false, days_before: 30, channel: 'email' },
          registration_expiry: { enabled: false, days_before: 30, channel: 'email' },
          vehicles: [],
        },
      })
    }
    if (url.match(/\/customers\/[^/]+\/reminders$/) && method === 'PUT') {
      const body = route.request().postDataJSON()
      expect(body.consent_record?.source).toBe('manually_recorded_by_staff:phone')
      consentWritten = true
      return route.fulfill({ json: body })
    }
    if (url.includes('/reminders/revoke') && method === 'POST') {
      revokeWritten = true
      return route.fulfill({ json: {} })
    }
    if (url.match(/\/customers\/[^/]+$/) && method === 'GET') {
      return route.fulfill({ json: customerBody() })
    }
    return route.fulfill({ json: {} })
  })
})

test('admin consent gate → confirm → profile shows consent → revoke', async ({ page }) => {
  await page.goto(`/customers/${CUSTOMER_ID}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Jane Smith' })).toBeVisible()

  // Open Configure Reminders, enable service_due, Save → gate opens.
  await page.getByRole('button', { name: /reminders configured|configure reminders/i }).click()
  await page.getByRole('button', { name: /^Save$/ }).click()
  await expect(page.getByText(/Confirm reminder consent/i)).toBeVisible()

  // Choose method + confirm → PUT with consent_record (asserted in route).
  await page.getByLabel(/how was consent obtained/i).selectOption('phone')
  await page.getByRole('button', { name: /confirm consent/i }).click()
  await expect.poll(() => consentWritten).toBe(true)

  // The Reminder Consent tab shows the recorded consent.
  await page.getByRole('tab', { name: /Reminder Consent/i }).click()
  await expect(page.getByTestId('consent-section')).toBeVisible()

  // Revoke the active entry.
  await page.getByTestId('revoke-service_due-email').click()
  await page.getByLabel(/how was the revocation obtained/i).selectOption('phone')
  await page.getByLabel(/^Reason$/i).fill('Customer requested')
  await page.getByRole('button', { name: /revoke consent/i }).click()
  await expect.poll(() => revokeWritten).toBe(true)
})
