import { useState, useEffect, useMemo, FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { Page, Block, Card, Button } from 'konsta/react'
import { loadStripe } from '@stripe/stripe-js'
import {
  Elements,
  PaymentElement,
  useStripe,
  useElements,
} from '@stripe/react-stripe-js'
import axios from 'axios'

/**
 * PublicPaymentScreen — Konsta UI redesign of the public invoice payment page.
 *
 * Renders at `/pay/:token` without authentication. Displays an invoice summary
 * card (org logo, invoice number, customer, collapsed line items, total) and a
 * Stripe Elements payment form with a "Pay NZD X,XXX.XX" primary button.
 *
 * Business logic is preserved unchanged from the frontend InvoicePaymentPage:
 * - GET /api/v1/public/pay/:token for invoice data
 * - Stripe Elements (PaymentElement) for payment input
 * - POST /api/v1/public/pay/:token/confirm after successful payment
 * - POST /api/v1/public/pay/:token/update-surcharge for surcharge calculation
 *
 * Requirements: 16.1, 16.2, 16.3, 16.4
 */

// ---------------------------------------------------------------------------
// Types matching backend PaymentPageResponse schema
// ---------------------------------------------------------------------------

interface PaymentPageLineItem {
  description: string
  quantity: number
  unit_price: number
  line_total: number
}

interface SurchargeRateInfo {
  percentage: string
  fixed: string
  enabled: boolean
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
  surcharge_enabled: boolean
  surcharge_rates: Record<string, SurchargeRateInfo>
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatNZD(amount: number | null | undefined): string {
  return new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: 'NZD',
  }).format(amount ?? 0)
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

const METHOD_DISPLAY_NAMES: Record<string, string> = {
  card: 'Credit/Debit Card',
  afterpay_clearpay: 'Afterpay',
  klarna: 'Klarna',
  bank_transfer: 'Bank Transfer',
}

// ---------------------------------------------------------------------------
// Invoice Summary Card
// ---------------------------------------------------------------------------

interface InvoiceSummaryProps {
  data: PaymentPageData
}

function InvoiceSummary({ data }: InvoiceSummaryProps) {
  const [showLineItems, setShowLineItems] = useState(false)
  const primaryColour = data?.org_primary_colour ?? '#2563eb'
  const lineItems = data?.line_items ?? []

  return (
    <Card className="!m-0 overflow-hidden">
      {/* Org branding header */}
      <div
        className="flex items-center gap-3 px-4 py-3"
        style={{ backgroundColor: primaryColour }}
      >
        {data?.org_logo_url && (
          <img
            src={data.org_logo_url}
            alt={`${data?.org_name ?? 'Organisation'} logo`}
            className="h-10 w-10 rounded-lg bg-white object-contain p-0.5"
          />
        )}
        <div>
          <h2 className="text-base font-semibold text-white">
            {data?.org_name ?? 'Invoice'}
          </h2>
          {data?.invoice_number && (
            <p className="text-xs text-white/80">
              Invoice {data.invoice_number}
            </p>
          )}
        </div>
      </div>

      <div className="p-4">
        {/* Invoice meta grid */}
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              Status
            </span>
            <p className="font-medium capitalize text-gray-900 dark:text-gray-100">
              {data?.status ?? '—'}
            </p>
          </div>
          <div>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              Due Date
            </span>
            <p className="font-medium text-gray-900 dark:text-gray-100">
              {formatDate(data?.due_date)}
            </p>
          </div>
          <div>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              Issue Date
            </span>
            <p className="font-medium text-gray-900 dark:text-gray-100">
              {formatDate(data?.issue_date)}
            </p>
          </div>
          <div>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              Invoice
            </span>
            <p className="font-medium text-gray-900 dark:text-gray-100">
              {data?.invoice_number ?? '—'}
            </p>
          </div>
        </div>

        {/* Collapsible line items */}
        {lineItems.length > 0 && (
          <div className="mt-4">
            <button
              type="button"
              onClick={() => setShowLineItems(!showLineItems)}
              className="flex min-h-[44px] w-full items-center justify-between text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400"
            >
              <span>
                {lineItems.length} line item{lineItems.length !== 1 ? 's' : ''}
              </span>
              <svg
                className={`h-4 w-4 transition-transform ${showLineItems ? 'rotate-180' : ''}`}
                viewBox="0 0 20 20"
                fill="currentColor"
                aria-hidden="true"
              >
                <path
                  fillRule="evenodd"
                  d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
                  clipRule="evenodd"
                />
              </svg>
            </button>

            {showLineItems && (
              <div className="mt-2 space-y-2">
                {lineItems.map((item, idx) => (
                  <div
                    key={idx}
                    className="flex items-start justify-between rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800"
                  >
                    <div className="flex-1 pr-3">
                      <p className="font-medium text-gray-900 dark:text-gray-100">
                        {item?.description ?? ''}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {item?.quantity ?? 0} × {formatNZD(item?.unit_price ?? 0)}
                      </p>
                    </div>
                    <span className="whitespace-nowrap font-medium tabular-nums text-gray-900 dark:text-gray-100">
                      {formatNZD(item?.line_total ?? 0)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Totals */}
        <div className="mt-4 space-y-1.5 border-t border-gray-200 pt-3 text-sm dark:border-gray-700">
          <div className="flex justify-between text-gray-600 dark:text-gray-400">
            <span>Subtotal</span>
            <span className="tabular-nums">{formatNZD(data?.subtotal ?? 0)}</span>
          </div>
          <div className="flex justify-between text-gray-600 dark:text-gray-400">
            <span>GST</span>
            <span className="tabular-nums">{formatNZD(data?.gst_amount ?? 0)}</span>
          </div>
          <div className="flex justify-between border-t border-gray-200 pt-1.5 font-semibold text-gray-900 dark:border-gray-700 dark:text-gray-100">
            <span>Total</span>
            <span className="tabular-nums">{formatNZD(data?.total ?? 0)}</span>
          </div>
          {(data?.amount_paid ?? 0) > 0 && (
            <div className="flex justify-between text-gray-600 dark:text-gray-400">
              <span>Amount Paid</span>
              <span className="tabular-nums">
                −{formatNZD(data?.amount_paid ?? 0)}
              </span>
            </div>
          )}
          <div
            className="flex justify-between pt-1 text-base font-bold"
            style={{ color: primaryColour }}
          >
            <span>Balance Due</span>
            <span className="tabular-nums">
              {formatNZD(data?.balance_due ?? 0)}
            </span>
          </div>
        </div>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Payment Form (inner component — must be inside <Elements>)
// ---------------------------------------------------------------------------

interface PaymentFormProps {
  balanceDue: number
  invoiceNumber: string | null
  token: string
  surchargeEnabled: boolean
  surchargeRates: Record<string, SurchargeRateInfo>
}

function PaymentForm({
  balanceDue: rawBalanceDue,
  invoiceNumber,
  token,
  surchargeEnabled,
  surchargeRates,
}: PaymentFormProps) {
  const balanceDue = Number(rawBalanceDue) || 0
  const stripe = useStripe()
  const elements = useElements()
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [succeeded, setSucceeded] = useState(false)
  const [selectedMethod, setSelectedMethod] = useState<string | null>(null)
  const [surchargeAmount, setSurchargeAmount] = useState<number>(0)
  const [updatingPI, setUpdatingPI] = useState(false)

  // Compute surcharge locally for instant display, then update PaymentIntent on backend
  useEffect(() => {
    if (!selectedMethod || !surchargeEnabled) {
      setSurchargeAmount(0)
      return
    }

    const rate = surchargeRates?.[selectedMethod]
    if (!rate?.enabled) {
      setSurchargeAmount(0)
      return
    }

    const pct = parseFloat(rate?.percentage ?? '0') ?? 0
    const fixed = parseFloat(rate?.fixed ?? '0') ?? 0
    const computed =
      Math.round(((balanceDue ?? 0) * pct / 100 + fixed) * 100) / 100
    setSurchargeAmount(computed)

    const controller = new AbortController()
    const updatePI = async () => {
      setUpdatingPI(true)
      try {
        await axios.post(
          `/api/v1/public/pay/${token}/update-surcharge`,
          { payment_method_type: selectedMethod },
          { signal: controller.signal },
        )
      } catch (err) {
        if (!controller.signal.aborted) {
          setError('Failed to update payment amount. Please try again.')
        }
      } finally {
        if (!controller.signal.aborted) {
          setUpdatingPI(false)
        }
      }
    }
    updatePI()
    return () => controller.abort()
  }, [selectedMethod, surchargeEnabled, balanceDue, token, surchargeRates])

  const totalToPay = (balanceDue ?? 0) + (surchargeAmount ?? 0)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!stripe || !elements) return

    setProcessing(true)
    setError(null)

    const { error: stripeError, paymentIntent } = await stripe.confirmPayment({
      elements,
      confirmParams: {
        return_url: `${window.location.origin}/pay/${token}`,
      },
      redirect: 'if_required',
    })

    if (stripeError) {
      setError(stripeError.message ?? 'Payment failed. Please try again.')
      setProcessing(false)
      return
    }

    if (paymentIntent?.status === 'succeeded') {
      try {
        await axios.post(`/api/v1/public/pay/${token}/confirm`)
      } catch {
        // Non-fatal — webhook will eventually record it
        console.warn('Payment confirm call failed — webhook will handle it')
      }
      setSucceeded(true)
      setProcessing(false)
    } else if (paymentIntent?.status === 'requires_action') {
      setError('Additional verification required. Please follow the prompts.')
      setProcessing(false)
    } else {
      setError('Payment was not completed. Please try again.')
      setProcessing(false)
    }
  }

  if (succeeded) {
    const totalDisplay = formatNZD(totalToPay)
    const methodLabel =
      METHOD_DISPLAY_NAMES[selectedMethod ?? ''] ?? selectedMethod ?? ''

    return (
      <Card className="!m-0 overflow-hidden">
        <div className="p-6 text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30">
            <svg
              className="h-7 w-7 text-green-600 dark:text-green-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-green-900 dark:text-green-300">
            Payment Successful
          </h3>
          <p className="mt-2 text-sm text-green-700 dark:text-green-400">
            {totalDisplay} has been paid
            {invoiceNumber ? ` for invoice ${invoiceNumber}` : ''}.
          </p>
          {(surchargeAmount ?? 0) > 0 && (
            <div className="mt-3 rounded-lg bg-green-50 p-3 text-left text-sm dark:bg-green-900/20">
              <div className="flex justify-between text-green-800 dark:text-green-300">
                <span>Invoice amount</span>
                <span className="tabular-nums">{formatNZD(balanceDue)}</span>
              </div>
              <div className="flex justify-between text-green-800 dark:text-green-300">
                <span>Surcharge ({methodLabel})</span>
                <span className="tabular-nums">
                  {formatNZD(surchargeAmount ?? 0)}
                </span>
              </div>
              <div className="mt-1 flex justify-between border-t border-green-200 pt-1 font-semibold text-green-900 dark:border-green-700 dark:text-green-200">
                <span>Total paid</span>
                <span className="tabular-nums">{totalDisplay}</span>
              </div>
            </div>
          )}
          <p className="mt-3 text-sm text-green-600 dark:text-green-400">
            You will receive a confirmation email shortly.
          </p>
        </div>
      </Card>
    )
  }

  return (
    <Block className="!px-0">
      <h3 className="mb-1 px-4 text-base font-semibold text-gray-900 dark:text-gray-100">
        Payment Details
      </h3>
      <p className="mb-4 px-4 text-sm text-gray-600 dark:text-gray-400">
        Choose a payment method to pay {formatNZD(balanceDue)}
      </p>

      <form onSubmit={handleSubmit} noValidate className="space-y-4 px-4">
        {error && (
          <div
            role="alert"
            className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            {error}
          </div>
        )}

        {/* Amount summary — surcharge-aware */}
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800">
          {(surchargeAmount ?? 0) > 0 ? (
            <div className="space-y-1.5 text-sm">
              <div className="flex justify-between text-gray-700 dark:text-gray-300">
                <span>Invoice balance</span>
                <span className="tabular-nums">{formatNZD(balanceDue)}</span>
              </div>
              <div className="flex justify-between text-gray-700 dark:text-gray-300">
                <span>
                  Surcharge (
                  {METHOD_DISPLAY_NAMES[selectedMethod ?? ''] ??
                    selectedMethod ??
                    'Unknown'}
                  )
                </span>
                <span className="tabular-nums">
                  {formatNZD(surchargeAmount ?? 0)}
                </span>
              </div>
              <div className="flex justify-between border-t border-gray-200 pt-1.5 font-semibold text-gray-900 dark:border-gray-600 dark:text-gray-100">
                <span>Total to pay</span>
                <span className="tabular-nums">{formatNZD(totalToPay)}</span>
              </div>
              <p className="pt-1 text-xs text-gray-500 dark:text-gray-400">
                A surcharge is applied to cover payment processing fees
              </p>
            </div>
          ) : (
            <div className="flex justify-between text-sm font-semibold text-gray-900 dark:text-gray-100">
              <span>Amount to pay</span>
              <span className="tabular-nums">{formatNZD(balanceDue)}</span>
            </div>
          )}
        </div>

        {/* Stripe PaymentElement */}
        <div className="rounded-lg border border-gray-300 bg-white p-3 dark:border-gray-600 dark:bg-gray-800">
          <PaymentElement
            options={{ layout: 'tabs' }}
            onChange={(event) => {
              const methodType = event.value?.type ?? null
              setSelectedMethod(methodType)
            }}
          />
        </div>

        <p className="text-xs text-gray-500 dark:text-gray-400">
          Your payment is processed securely by Stripe. Card details are never
          stored on our servers.
        </p>

        <Button
          type="submit"
          large
          disabled={!stripe || processing || updatingPI}
        >
          {processing ? 'Processing…' : `Pay ${formatNZD(totalToPay)}`}
        </Button>
      </form>
    </Block>
  )
}

// ---------------------------------------------------------------------------
// Main PublicPaymentScreen component
// ---------------------------------------------------------------------------

export default function PublicPaymentScreen() {
  const { token } = useParams<{ token: string }>()
  const [data, setData] = useState<PaymentPageData | null>(null)
  const [loading, setLoading] = useState(true)
  const [errorState, setErrorState] = useState<{
    type: 'not_found' | 'expired' | 'network'
    message: string
  } | null>(null)
  const [redirectResult, setRedirectResult] = useState<
    'succeeded' | 'failed' | null
  >(null)

  // Check for Stripe redirect status (Klarna, Afterpay, etc.)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const status = params.get('redirect_status')
    if (status === 'succeeded') {
      setRedirectResult('succeeded')
      if (token) {
        axios
          .post(`/api/v1/public/pay/${token}/confirm`)
          .catch(() =>
            console.warn(
              'Payment confirm call failed — webhook will handle it',
            ),
          )
      }
    } else if (status === 'failed') {
      setRedirectResult('failed')
    }
    if (status) {
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [token])

  // Fetch payment page data on mount
  useEffect(() => {
    const controller = new AbortController()

    async function fetchPaymentPage() {
      if (!token) {
        setErrorState({ type: 'not_found', message: 'Invalid payment link.' })
        setLoading(false)
        return
      }

      try {
        const res = await axios.get<PaymentPageData>(
          `/api/v1/public/pay/${token}`,
          { signal: controller.signal },
        )
        setData(res.data ?? null)
      } catch (err) {
        if (controller.signal.aborted) return

        if (axios.isAxiosError(err)) {
          const status = err.response?.status
          if (status === 404) {
            setErrorState({
              type: 'not_found',
              message: 'Invalid payment link.',
            })
          } else if (status === 410) {
            setErrorState({
              type: 'expired',
              message:
                'This payment link has expired. Please contact the business for a new link.',
            })
          } else {
            setErrorState({
              type: 'network',
              message:
                'Something went wrong loading this page. Please try again later.',
            })
          }
        } else {
          setErrorState({
            type: 'network',
            message:
              'Something went wrong loading this page. Please try again later.',
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

  // Stripe promise — memoised so it's only created once when data arrives
  const stripePromise = useMemo(() => {
    if (!data?.publishable_key || !data?.connected_account_id) return null
    return loadStripe(data.publishable_key, {
      stripeAccount: data.connected_account_id,
    })
  }, [data?.publishable_key, data?.connected_account_id])

  // ── Loading state ──
  if (loading) {
    return (
      <Page className="bg-gray-50 dark:bg-gray-900">
        <div className="flex min-h-[60vh] items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      </Page>
    )
  }

  // ── Error states ──
  if (errorState) {
    const isExpired = errorState.type === 'expired'
    return (
      <Page className="bg-gray-50 dark:bg-gray-900">
        <div className="flex min-h-[60vh] items-center justify-center px-6">
          <Card className="!m-0 w-full max-w-sm">
            <div className="p-6 text-center">
              <div
                className={`mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full ${
                  isExpired
                    ? 'bg-amber-100 dark:bg-amber-900/30'
                    : 'bg-red-100 dark:bg-red-900/30'
                }`}
              >
                <svg
                  className={`h-7 w-7 ${
                    isExpired
                      ? 'text-amber-600 dark:text-amber-400'
                      : 'text-red-600 dark:text-red-400'
                  }`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
                  />
                </svg>
              </div>
              <h2
                className={`text-lg font-semibold ${
                  isExpired
                    ? 'text-amber-900 dark:text-amber-300'
                    : 'text-red-900 dark:text-red-300'
                }`}
              >
                {errorState.type === 'not_found'
                  ? 'Invalid Link'
                  : errorState.type === 'expired'
                    ? 'Link Expired'
                    : 'Error'}
              </h2>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                {errorState.message}
              </p>
            </div>
          </Card>
        </div>
      </Page>
    )
  }

  // ── Redirect result from Klarna/Afterpay/etc. ──
  if (redirectResult === 'succeeded') {
    return (
      <Page className="bg-gray-50 dark:bg-gray-900">
        <div className="flex min-h-[60vh] items-center justify-center px-6">
          <Card className="!m-0 w-full max-w-sm">
            <div className="p-6 text-center">
              <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30">
                <svg
                  className="h-7 w-7 text-green-600 dark:text-green-400"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 13l4 4L19 7"
                  />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-green-900 dark:text-green-300">
                Payment Successful
              </h3>
              <p className="mt-2 text-sm text-green-700 dark:text-green-400">
                Your payment for invoice {data?.invoice_number ?? ''} has been
                processed.
              </p>
              <p className="mt-1 text-sm text-green-600 dark:text-green-400">
                You will receive a confirmation email shortly.
              </p>
            </div>
          </Card>
        </div>
      </Page>
    )
  }

  // ── Invoice already paid ──
  if (data?.is_paid) {
    return (
      <Page className="bg-gray-50 dark:bg-gray-900">
        <div className="flex min-h-[60vh] items-center justify-center px-6">
          <Card className="!m-0 w-full max-w-sm">
            <div className="p-6 text-center">
              <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30">
                <svg
                  className="h-7 w-7 text-green-600 dark:text-green-400"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 13l4 4L19 7"
                  />
                </svg>
              </div>
              <h2 className="text-lg font-semibold text-green-900 dark:text-green-300">
                This invoice has been paid
              </h2>
              <p className="mt-2 text-sm text-green-700 dark:text-green-400">
                Invoice {data?.invoice_number ?? ''} has been fully paid. No
                further action is needed.
              </p>
            </div>
          </Card>
        </div>
      </Page>
    )
  }

  // ── Invoice not payable (voided, draft, etc.) ──
  if (!data?.is_payable) {
    return (
      <Page className="bg-gray-50 dark:bg-gray-900">
        <div className="flex min-h-[60vh] items-center justify-center px-6">
          <Card className="!m-0 w-full max-w-sm">
            <div className="p-6 text-center">
              <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30">
                <svg
                  className="h-7 w-7 text-amber-600 dark:text-amber-400"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
                  />
                </svg>
              </div>
              <h2 className="text-lg font-semibold text-amber-900 dark:text-amber-300">
                Invoice Not Payable
              </h2>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                {data?.error_message ??
                  'This invoice is not currently available for payment.'}
              </p>
            </div>
          </Card>
        </div>
      </Page>
    )
  }

  // ── Payable invoice — summary + payment form ──
  return (
    <Page className="bg-gray-50 dark:bg-gray-900">
      {/* Compact header */}
      <div className="bg-white px-4 py-3 shadow-sm dark:bg-gray-800">
        <div className="flex items-center gap-2">
          <LockIcon />
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
            Secure Payment
          </span>
        </div>
      </div>

      <Block className="space-y-4 pb-8">
        {/* Redirect failure banner */}
        {redirectResult === 'failed' && (
          <div
            role="alert"
            className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            Your previous payment attempt was not completed. Please try again.
          </div>
        )}

        {/* Invoice summary card */}
        <InvoiceSummary data={data!} />

        {/* Stripe payment form */}
        {stripePromise && data?.client_secret ? (
          <Elements
            stripe={stripePromise}
            options={{ clientSecret: data.client_secret }}
          >
            <PaymentForm
              balanceDue={Number(data?.balance_due ?? 0)}
              invoiceNumber={data?.invoice_number ?? null}
              token={token ?? ''}
              surchargeEnabled={data?.surcharge_enabled ?? false}
              surchargeRates={data?.surcharge_rates ?? {}}
            />
          </Elements>
        ) : (
          <Card className="!m-0">
            <div className="p-6 text-center">
              <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/30">
                <svg
                  className="h-7 w-7 text-red-600 dark:text-red-400"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 9v2m0 4h.01"
                  />
                </svg>
              </div>
              <h3 className="text-base font-semibold text-red-900 dark:text-red-300">
                Payment Unavailable
              </h3>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                Unable to initialise the payment form. Please try refreshing the
                page.
              </p>
            </div>
          </Card>
        )}

        {/* Footer */}
        <p className="text-center text-xs text-gray-400 dark:text-gray-500">
          Payments processed securely by{' '}
          <a
            href="https://stripe.com"
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
          >
            Stripe
          </a>
        </p>
      </Block>
    </Page>
  )
}

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------

function LockIcon() {
  return (
    <svg
      className="h-4 w-4 text-green-600 dark:text-green-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  )
}
