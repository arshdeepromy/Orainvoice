# Bugfix Requirements Document

## Introduction

When a user changes their organisation's business type from automotive to a non-automotive trade (e.g., plumber) via Settings → Business Type, automotive-specific UI elements — vehicle columns, vehicle selectors, vehicle info sections, and vehicle routes — remain visible across 10+ frontend pages. The backend, TenantContext, sidebar, and CataloguePage all gate correctly, but the majority of pages that render vehicle-specific UI do so unconditionally without checking `tradeFamily`. This causes non-automotive organisations to see irrelevant vehicle features throughout invoices, quotes, job cards, bookings, and vehicle routes.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a non-automotive organisation views the Invoice List page THEN the system displays the vehicle registration column despite `isAutomotive` being declared but never used to conditionally render it

1.2 WHEN a non-automotive organisation creates an invoice THEN the system renders the `VehicleLiveSearch` vehicle selector unconditionally

1.3 WHEN a non-automotive organisation views an invoice detail THEN the system shows the vehicle info section unconditionally

1.4 WHEN a non-automotive organisation views the Quote List page THEN the system displays the vehicle registration column with no `tradeFamily` check present

1.5 WHEN a non-automotive organisation creates a quote THEN the system renders the vehicle selector unconditionally

1.6 WHEN a non-automotive organisation views a quote detail THEN the system shows the vehicle info section unconditionally

1.7 WHEN a non-automotive organisation views the Job Card List page THEN the system displays vehicle info unconditionally

1.8 WHEN a non-automotive organisation creates a job card THEN the system renders the vehicle selector unconditionally

1.9 WHEN a non-automotive organisation views a job card detail THEN the system shows vehicle info unconditionally

1.10 WHEN a non-automotive organisation creates a booking THEN the system renders the vehicle selector in the booking form unconditionally

1.11 WHEN a non-automotive organisation navigates directly to `/vehicles` or `/vehicles/:id` via URL THEN the system renders the vehicle pages without any route guard

### Expected Behavior (Correct)

2.1 WHEN a non-automotive organisation views the Invoice List page THEN the system SHALL hide the vehicle registration column

2.2 WHEN a non-automotive organisation creates an invoice THEN the system SHALL hide the `VehicleLiveSearch` vehicle selector

2.3 WHEN a non-automotive organisation views an invoice detail THEN the system SHALL hide the vehicle info section

2.4 WHEN a non-automotive organisation views the Quote List page THEN the system SHALL hide the vehicle registration column

2.5 WHEN a non-automotive organisation creates a quote THEN the system SHALL hide the vehicle selector

2.6 WHEN a non-automotive organisation views a quote detail THEN the system SHALL hide the vehicle info section

2.7 WHEN a non-automotive organisation views the Job Card List page THEN the system SHALL hide the vehicle column

2.8 WHEN a non-automotive organisation creates a job card THEN the system SHALL hide the vehicle selector

2.9 WHEN a non-automotive organisation views a job card detail THEN the system SHALL hide the vehicle info section

2.10 WHEN a non-automotive organisation creates a booking THEN the system SHALL hide the vehicle selector in the booking form

2.11 WHEN a non-automotive organisation navigates directly to `/vehicles` or `/vehicles/:id` via URL THEN the system SHALL redirect the user to `/dashboard`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN an automotive organisation views the Invoice List page THEN the system SHALL CONTINUE TO display the vehicle registration column

3.2 WHEN an automotive organisation creates an invoice THEN the system SHALL CONTINUE TO render the `VehicleLiveSearch` vehicle selector

3.3 WHEN an automotive organisation views an invoice detail THEN the system SHALL CONTINUE TO show the vehicle info section

3.4 WHEN an automotive organisation views the Quote List page THEN the system SHALL CONTINUE TO display the vehicle registration column

3.5 WHEN an automotive organisation creates a quote THEN the system SHALL CONTINUE TO render the vehicle selector

3.6 WHEN an automotive organisation views a quote detail THEN the system SHALL CONTINUE TO show the vehicle info section

3.7 WHEN an automotive organisation views the Job Card List page THEN the system SHALL CONTINUE TO display the vehicle column

3.8 WHEN an automotive organisation creates a job card THEN the system SHALL CONTINUE TO render the vehicle selector

3.9 WHEN an automotive organisation views a job card detail THEN the system SHALL CONTINUE TO show the vehicle info section

3.10 WHEN an automotive organisation creates a booking THEN the system SHALL CONTINUE TO render the vehicle selector in the booking form

3.11 WHEN an automotive organisation navigates to `/vehicles` or `/vehicles/:id` THEN the system SHALL CONTINUE TO render the vehicle pages normally

3.12 WHEN an organisation with a null `tradeFamily` value views any page THEN the system SHALL CONTINUE TO treat the organisation as automotive for backward compatibility (showing all vehicle UI)

3.13 WHEN the sidebar Vehicles nav item is displayed for automotive organisations THEN the system SHALL CONTINUE TO show it correctly

3.14 WHEN the CataloguePage Parts/Fluids tabs are displayed for automotive organisations THEN the system SHALL CONTINUE TO show them correctly
