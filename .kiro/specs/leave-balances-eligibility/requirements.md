# Requirements Document

## Introduction

This feature adds a dedicated **Leave Balances** view to the OraInvoice staff-management surface and the **eligibility / accrual rules engine** that drives it. Today, OraInvoice already has the per-staff balance plumbing — `leave_types`, `leave_balances`, the append-only `leave_ledger`, the manual-adjust endpoint, and the request/approve workflow — but there is no org-wide place to see everyone's balances, and there is no engine that decides *when* a staff member becomes eligible for a given leave type under New Zealand law.

The genuinely new work is:

1. An **org-wide Leave Balances tab** that lists all staff with their balances, supports filtering/grouping by employment type (a display convenience only — see below), and lets an authorised user drill into one staff member's per-type balances and ledger history, and adjust a balance from the UI.
2. An **eligibility / accrual rules engine** that vests and starts balances based on **length of continuous service** (day-1 / 6-month / 12-month milestones) plus a **minimum-hours test**, encoded as a **versioned, effective-dated rule-set** so a future law change can be added additively.
3. **Eligibility-onset in-app notifications** plus an **explanatory note** surfaced to org users explaining *why* a staff member newly has a given leave entitlement.
4. **Casual 8% pay-as-you-go** handling and the **termination payout** rules (pre/post 12-month annual-leave vest).
5. An in-app **NZ Holidays Act 2003 reference guide** for org users.
6. **Module gating** under `staff_management` and **RBAC** governing who can view all balances versus adjust them.

A critical build constraint from the business: **eligibility MUST NOT branch on employment type** (permanent / fixed-term / full-time / part-time are treated identically under the Holidays Act 2003). Eligibility keys on exactly two facts — continuous service length and the hours test. The one genuinely different path is **casual**, which is paid 8% holiday pay each pay period instead of accruing annual leave. Employment type in this feature is therefore only a **display filter/grouping convenience**, never the eligibility gate.

The current law is encoded as the **"Holidays Act 2003" rule-set version**. A second rule-set (the **Employment Leave Bill**, expected to take effect around 2028) is explicitly **deferred** but the engine MUST be designed so the second version can be added without a rewrite.

This spec scopes the **gaps only**. It reuses the existing `leave_balances`, `leave_ledger`, `leave_types`, and the manual-adjust endpoint rather than introducing parallel tables; the rules engine and its configuration are the principal new backend pieces.

## Glossary

