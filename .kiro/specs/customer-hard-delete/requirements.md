# Requirements Document

## Introduction

Today, the "Delete customer" action in OraInvoice is not a real delete. `DELETE /api/v1/customers/{id}` routes to `anonymise_customer_endpoint` → `anonymise_customer()`, which performs an **in-place anonymise**: it sets `is_anonymised=True`, overwrites the name to "Anonymised Customer", clears contact PII, scrubs customer PII inside each linked invoice's `invoice_data_json`, and preserves the customer row, the `customer_vehicles` links, and all invoices/payments. The customer list then filters out `is_anonymised=True` records, so the row appears to "disappear".

A production incident exposed two problems with this design:

1. The destructive delete-as-anonymise runs with **no warning and no mandatory reason**. An org_admin clicked Delete expecting a deletion, the record was silently anonymised, and subsequent PUT edits returned HTTP 400 ("Cannot update an anonymised customer record").
2. Anonymising leaves **vehicles stranded** on a confusingly named ghost "Anonymised Customer" record, because the `customer_vehicles` links are preserved against the anonymised row.

This feature introduces a **guarded hard delete** of a customer record — a genuine removal of the customer — that replaces the silent anonymise-on-delete behaviour. The hard delete is gated by safety checks: it blocks when the customer has legally-retained financial documents (issued invoices and their payment chain), forces a mandatory reason, displays New Zealand financial record-keeping warnings, requires an explicit irreversible-confirmation step, orphans linked vehicles instead of destroying them, and captures a full audit trail. The existing anonymise capability remains available as the Privacy-Act erasure path but is no longer silently mapped to "Delete".

This document specifies WHAT the feature must do. Implementation specifics (the concrete per-table referential-integrity mechanics, the chosen frontend surface, exact API routes and schemas) are resolved in the design phase; several genuinely ambiguous decisions are explicitly flagged as **Open Decisions for Design** in Requirement 12.

## Glossary

- **Customer_Service**: The backend customer module (`app/modules/customers/`) responsible for customer CRUD, anonymise, and the new hard delete operation.
- **Hard_Delete**: The operation that genuinely removes a `customers` row (and its non-financial dependent rows per the referential-integrity policy), as distinct from anonymise.
- **Anonymise**: The existing Privacy-Act erasure operation that retains the `customers` row, sets `is_anonymised=True`, and scrubs PII while preserving financial records.
- **Org_Admin**: The organisation-level administrator role (`org_admin`); the only role permitted to perform Hard_Delete, mirroring the existing `DELETE /api/v1/customers/{id}` role guard.
- **Issued_Invoice**: An invoice whose `status` is any value other than `draft` — i.e. `issued`, `partially_paid`, `paid`, `overdue`, `voided`, `refunded`, or `partially_refunded`. These are legally-retained financial documents (a voided invoice number must still be retained as part of the financial record).
- **Draft_Invoice**: An invoice whose `status` is `draft`. A Draft_Invoice has never been issued and is not a legal financial record.
- **Financial_Document**: An Issued_Invoice and its attached financial chain — `payments` rows and `credit_notes` rows linked to that invoice. Quotes are not Financial_Documents.
- **Blocking_Document**: A Financial_Document whose existence prevents a Hard_Delete from proceeding until the org user explicitly deletes it first.
- **Orphaned_Vehicle**: A vehicle (`org_vehicles` or `global_vehicles` row) whose `customer_vehicles` link to the deleted customer has been removed, while the underlying vehicle row is preserved so its history and specifications survive and it remains findable.
- **Customer_Vehicle_Link**: A row in the `customer_vehicles` table connecting a customer to exactly one vehicle (`global_vehicle_id` or `org_vehicle_id`).
- **Deletion_Reason**: A mandatory, non-empty, free-text justification supplied by the org user and stored in the audit log.
- **Irreversible_Confirmation**: An explicit user confirmation step (for example, type-to-confirm or an explicit confirm action) acknowledging the Hard_Delete cannot be undone.
- **NZ_Retention_Warning**: A warning describing New Zealand financial record-keeping obligations, specifically that the Inland Revenue Department (IRD) requires tax invoices and business records be retained for approximately seven years.
- **Audit_Log**: The append-only audit trail written via `write_audit_log` in `app/core/audit.py`.
- **Referencing_Table**: Any database table with a `customer_id` column (with or without a declared foreign key to `customers.id`). Verified by an exhaustive `customer_id` scan of `app/**/models.py` — the authoritative list is the Referential Integrity Matrix in design.md. It includes: `customer_vehicles`, `invoices`, `quotes`, `recurring_schedules`, `pos_transactions`, `reminder_queue` (notifications), `job_cards`, `customer_claims`, `bookings`, `portal_sessions`, `portal_accounts`, `portal_fleet_accounts`, and the FK-less `projects`, `pricing_rules`, `expenses`, `jobs` (jobs_v2), `assets`, `loyalty_transactions`. Note several of these carry `customer_id` with **no declared FK**, so a naive delete does not raise but would leave a silent dangling reference.
- **RLS**: PostgreSQL Row-Level Security; all customer operations are scoped to the current organisation via `org_id`.

