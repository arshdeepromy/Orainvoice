import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'

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
  if (history.length === 0) return 'unknown'
  const latest = history[0]
  if (latest.peer_status === 'healthy') return 'healthy'
  if (latest.peer_status === 'degraded') return 'degraded'
  return 'unreachable'
}


function roleVariant(role: string) {
  if (role === 'primary') return 'success' as const
  if (role === 'standby') return 'warning' as const
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
    setHistory(hist)
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
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Action failed'
      setActionError(msg)
    } finally {
      setActionLoading(false)
    }
  }

  /* ---- derived state ---- */

  const peerHealth = derivePeerHealth(history)
  const lagSeconds = replication?.replication_lag_seconds ?? null
  const showLagWarning =
    lagSeconds != null && lagSeconds > 30
  const showDisconnectedWarning =
    replication != null && !replication.is_healthy && replication.subscription_status === 'error'
  const showForceCheckbox =
    modalAction === 'promote' && lagSeconds != null && lagSeconds > 5

  /* ---- loading state ---- */

  if (loading) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <Spinner label="Loading HA status" />
      </div>
    )
  }

  if (!identity) {
    return (
      <section className="rounded-lg border border-gray-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">HA Cluster Status</h3>
            <p className="mt-1 text-sm text-gray-500">
              High availability is not configured. Set up active-standby replication between two nodes.
            </p>
          </div>
          <Link
            to="/admin/ha-replication"
            className="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            Configure HA
          </Link>
        </div>
      </section>
    )
  }

  const latestHeartbeat = history.length > 0 ? history[0] : null

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
      {/* Header with current role */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-900">HA Cluster Status</h3>
        <div className="flex items-center gap-3">
          <Badge variant={roleVariant(identity.role)}>
            This node: {identity.role.charAt(0).toUpperCase() + identity.role.slice(1)}
          </Badge>
          <Link
            to="/admin/ha-replication"
            className="text-sm text-blue-600 hover:underline"
          >
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

      {/* Confirmation modal */}
      <Modal
        open={modalAction !== null}
        onClose={closeModal}
        title={modalAction === 'promote' ? 'Promote to Primary' : 'Demote to Standby'}
      >
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            {modalAction === 'promote'
              ? 'This will promote this standby node to primary. The node will begin accepting writes.'
              : 'This will demote this primary node to standby. The node will stop accepting writes.'}
          </p>

          {actionError && (
            <AlertBanner variant="error">{actionError}</AlertBanner>
          )}

          <Input
            label="Reason"
            placeholder="e.g. Rolling update, maintenance"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />

          {showForceCheckbox && (
            <label className="flex items-center gap-2 text-sm text-amber-700">
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
                className="rounded border-gray-300"
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
            <Button variant="secondary" size="sm" onClick={closeModal}>
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
      </Modal>
    </section>
  )
}

/* ------------------------------------------------------------------ */
/*  NodeCard sub-component                                             */
/* ------------------------------------------------------------------ */

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
    <div className="rounded-md border border-gray-200 p-4 space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-medium text-gray-900">
          {name} {isLocal && <span className="text-xs text-gray-500">(local)</span>}
        </span>
        <Badge variant={roleVariant(role)}>
          {role.charAt(0).toUpperCase() + role.slice(1)}
        </Badge>
      </div>

      <div className="flex items-center gap-2">
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${
            health === 'healthy'
              ? 'bg-green-500'
              : health === 'degraded'
                ? 'bg-amber-500'
                : health === 'unreachable'
                  ? 'bg-red-500'
                  : 'bg-gray-400'
          }`}
          aria-label={`Health: ${health}`}
        />
        <span className="text-sm text-gray-600 capitalize">{health}</span>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-gray-600">
        <dt className="text-gray-500">Sync</dt>
        <dd>{syncStatus}</dd>
        <dt className="text-gray-500">Lag</dt>
        <dd>{formatLag(lagSeconds)}</dd>
        {lastHeartbeat && (
          <>
            <dt className="text-gray-500">Last heartbeat</dt>
            <dd>{formatTime(lastHeartbeat)}</dd>
          </>
        )}
      </dl>
    </div>
  )
}
