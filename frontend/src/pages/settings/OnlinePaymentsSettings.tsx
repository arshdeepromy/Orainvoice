/**
 * OnlinePaymentsSettings — Stripe Connect settings page for org admins.
 *
 * Tasks 5.1–5.4: Status display, conditional rendering, OAuth connect flow,
 * and disconnect flow with confirmation dialog.
 * Payment methods management section for connected accounts.
 */
import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Modal } from '@/components/ui/Modal'
import apiClient from '@/api/client'

/* ── Types ── */

interface OnlinePaymentsStatus {
  is_connected: boolean
  account_id_last4: string
  account_name: string
  connect_client_id_configured: boolean
  application_fee_percent: number | null
}

interface PaymentMethodInfo {
  type: string
  name: string
  description: string
  enabled: boolean
  always_on: boolean
  card_brands: string[]
}

interface PaymentMethodsResponse {
  payment_methods: PaymentMethodInfo[]
}

/* ── SVG Icons ── */

function VisaIcon({ className = 'h-8 w-12' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Visa">
      <rect width="48" height="32" rx="4" fill="#fff" stroke="#E5E7EB" strokeWidth="1" />
      <path d="M19.5 21h-2.7l1.7-10.5h2.7L19.5 21zm11.2-10.2c-.5-.2-1.4-.4-2.4-.4-2.7 0-4.5 1.4-4.5 3.4 0 1.5 1.4 2.3 2.4 2.8 1 .5 1.4.8 1.4 1.3 0 .7-.8 1-1.6 1-1.1 0-1.6-.2-2.5-.5l-.3-.2-.4 2.2c.6.3 1.8.5 3 .5 2.8 0 4.7-1.4 4.7-3.5 0-1.2-.7-2.1-2.3-2.8-.9-.5-1.5-.8-1.5-1.3 0-.4.5-.9 1.5-.9.9 0 1.5.2 2 .4l.2.1.3-2.1zm6.8-.3h-2.1c-.6 0-1.1.2-1.4.8L30 21h2.8l.6-1.5h3.5l.3 1.5H40l-2.3-10.5h-2.2zm-2.4 6.8l1.1-3 .3-.8.2.7.6 3.1h-2.2zM16.3 10.5L13.6 18l-.3-1.4c-.5-1.7-2.1-3.5-3.8-4.4l2.4 8.8h2.9l4.3-10.5h-2.8z" fill="#1A1F71" />
      <path d="M11.5 10.5H7.1l0 .2c3.4.9 5.6 2.9 6.5 5.4l-.9-4.7c-.2-.7-.7-.9-1.2-.9z" fill="#F79E1B" />
    </svg>
  )
}

function MastercardIcon({ className = 'h-8 w-12' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Mastercard">
      <rect width="48" height="32" rx="4" fill="#fff" stroke="#E5E7EB" strokeWidth="1" />
      <circle cx="19" cy="16" r="8" fill="#EB001B" />
      <circle cx="29" cy="16" r="8" fill="#F79E1B" />
      <path d="M24 10.3a8 8 0 0 1 0 11.4 8 8 0 0 1 0-11.4z" fill="#FF5F00" />
    </svg>
  )
}

function AmexIcon({ className = 'h-8 w-12' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="American Express">
      <rect width="48" height="32" rx="4" fill="#006FCF" />
      <text x="24" y="18" textAnchor="middle" fill="#fff" fontSize="7" fontWeight="bold" fontFamily="Arial, sans-serif">AMEX</text>
    </svg>
  )
}

function UnionPayIcon({ className = 'h-8 w-12' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="UnionPay">
      <rect width="48" height="32" rx="4" fill="#fff" stroke="#E5E7EB" strokeWidth="1" />
      <rect x="6" y="6" width="12" height="20" rx="2" fill="#E21836" />
      <rect x="16" y="6" width="12" height="20" rx="2" fill="#00447C" />
      <rect x="26" y="6" width="16" height="20" rx="2" fill="#007B84" />
      <text x="34" y="18" textAnchor="middle" fill="#fff" fontSize="5" fontWeight="bold" fontFamily="Arial, sans-serif">UP</text>
    </svg>
  )
}

