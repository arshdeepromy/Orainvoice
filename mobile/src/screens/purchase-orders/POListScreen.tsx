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
import StatusBadge from '@/components/konsta/StatusBadge'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface PurchaseOrder {
  id: string
  po_number: string
  supplier_name: string | null
  amount: number
  status: string
  created_at: string
}

const PAGE_SIZE = 25

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

function POListContent() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<PurchaseOrder[]>([])
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

        const res = await apiClient.get<{ items?: PurchaseOrder[]; total?: number }>(
          '/api/v2/purchase-orders',
          { params, signal },
        )
        setItems(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load purchase orders')
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

  const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value), [])
  const handleSearchClear = useCallback(() => setSearch(''), [])

  if (isLoading && items.length === 0) {
    return (
      <Page data-testid="po-list-page">
        <div className="flex flex-1 items-center justify-center p-8"><Preloader /></div>
      </Page>
    )
  }

  return (
    <Page data-testid="po-list-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          <div className="px-4 pt-3">
            <Searchbar value={search} onChange={handleSearchChange} onClear={handleSearchClear} placeholder="Search POs…" data-testid="po-searchbar" />
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
              <p className="text-sm text-gray-400 dark:text-gray-500">No purchase orders found</p>
            </Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="po-list">
              {items.map((po) => (
                <ListItem
                  key={po.id}
                  link
                  onClick={() => navigate(`/purchase-orders/${po.id}`)}
                  title={<span className="font-bold text-gray-900 dark:text-gray-100">{po.po_number ?? 'PO'}</span>}
                  subtitle={<span className="text-xs text-gray-500 dark:text-gray-400">{po.supplier_name ?? 'Unknown Supplier'}</span>}
                  after={
                    <div className="flex flex-col items-end gap-1">
                      <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">{formatNZD(po.amount)}</span>
                      <StatusBadge status={po.status ?? 'draft'} size="sm" />
                    </div>
                  }
                  data-testid={`po-item-${po.id}`}
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
 * Purchase Orders screen — list + detail. ModuleGate `purchase_orders`.
 * Requirements: 40.1, 40.2, 40.3, 55.1
 */
export default function POListScreen() {
  return (
    <ModuleGate moduleSlug="purchase_orders">
      <POListContent />
    </ModuleGate>
  )
}
