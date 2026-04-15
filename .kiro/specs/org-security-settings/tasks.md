# Implementation Plan: Org Security Settings

## Overview

Implement org-level configurable security settings for OraInvoice, replacing hardcoded security parameters with a policy engine pattern. The implementation proceeds incrementally: database migration → Pydantic schemas → policy engines → API endpoints → RBAC integration → frontend UI → wiring. Each step builds on the previous, with property tests validating correctness at each layer.

## Tasks

- [x] 1. Database migration and Pydantic schemas
  - [x] 1.1 Create Alembic migration for new tables and columns
    - Create migration `0140_org_security_settings.py` in `alembic/versions/`
    - Add `custom_roles` table (id, org_id, name, slug, description, permissions JSONB, is_system, created_by, created_at, updated_at) with unique constraint on (org_id, slug) and index on org_id
    - Add `password_history` table (id, user_id, password_hash, created_at) with indexes on user_id and (user_id, created_at DESC)
    - Add `users.password_changed_at` TIMESTAMPTZ column
    - Add `users.custom_role_id` UUID column with FK to custom_roles(id) ON DELETE SET NULL
    - Use `IF NOT EXISTS` patterns per project conventions for idempotency
    - _Requirements: 2.2, 2.7, 2.8, 4.5, 4.6_

  - [x] 1.2 Create Pydantic schemas in `app/modules/auth/security_settings_schemas.py`
    - Implement all schema classes from design: MfaPolicy, PasswordPolicy, LockoutPolicy, SessionPolicy, OrgSecuritySettings, SecuritySettingsUpdate, LockoutPolicyUpdate (with cross-field validator), CustomRoleCreate, CustomRoleUpdate, RoleResponse, PermissionItem, PermissionGroup, AuditLogFilters, AuditLogEntry, AuditLogPage
    - Include all Field constraints (ge, le, min_length, max_length) as specified in design
    - Include ACTION_DESCRIPTIONS mapping dict
    - _Requirements: 1.1, 2.1, 2.5, 2.7, 3.1, 3.7, 5.1, 6.2, 6.4, 7.1, 7.2, 8.1, 8.2, 8.4, 8.5_

  - [x] 1.3 Write property test: Settings validation rejects out-of-range values (Property 18)
    - **Property 18: Settings validation rejects out-of-range values**
    - Generate random values outside each field's allowed range using Hypothesis
    - Verify Pydantic rejects out-of-range values and accepts in-range values for all constrained fields
    - **Validates: Requirements 7.3, 8.1, 8.2, 8.4, 8.5**

  - [x] 1.4 Write property test: Permanent lock threshold must exceed temporary (Property 8)
    - **Property 8: Permanent lock threshold must exceed temporary lock threshold**
    - Generate random pairs of (temp_threshold, permanent_threshold) using Hypothesis
    - Verify LockoutPolicyUpdate rejects when permanent <= temp and accepts when permanent > temp (both within allowed ranges)
    - **Validates: Requirements 3.7**

