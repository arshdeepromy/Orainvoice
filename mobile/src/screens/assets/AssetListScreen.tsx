import { useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Page, Searchbar, List, ListItem, Block, Preloader } from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

interface Asset {
  id: string
  name: string
  category: string | null
  value: number
  depreciation_rate: number | null
  current_value: number | null
  status: string | null
}

const PAGE_SIZE = 25

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function AssetListContent() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<Asset[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async (isRefresh: boolean, signal: AbortSignal) => {
    if (isRefresh) setIsRefreshing(true); else setIsLoading(true)
    setError(null)
    try {
      const params: Record<string, string | number> = { offset: 0, limit: PAGE_SIZE }
      if (search.trim()) params.search = search.trim()
      const res = await apiClient.get<{ items?: Asset[]; total?: number }>('/api/v1/assets', { params, signal })
      setItems(res.data?.items ?? [])
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') setError('Failed to load assets')
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
    return (<Page data-testid="assets-page"><div className="flex flex-1 items-center justify-center p-8"><Preloader /></div></Page>)
  }

  return (
    <Page data-testid="assets-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          <div className="px-4 pt-3">
            <Searchbar value={search} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)} onClear={() => setSearch('')} placeholder="Search assets…" data-testid="assets-searchbar" />
          </div>
          {error && (<Block><div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">{error}</div></Block>)}
          {items.length === 0 && !isLoading ? (
            <Block className="text-center"><p className="text-sm text-gray-400 dark:text-gray-500">No assets found</p></Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="assets-list">
              {items.map((asset) => (
                <ListItem key={asset.id} link onClick={() => navigate(`/assets/${asset.id}`)}
                  title={<span className="font-bold text-gray-900 dark:text-gray-100">{asset.name ?? 'Asset'}</span>}
                  subtitle={<span className="text-xs text-gray-500 dark:text-gray-400">{asset.category ?? 'General'}{asset.depreciation_rate ? ` · ${asset.depreciation_rate}% dep.` : ''}</span>}
                  after={
                    <div className="flex flex-col items-end gap-1">
                      <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">{formatNZD(asset.current_value ?? asset.value)}</span>
                      {asset.current_value != null && asset.current_value < asset.value && (
                        <span className="text-xs text-gray-400 line-through">{formatNZD(asset.value)}</span>
                      )}
                    </div>
                  }
                  data-testid={`asset-item-${asset.id}`}
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
 * Assets screen — list + detail. ModuleGate `assets`.
 * Requirements: 43.1, 43.2, 43.3, 55.1
 */
export default function AssetListScreen() {
  return (
    <ModuleGate moduleSlug="assets">
      <AssetListContent />
    </ModuleGate>
  )
}