function ApplePayIcon({ className = 'h-8 w-12' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Apple Pay">
      <rect width="48" height="32" rx="4" fill="#000" />
      <path d="M16.2 11.2c-.5.6-1.2 1-2 .9-.1-.8.3-1.6.7-2.1.5-.6 1.3-1 2-.9.1.8-.2 1.5-.7 2.1zm.7.5c-1.1-.1-2 .6-2.5.6s-1.3-.6-2.2-.6c-1.1 0-2.2.7-2.8 1.7-1.2 2-.3 5 .8 6.7.6.8 1.2 1.7 2.1 1.7.8 0 1.2-.5 2.2-.5s1.3.5 2.2.5c.9 0 1.4-.8 2-1.7.6-.9.9-1.8.9-1.8-1-.4-1.2-1.6-1.2-2.7 0-.9.4-1.8 1.1-2.3-.6-.8-1.5-1.3-2.6-1.6z" fill="#fff" />
      <text x="32" y="19" textAnchor="middle" fill="#fff" fontSize="7" fontWeight="600" fontFamily="Arial, sans-serif">Pay</text>
    </svg>
  )
}

function GooglePayIcon({ className = 'h-8 w-12' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Google Pay">
      <rect width="48" height="32" rx="4" fill="#fff" stroke="#E5E7EB" strokeWidth="1" />
      <path d="M22.7 16.5v3.1h-1v-7.7h2.6c.6 0 1.2.2 1.7.7.5.4.7 1 .7 1.6s-.2 1.2-.7 1.6c-.5.4-1 .7-1.7.7h-1.6zm0-3.6v2.7h1.7c.4 0 .7-.1 1-.4.3-.3.4-.6.4-1s-.2-.7-.4-1c-.3-.3-.6-.4-1-.4h-1.7z" fill="#3C4043" />
      <path d="M30.2 14.3c.7 0 1.3.2 1.7.6.4.4.6 1 .6 1.7v3h-.9v-.7c-.4.5-.9.8-1.6.8-.7 0-1.2-.2-1.6-.5-.4-.4-.6-.8-.6-1.3 0-.5.2-.9.6-1.3.4-.3.9-.5 1.6-.5.6 0 1 .1 1.3.4v-.3c0-.4-.1-.7-.4-1-.3-.3-.6-.4-1-.4-.6 0-1 .2-1.3.7l-.8-.5c.5-.7 1.2-1 2.1-1h.3zm-1.3 4c0 .3.1.5.4.7.2.2.5.3.8.3.4 0 .8-.2 1.1-.5.3-.3.5-.7.5-1.1-.3-.3-.8-.4-1.4-.4-.4 0-.8.1-1 .3-.3.2-.4.4-.4.7z" fill="#3C4043" />
      <path d="M37.5 14.5l-3.2 7.3h-1l1.2-2.6-2.1-4.7h1.1l1.5 3.5 1.5-3.5h1z" fill="#3C4043" />
      <path d="M18.5 16c0-.3 0-.6-.1-.9h-4.2v1.7h2.4c-.1.5-.4 1-.8 1.3v1.1h1.3c.8-.7 1.4-1.8 1.4-3.2z" fill="#4285F4" />
      <path d="M14.2 19.3c1.1 0 2-.4 2.7-1l-1.3-1c-.4.2-.8.4-1.4.4-.6 0-1.1-.2-1.5-.5-.4-.4-.7-.8-.8-1.4h-1.4v1.1c.7 1.4 2 2.4 3.7 2.4z" fill="#34A853" />
      <path d="M11.9 15.8c0-.3.1-.7.2-1v-1.1h-1.4c-.3.6-.5 1.3-.5 2.1s.2 1.5.5 2.1l1.4-1.1c-.1-.3-.2-.6-.2-1z" fill="#FBBC04" />
      <path d="M14.2 12.9c.6 0 1.1.2 1.5.6l1.1-1.1c-.7-.7-1.6-1-2.6-1-1.7 0-3 1-3.7 2.4l1.4 1.1c.3-1 1.3-1.9 2.3-1.9z" fill="#EA4335" />
    </svg>
  )
}

