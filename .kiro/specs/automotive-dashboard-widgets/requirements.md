# Requirements Document

## Introduction

Transform the existing OrgAdminDashboard from a sparse KPI-only layout into a rich, widget-based dashboard tailored for automotive trade businesses (mechanics, panel beaters, tyre shops). The dashboard uses trade-family gating so that automotive-specific widgets only appear for organisations with `tradeFamily === 'automotive-transport'`. Individual widgets are further gated behind their relevant backend modules (vehicles, inventory, bookings, claims). Users can rearrange widgets via drag-and-drop, and layout preferences persist across sessions. The design is responsive, reflowing to a single column on mobile, and follows the existing Tailwind CSS / Headless UI design system.

## Glossary

- **Dashboard**: The OrgAdminDashboard page rendered for users with the `org_admin` role
- **Widget**: A self-contained card component on the Dashboard that displays a specific data summary or interactive element
- **Widget_Grid**: The draggable, responsive grid layout container that holds and arranges all Widgets
- **Trade_Family**: The slug identifying an organisation's industry vertical (e.g. `automotive-transport`, `plumbing-gas`), sourced from `useTenant().tradeFamily`
- **Module_Gate**: The gating mechanism that conditionally renders UI based on whether a module slug is enabled for the organisation, using `useModules().isEnabled(slug)` or the `<ModuleGate>` component
- **Layout_Preferences**: The persisted arrangement (order and visibility) of Widgets for a given user, stored in localStorage or backend user settings
- **Reminder_Rule**: A configurable rule that defines the threshold (in days) before a WOF or service expiry date at which a reminder should surface in the dashboard widget
- **Reminder_Dismissal**: A record indicating that a specific WOF/Service expiry reminder has been dismissed or marked as "reminder sent" by the user, preventing it from reappearing in the widget

## Requirements

### Requirement 1: Trade-Family Gated Dashboard Rendering

**User Story:** As an org admin, I want the dashboard to show automotive-specific widgets only when my organisation belongs to the automotive trade family, so that non-automotive businesses see the existing generic dashboard.

#### Acceptance Criteria

1. WHEN the Dashboard loads, THE Dashboard SHALL read the Trade_Family from `useTenant().tradeFamily` using the pattern `const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'`
2. WHILE `isAutomotive` is true, THE Dashboard SHALL render the Widget_Grid containing all automotive-specific Widgets in addition to the existing KPI cards
3. WHILE `isAutomotive` is false, THE Dashboard SHALL render only the existing generic OrgAdminDashboard content (KPI cards and branch metrics)
4. IF `tradeFamily` is null, THEN THE Dashboard SHALL default to treating the organisation as automotive (backward compatibility with existing orgs that have no trade category set)

### Requirement 2: Module-Gated Widget Visibility

**User Story:** As an org admin, I want each widget to appear only when its corresponding backend module is enabled, so that I do not see widgets for features my organisation has not activated.

#### Acceptance Criteria

1. THE Dashboard SHALL gate the Inventory Overview Widget behind the `inventory` module using Module_Gate
2. THE Dashboard SHALL gate the Recent Claims & Status Widget behind the `claims` module using Module_Gate
3. THE Dashboard SHALL gate the Today's Bookings Widget behind the `bookings` module using Module_Gate
4. THE Dashboard SHALL gate the WOF/Service Expiry Reminders Widget behind the `vehicles` module using Module_Gate
5. THE Dashboard SHALL gate the Service/WOF Reminder Configuration Widget behind the `vehicles` module using Module_Gate
6. WHEN a module is disabled, THE Dashboard SHALL hide the corresponding Widget without leaving an empty gap in the Widget_Grid layout
7. THE Dashboard SHALL render the Recent Customers Served, Upcoming Public Holidays, Cash Flow Chart, and Active Staff Widgets without module gating (these use core data available to all organisations)

### Requirement 3: Draggable and Rearrangeable Widget Grid

**User Story:** As an org admin, I want to drag and rearrange widgets on my dashboard, so that I can prioritise the information most relevant to my workflow.

