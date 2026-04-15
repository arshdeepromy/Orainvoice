# Requirements Document — Org Security Settings

## Introduction

This feature adds a comprehensive Security Settings section to the organisation Settings page in OraInvoice. It consolidates MFA enforcement, password policies, account lockout configuration, custom roles and permissions, session management, and a security audit log viewer into a single admin-facing UI. The goal is to move hardcoded security parameters into org-level configurable settings, align with PCI DSS and ISO 27001 compliance patterns, and introduce a dynamic permission system derived from the module registry.

### Current State (from codebase investigation)

- **MFA**: Simple `mfa_policy` toggle (`optional` | `mandatory`) stored in `organisations.settings` JSONB. Enforced in `mfa_service.user_requires_mfa_setup()`. No per-role or per-user exclusion support.
- **Lockout**: Hardcoded constants in `auth/service.py`: `TEMP_LOCK_THRESHOLD = 5`, `TEMP_LOCK_MINUTES = 15`, `PERMANENT_LOCK_THRESHOLD = 10`. Not configurable per-org.
- **Password**: `bcrypt` hashing via `auth/password.py`. No minimum length, complexity, expiry, or history enforcement.
- **Roles**: Hardcoded in DB CHECK constraint `ck_users_role` and `ROLE_PERMISSIONS` dict in `auth/rbac.py`. Current roles: `global_admin`, `franchise_admin`, `org_admin`, `branch_admin`, `location_manager`, `salesperson`, `staff_member`, `kiosk`. No custom roles.
- **Sessions**: `sessions` table tracks `device_type`, `browser`, `ip_address`, `expires_at`. Expiry driven by `access_token_expire_minutes` (30) and `refresh_token_expire_days` (7) in `config.py`. Not configurable per-org. `max_sessions_per_user = 5` is global.
- **Audit Log**: `audit_log` table with `action`, `entity_type`, `ip_address`, `device_info`, `created_at`. Append-only (UPDATE/DELETE revoked at DB level). Events logged: `auth.login_success`, `auth.login_failed_*`, `org.mfa_policy_updated`, subscription events. No org-admin-facing viewer exists (only global admin via admin panel).
- **Modules**: `module_registry` table with `slug`, `display_name`, `category`. `ROLE_PERMISSIONS` in `rbac.py` is a static dict — not derived from enabled modules.

## Glossary

- **Security_Settings_Page**: The new "Security" section within the org Settings page, accessible to Org_Admin users.
- **Org_Admin**: A user with the `org_admin` role who manages organisation-level settings.
- **MFA_Policy_Engine**: The backend logic that evaluates MFA enforcement rules per user based on org-level MFA configuration.
- **Password_Policy_Engine**: The backend logic that validates passwords against the org-configured password policy rules.
- **Lockout_Policy_Engine**: The backend logic that enforces account lockout based on org-configured thresholds.
- **Permission_Registry**: A dynamic system that derives available permissions from the `module_registry` table and enabled modules, replacing the static `ROLE_PERMISSIONS` dict.
- **Custom_Role**: An org-defined role with a custom set of permissions selected from the Permission_Registry.
- **Session_Policy_Engine**: The backend logic that enforces session timeout and expiry based on org-level configuration.
- **Security_Audit_Log_Viewer**: The frontend component that displays security-related audit log entries filtered for the current organisation.
- **Org_Security_Settings**: The JSONB payload within `organisations.settings` that stores all security configuration for an organisation.

## Requirements

### Requirement 1: MFA Enforcement Configuration

**User Story:** As an Org_Admin, I want to configure MFA enforcement granularly (all users, admins only, or with specific user exclusions), so that I can balance security with usability for my organisation.

#### Acceptance Criteria