- **Leave_Balances_View**: The new org-wide UI surface (a tab/page under Staff or Leave) that lists all staff with their leave balances and provides drill-in, adjustment, configuration links, and the reference guide.
- **Accrual_Engine**: The new backend component that evaluates eligibility milestones and the hours test for each staff member × leave type, vests entitlements, and writes the resulting accrual entries to `leave_ledger` / `leave_balances`.
- **Rule_Set_Version**: A named, effective-dated set of leave eligibility and accrual rules. The first version is `holidays_act_2003`. Each version carries an `effective_from` date and (optionally) an `effective_until` date; the Accrual_Engine selects the version applicable to the evaluation date.
- **Continuous_Service**: The unbroken length of employment measured from a staff member's `employment_start_date` to a given evaluation date, expressed in completed months. A 90-day trial period does NOT delay or reset Continuous_Service.
- **Service_Milestone**: A Continuous_Service threshold that gates a leave entitlement under the Holidays Act 2003 rule-set. The milestones are **day 1** (0 months), **6 months**, and **12 months**.
- **Hours_Test**: The minimum-work test under the Holidays Act 2003 that gates sick, bereavement, and family-violence leave for staff who are not obviously full-time. It is met when, over the relevant qualifying period, the staff member has worked on average **at least 10 hours per week**, AND **at least 1 hour every week** OR **at least 40 hours every month**.
- **Vesting_Event**: The moment the Accrual_Engine determines a staff member has newly satisfied the eligibility conditions for a leave type (Service_Milestone reached and, where applicable, Hours_Test met), causing that leave type's balance to start being shown and (for accruing types) to receive its entitlement.
- **Eligibility_Note**: A human-readable explanatory message attached to a Vesting_Event and surfaced to org users, stating which leave type vested, the rule that triggered it, and the date (e.g. "Annual holidays vested — 12 months continuous service reached on 2026-03-01").
- **Otherwise_Working_Day** (OWD): A day on which a staff member would otherwise have worked had it not been a public holiday; used to decide whether a public holiday is paid and whether an alternative holiday is earned.
- **Alternative_Holiday**: A paid day off in lieu earned when a staff member works on a public holiday that is an Otherwise_Working_Day (also called a "lieu day").
- **Casual_PAYG**: The pay-as-you-go holiday-pay arrangement for casual staff (and fixed-term staff under 12 months by agreement), under which **8% of gross earnings** is paid each pay period instead of accruing annual holidays.
- **Termination_Payout**: The annual-holidays amount owed when employment ends — **8% of gross earnings** if termination occurs **before** the 12-month annual-leave vest, or the value of remaining accrued annual holidays paid at the **greater of ordinary weekly pay or average weekly earnings** if **on or after** the vest.
- **Reference_Guide**: An in-app help/reference page for org users that explains the NZ Holidays Act 2003 leave rules covered by this feature.
- **Employment_Type**: The configured classification on a staff profile (`employment_type` / `employment_basis` — e.g. permanent, fixed-term, full-time, part-time, casual). Used in this feature only as a display filter/grouping dimension and to identify casual staff for Casual_PAYG; it is NOT an eligibility gate for statutory leave.
- **Org_User**: An authenticated user belonging to an organisation (e.g. org_admin, branch_admin, manager) who interacts with the Leave_Balances_View, subject to RBAC.
- **Staff_Management_Module**: The module slug `staff_management` that gates access to all surfaces and endpoints in this feature.

## Requirements

### Requirement 1: Org-wide leave balances list

**User Story:** As an Org_User, I want a single Leave_Balances_View that lists every staff member with their leave balances, so that I can see the whole organisation's leave position in one place.

#### Acceptance Criteria

1. WHERE the Staff_Management_Module is enabled for the organisation, THE Leave_Balances_View SHALL be reachable from the staff/leave navigation.
2. IF the Staff_Management_Module is disabled for the organisation, THEN THE Leave_Balances_View SHALL NOT be reachable and the supporting list endpoint SHALL respond with HTTP 404 and detail `not_enabled`.
3. WHEN an authorised Org_User opens the Leave_Balances_View, THE System SHALL return the list of staff members with their per-leave-type balances in a response of the form `{ items, total }`.
4. THE System SHALL scope the balances list to the requesting organisation using row-level security.
5. WHEN the Leave_Balances_View renders a staff member's balance for a leave type, THE System SHALL display accrued hours, used hours, pending hours, and available hours, where available hours equals accrued minus used minus pending.
6. WHERE a staff member has no vested entitlement for a leave type, THE Leave_Balances_View SHALL omit that leave type's balance from that staff member's row.
7. WHEN the balances list contains more staff than the page size, THE System SHALL paginate the list using `offset` and `limit` parameters.
8. WHEN an authorised Org_User holding the balance-view permission with the Staff_Management_Module enabled opens the Leave_Balances_View and no staff members or balances fall within the user's scope, THE System SHALL return an empty result of the form `{ items: [], total: 0 }`.

### Requirement 2: Filter and group by employment type

**User Story:** As an Org_User, I want to filter and group the balances list by employment type, so that I can review balances for a subset of staff, while understanding that employment type does not change statutory eligibility.

#### Acceptance Criteria

