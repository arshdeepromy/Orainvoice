# Requirements Document

## Introduction

The invoice screen in the active web app (`frontend-v2/src/pages/invoices/InvoiceList.tsx`) places four horizontally-competing regions side by side: the global app sidebar (264px rail), the invoice list column (`w-80 min-w-[320px]`, hard 320px floor), the invoice preview card (`flex-1 min-w-0`), and the POS receipt preview panel (`w-[280px] shrink-0`). At intermediate viewport widths (observed around 970px) these regions cannot all fit, and the invoice preview is crushed or clipped.

This feature introduces a small set of responsive layout tiers for the invoice screen and the global shell so that, as the viewport narrows, regions collapse in a controlled, predictable order instead of overflowing. The change is frontend-only (responsive CSS and layout state in `frontend-v2/`). There are no backend, database, or API changes.

The scope is intentionally narrow: master–detail collapse on the invoice screen, POS receipt panel stacking, a responsive icon-only sidebar tier, and a no-clip safety net. Existing behaviors that must not regress are explicitly covered: print/PDF output, the org-level "Show POS receipt preview" toggle, the manual sidebar display preference, and the existing ≤860px mobile drawer.

## Glossary

- **Invoice_Screen**: The `InvoiceList` page in `frontend-v2/src/pages/invoices/InvoiceList.tsx`, comprising the invoice list column and the invoice detail/preview region.
- **App_Shell**: The authenticated org layout (`frontend-v2/src/layouts/OrgLayout.tsx`) that hosts the global sidebar, top bar, and scrolling content region.
- **Responsive_Sidebar**: The global navigation sidebar (`frontend-v2/src/components/shell/Sidebar.tsx`) rendered inside the App_Shell.
- **Master_Detail_View**: The two-region arrangement on the Invoice_Screen consisting of the invoice list column (master) and the invoice detail/preview region (detail).
- **Invoice_List_Column**: The master region listing invoices (currently `w-80 min-w-[320px]`).
- **Invoice_Detail_Region**: The detail region showing the selected invoice's detail and preview (currently `flex-1 min-w-0`, marked `data-print-content`).
- **Invoice_Preview_Card**: The invoice preview within the Invoice_Detail_Region (marked `data-preview="invoice"`).
- **POS_Receipt_Panel**: The POS receipt preview panel within the Invoice_Detail_Region (currently `w-[280px] shrink-0`, marked `data-preview="receipt"`).
- **Back_To_List_Control**: A user-activatable control shown only in collapsed single-pane mode that returns the Invoice_Screen from the Invoice_Detail_Region to the Invoice_List_Column.
- **Viewport_Width**: The browser viewport width in CSS pixels.
- **Drawer_Breakpoint**: The existing breakpoint at `max-width: 860px` (the custom `max-mobile` Tailwind variant), at and below which the Responsive_Sidebar is an off-canvas drawer.
- **Wide_Threshold**: The Viewport_Width at and above which the full labeled sidebar rail and the side-by-side Master_Detail_View are shown. Defined as 1280px.
- **Compact_Band**: The Viewport_Width range from 861px to 1279px inclusive (above the Drawer_Breakpoint and below the Wide_Threshold).
- **POS_Stack_Threshold**: The available width of the Invoice_Detail_Region, in CSS pixels, below which the POS_Receipt_Panel stacks below the Invoice_Preview_Card. Defined as 900px.
- **Sidebar_Display_Mode**: The org-level manual preference `sidebar_display_mode` (`icon_and_name` | `icon_only` | `name_only`) from `TenantContext`.
- **POS_Preview_Enabled**: The org-level toggle `settings.invoice.pos_preview_enabled` (defaults to true) controlling whether the POS_Receipt_Panel is shown at all.
- **Route_Invoice_Id**: The invoice id segment of the current route (`/invoices/:id`), read via `useParams` as `routeId` in `InvoiceList.tsx`. Present when the user deep-links or navigates to a specific invoice; absent on the bare invoices list path.
- **Invoices_List_Path**: The route path for the invoice list without a selected invoice id (`/invoices`).
- **Create_View**: The invoice creation form rendered inside the Invoice_Detail_Region when the route is `/invoices/new` (the `isCreating` state in `InvoiceList.tsx`).
- **Edit_Route**: The standalone full-page invoice edit route `/invoices/:id/edit`, which `InvoiceList.tsx` navigates away to and which occupies the route on its own.

## Requirements

### Requirement 1: Master–detail responsive collapse

**User Story:** As a user viewing invoices on a narrow or laptop-sized window, I want the invoice list and the invoice detail to not compete for horizontal space, so that the invoice preview is never crushed or clipped.

#### Acceptance Criteria