1. WHEN an Org_Admin opens the Security_Settings_Page, THE Security_Settings_Page SHALL display the current MFA enforcement mode with options: `optional`, `mandatory_all`, `mandatory_admins_only`.
2. WHEN an Org_Admin selects `mandatory_all`, THE MFA_Policy_Engine SHALL require MFA setup for all users in the organisation before granting access to protected resources.
3. WHEN an Org_Admin selects `mandatory_admins_only`, THE MFA_Policy_Engine SHALL require MFA setup only for users with `org_admin` or `branch_admin` roles.
4. WHEN an Org_Admin selects `optional`, THE MFA_Policy_Engine SHALL allow users to optionally configure MFA without enforcement.
5. WHEN an Org_Admin adds a user to the MFA exclusion list, THE MFA_Policy_Engine SHALL skip MFA enforcement for that specific user regardless of the enforcement mode.
6. WHEN an Org_Admin changes the MFA enforcement mode, THE Security_Settings_Page SHALL write an audit log entry with the previous and new policy values.
7. IF an Org_Admin attempts to exclude themselves from MFA while the policy is `mandatory_admins_only` or `mandatory_all`, THEN THE Security_Settings_Page SHALL reject the request with an error message.

### Requirement 2: Password Policy Configuration

**User Story:** As an Org_Admin, I want to define password policies for my organisation, so that user passwords meet security standards aligned with PCI DSS requirements.

#### Acceptance Criteria

1. THE Security_Settings_Page SHALL display configurable password policy fields: minimum length (8–128 characters), require uppercase, require lowercase, require digit, require special character.
2. WHEN an Org_Admin saves a password policy, THE Org_Security_Settings SHALL store the policy in the `organisations.settings` JSONB field under a `password_policy` key.
3. WHEN a user sets or changes a password, THE Password_Policy_Engine SHALL validate the password against the organisation's configured password policy.
4. WHEN a password fails validation, THE Password_Policy_Engine SHALL return a descriptive error listing each unmet requirement.
5. THE Security_Settings_Page SHALL display a configurable password expiry field (0–365 days, where 0 means no expiry).
6. WHEN password expiry is configured and a user's password age exceeds the configured days, THE Password_Policy_Engine SHALL force the user to change their password on next login.
7. THE Security_Settings_Page SHALL display a configurable password history count (0–24, where 0 means no history check).
8. WHEN password history is configured, THE Password_Policy_Engine SHALL reject passwords that match any of the last N password hashes stored for that user.
9. WHEN an Org_Admin saves password policy changes, THE Security_Settings_Page SHALL write an audit log entry with the previous and new policy values.

### Requirement 3: Account Lockout Policy Configuration

**User Story:** As an Org_Admin, I want to configure account lockout thresholds and durations, so that I can protect against brute-force attacks while controlling the lockout behaviour for my organisation.

#### Acceptance Criteria

1. THE Security_Settings_Page SHALL display configurable lockout fields: max failed attempts before temporary lock (3–10), temporary lockout duration in minutes (5–60), max failed attempts before permanent lock (5–20).
2. WHEN an Org_Admin saves lockout policy settings, THE Org_Security_Settings SHALL store the values in the `organisations.settings` JSONB field under a `lockout_policy` key.
3. WHEN a user reaches the configured temporary lock threshold, THE Lockout_Policy_Engine SHALL lock the account for the configured duration in minutes.
4. WHEN a user reaches the configured permanent lock threshold, THE Lockout_Policy_Engine SHALL deactivate the account and send a lockout notification email.
5. WHEN no org-level lockout policy is configured, THE Lockout_Policy_Engine SHALL use the current hardcoded defaults (5 temporary, 15 minutes, 10 permanent) as fallback values.
6. WHEN an Org_Admin saves lockout policy changes, THE Security_Settings_Page SHALL write an audit log entry with the previous and new policy values.
7. IF an Org_Admin sets the permanent lock threshold to a value less than or equal to the temporary lock threshold, THEN THE Security_Settings_Page SHALL reject the configuration with a validation error.

### Requirement 4: Custom Roles and Dynamic Permissions

**User Story:** As an Org_Admin, I want to create custom roles with specific permissions derived from enabled modules, so that I can assign fine-grained access control without relying on hardcoded roles.

#### Acceptance Criteria

