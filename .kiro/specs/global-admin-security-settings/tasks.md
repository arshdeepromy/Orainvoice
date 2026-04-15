# Implementation Plan: Global Admin Security Settings

## Overview

This plan implements a dedicated `/admin/security` page in the global admin console, consolidating MFA management, session management, password change, and a platform-wide security audit log into four collapsible sections. The backend work is limited to one new endpoint and service function for the cross-org audit log. The frontend reuses existing components (MfaSettings, PasswordRequirements, PasswordMatch, Collapsible, Pagination) and builds two new components (AdminSecurityPage, PlatformSecurityAuditLogSection).

## Tasks

- [x] 1. Add backend schemas and service for platform security audit log
  - [x] 1.1 Create `PlatformAuditLogEntry` and `PlatformAuditLogPage` Pydantic schemas in `app/modules/auth/security_settings_schemas.py`
    - `PlatformAuditLogEntry` extends `AuditLogEntry` with `org_name: str | None = None`
    - `PlatformAuditLogPage` has `items: list[PlatformAuditLogEntry]`, `total: int`, `page: int`, `page_size: int`, `truncated: bool = False`
    - _Requirements: 7.5_
  - [x] 1.2 Create `get_platform_security_audit_log` function in `app/modules/auth/security_audit_service.py`
    - Mirror the existing `get_security_audit_log` query but remove the `a.org_id = :org_id` WHERE clause
    - Add `LEFT JOIN organisations o ON o.id = a.org_id` and select `o.name AS org_name`
    - Retain the same `SECURITY_ACTION_SQL_FILTER`, pagination, 10,000-entry hard cap, and descending `created_at` ordering
    - Return `PlatformAuditLogPage` with `PlatformAuditLogEntry` items including resolved `user_email` and `org_name`
    - _Requirements: 7.3, 7.4, 7.5, 7.6, 7.7_
  - [x] 1.3 Add `GET /admin/security-audit-log` endpoint in `app/modules/admin/router.py`
    - Gate with `require_role("global_admin")`
    - Accept query parameters: `start_date`, `end_date`, `action`, `user_id`, `page`, `page_size`
    - Call `get_platform_security_audit_log` and return the result
    - _Requirements: 7.1, 7.2, 7.8_
  - [x] 1.4 Write property tests for platform audit log service (Properties 3–7)
    - **Property 3: Platform audit log filter acceptance** — random valid filter combos always return a valid `PlatformAuditLogPage`
    - **Validates: Requirements 7.2**
    - **Property 4: Platform audit log returns cross-org security actions** — security actions from any org appear in results without org_id filtering
    - **Validates: Requirements 7.3**
    - **Property 5: Platform audit log response enrichment** — every entry has resolved `user_email` and `org_name` conforming to `PlatformAuditLogEntry`
    - **Validates: Requirements 7.4, 7.5**
    - **Property 6: Platform audit log 10,000-entry hard cap** — when total exceeds 10,000, `truncated` is `true` and `total` is capped
    - **Validates: Requirements 7.6**
    - **Property 7: Platform audit log ordering invariant** — entries are ordered by `created_at` descending
    - **Validates: Requirements 7.7**
  - [x] 1.5 Write unit tests for the `GET /admin/security-audit-log` endpoint
    - Test auth guard: unauthenticated → 403, org_admin → 403, global_admin → 200
    - Test filter parameters are passed through correctly
    - _Requirements: 7.1, 7.8_

