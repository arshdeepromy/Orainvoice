import { useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Searchbar,
  List,
  ListItem,
  Block,
  Preloader,
  Badge,
} from 'konsta/react'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { SwipeAction } from '@/components/gestures/SwipeAction'
import KonstaFAB from '@/components/konsta/KonstaFAB'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Constants                                                          */
/* ------------------------------------------------------------------ */

const PAGE_SIZE = 25

/* ------------------------------------------------------------------ */
/* Types — matches CustomerSearchResult from backend                  */
/* ------------------------------------------------------------------ */

interface CustomerListItem {
  id: string
  first_name: string
  last_name: string | null
  company_name?: string | null
  company?: string | null
  display_name?: string | null
  email?: string | null
  phone?: string | null
  mobile_phone?: string | null
  work_phone?: string | null
  receivables: number
  unused_credits: number
}

/* ------------------------------------------------------------------ */
/* Inline SVG icons for swipe actions                                 */
/* ------------------------------------------------------------------ */

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

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function getDisplayName(c: CustomerListItem): string {
  if (c.display_name) return c.display_name
  const parts = [c.first_name, c.last_name].filter(Boolean)
  if (parts.length > 0) return parts.join(' ')
  return c.company_name ?? c.company ?? 'Unnamed'
}

function getSubtitle(c: CustomerListItem): string {
  const company = c.company_name ?? c.company ?? null
  const phone = c.phone ?? c.mobile_phone ?? null
  if (company) return company
  if (phone) return phone
  return ''
}

function formatNZD(value: number | null | undefined): string {
  return new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: 'NZD',
    minimumFractionDigits: 2,
  }).format(value ?? 0)
}

/* ------------------------------------------------------------------ */
/* Swipe action handlers (exported for testing)                       */
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
 * Customer list screen — Konsta UI redesign with:
 * - Sticky Konsta Searchbar
 * - Each customer as Konsta ListItem with display_name or first+last as title,
 *   company_name or phone as subtitle, receivables badge (red if > 0) on right
 * - Infinite scroll pagination (25 per page) using offset and limit
 * - FAB for "+ New Customer"
 * - Pull-to-refresh
 * - Tap row navigates to /customers/:id
 * - Safe API consumption: res.data?.items ?? [], res.data?.total ?? 0
 *
 * Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 7.1
 */
