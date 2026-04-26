# Requirements Document

## Introduction

The Setup Guide is a frontend-heavy onboarding experience that presents users with friendly, question-based prompts for each optional module available on their subscription plan. Instead of showing raw module toggles (the current Step 5 of the setup wizard), users answer plain-language questions like "Would you be sending quotes to your customers?" — answering "Yes" enables the module, answering "No" leaves it disabled.

The backend work is minimal: add `setup_question` and `setup_question_description` columns to the existing `module_registry` table, seed the questions, and expose two thin endpoints (GET questions, POST answers). The POST endpoint simply loops through answers and calls the existing `ModuleService.enable_module()` / `ModuleService.force_disable_module()` — no new service class or completion tracking table is needed. Completion is tracked via the existing `setup_wizard_progress.step_5_complete` flag, and re-run eligibility is determined by checking `org_modules.is_enabled = false`.

Core modules (invoicing, customers, notifications) and trade-family-gated modules (vehicles) are excluded — they are always enabled or auto-enabled respectively. The guide can be re-run later from Settings to enable previously skipped modules.

## Glossary

- **Setup_Guide**: The question-driven onboarding flow that replaces the technical module toggle step in the existing setup wizard.
- **Module_Registry**: The `module_registry` database table that stores metadata for all available modules, including slug, display name, description, category, and core status.
- **Org_Module**: The `org_modules` database table that tracks per-organisation module enablement state (`is_enabled` boolean).
- **Subscription_Plan**: The `subscription_plans` database table that defines which modules are available per plan via the `enabled_modules` JSONB array.
- **ModuleService**: The existing backend service (`app/core/modules.py`) that manages module enablement, disablement, dependency resolution, and Redis cache invalidation.
- **SetupWizardProgress**: The existing `setup_wizard_progress` table that tracks which wizard steps an organisation has completed, including `step_5_complete`.
- **Core_Module**: A module with `is_core = true` in the Module_Registry (invoicing, customers, notifications). Core modules are always enabled and require no setup question.
- **Trade_Gated_Module**: A module that is auto-enabled based on the organisation's trade family (e.g., vehicles for automotive). Trade-gated modules require no setup question.
- **Setup_Question**: A user-friendly question string stored in the Module_Registry that is presented during the Setup_Guide to determine whether a module should be enabled.
- **Welcome_Screen**: The introductory screen shown before any setup questions, explaining the purpose of the guide.
- **Summary_Screen**: The final screen shown after all questions, displaying the user's choices before confirmation.
- **Question_Card**: A rounded-corner card UI component that presents a single module's setup question with Yes/No selection.

## Requirements

### Requirement 1: Setup Question Metadata on Module Registry

**User Story:** As a platform administrator, I want each module to have a user-friendly setup question stored in its registry entry, so that the setup guide can dynamically generate questions without hardcoding.

#### Acceptance Criteria

1. THE Module_Registry SHALL include a `setup_question` text field for storing a user-friendly question per module.
2. THE Module_Registry SHALL include a `setup_question_description` text field for storing an optional explanatory sentence shown below the question.
3. WHEN a module has `is_core` set to true, THE Setup_Guide SHALL exclude that module from the question list regardless of whether a `setup_question` is defined.
4. WHEN a module has `trade_family_gated` set to true in the Module_Registry, THE Setup_Guide SHALL exclude that module from the question list.
5. WHEN a new module is added to the Module_Registry with a non-null `setup_question`, THE Setup_Guide SHALL automatically include that module in future runs without code changes.

### Requirement 2: Setup Guide Questions Endpoint

**User Story:** As a frontend developer, I want a single GET endpoint that returns the list of eligible setup questions for the current organisation, so that the frontend can render the question flow dynamically.

#### Acceptance Criteria

