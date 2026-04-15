/**
 * E2E Playwright tests for OraFlows Accounting pages (Sprint 1).
 *
 * Covers:
 *  - COA page loads with seeded accounts visible
 *  - Create custom account form submission
 *  - Manual journal entry creation with balanced lines
 *  - Accounting periods list and close action
 *  - Module gating: accounting nav hidden when module disabled
 *
 * All backend API calls are intercepted via page.route() so tests run
 * without a live backend.
 *
 * Validates: Requirements 1.1–1.7, 2.1–2.7, 3.1–3.5, 34.1–34.4
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
// Seed data — mirrors the NZ COA seed from the migration
// ---------------------------------------------------------------------------

const SEED_ACCOUNTS = [
  { id: 'acct-1000', code: '1000', name: 'Bank/Cash', account_type: 'asset', sub_type: 'current_asset', is_system: true, is_active: true, parent_id: null, tax_code: null, xero_account_code: '090', description: null, org_id: 'org-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  { id: 'acct-1100', code: '1100', name: 'Accounts Receivable', account_type: 'asset', sub_type: 'accounts_receivable', is_system: true, is_active: true, parent_id: null, tax_code: null, xero_account_code: null, description: null, org_id: 'org-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  { id: 'acct-1200', code: '1200', name: 'GST Receivable', account_type: 'asset', sub_type: 'current_asset', is_system: true, is_active: true, parent_id: null, tax_code: 'GST', xero_account_code: null, description: null, org_id: 'org-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  { id: 'acct-2000', code: '2000', name: 'Accounts Payable', account_type: 'liability', sub_type: 'current_liability', is_system: true, is_active: true, parent_id: null, tax_code: null, xero_account_code: null, description: null, org_id: 'org-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  { id: 'acct-2100', code: '2100', name: 'GST Payable', account_type: 'liability', sub_type: 'current_liability', is_system: true, is_active: true, parent_id: null, tax_code: 'GST', xero_account_code: null, description: null, org_id: 'org-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  { id: 'acct-4000', code: '4000', name: 'Sales Revenue', account_type: 'revenue', sub_type: 'operating_revenue', is_system: true, is_active: true, parent_id: null, tax_code: 'GST', xero_account_code: '200', description: null, org_id: 'org-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  { id: 'acct-6000', code: '6000', name: 'General Expenses', account_type: 'expense', sub_type: 'operating_expense', is_system: true, is_active: true, parent_id: null, tax_code: 'GST', xero_account_code: null, description: null, org_id: 'org-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
];

const SAMPLE_PERIODS = [
  {
    id: 'period-001',
    org_id: 'org-1',
    period_name: 'April 2026',
    start_date: '2026-04-01',
    end_date: '2026-04-30',
    is_closed: false,
    closed_by: null,
    closed_at: null,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
  },
  {
    id: 'period-002',
    org_id: 'org-1',
    period_name: 'March 2026',
    start_date: '2026-03-01',
    end_date: '2026-03-31',
    is_closed: true,
    closed_by: 'user-1',
    closed_at: '2026-04-01T09:00:00Z',
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-04-01T09:00:00Z',
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
    await jsonResponse(route, { branding: { name: 'TestOrg' } });
  });

  // Module context fetches from /api/v2/modules
  const modules = accountingEnabled ? [ACCOUNTING_MODULE] : [];
  await page.route('**/api/v2/modules', async (route) => {
    await jsonResponse(route, { modules, total: modules.length });
  });

  await page.route('**/api/v1/org/feature-flags', async (route) => {
    await jsonResponse(route, {});
  });
}

