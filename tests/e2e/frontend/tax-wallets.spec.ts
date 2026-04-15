/**
 * E2E Playwright tests for OraFlows Tax Wallets pages (Sprint 5).
 *
 * Covers:
 *  - Tax Wallets page loads with wallet balances
 *  - Manual deposit/withdrawal forms
 *  - Traffic light indicators display correctly
 *  - Tax Position dashboard widget
 *  - Module gating: tax pages hidden when accounting module disabled
 *
 * All backend API calls are intercepted via page.route() so tests run
 * without a live backend.
 *
 * Validates: Requirements 20.1–20.4, 21.1–21.5, 22.1–22.4, 23.1, 23.2, 34.1–34.4
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

async function jsonResponse(route: Route, body: Record<string, unknown> | unknown[], status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// Seed data
// ---------------------------------------------------------------------------

const SAMPLE_WALLETS = [
  {
    id: 'tw-001',
    org_id: 'org-1',
    wallet_type: 'gst',
    balance: 1500.0,
    target_balance: 3000.0,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-12T10:00:00Z',
  },
  {
    id: 'tw-002',
    org_id: 'org-1',
    wallet_type: 'income_tax',
    balance: 800.0,
    target_balance: 5000.0,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-12T10:00:00Z',
  },
  {
    id: 'tw-003',
    org_id: 'org-1',
    wallet_type: 'provisional_tax',
    balance: 0.0,
    target_balance: null,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-12T10:00:00Z',
  },
];

const SAMPLE_TRANSACTIONS = [
  {
    id: 'wtx-001',
    wallet_id: 'tw-001',
    amount: 500.0,
    transaction_type: 'auto_sweep',
    source_payment_id: 'pay-001',
    description: 'Auto-sweep GST from payment $3833.33',
    created_by: null,
    created_at: '2026-04-10T09:00:00Z',
  },
  {
    id: 'wtx-002',
    wallet_id: 'tw-001',
    amount: 1000.0,
    transaction_type: 'manual_deposit',
    source_payment_id: null,
    description: 'Manual top-up',
    created_by: 'user-1',
    created_at: '2026-04-11T14:00:00Z',
  },
];

const SAMPLE_SUMMARY = {
  currency: 'NZD',
  wallets: [
    {
      wallet_type: 'gst',
      balance: 1500.0,
      obligation: 2000.0,
      shortfall: 500.0,
      traffic_light: 'amber',
      next_due: '2026-06-28',
    },
    {
      wallet_type: 'income_tax',
      balance: 800.0,
      obligation: 5000.0,
      shortfall: 4200.0,
      traffic_light: 'red',
      next_due: '2026-08-28',
    },
  ],
  gst_wallet_balance: 1500.0,
  gst_owing: 2000.0,
  gst_shortfall: 500.0,
  income_tax_wallet_balance: 800.0,
  income_tax_estimate: 5000.0,
  income_tax_shortfall: 4200.0,
  next_gst_due: '2026-06-28',
  next_income_tax_due: '2026-08-28',
};

const SAMPLE_TAX_POSITION = {
  currency: 'NZD',
  gst_owing: 2000.0,
  next_gst_due: '2026-06-28',
  income_tax_estimate: 5000.0,
  next_income_tax_due: '2026-08-28',
  provisional_tax_amount: 1050.0,
  tax_year_start: '2026-04-01',
  tax_year_end: '2027-03-31',
  gst_wallet_balance: 1500.0,
  gst_shortfall: 500.0,
  gst_traffic_light: 'amber',
  income_tax_wallet_balance: 800.0,
  income_tax_shortfall: 4200.0,
  income_tax_traffic_light: 'red',
};

const MODULES_RESPONSE = {
  modules: [
    { module_key: 'accounting', is_enabled: true },
    { module_key: 'invoicing', is_enabled: true },
  ],
};

const MODULES_DISABLED_RESPONSE = {
  modules: [
    { module_key: 'accounting', is_enabled: false },
    { module_key: 'invoicing', is_enabled: true },
  ],
};

// ---------------------------------------------------------------------------
// Setup helper — intercept common API routes
// ---------------------------------------------------------------------------

async function setupAuthAndModules(page: Page, modulesEnabled = true) {
  // Auth login
  await page.route('**/api/v1/auth/login', (route) =>
    jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN, token_type: 'bearer' }),
  );

  // Auth me
  await page.route('**/api/v1/auth/me', (route) =>
    jsonResponse(route, {
      id: 'user-1',
      email: TEST_USER.email,
      role: 'org_admin',
      org_id: 'org-1',
      first_name: 'Test',
      last_name: 'Admin',
    }),
  );

  // Modules
  await page.route('**/api/v2/modules**', (route) =>
    jsonResponse(route, modulesEnabled ? MODULES_RESPONSE : MODULES_DISABLED_RESPONSE),
  );

  // Notifications
  await page.route('**/api/v1/notifications**', (route) =>
    jsonResponse(route, { items: [], total: 0 }),
  );

  // Organisation
  await page.route('**/api/v1/org**', (route) =>
    jsonResponse(route, {
      id: 'org-1',
      name: 'Test Workshop',
      settings: { tax_sweep_enabled: true, tax_sweep_gst_auto: true },
    }),
  );
}

