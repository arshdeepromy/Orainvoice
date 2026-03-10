# Requirements Document

## Introduction

Enhancements to the existing "New Booking" modal (`BookingForm.tsx`) in the internal booking management interface. The modal currently supports customer search, a plain-text vehicle rego field, a plain-text service type field, and a single "Send confirmation email/SMS to customer" checkbox. This feature set upgrades each of these areas: inline customer creation when no match is found, vehicle registration lookup gated behind the `vehicles` module (reusing existing `VehicleLiveSearch` component), service type selection with pricing from the `service_catalogue` table with inline add, and subscription-aware split confirmation/reminder notifications.

## Glossary

- **Booking_Modal**: The `BookingForm` React component rendered as a dialog for creating or editing bookings within the internal staff interface.
- **Customer_Search**: The typeahead search field in the Booking_Modal that queries the `/customers` API endpoint by name, phone, or email.
- **Inline_Customer_Form**: A collapsible form section within the Booking_Modal that allows creating a new customer without navigating away.
- **Vehicle_Rego_Field**: The vehicle registration input in the Booking_Modal, powered by the existing `VehicleLiveSearch` component.
- **Vehicles_Module**: The optional `vehicles` module gated by `ModuleService.is_enabled(org_id, "vehicles")` on the backend and `useModules().isEnabled('vehicles')` / `<ModuleGate module="vehicles">` on the frontend.
- **Service_Selector**: The service type field in the Booking_Modal that searches the `service_catalogue` table and displays pricing.
- **Inline_Service_Form**: A collapsible form section within the Booking_Modal that allows creating a new service catalogue entry without navigating away.
- **Service_Catalogue**: The `service_catalogue` database table storing organisation-scoped services with name, description, default_price, category, and active status.
- **Subscription_Plan**: The organisation's active subscription plan record containing `sms_included` (boolean) and `sms_included_quota` (integer) fields that determine SMS capability.
- **Confirmation_Notification**: An email or SMS message sent to the customer immediately upon booking creation.
- **Reminder_Notification**: A scheduled email or SMS message sent to the customer before the booking's scheduled time.
- **Booking_Service**: The backend `app/modules/bookings/service.py` module responsible for booking CRUD operations.
- **Notification_Service**: The backend `app/modules/notifications/service.py` module responsible for sending and scheduling notifications.

## Requirements

### Requirement 1: Customer Field with Inline Add

**User Story:** As a staff member, I want to add a new customer directly from the booking modal when no existing customer matches my search, so that I can complete the booking without leaving the modal.

#### Acceptance Criteria

1. WHEN the staff member types at least 2 characters into the Customer_Search field, THE Booking_Modal SHALL display matching customers from the `/customers` API in a dropdown list.
2. WHEN the Customer_Search returns zero results and the search query contains at least 2 characters, THE Booking_Modal SHALL display an "Add new customer" option at the bottom of the dropdown.
3. WHEN the staff member selects the "Add new customer" option, THE Booking_Modal SHALL expand an Inline_Customer_Form below the customer search field with fields for first name, last name, email, and phone.
4. WHEN the staff member submits the Inline_Customer_Form with a valid first name and last name, THE Booking_Modal SHALL create the customer via the existing customer creation API endpoint and auto-select the newly created customer for the booking.
5. IF the Inline_Customer_Form submission fails due to a validation error, THEN THE Booking_Modal SHALL display the error message inline below the Inline_Customer_Form without closing the form.
6. WHEN the staff member selects an existing customer from the dropdown, THE Booking_Modal SHALL hide the Inline_Customer_Form if it was previously expanded.
7. THE Inline_Customer_Form SHALL pre-populate the first name field with the current search query text when the search query appears to be a name.

### Requirement 2: Vehicle Rego Field with Module Gating

**User Story:** As a staff member at an automotive organisation, I want to search and select a vehicle by registration number in the booking modal, so that the booking is linked to the correct vehicle.

#### Acceptance Criteria

1. WHILE the Vehicles_Module is enabled for the organisation, THE Booking_Modal SHALL display the Vehicle_Rego_Field using the existing `VehicleLiveSearch` component.
2. WHILE the Vehicles_Module is disabled for the organisation, THE Booking_Modal SHALL hide the Vehicle_Rego_Field completely.
3. THE Vehicle_Rego_Field SHALL be optional and allow the staff member to leave it empty.
4. WHEN the staff member enters a vehicle registration in the Vehicle_Rego_Field, THE Booking_Modal SHALL use the existing vehicle search and lookup logic from the `VehicleLiveSearch` component without duplicating any vehicle search code.
5. WHEN the Booking_Service receives a booking creation request with a `vehicle_rego` value and the Vehicles_Module is disabled, THE Booking_Service SHALL ignore the vehicle_rego field and store null.
6. WHEN the Booking_Service receives a booking creation request with a `vehicle_rego` value and the Vehicles_Module is enabled, THE Booking_Service SHALL store the vehicle_rego on the booking record.

### Requirement 3: Service Type with Pricing and Inline Add

**User Story:** As a staff member, I want to select a service from the organisation's service catalogue with pricing displayed, or add a new service inline, so that bookings have accurate service and pricing information.

#### Acceptance Criteria

