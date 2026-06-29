# Requirements Document

## Introduction

The E-Signature Field Placement feature adds an in-app, drag-and-drop **field-placement editor** to the existing, already-shipped E-Signature Integration (`esignature-integration`). Today, when an Org_Sender uploads a PDF, picks an agreement type, and adds recipients, the system auto-places exactly one SIGNATURE field per signer on the PDF's last page at fixed default coordinates (the `_DEFAULT_FIELD_PAGE_*` constants / `place_signature_field` path in `app/modules/esignatures/service.py`). There is no way for the sender to choose where fields go or to add field types other than a signature.

This feature replaces that single auto-placement with a sender-defined field set. After choosing the PDF and recipients in the existing `SendForSignatureModal`, the Org_Sender sees every page of the uploaded PDF rendered in the browser and can drag field boxes onto the pages, move and resize them, assign each field to a specific recipient (color-coded), choose the field type (Signature, Initials, Name, Date, Email, Text), and mark each field required or optional (with a label/placeholder for Text fields). On send, the placed fields are created on the Documenso document via the v2 `field/create-many` endpoint instead of the single auto-placed signature.

The feature preserves the safety rule carried over from the existing spec (Requirement 17 of `esignature-integration`): every signer must have at least one signature-type field before the document is distributed. If the editor yields no signature field for a signer, the send is blocked with a clear, human-readable message.

This feature **extends** the existing module and MUST align with its established constraints rather than redesign them: the per-organisation Documenso connection model and team-scoped token usage (R13.7 of the existing spec), the `esignatures` module gate (HTTP 403 when disabled), the send RBAC (`org_admin` / `branch_admin` / `location_manager` via `require_esign_sender`), the safe-api-consumption rules (typed generics, `?.` / `?? []`, AbortController), and the rule that the Documenso UI is never exposed to OraInvoice organisation users (R5.3 of the existing spec).

In addition to the core in-app placement editor (Requirements 1–12 below), this feature also delivers five expanded capabilities that were previously deferred: **post-send field editing** (Requirement 13), **conditional / dependent fields** (Requirement 14), a **signing-order UI** (Requirement 15), the **mobile field-placement editor** in the OraInvoice mobile app (Requirement 16), and **saved field templates per agreement type** (Requirement 17). Several of these capabilities are constrained by what the Documenso signing engine can actually enforce; where a hard engine limitation exists (true post-signature mutation, server-side conditional enforcement) the requirements state the limitation and the degraded or alternative behaviour explicitly rather than promising enforcement the engine cannot deliver.

The primary frontend surface is `frontend-v2/` (React 18 + TypeScript + Vite + Tailwind). The mobile field-placement editor and send flow are delivered in the OraInvoice **mobile app** (`mobile/`, React 19 + Capacitor) for organisation users only, governed by the mobile steering guide (org-users only, v2 endpoints, safe API consumption, 44 px touch targets, `esignatures` ModuleGate, offline/abort patterns).

## Glossary