#### Acceptance Criteria

1. THE Widget_Grid SHALL allow the user to reorder Widgets by dragging and dropping them within the grid
2. WHEN the user completes a drag-and-drop operation, THE Widget_Grid SHALL persist the new Layout_Preferences to localStorage keyed by the user's ID
3. WHEN the Dashboard loads, THE Widget_Grid SHALL restore the previously saved Layout_Preferences from localStorage
4. IF no saved Layout_Preferences exist, THEN THE Widget_Grid SHALL render Widgets in a default order defined by the application
5. IF a previously saved Widget is no longer available (module disabled or trade family changed), THEN THE Widget_Grid SHALL remove that Widget from the saved layout and render the remaining Widgets without gaps
6. THE Widget_Grid SHALL use a CSS grid layout with 3 columns on desktop (1024px and above), 2 columns on tablet (640px to 1023px), and 1 column on mobile (below 640px)

### Requirement 4: Recent Customers Served Widget

**User Story:** As a mechanic shop admin, I want to see the last 5–10 customers I served along with their vehicle information, so that I can quickly reference recent work.

#### Acceptance Criteria

1. THE Recent_Customers_Served Widget SHALL display the 10 most recently invoiced customers for the current branch
2. FOR EACH customer entry, THE Recent_Customers_Served Widget SHALL display the customer name, the date of the most recent invoice, and the vehicle registration number (if a vehicle was linked to the invoice)
3. WHEN the user clicks on a customer entry, THE Recent_Customers_Served Widget SHALL navigate to that customer's profile page
4. IF no customers have been invoiced, THEN THE Recent_Customers_Served Widget SHALL display an empty state message reading "No recent customers"
5. IF vehicle data is unavailable for an invoice, THEN THE Recent_Customers_Served Widget SHALL display the customer entry without vehicle information

### Requirement 5: Today's Bookings Widget

**User Story:** As a mechanic shop admin, I want to see today's bookings with time, customer, and vehicle details, so that I can plan my workshop's day.

#### Acceptance Criteria

1. WHEN the Dashboard loads, THE Todays_Bookings Widget SHALL fetch and display all bookings scheduled for the current calendar date for the current branch
2. FOR EACH booking, THE Todays_Bookings Widget SHALL display the scheduled time, customer name, and vehicle registration number
3. THE Todays_Bookings Widget SHALL sort bookings in ascending chronological order by scheduled time
4. WHEN the user clicks on a booking entry, THE Todays_Bookings Widget SHALL navigate to that booking's detail page
5. IF no bookings exist for today, THEN THE Todays_Bookings Widget SHALL display an empty state message reading "No bookings for today"
6. THE Todays_Bookings Widget SHALL be gated behind the `bookings` module

### Requirement 6: Upcoming Public Holidays Widget

**User Story:** As a business owner, I want to see upcoming public holidays based on my country, so that I can plan staffing and scheduling around them.

#### Acceptance Criteria

1. WHEN the Dashboard loads, THE Public_Holidays Widget SHALL fetch and display the next 5 upcoming public holidays from the `public_holidays` table filtered by the organisation's country
2. FOR EACH holiday, THE Public_Holidays Widget SHALL display the holiday name and the date
3. THE Public_Holidays Widget SHALL sort holidays in ascending chronological order by date
4. IF no upcoming public holidays exist within the next 12 months, THEN THE Public_Holidays Widget SHALL display an empty state message reading "No upcoming public holidays"

### Requirement 7: Inventory Overview Widget

**User Story:** As a mechanic shop admin, I want to see a summary of my stock levels for tyres, parts, and fluids, so that I can identify low-stock items at a glance.

#### Acceptance Criteria