1. WHEN the staff member types into the Service_Selector field, THE Booking_Modal SHALL search the Service_Catalogue for active services matching the query and display results with name and default_price in the dropdown.
2. WHEN the staff member selects a service from the Service_Selector dropdown, THE Booking_Modal SHALL populate the service_type field with the selected service name and store the service catalogue entry ID and default_price on the booking.
3. WHEN the Service_Selector search returns zero results and the query contains at least 2 characters, THE Booking_Modal SHALL display an "Add new service" option at the bottom of the dropdown.
4. WHEN the staff member selects the "Add new service" option, THE Booking_Modal SHALL expand an Inline_Service_Form below the Service_Selector with fields for service name, default price, and category.
5. WHEN the staff member submits the Inline_Service_Form with a valid name and price, THE Booking_Modal SHALL create the service via the catalogue API endpoint and auto-select the newly created service for the booking.
6. IF the Inline_Service_Form submission fails due to a validation error, THEN THE Booking_Modal SHALL display the error message inline below the Inline_Service_Form without closing the form.
7. THE Booking_Modal SHALL display the selected service's price next to the service name after selection.
8. WHEN the BookingCreate API schema receives a booking with a service_catalogue_id, THE Booking_Service SHALL store both the service_type name and the service_catalogue_id on the booking record.
9. WHEN the BookingCreate API schema receives a booking with a service_catalogue_id, THE Booking_Service SHALL store the service_price from the catalogue entry on the booking record.

### Requirement 4: Subscription-Aware Booking Confirmation Notifications

**User Story:** As a staff member, I want to send booking confirmation notifications via the channels available on my organisation's subscription plan, so that customers receive confirmations through the appropriate channel.

#### Acceptance Criteria

1. THE Booking_Modal SHALL always display a "Send email confirmation" checkbox when creating a new booking.
2. WHILE the organisation's Subscription_Plan has `sms_included` set to true, THE Booking_Modal SHALL display a "Send SMS confirmation" checkbox in addition to the email checkbox.
3. WHILE the organisation's Subscription_Plan has `sms_included` set to false, THE Booking_Modal SHALL hide the "Send SMS confirmation" checkbox.
4. WHEN the staff member checks the email confirmation checkbox and submits the booking, THE Booking_Service SHALL trigger an email confirmation notification to the customer.
5. WHEN the staff member checks the SMS confirmation checkbox and submits the booking, THE Booking_Service SHALL trigger an SMS confirmation notification to the customer.
6. WHEN neither confirmation checkbox is checked, THE Booking_Service SHALL create the booking without sending any confirmation notification.

### Requirement 5: Booking Reminder Notifications

**User Story:** As a staff member, I want to configure a reminder notification for a booking, so that the customer receives a reminder before their appointment.

#### Acceptance Criteria

1. THE Booking_Modal SHALL display a reminder configuration section when creating a new booking.
2. THE reminder configuration section SHALL offer preset options of 24 hours before, 6 hours before, and a custom time input.
3. WHEN the staff member selects a preset reminder option, THE Booking_Modal SHALL store the selected reminder offset on the booking.
4. WHEN the staff member selects the custom reminder option, THE Booking_Modal SHALL display an input field for specifying the number of hours before the booking.
5. WHEN a booking is created with a reminder configured, THE Booking_Service SHALL schedule a reminder notification for the calculated reminder time (booking scheduled_at minus the reminder offset).
6. WHEN a booking with a scheduled reminder is cancelled, THE Booking_Service SHALL cancel the pending reminder notification.
7. THE Booking_Service SHALL send the reminder notification only once per booking, regardless of booking updates.
8. WHEN the reminder time has already passed at the time of booking creation, THE Booking_Service SHALL skip scheduling the reminder and log a warning.
9. THE reminder notification SHALL use the same channel (email and/or SMS) as the confirmation notification selected during booking creation.

### Requirement 6: Backend Schema and Model Updates

**User Story:** As a developer, I want the booking data model to support the new service pricing, notification preferences, and reminder fields, so that the enhanced booking modal data is persisted correctly.

#### Acceptance Criteria

1. THE Booking model SHALL include a `service_catalogue_id` column as an optional foreign key to the `service_catalogue` table.
2. THE Booking model SHALL include a `service_price` column as an optional decimal field to store the price at time of booking.
3. THE Booking model SHALL include a `send_email_confirmation` boolean column defaulting to false.
4. THE Booking model SHALL include a `send_sms_confirmation` boolean column defaulting to false.
5. THE Booking model SHALL include a `reminder_offset_hours` optional numeric column to store the reminder lead time.
6. THE Booking model SHALL include a `reminder_scheduled_at` optional datetime column to store the calculated reminder send time.
7. THE Booking model SHALL include a `reminder_cancelled` boolean column defaulting to false.
8. THE BookingCreate schema SHALL accept `service_catalogue_id`, `service_price`, `send_email_confirmation`, `send_sms_confirmation`, and `reminder_offset_hours` fields.
9. THE BookingResponse schema SHALL include `service_catalogue_id`, `service_price`, `send_email_confirmation`, `send_sms_confirmation`, `reminder_offset_hours`, `reminder_scheduled_at`, and `reminder_cancelled` fields.
10. THE database migration SHALL be numbered 0081 and add the new columns to the `bookings` table.
