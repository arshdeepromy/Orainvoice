import React from 'react'
import { Badge } from '@/components/ui/Badge'
import type { WizardData } from '../types'
import { COUNTRIES } from '../types'

interface ReadyStepProps {
  data: WizardData
  onGoToStep: (step: number) => void
}

function SummarySection({
  title,
  stepIndex,
  onEdit,
  children,
}: {
  title: string
  stepIndex: number
  onEdit: (step: number) => void
  children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
        <button
          type="button"
          onClick={() => onEdit(stepIndex)}
          className="text-xs text-blue-600 hover:text-blue-800 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
        >
          Edit
        </button>
      </div>
      <div className="text-sm text-gray-600 space-y-1">{children}</div>
    </div>
  )
}

export function ReadyStep({ data, onGoToStep }: ReadyStepProps) {
  const country = COUNTRIES.find((c) => c.code === data.countryCode)

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-900">You're All Set!</h2>
      <p className="text-sm text-gray-500">
        Review your configuration below. Click "Edit" on any section to make changes.
      </p>

      <div className="space-y-3">
        {/* Country */}
        <SummarySection title="Country & Region" stepIndex={0} onEdit={onGoToStep}>
          {country ? (
            <div className="flex flex-wrap gap-2">
              <Badge variant="info">{country.name}</Badge>
              <Badge variant="neutral">{data.currency}</Badge>
              <Badge variant="neutral">{data.taxLabel} {data.taxRate}%</Badge>
            </div>
          ) : (
            <p className="text-gray-400 italic">Not configured</p>
          )}
        </SummarySection>

        {/* Trade */}
        <SummarySection title="Trade Area" stepIndex={1} onEdit={onGoToStep}>
          {data.selectedTradeCategories.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {data.selectedTradeCategories.map((slug) => (
                <Badge key={slug} variant="info">{slug}</Badge>
              ))}
            </div>
          ) : (
            <p className="text-gray-400 italic">Not configured</p>
          )}
        </SummarySection>

        {/* Business */}
        <SummarySection title="Business Details" stepIndex={2} onEdit={onGoToStep}>
          {data.businessName ? (
            <div>
              <p className="font-medium text-gray-800">{data.businessName}</p>
              {data.tradingName && <p>Trading as: {data.tradingName}</p>}
              {data.phone && <p>Phone: {data.phone}</p>}
              {data.address && <p>Address: {data.address}</p>}
              {data.taxNumber && <p>{data.taxNumberLabel}: {data.taxNumber}</p>}
            </div>
          ) : (
            <p className="text-gray-400 italic">Not configured</p>
          )}
        </SummarySection>

        {/* Branding */}
        <SummarySection title="Branding" stepIndex={3} onEdit={onGoToStep}>
          <div className="flex items-center gap-3">
            {data.logoUrl ? (
              <img
                src={data.logoUrl}
                alt="Logo"
                className="h-8 w-8 object-contain rounded border border-gray-200"
              />
            ) : (
              <span className="text-gray-400 italic">No logo</span>
            )}
            <div className="flex gap-2">
              <div
                className="h-6 w-6 rounded border border-gray-300"
                style={{ backgroundColor: data.primaryColour }}
                title={`Primary: ${data.primaryColour}`}
              />
              <div
                className="h-6 w-6 rounded border border-gray-300"
                style={{ backgroundColor: data.secondaryColour }}
                title={`Secondary: ${data.secondaryColour}`}
              />
            </div>
          </div>
        </SummarySection>

        {/* Modules */}
        <SummarySection title="Modules" stepIndex={4} onEdit={onGoToStep}>
          {data.enabledModules.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {data.enabledModules.map((slug) => (
                <Badge key={slug} variant="success">{slug}</Badge>
              ))}
            </div>
          ) : (
            <p className="text-gray-400 italic">Default modules only</p>
          )}
        </SummarySection>

        {/* Catalogue */}
        <SummarySection title="Catalogue" stepIndex={5} onEdit={onGoToStep}>
          {data.catalogueItems.length > 0 ? (
            <p>
              {data.catalogueItems.filter((i) => i.item_type === 'service').length} services,{' '}
              {data.catalogueItems.filter((i) => i.item_type === 'product').length} products
            </p>
          ) : (
            <p className="text-gray-400 italic">No items added</p>
          )}
        </SummarySection>
      </div>
    </div>
  )
}
