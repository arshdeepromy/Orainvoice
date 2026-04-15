# Requirements Document

## Introduction

The Global Admin Security Settings feature adds a dedicated security page to the global admin console (`/admin/security`). Currently, the admin panel has no security settings page — global admins must navigate to their profile page for MFA and password management, and use the general audit log for security event review. This feature consolidates the global admin's personal security posture into a single, purpose-built page with four sections: MFA Management, Platform Security Audit Log, Session Management, and Password Change.

The page reuses existing frontend components (MfaSettings, SecurityAuditLogSection) and backend endpoints (`/auth/mfa/*`, `/auth/sessions`, `/auth/change-password`) where possible, and introduces a new backend endpoint for platform-wide security audit log queries (not scoped to a single org).

## Glossary

- **Global_Admin**: A platform-level user with the `global_admin` role who has no `org_id` and manages the entire OraInvoice platform.
- **Admin_Console**: The global admin panel accessible at `/admin/*`, rendered inside `AdminLayout`.
- **Security_Page**: The new page at `/admin/security` that consolidates all security-related settings for the Global_Admin.
- **MFA_Section**: The collapsible section of the Security_Page that allows the Global_Admin to enrol, disable, and manage personal MFA methods (TOTP, SMS, Email, Passkeys, Backup Codes).
- **Platform_Audit_Log_Section**: The collapsible section of the Security_Page that displays security-related audit events across all organisations and the platform itself.
- **Session_Section**: The collapsible section of the Security_Page that lists the Global_Admin's active sessions and allows revoking individual or all sessions.
- **Password_Section**: The collapsible section of the Security_Page that allows the Global_Admin to change their own password.
- **Collapsible**: A UI component (`@/components/ui/Collapsible`) that wraps content in an expandable/collapsible panel with a label.
- **Platform_Audit_Service**: A new backend service function that queries the `audit_log` table for security-related actions across all organisations (no `org_id` filter) for Global_Admin use.
- **Admin_Sidebar**: The navigation sidebar in `AdminLayout` that lists all admin console pages.

## Requirements

### Requirement 1: Security Page Navigation

**User Story:** As a Global_Admin, I want a "Security" link in the Admin_Sidebar, so that I can quickly access all security settings from the admin console.

#### Acceptance Criteria

1. THE Admin_Sidebar SHALL display a "Security" navigation link under the "Configuration" section, positioned after the "Settings" link.
2. WHEN the Global_Admin clicks the "Security" link, THE Admin_Console SHALL navigate to the `/admin/security` route.
3. WHILE the Global_Admin is on the `/admin/security` route, THE Admin_Sidebar SHALL highlight the "Security" link as active using the existing `sidebar-nav-active` styling.
4. THE Security_Page route SHALL be protected by the `RequireGlobalAdmin` route guard, consistent with all other admin routes.

### Requirement 2: Security Page Layout

**User Story:** As a Global_Admin, I want a well-organised security page with collapsible sections, so that I can focus on the security area I need without visual clutter.

#### Acceptance Criteria

1. THE Security_Page SHALL display a page title of "Security Settings" as an `h1` element.
2. THE Security_Page SHALL render four Collapsible sections in this order: MFA_Section ("🔐 MFA Management"), Session_Section ("⏱ Active Sessions"), Password_Section ("🔑 Change Password"), Platform_Audit_Log_Section ("📋 Security Audit Log").
3. THE MFA_Section SHALL be expanded by default (using the `defaultOpen` prop on Collapsible).
4. THE Session_Section, Password_Section, and Platform_Audit_Log_Section SHALL be collapsed by default.
5. THE Security_Page SHALL use the same Collapsible and border styling pattern as the existing org-level `SecuritySettings.tsx` page.

### Requirement 3: MFA Management Section

**User Story:** As a Global_Admin, I want to manage my personal MFA methods from the security page, so that I can secure my admin account without navigating to a separate profile page.

#### Acceptance Criteria

1. THE MFA_Section SHALL render the existing `MfaSettings` component from `@/pages/settings/MfaSettings`.
2. THE MfaSettings component SHALL call the existing `/auth/mfa/methods` endpoint to load the Global_Admin's MFA method statuses.
3. WHEN the Global_Admin enables a new MFA method (TOTP, SMS, or Email), THE MfaSettings component SHALL open the corresponding enrolment wizard modal (TotpEnrolWizard, SmsEnrolWizard, or EmailEnrolWizard).
4. WHEN the Global_Admin disables an MFA method, THE MfaSettings component SHALL prompt for password confirmation via the PasswordConfirmModal before calling `DELETE /auth/mfa/methods/{method}`.
5. THE MfaSettings component SHALL display the PasskeyManager and BackupCodesPanel sub-components for passkey and backup code management.
6. IF the `/auth/mfa/methods` endpoint returns an error, THEN THE MFA_Section SHALL display an error message within the section without affecting other sections.

### Requirement 4: Session Management Section

**User Story:** As a Global_Admin, I want to view and revoke my active sessions from the security page, so that I can detect and terminate unauthorised access to my admin account.

#### Acceptance Criteria

