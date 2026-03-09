# Vehicle Details Modal Implementation

## Feature
Added a comprehensive vehicle details modal that displays all Carjam data when clicking on a vehicle in the Global Vehicle Database search results.

## Implementation

### Frontend Changes

#### 1. Updated VehicleRecord Interface
Added all extended Carjam fields to the TypeScript interface:
- VIN, chassis, engine number
- Transmission, country of origin
- Number of owners, vehicle type
- Reported stolen status
- Power (kW), tare weight, gross vehicle mass
- Date first registered in NZ
- Plate type, submodel, second colour

**File:** `frontend/src/pages/admin/Settings.tsx`

#### 2. Added Modal Component
Created a detailed modal with organized sections:
- **Basic Information**: Rego, make, model, submodel, year, body type, colours
- **Technical Specifications**: VIN, chassis, engine, fuel, transmission, power, seats
- **Weight & Dimensions**: Tare weight, gross vehicle mass
- **Registration & Compliance**: Plate type, vehicle type, country, first registration date, owners, stolen status
- **Inspection & Odometer**: WOF expiry, rego expiry, odometer, last pulled date

#### 3. Added View Details Button
Added a "View Details" button in the search results table that opens the modal.

#### 4. Modal Features
- Clean, organized layout with sections
- Proper formatting for dates, numbers, and units
- Visual indicators for stolen status (⚠️ Yes / ✓ No)
- "Refresh from Carjam" button in modal footer
- Close button to dismiss modal

### Backend Changes

#### 1. Updated Search Query
Extended the SQL query to include all 15 additional Carjam fields:

**File:** `app/modules/admin/service.py`

```python
SELECT id, rego, make, model, year, colour, body_type, fuel_type, 
       engine_size, num_seats, wof_expiry, registration_expiry, 
       odometer_last_recorded, last_pulled_at, created_at,
       vin, chassis, engine_no, transmission, country_of_origin,
       number_of_owners, vehicle_type, reported_stolen, power_kw,
       tare_weight, gross_vehicle_mass, date_first_registered_nz,
       plate_type, submodel, second_colour
FROM global_vehicles 
WHERE rego ILIKE :rego 
ORDER BY rego 
LIMIT 50
```

#### 2. Updated Response Schema
Added all extended fields to `GlobalVehicleSearchResult`:

**File:** `app/modules/admin/schemas.py`

```python
class GlobalVehicleSearchResult(BaseModel):
    # ... basic fields ...
    # Extended Carjam fields
    vin: str | None = None
    chassis: str | None = None
    engine_no: str | None = None
    transmission: str | None = None
    country_of_origin: str | None = None
    number_of_owners: int | None = None
    vehicle_type: str | None = None
    reported_stolen: str | None = None
    power_kw: int | None = None
    tare_weight: int | None = None
    gross_vehicle_mass: int | None = None
    date_first_registered_nz: str | None = None
    plate_type: str | None = None
    submodel: str | None = None
    second_colour: str | None = None
```

## User Experience

### How to Use
1. Navigate to **Admin Console > Settings > Vehicle DB** tab
2. Search for a vehicle by registration (e.g., "QTD216")
3. Click the **"View Details"** button on any search result
4. Modal opens showing all available Carjam data organized in sections
5. Click **"Refresh from Carjam"** to update the data
6. Click **"Close"** to dismiss the modal

### Data Display
- Fields with data show the actual values
- Empty fields show "—" (em dash)
- Dates are formatted as "9 Mar 2026, 15:41"
- Numbers include proper units (kg, kW, cc, km)
- Stolen status shows visual indicators

## Example Data (QTD216)

**Basic Information:**
- Registration: QTD216
- Make: TOYOTA
- Model: NOAH
- Year: 2014
- Body Type: SW
- Colour: Grey

**Technical Specifications:**
- VIN: 7AT0H64NX24011160
- Chassis: ZWR80-0011160
- Engine Number: 2ZR-6056746
- Engine Size: 1797 cc
- Fuel Type: 07
- Seats: 7

**Weight & Dimensions:**
- Gross Vehicle Mass: 1995 kg

**Registration & Compliance:**
- Plate Type: ST (Standard)
- Vehicle Type: 07
- Country of Origin: JPN (Japan)
- First Registered NZ: 26 Aug 2024
- Reported Stolen: ✓ No

**Inspection & Odometer:**
- WOF Expiry: 17 Jul 2026
- Registration Expiry: 25 Aug 2026
- Odometer: 162,207 km
- Last Pulled: 9 Mar 2026, 15:41

## Files Modified

1. `frontend/src/pages/admin/Settings.tsx` - Added modal UI and state management
2. `app/modules/admin/service.py` - Extended search query with all fields
3. `app/modules/admin/schemas.py` - Added extended fields to response schema

## Status
✅ **COMPLETE** - Vehicle details modal fully implemented with all Carjam extended fields.
