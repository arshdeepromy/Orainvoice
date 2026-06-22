# Requirements Document

## Introduction

The Organisation Employee Portal gives each organisation an optional, self-contained login surface for its own staff/employees, reachable at an organisation-branded URL derived from a unique organisation slug (for example `localhost/{org_slug}`). When an organisation enables the portal from its settings, the organisation chooses a unique slug (with a real-time availability check) and the platform exposes an organisation-branded login page at that slug. Employees authenticate against dedicated portal-user credentials that are scoped to a single organisation, never against the global org-user (admin/salesperson) account pool.

This feature follows the architecture already established by the B2B Fleet Portal (`app/modules/fleet_portal/`): a cookie-authenticated, organisation-scoped, non-staff portal-user login surface with its own session cookie, its own CSRF double-submit cookie, path-scoped cookies, per-account lockout, and a dedicated audit log. The customer portal (`app/modules/portal/`) and fleet portal continue to operate unchanged in parallel.

A hard prerequisite is that employee identity resolves uniquely within a single organisation. The `staff_members` table currently has no database-level uniqueness on email or employee identifier; the only check is an application-level, org-scoped, active-only, case-sensitive duplicate check (`_check_duplicates` in `app/modules/staff/service.py`) that is racy and bypassable. Because the employee portal must resolve exactly one staff member per organisation at login, this feature introduces database-enforced, organisation-scoped, case-insensitive uniqueness for staff/employee identity, including de-duplication of existing data.

The feature also extends the single Capacitor mobile app (`mobile/`) so a first-time user chooses a portal type — Employee/Staff, Fleet, or Organisation — enters the organisation name or slug for the employee/fleet portals, is routed to the correct login, and has that selection persisted across app restarts until manual logout or an explicit "switch portal" action.

This document specifies WHAT the system must do. Specific implementation choices that the design phase must resolve are flagged explicitly as Open Design Decisions, while testable acceptance criteria are written for the agreed behaviour.

## Open Design Decisions (to resolve in design.md)

- **D1 — Exact web URL path shape for the branded login.** Candidates: `/{org_slug}`, `/org/{org_slug}`, or `/portal/{org_slug}`. The chosen shape must not collide with existing public, marketing, customer-portal (`/portal/{token}`), or fleet-portal (`/fleet/...`) routes. Requirement 8 specifies the collision-avoidance and resolution behaviour the chosen shape must satisfy.
- **D2 — Org slug mutability policy.** Whether a slug is immutable once set, or changeable with old-slug handling (redirect, grace period, or hard cut-over). Requirement 2 specifies criteria for both the "set" path and the "change" path; design selects the policy and the old-URL behaviour.
- **D3 — MVP employee-portal feature scope.** Which staff self-service capabilities ship in the first release (Requirement 7 lists the candidate set and marks the MVP floor); design confirms the final in-scope list and explicitly defers the rest.
- **D4 — Portal-user data model.** Whether employee portal accounts reuse/extend the existing `portal_accounts` table (adding an account type / discriminator) or use a dedicated table. Requirement 4 and Requirement 5 specify behaviour independent of the table choice.
- **D5 — Slug storage location.** Whether the org slug is a dedicated indexed column on `organisations` or a uniqueness-enforced settings field. Requirement 2 requires database-enforced uniqueness regardless of location.

## Glossary

- **Organisation**: A tenant of the platform (the `organisations` table). Owns its data under row-level security (RLS).
- **Org_Settings**: The organisation settings surface managed by `app/modules/organisations/service.py` (`get_org_settings` / `update_org_settings`, `SETTINGS_JSONB_KEYS` allow-list) and the frontend organisation settings page.
- **Org_Admin**: An organisation user whose role is `org_admin` (per `app/modules/auth/models.py`). The role permitted to enable/disable the Employee Portal and manage the slug.
- **Staff_Member**: A row in `staff_members` representing an employee or contractor of an Organisation.
- **Employee_Portal**: The organisation-scoped login surface and its authenticated pages for an Organisation's Staff_Members.
- **Org_Slug**: A unique, URL-safe identifier chosen by an Organisation that forms the organisation-branded portal URL (for example the `acme` in `localhost/acme`).
- **Portal_User**: A dedicated, organisation-scoped login account used to authenticate a Staff_Member into the Employee_Portal. A Portal_User is distinct from a global org-user (`users` table) account.
- **Employee_Portal_Session**: An HttpOnly-cookie-based authenticated session for a Portal_User, modelled on the fleet portal session pattern (session cookie + separate readable CSRF cookie, path-scoped).
- **Portal_Branding**: The Organisation's logo and brand colours (`logo_url`, `primary_colour`, `secondary_colour` from Org_Settings) plus organisation name, presented on the Employee_Portal login and pages.
- **Slug_Availability_Endpoint**: A public, rate-limited endpoint that reports whether a candidate Org_Slug is available.
- **Slug_Resolution_Endpoint**: A public, rate-limited endpoint that resolves an Org_Slug (or organisation name) to organisation identity and Portal_Branding for the mobile lookup, without exposing private organisation data.
- **Portal_Type_Selector**: The mobile app first-run screen where a user selects Employee/Staff portal, Fleet portal, or Organisation portal.
- **Email_Sender**: The unified email dispatch system (`app/integrations/email_sender.py`) with multi-provider failover.
- **Reserved_Slug**: A slug value disallowed because it would collide with an existing platform route, brand term, or operational path (for example `api`, `admin`, `portal`, `fleet`, `health`, `www`, `app`, `login`).
- **Portal_Audit_Log**: The authentication/security event log for portal accounts (pattern established by `portal_audit_log`).

