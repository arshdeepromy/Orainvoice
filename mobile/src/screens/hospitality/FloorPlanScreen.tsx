import { useState, useCallback, useRef, useEffect } from 'react'
import { Page, Block, Preloader } from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

interface TableItem {
  id: string
  number: number
  seats: number
  status: string
  customer_name: string | null
  x: number
  y: number
}

function statusColor(status: string): string {
  switch (status) {
    case 'occupied': return 'bg-red-100 border-red-300 dark:bg-red-900/30 dark:border-red-700'
    case 'reserved': return 'bg-amber-100 border-amber-300 dark:bg-amber-900/30 dark:border-amber-700'
    default: return 'bg-green-100 border-green-300 dark:bg-green-900/30 dark:border-green-700'
  }
}

function FloorPlanContent() {
  const [tables, setTables] = useState<TableItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fetchTables = useCallback(async (isRefresh: boolean, signal: AbortSignal) => {
    if (isRefresh) setIsRefreshing(true); else setIsLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<{ items?: TableItem[]; total?: number }>('/api/v1/tables', { signal })
      setTables(res.data?.items ?? [])
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') setError('Failed to load tables')
    } finally { setIsLoading(false); setIsRefreshing(false) }
  }, [])

  useEffect(() => {
    abortRef.current?.abort()
    const c = new AbortController(); abortRef.current = c
    fetchTables(false, c.signal)
    return () => c.abort()
  }, [fetchTables])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const c = new AbortController(); abortRef.current = c
    await fetchTables(true, c.signal)
  }, [fetchTables])

  if (isLoading) {
    return (<Page data-testid="floor-plan-page"><div className="flex flex-1 items-center justify-center p-8"><Preloader /></div></Page>)
  }

  return (
    <Page data-testid="floor-plan-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {error && (
            <Block><div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">{error}</div></Block>
          )}

          {/* Visual table layout */}
          <div className="relative mx-4 mt-4 min-h-[400px] rounded-lg border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800" data-testid="floor-layout">
            {tables.map((table) => (
              <button
                key={table.id}
                type="button"
                className={`absolute flex flex-col items-center justify-center rounded-lg border-2 p-2 text-center transition-colors ${statusColor(table.status)}`}
                style={{
                  left: `${Math.min(table.x ?? 10, 80)}%`,
                  top: `${Math.min(table.y ?? 10, 80)}%`,
                  width: '60px',
                  height: '60px',
                }}
                data-testid={`table-${table.id}`}
              >
                <span className="text-sm font-bold text-gray-900 dark:text-gray-100">T{table.number}</span>
                <span className="text-xs text-gray-500 dark:text-gray-400">{table.seats}s</span>
              </button>
            ))}
          </div>

          {/* Legend */}
          <Block>
            <div className="flex gap-4 text-xs">
              <div className="flex items-center gap-1"><span className="h-3 w-3 rounded-full bg-green-400" /> Available</div>
              <div className="flex items-center gap-1"><span className="h-3 w-3 rounded-full bg-amber-400" /> Reserved</div>
              <div className="flex items-center gap-1"><span className="h-3 w-3 rounded-full bg-red-400" /> Occupied</div>
            </div>
          </Block>

          {tables.length === 0 && !isLoading && (
            <Block className="text-center"><p className="text-sm text-gray-400 dark:text-gray-500">No tables configured</p></Block>
          )}
        </div>
      </PullRefresh>
    </Page>
  )
}

/**
 * Floor Plan screen — visual table layout. Gate by `tables` module + `food-hospitality` trade.
 * Requirements: 42.1, 55.1, 55.5
 */
export default function FloorPlanScreen() {
  return (
    <ModuleGate moduleSlug="tables" tradeFamily="food-hospitality">
      <FloorPlanContent />
    </ModuleGate>
  )
}
