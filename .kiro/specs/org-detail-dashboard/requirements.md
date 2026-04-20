# Requirements Document

## Introduction

The Organisation Detail Dashboard provides Global Admins with a comprehensive, compliance-safe view of any organisation on the OraInvoice platform. Clicking an organisation row on the Global Admin Organisations page navigates to a dedicated detail page showing the organisation's overview, billing, usage metrics, user management, security and audit information, and the ability to send targeted platform notifications. All data displayed adheres to PCI DSS requirements and privacy boundaries — only aggregate counts and masked payment data are shown, never raw customer PII or invoice content.

## Glossary

- **Dashboard**: The Organisation Detail Dashboard page accessible to Global Admins
- **Global_Admin**: A platform-level administrator with the `global_admin` role
- **Organisation**: A tenant record in the `organisations` table representing a business using OraInvoice
- **Org_List_Page**: The existing Global Admin Organisations page at `/admin/organisations`
- **Detail_Page**: The new organisation detail page at `/admin/organisations/:orgId`
- **Billing_Section**: The section of the Detail_Page displaying billing and payment information
- **Usage_Section**: The section of the Detail_Page displaying aggregate usage metrics
- **User_Section**: The section of the Detail_Page displaying user management information
- **Security_Section**: The section of the Detail_Page displaying security and audit log information
- **Notification_Panel**: The UI component for sending a targeted platform notification to the organisation
- **Payment_Method_Card**: A display component showing masked card details (brand + last 4 digits + expiry only)
- **Audit_Trail**: The append-only `audit_log` table recording all admin and system actions
- **MFA**: Multi-Factor Authentication methods configured per user (TOTP, SMS, Passkeys, backup codes)

## Requirements

### Requirement 1: Clickable Organisation Navigation

**User Story:** As a Global Admin, I want to click on an organisation name in the Organisations list to navigate to a detailed view, so that I can inspect and manage that organisation without leaving the admin interface.

#### Acceptance Criteria

1. WHEN a Global_Admin clicks an organisation name on the Org_List_Page, THE Dashboard SHALL navigate to the Detail_Page at `/admin/organisations/:orgId`
2. THE Detail_Page SHALL display a breadcrumb showing "Organisations > {Organisation Name}"
3. WHEN a Global_Admin clicks the "Organisations" breadcrumb link, THE Dashboard SHALL navigate back to the Org_List_Page
4. THE Detail_Page SHALL display a back button that navigates to the Org_List_Page
5. IF the organisation ID in the URL does not match any existing organisation, THEN THE Detail_Page SHALL display an error message and a link back to the Org_List_Page
6. THE Detail_Page route SHALL be nested under the existing `/admin` route and protected by the `RequireGlobalAdmin` guard

### Requirement 2: Organisation Overview Section

**User Story:** As a Global Admin, I want to see key organisation details at a glance, so that I can quickly understand the organisation's identity and status.

#### Acceptance Criteria

1. THE Dashboard SHALL display the organisation name, current status, and subscription plan name in a header area
2. THE Dashboard SHALL display the organisation signup date formatted in the organisation's locale
3. THE Dashboard SHALL display the business type (sole_trader, partnership, company, trust, or other)
4. THE Dashboard SHALL display the trade category name associated with the organisation
5. THE Dashboard SHALL display the organisation's billing interval (monthly, quarterly, annually)
6. THE Dashboard SHALL display the organisation's current status using the same colour-coded badge scheme as the Org_List_Page (active=green, trial=blue, payment_pending=amber, suspended=red, deleted=neutral)
7. WHEN the organisation has a trial end date, THE Dashboard SHALL display the trial expiry date
8. THE Dashboard SHALL display the organisation's timezone and locale settings

### Requirement 3: Billing Information Section

**User Story:** As a Global Admin, I want to see billing details for an organisation, so that I can diagnose payment issues and understand their subscription state.

#### Acceptance Criteria

1. THE Billing_Section SHALL display the current subscription plan name and monthly price
2. THE Billing_Section SHALL display the billing interval and next billing date
3. THE Billing_Section SHALL display payment method status showing only the card brand, last 4 digits, and expiry month/year
4. THE Billing_Section SHALL never display full card numbers, CVV, full bank account numbers, or Stripe payment method IDs
5. WHEN the organisation has no payment method on file, THE Billing_Section SHALL display "No payment method" with a warning indicator
6. THE Billing_Section SHALL display active coupons applied to the organisation, including coupon code, discount type, discount value, and remaining billing months
7. WHEN the organisation has a storage add-on, THE Billing_Section SHALL display the add-on package name, quantity in GB, and monthly price
8. THE Billing_Section SHALL display a billing history summary showing the count of successful and failed billing receipts in the last 90 days
9. WHEN the organisation has billing failures in the last 90 days, THE Billing_Section SHALL display the most recent failure date and count of failures

### Requirement 4: Usage Metrics Section

