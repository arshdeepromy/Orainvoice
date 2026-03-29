# Requirements Document

## Introduction

Customer Check-In Kiosk provides a tablet-facing self-service page at `/kiosk` where walk-in customers can register their name, phone, email, and vehicle registration. The data feeds directly into the organisation's existing customer and vehicle records so that staff already have the customer on file when creating invoices or bookings. A new `kiosk` role with severely restricted permissions ensures the tablet can be left unattended in the workshop waiting area without exposing sensitive organisation data.

## Glossary

- **Kiosk_Page**: The standalone React page served at `/kiosk`, rendered outside the main `OrgLayout`, designed for touch interaction on a tablet.
- **Kiosk_Role**: A new user role (`kiosk`) with access limited to customer creation/lookup and vehicle creation/lookup endpoints only.
- **Kiosk_User**: A user account with `role: kiosk`, created by an Org_Admin from the Settings area, scoped to a single organisation.
- **Check_In_Form**: The touch-optimised form displayed on the Kiosk_Page that collects customer and vehicle details.
- **Customer_Record**: An entry in the `customers` table representing an individual customer within an organisation.
- **Vehicle_Record**: An entry in the `org_vehicles` table representing a vehicle within an organisation.
- **Carjam_Lookup**: The existing third-party vehicle data API integration that resolves vehicle details from a registration plate number.
- **Org_Admin**: A user with the `org_admin` role who manages the organisation's settings, staff, and kiosk accounts.
- **Welcome_Screen**: The default idle state of the Kiosk_Page showing the organisation's branding and a single "Check In" button.
- **Success_Screen**: The confirmation view shown after a successful check-in, displaying a thank-you message before auto-resetting.

## Requirements

### Requirement 1: Kiosk Role and Authentication

**User Story:** As an Org_Admin, I want to create a dedicated kiosk user account with severely restricted permissions, so that a tablet in the waiting area can only create or look up customers and vehicles without accessing any other organisation data.

#### Acceptance Criteria

1. THE Auth_System SHALL accept `kiosk` as a valid value in the `role` column of the `users` table.
2. WHEN an Org_Admin creates a new user with `role: kiosk`, THE Auth_System SHALL create a Kiosk_User scoped to the Org_Admin's organisation.
3. WHEN a Kiosk_User authenticates, THE Auth_System SHALL issue a JWT containing `role: kiosk` and the organisation's `org_id`.
4. WHEN a Kiosk_User authenticates, THE Auth_System SHALL issue a refresh token with a 30-day expiry so the tablet remains logged in without frequent re-authentication.
5. THE RBAC_Middleware SHALL restrict Kiosk_User access to only the following endpoints: kiosk check-in (customer create/lookup), vehicle lookup/create, and organisation branding retrieval.
6. WHEN a Kiosk_User attempts to access any endpoint outside the permitted set, THE RBAC_Middleware SHALL return HTTP 403 Forbidden.
7. WHEN an Org_Admin revokes a Kiosk_User session or deactivates the Kiosk_User account, THE Auth_System SHALL invalidate all active sessions for that Kiosk_User within 60 seconds.
8. THE Auth_System SHALL allow multiple Kiosk_User accounts per organisation so that separate tablets can have independent credentials.

### Requirement 2: Kiosk Welcome Screen

**User Story:** As a walk-in customer, I want to see a clear, branded welcome screen on the workshop tablet, so that I know I'm at the right place and can easily start the check-in process.

#### Acceptance Criteria

1. THE Kiosk_Page SHALL be served at the route `/kiosk`, rendered outside the main `OrgLayout` (similar to auth pages).
2. THE Welcome_Screen SHALL display the organisation's logo and name at the top, retrieved from the existing branding endpoint.
3. THE Welcome_Screen SHALL display a welcome message in the format "Welcome to [Organisation Name]".
4. THE Welcome_Screen SHALL display a single large "Check In" button with a minimum tap target of 48×48 CSS pixels.
5. WHEN a customer taps the "Check In" button, THE Kiosk_Page SHALL navigate to the Check_In_Form.
6. THE Welcome_Screen SHALL use a minimum body font size of 18px and a minimum button font size of 22px for readability on a tablet.
7. IF the Kiosk_User session has expired, THEN THE Kiosk_Page SHALL redirect to a login screen where staff can re-authenticate the kiosk.

### Requirement 3: Check-In Form

**User Story:** As a walk-in customer, I want to enter my name, phone number, and optionally my email and vehicle registration, so that the workshop has my details on file before I'm served.

#### Acceptance Criteria

