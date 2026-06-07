import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Input, Badge, Spinner, Pagination, Select, Button } from '@/components/ui'
import { useTenant } from '@/contexts/TenantContext'
import { useModules } from '@/contexts/ModuleContext'
import { SendEmailModal } from '@/components/email/SendEmailModal'
import { SURFACE_REGISTRY } from '@/components/email/surfaceRegistry'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface LogEntry {
  id: string
  recipient: string
  channel: 'email' | 'sms'
  template_type: string
  subject: string
  status: 'queued' | 'sent' | 'delivered' | 'bounced' | 'opened' | 'failed'
  created_at: string
  provider_key?: string | null
  provider_message_id?: string | null
  bounced_at?: string | null
  bounce_reason?: string | null
  delivered_at?: string | null
}

interface LogResponse {
  entries: LogEntry[]
  total: number
  page: number
  page_size: number
}

// Status colour mapping per email-provider-unification spec (Req 16.6):
//   sent      → green  (success)
//   delivered → blue   (info)     — distinct from sent so admins see provider-confirmed delivery
//   bounced   → red    (danger)   — hover tooltip exposes bounce_reason
//   failed    → red    (danger)
//   queued    → grey   (neutral)
//   opened    → green  (success)
const STATUS_BADGE: Record<LogEntry['status'], 'neutral' | 'info' | 'success' | 'danger' | 'warn'> = {
  queued: 'neutral',
  sent: 'success',
  delivered: 'info',
  bounced: 'danger',
  opened: 'success',
  failed: 'danger',
}

/**
 * Vehicle-expiry reminder template types that support the shared Send Email
 * composer's Resend surface (R2.7). Only log rows whose `template_type` is one
 * of these get a Resend action; all other notifications have no Resend trigger.
 */
const RESEND_TEMPLATE_TYPES: ReadonlySet<string> = new Set([
  'wof_expiry_reminder',
  'cof_expiry_reminder',
  'registration_expiry_reminder',
  'service_due_reminder',
])

/**
 * Email/SMS delivery log viewer — shows recipient, template, timestamp,
 * delivery status, and subject for all sent notifications.
 *
 * Requirements: 35.1, 35.2, 36.6
 */
