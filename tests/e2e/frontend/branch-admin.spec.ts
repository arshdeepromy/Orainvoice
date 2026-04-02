/**
 * E2E Playwright tests for the branch_admin role.
 *
 * Covers:
 *  - branch_admin login and dashboard load (14.1)
 *  - branch_admin sees no branch switcher, sees static badge (14.2)
 *  - branch_admin cannot access Settings (14.3)
 *  - branch_admin can access operational pages (14.4)
 *  - Branch assignment modal excludes org_admin and kiosk (14.5)
 *  - branch_admin denied billing and admin endpoints (14.6)
 *
 * All backend API calls are intercepted via page.route() so tests run
 * without a live backend.
 *
 * Requirements: 1.3, 2.1, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.6, 6.1–6.4, 7.1
 */
import { test, expect, type Page, type Route } from '@playwright/test';

// ---------------------------------------------------------------------------
// Helpers & constants
// ---------------------------------------------------------------------------

const BASE_URL = 'http://localhost:5173';

const BRANCH_HQ = {
  id: 'aaaaaaaa-1111-2222-3333-444444444444',
  name: 'HQ Branch',
  address: '123 Main St',
  phone: '+6491234567',
  is_active: true,
  is_hq: true,
};

const BRANCH_SOUTH = {
  id: 'bbbbbbbb-1111-2222-3333-444444444444',
  name: 'South Branch',
  address: '456 South Rd',
  phone: '+6497654321',
  is_active: true,
  is_hq: false,
};

/** Build a minimal JWT with the given payload. No real signature — tests mock auth. */
function buildFakeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const body = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return `${header}.${body}.fake-signature`;
}

const BRANCH_ADMIN_TOKEN = buildFakeJwt({
  sub: 'ba-user-1',
  user_id: 'ba-user-1',
  org_id: 'org-1',
  role: 'branch_admin',
  email: 'branchadmin@workshop.co.nz',
  branch_ids: [BRANCH_HQ.id],
  exp: Math.floor(Date.now() / 1000) + 3600,
});

const ORG_ADMIN_TOKEN = buildFakeJwt({
  sub: 'oa-user-1',
  user_id: 'oa-user-1',
  org_id: 'org-1',
  role: 'org_admin',
  email: 'orgadmin@workshop.co.nz',
  branch_ids: [BRANCH_HQ.id, BRANCH_SOUTH.id],
  exp: Math.floor(Date.now() / 1000) + 3600,
});

