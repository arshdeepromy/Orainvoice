/**
 * LeaveBalancesPage — org-wide Leave Balances view (Leave Balances & Eligibility).
 *
 * A standalone page (reachable from the People sidebar group) listing every
 * staff member with their VESTED leave balances. Supports an employment-type
 * filter and group-by (display conveniences only — they never change statutory
 * eligibility, R2.5). Clicking a row drills into the per-staff `LeaveTab`
 * (fetching the full staff record because the list row is a lightweight
 * projection). Links to the NZ Holidays Act reference guide and to
 * Settings → Leave Types.
 *
 * Satisfies the frontend-feature-completeness checklist (loading / error+retry /
 * empty states) and safe-api-consumption (`?.`, `?? []`, typed generics,
 * AbortController cleanup).
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  getStaffLeaveContext,
  listOrgLeaveBalances,
  type StaffLeaveBalances,
  type StaffLeaveContext,
} from '@/api/leave'
import { useAuth } from '@/contexts/AuthContext'
import { AlertBanner, Badge, Button, Card, Modal, Spinner } from '@/components/ui'
import LeaveTab from '@/pages/staff/leave/LeaveTab'
import type { Staff } from '@/pages/staff/leave/types'

const PAGE_SIZE = 50

const EMPLOYMENT_TYPES = [
  'permanent',
  'fixed_term',
  'full_time',
  'part_time',
  'casual',
]

function availableHours(b: { accrued_hours: string; used_hours: string; pending_hours: string }): number {
  const a = Number(b.accrued_hours) || 0
  const u = Number(b.used_hours) || 0
  const p = Number(b.pending_hours) || 0
  return a - u - p
}

export default function LeaveBalancesPage() {
  const navigate = useNavigate()
  const { isOrgAdmin } = useAuth()

  const [items, setItems] = useState<StaffLeaveBalances[]>([])
  const [total, setTotal] = useState<number>(0)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const [employmentType, setEmploymentType] = useState<string>('')
  const [groupBy, setGroupBy] = useState<boolean>(false)
  const [offset, setOffset] = useState<number>(0)
  const [reloadKey, setReloadKey] = useState<number>(0)

  // Drill-in state.
  const [drillStaff, setDrillStaff] = useState<Staff | null>(null)
  const [drillLoading, setDrillLoading] = useState<boolean>(false)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    listOrgLeaveBalances(
      {
        employment_type: employmentType || undefined,
        group_by: groupBy ? 'employment_type' : undefined,
        offset,
        limit: PAGE_SIZE,
      },
      controller.signal,
    )
      .then((res) => {
        setItems(res.items ?? [])
        setTotal(res.total ?? 0)
      })
      .catch((err: unknown) => {
        if ((err as { code?: string })?.code === 'ERR_CANCELED') return
        setError('Could not load leave balances. Please try again.')
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employmentType, groupBy, offset, reloadKey])

  const openDrillIn = useCallback(async (staffId: string) => {
    setDrillLoading(true)
    try {
      const ctx: StaffLeaveContext = await getStaffLeaveContext(staffId)
      const staff: Staff = {
        id: ctx.id,
        name: ctx.name,
        employment_type: ctx.employment_type,
        standard_hours_per_week: ctx.standard_hours_per_week,
        shift_start: ctx.shift_start,
        shift_end: ctx.shift_end,
        availability_schedule: ctx.availability_schedule,
      }
      setDrillStaff(staff)
    } catch {
      setError('Could not open that staff member.')
    } finally {
      setDrillLoading(false)
    }
  }, [])

  const groupedRows = useMemo(() => items ?? [], [items])

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted">People</p>
          <h1 className="text-2xl font-semibold">Leave Balances</h1>
          <p className="text-sm text-muted">
            Org-wide statutory leave position with eligibility milestones.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="quiet" onClick={() => navigate('/leave/reference-guide')}>
            Holidays Act guide
          </Button>
          <Button
            variant="quiet"
            disabled={!isOrgAdmin}
            title={isOrgAdmin ? undefined : 'Requires leave-type configuration permission'}
            onClick={() => navigate('/settings?tab=leave-types')}
          >
            Configure leave types
          </Button>
        </div>
      </div>

      {/* Display-convenience note (R2.5) */}
      <AlertBanner variant="info">
        Employment type is a display convenience only — it does not change
        statutory leave eligibility.
      </AlertBanner>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-56">
          <label className="block text-xs text-muted mb-1" htmlFor="emp-type-filter">
            Employment type
          </label>
          <select
            id="emp-type-filter"
            className="h-[42px] w-full rounded-ctl border border-border bg-card px-3 text-sm"
            value={employmentType}
            onChange={(e) => {
              setOffset(0)
              setEmploymentType(e.target.value)
            }}
          >
            <option value="">All employment types</option>
            {EMPLOYMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace('_', ' ')}
              </option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={groupBy}
            onChange={(e) => {
              setOffset(0)
              setGroupBy(e.target.checked)
            }}
          />
          Group by employment type
        </label>
      </div>

      {/* Body */}
      {loading ? (
        <Card>
          <div className="p-4 space-y-3" aria-label="Loading leave balances">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="h-10 rounded bg-muted/20 animate-pulse" />
            ))}
          </div>
        </Card>
      ) : error ? (
        <Card>
          <div className="p-6 text-center space-y-3">
            <p className="text-sm text-danger">{error}</p>
            <Button onClick={() => setReloadKey((k) => k + 1)}>Retry</Button>
          </div>
        </Card>
      ) : groupedRows.length === 0 ? (
        <Card>
          <div className="p-10 text-center text-muted space-y-2">
            <p className="text-lg">No leave balances to show</p>
            <p className="text-sm">
              {employmentType
                ? 'No staff match this employment-type filter.'
                : 'Staff balances appear here once entitlements vest.'}
            </p>
          </div>
        </Card>
      ) : (
        <Card>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted border-b">
                <th className="p-3">Staff</th>
                <th className="p-3">Employment</th>
                <th className="p-3">Annual pay method</th>
                <th className="p-3">Vested balances</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {groupedRows.map((row) => (
                <tr key={row.staff_id} className="border-b last:border-0 hover:bg-muted/5">
                  <td className="p-3 font-medium">{row.staff_name}</td>
                  <td className="p-3 capitalize">
                    {(row.employment_type ?? '').replace('_', ' ')}
                  </td>
                  <td className="p-3">
                    {row.holiday_pay_method === 'casual_payg' ? (
                      <Badge variant="warn">8% pay-as-you-go</Badge>
                    ) : (
                      <Badge variant="neutral">Accrued</Badge>
                    )}
                  </td>
                  <td className="p-3">
                    {(row.balances ?? []).length === 0 ? (
                      <span className="text-muted">—</span>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {(row.balances ?? []).map((b) => (
                          <span
                            key={b.id}
                            className="rounded bg-muted/10 px-2 py-0.5 text-xs"
                            title={b.leave_type_name ?? undefined}
                          >
                            {b.leave_type_code}: {availableHours(b).toFixed(1)}h
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="p-3 text-right">
                    <Button
                      variant="ghost"
                      onClick={() => openDrillIn(row.staff_id)}
                      disabled={drillLoading}
                    >
                      View
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Pagination */}
      {!loading && !error && total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted">
            Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="quiet"
              disabled={offset === 0}
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            >
              Previous
            </Button>
            <Button
              variant="quiet"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      {/* Drill-in */}
      {drillStaff && (
        <Modal
          open
          onClose={() => setDrillStaff(null)}
          title={`Leave — ${drillStaff.name ?? ''}`}
        >
          <LeaveTab staff={drillStaff} canAdjust={isOrgAdmin} />
        </Modal>
      )}

      {drillLoading && !drillStaff && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
          <Spinner />
        </div>
      )}
    </div>
  )
}
