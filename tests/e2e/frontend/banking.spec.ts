/**
 * E2E Playwright tests for OraFlows Banking pages (Sprint 4).
 *
 * Covers:
 *  - Bank Accounts page loads with account list
 *  - Bank Transactions page loads with transaction list and filters
 *  - Reconciliation Dashboard loads with summary cards
 *  - Module gating: banking pages hidden when accounting module disabled
 *
 * All backend API calls are intercepted via page.route() so tests run
 * without a live backend.
 *
 * Validates: Requirements 15.1–15.6, 16.1–16.4, 17.1–17.6, 18.1–18.5, 19.1–19.6, 34.1–34.4
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

const SAMPLE_BANK_ACCOUNTS = [
  {
    id: 'ba-001',
    org_id: 'org-1',
    akahu_account_id: 'acc_abc123',
    account_name: 'Business Cheque',
    account_number: '12-3456-7890123-00',
    bank_name: 'ANZ',
    account_type: 'checking',
    balance: 15420.5,
    currency: 'NZD',
    is_active: true,
    last_refreshed_at: '2026-04-10T08:00:00Z',
    linked_gl_account_id: 'gl-001',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-04-10T08:00:00Z',
  },
  {
    id: 'ba-002',
    org_id: 'org-1',
    akahu_account_id: 'acc_def456',
    account_name: 'Savings',
    account_number: '12-3456-7890123-01',
    bank_name: 'ANZ',
    account_type: 'savings',
    balance: 52000.0,
    currency: 'NZD',
    is_active: true,
    last_refreshed_at: '2026-04-10T08:00:00Z',
    linked_gl_account_id: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-04-10T08:00:00Z',
  },
];

const SAMPLE_TRANSACTIONS = [
  {
    id: 'txn-001',
    org_id: 'org-1',
    bank_account_id: 'ba-001',
    akahu_transaction_id: 'txn_abc123',
    date: '2026-04-09',
    description: 'Payment from Customer A',
    amount: 1500.0,
    balance: 16920.5,
    merchant_name: null,
    category: 'income',
    reconciliation_status: 'matched',
    matched_invoice_id: 'inv-001',
    matched_expense_id: null,
    matched_journal_id: null,
    created_at: '2026-04-09T10:00:00Z',
    updated_at: '2026-04-09T10:00:00Z',
  },
  {
    id: 'txn-002',
    org_id: 'org-1',
    bank_account_id: 'ba-001',
    akahu_transaction_id: 'txn_def456',
    date: '2026-04-08',
    description: 'Office Supplies - Warehouse Stationery',
    amount: -85.5,
    balance: 15335.0,
    merchant_name: 'Warehouse Stationery',
    category: 'office',
    reconciliation_status: 'unmatched',
    matched_invoice_id: null,
    matched_expense_id: null,
    matched_journal_id: null,
    created_at: '2026-04-08T14:00:00Z',
    updated_at: '2026-04-08T14:00:00Z',
  },
  {
    id: 'txn-003',
    org_id: 'org-1',
    bank_account_id: 'ba-001',
    akahu_transaction_id: 'txn_ghi789',
    date: '2026-04-07',
    description: 'Fuel - Z Energy',
    amount: -65.0,
    balance: 15270.0,
    merchant_name: 'Z Energy',
    category: 'transport',
    reconciliation_status: 'manual',
    matched_invoice_id: null,
    matched_expense_id: 'exp-001',
    matched_journal_id: null,
    created_at: '2026-04-07T09:00:00Z',
    updated_at: '2026-04-07T09:00:00Z',
  },
];

const SAMPLE_SUMMARY = {
  unmatched: 5,
  matched: 42,
  excluded: 3,
  manual: 2,
  total: 52,
  last_sync_at: '2026-04-10T08:00:00Z',
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

async function setupBankingRoutes(page: Page) {
  await page.route('**/api/v1/banking/accounts', async (route) => {
    if (route.request().url().match(/\/banking\/accounts$/)) {
      await jsonResponse(route, { items: SAMPLE_BANK_ACCOUNTS, total: SAMPLE_BANK_ACCOUNTS.length });
    } else {
      await route.continue();
    }
  });

  await page.route('**/api/v1/banking/transactions', async (route) => {
    await jsonResponse(route, { items: SAMPLE_TRANSACTIONS, total: SAMPLE_TRANSACTIONS.length });
  });

  await page.route('**/api/v1/banking/reconciliation-summary', async (route) => {
    await jsonResponse(route, SAMPLE_SUMMARY);
  });

  await page.route('**/api/v1/ledger/accounts*', async (route) => {
    await jsonResponse(route, { items: [], total: 0 });
  });
}

