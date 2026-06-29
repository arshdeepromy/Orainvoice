# Requirements Document

## Introduction

This feature makes the New Zealand payroll tax rates that drive payslip calculations configurable through the GUI instead of being hard-coded in application source. Today the NZ rates (PAYE income-tax brackets, secondary tax-code flat rates, ACC earner levy, student-loan rate and threshold, IETC parameters, and default KiwiSaver rates) live as module constants in `app/modules/timesheets/paye.py`. When Inland Revenue (IRD) changes a rate, a developer must edit code and deploy. The goal is to remove that dependency on developer/deploy cycles entirely.

The solution introduces a **two-tier, fully GUI-editable tax configuration model**:

1. **Platform tax defaults** — a single global baseline tax configuration, editable by a Global Admin in the Global Admin GUI (the same area used for integration credentials). It is seeded once from the current hard-coded rates by a database migration. When IRD changes a rate, a Global Admin edits the platform default in the UI; no code change or deploy is required.

2. **Per-organisation tax settings** — each organisation either inherits the platform default (the default behaviour) or overrides specific values. Organisation admins reach these settings from a Settings control on the Payroll page, mirroring the existing Timesheets Settings pattern.

At payslip time the effective value of each setting is **resolved by precedence**: an organisation override wins over the platform default, which wins over a hard-coded safety net. The safety net guarantees that payroll never computes against a blank, zero, or missing value even if both the override and the platform default are absent. Defaults always win over blanks: a missing override falls through to the platform default rather than being treated as zero.

Every change to platform or organisation tax settings is recorded in the audit log. Validation blocks nonsensical values (for example, PAYE brackets that are not strictly ascending, rates outside sane bounds, or an ACC cap that is not positive) before they can be saved.

Effective-dating (storing past and future-dated rate sets and selecting by pay-period date) is explicitly **out of scope** for this iteration. Only the current settings are stored and edited in place, with an audit history of changes. Effective-dating is noted as a possible future enhancement.

## Glossary

- **Payroll_Tax_Settings**: The new capability that stores, validates, resolves, and exposes NZ payroll tax configuration through the GUI. Backend routes are mounted under `/api/v2`.
- **Platform_Tax_Default**: The single, global baseline tax configuration record, editable only by a Global_Admin. Exactly one Platform_Tax_Default exists for the platform.
- **Org_Tax_Settings**: A per-organisation tax configuration record. It is org-scoped and may inherit the Platform_Tax_Default or override individual fields.
- **Resolved_Tax_Config**: The fully populated set of tax values used for a single payslip computation, produced by resolving each field through the Resolution_Precedence.
- **Resolution_Precedence**: The ordered rule for choosing a value for each tax field: Org_Tax_Settings override, then Platform_Tax_Default, then Safety_Net.
- **Safety_Net**: The hard-coded fallback values (the current 2024/25 constants) used when neither an Org_Tax_Settings override nor a Platform_Tax_Default value is available for a field.
- **PAYE_Bracket**: One progressive income-tax band, expressed as an `upper_limit` (annual income ceiling) and a `rate` (marginal tax rate). The top band has an open-ended (infinite) `upper_limit`.
- **PAYE_Bracket_Set**: The ordered list of PAYE_Brackets that defines the progressive income-tax schedule.
- **Secondary_Tax_Rate**: The flat annual tax rate applied to a secondary tax code. The supported secondary codes are SB, S, SH, ST, and SA.
- **ACC_Levy_Rate**: The ACC earner levy rate applied to liable earnings.
- **ACC_Max_Liable_Earnings**: The maximum annual earnings on which the ACC earner levy is charged (the ACC cap).
- **Student_Loan_Rate**: The student-loan repayment rate applied to earnings above the Student_Loan_Threshold.
- **Student_Loan_Threshold**: The annual income threshold above which student-loan repayments apply.
- **IETC_Parameters**: The Independent Earner Tax Credit parameters for the ME tax code: credit amount, lower bound, abatement start, abatement rate, and upper bound.
- **Default_KiwiSaver_Employee_Rate**: The KiwiSaver employee contribution rate used when a staff profile does not specify one.
- **Default_KiwiSaver_Employer_Rate**: The KiwiSaver employer contribution rate used when a staff profile does not specify one.
- **Tax_Year_Label**: A human-readable label identifying the tax year a configuration represents, for example "2024/25". It is for display only and does not affect calculations.
- **PAYE_Engine**: The payslip calculation engine (`compute_paye` in `app/modules/timesheets/paye.py`) that computes PAYE, ACC levy, student loan, and KiwiSaver for a pay period.
- **Global_Admin**: A platform-level administrator who manages the Platform_Tax_Default.
- **Org_Admin**: An organisation-level administrator (role `org_admin`) who manages that organisation's Org_Tax_Settings.
- **Audit_Log**: The existing org-scoped audit logging facility used to record configuration changes.
- **Seed_Migration**: The Alembic migration that creates the Platform_Tax_Default record once, populated from the current hard-coded 2024/25 constants.
- **Tax_Field**: Any single configurable value within a tax configuration (for example ACC_Levy_Rate, or one PAYE_Bracket_Set).

