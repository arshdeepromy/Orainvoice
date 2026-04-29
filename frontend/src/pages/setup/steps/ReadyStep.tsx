import React, { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import apiClient from '@/api/client'
import type { WizardData } from '../types'
import { COUNTRIES } from '../types'

interface ReadyStepProps {
  data: WizardData
  onGoToStep: (step: number) => void
}

interface OrgSummary {
  name: string
  country_code: string | null
  trade_category_name: string | null
  trade_family_name: string | null
  phone: string | null
  address: string | null
  website: string | null
  trading_name: string | null
  tax_number: string | null
  tax_label: string | null
  tax_rate: number | null
  currency: string | null
  logo_url: string | null
  primary_colour: string | null
  secondary_colour: string | null
  enabled_modules: string[]
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
  const [orgData, setOrgData] = useState<OrgSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    const fetchOrgData = async () => {
      try {
        // Fetch org settings to get the real saved data
        const res = await apiClient.get('/org/settings', { signal: controller.signal })
        const d = res.data
        setOrgData({
          name: d?.org_name ?? d?.name ?? '',
          country_code: d?.country_code ?? d?.address_country ?? null,
          trade_category_name: d?.trade_category ?? null,
          trade_family_name: d?.trade_family ?? null,
          phone: d?.phone ?? null,
          address: d?.address ?? null,
          website: d?.website ?? null,
          trading_name: d?.trading_name ?? null,
          tax_number: d?.gst_number ?? d?.tax_number ?? null,
          tax_label: d?.tax_label ?? null,
          tax_rate: d?.gst_percentage ?? null,
          currency: d?.base_currency ?? null,
          logo_url: d?.logo_url ?? null,
          primary_colour: d?.primary_colour ?? '#2563eb',
          secondary_colour: d?.secondary_colour ?? '#1e40af',
          enabled_modules: [],
        })
      } catch {
        // Fall back to local wizard data if fetch fails
      } finally {
        setLoading(false)
      }
    }

    // Also fetch enabled modules
    const fetchModules = async () => {
      try {
        const res = await apiClient.get('/modules', { baseURL: '/api/v2', signal: controller.signal })
        const mods = res.data?.modules ?? []
        const enabled = mods.filter((m: { is_enabled: boolean; is_core: boolean }) => m.is_enabled && !m.is_core)
        setOrgData(prev => prev ? { ...prev, enabled_modules: enabled.map((m: { slug: string }) => m.slug) } : prev)
      } catch {
        // Non-critical
      }
    }

    fetchOrgData()
    fetchModules()
    return () => controller.abort()
  }, [])

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <Spinner label="Loading summary" />
      </div>
    )
  }

  // Use fetched org data, fall back to local wizard data
  const countryCode = orgData?.country_code ?? data.countryCode
  const country = COUNTRIES.find((c) => c.code === countryCode)
  const businessName = orgData?.name ?? data.businessName
  const tradeName = orgData?.trading_name ?? data.tradingName
  const phone = orgData?.phone ?? data.phone
  const address = orgData?.address ?? data.address
  const taxNumber = orgData?.tax_number ?? data.taxNumber
  const taxLabel = orgData?.tax_label ?? data.taxNumberLabel ?? 'Tax'
  const taxRate = orgData?.tax_rate ?? data.taxRate
  const currency = orgData?.currency ?? data.currency
  const logoUrl = orgData?.logo_url ?? data.logoUrl
  const primaryColour = orgData?.primary_colour ?? data.primaryColour
  const secondaryColour = orgData?.secondary_colour ?? data.secondaryColour
  const tradeCategoryName = orgData?.trade_category_name
  const tradeFamilyName = orgData?.trade_family_name
  const enabledModules = orgData?.enabled_modules ?? data.enabledModules

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
              {currency && <Badge variant="neutral">{currency}</Badge>}
              {taxRate != null && <Badge variant="neutral">{taxLabel} {taxRate}%</Badge>}
            </div>
          ) : (
            <p className="text-gray-400 italic">Not configured</p>
          )}
        </SummarySection>

        {/* Trade */}
        <SummarySection title="Trade Area" stepIndex={1} onEdit={onGoToStep}>
          {tradeCategoryName || tradeFamilyName ? (
            <div className="flex flex-wrap gap-2">
              {tradeFamilyName && <Badge variant="info">{tradeFamilyName}</Badge>}
              {tradeCategoryName && <Badge variant="neutral">{tradeCategoryName}</Badge>}
            </div>
          ) : data.selectedTradeCategories.length > 0 ? (
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
          {businessName ? (
            <div>
              <p className="font-medium text-gray-800">{businessName}</p>
              {tradeName && <p>Trading as: {tradeName}</p>}
              {phone && <p>Phone: {phone}</p>}
              {address && <p>Address: {address}</p>}
              {taxNumber && <p>{taxLabel}: {taxNumber}</p>}
            </div>
          ) : (
            <p className="text-gray-400 italic">Not configured</p>
          )}
        </SummarySection>

        {/* Branding */}
        <SummarySection title="Branding" stepIndex={3} onEdit={onGoToStep}>
          <div className="flex items-center gap-3">
            {logoUrl ? (
              <img
                src={logoUrl}
                alt="Logo"
                className="h-8 w-8 object-contain rounded border border-gray-200"
              />
            ) : (
              <span className="text-gray-400 italic">No logo</span>
            )}
            <div className="flex gap-2">
              <div
                className="h-6 w-6 rounded border border-gray-300"
                style={{ backgroundColor: primaryColour }}
                title={`Primary: ${primaryColour}`}
              />
              <div
                className="h-6 w-6 rounded border border-gray-300"
                style={{ backgroundColor: secondaryColour }}
                title={`Secondary: ${secondaryColour}`}
              />
            </div>
          </div>
        </SummarySection>

        {/* Modules */}
        <SummarySection title="Modules" stepIndex={4} onEdit={onGoToStep}>
          {enabledModules.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {enabledModules.map((slug) => (
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
