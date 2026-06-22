# Requirements Document

## Introduction

The E-Signature Integration adds a new `esignatures` module to OraInvoice that lets organisation users send documents for legally-binding digital signature through a self-hosted **Documenso** instance, track signing progress, and store the completed signed PDF back inside OraInvoice.

Two send surfaces are covered:

- **Sales and purchase agreements** initiated from the invoicing / quotes side of the platform.
- **NDAs, employment agreements, and contractor agreements** initiated from the staff Documents side.

A dedicated sidebar entry ("Agreements") provides an organisation-wide dashboard, while contextual "Send for signature" actions appear on invoice/quote pages and the Staff → Documents tab.

Documenso is the signing engine; **OraInvoice remains the system of record**. A new org-scoped table (`esign_envelopes`) maps OraInvoice documents and recipients to Documenso document identifiers. Organisation users never touch the Documenso UI or admin. OraInvoice is multi-tenant SaaS used by independent organisations, and each organisation has its **own Documenso Team** on the shared self-hosted Documenso instance, with its own team-scoped API token and its own webhook secret, provisioned by a Global Admin during that organisation's onboarding. Per-organisation provisioning is performed from the Global Admin Organisations area in one of two ways: a one-click, best-effort **auto-provision** action that attempts to create the organisation's Documenso Team, team-scoped token, and webhook automatically, or **manual** entry/editing of the connection details. Manual per-organisation provisioning is the guaranteed, supported path and remains available as the fallback at all times; auto-provisioning is an optional convenience that depends on Documenso internals not covered by Documenso's public API. This gives genuine signing-layer isolation between tenants — one organisation's documents live in its own Documenso Team rather than a shared account. Isolation is therefore enforced at two layers: at the Documenso signing layer (each organisation's documents reside in its own Team) AND inside OraInvoice (org-scoped rows, RLS, ownership checks on every read/download).

Per-organisation Documenso connections follow the existing per-org integration pattern (analogous to the app's per-org accounting/Xero connections): each organisation's connection record holds the Documenso base URL, the Documenso Team id, the team-scoped service token, the webhook secret, a per-org webhook routing identifier, and a verification flag — all envelope-encrypted and org-scoped. Webhooks from Documenso are routed per organisation via an opaque routing identifier in the callback URL, then authenticated by constant-time comparison of the `X-Documenso-Secret` header against that organisation's stored webhook secret, and are idempotent. Completed signed PDFs are pulled back through the encrypted uploads pipeline and attached to the originating entity. Every envelope state transition writes an audit log row and an in-app notification.

## Glossary

- **Esign_Module**: The new OraInvoice module (slug `esignatures`) that manages e-signature envelopes, recipients, status tracking, and signed-document storage. Routes are mounted under `/api/v2/esign`.
- **Documenso**: The self-hosted, open-source e-signature engine integrated via its REST API v2 (`/api/v2/...`; v1 is deprecated). It is the signing engine only; it is never exposed to organisation users.
- **Documenso_Document**: A document object inside Documenso, created from an uploaded PDF, identified by a Documenso-assigned document identifier.
- **Envelope**: An OraInvoice record (row in `esign_envelopes`) that represents one document sent for signature. It carries `org_id`, the originating entity reference, the mapped Documenso document identifier, the current lifecycle status, and metadata. The Envelope is the system-of-record mapping between OraInvoice and Documenso.
- **Recipient**: A party who must view and/or sign a document. A Recipient has a name, an email address, and a signing role. Recipients are external parties who sign via one-time Documenso signing links and do not require an OraInvoice account.
- **Agreement_Type**: The category of document being sent: `sales_agreement`, `purchase_agreement`, `nda`, `employment_agreement`, or `contractor_agreement`.
- **Originating_Entity**: The OraInvoice record a given Envelope is attached to: an invoice, a quote, or a staff member.
- **IntegrationConfig**: The existing OraInvoice envelope-encrypted credential-storage pattern for third-party integrations, configured through the Global Admin integrations UI. The per-organisation Documenso_Org_Connection follows this same envelope-encrypted, org-scoped storage pattern.
- **Documenso_Org_Connection**: The per-organisation record holding that organisation's Documenso base URL, Documenso_Team_Id, team-scoped Documenso_Service_Token, Webhook_Signing_Secret, Webhook_Routing_Id, and verification status (`is_verified`). It is envelope-encrypted and org-scoped, analogous to the app's existing per-org accounting/Xero connections, and replaces any single shared global Documenso configuration row.
- **Documenso_Service_Token**: The team-scoped Documenso API token for a specific organisation's Documenso Team, used by OraInvoice to call Documenso on behalf of that organisation, sent as the raw token value in the `Authorization` header (no `Bearer` prefix), stored envelope-encrypted per organisation in the Documenso_Org_Connection.
- **Webhook_Signing_Secret**: The per-organisation shared secret Documenso sends verbatim in the `X-Documenso-Secret` header for that organisation's Team webhook; OraInvoice constant-time-compares it against the stored value. Stored envelope-encrypted per organisation in the Documenso_Org_Connection.
- **Webhook_Routing_Id**: An opaque per-organisation identifier embedded in that organisation's registered Documenso webhook callback URL (`/api/v2/esign/webhook/{routing_id}`) so that inbound webhooks are attributed to the correct organisation before the per-org Webhook_Signing_Secret is verified. It is not a secret by itself.
- **Esign_Webhook**: An inbound HTTP request from Documenso to OraInvoice notifying of a signing event (for example `DOCUMENT_SENT`, `DOCUMENT_OPENED`, `DOCUMENT_VIEWED`, `DOCUMENT_RECIPIENT_COMPLETED`, `DOCUMENT_COMPLETED`, `DOCUMENT_RECIPIENT_REJECTED`, `DOCUMENT_CANCELLED`). The payload carries `{ event, payload: { id, status, recipients[...] }, createdAt, webhookEndpoint }` and contains no unique event identifier.
- **Envelope_Status**: The lifecycle state of an Envelope: `draft`, `sent`, `viewed`, `partially_signed`, `completed`, `declined`, `voided`, or `error`.
- **Signed_Document**: The completed, fully-signed PDF produced by Documenso, retrieved by OraInvoice and stored via the encrypted uploads pipeline.
- **Encrypted_Uploads_Pipeline**: The existing OraInvoice envelope-encrypted file storage pipeline (`app/modules/uploads`), distinct from the plaintext compliance document store.
- **Documenso_Team_Id**: The identifier of the organisation's Documenso Team on the shared Documenso instance. The organisation's documents are created within this Team for signing-layer isolation. It is actively used on every Documenso API call made on behalf of that organisation.
- **Global_Admin**: A platform-level administrator who provisions and configures each organisation's Documenso connection credentials.
- **Global_Admin_Organisations_Page**: The existing Global Admin Organisations area listing every organisation, from which a Global_Admin triggers per-organisation actions and opens an individual organisation's management views.
- **Provisioning_Adapter**: A configured, isolated component through which the Esign_Module attempts auto-provisioning of an organisation's Documenso Team, team-scoped Documenso_Service_Token, and webhook. It relies on Documenso internals not covered by Documenso's public REST API (Documenso's admin tRPC layer or direct writes to Documenso's self-hosted PostgreSQL) and is therefore best-effort and optional. Failures within the Provisioning_Adapter do not affect the manual configuration path.
- **Org_Sender**: An organisation user holding the `org_admin`, `branch_admin`, or `location_manager` role who is permitted to initiate sends for signature.
- **Audit_Log**: The existing org-scoped audit logging facility, written via `write_audit_log`.
- **In_App_Notification**: The existing in-app notification facility, written via `create_in_app_notification`.
- **Module_Gate**: The existing module-enablement mechanism (`app/middleware/modules.py` and `app/middleware/feature_flags.py`) that enables or disables a module per organisation.

## Requirements

### Requirement 1: Per-Organisation Documenso Connection Configuration

**User Story:** As a Global_Admin, I want to configure each organisation's Documenso connection during that organisation's onboarding, so that the platform can call that organisation's own Documenso Team securely without storing secrets in environment files.

#### Acceptance Criteria

1. THE Esign_Module SHALL expose, within a specific organisation's integration settings, a Documenso connection entry for a Global_Admin to enter that organisation's Documenso base URL, Documenso_Team_Id, Documenso_Service_Token, and Webhook_Signing_Secret.
2. WHEN a Global_Admin saves an organisation's Documenso connection, THE Esign_Module SHALL store that organisation's Documenso_Service_Token and Webhook_Signing_Secret envelope-encrypted in that organisation's Documenso_Org_Connection record.
3. THE Esign_Module SHALL retrieve an organisation's Documenso_Service_Token and Webhook_Signing_Secret from that organisation's Documenso_Org_Connection record at call time AND SHALL NOT read these values from environment variables for Documenso API calls.
9. IF the requesting organisation has no configured and verified Documenso_Org_Connection, THEN THE Esign_Module SHALL fail every Documenso operation for that organisation with a human-readable error indicating the organisation's Documenso integration is not configured.
10. IF a Global_Admin triggers a connection test for an organisation before that organisation's Documenso connection is configured, THEN THE Esign_Module SHALL reject the connection test with a human-readable error indicating the organisation's Documenso connection must be configured first.
4. WHEN an organisation's Documenso connection is returned to the integration settings UI, THE Esign_Module SHALL mask that organisation's Documenso_Service_Token and Webhook_Signing_Secret rather than returning their plaintext values.
5. WHEN a Global_Admin saves a value for an organisation's connection that matches the masked representation, THE Esign_Module SHALL retain the previously stored value for that field rather than overwriting it with the mask.
6. WHEN a Global_Admin triggers a connection test for an organisation, THE Esign_Module SHALL perform an authenticated request to Documenso using that organisation's team-scoped Documenso_Service_Token AND SHALL report whether the organisation's credentials are valid.
7. WHEN a Global_Admin creates or updates an organisation's Documenso connection, THE Esign_Module SHALL write an Audit_Log entry recording the configuration change without including the plaintext credential values.
8. THE Esign_Module SHALL store the Documenso_Team_Id on the organisation's Documenso_Org_Connection AND SHALL use that Documenso_Team_Id to scope that organisation's Documenso API calls to its own Documenso Team.

### Requirement 2: Module Gating and Navigation

**User Story:** As an Org_Sender, I want an "Agreements" area that appears only when the e-signature module is enabled for my organisation, so that signing features are available to businesses that use them.

#### Acceptance Criteria

1. THE Esign_Module SHALL register the slug `esignatures` in the module registry consumed by `app/middleware/modules.py` and `app/middleware/feature_flags.py`.
2. WHILE the `esignatures` module is disabled for an organisation, THE Esign_Module SHALL return HTTP 403 for requests to endpoints under `/api/v2/esign`.
3. WHILE the `esignatures` module is enabled for an organisation, THE Esign_Module SHALL display an "Agreements" entry in the organisation sidebar.
4. WHILE the `esignatures` module is disabled for an organisation, THE Esign_Module SHALL hide the "Agreements" sidebar entry.
5. THE Esign_Module SHALL make the `esignatures` module available to every trade family without trade-family gating.

### Requirement 3: Create and Send an Envelope

**User Story:** As an Org_Sender, I want to upload or select a document, add recipients, and send it for signature, so that the other party can sign it digitally.

#### Acceptance Criteria

1. WHEN an Org_Sender initiates a send with a source PDF, an Agreement_Type, and at least one Recipient, THE Esign_Module SHALL create a Documenso_Document from the PDF, register the Recipients in Documenso, and request Documenso to send the document for signature.
2. WHEN a Documenso_Document is created for a send, THE Esign_Module SHALL create an Envelope row carrying the `org_id`, the Agreement_Type, the Originating_Entity reference, the mapped Documenso document identifier, and an initial Envelope_Status of `sent`.
3. IF an Org_Sender attempts to create a send with no Recipient, THEN THE Esign_Module SHALL reject the request with a validation error AND SHALL NOT create a Documenso_Document.
4. IF an Org_Sender attempts to create a send with a source file that is not a PDF, THEN THE Esign_Module SHALL reject the request with a validation error AND SHALL NOT create a Documenso_Document.
5. IF the Documenso API returns an error during document creation or send, THEN THE Esign_Module SHALL record the Envelope with Envelope_Status `error` AND SHALL return a human-readable error message to the Org_Sender.
6. THE Esign_Module SHALL support each Agreement_Type value: `sales_agreement`, `purchase_agreement`, `nda`, `employment_agreement`, and `contractor_agreement`.
7. WHEN an Envelope is successfully created and sent, THE Esign_Module SHALL write an Audit_Log entry and create an In_App_Notification recording the send.
8. IF a send attempt fails due to a validation error or a Documenso API failure, THEN THE Esign_Module SHALL write an Audit_Log entry and create an In_App_Notification recording the failed send attempt.

### Requirement 4: Recipient Management

**User Story:** As an Org_Sender, I want to specify each recipient's name, email, and role on an envelope, so that the right people are asked to sign.

#### Acceptance Criteria

1. THE Esign_Module SHALL accept one or more Recipients per Envelope, each with a name, an email address, and a signing role.
2. WHEN a Recipient email address is provided, THE Esign_Module SHALL validate that the email address is syntactically valid before sending to Documenso.
3. IF a Recipient email address is syntactically invalid, THEN THE Esign_Module SHALL reject the send with a validation error identifying the invalid Recipient AND SHALL NOT create a Documenso_Document.
4. THE Esign_Module SHALL persist each Recipient associated with its Envelope, including the Recipient's per-recipient signing status.
5. WHEN Documenso reports a status change for an individual Recipient, THE Esign_Module SHALL update that Recipient's persisted per-recipient signing status.
6. IF a send includes multiple Recipients and any one Recipient email address is syntactically invalid, THEN THE Esign_Module SHALL reject the entire send AND SHALL NOT create a Documenso_Document or register any Recipient in Documenso.

### Requirement 5: External Signing Without an Account

**User Story:** As an external signer, I want to sign a document from a one-time link without creating an account, so that signing is frictionless.

#### Acceptance Criteria

1. THE Esign_Module SHALL rely on Documenso-issued one-time signing links for external Recipients AND SHALL NOT require external Recipients to hold an OraInvoice account.
2. WHERE a Recipient is a staff member signing their own NDA or agreement, THE Esign_Module SHALL allow the staff member to access the signing link via the Employee Portal or via a plain email link.
3. THE Esign_Module SHALL NOT expose the Documenso administrative or organisation UI to any OraInvoice organisation user.
4. IF a staff member cannot reach a signing link because neither the Employee Portal nor email delivery is available, THEN THE Esign_Module SHALL keep the Envelope in its current non-terminal status so that access can be retried once at least one delivery method is available.

### Requirement 6: Envelope Status Lifecycle

**User Story:** As an Org_Sender, I want to see the current signing status of each envelope, so that I know whether a document is still awaiting signature or completed.

#### Acceptance Criteria

1. THE Esign_Module SHALL represent each Envelope with exactly one Envelope_Status from: `draft`, `sent`, `viewed`, `partially_signed`, `completed`, `declined`, `voided`, and `error`.
2. WHEN an Esign_Webhook reports `DOCUMENT_OPENED` or `DOCUMENT_VIEWED`, THE Esign_Module SHALL set the Envelope_Status to `viewed` unless the Envelope is already in a terminal status.
3. WHEN an Esign_Webhook reports `DOCUMENT_RECIPIENT_COMPLETED` while at least one other Recipient remains unsigned, THE Esign_Module SHALL set the Envelope_Status to `partially_signed`.
4. WHEN an Esign_Webhook reports `DOCUMENT_COMPLETED`, THE Esign_Module SHALL set the Envelope_Status to `completed`, including the case where all Recipients sign without any intervening `partially_signed` transition.
5. WHEN an Esign_Webhook reports `DOCUMENT_RECIPIENT_REJECTED`, THE Esign_Module SHALL set the Envelope_Status to `declined`.
6. WHEN an Esign_Webhook reports `DOCUMENT_CANCELLED` for an Envelope that is not already in a terminal status, THE Esign_Module SHALL set the Envelope_Status to `voided`.
7. THE Esign_Module SHALL treat `completed`, `declined`, and `voided` as terminal statuses AND SHALL NOT transition an Envelope out of a terminal status in response to a subsequent non-void event.
8. WHEN an Envelope_Status changes, THE Esign_Module SHALL write an Audit_Log entry and create an In_App_Notification recording the transition.

### Requirement 7: Void an Envelope

**User Story:** As an Org_Sender, I want to void an envelope that is still awaiting signature, so that I can cancel a send that is no longer needed.

#### Acceptance Criteria

1. WHILE an Envelope is in a non-terminal status, THE Esign_Module SHALL allow an Org_Sender to void the Envelope.
2. WHEN an Org_Sender voids an Envelope, THE Esign_Module SHALL request Documenso to void the corresponding Documenso_Document AND SHALL set the Envelope_Status to `voided`.
3. IF an Org_Sender attempts to void an Envelope that is already in a terminal status, THEN THE Esign_Module SHALL reject the request with a human-readable error indicating the Envelope can no longer be voided.
4. WHEN an Envelope is voided, THE Esign_Module SHALL write an Audit_Log entry and create an In_App_Notification recording the void.

### Requirement 8: Webhook Verification and Idempotency

**User Story:** As the platform, I want inbound Documenso webhooks to be authenticated and processed exactly once, so that signing status updates are trustworthy and not duplicated.

#### Acceptance Criteria

1. WHEN an Esign_Webhook is received at `/api/v2/esign/webhook/{routing_id}`, THE Esign_Module SHALL resolve the organisation from the Webhook_Routing_Id in the URL, load that organisation's Webhook_Signing_Secret, and verify the `X-Documenso-Secret` header value against it using a constant-time comparison before processing.
2. IF the Webhook_Routing_Id maps to no organisation, OR the `X-Documenso-Secret` header value does not match the resolved organisation's Webhook_Signing_Secret, THEN THE Esign_Module SHALL reject the request with HTTP 401 AND SHALL NOT modify any Envelope.
3. WHEN an Esign_Webhook is successfully verified, THE Esign_Module SHALL compute a synthesized dedupe key from stable payload fields (a hash of the event type, the Documenso document identifier, the recipient/status, and the `createdAt` timestamp) AND SHALL record that synthesized dedupe key uniquely.
4. WHEN an Esign_Webhook arrives whose synthesized dedupe key has already been processed, THE Esign_Module SHALL acknowledge the webhook without re-applying the associated state change.
5. WHEN an Esign_Webhook references a Documenso document identifier that maps to no Envelope within the resolved organisation, THE Esign_Module SHALL acknowledge the webhook without modifying any Envelope.

### Requirement 9: Store the Completed Signed Document

**User Story:** As an Org_Sender, I want the completed signed PDF stored securely in OraInvoice and attached to the originating entity, so that I have the signed agreement on file.

#### Acceptance Criteria

1. WHEN an Envelope reaches Envelope_Status `completed`, THE Esign_Module SHALL retrieve the Signed_Document from Documenso.
2. WHEN a Signed_Document is retrieved, THE Esign_Module SHALL store it through the Encrypted_Uploads_Pipeline AND SHALL NOT store it in the plaintext compliance document store.
3. WHEN a Signed_Document is stored for an Envelope whose Originating_Entity is a staff member, THE Esign_Module SHALL make that Signed_Document visible and downloadable from that staff member's Staff → Documents tab, served from the Encrypted_Uploads_Pipeline rather than the plaintext compliance document store.
4. WHEN a Signed_Document is stored for an Envelope whose Originating_Entity is an invoice or a quote, THE Esign_Module SHALL attach the Signed_Document to that invoice or quote.
5. IF retrieval of the Signed_Document from Documenso fails after an Envelope reaches `completed`, THEN THE Esign_Module SHALL retain the Envelope in `completed` status, record the retrieval failure, AND retry retrieval on a subsequent webhook or scheduled attempt.
6. WHEN a Signed_Document has been stored and attached, THE Esign_Module SHALL write an Audit_Log entry recording that the signed document was stored.
7. IF storing a Signed_Document through the Encrypted_Uploads_Pipeline fails, THEN THE Esign_Module SHALL reject the storage attempt, SHALL NOT store the Signed_Document in any alternative or temporary location, AND SHALL retry storage on a subsequent webhook or scheduled attempt.

### Requirement 10: Contextual Send Actions

**User Story:** As an Org_Sender, I want "Send for signature" actions directly on invoice/quote pages and the Staff → Documents tab, so that I can send agreements without leaving the relevant record.

#### Acceptance Criteria

1. WHILE the `esignatures` module is enabled, THE Esign_Module SHALL display a "Send for signature" action on invoice and quote pages.
2. WHILE the `esignatures` module is enabled, THE Esign_Module SHALL display a "Send for signature" action on the Staff → Documents tab.
3. WHEN an Org_Sender initiates a send from an invoice or quote page, THE Esign_Module SHALL pre-associate the resulting Envelope with that invoice or quote as the Originating_Entity.
4. WHEN an Org_Sender initiates a send from the Staff → Documents tab, THE Esign_Module SHALL pre-associate the resulting Envelope with that staff member as the Originating_Entity.
5. WHILE the `esignatures` module is disabled, THE Esign_Module SHALL hide the "Send for signature" actions on invoice pages, quote pages, and the Staff → Documents tab.

### Requirement 11: Agreements Dashboard

**User Story:** As an Org_Sender, I want a dashboard listing all of my organisation's envelopes with their statuses, so that I can track signing progress in one place.

#### Acceptance Criteria

1. WHEN an Org_Sender opens the Agreements dashboard, THE Esign_Module SHALL list the Envelopes belonging to that user's organisation.
2. THE Esign_Module SHALL display, for each listed Envelope, the Agreement_Type, the Recipients, the current Envelope_Status, and the Originating_Entity reference.
3. WHEN an Org_Sender filters the dashboard by Envelope_Status, THE Esign_Module SHALL return only Envelopes matching the selected status within that user's organisation.
4. THE Esign_Module SHALL order the Agreements dashboard list by most recently updated Envelope first.
5. WHEN an Org_Sender opens an Envelope from the dashboard, THE Esign_Module SHALL display the Envelope's per-recipient signing status and, where present, a link to the stored Signed_Document.
6. IF the Esign_Module cannot apply a requested Envelope_Status filter, THEN THE Esign_Module SHALL return no Envelopes rather than an unfiltered list AND SHALL include a human-readable error indicating the filter could not be applied.

### Requirement 12: Role-Based Access Control for Sending

**User Story:** As an organisation, I want only authorised users to initiate sends, so that signature requests are controlled.

#### Acceptance Criteria

1. WHEN a user with the `org_admin`, `branch_admin`, or `location_manager` role initiates a send, THE Esign_Module SHALL permit the send.
2. IF a user without the `org_admin`, `branch_admin`, or `location_manager` role attempts to initiate a send, THEN THE Esign_Module SHALL reject the request with HTTP 403.
3. IF a user without the `org_admin`, `branch_admin`, or `location_manager` role attempts to void an Envelope, THEN THE Esign_Module SHALL reject the request with HTTP 403.

### Requirement 13: Multi-Tenant Isolation

**User Story:** As an organisation, I want my envelopes and signed documents to be invisible and inaccessible to other organisations, so that my agreements remain confidential both at the Documenso signing layer and within OraInvoice.

#### Acceptance Criteria

1. THE Esign_Module SHALL persist an `org_id` on every Envelope row.
2. THE Esign_Module SHALL enforce row-level security on the `esign_envelopes` table scoped by `org_id`.
3. WHEN an Org_Sender requests a list of Envelopes, THE Esign_Module SHALL return only Envelopes whose `org_id` matches the requesting user's organisation, returning an empty list when the organisation has no matching Envelopes.
4. WHEN a user requests to read an Envelope or download a Signed_Document, THE Esign_Module SHALL verify that the Envelope's `org_id` matches the requesting user's organisation before returning data.
5. IF a user requests an Envelope or Signed_Document belonging to another organisation, THEN THE Esign_Module SHALL reject the request with HTTP 404 AND SHALL NOT return the requested data or otherwise confirm that the Envelope exists.
6. WHEN an Esign_Webhook results in retrieving or storing data for an Envelope, THE Esign_Module SHALL associate the retrieved data with the `org_id` recorded on that Envelope.
7. WHEN the Esign_Module makes a Documenso API call on behalf of an organisation, THE Esign_Module SHALL use that organisation's team-scoped Documenso_Service_Token scoped to that organisation's Documenso_Team_Id, so that the document is created within the organisation's own Documenso Team, AND SHALL NOT use another organisation's Documenso_Service_Token.

### Requirement 14: Audit Logging and Notifications

**User Story:** As an organisation, I want every envelope state change recorded in the audit log and surfaced as an in-app notification, so that I have traceability and timely awareness of signing activity.

#### Acceptance Criteria

1. WHEN an Envelope transitions between any of `sent`, `viewed`, `partially_signed`, `completed`, `declined`, and `voided`, THE Esign_Module SHALL write an org-scoped Audit_Log entry via `write_audit_log` recording the transition.
2. WHEN an Envelope transitions between any of `sent`, `viewed`, `partially_signed`, `completed`, `declined`, and `voided`, THE Esign_Module SHALL create an In_App_Notification via `create_in_app_notification` recording the transition.
3. IF writing the Audit_Log entry or creating the In_App_Notification fails, THEN THE Esign_Module SHALL log the failure AND SHALL NOT roll back the underlying Envelope_Status change (audit and notification side-effects are best-effort relative to the status change).
4. THE Esign_Module SHALL exclude plaintext credential values and signed-document contents from Audit_Log entries and In_App_Notifications.

### Requirement 15: Privacy and Data Protection

**User Story:** As an organisation handling sensitive agreements, I want credentials and signed documents protected, so that personal data and confidential agreements are not exposed.

#### Acceptance Criteria

1. THE Esign_Module SHALL store the Documenso_Service_Token and Webhook_Signing_Secret only in envelope-encrypted form.
2. THE Esign_Module SHALL store every Signed_Document only through the Encrypted_Uploads_Pipeline.
3. WHEN any Esign_Module API response is returned, THE Esign_Module SHALL exclude plaintext Documenso credentials from the response.
4. THE Esign_Module SHALL transmit Documenso API requests and Signed_Document downloads over HTTPS.
5. WHEN an error response is returned from any Esign_Module endpoint, THE Esign_Module SHALL exclude raw database text and raw exception text from the response.

### Requirement 16: Human-Readable Error Messages

**User Story:** As an Org_Sender, I want clear error messages when a send or signing action fails, so that I understand what went wrong and what to do next.

#### Acceptance Criteria

1. WHEN any Esign_Module endpoint returns an error response, THE Esign_Module SHALL include a human-readable message describing the problem and, where helpful, the corrective action.
2. WHERE an error response includes a machine-readable code, THE Esign_Module SHALL include that code as a secondary field AND SHALL always include a human-readable message alongside it.
3. WHEN an error arises from a Documenso API failure, a validation failure, a credential/configuration problem, an access-control rejection, or an unexpected server error, THE Esign_Module SHALL include a human-readable message in the error response.

### Requirement 17: Signature Field Placement

**User Story:** As an Org_Sender, I want every signer to have at least one signature field on the document before it is sent, so that recipients have something to sign and the completed PDF carries valid signatures.

#### Acceptance Criteria

1. WHEN an Org_Sender sends a document for signature, THE Esign_Module SHALL ensure at least one signature field is placed for each signer Recipient before requesting Documenso to send, either by placing a SIGNATURE field per signer via the Documenso Fields API or by sending from a Documenso template that already carries signer fields.
2. IF a send would result in a signer Recipient with no signature field, THEN THE Esign_Module SHALL NOT request the send AND SHALL return a human-readable validation error identifying the signer without a signature field.

### Requirement 18: Per-Organisation Webhook Subscription Registration

**User Story:** As a Global_Admin, I want each organisation's Documenso Team webhook subscription that points at OraInvoice to be registered and verifiable per organisation and per environment, so that signing events for that organisation actually reach OraInvoice.

#### Acceptance Criteria

1. THE Esign_Module SHALL provide a documented Global_Admin provisioning step to register, in the Documenso UI, that organisation's Documenso Team webhook subscription targeting `/api/v2/esign/webhook/{org_routing_id}` with that organisation's Webhook_Signing_Secret for the active environment.
2. THE Esign_Module SHALL surface, for a given organisation, whether that organisation's Documenso connection and webhook subscription are configured and verified.
3. WHERE separate Documenso instances or URLs exist per environment, THE Esign_Module SHALL register and verify each organisation's webhook subscription independently for each organisation and each environment.

### Requirement 19: Per-Organisation Provisioning and Connection Lifecycle

**User Story:** As a Global_Admin, I want to provision and verify each organisation's Documenso connection at onboarding, so that an organisation can only send for signature once its own Documenso Team is wired up correctly.

#### Acceptance Criteria

1. WHEN a Global_Admin onboards an organisation, THE Esign_Module SHALL allow the Global_Admin to record that organisation's Documenso_Org_Connection comprising the Documenso base URL, Documenso_Team_Id, team-scoped Documenso_Service_Token, Webhook_Signing_Secret, and Webhook_Routing_Id.
2. WHEN a Global_Admin runs a connection test for an organisation, THE Esign_Module SHALL perform an authenticated request against that organisation's Documenso Team using the team-scoped Documenso_Service_Token AND SHALL set the organisation's `is_verified` flag according to whether the request succeeds.
3. WHILE an organisation's Documenso_Org_Connection is not verified, THE Esign_Module SHALL treat that organisation's `esignatures` features as unusable.
4. IF an Org_Sender attempts to send for signature WHILE the organisation's Documenso_Org_Connection is missing or unverified, THEN THE Esign_Module SHALL block the send with a human-readable error directing the user to have the Documenso integration set up.
5. WHEN a Global_Admin updates an organisation's Documenso_Org_Connection, THE Esign_Module SHALL clear the organisation's `is_verified` flag until a subsequent connection test succeeds.
6. THE Esign_Module SHALL provide, on the Global_Admin_Organisations_Page, a per-organisation action labelled "Provision e-signature" that triggers auto-provisioning for that organisation.
7. WHEN a Global_Admin opens an organisation from the Global_Admin_Organisations_Page, THE Esign_Module SHALL provide access to that organisation's Documenso connection management view in which the Global_Admin can enter or edit that organisation's Documenso base URL, Documenso_Team_Id, Documenso_Service_Token, and Webhook_Signing_Secret, view that organisation's webhook URL and verification status, and run the connection test.
8. WHEN that organisation's Documenso connection management view returns the Documenso_Service_Token and Webhook_Signing_Secret, THE Esign_Module SHALL mask those values rather than returning their plaintext values.

### Requirement 20: Optional Auto-Provisioning of a Documenso Team and Token (Global Admin)

**User Story:** As a Global_Admin, I want a one-click "Provision e-signature" action on an organisation, so that its Documenso Team, team-scoped token, and webhook are created automatically, with a manual fallback if that fails.

#### Acceptance Criteria

1. WHEN a Global_Admin triggers auto-provisioning for an organisation, THE Esign_Module SHALL attempt, via the configured Provisioning_Adapter, to create that organisation's Documenso Team, mint a team-scoped Documenso_Service_Token, obtain and record that organisation's Webhook_Signing_Secret, and generate that organisation's Webhook_Routing_Id, then store these values in that organisation's Documenso_Org_Connection.
2. WHEN auto-provisioning succeeds for an organisation, THE Esign_Module SHALL run the connection test, set that organisation's `is_verified` flag according to the connection test result, AND surface that organisation's webhook URL for the Global_Admin to confirm and register.
3. IF auto-provisioning fails at any step, THEN THE Esign_Module SHALL return a human-readable error AND SHALL leave that organisation's Documenso_Org_Connection in a state the Global_Admin can complete manually, with no partially-applied broken state and with any successfully-created Documenso artefacts recorded so that they can be reused or completed by manual entry.
4. THE Esign_Module SHALL treat auto-provisioning as an optional, best-effort capability that relies on Documenso internals not covered by Documenso's public REST API, AND SHALL keep the manual per-organisation connection configuration described in Requirement 1 and Requirement 19 available as the supported fallback at all times.
5. WHERE auto-provisioning is disabled or unavailable in an environment, THE Esign_Module SHALL allow manual configuration of an organisation's Documenso_Org_Connection AND SHALL indicate to the Global_Admin that auto-provisioning is unavailable.

## Non-Functional Constraints and Assumptions

These items constrain the design and are recorded as accepted context rather than testable behavioural requirements:

- **Documenso licensing (AGPLv3)**: OraInvoice integrates with Documenso solely through its REST API. The Documenso source is not forked or modified.
- **Signing certificate**: Documenso requires a signing certificate (`.p12`). Development uses a self-signed certificate; production requires a real certificate. Certificate provisioning is an operational task outside the application's runtime behaviour.
- **Public signer URL**: External signers reach Documenso-hosted signing links, which requires Documenso to be reachable at a public hostname (via the existing Cloudflare tunnel). Public reachability is a deployment/operational concern.
- **Per-org tenancy model**: Each organisation has its own Documenso Team on the shared self-hosted Documenso instance, with its own team-scoped Documenso_Service_Token and its own Webhook_Signing_Secret. Tenant isolation is enforced at the Documenso signing layer (per-org Team) as well as within OraInvoice (org_id/RLS/ownership). Each organisation's connection is stored in its own envelope-encrypted, org-scoped Documenso_Org_Connection record.
- **Manual provisioning (Global Admin)**: Documenso's REST API (verified against the running instance: v1/v2 expose documents, recipients, fields, templates, and `teamId` scoping) does NOT expose account, team, or token creation endpoints. Provisioning each organisation's Documenso Team, team-scoped token, and webhook secret can therefore be performed as a one-time manual Global_Admin step in the Documenso UI at org onboarding, with the resulting connection details recorded in OraInvoice. Manual provisioning is the guaranteed, supported path and remains available as the fallback at all times.
- **Optional auto-provisioning (best-effort, isolated)**: The optional auto-provisioning capability (Requirement 20) does not use Documenso's public REST API — no team, token, or webhook-subscription creation endpoints exist there. It instead depends on Documenso's unsupported internals (Documenso's admin tRPC layer or direct writes to Documenso's self-hosted PostgreSQL) and may break on Documenso upgrades. It is isolated behind the Provisioning_Adapter so that any failure is contained and does not affect the manual provisioning path, which remains the supported fallback.
- **Residual shared-instance trust**: Per-org Documenso Teams provide signing-layer isolation between organisations, so one organisation's documents are not visible inside another organisation's Team. The residual trust is that the platform operator (Global_Admin) runs the shared Documenso instance and could access any Team via Documenso server or database access — a standard property of any self-hosted shared instance, not a defect of this design.
- **Raspberry Pi resource limits**: Production runs on an ARM Raspberry Pi with limited resources. The Documenso instance and OraInvoice must coexist within these constraints; capacity planning is an operational concern.
- **Local development instance**: A Documenso dev instance is already running (web at `http://localhost:3030`, MailDev at `http://localhost:1080`, compose under `/mnt/hindi-tv/Invoicing/documenso/`) for integration testing.
