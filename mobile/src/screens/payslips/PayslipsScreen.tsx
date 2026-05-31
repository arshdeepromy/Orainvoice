/**
 * PayslipsScreen — mobile staff self-service payslips list (Phase 4
 * task D11 / G9).
 *
 * Mounted at `/payslips` behind `AuthGuard` (in StackRoutes) and
 * gated by the `payroll` module via `ModuleGate`. Server enforces
 * ownership via `staff_members.user_id`.
 *
 * Per design.md §6.8 + R8a + G9 + the mobile-app steering rules:
 *   - Calls `GET /api/v2/staff/me/payslips?limit=50` on mount via the
 *     shared `apiClient` axios instance.
 *   - Renders a Konsta List of finalised payslips with period range,
 *     gross + net, and a "PDF" button per row.
 *   - Drafts/voided are filtered server-side per R8a — but we
 *     defensively also filter client-side.
 *   - "PDF" download:
 *       * On native (`Capacitor.isNativePlatform()`), opens the
 *         system share sheet via `@capacitor/share` so the staff can
 *         save / send the PDF off-device.
 *       * On web (jsdom / Capacitor browser), falls back to a normal
 *         `window.open` of the same URL — the auth cookie / bearer
 *         token already on the request validates the session
 *         server-side.
 *   - 44×44 touch targets via Konsta defaults; dark-mode classes;
 *     `pb-safe` for safe-area; `pb-24` to clear the bottom tab bar.
 *   - AbortController on the fetch effect.
 *
 * A More-menu entry exists at `mobile/src/screens/more/MoreMenuScreen.tsx`
 * (id `payslips`, `moduleSlug: 'payroll'`, category `operations`) so the
 * route is reachable from the More tab in addition to deep links.
 *
 * **Validates: Staff Management Phase 4 task D11, R8a, G9**
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Page,
  List,
  ListItem,
  Block,
  Preloader,
} from 'konsta/react'

import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types — mirror MyPayslip schema in the backend                     */
/* ------------------------------------------------------------------ */

type PayslipStatus = 'draft' | 'finalised' | 'voided'

interface PayPeriod {
  id: string
  start_date: string
  end_date: string
  pay_date: string
  status: string
}

interface MyPayslip {
  id: string
  pay_period_id: string
  pay_period: PayPeriod | null
  status: PayslipStatus | string
  gross_pay: string
  net_pay: string
  finalised_at: string | null
  pdf_url: string | null
}

interface MyPayslipListResponse {
  items?: MyPayslip[]
  total?: number
}

const PAGE_SIZE = 50

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function isNativePlatform(): boolean {
  return !!(window as unknown as {
    Capacitor?: { isNativePlatform?: () => boolean }
  }).Capacitor?.isNativePlatform?.()
}