// ===========================================================================
// Test suites
// ===========================================================================

test.describe('Banking — Bank Accounts Page', () => {
  test('Bank accounts page loads with account list', async ({ page }) => {
    await setupAuthRoutes(page);
    await setupBankingRoutes(page);

    await page.goto(`${BASE_URL}/banking/accounts`);

    await expect(page.getByRole('heading', { name: 'Bank Accounts' })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('2 connected accounts')).toBeVisible();

    // Table headers
    await expect(page.getByText('Account')).toBeVisible();
    await expect(page.getByText('Bank')).toBeVisible();
    await expect(page.getByText('Balance')).toBeVisible();

    // Account data rendered
    await expect(page.getByText('Business Cheque')).toBeVisible();
    await expect(page.getByText('Savings')).toBeVisible();
    await expect(page.getByText('ANZ').first()).toBeVisible();

    // GL link status
    await expect(page.getByText('✓ Linked')).toBeVisible();
    await expect(page.getByText('Not linked')).toBeVisible();

    // Action buttons
    await expect(page.getByText('↻ Sync Now')).toBeVisible();
    await expect(page.getByText('+ Connect Bank')).toBeVisible();
  });
});

test.describe('Banking — Transactions Page', () => {
  test('Bank transactions page loads with transaction list', async ({ page }) => {
    await setupAuthRoutes(page);
    await setupBankingRoutes(page);

    await page.goto(`${BASE_URL}/banking/transactions`);

    await expect(page.getByRole('heading', { name: 'Bank Transactions' })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('3 transactions')).toBeVisible();

    // Table headers
    await expect(page.getByText('Date')).toBeVisible();
    await expect(page.getByText('Description')).toBeVisible();
    await expect(page.getByText('Amount')).toBeVisible();
    await expect(page.getByText('Status')).toBeVisible();

    // Transaction data
    await expect(page.getByText('Payment from Customer A')).toBeVisible();
    await expect(page.getByText('Office Supplies - Warehouse Stationery')).toBeVisible();

    // Status badges
    await expect(page.getByText('matched').first()).toBeVisible();
    await expect(page.getByText('unmatched')).toBeVisible();

    // Status filter dropdown
    await expect(page.getByRole('combobox')).toBeVisible();
  });
});

test.describe('Banking — Reconciliation Dashboard', () => {
  test('Reconciliation dashboard loads with summary cards', async ({ page }) => {
    await setupAuthRoutes(page);
    await setupBankingRoutes(page);

    await page.goto(`${BASE_URL}/banking/reconciliation`);

    await expect(page.getByRole('heading', { name: 'Reconciliation' })).toBeVisible({ timeout: 5000 });

    // Summary stat cards
    await expect(page.getByText('Total')).toBeVisible();
    await expect(page.getByText('52')).toBeVisible();
    await expect(page.getByText('Matched')).toBeVisible();
    await expect(page.getByText('42')).toBeVisible();
    await expect(page.getByText('Unmatched')).toBeVisible();

    // Last sync info
    await expect(page.getByText('Last sync:')).toBeVisible();

    // Navigation links
    await expect(page.getByText('Bank Accounts')).toBeVisible();
    await expect(page.getByText('View Transactions')).toBeVisible();
  });
});

test.describe('Banking — Module Gating', () => {
  test('Banking pages redirect to dashboard when accounting module disabled', async ({ page }) => {
    await setupAuthRoutes(page, false);

    await page.route('**/api/v1/banking/**', async (route) => {
      await jsonResponse(route, { items: [], total: 0 });
    });

    await page.goto(`${BASE_URL}/banking/accounts`);
    await page.waitForURL((url) => url.pathname.includes('/dashboard'), { timeout: 5000 });

    await page.goto(`${BASE_URL}/banking/transactions`);
    await page.waitForURL((url) => url.pathname.includes('/dashboard'), { timeout: 5000 });

    await page.goto(`${BASE_URL}/banking/reconciliation`);
    await page.waitForURL((url) => url.pathname.includes('/dashboard'), { timeout: 5000 });
  });
});
