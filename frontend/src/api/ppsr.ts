/**
 * Typed API client for the PPSR module (Phase 1).
 *
 * Mirrors the schemas in `app/modules/ppsr/schemas.py` and the routes
 * in `app/modules/ppsr/router.py` (registered at `/api/v2/ppsr/*`).
 *
 * Conventions (per `.kiro/steering/safe-api-consumption.md` and the
 * project rules in `project-overview.md`):
 *
 *   - Every list endpoint returns `{ items, total }`; wrappers
 *     normalise to `{ items: res.data?.items ?? [], total: res.data?.total ?? 0 }`.
 *   - Pagination params are `offset` + `limit` (NOT `skip`).
 *   - Every async function accepts an optional `AbortSignal` and
 *     forwards it via the axios request config (`{ signal }`).
 *   - Typed generics on every `apiClient.*` call — never `as any`.
 *   - Absolute paths beginning with `/api/v2/...` — the client's
 *     `client.ts` strips the `/api/v1` baseURL when the URL starts
 *     with `/api/`.
 *   - PDF export returns a `Blob` for browser download.
 *
 * **Validates: PPSR module spec task D1**
 */

import apiClient from './client'

// ===========================================================================
// Type definitions — mirror app/modules/ppsr/schemas.py
// ===========================================================================

/**
 * Money-owing match value reported by CarJam on the PPSR endpoint.
 * `Y` / `PY` = matched (money owing); `M` / `PM` = matched (no owing);
 * `U` = unknown; `N` = no match (clear).
 */
export type PpsrMatch = 'Y' | 'PY' | 'M' | 'PM' | 'U' | 'N'

/** Common wrapper shape per project rule. */
export interface ListResponse<T> {
  items: T[]
  total: number
}

// ---------------------------------------------------------------------------
// Request schemas
// ---------------------------------------------------------------------------

/**
 * Body of `POST /api/v2/ppsr/search`.
 *
 * Per design §5 the API takes the option flags **flattened** at the
 * top level (rather than nested under an `options` key) so the JSON
 * wire format matches the UI form 1:1.
 */
export interface PpsrSearchRequest {
  /** NZ vehicle plate; 1-8 alphanumeric (validated server-side). */
  rego: string
  include_ownership_history?: boolean
  include_current_owner?: boolean
  include_warnings?: boolean
  include_fws?: boolean
  check_hidden_plates?: boolean
  s241_purpose?: string | null
  /**
   * Ignore the 5-minute cache and re-call CarJam. Counts against the
   * org's monthly quota.
   */
  force_refresh?: boolean
}

/** Body of `POST /api/v2/ppsr/searches/:id/link-vehicle`. */
export interface PpsrLinkVehicleRequest {
  org_vehicle_id: string
}

// ---------------------------------------------------------------------------
// Response schemas
// ---------------------------------------------------------------------------

/**
 * Response payload for `POST /search` and `GET /searches/:id`.
 *
 * `cached` + `cached_at` + `source_search_id` together let the UI
 * render the "Cached at HH:MM" badge.
 */
export interface PpsrSearchResult {
  search_id: string
  rego: string
  cached: boolean
  cached_at: string | null
  source_search_id: string | null

  match: PpsrMatch | string | null
  match_description: string | null
  statement_count: number

  ppsr_details: Record<string, unknown>[]
  ownership_history: Record<string, unknown>[] | null
  current_owner: Record<string, unknown> | null
  warnings: Record<string, unknown>[]
  basic: Record<string, unknown> | null

  not_found: boolean
  charges_cents: number | null
  carjam_request_id: string | null
}

/**
 * Row in the paginated search-history list. Server-side only exposes
 * denormalised summary columns — the encrypted payload never leaves
 * the database in this shape (G31).
 */
export interface PpsrSearchSummary {
  id: string
  rego: string
  match: PpsrMatch | string | null
  match_description: string | null
  statement_count: number
  has_warnings: boolean
  has_ownership_data: boolean
  not_found: boolean
  forgotten_at: string | null
  org_vehicle_id: string | null
  user_id: string
  created_at: string
}

/** `GET /api/v2/ppsr/searches` — `{ items, total }` per project rule. */
export interface PpsrSearchListResponse {
  items: PpsrSearchSummary[]
  total: number
}

/**
 * `GET /api/v2/ppsr/quota`.
 *
 * Field naming follows G44 — counters are exposed as
 * `hidden_plate_used` / `hidden_plate_included` (not `money_owing_*`).
 * `resets_at` is the org's next billing-cycle boundary; `null` when
 * the org is not yet billable.
 */
export interface PpsrQuotaResponse {
  used: number
  included: number
  hidden_plate_used: number
  hidden_plate_included: number
  resets_at: string | null
  /** Whether owner/ownership-history lookups are enabled in CarJam config. */
  owner_lookups_enabled?: boolean
  /** Whether s241_purpose_default is configured (non-empty). */
  s241_purpose_configured?: boolean
}

