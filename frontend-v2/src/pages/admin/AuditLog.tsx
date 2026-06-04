import { useState, useEffect, useCallback } from 'react'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Modal } from '@/components/ui/Modal'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

/* ── Types ── */

export type AuditAction =
  | 'create'
  | 'update'
  | 'delete'
  | 'login'
  | 'logout'
  | 'void'
  | 'issue'
  | 'payment'
  | 'refund'
  | 'export'
  | 'merge'
  | 'anonymise'
  | 'invite'
  | 'settings_change'

export interface AuditEntry {
  id: string
  timestamp: string
  user_id: string
  user_email: string
  action: AuditAction
  entity_type: string
  entity_id: string | null
  description: string
  before_value: string | null
  after_value: string | null
  ip_address: string | null
  device_info: string | null
  org_id: string | null
  org_name: string | null
}

export interface AuditLogResponse {
  entries: AuditEntry[]
  total: number
}

/* ── Constants ── */

const ACTION_OPTIONS = [
  { value: '', label: 'All actions' },
  { value: 'create', label: 'Create' },
  { value: 'update', label: 'Update' },
  { value: 'delete', label: 'Delete' },
  { value: 'login', label: 'Login' },
  { value: 'logout', label: 'Logout' },
  { value: 'void', label: 'Void' },
  { value: 'issue', label: 'Issue' },
  { value: 'payment', label: 'Payment' },
  { value: 'refund', label: 'Refund' },
  { value: 'export', label: 'Export' },
  { value: 'merge', label: 'Merge' },
  { value: 'anonymise', label: 'Anonymise' },
  { value: 'invite', label: 'Invite' },
  { value: 'settings_change', label: 'Settings Change' },
]

const ACTION_BADGE_VARIANT: Record<AuditAction, 'success' | 'warn' | 'danger' | 'info' | 'neutral'> = {
  create: 'success',
  update: 'info',
  delete: 'danger',
  login: 'neutral',
  logout: 'neutral',
  void: 'danger',
  issue: 'success',
  payment: 'success',
  refund: 'warn',
  export: 'info',
  merge: 'warn',
  anonymise: 'danger',
  invite: 'info',
  settings_change: 'warn',
}