1. WHEN a request is made to the setup guide questions endpoint, THE Setup_Guide SHALL return only modules where all of the following are true: the module is in the organisation's Subscription_Plan `enabled_modules` list (or plan has "all"), the module has `is_core` set to false, the module has `trade_family_gated` set to false, and the module has a non-null `setup_question`.
2. WHEN the `rerun` query parameter is set to true, THE Setup_Guide SHALL additionally filter to only modules where `org_modules.is_enabled` is false for the organisation.
3. THE Setup_Guide SHALL return each module's slug, display_name, setup_question, setup_question_description, category, and dependencies in the response.
4. THE Setup_Guide SHALL order the returned modules so that dependency prerequisites appear before modules that depend on them.
5. IF the organisation has no modules matching the eligibility criteria, THEN THE Setup_Guide SHALL return an empty list.

### Requirement 3: Setup Guide Submission Endpoint

**User Story:** As a frontend developer, I want a POST endpoint that accepts the user's yes/no answers and calls the existing ModuleService to enable or disable modules, so that the setup guide choices take effect immediately.

#### Acceptance Criteria

1. WHEN the user submits their setup guide answers, THE Setup_Guide SHALL accept a list of objects each containing a module slug and a boolean `enabled` value.
2. WHEN a module answer has `enabled` set to true, THE Setup_Guide SHALL call the existing ModuleService `enable_module` for that module, which auto-enables transitive dependencies.
3. WHEN a module answer has `enabled` set to false, THE Setup_Guide SHALL call the existing ModuleService `force_disable_module` for that module.
4. THE Setup_Guide SHALL rely on the existing ModuleService to handle dependency resolution and Redis cache invalidation.
5. WHEN the setup guide is completed for the first time, THE Setup_Guide SHALL set `step_5_complete` to true on the existing SetupWizardProgress record for the organisation.
6. IF a module slug in the submission does not exist in the Module_Registry, THEN THE Setup_Guide SHALL return a 400 error with a descriptive message identifying the invalid slug.

### Requirement 4: Wizard Integration

**User Story:** As a user, I want the setup wizard to use the setup guide for Step 5 instead of the raw module toggles, so that I get the friendly question-based experience during onboarding.

#### Acceptance Criteria

1. WHEN a user navigates to the setup wizard and reaches Step 5 (Module Selection), THE Setup_Guide SHALL redirect the user to the setup guide page.
2. WHEN `step_5_complete` is already true on the SetupWizardProgress record, THE Setup_Guide SHALL skip Step 5 and proceed to Step 6.

### Requirement 5: Welcome Screen

**User Story:** As a first-time user, I want to see a welcome message before the setup questions begin, so that I understand why the setup guide exists and that I can change my answers later.

#### Acceptance Criteria

1. WHEN the Setup_Guide is launched for the first time, THE Setup_Guide SHALL display a Welcome_Screen before any Question_Cards.
2. THE Welcome_Screen SHALL display a heading that welcomes the user to the platform.
3. THE Welcome_Screen SHALL display a message explaining that the setup guide tailors the experience to the user's business needs.
4. THE Welcome_Screen SHALL display a message informing the user that modules skipped during setup can be enabled later from Settings.
5. THE Welcome_Screen SHALL display a "Get Started" button that advances to the first Question_Card.
6. WHEN the Setup_Guide is re-run, THE Welcome_Screen SHALL display a message explaining that only previously skipped modules are shown.

### Requirement 6: Question Card UI

**User Story:** As a user, I want each module question presented as a clean, modern card with a clear yes/no choice, so that I can quickly decide which modules to enable.

#### Acceptance Criteria

