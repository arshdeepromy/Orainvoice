import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Badge, Spinner, AlertBanner } from '@/components/ui'
import { usePortalLocale } from './PortalLocaleContext'
import { formatDate } from './portalFormatters'

export interface PortalClaimAction {
  action_type: string
  from_status: string | null
  to_status: string | null
  notes: string | null
  performed_at: string
}

export interface PortalClaim {
  id: string
  reference: string | null
  claim_type: string
  status: string
  description: string
  resolution_type: string | null
  resolution_notes: string | null
  created_at: string
  actions: PortalClaimAction[]
}

interface ClaimsTabProps {
  token: string
}

const STATUS_CONFIG: Record<string, { label: string; variant: 'success' | 'warn' | 'danger' | 'info' | 'neutral' }> = {
  open: { label: 'Open', variant: 'warn' },
  investigating: { label: 'Investigating', variant: 'info' },
  approved: { label: 'Approved', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'danger' },
  resolved: { label: 'Resolved', variant: 'neutral' },
}

const CLAIM_TYPE_LABELS: Record<string, string> = {
  warranty: 'Warranty',
  defect: 'Defect',
  service_redo: 'Service Redo',
  exchange: 'Exchange',
  refund_request: 'Refund Request',
}

const RESOLUTION_TYPE_LABELS: Record<string, string> = {
  full_refund: 'Full Refund',
  partial_refund: 'Partial Refund',
  credit_note: 'Credit Note',
  exchange: 'Exchange',
  redo_service: 'Redo Service',
  no_action: 'No Action',
}

export function ClaimsTab({ token }: ClaimsTabProps) {
  const locale = usePortalLocale()
  const [claims, setClaims] = useState<PortalClaim[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const fetchClaims = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await apiClient.get(`/portal/${token}/claims`, { signal: controller.signal })
        setClaims(res.data?.claims ?? [])
      } catch (err) {
        if (!controller.signal.aborted) setError('Failed to load claims.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchClaims()
    return () => controller.abort()
  }, [token])

  if (loading) return <div className="py-8"><Spinner label="Loading claims" /></div>
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (claims.length === 0) return <p className="py-8 text-center text-sm text-muted">No claims found.</p>

  return (
    <div className="space-y-4">
      {claims.map((claim) => {
        const statusCfg = STATUS_CONFIG[claim.status] ?? { label: claim.status, variant: 'neutral' as const }
        const claimTypeLabel = CLAIM_TYPE_LABELS[claim.claim_type] ?? claim.claim_type

        return (
          <div key={claim.id} className="rounded-card border border-border bg-card shadow-card p-4">
            {/* Header row */}
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
                <span className="text-sm font-medium text-text">{claimTypeLabel}</span>
                {claim.reference && (
                  <span className="text-xs text-muted-2">{claim.reference}</span>
                )}
              </div>
              <span className="text-xs text-muted-2">{formatDate(claim.created_at, locale)}</span>
            </div>

            {/* Description */}
            <p className="text-sm text-text mb-2">{claim.description}</p>

            {/* Resolution details */}
            {claim.resolution_type && (
              <div className="mb-2 text-xs text-muted">
                <span>Resolution: <span className="text-text">{RESOLUTION_TYPE_LABELS[claim.resolution_type] ?? claim.resolution_type}</span></span>
                {claim.resolution_notes && (
                  <p className="mt-1 text-muted">{claim.resolution_notes}</p>
                )}
              </div>
            )}

            {/* Action timeline */}
            {(claim.actions ?? []).length > 0 && (
              <div className="mt-3 border-t border-border pt-3">
                <p className="text-xs font-medium text-muted mb-2">Timeline</p>
                <div className="space-y-2">
                  {(claim.actions ?? []).map((action, idx) => (
                    <div key={idx} className="flex items-start gap-2 text-xs">
                      <div className="mt-1 h-2 w-2 flex-shrink-0 rounded-full bg-border-strong" />
                      <div>
                        <span className="text-text font-medium">{formatActionType(action.action_type)}</span>
                        {action.to_status && (
                          <span className="text-muted"> → {STATUS_CONFIG[action.to_status]?.label ?? action.to_status}</span>
                        )}
                        <span className="text-muted-2 ml-2">{formatDate(action.performed_at, locale)}</span>
                        {action.notes && (
                          <p className="text-muted mt-0.5">{action.notes}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function formatActionType(actionType: string): string {
  return actionType
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}