1. THE Permission_Registry SHALL derive available permissions from the `module_registry` table, generating permission keys in the format `{module_slug}.{action}` (e.g., `invoices.create`, `inventory.read`).
2. WHEN a new module is added to the `module_registry` table, THE Permission_Registry SHALL automatically include permissions for that module without code changes.
3. THE Security_Settings_Page SHALL display a role management interface listing all built-in roles and any custom roles created for the organisation.
4. WHEN an Org_Admin creates a custom role, THE Security_Settings_Page SHALL present a permission picker grouped by module, showing only permissions for modules enabled for the organisation.
5. WHEN an Org_Admin saves a custom role, THE Security_Settings_Page SHALL store the role definition in a new `custom_roles` table with columns: `id`, `org_id`, `name`, `slug`, `permissions` (JSONB array of permission keys), `created_by`, `created_at`, `updated_at`.
6. WHEN a user is assigned a custom role, THE Permission_Registry SHALL evaluate that user's permissions from the custom role's permission list instead of the static `ROLE_PERMISSIONS` dict.
7. WHEN a module is disabled for an organisation, THE Permission_Registry SHALL exclude permissions for that module from all custom roles in that organisation, without deleting the permission entries from the role definition.
8. THE Security_Settings_Page SHALL prevent deletion of built-in roles (`global_admin`, `org_admin`, `branch_admin`, `location_manager`, `salesperson`, `staff_member`, `kiosk`, `franchise_admin`).
9. IF an Org_Admin attempts to delete a custom role that is currently assigned to one or more users, THEN THE Security_Settings_Page SHALL display the count of affected users and require confirmation before proceeding.
10. WHEN an Org_Admin creates, updates, or deletes a custom role, THE Security_Settings_Page SHALL write an audit log entry with the role details.

### Requirement 5: Session Management Configuration

**User Story:** As an Org_Admin, I want to configure session timeout and expiry policies, so that I can enforce session security appropriate for my organisation's risk profile.

#### Acceptance Criteria

1. THE Security_Settings_Page SHALL display configurable session fields: access token lifetime in minutes (5–120), refresh token lifetime in days (1–90), maximum concurrent sessions per user (1–10).
2. WHEN an Org_Admin saves session policy settings, THE Org_Security_Settings SHALL store the values in the `organisations.settings` JSONB field under a `session_policy` key.
3. WHEN a user authenticates, THE Session_Policy_Engine SHALL use the org-level session policy values instead of the global `access_token_expire_minutes` and `refresh_token_expire_days` from `config.py`.
4. WHEN no org-level session policy is configured, THE Session_Policy_Engine SHALL fall back to the global settings from `config.py`.
5. WHEN an Org_Admin adds a user or role to the session timeout exclusion list, THE Session_Policy_Engine SHALL use the global default session settings for that user or role instead of the org-level policy.
6. WHEN an Org_Admin saves session policy changes, THE Security_Settings_Page SHALL write an audit log entry with the previous and new policy values.
7. WHEN the maximum concurrent sessions per user is reduced, THE Session_Policy_Engine SHALL revoke the oldest sessions exceeding the new limit at the next login for each affected user.

### Requirement 6: Security Audit Log Viewer

**User Story:** As an Org_Admin, I want to view security-related audit log entries for my organisation, so that I can monitor login activity, failed attempts, password changes, and policy modifications.

#### Acceptance Criteria

1. THE Security_Audit_Log_Viewer SHALL display audit log entries filtered to the current organisation and to security-related actions (actions starting with `auth.` or `org.mfa_policy_updated` or `org.security_settings_updated`).
2. THE Security_Audit_Log_Viewer SHALL display for each entry: timestamp, user email (resolved from `user_id`), action description, IP address, browser and OS (parsed from `device_info`), and entity details.
3. THE Security_Audit_Log_Viewer SHALL support filtering by date range, action type, and user.
4. THE Security_Audit_Log_Viewer SHALL support pagination with a configurable page size (25, 50, 100 entries per page).
5. WHEN an Org_Admin views the Security_Audit_Log_Viewer, THE Security_Audit_Log_Viewer SHALL load the most recent entries first (descending by `created_at`).
6. THE Security_Audit_Log_Viewer SHALL display a human-readable description for each action (e.g., `auth.login_success` displayed as "Successful Login", `auth.login_failed_invalid_password` displayed as "Failed Login — Invalid Password").
7. IF the audit log contains more than 10,000 entries for the selected filters, THEN THE Security_Audit_Log_Viewer SHALL limit the query to the most recent 10,000 entries and display a notice to the Org_Admin.