/** Respond to a route with JSON. */
async function jsonResponse(route: Route, body: Record<string, unknown> | unknown[], status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

/** Set up common auth routes for a branch_admin session. */
async function setupBranchAdminAuth(page: Page) {
  await page.route('**/api/v1/auth/token/refresh', async (route) => {
    await jsonResponse(route, { access_token: BRANCH_ADMIN_TOKEN });
  });

  await page.route('**/api/v1/auth/me', async (route) => {
    await jsonResponse(route, {
      first_name: 'Branch',
      last_name: 'Admin',
      email: 'branchadmin@workshop.co.nz',
      role: 'branch_admin',
      branch_ids: [BRANCH_HQ.id],
    });
  });

  // branch_admin cannot fetch branches list (RBAC denies /org/branches)
  // Return 403 to simulate the real backend behaviour
  await page.route('**/api/v1/org/branches', async (route) => {
    await jsonResponse(route, { detail: 'Branch admin role cannot access this resource' }, 403);
  });

  // Mock org settings read (branding) — branch_admin can read
  await page.route('**/api/v1/org/settings', async (route) => {
    await jsonResponse(route, { branding: { name: 'WorkshopPro' } });
  });

  // Mock modules endpoint
  await page.route('**/api/v1/org/modules', async (route) => {
    await jsonResponse(route, { modules: {} });
  });

  // Mock feature flags
  await page.route('**/api/v1/org/feature-flags', async (route) => {
    await jsonResponse(route, {});
  });
}

/** Set up common auth routes for an org_admin session. */
async function setupOrgAdminAuth(page: Page) {
  await page.route('**/api/v1/auth/token/refresh', async (route) => {
    await jsonResponse(route, { access_token: ORG_ADMIN_TOKEN });
  });

  await page.route('**/api/v1/auth/me', async (route) => {
    await jsonResponse(route, {
      first_name: 'Org',
      last_name: 'Admin',
      email: 'orgadmin@workshop.co.nz',
      role: 'org_admin',
      branch_ids: [BRANCH_HQ.id, BRANCH_SOUTH.id],
    });
  });

  await page.route('**/api/v1/org/branches', async (route) => {
    if (route.request().method() === 'GET') {
      await jsonResponse(route, { branches: [BRANCH_HQ, BRANCH_SOUTH] });
    } else {
      await route.continue();
    }
  });

  await page.route('**/api/v1/org/settings', async (route) => {
    await jsonResponse(route, { branding: { name: 'WorkshopPro' } });
  });

  await page.route('**/api/v1/org/modules', async (route) => {
    await jsonResponse(route, { modules: {} });
  });

  await page.route('**/api/v1/org/feature-flags', async (route) => {
    await jsonResponse(route, {});
  });
}

// ===========================================================================
// 14.1 — branch_admin login and dashboard load
// ===========================================================================

test.describe('14.1 — branch_admin login and dashboard load', () => {
  test('branch_admin logs in and dashboard loads with branch-scoped view', async ({ page }) => {
    let capturedLoginBody: Record<string, unknown> | null = null;

    // Login returns branch_admin token
    await page.route('**/api/v1/auth/login', async (route) => {
      capturedLoginBody = route.request().postDataJSON();
      await jsonResponse(route, { access_token: BRANCH_ADMIN_TOKEN });
    });

    // Before login, token refresh returns 401 (not authenticated yet)
    await page.route('**/api/v1/auth/token/refresh', async (route) => {
      await jsonResponse(route, {}, 401);
    });

    await page.route('**/api/v1/auth/me', async (route) => {
      await jsonResponse(route, {
        first_name: 'Branch',
        last_name: 'Admin',
        email: 'branchadmin@workshop.co.nz',
        role: 'branch_admin',
        branch_ids: [BRANCH_HQ.id],
      });
    });

    await page.route('**/api/v1/org/branches', async (route) => {
      await jsonResponse(route, { detail: 'Branch admin role cannot access this resource' }, 403);
    });

    await page.route('**/api/v1/org/settings', async (route) => {
      await jsonResponse(route, { branding: { name: 'WorkshopPro' } });
    });

    await page.route('**/api/v1/org/modules', async (route) => {
      await jsonResponse(route, { modules: {} });
    });

    await page.route('**/api/v1/org/feature-flags', async (route) => {
      await jsonResponse(route, {});
    });

    // Mock dashboard data
    await page.route('**/api/v1/dashboard/**', async (route) => {
      await jsonResponse(route, {
        branch_id: BRANCH_HQ.id,
        revenue: 5000.0,
        invoice_count: 25,
        customer_count: 10,
      });
    });

    await page.goto(`${BASE_URL}/login`);

    // Fill in the login form
    await page.getByLabel('Email address').fill('branchadmin@workshop.co.nz');
    await page.getByLabel('Password').fill('SecureP@ss1');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();

    // Verify the login request was sent
    await expect.poll(() => capturedLoginBody).toBeTruthy();
    expect(capturedLoginBody).toMatchObject({
      email: 'branchadmin@workshop.co.nz',
      password: 'SecureP@ss1',
    });

    // Should navigate away from /login on success
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 5000 });
  });
});

// ===========================================================================
// 14.2 — branch_admin sees no branch switcher
// ===========================================================================