1. THE Setup_Guide SHALL display one Question_Card per eligible module.
2. EACH Question_Card SHALL display the module's `setup_question` text as the primary heading.
3. EACH Question_Card SHALL display the module's `setup_question_description` text below the heading when the description is not null.
4. EACH Question_Card SHALL provide a "Yes" selection and a "No" selection for the user to choose from.
5. THE Question_Card SHALL use rounded corners with a minimum border radius of 12 pixels.
6. THE Question_Card SHALL visually highlight the selected option (Yes or No) with a distinct colour.
7. WHEN the user selects "Yes" or "No" on a Question_Card, THE Setup_Guide SHALL automatically advance to the next Question_Card after a brief transition.
8. THE Setup_Guide SHALL display a progress indicator showing the current question number out of the total number of questions.
9. THE Setup_Guide SHALL allow the user to navigate back to a previous Question_Card to change their answer.

### Requirement 7: Summary and Confirmation Screen

**User Story:** As a user, I want to review all my choices before they are applied, so that I can correct any mistakes before modules are enabled or disabled.

#### Acceptance Criteria

1. WHEN the user has answered all questions, THE Setup_Guide SHALL display a Summary_Screen listing all modules with their chosen status (enabled or skipped).
2. THE Summary_Screen SHALL group modules by category for readability.
3. THE Summary_Screen SHALL visually distinguish enabled modules from skipped modules using colour or iconography.
4. THE Summary_Screen SHALL display a "Confirm" button that submits all answers to the backend.
5. THE Summary_Screen SHALL display a "Go Back" button that returns the user to the last Question_Card.
6. WHEN the user clicks "Confirm", THE Setup_Guide SHALL submit all answers to the setup guide submission endpoint and display a success state upon completion.
7. IF the submission fails, THEN THE Setup_Guide SHALL display an error message and allow the user to retry.

### Requirement 8: Re-run Capability

**User Story:** As a user, I want to re-run the setup guide from the settings page to enable modules I previously skipped, so that I can expand my feature set without contacting support.

#### Acceptance Criteria

1. THE Setup_Guide SHALL be accessible from the organisation settings page via a "Setup Guide" button or link.
2. WHEN the Setup_Guide is re-run, THE Setup_Guide SHALL fetch modules with the `rerun` parameter set to true, showing only modules where `org_modules.is_enabled` is false.
3. WHEN the re-run Setup_Guide has no modules to show (all eligible modules are already enabled), THE Setup_Guide SHALL display a message indicating all available modules are already enabled.
4. WHEN the user completes the re-run, THE Setup_Guide SHALL call the existing ModuleService to update the Org_Module records for any newly enabled modules.
5. THE Setup_Guide SHALL refresh the frontend ModuleContext after successful submission so that newly enabled modules appear in the sidebar and throughout the application immediately.

### Requirement 9: Dependency Awareness in Question Flow

**User Story:** As a user, I want the setup guide to handle module dependencies transparently, so that I do not accidentally enable a module without its prerequisites.

#### Acceptance Criteria

1. WHEN a module depends on another module that the user answered "no" to, THE Setup_Guide SHALL display an informational message on the dependent module's Question_Card indicating the prerequisite.
2. WHEN the user selects "Yes" for a module with unanswered dependencies, THE Setup_Guide SHALL rely on the existing ModuleService dependency resolution to auto-enable the dependency modules, and inform the user which additional modules were enabled.
3. THE Setup_Guide SHALL order questions so that prerequisite modules appear before their dependents in the question flow.

### Requirement 10: Steering Documentation for Future Module Developers

**User Story:** As a developer adding a new module to the platform, I want a steering document that explains how to add a setup guide question for the new module, so that the setup guide stays current as the platform grows.

#### Acceptance Criteria

1. THE Setup_Guide SHALL include a steering document at `.kiro/steering/setup-guide-for-new-modules.md` with instructions for adding setup questions when creating new modules.
2. THE steering document SHALL specify that every new non-core, non-trade-gated module must include a `setup_question` value in its Module_Registry migration.
3. THE steering document SHALL provide a template for the `setup_question` and `setup_question_description` fields.
4. THE steering document SHALL list the fields that must be populated in the Module_Registry for the Setup_Guide to include the module automatically.
5. THE steering document SHALL use the `inclusion: auto` front matter so it is loaded for all interactions.