// ---------------------------------------------------------------------------
// History-list query params
// ---------------------------------------------------------------------------

export interface ListSearchesParams {
  /** Filter by rego (exact, uppercase). */
  rego?: string
  /** Filter by money-owing match value (Y/PY/M/PM/U/N). */
  match?: PpsrMatch | string
  /** Filter by user (admin only — non-admins see only their own). */
  user_id?: string
  /** ISO datetime — earliest `created_at` to include. */
  date_from?: string
  /** ISO datetime — latest `created_at` to include. */
  date_to?: string
  offset?: number
  limit?: number
}

// ===========================================================================
// Endpoint methods
// ===========================================================================

/**
 * Run a PPSR check — cache hit when within TTL, otherwise fresh
 * CarJam call. May throw:
 *   - 402 `ppsr_quota_exceeded`
 *   - 422 `carjam_not_configured` / `s241_purpose_required` /
 *         `s241_not_authorised`
 *   - 429 `carjam_rate_limit` (with `Retry-After` header)
 *   - 502 `carjam_upstream_error`
 */
export async function search(
  payload: PpsrSearchRequest,
  signal?: AbortSignal,
): Promise<PpsrSearchResult> {
  const res = await apiClient.post<PpsrSearchResult>(
    '/api/v2/ppsr/search',
    payload,
    { signal },
  )
  return res.data
}

/**
 * List PPSR search history (paginated `{ items, total }`).
 *
 * Server-side filters: rego, match, user_id (admin only), date range.
 * Non-admins are force-filtered to their own searches by the service.
 */
export async function listSearches(
  params: ListSearchesParams = {},
  signal?: AbortSignal,
): Promise<PpsrSearchListResponse> {
  const res = await apiClient.get<PpsrSearchListResponse>(
    '/api/v2/ppsr/searches',
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

/**
 * Get the decrypted PPSR detail for a saved search.
 *
 * Returns HTTP 410 with `{ detail: "search_forgotten", forgotten_at }`
 * when the row's payload was wiped via the forget endpoint.
 */
export async function getSearch(
  id: string,
  signal?: AbortSignal,
): Promise<PpsrSearchResult> {
  const res = await apiClient.get<PpsrSearchResult>(
    `/api/v2/ppsr/searches/${id}`,
    { signal },
  )
  return res.data
}

/**
 * Download a saved PPSR search rendered as PDF (binary `application/pdf`).
 * Returns a `Blob` ready for browser download via an object URL.
 */
export async function exportPdf(
  id: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const res = await apiClient.get<Blob>(
    `/api/v2/ppsr/searches/${id}/export`,
    { responseType: 'blob', signal },
  )
  return res.data
}

/**
 * Org-admin only: wipe the encrypted payload from a saved search.
 * The summary row + audit trail are retained (G26 / G29).
 */
export async function forgetSearch(
  id: string,
  signal?: AbortSignal,
): Promise<void> {
  await apiClient.delete<void>(
    `/api/v2/ppsr/searches/${id}/forget`,
    { signal },
  )
}

/**
 * Bind a saved PPSR search to an existing `OrgVehicle` row so the
 * vehicle profile can surface the latest check (G23).
 */
export async function linkVehicle(
  id: string,
  payload: PpsrLinkVehicleRequest,
  signal?: AbortSignal,
): Promise<void> {
  await apiClient.post<{ status: string; search_id: string; org_vehicle_id: string }>(
    `/api/v2/ppsr/searches/${id}/link-vehicle`,
    payload,
    { signal },
  )
}

/**
 * Current-org PPSR quota usage. Powers the quota strip on the search
 * page.
 */
export async function getQuota(signal?: AbortSignal): Promise<PpsrQuotaResponse> {
  const res = await apiClient.get<PpsrQuotaResponse>(
    '/api/v2/ppsr/quota',
    { signal },
  )
  return {
    used: res.data?.used ?? 0,
    included: res.data?.included ?? 0,
    hidden_plate_used: res.data?.hidden_plate_used ?? 0,
    hidden_plate_included: res.data?.hidden_plate_included ?? 0,
    resets_at: res.data?.resets_at ?? null,
    owner_lookups_enabled: res.data?.owner_lookups_enabled ?? false,
    s241_purpose_configured: res.data?.s241_purpose_configured ?? false,
  }
}

// ===========================================================================
// Default export (namespace-style for callers that prefer `ppsrApi.search`)
// ===========================================================================

export const ppsrApi = {
  search,
  listSearches,
  getSearch,
  exportPdf,
  forgetSearch,
  linkVehicle,
  getQuota,
}

export default ppsrApi
