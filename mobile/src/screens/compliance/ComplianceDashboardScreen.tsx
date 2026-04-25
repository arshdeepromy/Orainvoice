import { useState, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ComplianceDocument, ComplianceStatus } from '@shared/types/compliance'
import { useApiList } from '@/hooks/useApiList'
import { MobileCard, MobileListItem, MobileBadge, MobileButton, MobileSpinner } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'No expiry'
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

const statusVariant: Record<ComplianceStatus, 'paid' | 'overdue' | 'draft'> = {
  valid: 'paid',
  expiring_soon: 'draft',
  expired: 'overdue',
}

const statusLabel: Record<ComplianceStatus, string> = {
  valid: 'Valid',
  expiring_soon: 'Expiring Soon',
  expired: 'Expired',
}

function isExpiringSoon(expiryDate: string | null): boolean {
  if (!expiryDate) return false
  const expiry = new Date(expiryDate)
  const now = new Date()
  const thirtyDays = 30 * 24 * 60 * 60 * 1000
  return expiry.getTime() - now.getTime() <= thirtyDays && expiry.getTime() > now.getTime()
}

/**
 * Compliance dashboard screen — document categories, counts, expiry status.
 * Document list with name, type, expiry date, status. 30-day expiry badge.
 * Pull-to-refresh. Wrapped in ModuleGate at the route level.
 *
 * Requirements: 27.1, 27.4, 27.6, 27.7
 */
export default function ComplianceDashboardScreen() {
  const navigate = useNavigate()
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)

  const {
    items: documents,
    isLoading,
    isRefreshing,
    refresh,
  } = useApiList<ComplianceDocument>({
    endpoint: '/api/v2/compliance-docs',
    dataKey: 'items',
    pageSize: 100,
  })

  // Group by document type (category)
  const categories = useMemo(() => {
    const map: Record<string, ComplianceDocument[]> = {}
    for (const doc of documents) {
      const type = doc.document_type ?? 'Other'
      if (!map[type]) map[type] = []
      map[type].push(doc)
    }
    return map
  }, [documents])

  // Status counts
  const statusCounts = useMemo(() => {
    const counts = { valid: 0, expiring_soon: 0, expired: 0 }
    for (const doc of documents) {
      const status = doc.status ?? 'valid'
      if (counts[status] !== undefined) counts[status]++
    }
    return counts
  }, [documents])

  const filteredDocs = selectedCategory
    ? categories[selectedCategory] ?? []
    : documents

  const handleDocTap = useCallback(
    (doc: ComplianceDocument) => {
      // Open document preview if file_url exists
      if (doc.file_url) {
        window.open(doc.file_url, '_blank')
      }
    },
    [],
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Compliance
          </h1>
          <MobileButton
            variant="primary"
            size="sm"
            onClick={() => navigate('/compliance/upload')}
            icon={
              <svg
                className="h-4 w-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            }
          >
            Upload
          </MobileButton>
        </div>

        {/* Status summary cards */}
        <div className="grid grid-cols-3 gap-2">
          <MobileCard padding="p-3">
            <div className="flex flex-col items-center">
              <span className="text-2xl font-bold text-green-600 dark:text-green-400">
                {statusCounts.valid}
              </span>
              <span className="text-xs text-gray-500 dark:text-gray-400">Valid</span>
            </div>
          </MobileCard>
          <MobileCard padding="p-3">
            <div className="flex flex-col items-center">
              <span className="text-2xl font-bold text-amber-600 dark:text-amber-400">
                {statusCounts.expiring_soon}
              </span>
              <span className="text-xs text-gray-500 dark:text-gray-400">Expiring</span>
            </div>
          </MobileCard>
          <MobileCard padding="p-3">
            <div className="flex flex-col items-center">
              <span className="text-2xl font-bold text-red-600 dark:text-red-400">
                {statusCounts.expired}
              </span>
              <span className="text-xs text-gray-500 dark:text-gray-400">Expired</span>
            </div>
          </MobileCard>
        </div>

        {/* Category filter chips */}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setSelectedCategory(null)}
            className={`min-h-[36px] rounded-full px-3 py-1 text-sm font-medium transition-colors ${
              selectedCategory === null
                ? 'bg-blue-600 text-white dark:bg-blue-500'
                : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
            }`}
          >
            All ({documents.length})
          </button>
          {Object.entries(categories).map(([type, docs]) => (
            <button
              key={type}
              type="button"
              onClick={() => setSelectedCategory(type)}
              className={`min-h-[36px] rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                selectedCategory === type
                  ? 'bg-blue-600 text-white dark:bg-blue-500'
                  : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
              }`}
            >
              {type} ({docs.length})
            </button>
          ))}
        </div>

        {/* Document list */}
        {isLoading ? (
          <div className="flex justify-center py-8">
            <MobileSpinner size="md" />
          </div>
        ) : filteredDocs.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-400 dark:text-gray-500">
            No compliance documents
          </p>
        ) : (
          <div className="flex flex-col">
            {filteredDocs.map((doc) => (
              <MobileListItem
                key={doc.id}
                title={doc.name ?? 'Document'}
                subtitle={`${doc.document_type ?? 'Unknown'} · Expires: ${formatDate(doc.expiry_date)}`}
                trailing={
                  <div className="flex flex-col items-end gap-1">
                    <MobileBadge
                      label={statusLabel[doc.status] ?? 'Valid'}
                      variant={statusVariant[doc.status] ?? 'paid'}
                    />
                    {isExpiringSoon(doc.expiry_date) && (
                      <span className="text-xs font-medium text-amber-600 dark:text-amber-400">
                        30 days
                      </span>
                    )}
                  </div>
                }
                onTap={() => handleDocTap(doc)}
              />
            ))}
          </div>
        )}
      </div>
    </PullRefresh>
  )
}