- **Esign_Module**: The existing OraInvoice module (slug `esignatures`) that manages e-signature envelopes, recipients, status tracking, and signed-document storage, with routes mounted under `/api/v2/esign`. This feature extends the send flow of that module.
- **Field_Placement_Editor**: The new in-app, drag-and-drop surface in (or launched from) the existing send flow where an Org_Sender renders the uploaded PDF and places, moves, resizes, assigns, types, and deletes fields before sending.
- **Send_Flow**: The existing "Send for signature" composer (`frontend-v2/src/components/esign/SendForSignatureModal.tsx`) where an Org_Sender selects a PDF, an Agreement_Type, and Recipients. The Field_Placement_Editor is a new step or surface within this flow.
- **Org_Sender**: An organisation user holding the `org_admin`, `branch_admin`, or `location_manager` role who is permitted to initiate sends for signature (the existing `require_esign_sender` RBAC).
- **Recipient**: A party on an Envelope with a name, an email address, and a signing role. Carried over unchanged from the existing spec.
- **Signing_Role**: A Recipient's role on the document. OraInvoice accepts `signer` and `viewer`; Documenso roles are `SIGNER`, `VIEWER`, `APPROVER`, `CC`, and `ASSISTANT`. Only `SIGNER` and `APPROVER` actually sign.
- **Signing_Recipient**: A Recipient whose Documenso role is `SIGNER` or `APPROVER` — that is, a Recipient who must sign and therefore requires at least one Signature_Field.
- **Field**: A placed input region on a page of the document, carrying a Field_Type, a target Recipient, a page number, a normalized position and size, a required/optional flag, and (for Text fields) optional label and placeholder metadata.
- **Field_Type**: The kind of a Field. The supported set is `signature`, `initials`, `name`, `date`, `email`, and `text`, mapped to the Documenso field types `SIGNATURE`, `INITIALS`, `NAME`, `DATE`, `EMAIL`, and `TEXT`.
- **Signature_Field**: A Field whose Field_Type is `signature` (a signature-type field). Carrying ≥1 Signature_Field per Signing_Recipient is the send-blocking safety rule.
- **Field_Set**: The complete collection of Fields the Org_Sender has placed across all pages of one document, to be created on the Documenso_Document on send.
- **Normalized_Coordinates**: A Field's position and size expressed in Documenso's normalized page units with the origin at the top-left of the page, independent of the on-screen render scale, as accepted by the Documenso `field/create-many` endpoint (`pageX`, `pageY`, `width`, `height`, plus `pageNumber`); OraInvoice's internal coordinate names `positionX`/`positionY`/`page` map to those wire keys.
- **Overlay_Coordinates**: A Field's position and size as rendered on screen, expressed in CSS pixels relative to the rendered PDF page element.
- **Coordinate_Mapping**: The transformation between Overlay_Coordinates (CSS pixels relative to a rendered page) and Normalized_Coordinates (Documenso normalized page units, origin top-left), in both directions.
- **PDF_Renderer**: The in-browser component that renders every page of the uploaded PDF for placement (PDF.js or an equivalent in-browser PDF rendering library).
- **Field_Palette**: The UI control set listing the available Field_Types from which the Org_Sender adds Fields to the document.
- **Documenso**: The self-hosted e-signature engine, integrated via its REST API v2. It is the signing engine only and is never exposed to organisation users.
- **Documenso_Document**: A document object inside Documenso created from the uploaded PDF, identified by a Documenso-assigned document identifier.
- **Field_Create_Endpoint**: The Documenso v2 endpoint `POST /api/v2/document/field/create-many`, which accepts `{ documentId, fields[] }` where each field carries `recipientId`, `type`, `pageNumber`, `pageX`, `pageY`, `width`, `height`, and optional `fieldMeta` (label / placeholder / text / required).
- **Distribute_Step**: The Documenso v2 `POST /api/v2/document/distribute` call that sends the document to recipients for signing. The Field_Set MUST be created before this step.
- **Envelope**: The existing OraInvoice record (row in `esign_envelopes`) representing one document sent for signature. Unchanged by this feature except that its send now carries a sender-defined Field_Set.
- **Module_Gate**: The existing module-enablement mechanism that returns HTTP 403 for requests under `/api/v2/esign` while the `esignatures` module is disabled for an organisation.
- **Documenso_Org_Connection**: The existing per-organisation, envelope-encrypted connection record holding the organisation's Documenso base URL, Documenso Team id, team-scoped service token, and webhook secret. Every Documenso call for an organisation uses that organisation's own team-scoped token.
- **Envelope_Status**: The lifecycle state of an Envelope, carried over from `esignature-integration`: one of `draft`, `sent`, `viewed`, `partially_signed`, `completed`, `declined`, `voided`, or `error`. `completed`, `declined`, and `voided` are terminal.
- **Editable_State**: The set of Envelope conditions in which a previously-sent Envelope's Field_Set may still be edited in place on Documenso: the Envelope is in Envelope_Status `sent` AND no Recipient has yet signed (no `DOCUMENT_RECIPIENT_COMPLETED` has been recorded for it). Any other condition is a Non_Editable_State.
- **Non_Editable_State**: Any Envelope condition outside the Editable_State — including Envelope_Status `viewed` where signing has begun, `partially_signed`, `completed`, `declined`, `voided`, or `error`, or any Envelope where at least one Recipient has signed. Field editing is not permitted in a Non_Editable_State; the only path to change fields is Void_And_Recreate.
- **Void_And_Recreate**: The supported alternative to editing a Non_Editable_State Envelope: void the existing Envelope (the existing void path, R7 of `esignature-integration`) and create a new Envelope with a fresh Field_Set. This is the only way to change fields once signing has begun, because the Documenso signing engine cannot mutate fields on a document that recipients have already begun signing.
- **Conditional_Field**: A Field whose visibility or required state is governed by a Field_Dependency on the value of another Field, rather than being unconditionally shown and required.
- **Field_Dependency**: A rule attached to a dependent Field consisting of a Trigger_Field, a Dependency_Condition, and the resulting effect (`show` or `require`) on the dependent Field. Example: "require Text field B when Checkbox field A is checked".
- **Trigger_Field**: The Field whose value a Field_Dependency observes. It must be a Field already placed in the same Field_Set, assigned to the same document.
- **Dependency_Condition**: The testable condition on the Trigger_Field's value that activates a Field_Dependency — for the supported set: `is_checked` / `is_not_checked` for checkbox-style triggers, and `equals <value>` / `not_equals <value>` / `is_filled` / `is_empty` for value-bearing triggers.
- **Dependency_Enforcement_Mode**: How a Field_Dependency is honoured at signing time. `enforced` means the Documenso signing engine applies the dependency server-side (via `fieldMeta`) so the dependent Field is shown/required only when the condition holds; `advisory` means the signing engine cannot apply the dependency, so all Fields are shown and the dependency is recorded for the sender's reference only.
- **Signing_Order**: The order in which Signing_Recipients are asked to sign a document. Expressed per Recipient as a 1-based position when the Signing_Order_Mode is sequential.
- **Signing_Order_Mode**: Whether Recipients sign in parallel or in sequence: `parallel` (all Signing_Recipients may sign at once — the current default behaviour) or `sequential` (each Signing_Recipient is invited to sign only after the previous one in the Signing_Order has signed). Mapped to Documenso's distribution mode (`PARALLEL` / `SEQUENTIAL`) and per-recipient `signingOrder`.
- **Mobile_App**: The OraInvoice mobile companion app (`mobile/`, React 19 + TypeScript + Vite + Capacitor 7), for organisation users only, governed by the mobile steering guide.
- **Mobile_Field_Placement_Editor**: The mobile-app surface that renders the uploaded PDF and lets an Org_Sender place, assign, type, and configure Fields on a small touch viewport. It uses the same backend send contract as the `frontend-v2/` Field_Placement_Editor.
- **Touch_Place**: The mobile placement interaction in which an Org_Sender selects a Field_Type and taps a position on the rendered page to place a Field there, then adjusts it with on-screen nudge and resize controls, instead of relying on fine-grained pointer dragging.
- **Field_Template**: A reusable, named, organisation-scoped collection of placed Fields — their Field_Type, page, Normalized_Coordinates, required flag, and (for `text`) label/placeholder — together with a Template_Recipient_Role per Field, optionally associated with one Agreement_Type. A Field_Template stores roles, not specific people.
- **Template_Recipient_Role**: An abstract recipient slot stored on a Field_Template (for example "signer 1", "signer 2", "viewer") to which template Fields are assigned, so that applying the template maps each role to one of the current send's actual Recipients without storing any specific person.
- **Apply_Template**: The action of populating the current send's Field_Set from a Field_Template by copying each template Field and mapping its Template_Recipient_Role to a Recipient of the current send.