1. WHEN an Org_User selects an Employment_Type filter value, THE Leave_Balances_View SHALL display only staff members whose configured Employment_Type matches the selected value.
2. WHEN an Org_User selects grouping by Employment_Type, THE Leave_Balances_View SHALL group staff rows by their configured Employment_Type.
3. WHEN no Employment_Type filter is selected, THE Leave_Balances_View SHALL display staff members of all employment types while continuing to honour any other active filters and search terms.
4. THE Accrual_Engine SHALL determine statutory leave eligibility independently of Employment_Type, using only Continuous_Service and the Hours_Test.
5. WHERE the Leave_Balances_View presents the Employment_Type filter, THE Leave_Balances_View SHALL display an explanatory statement that the filter is a display convenience and does not change statutory leave eligibility.

### Requirement 3: Per-staff balances and ledger history

**User Story:** As an Org_User, I want to drill into one staff member to see each leave type's balance and full usage history, so that I can understand how their balance was reached.

#### Acceptance Criteria

1. WHEN an Org_User opens a staff member's leave detail, THE System SHALL return that staff member's balances per leave type as `{ items, total }`.
2. WHEN an Org_User opens a staff member's leave detail, THE System SHALL return that staff member's `leave_ledger` history as `{ items, total }`.
3. WHEN the ledger history is returned, THE System SHALL order ledger entries by their occurrence date.
4. WHEN a ledger entry is displayed, THE System SHALL show the delta hours, the reason, and the occurrence date.
5. WHEN an Org_User requests ledger history for a single leave type, THE System SHALL return only ledger entries for that leave type.
6. THE System SHALL NOT update or delete existing `leave_ledger` rows when serving or modifying balance history.
7. WHEN a correction or administrative adjustment to leave history is required, THE System SHALL append a new `leave_ledger` row and SHALL NOT edit or remove any existing `leave_ledger` row.

### Requirement 4: Surface manual balance adjustment in the UI

**User Story:** As an authorised Org_User, I want to adjust a staff member's leave balance with a reason from the Leave_Balances_View, so that I can correct balances without leaving the page.

#### Acceptance Criteria

1. WHERE an Org_User holds the balance-adjust permission, THE Leave_Balances_View SHALL present a manual-adjustment action for a staff member's leave-type balance.
2. WHEN an authorised Org_User submits a manual adjustment with a delta and a reason, THE System SHALL apply the adjustment via the existing adjust endpoint and append a new `leave_ledger` row with reason `adjustment`.
3. IF an Org_User submits a manual adjustment without a reason, THEN THE System SHALL reject the adjustment and return a validation error.
4. IF an Org_User without the balance-adjust permission attempts a manual adjustment, THEN THE System SHALL reject the request with HTTP 403.
5. WHEN a manual adjustment succeeds, THE Leave_Balances_View SHALL display the updated balance and the new ledger entry.
6. WHEN a manual adjustment is applied, THE System SHALL write an audit-log entry recording the actor, the staff member, the leave type, the delta, and the reason.
7. IF the adjust operation fails after a `leave_ledger` row would be created, THEN THE System SHALL roll back the transaction so that no orphan `leave_ledger` row persists, committing the adjustment and its ledger row together or neither.

### Requirement 5: Surface leave-type configuration from the view

**User Story:** As an Org_User, I want the Leave_Balances_View to link to leave-type configuration, so that I can set up accrual and leave types without hunting through settings.

#### Acceptance Criteria

1. THE Leave_Balances_View SHALL present a link to the Settings → Leave Types configuration surface.
2. WHEN an Org_User activates the configuration link, THE System SHALL navigate to the leave-type configuration surface.
3. WHERE an Org_User lacks permission to configure leave types, THE Leave_Balances_View SHALL present the configuration link in a disabled or hidden state.
4. IF navigation to the leave-type configuration surface fails due to a network or server error, THEN THE Leave_Balances_View SHALL display an error message and SHALL allow the Org_User to retry the navigation manually without performing an automatic retry.

### Requirement 6: Versioned, effective-dated rule-set

**User Story:** As a product owner, I want the eligibility rules captured as a versioned, effective-dated rule-set, so that a future law change can be added without rewriting the engine.

