/**
 * MyPayslipsPage — Staff self-service payslips list (Phase 4 task D11 / G9).
 *
 * Mounted at `/staff/me/payslips` behind `RequireAuth` and the
 * payroll module gate (`ModuleRoute moduleSlug="payroll"`). The
 * server enforces ownership via the resolved `staff_members.user_id`
 * relationship; the screen itself is a thin presentation layer over
 * `listMyPayslips`.
 *
 * Per design.md §6.8 + R8a + G9:
 *   - Calls `listMyPayslips({ limit: 50 })` on mount.
 *   - Renders a table: pay period dates, gross_pay, net_pay, "PDF"
 *     link.
 *   - "PDF" opens `/api/v2/staff/me/payslips/{id}/pdf` in a new tab.
 *     The server validates the session cookie / bearer token before
 *     streaming the PDF, so we don't need a typed fetch + blob here.
 *   - Drafts/voided are filtered server-side per R8a — but we
 *     defensively also filter client-side so a regression in the
 *     server can't accidentally leak in-progress payslips.
 *
 * Conventions:
 *   - Typed client only (`frontend/src/api/payslips.ts`).
 *   - All API responses consumed with `?.` + `?? []` / `?? null`.
 *   - Decimal values arrive as strings; formatted via Intl.NumberFormat
 *     with NaN guards.
 *   - Every effect uses an AbortController.
 *   - Wraps content in `ModuleGate moduleSlug="payroll"` (the route
 *     itself also gates via `ModuleRoute`, but the inner gate is a
 *     defensive safety net mirroring the design spec).
 *
 * **Validates: Staff Management Phase 4 task D11, R8a, G9**
 */

import { useEffect, useMemo, useState } from 'react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { listMyPayslips } from '@/api/payslips'
import type { MyPayslip } from '@/api/payslips'

const NZD = new Intl.NumberFormat('en-NZ', {
  style: 'currency',
  currency: 'NZD',
})

function formatMoney(value: string | number | null | undefined): string {
  const n = typeof value === 'string' ? Number(value) : (value ?? 0)
  if (!Number.isFinite(n)) return NZD.format(0)
  return NZD.format(n)
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(`${iso}T00:00:00`).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

function formatPeriodRange(p: MyPayslip): string {
  const period = p?.pay_period ?? null
  if (!period) return '—'
  return `${formatDate(period.start_date)} – ${formatDate(period.end_date)}`
}

function isAbortError(err: unknown): boolean {
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

function readErrorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (
    detail &&
    typeof detail === 'object' &&
    'detail' in detail &&
    typeof (detail as { detail?: unknown }).detail === 'string'
  ) {
    return (detail as { detail: string }).detail
  }
  if (err instanceof Error) return err.message
  return 'Failed to load payslips.'
}

function MyPayslipsContent() {
  const [items, setItems] = useState<MyPayslip[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setLoadError(null)
    ;(async () => {
      try {
        const res = await listMyPayslips({ limit: 50 }, controller.signal)
        if (controller.signal.aborted) return
        setItems(res.items ?? [])
      } catch (err) {
        if (isAbortError(err)) return
        setLoadError(readErrorMessage(err))
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    })()
    return () => controller.abort()
  }, [])

  // Defence-in-depth: filter to finalised even though the server
  // already excludes drafts/voided per R8a.
  const finalised = useMemo<MyPayslip[]>(
    () =>
      (items ?? []).filter((p) => p?.status === 'finalised'),
    [items],
  )

  // Sort newest-first.
  const sorted = useMemo<MyPayslip[]>(
    () =>
      [...finalised].sort((a, b) => {
        const aKey = a?.pay_period?.end_date ?? a?.finalised_at ?? ''
        const bKey = b?.pay_period?.end_date ?? b?.finalised_at ?? ''
        return bKey.localeCompare(aKey)
      }),
    [finalised],
  )

  return (
    <div
      className="mx-auto w-full max-w-3xl px-4 py-6"
      data-testid="my-payslips-page"
    >
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          My payslips
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Your finalised payslips. Open the PDF for the full breakdown.
        </p>
      </header>

      {loadError && (
        <div
          role="alert"
          className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300"
          data-testid="my-payslips-error"
        >
          {loadError}
        </div>
      )}

      {loading ? (
        <p className="py-12 text-center text-sm text-gray-500 dark:text-gray-400">
          Loading…
        </p>
      ) : sorted.length === 0 ? (
        <div
          className="rounded-md border border-dashed border-gray-300 px-4 py-12 text-center text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400"
          data-testid="my-payslips-empty"
        >
          No payslips yet. They&rsquo;ll appear here once your employer
          finalises a pay run.
        </div>
      ) : (
        <div
          className="overflow-x-auto rounded-md border border-gray-200 dark:border-gray-700"
          data-testid="my-payslips-table-wrapper"
        >
          <table
            className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700"
            data-testid="my-payslips-table"
          >
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-gray-600 dark:text-gray-300">
                  Pay period
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Gross
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Net
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  PDF
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-800 dark:bg-gray-900">
              {sorted.map((p) => (
                <tr
                  key={p?.id ?? Math.random().toString(36)}
                  className="hover:bg-gray-50 dark:hover:bg-gray-800"
                  data-testid={`my-payslip-row-${p?.id ?? ''}`}
                >
                  <td className="px-4 py-2 text-gray-900 dark:text-gray-100">
                    {formatPeriodRange(p)}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-gray-900 dark:text-gray-100">
                    {formatMoney(p?.gross_pay)}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-gray-900 dark:text-gray-100">
                    {formatMoney(p?.net_pay)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <a
                      href={`/api/v2/staff/me/payslips/${p?.id}/pdf`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex min-h-[44px] items-center rounded border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
                      data-testid={`my-payslip-pdf-${p?.id ?? ''}`}
                    >
                      PDF
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function MyPayslipsPage() {
  return (
    <ModuleGate module="payroll">
      <MyPayslipsContent />
    </ModuleGate>
  )
}