## Requirements

### Requirement 1: Platform Tax Default exists and is seeded

**User Story:** As a Global_Admin, I want a single platform-wide baseline tax configuration seeded from the current rates, so that the platform has correct NZ tax values from day one without any code constants being authoritative.

#### Acceptance Criteria

1. THE Payroll_Tax_Settings SHALL maintain exactly one Platform_Tax_Default record for the platform.
2. WHEN the Seed_Migration runs, THE Payroll_Tax_Settings SHALL create the Platform_Tax_Default populated with the current 2024/25 values: PAYE_Bracket_Set of (15600, 0.105), (53500, 0.175), (78100, 0.30), (180000, 0.33), and an open-ended top band at 0.39; Secondary_Tax_Rate values SB=0.105, S=0.175, SH=0.30, ST=0.33, SA=0.39; ACC_Levy_Rate=0.016; ACC_Max_Liable_Earnings=142283; Student_Loan_Rate=0.12; Student_Loan_Threshold=24128; IETC_Parameters amount=520, lower=24000, abatement start=44000, abatement rate=0.13, upper=48000; Default_KiwiSaver_Employee_Rate=3.00; Default_KiwiSaver_Employer_Rate=3.00; and Tax_Year_Label="2024/25".
3. IF the Seed_Migration is run when a Platform_Tax_Default record already exists, THEN THE Payroll_Tax_Settings SHALL leave the existing Platform_Tax_Default unchanged.
4. WHERE no Platform_Tax_Default value is stored for a Tax_Field at resolution time, THE Payroll_Tax_Settings SHALL use the Safety_Net value for that Tax_Field.

### Requirement 2: Global Admin edits the Platform Tax Default

**User Story:** As a Global_Admin, I want to edit every platform tax value in the Global Admin GUI, so that I can apply IRD rate changes without a developer code change or deployment.

#### Acceptance Criteria

1. THE Payroll_Tax_Settings SHALL expose, in the Global Admin GUI, an editable view of the Platform_Tax_Default containing the PAYE_Bracket_Set, all Secondary_Tax_Rate values, ACC_Levy_Rate, ACC_Max_Liable_Earnings, Student_Loan_Rate, Student_Loan_Threshold, IETC_Parameters, Default_KiwiSaver_Employee_Rate, Default_KiwiSaver_Employer_Rate, and Tax_Year_Label.
2. WHEN a Global_Admin submits a valid change to the Platform_Tax_Default, THE Payroll_Tax_Settings SHALL persist the updated values to the Platform_Tax_Default record.
3. IF a user who is not a Global_Admin requests to view or modify the Platform_Tax_Default, THEN THE Payroll_Tax_Settings SHALL reject the request with an authorisation error AND SHALL record the rejected attempt in the Audit_Log for security monitoring.
4. WHEN a Global_Admin saves a change to the Platform_Tax_Default, THE Payroll_Tax_Settings SHALL record an Audit_Log entry identifying the acting Global_Admin, the changed Tax_Fields, the prior values, and the new values.
5. WHEN a Global_Admin updates the Platform_Tax_Default, THE Payroll_Tax_Settings SHALL apply the updated values to subsequent payslip computations for every organisation that has not overridden the corresponding Tax_Field.