## Requirements

### Requirement 1: Guarded Hard Delete of a Customer

**User Story:** As an org_admin, I want to genuinely delete a customer record, so that a record created in error (for example a duplicate kiosk-created customer) is actually removed rather than silently anonymised.

#### Acceptance Criteria

1. WHEN an Org_Admin requests a Hard_Delete of a customer AND all guard conditions in Requirements 2, 4, and 5 are satisfied, THE Customer_Service SHALL permanently remove the `customers` row for that customer within the requesting organisation.
2. WHEN a Hard_Delete completes successfully, THE Customer_Service SHALL return a result that identifies the deleted customer, the count of Customer_Vehicle_Links that were removed, and the count of Draft_Invoices the user chose to delete beforehand.
3. WHEN a Hard_Delete completes successfully, THE Customer_Service SHALL exclude the deleted customer from all subsequent customer queries within the organisation.
4. THE Customer_Service SHALL treat Hard_Delete and Anonymise as two distinct operations with distinct outcomes.
5. THE Customer_Service SHALL stop mapping the "Delete customer" user action to Anonymise.

### Requirement 2: Block Deletion When Legally-Retained Financial Documents Exist

**User Story:** As a business owner, I want the system to prevent deletion of a customer that still has issued invoices, so that I never lose financial records I am legally required to keep.

#### Acceptance Criteria

1. IF a customer has at least one Issued_Invoice, THEN THE Customer_Service SHALL reject the Hard_Delete and SHALL leave the customer and all related rows unchanged.
2. WHEN a Hard_Delete is rejected because Blocking_Documents exist, THE Customer_Service SHALL return the count of Blocking_Documents and an identifier and invoice number for each Blocking_Document.
3. WHEN a Hard_Delete is rejected because Blocking_Documents exist, THE Customer_Service SHALL return a message instructing the Org_Admin to delete the listed invoices before the customer can be deleted.
4. WHERE an Issued_Invoice has attached `payments` or `credit_notes`, THE Customer_Service SHALL treat that payment-and-credit-note chain as part of the same Blocking_Document set that must be explicitly deleted before the customer.
5. THE Customer_Service SHALL classify a Draft_Invoice as non-blocking for the purposes of Requirement 2.
6. THE Customer_Service SHALL classify a quote as non-blocking for the purposes of Requirement 2.

### Requirement 3: New Zealand Financial Record-Keeping Warning

**User Story:** As an org_admin, I want a clear warning about New Zealand record-keeping rules before I delete any invoice or customer, so that I understand the legal implications of the deletion.

#### Acceptance Criteria

1. WHEN an Org_Admin initiates a Hard_Delete, THE Customer_Service SHALL provide the NZ_Retention_Warning content describing the IRD approximately seven-year retention obligation for tax invoices and business records.
2. WHEN an Org_Admin initiates deletion of an invoice that is a Financial_Document, THE Customer_Service SHALL provide the NZ_Retention_Warning content before that invoice is deleted.
3. THE NZ_Retention_Warning SHALL state the approximate retention period of seven years.

### Requirement 4: Mandatory Deletion Reason

**User Story:** As a business owner, I want every customer deletion to require a written reason, so that there is an accountable record of why a record was removed.

#### Acceptance Criteria

1. IF a Hard_Delete request does not include a non-empty Deletion_Reason, THEN THE Customer_Service SHALL reject the Hard_Delete and SHALL leave the customer and all related rows unchanged.
2. THE Customer_Service SHALL treat a Deletion_Reason consisting only of whitespace as empty.
3. WHEN a Hard_Delete completes successfully, THE Customer_Service SHALL store the Deletion_Reason in the Audit_Log entry for that deletion.
4. WHERE the Org_Admin deletes one or more invoices as a prerequisite to a Hard_Delete, THE Customer_Service SHALL require and record a Deletion_Reason for that invoice deletion.