## Requirements

### Requirement 1: Render the Uploaded PDF for Field Placement

**User Story:** As an Org_Sender, I want to see every page of the uploaded PDF rendered in the browser, so that I can place fields on the exact pages and positions where signers should act.

#### Acceptance Criteria

1. WHEN an Org_Sender has selected a PDF and at least one Recipient in the Send_Flow, THE Field_Placement_Editor SHALL render each page of the selected PDF using the PDF_Renderer.
2. THE Field_Placement_Editor SHALL render all pages of a multi-page PDF AND SHALL allow the Org_Sender to navigate to and place Fields on any rendered page.
3. WHILE a PDF page is rendering, THE Field_Placement_Editor SHALL display a loading indicator for that page until the page render completes.
4. IF the selected PDF cannot be rendered by the PDF_Renderer, THEN THE Field_Placement_Editor SHALL display a human-readable error indicating the document could not be rendered AND SHALL block progression to send.
5. WHERE a PDF page contains only scanned image content with no extractable text, THE Field_Placement_Editor SHALL render that page as an image and SHALL allow Fields to be placed on it.
6. THE Field_Placement_Editor SHALL render PDF pages entirely in the browser AND SHALL NOT transmit the PDF to Documenso before the Org_Sender confirms the send.

### Requirement 2: Field Palette and Supported Field Types

**User Story:** As an Org_Sender, I want a palette of field types to choose from, so that I can collect signatures and the other inputs each recipient needs to provide.

#### Acceptance Criteria

1. THE Field_Palette SHALL offer each supported Field_Type: `signature`, `initials`, `name`, `date`, `email`, and `text`.
2. WHEN an Org_Sender adds a Field of a chosen Field_Type, THE Field_Placement_Editor SHALL create a Field carrying that Field_Type on the targeted page.
3. WHEN a Field is created without an explicit required/optional choice, THE Field_Placement_Editor SHALL default a `signature`, `initials`, `name`, `email`, or `date` Field to required AND SHALL default a `text` Field to optional.
4. WHEN the Field_Set is created on the Documenso_Document, THE Esign_Module SHALL map each Field_Type to its corresponding Documenso field type: `signature` to `SIGNATURE`, `initials` to `INITIALS`, `name` to `NAME`, `date` to `DATE`, `email` to `EMAIL`, and `text` to `TEXT`.

### Requirement 3: Place, Move, Resize, and Delete Fields

**User Story:** As an Org_Sender, I want to drag fields onto the page and adjust their position and size, so that fields sit exactly where each recipient should sign or enter information.

#### Acceptance Criteria