export default function NotificationLog() {
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [channelFilter, setChannelFilter] = useState('')
  const pageSize = 20

  /* Resend capability gate (R22.1–22.3): the vehicles module must be enabled
     AND the org's trade family must be automotive. When false we fail closed —
     the whole Resend capability (column + per-row action) is not rendered. */
  const { tradeFamily } = useTenant()
  const { isEnabled: isModuleEnabled } = useModules()
  const vehiclesEnabled = isModuleEnabled('vehicles')
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
  const canResend = vehiclesEnabled && isAutomotive

  /* Shared Send Email composer — driven by the notification-log row whose
     Resend action was clicked. Resend keys off the log id (`logId`); the
     backend reconstructs vehicle/customer context from the log row itself. */
  const [resendEntry, setResendEntry] = useState<LogEntry | null>(null)

  const fetchLog = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize }
      if (statusFilter) params.status = statusFilter
      if (channelFilter) params.channel = channelFilter
      const res = await apiClient.get<LogResponse>('/notifications/log', { params })
      setEntries(res.data?.entries ?? [])
      setTotal(res.data?.total ?? 0)
    } catch {
      setError('Failed to load notification log.')
    } finally {
      setLoading(false)
    }
  }, [page, statusFilter, channelFilter])

  useEffect(() => { fetchLog() }, [fetchLog])

  // Reset page when filters change
  useEffect(() => { setPage(1) }, [statusFilter, channelFilter])

  // Client-side search filter (backend doesn't support search parameter)
  const filteredEntries = search.trim()
    ? entries.filter((entry) => {
        const q = search.trim().toLowerCase()
        return (
          entry.recipient.toLowerCase().includes(q) ||
          entry.template_type.toLowerCase().includes(q) ||
          entry.subject.toLowerCase().includes(q)
        )
      })
    : entries

  return (
    <div>
      <p className="text-sm text-muted mb-4">
        View delivery status for all sent emails and SMS messages.
      </p>

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end mb-4">
        <div className="flex-1 max-w-sm">
          <Input
            label="Search"
            placeholder="Recipient, template, or subject…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search notification log"
          />
        </div>
        <div className="w-40">
          <Select
            label="Status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            options={[
              { value: '', label: 'All statuses' },
              { value: 'queued', label: 'Queued' },
              { value: 'sent', label: 'Sent' },
              { value: 'delivered', label: 'Delivered' },
              { value: 'bounced', label: 'Bounced' },
              { value: 'opened', label: 'Opened' },
              { value: 'failed', label: 'Failed' },
            ]}
          />
        </div>
        <div className="w-36">
          <Select
            label="Channel"
            value={channelFilter}
            onChange={(e) => setChannelFilter(e.target.value)}
            options={[
              { value: '', label: 'All channels' },
              { value: 'email', label: 'Email' },
              { value: 'sms', label: 'SMS' },
            ]}
          />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {loading && !filteredEntries.length && (
        <div className="py-16"><Spinner label="Loading notification log" /></div>
      )}

      {!loading && (
        <>
          <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <table className="min-w-full" role="grid">
              <caption className="sr-only">Notification delivery log</caption>
              <thead>
                <tr>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Recipient</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Channel</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Template</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Subject</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Provider</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Sent</th>
                  {canResend && (
                    <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Actions</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {filteredEntries.length === 0 ? (
                  <tr>
                    <td colSpan={canResend ? 8 : 7} className="px-4 py-12 text-center text-sm text-muted">
                      {search || statusFilter || channelFilter
                        ? 'No log entries match your filters.'
                        : 'No notifications sent yet.'}
                    </td>
                  </tr>
                ) : (
                  filteredEntries.map((entry) => (
                    <tr key={entry.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-text">{entry.recipient}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <Badge variant={entry.channel === 'email' ? 'info' : 'neutral'}>
                          {entry.channel.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-text">{entry.template_type}</td>
                      <td className="px-4 py-3 text-sm text-text max-w-xs truncate">{entry.subject}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-text">
                        {entry.provider_key ?? '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        {entry.status === 'bounced' ? (
                          <span title={entry.bounce_reason ?? ''}>
                            <Badge variant={STATUS_BADGE[entry.status]}>
                              {entry.status.charAt(0).toUpperCase() + entry.status.slice(1)}
                            </Badge>
                          </span>
                        ) : (
                          <Badge variant={STATUS_BADGE[entry.status]}>
                            {entry.status.charAt(0).toUpperCase() + entry.status.slice(1)}
                          </Badge>
                        )}
                      </td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">
                        {new Date(entry.created_at).toLocaleString('en-NZ')}
                      </td>
                      {canResend && (
                        <td className="whitespace-nowrap px-4 py-3 text-sm">
                          {RESEND_TEMPLATE_TYPES.has(entry.template_type) ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setResendEntry(entry)}
                            >
                              Resend
                            </Button>
                          ) : null}
                        </td>
                      )}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {total > pageSize && (
            <div className="mt-4">
              <Pagination
                currentPage={page}
                totalPages={Math.ceil(total / pageSize)}
                onPageChange={setPage}
              />
            </div>
          )}
        </>
      )}

      {/* ---- Send Email composer modal (shared) — Resend reminder surface ----
         Only mounts when the Resend gate passes (R22.2/22.3) and a row has been
         selected. The resend endpoint is keyed by `logId` (the URL is
         /api/v2/notifications/log/{logId}/resend) and the backend reconstructs
         the customer/vehicle context from the log row, so `entityId` is not used
         for lookup — we pass the log id as a stable best-effort placeholder
         (the design's (customer_id, global_vehicle_id) pair is not carried on
         the notification_log row in this view; logId is the operative key). */}
      {canResend && resendEntry && (
        <SendEmailModal
          open={true}
          onClose={() => setResendEntry(null)}
          templateType={resendEntry.template_type}
          entityType="customer_vehicle"
          entityId={resendEntry.id}
          logId={resendEntry.id}
          surfaceLabel={SURFACE_REGISTRY[resendEntry.template_type]?.surfaceLabel ?? 'Resend Reminder'}
          onSent={() => { fetchLog() }}
        />
      )}
    </div>
  )
}