**User Story:** As a Global Admin, I want to see aggregate usage metrics for an organisation, so that I can understand their platform utilisation and identify potential issues.

#### Acceptance Criteria

1. THE Usage_Section SHALL display the total number of invoices issued by the organisation
2. THE Usage_Section SHALL display the total number of quotes created by the organisation
3. THE Usage_Section SHALL display the total number of customers belonging to the organisation
4. THE Usage_Section SHALL display the total number of vehicles associated with the organisation
5. THE Usage_Section SHALL display storage used versus storage quota as both a numeric value (e.g. "2.5 / 10 GB") and a visual progress bar
6. WHEN storage usage exceeds 80% of quota, THE Usage_Section SHALL display the progress bar in an amber colour
7. WHEN storage usage exceeds 95% of quota, THE Usage_Section SHALL display the progress bar in a red colour
8. THE Usage_Section SHALL display Carjam lookups used this month versus the plan's included allowance
9. THE Usage_Section SHALL display SMS messages sent this month versus the plan's included SMS quota
10. THE Usage_Section SHALL display only aggregate counts and never display actual invoice content, customer PII, or financial data

### Requirement 5: User Management Section

**User Story:** As a Global Admin, I want to see user details for an organisation, so that I can understand seat utilisation and identify security concerns.

#### Acceptance Criteria

1. THE User_Section SHALL display the number of active users versus the plan's seat limit (e.g. "3 / 5 seats")
2. THE User_Section SHALL display a table of users belonging to the organisation with columns: name, email, role, last login date, and MFA status
3. THE User_Section SHALL display each user's MFA enrollment status as "Enabled" or "Not enrolled"
4. WHEN a user has not logged in within the last 90 days, THE User_Section SHALL highlight that user's row with a visual indicator
5. THE User_Section SHALL display the user's role using the display name (e.g. "Org Admin" instead of "org_admin")
6. WHEN the organisation has reached its seat limit, THE User_Section SHALL display a warning indicator next to the seat count

### Requirement 6: Security and Audit Log Section

**User Story:** As a Global Admin, I want to see security events and admin actions for an organisation, so that I can monitor for suspicious activity and review administrative changes.

#### Acceptance Criteria

1. THE Security_Section SHALL display recent login attempts for the organisation's users, showing user email, success or failure status, IP address, timestamp, and device info
2. THE Security_Section SHALL display login attempts from the last 30 days, limited to the most recent 50 entries
3. THE Security_Section SHALL display recent admin actions performed on the organisation (suspend, reinstate, plan change, coupon applied, delete request), showing action type, performing admin email, timestamp, and IP address
4. THE Security_Section SHALL display admin actions from the last 90 days, limited to the most recent 50 entries
5. THE Security_Section SHALL display action metadata only and never display the actual data values that were changed (before_value and after_value from audit_log)
6. THE Security_Section SHALL display a summary of MFA enrollment across the organisation's users (e.g. "3 of 5 users have MFA enabled")
7. THE Security_Section SHALL display failed payment attempts from the last 90 days, showing date and count

### Requirement 7: Send Targeted Notification

**User Story:** As a Global Admin, I want to send a platform notification targeted to a specific organisation from the detail view, so that I can communicate directly with that organisation's users.

#### Acceptance Criteria

1. THE Detail_Page SHALL provide a "Send Notification" button that opens the Notification_Panel
2. THE Notification_Panel SHALL allow the Global_Admin to enter a notification title, message, severity (info, warning, critical), and type (maintenance, alert, feature, info)
3. WHEN the Global_Admin submits the notification, THE Dashboard SHALL create a platform notification with target_type set to "specific_orgs" and target_value set to the current organisation's ID
4. WHEN the notification is created successfully, THE Dashboard SHALL display a success confirmation and close the Notification_Panel
5. IF the notification creation fails, THEN THE Dashboard SHALL display an error message and keep the Notification_Panel open for correction
6. THE Notification_Panel SHALL pre-fill the target organisation and not allow changing the target

### Requirement 8: Compliance and Access Control

**User Story:** As a platform operator, I want all access to organisation detail data to be audit-logged and compliant with PCI DSS, so that the platform meets security and regulatory requirements.

#### Acceptance Criteria

1. WHEN a Global_Admin loads the Detail_Page, THE Dashboard SHALL record an audit log entry with action "org_detail_viewed", entity_type "organisation", and the organisation's ID
2. THE Dashboard SHALL never include full card numbers, CVV, full bank account numbers, or Stripe internal IDs in any API response served to the Detail_Page
3. THE Dashboard SHALL never include actual invoice content, customer personal information, or financial transaction details in any API response served to the Detail_Page
4. THE Detail_Page SHALL only be accessible to users with the `global_admin` role
5. IF a non-global-admin user attempts to access the Detail_Page URL directly, THEN THE Dashboard SHALL redirect the user to the appropriate non-admin landing page

### Requirement 9: Backend API for Organisation Detail