### Requirement 3: Organisation inherits or overrides tax settings

**User Story:** As an Org_Admin, I want my organisation to inherit the platform tax defaults by default and override only the specific values I need, so that I am not forced to maintain a full tax table and I am protected when IRD rates change centrally.

#### Acceptance Criteria

1. WHERE an organisation has no Org_Tax_Settings override for a Tax_Field, THE Payroll_Tax_Settings SHALL use the Platform_Tax_Default value for that Tax_Field when resolving that organisation's Resolved_Tax_Config.
2. WHEN an Org_Admin sets an override for a Tax_Field, THE Payroll_Tax_Settings SHALL persist the override against that Org_Admin's organisation.
3. WHEN an Org_Admin sets an override for a Tax_Field, THE Payroll_Tax_Settings SHALL use the override value for that Tax_Field when resolving that organisation's Resolved_Tax_Config.
4. THE Payroll_Tax_Settings SHALL scope each Org_Tax_Settings record to a single organisation so that one organisation's overrides do not affect any other organisation.
5. IF a user who is not an Org_Admin of the organisation requests to view or modify that organisation's Org_Tax_Settings, THEN THE Payroll_Tax_Settings SHALL reject the request with an authorisation error AND SHALL record the rejected attempt in the Audit_Log for security monitoring.

### Requirement 4: Payroll Settings entry point on the Payroll page

**User Story:** As an Org_Admin, I want a Settings control on the Payroll page like the one on the Timesheets page, so that I can reach my organisation's tax settings from where I run payroll.

#### Acceptance Criteria

1. WHERE the requesting user is an Org_Admin, THE Payroll_Tax_Settings SHALL present a Settings control on the Payroll page that opens that organisation's Org_Tax_Settings view.
2. WHERE the requesting user is not an Org_Admin, THE Payroll_Tax_Settings SHALL omit the Payroll-page Settings control.
3. WHEN an Org_Admin opens the Org_Tax_Settings view, THE Payroll_Tax_Settings SHALL display, for each Tax_Field, the value currently in effect for that organisation and whether that value is inherited from the Platform_Tax_Default or set as an organisation override.

### Requirement 5: Resolution precedence at payslip time

**User Story:** As an Org_Admin running payroll, I want each tax value resolved as override, then platform default, then safety net, so that payslips always use the most specific configured value and never a blank or wrong value.

#### Acceptance Criteria

1. WHEN the PAYE_Engine computes a payslip for an organisation, THE Payroll_Tax_Settings SHALL provide a Resolved_Tax_Config in which each Tax_Field is taken from the Org_Tax_Settings override when present, otherwise the Platform_Tax_Default value when present, otherwise the Safety_Net value.
2. WHILE an organisation has no override for a Tax_Field, THE Payroll_Tax_Settings SHALL resolve that Tax_Field to the Platform_Tax_Default value rather than to zero or blank.
3. IF a Tax_Field has neither an Org_Tax_Settings override nor a Platform_Tax_Default value, THEN THE Payroll_Tax_Settings SHALL resolve that Tax_Field to the Safety_Net value.
4. THE Payroll_Tax_Settings SHALL resolve every Tax_Field in the Resolved_Tax_Config to a populated value before the PAYE_Engine performs any calculation.

### Requirement 6: PAYE engine reads the resolved configuration

**User Story:** As an Org_Admin, I want the payslip engine to compute PAYE, ACC, student loan, IETC, and KiwiSaver from the resolved tax configuration, so that the values I (or the Global_Admin) configure actually drive the numbers on payslips.