- [x] 2. Checkpoint - Ensure migration and schema tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implement policy engines
  - [x] 3.1 Implement Security Settings Service in `app/modules/auth/security_settings_service.py`
    - Implement `get_security_settings(db, org_id)` — read from organisations.settings JSONB, merge with defaults
    - Implement `update_security_settings(db, org_id, user_id, updates, ip_address, device_info)` — partial update, validate, persist, write audit log entry with before/after values
    - Follow existing pattern: `flush()` then `refresh()` before returning
    - _Requirements: 7.1, 7.2, 7.3, 9.4, 9.5_

  - [x] 3.2 Write property test: Settings round-trip persistence (Property 6)
    - **Property 6: Security settings round-trip persistence**
    - Generate random valid OrgSecuritySettings objects (all fields within allowed ranges) using Hypothesis
    - Verify saving to JSONB and reading back produces an equivalent object
    - **Validates: Requirements 2.2, 3.2, 5.2**

  - [x] 3.3 Write property test: Partial update preserves unmodified sections (Property 17)
    - **Property 17: Partial settings update preserves unmodified sections**
    - Generate random existing OrgSecuritySettings and a SecuritySettingsUpdate modifying only a subset of sections
    - Verify unmodified sections remain identical after applying the update
    - **Validates: Requirements 7.2**

  - [x] 3.4 Implement MFA Policy Engine — extend `app/modules/auth/mfa_service.py`
    - Add `user_requires_mfa_setup(db, user, org_settings)` that evaluates MFA requirement based on org policy mode, user role, and exclusion list
    - Return false for `optional`, true for `mandatory_all` (unless excluded), true for `mandatory_admins_only` only if user is org_admin or branch_admin (unless excluded)
    - Add validation: reject self-exclusion for org_admin under mandatory modes
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.7_

  - [x] 3.5 Write property test: MFA Policy Engine evaluates correctly (Property 1)
    - **Property 1: MFA Policy Engine evaluates correctly for all users and modes**
    - Generate random users (with various roles), MFA policy modes, and exclusion lists using Hypothesis
    - Verify correct return value for each combination of mode, role, and exclusion status
    - **Validates: Requirements 1.2, 1.3, 1.4, 1.5**

  - [x] 3.6 Write property test: Admin self-exclusion rejection (Property 2)
    - **Property 2: Org_Admin cannot self-exclude from MFA under mandatory modes**
    - Generate random org_admin users and mandatory MFA modes using Hypothesis
    - Verify attempting to add the admin's own ID to the exclusion list is rejected
    - **Validates: Requirements 1.7**

  - [x] 3.7 Implement Password Policy Engine in `app/modules/auth/password_policy.py`
    - Implement `validate_password_against_policy(password, policy)` — return list of unmet requirements
    - Implement `check_password_history(db, user_id, password, history_count)` — bcrypt check against last N hashes, return True if match found
    - Implement `record_password_in_history(db, user_id, password_hash)` — store hash in password_history table
    - Implement `is_password_expired(user, policy)` — check password_changed_at against expiry_days
    - _Requirements: 2.3, 2.4, 2.6, 2.8_

  - [x] 3.8 Write property test: Password validation correctness (Property 3)
    - **Property 3: Password validation returns exactly the unmet requirements**
    - Generate random passwords and password policies using Hypothesis
    - Verify the error list contains exactly one item per unmet requirement and is empty iff all requirements are satisfied
    - **Validates: Requirements 2.3, 2.4**

  - [x] 3.9 Write property test: Password expiry detection (Property 4)
    - **Property 4: Password expiry detection is correct**
    - Generate random users with password_changed_at timestamps and policies with various expiry_days using Hypothesis
    - Verify is_password_expired returns true iff days since password_changed_at exceeds expiry_days, and always false when expiry_days is 0
    - **Validates: Requirements 2.6**

  - [x] 3.10 Write property test: Password history rejects previously used passwords (Property 5)
    - **Property 5: Password history rejects previously used passwords**
    - Generate random password history lists and history_count values using Hypothesis
    - Verify check_password_history returns true iff candidate matches any of the most recent min(N, history_count) hashes, and always false when history_count is 0
    - **Validates: Requirements 2.8**

  - [x] 3.11 Implement Lockout Policy Engine — refactor constants in `app/modules/auth/service.py`
    - Add `get_lockout_policy(org_settings)` — extract lockout policy from org settings, fall back to hardcoded defaults (5, 15, 10)
    - Update existing lockout logic to use `get_lockout_policy()` instead of hardcoded constants
    - _Requirements: 3.3, 3.4, 3.5_

  - [x] 3.12 Write property test: Lockout engine applies correct thresholds (Property 7)
    - **Property 7: Lockout engine applies correct thresholds**
    - Generate random users, lockout policies, and failed_login_count values using Hypothesis
    - Verify temp lock at temp_lock_threshold, permanent deactivation at permanent_lock_threshold, no lockout below temp_lock_threshold
    - **Validates: Requirements 3.3, 3.4**

  - [x] 3.13 Implement Session Policy Engine — extend `app/modules/auth/jwt.py`
    - Add `get_session_policy(org_settings)` — extract session policy from org settings, fall back to global config values
    - Handle exclusion list: if user ID or role is in excluded list, return global defaults
    - Update session creation to use org-level expiry values
    - _Requirements: 5.3, 5.4, 5.5_

  - [x] 3.14 Write property test: Session policy respects org overrides and exclusions (Property 13)
    - **Property 13: Session policy engine respects org overrides and exclusions**
    - Generate random users, session policies, and exclusion lists using Hypothesis
    - Verify org-level values are used unless user is excluded, in which case global defaults are returned
    - **Validates: Requirements 5.3, 5.4, 5.5**

  - [x] 3.15 Write property test: Session limit enforcement revokes oldest sessions (Property 14)
    - **Property 14: Session limit enforcement revokes oldest sessions**
    - Generate random session lists and max_sessions_per_user values using Hypothesis
    - Verify after enforcement, at most M sessions remain and the revoked ones are the oldest by created_at
    - **Validates: Requirements 5.7**

