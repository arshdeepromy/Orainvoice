/**
 * ExpiringPaymentWarningModal
 *
 * Dismissible modal that warns an org_admin when their payment method
 * is expiring within 30 days. Displays card brand, last 4 digits, and
 * expiry date. Offers navigation to billing settings or dismissal.
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
 */

import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import type { ExpiringMethod } from '@/hooks/usePaymentMethodEnforcement'

interface ExpiringPaymentWarningModalProps {
  open: boolean
  expiringMethod: ExpiringMethod | null
  onDismiss: () => void
}

export function ExpiringPaymentWarningModal({
  open,
  expiringMethod,
  onDismiss,
}: ExpiringPaymentWarningModalProps) {
  const navigate = useNavigate()

  if (!open) return null

  function handleUpdatePayment() {
    navigate('/settings?tab=billing')
    onDismiss()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="expiring-payment-title"
    >
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-2xl">
        <div className="mb-4 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-yellow-100">
            <svg
              className="h-6 w-6 text-yellow-600"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
              />
            </svg>
          </div>
          <h2
            id="expiring-payment-title"
            className="text-lg font-semibold text-gray-900"
          >
            Payment method expiring soon
          </h2>
          <p className="mt-2 text-sm text-gray-600">
            Your {expiringMethod?.brand ?? 'card'} card ending in{' '}
            {expiringMethod?.last4 ?? '****'} expires{' '}
            {expiringMethod?.exp_month ?? '--'}/{expiringMethod?.exp_year ?? '----'}.
            Please update your payment method to avoid service interruption.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <Button
            size="sm"
            className="w-full"
            onClick={handleUpdatePayment}
          >
            Update Payment Method
          </Button>
          <Button
            variant="secondary"
            size="sm"
            className="w-full"
            onClick={onDismiss}
          >
            Dismiss
          </Button>
        </div>
      </div>
    </div>
  )
}
