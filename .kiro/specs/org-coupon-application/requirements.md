# Requirements Document

## Introduction

This feature enables Global Admins to apply coupons directly to organisations from the Global Admin Console's Organisations page. Currently, coupons can only be redeemed by organisations themselves during signup or via a public endpoint. This feature adds an admin-initiated coupon application flow with an "Apply Coupon" action button on the Organisations page, a modal for selecting/entering a coupon code, backend validation and application logic, and an in-app notification sent to the target organisation informing them of the coupon benefit applied by Oraflows Limited.

The system already has `Coupon` and `OrganisationCoupon` models, a `redeem_coupon` service function, and a `PlatformNotification` system with targeted delivery (`specific_orgs` target type). This feature builds on those existing foundations.

## Glossary

- **Global_Admin**: A user with the `global_admin` role who manages the platform via the Global Admin Console.
- **Organisation**: A tenant account in the multi-tenant SaaS platform, represented by the `organisations` table.
- **Coupon**: A discount or benefit definition stored in the `coupons` table, with types: `percentage`, `fixed_amount`, or `trial_extension`.
- **OrganisationCoupon**: A join record in `organisation_coupons` linking a coupon to an organisation, tracking application date and billing usage.
- **Admin_Console**: The Global Admin Console frontend, accessible only to Global_Admin users.
- **Organisations_Page**: The page at `/admin/organisations` in the Admin_Console that lists all organisations with management actions.
- **Apply_Coupon_Modal**: A dialog presented to the Global_Admin for selecting a coupon to apply to a specific organisation.
- **Platform_Notification**: An in-app notification delivered via the `platform_notifications` table and displayed as a banner to targeted organisations.
- **Coupon_Benefit_Description**: A human-readable summary of what the coupon provides (e.g., "20% off for 3 months", "$50 off per billing cycle", "14 extra trial days").

## Requirements

### Requirement 1: Apply Coupon Action on Organisations Page

**User Story:** As a Global_Admin, I want to see an "Apply Coupon" action button for each organisation on the Organisations page, so that I can apply coupons to organisations without needing them to redeem codes themselves.

#### Acceptance Criteria

1. WHILE an organisation has a status other than "deleted", THE Organisations_Page SHALL display an "Apply Coupon" button in the actions column for that organisation.
2. WHEN the Global_Admin clicks the "Apply Coupon" button for an organisation, THE Organisations_Page SHALL open the Apply_Coupon_Modal pre-populated with the selected organisation's name and ID.

### Requirement 2: Apply Coupon Modal — Coupon Selection

**User Story:** As a Global_Admin, I want to search and select from available active coupons in a modal, so that I can quickly find and apply the right coupon to an organisation.

#### Acceptance Criteria

1. WHEN the Apply_Coupon_Modal opens, THE Apply_Coupon_Modal SHALL display the target organisation's name as a read-only header.
2. WHEN the Apply_Coupon_Modal opens, THE Apply_Coupon_Modal SHALL load and display a list of active coupons from the existing `GET /admin/coupons` endpoint.
3. THE Apply_Coupon_Modal SHALL display each coupon with its code, description, discount type, discount value, and remaining usage count.
4. WHEN the Global_Admin types in the coupon search field, THE Apply_Coupon_Modal SHALL filter the coupon list by code or description matching the search text.
5. WHEN the Global_Admin selects a coupon from the list, THE Apply_Coupon_Modal SHALL highlight the selected coupon and display a Coupon_Benefit_Description preview.
6. WHEN the Global_Admin clicks the "Apply" button with a coupon selected, THE Apply_Coupon_Modal SHALL send the apply request to the backend and display a loading state until the response is received.

### Requirement 3: Backend Coupon Application by Admin

**User Story:** As a Global_Admin, I want the system to validate and apply a coupon to an organisation on my behalf, so that the organisation receives the coupon benefit immediately.

#### Acceptance Criteria

