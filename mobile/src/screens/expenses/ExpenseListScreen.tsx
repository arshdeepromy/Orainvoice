import { useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Searchbar,
  List,
  ListItem,
  Block,
  Preloader,
} from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import KonstaFAB from '@/components/konsta/KonstaFAB'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface Expense {
  id: string
  description: string | null
  amount: number
  category: string | null
  date: string
  receipt_url: string | null
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

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}

/* ------------------------------------------------------------------ */
/* Receipt icon                                                       */
/* ------------------------------------------------------------------ */

function ReceiptIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
      <circle cx="12" cy="13" r="4" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

function ExpensesContent() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<Expense[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchExpenses = useCallback(
    async (isRefresh: boolean, signal: AbortSignal) => {
      if (isRefresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const params: Record<string, string | number> = { offset: 0, limit: PAGE_SIZE }
        if (search.trim()) params.search = search.trim()

        const res = await apiClient.get<{ items?: Expense[]; total?: number }>(
          '/api/v2/expenses',
          { params, signal },
        )
        setItems(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load expenses')
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
    fetchExpenses(false, controller.signal)
    return () => controller.abort()
  }, [fetchExpenses])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchExpenses(true, controller.signal)
  }, [fetchExpenses])

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value),
    [],
  )
  const handleSearchClear = useCallback(() => setSearch(''), [])

  if (isLoading && items.length === 0) {
    return (
      <Page data-testid="expenses-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="expenses-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          <div className="px-4 pt-3">
            <Searchbar
              value={search}
              onChange={handleSearchChange}
              onClear={handleSearchClear}
              placeholder="Search expenses…"
              data-testid="expenses-searchbar"
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
              <p className="text-sm text-gray-400 dark:text-gray-500">No expenses found</p>
            </Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="expenses-list">
              {items.map((expense) => (
                <ListItem
                  key={expense.id}
                  title={
                    <span className="font-bold text-gray-900 dark:text-gray-100">
                      {expense.description ?? 'Expense'}
                    </span>
                  }
                  subtitle={
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {formatDate(expense.date)}{expense.category ? ` · ${expense.category}` : ''}
                    </span>
                  }
                  after={
                    <div className="flex items-center gap-2">
                      {expense.receipt_url && (
                        <ReceiptIcon className="h-4 w-4 text-green-500" />
                      )}
                      <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                        {formatNZD(expense.amount)}
                      </span>
                    </div>
                  }
                  data-testid={`expense-item-${expense.id}`}
                />
              ))}
            </List>
          )}
        </div>
      </PullRefresh>

      <KonstaFAB label="+ New Expense" onClick={() => navigate('/expenses/new')} />
    </Page>
  )
}

/**
 * Expenses screen — list with Camera button for receipt capture. FAB.
 * ModuleGate `expenses`.
 *
 * Requirements: 35.1, 35.2, 35.3, 35.4, 35.5, 50.2, 55.1
 */
export default function ExpenseListScreen() {
  return (
    <ModuleGate moduleSlug="expenses">
      <ExpensesContent />
    </ModuleGate>
  )
}