function StripeLinkIcon({ className = 'h-8 w-12' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Stripe Link">
      <rect width="48" height="32" rx="4" fill="#635BFF" />
      <text x="24" y="18" textAnchor="middle" fill="#fff" fontSize="7" fontWeight="600" fontFamily="Arial, sans-serif">Link</text>
    </svg>
  )
}

function AfterpayIcon({ className = 'h-8 w-12' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Afterpay">
      <rect width="48" height="32" rx="4" fill="#B2FCE4" />
      <text x="24" y="18" textAnchor="middle" fill="#000" fontSize="6" fontWeight="700" fontFamily="Arial, sans-serif">Afterpay</text>
    </svg>
  )
}

function KlarnaIcon({ className = 'h-8 w-12' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Klarna">
      <rect width="48" height="32" rx="4" fill="#FFB3C7" />
      <text x="24" y="18" textAnchor="middle" fill="#000" fontSize="7" fontWeight="700" fontFamily="Arial, sans-serif">Klarna</text>
    </svg>
  )
}

function GenericPaymentIcon({ className = 'h-8 w-12', label = '' }: { className?: string; label?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label={label}>
      <rect width="48" height="32" rx="4" fill="#F3F4F6" stroke="#D1D5DB" strokeWidth="1" />
      <rect x="8" y="10" width="32" height="4" rx="1" fill="#9CA3AF" />
      <rect x="8" y="18" width="20" height="3" rx="1" fill="#D1D5DB" />
    </svg>
  )
}

/* ── Small Checkbox Icon for inline grid ── */

function SmallPaymentMethodIcon({ type }: { type: string }) {
  const size = 'h-5 w-7'
  switch (type) {
    case 'card':
      return (
        <div className="flex items-center gap-0.5">
          <VisaIcon className={size} />
          <MastercardIcon className={size} />
          <AmexIcon className={size} />
          <UnionPayIcon className={size} />
        </div>
      )
    case 'apple_pay':
      return <ApplePayIcon className={size} />
    case 'google_pay':
      return <GooglePayIcon className={size} />
    case 'link':
      return <StripeLinkIcon className={size} />
    case 'afterpay_clearpay':
      return <AfterpayIcon className={size} />
    case 'klarna':
      return <KlarnaIcon className={size} />
    default:
      return <GenericPaymentIcon className={size} label={type} />
  }
}

/* ── Pencil Edit Icon ── */

function PencilIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M2.695 14.763l-1.262 3.154a.5.5 0 00.65.65l3.155-1.262a4 4 0 001.343-.885L17.5 5.5a2.121 2.121 0 00-3-3L3.58 13.42a4 4 0 00-.885 1.343z" />
    </svg>
  )
}


/* ── Payment Methods Section (inline checkboxes) ── */

