/**
 * Typed API client for the **Global-Admin** per-organisation Documenso
 * connection surface (feature: esignature-integration, Task 18.3).
 *
 * Distinct from `api/esign.ts` — that client is the **org-user** Agreements
 * surface (`/api/v2/esign/envelopes...`). The endpoints here are
 * **Global-Admin-only**, carry the target `org_id` in the path, and are
 * mounted under the admin prefix in `app/modules/esignatures/connection_router.py`:
 *
 *   - GET  /api/v2/admin/organisations/{org_id}/esign/connection        (masked)
 *   - PUT  /api/v2/admin/organisations/{org_id}/esign/connection        (save/update)
 *   - POST /api/v2/admin/organisations/{org_id}/esign/connection/test   (sets is_verified)
 *
 * Mirrors the Pydantic schemas in `connection_router.py` (`ConnectionResponse`,
 * `ConnectionSaveRequest`, `ConnectionTestResponse`).
 *
 * Conventions (per `.kiro/steering/safe-api-consumption.md`, the project
 * rules, and the `api/esign.ts` conventions):
 *
 *   - v2 endpoints use absolute `/api/v2/...` paths (the axios client in
 *     `client.ts` strips the `/api/v1` baseURL when the URL starts with
 *     `/api/`).
 *   - Every call accepts an optional `AbortSignal` forwarded via `{ signal }`.
 *   - Typed generics on every `apiClient.*` call — never `as any`.
 *   - Read sites use `?.` / `?? ''` / `?? false` so a partial / blank response
 *     can never crash a consumer.
 *
 * Secret handling: GET/PUT responses are **always masked** — `service_token`
 * and `webhook_signing_secret` come back as an asterisk mask (`********`) plus a
 * `*_last4` projection, never plaintext (R1.4, R15.3). On save, echoing the mask
 * back retains the stored secret (R1.5).
 *
 * _Requirements: 1.1, 1.4, 1.5, 1.6, 18.1, 19.1, 19.2 (and the frontend
 * safe-consumption rules)_
 */

import apiClient from './client'

// ===========================================================================
// Constants
// ===========================================================================

/**
 * The asterisk mask the backend returns for a *set* secret. Echoing this value
 * back unchanged on PUT retains the stored secret (R1.5). Kept here so the UI
 * can detect "the field still holds the masked placeholder" without hard-coding
 * the literal in multiple places.
 */
export const SECRET_MASK = '********'

/**
 * Webhook subscription lifecycle states surfaced by the backend
 * (`connection_router._subscription_status`), in lifecycle order.
 */
export type WebhookSubscriptionStatus =
  | 'not_configured'
  | 'pending_verification'
  | 'verified'
  | 'active'

// ===========================================================================
// Response / request types — mirror connection_router.py schemas
// ===========================================================================

/**
 * Masked projection of an organisation's Documenso connection (R1.4).
 * `service_token` / `webhook_signing_secret` are the asterisk mask
 * (`********` when a secret is stored, `''` when not); `*_last4` is the
 * trailing-4 projection. Plaintext secrets are never returned (R15.3).
 */
export interface EsignConnection {
  configured: boolean
  org_id: string
  base_url: string | null
  documenso_team_id: string | null
  is_verified: boolean
  /** Masked echo (`********` when set, else `''`). */
  service_token: string
  service_token_last4: string
  /** Masked echo (`********` when set, else `''`). */
  webhook_signing_secret: string
  webhook_secret_last4: string
  webhook_routing_id: string | null
  /** Fully-qualified URL to copy into Documenso, or null when unresolvable. */
  webhook_url: string | null
  webhook_subscription_status: WebhookSubscriptionStatus
  created_at: string | null
  updated_at: string | null
}

/**
 * Create/update payload. Secrets may be sent as plaintext (to set/replace) or
 * as the masked echo (`********`) returned by GET (to retain the stored value,
 * R1.5). The opaque `webhook_routing_id` is generated server-side and is never
 * accepted from the client. Omitted (`undefined`) fields are left untouched.
 */
export interface EsignConnectionSave {
  base_url?: string | null
  documenso_team_id?: string | null
  service_token?: string | null
  webhook_signing_secret?: string | null
}

/** Result of testing an organisation's Documenso connection (R1.6 / R19.2). */
export interface EsignConnectionTestResult {
  is_verified: boolean
  valid: boolean
}

/**
 * Outcome of the optional best-effort auto-provision run (R19.6, R20),
 * mirroring `connection_router.AutoProvisionResponse.status`:
 *
 *   - `provisioned` — the org's Team, token, and webhook were created and the
 *     verifying connection test ran; `connection.is_verified` reflects the row.
 *   - `partial`     — auto-provisioning failed at some step; whatever artefacts
 *     were created are persisted and **manually completable** on the same row.
 *   - `unavailable` — auto-provisioning is turned off in this environment
 *     (`ESIGN_PROVISIONING_MODE=off`); the manual path is unaffected.
 */