1. WHEN an Org_Sender drags a Field_Type from the Field_Palette onto a rendered page, THE Field_Placement_Editor SHALL place a Field at the drop position on that page.
2. WHEN an Org_Sender drags an existing Field, THE Field_Placement_Editor SHALL move that Field to the new position on the same page.
3. WHEN an Org_Sender resizes an existing Field using its resize handle, THE Field_Placement_Editor SHALL update that Field's width and height to the new size.
4. WHEN an Org_Sender deletes a Field, THE Field_Placement_Editor SHALL remove that Field from the Field_Set AND SHALL stop rendering it on the page.
5. WHILE an Org_Sender moves or resizes a Field, THE Field_Placement_Editor SHALL constrain the Field so that its entire area remains within the bounds of the page it is placed on.
6. THE Field_Placement_Editor SHALL enforce a minimum Field width and a minimum Field height so that a resized Field remains large enough to display its Field_Type label.

### Requirement 4: Assign Fields to Recipients

**User Story:** As an Org_Sender, I want each field assigned to a specific recipient and color-coded, so that the right person is asked to complete the right field.

#### Acceptance Criteria

1. THE Field_Placement_Editor SHALL associate every Field with exactly one Recipient from the Send_Flow's Recipient list.
2. WHEN an Org_Sender places a Field, THE Field_Placement_Editor SHALL assign that Field to the currently selected Recipient.
3. WHEN an Org_Sender changes the Recipient assigned to a Field, THE Field_Placement_Editor SHALL update that Field's assigned Recipient.
4. THE Field_Placement_Editor SHALL assign each Recipient a distinct color AND SHALL render every Field in the color of its assigned Recipient.
5. WHEN a Recipient is removed in the Send_Flow, THE Field_Placement_Editor SHALL remove every Field assigned to that Recipient from the Field_Set.
6. WHERE a Recipient has a `viewer` Signing_Role, THE Field_Placement_Editor SHALL allow the Field_Set to contain no Fields assigned to that Recipient.

### Requirement 5: Per-Field Required Flag and Text Metadata

**User Story:** As an Org_Sender, I want to mark fields required or optional and label my text fields, so that recipients know what to fill in and which inputs are mandatory.

#### Acceptance Criteria

1. WHEN an Org_Sender toggles a Field between required and optional, THE Field_Placement_Editor SHALL persist the chosen required flag on that Field.
2. WHERE a Field's Field_Type is `text`, THE Field_Placement_Editor SHALL allow the Org_Sender to enter a label and a placeholder for that Field.
3. WHEN the Field_Set is created on the Documenso_Document, THE Esign_Module SHALL include each Field's required flag in that Field's `fieldMeta`.
4. WHERE a `text` Field carries a label or a placeholder, THE Esign_Module SHALL include that label and placeholder in the Field's `fieldMeta` when creating the Field_Set.
5. THE Field_Placement_Editor SHALL display, for every Field, a visible indication of whether the Field is required or optional.

### Requirement 6: Validation Before Send

**User Story:** As an Org_Sender, I want the document blocked from sending until every signer has a signature field and all fields are valid, so that recipients always have something to sign and no field is misconfigured.

#### Acceptance Criteria

1. IF the Field_Set contains a Signing_Recipient with no Signature_Field, THEN THE Esign_Module SHALL block the send AND SHALL return a human-readable error identifying each Signing_Recipient that has no Signature_Field.
2. IF any Field in the Field_Set is assigned to no Recipient, THEN THE Esign_Module SHALL block the send AND SHALL return a human-readable error identifying the unassigned Field.
3. IF any Field in the Field_Set extends beyond the bounds of its page, THEN THE Esign_Module SHALL block the send AND SHALL return a human-readable error identifying the out-of-bounds Field.
4. WHILE the Field_Set fails any send-validation rule, THE Field_Placement_Editor SHALL keep the send control disabled.
5. WHEN the Org_Sender corrects every send-validation failure, THE Field_Placement_Editor SHALL enable the send control.
6. THE Esign_Module SHALL re-validate the submitted Field_Set on the server before creating any Field on the Documenso_Document AND SHALL reject a send whose Field_Set fails server-side validation with a human-readable error without creating any Field.

### Requirement 7: Coordinate Mapping Accuracy

**User Story:** As an Org_Sender, I want fields to appear on the signed document exactly where I placed them, so that signatures and inputs land in the correct location.

#### Acceptance Criteria

1. WHEN a Field is placed, moved, or resized, THE Field_Placement_Editor SHALL convert that Field's Overlay_Coordinates into Normalized_Coordinates using the rendered page's dimensions, with the origin at the top-left of the page.
2. THE Coordinate_Mapping SHALL produce Normalized_Coordinates that are independent of the on-screen render scale across the supported viewport width range of 320 pixels and above.
3. WHEN a Field's Normalized_Coordinates are converted back to Overlay_Coordinates at the same render scale, THE Coordinate_Mapping SHALL reproduce the Field's original Overlay_Coordinates within a tolerance of one CSS pixel (round-trip property).
4. WHEN the Field_Set is created on the Documenso_Document, THE Esign_Module SHALL send each Field's normalized coordinates to the Field_Create_Endpoint as its `pageNumber`, `pageX`, `pageY`, `width`, and `height` wire keys.
5. WHERE a PDF has pages of differing dimensions, THE Coordinate_Mapping SHALL map each Field using the dimensions of the specific page that Field is placed on.

