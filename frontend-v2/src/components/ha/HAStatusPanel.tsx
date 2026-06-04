import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '@/api/client'
import { Badge, Spinner, AlertBanner, Button, Input, Card, cx } from '@/components/ui'

/* ============================================================
   HAStatusPanel (Task 17 port of frontend/src/components/ha/HAStatusPanel).
   ------------------------------------------------------------
   Rendered by the GlobalAdminDashboard, so it's ported here as part of
   preserving that variant's functionality (FR-1). ALL logic is copied
   verbatim from the original:
     • GET /ha/identity / /ha/history / /ha/replication/status (safeFetch
       fallbacks), 10s polling, cancelled guard.
     • derivePeerHealth / formatLag / formatTime helpers (unchanged).
     • promote (POST /ha/promote) / demote (POST /ha/demote) with the
       CONFIRM-text gate, reason, and the lag>5s force-promotion checkbox.
     • the same warning banners (lag>30s, subscription error).

   Design (FR-2 + FR-2b): restyled onto the new token surface to match the
   dashboard cards (rounded-card / border / shadow-card, Badge pills,
   AlertBanner). The original used the shared <Modal> (Task 73, not yet
   ported), so the confirmation dialog is designed on-the-fly here in the
   same language — a fixed scrim + centred card panel, identical to the
   inline modal pattern the original GlobalAdminDashboard already uses for
   its token-refresh log.

   NOTE: the frontend-v2 Badge variant union uses `warn`/`danger` (not the
   original `warning`/`error`), so roleVariant maps onto those tone names.
   ============================================================ */

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface HAIdentity {
  node_id: string
  node_name: string
  role: string
  peer_endpoint: string
  auto_promote_enabled: boolean
  heartbeat_interval_seconds: number
  failover_timeout_seconds: number
  created_at: string
  updated_at: string
}

interface HeartbeatHistoryEntry {
  timestamp: string
  peer_status: string
  replication_lag_seconds: number | null
  response_time_ms: number | null
  error: string | null
}

interface ReplicationStatus {
  publication_name: string | null
  subscription_name: string | null
  subscription_status: string | null
  replication_lag_seconds: number | null
  last_replicated_at: string | null
  tables_published: number
  is_healthy: boolean
}

type HealthStatus = 'healthy' | 'degraded' | 'unreachable' | 'unknown'
type ModalAction = 'promote' | 'demote' | null

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

async function safeFetch<T>(url: string, fallback: T): Promise<T> {
  try {
    const res = await apiClient.get<T>(url)
    return res.data
  } catch {
    return fallback
  }
}

function derivePeerHealth(history: HeartbeatHistoryEntry[]): HealthStatus {
  if (!Array.isArray(history) || history.length === 0) return 'unknown'
  const latest = history[0]
  if (latest?.peer_status === 'healthy') return 'healthy'
  if (latest?.peer_status === 'degraded') return 'degraded'
  return 'unreachable'
}

/** Badge tone for a node role. frontend-v2 Badge uses `warn`/`neutral`. */
function roleVariant(role: string) {
  if (role === 'primary') return 'success' as const
  if (role === 'standby') return 'warn' as const
  return 'neutral' as const
}

