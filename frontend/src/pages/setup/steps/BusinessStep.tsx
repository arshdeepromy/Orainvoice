import React, { useMemo } from 'react'
import { Input } from '@/components/ui/Input'
import type { WizardData } from '../types'

interface BusinessStepProps {
  data: WizardData
  onChange: (updates: Partial<WizardData>) => void
  errors: Record<string, string>
}

export function BusinessStep({ data, onChange, errors }: BusinessStepProps) {
  const taxValidation = useMemo(() => {
    if (!data.taxNumber || !data.taxNumberRegex) return ''
    try {
      const regex = new RegExp(data.taxNumberRegex)
      if (!regex.test(data.taxNumber)) {
        return `Invalid ${data.taxNumberLabel} format`
      }
    } catch {
      // Invalid regex pattern — skip validation
    }
    return ''
  }, [data.taxNumber, data.taxNumberRegex, data.taxNumberLabel])

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-900">Business Details</h2>
      <p className="text-sm text-gray-500">
        Tell us about your business. Only the business name is required.
      </p>

      <Input
        label="Business name *"
        value={data.businessName}
        onChange={(e) => onChange({ businessName: e.target.value })}
        placeholder="e.g. Smith's Workshop Ltd"
        error={errors.businessName}
      />

      <Input
        label="Trading name"
        value={data.tradingName}
        onChange={(e) => onChange({ tradingName: e.target.value })}
        placeholder="e.g. Smith's Auto"
        helperText="The name your customers know you by (if different)"
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input
          label="Registration number"
          value={data.registrationNumber}
          onChange={(e) => onChange({ registrationNumber: e.target.value })}
          placeholder="Company registration #"
        />

        <Input
          label={data.taxNumberLabel || 'Tax number'}
          value={data.taxNumber}
          onChange={(e) => onChange({ taxNumber: e.target.value })}
          placeholder={`Enter your ${data.taxNumberLabel || 'tax number'}`}
          error={taxValidation || errors.taxNumber}
          helperText={
            data.countryCode === 'NZ'
              ? '8 or 9 digit IRD number'
              : data.countryCode === 'AU'
                ? '11 digit ABN'
                : data.countryCode === 'GB'
                  ? 'Format: GB123456789'
                  : undefined
          }
        />
      </div>

      <Input
        label="Phone"
        type="tel"
        value={data.phone}
        onChange={(e) => onChange({ phone: e.target.value })}
        placeholder="+64 9 123 4567"
        error={errors.phone}
      />

      <div className="flex flex-col gap-1">
        <label htmlFor="business-address" className="text-sm font-medium text-gray-700">
          Address
        </label>
        <textarea
          id="business-address"
          value={data.address}
          onChange={(e) => onChange({ address: e.target.value })}
          placeholder="123 Main Street, City, Region"
          rows={2}
          className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
            placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2
            focus-visible:ring-blue-500 focus-visible:border-blue-500"
        />
      </div>

      <Input
        label="Website"
        type="url"
        value={data.website}
        onChange={(e) => onChange({ website: e.target.value })}
        placeholder="https://www.yourbusiness.com"
        error={errors.website}
      />
    </div>
  )
}