### Requirement 8: Persist the Sender-Defined Field Set to Documenso

**User Story:** As an Org_Sender, I want my placed fields created on the document when I send, so that recipients see and complete exactly the fields I defined.

#### Acceptance Criteria

1. WHEN an Org_Sender confirms a send with a valid Field_Set, THE Esign_Module SHALL create the Documenso_Document from the PDF, register the Recipients, and create every Field in the Field_Set on the Documenso_Document via the Field_Create_Endpoint before the Distribute_Step.
2. WHEN creating the Field_Set, THE Esign_Module SHALL set each Field's `recipientId` to the Documenso recipient identifier of that Field's assigned Recipient.
3. THE Esign_Module SHALL create the sender-defined Field_Set in place of the previous single auto-placed signature field for sends that carry a Field_Set.
4. IF the Field_Create_Endpoint returns an error while creating the Field_Set, THEN THE Esign_Module SHALL NOT perform the Distribute_Step, SHALL record the Envelope with Envelope_Status `error`, AND SHALL return a human-readable error message to the Org_Sender.
5. WHEN the Field_Set has been created and the document has been distributed, THE Esign_Module SHALL record the Envelope as it does for an existing send, including its `org_id`, Agreement_Type, Originating_Entity reference, mapped Documenso document identifier, and initial Envelope_Status.

### Requirement 9: Alignment With Existing Module Constraints

**User Story:** As an organisation, I want the field-placement send to obey the same security, tenancy, and access controls as the existing send flow, so that adding field placement does not weaken any guarantee.

#### Acceptance Criteria

1. WHILE the `esignatures` module is disabled for an organisation, THE Esign_Module SHALL return HTTP 403 for a field-placement send request under `/api/v2/esign`.
2. IF a user without the `org_admin`, `branch_admin`, or `location_manager` role attempts a field-placement send, THEN THE Esign_Module SHALL reject the request with HTTP 403.
3. WHEN the Esign_Module creates the Documenso_Document and Field_Set for an organisation, THE Esign_Module SHALL use that organisation's own team-scoped Documenso service token scoped to that organisation's Documenso Team AND SHALL NOT use another organisation's service token.
4. THE Field_Placement_Editor SHALL NOT expose the Documenso administrative or organisation UI to any OraInvoice organisation user.
5. WHEN the Field_Placement_Editor consumes Esign_Module API responses, THE Field_Placement_Editor SHALL use typed access with optional chaining and array fallbacks AND SHALL bind each in-flight request to an AbortController that is aborted on unmount or cancel.
6. IF the organisation's Documenso_Org_Connection is missing or unverified, THEN THE Esign_Module SHALL block the field-placement send with a human-readable error directing the user to have the Documenso integration set up.

### Requirement 10: Accessibility and Touch Targets

**User Story:** As an Org_Sender using a keyboard or a touch device, I want to place and adjust fields without a precise mouse, so that the editor is usable for everyone.

#### Acceptance Criteria

1. THE Field_Placement_Editor SHALL render each interactive Field control and palette control with a minimum target size of 44 by 44 CSS pixels.
2. THE Field_Placement_Editor SHALL allow an Org_Sender to select a Field and move it using the keyboard.
3. THE Field_Placement_Editor SHALL allow an Org_Sender to delete a selected Field using the keyboard.
4. WHEN a Field is selected, THE Field_Placement_Editor SHALL convey the Field's Field_Type and assigned Recipient through an accessible name.
5. THE Field_Placement_Editor SHALL support placing and adjusting Fields via touch input on the supported viewport width range of 320 pixels and above.

### Requirement 11: Autosave and Cancel of In-Progress Placement

**User Story:** As an Org_Sender, I want my in-progress field placement preserved until I send or cancel, so that I do not lose work and can abandon a draft cleanly.

#### Acceptance Criteria

1. WHILE an Org_Sender edits the Field_Set, THE Field_Placement_Editor SHALL retain the current Field_Set in client state across page navigation within the editor.
2. WHEN an Org_Sender cancels the Field_Placement_Editor, THE Field_Placement_Editor SHALL discard the in-progress Field_Set AND SHALL abort any in-flight send request.
3. WHEN an Org_Sender reopens the Send_Flow after a cancel, THE Field_Placement_Editor SHALL start from an empty Field_Set.
4. IF a field-placement send fails after submission, THEN THE Field_Placement_Editor SHALL retain the Field_Set so that the Org_Sender can correct the failure and retry.

### Requirement 12: Human-Readable Error Messages

**User Story:** As an Org_Sender, I want clear messages when placement or sending fails, so that I understand what went wrong and how to fix it.

#### Acceptance Criteria