export type EsignAutoProvisionStatus = 'provisioned' | 'partial' | 'unavailable'

/**
 * Result of `POST /api/v2/admin/organisations/{org_id}/esign/auto-provision`.
 *
 * `connection` is the same **masked** projection as the connection `GET`
 * (`*_last4`, never plaintext — R1.4/R15.3). On a non-success outcome `error`
 * carries the humanized server message and `code` the machine code, while
 * `connection` still reflects whatever partial state was recorded so the
 * Global Admin can finish setup manually (R20.3).
 */
export interface EsignAutoProvisionResult {
  status: EsignAutoProvisionStatus
  connection: EsignConnection
  error: string | null
  code: string | null
}

// ---------------------------------------------------------------------------
// Wire types — what the backend actually serialises (every field optional /
// nullable so a partial payload can never crash the normaliser).
// ---------------------------------------------------------------------------

interface EsignConnectionWire {
  configured?: boolean | null
  org_id?: string | null
  base_url?: string | null
  documenso_team_id?: string | null
  is_verified?: boolean | null
  service_token?: string | null
  service_token_last4?: string | null
  webhook_signing_secret?: string | null
  webhook_secret_last4?: string | null
  webhook_routing_id?: string | null
  webhook_url?: string | null
  webhook_subscription_status?: string | null
  created_at?: string | null
  updated_at?: string | null
}

interface EsignConnectionTestWire {
  is_verified?: boolean | null
  valid?: boolean | null
}

interface EsignAutoProvisionWire {
  status?: string | null
  connection?: EsignConnectionWire | null
  error?: string | null
  code?: string | null
}

// ===========================================================================
// Normalisers — coerce a partial/blank wire payload into a fully-populated,
// crash-proof shape so callers never see `undefined`.
// ===========================================================================

const SUBSCRIPTION_STATUSES: readonly WebhookSubscriptionStatus[] = [
  'not_configured',
  'pending_verification',
  'verified',
  'active',
]

function normaliseSubscriptionStatus(
  value: string | null | undefined,
): WebhookSubscriptionStatus {
  return SUBSCRIPTION_STATUSES.includes(value as WebhookSubscriptionStatus)
    ? (value as WebhookSubscriptionStatus)
    : 'not_configured'
}

function normaliseConnection(
  wire: EsignConnectionWire | null | undefined,
): EsignConnection {
  return {
    configured: wire?.configured ?? false,
    org_id: wire?.org_id ?? '',
    base_url: wire?.base_url ?? null,
    documenso_team_id: wire?.documenso_team_id ?? null,
    is_verified: wire?.is_verified ?? false,
    service_token: wire?.service_token ?? '',
    service_token_last4: wire?.service_token_last4 ?? '',
    webhook_signing_secret: wire?.webhook_signing_secret ?? '',
    webhook_secret_last4: wire?.webhook_secret_last4 ?? '',
    webhook_routing_id: wire?.webhook_routing_id ?? null,
    webhook_url: wire?.webhook_url ?? null,
    webhook_subscription_status: normaliseSubscriptionStatus(
      wire?.webhook_subscription_status,
    ),
    created_at: wire?.created_at ?? null,
    updated_at: wire?.updated_at ?? null,
  }
}

function normaliseTestResult(
  wire: EsignConnectionTestWire | null | undefined,
): EsignConnectionTestResult {
  return {
    is_verified: wire?.is_verified ?? false,
    valid: wire?.valid ?? false,
  }
}

const AUTO_PROVISION_STATUSES: readonly EsignAutoProvisionStatus[] = [
  'provisioned',
  'partial',
  'unavailable',
]

function normaliseAutoProvisionStatus(
  value: string | null | undefined,
): EsignAutoProvisionStatus {
  // Fail safe: an unknown / missing status is treated as `partial` so the UI
  // always steers the Global Admin toward the always-available manual path
  // rather than implying a (possibly false) success.
  return AUTO_PROVISION_STATUSES.includes(value as EsignAutoProvisionStatus)
    ? (value as EsignAutoProvisionStatus)
    : 'partial'
}

function normaliseAutoProvision(
  wire: EsignAutoProvisionWire | null | undefined,
): EsignAutoProvisionResult {
  return {
    status: normaliseAutoProvisionStatus(wire?.status),
    connection: normaliseConnection(wire?.connection),
    error: wire?.error ?? null,
    code: wire?.code ?? null,
  }
}

// ===========================================================================
// Endpoints
// ===========================================================================

