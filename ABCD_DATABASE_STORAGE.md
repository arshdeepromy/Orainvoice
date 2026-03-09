# ABCD Lookup Database Storage

## Change Summary
Updated the ABCD test endpoint to store vehicle data in the `global_vehicles` database, just like the regular lookup does.

## Previous Behavior
- ABCD test endpoint only returned data
- Did NOT store in database
- Data was lost after the test

## New Behavior
- ABCD test endpoint stores data in `global_vehicles` table
- Creates new record if vehicle doesn't exist
- Updates existing record if vehicle already exists
- Sets `lookup_type='abcd'` to track API used
- Does NOT increment org usage counters (still a test endpoint)

## Implementation

### Database Storage Logic
**File:** `app/modules/admin/router.py`

```python
# After successful ABCD lookup:

# 1. Check if vehicle exists
existing_result = await db.execute(
    select(GlobalVehicle).where(GlobalVehicle.rego == rego)
)
existing_vehicle = existing_result.scalar_one_or_none()

if existing_vehicle:
    # 2a. Update existing record
    existing_vehicle.make = result.make
    existing_vehicle.model = result.model
    # ... update all fields ...
    existing_vehicle.lookup_type = result.lookup_type  # 'abcd'
    await db.flush()
    await db.commit()
else:
    # 2b. Create new record
    new_vehicle = _carjam_data_to_global_vehicle(result)
    db.add(new_vehicle)
    await db.flush()
    await db.commit()
```

### Response Changes
Added `stored: true` to response:

```json
{
  "success": true,
  "message": "Vehicle found and stored: TOYOTA NOAH",
  "data": { ... },
  "source": "carjam_abcd",
  "mvr_used": true,
  "attempts": 2,
  "stored": true
}
```

## Data Flow

### Scenario 1: New Vehicle (ABCD Lookup)
1. Admin tests ABCD lookup for "ABC123"
2. ABCD API returns vehicle data
3. New record created in `global_vehicles`:
   - `rego='ABC123'`
   - `lookup_type='abcd'`
   - All vehicle fields populated
4. Response: "Vehicle found and stored"

### Scenario 2: Existing Vehicle (Update)
1. Vehicle "QTD216" already exists with `lookup_type='basic'`
2. Admin tests ABCD lookup for "QTD216"
3. Existing record updated:
   - All fields refreshed with ABCD data
   - `lookup_type` changed to `'abcd'`
   - `last_pulled_at` updated
4. Response: "Vehicle found and stored"

### Scenario 3: Subsequent Lookups
1. Vehicle "ABC123" exists with `lookup_type='abcd'`
2. User does regular lookup for "ABC123"
3. Cache hit - returns existing data
4. Shows `lookup_type='abcd'` in response
5. No API call needed

## Benefits

### 1. Data Persistence
- ABCD test data is now saved
- Can be used for future lookups
- Reduces API calls

### 2. Cost Tracking
- `lookup_type='abcd'` tracks which API was used
- Can analyze cost savings from ABCD API
- Billing reports can separate basic vs ABCD

### 3. Cache Building
- Admin can pre-populate cache with ABCD lookups
- Lower cost way to build vehicle database
- Useful for bulk imports

### 4. Data Quality
- Know which vehicles have ABCD vs full data
- Can refresh specific vehicles with full API if needed
- Audit trail of data sources

## Database State

### Query Examples

```sql
-- Find all ABCD lookups
SELECT rego, make, model, lookup_type, last_pulled_at
FROM global_vehicles
WHERE lookup_type = 'abcd'
ORDER BY last_pulled_at DESC;

-- Count by lookup type
SELECT lookup_type, COUNT(*) as count
FROM global_vehicles
GROUP BY lookup_type;

-- Find vehicles that need full data refresh
SELECT rego, make, model, lookup_type
FROM global_vehicles
WHERE lookup_type = 'abcd'
  AND last_pulled_at < NOW() - INTERVAL '30 days';
```

### Example Records

```
rego    | make   | model | lookup_type | last_pulled_at
--------|--------|-------|-------------|-------------------
QTD216  | TOYOTA | NOAH  | basic       | 2026-03-09 02:41
ABC123  | HONDA  | CIVIC | abcd        | 2026-03-09 16:30
XYZ789  | MAZDA  | CX-5  | abcd        | 2026-03-09 16:35
```

## Usage Counter Behavior

### ABCD Test Endpoint
- ✅ Stores in database
- ❌ Does NOT increment org usage counter
- ❌ Does NOT charge org
- Purpose: Admin testing and cache building

### Regular Lookup Endpoint
- ✅ Stores in database (if not cached)
- ✅ Increments org usage counter (if not cached)
- ✅ Charges org (if not cached)
- Purpose: Production vehicle lookups

## UI Indication

### Vehicle Details Modal
Shows lookup type with color coding:
- **Basic (Full Data)** - Green text
- **ABCD (Lower Cost)** - Blue text

### Search Results
Can see which vehicles were looked up with ABCD API.

## Future Enhancements

### 1. Bulk ABCD Import
```python
# Admin can import list of regos using ABCD
POST /api/v1/admin/integrations/carjam/bulk-abcd
{
  "regos": ["ABC123", "XYZ789", "DEF456"],
  "use_mvr": false
}
```

### 2. Automatic Upgrade
```python
# Automatically upgrade ABCD data to full data when needed
if vehicle.lookup_type == 'abcd' and needs_full_data:
    await client.lookup_vehicle(rego)  # Full API
    vehicle.lookup_type = 'basic'
```

### 3. Cost Analytics
```sql
-- Calculate cost savings from ABCD
SELECT 
  COUNT(*) FILTER (WHERE lookup_type = 'abcd') as abcd_count,
  COUNT(*) FILTER (WHERE lookup_type = 'basic') as basic_count,
  COUNT(*) FILTER (WHERE lookup_type = 'abcd') * 0.05 as abcd_cost,
  COUNT(*) FILTER (WHERE lookup_type = 'basic') * 0.15 as basic_cost
FROM global_vehicles;
```

## Testing

### Test Case 1: New ABCD Lookup
```bash
# Before: No record in database
SELECT * FROM global_vehicles WHERE rego = 'TEST123';
# Result: 0 rows

# Do ABCD lookup
POST /api/v1/admin/integrations/carjam/lookup-test-abcd
{"rego": "TEST123", "use_mvr": true}

# After: Record exists
SELECT rego, lookup_type FROM global_vehicles WHERE rego = 'TEST123';
# Result: TEST123 | abcd
```

### Test Case 2: Update Existing
```bash
# Before: Record exists with basic
SELECT rego, lookup_type FROM global_vehicles WHERE rego = 'QTD216';
# Result: QTD216 | basic

# Do ABCD lookup
POST /api/v1/admin/integrations/carjam/lookup-test-abcd
{"rego": "QTD216", "use_mvr": true}

# After: Record updated to abcd
SELECT rego, lookup_type FROM global_vehicles WHERE rego = 'QTD216';
# Result: QTD216 | abcd
```

### Test Case 3: Verify in UI
1. Do ABCD lookup for a vehicle
2. Go to Settings > Vehicle DB
3. Search for the vehicle
4. Click "View Details"
5. Should show "ABCD (Lower Cost)" in blue

## Files Modified

1. `app/modules/admin/router.py` - Added database storage to ABCD test endpoint

## Status
✅ **COMPLETE** - ABCD lookups now store data in global_vehicles database with `lookup_type='abcd'`.

Test it now - do an ABCD lookup and then search for the vehicle in the Vehicle DB to see it stored!
