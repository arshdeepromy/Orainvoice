# Requirements Document

## Introduction

This feature enforces that organisation administrators (org_admin users) must have a valid payment method on file before they can use the application. When an org admin logs in and the organisation has no payment method, a blocking modal prevents all app usage until a card is added. When a payment method is expiring soon (within 30 days), a warning modal prompts the admin to update their card on every login until resolved. This enforcement applies exclusively to org_admin users — global admins, salespersons, branch admins, and kiosk users are unaffected.

## Glossary

- **Payment_Method_Enforcement_System**: The frontend and backend components responsible for checking payment method status after login and displaying appropriate modals to org_admin users.
- **Org_Admin**: A user with the `org_admin` role who manages an organisation within the platform.
- **Blocking_Modal**: A full-screen, non-dismissible modal overlay that prevents the user from interacting with any part of the application until the required action is completed.
- **Warning_Modal**: A dismissible modal overlay that alerts the user to an upcoming issue but allows them to continue using the application after acknowledgement.
- **Payment_Method_Status_API**: A backend endpoint that returns the payment method status for the authenticated user's organisation, including whether any payment method exists and whether any are expiring soon.
- **Expiring_Soon**: A payment method whose card expiry date falls within 30 days of the current date.
- **OrgPaymentMethod**: The existing SQLAlchemy model (`org_payment_methods` table) that stores Stripe payment method metadata per organisation, including `exp_month`, `exp_year`, `brand`, `last4`, and `is_default`.

## Requirements

### Requirement 1: Payment Method Status Check on Login

**User Story:** As an org admin, I want the system to check my organisation's payment method status after I log in, so that I am immediately informed if action is needed.

#### Acceptance Criteria

1. WHEN an Org_Admin user successfully authenticates, THE Payment_Method_Enforcement_System SHALL query the Payment_Method_Status_API to retrieve the organisation's payment method status.
2. WHEN a user with a role other than org_admin successfully authenticates, THE Payment_Method_Enforcement_System SHALL skip the payment method status check entirely.
3. THE Payment_Method_Status_API SHALL return a response containing: whether the organisation has at least one payment method, whether any payment method is expiring within 30 days, and the details (brand, last4, exp_month, exp_year) of the soonest-expiring method if applicable.
4. IF the Payment_Method_Status_API request fails, THEN THE Payment_Method_Enforcement_System SHALL allow the user to proceed to the application and log the error for observability (graceful degradation per performance-and-resilience steering).
5. THE frontend SHALL use `AbortController` cleanup in the `useEffect` that fetches payment method status, to prevent race conditions on rapid navigation or React StrictMode double-firing (per safe-api-consumption steering, ISSUE-014 pattern).
6. THE frontend SHALL guard all response field access with optional chaining (`?.`) and nullish coalescing (`?? fallback`) per safe-api-consumption steering — e.g. `res.data?.has_payment_method ?? true` (fail-open on malformed response).

### Requirement 2: Blocking Modal for Missing Payment Method

**User Story:** As a platform operator, I want org admins without a payment method to be blocked from using the app until they add one, so that all active organisations have a valid billing method on file.

#### Acceptance Criteria

1. WHEN the Payment_Method_Status_API indicates the organisation has no payment method, THE Payment_Method_Enforcement_System SHALL display the Blocking_Modal to the Org_Admin user.
2. WHILE the Blocking_Modal is displayed, THE Payment_Method_Enforcement_System SHALL prevent the Org_Admin user from navigating to any application page, clicking any navigation element, or interacting with any content behind the modal.
3. WHILE the Blocking_Modal is displayed, THE Payment_Method_Enforcement_System SHALL NOT provide a close button, dismiss action, or any mechanism to bypass the modal without adding a payment method.
4. THE Blocking_Modal SHALL display a clear message explaining that a payment method is required to continue using the application.
5. THE Blocking_Modal SHALL contain a form or action that allows the Org_Admin user to add a payment card using the existing Stripe SetupIntent flow.
6. WHEN the Org_Admin user successfully adds a payment method through the Blocking_Modal, THE Payment_Method_Enforcement_System SHALL dismiss the Blocking_Modal and allow the user to proceed to the application.
7. THE Blocking_Modal SHALL NOT display masked credential values (e.g. `sk_live_****`) or any Stripe secret keys in the UI or error messages (per security-hardening-checklist steering, Section 2).

### Requirement 3: Warning Modal for Expiring Payment Method

**User Story:** As an org admin, I want to be warned when my payment method is about to expire, so that I can update it before billing fails.

#### Acceptance Criteria