### Requirement 5: Irreversible-Action Confirmation

**User Story:** As an org_admin, I want to explicitly confirm that I understand a customer deletion cannot be undone, so that I do not destroy a record by accident.

#### Acceptance Criteria

1. WHEN an Org_Admin initiates a Hard_Delete, THE Customer_Service SHALL present an Irreversible_Confirmation indicating the deletion cannot be undone.
2. IF a Hard_Delete request does not include a valid Irreversible_Confirmation, THEN THE Customer_Service SHALL reject the Hard_Delete and SHALL leave the customer and all related rows unchanged.
3. WHEN a valid Irreversible_Confirmation and a non-empty Deletion_Reason are both present AND all other guard conditions are satisfied, THE Customer_Service SHALL proceed with the Hard_Delete.

### Requirement 6: Orphan Vehicles, Preserve Vehicle Records

**User Story:** As a workshop manager, I want a customer's vehicles to survive when the customer is deleted, so that vehicle history and specifications are not lost and the vehicles can be re-linked later.

#### Acceptance Criteria

1. WHEN a Hard_Delete completes successfully, THE Customer_Service SHALL remove every Customer_Vehicle_Link that references the deleted customer.
2. WHEN a Hard_Delete completes successfully, THE Customer_Service SHALL preserve every `org_vehicles` row and every `global_vehicles` row that was linked to the deleted customer.
3. WHEN a Hard_Delete completes successfully, THE Customer_Service SHALL leave each Orphaned_Vehicle findable through vehicle search and lookup.
4. WHEN a Hard_Delete completes successfully, THE Customer_Service SHALL NOT remove any `customer_vehicles` row that references a different customer.

### Requirement 7: Preserve Financial and Transaction History

**User Story:** As a business owner, I want the customer-delete operation itself to never destroy financial records, so that the only financial rows ever removed are the ones I explicitly deleted first.

#### Acceptance Criteria

1. THE Customer_Service SHALL NOT delete any `invoices`, `payments`, or `credit_notes` row as a direct effect of the Hard_Delete operation.
2. WHERE the Org_Admin has explicitly deleted Draft_Invoices before the Hard_Delete, THE Customer_Service SHALL treat only those user-initiated deletions as the cause of any removed invoice rows.
3. WHEN a Hard_Delete is attempted while any Issued_Invoice remains, THE Customer_Service SHALL reject the Hard_Delete per Requirement 2.

### Requirement 8: Full Audit Trail

**User Story:** As a business owner, I want a complete audit record of every customer deletion, so that I can later see who deleted what, when, and why.

#### Acceptance Criteria

1. WHEN a Hard_Delete completes successfully, THE Customer_Service SHALL write an Audit_Log entry recording the acting user identifier, the deletion timestamp, and the Deletion_Reason.
2. WHEN a Hard_Delete completes successfully, THE Audit_Log entry SHALL record the deleted customer identifier and the identifiers of any invoices the Org_Admin deleted as a prerequisite.
3. WHEN a Hard_Delete completes successfully, THE Audit_Log entry SHALL record the identifiers of the Orphaned_Vehicles.
4. THE Customer_Service SHALL use a distinct Audit_Log action name for Hard_Delete that differs from the Anonymise action name.
5. THE Customer_Service SHALL exclude customer PII beyond the identifiers necessary to attribute the deletion from the Audit_Log entry.

### Requirement 9: Transactional, All-or-Nothing Execution

**User Story:** As a business owner, I want a customer deletion to either fully succeed or fully roll back, so that a failed delete never leaves the data half-removed or inconsistent.

#### Acceptance Criteria

1. THE Customer_Service SHALL perform the Hard_Delete and its dependent row changes within a single database transaction.
2. IF any step of the Hard_Delete fails, THEN THE Customer_Service SHALL roll back all changes so that the customer and all related rows match their state before the operation.
3. IF any step of the Hard_Delete fails, THEN THE Customer_Service SHALL NOT write a success Audit_Log entry for that deletion.
4. WHEN a Hard_Delete is requested for a customer that does not exist within the organisation, THE Customer_Service SHALL return a not-found result without modifying any data.

### Requirement 10: Role and Multi-Tenant Scoping

**User Story:** As a platform operator, I want hard delete restricted to org admins and scoped to a single organisation, so that one organisation can never delete another organisation's data.

