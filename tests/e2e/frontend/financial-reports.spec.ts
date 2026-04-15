/**
 * E2E Playwright tests for OraFlows Financial Report pages (Sprint 2).
 *
 * Covers:
 *  - P&L report page loads with date range picker and basis toggle
 *  - Balance Sheet page loads and shows balanced indicator
 *  - Aged Receivables page loads with bucket columns
 *  - Module gating: report pages hidden when accounting module disabled
 *
 * All backend API calls are intercepted via page.route() so tests run
 * without a live backend.
 *
 * Validates: Requirements 6.1–6.7, 7.1–7.5, 8.1–8.3, 34.1–34.4
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
// Seed data — mock report responses
// ---------------------------------------------------------------------------

const SAMPLE_PL: Record<string, unknown> = {
  currency: 'NZD',
  period_start: '2026-03-01',
  period_end: '2026-03-31',
  basis: 'accrual',
  revenue_items: [
    { account_id: 'acct-4000', account_code: '4000', account_name: 'Sales Revenue', amount: 12500 },
  ],
  total_revenue: 12500,
  cogs_items: [],
  total_cogs: 0,
  gross_profit: 12500,
  gross_margin_pct: 100,
  expense_items: [
    { account_id: 'acct-6000', account_code: '6000', account_name: 'General Expenses', amount: 3200 },
  ],
  total_expenses: 3200,
  net_profit: 9300,
  net_margin_pct: 74.4,
};

const SAMPLE_BS: Record<string, unknown> = {
  currency: 'NZD',
  as_at_date: '2026-03-31',
  assets: {
    current: [
      { account_id: 'acct-1000', account_code: '1000', account_name: 'Bank/Cash', sub_type: 'current_asset', balance: 15000 },
    ],
    non_current: [],
    total: 15000,
  },
  liabilities: {
    current: [
      { account_id: 'acct-2000', account_code: '2000', account_name: 'Accounts Payable', sub_type: 'current_liability', balance: 3000 },
    ],
    non_current: [],
    total: 3000,
  },
  equity: {
    items: [
      { account_id: 'acct-3000', account_code: '3000', account_name: 'Retained Earnings', sub_type: 'retained_earnings', balance: 12000 },
    ],
    total: 12000,
  },
  total_assets: 15000,
  total_liabilities: 3000,
  total_equity: 12000,
  balanced: true,
};

const SAMPLE_AR: Record<string, unknown> = {
  report_date: '2026-03-31',
  customers: [
    {
      customer_id: 'cust-1',
      customer_name: 'Acme Motors',
      current: 1500,
      '31_60': 800,
      '61_90': 0,
      '90_plus': 200,
      total: 2500,
      invoices: [
        { invoice_id: 'inv-1', invoice_number: 'INV-0001', due_date: '2026-03-20', balance_due: 1500, days_overdue: 11, bucket: 'current' },
        { invoice_id: 'inv-2', invoice_number: 'INV-0002', due_date: '2026-02-10', balance_due: 800, days_overdue: 49, bucket: '31_60' },
        { invoice_id: 'inv-3', invoice_number: 'INV-0003', due_date: '2025-12-01', balance_due: 200, days_overdue: 120, bucket: '90_plus' },
      ],
    },
  ],
  overall: { current: 1500, '31_60': 800, '61_90': 0, '90_plus': 200, total: 2500 },
};

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
    await jsonResponse(route, { branding: { name: 'TestOrg' } });
  });

  const modules = accountingEnabled ? [ACCOUNTING_MODULE] : [];
  await page.route('**/api/v2/modules', async (route) => {
    await jsonResponse(route, { modules, total: modules.length });
  });

  await page.route('**/api/v1/org/feature-flags', async (route) => {
    await jsonResponse(route, {});
  });
}

/** Set up report API routes with mock data. */
async function setupReportRoutes(page: Page) {
  await page.route('**/api/v1/reports/profit-loss*', async (route) => {
    await jsonResponse(route, SAMPLE_PL);
  });

  await page.route('**/api/v1/reports/balance-sheet*', async (route) => {
    await jsonResponse(route, SAMPLE_BS);
  });

  await page.route('**/api/v1/reports/aged-receivables*', async (route) => {
    await jsonResponse(route, SAMPLE_AR);
  });
}

