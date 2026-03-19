import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { ToastContainer, useToast } from '@/components/ui/Toast'

/* ── Types ── */

export interface PaymentMethod {
  id: string
  stripe_payment_method_id: string
  brand: string
  last4: string
  exp_month: number
  exp_year: number
  is_default: boolean
  is_verified: boolean
  is_expiring_soon: boolean
}

interface PaymentMethodListResponse {
  payment_methods: PaymentMethod[]
}

/* ── Helpers ── */

const brandLabels: Record<string, string> = {
  visa: 'Visa',
  mastercard: 'Mastercard',
  amex: 'American Express',
  discover: 'Discover',
  diners: 'Diners Club',
  jcb: 'JCB',
  unionpay: 'UnionPay',
}

function formatBrand(brand: string): string {
  return brandLabels[brand.toLowerCase()] ?? brand.charAt(0).toUpperCase() + brand.slice(1)
}

function formatExpiry(month: number, year: number): string {
  return `${String(month).padStart(2, '0')}/${year}`
}

/* ── Card Row ── */

function PaymentMethodCard({
  method,
  isSoleCard,
  onSetDefault,
  onRemove,
  settingDefault,
  removingId,
}: {
  method: PaymentMethod
  isSoleCard: boolean
  onSetDefault: (id: string) => void
  onRemove: (id: string) => void
  settingDefault: string | null
  removingId: string | null
}) {
  const isSettingThis = settingDefault === method.id
  const isRemovingThis = removingId === method.id

  return (
    <div
      className={`flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg border p-4 ${
        method.is_default ? 'border-blue-300 bg-blue-50' : 'border-gray-200 bg-white'
      }`}
    >
      {/* Card info */}
      <div className="flex items-center gap-3 min-w-0">
        {/* Brand icon placeholder */}
        <div className="flex h-10 w-14 items-center justify-center rounded bg-gray-100 text-xs font-bold text-gray-600 shrink-0">
          {formatBrand(method.brand).slice(0, 4)}
        </div>

        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-900">
              {formatBrand(method.brand)} •••• {method.last4}
            </span>
            {method.is_default && <Badge variant="info">Default</Badge>}
            {method.is_verified ? (
              <Badge variant="success">Verified</Badge>
            ) : (
              <Badge variant="warning">Unverified</Badge>
            )}
            {method.is_expiring_soon && (
              <span
                className="inline-flex items-center gap-1 text-xs font-medium text-amber-600"
                title="This card is expiring soon"
              >
                <span aria-hidden="true">⚠</span>
                Expiring soon
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500 mt-0.5">
            Expires {formatExpiry(method.exp_month, method.exp_year)}
          </p>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 shrink-0">
        {!method.is_default && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onSetDefault(method.id)}
            loading={isSettingThis}
            disabled={!!settingDefault || !!removingId}
          >
            Set as default
          </Button>
        )}

        <div className="relative group">
          <Button
            variant="danger"
            size="sm"
            onClick={() => onRemove(method.id)}
            loading={isRemovingThis}
            disabled={isSoleCard || !!settingDefault || !!removingId}
          >
            Remove
          </Button>
          {isSoleCard && (
            <div
              className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block
                w-64 rounded-md bg-gray-900 px-3 py-2 text-xs text-white shadow-lg z-10"
              role="tooltip"
            >
              You must have at least one valid payment method. Please add a new card before removing this one.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ── Main Component ── */

export interface PaymentMethodManagerProps {
  onAddCard?: () => void
  showAddForm?: boolean
}

export function PaymentMethodManager({ onAddCard, showAddForm }: PaymentMethodManagerProps) {
  const [methods, setMethods] = useState<PaymentMethod[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [settingDefault, setSettingDefault] = useState<string | null>(null)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchMethods = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<PaymentMethodListResponse>('/billing/payment-methods')
      setMethods(res.data.payment_methods)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr?.response?.data?.detail || 'Failed to load payment methods. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchMethods()
  }, [fetchMethods])

  /* ── Set default ── */
  const handleSetDefault = async (id: string) => {
    setSettingDefault(id)
    try {
      await apiClient.post(`/billing/payment-methods/${id}/set-default`)
      setMethods((prev) =>
        prev.map((m) => ({ ...m, is_default: m.id === id }))
      )
      addToast('success', 'Default payment method updated')
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      addToast('error', axiosErr?.response?.data?.detail || 'Failed to update default payment method. Please try again.')
    } finally {
      setSettingDefault(null)
    }
  }

  /* ── Remove ── */
  const handleRemoveClick = (id: string) => {
    setConfirmRemove(id)
  }

  const handleConfirmRemove = async () => {
    if (!confirmRemove) return
    const id = confirmRemove
    setConfirmRemove(null)
    setRemovingId(id)
    try {
      await apiClient.delete(`/billing/payment-methods/${id}`)
      setMethods((prev) => prev.filter((m) => m.id !== id))
      addToast('success', 'Payment method removed')
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      addToast('error', axiosErr?.response?.data?.detail || 'Failed to remove payment method. Please try again.')
    } finally {
      setRemovingId(null)
    }
  }

  /* ── Render ── */

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner label="Loading payment methods" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-3">
        <AlertBanner variant="error" title="Error loading payment methods">
          {error}
        </AlertBanner>
        <Button variant="secondary" size="sm" onClick={fetchMethods}>
          Retry
        </Button>
      </div>
    )
  }

  const isSoleCard = methods.length === 1

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Payment Methods</h2>
        {onAddCard && (
          <Button size="sm" onClick={onAddCard} disabled={showAddForm}>
            Add card
          </Button>
        )}
      </div>

      {methods.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center">
          <p className="text-gray-500">No payment methods on file.</p>
          <p className="text-sm text-gray-400 mt-1">Add a card to get started.</p>
          {onAddCard && (
            <Button size="sm" className="mt-4" onClick={onAddCard}>
              Add your first card
            </Button>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {methods.map((method) => (
            <PaymentMethodCard
              key={method.id}
              method={method}
              isSoleCard={isSoleCard}
              onSetDefault={handleSetDefault}
              onRemove={handleRemoveClick}
              settingDefault={settingDefault}
              removingId={removingId}
            />
          ))}
        </div>
      )}

      {/* Confirmation dialog for removal */}
      <ConfirmDialog
        open={!!confirmRemove}
        title="Remove payment method"
        message="Are you sure you want to remove this payment method? This action cannot be undone."
        confirmLabel="Remove"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={handleConfirmRemove}
        onCancel={() => setConfirmRemove(null)}
      />

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
