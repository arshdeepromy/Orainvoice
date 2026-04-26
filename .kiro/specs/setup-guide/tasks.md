# Implementation Plan: Setup Guide

## Overview

Replace the technical module toggle step (Step 5) in the existing setup wizard with a friendly, question-driven onboarding flow. Users answer plain-language questions to enable or skip optional modules. Minimal backend (2 columns + seed data, 2 endpoints, no new tables, no service class), frontend-heavy (state machine page + 3 components).

## Tasks

- [x] 1. Database migration and model update
  - [x] 1.1 Create Alembic migration to add columns and seed questions
    - Add `setup_question TEXT NULL` and `setup_question_description TEXT NULL` columns to `module_registry` table
    - Seed `setup_question` and `setup_question_description` values for all 23 non-core modules listed in the design's seed data table
    - Use `down_revision = '0150'` (current head)
    - _Requirements: 1.1, 1.2, 1.5_

  - [x] 1.2 Update `ModuleRegistry` model in `app/modules/module_management/models.py`
    - Add `setup_question: Mapped[str | None] = mapped_column(Text, nullable=True)` and `setup_question_description: Mapped[str | None] = mapped_column(Text, nullable=True)`
    - _Requirements: 1.1, 1.2_

- [x] 2. Backend schemas and router
  - [x] 2.1 Create Pydantic schemas in `app/modules/setup_guide/schemas.py`
    - Create `app/modules/setup_guide/__init__.py` (empty)
    - Define `SetupGuideQuestion`, `SetupGuideQuestionsResponse`, `SetupGuideAnswer`, `SetupGuideSubmitRequest`, `SetupGuideSubmitResponse` as specified in the design
    - _Requirements: 2.3, 3.1_

  - [x] 2.2 Create router in `app/modules/setup_guide/router.py`
    - Define `TRADE_GATED_MODULES: set[str] = {"vehicles"}` constant in the router
    - Implement `GET /questions` endpoint: query `module_registry` for modules with `setup_question IS NOT NULL` and `is_core = false`, filter out `TRADE_GATED_MODULES`, filter to modules in org's subscription plan, if `rerun=true` additionally filter to `org_modules.is_enabled = false`, sort by topological order using `DEPENDENCY_GRAPH` from `app/core/modules.py`, return `SetupGuideQuestionsResponse`
    - Implement `POST /submit` endpoint: validate all slugs exist in `module_registry` (return 400 for invalid), call `ModuleService.enable_module()` for `enabled=true` answers, call `ModuleService.force_disable_module()` for `enabled=false` answers, set `step_5_complete = true` on `setup_wizard_progress` (upsert), `db.flush()`, return `SetupGuideSubmitResponse` with auto-enabled deps list
    - All endpoints require authentication and org context (use `get_db_session` and `require_role` dependencies matching setup wizard pattern)
    - No service class — logic lives directly in route handlers per design decision
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 9.3_

  - [x] 2.3 Write property test for module filtering (Property 1)
    - **Property 1: Module filtering returns only eligible modules**
    - Use Hypothesis to generate random sets of modules with varying `is_core`, `setup_question`, plan membership, and trade-gated status
    - Assert returned modules satisfy all four eligibility conditions and every eligible module appears
    - **Validates: Requirements 1.3, 1.4, 1.5, 2.1, 2.5**

  - [x] 2.4 Write property test for rerun filtering (Property 2)
    - **Property 2: Rerun filtering returns only previously-skipped modules**
    - Use Hypothesis to generate org_modules records with varying `is_enabled` states
    - Assert rerun mode returns only base-eligible modules with `is_enabled = false`
    - **Validates: Requirements 2.2, 8.2**

  - [x] 2.5 Write property test for topological ordering (Property 3)
    - **Property 3: Topological ordering of questions**
    - Use Hypothesis to generate dependency graphs and module sets
    - Assert that for every pair (A depends on B), B appears before A in the result
    - **Validates: Requirements 2.4, 9.3**

  - [x] 2.6 Write property test for answer dispatch (Property 4)
    - **Property 4: Answer dispatch correctness**
    - Use Hypothesis to generate lists of valid answers
    - Mock `ModuleService.enable_module` and `force_disable_module`, assert each is called exactly once per corresponding answer
    - **Validates: Requirements 3.2, 3.3, 8.4**

  - [x] 2.7 Write property test for Step 5 completion (Property 5)
    - **Property 5: First-run marks wizard Step 5 complete**
    - Use Hypothesis to generate first-run submissions
    - Assert `setup_wizard_progress.step_5_complete = true` after submission
    - **Validates: Requirements 3.5**

  - [x] 2.8 Write property test for invalid slug rejection (Property 6)
    - **Property 6: Invalid slug rejection**
    - Use Hypothesis to generate submissions with at least one non-existent slug
    - Assert 400 status code with message identifying the invalid slug
    - **Validates: Requirements 3.6**

  - [x] 2.9 Register router in `app/main.py`
    - Import `setup_guide_router` from `app.modules.setup_guide.router`
    - Register with `app.include_router(setup_guide_router, prefix="/api/v2/setup-guide", tags=["v2-setup-guide"])`
    - _Requirements: 2.1_