## Requirements

### Requirement 1: Database-Enforced Organisation-Scoped Staff Identity Uniqueness (Prerequisite)

**User Story:** As the system, I want each Staff_Member to be uniquely identifiable within an Organisation by a case-insensitive email and by employee identifier, so that the Employee_Portal can resolve exactly one Staff_Member per login.

#### Acceptance Criteria

1. THE Staff_Module SHALL treat a Staff_Member as active when its status is not deleted, archived, or otherwise marked inactive, and SHALL apply all organisation-scoped uniqueness rules only to active Staff_Members.
2. THE Staff_Module SHALL enforce, at the database level, that at most one active Staff_Member per Organisation exists for a given normalised email address, where normalisation is defined as trimming leading and trailing whitespace and folding to lowercase.
3. WHERE an active Staff_Member has a non-null, non-empty employee identifier, THE Staff_Module SHALL enforce, at the database level, that at most one active Staff_Member per Organisation exists for that employee identifier.
4. WHEN two concurrent requests attempt to create active Staff_Members with the same normalised email in the same Organisation, THE Staff_Module SHALL persist exactly one Staff_Member, SHALL reject the other request with an error indicating a duplicate Staff_Member, and SHALL leave no partial record from the rejected request.
5. IF a request attempts to create or update an active Staff_Member to an email whose normalised form matches an existing active Staff_Member in the same Organisation, THEN THE Staff_Module SHALL reject the request with an error indicating a duplicate email and SHALL leave the existing Staff_Member unchanged.
6. THE Staff_Module SHALL permit the same normalised email address to exist as active Staff_Members in different Organisations, scoping all uniqueness enforcement to a single Organisation rather than globally.
7. WHEN the uniqueness constraint is introduced over existing data, THE Staff_Module SHALL detect every group of active Staff_Members in the same Organisation sharing a normalised email or employee identifier, and SHALL retain exactly one survivor per group selected as the record with the earliest creation timestamp (and, where timestamps are equal, the smallest record identifier), marking the remaining group members inactive before the constraint is enforced, without deleting historical non-active records that fall outside the active-uniqueness scope.
8. WHEN the duplicate-resolution step runs, THE Staff_Module SHALL record, for each resolved group, the retained survivor identifier and each de-duplicated Staff_Member identifier, so the action is auditable.
9. THE Staff_Module SHALL apply the same organisation-scoped email normalisation and comparison defined in criterion 2 in its application-level duplicate check, so that the application check and the database constraint produce identical duplicate determinations.

### Requirement 2: Unique Organisation Slug

**User Story:** As an Org_Admin, I want to choose a unique, URL-safe slug for my organisation, so that my employees can reach a branded login at a memorable address.

#### Acceptance Criteria

1. THE Org_Settings SHALL allow an Org_Admin to define an Org_Slug for the Organisation.
2. THE Org_Settings SHALL accept an Org_Slug only when ALL of the following hold: the value contains only lowercase letters (a–z) and digits (0–9) and hyphens; each hyphen is single and internal; the value does not begin or end with a hyphen; and the value length is between 3 and 63 characters inclusive.
3. IF a submitted Org_Slug fails any condition in criterion 2, THEN THE Org_Settings SHALL reject the value without storing it AND SHALL return a human-readable message describing the violated format rule.
4. THE Org_Settings SHALL maintain a Reserved_Slug list and SHALL reject, without storing, any submitted Org_Slug whose normalised lowercase form equals any entry in the Reserved_Slug list, returning a human-readable message indicating the value is reserved.
5. THE Org_Settings SHALL enforce, at the database level, that each stored Org_Slug is unique across all Organisations when compared in normalised lowercase form.
6. IF a submitted Org_Slug, in normalised lowercase form, is already assigned to another Organisation, THEN THE Org_Settings SHALL reject the value without storing it AND SHALL return a human-readable message indicating the slug is taken.
7. WHEN an Org_Slug is stored, THE Org_Settings SHALL store it in normalised lowercase form.
8. THE Org_Settings SHALL treat all Org_Slug comparison, reservation, and uniqueness checks as case-insensitive.
9. WHERE the design permits changing an existing Org_Slug, WHEN an Org_Admin changes the Org_Slug to a value accepted by criteria 2 through 6, THE Org_Settings SHALL apply the configured old-URL handling policy (design decision D2) AND SHALL make the new Org_Slug resolve to the Organisation's Employee_Portal.
10. WHERE the design defines an Org_Slug as immutable after first set, IF an Org_Admin attempts to change an already-set Org_Slug, THEN THE Org_Settings SHALL reject the change without modifying the stored Org_Slug AND SHALL return a human-readable message indicating the slug cannot be changed.
11. WHILE an Org_Slug change is in effect under a hard cut-over policy, THE Employee_Portal SHALL NOT resolve the previous Org_Slug to the Organisation.

