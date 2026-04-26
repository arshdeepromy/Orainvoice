import { useState, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApiList } from '@/hooks/useApiList'
import { MobileSpinner } from '@/components/ui'
import { SwipeAction } from '@/components/gestures/SwipeAction'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Types — matches CustomerSearchResult from backend                  */
/* ------------------------------------------------------------------ */

interface CustomerListItem {
  id: string
  first_name: string
  last_name: string
  company_name?: string | null
  display_name?: string | null
  email?: string | null
  phone?: string | null
  mobile_phone?: string | null
  work_phone?: string | null
  receivables: number
  unused_credits: number
}

/* ------------------------------------------------------------------ */
/* Filter tab type                                                    */
/* ------------------------------------------------------------------ */

type FilterTab = 'active' | 'unpaid' | 'all'

/* ------------------------------------------------------------------ */
/* Avatar colour hash                                                 */
/* ------------------------------------------------------------------ */

const AVATAR_COLORS = [
  'bg-blue-500',
  'bg-green-500',
  'bg-purple-500',
  'bg-orange-500',
  'bg-pink-500',
  'bg-teal-500',
  'bg-indigo-500',
  'bg-red-500',
]

function getAvatarColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length] ?? AVATAR_COLORS[0]
}

function getInitials(c: CustomerListItem): string {
  const first = (c.first_name ?? '').charAt(0).toUpperCase()
  const last = (c.last_name ?? '').charAt(0).toUpperCase()
  if (first && last) return `${first}${last}`
  if (first) return first
  if (c.company_name) return c.company_name.charAt(0).toUpperCase()
  return '?'
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function getDisplayName(c: CustomerListItem): string {
  if (c.display_name) return c.display_name
  const parts = [c.first_name, c.last_name].filter(Boolean)
  if (parts.length > 0) return parts.join(' ')
  return c.company_name ?? 'Unnamed'
}

function formatNZD(value: number | null | undefined): string {
  return new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: 'NZD',
    minimumFractionDigits: 2,
  }).format(value ?? 0)
}

/* ------------------------------------------------------------------ */
/* Inline SVG icons                                                   */
/* ------------------------------------------------------------------ */

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  )
}

function FilterIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h18" />
      <path d="M7 12h10" />
      <path d="M10 18h4" />
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

function SmsIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  )
}

function CloseIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </svg>
  )
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

/* ------------------------------------------------------------------ */
/* CustomerListScreen                                                 */
/* ------------------------------------------------------------------ */

/**
 * Customer list screen — Zoho Invoice-style layout with avatar cards,
 * filter tabs, search, swipe actions, pull-to-refresh, and FAB.
 */
