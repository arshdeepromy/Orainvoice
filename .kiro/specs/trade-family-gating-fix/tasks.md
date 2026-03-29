# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Fault Condition** - Vehicle UI Rendered for Non-Automotive Organisations
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate vehicle-specific UI renders for non-automotive orgs
  - **Scoped PBT Approach**: Scope the property to concrete failing cases — render each affected component with `tradeFamily: 'plumbing'` and assert vehicle UI is absent
  - **Bug Condition from design**: `isBugCondition(input)` where `(input.tradeFamily ?? 'automotive-transport') !== 'automotive-transport'` AND `input.page IN ['InvoiceCreate', 'InvoiceDetail', 'QuoteCreate', 'QuoteDetail', 'JobCardList', 'JobCardCreate', 'JobCardDetail', 'BookingForm', 'VehicleRoutes']` AND `vehicleUIIsRendered(input.page)`
  - Create test file `frontend/src/pages/__tests__/trade-family-gating.fault.test.tsx`
  - Mock `TenantContext` with `tradeFamily: 'plumbing'` for all test cases
  - Test InvoiceCreate: render with `tradeFamily: 'plumbing'` — assert `VehicleLiveSearch` is NOT in the document
  - Test InvoiceDetail: render with `tradeFamily: 'plumbing'` — assert vehicle info section is NOT rendered
  - Test QuoteCreate: render with `tradeFamily: 'plumbing'` — assert vehicle lookup section is NOT rendered
  - Test QuoteDetail: render with `tradeFamily: 'plumbing'` and a quote with `vehicle_rego` — assert vehicle rego is NOT displayed
  - Test JobCardList: render with `tradeFamily: 'plumbing'` — assert "Rego" column header is NOT present
  - Test JobCardCreate: render with `tradeFamily: 'plumbing'` — assert vehicle section is NOT rendered
  - Test JobCardDetail: render with `tradeFamily: 'plumbing'` — assert vehicle section is NOT rendered
  - Test BookingForm: render with `tradeFamily: 'plumbing'` — assert `VehicleLiveSearch` is NOT rendered
  - Test App.tsx vehicle route: navigate to `/vehicles` with `tradeFamily: 'plumbing'` — assert redirect to `/dashboard`
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct — it proves the bug exists because vehicle UI renders without tradeFamily checks)
  - Document counterexamples found: vehicle UI elements render for non-automotive orgs because no `tradeFamily` check exists in the components
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Vehicle UI Shown for Automotive and Null-TradeFamily Organisations
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for automotive and null-tradeFamily inputs — vehicle UI renders correctly
  - Create test file `frontend/src/pages/__tests__/trade-family-gating.preservation.test.tsx`
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements in design
  - Test InvoiceCreate with `tradeFamily: 'automotive-transport'`: observe `VehicleLiveSearch` renders — write assertion preserving this
  - Test InvoiceCreate with `tradeFamily: null`: observe `VehicleLiveSearch` renders — write assertion preserving backward compat
  - Test InvoiceDetail with `tradeFamily: 'automotive-transport'`: observe vehicle info section renders — preserve
  - Test QuoteCreate with `tradeFamily: 'automotive-transport'`: observe vehicle lookup renders — preserve
  - Test QuoteDetail with `tradeFamily: 'automotive-transport'` and quote with `vehicle_rego`: observe vehicle info renders — preserve
  - Test JobCardList with `tradeFamily: 'automotive-transport'`: observe "Rego" column renders — preserve
  - Test JobCardCreate with `tradeFamily: 'automotive-transport'`: observe vehicle section renders — preserve
  - Test JobCardDetail with `tradeFamily: 'automotive-transport'`: observe vehicle section renders — preserve
  - Test BookingForm with `tradeFamily: 'automotive-transport'`: observe `VehicleLiveSearch` renders — preserve
  - Test App.tsx `/vehicles` route with `tradeFamily: 'automotive-transport'`: observe VehicleList renders — preserve
  - Test null tradeFamily backward compatibility: for all affected pages, `tradeFamily: null` renders vehicle UI identically to `'automotive-transport'`
  - Property-based test: generate random non-automotive `tradeFamily` strings (e.g. `'plumbing'`, `'electrical'`, `'landscaping'`) — these are NOT tested here (they are the fault condition); this test only covers automotive and null
  - Property-based test: `isAutomotive` derivation — for `tradeFamily: 'automotive-transport'` and `tradeFamily: null`, `isAutomotive` is `true`
  - Verify tests PASS on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14_

