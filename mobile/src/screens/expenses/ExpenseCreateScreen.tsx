import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { MobileForm, MobileInput, MobileSelect, MobileButton } from '@/components/ui'
import { CameraCapture } from '@/components/common/CameraCapture'
import type { CameraPhoto } from '@/hooks/useCamera'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Category options                                                   */
/* ------------------------------------------------------------------ */

const EXPENSE_CATEGORIES = [
  { value: 'fuel', label: 'Fuel' },
  { value: 'materials', label: 'Materials' },
  { value: 'tools', label: 'Tools & Equipment' },
  { value: 'travel', label: 'Travel' },
  { value: 'meals', label: 'Meals & Entertainment' },
  { value: 'office', label: 'Office Supplies' },
  { value: 'vehicle', label: 'Vehicle Maintenance' },
  { value: 'other', label: 'Other' },
]

/**
 * Expense create screen — form with description, amount, category, date,
 * receipt photo (camera capture or gallery selection).
 *
 * Requirements: 20.2, 20.3, 20.4, 20.5
 */
export default function ExpenseCreateScreen() {
  const navigate = useNavigate()

  const [description, setDescription] = useState('')
  const [amount, setAmount] = useState('')
  const [category, setCategory] = useState('')
  const [date, setDate] = useState(new Date().toISOString().split('T')[0])
  const [receipt, setReceipt] = useState<CameraPhoto | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const validate = useCallback((): boolean => {
    const newErrors: Record<string, string> = {}
    if (!description.trim()) newErrors.description = 'Description is required'
    const parsed = parseFloat(amount)
    if (!amount || isNaN(parsed) || parsed <= 0) newErrors.amount = 'Enter a valid amount'
    if (!date) newErrors.date = 'Date is required'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }, [description, amount, date])

  const handleSubmit = useCallback(async () => {
    if (!validate()) return

    setIsSubmitting(true)
    try {
      const body: Record<string, unknown> = {
        description: description.trim(),
        amount: parseFloat(amount),
        category: category || null,
        date,
      }

      // If receipt photo captured, include as base64
      if (receipt) {
        body.receipt_data = receipt.dataUrl
      }

      await apiClient.post('/api/v2/expenses', body)
      navigate('/expenses', { replace: true })
    } catch {
      setErrors({ submit: 'Failed to create expense' })
    } finally {
      setIsSubmitting(false)
    }
  }, [validate, description, amount, category, date, receipt, navigate])

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back button */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
        aria-label="Back"
      >
        <svg
          className="h-5 w-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m15 18-6-6 6-6" />
        </svg>
        Back
      </button>

      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        New Expense
      </h1>

      <MobileForm onSubmit={handleSubmit}>
        <MobileInput
          label="Description"
          value={description}
          onChange={(e) => {
            setDescription(e.target.value)
            setErrors((prev) => ({ ...prev, description: '' }))
          }}
          error={errors.description}
          placeholder="What was the expense for?"
          required
        />

        <MobileInput
          label="Amount"
          type="number"
          step="0.01"
          min="0"
          value={amount}
          onChange={(e) => {
            setAmount(e.target.value)
            setErrors((prev) => ({ ...prev, amount: '' }))
          }}
          error={errors.amount}
          placeholder="0.00"
          required
        />

        <MobileSelect
          label="Category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          options={EXPENSE_CATEGORIES}
          placeholder="Select category"
        />

        <MobileInput
          label="Date"
          type="date"
          value={date}
          onChange={(e) => {
            setDate(e.target.value)
            setErrors((prev) => ({ ...prev, date: '' }))
          }}
          error={errors.date}
          required
        />

        {/* Receipt photo */}
        <CameraCapture
          label="Receipt Photo"
          onCapture={(photo) => setReceipt(photo)}
        />

        {receipt && (
          <div className="flex items-center gap-2">
            <img
              src={receipt.dataUrl}
              alt="Receipt"
              className="h-16 w-16 rounded-lg object-cover"
            />
            <MobileButton
              variant="ghost"
              size="sm"
              onClick={() => setReceipt(null)}
            >
              Remove
            </MobileButton>
          </div>
        )}

        {errors.submit && (
          <p className="text-sm text-red-600 dark:text-red-400" role="alert">
            {errors.submit}
          </p>
        )}

        <MobileButton
          variant="primary"
          fullWidth
          type="submit"
          isLoading={isSubmitting}
        >
          Create Expense
        </MobileButton>
      </MobileForm>
    </div>
  )
}