1. THE Inventory_Overview Widget SHALL display summary boxes showing the total count of stock items grouped by category (tyres, parts, fluids, and other)
2. FOR EACH category, THE Inventory_Overview Widget SHALL display the category name, total item count, and the count of items below their reorder threshold
3. WHEN items are below their reorder threshold, THE Inventory_Overview Widget SHALL highlight the low-stock count using a warning colour (amber or red)
4. WHEN the user clicks on a category box, THE Inventory_Overview Widget SHALL navigate to the inventory stock levels page filtered by that category
5. THE Inventory_Overview Widget SHALL be gated behind the `inventory` module
6. IF no stock items exist, THEN THE Inventory_Overview Widget SHALL display an empty state message reading "No inventory items"

### Requirement 8: Cash Flow Chart Widget

**User Story:** As a business owner, I want to see a chart of revenue versus expenses over time, so that I can monitor my business's financial health.

#### Acceptance Criteria

1. THE Cash_Flow_Chart Widget SHALL display a bar or line chart showing monthly revenue and monthly expenses for the last 6 months
2. THE Cash_Flow_Chart Widget SHALL use distinct colours for revenue (green) and expenses (red) series
3. THE Cash_Flow_Chart Widget SHALL label the x-axis with month names and the y-axis with currency values formatted in NZD
4. WHEN the user hovers over a data point, THE Cash_Flow_Chart Widget SHALL display a tooltip showing the exact revenue and expense amounts for that month
5. IF no financial data exists for the period, THEN THE Cash_Flow_Chart Widget SHALL display an empty state message reading "No financial data available"

### Requirement 9: Recent Claims & Status Widget

**User Story:** As a mechanic shop admin, I want to see recent customer claims and their current status, so that I can track warranty and dispute resolution progress.

#### Acceptance Criteria

1. THE Recent_Claims Widget SHALL display the 10 most recent claims for the current branch, ordered by creation date descending
2. FOR EACH claim, THE Recent_Claims Widget SHALL display the claim reference number, customer name, claim date, and current status
3. THE Recent_Claims Widget SHALL display the claim status using colour-coded badges (e.g. green for resolved, amber for in progress, red for rejected, grey for pending)
4. WHEN the user clicks on a claim entry, THE Recent_Claims Widget SHALL navigate to that claim's detail page
5. THE Recent_Claims Widget SHALL be gated behind the `claims` module
6. IF no claims exist, THEN THE Recent_Claims Widget SHALL display an empty state message reading "No recent claims"

### Requirement 10: Active Staff Widget

**User Story:** As a mechanic shop admin, I want to see which staff members are currently clocked in, so that I can manage workshop capacity in real time.

#### Acceptance Criteria

1. THE Active_Staff Widget SHALL display a list of staff members who are currently clocked in for the current branch
2. FOR EACH active staff member, THE Active_Staff Widget SHALL display the staff member's name and their clock-in time
3. THE Active_Staff Widget SHALL display the total count of currently active staff members as a header summary
4. IF no staff members are currently clocked in, THEN THE Active_Staff Widget SHALL display an empty state message reading "No staff currently clocked in"

### Requirement 11: WOF/Service Expiry Reminders Widget

**User Story:** As a mechanic shop admin, I want to see vehicles with WOF or service due within 30 days linked to their customers, so that I can proactively contact customers for upcoming maintenance.

#### Acceptance Criteria

1. THE Expiry_Reminders Widget SHALL display vehicles with a WOF expiry date or next service date within the next 30 days, linked to their customer owner
2. FOR EACH reminder entry, THE Expiry_Reminders Widget SHALL display the vehicle registration number, vehicle make and model, the expiry type (WOF or Service), the expiry date, and the customer name
3. THE Expiry_Reminders Widget SHALL sort entries in ascending order by expiry date (soonest first)
4. THE Expiry_Reminders Widget SHALL provide a "Mark Reminder Sent" button for each entry that records a Reminder_Dismissal
5. WHEN the user clicks "Mark Reminder Sent", THE Expiry_Reminders Widget SHALL visually update the entry to show a "Sent" badge and persist the Reminder_Dismissal to the backend
6. THE Expiry_Reminders Widget SHALL provide a "Dismiss" button for each entry that hides the reminder from the widget
7. WHEN the user clicks "Dismiss", THE Expiry_Reminders Widget SHALL remove the entry from the visible list and persist the Reminder_Dismissal to the backend
8. THE Expiry_Reminders Widget SHALL NOT display entries that have been previously dismissed or marked as reminder sent
9. THE Expiry_Reminders Widget SHALL be gated behind the `vehicles` module
10. IF no vehicles have upcoming expiries, THEN THE Expiry_Reminders Widget SHALL display an empty state message reading "No upcoming WOF or service expiries"

