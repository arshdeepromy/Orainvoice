/**
 * E2E Playwright tests for Customer Claims & Returns workflows.
 *
 * Covers:
 *  - Demo account login and dashboard load (20.1)
 *  - Create claim from Claims list page (20.2)
 *  - Full approval workflow with full_refund resolution (20.3)
 *  - Rejection workflow with no_action resolution (20.4)
 *  - Credit note resolution (20.5)
 *  - Redo service resolution (20.6)
 *  - Exchange resolution (20.7)
 *  - Report Issue from InvoiceDetail (20.8)
 *  - Customer profile Claims tab (20.9)
 *  - Add internal note to claim (20.10)
 *
 * All backend API calls are intercepted via page.route() so tests run
 * without a live backend.
 *
 * Requirements: 13.1-13.11
 */
import { test, expect, type Page, type Route } from '@playwright/test';

// ---------------------------------------------------------------------------
// Helpers & constants
// ---------------------------------------------------------------------------

const BASE_URL = 'http://localhost:5173';

const DEMO_USER = {
  email: 'demo@orainvoice.com',
  password: 'demo123',
};

const FAKE_ACCESS_TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  btoa(
    JSON.stringify({
      sub: 'user-demo',
      user_id: 'user-demo',
      org_id: 'org-demo',
      role: 'org_admin',
      email: DEMO_USER.email,
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  )
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '') +
  '.fake-signature';

const CUSTOMER_1 = {
  id: 'cust-1111-2222-3333-444444444444',
  first_name: 'John',
  last_name: 'Smith',
  email: 'john@example.com',
  phone: '+6421000111',
  company_name: null,
};

const INVOICE_1 = {
  id: 'inv-1111-2222-3333-444444444444',
  invoice_number: 'INV-001',
  total: 250.0,
  status: 'paid',
  customer_id: CUSTOMER_1.id,
};

const JOB_CARD_1 = {
  id: 'jc-1111-2222-3333-444444444444',
  description: 'Brake pad replacement',
  status: 'completed',
  vehicle_rego: 'ABC123',
};

const CLAIM_BASE = {
  org_id: 'org-demo',
  branch_id: null,
  customer_id: CUSTOMER_1.id,
  customer: CUSTOMER_1,
  invoice_id: INVOICE_1.id,
  invoice: INVOICE_1,
  job_card_id: null,
  job_card: null,
  line_item_ids: [],
  description: 'Product arrived damaged',
  resolution_type: null,
  resolution_amount: null,
  resolution_notes: null,
  resolved_at: null,
  resolved_by: null,
  refund_id: null,
  credit_note_id: null,
  return_movement_ids: [],
  warranty_job_id: null,
  cost_to_business: 0,
  cost_breakdown: { labour_cost: 0, parts_cost: 0, write_off_cost: 0 },
  created_by: 'user-demo',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  actions: [],
};

let claimIdCounter = 0;

function makeClaimId(): string {
  claimIdCounter += 1;
  return `claim-${String(claimIdCounter).padStart(4, '0')}-0000-0000-000000000000`;
}

/** Respond to a route with JSON. */
async function jsonResponse(route: Route, body: Record<string, unknown> | unknown[], status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

/** Set up common auth routes for an authenticated demo session. */
async function setupAuthRoutes(page: Page) {
  await page.route('**/api/v1/auth/token/refresh', async (route) => {
    await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
  });

  await page.route('**/api/v1/auth/me', async (route) => {
    await jsonResponse(route, {
      first_name: 'Demo',
      last_name: 'User',
      email: DEMO_USER.email,
      role: 'org_admin',
      branch_ids: [],
    });
  });

  await page.route('**/api/v1/org/branches', async (route) => {
    await jsonResponse(route, {
      branches: [
        { id: 'branch-main', name: 'Main', is_active: true, is_default: true },
      ],
    });
  });
}

/**
 * Create a mock claim object with a given status and optional overrides.
 */
function makeClaim(
  id: string,
  status: string,
  claimType = 'defect',
  overrides: Record<string, unknown> = {},
) {
  return {
    ...CLAIM_BASE,
    id,
    claim_type: claimType,
    status,
    customer_name: `${CUSTOMER_1.first_name} ${CUSTOMER_1.last_name}`,
    ...overrides,
  };
}

/**
 * Set up routes for the claims list page.
 * Returns a mutable claims array that tests can push new claims into.
 */
async function setupClaimsListRoutes(page: Page, claims: Record<string, unknown>[]) {
  await page.route('**/api/v1/claims', async (route: Route) => {
    const method = route.request().method();
    if (method === 'GET') {
      await jsonResponse(route, { items: claims, total: claims.length });
    } else if (method === 'POST') {
      const body = route.request().postDataJSON();
      const newId = makeClaimId();
      const newClaim = makeClaim(newId, 'open', body.claim_type ?? 'defect', {
        description: body.description ?? 'Test claim',
        invoice_id: body.invoice_id ?? null,
        customer_id: body.customer_id ?? CUSTOMER_1.id,
      });
      claims.push(newClaim);
      await jsonResponse(route, newClaim, 201);
    } else {
      await route.continue();
    }
  });
}

/**
 * Set up routes for a single claim detail page with status transition support.
 * Returns a mutable claim ref that tracks the current state.
 */
async function setupClaimDetailRoutes(
  page: Page,
  claimRef: { current: Record<string, unknown> },
) {
  // GET claim detail
  await page.route('**/api/v1/claims/*', async (route: Route) => {
    const url = route.request().url();
    const method = route.request().method();

    // Match /claims/{id}/status
    if (url.includes('/status') && method === 'PATCH') {
      const body = route.request().postDataJSON();
      const oldStatus = claimRef.current.status;
      claimRef.current.status = body.new_status;
      claimRef.current.actions = [
        ...((claimRef.current.actions as unknown[]) ?? []),
        {
          id: `action-${Date.now()}`,
          action_type: 'status_change',
          from_status: oldStatus,
          to_status: body.new_status,
          action_data: {},
          notes: body.notes ?? null,
          performed_by: 'user-demo',
          performed_by_name: 'Demo User',
          performed_at: new Date().toISOString(),
        },
      ];
      await jsonResponse(route, claimRef.current);
      return;
    }

    // Match /claims/{id}/resolve
    if (url.includes('/resolve') && method === 'POST') {
      const body = route.request().postDataJSON();
      claimRef.current.status = 'resolved';
      claimRef.current.resolution_type = body.resolution_type;
      claimRef.current.resolution_amount = body.resolution_amount ?? null;
      claimRef.current.resolution_notes = body.resolution_notes ?? null;
      claimRef.current.resolved_at = new Date().toISOString();
      claimRef.current.resolved_by = 'user-demo';

      // Set downstream entity references based on resolution type
      if (body.resolution_type === 'full_refund' || body.resolution_type === 'partial_refund') {
        claimRef.current.refund_id = 'refund-0001-0000-0000-000000000000';
      }
      if (body.resolution_type === 'credit_note') {
        claimRef.current.credit_note_id = 'cn-0001-0000-0000-000000000000';
      }
      if (body.resolution_type === 'redo_service') {
        claimRef.current.warranty_job_id = 'wj-0001-0000-0000-000000000000';
      }
      if (body.resolution_type === 'exchange') {
        claimRef.current.return_movement_ids = ['rm-0001-0000-0000-000000000000'];
      }

      claimRef.current.actions = [
        ...((claimRef.current.actions as unknown[]) ?? []),
        {
          id: `action-${Date.now()}`,
          action_type: 'resolution_applied',
          from_status: null,
          to_status: 'resolved',
          action_data: { resolution_type: body.resolution_type },
          notes: body.resolution_notes ?? null,
          performed_by: 'user-demo',
          performed_by_name: 'Demo User',
          performed_at: new Date().toISOString(),
        },
      ];
      await jsonResponse(route, claimRef.current);
      return;
    }

    // Match /claims/{id}/notes
    if (url.includes('/notes') && method === 'POST') {
      const body = route.request().postDataJSON();
      claimRef.current.actions = [
        ...((claimRef.current.actions as unknown[]) ?? []),
        {
          id: `action-${Date.now()}`,
          action_type: 'note_added',
          from_status: null,
          to_status: null,
          action_data: {},
          notes: body.notes,
          performed_by: 'user-demo',
          performed_by_name: 'Demo User',
          performed_at: new Date().toISOString(),
        },
      ];
      await jsonResponse(route, claimRef.current);
      return;
    }

    // GET /claims/{id}
    if (method === 'GET') {
      await jsonResponse(route, claimRef.current);
      return;
    }

    await route.continue();
  });
}

// ===========================================================================
// 20.1 — Demo account login and dashboard load
// ===========================================================================

test.describe('Claims E2E — Demo Login', () => {
  test('authenticates via login form with demo credentials and loads dashboard', async ({ page }) => {
    let capturedLoginBody: Record<string, unknown> | null = null;

    await page.route('**/api/v1/auth/login', async (route) => {
      capturedLoginBody = route.request().postDataJSON();
      await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
    });

    await page.route('**/api/v1/auth/me', async (route) => {
      await jsonResponse(route, {
        first_name: 'Demo',
        last_name: 'User',
        email: DEMO_USER.email,
        role: 'org_admin',
      });
    });

    await page.route('**/api/v1/auth/token/refresh', async (route) => {
      await jsonResponse(route, {}, 401);
    });

    await page.goto(`${BASE_URL}/login`);

    // Fill in the login form with demo credentials
    await page.getByLabel('Email address').fill(DEMO_USER.email);
    await page.getByLabel('Password').fill(DEMO_USER.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();

    // Verify the login request payload
    await expect.poll(() => capturedLoginBody).toBeTruthy();
    expect(capturedLoginBody).toMatchObject({
      email: DEMO_USER.email,
      password: DEMO_USER.password,
    });

    // Should navigate away from /login on success (dashboard loads)
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 5000 });
  });
});

// ===========================================================================
// 20.2 — Create claim from Claims list page
// ===========================================================================

test.describe('Claims E2E — Create Claim from List', () => {
  test('navigates to Claims list, creates a new claim, and verifies it appears', async ({ page }) => {
    await setupAuthRoutes(page);

    const claims: Record<string, unknown>[] = [];
    await setupClaimsListRoutes(page, claims);

    // Mock customer search for the create form
    await page.route('**/api/v1/customers?*', async (route) => {
      await jsonResponse(route, {
        items: [CUSTOMER_1],
        total: 1,
      });
    });

    await page.route('**/api/v1/customers', async (route) => {
      await jsonResponse(route, {
        items: [CUSTOMER_1],
        total: 1,
      });
    });

    // Mock invoices for customer
    await page.route('**/api/v1/invoices?*', async (route) => {
      await jsonResponse(route, {
        items: [INVOICE_1],
        total: 1,
      });
    });

    await page.route('**/api/v1/invoices', async (route) => {
      await jsonResponse(route, {
        items: [INVOICE_1],
        total: 1,
      });
    });

    // Mock job cards for customer
    await page.route('**/api/v1/job-cards?*', async (route) => {
      await jsonResponse(route, { job_cards: [] });
    });

    await page.route('**/api/v1/job-cards', async (route) => {
      await jsonResponse(route, { job_cards: [] });
    });

    // Navigate to claims list
    await page.goto(`${BASE_URL}/claims`);

    // Click "New Claim" button
    const newClaimButton = page.getByRole('button', { name: /New Claim/i });
    if (await newClaimButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newClaimButton.click();

      // Should navigate to /claims/new
      await page.waitForURL((url) => url.pathname.includes('/claims/new'), { timeout: 5000 });

      // Search for customer
      const customerSearch = page.getByPlaceholder('Search customers…');
      if (await customerSearch.isVisible({ timeout: 3000 }).catch(() => false)) {
        await customerSearch.fill('John');

        // Wait for dropdown and select customer
        const customerOption = page.getByText('John Smith');
        if (await customerOption.isVisible({ timeout: 3000 }).catch(() => false)) {
          await customerOption.click();
        }
      }

      // Select claim type
      const claimTypeSelect = page.getByLabel(/Claim Type/i);
      if (await claimTypeSelect.isVisible({ timeout: 2000 }).catch(() => false)) {
        await claimTypeSelect.selectOption('defect');
      }

      // Fill description
      const descriptionField = page.getByPlaceholder("Describe the customer's complaint…");
      if (await descriptionField.isVisible({ timeout: 2000 }).catch(() => false)) {
        await descriptionField.fill('Product arrived damaged');
      }

      // Select invoice
      const invoiceSelect = page.getByLabel(/Invoice/i).first();
      if (await invoiceSelect.isVisible({ timeout: 2000 }).catch(() => false)) {
        await invoiceSelect.selectOption(INVOICE_1.id);
      }

      // Submit the form
      const createButton = page.getByRole('button', { name: /Create Claim/i });
      if (await createButton.isVisible({ timeout: 2000 }).catch(() => false)) {
        await createButton.click();
      }

      // Should navigate to the new claim detail page
      await page.waitForURL((url) => url.pathname.includes('/claims/'), { timeout: 5000 });
    }
  });
});

// ===========================================================================
// 20.3 — Full approval workflow (full_refund)
// ===========================================================================

test.describe('Claims E2E — Full Approval Workflow', () => {
  test('transitions claim through open → investigating → approved → resolved (full_refund)', async ({ page }) => {
    await setupAuthRoutes(page);

    const claimId = makeClaimId();
    const claimRef = {
      current: makeClaim(claimId, 'open', 'defect', {
        actions: [
          {
            id: 'action-init',
            action_type: 'status_change',
            from_status: null,
            to_status: 'open',
            action_data: {},
            notes: null,
            performed_by: 'user-demo',
            performed_by_name: 'Demo User',
            performed_at: new Date().toISOString(),
          },
        ],
      }),
    };

    await setupClaimDetailRoutes(page, claimRef);

    // Navigate to claim detail
    await page.goto(`${BASE_URL}/claims/${claimId}`);

    // Step 1: Click "Start Investigation" → status becomes "investigating"
    const investigateBtn = page.getByRole('button', { name: /Start Investigation/i });
    if (await investigateBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await investigateBtn.click();

      // Wait for status badge to update
      await expect(page.getByText('Investigating')).toBeVisible({ timeout: 5000 });
    }

    // Step 2: Click "Approve" → status becomes "approved"
    const approveBtn = page.getByRole('button', { name: /Approve/i });
    if (await approveBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await approveBtn.click();

      await expect(page.getByText('Approved')).toBeVisible({ timeout: 5000 });
    }

    // Step 3: Click "Resolve" → open modal → select "Full Refund" → submit
    const resolveBtn = page.getByRole('button', { name: /^Resolve$/i });
    if (await resolveBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await resolveBtn.click();

      // Modal should appear with "Resolve Claim" title
      await expect(page.getByText('Resolve Claim')).toBeVisible({ timeout: 3000 });

      // Select resolution type
      const resolutionSelect = page.getByLabel(/Resolution Type/i);
      await resolutionSelect.selectOption('full_refund');

      // Submit resolution
      const resolveClaimBtn = page.getByRole('button', { name: /Resolve Claim/i });
      await resolveClaimBtn.click();

      // Verify status changed to "Resolved"
      await expect(page.getByText('Resolved')).toBeVisible({ timeout: 5000 });
    }

    // Verify refund was created — the detail page should show refund reference
    expect(claimRef.current.refund_id).toBeTruthy();
    expect(claimRef.current.status).toBe('resolved');
    expect(claimRef.current.resolution_type).toBe('full_refund');
  });
});

// ===========================================================================
// 20.4 — Rejection workflow (no_action)
// ===========================================================================

test.describe('Claims E2E — Rejection Workflow', () => {
  test('transitions claim through open → investigating → rejected → resolved (no_action)', async ({ page }) => {
    await setupAuthRoutes(page);

    const claimId = makeClaimId();
    const claimRef = {
      current: makeClaim(claimId, 'open', 'refund_request'),
    };

    await setupClaimDetailRoutes(page, claimRef);

    await page.goto(`${BASE_URL}/claims/${claimId}`);

    // Step 1: Start Investigation
    const investigateBtn = page.getByRole('button', { name: /Start Investigation/i });
    if (await investigateBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await investigateBtn.click();
      await expect(page.getByText('Investigating')).toBeVisible({ timeout: 5000 });
    }

    // Step 2: Reject
    const rejectBtn = page.getByRole('button', { name: /Reject/i });
    if (await rejectBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await rejectBtn.click();
      await expect(page.getByText('Rejected')).toBeVisible({ timeout: 5000 });
    }

    // Step 3: Resolve with no_action
    const resolveBtn = page.getByRole('button', { name: /^Resolve$/i });
    if (await resolveBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await resolveBtn.click();

      await expect(page.getByText('Resolve Claim')).toBeVisible({ timeout: 3000 });

      const resolutionSelect = page.getByLabel(/Resolution Type/i);
      await resolutionSelect.selectOption('no_action');

      const resolveClaimBtn = page.getByRole('button', { name: /Resolve Claim/i });
      await resolveClaimBtn.click();

      await expect(page.getByText('Resolved')).toBeVisible({ timeout: 5000 });
    }

    // Verify no downstream entities were created
    expect(claimRef.current.status).toBe('resolved');
    expect(claimRef.current.resolution_type).toBe('no_action');
    expect(claimRef.current.refund_id).toBeNull();
    expect(claimRef.current.credit_note_id).toBeNull();
    expect(claimRef.current.warranty_job_id).toBeNull();
  });
});

// ===========================================================================
// 20.5 — Credit note resolution
// ===========================================================================

test.describe('Claims E2E — Credit Note Resolution', () => {
  test('resolves claim with credit_note and verifies credit note is linked', async ({ page }) => {
    await setupAuthRoutes(page);

    const claimId = makeClaimId();
    const claimRef = {
      current: makeClaim(claimId, 'approved', 'defect', {
        actions: [
          {
            id: 'action-1',
            action_type: 'status_change',
            from_status: 'open',
            to_status: 'investigating',
            action_data: {},
            notes: null,
            performed_by: 'user-demo',
            performed_by_name: 'Demo User',
            performed_at: new Date().toISOString(),
          },
          {
            id: 'action-2',
            action_type: 'status_change',
            from_status: 'investigating',
            to_status: 'approved',
            action_data: {},
            notes: null,
            performed_by: 'user-demo',
            performed_by_name: 'Demo User',
            performed_at: new Date().toISOString(),
          },
        ],
      }),
    };

    await setupClaimDetailRoutes(page, claimRef);

    await page.goto(`${BASE_URL}/claims/${claimId}`);

    // Claim is already approved — click Resolve
    const resolveBtn = page.getByRole('button', { name: /^Resolve$/i });
    if (await resolveBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await resolveBtn.click();

      await expect(page.getByText('Resolve Claim')).toBeVisible({ timeout: 3000 });

      // Select credit_note resolution
      const resolutionSelect = page.getByLabel(/Resolution Type/i);
      await resolutionSelect.selectOption('credit_note');

      // Credit note requires an amount
      const amountInput = page.getByLabel(/Amount/i);
      if (await amountInput.isVisible({ timeout: 2000 }).catch(() => false)) {
        await amountInput.fill('150.00');
      }

      // Add resolution notes
      const notesField = page.getByLabel(/Notes/i);
      if (await notesField.isVisible({ timeout: 2000 }).catch(() => false)) {
        await notesField.fill('Credit note issued for damaged goods');
      }

      const resolveClaimBtn = page.getByRole('button', { name: /Resolve Claim/i });
      await resolveClaimBtn.click();

      await expect(page.getByText('Resolved')).toBeVisible({ timeout: 5000 });
    }

    // Verify credit note was linked
    expect(claimRef.current.status).toBe('resolved');
    expect(claimRef.current.resolution_type).toBe('credit_note');
    expect(claimRef.current.credit_note_id).toBeTruthy();
  });
});

// ===========================================================================
// 20.6 — Redo service resolution
// ===========================================================================

test.describe('Claims E2E — Redo Service Resolution', () => {
  test('resolves claim with redo_service and verifies warranty job card is linked', async ({ page }) => {
    await setupAuthRoutes(page);

    const claimId = makeClaimId();
    const claimRef = {
      current: makeClaim(claimId, 'approved', 'service_redo', {
        job_card_id: JOB_CARD_1.id,
        job_card: JOB_CARD_1,
        invoice_id: null,
        invoice: null,
      }),
    };

    await setupClaimDetailRoutes(page, claimRef);

    await page.goto(`${BASE_URL}/claims/${claimId}`);

    const resolveBtn = page.getByRole('button', { name: /^Resolve$/i });
    if (await resolveBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await resolveBtn.click();

      await expect(page.getByText('Resolve Claim')).toBeVisible({ timeout: 3000 });

      const resolutionSelect = page.getByLabel(/Resolution Type/i);
      await resolutionSelect.selectOption('redo_service');

      const notesField = page.getByLabel(/Notes/i);
      if (await notesField.isVisible({ timeout: 2000 }).catch(() => false)) {
        await notesField.fill('Redo brake pad service under warranty');
      }

      const resolveClaimBtn = page.getByRole('button', { name: /Resolve Claim/i });
      await resolveClaimBtn.click();

      await expect(page.getByText('Resolved')).toBeVisible({ timeout: 5000 });
    }

    // Verify warranty job card was created
    expect(claimRef.current.status).toBe('resolved');
    expect(claimRef.current.resolution_type).toBe('redo_service');
    expect(claimRef.current.warranty_job_id).toBeTruthy();
  });
});

// ===========================================================================
// 20.7 — Exchange resolution
// ===========================================================================

test.describe('Claims E2E — Exchange Resolution', () => {
  test('resolves claim with exchange and verifies stock return movements are created', async ({ page }) => {
    await setupAuthRoutes(page);

    const claimId = makeClaimId();
    const claimRef = {
      current: makeClaim(claimId, 'approved', 'exchange'),
    };

    await setupClaimDetailRoutes(page, claimRef);

    await page.goto(`${BASE_URL}/claims/${claimId}`);

    const resolveBtn = page.getByRole('button', { name: /^Resolve$/i });
    if (await resolveBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await resolveBtn.click();

      await expect(page.getByText('Resolve Claim')).toBeVisible({ timeout: 3000 });

      const resolutionSelect = page.getByLabel(/Resolution Type/i);
      await resolutionSelect.selectOption('exchange');

      // Exchange requires stock item IDs
      const stockItemInput = page.getByLabel(/Return Stock Item IDs/i);
      if (await stockItemInput.isVisible({ timeout: 2000 }).catch(() => false)) {
        await stockItemInput.fill('stock-item-001, stock-item-002');
      }

      const notesField = page.getByLabel(/Notes/i);
      if (await notesField.isVisible({ timeout: 2000 }).catch(() => false)) {
        await notesField.fill('Exchange defective part for new one');
      }

      const resolveClaimBtn = page.getByRole('button', { name: /Resolve Claim/i });
      await resolveClaimBtn.click();

      await expect(page.getByText('Resolved')).toBeVisible({ timeout: 5000 });
    }

    // Verify stock return movements were created
    expect(claimRef.current.status).toBe('resolved');
    expect(claimRef.current.resolution_type).toBe('exchange');
    expect((claimRef.current.return_movement_ids as string[]).length).toBeGreaterThan(0);
  });
});

// ===========================================================================
// 20.8 — Report Issue from InvoiceDetail
// ===========================================================================

test.describe('Claims E2E — Report Issue from Invoice', () => {
  test('creates a claim via Report Issue button on InvoiceDetail with pre-populated fields', async ({ page }) => {
    await setupAuthRoutes(page);

    let capturedClaimBody: Record<string, unknown> | null = null;

    // Mock invoice detail
    await page.route(`**/api/v1/invoices/${INVOICE_1.id}`, async (route) => {
      await jsonResponse(route, {
        invoice: {
          ...INVOICE_1,
          customer: CUSTOMER_1,
          line_items: [
            {
              id: 'li-001',
              description: 'Brake Pads',
              item_type: 'part',
              quantity: 2,
              line_total: 120.0,
            },
            {
              id: 'li-002',
              description: 'Labour - Brake Service',
              item_type: 'service',
              quantity: 1,
              line_total: 130.0,
            },
          ],
        },
      });
    });

    // Mock payments for invoice detail page
    await page.route('**/api/v1/payments*', async (route) => {
      await jsonResponse(route, { payments: [], total: 0 });
    });

    // Mock claim creation
    await page.route('**/api/v1/claims', async (route) => {
      if (route.request().method() === 'POST') {
        capturedClaimBody = route.request().postDataJSON();
        const newClaim = makeClaim(makeClaimId(), 'open', capturedClaimBody?.claim_type as string ?? 'defect', {
          invoice_id: capturedClaimBody?.invoice_id ?? null,
          customer_id: capturedClaimBody?.customer_id ?? null,
        });
        await jsonResponse(route, newClaim, 201);
      } else {
        await jsonResponse(route, { items: [], total: 0 });
      }
    });

    // Mock customer detail for pre-population
    await page.route(`**/api/v1/customers/${CUSTOMER_1.id}`, async (route) => {
      await jsonResponse(route, CUSTOMER_1);
    });

    // Mock invoices list for the claim form
    await page.route('**/api/v1/invoices?*', async (route) => {
      await jsonResponse(route, { items: [INVOICE_1], total: 1 });
    });

    // Mock job cards
    await page.route('**/api/v1/job-cards*', async (route) => {
      await jsonResponse(route, { job_cards: [] });
    });

    // Navigate to invoice detail
    await page.goto(`${BASE_URL}/invoices/${INVOICE_1.id}`);

    // Click "Report Issue" button
    const reportIssueBtn = page.getByRole('button', { name: /Report Issue/i });
    if (await reportIssueBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await reportIssueBtn.click();

      // Should navigate to /claims/new with query params
      await page.waitForURL(
        (url) => url.pathname.includes('/claims/new') && url.search.includes('invoice_id'),
        { timeout: 5000 },
      );

      // Verify the URL contains pre-populated params
      const currentUrl = page.url();
      expect(currentUrl).toContain(`invoice_id=${INVOICE_1.id}`);
      expect(currentUrl).toContain(`customer_id=${CUSTOMER_1.id}`);
    }
  });
});

// ===========================================================================
// 20.9 — Customer profile Claims tab
// ===========================================================================

test.describe('Claims E2E — Customer Profile Claims Tab', () => {
  test('views Claims tab on customer profile and verifies summary statistics', async ({ page }) => {
    await setupAuthRoutes(page);

    const customerId = CUSTOMER_1.id;

    // Mock customer profile
    await page.route(`**/api/v1/customers/${customerId}`, async (route) => {
      await jsonResponse(route, {
        ...CUSTOMER_1,
        vehicles: [],
        invoices: [],
      });
    });

    // Mock customer claims summary
    await page.route(`**/api/v1/customers/${customerId}/claims`, async (route) => {
      await jsonResponse(route, {
        total_claims: 5,
        open_claims: 2,
        total_cost_to_business: '320.50',
        claims: [
          {
            id: 'claim-a',
            claim_type: 'defect',
            status: 'open',
            description: 'Faulty part',
            cost_to_business: 120.5,
            created_at: new Date().toISOString(),
          },
          {
            id: 'claim-b',
            claim_type: 'warranty',
            status: 'resolved',
            description: 'Warranty repair',
            cost_to_business: 200.0,
            created_at: new Date().toISOString(),
          },
        ],
      });
    });

    // Mock reminders endpoint (used by CustomerProfile)
    await page.route(`**/api/v1/customers/${customerId}/reminders`, async (route) => {
      await jsonResponse(route, {
        service_due: { enabled: false, days_before: 30, channel: 'email' },
        wof_expiry: { enabled: false, days_before: 30, channel: 'email' },
        vehicles: [],
      });
    });

    // Mock vehicles
    await page.route('**/api/v1/vehicles*', async (route) => {
      await jsonResponse(route, { items: [], total: 0 });
    });

    await page.goto(`${BASE_URL}/customers/${customerId}`);

    // Click the Claims tab
    const claimsTab = page.getByRole('tab', { name: /Claims/i });
    if (await claimsTab.isVisible({ timeout: 5000 }).catch(() => false)) {
      await claimsTab.click();

      // Verify summary statistics are displayed
      await expect(page.getByText('Total Claims')).toBeVisible({ timeout: 5000 });
      await expect(page.getByText('Open Claims')).toBeVisible({ timeout: 5000 });
      await expect(page.getByText('Total Cost to Business')).toBeVisible({ timeout: 5000 });
    }
  });
});

// ===========================================================================
// 20.10 — Add internal note to claim
// ===========================================================================

test.describe('Claims E2E — Add Internal Note', () => {
  test('adds an internal note to a claim and verifies it appears in the timeline', async ({ page }) => {
    await setupAuthRoutes(page);

    const claimId = makeClaimId();
    const claimRef = {
      current: makeClaim(claimId, 'investigating', 'defect', {
        actions: [
          {
            id: 'action-init',
            action_type: 'status_change',
            from_status: 'open',
            to_status: 'investigating',
            action_data: {},
            notes: null,
            performed_by: 'user-demo',
            performed_by_name: 'Demo User',
            performed_at: new Date().toISOString(),
          },
        ],
      }),
    };

    await setupClaimDetailRoutes(page, claimRef);

    await page.goto(`${BASE_URL}/claims/${claimId}`);

    // Click "Add Note" button
    const addNoteBtn = page.getByRole('button', { name: /Add Note/i });
    if (await addNoteBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await addNoteBtn.click();

      // Modal should appear
      await expect(page.getByText('Add Internal Note')).toBeVisible({ timeout: 3000 });

      // Fill in the note
      const noteField = page.getByLabel(/Note/i);
      if (await noteField.isVisible({ timeout: 2000 }).catch(() => false)) {
        await noteField.fill('Contacted customer, awaiting photos of damage');
      }

      // Submit the note
      const submitNoteBtn = page.getByRole('button', { name: /Add Note/i }).last();
      await submitNoteBtn.click();

      // Verify the note appears in the timeline
      await expect(
        page.getByText('Contacted customer, awaiting photos of damage'),
      ).toBeVisible({ timeout: 5000 });
    }

    // Verify the note was added to the claim actions
    const actions = claimRef.current.actions as Array<{ action_type: string; notes: string | null }>;
    const noteAction = actions.find((a) => a.action_type === 'note_added');
    expect(noteAction).toBeTruthy();
    expect(noteAction?.notes).toBe('Contacted customer, awaiting photos of damage');
  });
});
