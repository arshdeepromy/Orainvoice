import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { usePortalLocale } from './PortalLocaleContext'
import { formatDate, formatCurrency } from './portalFormatters'

export interface PortalProgressClaim {
  id: string
  project_id: string
  claim_number: number
  status: string
  contract_value: number
  revised_contract_value: number
  work_completed_to_date: number
  work_completed_this_period: number
  materials_on_site: number
  retention_withheld: number
  amount_due: number
  completion_percentage: number
  submitted_at: string | null
  approved_at: string | null
  created_at: string
}

interface ProgressClaimsTabProps {
  token: string
}

const STATUS_CONFIG: Record<string, { label: string; variant: 'success' | 'warning' | 'error' | 'info' | 'neutral' }> = {
  submitted: { label: 'Submitted', variant: 'info' },
  approved: { label: 'Approved', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'error' },
}

export function ProgressClaimsTab({ token }: ProgressClaimsTabProps) {
  const locale = usePortalLocale()
  const [claims, setClaims] = useState<PortalProgressClaim[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const fetchClaims = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await apiClient.get(`/portal/${token}/progress-claims`, { signal: controller.signal })
        setClaims(res.data?.progress_claims ?? [])
      } catch (err) {
        if (!controller.signal.aborted) setError('Failed to load progress claims.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchClaims()
    return () => controller.abort()
  }, [token])

  if (loading) return <div className="py-8"><Spinner label="Loading progress claims" /></div>
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (claims.length === 0) return <p className="py-8 text-center text-sm text-gray-500">No progress claims found.</p>

  return (
    <div className="space-y-4">
      {claims.map((claim) => {
        const statusCfg = STATUS_CONFIG[claim.status] ?? { label: claim.status, variant: 'neutral' as const }
        return (
          <div key={claim.id} className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
                <span className="text-sm font-semibold text-gray-900">Claim #{claim.claim_number ?? 0}</span>
              </div>
              <span className="text-xs text-gray-400">{formatDate(claim.created_at, locale)}</span>
            </div>

            {/* Progress bar */}
            <div className="mb-3">
              <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
                <span>Completion</span>
                <span className="font-medium text-gray-700">{(claim.completion_percentage ?? 0).toFixed(1)}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-gray-100">
                <div
                  className="h-2 rounded-full bg-blue-500 transition-all"
                  style={{ width: `${Math.min(claim.completion_percentage ?? 0, 100)}%` }}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500">
              <span>Contract value: <span className="text-gray-700">{formatCurrency(claim.contract_value ?? 0, locale)}</span></span>
              <span>Revised: <span className="text-gray-700">{formatCurrency(claim.revised_contract_value ?? 0, locale)}</span></span>
              <span>This period: <span className="text-gray-700">{formatCurrency(claim.work_completed_this_period ?? 0, locale)}</span></span>
              <span>To date: <span className="text-gray-700">{formatCurrency(claim.work_completed_to_date ?? 0, locale)}</span></span>
              {(claim.materials_on_site ?? 0) > 0 && (
                <span>Materials on site: <span className="text-gray-700">{formatCurrency(claim.materials_on_site ?? 0, locale)}</span></span>
              )}
              {(claim.retention_withheld ?? 0) > 0 && (
                <span>Retention: <span className="text-gray-700">{formatCurrency(claim.retention_withheld ?? 0, locale)}</span></span>
              )}
            </div>

            <div className="mt-2 flex items-center justify-between border-t border-gray-100 pt-2">
              <span className="text-sm font-medium text-gray-900">
                Amount due: {formatCurrency(claim.amount_due ?? 0, locale)}
              </span>
              <div className="flex gap-3 text-xs text-gray-400">
                {claim.submitted_at && <span>Submitted: {formatDate(claim.submitted_at, locale)}</span>}
                {claim.approved_at && <span>Approved: {formatDate(claim.approved_at, locale)}</span>}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