### Requirement 3: Real-Time Slug Availability Check

**User Story:** As an Org_Admin, I want the settings UI to tell me immediately whether a slug is available, so that I can pick a valid, free slug without trial-and-error submissions.

#### Acceptance Criteria

1. WHEN an Org_Admin stops typing a candidate Org_Slug in the Org_Settings UI for at least 300 milliseconds, THE Org_Settings UI SHALL send the candidate to the Slug_Availability_Endpoint.
2. WHEN the Slug_Availability_Endpoint receives a candidate Org_Slug, THE Slug_Availability_Endpoint SHALL return an availability result of exactly one of {available, unavailable, invalid} within 1 second under normal operating load.
3. WHEN a candidate Org_Slug equals a Reserved_Slug, THE Slug_Availability_Endpoint SHALL return the result unavailable.
4. WHEN a candidate Org_Slug is already assigned to an Organisation other than the requesting Organisation, THE Slug_Availability_Endpoint SHALL return the result unavailable.
5. WHEN a candidate Org_Slug is currently assigned to the requesting Organisation itself, THE Slug_Availability_Endpoint SHALL return the result available.
6. IF a candidate Org_Slug does not match the required Org_Slug format (length between 3 and 63 characters inclusive, lowercase alphanumeric characters and single hyphens, not beginning or ending with a hyphen), THEN THE Slug_Availability_Endpoint SHALL return the result invalid together with a human-readable reason identifying which format rule was violated, and SHALL NOT return available.
7. WHEN the Slug_Availability_Endpoint returns an availability result, THE Org_Settings UI SHALL display that result to the Org_Admin before the slug is saved.
8. IF the Slug_Availability_Endpoint does not return a result within 1 second or returns an error, THEN THE Org_Settings UI SHALL display a message indicating the availability check could not be completed and SHALL NOT indicate the candidate is available.
9. WHEN an Org_Admin submits a candidate Org_Slug that passed the availability check, THE Org_Settings SHALL re-validate uniqueness against Reserved_Slug values and all other Organisations at save time, and IF the candidate is no longer unique, THEN THE Org_Settings SHALL reject the submission with an error indicating the slug is no longer available and SHALL retain the Org_Admin's entered value.

### Requirement 4: Enabling and Disabling the Employee Portal

**User Story:** As an Org_Admin, I want to turn the Employee_Portal on or off from organisation settings, so that I control whether my employees can log in through the branded portal.

#### Acceptance Criteria

1. THE Org_Settings SHALL expose an Employee_Portal enablement flag for the Organisation that holds exactly one of two values (enabled or disabled) and that defaults to disabled at Organisation creation.
2. THE Org_Settings SHALL restrict changing the Employee_Portal enablement flag and the Org_Slug to authenticated users holding the Org_Admin role for that same Organisation.
3. IF a user that is not authenticated as an Org_Admin of the target Organisation attempts to change the Employee_Portal enablement flag or the Org_Slug, THEN THE Org_Settings SHALL reject the request with an authorization error and SHALL leave the flag and Org_Slug unchanged.
4. WHEN an Org_Admin attempts to enable the Employee_Portal while the Organisation has no valid Org_Slug set, THE Org_Settings SHALL block the enablement, SHALL leave the flag set to disabled, AND SHALL return a message instructing the Org_Admin to set a valid Org_Slug first.
5. WHILE the Employee_Portal is disabled for an Organisation, THE Employee_Portal SHALL reject every login attempt at that Organisation's branded URL and SHALL return a human-readable message indicating the portal is unavailable, without establishing an Employee_Portal_Session.
6. WHEN an Org_Admin disables the Employee_Portal for an Organisation, THE Employee_Portal SHALL invalidate all active Employee_Portal_Sessions for that Organisation within 30 seconds of the change being persisted.
7. WHEN the Employee_Portal enablement flag or the Org_Slug is changed, THE Org_Settings SHALL write an audit log entry recording the acting user identity, the previous value, the new value, and the change timestamp.
8. IF writing the audit log entry for a change to the Employee_Portal enablement flag or the Org_Slug fails, THEN THE Org_Settings SHALL roll back the change AND SHALL return an error indicating the change was not applied.

### Requirement 5: Employee Portal Credential Issuance

**User Story:** As an Org_Admin, I want my onboarded staff to receive Employee_Portal login credentials, so that employees can access the portal without me sharing my own admin login.

#### Acceptance Criteria

