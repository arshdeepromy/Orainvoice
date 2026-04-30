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
import HapticButton from '@/components/konsta/HapticButton'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface PODetail {
  id: string
  po_number: string
  supplier_name: string | null
  supplier_email: string | null
  supplier_phone: string | null
  amount: number
  status: string
  delivery_status: string | null
  expected_delivery: string | null
  created_at: string
  notes: string | null
  line_items: POLineItem[]
}

interface POLineItem {
  id: string
  description: string
  quantity: number
  unit_price: number
  amount: number
  received_quantity: number | null
}

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
 * Purchase order detail — line items, supplier details, delivery status.
 * Requirements: 40.2, 40.3
 */
export default function PODetailScreen() {
  const { id } = useParams<{ id: string }>()

  const { data, isLoading, error } = useApiDetail<PODetail>({
    endpoint: `/api/v2/purchase-orders/${id}`,
  })

  if (isLoading) {
    return (
      <Page data-testid="po-detail-page">
        <KonstaNavbar title="Purchase Order" showBack />
        <div className="flex flex-1 items-center justify-center p-8"><Preloader /></div>
      </Page>
    )
  }

  if (error || !data) {
    return (
      <Page data-testid="po-detail-page">
        <KonstaNavbar title="Purchase Order" showBack />
        <Block><p className="text-center text-red-600 dark:text-red-400">{error ?? 'Purchase order not found'}</p></Block>
      </Page>
    )
  }

  const lineItems: POLineItem[] = data.line_items ?? []

  return (
    <Page data-testid="po-detail-page">
      <KonstaNavbar
        title={data.po_number ?? 'Purchase Order'}
        subtitle={data.supplier_name ?? 'Unknown Supplier'}
        showBack
      />

      <div className="flex flex-col pb-24">
        <Block className="flex justify-end">
          <StatusBadge status={data.status ?? 'draft'} size="md" />
        </Block>

        {/* Supplier */}
        <BlockTitle>Supplier</BlockTitle>
        <List strongIos outlineIos dividersIos>
          <ListItem title="Name" after={data.supplier_name ?? 'N/A'} />
          {data.supplier_email && <ListItem title="Email" after={data.supplier_email} />}
          {data.supplier_phone && <ListItem title="Phone" after={data.supplier_phone} />}
        </List>

        {/* Delivery */}
        <BlockTitle>Delivery</BlockTitle>
        <List strongIos outlineIos dividersIos>
          <ListItem title="Created" after={formatDate(data.created_at)} />
          <ListItem title="Expected Delivery" after={formatDate(data.expected_delivery)} />
          {data.delivery_status && <ListItem title="Delivery Status" after={<span className="capitalize">{data.delivery_status}</span>} />}
        </List>

        {/* Line Items */}
        <BlockTitle>Line Items ({lineItems.length})</BlockTitle>
        {lineItems.length === 0 ? (
          <Block><p className="text-sm text-gray-500 dark:text-gray-400">No line items</p></Block>
        ) : (
          <List strongIos outlineIos dividersIos data-testid="po-line-items">
            {lineItems.map((li) => (
              <ListItem
                key={li.id}
                title={li.description || 'Item'}
                subtitle={
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {li.quantity ?? 0} × {formatNZD(li.unit_price)}
                    {li.received_quantity != null && ` · Received: ${li.received_quantity}`}
                  </span>
                }
                after={<span className="font-medium">{formatNZD(li.amount)}</span>}
              />
            ))}
          </List>
        )}

        {/* Total */}
        <Block>
          <div className="flex justify-between border-t border-gray-200 pt-3 dark:border-gray-600">
            <span className="font-semibold text-gray-900 dark:text-gray-100">Total</span>
            <span className="font-semibold text-gray-900 dark:text-gray-100">{formatNZD(data.amount)}</span>
          </div>
        </Block>

        {/* Receive Stock action */}
        {data.status !== 'received' && (
          <Block>
            <HapticButton large className="k-color-primary w-full" hapticStyle="medium" data-testid="receive-stock-btn">
              Receive Stock
            </HapticButton>
          </Block>
        )}

        {/* Notes */}
        {data.notes && (
          <>
            <BlockTitle>Notes</BlockTitle>
            <Block><p className="text-sm text-gray-700 dark:text-gray-300">{data.notes}</p></Block>
          </>
        )}
      </div>
    </Page>
  )
}
