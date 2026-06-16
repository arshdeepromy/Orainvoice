/**
 * BackupSettings — destinations / schedule & retention / notifications (Task 17.3).
 *
 * Three tabbed sections behind the Global-Admin Cloud Backup area:
 *   1. Destinations    — list (masked creds + connection/residency badges),
 *                        per-type Add forms, Edit, Set-as-primary, Test, Disconnect,
 *                        residency notice + acknowledgement, OAuth popup connect with
 *                        postMessage handoff (row flips to connected, no dead-end page).
 *   2. Schedule        — cron + backup window + retention with inline RPO/RTO warnings.
 *   3. Notifications   — per-event toggles, channel enables, webhook, recipient lists
 *                        (empty-list → global_admin fallback hint) + Send test.
 *
 * Safe consumption throughout: optional chaining, `?? []` / `?? 0`, AbortController in
 * every fetch effect (and the postMessage listener removed on unmount), typed generics,
 * no `as any`. Masked credentials are never shown in clear; a masked value submitted
 * back is preserved by the backend.
 *
 * Requirements: 2.1, 2.2, 2.7, 8.1, 8.2, 8.4, 18.11, 18.12, 20.3, 25.2, 28.5, 29.2,
 * 30.2, 30.7
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Modal } from '@/components/ui/Modal'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Tabs } from '@/components/ui/Tabs'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import {
  listDestinations,
  createDestination,
  editDestination,
  setPrimaryDestination,
  deleteDestination,
  testDestination,
  getDestinationStorage,
  getResidencyNotice,
  acknowledgeResidency,
  oauthConnect,
  getConfig,
  updateConfig,
  testNotifications,
  isOAuthProvider,
  PROVIDER_FIELDS,
  PROVIDER_LABELS,
  type Destination,
  type ProviderType,
  type ProviderFieldDef,
  type BackupConfig,
  type ConfigUpdate,
  type ChannelResult,
  type ResidencyNotice,
  type StorageUsage,
} from '@/api/backup/settings'

/* ================================================================== */
/*  Shared helpers                                                     */
/* ================================================================== */

function errorDetail(err: unknown, fallback: string): string {
  if (err && typeof err === 'object') {
    const resp = (err as { response?: { data?: { detail?: unknown } } }).response
    const detail = resp?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return fallback
}

function isAbort(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false
  const name = (err as { name?: string }).name
  const code = (err as { code?: string }).code
  return name === 'CanceledError' || name === 'AbortError' || code === 'ERR_CANCELED'
}

function connectionBadge(state: string) {
  const s = (state ?? '').toLowerCase()
  if (s === 'connected') return <Badge variant="success">Connected</Badge>
  if (s === 'error') return <Badge variant="danger">Error</Badge>
  return <Badge variant="neutral">{state || 'Disconnected'}</Badge>
}

function ToggleSwitch({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean
  onChange: (val: boolean) => void
  disabled?: boolean
  label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2
        disabled:opacity-50 disabled:cursor-not-allowed
        ${checked ? 'bg-accent' : 'bg-border-strong'}`}
    >
      <span
        aria-hidden="true"
        className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-card shadow ring-0 transition-transform
          ${checked ? 'translate-x-5' : 'translate-x-0'}`}
      />
    </button>
  )
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  label: string
  description?: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <div className="min-w-0">
        <p className="text-[13.5px] font-medium text-text">{label}</p>
        {description && <p className="text-[12px] text-muted">{description}</p>}
      </div>
      <ToggleSwitch checked={checked} onChange={onChange} disabled={disabled} label={label} />
    </div>
  )
}

/* ================================================================== */
/*  Destination Add / Edit form                                        */
/* ================================================================== */

interface DestinationFormProps {
  provider: ProviderType
  /** When editing, the existing destination (config carries masked secrets). */
  existing?: Destination
  onClose: () => void
  onSaved: (saved: Destination) => void
}