#### Acceptance Criteria

1. THE Accrual_Engine SHALL associate every eligibility and accrual rule with a named Rule_Set_Version.
2. THE Accrual_Engine SHALL record an `effective_from` date for each Rule_Set_Version.
3. WHEN the Accrual_Engine evaluates eligibility for a given date, THE Accrual_Engine SHALL strictly select the latest effective Rule_Set_Version whose `effective_from` date is on or before the evaluation date.
4. WHERE multiple Rule_Set_Versions have an `effective_from` date on or before the evaluation date, THE Accrual_Engine SHALL strictly select the version with the latest `effective_from` date.
5. THE Accrual_Engine SHALL apply the `holidays_act_2003` Rule_Set_Version for evaluation dates on or after its effective date and before any later version's effective date.
6. WHEN a Vesting_Event is recorded, THE System SHALL record the Rule_Set_Version that produced it.

### Requirement 7: Continuous service and milestone evaluation

**User Story:** As an Org_User, I want eligibility computed from continuous service milestones, so that staff gain entitlements at the legally correct time regardless of employment type.

#### Acceptance Criteria

1. THE Accrual_Engine SHALL compute Continuous_Service for a staff member as the elapsed time from `employment_start_date` to the evaluation date.
2. THE Accrual_Engine SHALL evaluate eligibility against the Service_Milestones of day 1, 6 months, and 12 months.
3. THE Accrual_Engine SHALL NOT delay or reset Continuous_Service on account of a trial period.
4. IF a staff member has no `employment_start_date`, THEN THE Accrual_Engine SHALL immediately skip all milestone processing for that staff member without performing any partial calculation, and SHALL surface that the start date is required.
5. THE Accrual_Engine SHALL determine eligibility for statutory leave types without reference to Employment_Type, except to identify casual staff for Casual_PAYG handling.
6. THE Accrual_Engine SHALL require a staff member classified as casual to meet the same Service_Milestones, and the Hours_Test where applicable, as any other staff member before becoming eligible for a statutory leave type, and SHALL NOT grant any casual staff member day-1 statutory accrual on the basis of casual classification.

### Requirement 8: Hours test evaluation

**User Story:** As an Org_User, I want the hours test applied to sick, bereavement, and family-violence eligibility, so that part-time and casual staff qualify only when they meet the legal work threshold.

#### Acceptance Criteria

1. THE Accrual_Engine SHALL evaluate the Hours_Test as met when, over the qualifying period, a staff member has worked on average at least 10 hours per week AND at least 1 hour every week OR at least 40 hours every month.
2. WHEN the Accrual_Engine evaluates sick-leave eligibility, THE Accrual_Engine SHALL require the 6-month Service_Milestone AND the Hours_Test to be met.
3. WHEN the Accrual_Engine evaluates bereavement-leave eligibility, THE Accrual_Engine SHALL require the 6-month Service_Milestone AND the Hours_Test to be met.
4. WHEN the Accrual_Engine evaluates family-violence-leave eligibility, THE Accrual_Engine SHALL require the 6-month Service_Milestone AND the Hours_Test to be met.
5. WHERE the data needed to evaluate the Hours_Test is unavailable for a staff member, THE Accrual_Engine SHALL treat the Hours_Test as not met and SHALL record the reason in the evaluation result.

### Requirement 9: Annual holidays eligibility and vesting

**User Story:** As an Org_User, I want annual holidays to vest after 12 months of continuous service, so that staff entitlements match the Holidays Act 2003.

#### Acceptance Criteria

1. WHEN a staff member reaches the 12-month Service_Milestone, THE Accrual_Engine SHALL vest the annual-holidays entitlement of 4 weeks for that staff member.
2. WHEN the annual-holidays entitlement vests, THE Accrual_Engine SHALL append a `leave_ledger` entry with reason `accrual` recording the vested hours.
3. WHILE a staff member has not reached the 12-month Service_Milestone, THE Accrual_Engine SHALL NOT vest accruing annual holidays for that staff member.
4. THE Accrual_Engine SHALL express the 4-week annual-holidays entitlement in hours using the staff member's standard weekly hours.
5. WHERE a staff member is classified as casual, THE Accrual_Engine SHALL apply Casual_PAYG instead of accruing annual holidays.

