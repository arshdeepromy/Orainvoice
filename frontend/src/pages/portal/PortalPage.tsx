import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
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
import { JobsTab } from './JobsTab'
import { ClaimsTab } from './ClaimsTab'
import { DocumentsTab } from './DocumentsTab'
import { ProjectsTab } from './ProjectsTab'
import { ProgressClaimsTab } from './ProgressClaimsTab'
import { RecurringTab } from './RecurringTab'
import { MessagesTab } from './MessagesTab'
import { PoweredByFooter } from './PoweredByFooter'
import { CookieConsent } from './CookieConsent'
import { MyDetails } from './MyDetails'
import { MyPrivacy } from './MyPrivacy'
import { PortalLocaleProvider } from './PortalLocaleContext'
import { formatCurrency } from './portalFormatters'

export interface PortalInfo {
  customer: {
    customer_id: string
    first_name: string
    last_name: string
    email: string | null
    phone: string | null
  }
  branding: {
    org_name: string
    logo_url: string | null
    primary_colour: string | null
    secondary_colour: string | null
    powered_by: {
      platform_name: string
      logo_url: string | null
      signup_url: string | null
      website_url: string | null
      show_powered_by: boolean
    } | null
    language: string | null
  }
  outstanding_balance: number
  invoice_count: number
  total_paid: number
}

export function PortalPage() {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const [info, setInfo] = useState<PortalInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [signingOut, setSigningOut] = useState(false)

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

  // Req 43.1 — Prevent token leakage via Referrer headers
  useEffect(() => {
    const meta = document.createElement('meta')
    meta.name = 'referrer'
    meta.content = 'no-referrer'
    document.head.appendChild(meta)
    return () => {
      document.head.removeChild(meta)
    }
  }, [])

  // Req 43.2 — Remove token from address bar after successful validation
  useEffect(() => {
    if (info && !loading && !error) {
      window.history.replaceState({}, '', '/portal/dashboard')
    }
  }, [info, loading, error])

  const handleSignOut = useCallback(async () => {
    setSigningOut(true)
    try {
      await apiClient.post('/portal/logout')
    } catch {
      // Best-effort — clear local state regardless
    }
    setInfo(null)
    navigate('/portal/signed-out', { replace: true })
  }, [navigate])

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
        <div className="mt-4 text-center">
          <a
            href="/portal/recover"
            className="text-sm font-medium hover:opacity-80"
            style={{ color: 'var(--portal-accent, #2563eb)' }}
          >
            Forgot your link?
          </a>
        </div>
      </div>
    )
  }

  const primaryColor = info.branding.primary_colour ?? '#2563eb'
  const secondaryColor = info.branding.secondary_colour ?? primaryColor
  const locale = info.branding.language ?? 'en-NZ'

  return (
    <PortalLocaleProvider value={locale}>
    <CookieConsent />
    <div
      lang={locale}
      style={{
        '--portal-accent': primaryColor,
        '--portal-accent-secondary': secondaryColor,
      } as React.CSSProperties}
    >
      {/* Welcome header */}
      <div className="mb-6 flex items-start justify-between">
        <div className="flex items-center gap-4">
          {info.branding.logo_url && (
            <img
              src={info.branding.logo_url}
              alt={`${info.branding.org_name} logo`}
              className="h-12 w-auto max-w-[120px] object-contain"
            />
          )}
          <div>
          <h1 className="text-2xl font-semibold text-gray-900">
            Welcome, {info.customer.first_name + ' ' + info.customer.last_name}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage your invoices and vehicle service history with {info.branding.org_name}
          </p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleSignOut}
          disabled={signingOut}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 min-h-[44px]"
          style={{ '--tw-ring-color': 'var(--portal-accent, #2563eb)' } as React.CSSProperties}
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
          {signingOut ? 'Signing out…' : 'Sign Out'}
        </button>
      </div>

      {/* Summary cards */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <SummaryCard
          label="Outstanding Balance"
          value={formatCurrency(info.outstanding_balance ?? 0, locale)}
          variant={(info.outstanding_balance ?? 0) > 0 ? 'warning' : 'success'}
        />
        <SummaryCard label="Total Invoices" value={String(info.invoice_count ?? 0)} variant="neutral" />
        <SummaryCard label="Total Paid" value={formatCurrency(info.total_paid ?? 0, locale)} variant="success" />
      </div>

      {/* My Details section */}
      <MyDetails
        token={token!}
        email={info.customer.email ?? null}
        phone={info.customer.phone ?? null}
        onUpdated={(email, phone) => {
          setInfo((prev) =>
            prev
              ? {
                  ...prev,
                  customer: { ...prev.customer, email, phone },
                }
              : prev,
          )
        }}
      />

      {/* My Privacy section (Req 45.1, 45.2, 45.5) */}
      <MyPrivacy token={token!} />

      {/* Tabbed content */}
      <Tabs
        tabs={[
          {
            id: 'invoices',
            label: 'Invoices',
            content: <InvoiceHistory token={token!} primaryColor={primaryColor} />,
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
            id: 'jobs',
            label: 'Jobs',
            content: <JobsTab token={token!} />,
          },
          {
            id: 'claims',
            label: 'Claims',
            content: <ClaimsTab token={token!} />,
          },
          {
            id: 'documents',
            label: 'Documents',
            content: <DocumentsTab token={token!} />,
          },
          {
            id: 'projects',
            label: 'Projects',
            content: <ProjectsTab token={token!} />,
          },
          {
            id: 'progress-claims',
            label: 'Progress Claims',
            content: <ProgressClaimsTab token={token!} />,
          },
          {
            id: 'recurring',
            label: 'Recurring',
            content: <RecurringTab token={token!} />,
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
          {
            id: 'messages',
            label: 'Messages',
            content: <MessagesTab token={token!} />,
          },
        ]}
        defaultTab="invoices"
      />

      {/* Powered By footer */}
      <PoweredByFooter poweredBy={info.branding.powered_by ?? null} />
    </div>
    </PortalLocaleProvider>
  )
}

/* ── Helpers ── */

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
    <div
      className={`rounded-lg border bg-white p-4 ${variantBorder[variant]}`}
      style={{ borderLeftWidth: '4px', borderLeftColor: 'var(--portal-accent, #2563eb)' }}
    >
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${variantText[variant]}`}>
        {value}
      </p>
    </div>
  )
}