- [x] 4. Checkpoint - Ensure all policy engine tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement Permission Registry and Custom Roles
  - [x] 5.1 Implement Permission Registry in `app/modules/auth/permission_registry.py`
    - Implement `get_available_permissions(db, org_id)` — derive permissions from module_registry + org_modules, return grouped by module
    - Define STANDARD_ACTIONS = ["create", "read", "update", "delete"]
    - Implement `evaluate_custom_role_permissions(role_permissions, disabled_modules)` — filter out permissions for disabled modules
    - Add Redis caching for permission derivation
    - _Requirements: 4.1, 4.2, 4.4, 4.7_

  - [x] 5.2 Write property test: Permission Registry derives from module registry (Property 9)
    - **Property 9: Permission Registry derives permissions from module registry**
    - Generate random sets of module slugs using Hypothesis
    - Verify generated permission keys follow `{module_slug}.{action}` format for each standard action, and module slugs match exactly
    - **Validates: Requirements 4.1, 4.2**

  - [x] 5.3 Write property test: Disabled modules excluded from custom role permissions (Property 10)
    - **Property 10: Disabled modules are excluded from effective custom role permissions**
    - Generate random permission lists and disabled module sets using Hypothesis
    - Verify returned permissions exclude disabled module prefixes while stored list is unchanged
    - **Validates: Requirements 4.4, 4.7**

  - [x] 5.4 Implement Custom Roles Service in `app/modules/auth/custom_roles_service.py`
    - Implement `list_roles(db, org_id)` — list built-in + custom roles with user counts
    - Implement `create_custom_role(db, org_id, ...)` — create role, write audit log
    - Implement `update_custom_role(db, role_id, ...)` — update role, write audit log
    - Implement `delete_custom_role(db, role_id, ...)` — prevent built-in deletion, check assigned users, write audit log
    - Follow existing pattern: `flush()` then `refresh()` before returning
    - _Requirements: 4.3, 4.5, 4.8, 4.9, 4.10_

  - [x] 5.5 Write property test: Built-in roles cannot be deleted (Property 12)
    - **Property 12: Built-in roles cannot be deleted**
    - Generate random built-in role slugs from the known set using Hypothesis
    - Verify deletion is rejected for all built-in roles
    - **Validates: Requirements 4.8**

  - [x] 5.6 Extend RBAC for custom roles in `app/modules/auth/rbac.py`
    - Extend `enforce_rbac` middleware to check custom_role_id on users
    - When user has custom_role_id, load custom role permissions from custom_roles table
    - Filter permissions through `evaluate_custom_role_permissions()` for disabled modules
    - Built-in roles continue using static ROLE_PERMISSIONS dict unchanged
    - _Requirements: 4.6_

  - [x] 5.7 Write property test: Custom role permissions used for custom role users (Property 11)
    - **Property 11: Custom role permissions are used for users with custom roles**
    - Generate random custom role permission lists using Hypothesis
    - Verify has_permission returns true for permissions in the list and false for those not in the list
    - **Validates: Requirements 4.6**

