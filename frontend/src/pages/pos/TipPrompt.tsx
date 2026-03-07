/**
 * Tip prompt component for POS transactions.
 * Shows preset percentage buttons (10%, 15%, 20%) and a custom amount option.
 * Displayed after payment amount entry when the Tipping module is enabled.
 *
 * Validates: Requirement 24.1 — Tipping prompt on POS
 */

import { useState } from 'react'

interface TipPromptProps {
  /** The transaction subtotal to calculate percentages from */
  subtotal: number
  /** Called when user confirms a tip amount (0 for no tip) */
  onConfirm: (tipAmount: number) => void
  /** Called when user skips tipping */
  onSkip: () => void
}

const PRESET_PERCENTAGES = [10, 15, 20]

export default function TipPrompt({ subtotal, onConfirm, onSkip }: TipPromptProps) {
  const [selectedPreset, setSelectedPreset] = useState<number | null>(null)
  const [customAmount, setCustomAmount] = useState<string>('')
  const [isCustom, setIsCustom] = useState(false)

  const tipAmount = isCustom
    ? parseFloat(customAmount) || 0
    : selectedPreset !== null
      ? Math.round(subtotal * (selectedPreset / 100) * 100) / 100
      : 0

  const handlePresetClick = (pct: number) => {
    setIsCustom(false)
    setSelectedPreset(pct)
  }

  const handleCustomClick = () => {
    setIsCustom(true)
    setSelectedPreset(null)
  }

  const handleConfirm = () => {
    onConfirm(tipAmount)
  }

  const hasSelection = tipAmount > 0

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      role="dialog"
      aria-label="Add a tip"
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-center">Add a Tip</h2>
        </div>

        <div className="px-6 py-6">
          {/* Subtotal display */}
          <div className="text-center mb-6">
            <p className="text-sm text-gray-500">Transaction Total</p>
            <p className="text-2xl font-bold text-gray-900" data-testid="tip-subtotal">
              ${subtotal.toFixed(2)}
            </p>
          </div>

          {/* Preset percentage buttons */}
          <div className="flex gap-3 mb-4" role="group" aria-label="Tip percentage presets">
            {PRESET_PERCENTAGES.map((pct) => {
              const amount = Math.round(subtotal * (pct / 100) * 100) / 100
              const isSelected = !isCustom && selectedPreset === pct
              return (
                <button
                  key={pct}
                  type="button"
                  onClick={() => handlePresetClick(pct)}
                  className={`flex-1 py-3 rounded-lg text-center border-2 transition-colors ${
                    isSelected
                      ? 'border-blue-600 bg-blue-50 text-blue-700'
                      : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300'
                  }`}
                  aria-pressed={isSelected}
                  data-testid={`tip-preset-${pct}`}
                >
                  <span className="block text-lg font-semibold">{pct}%</span>
                  <span className="block text-sm text-gray-500">${amount.toFixed(2)}</span>
                </button>
              )
            })}
          </div>

          {/* Custom amount */}
          <div className="mb-4">
            <button
              type="button"
              onClick={handleCustomClick}
              className={`w-full py-2 rounded-lg text-sm font-medium border-2 transition-colors ${
                isCustom
                  ? 'border-blue-600 bg-blue-50 text-blue-700'
                  : 'border-gray-200 text-gray-600 hover:border-gray-300'
              }`}
              data-testid="tip-custom-btn"
            >
              Custom Amount
            </button>
            {isCustom && (
              <div className="mt-3">
                <label htmlFor="custom-tip" className="sr-only">Custom tip amount</label>
                <input
                  id="custom-tip"
                  type="number"
                  min={0}
                  step={0.01}
                  value={customAmount}
                  onChange={(e) => setCustomAmount(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-lg text-center"
                  placeholder="0.00"
                  autoFocus
                  data-testid="tip-custom-input"
                />
              </div>
            )}
          </div>

          {/* Tip amount display */}
          {hasSelection && (
            <div className="text-center py-3 bg-green-50 rounded-lg mb-4">
              <p className="text-sm text-gray-600">Tip Amount</p>
              <p className="text-2xl font-bold text-green-600" data-testid="tip-amount">
                ${tipAmount.toFixed(2)}
              </p>
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="px-6 py-4 border-t border-gray-200 flex gap-3">
          <button
            onClick={onSkip}
            className="flex-1 py-2.5 rounded-md border border-gray-300 text-gray-700 font-medium hover:bg-gray-50"
            data-testid="tip-skip"
          >
            No Tip
          </button>
          <button
            onClick={handleConfirm}
            disabled={!hasSelection}
            className="flex-1 py-2.5 rounded-md bg-blue-600 text-white font-semibold hover:bg-blue-700 disabled:opacity-50"
            data-testid="tip-confirm"
          >
            Add Tip
          </button>
        </div>
      </div>
    </div>
  )
}
