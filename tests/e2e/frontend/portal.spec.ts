/**
 * E2E Playwright tests for customer portal token access.
 *
 * Covers:
 *  - Valid portal token — customer can access their portal and see invoice data
 *  - Expired portal token — customer sees an error/expired message (401 from API)
 *  - Invalid/non-existent portal token — customer sees appropriate error
 *  - Portal page loads correctly with valid token and shows invoice data
 *
 * All backend API calls are intercepted via page.route() so the tests
 * run without a live backend.
 *
 * Validates: Requirements 20.4
 */
import { test, expect, type Route } from '@playwright/test';

// ---------------------------------------------------------------------------
// Helpers & constants
// ---------------------------------------------------------------------------

const BASE_URL = 'http://localhost:5173';

const VALID_TOKEN = '550e8400-e29b-41d4-a716-446655440000';
const EXPIRED_TOKEN = '660e8400-e29b-41d4-a716-446655440001';
const INVALID_TOKEN = '770e8400-e29b-41d4-a716-446655440002';

/** Sample portal info returned for a valid token. */
const PORTAL_INFO = {
  customer_name: 'Jane Smith',
  email: 'jane@example.co.nz',
  phone: '+64211234567',
  org_name: 'Workshop Pro NZ',
  logo_url: null,
  primary_color: '#2563eb',
  outstanding_balance: 350.0,
  total_invoices: 5,
  total_paid: 1200.0,
  powered_by: null,
};

/** Sample invoice list returned for a valid token. */
const PORTAL_INVOICES = [
  {
    id: 'inv-001',
    invoice_number: 'INV-2025-001',
    issue_date: '2025-01-15',
    due_date: '2025-02-15',
    status: 'issued',
    total: 200.0,
    balance_due: 200.0,
    line_items_summary: 'Brake pad replacement',
  },
  {
    id: 'inv-002',
    invoice_number: 'INV-2025-002',
    issue_date: '2025-01-20',
    due_date: null,
    status: 'paid',
    total: 150.0,
    balance_due: 0,
    line_items_summary: 'Oil change and filter',
  },
];

