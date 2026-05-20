/**
 * Pure utility for building the ordered list of vehicle display fields
 * shown on invoices across all rendering surfaces.
 *
 * This function encapsulates the conditional display logic for vehicle info:
 * - Display order: Registration → Vehicle → Odometer/Service Due → WOF/COF Expiry
 * - Service Due replaces Odometer when service_due_updated is true
 * - WOF/COF shown conditionally based on update flags and date comparison
 * - Null/empty fields are omitted entirely
 * - Backward compatibility: when vehicleDisplay is null, uses fallback fields
 */

export interface VehicleDisplayData {
  rego: string | null
  make: string | null
  model: string | null
  year: number | null
  odometer: number | null
  inspection_type: 'wof' | 'cof' | null
  wof_expiry: string | null       // ISO date string
  cof_expiry: string | null       // ISO date string
  service_due_date: string | null  // ISO date string
  wof_updated: boolean
  cof_updated: boolean
  service_due_updated: boolean
}

export interface VehicleDisplayField {
  label: string
  value: string
  hint?: string
}

/**
 * Formats a number with thousands separators (e.g. 125000 → "125,000").
 */
function formatNumber(n: number): string {
  return n.toLocaleString('en-NZ')
}

/**
 * Builds the vehicle make/model/year combined string.
 * Returns null if no components are present.
 */
function buildVehicleString(
  make: string | null | undefined,
  model: string | null | undefined,
  year: number | null | undefined,
): string | null {
  const parts: string[] = []
  if (year != null && year > 0) parts.push(String(year))
  if (make) parts.push(make)
  if (model) parts.push(model)
  return parts.length > 0 ? parts.join(' ') : null
}

/**
 * Builds the ordered array of vehicle display fields for an invoice.
 *
 * @param vehicleDisplay - The vehicle display data stored in invoice_data_json, or null for old invoices
 * @param issueDate - The invoice issue date (ISO string) used for future/past comparison
 * @param fallback - Fallback fields from invoice columns for backward compatibility
 * @returns Ordered array of fields to display (empty fields omitted)
 */
export function buildVehicleDisplayFields(
  vehicleDisplay: VehicleDisplayData | null | undefined,
  issueDate: string,
  fallback?: {
    vehicle_rego?: string | null
    vehicle_make?: string | null
    vehicle_model?: string | null
    vehicle_year?: number | null
    vehicle_odometer?: number | null
    vehicle?: { wof_expiry?: string; cof_expiry?: string; inspection_type?: string } | null
  },
): VehicleDisplayField[] {
  // Backward compatibility: when vehicleDisplay is null/undefined, use fallback fields
  // and show all available data without conditional logic
  if (vehicleDisplay == null) {
    return buildFallbackFields(fallback)
  }

  const fields: VehicleDisplayField[] = []

  // 1. Registration
  if (vehicleDisplay.rego) {
    fields.push({ label: 'Registration', value: vehicleDisplay.rego })
  }

  // 2. Vehicle (make/model/year combined)
  const vehicleStr = buildVehicleString(
    vehicleDisplay.make,
    vehicleDisplay.model,
    vehicleDisplay.year,
  )
  if (vehicleStr) {
    fields.push({ label: 'Vehicle', value: vehicleStr })
  }

  // 3. Odometer OR Service Due Date (mutually exclusive)
  if (vehicleDisplay.service_due_updated) {
    // Service Due replaces Odometer when updated
    if (vehicleDisplay.service_due_date) {
      const field: VehicleDisplayField = {
        label: 'Service Due',
        value: vehicleDisplay.service_due_date,
      }
      // Add hint when odometer is a positive value
      if (vehicleDisplay.odometer != null && vehicleDisplay.odometer > 0) {
        field.hint = `or due at ${formatNumber(vehicleDisplay.odometer + 10000)} km`
      }
      fields.push(field)
    }
  } else {
    // Show odometer when service_due_updated is false and odometer has a value
    if (vehicleDisplay.odometer != null && vehicleDisplay.odometer > 0) {
      fields.push({
        label: 'Odometer',
        value: `${formatNumber(vehicleDisplay.odometer)} km`,
      })
    }
  }

  // 4. WOF/COF Expiry (conditional on flags + date comparison)
  const inspectionType = vehicleDisplay.inspection_type
  if (inspectionType === 'cof') {
    // COF logic
    if (shouldShowExpiry(vehicleDisplay.cof_updated, vehicleDisplay.cof_expiry, issueDate)) {
      fields.push({
        label: 'COF Expiry',
        value: vehicleDisplay.cof_expiry!,
      })
    }
  } else {
    // WOF logic (default when inspection_type is 'wof' or null)
    if (shouldShowExpiry(vehicleDisplay.wof_updated, vehicleDisplay.wof_expiry, issueDate)) {
      fields.push({
        label: 'WOF Expiry',
        value: vehicleDisplay.wof_expiry!,
      })
    }
  }

  return fields
}

/**
 * Determines whether an inspection expiry field should be shown.
 *
 * Rules:
 * - Show when updated flag is true (user changed it during creation)
 * - Show when updated flag is false AND expiry date is strictly after issue date
 * - Hide when updated flag is false AND expiry date is on or before issue date
 * - Hide when expiry date is null/empty
 */
function shouldShowExpiry(
  updated: boolean,
  expiryDate: string | null | undefined,
  issueDate: string,
): boolean {
  if (!expiryDate) return false

  if (updated) return true

  // Compare dates as strings (ISO format allows lexicographic comparison)
  return expiryDate > issueDate
}

/**
 * Builds display fields from fallback data (backward compatibility for old invoices).
 * Shows all available data without conditional logic.
 */
function buildFallbackFields(
  fallback?: {
    vehicle_rego?: string | null
    vehicle_make?: string | null
    vehicle_model?: string | null
    vehicle_year?: number | null
    vehicle_odometer?: number | null
    vehicle?: { wof_expiry?: string; cof_expiry?: string; inspection_type?: string } | null
  },
): VehicleDisplayField[] {
  if (!fallback) return []

  const fields: VehicleDisplayField[] = []

  // Registration
  if (fallback.vehicle_rego) {
    fields.push({ label: 'Registration', value: fallback.vehicle_rego })
  }

  // Vehicle (make/model/year)
  const vehicleStr = buildVehicleString(
    fallback.vehicle_make,
    fallback.vehicle_model,
    fallback.vehicle_year,
  )
  if (vehicleStr) {
    fields.push({ label: 'Vehicle', value: vehicleStr })
  }

  // Odometer (always shown in fallback mode when available)
  if (fallback.vehicle_odometer != null && fallback.vehicle_odometer > 0) {
    fields.push({
      label: 'Odometer',
      value: `${formatNumber(fallback.vehicle_odometer)} km`,
    })
  }

  // WOF/COF Expiry (from vehicle object, no conditional logic in fallback)
  const vehicle = fallback.vehicle
  if (vehicle) {
    if (vehicle.inspection_type === 'cof' && vehicle.cof_expiry) {
      fields.push({ label: 'COF Expiry', value: vehicle.cof_expiry })
    } else if (vehicle.wof_expiry) {
      fields.push({ label: 'WOF Expiry', value: vehicle.wof_expiry })
    }
  }

  return fields
}
