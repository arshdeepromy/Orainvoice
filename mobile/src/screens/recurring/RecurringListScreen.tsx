import { useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Searchbar,
  List,
  ListItem,
  Block,
  Preloader,
  Chip,
} from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import StatusBadge from '@/components/konsta/StatusBadge'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface RecurringInvoice {
  id: string
  customer_name: string | null
  amount: number
  frequency: string
  next_run_date: string | null
  status: string
}

const PAGE_SIZE = 25

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'N/A'
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
  } catch {
    return dateStr
  }
}

function frequencyChipColors(freq: string) {
  switch (freq) {
    case 'weekly':
      return { fillBgIos: 'bg-blue-100', fillBgMaterial: 'bg-blue-100', fillTextIos: 'text-blue-700', fillTextMaterial: 'text-blue-700' }
    case 'monthly':
      return { fillBgIos: 'bg-green-100', fillBgMaterial: 'bg-green-100', fillTextIos: 'text-green-700', fillTextMaterial: 'text-green-700' }
    case 'quarterly':
      return { fillBgIos: 'bg-purple-100', fillBgMaterial: 'bg-purple-100', fillTextIos: 'text-purple-700', fillTextMaterial: 'text-purple-700' }
    case 'yearly':
      return { fillBgIos: 'bg-amber-100', fillBgMaterial: 'bg-amber-100', fillTextIos: 'text-amber-700', fillTextMaterial: 'text-amber-700' }
    default:
      return { fillBgIos: 'bg-gray-100', fillBgMaterial: 'bg-gray-100', fillTextIos: 'text-gray-700', fillTextMaterial: 'text-gray-700' }
  }
}

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

function RecurringContent() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<RecurringInvoice[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(
    async (isRefresh: boolean, signal: AbortSignal) => {
      if (isRefresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const params: Record<string, string | number> = { offset: 0, limit: PAGE_SIZE }
        if (search.trim()) params.search = search.trim()

        const res = await apiClient.get<{ items?: RecurringInvoice[]; total?: number }>(
          '/api/v2/recurring',
          { params, signal },
        )
        setItems(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load recurring invoices')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [search],
  )

  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    fetchData(false, controller.signal)
    return () => controller.abort()
  }, [fetchData])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchData(true, controller.signal)
  }, [fetchData])

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value),
    [],
  )
  const handleSearchClear = useCallback(() => setSearch(''), [])

  if (isLoading && items.length === 0) {
    return (
      <Page data-testid="recurring-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="recurring-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          <div className="px-4 pt-3">
            <Searchbar
              value={search}
              onChange={handleSearchChange}
              onClear={handleSearchClear}
              placeholder="Search recurring…"
              data-testid="recurring-searchbar"
            />
          </div>

          {error && (
            <Block>
              <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
                {error}
                <button type="button" onClick={() => handleRefresh()} className="ml-2 font-medium underline">Retry</button>
              </div>
            </Block>
          )}

          {items.length === 0 && !isLoading ? (
            <Block className="text-center">
              <p className="text-sm text-gray-400 dark:text-gray-500">No recurring invoices found</p>
            </Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="recurring-list">
              {items.map((r) => (
                <ListItem
                  key={r.id}
                  link
                  onClick={() => navigate(`/recurring/${r.id}`)}
                  title={
                    <span className="font-bold text-gray-900 dark:text-gray-100">
                      {r.customer_name ?? 'Unknown Customer'}
                    </span>
                  }
                  subtitle={
                    <span className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                      <Chip className="text-xs" colors={frequencyChipColors(r.frequency ?? 'monthly')}>
                        {(r.frequency ?? 'monthly').charAt(0).toUpperCase() + (r.frequency ?? 'monthly').slice(1)}
                      </Chip>
                      <span>Next: {formatDate(r.next_run_date)}</span>
                    </span>
                  }
                  after={
                    <div className="flex flex-col items-end gap-1">
                      <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                        {formatNZD(r.amount)}
                      </span>
                      <StatusBadge status={r.status ?? 'active'} size="sm" />
                    </div>
                  }
                  data-testid={`recurring-item-${r.id}`}
                />
              ))}
            </List>
          )}
        </div>
      </PullRefresh>
    </Page>
  )
}

/**
 * Recurring Invoices screen — list with frequency badge.
 * ModuleGate `recurring_invoices`.
 *
 * Requirements: 39.1, 39.2, 39.3, 55.1
 */
export default function RecurringListScreen() {
  return (
    <ModuleGate moduleSlug="recurring_invoices">
      <RecurringContent />
    </ModuleGate>
  )
}
