/**
 * E2E Playwright tests for OraFlows GST Filing pages (Sprint 3).
 *
 * Covers:
 *  - GST periods page loads with period list
 *  - GST filing detail page shows return data
 *  - GST basis toggle in settings
 *  - Module gating: GST pages hidden when accounting module disabled
 *
 * All backend API calls are intercepted via page.route() so tests run
 * without a live backend.
 *
 * Validates: Requirements 11.1–11.4, 12.1–12.4, 34.1–34.4
 */
import { test, expect, type Page, type Route } from '@playwright/test';

// ---------------------------------------------------------------------------
// Helpers & constants
// ---------------------------------------------------------------------------

const BASE_URL = 'http://localhost:5173';

const TEST_USER = {
  email: 'admin@workshop.co.nz',
  password: 'SecureP@ss1',
};

const FAKE_ACCESS_TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  btoa(
    JSON.stringify({
      sub: 'user-1',
      user_id: 'user-1',
      org_id: 'org-1',
      role: 'org_admin',
      email: TEST_USER.email,
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  )
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '') +
  '.fake-signature';

/** Respond to a route with JSON. */
async function jsonResponse(route: Route, body: Record<string, unknown> | unknown[], status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// Seed data — mock GST filing periods
// ---------------------------------------------------------------------------

const SAMPLE_GST_PERIODS = [
  {
    id: 'gst-period-001',
    org_id: 'org-1',
    period_type: 'two_monthly',
    period_start: '2026-03-01',
    period_end: '2026-04-30',
    due_date: '2026-05-28',
    status: 'draft',
    filed_at: null,
    filed_by: null,
    ird_reference: null,
    return_data: null,
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
  },
  {
    id: 'gst-period-002',
    org_id: 'org-1',
    period_type: 'two_monthly',
    period_start: '2026-01-01',
    period_end: '2026-02-28',
    due_date: '2026-03-28',
    status: 'filed',
    filed_at: '2026-03-15T10:00:00Z',
    filed_by: 'user-1',
    ird_reference: 'IRD-GST-2026-001',
    return_data: {
      total_sales: 25000,
      total_purchases: 8500,
      gst_collected: 3750,
      gst_paid: 1275,
      gst_owing: 2475,
    },
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-03-15T10:00:00Z',
  },
];

const ACCOUNTING_MODULE = {
  slug: 'accounting',
  display_name: 'Accounting',
  description: 'Double-entry ledger, COA, journal entries',
  category: 'finance',
  is_core: false,
  is_enabled: true,
};

// ---------------------------------------------------------------------------
// Auth + common route setup
// ---------------------------------------------------------------------------

/** Set up authenticated session routes with accounting module enabled. */
async function setupAuthRoutes(page: Page, accountingEnabled = true) {
  await page.route('**/api/v1/auth/token/refresh', async (route) => {
    await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
  });

  await page.route('**/api/v1/auth/me', async (route) => {
    await jsonResponse(route, {
      first_name: 'Test',
      last_name: 'Admin',
      email: TEST_USER.email,
      role: 'org_admin',
      branch_ids: [],
    });
  });

  await page.route('**/api/v1/org/branches', async (route) => {
    await jsonResponse(route, { branches: [] });
  });

  await page.route('**/api/v1/org/settings', async (route) => {
    const method = route.request().method();
    if (method === 'PUT') {
      const body = route.request().postDataJSON();
      await jsonResponse(route, { branding: { name: 'TestOrg' }, ...body });
    } else {
      await jsonResponse(route, {
        branding: { name: 'TestOrg' },
        gst_number: '49091850',
        gst_percentage: 15,
        gst_inclusive: true,
      });
    }
  });

  const modules = accountingEnabled ? [ACCOUNTING_MODULE] : [];
  await page.route('**/api/v2/modules', async (route) => {
    await jsonResponse(route, { modules, total: modules.length });
  });

  await page.route('**/api/v1/org/feature-flags', async (route) => {
    await jsonResponse(route, {});
  });
}

/** Set up GST filing API routes with mock data. */
async function setupGstRoutes(page: Page) {
  // GST periods list
  await page.route('**/api/v1/gst/periods', async (route) => {
    const url = route.request().url();
    // Only match the list endpoint, not /gst/periods/{id}
    if (url.match(/\/gst\/periods$/)) {
      await jsonResponse(route, { items: SAMPLE_GST_PERIODS, total: SAMPLE_GST_PERIODS.length });
    } else {
      await route.continue();
    }
  });

  // GST period detail
  await page.route('**/api/v1/gst/periods/*', async (route) => {
    const url = route.request().url();
    const match = url.match(/\/gst\/periods\/([^/]+)$/);
    if (match) {
      const periodId = match[1];
      const period = SAMPLE_GST_PERIODS.find((p) => p.id === periodId);
      if (period) {
        await jsonResponse(route, period);
      } else {
        await jsonResponse(route, { detail: 'Period not found' }, 404);
      }
    } else {
      await route.continue();
    }
  });
}

// ===========================================================================
// Test suites
// ===========================================================================

test.describe('GST Filing — Periods List', () => {
  test('GST periods page loads with period list', async ({ page }) => {
    await setupAuthRoutes(page);
    await setupGstRoutes(page);

    await page.goto(`${BASE_URL}/tax/gst-periods`);

    // Page heading
    await expect(page.getByRole('heading', { name: 'GST Filing Periods' })).toBeVisible({ timeout: 5000 });

    // Period count subtitle
    await expect(page.getByText('2 periods')).toBeVisible();

    // Table column headers present
    await expect(page.getByText('Period')).toBeVisible();
    await expect(page.getByText('Type')).toBeVisible();
    await expect(page.getByText('Due Date')).toBeVisible();
    await expect(page.getByText('Status')).toBeVisible();

    // Status badges rendered
    await expect(page.getByText('Draft')).toBeVisible();
    await expect(page.getByText('Filed')).toBeVisible();

    // Period type rendered
    await expect(page.getByText('two monthly').first()).toBeVisible();

    // Generate button present
    await expect(page.getByRole('button', { name: '+ Generate Periods' })).toBeVisible();
  });
});

test.describe('GST Filing — Detail Page', () => {
  test('GST filing detail page shows return data', async ({ page }) => {
    await setupAuthRoutes(page);
    await setupGstRoutes(page);

    // Navigate to the filed period with return data
    await page.goto(`${BASE_URL}/tax/gst-periods/gst-period-002`);

    // Status badge
    await expect(page.getByText('Filed')).toBeVisible({ timeout: 5000 });

    // Period type label
    await expect(page.getByText('two monthly period')).toBeVisible();

    // Return Data section heading
    await expect(page.getByRole('heading', { name: 'Return Data' })).toBeVisible();

    // Return data fields rendered in the table
    await expect(page.getByText('total_sales')).toBeVisible();
    await expect(page.getByText('gst_collected')).toBeVisible();
    await expect(page.getByText('gst_owing')).toBeVisible();

    // Return data values rendered
    await expect(page.getByText('25000.00')).toBeVisible();
    await expect(page.getByText('2475.00')).toBeVisible();

    // IRD Reference displayed
    await expect(page.getByText('IRD-GST-2026-001')).toBeVisible();

    // Back link present
    await expect(page.getByText('← Back to GST Periods')).toBeVisible();
  });
});

test.describe('GST Filing — Basis Toggle in Settings', () => {
  test('GST basis toggle in settings page', async ({ page }) => {
    await setupAuthRoutes(page);

    await page.goto(`${BASE_URL}/settings`);

    // Wait for settings page to load
    await page.waitForLoadState('networkidle');

    // Navigate to the GST settings tab
    const gstTab = page.getByText('GST', { exact: true }).or(page.getByText('Tax', { exact: true }));
    if (await gstTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await gstTab.click();
    }

    // GST Number field should be visible
    await expect(page.getByLabel('GST Number')).toBeVisible({ timeout: 5000 });

    // GST Percentage field should be visible
    await expect(page.getByLabel('GST Percentage')).toBeVisible();

    // GST inclusive/exclusive toggle should be present
    const gstToggle = page.locator('[role="switch"]').first();
    await expect(gstToggle).toBeVisible();

    // Toggle should be clickable (switch from inclusive to exclusive)
    await gstToggle.click();

    // Verify the toggle text changes
    await expect(page.getByText('GST Exclusive')).toBeVisible();
  });
});

test.describe('GST Filing — Module Gating', () => {
  test('GST pages redirect to dashboard when accounting module disabled', async ({ page }) => {
    await setupAuthRoutes(page, false);

    // Mock GST endpoints in case they're called before redirect
    await page.route('**/api/v1/gst/**', async (route) => {
      await jsonResponse(route, { items: [], total: 0 });
    });

    // Try navigating to GST periods — should redirect to dashboard
    await page.goto(`${BASE_URL}/tax/gst-periods`);
    await page.waitForURL((url) => url.pathname.includes('/dashboard'), { timeout: 5000 });

    // Try navigating to GST filing detail — should redirect to dashboard
    await page.goto(`${BASE_URL}/tax/gst-periods/gst-period-001`);
    await page.waitForURL((url) => url.pathname.includes('/dashboard'), { timeout: 5000 });
  });
});
