import { useState, useEffect, useMemo, FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { loadStripe } from '@stripe/stripe-js'
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js'
import axios from 'axios'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Button } from '@/components/ui/Button'

/* ── Types matching backend PaymentPageResponse schema ── */

interface PaymentPageLineItem {
  description: string
  quantity: number
  unit_price: number
  line_total: number
}

interface PaymentPageData {
  org_name: string
  org_logo_url: string | null
  org_primary_colour: string | null
  invoice_number: string | null
  issue_date: string | null
  due_date: string | null
  currency: string
  line_items: PaymentPageLineItem[]
  subtotal: number
  gst_amount: number
  total: number
  amount_paid: number
  balance_due: number
  status: string
  client_secret: string | null
  connected_account_id: string | null
  publishable_key: string | null
  is_paid: boolean
  is_payable: boolean
  error_message: string | null
}

/* ── Currency formatter ── */

function formatCurrency(amount: number, currency: string): string {
  const code = (currency ?? 'NZD').toUpperCase()
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: code }).format(amount ?? 0)
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

/* ══════════════════════════════════════════════════════════════════════════
   Task 8.3 — Invoice Preview Section
   ══════════════════════════════════════════════════════════════════════════ */

interface InvoicePreviewProps {
  data: PaymentPageData
}

