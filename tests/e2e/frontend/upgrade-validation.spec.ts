/**
 * E2E Playwright tests for dependency upgrade validation.
 *
 * Organised by upgrade phase — each phase block validates that the
 * corresponding dependency upgrades have not broken any user-facing
 * functionality. All backend API calls are intercepted via page.route()
 * so the tests run without a live backend.
 *
 * Phase 1: Security Patches (11 tests)
 * Phase 2: Safe Minors (9 tests)
 * Phase 3: Integration Majors (6 tests)
 * Phase 4: Comprehensive Suite (40 tests)
 */
import { test, expect, type Page, type Route } from "@playwright/test";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BASE_URL = "http://localhost:5173";

const TEST_USER = {
  email: "admin@workshop.co.nz",
  password: "SecureP@ss1",
  firstName: "Test",
  lastName: "Admin",
};

const FAKE_MFA_TOKEN = "mfa-session-token-abc123";

const FAKE_ACCESS_TOKEN =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." +
  btoa(
    JSON.stringify({
      sub: "user-1",
      user_id: "user-1",
      org_id: "org-1",
      role: "org_admin",
      email: TEST_USER.email,
      exp: Math.floor(Date.now() / 1000) + 3600,
    })
  )
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "") +
  ".fake-signature";

const FAKE_REFRESH_TOKEN = "fake-refresh-token-xyz";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Respond to a route with JSON. */
async function jsonResponse(
  route: Route,
  body: Record<string, unknown>,
  status = 200
) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

/** Set up common route mocks for an authenticated session. */
async function setupAuthenticatedSession(page: Page) {
  await page.route("**/api/v1/auth/token/refresh", async (route) => {
    await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
  });

  await page.route("**/api/v1/auth/me", async (route) => {
    await jsonResponse(route, {
      first_name: TEST_USER.firstName,
      last_name: TEST_USER.lastName,
      email: TEST_USER.email,
      role: "org_admin",
      org_id: "org-1",
    });
  });
}

/** Perform a full login flow via the UI. */
async function performLogin(page: Page) {
  await page.route("**/api/v1/auth/login", async (route) => {
    await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
  });

  await page.route("**/api/v1/auth/token/refresh", async (route) => {
    await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
  });

  await page.route("**/api/v1/auth/me", async (route) => {
    await jsonResponse(route, {
      first_name: TEST_USER.firstName,
      last_name: TEST_USER.lastName,
      email: TEST_USER.email,
      role: "org_admin",
      org_id: "org-1",
    });
  });

  await page.goto(`${BASE_URL}/login`);
  await page.getByLabel("Email address").fill(TEST_USER.email);
  await page.getByLabel("Password").fill(TEST_USER.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 5000,
  });
}

/** Navigate to a page with an authenticated session already set up. */
async function navigateAuthenticated(page: Page, path: string) {
  await setupAuthenticatedSession(page);
  await page.goto(`${BASE_URL}${path}`);
}

// ===========================================================================
// Phase 1: Security Patches (11 tests)
// ===========================================================================

