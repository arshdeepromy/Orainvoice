import type { ReactNode } from 'react'
import { useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useApiDetail } from '@/hooks/useApiDetail'
import { useApiList } from '@/hooks/useApiList'
import {
  MobileCard,
  MobileButton,
  MobileSpinner,
  MobileListItem,
  MobileBadge,
  MobileModal,
} from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types — matches CustomerProfileResponse from backend               */
/* ------------------------------------------------------------------ */

interface Address {
  street?: string | null
  city?: string | null
  state?: string | null
  postal_code?: string | null
  country?: string | null
}

interface ContactPerson {
  salutation?: string | null
  first_name: string
  last_name: string
  email?: string | null
  work_phone?: string | null
  mobile_phone?: string | null
  designation?: string | null
  is_primary?: boolean
}

interface CustomerProfile {
  id: string
  customer_type: string
  salutation?: string | null
  first_name: string
  last_name: string
  company_name?: string | null
  display_name?: string | null
  email?: string | null
  phone?: string | null
  work_phone?: string | null
  mobile_phone?: string | null
  currency: string
  language: string
  payment_terms: string
  billing_address?: Address | null
  shipping_address?: Address | null
  contact_persons?: ContactPerson[] | null
  notes?: string | null
  remarks?: string | null
  is_anonymised: boolean
  created_at: string
  updated_at: string
  vehicles?: unknown[]
  invoices?: unknown[]
  total_spend?: string
  outstanding_balance?: string
}

/* ------------------------------------------------------------------ */
/* Linked entity types (for tabs)                                     */
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

type ProfileTab = 'invoices' | 'quotes' | 'jobs'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function getDisplayName(c: CustomerProfile): string {
  if (c.display_name) return c.display_name
  const parts = [c.first_name, c.last_name].filter(Boolean)
  if (parts.length > 0) return parts.join(' ')
  return c.company_name ?? 'Unnamed'
}

function formatNZD(value: string | number | null | undefined): string {
  const num = typeof value === 'string' ? parseFloat(value) : (value ?? 0)
  return new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: 'NZD',
    minimumFractionDigits: 2,
  }).format(isNaN(num) ? 0 : num)
}

function formatPaymentTerms(terms: string | null | undefined): string {
  const map: Record<string, string> = {
    due_on_receipt: 'DUE ON RECEIPT',
    net_7: 'NET 7',
    net_15: 'NET 15',
    net_30: 'NET 30',
    net_45: 'NET 45',
    net_60: 'NET 60',
    net_90: 'NET 90',
  }
  return map[terms ?? ''] ?? 'DUE ON RECEIPT'
}

function formatAddress(addr: Address | null | undefined): string | null {
  if (!addr) return null
  const parts = [addr.street, addr.city, addr.state, addr.postal_code, addr.country].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : null
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

const AVATAR_COLORS = [
  'bg-blue-500', 'bg-green-500', 'bg-purple-500', 'bg-orange-500',
  'bg-pink-500', 'bg-teal-500', 'bg-indigo-500', 'bg-red-500',
]

function getAvatarColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length] ?? AVATAR_COLORS[0]
}

function getInitials(c: CustomerProfile): string {
  const first = (c.first_name ?? '').charAt(0).toUpperCase()
  const last = (c.last_name ?? '').charAt(0).toUpperCase()
  if (first && last) return `${first}${last}`
  if (first) return first
  if (c.company_name) return c.company_name.charAt(0).toUpperCase()
  return '?'
}

/* ------------------------------------------------------------------ */
/* Inline SVG icons                                                   */
/* ------------------------------------------------------------------ */

function BackIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m15 18-6-6 6-6" />
    </svg>
  )
}

function PhoneIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" />
    </svg>
  )
}

function MailIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect width="20" height="16" x="2" y="4" rx="2" />
      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </svg>
  )
}

function MessageIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  )
}

function MoreIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="1" />
      <circle cx="12" cy="5" r="1" />
      <circle cx="12" cy="19" r="1" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* CustomerProfileScreen                                              */
/* ------------------------------------------------------------------ */

/**
 * Customer profile screen — Zoho Invoice-style detail view with
 * quick actions, financial summary, addresses, contact persons,
 * and linked invoices/quotes/jobs tabs.
 */
export default function CustomerProfileScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<ProfileTab>('invoices')
  const [showMoreSheet, setShowMoreSheet] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  const {
    data: customer,
    isLoading,
    error,
    refetch,
  } = useApiDetail<CustomerProfile>({
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

  const handleDelete = useCallback(async () => {
    if (!id) return
    setIsDeleting(true)
    try {
      await apiClient.delete(`/api/v1/customers/${id}`)
      navigate('/customers', { replace: true })
    } catch {
      // Silently fail — user can retry
    } finally {
      setIsDeleting(false)
      setShowDeleteConfirm(false)
      setShowMoreSheet(false)
    }
  }, [id, navigate])

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

  const displayNameStr = getDisplayName(customer)
  const primaryPhone = customer.mobile_phone ?? customer.phone ?? null
  const outstandingBalance = customer.outstanding_balance ?? '0.00'
  const billingAddr = formatAddress(customer.billing_address as Address | null)
  const shippingAddr = formatAddress(customer.shipping_address as Address | null)
  const contactPersons = (customer.contact_persons ?? []) as ContactPerson[]
  const primaryContact = contactPersons.find((cp) => cp.is_primary) ?? contactPersons[0] ?? null

  const tabs: { key: ProfileTab; label: string; count: number }[] = [
    { key: 'invoices', label: 'Invoices', count: invoiceList.total },
    { key: 'quotes', label: 'Quotes', count: quoteList.total },
    { key: 'jobs', label: 'Jobs', count: jobList.total },
  ]

  return (
    <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
      <div className="flex min-h-screen flex-col bg-gray-50 dark:bg-gray-900">
        {/* Header bar */}
        <div className="sticky top-0 z-20 flex items-center justify-between bg-white px-2 py-2 dark:bg-gray-800">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full text-gray-600 active:bg-gray-100 dark:text-gray-300 dark:active:bg-gray-700"
            aria-label="Go back"
          >
            <BackIcon className="h-6 w-6" />
          </button>
          <h1 className="flex-1 truncate px-2 text-center text-lg font-semibold text-gray-900 dark:text-gray-100">
            {displayNameStr}
          </h1>
          <button
            type="button"
            onClick={() => navigate(`/customers/${id}/edit`)}
            className="flex min-h-[44px] items-center justify-center rounded-lg px-3 text-sm font-medium text-blue-600 active:bg-blue-50 dark:text-blue-400 dark:active:bg-gray-700"
          >
            Edit
          </button>
        </div>

        <div className="flex flex-col gap-4 p-4">
          {/* Name + avatar + email */}
          <div className="flex items-center gap-4">
            <div
              className={`flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-full text-lg font-bold text-white ${getAvatarColor(displayNameStr)}`}
              aria-hidden="true"
            >
              {getInitials(customer)}
            </div>
            <div className="min-w-0 flex-1">
              {customer.company_name && (
                <p className="text-lg font-bold text-gray-900 dark:text-gray-100">
                  {customer.company_name}
                </p>
              )}
              {!customer.company_name && (
                <p className="text-lg font-bold text-gray-900 dark:text-gray-100">
                  {displayNameStr}
                </p>
              )}
              {customer.email && (
                <p className="truncate text-sm text-gray-500 dark:text-gray-400">
                  {customer.email}
                </p>
              )}
            </div>
          </div>

          {/* Quick action buttons */}
          <div className="flex justify-around">
            <QuickActionButton
              icon={<PhoneIcon className="h-5 w-5" />}
              label="Call"
              disabled={!primaryPhone}
              onTap={() => primaryPhone && window.open(`tel:${primaryPhone}`, '_system')}
            />
            <QuickActionButton
              icon={<MailIcon className="h-5 w-5" />}
              label="Mail"
              disabled={!customer.email}
              onTap={() => customer.email && window.open(`mailto:${customer.email}`, '_system')}
            />
            <QuickActionButton
              icon={<MessageIcon className="h-5 w-5" />}
              label="Message"
              disabled={!primaryPhone}
              onTap={() => primaryPhone && window.open(`sms:${primaryPhone}`, '_system')}
            />
            <QuickActionButton
              icon={<MoreIcon className="h-5 w-5" />}
              label="More"
              onTap={() => setShowMoreSheet(true)}
            />
          </div>

          {/* Financial summary */}
          <MobileCard>
            <div className="flex">
              <div className="flex-1 text-center">
                <p className="text-xs font-medium uppercase text-gray-400 dark:text-gray-500">
                  Outstanding Receivables
                </p>
                <p className="mt-1 text-lg font-bold text-gray-900 dark:text-gray-100">
                  {formatNZD(outstandingBalance)}
                </p>
              </div>
              <div className="mx-4 w-px bg-gray-200 dark:bg-gray-700" />
              <div className="flex-1 text-center">
                <p className="text-xs font-medium uppercase text-gray-400 dark:text-gray-500">
                  Unused Credits
                </p>
                <p className="mt-1 text-lg font-bold text-gray-900 dark:text-gray-100">
                  {formatNZD(0)}
                </p>
              </div>
            </div>
          </MobileCard>

          {/* Payment terms */}
          <MobileCard padding="px-4 py-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-500 dark:text-gray-400">Payment Terms</span>
              <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                {formatPaymentTerms(customer.payment_terms)}
              </span>
            </div>
          </MobileCard>

          {/* Billing Address */}
          {billingAddr && (
            <MobileCard>
              <p className="mb-1 text-xs font-medium uppercase text-gray-400 dark:text-gray-500">
                Billing Address
              </p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{billingAddr}</p>
              {customer.phone && (
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  {customer.phone}
                </p>
              )}
            </MobileCard>
          )}

          {/* Shipping Address */}
          {shippingAddr && (
            <MobileCard>
              <p className="mb-1 text-xs font-medium uppercase text-gray-400 dark:text-gray-500">
                Shipping Address
              </p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{shippingAddr}</p>
            </MobileCard>
          )}

          {/* Primary Contact */}
          {primaryContact && (
            <MobileCard>
              <p className="mb-2 text-xs font-medium uppercase text-gray-400 dark:text-gray-500">
                Primary Contact
              </p>
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                {[primaryContact.salutation, primaryContact.first_name, primaryContact.last_name]
                  .filter(Boolean)
                  .join(' ')}
              </p>
              {primaryContact.email && (
                <div className="mt-1 flex items-center gap-2">
                  <MailIcon className="h-4 w-4 text-gray-400" />
                  <a
                    href={`mailto:${primaryContact.email}`}
                    className="text-sm text-blue-600 dark:text-blue-400"
                  >
                    {primaryContact.email}
                  </a>
                </div>
              )}
              {(primaryContact.mobile_phone ?? primaryContact.work_phone) && (
                <div className="mt-1 flex items-center gap-2">
                  <PhoneIcon className="h-4 w-4 text-gray-400" />
                  <a
                    href={`tel:${primaryContact.mobile_phone ?? primaryContact.work_phone}`}
                    className="text-sm text-blue-600 dark:text-blue-400"
                  >
                    {primaryContact.mobile_phone ?? primaryContact.work_phone}
                  </a>
                </div>
              )}
            </MobileCard>
          )}

          {/* Tabs — Invoices / Quotes / Jobs */}
          <div className="flex border-b border-gray-200 dark:border-gray-700" role="tablist">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`flex-1 min-h-[44px] py-3 text-center text-sm font-medium transition-colors ${
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

        {/* "More" bottom sheet */}
        <MobileModal
          isOpen={showMoreSheet}
          onClose={() => setShowMoreSheet(false)}
          title="Actions"
        >
          <div className="flex flex-col gap-1 pb-4">
            <BottomSheetItem
              label="New Transaction"
              onTap={() => {
                setShowMoreSheet(false)
                navigate(`/invoices/new?customer_id=${id}`)
              }}
            />
            <BottomSheetItem
              label="Customer Statement"
              onTap={() => {
                setShowMoreSheet(false)
                navigate(`/reports/customer-statement?customer_id=${id}`)
              }}
            />
            <BottomSheetItem
              label="Mark as Inactive"
              onTap={() => {
                setShowMoreSheet(false)
                setShowDeleteConfirm(true)
              }}
            />
            <BottomSheetItem
              label="Delete"
              danger
              onTap={() => {
                setShowMoreSheet(false)
                setShowDeleteConfirm(true)
              }}
            />
          </div>
        </MobileModal>

        {/* Delete confirmation modal */}
        <MobileModal
          isOpen={showDeleteConfirm}
          onClose={() => setShowDeleteConfirm(false)}
          title="Delete Customer"
        >
          <div className="flex flex-col gap-4 pb-4">
            <p className="text-sm text-gray-600 dark:text-gray-300">
              Are you sure you want to delete this customer? This action will anonymise
              their data and cannot be undone.
            </p>
            <div className="flex gap-3">
              <MobileButton
                variant="secondary"
                fullWidth
                onClick={() => setShowDeleteConfirm(false)}
              >
                Cancel
              </MobileButton>
              <MobileButton
                variant="danger"
                fullWidth
                isLoading={isDeleting}
                onClick={handleDelete}
              >
                Delete
              </MobileButton>
            </div>
          </div>
        </MobileModal>
      </div>
    </PullRefresh>
  )
}

/* ------------------------------------------------------------------ */
/* Sub-components                                                     */
/* ------------------------------------------------------------------ */

function QuickActionButton({
  icon,
  label,
  disabled,
  onTap,
}: {
  icon: ReactNode
  label: string
  disabled?: boolean
  onTap: () => void
}) {
  return (
    <button
      type="button"
      onClick={onTap}
      disabled={disabled}
      className={`flex min-h-[44px] min-w-[44px] flex-col items-center gap-1 ${
        disabled
          ? 'opacity-30'
          : 'text-blue-600 active:opacity-70 dark:text-blue-400'
      }`}
      aria-label={label}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 dark:bg-blue-900/30">
        {icon}
      </div>
      <span className="text-xs font-medium">{label}</span>
    </button>
  )
}

function BottomSheetItem({
  label,
  danger,
  onTap,
}: {
  label: string
  danger?: boolean
  onTap: () => void
}) {
  return (
    <button
      type="button"
      onClick={onTap}
      className={`min-h-[44px] w-full rounded-lg px-4 py-3 text-left text-base font-medium active:bg-gray-100 dark:active:bg-gray-700 ${
        danger
          ? 'text-red-600 dark:text-red-400'
          : 'text-gray-900 dark:text-gray-100'
      }`}
    >
      {label}
    </button>
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
          title={inv.invoice_number ?? 'Invoice'}
          subtitle={inv.due_date}
          trailing={
            <div className="flex flex-col items-end gap-1">
              <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                {formatNZD(inv.total ?? 0)}
              </span>
              <MobileBadge label={inv.status} variant={badgeVariant(inv.status)} />
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
                {formatNZD(q.total ?? 0)}
              </span>
              <MobileBadge label={q.status} variant={badgeVariant(q.status)} />
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
          trailing={<MobileBadge label={j.status} variant={badgeVariant(j.status)} />}
          onTap={() => onTap(j)}
        />
      ))}
    </div>
  )
}