- [x] 6. Checkpoint - Ensure Permission Registry and Custom Roles tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement Security Audit Log Service
  - [x] 7.1 Implement Security Audit Log Service in `app/modules/auth/security_audit_service.py`
    - Implement `get_security_audit_log(db, org_id, filters)` — query audit_log for security-related actions, paginated
    - Filter to actions with `auth.` prefix or `org.mfa_policy_updated` or `org.security_settings_updated` or `org.custom_role_*`
    - Resolve user_email from user_id (return null for deleted users)
    - Parse device_info into browser/OS (return null if unparseable)
    - Map action keys to human-readable descriptions via ACTION_DESCRIPTIONS
    - Order descending by created_at, limit to 10,000 entries with truncated flag
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 8.3_

  - [x] 7.2 Write property test: Audit log query correctness (Property 15)
    - **Property 15: Audit log query returns only org-scoped security actions in correct order**
    - Generate random audit log entries with various org_ids, actions, and timestamps using Hypothesis
    - Verify all returned entries belong to queried org, have security-related action prefix, match filters, are ordered descending by created_at, and don't exceed page_size
    - **Validates: Requirements 6.1, 6.3, 6.4, 6.5**

  - [x] 7.3 Write property test: Audit log entries contain required fields (Property 16)
    - **Property 16: Audit log entries contain all required fields with human-readable descriptions**
    - Generate random audit log entries with known action keys using Hypothesis
    - Verify response includes timestamp, user_email, action, action_description (non-empty), ip_address, browser, os; and action_description matches ACTION_DESCRIPTIONS for known keys
    - **Validates: Requirements 6.2, 6.6**

- [x] 8. Implement API Router
  - [x] 8.1 Create API router in `app/modules/auth/security_settings_router.py`
    - Implement `GET /api/v1/org/security-settings` — return complete OrgSecuritySettings
    - Implement `PUT /api/v1/org/security-settings` — accept SecuritySettingsUpdate, validate, persist, audit
    - Implement `GET /api/v1/org/security-audit-log` — return paginated AuditLogPage with filters
    - Implement `GET /api/v1/org/roles` — list built-in + custom roles
    - Implement `POST /api/v1/org/roles` — create custom role
    - Implement `PUT /api/v1/org/roles/{role_id}` — update custom role
    - Implement `DELETE /api/v1/org/roles/{role_id}` — delete custom role (with user count check)
    - Implement `GET /api/v1/org/permissions` — return PermissionListResponse grouped by module
    - Gate all endpoints with `require_role("org_admin")`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [x] 8.2 Register router in the FastAPI app
    - Import and include the security_settings_router in the main app router setup
    - _Requirements: 7.1_

  - [x] 8.3 Write property test: Security endpoints reject non-admin users (Property 19)
    - **Property 19: Security endpoints reject non-admin users**
    - Generate random users with non-admin roles using Hypothesis
    - Verify all security settings endpoints return HTTP 403
    - **Validates: Requirements 7.4**