#### Acceptance Criteria

1. IF a Hard_Delete is requested by a user whose role is not Org_Admin, THEN THE Customer_Service SHALL reject the request and SHALL leave all data unchanged.
2. IF a Hard_Delete is requested for a customer that belongs to a different organisation than the requesting user, THEN THE Customer_Service SHALL return a not-found result and SHALL leave that customer unchanged.
3. THE Customer_Service SHALL scope every query and every deletion in the Hard_Delete operation to the requesting organisation under RLS.

### Requirement 11: Referential Integrity Across Referencing Tables

**User Story:** As a developer, I want every table that references a customer to be handled explicitly on hard delete, so that no foreign-key violation occurs and no financial or legal record is silently destroyed.

#### Acceptance Criteria

1. THE Customer_Service SHALL define, for every Referencing_Table, an explicit handling policy of exactly one of: block the delete, require prior explicit deletion, set the reference to null, or cascade.
2. THE Customer_Service SHALL NOT silently destroy any financial or legal record as a side effect of resolving a Referencing_Table reference.
3. WHEN a Hard_Delete completes successfully, THE Customer_Service SHALL leave no Referencing_Table row holding a dangling reference to the deleted customer.
4. WHERE a Referencing_Table holds a Financial_Document or other legally-retained record, THE Customer_Service SHALL apply the block or require-prior-deletion policy rather than cascade or set-null.

### Requirement 12: Relationship to Anonymise and Open Decisions for Design

**User Story:** As a product owner, I want the relationship between hard delete and the existing anonymise capability defined, so that both privacy erasure and genuine deletion remain available without one silently replacing the other.

#### Acceptance Criteria

1. THE Customer_Service SHALL keep the Anonymise capability available as the Privacy-Act erasure path.
2. THE Customer_Service SHALL present Hard_Delete and Anonymise as separately selectable actions to the Org_Admin.
3. THE Customer_Service SHALL NOT route the "Delete customer" action to Anonymise without an explicit Org_Admin choice.

#### Open Decisions for Design (to be resolved in the design phase)

- **D1 — Existing endpoint contract:** Whether the new Hard_Delete reuses the existing `DELETE /api/v1/customers/{id}` route (changing its meaning from anonymise to guarded hard delete) or is introduced as a new endpoint, and how the Anonymise action is then exposed. The design MUST NOT leave the current "Delete = silent anonymise" behaviour in place.
- **D2 — Per-table referential-integrity policy:** The concrete block / require-prior-delete / set-null / cascade decision for each Referencing_Table (`customer_vehicles`, `invoices`, `quotes`, `recurring_schedules`, `pos_transactions`, notifications `reminder_queue`, `job_cards`, `customer_claims`, `bookings`, `portal_sessions`/`portal_accounts`/`portal_fleet_accounts`, and the FK-less `projects`, `pricing_rules`, `expenses`, `jobs` (jobs_v2), `assets`, `loyalty_transactions`), including any Alembic migration needed to add `ON DELETE` behaviour, subject to Requirement 11.
- **D3 — Scope of "must delete first":** Whether the financial chain that blocks deletion is limited to Issued_Invoices plus their payments and credit notes, or also includes other legally-retained documents (for example claims), subject to Requirement 2 and Requirement 11.
- **D4 — Frontend target(s):** Which frontend surfaces receive the confirmation/warning UI. **Resolved:** the redesign (`frontend-v2/`) only — the production frontend (`frontend/`, v1.13.0) is explicitly out of scope and must not be modified. The confirmation and warning UI MUST follow `safe-api-consumption.md`.
- **D5 — Confirmation mechanism:** Whether Irreversible_Confirmation is implemented as type-to-confirm, an explicit confirm step, or both.
- **D6 — Idempotency:** Whether repeating a Hard_Delete for an already-deleted customer returns an idempotent not-found result, per Requirement 9.4.

## Non-Functional Requirements

### NFR 1: Data Safety and Backward Compatibility

1. THE Customer_Service SHALL execute the Hard_Delete as a single all-or-nothing transaction (see Requirement 9).
2. IF the Hard_Delete fails for any reason, THEN THE Customer_Service SHALL leave the data exactly as it was before the operation.
3. THE Customer_Service SHALL preserve the existing Anonymise behaviour and its API for callers that continue to use it.

### NFR 2: Backend Implementation Patterns

