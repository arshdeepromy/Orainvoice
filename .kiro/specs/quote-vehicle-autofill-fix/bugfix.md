# Bugfix Requirements Document

## Introduction

When a user selects a customer in the Quote creation form (`QuoteCreate.tsx`) that has linked vehicles, the vehicle details do not auto-fill into the vehicle field. This feature works correctly in the Invoice creation form (`InvoiceCreate.tsx`). The root cause is that the local `CustomerSearch` component defined inside `QuoteCreate.tsx` does not pass `include_vehicles: true` to the `/customers` API call and does not support an `onVehicleAutoSelect` callback to trigger vehicle auto-fill when a customer is selected.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a user selects a customer with linked vehicles in the QuoteCreate form THEN the system does not auto-fill the vehicle field with the customer's first linked vehicle

1.2 WHEN the QuoteCreate local `CustomerSearch` component fetches customers from the API THEN the system does not include `include_vehicles: true` in the request params, so linked vehicle data is never returned

1.3 WHEN a customer with linked vehicles is selected in QuoteCreate THEN the system does not invoke any vehicle auto-fill callback because the local `CustomerSearch` component does not accept or call an `onVehicleAutoSelect` prop

### Expected Behavior (Correct)

2.1 WHEN a user selects a customer with linked vehicles in the QuoteCreate form AND no vehicle is currently selected THEN the system SHALL auto-fill the vehicle field with the first linked vehicle's details (id, rego, make, model, year, colour) and set the vehicleRego state

2.2 WHEN the QuoteCreate `CustomerSearch` component fetches customers from the API THEN the system SHALL pass `include_vehicles: true` in the request params so that linked vehicle data is available in the response

2.3 WHEN a customer with linked vehicles is selected in QuoteCreate AND a vehicle is already selected THEN the system SHALL NOT overwrite the existing vehicle selection

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a user selects a vehicle rego in VehicleLiveSearch that has a linked customer THEN the system SHALL CONTINUE TO auto-fill the customer field (vehicle→customer backfill)

3.2 WHEN a user selects a customer with no linked vehicles in QuoteCreate THEN the system SHALL CONTINUE TO select the customer without modifying the vehicle field

3.3 WHEN a user clears the customer selection in QuoteCreate THEN the system SHALL CONTINUE TO clear the customer state without affecting the vehicle field

3.4 WHEN a user searches for customers in QuoteCreate THEN the system SHALL CONTINUE TO perform fuzzy sequential character matching on first name, last name, display name, and phone

3.5 WHEN a user creates a new customer via the "+ Add New Customer" button in QuoteCreate THEN the system SHALL CONTINUE TO create and select the customer normally

---

## Bug Condition (Formal)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type CustomerSelectEvent
  OUTPUT: boolean
  
  // Returns true when a customer with linked vehicles is selected and no vehicle is currently set
  RETURN X.customer.linked_vehicles.length > 0 AND X.currentVehicle = null
END FUNCTION
```

## Property Specification

```pascal
// Property: Fix Checking — Vehicle Auto-Fill on Customer Select
FOR ALL X WHERE isBugCondition(X) DO
  result ← CustomerSearch'.handleSelect(X)
  ASSERT result.vehicle.id = X.customer.linked_vehicles[0].id
  ASSERT result.vehicle.rego = X.customer.linked_vehicles[0].rego
  ASSERT result.vehicle.make = X.customer.linked_vehicles[0].make
  ASSERT result.vehicle.model = X.customer.linked_vehicles[0].model
  ASSERT result.vehicle.year = X.customer.linked_vehicles[0].year
  ASSERT result.vehicle.colour = X.customer.linked_vehicles[0].colour
  ASSERT result.vehicleRego = X.customer.linked_vehicles[0].rego
END FOR
```

## Preservation Goal

```pascal
// Property: Preservation Checking — Non-buggy inputs unchanged
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT CustomerSearch(X) = CustomerSearch'(X)
END FOR
```

This ensures that:
- Customers without linked vehicles behave identically before and after the fix
- Selecting a customer when a vehicle is already chosen does not overwrite the vehicle
- All other CustomerSearch functionality (search, create, clear) remains unchanged
