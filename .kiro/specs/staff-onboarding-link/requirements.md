# Requirements Document

## Introduction

Self-service staff onboarding via a secure, token-gated link. When adding a new staff member, an admin can opt to send an onboarding email containing a unique link. The staff member opens the link (no login required) and fills in their personal details, bank account, IRD/tax information, and uploads working rights documents. This eliminates the need for admins to manually collect and enter this data.

## Glossary

- **Onboarding_Token**: A cryptographically random, time-limited token that grants access to the self-service onboarding form without requiring authentication.
- **Onboarding_Form**: The public-facing web page where a staff member enters their personal, payroll, and compliance information.
- **Staff_Module**: The existing OraInvoice module that manages staff records, pay rates, schedules, and compliance.
- **Email_Sender**: The unified email dispatch system (`app/integrations/email_sender.py`) that sends transactional emails via configured providers with failover.
- **Compliance_Document**: A file (passport, visa, permit) uploaded to prove working rights, stored via the existing compliance document infrastructure.
- **Admin**: An organisation user with `org_admin` or `branch_admin` role who manages staff.
- **Onboarding_Draft**: A server-side persisted snapshot of partial Onboarding_Form data, keyed to the Onboarding_Token, allowing a staff member to save progress and resume later from any device.
- **Completion_Percentage**: A deterministic, section-weighted figure (0–100) computed server-side across the Onboarding_Form sections (Personal, Bank, IRD/Tax, Residency, Documents) representing how far a staff member has progressed through onboarding.
- **In_App_Notification**: A notification record created via the existing in-app notification system (`app/modules/in_app_notifications`) using the `create_in_app_notification(...)` helper, which targets either a specific `user_id` or a role broadcast via `audience_roles` (default `["org_admin"]`) and never raises on failure.
- **Onboarding_Completion_Notification**: The set of best-effort notifications (an In_App_Notification and an email) generated for the organisation's onboarding-link senders (`org_admin` and `branch_admin` users) when a staff member successfully completes onboarding.
- **Confirmation_Email**: The best-effort thank-you email sent to a staff member by the Email_Sender upon successful final submission of the Onboarding_Form.

## Requirements

### Requirement 1: Send Onboarding Link Checkbox

**User Story:** As an admin, I want a "Send onboarding link" checkbox in the Add Staff dialog, so that I can invite the new staff member to complete their own details.

#### Acceptance Criteria

1. WHEN the Add Staff dialog is open, THE Staff_Module SHALL display a "Send onboarding link" checkbox alongside the existing "Also create as a user" checkbox.
2. WHILE the "Send onboarding link" checkbox is checked AND the email field is empty, THE Staff_Module SHALL display an onboarding-specific validation message indicating that an email address is required to send the onboarding link AND SHALL block form submission until an email address is provided. (This onboarding-specific validation is distinct in purpose from the general email-required validation in Acceptance Criterion 6; both apply.)
3. WHEN the admin submits the Add Staff form with "Send onboarding link" checked AND a valid email address provided, THE Staff_Module SHALL create the staff record AND generate an Onboarding_Token AND send an onboarding email to the staff member's email address.
4. WHEN the admin submits the Add Staff form with "Send onboarding link" unchecked, THE Staff_Module SHALL create the staff record without generating a token or sending an email.
5. THE Staff_Module SHALL allow both "Send onboarding link" and "Also create as a user" to be checked simultaneously without conflict.
6. WHEN the admin submits the Add Staff form, THE Staff_Module SHALL validate that an email address is provided regardless of the "Send onboarding link" checkbox state (this is the general email-required validation, serving a different purpose than the onboarding-specific validation in Acceptance Criterion 2) AND SHALL block submission until a valid email address is provided.
7. THE Staff_Module SHALL create a staff record only when the admin actually submits the Add Staff form AND SHALL NOT create any staff record before submission.

### Requirement 2: Onboarding Token Generation and Storage