1. WHEN the Session_Section is expanded, THE Security_Page SHALL call `GET /auth/sessions` to fetch the Global_Admin's active sessions.
2. THE Session_Section SHALL display each active session with: device type, browser name, operating system, IP address, creation timestamp, and a "current" badge for the requesting session.
3. WHEN the Global_Admin clicks "Revoke" on a non-current session, THE Security_Page SHALL call `DELETE /auth/sessions/{session_id}` to revoke that session.
4. WHEN a session is successfully revoked, THE Session_Section SHALL remove the revoked session from the displayed list and show a success toast notification.
5. THE Session_Section SHALL display a "Revoke All Other Sessions" button that calls `POST /auth/sessions/revoke-all` to invalidate all sessions except the current one.
6. WHEN "Revoke All Other Sessions" succeeds, THE Session_Section SHALL refresh the session list and show a success toast notification with the count of revoked sessions.
7. IF the session list endpoint returns an error, THEN THE Session_Section SHALL display an error message within the section.
8. THE Session_Section SHALL use AbortController cleanup in its useEffect to prevent race conditions on unmount.

### Requirement 5: Password Change Section

**User Story:** As a Global_Admin, I want to change my password from the security page, so that I can maintain strong credentials without navigating to my profile.

#### Acceptance Criteria

1. THE Password_Section SHALL render a form with three fields: "Current password", "New password", and "Confirm new password".
2. THE Password_Section SHALL display the `PasswordRequirements` component below the "New password" field to show real-time password strength feedback.
3. THE Password_Section SHALL display the `PasswordMatch` component below the "Confirm new password" field to show whether the passwords match.
4. WHEN the Global_Admin submits the form, THE Security_Page SHALL validate that the new password meets all requirements using the `allPasswordRulesMet` function before calling the API.
5. WHEN validation passes, THE Security_Page SHALL call `POST /auth/change-password` with `{ current_password, new_password }`.
6. WHEN the password change succeeds, THE Password_Section SHALL clear all form fields and display a success message.
7. IF the password change endpoint returns an error, THEN THE Password_Section SHALL display the error detail from the response.
8. THE Password_Section SHALL disable the submit button while the request is in progress and when required fields are empty.

### Requirement 6: Platform Security Audit Log Section

**User Story:** As a Global_Admin, I want to view platform-wide security events (login attempts, MFA changes, password resets, session revocations) across all organisations, so that I can monitor the security posture of the entire platform.

#### Acceptance Criteria

1. THE Platform_Audit_Log_Section SHALL call a new `GET /admin/security-audit-log` endpoint that returns security-related audit events across all organisations.
2. THE Platform_Audit_Log_Section SHALL display the same columns as the existing org-level SecurityAuditLogSection: Timestamp, User, Action, IP Address, Browser, and OS.
3. THE Platform_Audit_Log_Section SHALL include an additional "Organisation" column showing the org name or "Platform" for events with no org_id.
4. THE Platform_Audit_Log_Section SHALL support the same filter controls as the org-level audit log: date range (start/end), action type dropdown, user ID filter, and page size selector.
5. THE Platform_Audit_Log_Section SHALL paginate results using the existing `Pagination` component, with a default page size of 25.
6. WHEN the total matching entries exceed 10,000, THE Platform_Audit_Log_Section SHALL display a truncation warning banner.
7. IF the audit log endpoint returns an error, THEN THE Platform_Audit_Log_Section SHALL display an error message within the section.
8. THE Platform_Audit_Log_Section SHALL use AbortController cleanup in its useEffect to prevent race conditions on unmount.

### Requirement 7: Platform Security Audit Log Backend Endpoint

**User Story:** As a Global_Admin, I want a backend endpoint that returns security audit events across all organisations, so that the Platform_Audit_Log_Section has data to display.

#### Acceptance Criteria

1. THE Backend SHALL expose a `GET /admin/security-audit-log` endpoint gated with `require_role("global_admin")`.
2. THE endpoint SHALL accept the same query parameters as the org-level audit log: `start_date`, `end_date`, `action`, `user_id`, `page`, and `page_size`.
3. THE endpoint SHALL query the `audit_log` table for security-related actions (actions matching `auth.*`, `org.mfa_policy_updated`, `org.security_settings_updated`, `org.custom_role_*`) without filtering by `org_id`.
4. THE endpoint SHALL join with the `users` table to resolve `user_email` and with the `organisations` table to resolve `org_name`.
5. THE endpoint SHALL return the same `AuditLogPage` response schema as the org-level endpoint, with an additional `org_name` field on each entry.
6. THE endpoint SHALL enforce the same 10,000-entry hard cap as the org-level audit log, returning `truncated: true` when the total exceeds the cap.
7. THE endpoint SHALL order results by `created_at` descending (most recent first).
8. IF an unauthenticated or non-global_admin user calls the endpoint, THEN THE Backend SHALL return HTTP 403.

### Requirement 8: Frontend API Safety Compliance

**User Story:** As a developer, I want all API calls on the Security_Page to follow the safe-api-consumption patterns, so that the page does not crash on malformed or missing API responses.

#### Acceptance Criteria

1. THE Security_Page SHALL use optional chaining (`?.`) and nullish coalescing (`?? []`, `?? 0`) on every API response property access, per the safe-api-consumption steering doc.
2. THE Security_Page SHALL use AbortController cleanup in every useEffect that makes API calls.
3. THE Security_Page SHALL use typed generics on all `apiClient` calls — no `as any` type assertions.
4. THE Security_Page SHALL guard all `.map()`, `.filter()`, and `.length` calls on API response arrays with `?? []` fallbacks.
5. THE Security_Page SHALL use the `useToast` hook for error and success notifications, consistent with the existing SecuritySettings page pattern.