/**
 * GET /api/v2/admin/organisations/{org_id}/esign/connection
 *
 * Return the organisation's Documenso connection with secrets **masked**
 * (R1.4, R15.3). When the org has no connection yet the backend returns a
 * stable "not configured" shape (HTTP 200, `configured: false`) so the form
 * can render empty.
 */
export async function getEsignConnection(
  orgId: string,
  signal?: AbortSignal,
): Promise<EsignConnection> {
  const res = await apiClient.get<EsignConnectionWire>(
    `/api/v2/admin/organisations/${orgId}/esign/connection`,
    { signal },
  )
  return normaliseConnection(res.data)
}

/**
 * PUT /api/v2/admin/organisations/{org_id}/esign/connection
 *
 * Create or update the organisation's Documenso connection. `base_url` /
 * `documenso_team_id` are stored as-is; secrets are envelope-encrypted by the
 * service. A secret echoed back as the masked placeholder (`********`) retains
 * the stored value rather than overwriting it (R1.5). Any save clears
 * `is_verified` until a fresh test succeeds (R19.5). The response is masked.
 */
export async function saveEsignConnection(
  orgId: string,
  payload: EsignConnectionSave,
  signal?: AbortSignal,
): Promise<EsignConnection> {
  const res = await apiClient.put<EsignConnectionWire>(
    `/api/v2/admin/organisations/${orgId}/esign/connection`,
    payload,
    { signal },
  )
  return normaliseConnection(res.data)
}

/**
 * POST /api/v2/admin/organisations/{org_id}/esign/connection/test
 *
 * Test the organisation's Documenso connection and persist `is_verified`
 * (R1.6, R19.2). Reports `valid`. When the org has no connection row yet the
 * backend returns a humanized "configure first" error (R1.10) which surfaces
 * as a rejected promise carrying the standard `{ message, code }` body.
 */
export async function testEsignConnection(
  orgId: string,
  signal?: AbortSignal,
): Promise<EsignConnectionTestResult> {
  const res = await apiClient.post<EsignConnectionTestWire>(
    `/api/v2/admin/organisations/${orgId}/esign/connection/test`,
    {},
    { signal },
  )
  return normaliseTestResult(res.data)
}

/**
 * POST /api/v2/admin/organisations/{org_id}/esign/auto-provision
 *
 * Trigger the optional, best-effort auto-provisioning for the target org
 * (R19.6, R20): create the org's Documenso Team, mint its team-scoped token,
 * register its webhook subscription, and run the verifying connection test.
 *
 * The backend reports the outcome via `status` (`provisioned` / `partial` /
 * `unavailable`). It returns HTTP 200 for `provisioned` and `unavailable`, and
 * HTTP 502 for `partial` — but in **all three** cases the body carries the full
 * `{ status, connection, error, code }` shape (the masked, partial-or-verified
 * connection is always present so the manual path stays completable, R20.3).
 *
 * Because `partial` arrives as a 502, this client catches that case and resolves
 * it into a normal result rather than throwing, so the caller can render the
 * "configure manually" affordance uniformly. Genuine transport failures (403 /
 * 404 / network / abort), which lack the structured body, are re-thrown so the
 * caller can surface a generic error via {@link extractEsignError}.
 */
export async function autoProvisionEsignConnection(
  orgId: string,
  signal?: AbortSignal,
): Promise<EsignAutoProvisionResult> {
  try {
    const res = await apiClient.post<EsignAutoProvisionWire>(
      `/api/v2/admin/organisations/${orgId}/esign/auto-provision`,
      {},
      { signal },
    )
    return normaliseAutoProvision(res.data)
  } catch (err: unknown) {
    const data = (err as { response?: { data?: unknown } })?.response?.data
    if (data && typeof data === 'object' && 'status' in (data as Record<string, unknown>)) {
      // The `partial` outcome (HTTP 502) still carries the full structured body.
      return normaliseAutoProvision(data as EsignAutoProvisionWire)
    }
    throw err
  }
}

/**
 * Extract a humanized `{ message, code }` from an axios error raised by any of
 * the connection endpoints. The backend renders errors as either
 * `{ detail: { message, code } }` (humanized esign errors) or
 * `{ detail: "..." }` (plain validation strings). Returns a safe fallback when
 * neither shape is present so the UI always has something to show.
 */
export function extractEsignError(err: unknown): { message: string; code: string | null } {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (detail && typeof detail === 'object') {
    const obj = detail as { message?: string | null; code?: string | null }
    return {
      message: obj.message ?? 'Something went wrong handling your request.',
      code: obj.code ?? null,
    }
  }
  if (typeof detail === 'string' && detail.trim()) {
    return { message: detail, code: null }
  }
  return { message: 'Something went wrong handling your request.', code: null }
}