1. THE Employee_Portal SHALL represent employee login credentials as Portal_Users that are scoped to exactly one Organisation, AND SHALL store Portal_Users in a separate identity store from global org-user (`users`) accounts such that a Portal_User can authenticate only against the Employee_Portal and never against the global org-user authentication endpoints, and a global org-user credential can never authenticate as a Portal_User.
2. THE Employee_Portal SHALL enforce, at the database level, that at most one active Portal_User per Organisation exists for a given email address, where the email address is normalised by trimming leading and trailing whitespace and converting to lowercase before the uniqueness comparison.
3. WHEN an Org_Admin issues Employee_Portal access for a Staff_Member, THE Employee_Portal SHALL create exactly one Portal_User linked to that Staff_Member within the same Organisation AND SHALL return a success confirmation identifying the created Portal_User.
4. WHEN a Staff_Member completes self-service onboarding via the staff onboarding link feature AND the Employee_Portal is enabled, THE Employee_Portal SHALL be the login destination for that Staff_Member, using the credential-issuance mechanism defined in this requirement.
5. WHEN a Portal_User is created via invitation, THE Employee_Portal SHALL require the invited Staff_Member to set a password of between 8 and 128 characters inclusive before first authenticated access AND SHALL persist only a hashed form of the password, never the plaintext password.
6. IF an invited Staff_Member submits a password shorter than 8 characters or longer than 128 characters, THEN THE Employee_Portal SHALL reject the request with an error message indicating the allowed password length, SHALL NOT create or activate the Portal_User, AND SHALL leave any existing Portal_User state unchanged.
7. IF an Org_Admin attempts to issue Employee_Portal access for a Staff_Member whose normalised email collides with an existing active Portal_User in the same Organisation, THEN THE Employee_Portal SHALL reject the request with a human-readable duplicate error, SHALL NOT create a new Portal_User, AND SHALL leave the existing Portal_User unchanged.
8. THE Employee_Portal SHALL treat an issued invitation as valid for 7 days from the time of issuance.
9. IF an invited Staff_Member attempts to set a password using an invitation whose 7-day validity period has elapsed, THEN THE Employee_Portal SHALL reject the request with an error message indicating the invitation has expired AND SHALL NOT activate the Portal_User.
10. WHEN an Org_Admin revokes a Staff_Member's Employee_Portal access, THE Employee_Portal SHALL deactivate the associated Portal_User AND SHALL invalidate that Portal_User's active Employee_Portal_Sessions.
11. WHERE a Staff_Member is deactivated in the Staff_Module, THE Employee_Portal SHALL prevent that Staff_Member's Portal_User from authenticating AND SHALL invalidate that Portal_User's active Employee_Portal_Sessions.

### Requirement 6: Employee Portal Login and Session

**User Story:** As an employee, I want to log in at my organisation's branded portal address, so that I can access my work information securely.

#### Acceptance Criteria

1. WHEN a Portal_User submits valid credentials at an enabled Organisation's Employee_Portal, THE Employee_Portal SHALL establish an Employee_Portal_Session using an HttpOnly session cookie and a separate readable CSRF cookie, following the fleet portal cookie pattern.
2. THE Employee_Portal SHALL scope the session cookie and CSRF cookie to the Employee_Portal path so that they do not collide with the staff app (`/api/*`), the customer portal, or the fleet portal (`/fleet`) cookies.
3. WHEN a Portal_User submits credentials, THE Employee_Portal SHALL resolve the Portal_User within the Organisation identified by the Org_Slug in the request AND SHALL NOT authenticate a Portal_User belonging to a different Organisation.
4. IF a login attempt presents an email or password that does not match an active Portal_User in the resolved Organisation, THEN THE Employee_Portal SHALL reject the attempt with a single generic message indicating the email or password is invalid that is identical regardless of whether the email exists, AND SHALL NOT establish an Employee_Portal_Session.
5. WHEN a Portal_User reaches 5 consecutive failed login attempts, THE Employee_Portal SHALL lock the account for 15 minutes AND SHALL reject all login attempts for that Portal_User during the lock with a message indicating the account is temporarily locked.
6. WHEN the 15-minute lockout duration elapses, THE Employee_Portal SHALL reset the consecutive failed-attempt count to 0 AND SHALL accept new login attempts for that Portal_User.
7. WHEN state-changing Employee_Portal requests are received, THE Employee_Portal SHALL require a valid double-submit CSRF token.
8. IF a state-changing Employee_Portal request is missing the CSRF token OR the submitted CSRF token does not match the CSRF cookie, THEN THE Employee_Portal SHALL reject the request without performing the state change AND SHALL return an error response indicating CSRF validation failed.
9. WHEN a Portal_User logs out, THE Employee_Portal SHALL destroy the Employee_Portal_Session AND SHALL clear the session and CSRF cookies.
10. WHILE an Employee_Portal_Session has been inactive for more than 30 minutes OR has existed for more than 12 hours since establishment, THE Employee_Portal SHALL treat the session as invalid AND SHALL require re-authentication before serving Employee_Portal requests.
11. IF a login attempt is made against an Org_Slug that does not resolve to any Organisation, THEN THE Employee_Portal SHALL reject the attempt with a human-readable not-found message AND SHALL NOT reveal whether other Organisations exist AND SHALL NOT establish an Employee_Portal_Session.

### Requirement 7: Employee Portal Capabilities (Scope)

**User Story:** As an employee, I want to view and manage my own work information in the portal, so that I can self-serve common tasks without contacting an admin.

#### Acceptance Criteria