- [x] 3. Fix trade family gating across affected pages

  - [x] 3.1 Add `RequireAutomotive` route guard in App.tsx
    - Create `RequireAutomotive` component that reads `tradeFamily` from `useTenant()`, computes `isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'`, and returns `<Navigate to="/dashboard" replace />` if not automotive, otherwise `<Outlet />`
    - Wrap `/vehicles` and `/vehicles/:id` routes with `<Route element={<RequireAutomotive />}>...</Route>`
    - _Bug_Condition: isBugCondition(input) where tradeFamily is non-automotive AND page is VehicleRoutes_
    - _Expected_Behavior: Non-automotive users redirected to /dashboard for /vehicles routes_
    - _Preservation: Automotive and null-tradeFamily users continue to access /vehicles normally_
    - _Requirements: 2.11, 3.11, 3.12_

  - [x] 3.2 Add `isAutomotive` gating to InvoiceCreate.tsx
    - Add `const { tradeFamily } = useTenant()` (or destructure from existing `useTenant()` call)
    - Compute `const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'`
    - Wrap `<ModuleGate module="vehicles">` vehicle search section in `{isAutomotive && ...}`
    - Gate fluid usage section and labour picker button with `isAutomotive` where applicable
    - _Bug_Condition: tradeFamily is non-automotive AND InvoiceCreate renders VehicleLiveSearch_
    - _Expected_Behavior: VehicleLiveSearch hidden for non-automotive orgs_
    - _Preservation: VehicleLiveSearch continues to render for automotive and null tradeFamily_
    - _Requirements: 2.2, 3.2_

  - [x] 3.3 Add `isAutomotive` gating to InvoiceDetail.tsx
    - Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`
    - Wrap `<ModuleGate module="vehicles">` vehicle info section in `{isAutomotive && ...}`
    - _Bug_Condition: tradeFamily is non-automotive AND InvoiceDetail renders vehicle info_
    - _Expected_Behavior: Vehicle info section hidden for non-automotive orgs_
    - _Preservation: Vehicle info section continues to render for automotive and null tradeFamily_
    - _Requirements: 2.3, 3.3_

  - [x] 3.4 Add `isAutomotive` gating to QuoteCreate.tsx
    - Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`
    - Augment existing `{isEnabled('vehicles') && ...}` to `{isAutomotive && isEnabled('vehicles') && ...}`
    - Gate `vehicle_rego`, `vehicle_make`, `vehicle_model` fields in `buildPayload()` with `isAutomotive`
    - _Bug_Condition: tradeFamily is non-automotive AND QuoteCreate renders vehicle lookup_
    - _Expected_Behavior: Vehicle lookup hidden for non-automotive orgs_
    - _Preservation: Vehicle lookup continues to render for automotive and null tradeFamily_
    - _Requirements: 2.5, 3.5_

  - [x] 3.5 Add `isAutomotive` gating to QuoteDetail.tsx
    - Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`
    - Wrap `{quote.vehicle_rego && ...}` vehicle info block in `{isAutomotive && quote.vehicle_rego && ...}`
    - _Bug_Condition: tradeFamily is non-automotive AND QuoteDetail renders vehicle rego_
    - _Expected_Behavior: Vehicle rego hidden for non-automotive orgs_
    - _Preservation: Vehicle rego continues to render for automotive and null tradeFamily_
    - _Requirements: 2.6, 3.6_

  - [x] 3.6 Add `isAutomotive` gating to JobCardList.tsx
    - Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`
    - Wrap "Rego" `<th>` column header in `{isAutomotive && <th>Rego</th>}`
    - Wrap corresponding `<td>` cell in `{isAutomotive && <td>{rego}</td>}`
    - Adjust `colSpan` on empty-state row to account for conditional column
    - _Bug_Condition: tradeFamily is non-automotive AND JobCardList renders Rego column_
    - _Expected_Behavior: Rego column hidden for non-automotive orgs_
    - _Preservation: Rego column continues to render for automotive and null tradeFamily_
    - _Requirements: 2.7, 3.7_

  - [x] 3.7 Add `isAutomotive` gating to JobCardCreate.tsx
    - Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`
    - Wrap entire Vehicle section (`<section aria-labelledby="section-vehicle">...</section>`) in `{isAutomotive && ...}`
    - Gate `vehicle_id` field in save payload with `isAutomotive`
    - _Bug_Condition: tradeFamily is non-automotive AND JobCardCreate renders vehicle section_
    - _Expected_Behavior: Vehicle section hidden for non-automotive orgs_
    - _Preservation: Vehicle section continues to render for automotive and null tradeFamily_
    - _Requirements: 2.8, 3.8_

  - [x] 3.8 Add `isAutomotive` gating to JobCardDetail.tsx
    - Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`
    - Wrap Vehicle `<section>` showing `jobCard.vehicle_rego` in `{isAutomotive && ...}`
    - _Bug_Condition: tradeFamily is non-automotive AND JobCardDetail renders vehicle section_
    - _Expected_Behavior: Vehicle section hidden for non-automotive orgs_
    - _Preservation: Vehicle section continues to render for automotive and null tradeFamily_
    - _Requirements: 2.9, 3.9_

  - [x] 3.9 Add `isAutomotive` gating to BookingForm.tsx
    - Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`
    - Wrap `<ModuleGate module="vehicles">` containing `VehicleLiveSearch` in `{isAutomotive && ...}`
    - Add `isAutomotive` to the fluid usage section condition: `isAutomotive && vehiclesEnabled && selectedVehicle`
    - _Bug_Condition: tradeFamily is non-automotive AND BookingForm renders VehicleLiveSearch_
    - _Expected_Behavior: VehicleLiveSearch hidden for non-automotive orgs_
    - _Preservation: VehicleLiveSearch continues to render for automotive and null tradeFamily_
    - _Requirements: 2.10, 3.10_

  - [x] 3.10 Verify InvoiceList.tsx existing gating is correct
    - Confirm `isAutomotive` is already computed from `useTenant()` and used to gate vehicle info in the detail panel
    - Verify the list view has no ungated vehicle columns
    - If any gaps found, add missing `isAutomotive` guards
    - _Bug_Condition: tradeFamily is non-automotive AND InvoiceList renders vehicle UI_
    - _Expected_Behavior: Vehicle UI hidden for non-automotive orgs (already partially implemented)_
    - _Preservation: Vehicle UI continues to render for automotive and null tradeFamily_
    - _Requirements: 2.1, 3.1_

  - [x] 3.11 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Vehicle UI Hidden for Non-Automotive Organisations
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior (vehicle UI absent for non-automotive orgs)
    - When this test passes, it confirms the expected behavior is satisfied across all affected pages
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11_

  - [x] 3.12 Verify preservation tests still pass
    - **Property 2: Preservation** - Vehicle UI Shown for Automotive and Null-TradeFamily Organisations
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions — automotive and null-tradeFamily orgs still see all vehicle UI)
    - Confirm all tests still pass after fix (no regressions)

  - [x] 3.13 Rebuild frontend in container
    - Run `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend sh -c "rm -rf /app/dist/* && npx vite build"` to rebuild the frontend with all changes
    - Verify build completes without errors

- [-] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Verify fault condition test (task 1) now PASSES after fix
  - Verify preservation test (task 2) still PASSES after fix
  - Confirm no TypeScript compilation errors in changed files
  - Confirm frontend build succeeds in container