function formatNZD(value: string | number | null | undefined): string {
  const n = typeof value === 'string' ? Number(value) : (value ?? 0)
  if (!Number.isFinite(n)) {
    return `NZD0.00`
  }
  return `NZD${(n as number).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
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

/* ------------------------------------------------------------------ */
/* Inner content                                                      */
/* ------------------------------------------------------------------ */

function PayslipsContent() {
  const [items, setItems] = useState<MyPayslip[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchPayslips = useCallback(
    async (isRefresh: boolean, signal: AbortSignal) => {
      if (isRefresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const res = await apiClient.get<MyPayslipListResponse>(
          '/api/v2/staff/me/payslips',
          { params: { offset: 0, limit: PAGE_SIZE }, signal },
        )
        setItems(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return
        if (
          err instanceof DOMException &&
          err.name === 'AbortError'
        )
          return
        setError('Failed to load payslips')
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [],
  )

  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    fetchPayslips(false, controller.signal)
    return () => controller.abort()
  }, [fetchPayslips])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchPayslips(true, controller.signal)
  }, [fetchPayslips])

  // Defensive client-side filter (server already filters per R8a).
  const finalised = useMemo<MyPayslip[]>(
    () => (items ?? []).filter((p) => p?.status === 'finalised'),
    [items],
  )

  // Sort newest-first by pay_period.end_date.
  const sorted = useMemo<MyPayslip[]>(
    () =>
      [...finalised].sort((a, b) => {
        const aKey = a?.pay_period?.end_date ?? a?.finalised_at ?? ''
        const bKey = b?.pay_period?.end_date ?? b?.finalised_at ?? ''
        return bKey.localeCompare(aKey)
      }),
    [finalised],
  )

  const handleDownloadPdf = useCallback(
    async (payslip: MyPayslip) => {
      if (!payslip?.id) return
      const url = `/api/v2/staff/me/payslips/${payslip.id}/pdf`
      // Native: try the Capacitor Share sheet so the staff can save /
      // send the PDF off-device. On any failure (e.g. the user
      // cancelled the share sheet) we silently fall back to a normal
      // window.open.
      if (isNativePlatform()) {
        try {
          const { Share } = await import('@capacitor/share')
          const periodLabel =
            payslip?.pay_period?.end_date ?? 'payslip'
          await Share.share({
            title: 'Payslip',
            text: `Payslip — ${periodLabel}`,
            url,
            dialogTitle: 'Save or share payslip',
          })
          return
        } catch {
          // fall through to window.open
        }
      }
      try {
        window.open(url, '_blank', 'noopener,noreferrer')
      } catch {
        // Some Capacitor browsers may block window.open — last-resort
        // navigate via location.assign which keeps the auth cookie.
        if (typeof window !== 'undefined' && window.location) {
          window.location.assign(url)
        }
      }
    },
    [],
  )

  if (isLoading && items.length === 0) {
    return (
      <Page data-testid="payslips-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="payslips-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24 pb-safe">
          <div className="px-4 pb-1 pt-4">
            <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
              My payslips
            </h1>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Your finalised payslips. Tap PDF to download or share.
            </p>
          </div>

          {error && (
            <Block>
              <div
                role="alert"
                className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
                data-testid="payslips-error"
              >
                {error}
                <button
                  type="button"
                  onClick={() => handleRefresh()}
                  className="ml-2 font-medium underline"
                >
                  Retry
                </button>
              </div>
            </Block>
          )}

          {sorted.length === 0 && !isLoading && !error ? (
            <Block className="text-center" data-testid="payslips-empty">
              <p className="text-sm text-gray-400 dark:text-gray-500">
                No payslips yet. They&rsquo;ll appear here once your employer
                finalises a pay run.
              </p>
            </Block>
          ) : sorted.length > 0 ? (
            <List strongIos outlineIos dividersIos data-testid="payslips-list">
              {sorted.map((payslip) => (
                <ListItem
                  key={payslip.id}
                  title={
                    <span className="font-bold text-gray-900 dark:text-gray-100">
                      {formatPeriodRange(payslip)}
                    </span>
                  }
                  subtitle={
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      Net {formatNZD(payslip.net_pay)} · Gross{' '}
                      {formatNZD(payslip.gross_pay)}
                    </span>
                  }
                  after={
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        void handleDownloadPdf(payslip)
                      }}
                      className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded border border-gray-300 px-3 py-2 text-xs font-semibold text-gray-700 active:bg-gray-100 dark:border-gray-600 dark:text-gray-200 dark:active:bg-gray-800"
                      data-testid={`payslip-pdf-${payslip.id}`}
                      aria-label={`Download payslip PDF for ${formatPeriodRange(payslip)}`}
                    >
                      PDF
                    </button>
                  }
                  data-testid={`payslip-item-${payslip.id}`}
                />
              ))}
            </List>
          ) : null}
        </div>
      </PullRefresh>
    </Page>
  )
}

/* ------------------------------------------------------------------ */
/* Module-gated entry point                                            */
/* ------------------------------------------------------------------ */

export default function PayslipsScreen() {
  return (
    <ModuleGate moduleSlug="payroll">
      <PayslipsContent />
    </ModuleGate>
  )
}