async function loginViaUI(page: Page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');

  // Set auth token directly in localStorage to skip login form
  await page.evaluate((token) => {
    localStorage.setItem('access_token', token);
  }, FAKE_ACCESS_TOKEN);
}

// ---------------------------------------------------------------------------
// Tests: Tax Wallets page
// ---------------------------------------------------------------------------

test.describe('Tax Wallets Page', () => {
  test('loads and displays wallet balances', async ({ page }) => {
    await setupAuthAndModules(page);

    await page.route('**/api/v1/tax-wallets', (route) => {
      if (route.request().url().includes('/summary')) return route.fallback();
      return jsonResponse(route, { items: SAMPLE_WALLETS, total: 3 });
    });

    await loginViaUI(page);
    await page.goto(`${BASE_URL}/tax/wallets`);
    await page.waitForLoadState('networkidle');

    // Should show all 3 wallet types
    await expect(page.getByText('Tax Savings Wallets')).toBeVisible();
    await expect(page.getByText('$1,500.00')).toBeVisible();
    await expect(page.getByText('$800.00')).toBeVisible();
  });

  test('deposit form submits correctly', async ({ page }) => {
    await setupAuthAndModules(page);

    await page.route('**/api/v1/tax-wallets', (route) => {
      if (route.request().url().includes('/summary')) return route.fallback();
      return jsonResponse(route, { items: SAMPLE_WALLETS, total: 3 });
    });

    await page.route('**/api/v1/tax-wallets/gst/deposit', (route) =>
      jsonResponse(route, {
        id: 'wtx-new',
        wallet_id: 'tw-001',
        amount: 250.0,
        transaction_type: 'manual_deposit',
        description: 'Test deposit',
        created_by: 'user-1',
        created_at: '2026-04-12T12:00:00Z',
      }),
    );

    await loginViaUI(page);
    await page.goto(`${BASE_URL}/tax/wallets`);
    await page.waitForLoadState('networkidle');

    // Click deposit on first wallet
    const depositButtons = page.getByRole('button', { name: 'Deposit' });
    await depositButtons.first().click();

    // Fill form
    await page.getByLabel('Amount ($)').fill('250');
    await page.getByPlaceholder('Optional description').fill('Test deposit');
    await page.getByRole('button', { name: 'Confirm' }).click();

    await expect(page.getByText('Deposit successful')).toBeVisible();
  });

  test('withdrawal rejection shows error', async ({ page }) => {
    await setupAuthAndModules(page);

    await page.route('**/api/v1/tax-wallets', (route) => {
      if (route.request().url().includes('/summary')) return route.fallback();
      return jsonResponse(route, { items: SAMPLE_WALLETS, total: 3 });
    });

    await page.route('**/api/v1/tax-wallets/gst/withdraw', (route) =>
      route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: {
            code: 'INSUFFICIENT_BALANCE',
            message: 'Withdrawal of $99999.00 exceeds wallet balance of $1500.00',
          },
        }),
      }),
    );

    await loginViaUI(page);
    await page.goto(`${BASE_URL}/tax/wallets`);
    await page.waitForLoadState('networkidle');

    // Click withdraw on first wallet
    const withdrawButtons = page.getByRole('button', { name: 'Withdraw' });
    await withdrawButtons.first().click();

    await page.getByLabel('Amount ($)').fill('99999');
    await page.getByRole('button', { name: 'Confirm' }).click();

    await expect(page.getByText(/exceeds wallet balance/i)).toBeVisible();
  });

  test('transaction history loads when wallet selected', async ({ page }) => {
    await setupAuthAndModules(page);

    await page.route('**/api/v1/tax-wallets', (route) => {
      if (route.request().url().includes('/summary')) return route.fallback();
      if (route.request().url().includes('/transactions')) {
        return jsonResponse(route, { items: SAMPLE_TRANSACTIONS, total: 2 });
      }
      return jsonResponse(route, { items: SAMPLE_WALLETS, total: 3 });
    });

    await page.route('**/api/v1/tax-wallets/gst/transactions', (route) =>
      jsonResponse(route, { items: SAMPLE_TRANSACTIONS, total: 2 }),
    );

    await loginViaUI(page);
    await page.goto(`${BASE_URL}/tax/wallets`);
    await page.waitForLoadState('networkidle');

    // Click on GST wallet card
    await page.getByText('$1,500.00').click();

    // Should show transaction history
    await expect(page.getByText('Transaction History')).toBeVisible();
    await expect(page.getByText('Auto Sweep')).toBeVisible();
    await expect(page.getByText('Manual Deposit')).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Tests: Tax Position dashboard
// ---------------------------------------------------------------------------

test.describe('Tax Position Dashboard', () => {
  test('loads and displays GST and income tax cards', async ({ page }) => {
    await setupAuthAndModules(page);

    await page.route('**/api/v1/reports/tax-position', (route) =>
      jsonResponse(route, SAMPLE_TAX_POSITION),
    );

    await page.route('**/api/v1/tax-wallets/summary', (route) =>
      jsonResponse(route, SAMPLE_SUMMARY),
    );

    await loginViaUI(page);
    await page.goto(`${BASE_URL}/tax/position`);
    await page.waitForLoadState('networkidle');

    await expect(page.getByText('Tax Position Dashboard')).toBeVisible();
    await expect(page.getByText('GST')).toBeVisible();
    await expect(page.getByText('Income Tax')).toBeVisible();
  });

  test('displays traffic light indicators', async ({ page }) => {
    await setupAuthAndModules(page);

    await page.route('**/api/v1/reports/tax-position', (route) =>
      jsonResponse(route, SAMPLE_TAX_POSITION),
    );

    await page.route('**/api/v1/tax-wallets/summary', (route) =>
      jsonResponse(route, SAMPLE_SUMMARY),
    );

    await loginViaUI(page);
    await page.goto(`${BASE_URL}/tax/position`);
    await page.waitForLoadState('networkidle');

    // Should show amber for GST (75% coverage) and red for income tax (16%)
    await expect(page.getByText('Amber')).toBeVisible();
    await expect(page.getByText('Red')).toBeVisible();
  });

  test('displays shortfall amounts', async ({ page }) => {
    await setupAuthAndModules(page);

    await page.route('**/api/v1/reports/tax-position', (route) =>
      jsonResponse(route, SAMPLE_TAX_POSITION),
    );

    await page.route('**/api/v1/tax-wallets/summary', (route) =>
      jsonResponse(route, SAMPLE_SUMMARY),
    );

    await loginViaUI(page);
    await page.goto(`${BASE_URL}/tax/position`);
    await page.waitForLoadState('networkidle');

    // GST shortfall $500, income tax shortfall $4,200
    await expect(page.getByText('$500.00')).toBeVisible();
    await expect(page.getByText('$4,200.00')).toBeVisible();
  });

  test('displays wallet coverage section', async ({ page }) => {
    await setupAuthAndModules(page);

    await page.route('**/api/v1/reports/tax-position', (route) =>
      jsonResponse(route, SAMPLE_TAX_POSITION),
    );

    await page.route('**/api/v1/tax-wallets/summary', (route) =>
      jsonResponse(route, SAMPLE_SUMMARY),
    );

    await loginViaUI(page);
    await page.goto(`${BASE_URL}/tax/position`);
    await page.waitForLoadState('networkidle');

    await expect(page.getByText('Wallet Coverage')).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Tests: Module gating
// ---------------------------------------------------------------------------

test.describe('Module Gating', () => {
  test('tax wallets page redirects when accounting disabled', async ({ page }) => {
    await setupAuthAndModules(page, false);

    await loginViaUI(page);
    await page.goto(`${BASE_URL}/tax/wallets`);
    await page.waitForLoadState('networkidle');

    // Should redirect to dashboard
    await expect(page).toHaveURL(/dashboard/);
  });

  test('tax position page redirects when accounting disabled', async ({ page }) => {
    await setupAuthAndModules(page, false);

    await loginViaUI(page);
    await page.goto(`${BASE_URL}/tax/position`);
    await page.waitForLoadState('networkidle');

    // Should redirect to dashboard
    await expect(page).toHaveURL(/dashboard/);
  });
});