/* ── Helpers ── */

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatActionLabel(action: string): string {
  return action
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/* ── Diff View ── */

function DiffView({ before, after }: { before: string | null; after: string | null }) {
  if (!before && !after) {
    return <p className="text-sm text-muted italic">No value changes recorded</p>
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div>
        <h4 className="text-xs font-medium text-muted uppercase mb-1">Before</h4>
        {before ? (
          <pre className="mono max-h-48 overflow-auto rounded bg-danger-soft border border-danger/30 p-3 text-xs text-text whitespace-pre-wrap">
            {before}
          </pre>
        ) : (
          <p className="text-sm text-muted-2 italic">No previous value</p>
        )}
      </div>
      <div>
        <h4 className="text-xs font-medium text-muted uppercase mb-1">After</h4>
        {after ? (
          <pre className="mono max-h-48 overflow-auto rounded bg-ok-soft border border-ok/30 p-3 text-xs text-text whitespace-pre-wrap">
            {after}
          </pre>
        ) : (
          <p className="text-sm text-muted-2 italic">No new value</p>
        )}
      </div>
    </div>
  )
}

/* ── Detail Modal ── */

function AuditDetailModal({
  entry,
  open,
  onClose,
}: {
  entry: AuditEntry | null
  open: boolean
  onClose: () => void
}) {
  if (!entry) return null

  return (
    <Modal open={open} onClose={onClose} title="Audit Entry Detail" className="max-w-2xl">
      <div className="space-y-4">
        {/* Header */}
        <div className="flex flex-wrap gap-2">
          <Badge variant={ACTION_BADGE_VARIANT[entry.action]}>
            {formatActionLabel(entry.action)}
          </Badge>
          <Badge variant="neutral">{entry.entity_type}</Badge>
          <span className="text-sm text-muted">{formatTimestamp(entry.timestamp)}</span>
        </div>

        {/* Entry ID */}
        <div>
          <h4 className="text-xs font-medium text-muted uppercase">Entry ID</h4>
          <p className="mono text-sm text-text">{entry.id}</p>
        </div>

        {/* Description */}
        <div>
          <h4 className="text-xs font-medium text-muted uppercase">Description</h4>
          <p className="text-sm text-text">{entry.description}</p>
        </div>

        {/* Who */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <h4 className="text-xs font-medium text-muted uppercase">User</h4>
            <p className="text-sm text-text">{entry.user_email}</p>
            <p className="mono text-xs text-muted">{entry.user_id}</p>
          </div>
          {entry.org_id && (
            <div>
              <h4 className="text-xs font-medium text-muted uppercase">Organisation</h4>
              <p className="text-sm text-text">{entry.org_name ?? '—'}</p>
              <p className="mono text-xs text-muted">{entry.org_id}</p>
            </div>
          )}
        </div>

        {/* Entity */}
        {entry.entity_id && (
          <div>
            <h4 className="text-xs font-medium text-muted uppercase">Entity</h4>
            <p className="text-sm text-text">
              {entry.entity_type} <span className="mono text-muted">{entry.entity_id}</span>
            </p>
          </div>
        )}

        {/* IP & Device */}
        <div className="grid grid-cols-2 gap-4">
          {entry.ip_address && (
            <div>
              <h4 className="text-xs font-medium text-muted uppercase">IP Address</h4>
              <p className="mono text-sm text-text">{entry.ip_address}</p>
            </div>
          )}
          {entry.device_info && (
            <div>
              <h4 className="text-xs font-medium text-muted uppercase">Device</h4>
              <p className="text-sm text-text">{entry.device_info}</p>
            </div>
          )}
        </div>

        {/* Before / After diff */}
        <div>
          <h4 className="text-xs font-medium text-muted uppercase mb-2">Changes</h4>
          <DiffView before={entry.before_value} after={entry.after_value} />
        </div>

        {/* Close */}
        <div className="border-t border-border pt-4">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Modal>
  )
}

/* ── Main Page ── */

export function AuditLog() {
  const { toasts, addToast, dismissToast } = useToast()

  // List state
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)

  // Filters
  const [search, setSearch] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  // Detail modal
  const [selectedEntry, setSelectedEntry] = useState<AuditEntry | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  /* ── Fetch audit log ── */
  const fetchAuditLog = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setLoadError(false)
    try {
      const params: Record<string, string> = {}
      if (search) params.action = search
      if (actionFilter) params.action = actionFilter
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      const res = await apiClient.get<{
        entries: Array<Record<string, any>>
        total: number
      }>('/admin/audit-log', { params, signal })
      const mapped: AuditEntry[] = (res.data?.entries ?? []).map((e) => ({
        id: e.id,
        timestamp: e.created_at,
        user_id: e.user_id ?? '',
        user_email: '',
        action: e.action as AuditAction,
        entity_type: e.entity_type ?? '',
        entity_id: e.entity_id,
        description: e.action ?? '',
        before_value: e.before_value ? JSON.stringify(e.before_value) : null,
        after_value: e.after_value ? JSON.stringify(e.after_value) : null,
        ip_address: e.ip_address,
        device_info: e.device_info,
        org_id: e.org_id,
        org_name: null,
      }))
      setEntries(mapped)
      setTotal(res.data?.total ?? 0)
    } catch {
      if (signal?.aborted) return
      setLoadError(true)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [search, actionFilter, dateFrom, dateTo])

  useEffect(() => {
    const controller = new AbortController()
    fetchAuditLog(controller.signal)
    return () => controller.abort()
  }, [fetchAuditLog])

  /* ── Open detail ── */
  const openDetail = (entryId: string) => {
    const entry = entries.find((e) => e.id === entryId)
    if (entry) {
      setSelectedEntry(entry)
      setDetailOpen(true)
    } else {
      addToast('error', 'Audit entry not found')
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold text-text mb-6">Audit Log</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4" role="search" aria-label="Audit log filters">
        <div className="flex-1 min-w-[200px]">
          <Input
            label="Search"
            placeholder="Search by user, action, or entity…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="w-44">
          <Select
            label="Action"
            options={ACTION_OPTIONS}
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
          />
        </div>
        <div className="w-44">
          <Input
            label="From"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </div>
        <div className="w-44">
          <Input
            label="To"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </div>
      </div>

      {/* Audit log table */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner label="Loading audit log" />
        </div>
      ) : loadError ? (
        <AlertBanner variant="error" title="Failed to load audit log">
          Could not load audit log. Please try again.
        </AlertBanner>
      ) : (
        <>
          <p className="text-sm text-muted mb-2">
            {total} entr{total !== 1 ? 'ies' : 'y'} found
          </p>
          <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
            <table className="min-w-full" role="grid" aria-label="Audit log entries">
              <thead>
                <tr>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    Time
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    User
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    Action
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    Entity
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    Description
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    IP Address
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {entries.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-sm text-muted">
                      No audit entries found
                    </td>
                  </tr>
                ) : (
                  entries.map((entry) => (
                    <tr
                      key={entry.id}
                      className="border-b border-border last:border-b-0 hover:bg-canvas cursor-pointer"
                      onClick={() => openDetail(entry.id)}
                    >
                      <td className="mono whitespace-nowrap px-4 py-3 text-xs text-muted">
                        {formatTimestamp(entry.timestamp)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-text">
                        {entry.user_email}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Badge variant={ACTION_BADGE_VARIANT[entry.action]}>
                          {formatActionLabel(entry.action)}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-text">
                        {entry.entity_type}
                      </td>
                      <td className="px-4 py-3 text-sm text-text max-w-xs truncate">
                        {entry.description}
                      </td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">
                        {entry.ip_address ?? '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation()
                            openDetail(entry.id)
                          }}
                        >
                          View
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Detail modal */}
      <AuditDetailModal
        entry={selectedEntry}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      />
    </div>
  )
}