function formatLag(seconds: number | null): string {
  if (seconds == null) return '—'
  if (seconds < 1) return '< 1s'
  return `${seconds.toFixed(1)}s`
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString()
  } catch {
    return iso
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function HAStatusPanel() {
  const [identity, setIdentity] = useState<HAIdentity | null>(null)
  const [history, setHistory] = useState<HeartbeatHistoryEntry[]>([])
  const [replication, setReplication] = useState<ReplicationStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  // Confirmation modal state
  const [modalAction, setModalAction] = useState<ModalAction>(null)
  const [confirmText, setConfirmText] = useState('')
  const [reason, setReason] = useState('')
  const [force, setForce] = useState(false)

  const fetchData = useCallback(async () => {
    const [id, hist, repl] = await Promise.all([
      safeFetch<HAIdentity | null>('/ha/identity', null),
      safeFetch<HeartbeatHistoryEntry[]>('/ha/history', []),
      safeFetch<ReplicationStatus | null>('/ha/replication/status', null),
    ])
    setIdentity(id)
    setHistory(hist ?? [])
    setReplication(repl)
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10_000)
    return () => clearInterval(interval)
  }, [fetchData])

  /* ---- action handlers ---- */

  const openModal = (action: 'promote' | 'demote') => {
    setModalAction(action)
    setConfirmText('')
    setReason('')
    setForce(false)
    setActionError(null)
  }

  const closeModal = () => {
    setModalAction(null)
    setActionError(null)
  }

  const handleConfirm = async () => {
    if (!modalAction || confirmText !== 'CONFIRM') return
    setActionLoading(true)
    setActionError(null)
    try {
      if (modalAction === 'promote') {
        await apiClient.post('/ha/promote', {
          confirmation_text: 'CONFIRM',
          reason,
          force,
        })
      } else {
        await apiClient.post('/ha/demote', {
          confirmation_text: 'CONFIRM',
          reason,
        })
      }
      closeModal()
      await fetchData()
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Action failed'
      setActionError(msg)
    } finally {
      setActionLoading(false)
    }
  }

  /* ---- derived state ---- */

  const peerHealth = derivePeerHealth(history)
  const lagSeconds = replication?.replication_lag_seconds ?? null
  const showLagWarning = lagSeconds != null && lagSeconds > 30
  const showDisconnectedWarning =
    replication != null && !replication.is_healthy && replication.subscription_status === 'error'
  const showForceCheckbox = modalAction === 'promote' && lagSeconds != null && lagSeconds > 5

  /* ---- loading state ---- */

  if (loading) {
    return (
      <Card className="p-6">
        <Spinner label="Loading HA status" />
      </Card>
    )
  }

  if (!identity) {
    return (
      <Card className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-[15px] font-semibold text-text">HA Cluster Status</h3>
            <p className="mt-1 text-[13px] text-muted">
              High availability is not configured. Set up active-standby replication between two
              nodes.
            </p>
          </div>
          <Button href="/admin/ha-replication" size="sm">
            Configure HA
          </Button>
        </div>
      </Card>
    )
  }

  // Safe consumption: a malformed/empty identity object (no role) is treated as
  // "not configured" rather than crashing on identity.role.charAt below.
  if (!identity.role) return null

  const latestHeartbeat = history.length > 0 ? history[0] : null

  return (
    <Card className="space-y-4 p-6">
      {/* Header with current role */}
      <div className="flex items-center justify-between">
        <h3 className="text-[15px] font-semibold text-text">HA Cluster Status</h3>
        <div className="flex items-center gap-3">
          <Badge variant={roleVariant(identity.role)}>
            This node: {identity.role.charAt(0).toUpperCase() + identity.role.slice(1)}
          </Badge>
          <Link to="/admin/ha-replication" className="text-[12.5px] font-medium text-accent hover:underline">
            Manage →
          </Link>
        </div>
      </div>

      {/* Warning banners */}
      {showLagWarning && (
        <AlertBanner variant="warning" title="Replication Lagging">
          Replication lag is {formatLag(lagSeconds)} (threshold: 30s).
        </AlertBanner>
      )}
      {showDisconnectedWarning && (
        <AlertBanner variant="error" title="Replication Disconnected">
          Replication subscription is in error state. Consider triggering a re-sync.
        </AlertBanner>
      )}

      {/* Node cards */}
      <div className="grid gap-4 sm:grid-cols-2">
        {/* Local node */}
        <NodeCard
          name={identity.node_name}
          role={identity.role}
          health="healthy"
          syncStatus={replication?.subscription_status ?? 'not_configured'}
          lagSeconds={lagSeconds}
          lastHeartbeat={null}
          isLocal
        />

        {/* Peer node */}
        <NodeCard
          name="Peer Node"
          role={identity.role === 'primary' ? 'standby' : 'primary'}
          health={peerHealth}
          syncStatus={replication?.subscription_status ?? 'unknown'}
          lagSeconds={latestHeartbeat?.replication_lag_seconds ?? null}
          lastHeartbeat={latestHeartbeat?.timestamp ?? null}
          isLocal={false}
        />
      </div>

      {/* Action buttons */}
      <div className="flex gap-3">
        {identity.role === 'standby' && (
          <Button variant="primary" size="sm" onClick={() => openModal('promote')}>
            Promote to Primary
          </Button>
        )}
        {identity.role === 'primary' && (
          <Button variant="danger" size="sm" onClick={() => openModal('demote')}>
            Demote to Standby
          </Button>
        )}
      </div>

      {/* Confirmation modal (designed on-the-fly — Task 73 Modal not yet ported) */}
      {modalAction !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
          onClick={closeModal}
          role="dialog"
          aria-modal="true"
          aria-label={modalAction === 'promote' ? 'Promote to Primary' : 'Demote to Standby'}
        >
          <div
            className="w-full max-w-md rounded-card border border-border bg-card shadow-pop"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border px-5 py-[17px]">
              <h3 className="text-[15px] font-semibold text-text">
                {modalAction === 'promote' ? 'Promote to Primary' : 'Demote to Standby'}
              </h3>
              <button
                onClick={closeModal}
                className="rounded p-1 text-muted-2 transition-colors hover:bg-canvas hover:text-text"
                aria-label="Close"
                type="button"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4 p-5">
              <p className="text-[13px] text-muted">
                {modalAction === 'promote'
                  ? 'This will promote this standby node to primary. The node will begin accepting writes.'
                  : 'This will demote this primary node to standby. The node will stop accepting writes.'}
              </p>

              {actionError && <AlertBanner variant="error">{actionError}</AlertBanner>}

              <Input
                label="Reason"
                placeholder="e.g. Rolling update, maintenance"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />

              {showForceCheckbox && (
                <label className="flex items-center gap-2 text-[13px] text-warn">
                  <input
                    type="checkbox"
                    checked={force}
                    onChange={(e) => setForce(e.target.checked)}
                    className="rounded border-border-strong"
                  />
                  Force promotion (replication lag &gt; 5s — potential data loss)
                </label>
              )}

              <Input
                label='Type "CONFIRM" to proceed'
                placeholder="CONFIRM"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
              />

              <div className="flex justify-end gap-3 pt-2">
                <Button variant="ghost" size="sm" onClick={closeModal}>
                  Cancel
                </Button>
                <Button
                  variant={modalAction === 'promote' ? 'primary' : 'danger'}
                  size="sm"
                  disabled={confirmText !== 'CONFIRM' || !reason.trim()}
                  loading={actionLoading}
                  onClick={handleConfirm}
                >
                  {modalAction === 'promote' ? 'Promote' : 'Demote'}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/*  NodeCard sub-component                                             */
/* ------------------------------------------------------------------ */

const HEALTH_DOT: Record<HealthStatus, string> = {
  healthy: 'bg-ok',
  degraded: 'bg-warn',
  unreachable: 'bg-danger',
  unknown: 'bg-muted-2',
}

function NodeCard({
  name,
  role,
  health,
  syncStatus,
  lagSeconds,
  lastHeartbeat,
  isLocal,
}: {
  name: string
  role: string
  health: HealthStatus
  syncStatus: string
  lagSeconds: number | null
  lastHeartbeat: string | null
  isLocal: boolean
}) {
  return (
    <div className="space-y-2 rounded-ctl border border-border p-4">
      <div className="flex items-center justify-between">
        <span className="text-[13.5px] font-medium text-text">
          {name} {isLocal && <span className="text-[11px] text-muted">(local)</span>}
        </span>
        <Badge variant={roleVariant(role)}>{role.charAt(0).toUpperCase() + role.slice(1)}</Badge>
      </div>

      <div className="flex items-center gap-2">
        <span
          className={cx('inline-block h-2.5 w-2.5 rounded-full', HEALTH_DOT[health])}
          aria-label={`Health: ${health}`}
        />
        <span className="text-[13px] capitalize text-muted">{health}</span>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[13px] text-muted">
        <dt className="text-muted-2">Sync</dt>
        <dd>{syncStatus}</dd>
        <dt className="text-muted-2">Lag</dt>
        <dd className="mono">{formatLag(lagSeconds)}</dd>
        {lastHeartbeat && (
          <>
            <dt className="text-muted-2">Last heartbeat</dt>
            <dd className="mono">{formatTime(lastHeartbeat)}</dd>
          </>
        )}
      </dl>
    </div>
  )
}

export default HAStatusPanel