- [x] 2. Checkpoint — Backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Create AdminSecurityPage with MFA, Session, and Password sections
  - [x] 3.1 Create `AdminSecurityPage` component at `frontend/src/pages/admin/AdminSecurityPage.tsx`
    - Render `h1` "Security Settings"
    - Render four `Collapsible` sections in order: MFA Management (`🔐 MFA Management`, `defaultOpen`), Active Sessions (`⏱ Active Sessions`), Change Password (`🔑 Change Password`), Security Audit Log (`📋 Security Audit Log`)
    - Use `useToast` for cross-section notifications
    - Follow the same Collapsible + border styling pattern as `SecuritySettings.tsx`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 3.2 Implement MFA section — embed `MfaSettings` component directly
    - Import and render `MfaSettings` from `@/pages/settings/MfaSettings` inside the MFA Collapsible
    - No wrapper needed — MfaSettings is self-contained with its own loading, error, and success states
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_
  - [x] 3.3 Implement Session Management section inline
    - Fetch `GET /auth/sessions` with AbortController cleanup when section is expanded
    - Display each session with: device type, browser, OS, IP address, creation timestamp, and "current" badge
    - Add "Revoke" button per non-current session calling `DELETE /auth/sessions/{session_id}`
    - Add "Revoke All Other Sessions" button calling `POST /auth/sessions/invalidate-all`
    - Show success toast on revoke, remove revoked session from list
    - Show success toast with count on revoke-all, refresh session list
    - Show error message within section on fetch failure
    - Use `?.` and `?? []` / `?? 0` on all API response property access
    - Use typed generics on `apiClient` calls — no `as any`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 8.1, 8.2, 8.3, 8.4, 8.5_
  - [x] 3.4 Implement Password Change section inline
    - Render form with "Current password", "New password", "Confirm new password" fields
    - Render `PasswordRequirements` below new password field, `PasswordMatch` below confirm field
    - Validate with `allPasswordRulesMet` before calling `POST /auth/change-password`
    - Clear fields and show success message on success
    - Display `response.data.detail` error on failure
    - Disable submit button while request is in progress or required fields are empty
    - Follow the exact pattern from `GlobalAdminProfile.tsx`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 8.1, 8.3, 8.5_
  - [x] 3.5 Write property tests for session display and password validation (Properties 1–2)
    - **Property 1: Session display completeness** — random session data renders all required fields and correct "current" badge
    - **Validates: Requirements 4.2**
    - **Property 2: Password validation gates API call** — if `allPasswordRulesMet` returns false, no API call is triggered
    - **Validates: Requirements 5.4**

- [x] 4. Create PlatformSecurityAuditLogSection component
  - [x] 4.1 Create `PlatformSecurityAuditLogSection` at `frontend/src/components/admin/PlatformSecurityAuditLogSection.tsx`
    - Model closely on existing `SecurityAuditLogSection` component
    - Call `GET /admin/security-audit-log` instead of `/org/security-audit-log`
    - Add "Organisation" column showing `org_name` or "Platform" when null
    - Include same filter controls: date range, action type dropdown, user ID filter, page size selector
    - Use `Pagination` component with default page size of 25
    - Show truncation warning banner when `truncated` is true
    - Show error message within section on fetch failure
    - Use AbortController cleanup in useEffect
    - Use `?.` and `?? []` / `?? 0` on all API response property access
    - Use typed generics on `apiClient` calls — no `as any`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 8.1, 8.2, 8.3, 8.4, 8.5_
  - [x] 4.2 Wire `PlatformSecurityAuditLogSection` into the audit log Collapsible in `AdminSecurityPage`
    - Import and render inside the "📋 Security Audit Log" Collapsible section
    - _Requirements: 2.2, 6.1_

- [x] 5. Checkpoint — Frontend components compile and render
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Wire navigation and routing
  - [x] 6.1 Add "Security" nav item to `AdminLayout` sidebar in `frontend/src/layouts/AdminLayout.tsx`
    - Add `{ to: '/admin/security', label: 'Security' }` to the `adminNavItems` array in the "Configuration" section, after the "Settings" entry
    - Active state highlighting uses existing `sidebar-nav-active` styling automatically via `NavLink`
    - _Requirements: 1.1, 1.2, 1.3_
  - [x] 6.2 Register `/admin/security` route in `frontend/src/App.tsx`
    - Import `AdminSecurityPage` at the top with other admin page imports
    - Add `<Route path="security" element={<SafePage name="admin-security"><AdminSecurityPage /></SafePage>} />` inside the admin route group
    - Route is automatically protected by `RequireGlobalAdmin` wrapper
    - _Requirements: 1.4_

- [x] 7. Final checkpoint — Full integration verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The frontend uses TypeScript/React; the backend uses Python/FastAPI
- All frontend API calls must follow the safe-api-consumption steering patterns (optional chaining, nullish coalescing, AbortController cleanup, typed generics)
- The existing `POST /auth/sessions/invalidate-all` endpoint is used (not `revoke-all` as mentioned in requirements — the design clarifies this)
- Property tests validate universal correctness properties from the design document
- Checkpoints ensure incremental validation at backend and frontend milestones