1. THE Customer_Service SHALL implement the Hard_Delete using async SQLAlchemy consistent with the existing customer module.
2. THE Customer_Service SHALL use `flush()` within the service layer and rely on the `get_db_session` `session.begin()` context manager for commit and rollback, consistent with the project's stated pattern.
3. THE Customer_Service SHALL enforce the Org_Admin role guard consistent with the existing `DELETE /api/v1/customers/{id}` guard.
4. THE Customer_Service SHALL return responses in the project's wrapped-response shape.

### NFR 3: Frontend Safety

1. WHERE confirmation or warning UI consumes API responses, THE frontend SHALL apply the safe API consumption patterns defined in `safe-api-consumption.md` (optional chaining and `?? []` / `?? 0` fallbacks, AbortController cleanup, no `as any`).
2. THE frontend SHALL field-name-align its request payload and response handling with the backend Pydantic schema.

### NFR 4: Auditability and Privacy

1. THE Customer_Service SHALL record the Deletion_Reason and a full Audit_Log entry for every successful Hard_Delete (see Requirement 8).
2. THE Customer_Service SHALL limit Audit_Log content to the identifiers and reason necessary to attribute the deletion, excluding unnecessary customer PII.

## Correctness Properties (Property-Based Test Candidates)

The following properties are derived from the testability prework and are strong candidates for property-based tests during design and implementation. Each runs cheaply against an in-memory/transactional test database (testing OraInvoice's own logic, not external services).

1. **Issued-invoice block invariant (Req 2.1):** For any customer with at least one Issued_Invoice, a Hard_Delete is always rejected and the customer still exists afterwards. (invariant / error-condition)
2. **Blocking set is exact (Req 2.2):** For any mix of invoice statuses, the returned blocking count equals the number of Issued_Invoices and the returned ids equal exactly that set. (model-based: `count == len(filter(issued))`)
3. **Mandatory-reason rejection (Req 4.1):** For any blank, whitespace-only, or missing Deletion_Reason, the Hard_Delete is always rejected with no state change. (error-condition)
4. **Reason round-trip (Req 4.3, 8.1):** For any successful Hard_Delete with reason R, the persisted Audit_Log reason equals R. (round-trip)
5. **Confirmation gate (Req 5.2):** Without a valid Irreversible_Confirmation, the Hard_Delete is always rejected with no state change. (error-condition)
6. **No dangling vehicle links (Req 6.1):** After a successful Hard_Delete, the count of `customer_vehicles` rows referencing the deleted customer is zero. (invariant)
7. **Vehicles orphaned, not destroyed (Req 6.2):** The set of `org_vehicles`/`global_vehicles` ids linked before the delete is a subset of the vehicle ids present after the delete. (invariant / metamorphic)
8. **No financial rows destroyed by the delete itself (Req 7.1):** The Hard_Delete operation removes zero `invoices`/`payments`/`credit_notes` rows directly; any removed invoice corresponds to an explicit prior user deletion. (invariant)
9. **Atomic rollback (Req 9.2):** With a fault injected mid-operation over a randomized related-row graph, the post-state equals the pre-state exactly. (invariant)
10. **Audit completeness (Req 8.1–8.3):** For any successful Hard_Delete, the Audit_Log entry contains the actor, timestamp, reason, deleted customer id, prerequisite-deleted invoice ids, and orphaned vehicle ids. (model-based)
11. **Org isolation (Req 10.2, 10.3):** A Hard_Delete targeting a customer in another organisation returns not-found and leaves that customer unchanged. (error-condition / security invariant)
12. **Drafts and quotes never block (Req 2.5, 2.6):** A customer whose only documents are Draft_Invoices and/or quotes is never blocked by Requirement 2. (invariant)
13. **Idempotent not-found (Req 9.4):** Re-issuing the same Hard_Delete for an already-deleted customer returns a deterministic not-found result with no error-state corruption. (idempotence)

### Example-Based / Edge-Case Tests (not property-based)

- **Distinct operations (Req 1.4):** Hard_Delete removes the row; Anonymise retains the row with `is_anonymised=True`. (example)
- **NZ retention warning presence/content (Req 3):** The warning is shown with the seven-year period before deleting an invoice or customer. (example / UI)
- **Role matrix (Req 10.1):** Each non-org_admin role is rejected with 403. (example / enumerable)
- **Per-table referential-integrity mechanics (Req 11):** Each Referencing_Table behaves per its design-assigned policy with 1–3 representative cases. (edge-case)
