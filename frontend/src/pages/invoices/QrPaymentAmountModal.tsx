import { useState, useEffect, useRef, useCallback, useMemo } from 'react'

/* ── Types ── */

export interface QrPaymentAmountModalProps {
  open: boolean
  onClose: () => void
  invoice: {
    id: string
    balance_due: number | string
    invoice_number: string | null
  }
  onContinue: (amount: number | null) => Promise<void>
  loading?: boolean
}

type Mode = 'full' | 'partial'

/* ── Constants ── */

const STRIPE_MIN_NZD = 0.5

/* ── Helpers ── */

/**
 * Coerce an unknown balance value (number or string) to a finite number.
 * Returns 0 when the value is null/undefined/NaN.
 */
function toBalance(raw: number | string | null | undefined): number {
  if (raw == null) return 0
  const n = typeof raw === 'number' ? raw : Number(raw)
  return Number.isFinite(n) ? n : 0
}

/**
 * Format a numeric value as $X.XX. Defensive against null/NaN.
 */
function formatMoney(value: number | string | null | undefined): string {
  return `$${toBalance(value).toFixed(2)}`
}

/**
 * Sanitise a typed amount string:
 * - strip non-digit/non-decimal characters
 * - keep at most one decimal separator
 * - truncate (do not round) to two decimal places
 */
function sanitiseAmountInput(raw: string): string {
  // Strip everything that is not a digit or '.'
  let cleaned = raw.replace(/[^\d.]/g, '')

  // Keep only the first decimal separator
  const firstDot = cleaned.indexOf('.')
  if (firstDot !== -1) {
    cleaned =
      cleaned.slice(0, firstDot + 1) +
      cleaned.slice(firstDot + 1).replace(/\./g, '')
  }

  // Truncate fractional part to 2dp (silently)
  const dotIdx = cleaned.indexOf('.')
  if (dotIdx !== -1 && cleaned.length - dotIdx - 1 > 2) {
    cleaned = cleaned.slice(0, dotIdx + 3)
  }

  return cleaned
}

/* ── Component ── */