1. WHEN a field-placement send fails validation or a Documenso API call, THE Esign_Module SHALL return a human-readable message describing the problem and, where helpful, the corrective action.
2. WHERE an error response includes a machine-readable code, THE Esign_Module SHALL include that code as a secondary field AND SHALL always include a human-readable message alongside it.
3. WHEN an error response is returned from a field-placement send, THE Esign_Module SHALL exclude raw database text and raw exception text from the response.

### Requirement 13: Edit Fields After Send (within limits)

**User Story:** As an Org_Sender, I want to correct or adjust the fields on a document I have already sent, so that I can fix a placement mistake without manually starting over — and when correction is no longer safe, I want to be guided to void and re-create instead.

#### Acceptance Criteria

1. WHILE an Envelope is in the Editable_State, THE Esign_Module SHALL allow an Org_Sender to open the Field_Placement_Editor on that Envelope, load its current Field_Set, and submit an edited Field_Set.
2. IF a user without the `org_admin`, `branch_admin`, or `location_manager` role attempts to edit the Field_Set of an Envelope, THEN THE Esign_Module SHALL reject the request with HTTP 403.
3. WHEN an Org_Sender submits an edited Field_Set for an Envelope in the Editable_State, THE Esign_Module SHALL re-validate the edited Field_Set with the same server-side rules as an initial send AND, on success, SHALL replace the Envelope's existing Documenso Fields with the edited Field_Set so that the prior Fields are removed and only the edited Field_Set remains on the Documenso_Document.
4. IF an Org_Sender attempts to edit the Field_Set of an Envelope in a Non_Editable_State, THEN THE Esign_Module SHALL reject the edit with a human-readable error stating that the document can no longer be edited because signing has begun or the document is finished, AND SHALL offer the Void_And_Recreate path.
5. WHEN an Org_Sender chooses Void_And_Recreate for an Envelope, THE Esign_Module SHALL void the existing Envelope via the existing void path AND SHALL open a new send pre-populated with a copy of the voided Envelope's Field_Set for editing before the new send is confirmed.
6. THE Esign_Module SHALL NOT mutate Fields on a Documenso_Document after any Recipient has signed it, on the basis that the Documenso signing engine does not support post-signature Field mutation; the only supported change after signing has begun is Void_And_Recreate.
7. WHEN an edited Field_Set is successfully applied to an Envelope in the Editable_State, THE Esign_Module SHALL write an Audit_Log entry recording the edit.
8. IF replacing the Documenso Fields fails during an edit, THEN THE Esign_Module SHALL leave the Envelope's prior Field_Set in effect on the Documenso_Document AND SHALL return a human-readable error without partially applying the edited Field_Set.

### Requirement 14: Conditional / Dependent Fields

**User Story:** As an Org_Sender, I want a field to appear or become required only when another field has a particular value, so that recipients are asked for information only when it is relevant.

#### Acceptance Criteria

1. WHEN an Org_Sender defines a Field_Dependency on a Field, THE Field_Placement_Editor SHALL record the Field_Dependency as a Trigger_Field, a Dependency_Condition, and an effect of `show` or `require` on the dependent Field.
2. THE Field_Placement_Editor SHALL allow the Trigger_Field of a Field_Dependency to be any other Field in the same Field_Set AND SHALL reject a Field_Dependency whose Trigger_Field is the dependent Field itself.
3. THE Field_Placement_Editor SHALL support each Dependency_Condition: `is_checked`, `is_not_checked`, `equals`, `not_equals`, `is_filled`, and `is_empty`.
4. IF a set of Field_Dependencies forms a cycle, THEN THE Field_Placement_Editor SHALL reject the Field_Dependency that closes the cycle with a human-readable error AND SHALL NOT store a cyclic dependency.
5. WHERE the Documenso signing engine supports server-side conditional logic for a Field_Dependency, THE Esign_Module SHALL set the Dependency_Enforcement_Mode to `enforced` AND SHALL encode the Field_Dependency in the Field's `fieldMeta` so the dependent Field is shown or required at signing time only when the Dependency_Condition holds.
6. WHERE the Documenso signing engine does not support server-side conditional logic for a Field_Dependency, THE Esign_Module SHALL set the Dependency_Enforcement_Mode to `advisory`, SHALL present every Field to the Recipient unconditionally, AND SHALL record the Field_Dependency for the Org_Sender's reference without representing it as enforced.
7. WHEN a Field_Dependency is `advisory`, THE Field_Placement_Editor SHALL display to the Org_Sender a human-readable notice that the dependency is recorded but not enforced during signing.
8. WHEN a dependent Field carries an `advisory` Field_Dependency with a `require` effect, THE Esign_Module SHALL treat that Field as optional at signing time so that an unmet advisory condition cannot block a Recipient from completing the document.

### Requirement 15: Signing-Order UI

**User Story:** As an Org_Sender, I want to choose whether recipients sign in parallel or in a set order, so that approvals happen in the sequence my process requires.