1. THE Check_In_Form SHALL collect the following fields: first name (required), last name (required), phone number (required), email address (optional), and vehicle registration (optional).
2. THE Check_In_Form SHALL validate that first name and last name each contain between 1 and 100 characters.
3. THE Check_In_Form SHALL validate that the phone number matches a recognisable phone format (digits, spaces, hyphens, plus prefix allowed; minimum 7 digits).
4. WHEN an email address is provided, THE Check_In_Form SHALL validate that the email address conforms to a standard email format.
5. THE Check_In_Form SHALL display all input fields with a minimum height of 48px and minimum font size of 18px for touch usability.
6. THE Check_In_Form SHALL display a prominent "Submit" button and a "Back" button to return to the Welcome_Screen.
7. WHEN the customer taps "Submit" with valid data, THE Check_In_Form SHALL send the data to the kiosk check-in backend endpoint.
8. WHILE the check-in request is in progress, THE Check_In_Form SHALL display a loading indicator and disable the Submit button to prevent duplicate submissions.

### Requirement 4: Customer Creation and Matching

**User Story:** As a workshop operator, I want the kiosk to create a new customer record or match an existing one, so that I don't end up with duplicate customer entries.

#### Acceptance Criteria

1. WHEN the kiosk check-in endpoint receives a submission, THE Kiosk_Backend SHALL search for an existing Customer_Record in the organisation by matching on phone number.
2. WHEN an existing Customer_Record matches the submitted phone number, THE Kiosk_Backend SHALL return the existing customer without creating a duplicate.
3. WHEN no existing Customer_Record matches, THE Kiosk_Backend SHALL create a new Customer_Record with the submitted first name, last name, phone, and email.
4. THE Kiosk_Backend SHALL set `customer_type` to `individual` for all kiosk-created Customer_Records.
5. WHEN a vehicle registration is provided and a Customer_Record is resolved, THE Kiosk_Backend SHALL look up the vehicle via the existing Carjam_Lookup integration and link the Vehicle_Record to the Customer_Record.
6. IF the Carjam_Lookup fails or returns no result for the provided registration, THEN THE Kiosk_Backend SHALL create a manual Vehicle_Record with only the registration plate and link it to the Customer_Record.
7. WHEN a vehicle registration is provided and the vehicle already exists in the organisation's records, THE Kiosk_Backend SHALL link the existing Vehicle_Record to the Customer_Record without creating a duplicate vehicle.
8. THE Kiosk_Backend SHALL return a response containing the customer's first name (for the Success_Screen greeting) and a boolean indicating whether the customer was newly created or matched.

### Requirement 5: Success Screen and Auto-Reset

**User Story:** As a walk-in customer, I want to see a confirmation that my check-in was successful, so that I know the workshop has my details and I can take a seat.

#### Acceptance Criteria

1. WHEN the kiosk check-in request succeeds, THE Kiosk_Page SHALL display the Success_Screen with the message "Thanks [First Name], we'll be with you shortly".
2. THE Success_Screen SHALL display a countdown timer showing the seconds remaining before auto-reset.
3. WHEN 10 seconds have elapsed on the Success_Screen, THE Kiosk_Page SHALL automatically navigate back to the Welcome_Screen.
4. THE Success_Screen SHALL display a "Done" button that allows the customer to return to the Welcome_Screen immediately without waiting for the timer.
5. IF the kiosk check-in request fails, THEN THE Kiosk_Page SHALL display a user-friendly error message (e.g., "Something went wrong, please try again") and a "Try Again" button that returns to the Check_In_Form with the previously entered data preserved.

### Requirement 6: Kiosk Security and Isolation

**User Story:** As an Org_Admin, I want the kiosk tablet to be safe to leave unattended in the waiting area, so that a stolen or misused tablet cannot expose sensitive business data.

#### Acceptance Criteria

1. THE RBAC_Middleware SHALL deny Kiosk_User access to all invoice, report, settings, admin, booking, quote, and financial endpoints.
2. THE Kiosk_Page SHALL not render any navigation menus, sidebars, or links to other application areas.
3. THE Kiosk_Page SHALL not store any customer data in browser local storage or session storage beyond the current check-in session.
4. WHEN the Kiosk_Page completes a check-in or returns to the Welcome_Screen, THE Kiosk_Page SHALL clear all form state from memory.
5. THE Kiosk_Backend check-in endpoint SHALL enforce rate limiting of 30 requests per minute per Kiosk_User to prevent abuse.
6. WHEN an Org_Admin views the user management settings, THE Settings_Page SHALL display Kiosk_User accounts with a distinct "Kiosk" badge and provide options to deactivate or revoke sessions.

### Requirement 7: Kiosk User Management

**User Story:** As an Org_Admin, I want to create, manage, and revoke kiosk accounts from the existing Settings area, so that I can control which tablets are authorised without needing a separate admin interface.

#### Acceptance Criteria

1. WHEN an Org_Admin navigates to the user management section in Settings, THE Settings_Page SHALL include a "Kiosk" option in the role selection when creating or editing a user.
2. WHEN creating a Kiosk_User, THE Settings_Page SHALL require only an email and password (no first/last name required, though allowed).
3. WHEN an Org_Admin deactivates a Kiosk_User, THE Auth_System SHALL revoke all active sessions for that Kiosk_User.
4. THE Settings_Page SHALL allow an Org_Admin to view the last activity timestamp for each Kiosk_User to monitor tablet usage.