### Requirement 10: Day-one entitlements (public holidays, alternative holidays, jury service)

**User Story:** As an Org_User, I want public holidays, alternative holidays, and jury-service protection recognised from day one, so that staff receive their day-one rights.

#### Acceptance Criteria

1. THE Accrual_Engine SHALL treat public-holiday entitlement as available from day 1 of Continuous_Service.
2. WHERE a public holiday falls on an Otherwise_Working_Day for a staff member, THE Accrual_Engine SHALL treat that public holiday as a paid entitlement for that staff member.
3. WHEN a staff member works a public holiday that is an Otherwise_Working_Day, THE Accrual_Engine SHALL recognise an Alternative_Holiday entitlement from day 1.
4. THE Accrual_Engine SHALL treat jury-service job protection as applicable from day 1 of Continuous_Service.

### Requirement 11: Casual pay-as-you-go (8%) handling

**User Story:** As an Org_User, I want casual staff handled with 8% pay-as-you-go holiday pay, so that casuals are treated per their genuinely different statutory path.

#### Acceptance Criteria

1. WHERE a staff member is classified as casual, THE System SHALL record that annual holidays are handled as Casual_PAYG at 8% of gross earnings rather than accrued.
2. WHILE a staff member is on Casual_PAYG, THE Accrual_Engine SHALL NOT vest an accruing annual-holidays balance for that staff member.
3. WHEN the Leave_Balances_View displays a casual staff member, THE Leave_Balances_View SHALL indicate that annual holidays are paid as Casual_PAYG.
4. WHERE a fixed-term staff member has an agreed term of more than 3 months and less than 12 months, THE System SHALL allow Casual_PAYG to be recorded for annual holidays only by explicit agreement.
5. WHERE a fixed-term staff member has an agreed term of 3 months or less, THE System SHALL allow Casual_PAYG to be recorded for annual holidays automatically without requiring explicit agreement.
6. THE System SHALL maintain exactly one active annual-holiday pay method for a staff member at any time, either Casual_PAYG or accrued annual holidays, and SHALL prevent the two methods from coexisting for that staff member.

### Requirement 12: Eligibility-onset notification

**User Story:** As an Org_User, I want an in-app notification when a staff member becomes newly eligible for a leave type, so that I am aware of new entitlements as they occur.

#### Acceptance Criteria

1. WHEN a Vesting_Event occurs for a staff member, THE System SHALL create an in-app notification for the relevant Org_Users.
2. WHEN the eligibility-onset notification is created, THE System SHALL include the staff member, the leave type, and the date the entitlement vested.
3. WHEN a leave type's balance vests for a staff member, THE Leave_Balances_View SHALL begin displaying that leave type's balance for that staff member.
4. IF any notification already exists for a given staff member and leave type combination, THEN THE System SHALL NOT create another eligibility-onset notification for that staff member and leave type, regardless of which Vesting_Event triggered it or when the existing notification was created.

### Requirement 13: Explanatory eligibility note

**User Story:** As an Org_User, I want an explanatory note attached when a staff member gains a leave entitlement, so that I understand why the entitlement now applies.

#### Acceptance Criteria

1. WHEN a Vesting_Event occurs, THE System SHALL attach an Eligibility_Note describing the leave type, the triggering rule, and the date.
2. WHEN an Eligibility_Note is created, THE System SHALL state the Service_Milestone or Hours_Test condition that triggered the Vesting_Event.
3. WHEN an Org_User views a staff member with a vested entitlement, THE Leave_Balances_View SHALL surface the associated Eligibility_Note.
4. THE System SHALL retain the Eligibility_Note as part of the append-only history and SHALL NOT delete it.