### Requirement 7: Security Settings API Endpoints

**User Story:** As a developer, I want well-structured API endpoints for reading and updating security settings, so that the frontend can interact with the security configuration reliably.

#### Acceptance Criteria

1. THE Security_Settings_Page SHALL provide a `GET /api/v1/org/security-settings` endpoint that returns the complete security settings object (MFA policy, password policy, lockout policy, session policy, MFA exclusions, session exclusions).
2. THE Security_Settings_Page SHALL provide a `PUT /api/v1/org/security-settings` endpoint that accepts partial updates to any security settings section.
3. WHEN the `PUT` endpoint receives a request, THE Security_Settings_Page SHALL validate all fields against their allowed ranges before persisting.
4. THE Security_Settings_Page SHALL restrict both endpoints to users with the `org_admin` role using the existing `require_role("org_admin")` dependency.
5. THE Security_Settings_Page SHALL provide a `GET /api/v1/org/security-audit-log` endpoint that returns paginated, filtered audit log entries for the current organisation.
6. THE Security_Settings_Page SHALL provide `GET /api/v1/org/roles` and `POST /api/v1/org/roles` endpoints for listing and creating custom roles.
7. THE Security_Settings_Page SHALL provide `PUT /api/v1/org/roles/{role_id}` and `DELETE /api/v1/org/roles/{role_id}` endpoints for updating and deleting custom roles.
8. THE Security_Settings_Page SHALL provide a `GET /api/v1/org/permissions` endpoint that returns the dynamically generated permission list from the Permission_Registry, grouped by module.

### Requirement 8: Compliance Alignment

**User Story:** As an Org_Admin, I want the security settings to align with PCI DSS and ISO 27001 requirements, so that my organisation can meet compliance obligations.

#### Acceptance Criteria

1. THE Password_Policy_Engine SHALL enforce a minimum password length of 8 characters as the lowest configurable value, aligning with PCI DSS Requirement 8.3.6.
2. THE Lockout_Policy_Engine SHALL enforce a minimum temporary lockout duration of 5 minutes, aligning with PCI DSS Requirement 8.3.4.
3. THE Security_Audit_Log_Viewer SHALL retain audit log entries for a minimum of 12 months, aligning with PCI DSS Requirement 10.7.
4. THE Session_Policy_Engine SHALL enforce a maximum access token lifetime of 120 minutes, aligning with PCI DSS Requirement 8.2.8.
5. WHEN password expiry is enabled, THE Password_Policy_Engine SHALL enforce a maximum expiry period of 365 days.
6. THE Security_Settings_Page SHALL display compliance guidance tooltips next to each configurable field, indicating the recommended value for PCI DSS compliance.

### Requirement 9: Settings Page Navigation Integration

**User Story:** As an Org_Admin, I want the Security section to appear in the Settings page navigation, so that I can access all security configuration from a single location.

#### Acceptance Criteria

1. THE Security_Settings_Page SHALL appear as a new navigation item labelled "Security" with a lock icon (🔒) in the Settings sidebar, positioned after "Users" and before "Billing".
2. WHEN a non-admin user views the Settings page, THE Security_Settings_Page navigation item SHALL be hidden.
3. THE Security_Settings_Page SHALL organise settings into collapsible sections: MFA Enforcement, Password Policy, Account Lockout, Roles & Permissions, Session Management, Audit Log.
4. WHEN the Security_Settings_Page loads, THE Security_Settings_Page SHALL fetch the current security settings from the `GET /api/v1/org/security-settings` endpoint.
5. WHEN an Org_Admin saves changes in any section, THE Security_Settings_Page SHALL send only the modified section to the `PUT /api/v1/org/security-settings` endpoint and display a success or error toast.