function InvoicePreview({ data }: InvoicePreviewProps) {
  const primaryColour = data?.org_primary_colour ?? '#2563eb'
  const currency = data?.currency ?? 'NZD'

  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      {/* Org branding header */}
      <div
        className="rounded-t-lg px-6 py-4"
        style={{ backgroundColor: primaryColour, opacity: 0.95 }}
      >
        <div className="flex items-center gap-3">
          {data?.org_logo_url && (
            <img
              src={data.org_logo_url}
              alt={`${data?.org_name ?? 'Organisation'} logo`}
              className="h-10 w-10 rounded-md bg-white object-contain p-0.5"
            />
          )}
          <h2 className="text-lg font-semibold text-white">
            {data?.org_name ?? 'Invoice'}
          </h2>
        </div>
      </div>

      <div className="p-6 space-y-5">
        {/* Invoice meta */}
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-gray-500">Invoice</span>
            <p className="font-medium text-gray-900">{data?.invoice_number ?? '—'}</p>
          </div>
          <div>
            <span className="text-gray-500">Status</span>
            <p className="font-medium text-gray-900 capitalize">{data?.status ?? '—'}</p>
          </div>
          <div>
            <span className="text-gray-500">Issue Date</span>
            <p className="font-medium text-gray-900">{formatDate(data?.issue_date)}</p>
          </div>
          <div>
            <span className="text-gray-500">Due Date</span>
            <p className="font-medium text-gray-900">{formatDate(data?.due_date)}</p>
          </div>
        </div>

        {/* Line items table */}
        {(data?.line_items ?? []).length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-gray-500">
                  <th className="pb-2 font-medium">Description</th>
                  <th className="pb-2 font-medium text-right">Qty</th>
                  <th className="pb-2 font-medium text-right">Unit Price</th>
                  <th className="pb-2 font-medium text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {(data?.line_items ?? []).map((item, idx) => (
                  <tr key={idx} className="border-b border-gray-100">
                    <td className="py-2 text-gray-900">{item?.description ?? ''}</td>
                    <td className="py-2 text-right text-gray-700 tabular-nums">
                      {(item?.quantity ?? 0)}
                    </td>
                    <td className="py-2 text-right text-gray-700 tabular-nums">
                      {formatCurrency(item?.unit_price ?? 0, currency)}
                    </td>
                    <td className="py-2 text-right text-gray-900 font-medium tabular-nums">
                      {formatCurrency(item?.line_total ?? 0, currency)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Totals */}
        <div className="space-y-2 border-t border-gray-200 pt-4 text-sm">
          <div className="flex justify-between text-gray-600">
            <span>Subtotal</span>
            <span className="tabular-nums">{formatCurrency(data?.subtotal ?? 0, currency)}</span>
          </div>
          <div className="flex justify-between text-gray-600">
            <span>GST</span>
            <span className="tabular-nums">{formatCurrency(data?.gst_amount ?? 0, currency)}</span>
          </div>
          <div className="flex justify-between font-semibold text-gray-900 border-t border-gray-200 pt-2">
            <span>Total</span>
            <span className="tabular-nums">{formatCurrency(data?.total ?? 0, currency)}</span>
          </div>
          {(data?.amount_paid ?? 0) > 0 && (
            <div className="flex justify-between text-gray-600">
              <span>Amount Paid</span>
              <span className="tabular-nums">
                −{formatCurrency(data?.amount_paid ?? 0, currency)}
              </span>
            </div>
          )}
          <div
            className="flex justify-between text-base font-bold pt-1"
            style={{ color: primaryColour }}
          >
            <span>Balance Due</span>
            <span className="tabular-nums">{formatCurrency(data?.balance_due ?? 0, currency)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════
   Task 8.2 — Payment Form Sub-Component
   ══════════════════════════════════════════════════════════════════════════ */

interface PaymentFormProps {
  balanceDue: number
  currency: string
  invoiceNumber: string | null
  clientSecret: string
}

function PaymentForm({ balanceDue, currency, invoiceNumber, clientSecret }: PaymentFormProps) {
  const stripe = useStripe()
  const elements = useElements()
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [succeeded, setSucceeded] = useState(false)

  const amountDisplay = formatCurrency(balanceDue ?? 0, currency ?? 'NZD')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!stripe || !elements) return

    setProcessing(true)
    setError(null)

    const cardElement = elements.getElement(CardElement)
    if (!cardElement) {
      setError('Card element not found. Please refresh and try again.')
      setProcessing(false)
      return
    }

    const { error: stripeError, paymentIntent } = await stripe.confirmCardPayment(
      clientSecret,
      { payment_method: { card: cardElement } },
    )

    if (stripeError) {
      setError(stripeError.message ?? 'Payment failed. Please try again.')
      setProcessing(false)
      return
    }

    if (paymentIntent?.status === 'succeeded') {
      setSucceeded(true)
      setProcessing(false)
    } else {
      setError('Payment was not completed. Please try again.')
      setProcessing(false)
    }
  }

  if (succeeded) {
    return (
      <div className="rounded-lg border border-green-200 bg-green-50 p-6 text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
          <svg className="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h3 className="text-lg font-semibold text-green-900">Payment Successful</h3>
        <p className="mt-2 text-sm text-green-700">
          {amountDisplay} has been paid
          {invoiceNumber ? ` for invoice ${invoiceNumber}` : ''}.
        </p>
        <p className="mt-1 text-sm text-green-600">
          You will receive a confirmation email shortly.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h3 className="text-lg font-semibold text-gray-900">Payment Details</h3>
      <p className="mt-1 text-sm text-gray-600">
        Enter your card details to pay {amountDisplay}
      </p>

      <form onSubmit={handleSubmit} className="mt-5 space-y-4" data-testid="invoice-payment-form">
        {error && (
          <AlertBanner variant="error">
            {error}
          </AlertBanner>
        )}

        {/* Amount summary */}
        <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
          <div className="flex justify-between text-sm font-semibold text-gray-900">
            <span>Amount to pay</span>
            <span className="tabular-nums">{amountDisplay}</span>
          </div>
        </div>

        {/* Card element */}
        <div className="rounded-md border border-gray-300 p-3">
          <CardElement
            options={{
              hidePostalCode: true,
              style: {
                base: {
                  fontSize: '16px',
                  color: '#1f2937',
                  '::placeholder': { color: '#9ca3af' },
                },
              },
            }}
          />
        </div>

        <p className="text-xs text-gray-500">
          Your payment is processed securely by Stripe. Card details are never stored on our servers.
        </p>

        <Button
          type="submit"
          loading={processing}
          disabled={!stripe || processing}
          className="w-full"
        >
          Pay {amountDisplay}
        </Button>
      </form>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════
   Task 8.1 — Main Page Component
   ══════════════════════════════════════════════════════════════════════════ */

export default function InvoicePaymentPage() {
  const { token } = useParams<{ token: string }>()
  const [data, setData] = useState<PaymentPageData | null>(null)
  const [loading, setLoading] = useState(true)
  const [errorState, setErrorState] = useState<{ type: 'not_found' | 'expired' | 'network'; message: string } | null>(null)

  /* Fetch payment page data on mount */
  useEffect(() => {
    const controller = new AbortController()

    async function fetchPaymentPage() {
      if (!token) {
        setErrorState({ type: 'not_found', message: 'Invalid payment link.' })
        setLoading(false)
        return
      }

      try {
        const res = await axios.get<PaymentPageData>(`/api/v1/public/pay/${token}`, {
          signal: controller.signal,
        })
        setData(res.data ?? null)
      } catch (err) {
        if (controller.signal.aborted) return

        if (axios.isAxiosError(err)) {
          const status = err.response?.status
          if (status === 404) {
            setErrorState({ type: 'not_found', message: 'Invalid payment link.' })
          } else if (status === 410) {
            setErrorState({
              type: 'expired',
              message: 'This payment link has expired. Please contact the business for a new link.',
            })
          } else {
            setErrorState({
              type: 'network',
              message: 'Something went wrong loading this page. Please try again later.',
            })
          }
        } else {
          setErrorState({
            type: 'network',
            message: 'Something went wrong loading this page. Please try again later.',
          })
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    fetchPaymentPage()
    return () => controller.abort()
  }, [token])

  /* Stripe promise — memoised so it's only created once when data arrives */
  const stripePromise = useMemo(() => {
    if (!data?.publishable_key || !data?.connected_account_id) return null
    return loadStripe(data.publishable_key, {
      stripeAccount: data.connected_account_id,
    })
  }, [data?.publishable_key, data?.connected_account_id])

  /* ── Loading state ── */
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <Spinner size="lg" label="Loading payment page" />
      </div>
    )
  }

  /* ── Error states ── */
  if (errorState) {
    const variant = errorState.type === 'expired' ? 'warning' : 'error'
    const title =
      errorState.type === 'not_found'
        ? 'Invalid Link'
        : errorState.type === 'expired'
          ? 'Link Expired'
          : 'Error'

    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md">
          <AlertBanner variant={variant} title={title}>
            {errorState.message}
          </AlertBanner>
        </div>
      </div>
    )
  }

  /* ── Invoice already paid ── */
  if (data?.is_paid) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md">
          <div className="rounded-lg border border-green-200 bg-green-50 p-6 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
              <svg className="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-lg font-semibold text-green-900">This invoice has been paid</h2>
            <p className="mt-2 text-sm text-green-700">
              Invoice {data?.invoice_number ?? ''} has been fully paid. No further action is needed.
            </p>
          </div>
        </div>
      </div>
    )
  }

  /* ── Invoice not payable (voided, draft, etc.) ── */
  if (!data?.is_payable) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md">
          <AlertBanner variant="warning" title="Invoice Not Payable">
            {data?.error_message ?? 'This invoice is not currently available for payment.'}
          </AlertBanner>
        </div>
      </div>
    )
  }

  /* ── Payable invoice — two-column layout ── */
  const primaryColour = data?.org_primary_colour ?? '#2563eb'

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar with org branding */}
      <header
        className="border-b px-4 py-3"
        style={{ backgroundColor: primaryColour }}
      >
        <div className="mx-auto flex max-w-5xl items-center gap-3">
          {data?.org_logo_url && (
            <img
              src={data.org_logo_url}
              alt={`${data?.org_name ?? 'Organisation'} logo`}
              className="h-8 w-8 rounded bg-white object-contain p-0.5"
            />
          )}
          <span className="text-sm font-medium text-white">
            {data?.org_name ?? 'Payment'}
          </span>
        </div>
      </header>

      {/* Main content — responsive two-column / stacked */}
      <main className="mx-auto max-w-5xl px-4 py-8">
        <div className="flex flex-col gap-8 md:flex-row">
          {/* Left / Top: Invoice preview */}
          <div className="w-full md:w-1/2">
            <InvoicePreview data={data!} />
          </div>

          {/* Right / Bottom: Payment form */}
          <div className="w-full md:w-1/2">
            {stripePromise && data?.client_secret ? (
              <Elements stripe={stripePromise} options={{ clientSecret: data.client_secret }}>
                <PaymentForm
                  balanceDue={data?.balance_due ?? 0}
                  currency={data?.currency ?? 'NZD'}
                  invoiceNumber={data?.invoice_number ?? null}
                  clientSecret={data.client_secret}
                />
              </Elements>
            ) : (
              <AlertBanner variant="error" title="Payment Unavailable">
                Unable to initialise the payment form. Please try refreshing the page.
              </AlertBanner>
            )}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-200 bg-white py-4 text-center text-xs text-gray-400">
        Payments processed securely by{' '}
        <a
          href="https://stripe.com"
          target="_blank"
          rel="noopener noreferrer"
          className="text-gray-500 hover:text-gray-700 underline"
        >
          Stripe
        </a>
      </footer>
    </div>
  )
}