#### Acceptance Criteria

1. THE Send_Flow SHALL allow an Org_Sender to choose a Signing_Order_Mode of `parallel` or `sequential` for a send.
2. WHEN an Org_Sender has not chosen a Signing_Order_Mode, THE Send_Flow SHALL default the Signing_Order_Mode to `parallel`, matching the current behaviour.
3. WHILE the Signing_Order_Mode is `sequential`, THE Send_Flow SHALL allow the Org_Sender to order the Signing_Recipients into a Signing_Order AND SHALL assign each Signing_Recipient a distinct 1-based position.
4. WHEN the Signing_Order_Mode is `sequential` and the Org_Sender confirms the send, THE Esign_Module SHALL send each Recipient's `signingOrder` position and the `SEQUENTIAL` distribution mode to Documenso on document creation and distribution.
5. WHEN the Signing_Order_Mode is `parallel` and the Org_Sender confirms the send, THE Esign_Module SHALL distribute the document to Documenso using the `PARALLEL` distribution mode.
6. WHERE the Signing_Order_Mode is `sequential`, THE Send_Flow SHALL exclude `viewer`-role Recipients from the signing positions while still including them on the document.

### Requirement 16: Mobile Field-Placement Editor

**User Story:** As an Org_Sender using the OraInvoice mobile app, I want to place signature fields and send a document for signature from my phone, so that I can run the whole send flow in the field without a desktop.

#### Acceptance Criteria

1. WHILE the `esignatures` module is disabled for an organisation, THE Mobile_App SHALL gate the Mobile_Field_Placement_Editor behind the `esignatures` ModuleGate AND SHALL NOT present the editor.
2. IF a Mobile_App user without the `org_admin`, `branch_admin`, or `location_manager` role opens the send flow, THEN THE Mobile_App SHALL withhold the Mobile_Field_Placement_Editor from that user.
3. THE Mobile_App SHALL provide a navigation entry to the e-signature send flow within the More menu, gated by the `esignatures` module.
4. THE Mobile_Field_Placement_Editor SHALL render every page of the uploaded PDF and SHALL support Touch_Place: selecting a Field_Type and tapping a position on a page to place a Field there.
5. WHEN a Field is selected in the Mobile_Field_Placement_Editor, THE Mobile_Field_Placement_Editor SHALL allow the Org_Sender to nudge the Field's position and adjust its size using on-screen controls with a minimum target size of 44 by 44 CSS pixels.
6. THE Mobile_Field_Placement_Editor SHALL support the supported viewport width range of 320 to 430 CSS pixels.
7. WHEN an Org_Sender confirms a mobile send, THE Mobile_App SHALL submit the same backend send contract as the `frontend-v2/` Field_Placement_Editor to the v2 `/api/v2/esign` endpoints.
8. WHEN the Mobile_App consumes Esign_Module API responses, THE Mobile_App SHALL use typed access with optional chaining and array fallbacks AND SHALL bind each in-flight request to an AbortController that is aborted on unmount or cancel.
9. THE Mobile_Field_Placement_Editor SHALL enforce the same client-side send-validation rules as the `frontend-v2/` editor, including that every Signing_Recipient has at least one Signature_Field before the send control is enabled.

### Requirement 17: Saved Field Templates per Agreement Type

**User Story:** As an Org_Sender, I want to save a placed set of fields as a reusable template and apply it to a new send, so that I do not have to re-place the same fields for documents I send repeatedly.

#### Acceptance Criteria

1. WHEN an Org_Sender saves the current Field_Set as a Field_Template with a name, THE Esign_Module SHALL store the Field_Template scoped to the Org_Sender's organisation, including each Field's Field_Type, page, Normalized_Coordinates, required flag, `text` label and placeholder where present, and Template_Recipient_Role, AND SHALL NOT store any specific Recipient's name or email.
2. WHERE an Org_Sender associates a Field_Template with an Agreement_Type, THE Esign_Module SHALL store that Agreement_Type association on the Field_Template.
3. WHEN an Org_Sender lists Field_Templates, THE Esign_Module SHALL return only Field_Templates belonging to the Org_Sender's organisation, enforced by row-level security on the Field_Template store.
4. WHEN an Org_Sender deletes a Field_Template, THE Esign_Module SHALL remove only that Field_Template within the Org_Sender's organisation.
5. WHEN an Org_Sender applies a Field_Template to a send, THE Field_Placement_Editor SHALL create one Field per template Field carrying the stored Field_Type, page, Normalized_Coordinates, required flag, and `text` metadata, AND SHALL map each Field's Template_Recipient_Role to a Recipient chosen for the current send.
6. IF a Field_Template has more Template_Recipient_Roles than the current send has Recipients to map them to, THEN THE Field_Placement_Editor SHALL prompt the Org_Sender to complete the role-to-Recipient mapping before applying AND SHALL NOT leave any applied Field unassigned.
7. IF a user without the `org_admin`, `branch_admin`, or `location_manager` role attempts to create, apply, or delete a Field_Template, THEN THE Esign_Module SHALL reject the request with HTTP 403.
8. WHEN a Field_Template is applied, THE resulting Field_Set SHALL be subject to the same send-validation rules as any other Field_Set before the send is permitted.