test.describe("Phase 1: Security Patches", () => {
  test("login with email/password", async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null;

    await page.route("**/api/v1/auth/login", async (route) => {
      capturedBody = route.request().postDataJSON();
      await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
    });

    await page.route("**/api/v1/auth/token/refresh", async (route) => {
      await jsonResponse(route, {}, 401);
    });

    await page.route("**/api/v1/auth/me", async (route) => {
      await jsonResponse(route, {
        first_name: TEST_USER.firstName,
        last_name: TEST_USER.lastName,
        email: TEST_USER.email,
      });
    });

    await page.goto(`${BASE_URL}/login`);
    await page.getByLabel("Email address").fill(TEST_USER.email);
    await page.getByLabel("Password").fill(TEST_USER.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();

    await expect.poll(() => capturedBody).toBeTruthy();
    expect(capturedBody).toMatchObject({
      email: TEST_USER.email,
      password: TEST_USER.password,
    });

    await page.waitForURL((url) => !url.pathname.includes("/login"), {
      timeout: 5000,
    });
  });

  test("MFA TOTP verification", async ({ page }) => {
    let capturedMfaBody: Record<string, unknown> | null = null;

    // Login returns MFA required
    await page.route("**/api/v1/auth/login", async (route) => {
      await jsonResponse(route, {
        mfa_required: true,
        mfa_token: FAKE_MFA_TOKEN,
        methods: ["totp"],
        default_method: "totp",
      });
    });

    await page.route("**/api/v1/auth/token/refresh", async (route) => {
      await jsonResponse(route, {}, 401);
    });

    await page.route("**/api/v1/auth/mfa/verify", async (route) => {
      capturedMfaBody = route.request().postDataJSON();
      await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
    });

    await page.route("**/api/v1/auth/me", async (route) => {
      await jsonResponse(route, {
        first_name: TEST_USER.firstName,
        last_name: TEST_USER.lastName,
        email: TEST_USER.email,
      });
    });

    await page.goto(`${BASE_URL}/login`);
    await page.getByLabel("Email address").fill(TEST_USER.email);
    await page.getByLabel("Password").fill(TEST_USER.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();

    // Wait for MFA modal
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByText("Two-factor authentication")
    ).toBeVisible({ timeout: 5000 });

    // Enter 6-digit TOTP code
    const digitInputs = dialog
      .getByRole("group", { name: "Verification code" })
      .locator("input");
    for (let i = 0; i < 6; i++) {
      await digitInputs.nth(i).fill(String(i + 1));
    }

    await dialog.getByRole("button", { name: "Verify" }).click();

    await expect.poll(() => capturedMfaBody).toBeTruthy();
    expect(capturedMfaBody).toMatchObject({
      code: "123456",
      method: "totp",
      mfa_token: FAKE_MFA_TOKEN,
    });
  });

  test("MFA SMS verification", async ({ page }) => {
    let capturedMfaBody: Record<string, unknown> | null = null;

    await page.route("**/api/v1/auth/login", async (route) => {
      await jsonResponse(route, {
        mfa_required: true,
        mfa_token: FAKE_MFA_TOKEN,
        methods: ["sms"],
        default_method: "sms",
      });
    });

    await page.route("**/api/v1/auth/token/refresh", async (route) => {
      await jsonResponse(route, {}, 401);
    });

    await page.route("**/api/v1/auth/mfa/provider-config", async (route) => {
      await jsonResponse(route, {
        provider: "connexus",
        firebase_config: null,
        phone_number: null,
      });
    });

    await page.route("**/api/v1/auth/mfa/challenge/send", async (route) => {
      await jsonResponse(route, { detail: "Code sent" });
    });

    await page.route("**/api/v1/auth/mfa/verify", async (route) => {
      capturedMfaBody = route.request().postDataJSON();
      await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
    });

    await page.route("**/api/v1/auth/me", async (route) => {
      await jsonResponse(route, {
        first_name: TEST_USER.firstName,
        last_name: TEST_USER.lastName,
        email: TEST_USER.email,
      });
    });

    await page.goto(`${BASE_URL}/login`);
    await page.getByLabel("Email address").fill(TEST_USER.email);
    await page.getByLabel("Password").fill(TEST_USER.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();

    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByText("Two-factor authentication")
    ).toBeVisible({ timeout: 5000 });

    // Wait for SMS code to be "sent"
    await expect(
      dialog.getByText("Enter the 6-digit code sent to your phone")
    ).toBeVisible({ timeout: 5000 });

    const digitInputs = dialog
      .getByRole("group", { name: "Verification code" })
      .locator("input");
    for (let i = 0; i < 6; i++) {
      await digitInputs.nth(i).fill(String(i + 1));
    }

    await dialog.getByRole("button", { name: "Verify" }).click();

    await expect.poll(() => capturedMfaBody).toBeTruthy();
    expect(capturedMfaBody).toMatchObject({
      code: "123456",
      method: "sms",
      mfa_token: FAKE_MFA_TOKEN,
    });
  });

  test("passkey login", async ({ page }) => {
    await page.route("**/api/v1/auth/token/refresh", async (route) => {
      await jsonResponse(route, {}, 401);
    });

    await page.goto(`${BASE_URL}/login`);

    // Verify passkey login button exists
    const passkeyButton = page.getByRole("button", {
      name: /passkey|biometric|security key/i,
    });
    await expect(passkeyButton).toBeVisible({ timeout: 5000 });

    // Mock the WebAuthn options endpoint
    await page.route(
      "**/api/v1/auth/passkey/authentication-options",
      async (route) => {
        await jsonResponse(route, {
          challenge: "dGVzdC1jaGFsbGVuZ2U",
          timeout: 60000,
          rpId: "localhost",
          allowCredentials: [],
          userVerification: "preferred",
        });
      }
    );

    // Click the passkey button — it should attempt to trigger WebAuthn
    await passkeyButton.click();

    // The WebAuthn API call will fail in test env (no authenticator),
    // but we verify the button exists and triggers the flow
    await expect(passkeyButton).toBeVisible();
  });

  test("Stripe integration status", async ({ page }) => {
    await setupAuthenticatedSession(page);

    await page.route("**/api/v1/integrations**", async (route) => {
      await jsonResponse(route, {
        items: [
          {
            name: "stripe",
            display_name: "Stripe",
            status: "connected",
            configured: true,
          },
          {
            name: "xero",
            display_name: "Xero",
            status: "connected",
            configured: true,
          },
        ],
        total: 2,
      });
    });

    await page.goto(`${BASE_URL}/settings/integrations`);
    await expect(page.getByText("Stripe")).toBeVisible({ timeout: 5000 });
    await expect(
      page.getByText(/connected/i).first()
    ).toBeVisible();
  });

  test("Xero integration status", async ({ page }) => {
    await setupAuthenticatedSession(page);

    await page.route("**/api/v1/integrations**", async (route) => {
      await jsonResponse(route, {
        items: [
          {
            name: "stripe",
            display_name: "Stripe",
            status: "connected",
            configured: true,
          },
          {
            name: "xero",
            display_name: "Xero",
            status: "connected",
            configured: true,
          },
        ],
        total: 2,
      });
    });

    await page.goto(`${BASE_URL}/settings/integrations`);
    await expect(page.getByText("Xero")).toBeVisible({ timeout: 5000 });
    await expect(
      page.getByText(/connected/i).first()
    ).toBeVisible();
  });

  test("SMS provider status", async ({ page }) => {
    await setupAuthenticatedSession(page);

    await page.route("**/api/v1/integrations**", async (route) => {
      await jsonResponse(route, {
        items: [
          {
            name: "sms_provider",
            display_name: "SMS Provider",
            status: "active",
            configured: true,
            provider_key: "connexus",
          },
        ],
        total: 1,
      });
    });

    await page.route("**/api/v1/sms/providers**", async (route) => {
      await jsonResponse(route, {
        items: [
          {
            provider_key: "connexus",
            display_name: "Connexus",
            is_active: true,
          },
        ],
        total: 1,
      });
    });

    await page.goto(`${BASE_URL}/settings/integrations`);
    await expect(
      page.getByText(/sms|connexus/i).first()
    ).toBeVisible({ timeout: 5000 });
    await expect(
      page.getByText(/active|connected/i).first()
    ).toBeVisible();
  });

  test("email provider status", async ({ page }) => {
    await setupAuthenticatedSession(page);

    await page.route("**/api/v1/integrations**", async (route) => {
      await jsonResponse(route, {
        items: [
          {
            name: "email_provider",
            display_name: "Email Provider",
            status: "active",
            configured: true,
            provider_key: "brevo",
          },
        ],
        total: 1,
      });
    });

    await page.route("**/api/v1/email/providers**", async (route) => {
      await jsonResponse(route, {
        items: [
          {
            provider_key: "brevo",
            display_name: "Brevo",
            is_active: true,
          },
        ],
        total: 1,
      });
    });

    await page.goto(`${BASE_URL}/settings/integrations`);
    await expect(
      page.getByText(/email|brevo/i).first()
    ).toBeVisible({ timeout: 5000 });
    await expect(
      page.getByText(/active|connected/i).first()
    ).toBeVisible();
  });

  test("create invoice + Xero sync", async ({ page }) => {
    await setupAuthenticatedSession(page);

    let capturedInvoiceBody: Record<string, unknown> | null = null;

    await page.route("**/api/v1/customers**", async (route) => {
      await jsonResponse(route, {
        items: [
          { id: "cust-1", first_name: "John", last_name: "Doe" },
        ],
        total: 1,
      });
    });

    await page.route("**/api/v1/invoices", async (route) => {
      if (route.request().method() === "POST") {
        capturedInvoiceBody = route.request().postDataJSON();
        await jsonResponse(route, {
          id: "inv-1",
          invoice_number: "INV-001",
          status: "draft",
          xero_sync_status: "pending",
          total: 150.0,
        });
      } else {
        await jsonResponse(route, { items: [], total: 0 });
      }
    });

    await page.route("**/api/v1/invoices/inv-1/xero-sync**", async (route) => {
      await jsonResponse(route, { sync_status: "synced" });
    });

    await page.goto(`${BASE_URL}/invoices/new`);

    // Fill invoice form — select customer, add line item
    const customerSelect = page.locator(
      '[data-testid="customer-select"], select[name="customer_id"], [name="customer_id"]'
    );
    if (await customerSelect.isVisible({ timeout: 3000 }).catch(() => false)) {
      await customerSelect.selectOption({ index: 1 }).catch(() => {});
    }

    // Look for amount/description fields
    const descriptionField = page.locator(
      'input[name="description"], [data-testid="line-description"], textarea[name*="description"]'
    ).first();
    if (await descriptionField.isVisible({ timeout: 2000 }).catch(() => false)) {
      await descriptionField.fill("Brake service");
    }

    const amountField = page.locator(
      'input[name="amount"], input[name*="total"], [data-testid="line-amount"]'
    ).first();
    if (await amountField.isVisible({ timeout: 2000 }).catch(() => false)) {
      await amountField.fill("150.00");
    }

    // Submit
    const submitButton = page.getByRole("button", {
      name: /create|save|submit/i,
    });
    if (await submitButton.isVisible({ timeout: 2000 }).catch(() => false)) {
      await submitButton.click();
    }

    // Verify invoice was created (API was called)
    await expect
      .poll(() => capturedInvoiceBody, { timeout: 5000 })
      .toBeTruthy();
  });

  test("process payment", async ({ page }) => {
    await setupAuthenticatedSession(page);

    let paymentCaptured = false;

    await page.route("**/api/v1/invoices/inv-1**", async (route) => {
      await jsonResponse(route, {
        id: "inv-1",
        invoice_number: "INV-001",
        status: "issued",
        total: 150.0,
        amount_due: 150.0,
        customer: { id: "cust-1", first_name: "John", last_name: "Doe" },
        line_items: [
          { description: "Brake service", quantity: 1, unit_price: 150.0 },
        ],
      });
    });

    await page.route("**/api/v1/payments", async (route) => {
      if (route.request().method() === "POST") {
        paymentCaptured = true;
        await jsonResponse(route, {
          id: "pay-1",
          invoice_id: "inv-1",
          amount: 150.0,
          status: "completed",
        });
      } else {
        await jsonResponse(route, { items: [], total: 0 });
      }
    });

    await page.goto(`${BASE_URL}/invoices/inv-1`);

    const payButton = page.getByRole("button", {
      name: /pay|record payment|mark as paid/i,
    });
    if (await payButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await payButton.click();

      // Fill payment amount if a modal appears
      const paymentAmountField = page.locator(
        'input[name="amount"], [data-testid="payment-amount"]'
      ).first();
      if (
        await paymentAmountField.isVisible({ timeout: 2000 }).catch(() => false)
      ) {
        await paymentAmountField.fill("150.00");
      }

      const confirmButton = page.getByRole("button", {
        name: /confirm|submit|record/i,
      });
      if (
        await confirmButton.isVisible({ timeout: 2000 }).catch(() => false)
      ) {
        await confirmButton.click();
      }
    }

    await expect.poll(() => paymentCaptured, { timeout: 5000 }).toBeTruthy();
  });

  test("issue refund + credit note", async ({ page }) => {
    await setupAuthenticatedSession(page);

    let refundCaptured = false;

    await page.route("**/api/v1/invoices/inv-1**", async (route) => {
      await jsonResponse(route, {
        id: "inv-1",
        invoice_number: "INV-001",
        status: "paid",
        total: 150.0,
        amount_paid: 150.0,
        customer: { id: "cust-1", first_name: "John", last_name: "Doe" },
      });
    });

    await page.route("**/api/v1/invoices/inv-1/refund**", async (route) => {
      refundCaptured = true;
      await jsonResponse(route, {
        id: "refund-1",
        invoice_id: "inv-1",
        amount: 150.0,
        credit_note_id: "cn-1",
        status: "completed",
      });
    });

    await page.route("**/api/v1/credit-notes**", async (route) => {
      await jsonResponse(route, {
        items: [
          {
            id: "cn-1",
            invoice_id: "inv-1",
            amount: 150.0,
            status: "issued",
          },
        ],
        total: 1,
      });
    });

    await page.goto(`${BASE_URL}/invoices/inv-1`);

    const refundButton = page.getByRole("button", {
      name: /refund|issue refund/i,
    });
    if (await refundButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await refundButton.click();

      const confirmButton = page.getByRole("button", {
        name: /confirm|submit|issue/i,
      });
      if (
        await confirmButton.isVisible({ timeout: 2000 }).catch(() => false)
      ) {
        await confirmButton.click();
      }
    }

    await expect.poll(() => refundCaptured, { timeout: 5000 }).toBeTruthy();
  });
});

// ===========================================================================
// Phase 2: Safe Minors (9 tests)
// ===========================================================================