export default function CustomerListScreen() {
  const navigate = useNavigate()
  const [activeFilter, setActiveFilter] = useState<FilterTab>('active')
  const [showSearch, setShowSearch] = useState(false)

  const {
    items,
    isLoading,
    isRefreshing,
    hasMore,
    search,
    setSearch,
    refresh,
    loadMore,
  } = useApiList<CustomerListItem>({
    endpoint: '/api/v1/customers',
    dataKey: 'customers',
  })

  // Client-side filter for tabs
  const filteredItems = useMemo(() => {
    if (activeFilter === 'unpaid') {
      return items.filter((c) => (c.receivables ?? 0) > 0)
    }
    // 'active' and 'all' show all items (we don't have an inactive status)
    return items
  }, [items, activeFilter])

  const handleTap = useCallback(
    (customer: CustomerListItem) => {
      navigate(`/customers/${customer.id}`)
    },
    [navigate],
  )

  const filterTabs: { key: FilterTab; label: string }[] = [
    { key: 'active', label: 'Active' },
    { key: 'unpaid', label: 'Unpaid' },
    { key: 'all', label: 'All' },
  ]

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex min-h-screen flex-col bg-gray-50 dark:bg-gray-900">
        {/* Header */}
        <div className="sticky top-0 z-20 bg-white px-4 pb-2 pt-4 dark:bg-gray-800">
          <div className="flex items-center justify-between">
            <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">
              Customers
            </h1>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setShowSearch((v) => !v)}
                className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full text-gray-600 active:bg-gray-100 dark:text-gray-300 dark:active:bg-gray-700"
                aria-label={showSearch ? 'Close search' : 'Search customers'}
              >
                {showSearch ? (
                  <CloseIcon className="h-5 w-5" />
                ) : (
                  <SearchIcon className="h-5 w-5" />
                )}
              </button>
              <button
                type="button"
                className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full text-gray-600 active:bg-gray-100 dark:text-gray-300 dark:active:bg-gray-700"
                aria-label="Filter and sort"
              >
                <FilterIcon className="h-5 w-5" />
              </button>
            </div>
          </div>

          {/* Search bar */}
          {showSearch && (
            <div className="mt-2">
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search customers…"
                className="w-full min-h-[44px] rounded-lg border border-gray-300 bg-gray-50 px-3 py-2 text-base text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-500"
                autoFocus
              />
            </div>
          )}

          {/* Filter tabs */}
          <div className="mt-3 flex gap-2" role="tablist">
            {filterTabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={activeFilter === tab.key}
                onClick={() => setActiveFilter(tab.key)}
                className={`min-h-[36px] rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
                  activeFilter === tab.key
                    ? 'bg-blue-600 text-white dark:bg-blue-500'
                    : 'bg-gray-100 text-gray-600 active:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:active:bg-gray-600'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Customer list */}
        <div className="flex-1 px-4 pb-24 pt-2">
          {isLoading && filteredItems.length === 0 ? (
            <div className="flex items-center justify-center py-12">
              <MobileSpinner size="lg" />
            </div>
          ) : filteredItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <p className="text-gray-400 dark:text-gray-500">No customers found</p>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {filteredItems.map((customer) => {
                const name = getDisplayName(customer)
                const phone = customer.mobile_phone ?? customer.phone ?? null
                const rightActions = [
                  ...(phone
                    ? [
                        {
                          label: 'Call',
                          icon: PhoneIcon,
                          color: 'bg-green-500',
                          onAction: () => handleCall(phone),
                        },
                        {
                          label: 'SMS',
                          icon: SmsIcon,
                          color: 'bg-blue-500',
                          onAction: () => handleSms(phone),
                        },
                      ]
                    : []),
                  ...(customer.email
                    ? [
                        {
                          label: 'Email',
                          icon: MailIcon,
                          color: 'bg-purple-500',
                          onAction: () => handleEmail(customer.email ?? null),
                        },
                      ]
                    : []),
                ]

                return (
                  <SwipeAction key={customer.id} rightActions={rightActions}>
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => handleTap(customer)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          handleTap(customer)
                        }
                      }}
                      className="flex items-center gap-3 rounded-xl bg-white p-3 shadow-sm ring-1 ring-gray-100 active:bg-gray-50 dark:bg-gray-800 dark:ring-gray-700 dark:active:bg-gray-700"
                    >
                      {/* Avatar */}
                      <div
                        className={`flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white ${getAvatarColor(name)}`}
                        aria-hidden="true"
                      >
                        {getInitials(customer)}
                      </div>

                      {/* Info */}
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-base font-medium text-gray-900 dark:text-gray-100">
                          {name}
                        </p>
                        {customer.email && (
                          <p className="truncate text-sm text-gray-500 dark:text-gray-400">
                            {customer.email}
                          </p>
                        )}
                        <div className="mt-1 flex gap-4">
                          <div>
                            <span className="text-xs text-gray-400 dark:text-gray-500">Receivables </span>
                            <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                              {formatNZD(customer.receivables)}
                            </span>
                          </div>
                          <div>
                            <span className="text-xs text-gray-400 dark:text-gray-500">Credits </span>
                            <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                              {formatNZD(customer.unused_credits)}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Chevron */}
                      <svg
                        className="h-5 w-5 flex-shrink-0 text-gray-400 dark:text-gray-500"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <path d="m9 18 6-6-6-6" />
                      </svg>
                    </div>
                  </SwipeAction>
                )
              })}

              {/* Load more */}
              {hasMore && (
                <button
                  type="button"
                  onClick={loadMore}
                  disabled={isLoading}
                  className="mx-auto mt-2 flex min-h-[44px] items-center justify-center rounded-lg px-6 py-2 text-sm font-medium text-blue-600 active:bg-blue-50 dark:text-blue-400 dark:active:bg-gray-800"
                >
                  {isLoading ? <MobileSpinner size="sm" /> : 'Load more'}
                </button>
              )}
            </div>
          )}
        </div>

        {/* FAB — New Customer */}
        <button
          type="button"
          onClick={() => navigate('/customers/new')}
          className="fixed bottom-20 right-4 z-30 flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 text-white shadow-lg active:bg-blue-700 dark:bg-blue-500 dark:active:bg-blue-600"
          aria-label="New customer"
        >
          <svg
            className="h-7 w-7"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>
    </PullRefresh>
  )
}
