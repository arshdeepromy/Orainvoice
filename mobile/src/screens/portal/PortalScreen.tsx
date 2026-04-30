import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Block,
  BlockTitle,
  Card,
  List,
  ListItem,
  Button,
  Preloader,
  Chip,
} from 'konsta/react'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import StatusBadge from '@/components/konsta/StatusBadge'
import HapticButton from '@/components/konsta/HapticButton'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface PortalInvoice {
  id: string
  invoice_number: string | null
  status: string
  total: number | null
  balance_due: number | null
  due_date: string | null
  issued_date: string | null
}

interface PortalQuote {
  id: string
  quote_number: string | null
  status: string
  total: number | null
  expiry_date: string | null
}

interface PortalBooking {
  id: string
  date: string | null
  time: string | null
  service_type: string | null
  status: string
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
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

type PortalTab = 'invoices' | 'quotes' | 'bookings'

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

/**
 * Customer Portal screen — self-service portal for customers.
 * View invoices, pay online, accept quotes, book appointments.
 * Restyled with Konsta UI components.
 *
 * Requirements: 48.1, 48.2
 */
export default function PortalScreen() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<PortalTab>('invoices')
  const [invoices, setInvoices] = useState<PortalInvoice[]>([])
  const [quotes, setQuotes] = useState<PortalQuote[]>([])
  const [bookings, setBookings] = useState<PortalBooking[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async (signal: AbortSignal, refresh = false) => {
    if (refresh) setIsRefreshing(true)
    else setIsLoading(true)
    setError(null)

    try {
      const [invRes, quoteRes, bookingRes] = await Promise.all([
        apiClient.get<{ items?: PortalInvoice[] }>('/api/v1/portal/invoices', { signal }),
        apiClient.get<{ items?: PortalQuote[] }>('/api/v1/portal/quotes', { signal }),
        apiClient.get<{ items?: PortalBooking[] }>('/api/v1/portal/bookings', { signal }),
      ])
      setInvoices(invRes.data?.items ?? [])
      setQuotes(quoteRes.data?.items ?? [])
      setBookings(bookingRes.data?.items ?? [])
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') {
        setError('Failed to load portal data')
      }
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    abortRef.current = controller
    fetchData(controller.signal)
    return () => controller.abort()
  }, [fetchData])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchData(controller.signal, true)
  }, [fetchData])

  const handlePayInvoice = useCallback(
    (invoiceId: string) => {
      navigate(`/pay/${invoiceId}`)
    },
    [navigate],
  )

  const handleAcceptQuote = useCallback(async (quoteId: string) => {
    try {
      await apiClient.post(`/api/v1/portal/quotes/${quoteId}/accept`)
      // Refresh data after accepting
      const controller = new AbortController()
      abortRef.current = controller
      await fetchData(controller.signal, true)
    } catch {
      // Silently fail
    }
  }, [fetchData])

  const handleBookAppointment = useCallback(() => {
    navigate('/portal/book')
  }, [navigate])

  if (isLoading && invoices.length === 0) {
    return (
      <Page data-testid="portal-page">
        <KonstaNavbar title="Customer Portal" />
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="portal-page">
      <KonstaNavbar title="Customer Portal" />

      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {/* Error banner */}
          {error && (
            <div
              role="alert"
              className="mx-4 mt-2 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
            >
              {error}
              <button type="button" onClick={handleRefresh} className="ml-2 font-medium underline">
                Retry
              </button>
            </div>
          )}

          {/* Tab selector */}
          <div className="flex gap-2 overflow-x-auto px-4 pt-4 pb-2">
            {(['invoices', 'quotes', 'bookings'] as const).map((tab) => (
              <Chip
                key={tab}
                className={`capitalize ${activeTab === tab ? 'bg-primary text-white' : ''}`}
                onClick={() => setActiveTab(tab)}
                data-testid={`portal-tab-${tab}`}
              >
                {tab}
              </Chip>
            ))}
          </div>

          {/* Invoices tab */}
          {activeTab === 'invoices' && (
            <>
              <BlockTitle>Your Invoices</BlockTitle>
              {invoices.length === 0 ? (
                <Block className="text-center">
                  <p className="text-sm text-gray-400 dark:text-gray-500">No invoices found</p>
                </Block>
              ) : (
                <List strongIos outlineIos>
                  {invoices.map((inv) => (
                    <ListItem
                      key={inv.id}
                      title={
                        <span className="font-medium text-gray-900 dark:text-gray-100">
                          {inv.invoice_number ?? 'Invoice'}
                        </span>
                      }
                      subtitle={
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          Due: {formatDate(inv.due_date)}
                        </span>
                      }
                      after={
                        <div className="flex flex-col items-end gap-1">
                          <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                            {formatNZD(inv.total)}
                          </span>
                          <StatusBadge status={inv.status ?? 'draft'} size="sm" />
                        </div>
                      }
                      data-testid={`portal-invoice-${inv.id}`}
                    />
                  ))}
                </List>
              )}

              {/* Pay outstanding invoices */}
              {invoices.filter((i) => (i.balance_due ?? 0) > 0).length > 0 && (
                <>
                  <BlockTitle>Outstanding</BlockTitle>
                  <Block>
                    {invoices
                      .filter((i) => (i.balance_due ?? 0) > 0)
                      .map((inv) => (
                        <Card key={inv.id} className="mb-3">
                          <div className="flex items-center justify-between">
                            <div>
                              <p className="font-medium text-gray-900 dark:text-gray-100">
                                {inv.invoice_number ?? 'Invoice'}
                              </p>
                              <p className="text-sm text-gray-500 dark:text-gray-400">
                                Balance: {formatNZD(inv.balance_due)}
                              </p>
                            </div>
                            <HapticButton
                              hapticStyle="light"
                              small
                              onClick={() => handlePayInvoice(inv.id)}
                              data-testid={`pay-invoice-${inv.id}`}
                            >
                              Pay Now
                            </HapticButton>
                          </div>
                        </Card>
                      ))}
                  </Block>
                </>
              )}
            </>
          )}

          {/* Quotes tab */}
          {activeTab === 'quotes' && (
            <>
              <BlockTitle>Your Quotes</BlockTitle>
              {quotes.length === 0 ? (
                <Block className="text-center">
                  <p className="text-sm text-gray-400 dark:text-gray-500">No quotes found</p>
                </Block>
              ) : (
                <List strongIos outlineIos>
                  {quotes.map((quote) => (
                    <ListItem
                      key={quote.id}
                      title={
                        <span className="font-medium text-gray-900 dark:text-gray-100">
                          {quote.quote_number ?? 'Quote'}
                        </span>
                      }
                      subtitle={
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          Expires: {formatDate(quote.expiry_date)}
                        </span>
                      }
                      after={
                        <div className="flex flex-col items-end gap-1">
                          <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                            {formatNZD(quote.total)}
                          </span>
                          <StatusBadge status={quote.status ?? 'draft'} size="sm" />
                          {quote.status === 'sent' && (
                            <Button
                              small
                              tonal
                              onClick={() => handleAcceptQuote(quote.id)}
                              data-testid={`accept-quote-${quote.id}`}
                            >
                              Accept
                            </Button>
                          )}
                        </div>
                      }
                      data-testid={`portal-quote-${quote.id}`}
                    />
                  ))}
                </List>
              )}
            </>
          )}

          {/* Bookings tab */}
          {activeTab === 'bookings' && (
            <>
              <BlockTitle>Your Bookings</BlockTitle>
              {bookings.length === 0 ? (
                <Block className="text-center">
                  <p className="text-sm text-gray-400 dark:text-gray-500">No bookings found</p>
                </Block>
              ) : (
                <List strongIos outlineIos>
                  {bookings.map((booking) => (
                    <ListItem
                      key={booking.id}
                      title={
                        <span className="font-medium text-gray-900 dark:text-gray-100">
                          {booking.service_type ?? 'Appointment'}
                        </span>
                      }
                      subtitle={
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          {formatDate(booking.date)}
                          {booking.time ? ` at ${booking.time}` : ''}
                        </span>
                      }
                      after={
                        <StatusBadge status={booking.status ?? 'pending'} size="sm" />
                      }
                      data-testid={`portal-booking-${booking.id}`}
                    />
                  ))}
                </List>
              )}

              <Block>
                <HapticButton
                  hapticStyle="light"
                  large
                  onClick={handleBookAppointment}
                  className="w-full"
                  data-testid="book-appointment-btn"
                >
                  Book Appointment
                </HapticButton>
              </Block>
            </>
          )}
        </div>
      </PullRefresh>
    </Page>
  )
}