1. WHILE the Viewport_Width is at or above the Wide_Threshold (1280px), THE Invoice_Screen SHALL display the Invoice_List_Column and the Invoice_Detail_Region simultaneously, with neither region clipped and without introducing horizontal scrolling of the Invoice_Screen.
2. WHILE the Viewport_Width is below the Wide_Threshold, THE Invoice_Screen SHALL render exactly one of the Invoice_List_Column or the Invoice_Detail_Region in the visible layout and SHALL NOT render the other region in the visible layout.
3. WHILE the Viewport_Width is below the Wide_Threshold AND no invoice is selected, THE Invoice_Screen SHALL display the Invoice_List_Column.
4. WHILE the Viewport_Width is below the Wide_Threshold AND an invoice is selected, THE Invoice_Screen SHALL display the Invoice_Detail_Region for the selected invoice.
5. WHEN the Viewport_Width crosses the Wide_Threshold in either direction, THE Invoice_Screen SHALL preserve the currently selected invoice identity without reloading the selected invoice.
6. WHEN the Viewport_Width crosses below the Wide_Threshold AND no invoice is selected, THE Invoice_Screen SHALL display the Invoice_List_Column.
7. WHEN the Invoice_Screen first mounts below the Wide_Threshold WITH a Route_Invoice_Id present, THE Invoice_Screen SHALL display the Invoice_Detail_Region for the invoice identified by the Route_Invoice_Id.
8. WHEN the Invoice_Screen first mounts below the Wide_Threshold WITHOUT a Route_Invoice_Id, THE Invoice_Screen SHALL display the Invoice_List_Column even when the Invoice_List_Column auto-selects a first invoice.
9. WHILE the Viewport_Width is below the Wide_Threshold AND no Route_Invoice_Id is present, THE Invoice_Screen SHALL display the Invoice_List_Column even when an invoice is auto-selected (auto-selection alone SHALL NOT cause the Invoice_Detail_Region to be displayed below the Wide_Threshold).

### Requirement 2: Back-to-list navigation and selection preservation

**User Story:** As a user on a narrow window viewing an invoice's detail, I want a clear way to get back to the list, so that I can navigate between invoices without losing my place.

#### Acceptance Criteria

1. WHILE the Viewport_Width is below the Wide_Threshold AND the Invoice_Detail_Region is displayed, THE Invoice_Screen SHALL display the Back_To_List_Control.
2. WHILE the Viewport_Width is at or above the Wide_Threshold, THE Invoice_Screen SHALL hide the Back_To_List_Control.
3. WHEN the user activates the Back_To_List_Control, THE Invoice_Screen SHALL display the Invoice_List_Column.
4. WHEN the user selects an invoice from the Invoice_List_Column while the Viewport_Width is below the Wide_Threshold, THE Invoice_Screen SHALL display the Invoice_Detail_Region for the selected invoice.
5. WHEN the user returns to the Invoice_List_Column via the Back_To_List_Control, THE Invoice_Screen SHALL retain the previously selected invoice as the selected invoice and SHALL render that invoice's list row with a persistent visual selected-state indicator distinct from unselected rows.
6. THE Back_To_List_Control SHALL be reachable via Tab/Shift+Tab, SHALL display a visible focus indicator when focused, and SHALL be activatable using both the Enter and Space keys.
7. WHEN the user activates the Back_To_List_Control while the Viewport_Width is below the Wide_Threshold, THE Invoice_Screen SHALL navigate the route to the Invoices_List_Path so that a subsequent reload or deep-link resolves to the Invoice_List_Column.
8. WHEN the user selects the retained invoice's list row again after returning via the Back_To_List_Control, THE Invoice_Screen SHALL navigate the route to `/invoices/:id` for that invoice and display the Invoice_Detail_Region.

### Requirement 3: POS receipt panel responsive stacking

**User Story:** As a user viewing an invoice in a narrow detail region, I want the POS receipt preview to move below the invoice preview rather than beside it, so that the invoice preview keeps enough width to render legibly.

#### Acceptance Criteria

1. WHILE the available width of the Invoice_Detail_Region is at or above the POS_Stack_Threshold AND POS_Preview_Enabled is true, THE Invoice_Detail_Region SHALL display the POS_Receipt_Panel beside the Invoice_Preview_Card.
2. WHILE the available width of the Invoice_Detail_Region is below the POS_Stack_Threshold AND POS_Preview_Enabled is true, THE Invoice_Detail_Region SHALL display the POS_Receipt_Panel below the Invoice_Preview_Card.
3. WHERE POS_Preview_Enabled is false, THE Invoice_Detail_Region SHALL hide the POS_Receipt_Panel at all Viewport_Width values.
4. WHILE the POS_Receipt_Panel is displayed below the Invoice_Preview_Card, THE Invoice_Preview_Card SHALL occupy the full available width of the Invoice_Detail_Region.
5. THE Invoice_Screen SHALL preserve the existing preview selection behavior between the Invoice_Preview_Card and the POS_Receipt_Panel when the POS_Receipt_Panel is stacked below.

### Requirement 4: Responsive icon-only sidebar tier

**User Story:** As a user on a laptop-sized window, I want the global sidebar to shrink to an icon-only rail, so that the invoice screen reclaims horizontal space without losing navigation.

#### Acceptance Criteria

