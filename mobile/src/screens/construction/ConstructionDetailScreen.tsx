import { useParams } from 'react-router-dom'
import { Page, List, ListItem, Block, BlockTitle, Preloader } from 'konsta/react'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import { useApiDetail } from '@/hooks/useApiDetail'
import StatusBadge from '@/components/konsta/StatusBadge'

interface ConstructionItem {
  id: string
  type: 'claim' | 'variation'
  number: string
  project_name: string | null
  description: string | null
  amount: number
  status: string
  approval_status: string | null
  created_at: string
  line_items: ConstructionLineItem[]
}

interface ConstructionLineItem {
  id: string
  description: string
  quantity: number
  unit_price: number
  amount: number
}

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  try { return new Date(dateStr).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' }) }
  catch { return dateStr }
}

/**
 * Construction detail — progress claims and variations with full breakdown.
 * Requirements: 41.1, 41.2
 */
export default function ConstructionDetailScreen() {
  const { id } = useParams<{ id: string }>()

  const { data: item, isLoading, error } = useApiDetail<ConstructionItem>({
    endpoint: `/api/v2/progress-claims/${id}`,
  })

  if (isLoading) {
    return (
      <Page data-testid="construction-detail-page">
        <KonstaNavbar title="Detail" showBack />
        <div className="flex flex-1 items-center justify-center p-8"><Preloader /></div>
      </Page>
    )
  }

  if (error || !item) {
    return (
      <Page data-testid="construction-detail-page">
        <KonstaNavbar title="Detail" showBack />
        <Block><p className="text-center text-red-600 dark:text-red-400">{error ?? 'Item not found'}</p></Block>
      </Page>
    )
  }

  const lineItems: ConstructionLineItem[] = item.line_items ?? []
  const typeLabel = item.type === 'claim' ? 'Progress Claim' : 'Variation'

  return (
    <Page data-testid="construction-detail-page">
      <KonstaNavbar
        title={item.number ?? typeLabel}
        subtitle={item.project_name ?? 'No project'}
        showBack
      />

      <div className="flex flex-col pb-24">
        <Block className="flex justify-end">
          <StatusBadge status={item.status ?? 'draft'} size="md" />
        </Block>

        {/* Details */}
        <BlockTitle>Details</BlockTitle>
        <List strongIos outlineIos dividersIos>
          <ListItem title="Type" after={typeLabel} />
          <ListItem title="Created" after={formatDate(item.created_at)} />
          {item.approval_status && <ListItem title="Approval" after={<span className="capitalize">{item.approval_status}</span>} />}
        </List>

        {/* Description */}
        {item.description && (
          <>
            <BlockTitle>Description</BlockTitle>
            <Block><p className="text-sm text-gray-700 dark:text-gray-300">{item.description}</p></Block>
          </>
        )}

        {/* Breakdown */}
        <BlockTitle>Breakdown ({lineItems.length})</BlockTitle>
        {lineItems.length === 0 ? (
          <Block><p className="text-sm text-gray-500 dark:text-gray-400">No line items</p></Block>
        ) : (
          <List strongIos outlineIos dividersIos>
            {lineItems.map((li) => (
              <ListItem key={li.id}
                title={li.description || 'Item'}
                subtitle={<span className="text-xs text-gray-500 dark:text-gray-400">{li.quantity ?? 0} × {formatNZD(li.unit_price)}</span>}
                after={<span className="font-medium">{formatNZD(li.amount)}</span>}
              />
            ))}
          </List>
        )}

        <Block>
          <div className="flex justify-between border-t border-gray-200 pt-3 dark:border-gray-600">
            <span className="font-semibold text-gray-900 dark:text-gray-100">Total</span>
            <span className="font-semibold text-gray-900 dark:text-gray-100">{formatNZD(item.amount)}</span>
          </div>
        </Block>
      </div>
    </Page>
  )
}