1. WHEN an authenticated Portal_User opens the Employee_Portal, THE Employee_Portal SHALL display only records whose owning Staff_Member equals the Portal_User's linked Staff_Member AND whose Organisation equals the Portal_User's Organisation, and SHALL exclude all other records.
2. THE Employee_Portal SHALL provide, as the MVP capability floor, a profile view for the authenticated Staff_Member AND a roster/schedule view for the authenticated Staff_Member.
3. WHERE the design includes additional capabilities from the candidate set (clock in/out, payslips, leave requests, and document access), THE Employee_Portal SHALL serve each capability only for records whose owning Staff_Member equals the authenticated Portal_User's linked Staff_Member.
4. WHERE a staff self-service surface already exists for a capability (for example the staff roster viewer and onboarding-collected profile data), THE Employee_Portal SHALL source that capability's data from the existing surface AND SHALL NOT create a duplicate copy of that data.
5. IF an authenticated Portal_User requests a record that does not belong to that Portal_User's linked Staff_Member, THEN THE Employee_Portal SHALL deny the request with a not-found or forbidden response that does not disclose the existence of other Staff_Members' records and does not return any field of the requested record.
6. WHERE a capability is marked out-of-scope for the MVP in design decision D3, THE Employee_Portal SHALL NOT expose that capability in the MVP release.
7. IF an authenticated Portal_User has no linked Staff_Member, THEN THE Employee_Portal SHALL deny access to staff-scoped capabilities AND SHALL present a human-readable message indicating the account is not yet linked to a staff record.

### Requirement 8: Web Routing for the Organisation-Scoped Portal URL

**User Story:** As an employee, I want my organisation's branded login URL to load the correct portal, so that I reach the right place regardless of other site routes.

#### Acceptance Criteria

1. WHEN a visitor requests a portal URL whose path is formed from a valid Org_Slug using the path shape selected in design decision D1, THE Employee_Portal SHALL serve the organisation-branded login page for that Organisation.
2. WHEN the Employee_Portal receives a portal URL, THE Employee_Portal SHALL resolve the Org_Slug to its Organisation before rendering any login page content, performing a case-insensitive match against stored Org_Slug values.
3. IF the Org_Slug in a portal URL does not resolve to an Organisation, OR resolves to an Organisation that does not have the Employee_Portal enabled, THEN THE Employee_Portal SHALL display a human-readable unavailable/not-found page that does not reveal whether the Organisation exists, AND SHALL NOT render the branded login page.
4. THE Employee_Portal route SHALL NOT resolve any incoming request whose top-level path segment matches an existing public, marketing, customer-portal (`/portal/{token}`), or fleet-portal (`/fleet/...`) route to the Employee_Portal.
5. THE Reserved_Slug set SHALL include every top-level path segment used by existing public, marketing, customer-portal, and fleet-portal routes, AND THE Employee_Portal SHALL reject any Org_Slug that matches a member of the Reserved_Slug set.
6. WHERE the deployment serves the platform over HTTPS, THE Employee_Portal SHALL serve the branded login page and all authenticated pages over HTTPS, AND IF such a page is requested over HTTP, THEN THE Employee_Portal SHALL redirect the request to the equivalent HTTPS URL.
7. WHEN the Employee_Portal serves the branded login page or any authenticated page, THE Employee_Portal SHALL include an instruction directing search engines not to index the page.

### Requirement 9: Slug Resolution Endpoint for Mobile Lookup

**User Story:** As a mobile user, I want to type my organisation's name or code and be shown the right branded login, so that I can reach my organisation's portal from the single app.

#### Acceptance Criteria

1. WHEN a lookup request supplies an Org_Slug or organisation name (1 to 100 characters) AND exactly one Organisation matches for the requested portal type AND that portal type is enabled for the Organisation, THE Slug_Resolution_Endpoint SHALL return the resolved organisation identity and Portal_Branding within 2 seconds under normal load.
2. THE Slug_Resolution_Endpoint SHALL be publicly reachable without authentication.
3. IF no Organisation matches the supplied Org_Slug or organisation name for the requested portal type, THEN THE Slug_Resolution_Endpoint SHALL return a human-readable not-found result that does not enumerate, list, or otherwise reveal the identity of any other Organisation.
4. WHEN more than one Organisation matches the supplied organisation name for the requested portal type, THE Slug_Resolution_Endpoint SHALL return a disambiguation result containing only the organisation name and Portal_Branding fields for each match, limited to a maximum of 10 candidates, and SHALL NOT return a single auto-resolved identity.
5. WHEN returning any matched Organisation, THE Slug_Resolution_Endpoint SHALL include only the organisation name and Portal_Branding fields needed to render a branded login AND SHALL NOT expose any other organisation data.
6. THE Slug_Resolution_Endpoint SHALL apply per-IP rate limiting of a maximum of 30 requests per 60-second window per source IP.
7. IF a source IP exceeds the configured rate limit, THEN THE Slug_Resolution_Endpoint SHALL reject the request with a rate-limit error indication and SHALL NOT return any organisation identity or Portal_Branding.
8. IF the requested portal type is disabled for an otherwise matched Organisation, THEN THE Slug_Resolution_Endpoint SHALL return a not-available result for that portal type that does not expose the Organisation's Portal_Branding.

### Requirement 10: Mobile First-Run Portal-Type Selector

**User Story:** As a mobile user logging in for the first time, I want to choose whether I am an Employee/Staff user, a Fleet user, or an Organisation user, so that the app takes me to the correct login.

#### Acceptance Criteria

