import { useEffect, useState } from 'react'
import apiClient from '@/api/client'

/* ── Types ── */

interface OrgBranding {
  org_name: string
  logo_url: string | null
}

interface KioskWelcomeProps {
  onCheckIn: () => void
}

/* ── KioskWelcome ── */

export function KioskWelcome({ onCheckIn }: KioskWelcomeProps) {
  const [branding, setBranding] = useState<OrgBranding | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()

    const fetchBranding = async () => {
      try {
        const res = await apiClient.get<{
          org_name: string
          logo_url: string | null
        }>('/org/settings', { signal: controller.signal })

        setBranding({
          org_name: res.data?.org_name ?? '',
          logo_url: res.data?.logo_url ?? null,
        })
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setLoadFailed(true)
        }
      }
    }

    fetchBranding()
    return () => controller.abort()
  }, [])

  const orgName = branding?.org_name || ''
  const logoUrl = branding?.logo_url || null
  const showBranding = !loadFailed && branding !== null

  return (
    <div className="w-full max-w-md space-y-8 rounded-xl bg-white p-8 text-center shadow-lg">
      {/* Org logo and name */}
      {showBranding && logoUrl && (
        <img
          src={logoUrl}
          alt={orgName ? `${orgName} logo` : 'Organisation logo'}
          className="mx-auto h-20 w-auto object-contain"
        />
      )}

      {showBranding && orgName && (
        <h2 className="text-xl font-semibold text-gray-700">{orgName}</h2>
      )}

      {/* Welcome message */}
      <h1
        className="text-2xl font-bold text-gray-900"
        style={{ fontSize: '18px', minHeight: '1em' }}
      >
        {showBranding && orgName
          ? `Welcome to ${orgName}`
          : 'Welcome'}
      </h1>

      <p className="text-lg text-gray-600" style={{ fontSize: '18px' }}>
        Tap below to check in
      </p>

      {/* Check In button — min 48×48px tap target, 22px font */}
      <button
        type="button"
        onClick={onCheckIn}
        className="inline-flex min-h-[48px] min-w-[48px] items-center justify-center rounded-lg bg-blue-600 px-8 py-3 font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        style={{ fontSize: '22px' }}
      >
        Check In
      </button>
    </div>
  )
}

export default KioskWelcome