/** Set up ledger API routes for COA, journal entries, and periods. */
async function setupLedgerRoutes(
  page: Page,
  accounts: Record<string, unknown>[],
  entries: Record<string, unknown>[],
  periods: Record<string, unknown>[],
) {
  // COA accounts
  await page.route('**/api/v1/ledger/accounts', async (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      await jsonResponse(route, { items: accounts, total: accounts.length });
    } else if (method === 'POST') {
      const body = route.request().postDataJSON();
      const newAccount = {
        id: `acct-new-${Date.now()}`,
        org_id: 'org-1',
        code: body.code,
        name: body.name,
        account_type: body.account_type,
        sub_type: body.sub_type ?? null,
        description: body.description ?? null,
        is_system: false,
        is_active: true,
        parent_id: null,
        tax_code: body.tax_code ?? null,
        xero_account_code: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      accounts.push(newAccount);
      await jsonResponse(route, newAccount, 201);
    } else {
      await route.continue();
    }
  });

  // Journal entries
  await page.route('**/api/v1/ledger/journal-entries', async (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      await jsonResponse(route, { items: entries, total: entries.length });
    } else if (method === 'POST') {
      const body = route.request().postDataJSON();
      const newEntry = {
        id: `je-new-${Date.now()}`,
        org_id: 'org-1',
        entry_number: `JE-${String(entries.length + 1).padStart(4, '0')}`,
        entry_date: body.entry_date,
        description: body.description,
        reference: body.reference ?? null,
        source_type: 'manual',
        source_id: null,
        period_id: null,
        is_posted: false,
        created_by: 'user-1',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        lines: (body.lines ?? []).map((l: Record<string, unknown>, i: number) => ({
          id: `jl-new-${Date.now()}-${i}`,
          journal_entry_id: `je-new-${Date.now()}`,
          org_id: 'org-1',
          account_id: l.account_id,
          debit: l.debit ?? 0,
          credit: l.credit ?? 0,
          description: l.description ?? null,
        })),
      };
      entries.push(newEntry);
      await jsonResponse(route, newEntry, 201);
    } else {
      await route.continue();
    }
  });

  // Accounting periods
  await page.route('**/api/v1/ledger/periods', async (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      await jsonResponse(route, { items: periods, total: periods.length });
    } else if (method === 'POST') {
      const body = route.request().postDataJSON();
      const newPeriod = {
        id: `period-new-${Date.now()}`,
        org_id: 'org-1',
        period_name: body.period_name,
        start_date: body.start_date,
        end_date: body.end_date,
        is_closed: false,
        closed_by: null,
        closed_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      periods.push(newPeriod);
      await jsonResponse(route, newPeriod, 201);
    } else {
      await route.continue();
    }
  });

  // Period close action
  await page.route('**/api/v1/ledger/periods/*/close', async (route) => {
    const url = route.request().url();
    const match = url.match(/periods\/([^/]+)\/close/);
    const periodId = match?.[1];
    const period = periods.find((p) => (p as { id: string }).id === periodId);
    if (period) {
      (period as Record<string, unknown>).is_closed = true;
      (period as Record<string, unknown>).closed_by = 'user-1';
      (period as Record<string, unknown>).closed_at = new Date().toISOString();
      await jsonResponse(route, period as Record<string, unknown>);
    } else {
      await jsonResponse(route, { detail: 'Period not found' }, 404);
    }
  });
}

// ===========================================================================
// Test suites
// ===========================================================================