#### Acceptance Criteria

1. WHEN the PAYE_Engine computes income tax for a primary tax code, THE PAYE_Engine SHALL apply the PAYE_Bracket_Set from the Resolved_Tax_Config.
2. WHEN the PAYE_Engine computes income tax for a secondary tax code, THE PAYE_Engine SHALL apply the Secondary_Tax_Rate for that code from the Resolved_Tax_Config.
3. WHEN the PAYE_Engine computes the ACC earner levy, THE PAYE_Engine SHALL apply the ACC_Levy_Rate and ACC_Max_Liable_Earnings from the Resolved_Tax_Config.
4. WHEN the PAYE_Engine computes a student-loan repayment, THE PAYE_Engine SHALL apply the Student_Loan_Rate and Student_Loan_Threshold from the Resolved_Tax_Config.
5. WHEN the PAYE_Engine computes the IETC for the ME tax code, THE PAYE_Engine SHALL apply the IETC_Parameters from the Resolved_Tax_Config.
6. WHERE a staff profile does not specify a KiwiSaver employee rate, THE PAYE_Engine SHALL apply the Default_KiwiSaver_Employee_Rate from the Resolved_Tax_Config.
7. WHERE a staff profile does not specify a KiwiSaver employer rate, THE PAYE_Engine SHALL apply the Default_KiwiSaver_Employer_Rate from the Resolved_Tax_Config.

### Requirement 7: PAYE bracket validation

**User Story:** As an Org_Admin or Global_Admin, I want PAYE brackets validated before they are saved, so that an invalid schedule cannot corrupt payroll calculations.

#### Acceptance Criteria

1. IF a submitted PAYE_Bracket_Set has `upper_limit` values that are not strictly ascending across the finite bands, THEN THE Payroll_Tax_Settings SHALL reject the submission with a validation error and SHALL NOT persist the change.
2. IF a submitted PAYE_Bracket_Set does not end with an open-ended top band, THEN THE Payroll_Tax_Settings SHALL reject the submission with a validation error and SHALL NOT persist the change.
3. IF any PAYE_Bracket in a submitted PAYE_Bracket_Set has a `rate` outside the range 0 to 1 inclusive, THEN THE Payroll_Tax_Settings SHALL reject the submission with a validation error and SHALL NOT persist the change.
4. IF a submitted PAYE_Bracket_Set contains fewer than one band, THEN THE Payroll_Tax_Settings SHALL reject the submission with a validation error and SHALL NOT persist the change.
5. IF any finite PAYE_Bracket `upper_limit` in a submitted PAYE_Bracket_Set is not greater than zero, THEN THE Payroll_Tax_Settings SHALL reject the submission with a validation error and SHALL NOT persist the change.

### Requirement 8: Rate, cap, and threshold validation

**User Story:** As an Org_Admin or Global_Admin, I want rates, caps, and thresholds validated against sane bounds, so that nonsensical values such as a negative cap or a 500% rate cannot be saved.

#### Acceptance Criteria

1. IF a submitted ACC_Levy_Rate, Student_Loan_Rate, Secondary_Tax_Rate, IETC abatement rate, Default_KiwiSaver_Employee_Rate, or Default_KiwiSaver_Employer_Rate is outside its permitted bounds, THEN THE Payroll_Tax_Settings SHALL reject the submission with a validation error and SHALL NOT persist the change.
2. IF a submitted ACC_Max_Liable_Earnings is not greater than zero, THEN THE Payroll_Tax_Settings SHALL reject the submission with a validation error and SHALL NOT persist the change.
3. IF a submitted Student_Loan_Threshold is less than zero, THEN THE Payroll_Tax_Settings SHALL reject the submission with a validation error and SHALL NOT persist the change.
4. IF a submitted set of IETC_Parameters has a lower bound, abatement start, and upper bound that are not in non-decreasing order, THEN THE Payroll_Tax_Settings SHALL reject the submission with a validation error and SHALL NOT persist the change.
5. IF a submission omits a required Secondary_Tax_Rate for any of the codes SB, S, SH, ST, or SA when overriding the secondary rate set, THEN THE Payroll_Tax_Settings SHALL reject the submission with a validation error and SHALL NOT persist the change.
6. WHEN a validation error is returned, THE Payroll_Tax_Settings SHALL include a human-readable message identifying the Tax_Field that failed validation.
7. IF generation of the human-readable validation message fails, THEN THE Payroll_Tax_Settings SHALL still reject the invalid submission and SHALL NOT persist the change.