- [x] 9. Checkpoint - Ensure API and audit log tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Integrate policy engines into auth flow
  - [x] 10.1 Wire Password Policy Engine into password change/set flows
    - Update password change endpoints to call `validate_password_against_policy()` before accepting
    - Call `record_password_in_history()` after successful password change
    - Call `check_password_history()` before accepting new password (when history_count > 0)
    - Update `users.password_changed_at` on password change
    - _Requirements: 2.3, 2.4, 2.6, 2.8, 2.9_

  - [x] 10.2 Wire Lockout Policy Engine into login flow
    - Update login handler in `app/modules/auth/service.py` to call `get_lockout_policy(org_settings)` instead of using hardcoded constants
    - Ensure temp lock and permanent lock use org-configured thresholds
    - _Requirements: 3.3, 3.4, 3.5, 3.6_

  - [x] 10.3 Wire Session Policy Engine into session creation
    - Update session/token creation to use `get_session_policy(org_settings)` for expiry values
    - Implement session limit enforcement: revoke oldest sessions exceeding max_sessions_per_user on login
    - _Requirements: 5.3, 5.4, 5.5, 5.7_

  - [x] 10.4 Wire MFA Policy Engine into MFA enforcement
    - Update existing MFA enforcement to use the new `user_requires_mfa_setup()` with org settings
    - Ensure exclusion list and mode-based logic is applied
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 11. Checkpoint - Ensure auth flow integration tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implement frontend Security Settings page
  - [x] 12.1 Create SecuritySettings page and integrate into Settings navigation
    - Create `frontend/src/pages/settings/SecuritySettings.tsx` as the main page component
    - Add `'security'` to `SettingsSection` union type in Settings.tsx
    - Add nav item `{ id: 'security', label: 'Security', icon: '🔒', adminOnly: true }` after 'users' and before 'billing'
    - Add `SecuritySettings` to `SECTION_COMPONENTS` map
    - Fetch current settings from `GET /api/v1/org/security-settings` on load
    - Organise into collapsible sections: MFA Enforcement, Password Policy, Account Lockout, Roles & Permissions, Session Management, Audit Log
    - Hide nav item for non-admin users
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 12.2 Implement MfaEnforcementSection component
    - Create `frontend/src/components/settings/security/MfaEnforcementSection.tsx`
    - MFA mode selector (optional, mandatory_all, mandatory_admins_only)
    - User exclusion list management
    - Save sends only mfa_policy section to PUT endpoint
    - Display compliance guidance tooltips
    - Follow safe API consumption patterns (?.  and ?? fallbacks)
    - _Requirements: 1.1, 1.5, 1.6, 8.6, 9.5_

  - [x] 12.3 Implement PasswordPolicySection component
    - Create `frontend/src/components/settings/security/PasswordPolicySection.tsx`
    - Fields: min_length (8–128), require_uppercase, require_lowercase, require_digit, require_special, expiry_days (0–365), history_count (0–24)
    - Save sends only password_policy section to PUT endpoint
    - Display compliance guidance tooltips
    - _Requirements: 2.1, 2.5, 2.7, 2.9, 8.6_

  - [x] 12.4 Implement LockoutPolicySection component
    - Create `frontend/src/components/settings/security/LockoutPolicySection.tsx`
    - Fields: temp_lock_threshold (3–10), temp_lock_minutes (5–60), permanent_lock_threshold (5–20)
    - Client-side validation: permanent > temporary threshold
    - Save sends only lockout_policy section to PUT endpoint
    - Display compliance guidance tooltips
    - _Requirements: 3.1, 3.6, 3.7, 8.6_

  - [x] 12.5 Implement RolesPermissionsSection component
    - Create `frontend/src/components/settings/security/RolesPermissionsSection.tsx`
    - List built-in + custom roles from `GET /api/v1/org/roles`
    - Create/edit modal with permission picker grouped by module from `GET /api/v1/org/permissions`
    - Prevent deletion of built-in roles (disable delete button)
    - Show user count and confirmation dialog when deleting custom role with assigned users
    - _Requirements: 4.3, 4.4, 4.5, 4.8, 4.9, 4.10_

  - [x] 12.6 Implement SessionPolicySection component
    - Create `frontend/src/components/settings/security/SessionPolicySection.tsx`
    - Fields: access_token_expire_minutes (5–120), refresh_token_expire_days (1–90), max_sessions_per_user (1–10)
    - User/role exclusion list management
    - Save sends only session_policy section to PUT endpoint
    - Display compliance guidance tooltips
    - _Requirements: 5.1, 5.2, 5.5, 5.6, 8.6_

  - [x] 12.7 Implement SecurityAuditLogSection component
    - Create `frontend/src/components/settings/security/SecurityAuditLogSection.tsx`
    - Filterable table: date range, action type, user
    - Paginated with configurable page size (25, 50, 100)
    - Display human-readable action descriptions
    - Show truncation notice when >10,000 entries
    - Use AbortController for API calls in useEffect
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

- [x] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use Hypothesis (already installed — see `.hypothesis/` directory)
- Test file: `tests/test_org_security_settings_property.py` for property tests
- Backend: Python 3.11, FastAPI, SQLAlchemy async. Frontend: React 18, TypeScript, Tailwind CSS, Headless UI
- All new code follows existing patterns: `flush()` then `refresh()` before returning ORM objects, `IF NOT EXISTS` in migrations, safe API consumption in frontend
- The `get_db_session` dependency uses `session.begin()` which auto-commits — use `flush()` not `commit()` in services
- Checkpoints ensure incremental validation
- Policy engines fall back to hardcoded defaults when no org config exists — zero-disruption deployment