export function QrPaymentAmountModal({
  open,
  onClose,
  invoice,
  onContinue,
  loading = false,
}: QrPaymentAmountModalProps) {
  const balanceDue = toBalance(invoice?.balance_due)
  const formattedBalance = useMemo(() => balanceDue.toFixed(2), [balanceDue])

  const [mode, setMode] = useState<Mode>('full')
  const [amount, setAmount] = useState<string>(formattedBalance)
  const amountInputRef = useRef<HTMLInputElement | null>(null)

  /* Reset internal state every time the modal is (re)opened. */
  useEffect(() => {
    if (open) {
      setMode('full')
      setAmount(balanceDue.toFixed(2))
    }
  }, [open, balanceDue])

  /* When user switches to Partial, focus the amount input. */
  useEffect(() => {
    if (open && mode === 'partial') {
      // Defer one tick so the input has been rendered
      const id = window.setTimeout(() => {
        amountInputRef.current?.focus()
        amountInputRef.current?.select()
      }, 0)
      return () => window.clearTimeout(id)
    }
    return undefined
  }, [open, mode])

  /* Close on Escape. */
  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !loading) {
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, loading, onClose])

  /* Validation: returns an error string when invalid in Partial mode, else null. */
  const validationError = useMemo<string | null>(() => {
    if (mode !== 'partial') return null
    const trimmed = amount.trim()
    if (trimmed === '' || trimmed === '.') return 'Enter an amount'
    const parsed = Number(trimmed)
    if (!Number.isFinite(parsed) || parsed === 0) return 'Enter an amount'
    if (parsed < STRIPE_MIN_NZD) return 'Amount must be at least $0.50'
    // Compare with a 1¢ tolerance for floating-point safety
    if (parsed - balanceDue > 0.005) {
      return `Amount cannot exceed the outstanding balance of ${formatMoney(balanceDue)}`
    }
    return null
  }, [mode, amount, balanceDue])

  const continueDisabled = loading || (mode === 'partial' && validationError !== null)

  const handleAmountChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const cursor = e.target.selectionStart
      const sanitised = sanitiseAmountInput(e.target.value)
      setAmount(sanitised)
      // Best-effort cursor preservation when characters were stripped
      if (cursor !== null && amountInputRef.current) {
        const delta = e.target.value.length - sanitised.length
        const nextPos = Math.max(0, cursor - delta)
        // Defer to after React updates the value
        window.requestAnimationFrame(() => {
          if (amountInputRef.current) {
            try {
              amountInputRef.current.setSelectionRange(nextPos, nextPos)
            } catch {
              /* ignore — some inputs (type=number) reject setSelectionRange */
            }
          }
        })
      }
    },
    [],
  )

  const handleContinue = useCallback(async () => {
    if (continueDisabled) return
    if (mode === 'full') {
      await onContinue(null)
      return
    }
    const parsed = parseFloat(amount)
    if (!Number.isFinite(parsed)) return
    await onContinue(parsed)
  }, [continueDisabled, mode, amount, onContinue])

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      // Only close when clicking the backdrop itself, not bubbled from children
      if (e.target === e.currentTarget && !loading) {
        onClose()
      }
    },
    [loading, onClose],
  )

  if (!open) return null

  const headerTitle = invoice?.invoice_number
    ? `QR Payment for ${invoice.invoice_number}`
    : 'QR Payment'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="qr-amount-modal-title"
      onClick={handleBackdropClick}
    >
      <div className="flex w-full max-w-md flex-col rounded-xl bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-gray-200 px-6 py-4">
          <h2
            id="qr-amount-modal-title"
            className="text-lg font-semibold text-gray-900"
          >
            {headerTitle}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            aria-label="Close"
            className="ml-4 inline-flex h-11 w-11 items-center justify-center rounded-md text-gray-400 hover:bg-gray-100 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
          >
            <svg
              className="h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          <div role="radiogroup" aria-label="Payment amount" className="space-y-3">
            {/* Full payment radio */}
            <label
              className={`flex min-h-[44px] cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 transition-colors ${
                mode === 'full'
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-gray-200 bg-white hover:bg-gray-50'
              }`}
            >
              <input
                type="radio"
                name="qr-payment-mode"
                value="full"
                checked={mode === 'full'}
                onChange={() => setMode('full')}
                disabled={loading}
                className="h-5 w-5 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="flex-1 text-sm font-medium text-gray-900">
                Full payment ({formatMoney(balanceDue)})
              </span>
            </label>

            {/* Partial payment radio */}
            <label
              className={`flex min-h-[44px] cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 transition-colors ${
                mode === 'partial'
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-gray-200 bg-white hover:bg-gray-50'
              }`}
            >
              <input
                type="radio"
                name="qr-payment-mode"
                value="partial"
                checked={mode === 'partial'}
                onChange={() => setMode('partial')}
                disabled={loading}
                className="h-5 w-5 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="flex-1 text-sm font-medium text-gray-900">
                Partial payment
              </span>
            </label>

            {/* Amount input — only visible in Partial mode */}
            {mode === 'partial' && (
              <div className="pl-1 pt-1">
                <label
                  htmlFor="qr-partial-amount"
                  className="block text-sm font-medium text-gray-700"
                >
                  Amount (NZD)
                </label>
                <div className="relative mt-1">
                  <span
                    className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-gray-500"
                    aria-hidden="true"
                  >
                    $
                  </span>
                  <input
                    ref={amountInputRef}
                    id="qr-partial-amount"
                    type="text"
                    inputMode="decimal"
                    autoComplete="off"
                    value={amount}
                    onChange={handleAmountChange}
                    disabled={loading}
                    aria-invalid={validationError !== null}
                    aria-describedby={
                      validationError ? 'qr-partial-amount-error' : undefined
                    }
                    className={`block w-full min-h-[44px] rounded-md border pl-7 pr-3 py-2 text-base shadow-sm focus:outline-none focus:ring-2 disabled:bg-gray-50 disabled:opacity-60 ${
                      validationError
                        ? 'border-red-300 focus:border-red-500 focus:ring-red-500'
                        : 'border-gray-300 focus:border-indigo-500 focus:ring-indigo-500'
                    }`}
                    placeholder="0.00"
                  />
                </div>
                {validationError && (
                  <p
                    id="qr-partial-amount-error"
                    role="alert"
                    className="mt-1.5 text-sm text-red-600"
                  >
                    {validationError}
                  </p>
                )}
                <p className="mt-1.5 text-xs text-gray-500">
                  Outstanding balance: {formatMoney(balanceDue)}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 border-t border-gray-200 bg-gray-50 px-6 py-4 rounded-b-xl">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-gray-300 bg-white px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleContinue}
            disabled={continueDisabled}
            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading && (
              <svg
                className="h-4 w-4 animate-spin"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            )}
            Continue
          </button>
        </div>
      </div>
    </div>
  )
}

export default QrPaymentAmountModal
