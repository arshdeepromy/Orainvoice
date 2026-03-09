# Vehicle DB Search Fix

## Issue
The Vehicle DB search in Platform Settings was not displaying results even though the backend was returning data successfully (HTTP 200).

## Root Cause
**Frontend-Backend Response Mismatch:**

- **Backend returns:** `{results: VehicleRecord[], total: number}`
- **Frontend expected:** `VehicleRecord[]` (array directly)

The frontend code was trying to use `res.data` as an array, but it was actually an object with a `results` property.

## Files Modified

### frontend/src/pages/admin/Settings.tsx
**Before:**
```typescript
const res = await apiClient.get<VehicleRecord[]>(`/admin/vehicle-db/search/${encodeURIComponent(searchRego.trim())}`)
setSearchResults(Array.isArray(res.data) ? res.data : [res.data])
```

**After:**
```typescript
const res = await apiClient.get<{ results: VehicleRecord[], total: number }>(`/admin/vehicle-db/search/${encodeURIComponent(searchRego.trim())}`)
setSearchResults(res.data.results || [])
```

### app/modules/admin/service.py
Added logging to track search results:
```python
logger.info(f"Vehicle DB search for '{rego}': found {len(results)} results")
```

## Backend Implementation (Verified Correct)

### Endpoint
`GET /api/v1/admin/vehicle-db/search/{rego}`

### Service Function
`search_global_vehicles()` in `app/modules/admin/service.py`

### Response Schema
```python
class GlobalVehicleSearchResponse(BaseModel):
    results: list[GlobalVehicleSearchResult]
    total: int
```

### SQL Query
```sql
SELECT id, rego, make, model, year, colour, body_type, fuel_type, 
       engine_size, num_seats, wof_expiry, registration_expiry, 
       odometer_last_recorded, last_pulled_at, created_at 
FROM global_vehicles 
WHERE rego ILIKE :rego 
ORDER BY rego 
LIMIT 50
```

Uses `ILIKE` for case-insensitive partial matching with `%{rego}%` pattern.

## Testing

### Test Case
- Search for: `QTD216`
- Expected: 1 result (TOYOTA NOAH 2014)
- Database confirmed: Record exists with all extended fields populated

### Verification
1. Backend logs show SQL query executing successfully
2. HTTP 200 OK responses
3. Frontend now properly extracts `results` array from response object

## Status
✅ **FIXED** - Frontend now correctly handles the backend response format.

The search will now display results in the table when you search for a vehicle registration.
