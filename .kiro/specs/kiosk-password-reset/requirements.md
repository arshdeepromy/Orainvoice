# Requirements: Kiosk User Password Reset by Org Admin

## Overview

As an org admin user, I should be able to reset the password for a kiosk user from the User Management page so that I can regain access to the kiosk tablet without needing the old password or relying on email-based reset flows.

## Requirements

### 1. UI — Reset Password Button

- 1.1 A "Reset Password" button SHALL be displayed in the actions column for users with role "kiosk" who are active
- 1.2 The "Reset Password" button SHALL NOT be displayed for non-kiosk users (org_admin, salesperson, branch_admin)
- 1.3 The "Reset Password" button SHALL NOT be displayed for inactive/deactivated kiosk users
- 1.4 The button SHALL use a secondary/neutral variant to distinguish it from destructive actions (Deactivate, Delete)

### 2. UI — Reset Password Modal

- 2.1 Clicking "Reset Password" SHALL open a modal dialog with title "Reset Kiosk Password"
- 2.2 The modal SHALL display the target user's email address for confirmation
- 2.3 The modal SHALL contain a "New Password" input field (type=password)
- 2.4 The modal SHALL contain a "Confirm Password" input field (type=password)
- 2.5 The modal SHALL have a "Cancel" button that closes the modal without action
- 2.6 The modal SHALL have a "Reset Password" submit button
- 2.7 The submit button SHALL be disabled until both password fields have at least 8 characters and match

### 3. Frontend Validation

- 3.1 The frontend SHALL validate that the new password is at least 8 characters
- 3.2 The frontend SHALL validate that the password and confirm password fields match
- 3.3 The frontend SHALL display inline validation errors when requirements are not met
- 3.4 The frontend SHALL NOT submit the form if validation fails

### 4. Backend Endpoint

- 4.1 The backend SHALL expose `POST /api/v1/org/users/{target_user_id}/reset-password`
- 4.2 The endpoint SHALL require the `org_admin` role (return 403 otherwise)
- 4.3 The endpoint SHALL accept a JSON body with field `new_password` (string, min 8, max 128 chars)
- 4.4 The endpoint SHALL return 200 with `{message, user_id, sessions_invalidated}` on success
- 4.5 The endpoint SHALL use `KioskPasswordResetResponse` as the `response_model`

### 5. Backend Validation & Authorization

- 5.1 The endpoint SHALL verify the target user exists and belongs to the same organisation as the caller
- 5.2 The endpoint SHALL return 404 if the target user is not found or belongs to a different org
- 5.3 The endpoint SHALL verify the target user has role "kiosk"
- 5.4 The endpoint SHALL return 400 if the target user is not a kiosk user
- 5.5 The endpoint SHALL verify the target user is active (is_active=True)
- 5.6 The endpoint SHALL return 400 if the target user is inactive

### 6. Password Update

- 6.1 The backend SHALL hash the new password using bcrypt (via `hash_password()`)
- 6.2 The backend SHALL update the target user's `password_hash` field in the database
- 6.3 The backend SHALL NOT require the old/current password (admin override)

### 7. Session Invalidation

- 7.1 After a successful password reset, the backend SHALL delete all active sessions for the target user
- 7.2 The response SHALL include the count of sessions invalidated
- 7.3 Session invalidation ensures the kiosk tablet must re-authenticate with the new password

### 8. Audit Logging

- 8.1 A successful password reset SHALL write an audit log entry
- 8.2 The audit log action SHALL be `auth.kiosk_password_reset`
- 8.3 The audit log SHALL record the acting admin's user_id and the target user's entity_id
- 8.4 The audit log SHALL record the IP address of the request

### 9. Success Feedback

- 9.1 On successful reset, the modal SHALL close
- 9.2 A success toast SHALL be displayed: "Password reset. Kiosk will need to re-login."
- 9.3 The user list SHALL be refreshed after a successful reset

### 10. Error Feedback

- 10.1 On API error, an error toast SHALL display the error detail from the response
- 10.2 The modal SHALL remain open on error so the admin can retry
- 10.3 Network errors SHALL display a generic "Failed to reset password" message
