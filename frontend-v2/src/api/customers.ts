/**
 * Customer reminder-consent API types + a client-side `computeMissingConsent`
 * mirror of the backend gate (F1).
 *
 * Field names match the backend Pydantic schemas exactly
 * (app/modules/customers/consent.py + schemas.py). Only the new consent /
 * revoke surfaces go through this module — existing customer calls stay
 * inline in CustomerList.tsx / CustomerProfile.tsx to limit blast radius.
 */

import apiClient from '@/api/client'

export type ReminderCategory =
  | 'service_due'
  | 'wof_expiry'
  | 'cof_expiry'
  | 'registration_expiry'

export type ReminderChannel = 'sms' | 'email' | 'both'

/** One ticked (category, channel) consent row (kiosk OR manual). */
export interface RemindersConsentEntry {
  vehicle_id: string | null
  category: ReminderCategory
  channel: ReminderChannel
}

/** Mirrors customer.custom_fields["reminder_consent"]. */
export interface RemindersConsentRecord {
  given_at: string
  source: string
  kiosk_session_id?: string | null
  entries: RemindersConsentEntry[]
  ip_address?: string | null
  user_agent?: string | null
  recorded_by_user_id?: string | null
  recorded_by_user_email?: string | null
  consent_text_version: string
  manual_note?: string | null
}

/** One appended revocation entry. */
export interface RemindersRevocationRecord {
  revoked_at: string
  source: string
  recorded_by_user_id: string
  recorded_by_user_email: string
  channel: ReminderChannel
  categories_affected: ReminderCategory[]
  reason_note: string
}

/** Body for POST /customers/{id}/reminders/revoke. */
export interface RemindersRevokeRequest {
  obtained_method: 'phone' | 'in_person' | 'email_reply' | 'other'
  channel: ReminderChannel
  categories_affected: ReminderCategory[]
  reason_note: string
}

/** A single still-missing (category, channel) pair (the 409 body shape). */
export interface MissingConsentPair {
  category: ReminderCategory
  channel: 'sms' | 'email'
}

/** Shape of the PUT /reminders 409 response. */
export interface ConsentRequiredResponse {
  error: 'consent_required'
  missing: MissingConsentPair[]
}

/** A reminder config entry as stored/sent. */
export interface ReminderConfigEntry {
  enabled: boolean
  days_before: number
  channel: ReminderChannel
}

const ALL_CATEGORIES: ReminderCategory[] = [
  'service_due',
  'wof_expiry',
  'cof_expiry',
  'registration_expiry',
]

/**
 * Build the set of `(category, effective_channel)` pairs covered by an
 * existing `reminder_consent` record. A `both` entry expands into both `sms`
 * and `email`. Mirrors the backend `coverage_for`.
 */
function coverageFor(
  consent: RemindersConsentRecord | null | undefined,
): Set<string> {
  const covered = new Set<string>()
  for (const entry of consent?.entries ?? []) {
    const category = entry?.category
    const channel = entry?.channel
    if (!category || !channel) continue
    if (channel === 'both') {
      covered.add(`${category}:sms`)
      covered.add(`${category}:email`)
    } else if (channel === 'sms' || channel === 'email') {
      covered.add(`${category}:${channel}`)
    }
  }
  return covered
}

/**
 * Return the `{category, channel}` pairs the new config is enabling that the
 * existing consent does not cover. A `both` requirement needs BOTH sms AND
 * email covered; an uncovered `both` is reported as two missing entries.
 * Mirrors the backend `compute_missing_consent` — an empty list means the
 * consent gate is not triggered.
 */
export function computeMissingConsent(
  existing: RemindersConsentRecord | null | undefined,
  newConfig: Partial<Record<ReminderCategory, ReminderConfigEntry>> | null | undefined,
): MissingConsentPair[] {
  const covered = coverageFor(existing)
  const missing: MissingConsentPair[] = []

  for (const category of ALL_CATEGORIES) {
    const entry = newConfig?.[category]
    if (!entry || !entry.enabled) continue
    const required: Array<'sms' | 'email'> =
      entry.channel === 'both'
        ? ['sms', 'email']
        : entry.channel === 'sms' || entry.channel === 'email'
          ? [entry.channel]
          : []
    for (const channel of required) {
      if (!covered.has(`${category}:${channel}`)) {
        missing.push({ category, channel })
      }
    }
  }

  return missing
}

/** Response from GET /customers/consent-text (staff-facing manual modal). */
export interface ConsentTextResponse {
  text: string
  version: string
}

/**
 * Fetch the reminder-consent banner text + version for the manual Consent
 * Confirmation modal. Uses the customer-router endpoint (org_admin /
 * salesperson gated) — NOT the kiosk endpoint, which is kiosk-role only.
 */
export async function fetchConsentText(
  signal?: AbortSignal,
): Promise<ConsentTextResponse> {
  const res = await apiClient.get<ConsentTextResponse>('/customers/consent-text', {
    signal,
  })
  return { text: res.data?.text ?? '', version: res.data?.version ?? '' }
}
