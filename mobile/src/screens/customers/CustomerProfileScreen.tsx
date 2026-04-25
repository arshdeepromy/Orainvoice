import { useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import type { Customer } from '@shared/types/customer'
import { useApiDetail } from '@/hooks/useApiDetail'
import { useApiList } from '@/hooks/useApiList'
import { MobileCard, MobileButton, MobileSpinner, MobileListItem, MobileBadge } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Linked entity types (minimal shapes for display)                   */
/* ------------------------------------------------------------------ */

interface LinkedInvoice {
  id: string
  invoice_number: string
  status: string
  total: number
  due_date: string
}

interface LinkedQuote {
  id: string
  quote_number?: string
  status: string
  total: number
  created_at: string
}

interface LinkedJob {
  id: string
  title?: string
  description?: string
  status: string
  created_at: string
}

/* ------------------------------------------------------------------ */
/* Tab type                                                           */
/* ------------------------------------------------------------------ */

type ProfileTab = 'invoices' | 'quotes' | 'jobs'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function displayName(c: Customer): string {
  const parts = [c.first_name, c.last_name].filter(Boolean)
  return parts.join(' ') || 'Unnamed'
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: 'NZD',
    minimumFractionDigits: 2,
  }).format(value)
}

function badgeVariant(status: string) {
  const map: Record<string, 'paid' | 'overdue' | 'draft' | 'sent' | 'cancelled' | 'pending' | 'active' | 'info'> = {
    paid: 'paid',
    overdue: 'overdue',
    draft: 'draft',
    sent: 'sent',
    cancelled: 'cancelled',
    pending: 'pending',
    active: 'active',
    accepted: 'paid',
    declined: 'cancelled',
    completed: 'paid',
    in_progress: 'info',
  }
  return map[status] ?? 'info'
}

/**
 * Customer profile screen — full contact details with linked invoices,
 * quotes, and job history tabs.
 *
 * Requirements: 7.4
 */