### Requirement 12: Service/WOF Reminder Configuration Widget

**User Story:** As a mechanic shop admin, I want to configure the reminder threshold for WOF and service expiry alerts, so that I can control how far in advance reminders appear.

#### Acceptance Criteria

1. THE Reminder_Configuration Widget SHALL display the current reminder threshold in days for WOF expiry reminders and service expiry reminders
2. THE Reminder_Configuration Widget SHALL allow the user to edit the WOF reminder threshold (number of days before expiry)
3. THE Reminder_Configuration Widget SHALL allow the user to edit the service reminder threshold (number of days before expiry)
4. WHEN the user saves a new threshold value, THE Reminder_Configuration Widget SHALL persist the updated Reminder_Rule to the backend
5. IF no Reminder_Rule exists, THEN THE Reminder_Configuration Widget SHALL default to 30 days for both WOF and service thresholds
6. THE Reminder_Configuration Widget SHALL validate that threshold values are positive integers between 1 and 365
7. THE Reminder_Configuration Widget SHALL be gated behind the `vehicles` module

### Requirement 13: Responsive Layout

**User Story:** As an org admin, I want the dashboard to work on desktop, tablet, and mobile devices, so that I can check my business status from any device.

#### Acceptance Criteria

1. WHILE the viewport width is 1024px or above, THE Widget_Grid SHALL render Widgets in a 3-column layout
2. WHILE the viewport width is between 640px and 1023px, THE Widget_Grid SHALL render Widgets in a 2-column layout
3. WHILE the viewport width is below 640px, THE Widget_Grid SHALL render Widgets in a single-column layout
4. THE Widget_Grid SHALL use consistent spacing (gap) between Widgets across all breakpoints
5. WHEN a Widget contains a data table, THE Widget SHALL make the table horizontally scrollable on narrow viewports rather than breaking the layout

### Requirement 14: Widget Visual Design

**User Story:** As an org admin, I want the dashboard widgets to have a modern, clean card-based design, so that the dashboard is visually appealing and easy to scan.

#### Acceptance Criteria

1. THE Dashboard SHALL render each Widget as a card with a white background, rounded corners, and a subtle border consistent with the existing KPI card styling (`rounded-lg border border-gray-200 bg-white`)
2. EACH Widget card SHALL include a header section with an icon, a title, and an optional action link
3. THE Dashboard SHALL use icons from a consistent icon set (Heroicons or the icon library already used in the project) for each Widget header
4. THE Dashboard SHALL use colour coding to convey status: green for positive/healthy, amber for warning, red for critical/overdue, grey for neutral/inactive
5. THE Dashboard SHALL use the existing Tailwind CSS utility classes and Headless UI components — no new CSS framework or component library SHALL be introduced

### Requirement 15: Safe API Data Consumption

**User Story:** As a developer, I want all dashboard API calls to follow the project's safe API consumption patterns, so that the dashboard does not crash from null or undefined API responses.

#### Acceptance Criteria

1. THE Dashboard SHALL use optional chaining (`?.`) and nullish coalescing (`?? []`, `?? 0`) on all API response data before rendering
2. THE Dashboard SHALL use `AbortController` cleanup in every `useEffect` that makes API calls
3. THE Dashboard SHALL use typed generics on all `apiClient.get()` calls — no `as any` type assertions
4. THE Dashboard SHALL guard all `.map()`, `.filter()`, and `.toLocaleString()` calls on API data with `?? []` or `?? 0` fallbacks
5. IF an API call fails, THEN THE affected Widget SHALL display a localised error message within the Widget card without crashing the entire Dashboard