export default function CustomerListScreen() {
  const navigate = useNavigate()

  // ── State ──────────────────────────────────────────────────────────
  const [items, setItems] = useState<CustomerListItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)

  const abortRef = useRef<AbortController | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const hasMore = items.length < total

  // ── Fetch data ─────────────────────────────────────────────────────
  const fetchCustomers = useCallback(
    async (
      currentOffset: number,
      isRefresh: boolean,
      signal: AbortSignal,
    ) => {
      if (isRefresh) {
        setIsRefreshing(true)
      } else if (currentOffset === 0) {
        setIsLoading(true)
      } else {
        setIsLoadingMore(true)
      }
      setError(null)

      try {
        const params: Record<string, string | number> = {
          offset: currentOffset,
          limit: PAGE_SIZE,
        }
        if (search.trim()) {
          params.search = search.trim()
        }

        const res = await apiClient.get<{ items?: CustomerListItem[]; customers?: CustomerListItem[]; total?: number }>(
          '/api/v1/customers',
          { params, signal },
        )

        // Safe API consumption — try items first, then customers key
        const newItems = res.data?.items ?? res.data?.customers ?? []
        const newTotal = res.data?.total ?? 0

        if (currentOffset === 0 || isRefresh) {
          setItems(newItems)
        } else {
          setItems((prev) => [...prev, ...newItems])
        }
        setTotal(newTotal)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load customers')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
        setIsLoadingMore(false)
      }
    },
    [search],
  )

  // Fetch on mount and when search changes (reset to offset 0)
  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setOffset(0)
    fetchCustomers(0, false, controller.signal)

    return () => controller.abort()
  }, [fetchCustomers])

  // ── Pull-to-refresh ────────────────────────────────────────────────
  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setOffset(0)
    await fetchCustomers(0, true, controller.signal)
  }, [fetchCustomers])

  // ── Infinite scroll via IntersectionObserver ───────────────────────
  const loadMore = useCallback(() => {
    if (isLoading || isRefreshing || isLoadingMore || !hasMore) return

    const nextOffset = offset + PAGE_SIZE
    setOffset(nextOffset)

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    fetchCustomers(nextOffset, false, controller.signal)
  }, [isLoading, isRefreshing, isLoadingMore, hasMore, offset, fetchCustomers])

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          loadMore()
        }
      },
      { rootMargin: '200px' },
    )

    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [loadMore])

  // ── Memoised search handler ────────────────────────────────────────
  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setSearch(e.target.value)
    },
    [],
  )

  const handleSearchClear = useCallback(() => {
    setSearch('')
  }, [])

  // ── Build swipe actions per customer ───────────────────────────────
  const buildRightActions = useCallback(
    (customer: CustomerListItem) => {
      const phone = customer.mobile_phone ?? customer.phone ?? null
      const actions = []

      if (phone) {
        actions.push({
          label: 'Call',
          icon: PhoneIcon,
          color: 'bg-green-500',
          onAction: () => handleCall(phone),
        })
        actions.push({
          label: 'SMS',
          icon: SmsIcon,
          color: 'bg-blue-500',
          onAction: () => handleSms(phone),
        })
      }

      if (customer.email) {
        actions.push({
          label: 'Email',
          icon: MailIcon,
          color: 'bg-purple-500',
          onAction: () => handleEmail(customer.email ?? null),
        })
      }

      return actions
    },
    [],
  )

  // ── Loading state ──────────────────────────────────────────────────
  if (isLoading && items.length === 0) {
    return (
      <Page data-testid="customer-list-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="customer-list-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {/* ── Searchbar ─────────────────────────────────────────── */}
          <div className="sticky top-0 z-10 px-4 pt-3">
            <Searchbar
              value={search}
              onChange={handleSearchChange}
              onClear={handleSearchClear}
              placeholder="Search customers…"
              data-testid="customer-searchbar"
            />
          </div>

          {/* ── Error Banner ──────────────────────────────────────── */}
          {error && (
            <Block>
              <div
                role="alert"
                className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
              >
                {error}
                <button
                  type="button"
                  onClick={() => handleRefresh()}
                  className="ml-2 font-medium underline"
                >
                  Retry
                </button>
              </div>
            </Block>
          )}

          {/* ── Customer List ─────────────────────────────────────── */}
          {items.length === 0 && !isLoading ? (
            <Block className="text-center">
              <p className="text-sm text-gray-400 dark:text-gray-500">
                No customers found
              </p>
            </Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="customer-list">
              {items.map((customer) => {
                const name = getDisplayName(customer)
                const subtitle = getSubtitle(customer)
                const receivables = customer.receivables ?? 0
                const rightActions = buildRightActions(customer)

                return (
                  <SwipeAction
                    key={customer.id}
                    rightActions={rightActions}
                  >
                    <ListItem
                      link
                      onClick={() => navigate(`/customers/${customer.id}`)}
                      title={
                        <span className="font-bold text-gray-900 dark:text-gray-100">
                          {name}
                        </span>
                      }
                      subtitle={
                        subtitle ? (
                          <span className="text-xs text-gray-500 dark:text-gray-400">
                            {subtitle}
                          </span>
                        ) : undefined
                      }
                      after={
                        receivables > 0 ? (
                          <Badge
                            colors={{
                              bg: 'bg-red-500',
                            }}
                            data-testid={`receivables-badge-${customer.id}`}
                          >
                            {formatNZD(receivables)}
                          </Badge>
                        ) : undefined
                      }
                      data-testid={`customer-item-${customer.id}`}
                    />
                  </SwipeAction>
                )
              })}
            </List>
          )}

          {/* ── Infinite scroll sentinel ──────────────────────────── */}
          {hasMore && (
            <div ref={sentinelRef} className="flex justify-center py-4">
              {isLoadingMore && <Preloader />}
            </div>
          )}
        </div>
      </PullRefresh>

      {/* ── FAB: + New Customer ─────────────────────────────────────── */}
      <KonstaFAB
        label="+ New Customer"
        onClick={() => navigate('/customers/new')}
      />
    </Page>
  )
}
