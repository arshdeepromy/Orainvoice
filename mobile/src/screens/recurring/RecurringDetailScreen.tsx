import { useParams } from 'react-router-dom'
import {
  Page,
  List,
  ListItem,
  Block,
  BlockTitle,
  Preloader,
} from 'konsta/react'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import { useApiDetail } from '@/hooks/useApiDetail'
import StatusBadge from '@/components/konsta/StatusBadge'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface RecurringDetail {
  id: string
  customer_name: string | null
  amount: number
  frequency: string
  next_run_date: string | null
  status: string
  start_date: string | null
  end_date: string | null
  line_items: RecurringLineItem[]
  history: GenerationRecord[]
}

interface RecurringLineItem {
  id: string
  description: string
  quantity: number
  unit_price: number
  amount: number
}

interface GenerationRecord {
  id: string
  invoice_number: string | null
  generated_at: string
  status: string
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'N/A'
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
  } catch {
    return dateStr ?? ''
  }
}

/**
 * Recurring invoice detail — template configuration and generation history.
 * Requirements: 39.2
 */
export default function RecurringDetailScreen() {
  const { id } = useParams<{ id: string }>()

  const { data, isLoading, error } = useApiDetail<RecurringDetail>({
    endpoint: `/api/v2/recurring/${id}`,
  })

  if (isLoading) {
    return (
      <Page data-testid="recurring-detail-page">
        <KonstaNavbar title="Recurring Invoice" showBack />
        <div className="flex flex-1 items-center justify-center p-8"><Preloader /></div>
      </Page>
    )
  }

  if (error || !data) {
    return (
      <Page data-testid="recurring-detail-page">
        <KonstaNavbar title="Recurring Invoice" showBack />
        <Block><p className="text-center text-red-600 dark:text-red-400">{error ?? 'Not found'}</p></Block>
      </Page>
    )
  }

  const lineItems: RecurringLineItem[] = data.line_items ?? []
  const history: GenerationRecord[] = data.history ?? []

  return (
    <Page data-testid="recurring-detail-page">
      <KonstaNavbar
        title="Recurring Invoice"
        subtitle={data.customer_name ?? 'Unknown Customer'}
        showBack
      />

      <div className="flex flex-col pb-24">
        {/* Status */}
        <Block className="flex justify-end">
          <StatusBadge status={data.status ?? 'active'} size="md" />
        </Block>

        {/* Configuration */}
        <BlockTitle>Configuration</BlockTitle>
        <List strongIos outlineIos dividersIos>
          <ListItem title="Frequency" after={<span className="capitalize">{data.frequency ?? 'monthly'}</span>} />
          <ListItem title="Amount" after={formatNZD(data.amount)} />
          <ListItem title="Next Run" after={formatDate(data.next_run_date)} />
          <ListItem title="Start" after={formatDate(data.start_date)} />
          {data.end_date && <ListItem title="End" after={formatDate(data.end_date)} />}
        </List>

        {/* Template Items */}
        <BlockTitle>Template Items ({lineItems.length})</BlockTitle>
        {lineItems.length === 0 ? (
          <Block><p className="text-sm text-gray-500 dark:text-gray-400">No line items</p></Block>
        ) : (
          <List strongIos outlineIos dividersIos>
            {lineItems.map((li) => (
              <ListItem
                key={li.id}
                title={li.description || 'Item'}
                subtitle={<span className="text-xs text-gray-500 dark:text-gray-400">{li.quantity ?? 0} × {formatNZD(li.unit_price)}</span>}
                after={<span className="font-medium">{formatNZD(li.amount)}</span>}
              />
            ))}
          </List>
        )}

        {/* Generation History */}
        <BlockTitle>Generation History ({history.length})</BlockTitle>
        {history.length === 0 ? (
          <Block><p className="text-sm text-gray-500 dark:text-gray-400">No invoices generated yet</p></Block>
        ) : (
          <List strongIos outlineIos dividersIos>
            {history.map((h) => (
              <ListItem
                key={h.id}
                title={h.invoice_number ?? 'Invoice'}
                subtitle={<span className="text-xs text-gray-500 dark:text-gray-400">{formatDate(h.generated_at)}</span>}
                after={<span className="text-xs capitalize text-gray-500 dark:text-gray-400">{h.status ?? 'generated'}</span>}
              />
            ))}
          </List>
        )}
      </div>
    </Page>
  )
}