1. WHEN the Payment_Method_Status_API indicates a payment method is expiring within 30 days and the organisation has at least one payment method, THE Payment_Method_Enforcement_System SHALL display the Warning_Modal to the Org_Admin user.
2. THE Warning_Modal SHALL display the brand, last four digits, and expiry date of the soonest-expiring payment method.
3. THE Warning_Modal SHALL provide a button that navigates the Org_Admin user to the Settings page where payment methods are managed.
4. THE Warning_Modal SHALL provide a dismiss button that closes the modal and allows the Org_Admin user to continue using the application.
5. WHEN the Org_Admin user logs in and a payment method is still expiring within 30 days, THE Payment_Method_Enforcement_System SHALL display the Warning_Modal on every login session until the expiring payment method is updated or removed.
6. WHILE the Blocking_Modal is displayed (no payment method), THE Payment_Method_Enforcement_System SHALL NOT display the Warning_Modal simultaneously.

### Requirement 4: Payment Method Status API Endpoint

**User Story:** As a frontend developer, I want a lightweight API endpoint that returns the payment method enforcement status, so that the frontend can determine which modal to show without fetching the full billing dashboard.

#### Acceptance Criteria

1. THE Payment_Method_Status_API SHALL be accessible at `GET /billing/payment-method-status`.
2. THE Payment_Method_Status_API SHALL return a JSON response with a Pydantic response model containing: `has_payment_method` (boolean), `has_expiring_soon` (boolean), and `expiring_method` (object with `brand`, `last4`, `exp_month`, `exp_year` fields, or null). The frontend SHALL match these field names exactly (per frontend-backend-contract-alignment steering, Rule 1).
3. THE Payment_Method_Status_API SHALL define "expiring soon" as a payment method whose card expiry date (last day of exp_month/exp_year) falls within 30 days of the current UTC date.
4. THE Payment_Method_Status_API SHALL require authentication and extract the organisation context from the authenticated user's JWT token. It SHALL handle `org_id = None` gracefully for platform-level roles (per security-hardening-checklist steering, Section 4).
5. IF the authenticated user does not belong to an organisation, THEN THE Payment_Method_Status_API SHALL return `{ has_payment_method: true, has_expiring_soon: false, expiring_method: null }` (safe default — no enforcement for users without org context).
6. THE Payment_Method_Status_API SHALL query only the local `org_payment_methods` table and SHALL NOT make external Stripe API calls, to keep the endpoint fast and suitable for every login (per performance-and-resilience steering, Section 4 — cache/avoid external calls on hot paths).
7. THE Payment_Method_Status_API response SHALL NOT leak any Stripe secret keys, payment method tokens, or internal IDs beyond `brand`, `last4`, `exp_month`, `exp_year` (per security-hardening-checklist steering, Section 2).
8. THE Payment_Method_Status_API error responses SHALL NOT leak stack traces, SQL queries, or internal file paths (per performance-and-resilience steering, Section 6).

### Requirement 5: Role-Based Enforcement Scope

**User Story:** As a platform operator, I want payment method enforcement to apply only to org_admin users, so that other user roles are not disrupted by billing concerns.

#### Acceptance Criteria

1. WHEN a user with the `global_admin` role logs in, THE Payment_Method_Enforcement_System SHALL NOT check payment method status or display any payment-related modals. Global admins have no `org_id` and must be handled gracefully (per security-hardening-checklist steering, Section 1 and 4).
2. WHEN a user with the `salesperson` role logs in, THE Payment_Method_Enforcement_System SHALL NOT check payment method status or display any payment-related modals.
3. WHEN a user with the `branch_admin` role logs in, THE Payment_Method_Enforcement_System SHALL NOT check payment method status or display any payment-related modals.
4. WHEN a user with the `kiosk` role logs in, THE Payment_Method_Enforcement_System SHALL NOT check payment method status or display any payment-related modals.
5. THE Payment_Method_Enforcement_System SHALL determine the user's role from the AuthContext provided by the existing JWT-based authentication system.
6. IF a new role is added in the future, THE Payment_Method_Enforcement_System SHALL default to NOT enforcing payment method checks for unknown roles (fail-open for non-billing roles, per security-hardening-checklist steering, Section 4 — audit all role lists when adding new roles).

### Requirement 6: End-to-End Testing

**User Story:** As a developer, I want automated tests that verify the payment method enforcement flow, so that regressions are caught before deployment.

#### Acceptance Criteria

1. AN end-to-end test script SHALL be created at `scripts/test_payment_method_enforcement_e2e.py` following the feature-testing-workflow steering pattern.
2. THE test script SHALL verify: the status API returns correct results for orgs with and without payment methods, the API handles missing org context gracefully, and role-based scoping works correctly.
3. THE test script SHALL include OWASP security checks: unauthenticated access returns 401, cross-org access is blocked, error responses do not leak internals (per feature-testing-workflow steering).
4. THE test script SHALL clean up any test data it creates.
