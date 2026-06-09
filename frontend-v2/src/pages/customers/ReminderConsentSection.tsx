/**
 * ReminderConsentSection (F5) — read-only view of a customer's reminder
 * consent on the Customer Profile.
 *
 * Renders the consent headline (source / given_at / recorded-by / version),
 * a per-entry grid, and the revocation history. When no consent is on record
 * it shows an empty state. A per-entry "Revoke" control (F6) is rendered when
 * `onRevoke` is supplied AND the entry's category is currently enabled.
 *
 * Requirements: 5.1, 5.2, 5.3, 6.5.
 */

import { Badge, Button } from '@/components/ui'
import type {
  ReminderCategory,
  ReminderChannel,
  RemindersConsentEntry,
  RemindersConsentRecord,
  RemindersRevocationRecord,
} from '@/api/customers'

const CATEGORY_LABEL: Record<ReminderCategory, string> = {
  service_due: 'Service due',
  wof_expiry: 'WOF expiry',
  cof_expiry: 'COF expiry',
  registration_expiry: 'Registration expiry',
}

/** Map a vehicle_id to a rego for display, or "Customer-wide" when null. */
function vehicleLabel(
  vehicleId: string | null,
  vehicleRegoById: Record<string, string>,
): string {
  if (!vehicleId) return 'Customer-wide'
  return vehicleRegoById[vehicleId] ?? 'Vehicle'
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString()
}

function sourceLabel(source: string): string {
  if (source === 'kiosk_self_checkin') return 'Kiosk self check-in'
  if (source.startsWith('manually_recorded_by_staff:')) {
    return `Manually recorded (${source.split(':')[1] ?? 'staff'})`
  }
  return source
}

export interface ReminderConsentSectionProps {
  consent: RemindersConsentRecord | null | undefined
  revocations: RemindersRevocationRecord[]
  /** Per-category enabled state — drives whether a Revoke control shows. */
  enabledByCategory?: Partial<Record<ReminderCategory, boolean>>
  /** Map of vehicle_id → rego for display. */
  vehicleRegoById?: Record<string, string>
  /** When supplied, renders a Revoke control beside each active entry (F6). */
  onRevoke?: (entry: { category: ReminderCategory; channel: ReminderChannel }) => void
}

export function ReminderConsentSection({
  consent,
  revocations,
  enabledByCategory = {},
  vehicleRegoById = {},
  onRevoke,
}: ReminderConsentSectionProps) {
  if (!consent) {
    return (
      <div
        className="rounded-card border border-dashed border-border p-4 text-[13px] text-muted-2"
        data-testid="consent-empty"
      >
        No consent on record.
      </div>
    )
  }

  const entries: RemindersConsentEntry[] = consent.entries ?? []
  const recordedBy =
    consent.recorded_by_user_email ??
    (consent.source === 'kiosk_self_checkin' ? 'Customer (kiosk)' : '—')

  return (
    <div className="space-y-4" data-testid="consent-section">
      {/* Headline */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-card border border-border p-4 text-[13px]">
        <div>
          <span className="text-muted-2">Source</span>{' '}
          <span className="font-medium text-text">{sourceLabel(consent.source)}</span>
        </div>
        <div>
          <span className="text-muted-2">Given</span>{' '}
          <span className="mono text-text">{formatDateTime(consent.given_at)}</span>
        </div>
        <div>
          <span className="text-muted-2">Recorded by</span>{' '}
          <span className="text-text">{recordedBy}</span>
        </div>
        <div>
          <span className="text-muted-2">Version</span>{' '}
          <span className="mono text-text">{consent.consent_text_version}</span>
        </div>
      </div>

      {/* Entries grid */}
      <div>
        <p className="mono mb-2 text-[11px] font-medium uppercase tracking-wider text-muted-2">
          Consented reminders
        </p>
        <div className="space-y-2">
          {entries.length === 0 ? (
            <p className="text-[13px] text-muted-2">No consented categories.</p>
          ) : (
            entries.map((e, i) => {
              const active = enabledByCategory[e.category] === true
              return (
                <div
                  key={`${e.category}:${e.channel}:${e.vehicle_id ?? 'all'}:${i}`}
                  className="flex items-center justify-between gap-3 rounded-ctl bg-canvas px-3 py-2 text-[13px]"
                  data-testid={`consent-entry-${e.category}-${e.channel}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-text">{CATEGORY_LABEL[e.category]}</span>
                    <Badge variant="info">{e.channel.toUpperCase()}</Badge>
                    <span className="text-muted-2">{vehicleLabel(e.vehicle_id, vehicleRegoById)}</span>
                  </div>
                  {onRevoke && active && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => onRevoke({ category: e.category, channel: e.channel })}
                      data-testid={`revoke-${e.category}-${e.channel}`}
                    >
                      Revoke
                    </Button>
                  )}
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Revocation history */}
      {(revocations ?? []).length > 0 && (
        <div>
          <p className="mono mb-2 text-[11px] font-medium uppercase tracking-wider text-muted-2">
            Revocation history
          </p>
          <div className="overflow-hidden rounded-card border border-border">
            <table className="w-full text-[13px]" data-testid="revocations-table">
              <thead>
                <tr className="bg-canvas text-left text-muted-2">
                  <th className="px-3 py-2 font-medium">Revoked</th>
                  <th className="px-3 py-2 font-medium">Categories</th>
                  <th className="px-3 py-2 font-medium">Channel</th>
                  <th className="px-3 py-2 font-medium">Reason</th>
                  <th className="px-3 py-2 font-medium">By</th>
                </tr>
              </thead>
              <tbody>
                {[...revocations]
                  .sort((a, b) => (b.revoked_at ?? '').localeCompare(a.revoked_at ?? ''))
                  .map((r, i) => (
                    <tr key={`${r.revoked_at}:${i}`} className="border-t border-border">
                      <td className="mono px-3 py-2 text-text">{formatDateTime(r.revoked_at)}</td>
                      <td className="px-3 py-2 text-text">
                        {(r.categories_affected ?? []).map((c) => CATEGORY_LABEL[c]).join(', ')}
                      </td>
                      <td className="px-3 py-2 text-text">{r.channel?.toUpperCase()}</td>
                      <td className="px-3 py-2 text-muted">{r.reason_note}</td>
                      <td className="px-3 py-2 text-muted">{r.recorded_by_user_email ?? '—'}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

export default ReminderConsentSection
