# Requirements Document — Customer Reminder Consent

## Introduction

OraInvoice sends WOF, COF, registration, and service-due reminder messages to customers via SMS and email. Under New Zealand law these are **commercial electronic messages**, which means each one requires a recipient's consent that the sender can prove on demand.

This feature adds consent capture, consent recording, and consent-honouring (revocation) flows to the existing reminder pipeline so the workshop can prove compliance with:

- **Unsolicited Electronic Messages Act 2007 (NZ)** — every commercial electronic message sent to or from a New Zealand-linked address requires the recipient's express, inferred, or deemed consent. The burden of proving consent lies on the sender. Penalties on conviction are up to NZ$200,000 for an individual and NZ$500,000 for a body corporate, per breach. The Act also requires a functional unsubscribe facility in every commercial electronic message and that an unsubscribe request be honoured within five working days of receipt.
- **Privacy Act 2020 (NZ)** — at the time we collect a customer's phone number or email address we must tell the customer the purpose of collection (Information Privacy Principle 3), and we must allow withdrawal of consent.

The workshop has chosen **manual / phone-based opt-out** as our compliance mechanism for the functional-unsubscribe requirement, supported by **automatic enqueue-time validity gating** that stops reminders firing once their underlying date has lapsed. We treat this as satisfying the Act's "functional unsubscribe facility" requirement because the Customer can revoke consent at any time by contacting the workshop, and an Org_User records that revocation in the system within the same business day — well inside the five-working-day legal window. Self-service unsubscribe (SMS STOP keyword handler, email unsubscribe link, customer-facing `/unsubscribe` endpoint) is explicitly out of scope of this spec.

Today's gaps that this spec closes:

1. The kiosk self-checkin screen captures phone and email but does not explicitly ask for consent to ongoing reminder messages. Inferred consent for the current job does not extend to ongoing future reminders.
2. Org users can manually toggle reminders on a customer profile with no check that consent has been obtained.
3. The system has no record of when consent was given, how it was given, or by which staff member it was recorded.
4. There is no first-class staff-facing flow for recording a verbal opt-out received over the phone or in person.
5. The reminder enqueue path skips reminders when an expiry date is `NULL` but does not skip when the date has already passed, so a Customer who never returns can keep receiving "your WOF is overdue" messages indefinitely.

The reminder consent record is stored as JSONB inside the existing `customer.custom_fields` column under the keys `reminder_consent` and `reminder_consent_revocations`. No new database schema migration is required.

## Glossary

- **The_System** — The OraInvoice platform: backend (FastAPI, `app.modules.customers`, `app.modules.kiosk`, `app.modules.notifications`, `app.modules.sms_chat`) and frontend (`frontend-v2/src/pages/customers/*`, `frontend-v2/src/pages/kiosk/*`).
- **The_Kiosk_App** — The public-facing self-checkin screen at `frontend-v2/src/pages/kiosk/*`, served from a tablet at the workshop reception. Supports multi-vehicle check-in via `KioskCheckInRequestV2.vehicles`.
- **Org_User** — An authenticated user of an organisation with role `org_admin` or `salesperson` (the roles that can call `PUT /customers/{id}/reminders` today).
- **Customer** — A person whose contact details are recorded in the `customers` table. The recipient of reminder messages.
- **Reminder** — A commercial electronic message of category `wof_expiry`, `cof_expiry`, `registration_expiry`, or `service_due`, delivered via channel `email` or `sms`. The four categories map to the existing notification templates `wof_expiry_reminder`, `cof_expiry_reminder`, `registration_expiry_reminder`, and `service_due_reminder`.
- **Reminder_Category** — One of the four enumerated reminder kinds: `wof_expiry`, `cof_expiry`, `registration_expiry`, `service_due`.
- **Reminder_Channel** — One of `sms`, `email`, or `both`.
- **Inspection_Type** — The mutually-exclusive NZ inspection regime that applies to a vehicle: `wof` (Warrant of Fitness — light vehicles) or `cof` (Certificate of Fitness — heavy or passenger-service vehicles). Sourced from `GlobalVehicle.inspection_type` (mirrored on `OrgVehicle.inspection_type`), populated by CarJam at vehicle lookup time via `app/integrations/carjam.py::_derive_inspection_type` from the `subject_to_wof` / `subject_to_cof` Y/N flags. May be `NULL` for non-vehicle services or when CarJam did not return either flag. A NZ vehicle is never subject to both at once.
- **reminder_config** — The existing JSONB blob at `customer.custom_fields["reminder_config"]` controlling whether each Reminder_Category is enabled, the days-before lead time, and the delivery channel. Read and written by `app.modules.customers.service.update_customer_reminder_config` and the `GET`/`PUT /customers/{id}/reminders` endpoints. Note that this blob is **per-Customer**, not per-vehicle: when a Customer has multiple vehicles, the union of consented categories and channels across all vehicles is what gets persisted here.
- **reminder_consent** — A new JSONB blob at `customer.custom_fields["reminder_consent"]` recording the legal evidence that the Customer agreed to receive reminders. Created or replaced by this feature. Its `entries` field is a list of `{vehicle_id, category, channel}` triples giving per-vehicle, per-category, per-channel granularity. (The previous-draft top-level `categories` array and `channels` array are removed in favour of `entries`.)
- **reminder_consent_revocations** — A new JSONB list at `customer.custom_fields["reminder_consent_revocations"]` recording each consent withdrawal event. Each entry has fields `revoked_at`, `source` (always begins with `manually_recorded_by_staff:` followed by the obtained-method key — for example `manually_recorded_by_staff:phone`), `recorded_by_user_id`, `recorded_by_user_email`, `channel`, `categories_affected`, and `reason_note`. Appended to by this feature.
- **Express_Consent** — Consent given by the Customer through a clear, deliberate act (a deliberately-ticked checkbox or a verbal "yes" recorded by a staff member). Defined by the Unsolicited Electronic Messages Act 2007.
- **Inferred_Consent** — Consent reasonably inferred from the conduct or business relationship of the Customer (for example, an existing customer relationship). Inferred consent is narrower than express consent and does not extend to ongoing future reminders unrelated to the current transaction.
- **Consent_Text_Version** — A string identifier (e.g., `2026-06-08-v1`) recorded on every consent record so The_System can prove which exact wording the Customer agreed to. Stored as `consent_text_version`.
- **Audit_Log_Row** — A row in the existing `audit_log` table (action string, before/after JSON values, actor user id, organisation id, timestamp).
- **Working_Day** — A day other than a Saturday, Sunday, or New Zealand public holiday, per the Unsolicited Electronic Messages Act 2007 definition. Used for the revocation-honour deadline.

