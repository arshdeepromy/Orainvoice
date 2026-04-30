import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Page, Card, List, ListItem, Block, Preloader, Chip } from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import KonstaFAB from '@/components/konsta/KonstaFAB'
import apiClient from '@/api/client'

interface ComplianceDocument {
  id: string
  name: string | null
  document_type: string | null
  expiry_date: string | null
  status: string
  file_url: string | null
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'No expiry'
  try { return new Date(dateStr).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' }) }
  catch { return dateStr }
}

function expiryPillColors(status: string) {
  switch (status) {
    case 'valid':
      return { fillBgIos: 'bg-green-100', fillBgMaterial: 'bg-green-100', fillTextIos: 'text-green-700', fillTextMaterial: 'text-green-700' }
    case 'expiring_soon':
      return { fillBgIos: 'bg-amber-100', fillBgMaterial: 'bg-amber-100', fillTextIos: 'text-amber-700', fillTextMaterial: 'text-amber-700' }
    case 'expired':
      return { fillBgIos: 'bg-red-100', fillBgMaterial: 'bg-red-100', fillTextIos: 'text-red-700', fillTextMaterial: 'text-red-700' }
    default:
      return { fillBgIos: 'bg-gray-100', fillBgMaterial: 'bg-gray-100', fillTextIos: 'text-gray-700', fillTextMaterial: 'text-gray-700' }
  }
}

const statusLabel: Record<string, string> = {
  valid: 'Valid',
  expiring_soon: 'Expiring',
  expired: 'Expired',
}

function ComplianceContent() {
  const navigate = useNavigate()
  const [documents, setDocuments] = useState<ComplianceDocument[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fetchDocs = useCallback(async (isRefresh: boolean, signal: AbortSignal) => {
    if (isRefresh) setIsRefreshing(true); else setIsLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<{ items?: ComplianceDocument[]; total?: number }>('/api/v2/compliance-docs', { params: { offset: 0, limit: 100 }, signal })
      setDocuments(res.data?.items ?? [])
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') setError('Failed to load documents')
    } finally { setIsLoading(false); setIsRefreshing(false) }
  }, [])

  useEffect(() => {
    abortRef.current?.abort()
    const c = new AbortController(); abortRef.current = c
    fetchDocs(false, c.signal)
    return () => c.abort()
  }, [fetchDocs])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const c = new AbortController(); abortRef.current = c
    await fetchDocs(true, c.signal)
  }, [fetchDocs])

  const statusCounts = useMemo(() => {
    const counts = { valid: 0, expiring_soon: 0, expired: 0 }
    for (const doc of documents) {
      const s = doc.status ?? 'valid'
      if (s in counts) counts[s as keyof typeof counts]++
    }
    return counts
  }, [documents])

  const categories = useMemo(() => {
    const map: Record<string, ComplianceDocument[]> = {}
    for (const doc of documents) {
      const type = doc.document_type ?? 'Other'
      if (!map[type]) map[type] = []
      map[type].push(doc)
    }
    return map
  }, [documents])

  const filteredDocs = selectedCategory ? categories[selectedCategory] ?? [] : documents

  if (isLoading && documents.length === 0) {
    return (<Page data-testid="compliance-page"><div className="flex flex-1 items-center justify-center p-8"><Preloader /></div></Page>)
  }

  return (
    <Page data-testid="compliance-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-2 px-4 pt-4">
            <Card className="text-center" data-testid="valid-count">
              <span className="text-2xl font-bold text-green-600 dark:text-green-400">{statusCounts.valid}</span>
              <p className="text-xs text-gray-500 dark:text-gray-400">Valid</p>
            </Card>
            <Card className="text-center" data-testid="expiring-count">
              <span className="text-2xl font-bold text-amber-600 dark:text-amber-400">{statusCounts.expiring_soon}</span>
              <p className="text-xs text-gray-500 dark:text-gray-400">Expiring</p>
            </Card>
            <Card className="text-center" data-testid="expired-count">
              <span className="text-2xl font-bold text-red-600 dark:text-red-400">{statusCounts.expired}</span>
              <p className="text-xs text-gray-500 dark:text-gray-400">Expired</p>
            </Card>
          </div>

          {/* Category filter chips */}
          <div className="flex flex-wrap gap-2 px-4 py-3" data-testid="category-chips">
            <Chip
              className={`cursor-pointer ${selectedCategory === null ? 'font-semibold' : ''}`}
              colors={selectedCategory === null ? { fillBgIos: 'bg-primary', fillBgMaterial: 'bg-primary', fillTextIos: 'text-white', fillTextMaterial: 'text-white' } : undefined}
              onClick={() => setSelectedCategory(null)}
            >
              All ({documents.length})
            </Chip>
            {Object.entries(categories).map(([type, docs]) => (
              <Chip
                key={type}
                className={`cursor-pointer ${selectedCategory === type ? 'font-semibold' : ''}`}
                colors={selectedCategory === type ? { fillBgIos: 'bg-primary', fillBgMaterial: 'bg-primary', fillTextIos: 'text-white', fillTextMaterial: 'text-white' } : undefined}
                onClick={() => setSelectedCategory(type)}
              >
                {type} ({docs.length})
              </Chip>
            ))}
          </div>

          {error && (<Block><div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">{error}</div></Block>)}

          {/* Document list */}
          {filteredDocs.length === 0 ? (
            <Block className="text-center"><p className="text-sm text-gray-400 dark:text-gray-500">No compliance documents</p></Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="compliance-list">
              {filteredDocs.map((doc) => (
                <ListItem key={doc.id}
                  title={<span className="font-medium text-gray-900 dark:text-gray-100">{doc.name ?? 'Document'}</span>}
                  subtitle={<span className="text-xs text-gray-500 dark:text-gray-400">{doc.document_type ?? 'Unknown'} · Expires: {formatDate(doc.expiry_date)}</span>}
                  after={
                    <Chip className="text-xs" colors={expiryPillColors(doc.status)}>
                      {statusLabel[doc.status] ?? 'Valid'}
                    </Chip>
                  }
                  data-testid={`compliance-doc-${doc.id}`}
                />
              ))}
            </List>
          )}
        </div>
      </PullRefresh>

      <KonstaFAB label="+ Upload" onClick={() => navigate('/compliance/upload')} />
    </Page>
  )
}

/**
 * Compliance Documents screen — expiry pills, Camera upload.
 * ModuleGate `compliance_docs`.
 * Requirements: 44.1, 44.2, 44.3, 44.4, 50.2, 55.1
 */
export default function ComplianceDashboardScreen() {
  return (
    <ModuleGate moduleSlug="compliance_docs">
      <ComplianceContent />
    </ModuleGate>
  )
}
