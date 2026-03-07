import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Tabs } from '@/components/ui/Tabs'
import { InvoiceHistory } from './InvoiceHistory'
import { VehicleHistory } from './VehicleHistory'
import { QuoteAcceptance } from './QuoteAcceptance'
import { AssetHistory } from './AssetHistory'
import { BookingManager } from './BookingManager'
import { LoyaltyBalance } from './LoyaltyBalance'
import { PoweredByFooter } from './PoweredByFooter'

export interface PortalInfo {
  customer_name: string
  email: string
  phone: string
  org_name: string
  logo_url: string | null
  primary_color: string
  outstanding_balance: number
  total_invoices: number
  total_paid: number
  powered_by?: {
    platform_name: string
    logo_url: string | null
    signup_url: string | null
    website_url: string | null
    show_powered_by: boolean
  } | null
  language?: string | null
}

export function PortalPage() {
  const { token } = useParams<{ token: string }>()
  const [info, setInfo] = useState<PortalInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchPortalInfo = useCallback(async () => {
    if (!token) return
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<PortalInfo>(`/portal/${token}`)
      setInfo(res.data)
    } catch {
      setError('Unable to load your portal. The link may have expired or is invalid.')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    fetchPortalInfo()
  }, [fetchPortalInfo])

  if (loading) {
    return (
      <div className="py-16">
        <Spinner label="Loading portal" />
      </div>
    )
  }

  if (error || !info) {
    return (
      <div className="py-8">
        <AlertBanner variant="error" title="Access Error">
          {error || 'Something went wrong. Please try again.'}
        </AlertBanner>
      </div>
    )
  }

  return (
    <div>
      {/* Welcome header */}
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">
          Welcome, {info.customer_name}
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage your invoices and vehicle service history with {info.org_name}
        </p>
      </div>

      {/* Summary cards */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <SummaryCard
          label="Outstanding Balance"
          value={formatNZD(info.outstanding_balance)}
          variant={info.outstanding_balance > 0 ? 'warning' : 'success'}
        />
        <SummaryCard label="Total Invoices" value={String(info.total_invoices)} variant="neutral" />
        <SummaryCard label="Total Paid" value={formatNZD(info.total_paid)} variant="success" />
      </div>

      {/* Tabbed content */}
      <Tabs
        tabs={[
          {
            id: 'invoices',
            label: 'Invoices',
            content: <InvoiceHistory token={token!} primaryColor={info.primary_color} />,
          },
          {
            id: 'quotes',
            label: 'Quotes',
            content: <QuoteAcceptance token={token!} />,
          },
          {
            id: 'assets',
            label: 'Assets',
            content: <AssetHistory token={token!} />,
          },
          {
            id: 'vehicles',
            label: 'Vehicles',
            content: <VehicleHistory token={token!} />,
          },
          {
            id: 'bookings',
            label: 'Bookings',
            content: <BookingManager token={token!} />,
          },
          {
            id: 'loyalty',
            label: 'Loyalty',
            content: <LoyaltyBalance token={token!} />,
          },
        ]}
        defaultTab="invoices"
      />

      {/* Powered By footer */}
      <PoweredByFooter poweredBy={info.powered_by} />
    </div>
  )
}

/* ── Helpers ── */

function formatNZD(amount: number): string {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(amount)
}

interface SummaryCardProps {
  label: string
  value: string
  variant: 'success' | 'warning' | 'neutral'
}

const variantBorder: Record<string, string> = {
  success: 'border-green-200',
  warning: 'border-amber-200',
  neutral: 'border-gray-200',
}

const variantText: Record<string, string> = {
  success: 'text-green-700',
  warning: 'text-amber-700',
  neutral: 'text-gray-900',
}

function SummaryCard({ label, value, variant }: SummaryCardProps) {
  return (
    <div className={`rounded-lg border bg-white p-4 ${variantBorder[variant]}`}>
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${variantText[variant]}`}>
        {value}
      </p>
    </div>
  )
}