function DestinationForm({ provider, existing, onClose, onSaved }: DestinationFormProps) {
  const fields = PROVIDER_FIELDS[provider] ?? []
  const [displayName, setDisplayName] = useState(existing?.display_name ?? '')
  const [residency, setResidency] = useState(existing?.residency ?? '')
  const [immutable, setImmutable] = useState(existing?.is_immutable_copy ?? false)
  const [lockDays, setLockDays] = useState(
    existing?.lock_window_days != null ? String(existing.lock_window_days) : '',
  )
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {}
    for (const f of fields) {
      const raw = existing?.config?.[f.key]
      init[f.key] = raw == null ? '' : String(raw)
    }
    return init
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const setField = useCallback((key: string, val: string) => {
    setValues((prev) => ({ ...prev, [key]: val }))
  }, [])

  const buildConfig = useCallback((): Record<string, unknown> => {
    const config: Record<string, unknown> = {}
    for (const f of fields) {
      const val = values[f.key] ?? ''
      // On create, only send non-empty fields. On edit, send entered values —
      // a masked secret round-tripped unchanged is preserved by the backend.
      if (val !== '' || existing) {
        config[f.key] = val
      }
    }
    if (residency.trim()) config.residency = residency.trim()
    return config
  }, [fields, values, residency, existing])

  const handleSubmit = useCallback(async () => {
    if (!displayName.trim()) {
      setError('A display name is required.')
      return
    }
    setSaving(true)
    setError(null)
    const lockWindow = lockDays.trim() === '' ? null : Number(lockDays)
    try {
      let saved: Destination
      if (existing) {
        saved = await editDestination(existing.id, {
          display_name: displayName.trim(),
          is_immutable_copy: immutable,
          lock_window_days: lockWindow,
          config: buildConfig(),
        })
      } else {
        saved = await createDestination({
          provider_type: provider,
          display_name: displayName.trim(),
          config: buildConfig(),
          residency: residency.trim() || null,
          is_immutable_copy: immutable,
          lock_window_days: lockWindow,
        })
      }
      onSaved(saved)
    } catch (err) {
      setError(errorDetail(err, 'Could not save the destination.'))
    } finally {
      setSaving(false)
    }
  }, [displayName, existing, immutable, lockDays, provider, residency, buildConfig, onSaved])

  const renderField = (f: ProviderFieldDef) => {
    const helper = f.secret && existing ? 'Leave the masked value to keep the stored secret.' : f.helperText
    if (f.type === 'select') {
      return (
        <Select
          key={f.key}
          label={f.label}
          value={values[f.key] ?? ''}
          placeholder="Select…"
          options={f.options ?? []}
          onChange={(e) => setField(f.key, e.target.value)}
        />
      )
    }
    return (
      <Input
        key={f.key}
        label={f.label}
        type={f.type === 'password' ? 'password' : 'text'}
        value={values[f.key] ?? ''}
        placeholder={f.placeholder}
        helperText={helper}
        autoComplete={f.secret ? 'off' : undefined}
        onChange={(e) => setField(f.key, e.target.value)}
      />
    )
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`${existing ? 'Edit' : 'Add'} ${PROVIDER_LABELS[provider] ?? provider} destination`}
      className="max-w-xl"
    >
      <div className="space-y-4">
        {error && (
          <AlertBanner variant="error" title="Could not save">
            {error}
          </AlertBanner>
        )}

        <Input
          label="Display name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="e.g. Primary offsite (Wasabi)"
        />

        {fields.map(renderField)}

        <Input
          label="Data residency"
          value={residency}
          onChange={(e) => setResidency(e.target.value)}
          placeholder="e.g. NZ, AU, offshore"
          helperText="Used for the residency disclosure shown to operators."
        />

        <div className="flex items-center justify-between gap-4 rounded-ctl border border-border px-3 py-2.5">
          <div>
            <p className="text-[13.5px] font-medium text-text">Immutable / write-once copy</p>
            <p className="text-[12px] text-muted">
              Apply an object-lock window so backups can't be deleted early.
            </p>
          </div>
          <ToggleSwitch
            checked={immutable}
            onChange={setImmutable}
            label="Immutable copy"
          />
        </div>

        {immutable && (
          <Input
            label="Lock window (days)"
            type="number"
            min={1}
            value={lockDays}
            onChange={(e) => setLockDays(e.target.value)}
            placeholder="e.g. 30"
          />
        )}

        {isOAuthProvider(provider) && !existing && (
          <AlertBanner variant="info" title="OAuth provider">
            Save the client credentials first, then use “Connect” on the destination row to
            authorize access in a popup.
          </AlertBanner>
        )}

        <div className="flex justify-end gap-3 pt-1">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" onClick={handleSubmit} loading={saving} disabled={saving}>
            {existing ? 'Save changes' : 'Add destination'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

/* ================================================================== */
/*  Residency notice modal                                             */
/* ================================================================== */

function ResidencyModal({
  destination,
  onClose,
  onAcknowledged,
}: {
  destination: Destination
  onClose: () => void
  onAcknowledged: () => void
}) {
  const [notice, setNotice] = useState<ResidencyNotice | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [acking, setAcking] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getResidencyNotice(destination.id, controller.signal)
      .then((data) => setNotice(data))
      .catch((err) => {
        if (!isAbort(err)) setError(errorDetail(err, 'Could not load the residency notice.'))
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [destination.id])

  const handleAck = useCallback(async () => {
    setAcking(true)
    setError(null)
    try {
      await acknowledgeResidency(destination.id)
      setNotice((prev) => (prev ? { ...prev, acknowledged: true } : prev))
      onAcknowledged()
    } catch (err) {
      setError(errorDetail(err, 'Could not record the acknowledgement.'))
    } finally {
      setAcking(false)
    }
  }, [destination.id, onAcknowledged])

  return (
    <Modal open onClose={onClose} title="Data residency notice" className="max-w-lg">
      {loading ? (
        <div className="flex justify-center py-8">
          <Spinner label="Loading residency notice" />
        </div>
      ) : error ? (
        <AlertBanner variant="error" title="Error">
          {error}
        </AlertBanner>
      ) : notice ? (
        <div className="space-y-4">
          {notice.offshore_warning && (
            <AlertBanner variant="warning" title={notice.headline || 'Offshore storage'}>
              {notice.body}
            </AlertBanner>
          )}
          {!notice.offshore_warning && notice.headline && (
            <div>
              <p className="text-[13.5px] font-semibold text-text">{notice.headline}</p>
              <p className="text-[13px] text-muted mt-1">{notice.body}</p>
            </div>
          )}

          <div className="rounded-ctl border border-border px-3 py-2.5 text-[13px] text-muted whitespace-pre-line">
            {notice.text}
          </div>

          {notice.biometric_notice && (
            <p className="text-[12.5px] text-muted">{notice.biometric_notice}</p>
          )}

          <div className="flex items-center gap-2 text-[12.5px]">
            <span className="text-muted">Residency:</span>
            <Badge variant={notice.offshore_warning ? 'warn' : 'neutral'}>
              {notice.residency || 'unknown'}
            </Badge>
            {notice.acknowledged && <Badge variant="success">Acknowledged</Badge>}
          </div>

          <div className="flex justify-end gap-3 pt-1">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Close
            </Button>
            {notice.requires_acknowledgement && !notice.acknowledged && (
              <Button variant="primary" size="sm" onClick={handleAck} loading={acking} disabled={acking}>
                Acknowledge
              </Button>
            )}
          </div>
        </div>
      ) : null}
    </Modal>
  )
}

/* ================================================================== */
/*  Destinations tab                                                   */
/* ================================================================== */

const PROVIDER_CHOICES: ProviderType[] = ['google_drive', 'onedrive', 's3', 'nas']

function maskedConfigSummary(dest: Destination): string {
  const cfg = dest.config ?? {}
  const parts: string[] = []
  const push = (key: string, label: string) => {
    const v = cfg[key]
    if (v != null && String(v) !== '') parts.push(`${label}: ${String(v)}`)
  }
  push('bucket', 'Bucket')
  push('region', 'Region')
  push('endpoint_url', 'Endpoint')
  push('share_path', 'Share')
  push('folder_path', 'Folder')
  push('access_key_id', 'Key')
  push('username', 'User')
  return parts.join('  ·  ')
}

function StorageUsageLine({
  destId,
  connected,
}: {
  destId: string
  connected: boolean
}) {
  const [usage, setUsage] = useState<StorageUsage | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!connected) {
      setUsage(null)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    getDestinationStorage(destId, controller.signal)
      .then((u) => setUsage(u))
      .catch(() => {
        /* usage is best-effort; never surface an error here */
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [destId, connected])

  if (!connected) return null
  if (loading && !usage) {
    return <p className="text-[12px] text-muted-2">Checking storage…</p>
  }
  if (!usage || !usage.reported) return null

  const fmt = (bytes: number | null): string => {
    if (bytes == null || bytes < 0) return '—'
    const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    let v = bytes
    let i = 0
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024
      i += 1
    }
    const rounded = v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)
    return `${rounded} ${units[i]}`
  }

  const total = usage.total_bytes
  const used = usage.used_bytes ?? 0
  const available = usage.available_bytes
  const pct =
    total && total > 0 ? Math.min(100, Math.round((used / total) * 100)) : null
  const barColor =
    pct != null && pct >= 90
      ? 'bg-danger'
      : pct != null && pct >= 75
        ? 'bg-warn'
        : 'bg-accent'

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center justify-between gap-x-3 text-[12px] text-muted">
        <span>
          Storage: <span className="text-text">{fmt(used)} used</span>
          {total != null && (
            <>
              {' '}of <span className="text-text">{fmt(total)}</span>
            </>
          )}
          {available != null && (
            <>
              {' · '}
              <span className="text-text">{fmt(available)} available</span>
            </>
          )}
        </span>
        {pct != null && <span className="mono">{pct}%</span>}
      </div>
      {pct != null && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted/20">
          <div
            className={`h-full rounded-full ${barColor} transition-[width] duration-500`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  )
}

/**
 * For OAuth destinations, surface the exact redirect/callback URL the operator
 * must register at the provider (Google Cloud / Azure). It includes the
 * destination id (only known after creation) and the live origin, so it is
 * copy-paste exact for this deployment. Without this the operator has no way to
 * discover the per-destination callback URL.
 */
function OAuthCallbackHint({ destId }: { destId: string }) {
  const [copied, setCopied] = useState(false)
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  const url = `${origin}/api/v1/backup/destinations/${destId}/oauth/callback`

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }, [url])

  return (
    <div className="rounded-ctl border border-border bg-canvas px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted-2">
          OAuth redirect URI — register this at the provider
        </span>
        <Button variant="ghost" size="sm" onClick={handleCopy}>
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <p className="mono mt-1 break-all text-[12px] text-text">{url}</p>
      <p className="mt-1 text-[11.5px] text-muted">
        Add this under Authorized redirect URIs (Google) / Redirect URIs (Azure), then click
        Connect.
      </p>
    </div>
  )
}

function DestinationRow({
  dest,
  busy,
  onSetPrimary,
  onTest,
  onEdit,
  onResidency,
  onDisconnect,
  onConnect,
  testResult,
}: {
  dest: Destination
  busy: boolean
  onSetPrimary: () => void
  onTest: () => void
  onEdit: () => void
  onResidency: () => void
  onDisconnect: () => void
  onConnect: () => void
  testResult: { ok: boolean; detail: string } | null
}) {
  const oauth = isOAuthProvider(dest.provider_type)
  const connected = (dest.connection_state ?? '').toLowerCase() === 'connected'
  return (
    <div className="flex flex-col gap-2 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-text">{dest.display_name}</span>
        <Badge variant="info" dot={false}>
          {PROVIDER_LABELS[dest.provider_type] ?? dest.provider_type}
        </Badge>
        {dest.is_primary && <Badge variant="success">Primary</Badge>}
        {connectionBadge(dest.connection_state)}
        {dest.is_immutable_copy && <Badge variant="warn" dot={false}>Immutable</Badge>}
        <Badge variant="neutral" dot={false}>{dest.residency || 'residency: n/a'}</Badge>
      </div>

      {maskedConfigSummary(dest) && (
        <p className="text-[12.5px] text-muted font-mono">{maskedConfigSummary(dest)}</p>
      )}

      <StorageUsageLine destId={dest.id} connected={connected} />

      {oauth && <OAuthCallbackHint destId={dest.id} />}

      {testResult && (
        <p className={`text-[12.5px] ${testResult.ok ? 'text-ok' : 'text-danger'}`}>
          {testResult.detail}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-0.5">
        {!dest.is_primary && (
          <Button variant="ghost" size="sm" onClick={onSetPrimary} disabled={busy}>
            Set as primary
          </Button>
        )}
        {oauth && (
          <Button variant={connected ? 'ghost' : 'primary'} size="sm" onClick={onConnect} disabled={busy}>
            {connected ? 'Reconnect' : 'Connect'}
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={onTest} disabled={busy}>
          Test connection
        </Button>
        <Button variant="ghost" size="sm" onClick={onEdit} disabled={busy}>
          Edit
        </Button>
        <Button variant="ghost" size="sm" onClick={onResidency} disabled={busy}>
          Residency
        </Button>
        <Button
          variant="danger"
          size="sm"
          onClick={onDisconnect}
          disabled={busy || dest.is_primary}
          title={dest.is_primary ? 'Set another destination as primary first' : undefined}
        >
          Disconnect
        </Button>
      </div>
    </div>
  )
}

function DestinationsTab() {
  const { toasts, addToast, dismissToast } = useToast()
  const [destinations, setDestinations] = useState<Destination[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; detail: string }>>({})

  const [addProvider, setAddProvider] = useState<ProviderType | ''>('')
  const [editing, setEditing] = useState<Destination | null>(null)
  const [residencyFor, setResidencyFor] = useState<Destination | null>(null)
  const [disconnecting, setDisconnecting] = useState<Destination | null>(null)

  const fetchDestinations = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await listDestinations(signal)
      setDestinations(data?.items ?? [])
      setError(false)
    } catch (err) {
      if (!isAbort(err)) setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    fetchDestinations(controller.signal)
    return () => controller.abort()
  }, [fetchDestinations])

  /* OAuth popup handoff — refetch destinations when the callback postMessages
     back, so a connected row flips without a manual refresh. No dead-end page. */
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const data = event.data
      if (!data || typeof data !== 'object') return
      if ((data as { type?: string }).type !== 'backup-oauth') return
      const ok = (data as { ok?: boolean }).ok === true
      const detail = (data as { error?: string }).error
      if (ok) {
        addToast('success', 'Destination connected.')
      } else {
        addToast('error', detail ? `Authorization failed: ${detail}` : 'Authorization was not completed.')
      }
      fetchDestinations()
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [addToast, fetchDestinations])

  const handleSetPrimary = useCallback(
    async (dest: Destination) => {
      setBusyId(dest.id)
      try {
        const data = await setPrimaryDestination(dest.id)
        setDestinations(data?.items ?? [])
        addToast('success', `“${dest.display_name}” is now the primary destination.`)
      } catch (err) {
        addToast('error', errorDetail(err, 'Could not set the primary destination.'))
      } finally {
        setBusyId(null)
      }
    },
    [addToast],
  )

  const handleTest = useCallback(
    async (dest: Destination) => {
      setBusyId(dest.id)
      try {
        const result = await testDestination(dest.id)
        const ok = (result?.state ?? '').toLowerCase() === 'connected'
        setTestResults((prev) => ({
          ...prev,
          [dest.id]: { ok, detail: result?.detail ?? (ok ? 'Connection succeeded.' : 'Connection failed.') },
        }))
        setDestinations((prev) =>
          prev.map((d) => (d.id === dest.id ? { ...d, connection_state: result?.state ?? d.connection_state } : d)),
        )
        addToast(ok ? 'success' : 'error', result?.detail ?? (ok ? 'Connection succeeded.' : 'Connection failed.'))
      } catch (err) {
        const detail = errorDetail(err, 'Connection test failed.')
        setTestResults((prev) => ({ ...prev, [dest.id]: { ok: false, detail } }))
        addToast('error', detail)
      } finally {
        setBusyId(null)
      }
    },
    [addToast],
  )

  const handleConnect = useCallback(
    async (dest: Destination) => {
      setBusyId(dest.id)
      try {
        const { authorization_url } = await oauthConnect(dest.id)
        const popup = window.open(
          authorization_url,
          'backup-oauth',
          'width=560,height=720,menubar=no,toolbar=no',
        )
        if (!popup) {
          addToast('error', 'Popup blocked. Allow popups for this site, then retry.')
        }
      } catch (err) {
        addToast('error', errorDetail(err, 'Could not start authorization.'))
      } finally {
        setBusyId(null)
      }
    },
    [addToast],
  )

  const confirmDisconnect = useCallback(async () => {
    if (!disconnecting) return
    const dest = disconnecting
    setBusyId(dest.id)
    try {
      await deleteDestination(dest.id)
      setDestinations((prev) => prev.filter((d) => d.id !== dest.id))
      addToast('success', `Disconnected “${dest.display_name}”.`)
      setDisconnecting(null)
    } catch (err) {
      addToast('error', errorDetail(err, 'Could not disconnect the destination.'))
    } finally {
      setBusyId(null)
    }
  }, [disconnecting, addToast])

  const handleSaved = useCallback(
    (saved: Destination, wasEdit: boolean) => {
      setDestinations((prev) => {
        const exists = prev.some((d) => d.id === saved.id)
        return exists ? prev.map((d) => (d.id === saved.id ? saved : d)) : [...prev, saved]
      })
      addToast('success', wasEdit ? 'Destination updated.' : 'Destination added.')
      setAddProvider('')
      setEditing(null)
    },
    [addToast],
  )

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="Loading destinations" />
      </div>
    )
  }

  if (error) {
    return (
      <AlertBanner variant="error" title="Error">
        Could not load backup destinations.
      </AlertBanner>
    )
  }

  return (
    <div className="space-y-5">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Add destination */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-64">
          <Select
            label="Add a destination"
            value={addProvider}
            placeholder="Choose a provider…"
            options={PROVIDER_CHOICES.map((p) => ({ value: p, label: PROVIDER_LABELS[p] ?? p }))}
            onChange={(e) => setAddProvider((e.target.value as ProviderType) || '')}
          />
        </div>
      </div>

      {destinations.length === 0 ? (
        <AlertBanner variant="info" title="No destinations yet">
          Add a backup destination to start storing encrypted backups offsite.
        </AlertBanner>
      ) : (
        <div className="divide-y divide-border rounded-card border border-border">
          {destinations.map((dest) => (
            <DestinationRow
              key={dest.id}
              dest={dest}
              busy={busyId === dest.id}
              testResult={testResults[dest.id] ?? null}
              onSetPrimary={() => handleSetPrimary(dest)}
              onTest={() => handleTest(dest)}
              onEdit={() => setEditing(dest)}
              onResidency={() => setResidencyFor(dest)}
              onDisconnect={() => setDisconnecting(dest)}
              onConnect={() => handleConnect(dest)}
            />
          ))}
        </div>
      )}

      {addProvider && (
        <DestinationForm
          provider={addProvider}
          onClose={() => setAddProvider('')}
          onSaved={(saved) => handleSaved(saved, false)}
        />
      )}

      {editing && (
        <DestinationForm
          provider={(editing.provider_type as ProviderType)}
          existing={editing}
          onClose={() => setEditing(null)}
          onSaved={(saved) => handleSaved(saved, true)}
        />
      )}

      {residencyFor && (
        <ResidencyModal
          destination={residencyFor}
          onClose={() => setResidencyFor(null)}
          onAcknowledged={() => addToast('success', 'Residency acknowledged.')}
        />
      )}

      <ConfirmDialog
        open={disconnecting !== null}
        title="Disconnect destination"
        message={
          disconnecting
            ? `Disconnect and remove “${disconnecting.display_name}”? Stored backups at this destination are not deleted.`
            : ''
        }
        confirmLabel="Disconnect"
        variant="danger"
        loading={busyId !== null && busyId === disconnecting?.id}
        onConfirm={confirmDisconnect}
        onCancel={() => setDisconnecting(null)}
      />
    </div>
  )
}