## Requirements

### Requirement 1 — Kiosk consent capture

**User Story:** As a Customer using the self-checkin kiosk, I want to be asked clearly whether I consent to receive WOF, COF, registration, and service reminders by SMS or email, so that the workshop has my Express_Consent under the Unsolicited Electronic Messages Act 2007 and a record sufficient to discharge the burden of proof.

#### Acceptance Criteria

1. THE The_Kiosk_App SHALL render a Reminder Consent step or section that appears only after the Customer has entered name, phone, and email values on the customer-details step.
2. WHEN the Reminder Consent step or section first renders for a check-in, THE The_Kiosk_App SHALL display the master consent checkbox in the unchecked state.
3. WHEN the Reminder Consent step or section first renders for a check-in, THE The_Kiosk_App SHALL display every Reminder_Category sub-checkbox row and every per-checkbox channel sub-control in their default state regardless of any value previously stored in browser localStorage, sessionStorage, autofill, or for any prior check-in on the same kiosk.
4. WHEN the master consent checkbox is in the unchecked state, THE The_Kiosk_App SHALL hide the Reminder_Category sub-checkboxes and every per-checkbox channel sub-control.
5. WHEN the master consent checkbox transitions from unchecked to checked, THE The_Kiosk_App SHALL render, for each vehicle the Customer is checking in (the kiosk supports multi-vehicle check-in via `KioskCheckInRequestV2.vehicles`), a vehicle row containing the rego, the make and model when known, and a vehicle-aware set of Reminder_Category sub-checkboxes determined by the rules in criteria 5a through 5e below, each pre-selected as checked.
   - **5a.** WHEN `vehicle.inspection_type` equals `"cof"`, OR (`vehicle.cof_expiry IS NOT NULL` AND `vehicle.wof_expiry IS NULL`), THE The_Kiosk_App SHALL render exactly one inspection-type sub-checkbox labelled "COF expiry" for that vehicle row, mapped to Reminder_Category `cof_expiry` (heavy or passenger-service vehicle).
   - **5b.** WHEN `vehicle.inspection_type` equals `"wof"`, OR (`vehicle.wof_expiry IS NOT NULL` AND `vehicle.cof_expiry IS NULL`), THE The_Kiosk_App SHALL render exactly one inspection-type sub-checkbox labelled "WOF expiry" for that vehicle row, mapped to Reminder_Category `wof_expiry` (light vehicle).
   - **5c.** WHEN both `vehicle.wof_expiry` and `vehicle.cof_expiry` are populated (rare or legacy data), THE The_Kiosk_App SHALL prefer the `vehicle.inspection_type` value; if `vehicle.inspection_type` is `NULL`, THE The_Kiosk_App SHALL render the COF sub-checkbox (heavier-compliance preference).
   - **5d.** WHEN both `vehicle.wof_expiry` and `vehicle.cof_expiry` are `NULL` AND `vehicle.inspection_type` is `NULL` (non-vehicle service or unknown), THE The_Kiosk_App SHALL NOT render an inspection-type sub-checkbox for that vehicle row.
   - **5e.** THE The_Kiosk_App SHALL render the `registration_expiry` and `service_due` sub-checkboxes for every vehicle row that represents an actual vehicle (i.e., not a non-vehicle service such as a plumbing call-out). For non-vehicle services The_Kiosk_App SHALL render only the `service_due` sub-checkbox.
