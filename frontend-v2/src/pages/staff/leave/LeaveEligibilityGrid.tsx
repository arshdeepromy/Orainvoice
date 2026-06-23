/**
 * LeaveEligibilityGrid — comprehensive per-staff leave overview.
 *
 * Renders one card for EVERY active leave type configured for the org, each
 * showing the staff member's eligibility status (eligible / not-yet-eligible
 * with the vesting date / available / 8% pay-as-you-go) alongside their
 * current balance. Replaces the old balance-only row which hid leave types
 * the staff member hadn't vested yet.
 *
 * Data: GET /api/v2/leave/staff/{id}/eligibility (the versioned rules engine).
 * Safe API consumption (?? [], typed generic, AbortController cleanup).
 */

import { useEffect, useState } from 'react'

import {
  getStaffLeaveEligibility,
  type LeaveEligibilityStatus,
  type StaffLeaveEligibility,
  type StaffLeaveEligibilityItem,
} from '@/api/leave'
import { Spinner } from '@/components/ui'

interface Props {
  staffId: string
}

function fmtHours(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '0h'
  const num = typeof value === 'number' ? value : parseFloat(value)
  if (Number.isNaN(num)) return '0h'
  const rounded = Math.round(num * 10) / 10
  return Number.isInteger(rounded) ? `${rounded}h` : `${rounded.toFixed(1)}h`
}

function fmtDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

const STATUS_META: Record<
  LeaveEligibilityStatus,
  { label: string; cls: string; dot: string }
> = {
  eligible: {
    label: 'Eligible',
    cls: 'bg-ok-soft text-ok',
    dot: 'bg-ok',
  },
  pending: {
    label: 'Not yet eligible',
    cls: 'bg-warn-soft text-warn',
    dot: 'bg-warn',
  },
  casual_payg: {
    label: '8% pay-as-you-go',
    cls: 'bg-accent-soft text-accent',
    dot: 'bg-accent',
  },
  always: {
    label: 'Available',
    cls: 'bg-[#EEF0F4] text-muted',
    dot: 'bg-muted',
  },
  no_start_date: {
    label: 'Add start date',
    cls: 'bg-[#EEF0F4] text-muted',
    dot: 'bg-muted',
  },
}

function subtitleFor(item: StaffLeaveEligibilityItem): string | null {
  if (item.status === 'pending') {
    const months = item.milestone_months ?? 0
    const when = fmtDate(item.eligible_on)
    const base =
      months > 0
        ? `Eligible after ${months} months of service${when ? ` — ${when}` : ''}`
        : when
          ? `Eligible ${when}`
          : 'Eligibility pending'
    return item.hours_test_required
      ? `${base}. Hours test (avg ≥10h/week) also applies.`
      : base
  }
  if (item.status === 'casual_payg') {
    return 'Annual holidays paid as 8% with each pay.'
  }
  if (item.status === 'no_start_date') {
    return 'Set an employment start date to evaluate eligibility.'
  }
  if (item.status === 'eligible' && item.is_statutory) {
    return 'Entitled now.'
  }
  return null
}

export default function LeaveEligibilityGrid({ staffId }: Props) {
  const [data, setData] = useState<StaffLeaveEligibility | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getStaffLeaveEligibility(staffId, controller.signal)
      .then((res) => setData(res))
      .catch((err: unknown) => {
        if ((err as { code?: string })?.code === 'ERR_CANCELED') return
        setError('Could not load leave eligibility.')
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [staffId, reloadKey])

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <Spinner label="Loading leave eligibility" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
        <p>{error}</p>
        <button
          type="button"
          onClick={() => setReloadKey((k) => k + 1)}
          className="mt-2 rounded-ctl bg-danger px-3 py-1 text-xs font-medium text-white hover:opacity-90"
        >
          Retry
        </button>
      </div>
    )
  }

  const items = data?.items ?? []

  return (
    <div className="space-y-3" data-testid="leave-eligibility-grid">
      {(data?.employment_start_date || data?.months_completed != null) && (
        <p className="text-xs text-muted">
          {data?.employment_start_date && (
            <>Started {fmtDate(data.employment_start_date)}</>
          )}
          {data?.months_completed != null && (
            <> · {data.months_completed} month(s) of continuous service</>
          )}
        </p>
      )}

      {items.length === 0 ? (
        <div className="rounded-card border border-dashed border-border p-6 text-center text-sm text-muted">
          No leave types configured.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => {
            const meta = STATUS_META[item.status]
            const subtitle = subtitleFor(item)
            const showBalance =
              item.has_balance ||
              item.eligible ||
              Number(item.available_hours) !== 0
            return (
              <div
                key={item.leave_type_id}
                data-testid={`leave-elig-card-${item.code}`}
                className="rounded-card border border-border bg-card p-4 shadow-card"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-text">
                      {item.name}
                    </h3>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted">
                      <span>{item.is_paid ? 'Paid' : 'Unpaid'}</span>
                      {item.is_statutory && <span>· Statutory</span>}
                      {item.confidential_visibility && (
                        <span className="text-accent">· Confidential</span>
                      )}
                    </div>
                  </div>
                  <span
                    className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${meta.cls}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
                    {meta.label}
                  </span>
                </div>

                {showBalance && (
                  <>
                    <div className="mt-3">
                      <div className="mono text-2xl font-semibold text-text">
                        {fmtHours(item.available_hours)}
                      </div>
                      <div className="text-xs text-muted">available</div>
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-muted">
                      <div>
                        <div className="mono font-medium text-text">
                          {fmtHours(item.accrued_hours)}
                        </div>
                        <div>accrued</div>
                      </div>
                      <div>
                        <div className="mono font-medium text-text">
                          {fmtHours(item.used_hours)}
                        </div>
                        <div>used</div>
                      </div>
                      <div>
                        <div className="mono font-medium text-text">
                          {fmtHours(item.pending_hours)}
                        </div>
                        <div>pending</div>
                      </div>
                    </div>
                  </>
                )}

                {subtitle && (
                  <p className="mt-3 text-[11px] leading-snug text-muted">
                    {subtitle}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
