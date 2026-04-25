/**
 * Service/WOF Reminder Configuration Widget
 *
 * Displays and allows editing of WOF and service reminder thresholds
 * in days. Validates 1–365 range on client side before submit.
 * Defaults to 30 days if no config exists.
 *
 * Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
 */

import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { WidgetCard } from './WidgetCard'
import type { ReminderConfig } from './types'

interface ReminderConfigWidgetProps {
  data: ReminderConfig | undefined | null
  isLoading: boolean
  error: string | null
}

function CogIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
}

/** Validate that a value is an integer between 1 and 365 inclusive */
export function isValidThreshold(value: number): boolean {
  return Number.isInteger(value) && value >= 1 && value <= 365
}

export function ReminderConfigWidget({ data, isLoading, error }: ReminderConfigWidgetProps) {
  const [wofDays, setWofDays] = useState<number>(30)
  const [serviceDays, setServiceDays] = useState<number>(30)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)

  // Sync form values from props on mount / when data changes
  useEffect(() => {
    setWofDays(data?.wof_days ?? 30)
    setServiceDays(data?.service_days ?? 30)
  }, [data?.wof_days, data?.service_days])

  const wofValid = isValidThreshold(wofDays)
  const serviceValid = isValidThreshold(serviceDays)
  const canSave = wofValid && serviceValid && !saving

  async function handleSave() {
    if (!canSave) return

    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)

    try {
      await apiClient.put('/dashboard/reminder-config', {
        wof_days: wofDays,
        service_days: serviceDays,
      })
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch {
      setSaveError('Failed to save configuration.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <WidgetCard
      title="Reminder Configuration"
      icon={CogIcon}
      isLoading={isLoading}
      error={error}
    >
      <div className="space-y-4">
        {/* WOF threshold */}
        <div>
          <label htmlFor="wof-days" className="block text-xs font-medium text-gray-700 mb-1">
            WOF Reminder Threshold (days)
          </label>
          <input
            id="wof-days"
            type="number"
            min={1}
            max={365}
            value={wofDays}
            onChange={(e) => setWofDays(parseInt(e.target.value, 10) || 0)}
            className={`block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-1 ${
              wofValid
                ? 'border-gray-300 focus:border-blue-500 focus:ring-blue-500'
                : 'border-red-300 focus:border-red-500 focus:ring-red-500'
            }`}
          />
          {!wofValid && (
            <p className="mt-1 text-xs text-red-600">Must be between 1 and 365</p>
          )}
        </div>

        {/* Service threshold */}
        <div>
          <label htmlFor="service-days" className="block text-xs font-medium text-gray-700 mb-1">
            Service Reminder Threshold (days)
          </label>
          <input
            id="service-days"
            type="number"
            min={1}
            max={365}
            value={serviceDays}
            onChange={(e) => setServiceDays(parseInt(e.target.value, 10) || 0)}
            className={`block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-1 ${
              serviceValid
                ? 'border-gray-300 focus:border-blue-500 focus:ring-blue-500'
                : 'border-red-300 focus:border-red-500 focus:ring-red-500'
            }`}
          />
          {!serviceValid && (
            <p className="mt-1 text-xs text-red-600">Must be between 1 and 365</p>
          )}
        </div>

        {/* Save button + feedback */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            disabled={!canSave}
            onClick={handleSave}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          {saveSuccess && (
            <span className="text-xs font-medium text-green-600">Saved successfully</span>
          )}
          {saveError && (
            <span className="text-xs font-medium text-red-600">{saveError}</span>
          )}
        </div>
      </div>
    </WidgetCard>
  )
}