6. FOR EACH Reminder_Category sub-checkbox the Customer ticks (per vehicle, per category), THE The_Kiosk_App SHALL render a per-checkbox channel sub-control with options `SMS`, `Email`, and `Both`, with no option pre-selected.
7. THE The_Kiosk_App MAY group multiple vehicles under a single Reminder Consent step or section. The master consent checkbox and the Consent_Text apply once across the step; each vehicle row inside the step carries its own set of sub-checkboxes per criterion 5, and each ticked sub-checkbox carries its own channel sub-control per criterion 6. The submit control becomes enabled only when, for every ticked sub-checkbox across all vehicle rows, a channel has been chosen.
8. THE The_Kiosk_App SHALL display the Consent_Text within the Reminder Consent step or section, and the Consent_Text SHALL state (a) what categories of message will be sent, (b) that the Customer can revoke consent at any time by phoning the workshop, and (c) that consent can be withdrawn at any time without penalty.
9. THE The_Kiosk_App SHALL render the primary Consent_Text at a CSS font size of at least 14 pixels and any secondary or supporting text at a CSS font size of at least 12 pixels.
10. THE The_Kiosk_App SHALL render every interactive control on the Reminder Consent step or section with a CSS-pixel hit area of at least 44 by 44 pixels.
11. THE The_Kiosk_App SHALL keep the "Continue" or "Complete check-in" submit control enabled regardless of whether the master consent checkbox is checked or unchecked, EXCEPT WHEN the master consent checkbox is checked and at least one ticked sub-checkbox is missing a channel selection, in which case THE The_Kiosk_App SHALL disable the submit control until every ticked sub-checkbox has a channel chosen.
12. WHEN the Customer submits the check-in with the master consent checkbox unchecked, THE The_System SHALL complete the check-in without writing any value to `customer.custom_fields["reminder_consent"]` and without modifying `customer.custom_fields["reminder_config"]`.
13. WHEN the Customer submits the check-in with the master consent checkbox checked and at least one ticked sub-checkbox with a channel chosen, THE The_System SHALL persist `customer.custom_fields["reminder_consent"]` containing fields `given_at` (UTC ISO 8601 timestamp), `source` (the literal string `kiosk_self_checkin`), `kiosk_session_id` (the kiosk session identifier), `entries` (a list of `{vehicle_id, category, channel}` triples — one per ticked sub-checkbox across all vehicle rows), `ip_address` (the request client IP), `user_agent` (the request `User-Agent` header value, truncated at 500 characters), and `consent_text_version` (the Consent_Text_Version that was rendered).
14. WHEN the Customer submits the check-in with the master consent checkbox checked, THE The_System SHALL update `customer.custom_fields["reminder_config"]` so that for every Reminder_Category present in `reminder_consent.entries` the entry is `{enabled: true, channel: <selected channel>, days_before: <existing or default value>}`. Because `reminder_config` is per-Customer (not per-vehicle), when the same Customer has multiple vehicles consenting to the same Reminder_Category with different channels, THE The_System SHALL persist the union: a category appears as `enabled: true` and the channel is `both` if any ticked entry chose `both` or if the per-vehicle channels differ; otherwise the channel is the single value all entries chose.
15. WHEN the Customer submits the check-in with the master consent checkbox checked, THE The_System SHALL write the consent record and the reminder configuration in the same database transaction as the check-in customer record.
16. IF persistence of `reminder_consent` or `reminder_config` fails during a check-in submission, THEN THE The_System SHALL roll back the entire transaction so that neither value is persisted and the customer is not created or updated, and SHALL return an HTTP 500 response with body `{"error": "consent_persistence_failed"}`.
17. WHEN persistence of `reminder_consent` succeeds, THE The_System SHALL write exactly one Audit_Log_Row with action `customer.reminder_consent.given`, with `after_value` containing the consent record fields excluding `ip_address` and excluding `user_agent`.