### Requirement 9: Reset to default actions

**User Story:** As an Org_Admin, I want to reset an overridden tax value back to inheriting the platform default, so that I can undo an override without knowing the underlying numbers.

#### Acceptance Criteria

1. WHEN an Org_Admin resets a Tax_Field to default, THE Payroll_Tax_Settings SHALL remove that organisation's override for that Tax_Field so that the field resolves to the Platform_Tax_Default.
2. WHEN an Org_Admin resets all Tax_Fields to default, THE Payroll_Tax_Settings SHALL remove every override for that organisation so that all fields resolve to the Platform_Tax_Default.
3. WHEN an Org_Admin resets a Tax_Field to default, THE Payroll_Tax_Settings SHALL record an Audit_Log entry identifying the acting Org_Admin, the reset Tax_Field, and the prior override value.
4. WHEN an Org_Admin views a Tax_Field after resetting it to default, THE Payroll_Tax_Settings SHALL display the Platform_Tax_Default value marked as inherited.

### Requirement 10: Audit of configuration changes

**User Story:** As an administrator, I want every tax configuration change recorded, so that there is a traceable history of who changed which rate and when, given effective-dating is not yet available.

#### Acceptance Criteria

1. WHEN an Org_Admin saves an override to an Org_Tax_Settings Tax_Field, THE Payroll_Tax_Settings SHALL record an Audit_Log entry identifying the acting Org_Admin, the organisation, the Tax_Field, the prior value, and the new value.
2. WHEN a Global_Admin saves a change to the Platform_Tax_Default, THE Payroll_Tax_Settings SHALL record an Audit_Log entry identifying the acting Global_Admin, the Tax_Field, the prior value, and the new value.
3. THE Payroll_Tax_Settings SHALL retain the recorded Audit_Log entries as the change history for tax configuration.

### Requirement 11: Payroll correctness is never blank or wrong

**User Story:** As an Org_Admin, I want payroll to always compute against valid tax values, so that payslips are never produced with blank, zero, or incorrect statutory figures even if configuration is missing.

#### Acceptance Criteria

1. WHEN the PAYE_Engine computes a payslip, THE Payroll_Tax_Settings SHALL provide a non-blank, non-null value for every Tax_Field in the Resolved_Tax_Config.
2. IF both the Org_Tax_Settings override and the Platform_Tax_Default are missing for every Tax_Field, THEN THE Payroll_Tax_Settings SHALL produce a Resolved_Tax_Config equal to the Safety_Net values.
3. WHEN a Tax_Field has no override and no Platform_Tax_Default value, THE Payroll_Tax_Settings SHALL resolve that Tax_Field to its Safety_Net value rather than to zero.
4. THE Payroll_Tax_Settings SHALL ensure that the Resolved_Tax_Config used for any payslip is identical to the result of applying the Resolution_Precedence to the stored configuration at computation time.

### Requirement 12: Effective-dating out of scope

**User Story:** As a product stakeholder, I want the current iteration limited to current settings only, so that the feature ships without the complexity of date-based rate selection while leaving room for it later.

#### Acceptance Criteria

1. THE Payroll_Tax_Settings SHALL store and edit only the current Platform_Tax_Default and current Org_Tax_Settings, without date-based selection of rate sets.
2. WHEN the PAYE_Engine resolves a Resolved_Tax_Config, THE Payroll_Tax_Settings SHALL use the current stored configuration regardless of the pay-period dates.