1. WHILE the Viewport_Width is at or above the Wide_Threshold, THE Responsive_Sidebar SHALL render as a docked rail showing navigation icons and labels.
2. WHILE the Viewport_Width is within the Compact_Band, THE Responsive_Sidebar SHALL render as a docked icon-only rail.
3. WHILE the Viewport_Width is at or below the Drawer_Breakpoint, THE Responsive_Sidebar SHALL render as the existing off-canvas drawer.
4. WHILE the Viewport_Width is within the Compact_Band, THE App_Shell SHALL allocate the width reclaimed by the icon-only rail to the content region.
5. WHILE the Viewport_Width is at or above the Wide_Threshold, THE Responsive_Sidebar SHALL render the rail unchanged from its current non-responsive appearance.
6. WHILE the Viewport_Width is within the Compact_Band, THE Responsive_Sidebar SHALL apply the icon-only treatment as a presentation-only change and SHALL NOT write or persist any change to the Sidebar_Display_Mode preference.
7. WHEN the Viewport_Width changes from the Compact_Band to at or above the Wide_Threshold, THE Responsive_Sidebar SHALL restore the rail's current non-responsive appearance without persisting any change to the Sidebar_Display_Mode preference.
8. WHILE an icon-only navigation item is displayed in the Compact_Band, THE Responsive_Sidebar SHALL expose the item's label to assistive technology.
9. WHILE the Viewport_Width is within the Compact_Band, THE Responsive_Sidebar SHALL render the footer org switcher and the header wordmark in an icon-only or collapsed treatment that remains usable and does not overflow the narrowed (approximately 72px) rail.

### Requirement 5: No-clip safety net

**User Story:** As a user at any window width, I want the invoice preview to remain readable rather than scrambled, so that I can always read the invoice even at unusual widths.

#### Acceptance Criteria

1. THE Invoice_Preview_Card SHALL remain within the horizontal bounds of the Invoice_Detail_Region at all Viewport_Width values.
2. IF the Invoice_Preview_Card content is wider than the available width of the Invoice_Detail_Region, THEN THE Invoice_Detail_Region SHALL keep the Invoice_Preview_Card readable by scrolling or scaling rather than overlapping adjacent content.
3. THE Invoice_List_Column SHALL remain within the horizontal bounds of the Invoice_Screen at all Viewport_Width values.

### Requirement 6: Regression prevention for existing behaviors

**User Story:** As an existing user, I want printing, the POS preview toggle, the mobile drawer, and the wide-screen layout to keep working as before, so that this change does not break workflows I rely on.

#### Acceptance Criteria

1. WHEN the user prints or generates a PDF of an invoice, THE Invoice_Screen SHALL hide the POS_Receipt_Panel (the existing `[data-preview="receipt"]` print rule) regardless of Viewport_Width.
2. WHEN the user prints or generates a PDF of an invoice, THE Invoice_Screen SHALL render the Invoice_Preview_Card at full page width as defined by the existing print styles.
3. WHILE the Viewport_Width is at or above the Wide_Threshold AND POS_Preview_Enabled is true, THE Invoice_Screen SHALL render the side-by-side Master_Detail_View and the beside-arranged POS_Receipt_Panel as in the current layout.
4. WHILE the Viewport_Width is at or below the Drawer_Breakpoint, THE App_Shell SHALL preserve the existing off-canvas drawer behavior, including opening via the hamburger control, dismissal via the scrim, and dismissal via the Escape key.
5. THE Invoice_Screen SHALL apply the POS_Preview_Enabled toggle to both the POS_Receipt_Panel visibility and the "Print POS Receipt" action as in the current behavior.

### Requirement 7: Accessibility of responsive state changes

**User Story:** As a keyboard or assistive-technology user, I want responsive layout changes to remain keyboard accessible and free of focus traps, so that narrowing the window does not make the invoice screen unusable.

#### Acceptance Criteria

1. WHEN a responsive transition hides the region containing keyboard focus, THE Invoice_Screen SHALL move focus to a visible, interactive element in the newly displayed region.
2. WHILE any responsive layout state is active, THE Invoice_Screen SHALL allow keyboard focus to move through all displayed interactive controls without trapping focus.
3. WHEN the user activates the Back_To_List_Control using the keyboard, THE Invoice_Screen SHALL move focus to the Invoice_List_Column.

### Requirement 8: Create/Edit view responsive behavior

**User Story:** As a user creating a new invoice on a narrow or laptop-sized window, I want the create form to use the full width instead of competing with the invoice list, so that the form is usable without horizontal crowding.

#### Acceptance Criteria

1. WHILE the Viewport_Width is below the Wide_Threshold AND the Create_View is active (route `/invoices/new`), THE Invoice_Screen SHALL display the Create_View as the sole visible pane and SHALL NOT render the Invoice_List_Column beside it.
2. WHILE the Viewport_Width is below the Wide_Threshold AND the Create_View is active, THE Invoice_Screen SHALL display the Back_To_List_Control to return to the Invoice_List_Column.
3. WHILE the Viewport_Width is at or above the Wide_Threshold AND the Create_View is active, THE Invoice_Screen SHALL display the existing side-by-side arrangement of the Invoice_List_Column and the Create_View unchanged.
4. WHERE the route is the Edit_Route (`/invoices/:id/edit`), THE Invoice_Screen SHALL treat the Edit_Route as a separate full-page route outside the Master_Detail_View single-pane logic.