### Requirement 2 — Manual enable warning on customer profile

**User Story:** As an Org_User configuring reminders on a customer profile, I want to be warned when I try to enable a reminder for a Customer whose consent record does not cover the new reminder, so that I confirm consent has been obtained before activating the reminder and satisfy the burden-of-proof requirement under the Unsolicited Electronic Messages Act 2007.

#### Acceptance Criteria

1. WHEN the Configure Reminders modal in `frontend-v2/src/pages/customers/CustomerList.tsx` or `frontend-v2/src/pages/customers/CustomerProfile.tsx` opens, THE The_System SHALL fetch the current `reminder_config` and the current `reminder_consent` for the Customer and display the consent state alongside each Reminder_Category row.
2. WHEN the Org_User submits the Configure Reminders modal, THE The_System SHALL compute, for every (Reminder_Category, Reminder_Channel) pair whose new state is `enabled: true`, whether a covering `reminder_consent` record exists. A consent record covers a (Reminder_Category, Reminder_Channel) pair when `reminder_consent.entries` contains at least one entry whose `category` equals the Reminder_Category and whose `channel` equals the Reminder_Channel or equals `both`.
3. WHEN the submission contains at least one (Reminder_Category, Reminder_Channel) pair whose previous state was not `enabled: true` and whose new state is `enabled: true` and that does not have a covering `reminder_consent` record, THE The_System SHALL block the underlying `PUT /customers/{id}/reminders` call and SHALL display a Consent Confirmation modal in front of the Configure Reminders modal.
4. THE Consent Confirmation modal SHALL display the Consent_Text for manual recording, list each (Reminder_Category, Reminder_Channel) pair that requires confirmation, and contain a required single-select control labelled "How was consent obtained?" with options `verbal_in_person`, `phone`, `email_reply`, `written_form`, and `other` and SHALL require a free-text note when `other` is selected.
5. THE Consent Confirmation modal SHALL contain a Confirm control and a Cancel control.
6. WHEN the Org_User activates the Cancel control on the Consent Confirmation modal, THE The_System SHALL close the Consent Confirmation modal and SHALL discard the pending reminder configuration change so that no `PUT /customers/{id}/reminders` call is issued and no `reminder_consent` record is written.
7. WHEN the Org_User activates the Confirm control on the Consent Confirmation modal, THE The_System SHALL persist `customer.custom_fields["reminder_consent"]`, in the same database transaction as the `reminder_config` update, with fields `given_at` (UTC ISO 8601 timestamp), `source` (the literal string `manually_recorded_by_staff:<obtained_method>` where `<obtained_method>` is the selected option key), `recorded_by_user_id` (the authenticated user id), `recorded_by_user_email` (the authenticated user email), `entries` (a list of `{vehicle_id: null, category, channel}` triples — one per (Reminder_Category, Reminder_Channel) pair being confirmed; `vehicle_id` is `null` because manual confirmation is per-Customer not per-vehicle), `consent_text_version` (the Consent_Text_Version that was rendered), and, when `other` was selected, `manual_note` (the free-text note).
8. IF persistence of `reminder_consent` fails when the Org_User activates the Confirm control, THEN THE The_System SHALL roll back the transaction so that `reminder_config` is not updated either, and SHALL return an HTTP 500 response with body `{"error": "consent_persistence_failed"}`.
9. WHEN persistence of `reminder_consent` succeeds via the Consent Confirmation modal, THE The_System SHALL write exactly one Audit_Log_Row with action `customer.reminder_consent.given`, with `after_value` containing the consent record fields.
10. WHEN every (Reminder_Category, Reminder_Channel) pair whose new state is `enabled: true` already has a covering `reminder_consent` record, THE The_System SHALL submit the `PUT /customers/{id}/reminders` request without displaying the Consent Confirmation modal and without writing a new `reminder_consent` record.
11. WHEN a (Reminder_Category, Reminder_Channel) pair whose new state is `enabled: false` is submitted, THE The_System SHALL submit the `PUT /customers/{id}/reminders` request without displaying the Consent Confirmation modal and without writing a `reminder_consent` record.
12. THE backend `PUT /customers/{id}/reminders` endpoint SHALL accept an optional request field `consent_record` whose presence indicates that the caller has provided a consent record to persist alongside the configuration update, and SHALL reject with HTTP 409 and body `{"error": "consent_required", "missing": [{"category": ..., "channel": ...}, ...]}` any request that newly enables a (Reminder_Category, Reminder_Channel) pair without a covering existing `reminder_consent` and without a `consent_record` in the request body.
13. WHEN The_System receives a repeat `PUT /customers/{id}/reminders` call that newly enables a (Reminder_Category, Reminder_Channel) pair that is not covered by `reminder_consent` and that does not include a `consent_record` field, THE The_System SHALL respond with HTTP 409 and SHALL NOT modify `reminder_config`.