test.describe('Accounting — Chart of Accounts', () => {
  test('COA page loads with seeded accounts visible', async ({ page }) => {
    await setupAuthRoutes(page);
    const accounts: Record<string, unknown>[] = [...SEED_ACCOUNTS];
    await setupLedgerRoutes(page, accounts, [], []);

    await page.goto(`${BASE_URL}/accounting`);

    // Page heading
    await expect(page.getByRole('heading', { name: 'Chart of Accounts' })).toBeVisible({ timeout: 5000 });

    // Verify seeded accounts are displayed in the table
    await expect(page.getByText('Bank/Cash')).toBeVisible();
    await expect(page.getByText('Accounts Receivable')).toBeVisible();
    await expect(page.getByText('Sales Revenue')).toBeVisible();
    await expect(page.getByText('General Expenses')).toBeVisible();

    // Verify account codes are visible
    await expect(page.getByText('1000')).toBeVisible();
    await expect(page.getByText('4000')).toBeVisible();

    // Verify account count in subtitle
    await expect(page.getByText(`${accounts.length} accounts`)).toBeVisible();
  });

  test('create custom account form submission', async ({ page }) => {
    await setupAuthRoutes(page);
    const accounts: Record<string, unknown>[] = [...SEED_ACCOUNTS];
    await setupLedgerRoutes(page, accounts, [], []);

    let capturedCreateBody: Record<string, unknown> | null = null;

    // Override the POST route to capture the request body
    await page.route('**/api/v1/ledger/accounts', async (route) => {
      const method = route.request().method();
      if (method === 'POST') {
        capturedCreateBody = route.request().postDataJSON();
        const newAccount = {
          id: 'acct-new-test',
          org_id: 'org-1',
          code: String(capturedCreateBody?.code ?? ''),
          name: String(capturedCreateBody?.name ?? ''),
          account_type: String(capturedCreateBody?.account_type ?? ''),
          sub_type: capturedCreateBody?.sub_type ? String(capturedCreateBody.sub_type) : null,
          description: capturedCreateBody?.description ? String(capturedCreateBody.description) : null,
          is_system: false,
          is_active: true,
          parent_id: null,
          tax_code: capturedCreateBody?.tax_code ? String(capturedCreateBody.tax_code) : null,
          xero_account_code: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        accounts.push(newAccount);
        await jsonResponse(route, newAccount, 201);
      } else {
        await jsonResponse(route, { items: accounts, total: accounts.length });
      }
    });

    await page.goto(`${BASE_URL}/accounting`);
    await expect(page.getByRole('heading', { name: 'Chart of Accounts' })).toBeVisible({ timeout: 5000 });

    // Click "+ New Account" button
    await page.getByRole('button', { name: '+ New Account' }).click();

    // Fill in the create form
    const dialog = page.locator('[class*="modal"], [role="dialog"]').first();
    await expect(dialog.getByText('New Account')).toBeVisible({ timeout: 3000 });

    await dialog.getByLabel('Code').fill('6100');
    await dialog.getByLabel('Name').fill('Marketing Expenses');
    await dialog.getByLabel('Account Type').selectOption('expense');
    await dialog.getByLabel('Tax Code').fill('GST');

    // Submit
    await dialog.getByRole('button', { name: 'Create' }).click();

    // Verify the request was sent with correct data
    await expect.poll(() => capturedCreateBody).toBeTruthy();
    expect(capturedCreateBody).toMatchObject({
      code: '6100',
      name: 'Marketing Expenses',
      account_type: 'expense',
    });
  });
});

test.describe('Accounting — Journal Entries', () => {
  test('manual journal entry creation with balanced lines', async ({ page }) => {
    await setupAuthRoutes(page);
    const accounts: Record<string, unknown>[] = [...SEED_ACCOUNTS];
    const entries: Record<string, unknown>[] = [];
    await setupLedgerRoutes(page, accounts, entries, []);

    let capturedEntryBody: Record<string, unknown> | null = null;

    // Override POST to capture the journal entry creation request
    await page.route('**/api/v1/ledger/journal-entries', async (route) => {
      const method = route.request().method();
      if (method === 'POST') {
        capturedEntryBody = route.request().postDataJSON();
        const newEntry = {
          id: 'je-new-test',
          org_id: 'org-1',
          entry_number: 'JE-0001',
          entry_date: capturedEntryBody?.entry_date,
          description: capturedEntryBody?.description,
          reference: capturedEntryBody?.reference ?? null,
          source_type: 'manual',
          source_id: null,
          period_id: null,
          is_posted: false,
          created_by: 'user-1',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          lines: [],
        };
        entries.push(newEntry);
        await jsonResponse(route, newEntry, 201);
      } else {
        await jsonResponse(route, { items: entries, total: entries.length });
      }
    });

    await page.goto(`${BASE_URL}/accounting/journal-entries`);
    await expect(page.getByRole('heading', { name: 'Journal Entries' })).toBeVisible({ timeout: 5000 });

    // Click "+ New Entry" button
    await page.getByRole('button', { name: '+ New Entry' }).click();

    // Fill in the journal entry form
    const dialog = page.locator('[class*="modal"], [role="dialog"]').first();
    await expect(dialog.getByText('New Manual Journal Entry')).toBeVisible({ timeout: 3000 });

    await dialog.getByLabel('Description').fill('Test manual journal entry');
    await dialog.getByLabel('Reference').fill('TEST-REF-001');

    // Fill line 1: Debit Bank/Cash $500
    const selects = dialog.locator('select');
    await selects.nth(0).selectOption({ label: '1000 — Bank/Cash' });
    const debitInputs = dialog.locator('input[placeholder="Debit"]');
    await debitInputs.nth(0).fill('500');

    // Fill line 2: Credit Sales Revenue $500
    await selects.nth(1).selectOption({ label: '4000 — Sales Revenue' });
    const creditInputs = dialog.locator('input[placeholder="Credit"]');
    await creditInputs.nth(1).fill('500');

    // Verify balanced indicator
    await expect(dialog.getByText('✓ Balanced')).toBeVisible();

    // Submit
    await dialog.getByRole('button', { name: 'Create Entry' }).click();

    // Verify the request was sent
    await expect.poll(() => capturedEntryBody).toBeTruthy();
    expect(capturedEntryBody).toMatchObject({
      description: 'Test manual journal entry',
      reference: 'TEST-REF-001',
      source_type: 'manual',
    });

    // Verify lines have balanced debits and credits
    const lines = (capturedEntryBody as unknown as Record<string, unknown>)?.lines as Array<{ debit: number; credit: number }>;
    expect(lines).toBeDefined();
    expect(lines.length).toBeGreaterThanOrEqual(2);
    const totalDebits = lines.reduce((sum, l) => sum + (l.debit || 0), 0);
    const totalCredits = lines.reduce((sum, l) => sum + (l.credit || 0), 0);
    expect(Math.abs(totalDebits - totalCredits)).toBeLessThan(0.01);
  });
});

test.describe('Accounting — Accounting Periods', () => {
  test('periods list and close action', async ({ page }) => {
    await setupAuthRoutes(page);
    const periods = [...SAMPLE_PERIODS];
    await setupLedgerRoutes(page, [...SEED_ACCOUNTS], [], periods);

    await page.goto(`${BASE_URL}/accounting/periods`);
    await expect(page.getByRole('heading', { name: 'Accounting Periods' })).toBeVisible({ timeout: 5000 });

    // Verify periods are listed
    await expect(page.getByText('April 2026')).toBeVisible();
    await expect(page.getByText('March 2026')).toBeVisible();

    // Verify status badges
    await expect(page.getByText('Open')).toBeVisible();
    await expect(page.getByText('Closed')).toBeVisible();

    // The open period should have a "Close Period" button
    const closeButton = page.getByRole('button', { name: 'Close Period' });
    await expect(closeButton).toBeVisible();

    // Mock the confirm dialog
    page.on('dialog', (dialog) => dialog.accept());

    // Click close on the open period
    await closeButton.click();

    // After closing, the page should refetch and show the period as closed
    // The route handler updates the period in-place, so the next GET returns it as closed
    await expect(page.getByText('Open')).not.toBeVisible({ timeout: 5000 });
  });
});

test.describe('Accounting — Module Gating', () => {
  test('accounting nav is hidden when module is disabled', async ({ page }) => {
    // Set up auth with accounting module DISABLED
    await setupAuthRoutes(page, false);

    await page.goto(`${BASE_URL}/dashboard`);

    // Wait for the page to load
    await page.waitForLoadState('networkidle');

    // The "Accounting" nav link should NOT be visible in the sidebar
    const accountingLink = page.locator('nav').getByText('Accounting', { exact: true });
    await expect(accountingLink).not.toBeVisible({ timeout: 3000 });

    // Banking and Tax nav links (also gated by accounting module) should also be hidden
    const bankingLink = page.locator('nav').getByText('Banking', { exact: true });
    await expect(bankingLink).not.toBeVisible();

    const taxLink = page.locator('nav').getByText('Tax', { exact: true });
    await expect(taxLink).not.toBeVisible();
  });

  test('accounting page redirects to dashboard when module is disabled', async ({ page }) => {
    // Set up auth with accounting module DISABLED
    await setupAuthRoutes(page, false);

    // Mock the ledger accounts endpoint (in case it's called before redirect)
    await page.route('**/api/v1/ledger/accounts', async (route) => {
      await jsonResponse(route, { items: [], total: 0 });
    });

    // Try to navigate directly to accounting page
    await page.goto(`${BASE_URL}/accounting`);

    // Should redirect to dashboard since module is disabled
    await page.waitForURL((url) => url.pathname.includes('/dashboard'), { timeout: 5000 });
  });
});
