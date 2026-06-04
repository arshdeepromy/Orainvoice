import React from 'react'
import { InvoicePreview } from '../components/InvoicePreview'
import type { WizardData } from '../types'

interface BrandingStepProps {
  data: WizardData
  onChange: (updates: Partial<WizardData>) => void
}

export function BrandingStep({ data, onChange }: BrandingStepProps) {
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null
    if (file) {
      const url = URL.createObjectURL(file)
      onChange({ logoFile: file, logoUrl: url })
    }
  }

  const removeLogo = () => {
    onChange({ logoFile: null, logoUrl: '' })
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-text">Brand Your Invoices</h2>
      <p className="text-sm text-muted">
        Upload your logo and pick brand colours. The preview updates in real-time.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Controls */}
        <div className="space-y-4">
          {/* Logo upload */}
          <div className="flex flex-col gap-1">
            <label htmlFor="logo-upload" className="text-sm font-medium text-text">
              Logo (PNG, JPG, or SVG)
            </label>
            <input
              id="logo-upload"
              type="file"
              accept=".png,.jpg,.jpeg,.svg,image/png,image/jpeg,image/svg+xml"
              onChange={handleFileChange}
              className="block w-full text-sm text-muted file:mr-4 file:py-2 file:px-4
                file:rounded-ctl file:border-0 file:text-sm file:font-medium
                file:bg-accent-soft file:text-accent hover:file:bg-accent-soft/70"
            />
            {data.logoUrl && (
              <div className="flex items-center gap-3 mt-1">
                <img
                  src={data.logoUrl}
                  alt="Logo preview"
                  className="h-10 w-10 object-contain rounded-ctl border border-border"
                />
                <button
                  type="button"
                  onClick={removeLogo}
                  className="text-xs text-danger hover:text-danger/80 underline"
                >
                  Remove
                </button>
              </div>
            )}
          </div>

          {/* Colour pickers */}
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1">
              <label htmlFor="primary-colour" className="text-sm font-medium text-text">
                Primary colour
              </label>
              <div className="flex items-center gap-3">
                <input
                  id="primary-colour"
                  type="color"
                  value={data.primaryColour}
                  onChange={(e) => onChange({ primaryColour: e.target.value })}
                  className="h-10 w-14 cursor-pointer rounded-ctl border border-border"
                />
                <span className="text-xs text-muted font-mono">{data.primaryColour}</span>
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="secondary-colour" className="text-sm font-medium text-text">
                Secondary colour
              </label>
              <div className="flex items-center gap-3">
                <input
                  id="secondary-colour"
                  type="color"
                  value={data.secondaryColour}
                  onChange={(e) => onChange({ secondaryColour: e.target.value })}
                  className="h-10 w-14 cursor-pointer rounded-ctl border border-border"
                />
                <span className="text-xs text-muted font-mono">{data.secondaryColour}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Live preview */}
        <div>
          <p className="text-sm font-medium text-text mb-2">Live preview</p>
          <InvoicePreview
            data={{
              businessName: data.businessName || 'Your Business',
              tradingName: data.tradingName,
              address: data.address,
              phone: data.phone,
              website: data.website,
              logoUrl: data.logoUrl || undefined,
              primaryColour: data.primaryColour,
              secondaryColour: data.secondaryColour,
              taxLabel: data.taxLabel,
              taxRate: data.taxRate,
              currency: data.currency,
              dateFormat: data.dateFormat,
            }}
          />
        </div>
      </div>
    </div>
  )
}