function PaymentMethodsSection() {
  const [methods, setMethods] = useState<PaymentMethodInfo[]>([])
  const [loadingMethods, setLoadingMethods] = useState(true)
  const [methodsError, setMethodsError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  // Draft state for checkbox edits (only used while editing)
  const [draftEnabled, setDraftEnabled] = useState<Set<string>>(new Set())

  const fetchMethods = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await apiClient.get<PaymentMethodsResponse>(
        '/payments/online-payments/payment-methods',
        { signal },
      )
      setMethods(res.data?.payment_methods ?? [])
      setMethodsError(null)
    } catch (err) {
      if (!(err as { name?: string })?.name?.includes('Cancel')) {
        setMethodsError('Failed to load payment methods.')
      }
    } finally {
      setLoadingMethods(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchMethods(controller.signal)
    return () => controller.abort()
  }, [fetchMethods])

  const enabledMethodNames = (methods ?? [])
    .filter((m) => m?.enabled)
    .map((m) => m?.name ?? '')
    .filter(Boolean)

  const handleEditClick = () => {
    // Initialize draft from current enabled state
    const enabled = new Set<string>(
      (methods ?? []).filter((m) => m?.enabled).map((m) => m?.type ?? '').filter(Boolean),
    )
    // Always include card
    enabled.add('card')
    setDraftEnabled(enabled)
    setEditing(true)
    setMethodsError(null)
  }

  const handleCancel = () => {
    setEditing(false)
    setMethodsError(null)
  }

  const handleCheckboxChange = (methodType: string, checked: boolean) => {
    setDraftEnabled((prev) => {
      const next = new Set(prev)
      if (checked) {
        next.add(methodType)
      } else {
        next.delete(methodType)
      }
      // Always keep card
      next.add('card')
      return next
    })
  }

  const handleSave = async () => {
    setSaving(true)
    setMethodsError(null)
    try {
      const res = await apiClient.put<PaymentMethodsResponse>(
        '/payments/online-payments/payment-methods',
        { enabled_methods: Array.from(draftEnabled) },
      )
      setMethods(res.data?.payment_methods ?? [])
      setEditing(false)
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      const detail = axiosErr.response?.data?.detail
      setMethodsError(detail ?? 'Failed to update payment methods.')
    } finally {
      setSaving(false)
    }
  }

  if (loadingMethods) {
    return (
      <div className="flex items-center gap-2 mt-3">
        <Spinner size="sm" label="Loading payment methods…" />
        <span className="text-sm text-gray-500">Loading payment methods…</span>
      </div>
    )
  }

  return (
    <div className="mt-3">
      {methodsError && (
        <AlertBanner variant="error" onDismiss={() => setMethodsError(null)} className="mb-3">
          {methodsError}
        </AlertBanner>
      )}

      {!editing ? (
        /* ── Summary view: "Payment Methods: Credit Card, Apple Pay ✏️" ── */
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-gray-600">Payment Methods:</span>
          <span className="text-sm font-medium text-gray-900">
            {enabledMethodNames.length > 0 ? enabledMethodNames.join(', ') : 'Credit & Debit Cards'}
          </span>
          <button
            type="button"
            onClick={handleEditClick}
            className="inline-flex items-center text-gray-400 hover:text-indigo-600 transition-colors p-0.5 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
            aria-label="Edit payment methods"
          >
            <PencilIcon className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : (
        /* ── Edit view: inline checkbox grid ── */
        <div>
          <div className="mb-2">
            <span className="text-sm font-medium text-gray-900">Payment Methods:</span>
            <p className="text-xs text-gray-500 mt-0.5">Choose which payment methods to accept:</p>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 mb-3">
            {(methods ?? []).map((method) => {
              const isCard = method?.type === 'card'
              const isChecked = isCard || draftEnabled.has(method?.type ?? '')
              return (
                <label
                  key={method?.type ?? ''}
                  className={`
                    flex items-center gap-2 rounded-md border px-3 py-2 text-sm cursor-pointer transition-all
                    ${isChecked ? 'border-indigo-300 bg-indigo-50/50' : 'border-gray-200 bg-white hover:border-gray-300'}
                    ${isCard ? 'opacity-75 cursor-not-allowed' : ''}
                  `}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    disabled={isCard}
                    onChange={(e) => handleCheckboxChange(method?.type ?? '', e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-50"
                  />
                  <SmallPaymentMethodIcon type={method?.type ?? ''} />
                  <span className="text-gray-900 truncate">{method?.name ?? ''}</span>
                </label>
              )
            })}
          </div>

          <div className="flex items-center gap-2">
            <Button size="sm" onClick={handleSave} loading={saving}>
              Save
            </Button>
            <Button size="sm" variant="secondary" onClick={handleCancel} disabled={saving}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Component ── */

/* ── Payout Settings Section ── */

interface PayoutInfo {
  payouts_enabled: boolean
  bank_name: string
  bank_last4: string
  bank_currency: string
  payout_schedule: string
  payout_interval: string
  payout_delay_days: number
}

function PayoutSettingsSection() {
  const [payoutInfo, setPayoutInfo] = useState<PayoutInfo | null>(null)
  const [loadingPayout, setLoadingPayout] = useState(true)
  const [payoutError, setPayoutError] = useState<string | null>(null)
  const [redirecting, setRedirecting] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    const fetchPayoutInfo = async () => {
      try {
        const res = await apiClient.get<PayoutInfo>(
          '/payments/online-payments/payout-info',
          { signal: controller.signal },
        )
        setPayoutInfo({
          payouts_enabled: res.data?.payouts_enabled ?? false,
          bank_name: res.data?.bank_name ?? '',
          bank_last4: res.data?.bank_last4 ?? '',
          bank_currency: res.data?.bank_currency ?? '',
          payout_schedule: res.data?.payout_schedule ?? '',
          payout_interval: res.data?.payout_interval ?? '',
          payout_delay_days: res.data?.payout_delay_days ?? 0,
        })
        setPayoutError(null)
      } catch (err) {
        if (!controller.signal.aborted) {
          setPayoutError('Failed to load payout settings.')
        }
      } finally {
        setLoadingPayout(false)
      }
    }
    fetchPayoutInfo()
    return () => controller.abort()
  }, [])

  const handleManagePayouts = async () => {
    setRedirecting(true)
    setPayoutError(null)
    try {
      const res = await apiClient.post<{ url: string }>(
        '/payments/online-payments/manage-payouts',
      )
      const url = res.data?.url ?? ''
      if (url) {
        window.location.href = url
      } else {
        setPayoutError('No management URL returned. Please try again.')
        setRedirecting(false)
      }
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      const detail = axiosErr.response?.data?.detail
      setPayoutError(detail ?? 'Failed to open payout management. Please try again.')
      setRedirecting(false)
    }
  }

  if (loadingPayout) {
    return (
      <div className="mt-4 pt-3 border-t border-gray-100">
        <div className="flex items-center gap-2">
          <Spinner size="sm" label="Loading payout settings…" />
          <span className="text-sm text-gray-500">Loading payout settings…</span>
        </div>
      </div>
    )
  }

  const hasBankAccount = (payoutInfo?.bank_last4 ?? '') !== ''

  return (
    <div className="mt-4 pt-3 border-t border-gray-100">
      <h4 className="text-sm font-semibold text-gray-900 mb-2">Payout Settings</h4>

      {payoutError && (
        <AlertBanner variant="error" onDismiss={() => setPayoutError(null)} className="mb-3">
          {payoutError}
        </AlertBanner>
      )}

      {hasBankAccount ? (
        <div className="space-y-1 mb-3">
          <p className="text-sm text-gray-600">
            Bank Account:{' '}
            <span className="font-medium text-gray-900">
              ····{payoutInfo?.bank_last4 ?? ''}
              {(payoutInfo?.bank_name ?? '') !== '' && ` (${payoutInfo?.bank_name ?? ''}`}
              {(payoutInfo?.bank_currency ?? '') !== '' && `, ${payoutInfo?.bank_currency ?? ''}`}
              {(payoutInfo?.bank_name ?? '') !== '' && ')'}
            </span>
          </p>
          {(payoutInfo?.payout_schedule ?? '') !== '' && (
            <p className="text-sm text-gray-600">
              Payout Schedule:{' '}
              <span className="font-medium text-gray-900">{payoutInfo?.payout_schedule ?? ''}</span>
            </p>
          )}
          <p className="text-sm text-gray-600">
            Status:{' '}
            {payoutInfo?.payouts_enabled ? (
              <span className="font-medium text-green-600">✓ Payouts enabled</span>
            ) : (
              <span className="font-medium text-amber-600">Payouts not enabled</span>
            )}
          </p>
        </div>
      ) : (
        <div className="mb-3">
          <p className="text-sm text-gray-600">No bank account configured for payouts.</p>
          <p className="text-sm text-gray-500">Set up your bank account to receive payments.</p>
        </div>
      )}

      <Button
        size="sm"
        variant="secondary"
        onClick={handleManagePayouts}
        loading={redirecting}
      >
        {hasBankAccount ? 'Manage Payouts →' : 'Set Up Payouts →'}
      </Button>
    </div>
  )
}

/* ── Main Component ── */

export default function OnlinePaymentsSettings() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState<OnlinePaymentsStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showDisconnectDialog, setShowDisconnectDialog] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const [callbackProcessing, setCallbackProcessing] = useState(false)

  /* ── Fetch status ── */

  const fetchStatus = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await apiClient.get<OnlinePaymentsStatus>(
        '/payments/online-payments/status',
        { signal },
      )
      setStatus({
        is_connected: res.data?.is_connected ?? false,
        account_id_last4: res.data?.account_id_last4 ?? '',
        account_name: res.data?.account_name ?? '',
        connect_client_id_configured: res.data?.connect_client_id_configured ?? false,
        application_fee_percent: res.data?.application_fee_percent ?? null,
      })
      setError(null)
    } catch (err) {
      if (!(err as { name?: string })?.name?.includes('Cancel')) {
        setError('Failed to load online payments status.')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  /* ── Initial load + OAuth callback detection ── */

  useEffect(() => {
    const controller = new AbortController()

    const code = searchParams.get('code')
    const state = searchParams.get('state')

    if (code && state) {
      // OAuth callback — exchange code for account connection
      setCallbackProcessing(true)
      const handleCallback = async () => {
        try {
          await apiClient.get<{ stripe_account_id: string; org_id: string }>(
            '/billing/stripe/connect/callback',
            { params: { code, state }, signal: controller.signal },
          )
          // Clear query params without full page reload
          setSearchParams({}, { replace: true })
          // Re-fetch status to show "Connected"
          await fetchStatus(controller.signal)
        } catch (err) {
          if (!(err as { name?: string })?.name?.includes('Cancel')) {
            const axiosErr = err as { response?: { data?: { detail?: string } } }
            const detail = axiosErr.response?.data?.detail
            setError(detail ?? 'Failed to connect Stripe account. Please try again.')
            // Clear query params even on error
            setSearchParams({}, { replace: true })
          }
        } finally {
          setCallbackProcessing(false)
          setLoading(false)
        }
      }
      handleCallback()
    } else {
      fetchStatus(controller.signal)
    }

    return () => controller.abort()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  /* ── OAuth connect flow ── */

  const handleConnect = async () => {
    setConnecting(true)
    setError(null)
    try {
      const res = await apiClient.post<{ authorize_url: string }>(
        '/billing/stripe/connect',
      )
      const authorizeUrl = res.data?.authorize_url
      if (authorizeUrl) {
        window.location.href = authorizeUrl
      } else {
        setError('No authorization URL returned. Please try again.')
      }
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      const detail = axiosErr.response?.data?.detail
      setError(detail ?? 'Failed to initiate Stripe connection. Please try again.')
    } finally {
      setConnecting(false)
    }
  }

  /* ── Disconnect flow ── */

  const handleDisconnect = async () => {
    setDisconnecting(true)
    setError(null)
    setShowDisconnectDialog(false)
    try {
      await apiClient.post<{ message: string; previous_account_last4: string }>(
        '/payments/online-payments/disconnect',
      )
      // Re-fetch status to show "Not Connected"
      await fetchStatus()
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      const detail = axiosErr.response?.data?.detail
      setError(detail ?? 'Failed to disconnect Stripe account. Please try again.')
    } finally {
      setDisconnecting(false)
    }
  }

  /* ── Render ── */

  if (loading || callbackProcessing) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner size="lg" label={callbackProcessing ? 'Connecting Stripe account…' : 'Loading online payments settings'} />
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Online Payments</h2>
        <p className="text-sm text-gray-600 mt-1">
          Accept online payments from customers via Stripe. Payments are deposited directly into your connected Stripe account.
        </p>
      </div>

      {error && (
        <AlertBanner variant="error" onDismiss={() => setError(null)}>
          {error}
        </AlertBanner>
      )}

      {/* Not configured by platform admin */}
      {!status?.connect_client_id_configured && (
        <div className="rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold text-gray-900">Stripe</h3>
            <Badge variant="neutral">Unavailable</Badge>
          </div>
          <AlertBanner variant="info">
            Online payments are not available. Contact your platform administrator to configure Stripe Connect.
          </AlertBanner>
        </div>
      )}

      {/* Configured but not connected */}
      {status?.connect_client_id_configured && !status?.is_connected && (
        <div className="rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold text-gray-900">Stripe</h3>
            <Badge variant="neutral">Not Connected</Badge>
          </div>
          <p className="text-sm text-gray-600 mb-4">
            Connect your Stripe account to start accepting online payments on invoices. Customers will be able to pay via a secure Stripe checkout page.
          </p>
          <Button onClick={handleConnect} loading={connecting}>
            Set Up Now
          </Button>
        </div>
      )}

      {/* Connected */}
      {status?.connect_client_id_configured && status?.is_connected && (
        <div className="rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold text-gray-900">Stripe</h3>
            <Badge variant="success">Connected</Badge>
          </div>

          <div className="space-y-1 mb-3">
            <p className="text-sm text-gray-600">
              Integration Status: <span className="font-medium text-green-600">Active</span>
            </p>
            {(status?.account_name ?? '') !== '' && (
              <p className="text-sm text-gray-600">
                Account Name: <span className="font-semibold text-gray-900">{status?.account_name ?? ''}</span>
              </p>
            )}
            <p className="text-sm text-gray-500">
              Account: <span className="font-medium text-gray-700">····{status?.account_id_last4 ?? ''}</span>
            </p>
            {(status?.application_fee_percent ?? null) !== null && (
              <p className="text-sm text-gray-500">
                Platform fee: <span className="font-medium text-gray-700">{status?.application_fee_percent ?? 0}%</span> per transaction
              </p>
            )}
          </div>

          {/* Inline payment methods section */}
          <PaymentMethodsSection />

          {/* Payout settings section */}
          <PayoutSettingsSection />

          <div className="mt-4 pt-3 border-t border-gray-100">
            <Button
              variant="danger"
              size="sm"
              onClick={() => setShowDisconnectDialog(true)}
              loading={disconnecting}
            >
              Disconnect
            </Button>
          </div>
        </div>
      )}

      {/* Disconnect confirmation dialog */}
      <Modal
        open={showDisconnectDialog}
        title="Disconnect Stripe?"
        onClose={() => setShowDisconnectDialog(false)}
      >
        <p className="text-sm text-gray-600 mb-2">
          Are you sure you want to disconnect your Stripe account?
        </p>
        <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-md p-3 mb-4">
          Any existing payment links sent to customers will stop working. You will need to reconnect to accept online payments again.
        </p>
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={() => setShowDisconnectDialog(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={handleDisconnect} loading={disconnecting}>
            Disconnect
          </Button>
        </div>
      </Modal>
    </div>
  )
}