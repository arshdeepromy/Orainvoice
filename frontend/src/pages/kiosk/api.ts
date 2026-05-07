/**
 * API helper functions for kiosk endpoints.
 *
 * Applies safe API consumption patterns (optional chaining, nullish coalescing)
 * per project conventions. Each function accepts an optional AbortSignal for
 * cleanup in useEffect hooks.
 *
 * Requirements: 3.1, 9.1
 */

import apiClient from '@/api/client'
import type { VehicleLookupResult, AutoFillMatch } from './types'

/** Response shape from GET /kiosk/customer-lookup */
interface CustomerLookupResponse {
  items: AutoFillMatch[]
  total: number
}

/**
 * Look up a vehicle by registration number.
 *
 * POST /api/v1/kiosk/vehicle-lookup
 *
 * The backend performs a cascading lookup: org_vehicles → global_vehicles → CarJam API.
 * Returns the vehicle data on success, or throws on 404/429/5xx.
 */
export async function lookupVehicle(
  rego: string,
  signal?: AbortSignal,
): Promise<VehicleLookupResult> {
  const res = await apiClient.post<VehicleLookupResult>(
    '/kiosk/vehicle-lookup',
    { rego },
    { signal },
  )

  return {
    id: res.data?.id ?? '',
    rego: res.data?.rego ?? '',
    make: res.data?.make ?? null,
    model: res.data?.model ?? null,
    body_type: res.data?.body_type ?? null,
    year: res.data?.year ?? null,
    colour: res.data?.colour ?? null,
    wof_expiry: res.data?.wof_expiry ?? null,
    rego_expiry: res.data?.rego_expiry ?? null,
    odometer: res.data?.odometer ?? null,
    source: res.data?.source ?? '',
  }
}

/**
 * Look up customers by phone or email for auto-fill.
 *
 * GET /api/v1/kiosk/customer-lookup
 *
 * Matches on exact phone OR case-insensitive email within the org.
 * Returns up to 5 matches. Silently returns empty on failure (caller
 * should catch errors for graceful degradation).
 */
export async function lookupCustomer(
  params: { phone?: string; email?: string },
  signal?: AbortSignal,
): Promise<{ items: AutoFillMatch[]; total: number }> {
  const res = await apiClient.get<CustomerLookupResponse>(
    '/kiosk/customer-lookup',
    {
      params: {
        ...(params.phone ? { phone: params.phone } : {}),
        ...(params.email ? { email: params.email } : {}),
      },
      signal,
    },
  )

  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}
