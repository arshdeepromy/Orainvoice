import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { MobileForm, MobileInput, MobileSelect, MobileButton } from '@/components/ui'
import { CustomerPicker } from '@/components/common/CustomerPicker'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Service type options                                                */
/* ------------------------------------------------------------------ */

const SERVICE_TYPES = [
  { value: 'consultation', label: 'Consultation' },
  { value: 'service', label: 'Service' },
  { value: 'repair', label: 'Repair' },
  { value: 'installation', label: 'Installation' },
  { value: 'inspection', label: 'Inspection' },
  { value: 'other', label: 'Other' },
]

const DURATION_OPTIONS = [
  { value: '15', label: '15 minutes' },
  { value: '30', label: '30 minutes' },
  { value: '45', label: '45 minutes' },
  { value: '60', label: '1 hour' },
  { value: '90', label: '1.5 hours' },
  { value: '120', label: '2 hours' },
  { value: '180', label: '3 hours' },
  { value: '240', label: '4 hours' },
]

/**
 * Booking create screen — form with customer selection, date, time,
 * duration, service type.
 *
 * Requirements: 21.3
 */
export default function BookingCreateScreen() {
  const navigate = useNavigate()

  const [customerId, setCustomerId] = useState('')
  const [customerName, setCustomerName] = useState('')
  const [date, setDate] = useState(new Date().toISOString().split('T')[0])
  const [startTime, setStartTime] = useState('09:00')
  const [duration, setDuration] = useState('60')
  const [serviceType, setServiceType] = useState('')
  const [notes, setNotes] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const validate = useCallback((): boolean => {
    const newErrors: Record<string, string> = {}
    if (!customerId) newErrors.customer = 'Select a customer'
    if (!date) newErrors.date = 'Date is required'
    if (!startTime) newErrors.startTime = 'Start time is required'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }, [customerId, date, startTime])

  const handleSubmit = useCallback(async () => {
    if (!validate()) return

    setIsSubmitting(true)
    try {
      await apiClient.post('/api/v1/bookings', {
        customer_id: customerId,
        date,
        start_time: startTime,
        duration_minutes: parseInt(duration, 10),
        service_type: serviceType || null,
        notes: notes.trim() || null,
      })
      navigate('/bookings', { replace: true })
    } catch {
      setErrors({ submit: 'Failed to create booking' })
    } finally {
      setIsSubmitting(false)
    }
  }, [validate, customerId, date, startTime, duration, serviceType, notes, navigate])

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
        New Booking
      </h1>

      <MobileForm onSubmit={handleSubmit}>
        <CustomerPicker
          value={customerId}
          displayValue={customerName}
          onChange={(id, name) => {
            setCustomerId(id)
            setCustomerName(name)
            setErrors((prev) => ({ ...prev, customer: '' }))
          }}
          error={errors.customer}
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

        <MobileInput
          label="Start Time"
          type="time"
          value={startTime}
          onChange={(e) => {
            setStartTime(e.target.value)
            setErrors((prev) => ({ ...prev, startTime: '' }))
          }}
          error={errors.startTime}
          required
        />

        <MobileSelect
          label="Duration"
          value={duration}
          onChange={(e) => setDuration(e.target.value)}
          options={DURATION_OPTIONS}
        />

        <MobileSelect
          label="Service Type"
          value={serviceType}
          onChange={(e) => setServiceType(e.target.value)}
          options={SERVICE_TYPES}
          placeholder="Select service type"
        />

        <MobileInput
          label="Notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Additional notes…"
        />

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
          Create Booking
        </MobileButton>
      </MobileForm>
    </div>
  )
}