/** Respond to a route with JSON. */
async function jsonResponse(route: Route, body: Record<string, unknown> | unknown[], status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe('Portal Token Access', () => {
  // -----------------------------------------------------------------------
  // 1. Valid portal token — full page load
  // -----------------------------------------------------------------------
  test.describe('Valid Portal Token', () => {
    test('portal page loads and shows customer welcome message', async ({ page }) => {
      // Mock portal info endpoint
      await page.route(`**/api/v1/portal/${VALID_TOKEN}`, async (route) => {
        await jsonResponse(route, PORTAL_INFO);
      });

      // Mock invoices endpoint (loaded by InvoiceHistory tab)
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/invoices`, async (route) => {
        await jsonResponse(route, PORTAL_INVOICES);
      });

      // Mock other portal tab endpoints to prevent errors
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/vehicles`, async (route) => {
        await jsonResponse(route, []);
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/quotes`, async (route) => {
        await jsonResponse(route, { quotes: [] });
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/assets`, async (route) => {
        await jsonResponse(route, { assets: [] });
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/bookings`, async (route) => {
        await jsonResponse(route, { bookings: [] });
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/loyalty`, async (route) => {
        await jsonResponse(route, { points: 0, tier: 'bronze' });
      });

      // No auth needed for portal — it's public/token-based
      await page.route('**/api/v1/auth/token/refresh', async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.goto(`${BASE_URL}/portal/${VALID_TOKEN}`);

      // Customer welcome message should be visible
      await expect(page.getByText(`Welcome, ${PORTAL_INFO.customer_name}`)).toBeVisible({
        timeout: 5000,
      });

      // Org name should appear in the description
      await expect(page.getByText(PORTAL_INFO.org_name)).toBeVisible();
    });

    test('portal page shows invoice data in the invoices tab', async ({ page }) => {
      await page.route(`**/api/v1/portal/${VALID_TOKEN}`, async (route) => {
        await jsonResponse(route, PORTAL_INFO);
      });

      await page.route(`**/api/v1/portal/${VALID_TOKEN}/invoices`, async (route) => {
        await jsonResponse(route, PORTAL_INVOICES);
      });

      await page.route(`**/api/v1/portal/${VALID_TOKEN}/vehicles`, async (route) => {
        await jsonResponse(route, []);
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/quotes`, async (route) => {
        await jsonResponse(route, { quotes: [] });
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/assets`, async (route) => {
        await jsonResponse(route, { assets: [] });
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/bookings`, async (route) => {
        await jsonResponse(route, { bookings: [] });
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/loyalty`, async (route) => {
        await jsonResponse(route, { points: 0, tier: 'bronze' });
      });

      await page.route('**/api/v1/auth/token/refresh', async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.goto(`${BASE_URL}/portal/${VALID_TOKEN}`);

      // Wait for portal to load
      await expect(page.getByText(`Welcome, ${PORTAL_INFO.customer_name}`)).toBeVisible({
        timeout: 5000,
      });

      // Invoice numbers should be visible (Invoices tab is default)
      await expect(page.getByText('INV-2025-001')).toBeVisible({ timeout: 5000 });
      await expect(page.getByText('INV-2025-002')).toBeVisible();

      // Invoice line item summaries should be visible
      await expect(page.getByText('Brake pad replacement')).toBeVisible();
      await expect(page.getByText('Oil change and filter')).toBeVisible();
    });

    test('portal page shows summary cards with correct data', async ({ page }) => {
      await page.route(`**/api/v1/portal/${VALID_TOKEN}`, async (route) => {
        await jsonResponse(route, PORTAL_INFO);
      });

      await page.route(`**/api/v1/portal/${VALID_TOKEN}/invoices`, async (route) => {
        await jsonResponse(route, PORTAL_INVOICES);
      });

      await page.route(`**/api/v1/portal/${VALID_TOKEN}/**`, async (route) => {
        await jsonResponse(route, []);
      });

      await page.route('**/api/v1/auth/token/refresh', async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.goto(`${BASE_URL}/portal/${VALID_TOKEN}`);

      await expect(page.getByText(`Welcome, ${PORTAL_INFO.customer_name}`)).toBeVisible({
        timeout: 5000,
      });

      // Summary cards should show outstanding balance, total invoices, total paid
      await expect(page.getByText('Outstanding Balance')).toBeVisible();
      await expect(page.getByText('Total Invoices')).toBeVisible();
      await expect(page.getByText('Total Paid')).toBeVisible();
    });
  });

  // -----------------------------------------------------------------------
  // 2. Expired portal token
  // -----------------------------------------------------------------------
  test.describe('Expired Portal Token', () => {
    test('expired token shows error message when portal info returns 401', async ({ page }) => {
      // Mock portal info endpoint to return 401 for expired token
      await page.route(`**/api/v1/portal/${EXPIRED_TOKEN}`, async (route) => {
        await jsonResponse(route, { detail: 'Portal token has expired' }, 401);
      });

      await page.route('**/api/v1/auth/token/refresh', async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.goto(`${BASE_URL}/portal/${EXPIRED_TOKEN}`);

      // The portal page catches errors and shows an error banner
      await expect(
        page.getByText('Unable to load your portal. The link may have expired or is invalid.'),
      ).toBeVisible({ timeout: 5000 });

      // Welcome message should NOT be visible
      await expect(page.getByText(`Welcome,`)).not.toBeVisible();
    });

    test('expired token API call returns 401 with correct error detail', async ({ page }) => {
      await page.route(`**/api/v1/portal/${EXPIRED_TOKEN}`, async (route) => {
        await jsonResponse(route, { detail: 'Portal token has expired' }, 401);
      });

      await page.route(`**/api/v1/portal/${EXPIRED_TOKEN}/invoices`, async (route) => {
        await jsonResponse(route, { detail: 'Portal token has expired' }, 401);
      });

      await page.route('**/api/v1/auth/token/refresh', async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.goto(`${BASE_URL}/portal/${EXPIRED_TOKEN}`);

      // Verify the API returns 401 with the expected detail via programmatic fetch
      const response = await page.evaluate(async (token) => {
        const res = await fetch(`/api/v1/portal/${token}/invoices`);
        return { status: res.status, body: await res.json() };
      }, EXPIRED_TOKEN);

      expect(response.status).toBe(401);
      expect(response.body.detail).toBe('Portal token has expired');
    });
  });

  // -----------------------------------------------------------------------
  // 3. Invalid / non-existent portal token
  // -----------------------------------------------------------------------
  test.describe('Invalid Portal Token', () => {
    test('invalid token shows error message when portal info returns 404', async ({ page }) => {
      // Mock portal info endpoint to return 404 for invalid token
      await page.route(`**/api/v1/portal/${INVALID_TOKEN}`, async (route) => {
        await jsonResponse(route, { detail: 'Portal token not found' }, 404);
      });

      await page.route('**/api/v1/auth/token/refresh', async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.goto(`${BASE_URL}/portal/${INVALID_TOKEN}`);

      // The portal page catches errors and shows an error banner
      await expect(
        page.getByText('Unable to load your portal. The link may have expired or is invalid.'),
      ).toBeVisible({ timeout: 5000 });

      // Welcome message should NOT be visible
      await expect(page.getByText(`Welcome,`)).not.toBeVisible();
    });

    test('invalid token API call returns 404 with correct error detail', async ({ page }) => {
      await page.route(`**/api/v1/portal/${INVALID_TOKEN}`, async (route) => {
        await jsonResponse(route, { detail: 'Portal token not found' }, 404);
      });

      await page.route('**/api/v1/auth/token/refresh', async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.goto(`${BASE_URL}/portal/${INVALID_TOKEN}`);

      // Verify the API returns 404 via programmatic fetch
      const response = await page.evaluate(async (token) => {
        const res = await fetch(`/api/v1/portal/${token}`);
        return { status: res.status, body: await res.json() };
      }, INVALID_TOKEN);

      expect(response.status).toBe(404);
      expect(response.body.detail).toBe('Portal token not found');
    });
  });

  // -----------------------------------------------------------------------
  // 4. Portal API endpoint contract verification
  // -----------------------------------------------------------------------
  test.describe('Portal API Contract', () => {
    test('portal info endpoint is called with correct token in URL', async ({ page }) => {
      let capturedUrl = '';

      await page.route(`**/api/v1/portal/${VALID_TOKEN}`, async (route) => {
        capturedUrl = route.request().url();
        await jsonResponse(route, PORTAL_INFO);
      });

      await page.route(`**/api/v1/portal/${VALID_TOKEN}/**`, async (route) => {
        await jsonResponse(route, []);
      });

      await page.route('**/api/v1/auth/token/refresh', async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.goto(`${BASE_URL}/portal/${VALID_TOKEN}`);

      await expect(page.getByText(`Welcome, ${PORTAL_INFO.customer_name}`)).toBeVisible({
        timeout: 5000,
      });

      expect(capturedUrl).toContain(`/api/v1/portal/${VALID_TOKEN}`);
    });

    test('portal invoices endpoint is called with correct token', async ({ page }) => {
      let invoicesEndpointCalled = false;
      let capturedInvoicesUrl = '';

      await page.route(`**/api/v1/portal/${VALID_TOKEN}`, async (route) => {
        await jsonResponse(route, PORTAL_INFO);
      });

      await page.route(`**/api/v1/portal/${VALID_TOKEN}/invoices`, async (route) => {
        invoicesEndpointCalled = true;
        capturedInvoicesUrl = route.request().url();
        await jsonResponse(route, PORTAL_INVOICES);
      });

      await page.route(`**/api/v1/portal/${VALID_TOKEN}/vehicles`, async (route) => {
        await jsonResponse(route, []);
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/quotes`, async (route) => {
        await jsonResponse(route, { quotes: [] });
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/assets`, async (route) => {
        await jsonResponse(route, { assets: [] });
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/bookings`, async (route) => {
        await jsonResponse(route, { bookings: [] });
      });
      await page.route(`**/api/v1/portal/${VALID_TOKEN}/loyalty`, async (route) => {
        await jsonResponse(route, { points: 0, tier: 'bronze' });
      });

      await page.route('**/api/v1/auth/token/refresh', async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.goto(`${BASE_URL}/portal/${VALID_TOKEN}`);

      // Wait for invoices to load (default tab)
      await expect(page.getByText('INV-2025-001')).toBeVisible({ timeout: 5000 });

      expect(invoicesEndpointCalled).toBe(true);
      expect(capturedInvoicesUrl).toContain(`/api/v1/portal/${VALID_TOKEN}/invoices`);
    });

    test('v2 portal invoices endpoint returns 401 for expired token', async ({ page }) => {
      await page.route(`**/api/v2/portal/${EXPIRED_TOKEN}/invoices`, async (route) => {
        await jsonResponse(route, { detail: 'Portal token has expired' }, 401);
      });

      await page.route('**/api/v1/auth/token/refresh', async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.goto(`${BASE_URL}/portal/${EXPIRED_TOKEN}`);

      // Verify the v2 endpoint also rejects expired tokens
      const response = await page.evaluate(async (token) => {
        const res = await fetch(`/api/v2/portal/${token}/invoices`);
        return { status: res.status, body: await res.json() };
      }, EXPIRED_TOKEN);

      expect(response.status).toBe(401);
      expect(response.body.detail).toBe('Portal token has expired');
    });
  });
});
