import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Customer } from '@shared/types/customer'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem, MobileButton } from '@/components/ui'
import { SwipeAction } from '@/components/gestures/SwipeAction'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Inline SVG icon components for swipe actions                       */
/* ------------------------------------------------------------------ */

function PhoneIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" />
    </svg>
  )
}

function MailIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect width="20" height="16" x="2" y="4" rx="2" />
      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </svg>
  )
}

function SmsIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* Helper: build display name from customer                           */
/* ------------------------------------------------------------------ */

function displayName(c: Customer): string {
  const parts = [c.first_name, c.last_name].filter(Boolean)
  return parts.join(' ') || 'Unnamed'
}

/* ------------------------------------------------------------------ */
/* Helper: build subtitle from phone / email                          */
/* ------------------------------------------------------------------ */

function subtitle(c: Customer): string | undefined {
  const parts: string[] = []
  if (c.phone) parts.push(c.phone)
  if (c.email) parts.push(c.email)
  return parts.length > 0 ? parts.join(' · ') : undefined
}

/* ------------------------------------------------------------------ */
/* Swipe action handlers                                              */
/* ------------------------------------------------------------------ */

export function handleCall(phone: string | null) {
  if (!phone) return
  window.open(`tel:${phone}`, '_system')
}

export function handleEmail(email: string | null) {
  if (!email) return
  window.open(`mailto:${email}`, '_system')
}

export function handleSms(phone: string | null) {
  if (!phone) return
  window.open(`sms:${phone}`, '_system')
}

/**
 * Customer list screen — searchable paginated list with swipe actions
 * for Call, Email, and SMS. Pull-to-refresh support.
 *
 * Requirements: 7.1, 7.2, 7.3, 7.6, 7.7, 7.8, 7.9
 */
export default function CustomerListScreen() {
  const navigate = useNavigate()

  const {
    items,
    isLoading,
    isRefreshing,
    hasMore,
    search,
    setSearch,
    refresh,
    loadMore,
  } = useApiList<Customer>({
    endpoint: '/api/v1/customers',
    dataKey: 'customers',
  })

  const handleTap = useCallback(
    (customer: Customer) => {
      navigate(`/customers/${customer.id}`)
    },
    [navigate],
  )

  const renderItem = useCallback(
    (customer: Customer) => {
      const rightActions = [
        ...(customer.phone
          ? [
              {
                label: 'Call',
                icon: PhoneIcon,
                color: 'bg-green-500',
                onAction: () => handleCall(customer.phone),
              },
              {
                label: 'SMS',
                icon: SmsIcon,
                color: 'bg-blue-500',
                onAction: () => handleSms(customer.phone),
              },
            ]
          : []),
        ...(customer.email
          ? [
              {
                label: 'Email',
                icon: MailIcon,
                color: 'bg-purple-500',
                onAction: () => handleEmail(customer.email),
              },
            ]
          : []),
      ]

      return (
        <SwipeAction rightActions={rightActions}>
          <MobileListItem
            title={displayName(customer)}
            subtitle={subtitle(customer)}
            trailing={
              customer.company ? (
                <span className="text-xs text-gray-400 dark:text-gray-500">
                  {customer.company}
                </span>
              ) : undefined
            }
            onTap={() => handleTap(customer)}
          />
        </SwipeAction>
      )
    },
    [handleTap],
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col">
        {/* Header with title and New Customer button */}
        <div className="flex items-center justify-between px-4 pb-1 pt-4">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Customers
          </h1>
          <MobileButton
            variant="primary"
            size="sm"
            onClick={() => navigate('/customers/new')}
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
            New
          </MobileButton>
        </div>

        {/* Paginated list with search */}
        <MobileList<Customer>
          items={items}
          renderItem={renderItem}
          onRefresh={refresh}
          onLoadMore={loadMore}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          emptyMessage="No customers found"
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search customers…"
          keyExtractor={(c) => c.id}
        />
      </div>
    </PullRefresh>
  )
}