### Requirement 3 — Manual revocation by org user (verbal opt-out)

**User Story:** As an Org_User, when a Customer phones the workshop or tells me in person that they want to stop receiving reminders, I want to record that revocation so that the Customer's withdrawal of consent is honoured and we can prove honour-within-deadline under the Unsolicited Electronic Messages Act 2007.

#### Acceptance Criteria

1. THE Customer Profile screen Reminder Consent section SHALL render a "Revoke consent" control beside each active consented (Reminder_Category, Reminder_Channel) entry — that is, every entry in `reminder_consent.entries` whose corresponding `reminder_config[<category>].enabled` is currently `true`.
2. WHEN the Org_User activates the Revoke control, THE The_System SHALL display a Revocation modal containing: a required free-text reason field labelled "Reason note", a required single-select source dropdown with options `phone` (label "Phone call from customer"), `in_person` (label "In person"), `email_reply` (label "Email reply"), and `other` (label "Other (free text)"), and a Confirm and Cancel control pair. WHEN `other` is selected, THE The_System SHALL require the free-text reason field to be non-empty and treat it as the explanatory note.
3. WHEN the Org_User activates the Cancel control on the Revocation modal, THE The_System SHALL close the modal and SHALL NOT modify `reminder_config` and SHALL NOT append to `reminder_consent_revocations`.
4. WHEN the Org_User activates the Confirm control on the Revocation modal, THE The_System SHALL set `customer.custom_fields["reminder_config"][<category>]["enabled"]` to `false` for every Reminder_Category in the affected (Reminder_Category, Reminder_Channel) entries and SHALL append to `customer.custom_fields["reminder_consent_revocations"]` exactly one record with fields `revoked_at` (UTC ISO 8601 timestamp), `source` (the literal string `manually_recorded_by_staff:<obtained_method>` where `<obtained_method>` is the selected source dropdown key), `recorded_by_user_id` (the authenticated user id), `recorded_by_user_email` (the authenticated user email), `channel` (the affected Reminder_Channel), `categories_affected` (the list of Reminder_Category values that were turned off by this revocation), and `reason_note` (the free-text reason).
5. THE The_System SHALL perform the `reminder_config` update and the `reminder_consent_revocations` append in the same database transaction.
6. IF persistence of either `reminder_config` or `reminder_consent_revocations` fails when the Org_User activates the Confirm control, THEN THE The_System SHALL roll back the transaction so that neither value is persisted, and SHALL return an HTTP 500 response with body `{"error": "revocation_persistence_failed"}`.
7. WHEN persistence succeeds, THE The_System SHALL write exactly one Audit_Log_Row with action `customer.reminder_consent.revoked`, with `after_value` containing `revoked_at`, `source`, `channel`, `categories_affected`, and `reason_note`, and excluding `recorded_by_user_id` and `recorded_by_user_email` from `after_value` (the actor identity is already captured by the `audit_log` row's own `user_id` column).
8. THE The_System SHALL apply every manual revocation no later than the same Working_Day on which the Org_User confirms the Revocation modal, well inside the five-Working-Day deadline imposed by the Unsolicited Electronic Messages Act 2007.
9. THE The_System SHALL persist the full `reason_note`, `recorded_by_user_id`, and `recorded_by_user_email` inside `customer.custom_fields["reminder_consent_revocations"]` (per the redaction rules of Requirement 7) so the legal evidence is preserved on the customer record itself.

### Requirement 4 — Auto-suppression based on validity windows

**User Story:** As a Compliance Officer, I want reminders to stop firing automatically when the underlying expiry or service-due date has already passed (because the Customer didn't return for the service), so that we don't continue to message Customers about already-expired things and so that reminders quietly resume the next time the date is updated, all without requiring re-consent.

The reminder enqueue path at `app/modules/notifications/reminder_queue_service.py::enqueue_customer_reminders` already iterates over `(wof_expiry, cof_expiry, registration_expiry, service_due)` per vehicle and skips when the relevant date column is `NULL`. This requirement extends that gate to also skip when the relevant date is on or before today's date in the organisation's local timezone.

#### Acceptance Criteria

1. THE `enqueue_customer_reminders` task SHALL skip a (Customer, vehicle, Reminder_Category) tuple when the relevant date is `NULL` (existing behaviour) OR when the relevant date is on or before today's date in the organisation's local timezone (new behaviour). The check SHALL be `relevant_date > today_in_org_timezone` (strict inequality), so a same-day expiry is treated as expired and reminders stop the day OF expiry once the morning enqueue run has executed — the safer interpretation for compliance.
2. THE relevant-date mapping for each Reminder_Category SHALL be:
   - `wof_expiry` → `vehicle.wof_expiry`
   - `cof_expiry` → `vehicle.cof_expiry`
   - `registration_expiry` → `vehicle.registration_expiry`
   - `service_due` → `vehicle.service_due_date`
3. WHEN the relevant date for a (Customer, vehicle, Reminder_Category) tuple is `NULL` or on or before today, THE `enqueue_customer_reminders` task SHALL leave `customer.custom_fields["reminder_config"][<category>]["enabled"]` unchanged at its current value (typically `true`) so that reminders resume automatically the next time the underlying date moves to a future value (e.g., a fresh CarJam refresh, a new WOF inspection invoice line, or an admin manual edit on the vehicle record), WITHOUT requiring re-consent — the original `(Customer, Reminder_Category, Reminder_Channel)` consent tuple is unchanged.
4. WHEN the relevant date for a (Customer, vehicle, Reminder_Category) tuple is `NULL` or on or before today, THE `enqueue_customer_reminders` task SHALL emit a debug-level log line of the form `skipped: <category> for <vehicle_rego> — date <relevant_date> is on or before today` so operators can confirm the gate is firing as expected.
5. THE auto-suppression behaviour SHALL NOT modify `customer.custom_fields["reminder_config"]` and SHALL NOT append to `customer.custom_fields["reminder_consent_revocations"]`. Auto-suppression is purely an enqueue-time gate.
6. THE The_System SHALL NOT write an Audit_Log_Row per auto-suppressed enqueue pass — these skips are quiet by design. (Sending a reminder still emits the existing `notification_sent` row; non-sending is the absence of one.)
7. WHEN the relevant date for a (Customer, vehicle, Reminder_Category) tuple subsequently moves to a future value, THE next run of `enqueue_customer_reminders` SHALL produce exactly the configured set of queue rows for that tuple, identical to what it would have produced if the date had been future-valued throughout, with no additional consent re-grant required.

### Requirement 5 — Consent visibility on customer record

**User Story:** As an Org_User, I want to see when and how a Customer's reminder consent was recorded and any subsequent revocations, so that I can produce evidence on demand if a compliance challenge is raised.

#### Acceptance Criteria

1. THE Customer Profile screen at `frontend-v2/src/pages/customers/CustomerProfile.tsx`, in a section labelled "Reminder Consent", SHALL render the value of `customer.custom_fields["reminder_consent"]["source"]`, the value of `reminder_consent.given_at` formatted in the organisation's locale and timezone, the resolved display name of the user identified by `reminder_consent.recorded_by_user_id` when that field is present, the value of `reminder_consent.consent_text_version`, and the contents of `reminder_consent.entries` rendered as a per-vehicle, per-category, per-channel grid.
2. WHEN `customer.custom_fields["reminder_consent"]` is absent, THE Customer Profile screen SHALL display the literal string "No consent on record" in the Reminder Consent section.
3. THE Customer Profile screen Reminder Consent section SHALL render every entry of `customer.custom_fields["reminder_consent_revocations"]` showing `revoked_at` formatted in the organisation's locale and timezone, `source`, `channel`, `categories_affected`, the resolved display name of the user identified by `recorded_by_user_id`, and `reason_note`.
4. THE Configure Reminders modal SHALL render, beside each Reminder_Category row, a visual indicator showing whether `reminder_consent` covers that (Reminder_Category, Reminder_Channel) pair.
5. WHERE the configuration option `customers_consent_column_visible` is enabled in org settings, THE Customer List screen at `frontend-v2/src/pages/customers/CustomerList.tsx` SHALL render an additional column titled "Reminder Consent" whose value is `Yes` when `reminder_consent` is present and `No` otherwise.

### Requirement 6 — Configurable consent text and versioning

**User Story:** As a workshop owner, I want the kiosk consent wording to be reviewable and the rendered version recorded against every consent record, so that if the wording changes I can prove which exact version each Customer agreed to.

#### Acceptance Criteria

1. THE The_System SHALL define a single source of truth for the kiosk Consent_Text in either a backend constant module (e.g., `app/modules/customers/consent_text.py`) or an org-level setting key in the existing org settings JSONB store. The choice between the two is to be resolved in the design phase; both options remain in scope of this requirement.
2. THE The_System SHALL define a Consent_Text_Version string in the same source of truth as the Consent_Text and SHALL change the Consent_Text_Version whenever the Consent_Text is changed.
3. WHEN The_System renders the kiosk Consent_Text on `frontend-v2/src/pages/kiosk/*`, THE The_System SHALL also expose the Consent_Text_Version to the kiosk frontend so the frontend can include it in the check-in submission.
4. WHEN The_System persists a `reminder_consent` record from any source, THE The_System SHALL set `reminder_consent.consent_text_version` to the Consent_Text_Version that was rendered to the actor at the time consent was given.
5. WHEN the Org_User views the Customer Profile Reminder Consent section, THE The_System SHALL render the literal value of `reminder_consent.consent_text_version` so the workshop can correlate any consent record to the exact text the Customer saw.

### Requirement 7 — Audit log shape and PII handling

**User Story:** As a Compliance Officer, I want consent-related Audit_Log_Rows to record what happened without leaking the kinds of PII that the audit log is not meant to hold, so that the audit log itself remains safe to export and review while the full evidence is preserved on the customer record.

#### Acceptance Criteria

1. WHEN The_System writes an Audit_Log_Row with action `customer.reminder_consent.given`, THE The_System SHALL omit the keys `ip_address` and `user_agent` from `after_value`.
2. WHEN The_System writes an Audit_Log_Row with action `customer.reminder_consent.revoked`, THE The_System SHALL include `revoked_at`, `source`, `channel`, `categories_affected`, and `reason_note` in `after_value` and SHALL NOT include `recorded_by_user_id` or `recorded_by_user_email` in `after_value` (those are recorded on the row's own `user_id` column).
3. THE The_System SHALL persist the full `ip_address` and `user_agent` values inside `customer.custom_fields["reminder_consent"]` so the legal evidence is preserved on the customer record itself. (The workshop has explicitly chosen this storage location; the audit log itself remains stripped per criteria 1 and 2.)

## Correctness Properties

The following properties are intended to be tested with property-based tests (Hypothesis), supplemented by example-based integration tests where appropriate. Each property is named so it can be referenced from the design and tasks documents.

- **CP-1 — Persistence integrity (transactional)** — For every successful kiosk check-in submission with the master consent checkbox checked, both `customer.custom_fields["reminder_consent"]` and `customer.custom_fields["reminder_config"]` are persisted in the same database transaction. For every kiosk check-in submission whose persistence of either value fails, neither value is persisted. Falsifying example: a check-in where `reminder_config` is updated but `reminder_consent` is missing.
- **CP-2 — Manual-enable gate** — For every `PUT /customers/{id}/reminders` request that newly transitions a (Reminder_Category, Reminder_Channel) pair from disabled to enabled without an existing covering `reminder_consent` and without a `consent_record` field in the request body, the response is HTTP 409 and `reminder_config` is unchanged.
- **CP-3 — Audit completeness** — For every successful consent-given action (kiosk or manual), exactly one `audit_log` row with action `customer.reminder_consent.given` is written. For every successful manual-revocation action, exactly one `audit_log` row with action `customer.reminder_consent.revoked` is written.
- **CP-4 — Default-unchecked invariant** — For every kiosk check-in initial render, the master consent checkbox, every Reminder_Category sub-checkbox, and every per-checkbox channel sub-control are in the unchecked or unselected state, regardless of any value previously stored in browser localStorage, sessionStorage, autofill state, or the kiosk's previous check-in.
- **CP-5 — Manual-revocation idempotence** — For every sequence of two or more manual-revocation Confirm activations against the same already-fully-revoked Customer (i.e., every consented entry already has `reminder_config[<category>].enabled = false`), the resulting state of `customer.custom_fields["reminder_config"]` is unchanged after the second and subsequent confirmations and the Org_User is not offered a revocation control to activate. (Manual revocation is staff-driven and gated by Requirement 3 criterion 1, which only renders the Revoke control beside currently-active consented entries — so a fully-revoked Customer has no active control to click.)
- **CP-6 — Auto-suppression invariant** — For every (Customer, vehicle, Reminder_Category) tuple where the relevant date (per Requirement 4 criterion 2) is `NULL` or on or before today's date in the organisation's local timezone, an `enqueue_customer_reminders` pass produces zero rows in `reminder_queue` for that tuple. After the relevant date is updated to a future value, the next `enqueue_customer_reminders` pass produces exactly the configured set of rows again, without any consent re-grant.

## Non-functional Requirements

### NFR-1 — Frontend safe API consumption

THE frontend code added by this feature SHALL follow `.kiro/steering/safe-api-consumption.md`: every read of an API response field uses `?.` and an `?? []` or `?? 0` fallback, every API call is typed with a generic, every `useEffect` containing an API call cleans up with an `AbortController`, and no `as any` is used to bypass typing.

### NFR-2 — Wrapped array responses

THE backend SHALL wrap every list response added by this feature in an object with at minimum the keys `items` and `total` (e.g., revocation history listings).

### NFR-3 — Storage of consent record

THE The_System SHALL store `reminder_consent` and `reminder_consent_revocations` as JSONB inside `customer.custom_fields` and SHALL NOT encrypt these values at the application layer. The Customer's `phone` and `email` columns on `customers` remain the canonical PII fields.

### NFR-4 — Kiosk accessibility

THE The_Kiosk_App Reminder Consent step or section SHALL meet WCAG 2.1 Level AA: the primary Consent_Text is rendered at a CSS font size of at least 14 pixels, secondary text at a CSS font size of at least 12 pixels, every interactive control has a 44 by 44 CSS-pixel hit area, the contrast ratio between text and background is at least 4.5 to 1 for body text and 3 to 1 for large text, and every form control has a programmatically associated visible label.

### NFR-5 — Audit log redaction shape

THE Audit_Log_Row writes performed by this feature SHALL match the redaction pattern used by the Phase 4 staff feature: `ip_address` and `user_agent` are recorded on the customer record only and are never written into an `audit_log` row's `after_value`.

### NFR-6 — Trade-family universality

THE The_System SHALL apply this feature to every organisation regardless of `tradeFamily` value (`automotive-transport`, `electrical-mechanical`, `plumbing-gas`, `building-construction`, `landscaping-outdoor`, `cleaning-facilities`, `it-technology`, `creative-professional`, `accounting-legal-financial`, `health-wellness`, `food-hospitality`, `retail`, `hair-beauty-personal-care`, `trades-support-hire`, `freelancing-contracting`). The kiosk consent UI and the manual-enable consent gate are gated only by the kiosk and customer modules respectively, not by trade family. For non-vehicle trade families (plumbing, electrical, cleaning, landscaping, IT, creative, accounting, health, food, retail, hair-beauty, trades-support, freelancing), THE The_Kiosk_App SHALL NOT render the WOF, COF, or `registration_expiry` sub-checkboxes per Requirement 1 criterion 5d/5e — only the `service_due` sub-checkbox renders, since service-due is the only Reminder_Category likely to be useful outside automotive.

### NFR-7 — Revocation latency

THE The_System SHALL apply every manual revocation no later than the same Working_Day on which the Org_User confirms the Revocation modal, well inside the five-Working-Day deadline imposed by the Unsolicited Electronic Messages Act 2007. Auto-suppression (Requirement 4) operates at every `enqueue_customer_reminders` run cadence; expired-date skips therefore take effect at the next scheduled enqueue pass after the date lapses.

## Out of Scope

The following items are explicitly excluded from this feature:

1. No new database table, no new column on `customers`, and no Alembic migration. The consent record lives entirely in `customer.custom_fields["reminder_consent"]` and `customer.custom_fields["reminder_consent_revocations"]` JSONB.
2. No redesign of the existing Configure Reminders modal layout or its endpoint contract beyond the addition of an optional `consent_record` field on `PUT /customers/{id}/reminders` and a `409 consent_required` response.
3. No change to the existing reminder enqueue or delivery pipeline (`enqueue_customer_reminders`, `process_customer_reminders`, `process_reminder_queue_scheduled`) beyond the validity-window gate added by Requirement 4 (the strict `relevant_date > today_in_org_timezone` skip and its debug log line).
4. **Self-service unsubscribe is OUT OF SCOPE.** No SMS STOP keyword handler, no email unsubscribe link, no public `/unsubscribe?token=<token>` endpoint, no unsubscribe-token table, and no HMAC-derived unsubscribe tokens. The Customer revokes consent by phoning the workshop; an Org_User records the revocation under Requirement 3.
5. No public consent-management portal page where the Customer can log in and manage their own consent settings. Customers manage consent via the kiosk (initial grant) and by phoning the workshop (revocation).
6. No backfill of historical consent records for Customers who already have `reminder_config` enabled before this feature ships. The Consent Confirmation modal in Requirement 2 will trigger on the next manual edit for those Customers.
7. No coverage of templates other than `wof_expiry_reminder`, `cof_expiry_reminder`, `registration_expiry_reminder`, and `service_due_reminder`. Other commercial electronic messages (invoices, statements, marketing) are out of scope of this consent regime spec.
8. **Manual revocation IS IN SCOPE** per the new Requirement 3. The Org_User records phone-call or in-person opt-outs through a Revocation modal on the Customer Profile screen.