// ===========================================================================
// Test suites
// ===========================================================================

test.describe('Financial Reports — Profit & Loss', () => {
  test('P&L page loads with date range picker and basis toggle', async ({ page }) => {
    await setupAuthRoutes(page);
    await setupReportRoutes(page);

    await page.goto(`${BASE_URL}/reports/profit-loss`);

    // Page heading
    await expect(page.getByRole('heading', { name: 'Profit & Loss' })).toBeVisible({ timeout: 5000 });

    // Date range inputs present
    await expect(page.getByLabel('Start Date')).toBeVisible();
    await expect(page.getByLabel('End Date')).toBeVisible();

    // Basis toggle present with both options
    const basisSelect = page.getByLabel('Basis');
    await expect(basisSelect).toBeVisible();
    await expect(basisSelect.locator('option[value="accrual"]')).toBeAttached();
    await expect(basisSelect.locator('option[value="cash"]')).toBeAttached();

    // Report data rendered
    await expect(page.getByText('Sales Revenue')).toBeVisible();
    await expect(page.getByText('General Expenses')).toBeVisible();
    await expect(page.getByText('Net Profit')).toBeVisible();
    await expect(page.getByText('accrual basis', { exact: false })).toBeVisible();
  });
});

test.describe('Financial Reports — Balance Sheet', () => {
  test('Balance Sheet page loads and shows balanced indicator', async ({ page }) => {
    await setupAuthRoutes(page);
    await setupReportRoutes(page);

    await page.goto(`${BASE_URL}/reports/balance-sheet`);

    // Page heading
    await expect(page.getByRole('heading', { name: 'Balance Sheet' })).toBeVisible({ timeout: 5000 });

    // As At Date picker present
    await expect(page.getByLabel('As At Date')).toBeVisible();

    // Report sections rendered
    await expect(page.getByText('Assets')).toBeVisible();
    await expect(page.getByText('Liabilities')).toBeVisible();
    await expect(page.getByText('Equity')).toBeVisible();

    // Balanced badge visible
    await expect(page.getByText('Balanced')).toBeVisible();

    // Account data rendered
    await expect(page.getByText('Bank/Cash')).toBeVisible();
    await expect(page.getByText('Accounts Payable')).toBeVisible();
    await expect(page.getByText('Retained Earnings')).toBeVisible();
  });
});

test.describe('Financial Reports — Aged Receivables', () => {
  test('Aged Receivables page loads with bucket columns', async ({ page }) => {
    await setupAuthRoutes(page);
    await setupReportRoutes(page);

    await page.goto(`${BASE_URL}/reports/aged-receivables`);

    // Page heading
    await expect(page.getByRole('heading', { name: 'Aged Receivables' })).toBeVisible({ timeout: 5000 });

    // Report Date picker present
    await expect(page.getByLabel('Report Date')).toBeVisible();

    // Bucket column headers present
    await expect(page.getByRole('columnheader', { name: 'Current' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: '31–60' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: '61–90' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: '90+' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Total' })).toBeVisible();

    // Customer data rendered
    await expect(page.getByText('Acme Motors')).toBeVisible();
  });
});

test.describe('Financial Reports — Module Gating', () => {
  test('report pages redirect to dashboard when accounting module disabled', async ({ page }) => {
    await setupAuthRoutes(page, false);

    // Mock report endpoints in case they're called before redirect
    await page.route('**/api/v1/reports/**', async (route) => {
      await jsonResponse(route, {});
    });

    // Try navigating to P&L — should redirect to dashboard
    await page.goto(`${BASE_URL}/reports/profit-loss`);
    await page.waitForURL((url) => url.pathname.includes('/dashboard'), { timeout: 5000 });

    // Try navigating to Balance Sheet — should redirect to dashboard
    await page.goto(`${BASE_URL}/reports/balance-sheet`);
    await page.waitForURL((url) => url.pathname.includes('/dashboard'), { timeout: 5000 });

    // Try navigating to Aged Receivables — should redirect to dashboard
    await page.goto(`${BASE_URL}/reports/aged-receivables`);
    await page.waitForURL((url) => url.pathname.includes('/dashboard'), { timeout: 5000 });
  });
});