1. WHEN the mobile app starts AND no portal selection is persisted AND no authenticated session exists, THE Portal_Type_Selector SHALL present exactly three selectable choices: Employee/Staff portal, Fleet portal, and Organisation portal.
2. WHEN the user selects Organisation portal, THE mobile app SHALL route to the existing organisation-user login flow AND SHALL persist the selected portal type so the Portal_Type_Selector is not shown again on subsequent app starts while the selection remains persisted.
3. WHEN the user selects Employee/Staff portal or Fleet portal, THE mobile app SHALL prompt the user to enter the organisation name or the Org_Slug used in the portal URL, accepting an input of 1 to 100 characters.
4. WHEN the user submits an organisation name or Org_Slug for the Employee/Staff or Fleet portal, THE mobile app SHALL call the Slug_Resolution_Endpoint to resolve the Organisation AND, on a successful resolution to an Organisation with the chosen portal type enabled, SHALL route to that Organisation's branded login for the chosen portal type AND SHALL persist the selected portal type.
5. WHILE a Slug_Resolution_Endpoint call is in progress, THE mobile app SHALL display a loading indicator AND SHALL disable the submit control until the call completes or times out.
6. IF the entered organisation name or Org_Slug does not resolve to an Organisation with the chosen portal type enabled, THEN THE mobile app SHALL display a visible error message indicating that the organisation was not found or the portal type is not enabled, SHALL retain the user on the input prompt, AND SHALL allow the user to re-enter the value.
7. IF the Slug_Resolution_Endpoint does not return a response within 10 seconds OR returns a failure, THEN THE mobile app SHALL display a visible error message indicating that resolution could not be completed, SHALL retain the entered value, AND SHALL allow the user to retry submission.
8. THE Portal_Type_Selector SHALL render all interactive elements with a touch target of at least 44×44 CSS pixels.

### Requirement 11: Mobile Persistence and Switching of Portal Selection

**User Story:** As a mobile user, I want the app to remember my chosen portal and organisation until I log out or switch, so that I do not repeat the selection every time I open the app.

#### Acceptance Criteria

1. WHEN a user successfully logs in after selecting a portal type and Organisation, THE mobile app SHALL persist the selected portal type and the resolved Organisation identifier to device storage that survives app restart.
2. IF persisting the selected portal type and resolved Organisation fails, THEN THE mobile app SHALL complete the current login session, SHALL display an error indication that the selection could not be saved, AND SHALL show the Portal_Type_Selector on the next app start.
3. WHEN the mobile app restarts WHILE a valid portal selection is persisted, THE mobile app SHALL route directly to the persisted portal type and Organisation login or session, SHALL NOT show the Portal_Type_Selector, AND SHALL complete this routing within 3 seconds of app launch under normal network conditions.
4. IF a persisted portal selection is absent, malformed, or references an Organisation the user can no longer access, THEN THE mobile app SHALL clear the persisted portal selection AND SHALL show the Portal_Type_Selector.
5. WHEN a user manually logs out, THE mobile app SHALL clear the persisted portal selection AND SHALL show the Portal_Type_Selector on the next start.
6. THE mobile app SHALL provide a "switch portal" action that returns the user to the Portal_Type_Selector AND clears the persisted portal selection.
7. WHEN the user invokes "switch portal" WHILE an Employee_Portal_Session or Fleet session is active, THE mobile app SHALL end that active session before returning to the Portal_Type_Selector.
8. WHEN a portal type and Organisation are persisted, THE mobile app SHALL resolve the correct API base/origin for that selection so that requests target the chosen portal's backend surface.
9. IF the API base/origin for the persisted portal selection cannot be resolved, THEN THE mobile app SHALL clear the persisted portal selection, SHALL display an error indication that the portal could not be reached, AND SHALL show the Portal_Type_Selector.

### Requirement 12: Mobile Error and Offline States

**User Story:** As a mobile user, I want clear feedback when the network fails or the organisation cannot be found, so that I am never left on a blank screen.

#### Acceptance Criteria

1. IF the Slug_Resolution_Endpoint call fails due to a network or server error, THEN THE mobile app SHALL display a human-readable error message indicating the lookup failed AND SHALL retain the previously entered input without clearing it AND SHALL NOT display a blank screen.
2. WHERE the error in criterion 1 is displayed, THE mobile app SHALL present a retry action that re-invokes the Slug_Resolution_Endpoint call with the same input when activated.
3. IF the Slug_Resolution_Endpoint call does not return a response within 10 seconds, THEN THE mobile app SHALL treat the call as failed AND SHALL display the human-readable error with the retry action defined in criteria 1 and 2.
4. WHILE the mobile device is offline AND no portal selection is persisted, THE mobile app SHALL display a human-readable message indicating that a network connection is required to look up an Organisation AND SHALL NOT display a blank screen.
5. WHEN a persisted Employee_Portal_Session is rejected as expired or invalid by the backend, THE mobile app SHALL navigate the user to the persisted Organisation's branded login screen rather than the Portal_Type_Selector.
6. IF a persisted Organisation's portal has been disabled, THEN THE mobile app SHALL display a human-readable message indicating the portal is unavailable AND SHALL present a "switch portal" action that returns the user to the Portal_Type_Selector when activated.

### Requirement 13: Organisation-Branded Login Presentation

**User Story:** As an employee, I want the login page to show my organisation's branding, so that I trust I am logging into the right place.