### Requirement 14: Termination payout rules

**User Story:** As an Org_User, I want termination payout amounts computed by the pre/post 12-month rule, so that final annual-holidays pay matches the Holidays Act 2003.

#### Acceptance Criteria

1. WHEN employment ends before the staff member reaches the 12-month Service_Milestone, THE System SHALL compute the annual-holidays Termination_Payout as 8% of gross earnings.
2. WHEN employment ends on or after the staff member reaches the 12-month Service_Milestone, THE System SHALL compute the annual-holidays Termination_Payout by multiplying the remaining accrued annual-holiday hours by the greater of ordinary weekly pay or average weekly earnings.
3. WHEN a Termination_Payout is computed, THE System SHALL record which payout rule was applied.
4. WHERE a staff member is on Casual_PAYG, THE System SHALL treat annual holidays as already paid and SHALL compute no additional accrued annual-holidays Termination_Payout.

### Requirement 15: NZ Holidays Act reference guide

**User Story:** As an Org_User, I want an in-app reference guide for the NZ Holidays Act 2003 rules, so that I can understand the leave rules without leaving the application.

#### Acceptance Criteria

1. WHERE the Staff_Management_Module is enabled, THE System SHALL provide a Reference_Guide page accessible to Org_Users.
2. THE Reference_Guide SHALL describe the eligibility rules for annual holidays, sick leave, bereavement leave, family-violence leave, public holidays, alternative holidays, and jury service.
3. THE Reference_Guide SHALL describe the Hours_Test and the Service_Milestones.
4. THE Reference_Guide SHALL state that parental leave is governed by a separate Act and is out of scope for accrual in this feature.
5. WHEN an Org_User opens the Leave_Balances_View, THE Leave_Balances_View SHALL present a link to the Reference_Guide.
6. WHERE the Reference_Guide is not yet fully populated, THE System SHALL still allow the Staff_Management_Module to be enabled.

### Requirement 16: Module gating and RBAC

**User Story:** As an organisation administrator, I want access to balances controlled by module gating and role permissions, so that only appropriate users can view all balances or adjust them.

#### Acceptance Criteria

1. THE System SHALL gate every Leave_Balances_View endpoint behind the Staff_Management_Module.
2. WHERE an Org_User holds the balance-view permission AND the Staff_Management_Module is enabled for the organisation, THE System SHALL allow that user to view all staff balances in the organisation, treating Staff_Management_Module access as a precondition in addition to the balance-view permission.
3. IF an Org_User without the balance-view permission requests the org-wide balances list, THEN THE System SHALL reject the request with HTTP 403.
4. WHERE an Org_User holds the balance-adjust permission, THE System SHALL allow that user to submit manual adjustments.
5. IF an Org_User without the balance-adjust permission attempts a manual adjustment, THEN THE System SHALL reject the request with HTTP 403.
6. WHEN the System scopes any balances or ledger query, THE System SHALL restrict results to the requesting organisation.

### Requirement 17: Future Employment Leave Bill rule-set (deferred, accommodated)

**User Story:** As a product owner, I want the future Employment Leave Bill rules accommodated as a deferred rule-set version, so that adopting the new law later is additive rather than a rewrite.

#### Acceptance Criteria

1. THE Accrual_Engine SHALL support registering an additional Rule_Set_Version with its own `effective_from` date without modifying the `holidays_act_2003` rules.
2. WHILE the evaluation date precedes the Employment Leave Bill rule-set's effective date, THE Accrual_Engine SHALL continue to apply the `holidays_act_2003` Rule_Set_Version.
3. THE Accrual_Engine SHALL represent rule parameters (milestone thresholds, accrual rates, hours-test bounds) as version-scoped configuration rather than hard-coded constants.
4. WHERE the Employment Leave Bill rule-set is not yet registered, THE Accrual_Engine SHALL operate using the `holidays_act_2003` Rule_Set_Version only.