**User Story:** As the system, I want to generate secure, time-limited tokens for onboarding links, so that only intended recipients can access the form.

#### Acceptance Criteria

1. WHEN an onboarding email is requested, THE Staff_Module SHALL generate a cryptographically random token of at least 32 bytes (URL-safe base64 encoded).
2. THE Staff_Module SHALL store the Onboarding_Token with the associated staff member ID, organisation ID, creation timestamp, and expiry timestamp.
3. THE Staff_Module SHALL set the token expiry to 7 days from creation.
4. WHEN a token has expired, THE Onboarding_Form SHALL reject access and display a message indicating the link has expired with instructions to contact the employer.
5. WHEN a staff member successfully submits the onboarding form, THE Staff_Module SHALL mark the token as consumed and prevent reuse. THE Staff_Module SHALL mark a token as consumed only on successful submission and SHALL NOT mark a token as consumed on expiry-rejection or staff deactivation (deactivation revokes a token, it does not consume it).
6. IF a token is used after the staff member has been deactivated, THEN THE Onboarding_Form SHALL reject access with an appropriate message.
7. WHEN a staff member successfully submits the onboarding form, THE Staff_Module SHALL treat form-data persistence and token consumption as a single atomic operation, so that the token is marked consumed if and only if the submitted form data is durably saved.
8. WHEN a staff member successfully submits the onboarding form, THE Staff_Module SHALL NOT automatically grant the staff member access to the staff portal (successful submission saves data only and does not change the staff member's access).

### Requirement 3: Onboarding Email Delivery

**User Story:** As a staff member, I want to receive a clear email with an onboarding link, so that I know what to do and can access the form easily.

#### Acceptance Criteria

1. WHEN an onboarding email is triggered, THE Email_Sender SHALL send the email using the unified multi-provider failover system.
2. THE Email_Sender SHALL include the organisation name in the email subject line (format: "Complete your onboarding — {org_name}").
3. THE Email_Sender SHALL include the staff member's first name as a greeting in the email body.
4. THE Email_Sender SHALL include a prominent call-to-action button linking to the onboarding form URL.
5. THE Email_Sender SHALL include text indicating the link expires in 7 days.
6. IF all email providers fail after the staff record has been committed, THEN THE Staff_Module SHALL log the failure and return an error response to the admin indicating the email could not be sent, while still preserving the created staff record (email-delivery failure preserves the record). IF the onboarding email is nonetheless delivered successfully through any provider, THEN THE Staff_Module SHALL likewise preserve the staff record, treating any successful delivery as satisfying the preservation requirement.
7. THE Staff_Module SHALL treat staff record creation and the onboarding email send as a single atomic transaction; IF the transaction fails, THEN THE Staff_Module SHALL NOT persist the staff record (record-creation failure rolls back so no partial record remains).
8. IF the onboarding email is sent successfully AND the staff record transaction is subsequently rolled back, THEN THE Staff_Module SHALL invalidate the onboarding link associated with the already-sent email so that the rolled-back record's link cannot be used.
9. THE Email_Sender SHALL apply the email content formatting requirements of Acceptance Criteria 2–5 only when the email will actually be dispatched; WHEN all providers have failed and no delivery will occur, THE Email_Sender SHALL skip content formatting.

### Requirement 4: Onboarding Form — Personal Details Section

**User Story:** As a staff member, I want to enter my personal details on the onboarding form, so that my employer has accurate contact and emergency information.

#### Acceptance Criteria

1. THE Onboarding_Form SHALL display input fields for: first name (pre-filled, read-only), last name, phone number, emergency contact name, and emergency contact phone.
2. THE Onboarding_Form SHALL pre-fill the first name and email from the staff record (both read-only).
3. WHEN the staff member submits the form, THE Onboarding_Form SHALL validate that emergency contact name and emergency contact phone are both provided or both empty.

### Requirement 5: Onboarding Form — Bank Account Details Section

**User Story:** As a staff member, I want to enter my bank account number for payroll, so that I can get paid correctly.

#### Acceptance Criteria

1. THE Onboarding_Form SHALL display an input field for the NZ bank account number (format: XX-XXXX-XXXXXXX-XXX).
2. WHEN a bank account number is entered, THE Onboarding_Form SHALL validate the format matches the NZ bank account pattern (2-4-7-2 or 2-4-7-3 digits) AND SHALL block submission until the entered format is valid.
3. THE Onboarding_Form SHALL mark the bank account field as optional by default (staff member may choose to provide it later).
4. WHERE an administrator has configured the bank account field as required in the form builder/config, THE Onboarding_Form SHALL require a bank account number before allowing submission.
5. WHERE a field is optional, THE Onboarding_Form SHALL still enforce all other applicable validation rules (such as format) on that field AND SHALL block submission when an optional field's entered value violates those rules.

### Requirement 6: Onboarding Form — IRD and Tax Information Section

**User Story:** As a staff member, I want to enter my IRD number and tax code, so that my employer can handle tax deductions correctly.

#### Acceptance Criteria

1. THE Onboarding_Form SHALL display input fields for: IRD number, tax code (dropdown with options M, ME, S, SH, ST, SB, CAE, NSW, ND), student loan (checkbox), KiwiSaver enrolled (checkbox), and KiwiSaver employee contribution rate (dropdown: 3%, 4%, 6%, 8%, 10%).
2. WHEN an IRD number is entered, THE Onboarding_Form SHALL validate it is 8 or 9 digits.
3. IF an entered IRD number is not 8 or 9 digits, THEN THE Onboarding_Form SHALL display a validation error AND SHALL NOT accept the IRD number.
4. WHILE KiwiSaver enrolled is unchecked, THE Onboarding_Form SHALL hide the KiwiSaver contribution rate field. WHILE any validation errors are present elsewhere in the form, THE Onboarding_Form SHALL also hide the KiwiSaver contribution rate field until the form is valid.
5. THE Onboarding_Form SHALL mark the IRD number and tax code fields as optional.

### Requirement 7: Onboarding Form — Working Rights Documents Section

**User Story:** As a staff member, I want to upload copies of my passport or visa, so that my employer has proof of my working rights on file.

#### Acceptance Criteria

1. THE Onboarding_Form SHALL display a file upload area for working rights documents (passport, visa, work permit).
2. THE Onboarding_Form SHALL accept file types: PDF, JPEG, PNG with a maximum file size of 10 MB per file.
3. THE Onboarding_Form SHALL allow uploading up to 3 documents in a single submission.
4. WHEN a file is uploaded, THE Onboarding_Form SHALL display the file name and a remove button; WHILE no files are present, THE Onboarding_Form SHALL hide the remove button.
5. THE Onboarding_Form SHALL mark the document upload section as optional.
6. WHEN the form is submitted with documents, THE Staff_Module SHALL store the documents using the existing compliance document infrastructure, linked to the staff member and organisation.

### Requirement 8: Onboarding Form — Residency Information Section

**User Story:** As a staff member, I want to declare my residency status, so that my employer knows my working rights situation.

#### Acceptance Criteria

1. THE Onboarding_Form SHALL display a dropdown for residency type with options: NZ Citizen, Permanent Resident, Work Visa, Student Visa, Other.
2. WHILE residency type is "Work Visa" or "Student Visa", THE Onboarding_Form SHALL display an additional date field for visa expiry date AND SHALL require a valid (non-past, non-empty) visa expiry date before allowing submission.
3. IF a visa expiry date that is in the past OR equal to the current date is entered, THEN THE Onboarding_Form SHALL display an error indicating the visa has expired AND SHALL block form submission until a valid future expiry date is provided (visa types always require a valid date before submission).

### Requirement 9: Onboarding Form Submission

**User Story:** As a staff member, I want to submit my completed onboarding form, so that my information is saved to the system.

#### Acceptance Criteria

1. WHEN the staff member clicks Submit, THE Onboarding_Form SHALL validate all entered fields according to their respective validation rules.
2. IF validation fails, THEN THE Onboarding_Form SHALL display inline error messages next to the invalid fields without losing entered data. (This per-field message requirement is subsumed by the general human-readable error rule in Requirement 14.)
3. WHEN the form is submitted successfully, THE Staff_Module SHALL update the staff member record with all provided information.
4. WHEN the form is submitted successfully, THE Staff_Module SHALL encrypt the IRD number and bank account number before storage using envelope encryption.
5. WHEN the form is submitted successfully, THE Onboarding_Form SHALL display a confirmation message thanking the staff member.
6. WHEN the form is submitted successfully, THE Staff_Module SHALL mark the Onboarding_Token as consumed.
7. IF envelope encryption of the IRD number or bank account number fails after validation has passed, THEN THE Staff_Module SHALL reject the entire submission, SHALL NOT store any submitted data in unencrypted form, AND SHALL require the staff member to resubmit.
8. IF a submission fails for any reason (validation failure, encryption failure, persistence failure, or any other error), THEN THE Staff_Module SHALL NOT mark the Onboarding_Token as consumed, so that the token remains available for resubmission until a successful submission occurs.
9. WHEN a staff member successfully submits the onboarding form, THE Staff_Module SHALL write an audit log entry (org-scoped, entity type staff_member, capturing the submitter's IP address) recording that onboarding was completed, in the same transaction as the data persistence and token consumption. THE Staff_Module SHALL NOT include plaintext IRD or bank account values in the audit entry.

### Requirement 10: Resend and Manage Onboarding Links

**User Story:** As an admin, I want to resend or revoke onboarding links, so that I can handle cases where the staff member lost the email or left the company.

#### Acceptance Criteria

1. WHEN viewing a staff member's detail page AND an active (non-expired, non-consumed) onboarding token exists, THE Staff_Module SHALL display the token status (pending, with expiry date). (Extended by Requirement 13, which expands this status into the distinct lifecycle states not_started, in_progress, completed, expired, and revoked, with completion percentage and last-saved timestamp; the meaning of this criterion is unchanged.)
2. WHEN the admin clicks "Resend onboarding link" on the staff detail page, THE Staff_Module SHALL revoke the existing token AND generate a new token AND send a new onboarding email.
3. WHEN the admin clicks "Revoke onboarding link", THE Staff_Module SHALL mark the token as revoked AND the onboarding form SHALL reject access for that token. THE Onboarding_Form SHALL reject access to any revoked token regardless of how it became revoked (manual revocation, resend-triggered revocation, or automatic revocation on staff deactivation).
4. WHEN a staff member is deactivated, THE Staff_Module SHALL revoke all onboarding tokens for that staff member regardless of each token's current state (pending, already revoked, or otherwise), so that no token can be used after deactivation.
5. WHILE a staff member is deactivated, THE Staff_Module SHALL prevent generation of any new onboarding token for that staff member.

### Requirement 11: Public Onboarding Page Routing and Security

**User Story:** As the system, I want the onboarding page to be accessible without login but protected against abuse, so that staff can complete onboarding securely.

#### Acceptance Criteria

1. THE Onboarding_Form SHALL be served at a public URL path (no authentication required) following the pattern `/onboard/{token}`.
2. THE Staff_Module SHALL apply per-IP rate limiting of 30 requests per minute to the onboarding endpoints.
3. WHEN the onboarding form page loads, THE Onboarding_Form SHALL validate the token and display the form only if the token is valid, not expired, not consumed, and not revoked.
4. IF an onboarding URL is visited with an invalid, expired, consumed, or revoked token, THEN THE Onboarding_Form SHALL display a distinct, appropriate error message for each token failure state rather than a blank page. (These per-token-state messages are subsumed by the general human-readable error rule in Requirement 14.)
5. THE Onboarding_Form SHALL transmit all data over HTTPS.
6. THE Onboarding_Form SHALL not expose sensitive staff data beyond first name and email in the pre-filled fields.

### Requirement 12: Save Draft and Resume Later

**User Story:** As a staff member, I want to save my onboarding progress and continue later from any device, so that I do not lose work.

#### Acceptance Criteria

1. WHEN the staff member activates the "Save as draft" action on the Onboarding_Form, THE Staff_Module SHALL persist the current partial form data as an Onboarding_Draft server-side keyed to the Onboarding_Token.
2. WHEN a form field loses focus, THE Onboarding_Form SHALL persist the current partial form data as an Onboarding_Draft server-side using debounced autosave.
3. WHEN the staff member reopens the same onboarding link AND a saved Onboarding_Draft exists, THE Onboarding_Form SHALL repopulate the previously saved Onboarding_Draft values into the corresponding fields.
4. WHEN the staff member reopens the same onboarding link, THE Onboarding_Form SHALL pre-fill the first name and email from the staff record as read-only fields.
5. WHEN an Onboarding_Draft is saved, THE Staff_Module SHALL accept partial or incomplete data AND SHALL NOT enforce submit-time field validation, so that incomplete fields do not block saving.
6. WHEN an Onboarding_Draft containing an IRD number or bank account number is persisted, THE Staff_Module SHALL envelope-encrypt the partial IRD number and partial bank account number during the save process, so that the values are encrypted as part of saving and are never persisted in unencrypted form.
7. WHEN an Onboarding_Draft is saved, THE Staff_Module SHALL leave the Onboarding_Token in its pending state AND SHALL keep the Onboarding_Token usable until successful submission or token expiry.
8. WHEN a staff member successfully submits the onboarding form, THE Staff_Module SHALL purge the associated Onboarding_Draft.
9. WHEN an Onboarding_Token is revoked or has expired, THE Staff_Module SHALL purge the associated Onboarding_Draft. THE purge operation SHALL be idempotent AND SHALL handle the revoked and expired trigger conditions occurring simultaneously gracefully, so that concurrent or repeated purge triggers do not error or interfere with one another.
10. WHEN the staff member reopens an onboarding link whose Onboarding_Draft has been purged (due to token expiry or revocation), THE Onboarding_Form SHALL display a human-readable message explaining that the saved draft is no longer available AND SHALL direct the staff member to request a new onboarding link from their employer.
11. THE Staff_Module SHALL apply per-IP rate limiting of 30 requests per minute to the Onboarding_Draft endpoints AND SHALL serve the Onboarding_Draft endpoints over HTTPS, consistent with the other public onboarding endpoints (see Requirement 11).

### Requirement 13: Onboarding Progress Visibility for Admin

**User Story:** As an admin, I want to see whether a staff member has started, saved a draft, or completed onboarding, and how far along they are, so that I can follow up.

#### Acceptance Criteria

1. WHEN viewing a staff member's onboarding-link status, THE Staff_Module SHALL report exactly one lifecycle state from: not_started (Onboarding_Token pending with no Onboarding_Draft saved), in_progress (an Onboarding_Draft has been saved), completed (onboarding submitted and Onboarding_Token consumed), expired (Onboarding_Token pending and past expiry), and revoked (Onboarding_Token revoked).
2. WHILE the onboarding-link status is in_progress, THE Staff_Module SHALL include the Completion_Percentage AND the last-saved timestamp of the Onboarding_Draft in the status. THE Staff_Module SHALL also include the relevant timestamp for each other lifecycle state (not_started: token creation time; completed: submission/consumption time; expired: expiry time; revoked: revocation time).
3. THE Staff_Module SHALL compute the Completion_Percentage as a deterministic, section-weighted figure across the Onboarding_Form sections (Personal, Bank, IRD/Tax, Residency, Documents).
4. THE Staff_Module SHALL compute the Completion_Percentage server-side.
5. WHEN the staff detail page renders the onboarding-link card, THE Staff_Module SHALL surface the lifecycle state, and where applicable the Completion_Percentage and last-saved timestamp, on that card.

### Requirement 14: Human-Readable Error Messages

**User Story:** As a user (a staff member on the public onboarding form, or an admin using the onboarding-link controls), I want every error to be a clear human-readable message, so that I understand what went wrong and what to do.

#### Acceptance Criteria

1. WHEN any public onboarding endpoint returns an error response, THE Staff_Module SHALL include a human-readable message describing the problem and, where helpful, the corrective action.
2. WHEN any admin onboarding-link endpoint returns an error response, THE Staff_Module SHALL include a human-readable message describing the problem and, where helpful, the corrective action.
3. WHERE an error response includes a machine-readable code, THE Staff_Module SHALL include that code as a secondary field AND SHALL always include a human-readable message alongside it.
4. WHEN an error arises from a token-state rejection (expired, revoked, consumed, not-found, or staff-inactive), a validation failure, an encryption failure, an email-send failure, or an unexpected server error, THE Staff_Module SHALL include a human-readable message in the error response.
5. WHEN an error response is returned to a user, THE Staff_Module SHALL exclude raw database text and raw exception text from the response, consistent with the humanized-error approach used elsewhere in the platform.

> Note: This general rule subsumes the per-field error messaging of Requirement 9.2 and the per-token-state error messaging of Requirement 11.4.

### Requirement 15: Staff Completion Confirmation Email

**User Story:** As a staff member, I want to receive a confirmation email after I finish onboarding, so that I know my details were submitted successfully.

#### Acceptance Criteria

1. WHEN a staff member successfully submits the Onboarding_Form, THE Email_Sender SHALL send a Confirmation_Email to the staff member's email address thanking the staff member for completing onboarding.
2. THE Confirmation_Email SHALL include the organisation name AND a friendly thank-you message.
3. WHEN a staff member successfully submits the Onboarding_Form, THE Staff_Module SHALL send the Confirmation_Email in addition to the on-screen confirmation message described in Requirement 9.5.
4. IF the Confirmation_Email fails to send, THEN THE Staff_Module SHALL log the failure AND SHALL NOT roll back or block the successful onboarding submission (the Confirmation_Email is best-effort).
5. WHEN a staff member saves an Onboarding_Draft, THE Staff_Module SHALL NOT send the Confirmation_Email (the Confirmation_Email is sent only on successful final submission).

### Requirement 16: Organisation Notification on Onboarding Completion

**User Story:** As an admin (an organisation user who can send onboarding links), I want to be notified in-app and by email when a staff member completes their onboarding, so that I can review and act on the submitted details.

#### Acceptance Criteria

1. WHEN a staff member successfully submits the Onboarding_Form, THE Staff_Module SHALL create an In_App_Notification visible to the organisation users whose role can send onboarding links (`org_admin` and `branch_admin`), identifying the staff member who completed onboarding.
2. THE In_App_Notification SHALL link to the staff member's detail page.
3. WHEN a staff member successfully submits the Onboarding_Form, THE Email_Sender SHALL send an email to the same organisation users (`org_admin` and `branch_admin`) notifying them that the staff member has completed onboarding.
4. THE Onboarding_Completion_Notification SHALL identify the organisation and branch context so that the notifications are scoped to the correct organisation.
5. WHEN a staff member saves an Onboarding_Draft, THE Staff_Module SHALL NOT generate an Onboarding_Completion_Notification (the notifications are generated only on successful final submission).
6. IF creating the In_App_Notification or sending the notification email fails, THEN THE Staff_Module SHALL log the failure AND SHALL NOT roll back or block the successful onboarding submission (the Onboarding_Completion_Notification is best-effort).
7. WHEN any notification operation (In_App_Notification creation or notification email send) is attempted, THE Staff_Module SHALL log the outcome of that attempt regardless of whether an onboarding submission occurred.