#### Acceptance Criteria

1. WHEN the Employee_Portal login page renders for an Organisation, THE Employee_Portal SHALL display the Organisation's Portal_Branding name and, where set, its logo, primary colour, and secondary colour, completing the branded render within 2 seconds of the login page DOM becoming ready.
2. WHERE an Organisation has not set a logo, primary colour, or secondary colour, THE Employee_Portal SHALL render a neutral default presentation (the platform default logo and the platform default colour palette) and SHALL display the login form fully functional without surfacing any error indication.
3. IF a configured logo fails to load within 2 seconds, THEN THE Employee_Portal SHALL substitute the platform default logo, retain the configured colours, and continue rendering the login form without surfacing an error to the employee.
4. THE Employee_Portal SHALL source Portal_Branding from the existing Org_Settings branding fields rather than introducing a separate branding store.
5. WHEN Portal_Branding is presented on the mobile branded login, THE mobile app SHALL use the branding returned by the Slug_Resolution_Endpoint for the resolved Organisation.
6. IF the Slug_Resolution_Endpoint does not return branding for the resolved Organisation, or fails to respond within 5 seconds, THEN THE mobile app SHALL render the neutral default presentation and SHALL display an error indication that branding could not be loaded while keeping the login form usable.

### Requirement 14: Employee Portal Password Reset

**User Story:** As an employee, I want to reset my portal password if I forget it, so that I can regain access without contacting an admin.

#### Acceptance Criteria

1. WHEN a Portal_User submits a password reset request at an enabled Organisation's Employee_Portal, THE Employee_Portal SHALL respond within 5 seconds with a single generic confirmation message that is byte-for-byte identical regardless of whether the submitted email matches an active Portal_User, so that account existence is not revealed.
2. WHEN a password reset is requested for an existing active Portal_User, THE Email_Sender SHALL send a password reset message containing the reset token to that Portal_User's registered email address using the unified multi-provider system.
3. WHEN the Employee_Portal accepts a password reset request, THE Employee_Portal SHALL issue a single-use password reset token that expires 60 minutes (3600 seconds) after issuance.
4. WHEN a Portal_User submits a new password with a valid, unexpired, unused token AND the new password is between 8 and 128 characters inclusive (matching Requirement 5 rules), THE Employee_Portal SHALL update the stored password hash for that Portal_User.
5. WHEN the Employee_Portal updates the stored password hash following a successful reset, THE Employee_Portal SHALL invalidate the reset token so it cannot be reused.
6. IF a reset is submitted with a token that is expired, already-used, or unrecognised, THEN THE Employee_Portal SHALL reject the request, leave the stored password hash unchanged, and return a human-readable message indicating the token is invalid or expired.
7. IF a reset is submitted with a token that is valid and unexpired but the new password is fewer than 8 or more than 128 characters, THEN THE Employee_Portal SHALL reject the request, leave the stored password hash unchanged, and return a human-readable message indicating the password does not meet length requirements.
8. WHEN a Portal_User's password is reset successfully, THE Employee_Portal SHALL invalidate all of that Portal_User's existing Employee_Portal_Sessions.

### Requirement 15: Notifications for Credential Issuance and Reset

**User Story:** As an employee, I want to receive emails when my portal access is set up or my password is reset, so that I know how to log in.

#### Acceptance Criteria

1. WHEN an Org_Admin issues Employee_Portal access for a Staff_Member, THE Email_Sender SHALL, within 60 seconds of the issuance action, send the Staff_Member a credential-setup email that includes the Organisation name, a set-password link to the Organisation's branded Employee_Portal login, and the link's expiry duration.
2. THE credential-setup email and the password-reset email SHALL each be sent using the unified Email_Sender, which SHALL attempt every configured email provider in priority order until one provider accepts the message or all configured providers have been attempted.
3. IF all configured email providers fail to accept a credential-setup or password-reset email, THEN THE Employee_Portal SHALL record a failure log entry AND SHALL return a human-readable error to the initiating Org_Admin for credential-setup that states the email could not be delivered, while preserving any Portal_User record already created without rollback.
4. THE Employee_Portal SHALL exclude raw passwords from all emails AND SHALL deliver credentials exclusively via a set-password or reset link rather than including a password in any email.
5. WHEN a password reset is initiated for a Staff_Member, THE Email_Sender SHALL, within 60 seconds of the reset request, send the Staff_Member a password-reset email that includes the Organisation name, a reset link to the Organisation's branded Employee_Portal login, and the link's expiry duration.
6. IF the Staff_Member has no valid email address recorded at the time a credential-setup or password-reset email is requested, THEN THE Employee_Portal SHALL reject the send action AND SHALL return a human-readable error to the initiating Org_Admin indicating that a valid email address is required, while preserving any Portal_User record already created.

### Requirement 16: Security, Tenant Isolation, and Auditing

**User Story:** As the platform operator, I want the Employee_Portal to be isolated per organisation and resistant to abuse, so that no employee can access another organisation's data and attacks are limited and recorded.

#### Acceptance Criteria

