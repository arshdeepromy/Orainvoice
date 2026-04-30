import { useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Page, Searchbar, List, ListItem, Block, Preloader } from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import StatusBadge from '@/components/konsta/StatusBadge'
import apiClient from '@/api/client'

interface ProgressClaim {
  id: string
  claim_number: string
  project_name: string | null
  amount: number
  status: string
  created_at: string
}

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function ProgressClaimContent() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<ProgressClaim[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async (isRefresh: boolean, signal: AbortSignal) => {
    if (isRefresh) setIsRefreshing(true); else setIsLoading(true)
    setError(null)
    try {
      const params: Record<string, string | number> = { offset: 0, limit: 25 }
      if (search.trim()) params.search = search.trim()
      const res = await apiClient.get<{ items?: ProgressClaim[]; total?: number }>('/api/v2/progress-claims', { params, signal })
      setItems(res.data?.items ?? [])
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') setError('Failed to load claims')
    } finally { setIsLoading(false); setIsRefreshing(false) }
  }, [search])

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

  if (isLoading && items.length === 0) {
    return (<Page data-testid="progress-claims-page"><div className="flex flex-1 items-center justify-center p-8"><Preloader /></div></Page>)
  }

  return (
    <Page data-testid="progress-claims-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          <div className="px-4 pt-3">
            <Searchbar value={search} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)} onClear={() => setSearch('')} placeholder="Search claims…" data-testid="claims-searchbar" />
          </div>
          {error && (<Block><div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">{error}</div></Block>)}
          {items.length === 0 && !isLoading ? (
            <Block className="text-center"><p className="text-sm text-gray-400 dark:text-gray-500">No progress claims found</p></Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="claims-list">
              {items.map((claim) => (
                <ListItem key={claim.id} link onClick={() => navigate(`/construction/${claim.id}`)}
                  title={<span className="font-bold text-gray-900 dark:text-gray-100">{claim.claim_number ?? 'Claim'}</span>}
                  subtitle={<span className="text-xs text-gray-500 dark:text-gray-400">{claim.project_name ?? 'No project'}</span>}
                  after={<div className="flex flex-col items-end gap-1"><span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">{formatNZD(claim.amount)}</span><StatusBadge status={claim.status ?? 'draft'} size="sm" /></div>}
                  data-testid={`claim-item-${claim.id}`}
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
 * Progress Claims screen — gate by `progress_claims` module + `building-construction` trade.
 * Requirements: 41.1, 55.1, 55.5
 */
export default function ProgressClaimListScreen() {
  return (
    <ModuleGate moduleSlug="progress_claims" tradeFamily="building-construction">
      <ProgressClaimContent />
    </ModuleGate>
  )
}