1. WHEN the Admin_Console sends a coupon application request, THE Admin_API SHALL validate that the coupon exists and is active.
2. WHEN the Admin_Console sends a coupon application request, THE Admin_API SHALL validate that the coupon has not expired and has not exceeded its usage limit.
3. WHEN the Admin_Console sends a coupon application request for a coupon already applied to the target organisation, THE Admin_API SHALL return an error indicating the coupon has already been applied.
4. WHEN all validations pass, THE Admin_API SHALL create an `OrganisationCoupon` record with the current timestamp as `applied_at`, increment the coupon's `times_redeemed` counter, and extend the trial period when the coupon type is `trial_extension`.
5. WHEN the coupon is applied successfully, THE Admin_API SHALL write an audit log entry recording the Global_Admin who applied the coupon, the target organisation, and the coupon details.
6. WHEN the coupon is applied successfully, THE Admin_API SHALL return a success response containing the organisation coupon ID and the Coupon_Benefit_Description.
7. IF the coupon does not exist or is inactive, THEN THE Admin_API SHALL return a 404 error with a descriptive message.
8. IF the coupon has expired or reached its usage limit, THEN THE Admin_API SHALL return a 400 error with a descriptive message.
9. IF the coupon has already been applied to the organisation, THEN THE Admin_API SHALL return a 409 error with a descriptive message.

### Requirement 4: In-App Notification on Coupon Application

**User Story:** As an organisation user, I want to receive an in-app notification when a coupon is applied to my organisation by the platform, so that I am aware of the benefit and who applied it.

#### Acceptance Criteria

1. WHEN a coupon is successfully applied to an organisation by a Global_Admin, THE Admin_API SHALL create a Platform_Notification targeted to the specific organisation using the `specific_orgs` target type.
2. THE Platform_Notification SHALL have a title of "Coupon Applied by Oraflows Limited".
3. THE Platform_Notification SHALL have a message containing the Coupon_Benefit_Description (e.g., "You've received a 20% discount on your subscription for the next 3 months" or "Your trial has been extended by 14 days").
4. THE Platform_Notification SHALL have a notification type of "info" and a severity of "info".
5. THE Platform_Notification SHALL be published immediately (published_at set to the current timestamp).
6. WHEN an organisation user logs in or the notification banner refreshes, THE PlatformNotificationBanner SHALL display the coupon notification as a dismissible banner.

### Requirement 5: Coupon Benefit Description Generation

**User Story:** As a Global_Admin or organisation user, I want to see a clear human-readable description of what a coupon provides, so that the benefit is immediately understandable.

#### Acceptance Criteria

1. WHEN the coupon discount type is "percentage", THE System SHALL generate a description in the format "X% discount on your subscription" followed by "for Y months" when duration_months is set, or "ongoing" when duration_months is not set.
2. WHEN the coupon discount type is "fixed_amount", THE System SHALL generate a description in the format "$X off per billing cycle" followed by "for Y months" when duration_months is set, or "ongoing" when duration_months is not set.
3. WHEN the coupon discount type is "trial_extension", THE System SHALL generate a description in the format "Trial extended by X days".

### Requirement 6: Apply Coupon Modal — Success and Error Feedback

**User Story:** As a Global_Admin, I want clear feedback after applying a coupon, so that I know whether the operation succeeded or what went wrong.

#### Acceptance Criteria

1. WHEN the coupon application succeeds, THE Apply_Coupon_Modal SHALL close and THE Organisations_Page SHALL display a success toast notification with the message "Coupon applied to [organisation name]".
2. IF the backend returns a 409 conflict error, THEN THE Apply_Coupon_Modal SHALL display an inline error message stating the coupon has already been applied to this organisation.
3. IF the backend returns a 400 or 404 error, THEN THE Apply_Coupon_Modal SHALL display an inline error message with the backend-provided error detail.
4. IF the backend returns an unexpected error, THEN THE Apply_Coupon_Modal SHALL display a generic error message "Failed to apply coupon. Please try again."

### Requirement 7: Admin Coupon Application Endpoint

**User Story:** As a developer, I want a dedicated admin endpoint for applying coupons to organisations, so that the admin flow is separate from the public redemption flow and includes notification logic.

#### Acceptance Criteria

1. THE Admin_API SHALL expose a `POST /admin/organisations/{org_id}/apply-coupon` endpoint requiring the `global_admin` role.
2. THE endpoint SHALL accept a request body containing the coupon ID (UUID).
3. THE endpoint SHALL reuse the existing coupon validation logic (active check, expiry check, usage limit check, duplicate check) from the `redeem_coupon` service.
4. THE endpoint SHALL return a response containing the organisation coupon ID, the coupon code, the Coupon_Benefit_Description, and a success message.
5. IF the organisation ID in the URL path is not a valid UUID or does not match an existing organisation, THEN THE Admin_API SHALL return a 404 error.