- [x] 3. Checkpoint — Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Frontend components
  - [x] 4.1 Create `WelcomeScreen` component at `frontend/src/pages/setup-guide/WelcomeScreen.tsx`
    - Accept props: `{ isRerun: boolean, onStart: () => void }`
    - First-run: "Welcome to OraInvoice" heading, explanation text about tailoring the experience, note that skipped modules can be enabled later from Settings, "Get Started" button
    - Re-run: "Enable More Modules" heading, explain only previously skipped modules are shown
    - Use Tailwind CSS, rounded card styling consistent with the app
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 4.2 Create `QuestionCard` component at `frontend/src/pages/setup-guide/QuestionCard.tsx`
    - Accept props: `{ question, currentIndex, totalQuestions, selectedAnswer, onAnswer, onBack, dependencyWarning }`
    - Display `setup_question` as heading, `setup_question_description` below when non-null
    - Yes/No buttons with highlight on selection (green for Yes, gray for No)
    - Auto-advance after 400ms delay on selection
    - Progress indicator: "Question X of Y" with visual progress bar
    - Back button (disabled on first question)
    - Dependency info message when `dependencyWarning` is non-null
    - Use `rounded-xl` (12px+ border radius)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 9.1_

  - [x] 4.3 Create `SummaryScreen` component at `frontend/src/pages/setup-guide/SummaryScreen.tsx`
    - Accept props: `{ questions, answers, autoEnabled, onConfirm, onGoBack, isSubmitting, error }`
    - Group modules by `category`
    - Show enabled modules with green check icon, skipped with gray dash
    - Show auto-enabled dependencies with info badge
    - "Confirm" button (primary, shows spinner when submitting)
    - "Go Back" button (secondary)
    - Error message with retry on submission failure
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [x] 4.4 Create `SetupGuide` page at `frontend/src/pages/setup-guide/SetupGuide.tsx`
    - Manage state machine: `loading → welcome → questions → summary → submitting → success`
    - Fetch questions from `GET /api/v2/setup-guide/questions` using `apiClient.get('/setup-guide/questions', { baseURL: '/api/v2' })` with `rerun` param from URL query string
    - Manage `answers: Record<string, boolean>` state and `currentIndex` for navigation
    - Compute dependency warnings: if a module depends on another that was answered "no", show warning text
    - Handle submission via `POST /api/v2/setup-guide/submit`
    - Call `useModules().refetch()` after successful submission to refresh sidebar
    - Handle empty questions list for rerun (show "all modules already enabled" message)
    - Use `?.` and `?? []` / `?? 0` on all API data per safe-api-consumption steering
    - Add `AbortController` cleanup in `useEffect` for API calls
    - Render `WelcomeScreen`, `QuestionCard`, or `SummaryScreen` based on current state
    - _Requirements: 2.1, 3.1, 5.1, 6.1, 7.1, 8.3, 8.5, 9.1, 9.2_

  - [x] 4.5 Write unit tests for frontend components
    - Test QuestionCard renders `setup_question` as heading, shows/hides description based on null
    - Test progress indicator shows correct "X of Y" values
    - Test SummaryScreen lists every module with matching enabled/skipped status
    - Test SummaryScreen groups modules by category
    - Test dependency warning message appears on QuestionCard when prerequisite answered "no"
    - Use React Testing Library
    - **Validates: Requirements 6.2, 6.3, 6.8, 7.1, 7.2, 9.1**

- [x] 5. Checkpoint — Frontend components complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Integration and wiring
  - [x] 6.1 Add `/setup-guide` route in `frontend/src/App.tsx`
    - Add lazy import: `const SetupGuide = lazy(() => import('@/pages/setup-guide/SetupGuide'))`
    - Add route inside OrgLayout routes: `<Route path="/setup-guide" element={<SetupGuide />} />`
    - _Requirements: 8.1_

  - [x] 6.2 Integrate with SetupWizard in `frontend/src/pages/setup/SetupWizard.tsx`
    - When wizard reaches Step 5 (Modules, `currentStep === 4`), redirect to `/setup-guide` using `useNavigate`
    - When `step_5_complete` is already true in loaded progress, skip Step 5 and advance to Step 6
    - _Requirements: 4.1, 4.2_

  - [x] 6.3 Add "Re-run Setup Guide" button in `frontend/src/pages/settings/Settings.tsx`
    - Add a button in the Modules settings tab that navigates to `/setup-guide?rerun=true`
    - _Requirements: 8.1_

  - [x] 6.4 Create steering document at `.kiro/steering/setup-guide-for-new-modules.md`
    - Use `inclusion: auto` front matter
    - Include instructions for adding `setup_question` and `setup_question_description` to new module registry migrations
    - Provide a template for the question and description fields
    - List the fields that must be populated for the Setup Guide to include the module automatically
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [x] 7. Checkpoint — Integration complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Integration tests
  - [x] 8.1 Write integration tests for the full setup guide flow
    - Test full first-run flow: GET questions → POST submit → verify org_modules updated
    - Test full rerun flow: complete first run → re-run with `rerun=true` → verify only skipped modules shown
    - Test wizard Step 5 redirect triggers correctly
    - _Requirements: 2.1, 3.2, 3.3, 3.5, 4.1, 8.2, 8.4_

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- **No new tables** — completion tracked via existing `setup_wizard_progress.step_5_complete`
- **No service class** — router handlers call `ModuleService` directly per design decision
- **No `/status` endpoint** — wizard already checks its own progress record
- **No `trade_family_gated` column** — hardcoded set in router (matches `CORE_MODULES` pattern)
- Backend uses `flush()` not `commit()` — `session.begin()` auto-commits
- Frontend API calls use `{ baseURL: '/api/v2' }` override to avoid the v1 double-prefix issue (ISSUE-006)
- All API data access must follow safe-api-consumption patterns (`?.`, `?? []`, `?? 0`)
