import { useEffect, useState } from 'react'
import apiClient from '@/api/client'

/**
 * KioskBrand — the persistent brand lockup pinned to the top of every kiosk
 * screen (design: `.k-brand` in OraInvoice_Handoff/app/Kiosk.html).
 *
 * Fetches org branding (name + logo) from GET /org/settings — the same source
 * the old KioskWelcome used, lifted here so the header stays visible across the
 * whole check-in flow. Renders the org logo when available, otherwise the accent
 * mark + org name. Branding-load failure degrades to the bare mark (no crash).
 */
export function KioskBrand() {
  const [orgName, setOrgName] = useState('')
  const [logoUrl, setLogoUrl] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .get<{ org_name?: string; logo_url?: string | null }>('/org/settings', {
        signal: controller.signal,
      })
      .then((res) => {
        setOrgName(res.data?.org_name ?? '')
        setLogoUrl(res.data?.logo_url ?? null)
      })
      .catch(() => {
        /* Silent — header degrades to the bare mark. */
      })
    return () => controller.abort()
  }, [])

  return (
    <div className="k-brand">
      {logoUrl ? (
        <img src={logoUrl} alt={orgName ? `${orgName} logo` : 'Logo'} />
      ) : (
        <div className="m">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
            <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2z" />
          </svg>
        </div>
      )}
      {orgName && <div className="n">{orgName}</div>}
    </div>
  )
}

export default KioskBrand
