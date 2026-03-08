# Requirements Document

## Introduction

This feature adds the frontend public signup flow that connects to the existing backend `POST /api/v1/auth/signup` and `POST /api/v1/auth/verify-email` endpoints. A new user visits `/signup`, fills in organisation and admin details, selects a plan, submits the form, completes Stripe card collection via the returned SetupIntent, verifies their email and sets a password, and is then routed into the existing Setup Wizard. A "Sign up" link is added to the Login page, and the Login page gains a "Don't have an account?" prompt linking to signup.

## Glossary

- **Signup_Page**: The frontend page component rendered at `/signup` that collects organisation name, admin email, admin first name, admin last name, and plan selection, then submits to the Signup_API.
- **Signup_API**: The existing backend endpoint `POST /api/v1/auth/signup` that creates an organisation, admin user, Stripe customer, and returns a `PublicSignupResponse`.
- **Verify_Email_Page**: The frontend page component rendered at `/verify-email` that accepts a token from the verification email link, collects a password, and submits to the Verify_Email_API.
- **Verify_Email_API**: The existing backend endpoint `POST /api/v1/auth/verify-email` that validates the token, sets the password, verifies the email, and returns JWT tokens.
- **Stripe_Card_Element**: The Stripe.js embedded card collection UI used to confirm the SetupIntent client secret returned by the Signup_API.
- **Setup_Wizard**: The existing 7-step setup wizard at `/setup` that configures the new organisation.
- **Login_Page**: The existing login page at `/login`.
- **GuestOnly_Guard**: The existing route guard that redirects authenticated users away from guest-only pages.
- **App_Router**: The React Router configuration in `App.tsx` that defines all application routes.

## Requirements

### Requirement 1: Signup Page Form

**User Story:** As a prospective customer, I want a public signup page where I can enter my organisation and personal details, so that I can create a new account with a 14-day trial.

#### Acceptance Criteria

1. THE Signup_Page SHALL render a form with fields for organisation name, admin email, admin first name, admin last name, and a plan selector.
2. WHEN the user submits the form with valid data, THE Signup_Page SHALL send a POST request to the Signup_API with the field values.
3. WHEN the Signup_API returns a successful response, THE Signup_Page SHALL store the `signup_token` and proceed to Stripe card collection.
4. IF the Signup_API returns a 400 error, THEN THE Signup_Page SHALL display the error message from the response `detail` field to the user.
5. WHILE the form submission is in progress, THE Signup_Page SHALL disable the submit button and display a loading indicator.
6. THE Signup_Page SHALL validate that organisation name is between 1 and 255 characters before submission.
7. THE Signup_Page SHALL validate that admin email is a valid email format before submission.
8. THE Signup_Page SHALL validate that admin first name and admin last name are between 1 and 100 characters before submission.

### Requirement 2: Stripe Card Collection

**User Story:** As a prospective customer, I want to securely provide my payment card details during signup, so that billing can begin after my trial ends.

#### Acceptance Criteria

1. WHEN the Signup_API returns a successful response, THE Signup_Page SHALL initialise the Stripe_Card_Element using the `stripe_setup_intent_client_secret` from the response.
2. WHEN the user confirms the Stripe_Card_Element, THE Signup_Page SHALL call `stripe.confirmCardSetup` with the client secret.
3. WHEN `stripe.confirmCardSetup` succeeds, THE Signup_Page SHALL display a success message and instruct the user to check their email for a verification link.
4. IF `stripe.confirmCardSetup` fails, THEN THE Signup_Page SHALL display the Stripe error message to the user and allow retry.

### Requirement 3: Email Verification Page

**User Story:** As a new admin user, I want to verify my email and set my password via a link sent to my email, so that I can securely access my new account.

#### Acceptance Criteria

1. THE Verify_Email_Page SHALL render at the `/verify-email` route with a password input field and a confirm-password input field.
2. WHEN the Verify_Email_Page loads, THE Verify_Email_Page SHALL extract the `token` query parameter from the URL.
3. IF the `token` query parameter is missing, THEN THE Verify_Email_Page SHALL display an error message stating the link is invalid.
4. WHEN the user submits a valid password, THE Verify_Email_Page SHALL send a POST request to the Verify_Email_API with the token and password.
5. WHEN the Verify_Email_API returns a successful response containing JWT tokens, THE Verify_Email_Page SHALL store the tokens in the auth context and redirect the user to the Setup_Wizard at `/setup`.
6. IF the Verify_Email_API returns a 400 error, THEN THE Verify_Email_Page SHALL display the error message from the response `detail` field.
7. THE Verify_Email_Page SHALL validate that the password is at least 10 characters long before submission.
8. THE Verify_Email_Page SHALL validate that the password and confirm-password fields match before submission.

### Requirement 4: Signup Route Registration

**User Story:** As a prospective customer, I want to access the signup page at `/signup`, so that I can create a new account without being redirected to login.

#### Acceptance Criteria

1. THE App_Router SHALL register a `/signup` route that renders the Signup_Page.
2. THE App_Router SHALL register a `/verify-email` route that renders the Verify_Email_Page.
3. THE App_Router SHALL wrap the `/signup` route with the GuestOnly_Guard so that authenticated users are redirected to the dashboard.
4. THE App_Router SHALL wrap the `/verify-email` route with the GuestOnly_Guard so that authenticated users are redirected to the dashboard.

### Requirement 5: Login Page Signup Link

**User Story:** As a visitor on the login page, I want to see a link to the signup page, so that I can easily find how to create a new account.

#### Acceptance Criteria

1. THE Login_Page SHALL display a "Don't have an account? Sign up" link below the sign-in form.
2. WHEN the user clicks the signup link, THE Login_Page SHALL navigate the user to the `/signup` route.

### Requirement 6: Plan Selection

**User Story:** As a prospective customer, I want to select a subscription plan during signup, so that I can choose the tier that fits my business.

#### Acceptance Criteria

1. WHEN the Signup_Page loads, THE Signup_Page SHALL fetch the list of available public plans from the backend.
2. THE Signup_Page SHALL display each available plan with its name and price.
3. THE Signup_Page SHALL require the user to select exactly one plan before form submission.
4. IF no public plans are available, THEN THE Signup_Page SHALL display a message indicating that signup is temporarily unavailable.

### Requirement 7: Signup-to-Setup Navigation Flow

**User Story:** As a new admin user, I want to be guided through the complete signup flow from form submission to setup wizard, so that I can get my business configured without confusion.

#### Acceptance Criteria

1. WHEN the user completes Stripe card collection successfully, THE Signup_Page SHALL display a confirmation screen instructing the user to check their email.
2. WHEN the user completes email verification and password setup, THE Verify_Email_Page SHALL redirect the user to `/setup` to begin the Setup_Wizard.
3. IF the user navigates to `/setup` without being authenticated, THEN THE App_Router SHALL redirect the user to `/login`.