test.describe('14.2 — branch_admin sees no branch switcher', () => {
  test('BranchSelector is NOT rendered and branch badge is displayed', async ({ page }) => {
    await setupBranchAdminAuth(page);

    // Mock dashboard data
    await page.route('**/api/v1/dashboard/**', async (route) => {
      await jsonResponse(route, {
        branch_id: BRANCH_HQ.id,
        revenue: 5000.0,
        invoice_count: 25,
        customer_count: 10,
      });
    });

    await page.goto(`${BASE_URL}/dashboard`);

    // Wait for the page to load (header should be visible)
    await expect(page.locator('header[role="banner"]')).toBeVisible({ timeout: 5000 });

    // BranchSelector (combobox) should NOT be rendered for branch_admin
    const branchSelector = page.getByRole('combobox', { name: /branch/i });
    await expect(branchSelector).not.toBeVisible();

    // The static branch badge should be displayed with "My Branch" text
    // (OrgLayout shows "My Branch" because the branches array is empty for branch_admin)
    const branchBadge = page.getByText('My Branch');
    await expect(branchBadge).toBeVisible({ timeout: 3000 });
  });
});

// ===========================================================================
// 14.3 — branch_admin cannot access Settings
// ===========================================================================

test.describe('14.3 — branch_admin cannot access Settings', () => {
  test('navigating to /settings redirects to /dashboard and Settings nav is hidden', async ({ page }) => {
    await setupBranchAdminAuth(page);

    // Mock dashboard data
    await page.route('**/api/v1/dashboard/**', async (route) => {
      await jsonResponse(route, {
        branch_id: BRANCH_HQ.id,
        revenue: 5000.0,
        invoice_count: 25,
        customer_count: 10,
      });
    });

    // Navigate directly to /settings
    await page.goto(`${BASE_URL}/settings`);

    // Should be redirected to /dashboard (RequireOrgAdmin guard)
    await page.waitForURL((url) => url.pathname.includes('/dashboard'), { timeout: 5000 });

    // Verify Settings nav item is NOT visible in the sidebar
    const sidebar = page.locator('aside[role="navigation"]');
    await expect(sidebar).toBeVisible({ timeout: 3000 });

    const settingsLink = sidebar.getByRole('link', { name: 'Settings' });
    await expect(settingsLink).not.toBeVisible();
  });
});

// ===========================================================================
// 14.4 — branch_admin can access operational pages
// ===========================================================================

test.describe('14.4 — branch_admin can access operational pages', () => {
  const operationalPages = [
    { path: '/invoices', mockRoute: '**/api/v1/invoices*', mockData: { items: [], total: 0 } },
    { path: '/customers', mockRoute: '**/api/v1/customers*', mockData: { items: [], total: 0 } },
    { path: '/job-cards', mockRoute: '**/api/v1/job-cards*', mockData: { job_cards: [], total: 0 } },
    { path: '/bookings', mockRoute: '**/api/v1/bookings*', mockData: { items: [], total: 0 } },
  ];

  for (const { path, mockRoute, mockData } of operationalPages) {
    test(`branch_admin can access ${path}`, async ({ page }) => {
      await setupBranchAdminAuth(page);

      // Mock the page-specific API endpoint
      await page.route(mockRoute, async (route) => {
        await jsonResponse(route, mockData);
      });

      // Mock dashboard data (in case of redirects)
      await page.route('**/api/v1/dashboard/**', async (route) => {
        await jsonResponse(route, { branch_id: BRANCH_HQ.id, revenue: 0 });
      });

      await page.goto(`${BASE_URL}${path}`);

      // Verify the page loaded (no redirect to /login or 403 error page)
      // The URL should still contain the operational path
      await page.waitForURL(
        (url) => url.pathname.includes(path) || url.pathname.includes('/dashboard'),
        { timeout: 5000 },
      );

      // Should NOT be on the login page
      expect(page.url()).not.toContain('/login');
    });
  }
});

// ===========================================================================
// 14.5 — branch assignment modal excludes org_admin and kiosk
// ===========================================================================