## Out of Scope

The following remain explicitly out of scope and are recorded so a reviewer does not flag them as omissions:

- **True post-signature field mutation**: Changing the Fields on a Documenso_Document after any Recipient has signed is not possible through the Documenso signing engine and is not attempted; the supported alternative is Void_And_Recreate (Requirement 13).
- **Enforced conditional logic when the engine cannot apply it**: When the Documenso signing engine cannot enforce a Field_Dependency, conditional behaviour is recorded as `advisory` only (Requirement 14.6); OraInvoice does not build a parallel signing UI to enforce conditions outside Documenso.
- **Cross-organisation Field_Templates**: Field_Templates are organisation-scoped; sharing templates between organisations is not supported.
- **Reordering signing after distribution**: The Signing_Order is fixed at send time; changing the order of an already-distributed Envelope is not supported (use Void_And_Recreate).

## Non-Functional Constraints and Assumptions

These items constrain the design and are recorded as accepted context rather than testable behavioural requirements:

- **In-browser PDF rendering**: Page rendering uses PDF.js or an equivalent in-browser PDF rendering library bundled into `frontend-v2/`. Rendering happens client-side; the PDF bytes are uploaded to Documenso only on confirmed send, through the existing per-org send pipeline.
- **Documenso v2 field API**: The Documenso client has been migrated to the v2 RPC API. Field creation uses `POST /api/v2/document/field/create-many` with `{ documentId, fields[] }`, where each field carries `recipientId`, `type`, `pageNumber`, `pageX`, `pageY`, `width`, `height`, and optional `fieldMeta`. Document creation posts the PDF inline as `multipart/form-data` to `POST /api/v2/document/create` (a JSON `payload` part plus the raw PDF `file` part), returning `{ id, envelopeId }`, and the recipients (with their tokens) are read back via `GET /api/v2/document/{id}` — there is no presigned `uploadUrl` step; distribution uses `POST /api/v2/document/distribute`.
- **Normalized coordinate convention**: Documenso accepts field positions in normalized page units with the origin at the top-left of the page. The editor is responsible for the Coordinate_Mapping between on-screen CSS pixels and these normalized units.
- **Replaces auto-placement**: This feature replaces the existing single auto-placed SIGNATURE field (the `_DEFAULT_FIELD_PAGE_*` / `place_signature_field` path in `app/modules/esignatures/service.py`) for sends that carry a sender-defined Field_Set, while preserving the Requirement 17 safety rule from `esignature-integration` that every Signing_Recipient must have at least one Signature_Field before distribution.
- **Reuses existing module guarantees**: Module gating (HTTP 403 when disabled), send RBAC (`require_esign_sender`), per-org team-scoped Documenso calls, envelope recording, audit logging, and notifications are inherited unchanged from `esignature-integration` and are not redefined here.
- **Large and many-page PDFs**: Rendering and placement must remain usable for large or many-page PDFs; pages may be rendered progressively. Specific performance budgets are an operational/design concern rather than a behavioural requirement.
- **Documenso conditional-logic capability is uncertain**: Documenso's public v2 field model may not support server-side conditional logic via `fieldMeta`. Requirement 14 is written so that the Dependency_Enforcement_Mode (`enforced` vs `advisory`) is resolved against the engine's actual capability at design time; the requirement does not promise enforcement the engine cannot deliver. Confirming the exact `fieldMeta` capability is a design-phase investigation.
- **Post-send edit replaces the Field_Set**: Requirement 13 edits operate by replacing the Documenso Fields for an Envelope in the Editable_State (delete-and-recreate the Field_Set), not by diff-patching individual Fields; this matches the create-many field API and keeps the edit atomic.
- **New persistence for templates**: Field_Templates (Requirement 17) require a new organisation-scoped, RLS-protected store (table) for template definitions, distinct from the transient per-send Field_Set, which remains non-persistent. The signing-order, conditional, and post-send-edit capabilities do not require new tables beyond reusing the existing `esign_envelopes` / `esign_recipients` rows.
- **Mobile delivery is governed by the mobile steering guide**: The Mobile_Field_Placement_Editor (Requirement 16) lives in `mobile/` (React 19 + Capacitor), is for organisation users only, uses v2 endpoints with safe API consumption and AbortController cleanup, honours 44 px touch targets and the 320–430 px viewport range, and is gated by the `esignatures` ModuleGate. Touch placement uses Touch_Place (tap-to-place plus nudge/resize controls) rather than fine pointer dragging, reflecting the realistic constraint of precise placement on a small touch screen.
