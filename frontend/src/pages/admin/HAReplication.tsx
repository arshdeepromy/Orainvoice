import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Modal } from '@/components/ui/Modal'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface HAConfig {
  node_id: string
  node_name: string
  role: string
  peer_endpoint: string
  auto_promote_enabled: boolean
  heartbeat_interval_seconds: number
  failover_timeout_seconds: number
  maintenance_mode: boolean
  created_at: string
  updated_at: string
  peer_db_host: string | null
  peer_db_port: number | null
  peer_db_name: string | null
  peer_db_user: string | null
  peer_db_configured: boolean
  peer_db_sslmode: string | null
  heartbeat_secret_configured: boolean
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

interface FailoverStatus {
  auto_promote_enabled: boolean
  peer_unreachable_seconds: number | null
  failover_timeout_seconds: number
  seconds_until_auto_promote: number | null
  split_brain_detected: boolean
  is_stale_primary: boolean
  promoted_at: string | null
}

type ModalAction = 'promote' | 'demote' | 'init-replication' | 'stop-replication' | 'resync' | 'maintenance-enter' | 'maintenance-exit' | 'demote-and-sync' | null

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
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

/* ------------------------------------------------------------------ */
/*  Setup Guide Component                                              */
/* ------------------------------------------------------------------ */

function SetupGuide({ configured }: { configured: boolean }) {
  const [open, setOpen] = useState(!configured)

  return (
    <section className="rounded-lg border border-blue-200 bg-blue-50">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-6 py-4 text-left"
      >
        <span className="text-sm font-medium text-blue-900">
          {configured ? 'HA Setup Guide' : 'Getting Started — HA Setup Guide'}
        </span>
        <svg
          className={`h-5 w-5 text-blue-600 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="border-t border-blue-200 px-6 pb-5 pt-4 text-sm text-blue-900 space-y-4">
          <div>
            <p className="font-medium mb-2">Prerequisites</p>
            <ul className="list-disc pl-5 space-y-1 text-blue-800">
              <li>Both nodes must be reachable via LAN IPs through VPN (or <code className="bg-blue-100 px-1 rounded">host.docker.internal</code> for local dev)</li>
              <li>PostgreSQL port must be accessible from the peer node — verify with <code className="bg-blue-100 px-1 rounded">pg_isready</code> or a test connection</li>
              <li>Both nodes must have <code className="bg-blue-100 px-1 rounded">wal_level=logical</code> set in PostgreSQL</li>
              <li>The <strong>Heartbeat Secret</strong> field in Node Configuration must be identical on both nodes</li>
              <li><code className="bg-blue-100 px-1 rounded">JWT_SECRET</code> and <code className="bg-blue-100 px-1 rounded">ENCRYPTION_MASTER_KEY</code> must be identical so tokens work across nodes</li>
              <li>The standby database must have the schema (migrations) but <span className="font-semibold">no seed data</span> — all data comes from replication</li>
            </ul>
          </div>

          <div>
            <p className="font-medium mb-2">Step 1 — Configure the Primary Node</p>
            <ol className="list-decimal pl-5 space-y-1 text-blue-800">
              <li>Set Node Name, Role = <span className="font-semibold">Primary</span>, and the Peer Endpoint (standby's HTTP URL)</li>
              <li>Click <span className="font-semibold">Save Configuration</span></li>
              <li>Click <span className="font-semibold">Initialize Replication</span> — this creates the PostgreSQL publication</li>
            </ol>
          </div>

          <div>
            <p className="font-medium mb-2">Step 2 — Configure the Standby Node</p>
            <ol className="list-decimal pl-5 space-y-1 text-blue-800">
              <li>Set Node Name, Role = <span className="font-semibold">Standby</span>, and the Peer Endpoint (primary's HTTP URL)</li>
              <li>Optionally enable <span className="font-semibold">Auto-promote</span> for automatic failover</li>
              <li>Click <span className="font-semibold">Save Configuration</span></li>
              <li>Click <span className="font-semibold">Initialize Replication</span> — this creates the subscription and starts the initial data sync</li>
            </ol>
          </div>

          <div>
            <p className="font-medium mb-2">Step 3 — Verify</p>
            <ul className="list-disc pl-5 space-y-1 text-blue-800">
              <li>Heartbeat should show <span className="text-green-700 font-semibold">healthy</span> on both nodes</li>
              <li>Replication Details should show the subscription as <span className="font-semibold">active</span> with low lag</li>
              <li>Create a test record on the primary and verify it appears on the standby</li>
            </ul>
          </div>

          <div className="rounded-md bg-amber-50 border border-amber-200 p-3">
            <p className="font-medium text-amber-900 mb-1">Security Notes</p>
            <ul className="list-disc pl-5 space-y-1 text-amber-800">
              <li>Generate SSL certificates with <code className="bg-amber-100 px-1 rounded">bash scripts/generate_pg_certs.sh</code> and set SSL Mode to <code className="bg-amber-100 px-1 rounded">require</code> in Peer Database Settings</li>
              <li>In production, create a dedicated replication user via the "Replication User" section below (not the superuser)</li>
              <li>Restrict <code className="bg-amber-100 px-1 rounded">pg_hba.conf</code> to only allow the peer's specific IP address</li>
              <li>The peer DB password is encrypted at rest — but protect your <code className="bg-amber-100 px-1 rounded">.env</code> files too</li>
              <li>Rotate the <strong>Heartbeat Secret</strong> periodically by updating both nodes simultaneously via the GUI</li>
            </ul>
          </div>

          <div className="rounded-md bg-gray-50 border border-gray-200 p-3">
            <p className="font-medium text-gray-900 mb-1">Failover Procedure</p>
            <ol className="list-decimal pl-5 space-y-1 text-gray-700">
              <li>If the primary goes down, promote the standby using the <span className="font-semibold">Promote to Primary</span> button</li>
              <li>Update DNS or reverse proxy to point traffic to the new primary</li>
              <li>When the old primary comes back, configure it as Standby and click <span className="font-semibold">Initialize Replication</span> to sync from the new primary</li>
              <li>If the old primary has stale data, use <span className="font-semibold">Trigger Re-sync</span> for a full data copy</li>
            </ol>
          </div>
        </div>
      )}
    </section>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Page Component                                                */
/* ------------------------------------------------------------------ */

export function HAReplication() {
  const [config, setConfig] = useState<HAConfig | null>(null)
  const [history, setHistory] = useState<HeartbeatHistoryEntry[]>([])
  const [replication, setReplication] = useState<ReplicationStatus | null>(null)
  const [failoverStatus, setFailoverStatus] = useState<FailoverStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)

  // Config form state
  const [formNodeName, setFormNodeName] = useState('')
  const [formRole, setFormRole] = useState('standalone')
  const [formPeerEndpoint, setFormPeerEndpoint] = useState('')
  const [formAutoPromote, setFormAutoPromote] = useState(false)
  const [formHeartbeatInterval, setFormHeartbeatInterval] = useState(10)
  const [formFailoverTimeout, setFormFailoverTimeout] = useState(90)

  // Peer DB form state
  const [formPeerDbHost, setFormPeerDbHost] = useState('')
  const [formPeerDbPort, setFormPeerDbPort] = useState(5432)
  const [formPeerDbName, setFormPeerDbName] = useState('')
  const [formPeerDbUser, setFormPeerDbUser] = useState('')
  const [formPeerDbPassword, setFormPeerDbPassword] = useState('')
  const [formPeerDbSslmode, setFormPeerDbSslmode] = useState('disable')
  const [formHeartbeatSecret, setFormHeartbeatSecret] = useState('')
  const [testingConnection, setTestingConnection] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  // Replication user state
  const [replUserName, setReplUserName] = useState('replicator')
  const [replUserPassword, setReplUserPassword] = useState('')
  const [creatingReplUser, setCreatingReplUser] = useState(false)
  const [replUserResult, setReplUserResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [replConnectionInfo, setReplConnectionInfo] = useState<{
    host: string; port: number; dbname: string; user: string; password: string; ssl_enabled: boolean; connection_string: string
  } | null>(null)
  const [showReplInfoModal, setShowReplInfoModal] = useState(false)
  const [fetchingDbInfo, setFetchingDbInfo] = useState(false)

  // Action modal state
  const [modalAction, setModalAction] = useState<ModalAction>(null)
  const [confirmText, setConfirmText] = useState('')
  const [reason, setReason] = useState('')
  const [force, setForce] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)

  // Replication slots state
  const [slots, setSlots] = useState<{ slot_name: string; slot_type: string; active: boolean; retained_wal: string | null; active_pid: number | null; idle_seconds: number | null }[]>([])
  const [droppingSlot, setDroppingSlot] = useState<string | null>(null)

  // New Standby Setup Wizard state
  const [wizardOpen, setWizardOpen] = useState(false)
  const [wizardStep, setWizardStep] = useState(0) // 0-3
  const [wizardStepComplete, setWizardStepComplete] = useState([false, false, false, false])
  const [wizardSaving, setWizardSaving] = useState(false)
  const [wizardSaveError, setWizardSaveError] = useState<string | null>(null)
  const [wizardTestResult, setWizardTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [wizardTestingConnection, setWizardTestingConnection] = useState(false)
  const [wizardReplUserName, setWizardReplUserName] = useState('replicator')
  const [wizardReplUserPassword, setWizardReplUserPassword] = useState('')
  const [wizardCreatingReplUser, setWizardCreatingReplUser] = useState(false)
  const [wizardReplUserResult, setWizardReplUserResult] = useState<{ ok: boolean; message: string } | null>(null)

  // Track whether initial form state has been populated
  const [formInitialized, setFormInitialized] = useState(false)

  const fetchData = useCallback(async () => {
    const [cfg, hist, repl, slotsData, failover] = await Promise.all([
      safeFetch<HAConfig | null>('/ha/identity', null),
      safeFetch<HeartbeatHistoryEntry[]>('/ha/history', []),
      safeFetch<ReplicationStatus | null>('/ha/replication/status', null),
      safeFetch<{ slots: typeof slots }>('/ha/replication/slots', { slots: [] }),
      safeFetch<FailoverStatus | null>('/ha/failover-status', null),
    ])
    setConfig(cfg)
    setHistory(hist)
    setReplication(repl)
    setSlots(slotsData?.slots ?? [])
    setFailoverStatus(failover)
    // Only populate form fields on initial load — not on polling refreshes
    if (cfg && !formInitialized) {
      setFormNodeName(cfg.node_name)
      setFormRole(cfg.role)
      setFormPeerEndpoint(cfg.peer_endpoint || '')
      setFormAutoPromote(cfg.auto_promote_enabled)
      setFormHeartbeatInterval(cfg.heartbeat_interval_seconds)
      setFormFailoverTimeout(cfg.failover_timeout_seconds)
      setFormPeerDbHost(cfg.peer_db_host || '')
      setFormPeerDbPort(cfg.peer_db_port || 5432)
      setFormPeerDbName(cfg.peer_db_name || '')
      setFormPeerDbUser(cfg.peer_db_user || '')
      setFormPeerDbSslmode(cfg.peer_db_sslmode || 'disable')
      setFormInitialized(true)
    }
    setLoading(false)
  }, [formInitialized])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10_000)
    return () => clearInterval(interval)
  }, [fetchData])

  /* ---- Save config ---- */
  const handleSaveConfig = async () => {
    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)
    try {
      await apiClient.put('/ha/configure', {
        node_name: formNodeName,
        role: formRole,
        peer_endpoint: formPeerEndpoint,
        auto_promote_enabled: formAutoPromote,
        heartbeat_interval_seconds: formHeartbeatInterval,
        failover_timeout_seconds: formFailoverTimeout,
        peer_db_host: formPeerDbHost || null,
        peer_db_port: formPeerDbPort,
        peer_db_name: formPeerDbName || null,
        peer_db_user: formPeerDbUser || null,
        peer_db_password: formPeerDbPassword || null,
        peer_db_sslmode: formPeerDbSslmode,
        heartbeat_secret: formHeartbeatSecret || null,
      })
      setSaveSuccess(true)
      // Re-sync form from server after save
      setFormInitialized(false)
      await fetchData()
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to save configuration'
      setSaveError(msg)
    } finally {
      setSaving(false)
    }
  }

  /* ---- Action handlers ---- */
  const openModal = (action: ModalAction) => {
    setModalAction(action)
    setConfirmText('')
    setReason('')
    setForce(false)
    setActionError(null)
    setActionSuccess(null)
  }

  const closeModal = () => {
    setModalAction(null)
    setActionError(null)
  }

  const handleAction = async () => {
    if (!modalAction) return
    const needsConfirm = ['promote', 'demote', 'resync', 'stop-replication', 'demote-and-sync'].includes(modalAction)
      || (modalAction === 'init-replication' && config?.role === 'standby')
    if (needsConfirm && confirmText !== 'CONFIRM') return

    setActionLoading(true)
    setActionError(null)
    try {
      switch (modalAction) {
        case 'promote':
          await apiClient.post('/ha/promote', { confirmation_text: 'CONFIRM', reason, force })
          break
        case 'demote':
          await apiClient.post('/ha/demote', { confirmation_text: 'CONFIRM', reason })
          break
        case 'init-replication':
          if (config?.role === 'standby') {
            await apiClient.post('/ha/replication/init', null, { params: { truncate_first: true } })
          } else {
            await apiClient.post('/ha/replication/init')
          }
          break
        case 'stop-replication':
          await apiClient.post('/ha/replication/stop')
          break
        case 'resync':
          await apiClient.post('/ha/replication/resync')
          break
        case 'maintenance-enter':
          await apiClient.post('/ha/maintenance-mode')
          break
        case 'maintenance-exit':
          await apiClient.post('/ha/ready')
          break
        case 'demote-and-sync':
          await apiClient.post('/ha/demote-and-sync', { confirmation_text: 'CONFIRM', reason })
          break
      }
      closeModal()
      setActionSuccess(`${modalAction} completed successfully`)
      setTimeout(() => setActionSuccess(null), 4000)
      await fetchData()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Action failed'
      setActionError(msg)
    } finally {
      setActionLoading(false)
    }
  }

  /* ---- Test peer DB connection ---- */
  const handleTestConnection = async () => {
    if (!formPeerDbHost || !formPeerDbName || !formPeerDbUser || !formPeerDbPassword) return
    setTestingConnection(true)
    setTestResult(null)
    try {
      const res = await apiClient.post('/ha/test-db-connection', {
        host: formPeerDbHost,
        port: formPeerDbPort,
        dbname: formPeerDbName,
        user: formPeerDbUser,
        password: formPeerDbPassword,
        sslmode: formPeerDbSslmode,
      })
      const data = res.data as { message?: string; wal_level?: string; replication_ready?: boolean; ssl_active?: boolean }
      let msg = data.replication_ready
        ? `${data.message} (wal_level=${data.wal_level})`
        : `${data.message} — WARNING: wal_level=${data.wal_level} (needs "logical" for replication)`
      if (data.ssl_active) msg += ' — SSL active ✓'
      else if (formPeerDbSslmode !== 'disable') msg += ' — SSL not active ✗'
      setTestResult({ ok: true, message: msg })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Connection test failed'
      setTestResult({ ok: false, message: msg })
    } finally {
      setTestingConnection(false)
    }
  }

  /* ---- Drop replication slot ---- */
  const handleDropSlot = async (slotName: string) => {
    if (!confirm(`Drop replication slot "${slotName}"? This cannot be undone.`)) return
    setDroppingSlot(slotName)
    try {
      await apiClient.delete(`/ha/replication/slots/${slotName}`)
      setActionSuccess(`Slot "${slotName}" dropped successfully`)
      setTimeout(() => setActionSuccess(null), 4000)
      await fetchData()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to drop slot'
      setActionError(msg)
      setTimeout(() => setActionError(null), 5000)
    } finally {
      setDroppingSlot(null)
    }
  }

  /* ---- Create replication user ---- */
  const handleCreateReplUser = async () => {
    if (!replUserPassword) return
    setCreatingReplUser(true)
    setReplUserResult(null)
    setReplConnectionInfo(null)
    try {
      const res = await apiClient.post('/ha/create-replication-user', {
        username: replUserName,
        password: replUserPassword,
      })
      const data = res.data as {
        message?: string
        connection_info?: {
          host: string; port: number; dbname: string; user: string
          ssl_enabled: boolean; connection_string: string
        }
      }
      setReplUserResult({ ok: true, message: data.message || 'User created' })
      if (data.connection_info) {
        // Replace <password> placeholder with the actual password for the modal
        const connStr = data.connection_info.connection_string.replace('<password>', replUserPassword)
        setReplConnectionInfo({
          ...data.connection_info,
          password: replUserPassword,
          connection_string: connStr,
        })
        setShowReplInfoModal(true)
      }
      setReplUserPassword('')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create user'
      setReplUserResult({ ok: false, message: msg })
    } finally {
      setCreatingReplUser(false)
    }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
  }

  const copyAllReplInfo = () => {
    if (!replConnectionInfo) return
    const lines = [
      `Host: ${replConnectionInfo.host}`,
      `Port: ${replConnectionInfo.port}`,
      `Database: ${replConnectionInfo.dbname}`,
      `User: ${replConnectionInfo.user}`,
      `Password: ${replConnectionInfo.password}`,
      `SSL Mode: ${replConnectionInfo.ssl_enabled ? 'require' : 'disable'}`,
      ``,
      `Connection String: ${replConnectionInfo.connection_string}`,
    ].join('\n')
    navigator.clipboard.writeText(lines)
  }

  const handleViewConnectionInfo = async () => {
    setFetchingDbInfo(true)
    try {
      const res = await apiClient.get('/ha/local-db-info')
      const data = res.data as { lan_ip: string; pg_port: number; db_name: string; ssl_enabled: boolean }
      const user = replUserName || 'replicator'
      const sslSuffix = data.ssl_enabled ? '?sslmode=require' : ''
      setReplConnectionInfo({
        host: data.lan_ip,
        port: data.pg_port,
        dbname: data.db_name,
        user,
        password: '(set when user was created)',
        ssl_enabled: data.ssl_enabled,
        connection_string: `postgresql://${user}:<password>@${data.lan_ip}:${data.pg_port}/${data.db_name}${sslSuffix}`,
      })
      setShowReplInfoModal(true)
    } catch {
      setReplUserResult({ ok: false, message: 'Failed to fetch local database info' })
    } finally {
      setFetchingDbInfo(false)
    }
  }

  /* ---- Wizard handlers ---- */
  const handleWizardSaveConfig = async () => {
    setWizardSaving(true)
    setWizardSaveError(null)
    try {
      await apiClient.put('/ha/configure', {
        node_name: formNodeName,
        role: formRole,
        peer_endpoint: formPeerEndpoint,
        auto_promote_enabled: formAutoPromote,
        heartbeat_interval_seconds: formHeartbeatInterval,
        failover_timeout_seconds: formFailoverTimeout,
        peer_db_host: formPeerDbHost || null,
        peer_db_port: formPeerDbPort,
        peer_db_name: formPeerDbName || null,
        peer_db_user: formPeerDbUser || null,
        peer_db_password: formPeerDbPassword || null,
        peer_db_sslmode: formPeerDbSslmode,
        heartbeat_secret: formHeartbeatSecret || null,
      })
      setWizardStepComplete(prev => {
        const next = [...prev]
        next[0] = true
        return next
      })
      setWizardStep(1)
      setFormInitialized(false)
      await fetchData()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to save configuration'
      setWizardSaveError(msg)
    } finally {
      setWizardSaving(false)
    }
  }

  const handleWizardTestConnection = async () => {
    if (!formPeerDbHost || !formPeerDbName || !formPeerDbUser || !formPeerDbPassword) return
    setWizardTestingConnection(true)
    setWizardTestResult(null)
    try {
      const res = await apiClient.post('/ha/test-db-connection', {
        host: formPeerDbHost,
        port: formPeerDbPort,
        dbname: formPeerDbName,
        user: formPeerDbUser,
        password: formPeerDbPassword,
        sslmode: formPeerDbSslmode,
      })
      const data = res.data as { message?: string; wal_level?: string; replication_ready?: boolean; ssl_active?: boolean }
      let msg = data?.replication_ready
        ? `${data?.message ?? 'Connected'} (wal_level=${data?.wal_level ?? 'unknown'})`
        : `${data?.message ?? 'Connected'} — WARNING: wal_level=${data?.wal_level ?? 'unknown'} (needs "logical" for replication)`
      if (data?.ssl_active) msg += ' — SSL active ✓'
      else if (formPeerDbSslmode !== 'disable') msg += ' — SSL not active ✗'
      setWizardTestResult({ ok: true, message: msg })
      setWizardStepComplete(prev => {
        const next = [...prev]
        next[1] = true
        return next
      })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Connection test failed'
      setWizardTestResult({ ok: false, message: msg })
    } finally {
      setWizardTestingConnection(false)
    }
  }

  const handleWizardCreateReplUser = async () => {
    if (!wizardReplUserPassword) return
    setWizardCreatingReplUser(true)
    setWizardReplUserResult(null)
    try {
      const res = await apiClient.post('/ha/create-replication-user', {
        username: wizardReplUserName,
        password: wizardReplUserPassword,
      })
      const data = res.data as { message?: string }
      setWizardReplUserResult({ ok: true, message: data?.message ?? 'User created' })
      setWizardStepComplete(prev => {
        const next = [...prev]
        next[2] = true
        return next
      })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create user'
      setWizardReplUserResult({ ok: false, message: msg })
    } finally {
      setWizardCreatingReplUser(false)
    }
  }

  const handleWizardDone = () => {
    setWizardOpen(false)
    setWizardStep(0)
    setWizardStepComplete([false, false, false, false])
    setWizardSaveError(null)
    setWizardTestResult(null)
    setWizardReplUserResult(null)
    setWizardReplUserPassword('')
  }

  // Determine if the suggestion banner should show
  const peerPermanentlyUnreachable =
    config?.role === 'primary' &&
    (failoverStatus?.peer_unreachable_seconds ?? 0) > 300

  /* ---- Derived state ---- */
  const peerHealth = history.length > 0 ? history[0].peer_status : 'unknown'
  const lagSeconds = replication?.replication_lag_seconds ?? null
  const isStandbyInit = modalAction === 'init-replication' && config?.role === 'standby'
  const isDemoteAndSync = modalAction === 'demote-and-sync'
  const needsConfirmText = modalAction && (['promote', 'demote', 'resync', 'demote-and-sync'].includes(modalAction) || isStandbyInit)
  const showForceCheckbox = modalAction === 'promote' && lagSeconds != null && lagSeconds > 5

  const modalTitles: Record<string, string> = {
    promote: 'Promote to Primary',
    demote: 'Demote to Standby',
    'init-replication': 'Initialize Replication',
    'stop-replication': 'Stop Replication',
    resync: 'Trigger Full Re-sync',
    'maintenance-enter': 'Enter Maintenance Mode',
    'maintenance-exit': 'Exit Maintenance Mode',
    'demote-and-sync': 'Role Conflict Detected',
  }

  const modalDescriptions: Record<string, string> = {
    promote: 'This will promote this standby node to primary. It will begin accepting writes.',
    demote: 'This will demote this primary node to standby. It will stop accepting writes.',
    'init-replication': config?.role === 'standby'
      ? 'This will replace ALL local data with data from the primary. Local users, organisations, and all business data will be overwritten. You will not be able to log in with local credentials after this.'
      : 'This will initialize PostgreSQL logical replication. Run this after configuring both nodes.',
    'stop-replication': 'This will stop replication by dropping the publication (primary) or subscription (standby). You can re-initialize later.',
    resync: 'This will drop and re-create the replication subscription with a full data copy. Use when replication is broken.',
    'maintenance-enter': 'This will put the node in maintenance mode. Heartbeat checks will report maintenance status.',
    'maintenance-exit': 'This will take the node out of maintenance mode and resume normal operation.',
    'demote-and-sync': 'This node was previously primary but another node has been promoted more recently. To restore the cluster to a healthy state, this node will be demoted to standby and will sync all data from the new primary.',
  }

  if (loading) {
    return (
      <div className="py-20">
        <Spinner size="lg" label="Loading HA configuration" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">HA Replication</h1>
        {config && (
          <Badge variant={roleVariant(config.role)}>
            {config.role.charAt(0).toUpperCase() + config.role.slice(1)}
          </Badge>
        )}
      </div>

      {actionSuccess && (
        <AlertBanner variant="success">{actionSuccess}</AlertBanner>
      )}

      {/* ── Setup Guide (collapsible) ── */}
      <SetupGuide configured={!!config} />

      {/* ── New Standby Setup Wizard — Suggestion Banner ── */}
      {peerPermanentlyUnreachable && !wizardOpen && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-5 py-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-amber-900">
                Peer node appears permanently unreachable. Would you like to set up a new standby?
              </p>
              <p className="mt-1 text-xs text-amber-700">
                The peer has been unreachable for {Math.round(failoverStatus?.peer_unreachable_seconds ?? 0)} seconds ({Math.round((failoverStatus?.peer_unreachable_seconds ?? 0) / 60)} minutes).
              </p>
            </div>
            <Button
              variant="primary"
              size="sm"
              onClick={() => setWizardOpen(true)}
            >
              Set Up New Standby
            </Button>
          </div>
        </div>
      )}

      {/* ── New Standby Setup Wizard ── */}
      {wizardOpen && (
        <section className="rounded-lg border-2 border-blue-300 bg-white p-6 space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-medium text-gray-900">New Standby Setup Wizard</h2>
            <button
              type="button"
              onClick={handleWizardDone}
              className="rounded p-1 text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              aria-label="Close wizard"
            >
              <span aria-hidden="true" className="text-xl leading-none">×</span>
            </button>
          </div>

          {/* Step indicator */}
          <div className="flex items-center gap-2">
            {['Peer DB Config', 'Test Connection', 'Replication User', 'Summary'].map((label, i) => (
              <div key={label} className="flex items-center gap-2">
                {i > 0 && (
                  <div className={`h-px w-6 ${i <= wizardStep ? 'bg-blue-400' : 'bg-gray-200'}`} />
                )}
                <div className="flex items-center gap-1.5">
                  <span
                    className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium ${
                      wizardStepComplete[i]
                        ? 'bg-green-100 text-green-700'
                        : i === wizardStep
                          ? 'bg-blue-100 text-blue-700'
                          : 'bg-gray-100 text-gray-500'
                    }`}
                  >
                    {wizardStepComplete[i] ? '✓' : i + 1}
                  </span>
                  <span className={`text-xs ${i === wizardStep ? 'font-medium text-gray-900' : 'text-gray-500'}`}>
                    {label}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Step 0: Configure peer database connection */}
          {wizardStep === 0 && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">
                Enter the new standby node's PostgreSQL connection details. These will be saved to your configuration.
              </p>

              {wizardSaveError && (
                <AlertBanner variant="error">{wizardSaveError}</AlertBanner>
              )}

              <div className="grid gap-4 sm:grid-cols-2">
                <Input
                  label="Host"
                  placeholder="e.g. host.docker.internal or 192.168.1.x"
                  value={formPeerDbHost}
                  onChange={(e) => setFormPeerDbHost(e.target.value)}
                />
                <Input
                  label="Port"
                  type="number"
                  value={String(formPeerDbPort)}
                  onChange={(e) => setFormPeerDbPort(Number(e.target.value) || 5432)}
                />
                <Input
                  label="Database Name"
                  placeholder="e.g. workshoppro"
                  value={formPeerDbName}
                  onChange={(e) => setFormPeerDbName(e.target.value)}
                />
                <Input
                  label="User"
                  placeholder="e.g. postgres"
                  value={formPeerDbUser}
                  onChange={(e) => setFormPeerDbUser(e.target.value)}
                />
                <Input
                  label="Password"
                  type="password"
                  placeholder="Enter password"
                  value={formPeerDbPassword}
                  onChange={(e) => setFormPeerDbPassword(e.target.value)}
                />
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">SSL Mode</label>
                  <select
                    value={formPeerDbSslmode}
                    onChange={(e) => setFormPeerDbSslmode(e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="disable">Disable (no SSL)</option>
                    <option value="require">Require (encrypted, no cert verification)</option>
                    <option value="verify-ca">Verify CA (encrypted + verify server cert)</option>
                    <option value="verify-full">Verify Full (encrypted + verify cert + hostname)</option>
                  </select>
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={async () => {
                    await handleWizardSaveConfig()
                  }}
                  loading={wizardSaving}
                  disabled={!formPeerDbHost || !formPeerDbName || !formPeerDbUser || !formPeerDbPassword}
                >
                  Save & Next
                </Button>
              </div>
            </div>
          )}

          {/* Step 1: Test connection */}
          {wizardStep === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">
                Test the connection to the peer database. The connection must succeed before you can proceed.
              </p>

              {wizardTestResult && (
                <AlertBanner variant={wizardTestResult.ok ? 'success' : 'error'}>
                  {wizardTestResult.message}
                </AlertBanner>
              )}

              <div className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700 space-y-1">
                <p><span className="font-medium">Host:</span> {formPeerDbHost}:{formPeerDbPort}</p>
                <p><span className="font-medium">Database:</span> {formPeerDbName}</p>
                <p><span className="font-medium">User:</span> {formPeerDbUser}</p>
                <p><span className="font-medium">SSL Mode:</span> {formPeerDbSslmode}</p>
              </div>

              <div className="flex justify-between gap-3 pt-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setWizardStep(0)
                    setWizardTestResult(null)
                  }}
                >
                  Back
                </Button>
                <div className="flex gap-3">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleWizardTestConnection}
                    loading={wizardTestingConnection}
                  >
                    Test Connection
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => setWizardStep(2)}
                    disabled={!wizardStepComplete[1]}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Step 2: Create replication user */}
          {wizardStep === 2 && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">
                Create a dedicated PostgreSQL user with replication privileges on this node's database.
                The new standby will use these credentials to connect.
              </p>

              {wizardReplUserResult && (
                <AlertBanner variant={wizardReplUserResult.ok ? 'success' : 'error'}>
                  {wizardReplUserResult.message}
                </AlertBanner>
              )}

              <div className="grid gap-4 sm:grid-cols-2">
                <Input
                  label="Username"
                  placeholder="replicator"
                  value={wizardReplUserName}
                  onChange={(e) => setWizardReplUserName(e.target.value)}
                />
                <Input
                  label="Password"
                  type="password"
                  placeholder="Strong password for replication user"
                  value={wizardReplUserPassword}
                  onChange={(e) => setWizardReplUserPassword(e.target.value)}
                />
              </div>

              <div className="flex justify-between gap-3 pt-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setWizardStep(1)
                    setWizardReplUserResult(null)
                  }}
                >
                  Back
                </Button>
                <div className="flex gap-3">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleWizardCreateReplUser}
                    loading={wizardCreatingReplUser}
                    disabled={!wizardReplUserName.trim() || !wizardReplUserPassword}
                  >
                    Create User
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => {
                      setWizardStepComplete(prev => {
                        const next = [...prev]
                        next[3] = true
                        return next
                      })
                      setWizardStep(3)
                    }}
                    disabled={!wizardStepComplete[2]}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Step 3: Summary */}
          {wizardStep === 3 && (
            <div className="space-y-4">
              <div className="rounded-md border border-green-200 bg-green-50 p-4">
                <p className="text-sm font-medium text-green-800 mb-2">Setup Complete — Next Steps</p>
                <ol className="list-decimal pl-5 space-y-2 text-sm text-green-800">
                  <li>Go to the new standby node's HA page</li>
                  <li>Configure it as <span className="font-semibold">Standby</span> with this node as the peer</li>
                  <li>Enter the replication user credentials in the Peer Database Settings</li>
                  <li>Click <span className="font-semibold">Initialize Replication</span></li>
                </ol>
              </div>

              <div className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700 space-y-1">
                <p className="font-medium text-gray-900 mb-2">Connection Details for the New Standby</p>
                <p><span className="font-medium">Peer Endpoint:</span> {formPeerEndpoint || '(configure in Node Configuration above)'}</p>
                <p><span className="font-medium">Replication User:</span> {wizardReplUserName}</p>
                <p><span className="font-medium">Database Host:</span> {formPeerDbHost}:{formPeerDbPort}</p>
                <p><span className="font-medium">Database Name:</span> {formPeerDbName}</p>
              </div>

              <div className="flex justify-between gap-3 pt-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setWizardStep(2)}
                >
                  Back
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleWizardDone}
                >
                  Done
                </Button>
              </div>
            </div>
          )}
        </section>
      )}

      {/* ── Configuration Form ── */}
      <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
        <h2 className="text-lg font-medium text-gray-900">
          {config ? 'Node Configuration' : 'Configure HA'}
        </h2>
        {!config && (
          <p className="text-sm text-gray-500">
            HA is not configured yet. Fill in the details below to set up this node.
          </p>
        )}

        {saveError && <AlertBanner variant="error">{saveError}</AlertBanner>}
        {saveSuccess && <AlertBanner variant="success">Configuration saved</AlertBanner>}

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Node Name"
            placeholder="e.g. Pi-Main"
            value={formNodeName}
            onChange={(e) => setFormNodeName(e.target.value)}
          />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
            <select
              value={formRole}
              onChange={(e) => setFormRole(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            >
              <option value="standalone">Standalone</option>
              <option value="primary">Primary</option>
              <option value="standby">Standby</option>
            </select>
          </div>
          <Input
            label="Peer Endpoint"
            placeholder="http://192.168.x.x:8999"
            value={formPeerEndpoint}
            onChange={(e) => setFormPeerEndpoint(e.target.value)}
          />
          <Input
            label="Heartbeat Interval (seconds)"
            type="number"
            value={String(formHeartbeatInterval)}
            onChange={(e) => setFormHeartbeatInterval(Number(e.target.value) || 10)}
          />
          <Input
            label="Failover Timeout (seconds)"
            type="number"
            value={String(formFailoverTimeout)}
            onChange={(e) => setFormFailoverTimeout(Number(e.target.value) || 90)}
          />
          <label className="flex items-center gap-2 text-sm text-gray-700 sm:col-span-2 pt-2">
            <input
              type="checkbox"
              checked={formAutoPromote}
              onChange={(e) => setFormAutoPromote(e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Enable auto-promote (standby auto-promotes when primary is unreachable)
          </label>
          <p className="text-xs text-amber-700 sm:col-span-2 -mt-1 pl-6">
            Note: If the primary is also unreachable by the standby (full partition), split-brain detection will be inactive until connectivity is restored.
          </p>
          <div className="sm:col-span-2">
            <Input
              label="Heartbeat Secret"
              type="password"
              placeholder={config?.heartbeat_secret_configured ? '••••••••  (leave blank to keep existing)' : 'Shared HMAC secret for heartbeat signing'}
              value={formHeartbeatSecret}
              onChange={(e) => setFormHeartbeatSecret(e.target.value)}
              helperText={config?.heartbeat_secret_configured
                ? '✓ Secret stored — leave blank to keep existing value. Must be identical on both nodes.'
                : 'Required for secure heartbeat signing. Must be identical on both nodes.'}
            />
          </div>
        </div>

        <div className="flex justify-end pt-2">
          <Button
            onClick={handleSaveConfig}
            loading={saving}
            disabled={!formNodeName.trim()}
          >
            {config ? 'Update Configuration' : 'Save Configuration'}
          </Button>
        </div>
      </section>

      {/* ── Peer Database Settings ── */}
      <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
        <h2 className="text-lg font-medium text-gray-900">Peer Database Settings</h2>
        <p className="text-sm text-gray-500">
          Configure the peer node's PostgreSQL connection for replication.
          {config?.peer_db_configured && (
            <span className="ml-1 text-green-600 font-medium">✓ Credentials stored</span>
          )}
        </p>

        {testResult && (
          <AlertBanner variant={testResult.ok ? 'success' : 'error'}>
            {testResult.message}
          </AlertBanner>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Host"
            placeholder="e.g. host.docker.internal or 192.168.1.x"
            value={formPeerDbHost}
            onChange={(e) => setFormPeerDbHost(e.target.value)}
          />
          <Input
            label="Port"
            type="number"
            value={String(formPeerDbPort)}
            onChange={(e) => setFormPeerDbPort(Number(e.target.value) || 5432)}
          />
          <Input
            label="Database Name"
            placeholder="e.g. workshoppro"
            value={formPeerDbName}
            onChange={(e) => setFormPeerDbName(e.target.value)}
          />
          <Input
            label="User"
            placeholder="e.g. postgres"
            value={formPeerDbUser}
            onChange={(e) => setFormPeerDbUser(e.target.value)}
          />
          <Input
            label="Password"
            type="password"
            placeholder={config?.peer_db_configured ? '••••••••  (leave blank to keep existing)' : 'Enter password'}
            value={formPeerDbPassword}
            onChange={(e) => setFormPeerDbPassword(e.target.value)}
          />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">SSL Mode</label>
            <select
              value={formPeerDbSslmode}
              onChange={(e) => setFormPeerDbSslmode(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            >
              <option value="disable">Disable (no SSL)</option>
              <option value="require">Require (encrypted, no cert verification)</option>
              <option value="verify-ca">Verify CA (encrypted + verify server cert)</option>
              <option value="verify-full">Verify Full (encrypted + verify cert + hostname)</option>
            </select>
          </div>
        </div>

        <div className="flex items-center gap-3 pt-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleTestConnection}
            loading={testingConnection}
            disabled={!formPeerDbHost || !formPeerDbName || !formPeerDbUser || !formPeerDbPassword}
          >
            Test Connection
          </Button>
          <span className="text-xs text-gray-400">
            Credentials are saved with the main configuration above. Test first, then save.
          </span>
        </div>
      </section>

      {/* ── Replication User Management ── */}
      <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
        <h2 className="text-lg font-medium text-gray-900">Replication User</h2>
        <p className="text-sm text-gray-500">
          Create a dedicated PostgreSQL user with minimal privileges for replication.
          Run this on the node whose database the peer will connect to.
        </p>

        {replUserResult && (
          <AlertBanner variant={replUserResult.ok ? 'success' : 'error'}>
            {replUserResult.message}
          </AlertBanner>
        )}

        <div className="grid gap-4 sm:grid-cols-3">
          <Input
            label="Username"
            placeholder="replicator"
            value={replUserName}
            onChange={(e) => setReplUserName(e.target.value)}
          />
          <Input
            label="Password"
            type="password"
            placeholder="Strong password for replication user"
            value={replUserPassword}
            onChange={(e) => setReplUserPassword(e.target.value)}
          />
          <div className="flex items-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={handleCreateReplUser}
              loading={creatingReplUser}
              disabled={!replUserName.trim() || !replUserPassword}
            >
              Create / Update User
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleViewConnectionInfo}
              loading={fetchingDbInfo}
            >
              View Connection Info
            </Button>
          </div>
        </div>
        <p className="text-xs text-gray-400">
          This creates a user with REPLICATION + SELECT privileges on the local database.
          Use this username and password in the peer node's "Peer Database Settings" above.
        </p>
      </section>

      {/* ── Status & Actions (only when configured) ── */}
      {config && config.role !== 'standalone' && (
        <>
          {/* Split-Brain Critical Alert Banner */}
          {failoverStatus?.split_brain_detected && (
            <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-medium text-red-800">
                  🚨 SPLIT-BRAIN DETECTED: This node's data may be stale. Writes are blocked until the conflict is resolved.
                </p>
                {failoverStatus?.is_stale_primary && (
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => openModal('demote-and-sync')}
                  >
                    Demote and Sync
                  </Button>
                )}
              </div>
            </div>
          )}

          {/* Auto-Promote Countdown / Status Banner */}
          {failoverStatus?.promoted_at && config.role === 'primary' && (
            <div className="rounded-lg border border-green-300 bg-green-50 px-4 py-3">
              <p className="text-sm font-medium text-green-800">
                ✓ This node has been automatically promoted to primary
              </p>
            </div>
          )}
          {failoverStatus?.auto_promote_enabled &&
            failoverStatus?.seconds_until_auto_promote != null &&
            failoverStatus?.peer_unreachable_seconds != null && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3">
              <p className="text-sm font-medium text-amber-800">
                ⚠ Primary unreachable for {Math.round(failoverStatus?.peer_unreachable_seconds ?? 0)} seconds, auto-promote in {Math.round(failoverStatus?.seconds_until_auto_promote ?? 0)} seconds
              </p>
            </div>
          )}
          {!failoverStatus?.auto_promote_enabled &&
            failoverStatus?.peer_unreachable_seconds != null && (
            <div className="rounded-lg border border-gray-300 bg-gray-50 px-4 py-3">
              <p className="text-sm font-medium text-gray-700">
                Primary unreachable for {Math.round(failoverStatus?.peer_unreachable_seconds ?? 0)} seconds. Auto-promote is disabled.
              </p>
            </div>
          )}

          {/* Cluster Status */}
          <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
            <h2 className="text-lg font-medium text-gray-900">Cluster Status</h2>

            {lagSeconds != null && lagSeconds > 30 && (
              <AlertBanner variant="warning" title="Replication Lagging">
                Replication lag is {formatLag(lagSeconds)} (threshold: 30s).
              </AlertBanner>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              {/* Local node */}
              <div className="rounded-md border border-gray-200 p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-900">
                    {config.node_name} <span className="text-xs text-gray-500">(local)</span>
                  </span>
                  <Badge variant={roleVariant(config.role)}>
                    {config.role.charAt(0).toUpperCase() + config.role.slice(1)}
                  </Badge>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-500" aria-label="Health: healthy" />
                  <span className="text-sm text-gray-600">Healthy</span>
                </div>
                {config.maintenance_mode && (
                  <Badge variant="warning">Maintenance Mode</Badge>
                )}
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-gray-600">
                  <dt className="text-gray-500">Sync</dt>
                  <dd>{replication?.subscription_status ?? 'not_configured'}</dd>
                  <dt className="text-gray-500">Lag</dt>
                  <dd>{formatLag(lagSeconds)}</dd>
                  <dt className="text-gray-500">Node ID</dt>
                  <dd className="font-mono text-xs truncate">{config.node_id}</dd>
                </dl>
              </div>

              {/* Peer node */}
              <div className="rounded-md border border-gray-200 p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-900">Peer Node</span>
                  <Badge variant={roleVariant(config.role === 'primary' ? 'standby' : 'primary')}>
                    {config.role === 'primary' ? 'Standby' : 'Primary'}
                  </Badge>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-block h-2.5 w-2.5 rounded-full ${
                      peerHealth === 'healthy' ? 'bg-green-500'
                        : peerHealth === 'degraded' ? 'bg-amber-500'
                        : peerHealth === 'unreachable' ? 'bg-red-500'
                        : 'bg-gray-400'
                    }`}
                    aria-label={`Health: ${peerHealth}`}
                  />
                  <span className="text-sm text-gray-600 capitalize">{peerHealth}</span>
                </div>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-gray-600">
                  <dt className="text-gray-500">Endpoint</dt>
                  <dd className="truncate">{config.peer_endpoint || '—'}</dd>
                  <dt className="text-gray-500">Last heartbeat</dt>
                  <dd>{history.length > 0 ? formatTime(history[0].timestamp) : '—'}</dd>
                </dl>
              </div>
            </div>
          </section>

          {/* Replication Details */}
          {replication && (
            <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-3">
              <h2 className="text-lg font-medium text-gray-900">Replication Details</h2>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
                <div>
                  <dt className="text-gray-500">Publication</dt>
                  <dd className="font-mono text-xs">{replication.publication_name ?? '—'}</dd>
                </div>
                <div>
                  <dt className="text-gray-500">Subscription</dt>
                  <dd className="font-mono text-xs">{replication.subscription_name ?? '—'}</dd>
                </div>
                <div>
                  <dt className="text-gray-500">Status</dt>
                  <dd>
                    <Badge variant={replication.is_healthy ? 'success' : 'error'}>
                      {replication.subscription_status ?? 'none'}
                    </Badge>
                  </dd>
                </div>
                <div>
                  <dt className="text-gray-500">Tables Published</dt>
                  <dd>{replication.tables_published}</dd>
                </div>
                <div>
                  <dt className="text-gray-500">Lag</dt>
                  <dd>{formatLag(replication.replication_lag_seconds)}</dd>
                </div>
                <div>
                  <dt className="text-gray-500">Last Replicated</dt>
                  <dd>{formatTime(replication.last_replicated_at)}</dd>
                </div>
              </dl>
            </section>
          )}

          {/* Replication Slots */}
          {slots.length > 0 && (
            <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-medium text-gray-900">Replication Slots</h2>
                <span className="text-xs text-gray-400">{slots.length} slot{slots.length !== 1 ? 's' : ''}</span>
              </div>
              <p className="text-sm text-gray-500">
                Replication slots track where each subscriber has read up to. Inactive (orphaned) slots can accumulate WAL and should be dropped.
              </p>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-gray-500">
                      <th className="pb-2 pr-4">Slot Name</th>
                      <th className="pb-2 pr-4">Type</th>
                      <th className="pb-2 pr-4">Status</th>
                      <th className="pb-2 pr-4">Retained WAL</th>
                      <th className="pb-2 pr-4">Idle</th>
                      <th className="pb-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {slots.map((slot) => (
                      <tr key={slot.slot_name} className="border-b border-gray-100">
                        <td className="py-2 pr-4 font-mono text-xs">{slot.slot_name}</td>
                        <td className="py-2 pr-4">{slot.slot_type}</td>
                        <td className="py-2 pr-4">
                          {slot.active ? (
                            <span className="inline-flex items-center gap-1 text-green-600">
                              <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
                              Active
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-amber-600">
                              <span className="inline-block h-2 w-2 rounded-full bg-amber-500" />
                              Inactive
                            </span>
                          )}
                        </td>
                        <td className="py-2 pr-4 text-gray-600">{slot.retained_wal ?? '—'}</td>
                        <td className="py-2 pr-4 text-gray-600">
                          {slot.idle_seconds != null
                            ? slot.idle_seconds < 60
                              ? `${Math.round(slot.idle_seconds)}s`
                              : slot.idle_seconds < 3600
                                ? `${Math.round(slot.idle_seconds / 60)}m`
                                : `${Math.round(slot.idle_seconds / 3600)}h`
                            : '—'}
                        </td>
                        <td className="py-2 text-right">
                          {!slot.active && (
                            <Button
                              variant="danger"
                              size="sm"
                              onClick={() => handleDropSlot(slot.slot_name)}
                              loading={droppingSlot === slot.slot_name}
                            >
                              Drop
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Actions */}
          <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
            <h2 className="text-lg font-medium text-gray-900">Actions</h2>
            <div className="flex flex-wrap gap-3">
              {config.role === 'standby' && (
                <Button variant="primary" size="sm" onClick={() => openModal('promote')}>
                  Promote to Primary
                </Button>
              )}
              {config.role === 'primary' && (
                <Button variant="danger" size="sm" onClick={() => openModal('demote')}>
                  Demote to Standby
                </Button>
              )}
              <Button variant="secondary" size="sm" onClick={() => openModal('init-replication')}>
                Initialize Replication
              </Button>
              <Button variant="danger" size="sm" onClick={() => openModal('stop-replication')}>
                Stop Replication
              </Button>
              <Button variant="secondary" size="sm" onClick={() => openModal('resync')}>
                Trigger Re-sync
              </Button>
              {!config.maintenance_mode ? (
                <Button variant="secondary" size="sm" onClick={() => openModal('maintenance-enter')}>
                  Enter Maintenance Mode
                </Button>
              ) : (
                <Button variant="secondary" size="sm" onClick={() => openModal('maintenance-exit')}>
                  Exit Maintenance Mode
                </Button>
              )}
            </div>
          </section>

          {/* Heartbeat History */}
          {history.length > 0 && (
            <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-3">
              <h2 className="text-lg font-medium text-gray-900">Heartbeat History (last {history.length})</h2>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-gray-500">
                      <th className="pb-2 pr-4">Time</th>
                      <th className="pb-2 pr-4">Peer Status</th>
                      <th className="pb-2 pr-4">Lag</th>
                      <th className="pb-2 pr-4">Response</th>
                      <th className="pb-2">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.slice(0, 20).map((entry, i) => (
                      <tr key={i} className="border-b border-gray-100">
                        <td className="py-1.5 pr-4 text-gray-600">{formatTime(entry.timestamp)}</td>
                        <td className="py-1.5 pr-4">
                          <span className={`inline-flex items-center gap-1 ${
                            entry.peer_status === 'healthy' ? 'text-green-600'
                              : entry.peer_status === 'degraded' ? 'text-amber-600'
                              : 'text-red-600'
                          }`}>
                            <span className={`inline-block h-1.5 w-1.5 rounded-full ${
                              entry.peer_status === 'healthy' ? 'bg-green-500'
                                : entry.peer_status === 'degraded' ? 'bg-amber-500'
                                : 'bg-red-500'
                            }`} />
                            {entry.peer_status}
                          </span>
                        </td>
                        <td className="py-1.5 pr-4 text-gray-600">{formatLag(entry.replication_lag_seconds)}</td>
                        <td className="py-1.5 pr-4 text-gray-600">
                          {entry.response_time_ms != null ? `${entry.response_time_ms.toFixed(0)}ms` : '—'}
                        </td>
                        <td className="py-1.5 text-red-600 text-xs">{entry.error ?? ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}

      {/* ── Action Confirmation Modal ── */}
      <Modal
        open={modalAction !== null}
        onClose={closeModal}
        title={modalAction ? modalTitles[modalAction] : ''}
      >
        <div className="space-y-4">
          {isStandbyInit || isDemoteAndSync ? (
            <div className="rounded-md border border-red-200 bg-red-50 p-3">
              <p className="text-sm font-medium text-red-800">
                ⚠️ {isDemoteAndSync ? 'Warning — Data Loss' : 'Warning — Data Replacement'}
              </p>
              <p className="mt-1 text-sm text-red-700">
                {modalAction ? modalDescriptions[modalAction] : ''}
              </p>
              {isDemoteAndSync && (
                <p className="mt-2 text-sm font-semibold text-red-800">
                  Any data written to this node after the failover will be lost. The new primary's data will replace all local data.
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-gray-600">
              {modalAction ? modalDescriptions[modalAction] : ''}
            </p>
          )}

          {actionError && <AlertBanner variant="error">{actionError}</AlertBanner>}

          {needsConfirmText && (
            <>
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
            </>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" size="sm" onClick={closeModal}>
              {isDemoteAndSync ? 'Dismiss' : 'Cancel'}
            </Button>
            <Button
              variant={modalAction === 'demote' || modalAction === 'resync' || modalAction === 'stop-replication' || modalAction === 'demote-and-sync' ? 'danger' : 'primary'}
              size="sm"
              disabled={needsConfirmText ? (confirmText !== 'CONFIRM' || !reason.trim()) : false}
              loading={actionLoading}
              onClick={handleAction}
            >
              {isDemoteAndSync ? 'Demote and Sync' : 'Confirm'}
            </Button>
          </div>
        </div>
      </Modal>

      {/* ── Replication User Connection Info Modal ── */}
      <Modal
        open={showReplInfoModal}
        onClose={() => setShowReplInfoModal(false)}
        title="Peer Database Connection Details"
      >
        {replConnectionInfo && (
          <div className="space-y-4">
            <p className="text-sm text-gray-600">
              Configure these settings on the remote peer node's "Peer Database Settings" section.
            </p>

            <div className="space-y-3">
              {[
                { label: 'Host', value: replConnectionInfo.host },
                { label: 'Port', value: String(replConnectionInfo.port) },
                { label: 'Database Name', value: replConnectionInfo.dbname },
                { label: 'User', value: replConnectionInfo.user },
                { label: 'Password', value: replConnectionInfo.password },
                { label: 'SSL Mode', value: replConnectionInfo.ssl_enabled ? 'require' : 'disable' },
              ].map((field) => (
                <div key={field.label} className="flex items-center gap-2">
                  <label className="w-32 shrink-0 text-sm font-medium text-gray-600">{field.label}</label>
                  <code className="flex-1 rounded border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm font-mono text-gray-800 select-all truncate">
                    {field.label === 'Password' ? '••••••••' : field.value}
                  </code>
                  <button
                    type="button"
                    onClick={() => copyToClipboard(field.value)}
                    className="shrink-0 rounded border border-gray-300 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    title={`Copy ${field.label}`}
                  >
                    Copy
                  </button>
                </div>
              ))}
            </div>

            <div className="border-t border-gray-200 pt-3">
              <label className="block text-sm font-medium text-gray-600 mb-1.5">Connection String</label>
              <div className="flex items-start gap-2">
                <code className="flex-1 rounded border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-mono text-gray-800 break-all select-all">
                  {replConnectionInfo.connection_string}
                </code>
                <button
                  type="button"
                  onClick={() => copyToClipboard(replConnectionInfo.connection_string)}
                  className="shrink-0 rounded border border-gray-300 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                >
                  Copy
                </button>
              </div>
            </div>

            <div className="flex justify-between items-center pt-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={copyAllReplInfo}
              >
                Copy All
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => setShowReplInfoModal(false)}
              >
                Done
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
