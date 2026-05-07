/**
 * Shared TypeScript interfaces for the kiosk vehicle check-in flow.
 *
 * Field names match the backend Pydantic schemas in app/modules/kiosk/schemas.py exactly.
 *
 * Requirements: 4.1, 6.1, 9.3
 */

/** Matches KioskVehicleLookupResponse — result from POST /kiosk/vehicle-lookup */
export interface VehicleLookupResult {
  id: string
  rego: string
  make: string | null
  model: string | null
  body_type: string | null
  year: number | null
  colour: string | null
  wof_expiry: string | null
  cof_expiry: string | null
  inspection_type: string | null
  rego_expiry: string | null
  odometer: number | null
  source: string
}

/** Vehicle entry collected during a kiosk session (frontend-enriched) */
export interface KioskVehicleEntry {
  global_vehicle_id: string
  rego: string
  make: string | null
  model: string | null
  body_type: string | null
  year: number | null
  wof_expiry: string | null
  rego_expiry: string | null
  last_odometer: number | null
  odometer_km: number | null
}

/** Form fields on the Customer Details screen */
export interface KioskFormData {
  first_name: string
  last_name: string
  phone: string
  email: string
}

/** Data displayed on the success screen after check-in */
export interface KioskSuccessData {
  customer_first_name: string
}

/** Matches KioskCustomerMatch — a customer match for auto-fill */
export interface AutoFillMatch {
  id: string
  first_name: string
  last_name: string
  phone: string | null
  email: string | null
}

/** Matches KioskCheckInRequestV2 — submission payload for POST /kiosk/check-in */
export interface CheckInPayload {
  first_name: string
  last_name: string
  phone: string
  email: string | null
  vehicles: Array<{ global_vehicle_id: string; odometer_km: number | null }>
  existing_customer_id: string | null
}

/** Matches KioskCheckInResponseV2 — response from POST /kiosk/check-in */
export interface CheckInResponse {
  customer_first_name: string
  is_new_customer: boolean
  vehicles_linked: number
}
