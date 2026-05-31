/**
 * LeaveTab — top-level tab for a single staff record's leave engine.
 *
 * Layout (per Phase 2 design §6.1):
 *   1. BalanceCardsRow at the top
 *   2. CasualLeaveBanner (when employment_type === 'casual')
 *   3. LedgerTable below
 *   4. Toolbar with "Request leave" + "Adjust balance" (admin only)
 *
 * Data is sourced from `useStaffLeave(staffId)` (D9), which already
 * handles AbortController cleanup, parallel fetches, and the safe
 * `?? []` fallbacks on every list. Leave types are fetched separately
 * via `listLeaveTypes`, scoped to the staff's org by the backend.
 *
 * **Validates: Staff Management Phase 2 task D1**
 */

import { useCallback, useEffect, useState } from 'react'
import axios from 'axios'

import useStaffLeave from '../../../hooks/useStaffLeave'
import {
  listLeaveTypes,
  type LeaveType,
} from '../../../api/leave'
import { Spinner } from '../../../components/ui/Spinner'

import BalanceCardsRow from './BalanceCardsRow'
import CasualLeaveBanner from './CasualLeaveBanner'
import LedgerTable from './LedgerTable'
import RequestLeaveModal from './RequestLeaveModal'
import AdjustBalanceModal from './AdjustBalanceModal'
import type { Staff } from './types'

interface Props {
  staff: Staff
  /** True when the current user is an org_admin (or branch admin with rights). */
  canAdjust: boolean
}

function isAbortError(err: unknown): boolean {
  if (axios.isCancel?.(err)) return true
  if (err instanceof DOMException && err.name === 'AbortError') return true
  if (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    (err as { code?: string }).code === 'ERR_CANCELED'
  ) {
    return true
  }
  return false
}

export default function LeaveTab({ staff, canAdjust }: Props) {
  const staffId = staff?.id ?? ''
  const {
    balances,
    ledger,
    loading: dataLoading,
    error: dataError,
    refresh,
  } = useStaffLeave(staffId)

  // Leave-type catalog. Sourced from /api/v2/leave/types (org-scoped).
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([])
  const [typesLoading, setTypesLoading] = useState<boolean>(true)
  const [typesError, setTypesError] = useState<string | null>(null)

  const loadLeaveTypes = useCallback(
    async (signal?: AbortSignal) => {
      setTypesLoading(true)
      setTypesError(null)
      try {
        const res = await listLeaveTypes({ limit: 100 }, signal)
        if (signal?.aborted) return
        setLeaveTypes(res.items ?? [])
      } catch (err) {
        if (signal?.aborted || isAbortError(err)) return
        setTypesError('Failed to load leave types')
      } finally {
        if (!signal?.aborted) setTypesLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    const controller = new AbortController()
    void loadLeaveTypes(controller.signal)
    return () => controller.abort()
  }, [loadLeaveTypes])

  // Modal + filter state
  const [showRequestModal, setShowRequestModal] = useState(false)
  const [showAdjustModal, setShowAdjustModal] = useState(false)
  const [filterTypeId, setFilterTypeId] = useState<string | undefined>(undefined)

  const isCasual = staff?.employment_type === 'casual'
  const loading = dataLoading || typesLoading
  const error = dataError ?? typesError

  const handleRequestSubmitted = useCallback(() => {
    refresh()
  }, [refresh])

  const handleAdjusted = useCallback(() => {
    refresh()
  }, [refresh])

  if (loading) {
    return (
      <div
        className="flex items-center justify-center py-12"
        data-testid="leave-tab-loading"
      >
        <Spinner size="lg" label="Loading leave data" />
      </div>
    )
  }

  if (error) {
    return (
      <div
        role="alert"
        data-testid="leave-tab-error"
        className="m-4 rounded-md bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300"
      >
        <p>{error}</p>
        <button
          type="button"
          onClick={() => {
            refresh()
            void loadLeaveTypes()
          }}
          className="mt-2 px-3 py-1 min-h-[36px] rounded bg-red-600 text-white text-xs font-medium hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="leave-tab">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          Leave
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setShowRequestModal(true)}
            className="px-4 py-2 min-h-[44px] rounded bg-blue-600 text-white text-sm font-medium hover:bg-blue-700"
            data-testid="leave-request-button"
          >
            Request leave
          </button>
          {canAdjust && (
            <button
              type="button"
              onClick={() => setShowAdjustModal(true)}
              className="px-4 py-2 min-h-[44px] rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800"
              data-testid="leave-adjust-button"
            >
              Adjust balance
            </button>
          )}
        </div>
      </div>

      <BalanceCardsRow
        balances={balances ?? []}
        leaveTypes={leaveTypes ?? []}
        employmentType={staff?.employment_type ?? ''}
      />

      {isCasual && <CasualLeaveBanner />}

      <LedgerTable
        ledger={ledger ?? []}
        leaveTypes={leaveTypes ?? []}
        filterByLeaveTypeId={filterTypeId}
        onFilterChange={setFilterTypeId}
      />

      {showRequestModal && (
        <RequestLeaveModal
          staffId={staffId}
          staff={staff}
          leaveTypes={leaveTypes ?? []}
          onClose={() => setShowRequestModal(false)}
          onSubmitted={handleRequestSubmitted}
        />
      )}

      {showAdjustModal && canAdjust && (
        <AdjustBalanceModal
          staffId={staffId}
          leaveTypes={leaveTypes ?? []}
          balances={balances ?? []}
          onClose={() => setShowAdjustModal(false)}
          onAdjusted={handleAdjusted}
        />
      )}
    </div>
  )
}
