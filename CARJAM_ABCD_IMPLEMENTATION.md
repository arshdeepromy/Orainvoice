# Carjam ABCD (Absolute Basic Car Details) Implementation

## Overview
Added support for Carjam's ABCD API - a lower-cost alternative to the full vehicle lookup API that provides basic vehicle information.

## What is ABCD?
ABCD (Absolute Basic Car Details) is Carjam's lowest-cost API product that provides adequate vehicle information for basic needs.

### Guaranteed Fields
- plate
- year_of_manufacture
- make
- model
- submodel
- vin (if exists)
- reported_stolen

### Additional Fields (when available)
- chassis, engine_no, cc_rating
- main_colour, second_colour
- country_of_origin
- tare_weight, gross_vehicle_mass
- date_of_first_registration_in_nz
- no_of_seats, fuel_type, vehicle_type, body_style
- transmission, number_of_owners
- wof/rego expiry, odometer
- And many more...

### Key Differences from Full API
1. **Lower Cost**: Cheaper per lookup
2. **MVR Option**: Can optionally access Motor Vehicle Register (+17c NZD)
3. **Async Response**: May return null initially while fetching data (with Refresh header)
4. **No Resale**: Data cannot be resold

## Implementation

### Backend Changes

#### 1. New Method in CarjamClient
**File:** `app/integrations/carjam.py`

```python
async def lookup_vehicle_abcd(self, rego: str, use_mvr: bool = True) -> CarjamVehicleData
```

**Parameters:**
- `rego`: Vehicle registration, VIN, or chassis number
- `use_mvr`: If True, allows fetching from MVR (+17c cost). Default: True

**Endpoint:** `/a/vehicle:abcd`

**Features:**
- Same rate limiting as full API
- Handles Refresh header for async data fetching
- Parses response using existing `_parse_vehicle_response()` function
- Returns same `CarjamVehicleData` dataclass

#### 2. New Test Endpoint
**File:** `app/modules/admin/router.py`

```python
POST /api/v1/admin/integrations/carjam/lookup-test-abcd
```

**Request Body:**
```json
{
  "rego": "ABC123",
  "use_mvr": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Vehicle found: TOYOTA NOAH",
  "data": { ... vehicle data ... },
  "source": "carjam_abcd",
  "mvr_used": true
}
```

**Features:**
- Admin-only endpoint (global_admin role required)
- Does NOT cache results
- Does NOT increment org usage counters
- 30-second timeout protection
- Proper error handling for all Carjam errors

### Frontend Changes

#### 1. New State Variables
**File:** `frontend/src/pages/admin/Integrations.tsx`

```typescript
const [abcdRego, setAbcdRego] = useState('')
const [abcdUseMvr, setAbcdUseMvr] = useState(true)
const [abcdTesting, setAbcdTesting] = useState(false)
const [abcdResult, setAbcdResult] = useState<...>(null)
```

#### 2. New Handler Function
```typescript
const handleAbcdLookup = async () => { ... }
```

Calls the ABCD test endpoint with rego and MVR option.

#### 3. New UI Section
Added "Test ABCD Lookup (Lower Cost)" section in Carjam integration page:

**Features:**
- Registration input field
- MVR checkbox (with cost warning)
- "ABCD Lookup" button
- Result display showing:
  - Source indicator (Carjam ABCD API)
  - MVR status (Enabled +17c / Disabled)
  - All available vehicle data
  - Stolen status with visual indicators

## Usage

### Admin Testing

1. Navigate to **Admin Console > Integrations > Carjam**
2. Scroll to **"Test ABCD Lookup (Lower Cost)"** section
3. Optionally uncheck "Use Motor Vehicle Register" to save 17c
4. Enter a registration number (e.g., "QTD216")
5. Click **"ABCD Lookup"**
6. View results showing all available data

### API Integration

```python
from app.integrations.carjam import CarjamClient
from app.core.redis import redis_pool

client = CarjamClient(
    redis=redis_pool,
    api_key="your_api_key",
    base_url="https://www.carjam.co.nz"
)

# With MVR access (+17c)
vehicle = await client.lookup_vehicle_abcd("ABC123", use_mvr=True)

# Without MVR access (cheaper)
vehicle = await client.lookup_vehicle_abcd("ABC123", use_mvr=False)
```

## Cost Comparison

| API Type | Cost | Data Completeness | Use Case |
|----------|------|-------------------|----------|
| Full API | Higher | Complete | Production lookups with caching |
| ABCD | Lower | Basic + extras | Testing, basic info needs |
| ABCD + MVR | Lower + 17c | Basic + MVR data | When MVR data needed |

## Error Handling

### Refresh Header
If Carjam is still fetching data, it returns:
- Null response body
- `Refresh: <seconds>` header

The implementation raises `CarjamError` with retry message.

### Rate Limiting
Uses the same global rate limiting as full API (shared counter).

### Timeouts
30-second timeout on test endpoint to prevent hanging.

## Testing

### Test Case 1: Basic ABCD Lookup
```bash
# Request
POST /api/v1/admin/integrations/carjam/lookup-test-abcd
{
  "rego": "QTD216",
  "use_mvr": false
}

# Expected: Vehicle data without MVR access
```

### Test Case 2: ABCD with MVR
```bash
# Request
POST /api/v1/admin/integrations/carjam/lookup-test-abcd
{
  "rego": "QTD216",
  "use_mvr": true
}

# Expected: Vehicle data with MVR access (+17c cost)
```

### Test Case 3: Invalid Rego
```bash
# Request
POST /api/v1/admin/integrations/carjam/lookup-test-abcd
{
  "rego": "INVALID123",
  "use_mvr": true
}

# Expected: 404 Not Found
```

## Files Modified

1. `app/integrations/carjam.py` - Added `lookup_vehicle_abcd()` method
2. `app/modules/admin/router.py` - Added ABCD test endpoint
3. `frontend/src/pages/admin/Integrations.tsx` - Added ABCD test UI

## Future Enhancements

1. Add ABCD option to production vehicle lookup service
2. Store ABCD lookup costs separately in billing
3. Add ABCD usage analytics
4. Implement automatic fallback from full API to ABCD based on cost settings

## Status
✅ **COMPLETE** - ABCD lookup fully implemented and ready for testing.

Test it now in Admin Console > Integrations > Carjam > Test ABCD Lookup section!