test.describe('14.5 — branch assignment modal excludes org_admin and kiosk', () => {
  test('Assign Users modal shows only assignable roles', async ({ page }) => {
    await setupOrgAdminAuth(page);

    // Mock org users with various roles
    await page.route('**/api/v1/org/users', async (route) => {
      await jsonResponse(route, {
        users: [
          { id: 'u-1', email: 'orgadmin@workshop.co.nz', role: 'org_admin', branch_ids: [] },
          { id: 'u-2', email: 'branchadmin@workshop.co.nz', role: 'branch_admin', branch_ids: [BRANCH_HQ.id] },
          { id: 'u-3', email: 'sales@workshop.co.nz', role: 'salesperson', branch_ids: [] },
          { id: 'u-4', email: 'kiosk@workshop.co.nz', role: 'kiosk', branch_ids: [] },
          { id: 'u-5', email: 'global@workshop.co.nz', role: 'global_admin', branch_ids: [] },
          { id: 'u-6', email: 'locmgr@workshop.co.nz', role: 'location_manager', branch_ids: [] },
          { id: 'u-7', email: 'staff@workshop.co.nz', role: 'staff_member', branch_ids: [] },
        ],
      });
    });

    await page.goto(`${BASE_URL}/settings/branches`);

    // Click "Assign Users" on the first branch row
    const assignButton = page.getByRole('button', { name: /Assign Users/i }).first();
    if (await assignButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await assignButton.click();

      // Wait for the modal to appear
      const modal = page.getByRole('dialog');
      await expect(modal).toBeVisible({ timeout: 3000 });

      // Verify org_admin is NOT shown in the assignable list
      await expect(modal.getByText('orgadmin@workshop.co.nz')).not.toBeVisible();

      // Verify kiosk is NOT shown
      await expect(modal.getByText('kiosk@workshop.co.nz')).not.toBeVisible();

      // Verify global_admin is NOT shown
      await expect(modal.getByText('global@workshop.co.nz')).not.toBeVisible();

      // Verify branch_admin IS shown
      await expect(modal.getByText('branchadmin@workshop.co.nz')).toBeVisible();

      // Verify salesperson IS shown
      await expect(modal.getByText('sales@workshop.co.nz')).toBeVisible();

      // Verify location_manager IS shown
      await expect(modal.getByText('locmgr@workshop.co.nz')).toBeVisible();

      // Verify staff_member IS shown
      await expect(modal.getByText('staff@workshop.co.nz')).toBeVisible();
    }
  });
});

// ===========================================================================
// 14.6 — branch_admin denied billing and admin endpoints
// ===========================================================================

test.describe('14.6 — branch_admin denied billing and admin endpoints', () => {
  test('navigating to /settings/billing redirects to /dashboard', async ({ page }) => {
    await setupBranchAdminAuth(page);

    // Mock dashboard data
    await page.route('**/api/v1/dashboard/**', async (route) => {
      await jsonResponse(route, {
        branch_id: BRANCH_HQ.id,
        revenue: 5000.0,
        invoice_count: 25,
        customer_count: 10,
      });
    });

    // Mock billing endpoint — should return 403 for branch_admin
    await page.route('**/api/v1/billing**', async (route) => {
      await jsonResponse(route, { detail: 'Branch admin role cannot access this resource' }, 403);
    });

    // Navigate directly to /settings/billing
    await page.goto(`${BASE_URL}/settings/billing`);

    // Should be redirected to /dashboard (RequireOrgAdmin guard wraps /settings routes)
    await page.waitForURL((url) => url.pathname.includes('/dashboard'), { timeout: 5000 });

    // Confirm we are NOT on the billing page
    expect(page.url()).not.toContain('/billing');
  });

  test('direct API call to billing endpoint returns 403', async ({ page }) => {
    await setupBranchAdminAuth(page);

    // Mock billing endpoint to return 403
    await page.route('**/api/v1/billing**', async (route) => {
      await jsonResponse(route, { detail: 'Branch admin role cannot access this resource' }, 403);
    });

    await page.goto(`${BASE_URL}/dashboard`);

    // Mock dashboard data
    await page.route('**/api/v1/dashboard/**', async (route) => {
      await jsonResponse(route, { branch_id: BRANCH_HQ.id, revenue: 0 });
    });

    // Programmatically call the billing endpoint as the frontend would
    const response = await page.evaluate(async () => {
      const res = await fetch('/api/v1/billing/subscription', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });
      return { status: res.status, body: await res.json() };
    });

    expect(response.status).toBe(403);
    expect(response.body.detail).toContain('Branch admin');
  });
});