/* ================================================================== */
/*  Schedule & retention tab                                           */
/* ================================================================== */

/** Normalise a backend time value to the `HH:MM` an <input type=time> wants. */
function toTimeInput(value: string | null): string {
  if (!value) return ''
  const m = /^(\d{2}:\d{2})/.exec(value)
  return m ? m[1] : ''
}

function numOrNull(value: string): number | null {
  const t = value.trim()
  if (t === '') return null
  const n = Number(t)
  return Number.isFinite(n) ? n : null
}

function ScheduleTab() {
  const { toasts, addToast, dismissToast } = useToast()
  const [config, setConfig] = useState<BackupConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [warnings, setWarnings] = useState<string[]>([])

  const [cron, setCron] = useState('')
  const [windowStart, setWindowStart] = useState('')
  const [windowEnd, setWindowEnd] = useState('')
  const [retentionCount, setRetentionCount] = useState('')
  const [retentionDays, setRetentionDays] = useState('')
  const [rpo, setRpo] = useState('')
  const [rto, setRto] = useState('')

  const applyConfig = useCallback((c: BackupConfig) => {
    setConfig(c)
    setCron(c.schedule_cron ?? '')
    setWindowStart(toTimeInput(c.backup_window_start))
    setWindowEnd(toTimeInput(c.backup_window_end))
    setRetentionCount(c.retention_count != null ? String(c.retention_count) : '')
    setRetentionDays(c.retention_days != null ? String(c.retention_days) : '')
    setRpo(c.rpo_seconds != null ? String(c.rpo_seconds) : '')
    setRto(c.rto_seconds != null ? String(c.rto_seconds) : '')
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    getConfig(controller.signal)
      .then((c) => {
        applyConfig(c)
        setError(false)
      })
      .catch((err) => {
        if (!isAbort(err)) setError(true)
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [applyConfig])

  const handleSave = useCallback(async () => {
    setSaving(true)
    setWarnings([])
    const body: ConfigUpdate = {
      schedule_cron: cron.trim() || null,
      backup_window_start: windowStart.trim() || null,
      backup_window_end: windowEnd.trim() || null,
      retention_count: numOrNull(retentionCount),
      retention_days: numOrNull(retentionDays),
      rpo_seconds: numOrNull(rpo) ?? undefined,
      rto_seconds: numOrNull(rto) ?? undefined,
    }
    try {
      const result = await updateConfig(body)
      if (result?.config) applyConfig(result.config)
      setWarnings(result?.warnings ?? [])
      addToast('success', 'Schedule & retention saved.')
    } catch (err) {
      addToast('error', errorDetail(err, 'Could not save the schedule.'))
    } finally {
      setSaving(false)
    }
  }, [cron, windowStart, windowEnd, retentionCount, retentionDays, rpo, rto, applyConfig, addToast])

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="Loading configuration" />
      </div>
    )
  }

  if (error || !config) {
    return (
      <AlertBanner variant="error" title="Error">
        Could not load the backup configuration.
      </AlertBanner>
    )
  }

  return (
    <div className="max-w-2xl space-y-5">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {warnings.length > 0 && (
        <AlertBanner variant="warning" title="RPO / RTO warning">
          <ul className="list-disc pl-5 space-y-1">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </AlertBanner>
      )}

      <Input
        label="Backup schedule (cron)"
        value={cron}
        onChange={(e) => setCron(e.target.value)}
        placeholder="0 2 * * *"
        helperText="Standard 5-field cron. Example: “0 2 * * *” runs daily at 02:00."
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input
          label="Backup window start"
          type="time"
          value={windowStart}
          onChange={(e) => setWindowStart(e.target.value)}
        />
        <Input
          label="Backup window end"
          type="time"
          value={windowEnd}
          onChange={(e) => setWindowEnd(e.target.value)}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input
          label="Retention — keep last N backups"
          type="number"
          min={0}
          value={retentionCount}
          onChange={(e) => setRetentionCount(e.target.value)}
          placeholder="e.g. 30"
        />
        <Input
          label="Retention — keep for N days"
          type="number"
          min={0}
          value={retentionDays}
          onChange={(e) => setRetentionDays(e.target.value)}
          placeholder="e.g. 90"
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input
          label="Recovery Point Objective (RPO, seconds)"
          type="number"
          min={0}
          value={rpo}
          onChange={(e) => setRpo(e.target.value)}
          helperText="Target maximum data loss window."
        />
        <Input
          label="Recovery Time Objective (RTO, seconds)"
          type="number"
          min={0}
          value={rto}
          onChange={(e) => setRto(e.target.value)}
          helperText="Target maximum time to restore."
        />
      </div>

      <div className="flex justify-end">
        <Button variant="primary" size="sm" onClick={handleSave} loading={saving} disabled={saving}>
          Save schedule
        </Button>
      </div>
    </div>
  )
}

/* ================================================================== */
/*  Notifications tab                                                  */
/* ================================================================== */

/** Parse a textarea (newline- or comma-separated) into a trimmed, deduped list. */
function parseList(text: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const raw of text.split(/[\n,]+/)) {
    const v = raw.trim()
    if (v && !seen.has(v)) {
      seen.add(v)
      out.push(v)
    }
  }
  return out
}