1. THE Employee_Portal SHALL apply per-IP rate limiting, measured per 60-second window per source IP, of a maximum of 10 requests to the login endpoint, 30 requests to the Slug_Availability_Endpoint, 30 requests to the Slug_Resolution_Endpoint, and 5 requests to the password-reset endpoints.
2. IF a source IP exceeds the configured rate limit for an endpoint, THEN THE Employee_Portal SHALL reject the request with a rate-limit error indication, SHALL NOT process the requested action, AND SHALL NOT establish an Employee_Portal_Session.
3. THE Employee_Portal SHALL scope every authenticated data query to the Portal_User's Organisation AND SHALL enforce tenant isolation consistent with the platform's row-level security so that no cross-organisation data is returned.
4. IF an authenticated request attempts to access data belonging to an Organisation other than the Portal_User's Organisation, THEN THE Employee_Portal SHALL deny the request with a not-found or forbidden response, SHALL return no fields of the requested data, AND SHALL NOT disclose whether that data exists.
5. WHEN an Employee_Portal authentication event occurs (successful login, failed login, lockout, logout, password reset, credential issuance, or access revocation), THE Employee_Portal SHALL record the event in the Portal_Audit_Log with the Organisation, the acting account where known, the source IP, the action, the outcome (success or failure), and a timestamp.
6. WHEN recording a failed login against an unknown email, THE Employee_Portal SHALL record the attempt without revealing whether the email exists.
7. THE Employee_Portal SHALL set the session cookie as HttpOnly AND SHALL mark cookies Secure in staging and production environments.
8. THE Employee_Portal SHALL NOT accept a session or CSRF cookie issued for the customer portal, the fleet portal, or the staff app as valid Employee_Portal credentials.

### Requirement 17: Migration and Backward Compatibility

**User Story:** As the platform operator, I want existing organisations and existing portals to keep working after this feature ships, so that the rollout is non-disruptive.

#### Acceptance Criteria

1. WHEN the feature is deployed, THE platform SHALL leave existing Organisations with no Org_Slug AND with the Employee_Portal disabled by default.
2. WHEN a request targets the Employee_Portal for an Organisation that has no Org_Slug set, THE Employee_Portal SHALL return a portal-not-configured response AND SHALL leave all other Organisation features returning the same response content and status they returned before the feature was deployed.
3. WHEN the feature is deployed, THE existing customer portal (`/portal/{token}`) and fleet portal (`/fleet/...`) SHALL continue to return the same response content and status they returned before the feature was deployed.
4. WHEN the mobile app is updated with the Portal_Type_Selector, THE mobile app SHALL continue to support existing organisation-user logins without requiring re-selection for users who already have an active organisation-user session.
5. WHEN database migrations for this feature run, THE migrations SHALL apply the de-duplication from Requirement 1 before enforcing the new uniqueness constraints.
6. WHEN a feature migration is re-run after having already been applied, THE migration SHALL complete without error AND SHALL create no duplicate schema objects and make no further data changes.
7. IF the Requirement 1 de-duplication has not completed successfully WHEN a uniqueness constraint is about to be enforced, THEN THE migration SHALL halt before enforcing the constraint AND SHALL leave the existing data unchanged.

### Requirement 18: Trade-Family Gating Decision

**User Story:** As a product owner, I want the Employee_Portal's trade-family gating to be explicit, so that the feature appears for the correct organisations.

#### Acceptance Criteria

1. WHEN an Organisation's user accesses the Employee_Portal, THE Employee_Portal SHALL display the portal and its non-trade-specific sub-sections regardless of the Organisation's trade family, AND SHALL NOT apply any trade-family gate to the portal as a whole.
2. WHERE a sub-section of the Employee_Portal surfaces trade-specific data, THE Employee_Portal SHALL render that sub-section only when the Organisation's trade family matches the sub-section's designated trade family or families, applying the same trade-family gating mechanism used by other features (frontend element gating plus conditional inclusion of trade-specific fields in request payloads).
3. WHERE a sub-section of the Employee_Portal surfaces trade-specific data AND the Organisation's trade family does not match that sub-section's designated trade family or families, THE Employee_Portal SHALL hide that sub-section, omit its trade-specific columns and form fields, and exclude its trade-specific fields from any request payload.
4. IF the Organisation's trade family is null or unset WHEN a trade-specific sub-section of the Employee_Portal is evaluated for gating, THEN THE Employee_Portal SHALL treat the trade family as "automotive-transport" for the gating decision.

### Requirement 19: Versioning and Changelog

**User Story:** As a maintainer, I want this feature's release to be versioned and recorded, so that deployments and changes are traceable.

#### Acceptance Criteria

1. WHEN the Employee_Portal feature is released, THE platform SHALL append a changelog entry to the project changelog containing the application version identifier, the release date, and a summary of the Employee_Portal changes.
2. WHEN the Employee_Portal feature is released, THE platform SHALL record the application version using a semantic version identifier of the form MAJOR.MINOR.PATCH that is greater than the immediately preceding recorded version.
3. IF the changelog entry cannot be written during release, THEN THE platform SHALL halt the release as incomplete and report an error indicating the changelog update failed, leaving the previously recorded changelog content unchanged.
4. WHERE the mobile app exposes a version surface, THE mobile app SHALL display a semantic version identifier of the form MAJOR.MINOR.PATCH whose value is greater than or equal to the application version recorded for the release that introduced the Portal_Type_Selector.
