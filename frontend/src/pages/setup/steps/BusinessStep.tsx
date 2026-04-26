import { useCallback, useMemo } from 'react'
import { Input } from '@/components/ui/Input'
import type { WizardData } from '../types'

interface BusinessStepProps {
  data: WizardData
  onChange: (updates: Partial<WizardData>) => void
  errors: Record<string, string>
}

/**
 * Auto-format NZ IRD number as user types: XX-XXX-XXX or XXX-XXX-XXX.
 * Strips non-digits, then inserts dashes at the right positions.
 */
function formatNzIrd(raw: string): string {
  const digits = raw.replace(/\D/g, '').slice(0, 9)
  if (digits.length <= 2) return digits
  if (digits.length <= 5) return `${digits.slice(0, digits.length <= 3 ? 2 : (digits.length > 5 ? 3 : 2))}-${digits.slice(digits.length <= 3 ? 2 : (digits.length > 5 ? 3 : 2))}`
  // 8 digits: XX-XXX-XXX, 9 digits: XXX-XXX-XXX
  if (digits.length <= 8) {
    return `${digits.slice(0, 2)}-${digits.slice(2, 5)}-${digits.slice(5)}`
  }
  return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`
}

/**
 * Auto-format AU ABN as user types: XX XXX XXX XXX.
 */
function formatAuAbn(raw: string): string {
  const digits = raw.replace(/\D/g, '').slice(0, 11)
  const parts: string[] = []
  if (digits.length > 0) parts.push(digits.slice(0, 2))
  if (digits.length > 2) parts.push(digits.slice(2, 5))
  if (digits.length > 5) parts.push(digits.slice(5, 8))
  if (digits.length > 8) parts.push(digits.slice(8, 11))
  return parts.join(' ')
}

export function BusinessStep({ data, onChange, errors }: BusinessStepProps) {
  const taxValidation = useMemo(() => {
    if (!data.taxNumber || !data.taxNumberRegex) return ''
    try {
      const regex = new RegExp(data.taxNumberRegex)
      // Test against digits-only version for flexibility
      const digitsOnly = data.taxNumber.replace(/\D/g, '')
      if (!regex.test(data.taxNumber) && !regex.test(digitsOnly)) {
        return `Invalid ${data.taxNumberLabel} format`
      }
    } catch {
      // Invalid regex pattern — skip validation
    }
    return ''
  }, [data.taxNumber, data.taxNumberRegex, data.taxNumberLabel])

  const handleTaxNumberChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const raw = e.target.value
      if (data.countryCode === 'NZ') {
        onChange({ taxNumber: formatNzIrd(raw) })
      } else if (data.countryCode === 'AU') {
        onChange({ taxNumber: formatAuAbn(raw) })
      } else {
        onChange({ taxNumber: raw })
      }
    },
    [data.countryCode, onChange],
  )

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
          onChange={handleTaxNumberChange}
          placeholder={
            data.countryCode === 'NZ'
              ? '123-456-789'
              : data.countryCode === 'AU'
                ? '12 345 678 901'
                : `Enter your ${data.taxNumberLabel || 'tax number'}`
          }
          error={taxValidation || errors.taxNumber}
          helperText={
            data.countryCode === 'NZ'
              ? '8 or 9 digit IRD number (dashes added automatically)'
              : data.countryCode === 'AU'
                ? '11 digit ABN (spaces added automatically)'
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

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input
          label="Unit / Suite"
          value={data.addressUnit}
          onChange={(e) => onChange({ addressUnit: e.target.value })}
          placeholder="e.g. Unit 3"
        />
        <Input
          label="Street Number & Name"
          value={data.addressStreet}
          onChange={(e) => onChange({ addressStreet: e.target.value })}
          placeholder="e.g. 34 Wai Iti Place"
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Input
          label="City / Town"
          value={data.addressCity}
          onChange={(e) => onChange({ addressCity: e.target.value })}
          placeholder="e.g. Auckland"
        />
        <Input
          label="State / Region"
          value={data.addressState}
          onChange={(e) => onChange({ addressState: e.target.value })}
          placeholder="e.g. Auckland"
        />
        <Input
          label="Postcode"
          value={data.addressPostcode}
          onChange={(e) => onChange({ addressPostcode: e.target.value })}
          placeholder="e.g. 0600"
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
