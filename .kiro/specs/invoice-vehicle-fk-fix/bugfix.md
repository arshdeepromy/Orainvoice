# Bugfix Requirements Document

## Introduction

When creating an invoice for a customer with a manually-entered org-scoped vehicle (one that exists in `org_vehicles` but NOT in `global_vehicles`), the `create_invoice()` function crashes with a `ForeignKeyViolationError`. The API returns a 503 to the user. This happens because the auto-link logic in `create_invoice()` always inserts into `customer_vehicles` using the `global_vehicle_id` column, even when the vehicle ID actually belongs to an `org_vehicles` record with no corresponding `global_vehicles` row. The `customer_vehicles` table has a foreign key constraint on `global_vehicle_id` referencing `global_vehicles.id`, so the insert fails.

The same pattern exists in `update_invoice()` where vehicle-related updates (service due date, WOF expiry) assume the vehicle ID is always a global vehicle.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a user creates an invoice with a vehicle ID that belongs to an org-scoped vehicle (exists in `org_vehicles` but NOT in `global_vehicles`) THEN the system crashes with a `ForeignKeyViolationError` on the `customer_vehicles` table because it attempts to insert the ID into the `global_vehicle_id` column

1.2 WHEN a user creates an invoice with an org-scoped vehicle and the auto-link logic runs THEN the system always populates `global_vehicle_id` on the `CustomerVehicle` record, violating the foreign key constraint `fk_customer_vehicles_global_vehicle_id`

1.3 WHEN a user creates an invoice with an org-scoped vehicle THEN the API returns a 503 error instead of successfully creating the invoice

1.4 WHEN a user updates a draft invoice with an org-scoped vehicle ID and provides a service due date or WOF expiry THEN the system queries `global_vehicles` for that ID and fails to find it, silently skipping the vehicle metadata update

### Expected Behavior (Correct)

2.1 WHEN a user creates an invoice with a vehicle ID that belongs to an org-scoped vehicle THEN the system SHALL determine whether the ID exists in `global_vehicles` or `org_vehicles` and use the correct column (`global_vehicle_id` or `org_vehicle_id`) when inserting into `customer_vehicles`

2.2 WHEN a user creates an invoice with an org-scoped vehicle and the auto-link logic runs THEN the system SHALL populate `org_vehicle_id` (not `global_vehicle_id`) on the `CustomerVehicle` record, satisfying the CHECK constraint and foreign key constraints

2.3 WHEN a user creates an invoice with an org-scoped vehicle THEN the system SHALL successfully create the invoice and return a 201 response with the invoice data

2.4 WHEN a user updates a draft invoice with an org-scoped vehicle ID and provides a service due date or WOF expiry THEN the system SHALL update the `org_vehicles` record with the provided metadata instead of only checking `global_vehicles`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a user creates an invoice with a vehicle ID that exists in `global_vehicles` THEN the system SHALL CONTINUE TO auto-link the customer to the vehicle using `global_vehicle_id` in the `customer_vehicles` table

3.2 WHEN a user creates an invoice with a global vehicle and the customer is already linked to that vehicle THEN the system SHALL CONTINUE TO skip creating a duplicate `customer_vehicles` link

3.3 WHEN a user creates an invoice with a global vehicle and provides an odometer reading THEN the system SHALL CONTINUE TO record the odometer reading against the global vehicle

3.4 WHEN a user creates an invoice with a global vehicle and provides a service due date THEN the system SHALL CONTINUE TO update the service due date on the `global_vehicles` record

3.5 WHEN a user creates an invoice with a global vehicle and provides a WOF expiry date THEN the system SHALL CONTINUE TO update the WOF expiry on the `global_vehicles` record

3.6 WHEN a user creates an invoice without any vehicle ID THEN the system SHALL CONTINUE TO skip the auto-link logic entirely and create the invoice without vehicle linking

3.7 WHEN a user updates a draft invoice with a global vehicle ID THEN the system SHALL CONTINUE TO update service due date and WOF expiry on the `global_vehicles` record

---

### Bug Condition (Formal)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type InvoiceCreateInput
  OUTPUT: boolean
  
  // Returns true when the provided vehicle ID exists only in org_vehicles
  // and has no corresponding row in global_vehicles
  RETURN X.global_vehicle_id IS NOT NULL
     AND X.global_vehicle_id NOT IN global_vehicles.id
     AND X.global_vehicle_id IN org_vehicles.id
END FUNCTION
```

### Fix Checking Property

```pascal
// Property: Fix Checking — Org-scoped vehicle linking
FOR ALL X WHERE isBugCondition(X) DO
  result ← create_invoice'(X)
  ASSERT no_crash(result)
  ASSERT result.status_code = 201
  ASSERT customer_vehicle_link.org_vehicle_id = X.global_vehicle_id
  ASSERT customer_vehicle_link.global_vehicle_id IS NULL
END FOR
```

### Preservation Checking Property

```pascal
// Property: Preservation Checking — Global vehicle linking unchanged
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT create_invoice(X) = create_invoice'(X)
END FOR
```
