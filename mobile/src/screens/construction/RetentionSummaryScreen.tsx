import { useCallback, useRef, useEffect, useState } from 'react'
import { Page, Card, List, ListItem, Block, BlockTitle, Preloader } from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

interface RetentionSummary {
  total_retained: number
  total_released: number
  total_pending: number
  release_schedules: ReleaseSchedule[]
}

interface ReleaseSchedule {
  id: string
  project_name: string | null
  amount: number
  release_date: string
  status: string
}

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  try { return new Date(dateStr).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' }) }
  catch { return dateStr }
}

function RetentionContent() {
  const [data, setData] = useState<RetentionSummary | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async (isRefresh: boolean, signal: AbortSignal) => {
    if (isRefresh) setIsRefreshing(true); else setIsLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<RetentionSummary>('/api/v2/retentions/summary', { signal })
      setData(res.data ?? null)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') setError('Failed to load retentions')
    } finally { setIsLoading(false); setIsRefreshing(false) }
  }, [])

  useEffect(() => {
    abortRef.current?.abort()
    const c = new AbortController(); abortRef.current = c
    fetchData(false, c.signal)
    return () => c.abort()
  }, [fetchData])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const c = new AbortController(); abortRef.current = c
    await fetchData(true, c.signal)
  }, [fetchData])

  if (isLoading) {
    return (<Page data-testid="retentions-page"><div className="flex flex-1 items-center justify-center p-8"><Preloader /></div></Page>)
  }

  if (error) {
    return (<Page data-testid="retentions-page"><Block><p className="text-center text-red-600 dark:text-red-400">{error}</p></Block></Page>)
  }

  const schedules: ReleaseSchedule[] = data?.release_schedules ?? []

  return (
    <Page data-testid="retentions-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-2 px-4 pt-4">
            <Card className="text-center" data-testid="retained-card">
              <p className="text-xs text-gray-500 dark:text-gray-400">Retained</p>
              <p className="text-lg font-bold text-gray-900 dark:text-gray-100">{formatNZD(data?.total_retained)}</p>
            </Card>
            <Card className="text-center" data-testid="released-card">
              <p className="text-xs text-gray-500 dark:text-gray-400">Released</p>
              <p className="text-lg font-bold text-green-600 dark:text-green-400">{formatNZD(data?.total_released)}</p>
            </Card>
            <Card className="text-center" data-testid="pending-card">
              <p className="text-xs text-gray-500 dark:text-gray-400">Pending</p>
              <p className="text-lg font-bold text-amber-600 dark:text-amber-400">{formatNZD(data?.total_pending)}</p>
            </Card>
          </div>

          <BlockTitle>Release Schedule</BlockTitle>
          {schedules.length === 0 ? (
            <Block className="text-center"><p className="text-sm text-gray-400 dark:text-gray-500">No scheduled releases</p></Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="release-schedule-list">
              {schedules.map((s) => (
                <ListItem key={s.id}
                  title={<span className="font-medium text-gray-900 dark:text-gray-100">{s.project_name ?? 'Project'}</span>}
                  subtitle={<span className="text-xs text-gray-500 dark:text-gray-400">Release: {formatDate(s.release_date)}</span>}
                  after={<span className="font-medium text-gray-900 dark:text-gray-100">{formatNZD(s.amount)}</span>}
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
 * Retention summary — gate by `retentions` module + `building-construction` trade.
 * Requirements: 41.3, 41.4, 55.1, 55.5
 */
export default function RetentionSummaryScreen() {
  return (
    <ModuleGate moduleSlug="retentions" tradeFamily="building-construction">
      <RetentionContent />
    </ModuleGate>
  )
}
