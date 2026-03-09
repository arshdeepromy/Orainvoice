# Lookup Type Tracking Implementation

## Overview
Added `lookup_type` field to track which Carjam API was used for each vehicle lookup - either "basic" (full API) or "abcd" (lower-cost API).

## Why This Matters
- **Cost Tracking**: Know which lookups used the cheaper ABCD API vs full API
- **Data Quality**: Understand data completeness based on API type
- **Billing**: Accurately track API costs per lookup type
- **Analytics**: Report on API usage patterns

## Implementation

### Database Changes

#### Migration
**File:** `alembic/versions/2026_03_09_1600-add_lookup_type_field.py`

```sql
ALTER TABLE global_vehicles 
ADD COLUMN lookup_type VARCHAR(10) DEFAULT 'basic';

UPDATE global_vehicles 
SET lookup_type = 'basic' 
WHERE lookup_type IS NULL;
```

**Values:**
- `basic` - Full Carjam API (default)
- `abcd` - ABCD (Absolute Basic Car Details) API

#### Model Update
**File:** `app/modules/admin/models.py`

```python
class GlobalVehicle(Base):
    # ... existing fields ...
    lookup_type: Mapped[str | None] = mapped_column(
        String(10), 
        nullable=True, 
        server_default='basic'
    )
```

### Backend Changes

#### 1. CarjamVehicleData Dataclass
**File:** `app/integrations/carjam.py`

Added `lookup_type` field to the dataclass:
```python
@dataclass(frozen=True)
class CarjamVehicleData:
    rego: str
    lookup_type: str = "basic"  # "basic" or "abcd"
    # ... other fields ...
```

#### 2. Parsing Function
Updated `_parse_vehicle_response()` to accept and set lookup_type:
```python
def _parse_vehicle_response(
    rego: str, 
    data: dict[str, Any], 
    lookup_type: str = "basic"
) -> CarjamVehicleData:
    return CarjamVehicleData(
        rego=rego.upper().strip(),
        lookup_type=lookup_type,
        # ... other fields ...
    )
```

#### 3. API Methods
Both lookup methods now set the correct type:

```python
# Full API
async def lookup_vehicle(self, rego: str) -> CarjamVehicleData:
    # ...
    return _parse_vehicle_response(rego, vehicle_data, lookup_type="basic")

# ABCD API
async def lookup_vehicle_abcd(self, rego: str, use_mvr: bool = True) -> CarjamVehicleData:
    # ...
    return _parse_vehicle_response(rego, body, lookup_type="abcd")
```

#### 4. Vehicle Service
**File:** `app/modules/vehicles/service.py`

Updated functions to store and return lookup_type:
- `_carjam_data_to_global_vehicle()` - Stores lookup_type when creating record
- `_global_vehicle_to_dict()` - Includes lookup_type in response
- `refresh_vehicle()` - Updates lookup_type on refresh

#### 5. Admin Search Service
**File:** `app/modules/admin/service.py`

Updated SQL query to include lookup_type:
```python
SELECT id, rego, make, model, ..., lookup_type
FROM global_vehicles 
WHERE rego ILIKE :rego
```

#### 6. Response Schema
**File:** `app/modules/admin/schemas.py`

```python
class GlobalVehicleSearchResult(BaseModel):
    # ... existing fields ...
    lookup_type: str | None = None
```

### Frontend Changes

#### 1. TypeScript Interface
**File:** `frontend/src/pages/admin/Settings.tsx`

```typescript
export interface VehicleRecord {
  // ... existing fields ...
  lookup_type: string | null
}
```

#### 2. Vehicle Details Modal
Added lookup_type display in the "Inspection & Odometer" section:

```tsx
<div>
  <p className="text-xs text-gray-500">Lookup Type</p>
  <p className="text-sm font-medium text-gray-900">
    <span className={selectedVehicle.lookup_type === 'abcd' ? 'text-blue-600' : 'text-green-600'}>
      {selectedVehicle.lookup_type === 'abcd' ? 'ABCD (Lower Cost)' : 'Basic (Full Data)'}
    </span>
  </p>
</div>
```

**Visual Indicators:**
- `basic` - Green text: "Basic (Full Data)"
- `abcd` - Blue text: "ABCD (Lower Cost)"

## Data Flow

### New Lookup (Basic API)
1. User requests vehicle lookup
2. `lookup_vehicle()` called → sets `lookup_type="basic"`
3. Data stored in `global_vehicles` with `lookup_type='basic'`
4. Response includes `lookup_type: "basic"`

### New Lookup (ABCD API)
1. Admin tests ABCD lookup
2. `lookup_vehicle_abcd()` called → sets `lookup_type="abcd"`
3. Data stored in `global_vehicles` with `lookup_type='abcd'`
4. Response includes `lookup_type: "abcd"`

### Cached Lookup
1. User requests vehicle lookup
2. Record found in database
3. Returns existing data with original `lookup_type`
4. No API call made

### Refresh
1. Admin refreshes vehicle
2. New API call made (basic or abcd)
3. `lookup_type` updated to reflect new API used
4. All other fields updated

## Database State

### Existing Records
All existing records automatically set to `lookup_type='basic'` by migration.

### New Records
- Basic API lookups: `lookup_type='basic'`
- ABCD API lookups: `lookup_type='abcd'`

### Query Example
```sql
-- Count by lookup type
SELECT lookup_type, COUNT(*) 
FROM global_vehicles 
GROUP BY lookup_type;

-- Find ABCD lookups
SELECT rego, make, model, lookup_type 
FROM global_vehicles 
WHERE lookup_type = 'abcd';
```

## UI Display

### Vehicle Details Modal
Shows lookup type in the "Inspection & Odometer" section:
- **Basic (Full Data)** - Green text
- **ABCD (Lower Cost)** - Blue text

### Search Results
Currently shows in table (can be added as column if needed).

## Benefits

1. **Cost Analysis**: Track which API is being used more
2. **Data Quality**: Understand completeness based on API type
3. **Billing Accuracy**: Separate costs for basic vs ABCD lookups
4. **Audit Trail**: Know exactly how each vehicle was looked up
5. **Future Optimization**: Make informed decisions about API usage

## Future Enhancements

1. Add lookup_type filter in Vehicle DB search
2. Show lookup_type in search results table
3. Add analytics dashboard showing API usage breakdown
4. Implement automatic API selection based on cost/data needs
5. Add lookup_type to billing reports

## Files Modified

1. `alembic/versions/2026_03_09_1600-add_lookup_type_field.py` - New migration
2. `app/modules/admin/models.py` - Added lookup_type field
3. `app/integrations/carjam.py` - Added lookup_type to dataclass and methods
4. `app/modules/vehicles/service.py` - Store and return lookup_type
5. `app/modules/admin/service.py` - Include lookup_type in search
6. `app/modules/admin/schemas.py` - Added lookup_type to schema
7. `frontend/src/pages/admin/Settings.tsx` - Display lookup_type in modal

## Status
✅ **COMPLETE** - Lookup type tracking fully implemented and migrated.

All vehicle lookups now track which API was used, and the information is displayed in the vehicle details modal!
