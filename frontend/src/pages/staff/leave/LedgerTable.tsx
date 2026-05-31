/**
 * LedgerTable — read-only table of leave-ledger entries.
 *
 * Columns: Date, Leave type, Reason, Delta hours, Notes, Created by.
 * Bereavement entries surface `request_relationship_to_subject` inline
 * (e.g., "Bereavement (close family)") so admins can see why the cap
 * applied without drilling into the underlying request.
 *
 * Filter dropdown narrows by leave_type. Rows render newest first.
 *
 * **Validates: Staff Management Phase 2 task D4**
 */

import type {
  LeaveLedgerEntry,
  LeaveType,
  RelationshipToSubject,
} from '../../../api/leave'

interface Props {
  ledger: LeaveLedgerEntry[]
  leaveTypes: LeaveType[]
  filterByLeaveTypeId?: string
  onFilterChange: (id: string | undefined) => void
}

const REASON_LABELS: Record<string, string> = {
  accrual: 'Accrual',
  request_approved: 'Request approved',
  request_cancelled_after_approval: 'Cancelled after approval',
  request_cancelled: 'Cancelled',
  manual_adjustment: 'Manual adjustment',
  adjustment: 'Manual adjustment',
  opening_balance: 'Opening balance',
  termination_payout: 'Termination payout',
  public_holiday_extension: 'Public holiday extension',
  public_holiday_worked: 'Public holiday worked',
  pay_run_payout: 'Pay run payout',
  toil_accrual: 'TOIL accrual',
  carry_over: 'Carry over',
  expiry: 'Expiry',
}

function reasonLabel(reason: string | null | undefined): string {
  if (!reason) return '—'
  return REASON_LABELS[reason] ?? reason
}

function relationshipLabel(
  rel: RelationshipToSubject | string | null | undefined,
): string {
  if (rel === 'close_family') return 'close family'
  if (rel === 'other') return 'other'
  return ''
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

function formatDelta(deltaStr: string | null | undefined): {
  text: string
  positive: boolean
} {
  const num = parseFloat(deltaStr ?? '') || 0
  const positive = num >= 0
  const sign = positive ? '+' : '−'
  const abs = Math.abs(num)
  const rounded = Math.round(abs * 10) / 10
  const formatted = Number.isInteger(rounded)
    ? rounded.toString()
    : rounded.toFixed(1)
  return { text: `${sign}${formatted}h`, positive }
}

export default function LedgerTable({
  ledger,
  leaveTypes,
  filterByLeaveTypeId,
  onFilterChange,
}: Props) {
  const typeById = new Map<string, LeaveType>()
  for (const lt of leaveTypes ?? []) typeById.set(lt.id, lt)

  const filtered = (ledger ?? []).filter(
    (e) => !filterByLeaveTypeId || e.leave_type_id === filterByLeaveTypeId,
  )

  // Sort newest first by occurred_at; fall back to created_at on tie.
  const sorted = [...filtered].sort((a, b) => {
    const ao = a?.occurred_at ?? ''
    const bo = b?.occurred_at ?? ''
    if (ao !== bo) return ao < bo ? 1 : -1
    const ac = a?.created_at ?? ''
    const bc = b?.created_at ?? ''
    if (ac !== bc) return ac < bc ? 1 : -1
    return 0
  })

  return (
    <div
      className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
      data-testid="ledger-table"
    >
      <div className="flex items-center justify-between gap-3 border-b border-gray-200 dark:border-gray-700 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          Leave history
        </h3>
        <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
          <span>Filter</span>
          <select
            data-testid="ledger-filter"
            value={filterByLeaveTypeId ?? ''}
            onChange={(e) => onFilterChange(e.target.value || undefined)}
            className="min-h-[36px] rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All leave types</option>
            {(leaveTypes ?? []).map((lt) => (
              <option key={lt.id} value={lt.id}>
                {lt.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {sorted.length === 0 ? (
        <div className="px-4 py-6 text-center text-sm text-gray-500 dark:text-gray-400">
          No ledger entries yet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800/40">
              <tr className="text-left text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400">
                <th scope="col" className="px-4 py-2 font-medium">Date</th>
                <th scope="col" className="px-4 py-2 font-medium">Leave type</th>
                <th scope="col" className="px-4 py-2 font-medium">Reason</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">Δ Hours</th>
                <th scope="col" className="px-4 py-2 font-medium">Notes</th>
                <th scope="col" className="px-4 py-2 font-medium">Created by</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {sorted.map((e) => {
                const lt = typeById.get(e.leave_type_id)
                const baseTypeName = lt?.name ?? e.leave_type_code ?? '—'
                const rel = relationshipLabel(
                  e.request_relationship_to_subject,
                )
                const typeLabel =
                  rel && (lt?.code === 'bereavement' || e.leave_type_code === 'bereavement')
                    ? `${baseTypeName} (${rel})`
                    : baseTypeName
                const delta = formatDelta(e.delta_hours)
                return (
                  <tr
                    key={e.id}
                    data-testid={`ledger-row-${e.id}`}
                    className="hover:bg-gray-50 dark:hover:bg-gray-800/40"
                  >
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
                      {formatDate(e.occurred_at)}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
                      {typeLabel}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
                      {reasonLabel(e.reason)}
                    </td>
                    <td
                      className={`px-4 py-2 whitespace-nowrap text-right font-medium ${
                        delta.positive
                          ? 'text-green-700 dark:text-green-300'
                          : 'text-red-700 dark:text-red-300'
                      }`}
                    >
                      {delta.text}
                    </td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">
                      {/* The ledger schema doesn't expose a "notes" column
                          directly; surface request_id when present so admins
                          can correlate with a request, otherwise blank. */}
                      {e.request_id ? (
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          Request {e.request_id.slice(0, 8)}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-gray-600 dark:text-gray-400">
                      {e.created_by_email ?? '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