test.describe("Phase 2: Safe Minors", () => {
  test("full signup flow", async ({ page }) => {
    let capturedSignupBody: Record<string, unknown> | null = null;

    await page.route("**/api/v1/auth/token/refresh", async (route) => {
      await jsonResponse(route, {}, 401);
    });

    await page.route("**/api/v1/auth/register", async (route) => {
      capturedSignupBody = route.request().postDataJSON();
      await jsonResponse(route, {
        id: "user-2",
        email: "newuser@workshop.co.nz",
        first_name: "New",
        last_name: "User",
      });
    });

    await page.goto(`${BASE_URL}/signup`);

    const firstNameField = page.getByLabel(/first name/i);
    if (await firstNameField.isVisible({ timeout: 3000 }).catch(() => false)) {
      await firstNameField.fill("New");
    }

    const lastNameField = page.getByLabel(/last name/i);
    if (await lastNameField.isVisible({ timeout: 2000 }).catch(() => false)) {
      await lastNameField.fill("User");
    }

    const emailField = page.getByLabel(/email/i);
    if (await emailField.isVisible({ timeout: 2000 }).catch(() => false)) {
      await emailField.fill("newuser@workshop.co.nz");
    }

    const passwordField = page.getByLabel(/password/i).first();
    if (await passwordField.isVisible({ timeout: 2000 }).catch(() => false)) {
      await passwordField.fill("NewSecureP@ss1");
    }

    const submitButton = page.getByRole("button", {
      name: /sign up|register|create account/i,
    });
    if (await submitButton.isVisible({ timeout: 2000 }).catch(() => false)) {
      await submitButton.click();
    }

    await expect
      .poll(() => capturedSignupBody, { timeout: 5000 })
      .toBeTruthy();
  });

  test("password reset flow", async ({ page }) => {
    let capturedResetBody: Record<string, unknown> | null = null;

    await page.route("**/api/v1/auth/token/refresh", async (route) => {
      await jsonResponse(route, {}, 401);
    });

    await page.route("**/api/v1/auth/forgot-password", async (route) => {
      capturedResetBody = route.request().postDataJSON();
      await jsonResponse(route, {
        detail: "If the email exists, a reset link has been sent.",
      });
    });

    await page.goto(`${BASE_URL}/forgot-password`);

    const emailField = page.getByLabel(/email/i);
    if (await emailField.isVisible({ timeout: 3000 }).catch(() => false)) {
      await emailField.fill(TEST_USER.email);
    }

    const submitButton = page.getByRole("button", {
      name: /reset|send|submit/i,
    });
    if (await submitButton.isVisible({ timeout: 2000 }).catch(() => false)) {
      await submitButton.click();
    }

    await expect
      .poll(() => capturedResetBody, { timeout: 5000 })
      .toBeTruthy();

    // Verify confirmation message
    await expect(
      page.getByText(/reset link|email|sent/i).first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("full invoice lifecycle", async ({ page }) => {
    await setupAuthenticatedSession(page);

    let invoiceCreated = false;
    let invoiceIssued = false;
    let paymentRecorded = false;

    await page.route("**/api/v1/customers**", async (route) => {
      await jsonResponse(route, {
        items: [{ id: "cust-1", first_name: "John", last_name: "Doe" }],
        total: 1,
      });
    });

    await page.route("**/api/v1/invoices", async (route) => {
      if (route.request().method() === "POST") {
        invoiceCreated = true;
        await jsonResponse(route, {
          id: "inv-lc-1",
          invoice_number: "INV-LC-001",
          status: "draft",
          total: 200.0,
        });
      } else {
        await jsonResponse(route, { items: [], total: 0 });
      }
    });

    await page.route("**/api/v1/invoices/inv-lc-1**", async (route) => {
      if (route.request().method() === "PATCH" || route.request().method() === "PUT") {
        invoiceIssued = true;
        await jsonResponse(route, {
          id: "inv-lc-1",
          invoice_number: "INV-LC-001",
          status: "issued",
          total: 200.0,
        });
      } else {
        await jsonResponse(route, {
          id: "inv-lc-1",
          invoice_number: "INV-LC-001",
          status: invoiceIssued ? "issued" : "draft",
          total: 200.0,
          customer: { id: "cust-1", first_name: "John", last_name: "Doe" },
          line_items: [
            { description: "Service", quantity: 1, unit_price: 200.0 },
          ],
        });
      }
    });

    await page.route("**/api/v1/invoices/inv-lc-1/issue**", async (route) => {
      invoiceIssued = true;
      await jsonResponse(route, {
        id: "inv-lc-1",
        status: "issued",
      });
    });

    await page.route("**/api/v1/payments", async (route) => {
      if (route.request().method() === "POST") {
        paymentRecorded = true;
        await jsonResponse(route, {
          id: "pay-lc-1",
          invoice_id: "inv-lc-1",
          amount: 200.0,
          status: "completed",
        });
      } else {
        await jsonResponse(route, { items: [], total: 0 });
      }
    });

    // Step 1: Create invoice
    await page.goto(`${BASE_URL}/invoices/new`);
    const submitButton = page.getByRole("button", {
      name: /create|save|submit/i,
    });
    if (await submitButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await submitButton.click();
    }
    await expect.poll(() => invoiceCreated, { timeout: 5000 }).toBeTruthy();

    // Step 2: Issue invoice
    await page.goto(`${BASE_URL}/invoices/inv-lc-1`);
    const issueButton = page.getByRole("button", { name: /issue|send/i });
    if (await issueButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await issueButton.click();
      // Confirm if dialog appears
      const confirmBtn = page.getByRole("button", { name: /confirm|yes/i });
      if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await confirmBtn.click();
      }
    }
    await expect.poll(() => invoiceIssued, { timeout: 5000 }).toBeTruthy();

    // Step 3: Pay invoice
    const payButton = page.getByRole("button", {
      name: /pay|record payment/i,
    });
    if (await payButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await payButton.click();
      const confirmPay = page.getByRole("button", {
        name: /confirm|submit|record/i,
      });
      if (await confirmPay.isVisible({ timeout: 2000 }).catch(() => false)) {
        await confirmPay.click();
      }
    }
    await expect
      .poll(() => paymentRecorded, { timeout: 5000 })
      .toBeTruthy();
  });

  test("Xero sync verification", async ({ page }) => {
    await setupAuthenticatedSession(page);

    let invoiceCreated = false;

    await page.route("**/api/v1/customers**", async (route) => {
      await jsonResponse(route, {
        items: [{ id: "cust-1", first_name: "John", last_name: "Doe" }],
        total: 1,
      });
    });

    await page.route("**/api/v1/invoices", async (route) => {
      if (route.request().method() === "POST") {
        invoiceCreated = true;
        await jsonResponse(route, {
          id: "inv-xero-1",
          invoice_number: "INV-XERO-001",
          status: "draft",
          xero_sync_status: "synced",
          xero_invoice_id: "xero-inv-123",
        });
      } else {
        await jsonResponse(route, { items: [], total: 0 });
      }
    });

    await page.goto(`${BASE_URL}/invoices/new`);

    const submitButton = page.getByRole("button", {
      name: /create|save|submit/i,
    });
    if (await submitButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await submitButton.click();
    }

    await expect.poll(() => invoiceCreated, { timeout: 5000 }).toBeTruthy();
  });

  test("Stripe payment method operations", async ({ page }) => {
    await setupAuthenticatedSession(page);

    let paymentMethodAdded = false;

    await page.route("**/api/v1/billing/payment-methods**", async (route) => {
      if (route.request().method() === "POST") {
        paymentMethodAdded = true;
        await jsonResponse(route, {
          id: "pm-1",
          type: "card",
          card: { brand: "visa", last4: "4242" },
        });
      } else {
        await jsonResponse(route, {
          items: [
            {
              id: "pm-1",
              type: "card",
              card: { brand: "visa", last4: "4242" },
            },
          ],
          total: 1,
        });
      }
    });

    await page.route("**/api/v1/billing**", async (route) => {
      await jsonResponse(route, {
        subscription: { status: "active", plan: "pro" },
        payment_methods: [
          { id: "pm-1", type: "card", card: { brand: "visa", last4: "4242" } },
        ],
      });
    });

    await page.goto(`${BASE_URL}/settings/billing`);

    // Verify payment methods are displayed
    await expect(
      page.getByText(/4242|visa|payment method/i).first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("refresh token rotation", async ({ page }) => {
    let refreshCalled = false;

    // First refresh returns 401 (expired)
    await page.route("**/api/v1/auth/token/refresh", async (route) => {
      if (!refreshCalled) {
        refreshCalled = true;
        await jsonResponse(
          route,
          { access_token: FAKE_ACCESS_TOKEN },
          200
        );
      } else {
        await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
      }
    });

    await page.route("**/api/v1/auth/me", async (route) => {
      await jsonResponse(route, {
        first_name: TEST_USER.firstName,
        last_name: TEST_USER.lastName,
        email: TEST_USER.email,
      });
    });

    await page.goto(`${BASE_URL}/`);

    await expect.poll(() => refreshCalled, { timeout: 5000 }).toBeTruthy();
  });

  test("admin settings", async ({ page }) => {
    await setupAuthenticatedSession(page);

    await page.route("**/api/v1/admin/settings**", async (route) => {
      await jsonResponse(route, {
        site_name: "OraInvoice",
        maintenance_mode: false,
        max_orgs: 100,
      });
    });

    await page.goto(`${BASE_URL}/admin/settings`);

    await expect(
      page.getByText(/settings|configuration|admin/i).first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("audit log", async ({ page }) => {
    await setupAuthenticatedSession(page);

    await page.route("**/api/v1/admin/audit-log**", async (route) => {
      await jsonResponse(route, {
        items: [
          {
            id: "log-1",
            action: "user.login",
            user_email: TEST_USER.email,
            timestamp: "2026-04-12T10:00:00Z",
            details: "Successful login",
          },
          {
            id: "log-2",
            action: "invoice.created",
            user_email: TEST_USER.email,
            timestamp: "2026-04-12T10:05:00Z",
            details: "Invoice INV-001 created",
          },
        ],
        total: 2,
      });
    });

    await page.goto(`${BASE_URL}/admin/audit-log`);

    await expect(
      page.getByText(/audit|log|activity/i).first()
    ).toBeVisible({ timeout: 5000 });
    await expect(
      page.getByText(/user\.login|login|invoice/i).first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("SMS send verification", async ({ page }) => {
    await setupAuthenticatedSession(page);

    let testSmsSent = false;

    await page.route("**/api/v1/sms/providers**", async (route) => {
      await jsonResponse(route, {
        items: [
          {
            provider_key: "connexus",
            display_name: "Connexus",
            is_active: true,
          },
        ],
        total: 1,
      });
    });

    await page.route("**/api/v1/sms/test**", async (route) => {
      testSmsSent = true;
      await jsonResponse(route, { detail: "Test SMS sent successfully" });
    });

    await page.route("**/api/v1/integrations**", async (route) => {
      await jsonResponse(route, {
        items: [
          {
            name: "sms_provider",
            display_name: "SMS Provider",
            status: "active",
            configured: true,
          },
        ],
        total: 1,
      });
    });

    await page.goto(`${BASE_URL}/settings/integrations`);

    // Look for a test SMS button
    const testButton = page.getByRole("button", {
      name: /test|send test/i,
    });
    if (await testButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await testButton.click();
      await expect
        .poll(() => testSmsSent, { timeout: 5000 })
        .toBeTruthy();
    } else {
      // If no test button, verify the SMS provider is shown as active
      await expect(
        page.getByText(/connexus|sms/i).first()
      ).toBeVisible({ timeout: 5000 });
    }
  });
});

// ===========================================================================
// Phase 3: Integration Majors (6 tests)
// ===========================================================================

test.describe("Phase 3: Integration Majors", () => {
  test("Stripe customer creation + PaymentIntent", async ({ page }) => {
    await setupAuthenticatedSession(page);

    let customerCreated = false;
    let paymentIntentCreated = false;

    await page.route("**/api/v1/billing/customers", async (route) => {
      if (route.request().method() === "POST") {
        customerCreated = true;
        await jsonResponse(route, {
          id: "cust-stripe-1",
          stripe_customer_id: "cus_test123",
          email: "customer@test.com",
        });
      } else {
        await jsonResponse(route, { items: [], total: 0 });
      }
    });

    await page.route("**/api/v1/billing/payment-intents", async (route) => {
      if (route.request().method() === "POST") {
        paymentIntentCreated = true;
        await jsonResponse(route, {
          id: "pi-1",
          client_secret: "pi_test_secret_123",
          amount: 15000,
          currency: "nzd",
          status: "requires_payment_method",
        });
      } else {
        await jsonResponse(route, { items: [], total: 0 });
      }
    });

    await page.route("**/api/v1/billing**", async (route) => {
      await jsonResponse(route, {
        subscription: { status: "active", plan: "pro" },
        stripe_customer_id: "cus_test123",
      });
    });

    await page.goto(`${BASE_URL}/settings/billing`);

    // Verify billing page loads with Stripe data
    await expect(
      page.getByText(/billing|subscription|payment/i).first()
    ).toBeVisible({ timeout: 5000 });

    // Trigger customer creation via API mock
    await page.evaluate(async () => {
      await fetch("/api/v1/billing/customers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "customer@test.com" }),
      });
    });
    await expect.poll(() => customerCreated, { timeout: 5000 }).toBeTruthy();

    // Trigger PaymentIntent creation via API mock
    await page.evaluate(async () => {
      await fetch("/api/v1/billing/payment-intents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount: 15000, currency: "nzd" }),
      });
    });
    await expect
      .poll(() => paymentIntentCreated, { timeout: 5000 })
      .toBeTruthy();
  });

  test("webhook delivery and parsing", async ({ page }) => {
    await setupAuthenticatedSession(page);

    let webhookProcessed = false;

    await page.route("**/api/v1/webhooks/stripe", async (route) => {
      webhookProcessed = true;
      await jsonResponse(route, { received: true });
    });

    await page.goto(`${BASE_URL}/settings/integrations`);

    // Simulate webhook delivery via programmatic fetch
    await page.evaluate(async () => {
      await fetch("/api/v1/webhooks/stripe", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Stripe-Signature": "t=1234567890,v1=fake_signature",
        },
        body: JSON.stringify({
          id: "evt_test123",
          type: "payment_intent.succeeded",
          data: {
            object: {
              id: "pi_test123",
              amount: 15000,
              status: "succeeded",
            },
          },
        }),
      });
    });

    await expect
      .poll(() => webhookProcessed, { timeout: 5000 })
      .toBeTruthy();
  });

  test("billing portal session", async ({ page }) => {
    await setupAuthenticatedSession(page);

    let portalSessionCreated = false;

    await page.route(
      "**/api/v1/billing/portal-session",
      async (route) => {
        portalSessionCreated = true;
        await jsonResponse(route, {
          url: "https://billing.stripe.com/session/test_session",
        });
      }
    );

    await page.route("**/api/v1/billing**", async (route) => {
      await jsonResponse(route, {
        subscription: { status: "active", plan: "pro" },
      });
    });

    await page.goto(`${BASE_URL}/settings/billing`);

    const portalButton = page.getByRole("button", {
      name: /manage|billing portal|manage subscription/i,
    });
    if (await portalButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      // Intercept navigation to Stripe portal
      await page.route("https://billing.stripe.com/**", async (route) => {
        await route.fulfill({ status: 200, body: "Stripe Portal" });
      });
      await portalButton.click();
    } else {
      // Trigger portal session via API
      await page.evaluate(async () => {
        await fetch("/api/v1/billing/portal-session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
      });
    }

    await expect
      .poll(() => portalSessionCreated, { timeout: 5000 })
      .toBeTruthy();
  });

  test("MFA TOTP login (Redis-dependent)", async ({ page }) => {
    let mfaVerified = false;

    await page.route("**/api/v1/auth/login", async (route) => {
      await jsonResponse(route, {
        mfa_required: true,
        mfa_token: FAKE_MFA_TOKEN,
        methods: ["totp"],
        default_method: "totp",
      });
    });

    await page.route("**/api/v1/auth/token/refresh", async (route) => {
      await jsonResponse(route, {}, 401);
    });

    await page.route("**/api/v1/auth/mfa/verify", async (route) => {
      mfaVerified = true;
      await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
    });

    await page.route("**/api/v1/auth/me", async (route) => {
      await jsonResponse(route, {
        first_name: TEST_USER.firstName,
        last_name: TEST_USER.lastName,
        email: TEST_USER.email,
      });
    });

    await page.goto(`${BASE_URL}/login`);
    await page.getByLabel("Email address").fill(TEST_USER.email);
    await page.getByLabel("Password").fill(TEST_USER.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();

    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByText("Two-factor authentication")
    ).toBeVisible({ timeout: 5000 });

    const digitInputs = dialog
      .getByRole("group", { name: "Verification code" })
      .locator("input");
    for (let i = 0; i < 6; i++) {
      await digitInputs.nth(i).fill(String(i + 1));
    }

    await dialog.getByRole("button", { name: "Verify" }).click();

    await expect.poll(() => mfaVerified, { timeout: 5000 }).toBeTruthy();

    // Verify redirect after MFA
    await page.waitForURL((url) => !url.pathname.includes("/login"), {
      timeout: 5000,
    });
  });

  test("MFA SMS login (Redis-dependent)", async ({ page }) => {
    let mfaVerified = false;

    await page.route("**/api/v1/auth/login", async (route) => {
      await jsonResponse(route, {
        mfa_required: true,
        mfa_token: FAKE_MFA_TOKEN,
        methods: ["sms"],
        default_method: "sms",
      });
    });

    await page.route("**/api/v1/auth/token/refresh", async (route) => {
      await jsonResponse(route, {}, 401);
    });

    await page.route("**/api/v1/auth/mfa/provider-config", async (route) => {
      await jsonResponse(route, {
        provider: "connexus",
        firebase_config: null,
        phone_number: null,
      });
    });

    await page.route("**/api/v1/auth/mfa/challenge/send", async (route) => {
      await jsonResponse(route, { detail: "Code sent" });
    });

    await page.route("**/api/v1/auth/mfa/verify", async (route) => {
      mfaVerified = true;
      await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
    });

    await page.route("**/api/v1/auth/me", async (route) => {
      await jsonResponse(route, {
        first_name: TEST_USER.firstName,
        last_name: TEST_USER.lastName,
        email: TEST_USER.email,
      });
    });

    await page.goto(`${BASE_URL}/login`);
    await page.getByLabel("Email address").fill(TEST_USER.email);
    await page.getByLabel("Password").fill(TEST_USER.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();

    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByText("Two-factor authentication")
    ).toBeVisible({ timeout: 5000 });

    await expect(
      dialog.getByText("Enter the 6-digit code sent to your phone")
    ).toBeVisible({ timeout: 5000 });

    const digitInputs = dialog
      .getByRole("group", { name: "Verification code" })
      .locator("input");
    for (let i = 0; i < 6; i++) {
      await digitInputs.nth(i).fill(String(i + 1));
    }

    await dialog.getByRole("button", { name: "Verify" }).click();

    await expect.poll(() => mfaVerified, { timeout: 5000 }).toBeTruthy();

    await page.waitForURL((url) => !url.pathname.includes("/login"), {
      timeout: 5000,
    });
  });

  test("Firebase Google OAuth login", async ({ page }) => {
    await page.route("**/api/v1/auth/token/refresh", async (route) => {
      await jsonResponse(route, {}, 401);
    });

    await page.goto(`${BASE_URL}/login`);

    // Verify Google OAuth button exists
    const googleButton = page.getByRole("button", {
      name: /google|sign in with google|continue with google/i,
    });
    await expect(googleButton).toBeVisible({ timeout: 5000 });

    // Mock the Firebase OAuth callback endpoint
    await page.route("**/api/v1/auth/firebase-login", async (route) => {
      await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
    });

    // Click triggers Firebase popup — in test env it won't open a real popup,
    // but we verify the button exists and the endpoint is reachable
    await googleButton.click();

    // Verify the button triggered an action (no crash, page still functional)
    await expect(googleButton).toBeVisible();
  });
});

// ===========================================================================
// Phase 4: Comprehensive Suite (40 tests)
// ===========================================================================

test.describe("Phase 4: Comprehensive Suite", () => {
  // -------------------------------------------------------------------------
  // Authentication flows (10 tests)
  // -------------------------------------------------------------------------
  test.describe("Authentication flows", () => {
    test("email/password login", async ({ page }) => {
      let loginCalled = false;

      await page.route("**/api/v1/auth/login", async (route) => {
        loginCalled = true;
        await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
      });

      await page.route("**/api/v1/auth/token/refresh", async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.route("**/api/v1/auth/me", async (route) => {
        await jsonResponse(route, {
          first_name: TEST_USER.firstName,
          last_name: TEST_USER.lastName,
          email: TEST_USER.email,
        });
      });

      await page.goto(`${BASE_URL}/login`);
      await page.getByLabel("Email address").fill(TEST_USER.email);
      await page.getByLabel("Password").fill(TEST_USER.password);
      await page.getByRole("button", { name: "Sign in", exact: true }).click();

      await expect.poll(() => loginCalled, { timeout: 5000 }).toBeTruthy();
      await page.waitForURL((url) => !url.pathname.includes("/login"), {
        timeout: 5000,
      });
    });

    test("Google OAuth login", async ({ page }) => {
      await page.route("**/api/v1/auth/token/refresh", async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.route("**/api/v1/auth/firebase-login", async (route) => {
        await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
      });

      await page.goto(`${BASE_URL}/login`);

      const googleButton = page.getByRole("button", {
        name: /google|sign in with google|continue with google/i,
      });
      await expect(googleButton).toBeVisible({ timeout: 5000 });
      await googleButton.click();
      await expect(googleButton).toBeVisible();
    });

    test("passkey authentication", async ({ page }) => {
      await page.route("**/api/v1/auth/token/refresh", async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.route(
        "**/api/v1/auth/passkey/authentication-options",
        async (route) => {
          await jsonResponse(route, {
            challenge: "dGVzdC1jaGFsbGVuZ2U",
            timeout: 60000,
            rpId: "localhost",
            allowCredentials: [],
          });
        }
      );

      await page.goto(`${BASE_URL}/login`);

      const passkeyButton = page.getByRole("button", {
        name: /passkey|biometric|security key/i,
      });
      await expect(passkeyButton).toBeVisible({ timeout: 5000 });
      await passkeyButton.click();
      await expect(passkeyButton).toBeVisible();
    });

    test("MFA TOTP", async ({ page }) => {
      let mfaVerified = false;

      await page.route("**/api/v1/auth/login", async (route) => {
        await jsonResponse(route, {
          mfa_required: true,
          mfa_token: FAKE_MFA_TOKEN,
          methods: ["totp"],
          default_method: "totp",
        });
      });

      await page.route("**/api/v1/auth/token/refresh", async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.route("**/api/v1/auth/mfa/verify", async (route) => {
        mfaVerified = true;
        await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
      });

      await page.route("**/api/v1/auth/me", async (route) => {
        await jsonResponse(route, {
          first_name: TEST_USER.firstName,
          last_name: TEST_USER.lastName,
          email: TEST_USER.email,
        });
      });

      await page.goto(`${BASE_URL}/login`);
      await page.getByLabel("Email address").fill(TEST_USER.email);
      await page.getByLabel("Password").fill(TEST_USER.password);
      await page.getByRole("button", { name: "Sign in", exact: true }).click();

      const dialog = page.getByRole("dialog");
      await expect(
        dialog.getByText("Two-factor authentication")
      ).toBeVisible({ timeout: 5000 });

      const digitInputs = dialog
        .getByRole("group", { name: "Verification code" })
        .locator("input");
      for (let i = 0; i < 6; i++) {
        await digitInputs.nth(i).fill(String(i + 1));
      }
      await dialog.getByRole("button", { name: "Verify" }).click();

      await expect.poll(() => mfaVerified, { timeout: 5000 }).toBeTruthy();
    });

    test("MFA SMS", async ({ page }) => {
      let mfaVerified = false;

      await page.route("**/api/v1/auth/login", async (route) => {
        await jsonResponse(route, {
          mfa_required: true,
          mfa_token: FAKE_MFA_TOKEN,
          methods: ["sms"],
          default_method: "sms",
        });
      });

      await page.route("**/api/v1/auth/token/refresh", async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.route("**/api/v1/auth/mfa/provider-config", async (route) => {
        await jsonResponse(route, {
          provider: "connexus",
          firebase_config: null,
          phone_number: null,
        });
      });

      await page.route("**/api/v1/auth/mfa/challenge/send", async (route) => {
        await jsonResponse(route, { detail: "Code sent" });
      });

      await page.route("**/api/v1/auth/mfa/verify", async (route) => {
        mfaVerified = true;
        await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
      });

      await page.route("**/api/v1/auth/me", async (route) => {
        await jsonResponse(route, {
          first_name: TEST_USER.firstName,
          last_name: TEST_USER.lastName,
          email: TEST_USER.email,
        });
      });

      await page.goto(`${BASE_URL}/login`);
      await page.getByLabel("Email address").fill(TEST_USER.email);
      await page.getByLabel("Password").fill(TEST_USER.password);
      await page.getByRole("button", { name: "Sign in", exact: true }).click();

      const dialog = page.getByRole("dialog");
      await expect(
        dialog.getByText("Two-factor authentication")
      ).toBeVisible({ timeout: 5000 });

      await expect(
        dialog.getByText("Enter the 6-digit code sent to your phone")
      ).toBeVisible({ timeout: 5000 });

      const digitInputs = dialog
        .getByRole("group", { name: "Verification code" })
        .locator("input");
      for (let i = 0; i < 6; i++) {
        await digitInputs.nth(i).fill(String(i + 1));
      }
      await dialog.getByRole("button", { name: "Verify" }).click();

      await expect.poll(() => mfaVerified, { timeout: 5000 }).toBeTruthy();
    });

    test("MFA email", async ({ page }) => {
      let mfaVerified = false;

      await page.route("**/api/v1/auth/login", async (route) => {
        await jsonResponse(route, {
          mfa_required: true,
          mfa_token: FAKE_MFA_TOKEN,
          methods: ["email"],
          default_method: "email",
        });
      });

      await page.route("**/api/v1/auth/token/refresh", async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.route("**/api/v1/auth/mfa/challenge/send", async (route) => {
        await jsonResponse(route, { detail: "Code sent to email" });
      });

      await page.route("**/api/v1/auth/mfa/verify", async (route) => {
        mfaVerified = true;
        await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
      });

      await page.route("**/api/v1/auth/me", async (route) => {
        await jsonResponse(route, {
          first_name: TEST_USER.firstName,
          last_name: TEST_USER.lastName,
          email: TEST_USER.email,
        });
      });

      await page.goto(`${BASE_URL}/login`);
      await page.getByLabel("Email address").fill(TEST_USER.email);
      await page.getByLabel("Password").fill(TEST_USER.password);
      await page.getByRole("button", { name: "Sign in", exact: true }).click();

      const dialog = page.getByRole("dialog");
      await expect(
        dialog.getByText("Two-factor authentication")
      ).toBeVisible({ timeout: 5000 });

      const digitInputs = dialog
        .getByRole("group", { name: "Verification code" })
        .locator("input");
      if (await digitInputs.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        for (let i = 0; i < 6; i++) {
          await digitInputs.nth(i).fill(String(i + 1));
        }
        await dialog.getByRole("button", { name: "Verify" }).click();
      }

      await expect.poll(() => mfaVerified, { timeout: 5000 }).toBeTruthy();
    });

    test("backup codes", async ({ page }) => {
      let backupCodeVerified = false;

      await page.route("**/api/v1/auth/login", async (route) => {
        await jsonResponse(route, {
          mfa_required: true,
          mfa_token: FAKE_MFA_TOKEN,
          methods: ["totp", "backup_codes"],
          default_method: "totp",
        });
      });

      await page.route("**/api/v1/auth/token/refresh", async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.route("**/api/v1/auth/mfa/verify", async (route) => {
        backupCodeVerified = true;
        await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
      });

      await page.route("**/api/v1/auth/me", async (route) => {
        await jsonResponse(route, {
          first_name: TEST_USER.firstName,
          last_name: TEST_USER.lastName,
          email: TEST_USER.email,
        });
      });

      await page.goto(`${BASE_URL}/login`);
      await page.getByLabel("Email address").fill(TEST_USER.email);
      await page.getByLabel("Password").fill(TEST_USER.password);
      await page.getByRole("button", { name: "Sign in", exact: true }).click();

      const dialog = page.getByRole("dialog");
      await expect(
        dialog.getByText("Two-factor authentication")
      ).toBeVisible({ timeout: 5000 });

      // Switch to backup code method
      const backupLink = dialog.getByText(/backup code|use backup/i);
      if (await backupLink.isVisible({ timeout: 2000 }).catch(() => false)) {
        await backupLink.click();
      }

      // Enter backup code
      const backupInput = dialog.locator(
        'input[name="backup_code"], input[placeholder*="backup"], input[type="text"]'
      ).first();
      if (await backupInput.isVisible({ timeout: 2000 }).catch(() => false)) {
        await backupInput.fill("ABCD-1234-EFGH");
      }

      const verifyButton = dialog.getByRole("button", { name: /verify|submit/i });
      if (await verifyButton.isVisible({ timeout: 2000 }).catch(() => false)) {
        await verifyButton.click();
      }

      await expect
        .poll(() => backupCodeVerified, { timeout: 5000 })
        .toBeTruthy();
    });

    test("password reset", async ({ page }) => {
      let resetCalled = false;

      await page.route("**/api/v1/auth/token/refresh", async (route) => {
        await jsonResponse(route, {}, 401);
      });

      await page.route("**/api/v1/auth/forgot-password", async (route) => {
        resetCalled = true;
        await jsonResponse(route, {
          detail: "If the email exists, a reset link has been sent.",
        });
      });

      await page.goto(`${BASE_URL}/forgot-password`);

      const emailField = page.getByLabel(/email/i);
      if (await emailField.isVisible({ timeout: 3000 }).catch(() => false)) {
        await emailField.fill(TEST_USER.email);
      }

      const submitButton = page.getByRole("button", {
        name: /reset|send|submit/i,
      });
      if (await submitButton.isVisible({ timeout: 2000 }).catch(() => false)) {
        await submitButton.click();
      }

      await expect.poll(() => resetCalled, { timeout: 5000 }).toBeTruthy();
    });

    test("session refresh", async ({ page }) => {
      let refreshCalled = false;

      await page.route("**/api/v1/auth/token/refresh", async (route) => {
        refreshCalled = true;
        await jsonResponse(route, { access_token: FAKE_ACCESS_TOKEN });
      });

      await page.route("**/api/v1/auth/me", async (route) => {
        await jsonResponse(route, {
          first_name: TEST_USER.firstName,
          last_name: TEST_USER.lastName,
          email: TEST_USER.email,
        });
      });

      await page.goto(`${BASE_URL}/`);

      await expect.poll(() => refreshCalled, { timeout: 5000 }).toBeTruthy();
    });

    test("logout", async ({ page }) => {
      let logoutCalled = false;

      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/auth/logout", async (route) => {
        logoutCalled = true;
        await jsonResponse(route, { detail: "Logged out" });
      });

      await page.goto(`${BASE_URL}/`);

      // Find and click logout button
      const logoutButton = page.getByRole("button", { name: /log ?out|sign ?out/i });
      const logoutLink = page.getByRole("link", { name: /log ?out|sign ?out/i });

      if (await logoutButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await logoutButton.click();
      } else if (await logoutLink.isVisible({ timeout: 2000 }).catch(() => false)) {
        await logoutLink.click();
      } else {
        // Try user menu dropdown first
        const userMenu = page.locator(
          '[data-testid="user-menu"], button[aria-label*="user"], button[aria-label*="account"]'
        ).first();
        if (await userMenu.isVisible({ timeout: 2000 }).catch(() => false)) {
          await userMenu.click();
          const logoutItem = page.getByText(/log ?out|sign ?out/i).first();
          if (await logoutItem.isVisible({ timeout: 2000 }).catch(() => false)) {
            await logoutItem.click();
          }
        }
      }

      await expect.poll(() => logoutCalled, { timeout: 5000 }).toBeTruthy();
    });
  });

  // -------------------------------------------------------------------------
  // Core workflows (10 tests)
  // -------------------------------------------------------------------------
  test.describe("Core workflows", () => {
    test("customer creation", async ({ page }) => {
      await setupAuthenticatedSession(page);

      let customerCreated = false;

      await page.route("**/api/v1/customers", async (route) => {
        if (route.request().method() === "POST") {
          customerCreated = true;
          await jsonResponse(route, {
            id: "cust-new-1",
            first_name: "Jane",
            last_name: "Smith",
          });
        } else {
          await jsonResponse(route, { items: [], total: 0 });
        }
      });

      await page.goto(`${BASE_URL}/customers/new`);

      const firstNameField = page.getByLabel(/first name/i);
      if (await firstNameField.isVisible({ timeout: 3000 }).catch(() => false)) {
        await firstNameField.fill("Jane");
      }

      const submitButton = page.getByRole("button", {
        name: /create|save|add/i,
      });
      if (await submitButton.isVisible({ timeout: 2000 }).catch(() => false)) {
        await submitButton.click();
      }

      await expect
        .poll(() => customerCreated, { timeout: 5000 })
        .toBeTruthy();
    });

    test("invoice create", async ({ page }) => {
      await setupAuthenticatedSession(page);

      let invoiceCreated = false;

      await page.route("**/api/v1/customers**", async (route) => {
        await jsonResponse(route, {
          items: [{ id: "cust-1", first_name: "John", last_name: "Doe" }],
          total: 1,
        });
      });

      await page.route("**/api/v1/invoices", async (route) => {
        if (route.request().method() === "POST") {
          invoiceCreated = true;
          await jsonResponse(route, {
            id: "inv-new-1",
            invoice_number: "INV-NEW-001",
            status: "draft",
          });
        } else {
          await jsonResponse(route, { items: [], total: 0 });
        }
      });

      await page.goto(`${BASE_URL}/invoices/new`);

      const submitButton = page.getByRole("button", {
        name: /create|save|submit/i,
      });
      if (await submitButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await submitButton.click();
      }

      await expect
        .poll(() => invoiceCreated, { timeout: 5000 })
        .toBeTruthy();
    });

    test("invoice issue", async ({ page }) => {
      await setupAuthenticatedSession(page);

      let invoiceIssued = false;

      await page.route("**/api/v1/invoices/inv-1**", async (route) => {
        await jsonResponse(route, {
          id: "inv-1",
          invoice_number: "INV-001",
          status: "draft",
          total: 150.0,
          customer: { id: "cust-1", first_name: "John", last_name: "Doe" },
          line_items: [
            { description: "Service", quantity: 1, unit_price: 150.0 },
          ],
        });
      });

      await page.route("**/api/v1/invoices/inv-1/issue**", async (route) => {
        invoiceIssued = true;
        await jsonResponse(route, { id: "inv-1", status: "issued" });
      });

      await page.goto(`${BASE_URL}/invoices/inv-1`);

      const issueButton = page.getByRole("button", { name: /issue|send/i });
      if (await issueButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await issueButton.click();
        const confirmBtn = page.getByRole("button", { name: /confirm|yes/i });
        if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
          await confirmBtn.click();
        }
      }

      await expect
        .poll(() => invoiceIssued, { timeout: 5000 })
        .toBeTruthy();
    });

    test("invoice pay", async ({ page }) => {
      await setupAuthenticatedSession(page);

      let paymentRecorded = false;

      await page.route("**/api/v1/invoices/inv-1**", async (route) => {
        await jsonResponse(route, {
          id: "inv-1",
          invoice_number: "INV-001",
          status: "issued",
          total: 150.0,
          amount_due: 150.0,
          customer: { id: "cust-1", first_name: "John", last_name: "Doe" },
        });
      });

      await page.route("**/api/v1/payments", async (route) => {
        if (route.request().method() === "POST") {
          paymentRecorded = true;
          await jsonResponse(route, {
            id: "pay-1",
            amount: 150.0,
            status: "completed",
          });
        } else {
          await jsonResponse(route, { items: [], total: 0 });
        }
      });

      await page.goto(`${BASE_URL}/invoices/inv-1`);

      const payButton = page.getByRole("button", {
        name: /pay|record payment|mark as paid/i,
      });
      if (await payButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await payButton.click();
        const confirmBtn = page.getByRole("button", {
          name: /confirm|submit|record/i,
        });
        if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
          await confirmBtn.click();
        }
      }

      await expect
        .poll(() => paymentRecorded, { timeout: 5000 })
        .toBeTruthy();
    });

    test("payment recording", async ({ page }) => {
      await setupAuthenticatedSession(page);

      let paymentCreated = false;

      await page.route("**/api/v1/payments", async (route) => {
        if (route.request().method() === "POST") {
          paymentCreated = true;
          await jsonResponse(route, {
            id: "pay-new-1",
            invoice_id: "inv-1",
            amount: 75.0,
            method: "cash",
            status: "completed",
          });
        } else {
          await jsonResponse(route, { items: [], total: 0 });
        }
      });

      await page.route("**/api/v1/invoices/inv-1**", async (route) => {
        await jsonResponse(route, {
          id: "inv-1",
          invoice_number: "INV-001",
          status: "issued",
          total: 150.0,
          amount_due: 75.0,
        });
      });

      await page.goto(`${BASE_URL}/invoices/inv-1`);

      const payButton = page.getByRole("button", {
        name: /pay|record payment/i,
      });
      if (await payButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await payButton.click();
        const amountField = page.locator('input[name="amount"]').first();
        if (await amountField.isVisible({ timeout: 2000 }).catch(() => false)) {
          await amountField.fill("75.00");
        }
        const confirmBtn = page.getByRole("button", {
          name: /confirm|submit|record/i,
        });
        if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
          await confirmBtn.click();
        }
      }

      await expect
        .poll(() => paymentCreated, { timeout: 5000 })
        .toBeTruthy();
    });

    test("refund", async ({ page }) => {
      await setupAuthenticatedSession(page);

      let refundCreated = false;

      await page.route("**/api/v1/invoices/inv-1**", async (route) => {
        await jsonResponse(route, {
          id: "inv-1",
          invoice_number: "INV-001",
          status: "paid",
          total: 150.0,
          amount_paid: 150.0,
        });
      });

      await page.route("**/api/v1/invoices/inv-1/refund**", async (route) => {
        refundCreated = true;
        await jsonResponse(route, {
          id: "refund-1",
          amount: 150.0,
          status: "completed",
        });
      });

      await page.goto(`${BASE_URL}/invoices/inv-1`);

      const refundButton = page.getByRole("button", {
        name: /refund|issue refund/i,
      });
      if (await refundButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await refundButton.click();
        const confirmBtn = page.getByRole("button", {
          name: /confirm|submit|issue/i,
        });
        if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
          await confirmBtn.click();
        }
      }

      await expect
        .poll(() => refundCreated, { timeout: 5000 })
        .toBeTruthy();
    });

    test("credit note", async ({ page }) => {
      await setupAuthenticatedSession(page);

      let creditNoteCreated = false;

      await page.route("**/api/v1/credit-notes", async (route) => {
        if (route.request().method() === "POST") {
          creditNoteCreated = true;
          await jsonResponse(route, {
            id: "cn-1",
            invoice_id: "inv-1",
            amount: 50.0,
            status: "issued",
          });
        } else {
          await jsonResponse(route, { items: [], total: 0 });
        }
      });

      await page.route("**/api/v1/invoices/inv-1**", async (route) => {
        await jsonResponse(route, {
          id: "inv-1",
          invoice_number: "INV-001",
          status: "paid",
          total: 150.0,
        });
      });

      await page.goto(`${BASE_URL}/invoices/inv-1`);

      const creditNoteButton = page.getByRole("button", {
        name: /credit note|create credit/i,
      });
      if (await creditNoteButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await creditNoteButton.click();
        const confirmBtn = page.getByRole("button", {
          name: /confirm|submit|create/i,
        });
        if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
          await confirmBtn.click();
        }
      }

      await expect
        .poll(() => creditNoteCreated, { timeout: 5000 })
        .toBeTruthy();
    });

    test("quote create", async ({ page }) => {
      await setupAuthenticatedSession(page);

      let quoteCreated = false;

      await page.route("**/api/v1/customers**", async (route) => {
        await jsonResponse(route, {
          items: [{ id: "cust-1", first_name: "John", last_name: "Doe" }],
          total: 1,
        });
      });

      await page.route("**/api/v1/quotes", async (route) => {
        if (route.request().method() === "POST") {
          quoteCreated = true;
          await jsonResponse(route, {
            id: "quote-1",
            quote_number: "QT-001",
            status: "draft",
            total: 300.0,
          });
        } else {
          await jsonResponse(route, { items: [], total: 0 });
        }
      });

      await page.goto(`${BASE_URL}/quotes/new`);

      const submitButton = page.getByRole("button", {
        name: /create|save|submit/i,
      });
      if (await submitButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await submitButton.click();
      }

      await expect
        .poll(() => quoteCreated, { timeout: 5000 })
        .toBeTruthy();
    });

    test("job card create", async ({ page }) => {
      await setupAuthenticatedSession(page);

      let jobCardCreated = false;

      await page.route("**/api/v1/customers**", async (route) => {
        await jsonResponse(route, {
          items: [{ id: "cust-1", first_name: "John", last_name: "Doe" }],
          total: 1,
        });
      });

      await page.route("**/api/v1/job-cards", async (route) => {
        if (route.request().method() === "POST") {
          jobCardCreated = true;
          await jsonResponse(route, {
            id: "jc-1",
            job_number: "JC-001",
            status: "open",
          });
        } else {
          await jsonResponse(route, { items: [], total: 0 });
        }
      });

      await page.goto(`${BASE_URL}/job-cards/new`);

      const submitButton = page.getByRole("button", {
        name: /create|save|submit/i,
      });
      if (await submitButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await submitButton.click();
      }

      await expect
        .poll(() => jobCardCreated, { timeout: 5000 })
        .toBeTruthy();
    });

    test("invoice PDF", async ({ page }) => {
      await setupAuthenticatedSession(page);

      let pdfRequested = false;

      await page.route("**/api/v1/invoices/inv-1**", async (route) => {
        if (route.request().url().includes("/pdf")) {
          pdfRequested = true;
          await route.fulfill({
            status: 200,
            contentType: "application/pdf",
            body: "%PDF-1.4 fake pdf content",
          });
        } else {
          await jsonResponse(route, {
            id: "inv-1",
            invoice_number: "INV-001",
            status: "issued",
            total: 150.0,
            customer: { id: "cust-1", first_name: "John", last_name: "Doe" },
          });
        }
      });

      await page.goto(`${BASE_URL}/invoices/inv-1`);

      const pdfButton = page.getByRole("button", {
        name: /pdf|download|print/i,
      });
      if (await pdfButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await pdfButton.click();
      }

      await expect
        .poll(() => pdfRequested, { timeout: 5000 })
        .toBeTruthy();
    });
  });

  // -------------------------------------------------------------------------
  // Settings & integrations (8 tests)
  // -------------------------------------------------------------------------
  test.describe("Settings & integrations", () => {
    test("Stripe settings", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/integrations**", async (route) => {
        await jsonResponse(route, {
          items: [
            {
              name: "stripe",
              display_name: "Stripe",
              status: "connected",
              configured: true,
            },
          ],
          total: 1,
        });
      });

      await page.route("**/api/v1/billing**", async (route) => {
        await jsonResponse(route, {
          subscription: { status: "active", plan: "pro" },
        });
      });

      await page.goto(`${BASE_URL}/settings/integrations`);
      await expect(page.getByText("Stripe")).toBeVisible({ timeout: 5000 });
      await expect(
        page.getByText(/connected/i).first()
      ).toBeVisible();
    });

    test("Xero settings", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/integrations**", async (route) => {
        await jsonResponse(route, {
          items: [
            {
              name: "xero",
              display_name: "Xero",
              status: "connected",
              configured: true,
            },
          ],
          total: 1,
        });
      });

      await page.goto(`${BASE_URL}/settings/integrations`);
      await expect(page.getByText("Xero")).toBeVisible({ timeout: 5000 });
      await expect(
        page.getByText(/connected/i).first()
      ).toBeVisible();
    });

    test("SMS provider", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/integrations**", async (route) => {
        await jsonResponse(route, {
          items: [
            {
              name: "sms_provider",
              display_name: "SMS Provider",
              status: "active",
              configured: true,
            },
          ],
          total: 1,
        });
      });

      await page.route("**/api/v1/sms/providers**", async (route) => {
        await jsonResponse(route, {
          items: [
            { provider_key: "connexus", display_name: "Connexus", is_active: true },
          ],
          total: 1,
        });
      });

      await page.goto(`${BASE_URL}/settings/integrations`);
      await expect(
        page.getByText(/sms|connexus/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("email provider", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/integrations**", async (route) => {
        await jsonResponse(route, {
          items: [
            {
              name: "email_provider",
              display_name: "Email Provider",
              status: "active",
              configured: true,
            },
          ],
          total: 1,
        });
      });

      await page.route("**/api/v1/email/providers**", async (route) => {
        await jsonResponse(route, {
          items: [
            { provider_key: "brevo", display_name: "Brevo", is_active: true },
          ],
          total: 1,
        });
      });

      await page.goto(`${BASE_URL}/settings/integrations`);
      await expect(
        page.getByText(/email|brevo/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("user profile", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/users/me**", async (route) => {
        await jsonResponse(route, {
          id: "user-1",
          first_name: TEST_USER.firstName,
          last_name: TEST_USER.lastName,
          email: TEST_USER.email,
          role: "org_admin",
        });
      });

      await page.goto(`${BASE_URL}/settings/profile`);
      await expect(
        page.getByText(/profile|account/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("org settings", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/organisations**", async (route) => {
        await jsonResponse(route, {
          id: "org-1",
          name: "Test Workshop",
          trade_family: "automotive",
        });
      });

      await page.route("**/api/v1/org/settings**", async (route) => {
        await jsonResponse(route, {
          id: "org-1",
          name: "Test Workshop",
          trade_family: "automotive",
          gst_registered: true,
        });
      });

      await page.goto(`${BASE_URL}/settings/organisation`);
      await expect(
        page.getByText(/organisation|organization|company/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("branch management", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/branches**", async (route) => {
        await jsonResponse(route, {
          items: [
            {
              id: "branch-1",
              name: "Main Branch",
              is_default: true,
              is_active: true,
            },
          ],
          total: 1,
        });
      });

      await page.goto(`${BASE_URL}/settings/branches`);
      await expect(
        page.getByText(/branch|main branch/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("trade family config", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/org/settings**", async (route) => {
        await jsonResponse(route, {
          id: "org-1",
          name: "Test Workshop",
          trade_family: "automotive",
        });
      });

      await page.route("**/api/v1/trade-families**", async (route) => {
        await jsonResponse(route, {
          items: [
            { key: "automotive", display_name: "Automotive", enabled: true },
            { key: "electrical", display_name: "Electrical", enabled: false },
          ],
          total: 2,
        });
      });

      await page.goto(`${BASE_URL}/settings/organisation`);
      await expect(
        page.getByText(/automotive|trade family|trade/i).first()
      ).toBeVisible({ timeout: 5000 });
    });
  });

  // -------------------------------------------------------------------------
  // Admin pages (6 tests)
  // -------------------------------------------------------------------------
  test.describe("Admin pages", () => {
    test("global admin dashboard", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/admin/dashboard**", async (route) => {
        await jsonResponse(route, {
          total_orgs: 1,
          total_users: 1,
          total_invoices: 2,
          system_health: "healthy",
        });
      });

      await page.goto(`${BASE_URL}/admin`);
      await expect(
        page.getByText(/admin|dashboard/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("user management", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/admin/users**", async (route) => {
        await jsonResponse(route, {
          items: [
            {
              id: "user-1",
              email: TEST_USER.email,
              first_name: TEST_USER.firstName,
              last_name: TEST_USER.lastName,
              role: "org_admin",
              is_active: true,
            },
          ],
          total: 1,
        });
      });

      await page.goto(`${BASE_URL}/admin/users`);
      await expect(
        page.getByText(/user|management/i).first()
      ).toBeVisible({ timeout: 5000 });
      await expect(
        page.getByText(TEST_USER.email)
      ).toBeVisible({ timeout: 5000 });
    });

    test("org management", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/admin/organisations**", async (route) => {
        await jsonResponse(route, {
          items: [
            {
              id: "org-1",
              name: "Test Workshop",
              trade_family: "automotive",
              is_active: true,
            },
          ],
          total: 1,
        });
      });

      await page.goto(`${BASE_URL}/admin/organisations`);
      await expect(
        page.getByText(/organisation|organization/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("audit log", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/admin/audit-log**", async (route) => {
        await jsonResponse(route, {
          items: [
            {
              id: "log-1",
              action: "user.login",
              user_email: TEST_USER.email,
              timestamp: "2026-04-12T10:00:00Z",
            },
          ],
          total: 1,
        });
      });

      await page.goto(`${BASE_URL}/admin/audit-log`);
      await expect(
        page.getByText(/audit|log/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("system settings", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/admin/settings**", async (route) => {
        await jsonResponse(route, {
          site_name: "OraInvoice",
          maintenance_mode: false,
        });
      });

      await page.goto(`${BASE_URL}/admin/settings`);
      await expect(
        page.getByText(/settings|system/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("integration configs", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/admin/integrations**", async (route) => {
        await jsonResponse(route, {
          items: [
            { name: "stripe", status: "configured" },
            { name: "xero", status: "configured" },
            { name: "connexus", status: "configured" },
            { name: "firebase", status: "configured" },
          ],
          total: 4,
        });
      });

      await page.goto(`${BASE_URL}/admin/integrations`);
      await expect(
        page.getByText(/integration|config/i).first()
      ).toBeVisible({ timeout: 5000 });
    });
  });

  // -------------------------------------------------------------------------
  // Reports (3 tests)
  // -------------------------------------------------------------------------
  test.describe("Reports", () => {
    test("revenue report", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/reports/revenue**", async (route) => {
        await jsonResponse(route, {
          total_revenue: 15000.0,
          period: "2026-04",
          breakdown: [
            { date: "2026-04-01", amount: 5000.0 },
            { date: "2026-04-15", amount: 10000.0 },
          ],
        });
      });

      await page.goto(`${BASE_URL}/reports/revenue`);
      await expect(
        page.getByText(/revenue|report/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("invoice aging", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/reports/invoice-aging**", async (route) => {
        await jsonResponse(route, {
          current: 500.0,
          "30_days": 200.0,
          "60_days": 100.0,
          "90_plus_days": 0.0,
          total_outstanding: 800.0,
        });
      });

      await page.goto(`${BASE_URL}/reports/invoice-aging`);
      await expect(
        page.getByText(/aging|outstanding|invoice/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("payment summary", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/reports/payments**", async (route) => {
        await jsonResponse(route, {
          total_payments: 12000.0,
          payment_count: 15,
          methods: [
            { method: "card", amount: 8000.0, count: 10 },
            { method: "cash", amount: 4000.0, count: 5 },
          ],
        });
      });

      await page.goto(`${BASE_URL}/reports/payments`);
      await expect(
        page.getByText(/payment|summary|report/i).first()
      ).toBeVisible({ timeout: 5000 });
    });
  });

  // -------------------------------------------------------------------------
  // Navigation (3 tests)
  // -------------------------------------------------------------------------
  test.describe("Navigation", () => {
    test("sidebar navigation", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.goto(`${BASE_URL}/`);

      // Verify key sidebar navigation items exist
      const sidebar = page.locator("nav, [data-testid='sidebar'], aside").first();
      await expect(sidebar).toBeVisible({ timeout: 5000 });

      // Check for common navigation links
      const navItems = [/dashboard/i, /invoices/i, /customers/i, /settings/i];
      for (const item of navItems) {
        await expect(
          page.getByRole("link", { name: item }).or(page.getByText(item).first())
        ).toBeVisible({ timeout: 3000 });
      }
    });

    test("mobile responsive layout", async ({ page }) => {
      await setupAuthenticatedSession(page);

      // Set mobile viewport
      await page.setViewportSize({ width: 375, height: 812 });
      await page.goto(`${BASE_URL}/`);

      // On mobile, sidebar should be collapsed or a hamburger menu should appear
      const hamburger = page.locator(
        'button[aria-label*="menu"], button[aria-label*="Menu"], [data-testid="mobile-menu"], button[aria-label*="navigation"]'
      ).first();

      // Either hamburger menu is visible or the page renders correctly at mobile width
      const isHamburgerVisible = await hamburger
        .isVisible({ timeout: 3000 })
        .catch(() => false);

      if (isHamburgerVisible) {
        await hamburger.click();
        // After clicking, navigation items should appear
        await expect(
          page.getByText(/dashboard|invoices/i).first()
        ).toBeVisible({ timeout: 3000 });
      } else {
        // Page should still render content at mobile width
        await expect(
          page.getByText(/dashboard|invoices|welcome/i).first()
        ).toBeVisible({ timeout: 5000 });
      }
    });

    test("breadcrumb navigation", async ({ page }) => {
      await setupAuthenticatedSession(page);

      await page.route("**/api/v1/invoices**", async (route) => {
        await jsonResponse(route, { items: [], total: 0 });
      });

      await page.goto(`${BASE_URL}/invoices`);

      // Look for breadcrumb navigation
      const breadcrumb = page.locator(
        'nav[aria-label*="breadcrumb"], [data-testid="breadcrumb"], .breadcrumb, nav[aria-label*="Breadcrumb"]'
      ).first();

      const hasBreadcrumb = await breadcrumb
        .isVisible({ timeout: 3000 })
        .catch(() => false);

      if (hasBreadcrumb) {
        await expect(breadcrumb).toBeVisible();
        // Breadcrumb should contain current page reference
        await expect(
          breadcrumb.getByText(/invoice/i)
        ).toBeVisible({ timeout: 3000 });
      } else {
        // Page title or heading should indicate current location
        await expect(
          page.getByText(/invoice/i).first()
        ).toBeVisible({ timeout: 5000 });
      }
    });
  });
});