export default function CustomerProfileScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<ProfileTab>('invoices')

  const {
    data: customer,
    isLoading,
    error,
    refetch,
  } = useApiDetail<Customer>({
    endpoint: `/api/v1/customers/${id}`,
    enabled: !!id,
  })

  // Linked invoices
  const invoiceList = useApiList<LinkedInvoice>({
    endpoint: '/api/v1/invoices',
    dataKey: 'invoices',
    initialFilters: { customer_id: id ?? '' },
  })

  // Linked quotes
  const quoteList = useApiList<LinkedQuote>({
    endpoint: '/api/v1/quotes',
    dataKey: 'quotes',
    initialFilters: { customer_id: id ?? '' },
  })

  // Linked jobs
  const jobList = useApiList<LinkedJob>({
    endpoint: '/api/v2/jobs',
    dataKey: 'jobs',
    initialFilters: { customer_id: id ?? '' },
  })

  const isRefreshing =
    invoiceList.isRefreshing || quoteList.isRefreshing || jobList.isRefreshing

  const handleRefresh = useCallback(async () => {
    await Promise.all([
      refetch(),
      invoiceList.refresh(),
      quoteList.refresh(),
      jobList.refresh(),
    ])
  }, [refetch, invoiceList, quoteList, jobList])

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <MobileSpinner size="lg" />
      </div>
    )
  }

  if (error || !customer) {
    return (
      <div className="flex flex-col items-center gap-4 p-8">
        <p className="text-gray-500 dark:text-gray-400">
          {error ?? 'Customer not found'}
        </p>
        <MobileButton variant="secondary" onClick={() => navigate(-1)}>
          Go Back
        </MobileButton>
      </div>
    )
  }

  const tabs: { key: ProfileTab; label: string; count: number }[] = [
    { key: 'invoices', label: 'Invoices', count: invoiceList.total },
    { key: 'quotes', label: 'Quotes', count: quoteList.total },
    { key: 'jobs', label: 'Jobs', count: jobList.total },
  ]

  return (
    <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-4 p-4">
        {/* Customer name and company */}
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            {displayName(customer)}
          </h1>
          {customer.company && (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {customer.company}
            </p>
          )}
        </div>

        {/* Contact details card */}
        <MobileCard>
          <div className="flex flex-col gap-3">
            {customer.phone && (
              <ContactRow
                label="Phone"
                value={customer.phone}
                href={`tel:${customer.phone}`}
              />
            )}
            {customer.email && (
              <ContactRow
                label="Email"
                value={customer.email}
                href={`mailto:${customer.email}`}
              />
            )}
            {customer.address && (
              <ContactRow label="Address" value={customer.address} />
            )}
            {!customer.phone && !customer.email && !customer.address && (
              <p className="text-sm text-gray-400 dark:text-gray-500">
                No contact details
              </p>
            )}
          </div>
        </MobileCard>

        {/* Quick action buttons */}
        <div className="flex gap-2">
          {customer.phone && (
            <MobileButton
              variant="secondary"
              size="sm"
              onClick={() => window.open(`tel:${customer.phone}`, '_system')}
            >
              Call
            </MobileButton>
          )}
          {customer.email && (
            <MobileButton
              variant="secondary"
              size="sm"
              onClick={() => window.open(`mailto:${customer.email}`, '_system')}
            >
              Email
            </MobileButton>
          )}
          {customer.phone && (
            <MobileButton
              variant="secondary"
              size="sm"
              onClick={() => window.open(`sms:${customer.phone}`, '_system')}
            >
              SMS
            </MobileButton>
          )}
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-200 dark:border-gray-700" role="tablist">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 py-3 text-center text-sm font-medium transition-colors ${
                activeTab === tab.key
                  ? 'border-b-2 border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400'
                  : 'text-gray-500 dark:text-gray-400'
              }`}
            >
              {tab.label} ({tab.count})
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div role="tabpanel">
          {activeTab === 'invoices' && (
            <LinkedInvoicesList
              items={invoiceList.items}
              isLoading={invoiceList.isLoading}
              onTap={(inv) => navigate(`/invoices/${inv.id}`)}
            />
          )}
          {activeTab === 'quotes' && (
            <LinkedQuotesList
              items={quoteList.items}
              isLoading={quoteList.isLoading}
              onTap={(q) => navigate(`/quotes/${q.id}`)}
            />
          )}
          {activeTab === 'jobs' && (
            <LinkedJobsList
              items={jobList.items}
              isLoading={jobList.isLoading}
              onTap={(j) => navigate(`/jobs/${j.id}`)}
            />
          )}
        </div>
      </div>
    </PullRefresh>
  )
}

/* ------------------------------------------------------------------ */
/* Sub-components                                                     */
/* ------------------------------------------------------------------ */

function ContactRow({
  label,
  value,
  href,
}: {
  label: string
  value: string
  href?: string
}) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-sm text-gray-500 dark:text-gray-400">{label}</span>
      {href ? (
        <a
          href={href}
          className="text-sm font-medium text-blue-600 dark:text-blue-400"
        >
          {value}
        </a>
      ) : (
        <span className="text-right text-sm font-medium text-gray-900 dark:text-gray-100">
          {value}
        </span>
      )}
    </div>
  )
}

function LinkedInvoicesList({
  items,
  isLoading,
  onTap,
}: {
  items: LinkedInvoice[]
  isLoading: boolean
  onTap: (inv: LinkedInvoice) => void
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <MobileSpinner size="sm" />
      </div>
    )
  }
  if (items.length === 0) {
    return (
      <p className="py-4 text-center text-sm text-gray-400 dark:text-gray-500">
        No invoices
      </p>
    )
  }
  return (
    <div className="flex flex-col">
      {items.map((inv) => (
        <MobileListItem
          key={inv.id}
          title={inv.invoice_number ?? `Invoice`}
          subtitle={inv.due_date}
          trailing={
            <div className="flex flex-col items-end gap-1">
              <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                {formatCurrency(inv.total ?? 0)}
              </span>
              <MobileBadge
                label={inv.status}
                variant={badgeVariant(inv.status)}
              />
            </div>
          }
          onTap={() => onTap(inv)}
        />
      ))}
    </div>
  )
}

function LinkedQuotesList({
  items,
  isLoading,
  onTap,
}: {
  items: LinkedQuote[]
  isLoading: boolean
  onTap: (q: LinkedQuote) => void
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <MobileSpinner size="sm" />
      </div>
    )
  }
  if (items.length === 0) {
    return (
      <p className="py-4 text-center text-sm text-gray-400 dark:text-gray-500">
        No quotes
      </p>
    )
  }
  return (
    <div className="flex flex-col">
      {items.map((q) => (
        <MobileListItem
          key={q.id}
          title={q.quote_number ?? 'Quote'}
          subtitle={q.created_at}
          trailing={
            <div className="flex flex-col items-end gap-1">
              <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                {formatCurrency(q.total ?? 0)}
              </span>
              <MobileBadge
                label={q.status}
                variant={badgeVariant(q.status)}
              />
            </div>
          }
          onTap={() => onTap(q)}
        />
      ))}
    </div>
  )
}

function LinkedJobsList({
  items,
  isLoading,
  onTap,
}: {
  items: LinkedJob[]
  isLoading: boolean
  onTap: (j: LinkedJob) => void
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <MobileSpinner size="sm" />
      </div>
    )
  }
  if (items.length === 0) {
    return (
      <p className="py-4 text-center text-sm text-gray-400 dark:text-gray-500">
        No jobs
      </p>
    )
  }
  return (
    <div className="flex flex-col">
      {items.map((j) => (
        <MobileListItem
          key={j.id}
          title={j.title ?? j.description ?? 'Job'}
          trailing={
            <MobileBadge
              label={j.status}
              variant={badgeVariant(j.status)}
            />
          }
          onTap={() => onTap(j)}
        />
      ))}
    </div>
  )
}