function NotificationsTab() {
  const { toasts, addToast, dismissToast } = useToast()
  const [config, setConfig] = useState<BackupConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResults, setTestResults] = useState<ChannelResult[] | null>(null)

  const [notifyBackupFailure, setNotifyBackupFailure] = useState(false)
  const [notifyBackupSuccess, setNotifyBackupSuccess] = useState(false)
  const [notifyRestoreFailure, setNotifyRestoreFailure] = useState(false)
  const [notifyRestoreSuccess, setNotifyRestoreSuccess] = useState(false)
  const [emailEnabled, setEmailEnabled] = useState(false)
  const [smsEnabled, setSmsEnabled] = useState(false)
  const [webhookUrl, setWebhookUrl] = useState('')
  const [emails, setEmails] = useState('')
  const [smsNumbers, setSmsNumbers] = useState('')

  const applyConfig = useCallback((c: BackupConfig) => {
    setConfig(c)
    setNotifyBackupFailure(c.notify_backup_failure)
    setNotifyBackupSuccess(c.notify_backup_success)
    setNotifyRestoreFailure(c.notify_restore_failure)
    setNotifyRestoreSuccess(c.notify_restore_success)
    setEmailEnabled(c.email_enabled)
    setSmsEnabled(c.sms_enabled)
    setWebhookUrl(c.webhook_url ?? '')
    setEmails((c.notification_emails ?? []).join('\n'))
    setSmsNumbers((c.notification_sms_numbers ?? []).join('\n'))
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    getConfig(controller.signal)
      .then((c) => {
        applyConfig(c)
        setError(false)
      })
      .catch((err) => {
        if (!isAbort(err)) setError(true)
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [applyConfig])

  const emailList = useMemo(() => parseList(emails), [emails])
  const smsList = useMemo(() => parseList(smsNumbers), [smsNumbers])

  const handleSave = useCallback(async () => {
    setSaving(true)
    const body: ConfigUpdate = {
      notify_backup_failure: notifyBackupFailure,
      notify_backup_success: notifyBackupSuccess,
      notify_restore_failure: notifyRestoreFailure,
      notify_restore_success: notifyRestoreSuccess,
      email_enabled: emailEnabled,
      sms_enabled: smsEnabled,
      webhook_url: webhookUrl.trim() || null,
      notification_emails: emailList,
      notification_sms_numbers: smsList,
    }
    try {
      const result = await updateConfig(body)
      if (result?.config) applyConfig(result.config)
      addToast('success', 'Notification settings saved.')
    } catch (err) {
      addToast('error', errorDetail(err, 'Could not save notification settings.'))
    } finally {
      setSaving(false)
    }
  }, [
    notifyBackupFailure, notifyBackupSuccess, notifyRestoreFailure, notifyRestoreSuccess,
    emailEnabled, smsEnabled, webhookUrl, emailList, smsList, applyConfig, addToast,
  ])

  const handleSendTest = useCallback(async () => {
    setTesting(true)
    setTestResults(null)
    try {
      const result = await testNotifications()
      setTestResults(result?.results ?? [])
    } catch (err) {
      addToast('error', errorDetail(err, 'Could not send test notifications.'))
    } finally {
      setTesting(false)
    }
  }, [addToast])

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="Loading configuration" />
      </div>
    )
  }

  if (error || !config) {
    return (
      <AlertBanner variant="error" title="Error">
        Could not load the backup configuration.
      </AlertBanner>
    )
  }

  return (
    <div className="max-w-2xl space-y-6">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Per-event toggles */}
      <section>
        <h2 className="text-[14px] font-semibold text-text mb-1">Notify on</h2>
        <div className="divide-y divide-border rounded-card border border-border px-4">
          <ToggleRow label="Backup failure" checked={notifyBackupFailure} onChange={setNotifyBackupFailure} />
          <ToggleRow label="Backup success" checked={notifyBackupSuccess} onChange={setNotifyBackupSuccess} />
          <ToggleRow label="Restore failure" checked={notifyRestoreFailure} onChange={setNotifyRestoreFailure} />
          <ToggleRow label="Restore success" checked={notifyRestoreSuccess} onChange={setNotifyRestoreSuccess} />
        </div>
      </section>

      {/* Channels */}
      <section>
        <h2 className="text-[14px] font-semibold text-text mb-1">Channels</h2>
        <div className="divide-y divide-border rounded-card border border-border px-4">
          <ToggleRow
            label="Email"
            description="Send notifications by email."
            checked={emailEnabled}
            onChange={setEmailEnabled}
          />
          <ToggleRow
            label="SMS"
            description="Send notifications by SMS."
            checked={smsEnabled}
            onChange={setSmsEnabled}
          />
        </div>
      </section>

      <Input
        label="Webhook URL"
        value={webhookUrl}
        onChange={(e) => setWebhookUrl(e.target.value)}
        placeholder="https://hooks.example.com/backup"
        helperText="Optional. POSTed a JSON payload on each notified event."
      />

      {/* Recipient lists */}
      <div className="space-y-2">
        <label htmlFor="notif-emails" className="text-[12.5px] font-medium text-text block">
          Email recipients
        </label>
        <textarea
          id="notif-emails"
          value={emails}
          onChange={(e) => setEmails(e.target.value)}
          rows={3}
          placeholder="ops@example.com&#10;admin@example.com"
          className="w-full rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text
            placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
        />
        <p className="text-[12px] text-muted">
          {emailList.length === 0
            ? 'No recipients — notifications fall back to all global_admin users.'
            : `${emailList.length} recipient${emailList.length === 1 ? '' : 's'}. One per line or comma-separated.`}
        </p>
      </div>

      <div className="space-y-2">
        <label htmlFor="notif-sms" className="text-[12.5px] font-medium text-text block">
          SMS recipients
        </label>
        <textarea
          id="notif-sms"
          value={smsNumbers}
          onChange={(e) => setSmsNumbers(e.target.value)}
          rows={3}
          placeholder="+64211234567&#10;+64277654321"
          className="w-full rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text
            placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
        />
        <p className="text-[12px] text-muted">
          {smsList.length === 0
            ? 'No recipients — notifications fall back to all global_admin users.'
            : `${smsList.length} recipient${smsList.length === 1 ? '' : 's'}. One per line or comma-separated.`}
        </p>
      </div>

      {/* Test results */}
      {testResults && (
        <div className="rounded-card border border-border divide-y divide-border">
          {testResults.length === 0 ? (
            <p className="px-4 py-3 text-[13px] text-muted">No channels were tested.</p>
          ) : (
            testResults.map((r, i) => (
              <div key={`${r.channel}-${i}`} className="flex items-center justify-between gap-3 px-4 py-2.5">
                <span className="text-[13.5px] font-medium text-text capitalize">{r.channel}</span>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[12.5px] text-muted truncate">{r.detail}</span>
                  <Badge variant={r.ok ? 'success' : 'danger'}>{r.ok ? 'OK' : 'Failed'}</Badge>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      <div className="flex justify-end gap-3">
        <Button variant="ghost" size="sm" onClick={handleSendTest} loading={testing} disabled={testing}>
          Send test
        </Button>
        <Button variant="primary" size="sm" onClick={handleSave} loading={saving} disabled={saving}>
          Save notifications
        </Button>
      </div>
    </div>
  )
}

/* ================================================================== */
/*  Page                                                               */
/* ================================================================== */

export function BackupSettings() {
  const tabs = [
    { id: 'destinations', label: 'Destinations', content: <DestinationsTab /> },
    { id: 'schedule', label: 'Schedule & retention', content: <ScheduleTab /> },
    { id: 'notifications', label: 'Notifications', content: <NotificationsTab /> },
  ]
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold text-text">Backup Settings</h1>
        <p className="text-sm text-muted">
          Manage backup destinations, schedule &amp; retention, and notifications.
        </p>
      </div>
      <Tabs tabs={tabs} defaultTab="destinations" urlPersist />
    </div>
  )
}