**User Story:** As a Global Admin, I want a single API endpoint that returns all organisation detail data in one request, so that the detail page loads efficiently.

#### Acceptance Criteria

1. THE Admin_API SHALL provide a GET endpoint at `/admin/organisations/{org_id}/detail` that returns the organisation overview, billing, usage, users, and security data
2. THE Admin_API SHALL require the `global_admin` role for the detail endpoint
3. THE Admin_API SHALL return payment method data containing only brand, last 4 digits, expiry month, and expiry year — never the full card number or Stripe payment method ID
4. THE Admin_API SHALL return user data containing name, email, role, last login date, and MFA enrollment status — never password hashes or authentication tokens
5. THE Admin_API SHALL return only aggregate counts for invoices, quotes, customers, and vehicles — never the actual records
6. WHEN the organisation ID does not exist, THE Admin_API SHALL return a 404 status code with a descriptive error message
7. THE Admin_API SHALL record an audit log entry each time the detail endpoint is called

### Requirement 10: Organisation Health Indicators

**User Story:** As a Global Admin, I want to see at-a-glance health indicators for an organisation, so that I can quickly identify organisations that need attention.

#### Acceptance Criteria

1. THE Dashboard SHALL display a health summary with colour-coded indicators for: billing status, storage usage, seat utilisation, and MFA adoption
2. WHEN the organisation has failed payments in the last 30 days, THE Dashboard SHALL display a red billing health indicator
3. WHEN storage usage exceeds 90% of quota, THE Dashboard SHALL display an amber storage health indicator
4. WHEN all user seats are occupied, THE Dashboard SHALL display an amber seat utilisation indicator
5. WHEN fewer than 50% of users have MFA enabled, THE Dashboard SHALL display an amber MFA adoption indicator
6. WHEN the organisation status is "suspended" or "payment_pending", THE Dashboard SHALL display a red overall status indicator

### Requirement 11: Quick Actions

**User Story:** As a Global Admin, I want to perform common administrative actions directly from the detail page, so that I do not need to navigate back to the list to manage an organisation.

#### Acceptance Criteria

1. THE Detail_Page SHALL provide quick action buttons for: suspend, reinstate, change plan, and apply coupon — matching the existing actions available on the Org_List_Page
2. WHEN the organisation status is "active" or "trial", THE Detail_Page SHALL display the "Suspend" action
3. WHEN the organisation status is "suspended", THE Detail_Page SHALL display the "Reinstate" action
4. WHEN a Global_Admin performs a quick action, THE Dashboard SHALL refresh the organisation detail data after the action completes
5. THE Detail_Page SHALL reuse the existing modal dialogs from the Org_List_Page for suspend (with reason), delete (with reason), and plan change actions

### Requirement 12: Layout, Responsiveness, and UI Best Practices

**User Story:** As a Global Admin, I want the organisation detail page to be well-structured and readable without horizontal scrolling or data overflow, so that I can efficiently review information on any screen size.

#### Acceptance Criteria

1. THE Detail_Page SHALL use a sectioned card layout where each data group (overview, billing, usage, users, security, health) is contained in its own bordered card with a clear heading
2. THE Detail_Page SHALL use a responsive grid layout that stacks sections vertically on narrow screens (below 1024px) and arranges them in a two-column grid on wider screens
3. ALL text content within the Detail_Page SHALL be truncated with an ellipsis (`text-overflow: ellipsis; overflow: hidden`) when it exceeds its container width, and SHALL show the full text in a tooltip on hover
4. ALL numeric values SHALL be right-aligned within their containers for consistent readability
5. ALL tables within the Detail_Page (users, audit log, login attempts) SHALL be horizontally scrollable within their card container rather than causing the entire page to scroll horizontally
6. THE Detail_Page SHALL use consistent spacing (padding and margins) matching the existing admin page patterns (Tailwind `space-y-6` between sections, `p-4` or `p-6` within cards)
7. THE Detail_Page SHALL use the existing project UI components (Badge, Button, Spinner, AlertBanner, DataTable, Modal, Input, Select, Toast) and not introduce new component libraries
8. WHEN data is loading, THE Detail_Page SHALL display skeleton placeholders or a spinner within each section rather than showing empty or broken layouts
9. THE Detail_Page SHALL have a maximum content width of `max-w-7xl` centred on the page to prevent content from stretching across ultra-wide monitors
10. ALL progress bars (storage, Carjam, SMS) SHALL display both the visual bar and a numeric label (e.g. "2.5 / 10 GB") so the data is accessible without relying solely on colour
11. THE Detail_Page SHALL group related health indicators in a compact summary row at the top of the page, using icon + label + colour rather than large cards, to avoid pushing content below the fold
12. WHEN a section has no data (e.g. no coupons, no billing failures, no login attempts), THE Detail_Page SHALL display a concise empty state message (e.g. "No active coupons") rather than hiding the section entirely
