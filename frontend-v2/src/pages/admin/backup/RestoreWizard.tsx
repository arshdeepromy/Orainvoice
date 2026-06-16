/**
 * RestoreWizard — multi-step Cloud Backup restore flow (Task 17.5).
 *
 * Steps (key-material step is skipped when a key is already active, Req 16.7):
 *   1. (on entry) GET /keys/status + load backups/destinations.
 *   2. Source — pick the backup to restore + show the primary destination it is
 *      read from (the backend always reads from the configured primary).
 *   3. Key material — recovery-kit upload + passphrase → POST /keys/bootstrap,
 *      shown ONLY when has_active_key is false (Req 16.7, 16.12).
 *   4. Mode — full / per-org / dry-run.
 *   5. Per-org — browse the entity-type tree with counts + conflict policy;
 *      submit is blocked when zero entities are selected (Req 14, 15.1, 15.6).
 *   6. Full — runs POST /restore/dry-run first; when older_schema is set it
 *      shows the older-schema confirmation gate, then submits POST /restore/full
 *      with confirm_older_schema=true (Req 10.5-10.7); a maintenance/fence/
 *      rollback banner is shown for the destructive full path (Req 12.1).
 *   7. Dry-run — read-only pre-flight validation results.
 *   8. Live progress modal with a Cancel control (POST /restore/jobs/{id}/cancel)
 *      enabled only pre-apply; once the destructive apply has begun the backend
 *      refuses with 409 and the control is disabled (Req 12.16, 12.17). The
 *      modal polls GET /restore/jobs/{id} and surfaces the terminal outcome —
 *      success summary or the failure reason (Req 13.3).
 *
 * The progress modal polls GET /restore/jobs/{id} for live status and the
 * terminal outcome (completed summary or failure reason), so an operator is no
 * longer blind to a background restore that fails after acceptance.
 *
 * Requirements: 10.5, 10.6, 10.7, 11.1, 12.1, 12.16, 12.17, 14.1, 15.1, 15.6,
 * 16.7, 16.12
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Badge from '@/components/ui/Badge'
import Button from '@/components/ui/Button'
import Card, { CardBody, CardHead } from '@/components/ui/Card'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import { Select } from '@/components/ui/Select'
import { Spinner } from '@/components/ui/Spinner'
import {
  bootstrapKey,
  browseBackup,
  cancelRestoreJob,
  errorDetail,
  fetchBackups,
  fetchDestinations,
  fetchKeyStatus,
  getRestoreJobStatus,
  runDryRun,
  submitFullRestore,
  submitPerOrgRestore,
  uploadAndRestore,
  TERMINAL_RESTORE_STATUSES,
  type BackupRow,
  type BrowseOrg,
  type ConflictPolicy,
  type DestinationRow,
  type DryRunResult,
  type JobStatus,
  type KeyStatus,
  type RecoveryKit,
} from '@/api/backup/restore'

/* ------------------------------------------------------------------ */
/*  Types + helpers                                                    */
/* ------------------------------------------------------------------ */

type WizardStep = 'source' | 'key' | 'mode' | 'perorg' | 'full' | 'dryrun'
type RestoreMode = 'full' | 'per_org' | 'dry_run'

const STEP_TITLES: Record<WizardStep, string> = {
  source: 'Select backup',
  key: 'Key material',
  mode: 'Restore mode',
  perorg: 'Choose data',
  full: 'Full restore',
  dryrun: 'Dry-run',
}

const CONFLICT_OPTIONS: { value: ConflictPolicy; label: string }[] = [
  { value: 'overwrite', label: 'Overwrite — restore over existing data (recommended)' },
  { value: 'skip', label: 'Skip — only add back missing records' },
  { value: 'restore_as_new', label: 'Insert as new copies (empty organisation only)' },
]

/** Human explanation shown under the policy selector, by policy. */
const CONFLICT_HELP: Record<ConflictPolicy, string> = {
  overwrite:
    'Updates records that still exist to match the backup and re-creates any that were deleted. Use this to recover from accidental deletes or bad edits.',
  skip:
    'Inserts only records that are missing and leaves everything currently in the organisation untouched. Use this to top up deleted records without changing current data.',
  restore_as_new:
    'Inserts the backup’s rows as brand-new copies under this organisation. This only works on an empty organisation — restoring into one that already has data (users, customers, invoices) will be rejected because identities such as login emails must stay unique. Intended for sandboxes/migrations, not for restoring a live organisation.',
}

function formatBytes(bytes: number | null): string {
  if (bytes == null || bytes <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

function outcomeVariant(outcome: string): 'ok' | 'warn' | 'danger' | 'neutral' {
  const key = (outcome ?? '').toLowerCase()
  if (key === 'ok' || key === 'pass' || key === 'passed' || key === 'success') return 'ok'
  if (key === 'warn' || key === 'warning') return 'warn'
  if (key === 'fail' || key === 'failed' || key === 'error') return 'danger'
  return 'neutral'
}

/* ================================================================== */
/*  Main component                                                     */
/* ================================================================== */

export function RestoreWizard() {
  return (
    <div className="flex flex-col gap-8">
      <UploadRestorePanel />
      <RestoreFromCloudWizard />
    </div>
  )
}

/* ================================================================== */
/*  Upload & restore panel (fast DR path)                              */
/* ================================================================== */

function UploadRestorePanel() {
  const [expanded, setExpanded] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [kit, setKit] = useState('')
  const [passphrase, setPassphrase] = useState('')
  const [confirmOlder, setConfirmOlder] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)

  const handleKitFile = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    const reader = new FileReader()
    reader.onload = () => setKit(reader.result as string)
    reader.readAsText(f)
  }, [])

  const handleSubmit = useCallback(async () => {
    if (!file) return
    setSubmitting(true)
    setError(null)
    const controller = new AbortController()
    try {
      const accepted = await uploadAndRestore(
        file, kit, passphrase, confirmOlder, controller.signal,
      )
      setJobId(accepted.job_id)
    } catch (err) {
      setError(errorDetail(err, 'Could not start the restore.'))
    } finally {
      setSubmitting(false)
    }
  }, [file, kit, passphrase, confirmOlder])

  if (jobId) {
    return (
      <>
        <Card>
          <CardHead title="Upload restore launched" />
          <CardBody>
            <AlertBanner variant="info">
              A full destructive restore is running from the uploaded bundle. Close
              the modal to hide it — the restore continues in the background.
            </AlertBanner>
          </CardBody>
        </Card>
        <RestoreProgressModal
          jobId={jobId}
          mode="full"
          onClose={() => { setJobId(null); setExpanded(false) }}
        />
      </>
    )
  }

  return (
    <Card>
      <CardHead title="Restore from a backup file (fast DR)">
        <Button variant="ghost" size="sm" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Collapse' : 'Upload a backup'}
        </Button>
      </CardHead>
      {expanded && (
        <CardBody className="flex flex-col gap-4">
          <p className="text-[13px] text-muted">
            Upload a portable backup bundle (<code>.tar</code>) you exported from
            History, along with your Recovery Kit and passphrase. This triggers a
            full destructive restore — the server becomes the backup. No
            destination setup required.
          </p>

          <div className="flex flex-col gap-1">
            <label className="text-[12.5px] font-medium text-text">Backup bundle (.tar)</label>
            <input
              type="file"
              accept=".tar"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-[13px] text-text"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[12.5px] font-medium text-text">Recovery Kit (JSON file)</label>
            <input type="file" accept=".json" onChange={handleKitFile} className="text-[13px] text-text" />
            {kit && (
              <span className="text-[12px] text-ok">✓ Recovery Kit loaded</span>
            )}
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[12.5px] font-medium text-text">Passphrase</label>
            <input
              type="password"
              autoComplete="off"
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
              placeholder="The passphrase you set when the key was created"
              className="h-[42px] w-full rounded-ctl border border-border bg-card px-3 text-[13.5px] text-text
                placeholder:text-muted-2
                focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            />
          </div>

          <label className="flex cursor-pointer items-center gap-2.5">
            <input
              type="checkbox"
              checked={confirmOlder}
              onChange={(e) => setConfirmOlder(e.target.checked)}
              className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
            />
            <span className="text-[13px] text-text">
              Confirm: I understand this backup may have an older schema version
            </span>
          </label>

          {error && <AlertBanner variant="error">{error}</AlertBanner>}

          <AlertBanner variant="warning">
            This is a <strong>full destructive restore</strong>. The entire database
            will be replaced with the backup's contents under maintenance mode. Make
            sure you have no active users before proceeding.
          </AlertBanner>

          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" onClick={() => setExpanded(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleSubmit}
              loading={submitting}
              disabled={!file || !kit || !passphrase}
            >
              Upload & Restore
            </Button>
          </div>
        </CardBody>
      )}
    </Card>
  )
}

/* ================================================================== */
/*  Cloud‑based restore wizard (existing flow)                         */
/* ================================================================== */

function RestoreFromCloudWizard() {
  const [searchParams] = useSearchParams()
  const preselectedBackupId = searchParams.get('backup_id')

  /* ---- initial load ---- */
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [keyStatus, setKeyStatus] = useState<KeyStatus | null>(null)
  const [backups, setBackups] = useState<BackupRow[]>([])
  const [destinations, setDestinations] = useState<DestinationRow[]>([])

  /* ---- wizard state ---- */
  const [step, setStep] = useState<WizardStep>('source')
  const [selectedBackupId, setSelectedBackupId] = useState<string>('')
  const [mode, setMode] = useState<RestoreMode>('full')

  /* ---- key material (fresh-deployment bootstrap) ---- */
  const [recoveryKit, setRecoveryKit] = useState<RecoveryKit | null>(null)
  const [recoveryKitName, setRecoveryKitName] = useState<string>('')
  const [passphrase, setPassphrase] = useState<string>('')
  const [kitError, setKitError] = useState<string | null>(null)
  const [bootstrapping, setBootstrapping] = useState(false)

  /* ---- per-org browse ---- */
  const [browseOrgs, setBrowseOrgs] = useState<BrowseOrg[]>([])
  const [browseLoading, setBrowseLoading] = useState(false)
  const [browseError, setBrowseError] = useState<string | null>(null)
  const [selectedOrgId, setSelectedOrgId] = useState<string>('')
  const [selectedEntities, setSelectedEntities] = useState<Set<string>>(new Set())
  const [conflictPolicy, setConflictPolicy] = useState<ConflictPolicy>('overwrite')
  const [restoreFiles, setRestoreFiles] = useState(true)

  /* ---- dry-run / full ---- */
  const [dryRun, setDryRun] = useState<DryRunResult | null>(null)
  const [dryRunLoading, setDryRunLoading] = useState(false)
  const [dryRunError, setDryRunError] = useState<string | null>(null)
  const [confirmOlderSchema, setConfirmOlderSchema] = useState(false)

  /* ---- submission + progress modal ---- */
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobMode, setJobMode] = useState<RestoreMode | null>(null)

  const selectedBackup = useMemo(
    () => backups.find((b) => b.id === selectedBackupId) ?? null,
    [backups, selectedBackupId],
  )
  const primaryDestination = useMemo(
    () => destinations.find((d) => d.is_primary) ?? null,
    [destinations],
  )
  const needsKey = keyStatus ? !keyStatus.has_active_key : false

  /* ---- initial fetch (keys/status + backups + destinations) ---- */
  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    setLoading(true)
    setLoadError(null)
    ;(async () => {
      try {
        const [status, backupList, destList] = await Promise.all([
          fetchKeyStatus(signal),
          fetchBackups(signal),
          fetchDestinations(signal),
        ])
        setKeyStatus(status)
        setBackups(backupList.items ?? [])
        setDestinations(destList.items ?? [])
      } catch (err) {
        if (signal.aborted) return
        setLoadError(errorDetail(err, 'Could not load restore data.'))
      } finally {
        if (!signal.aborted) setLoading(false)
      }
    })()
    return () => controller.abort()
  }, [])

  /* ---- preselect backup from ?backup_id= once backups load ---- */
  useEffect(() => {
    if (!preselectedBackupId) return
    if (backups.some((b) => b.id === preselectedBackupId)) {
      setSelectedBackupId(preselectedBackupId)
    }
  }, [preselectedBackupId, backups])

  /* ---- navigation ---- */
  const goToModeStep = useCallback(() => {
    setStep(needsKey ? 'key' : 'mode')
  }, [needsKey])

  const startMode = useCallback(() => {
    if (mode === 'per_org') setStep('perorg')
    else if (mode === 'dry_run') setStep('dryrun')
    else setStep('full')
  }, [mode])

  const resetWizard = useCallback(() => {
    setStep('source')
    setMode('full')
    setBrowseOrgs([])
    setSelectedOrgId('')
    setSelectedEntities(new Set())
    setConflictPolicy('overwrite')
    setRestoreFiles(true)
    setDryRun(null)
    setDryRunError(null)
    setConfirmOlderSchema(false)
    setSubmitError(null)
    setJobId(null)
    setJobMode(null)
  }, [])

  /* ---- key material bootstrap (Req 16.7) ---- */
  const onKitFileChange = useCallback((file: File | null) => {
    setKitError(null)
    if (!file) {
      setRecoveryKit(null)
      setRecoveryKitName('')
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result ?? '')) as RecoveryKit
        setRecoveryKit(parsed)
        setRecoveryKitName(file.name)
      } catch {
        setRecoveryKit(null)
        setRecoveryKitName('')
        setKitError('That file is not a valid Recovery Kit (expected JSON).')
      }
    }
    reader.onerror = () => setKitError('Could not read the selected file.')
    reader.readAsText(file)
  }, [])

  const onBootstrap = useCallback(async () => {
    if (!recoveryKit || !passphrase) {
      setKitError('Upload the Recovery Kit and enter its passphrase.')
      return
    }
    const controller = new AbortController()
    setBootstrapping(true)
    setKitError(null)
    try {
      const status = await bootstrapKey(
        recoveryKit,
        passphrase,
        selectedBackup?.key_version ?? null,
        controller.signal,
      )
      setKeyStatus(status)
      // Key material is now installed — the seamless path covers subsequent
      // restore calls, so we drop the kit/passphrase from memory.
      setRecoveryKit(null)
      setRecoveryKitName('')
      setPassphrase('')
      setStep('mode')
    } catch (err) {
      if (!controller.signal.aborted) {
        setKitError(errorDetail(err, 'Could not bootstrap the backup key from that kit.'))
      }
    } finally {
      if (!controller.signal.aborted) setBootstrapping(false)
    }
  }, [recoveryKit, passphrase, selectedBackup])

  /* ---- per-org browse (Req 15.1) ---- */
  useEffect(() => {
    if (step !== 'perorg' || !selectedBackupId) return
    const controller = new AbortController()
    const { signal } = controller
    setBrowseLoading(true)
    setBrowseError(null)
    ;(async () => {
      try {
        const res = await browseBackup(selectedBackupId, signal)
        setBrowseOrgs(res.items ?? [])
      } catch (err) {
        if (signal.aborted) return
        setBrowseError(errorDetail(err, 'Could not browse this backup.'))
      } finally {
        if (!signal.aborted) setBrowseLoading(false)
      }
    })()
    return () => controller.abort()
  }, [step, selectedBackupId])

  const onSelectOrg = useCallback(
    (orgId: string) => {
      setSelectedOrgId(orgId)
      // Default to "restore everything" — pre-select all of the org's entity
      // types so the restore is enabled by default; the operator can narrow it.
      const org = browseOrgs.find((o) => o.org_id === orgId)
      setSelectedEntities(new Set((org?.entities ?? []).map((e) => e.entity_type)))
    },
    [browseOrgs],
  )

  const toggleEntity = useCallback((entityType: string) => {
    setSelectedEntities((prev) => {
      const next = new Set(prev)
      if (next.has(entityType)) next.delete(entityType)
      else next.add(entityType)
      return next
    })
  }, [])

  const selectedOrg = useMemo(
    () => browseOrgs.find((o) => o.org_id === selectedOrgId) ?? null,
    [browseOrgs, selectedOrgId],
  )

  /* ---- full path dry-run (auto-run on entering the full step, Req 10.5) ---- */
  useEffect(() => {
    if ((step !== 'full' && step !== 'dryrun') || !selectedBackupId) return
    const controller = new AbortController()
    const { signal } = controller
    setDryRunLoading(true)
    setDryRunError(null)
    setDryRun(null)
    setConfirmOlderSchema(false)
    ;(async () => {
      try {
        const res = await runDryRun(selectedBackupId, null, null, signal)
        setDryRun(res)
      } catch (err) {
        if (signal.aborted) return
        setDryRunError(errorDetail(err, 'The pre-flight dry-run failed.'))
      } finally {
        if (!signal.aborted) setDryRunLoading(false)
      }
    })()
    return () => controller.abort()
  }, [step, selectedBackupId])

  /* ---- submit (full / per-org) ---- */
  const onSubmitFull = useCallback(async () => {
    if (!selectedBackupId || !dryRun) return
    const controller = new AbortController()
    setSubmitting(true)
    setSubmitError(null)
    try {
      const accepted = await submitFullRestore(
        selectedBackupId,
        dryRun.older_schema, // confirm_older_schema=true only when older (Req 10.6/10.7)
        null,
        null,
        controller.signal,
      )
      setJobId(accepted.job_id)
      setJobMode('full')
    } catch (err) {
      if (!controller.signal.aborted) {
        setSubmitError(errorDetail(err, 'Could not start the full restore.'))
      }
    } finally {
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }, [selectedBackupId, dryRun])

  const onSubmitPerOrg = useCallback(async () => {
    if (!selectedBackupId || !selectedOrgId) return
    const controller = new AbortController()
    setSubmitting(true)
    setSubmitError(null)
    try {
      const accepted = await submitPerOrgRestore(
        selectedBackupId,
        selectedOrgId,
        conflictPolicy,
        // No selection → restore the ENTIRE organisation (backend treats
        // selected_tables=null as all of the org's tables).
        selectedEntities.size > 0 ? Array.from(selectedEntities) : null,
        restoreFiles,
        null,
        null,
        controller.signal,
      )
      setJobId(accepted.job_id)
      setJobMode('per_org')
    } catch (err) {
      if (!controller.signal.aborted) {
        setSubmitError(errorDetail(err, 'Could not start the per-org restore.'))
      }
    } finally {
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }, [selectedBackupId, selectedOrgId, selectedEntities, conflictPolicy, restoreFiles])

  /* ---- stepper model ---- */
  const stepOrder = useMemo<WizardStep[]>(() => {
    const tail: WizardStep =
      step === 'perorg' ? 'perorg' : step === 'dryrun' ? 'dryrun' : 'full'
    const seq: WizardStep[] = ['source']
    if (needsKey) seq.push('key')
    seq.push('mode')
    seq.push(tail)
    return seq
  }, [needsKey, step])

  /* ---- early returns ---- */
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading restore data" />
      </div>
    )
  }

  if (loadError) {
    return (
      <AlertBanner variant="error" title="Error">
        {loadError}
      </AlertBanner>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-text">Restore Wizard</h1>
        <p className="mt-1 text-sm text-muted">
          Restore the platform from a cloud backup. Full restores are destructive
          and run under maintenance mode.
        </p>
      </div>

      {/* Stepper */}
      <ol className="flex flex-wrap items-center gap-2 text-[12.5px]">
        {stepOrder.map((s, idx) => {
          const active = s === step
          const done = stepOrder.indexOf(step) > idx
          return (
            <li key={s} className="flex items-center gap-2">
              <span
                className={`inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 font-medium ${
                  active
                    ? 'bg-accent text-white'
                    : done
                      ? 'bg-ok-soft text-ok'
                      : 'bg-[#EEF0F4] text-muted'
                }`}
              >
                {idx + 1}. {STEP_TITLES[s]}
              </span>
              {idx < stepOrder.length - 1 && <span className="text-muted-2">→</span>}
            </li>
          )
        })}
      </ol>

      {/* ---------------- Step: source ---------------- */}
      {step === 'source' && (
        <Card>
          <CardHead title="Select a backup to restore from" />
          <CardBody className="flex flex-col gap-4">
            {primaryDestination ? (
              <p className="text-[13px] text-muted">
                Backups are read from the primary destination:{' '}
                <span className="font-medium text-text">
                  {primaryDestination.display_name}
                </span>{' '}
                <Badge variant="info" dot={false}>
                  {primaryDestination.provider_type}
                </Badge>
              </p>
            ) : (
              <AlertBanner variant="warning" title="No primary destination">
                No primary backup destination is configured. Restores read from the
                primary destination — configure one before continuing.
              </AlertBanner>
            )}

            {backups.length === 0 ? (
              <p className="py-6 text-center text-muted">No backups are available.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {backups.map((b) => {
                  const selected = b.id === selectedBackupId
                  return (
                    <button
                      key={b.id}
                      type="button"
                      onClick={() => setSelectedBackupId(b.id)}
                      aria-pressed={selected}
                      className={`flex flex-col gap-1 rounded-ctl border px-4 py-3 text-left transition-colors ${
                        selected
                          ? 'border-accent bg-accent-soft'
                          : 'border-border bg-card hover:border-border-strong'
                      }`}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-text">{formatDate(b.created_at)}</span>
                        <Badge variant="neutral" dot={false}>{b.scope}</Badge>
                        {b.app_version && (
                          <span className="text-[12px] text-muted">v{b.app_version}</span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[12px] text-muted">
                        <span>Size: {formatBytes(b.dump_size_bytes)}</span>
                        <span>Files: {b.file_count ?? 0}</span>
                        {b.schema_version && <span>Schema: {b.schema_version}</span>}
                        {b.key_version != null && <span>Key v{b.key_version}</span>}
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {/* ---------------- Step: key material (Req 16.7) ---------------- */}
      {step === 'key' && (
        <Card>
          <CardHead title="Provide key material" />
          <CardBody className="flex flex-col gap-4">
            <AlertBanner variant="info" title="This deployment has no active backup key">
              To decrypt this backup, upload the Recovery Kit and enter its passphrase.
              This bootstraps the backup key for restore (Req 16.7).
            </AlertBanner>

            <div className="flex flex-col gap-[7px]">
              <label htmlFor="recovery-kit-file" className="text-[12.5px] font-medium text-text">
                Recovery Kit file (JSON)
              </label>
              <input
                id="recovery-kit-file"
                type="file"
                accept="application/json,.json"
                onChange={(e) => onKitFileChange(e.target.files?.[0] ?? null)}
                className="text-[13px] text-text file:mr-3 file:rounded-ctl file:border file:border-border file:bg-card file:px-3 file:py-1.5 file:text-[13px] file:text-text hover:file:border-border-strong"
              />
              {recoveryKitName && (
                <p className="text-[12px] text-muted">Loaded: {recoveryKitName}</p>
              )}
            </div>

            <Input
              label="Passphrase"
              type="password"
              autoComplete="off"
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
              placeholder="Recovery Kit passphrase"
            />

            {kitError && (
              <AlertBanner variant="error" title="Could not bootstrap key">
                {kitError}
              </AlertBanner>
            )}
          </CardBody>
        </Card>
      )}

      {/* ---------------- Step: mode ---------------- */}
      {step === 'mode' && (
        <Card>
          <CardHead title="Choose a restore mode" />
          <CardBody className="flex flex-col gap-3">
            {([
              {
                value: 'full' as RestoreMode,
                title: 'Full platform restore',
                desc: 'Destructive. Restores the entire platform under maintenance mode. Runs a pre-flight dry-run first.',
              },
              {
                value: 'per_org' as RestoreMode,
                title: 'Per-organisation restore',
                desc: 'Restore selected entity types for a single organisation with a conflict policy.',
              },
              {
                value: 'dry_run' as RestoreMode,
                title: 'Dry-run (validation only)',
                desc: 'Validate checksum + schema compatibility without writing any data.',
              },
            ]).map((opt) => {
              const selected = mode === opt.value
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setMode(opt.value)}
                  aria-pressed={selected}
                  className={`flex flex-col gap-1 rounded-ctl border px-4 py-3 text-left transition-colors ${
                    selected
                      ? 'border-accent bg-accent-soft'
                      : 'border-border bg-card hover:border-border-strong'
                  }`}
                >
                  <span className="font-medium text-text">{opt.title}</span>
                  <span className="text-[12.5px] text-muted">{opt.desc}</span>
                </button>
              )
            })}
          </CardBody>
        </Card>
      )}

      {/* ---------------- Step: per-org (Req 14, 15.1, 15.6) ---------------- */}
      {step === 'perorg' && (
        <Card>
          <CardHead title="Choose organisation + data to restore" />
          <CardBody className="flex flex-col gap-4">
            {browseLoading ? (
              <div className="flex justify-center py-8">
                <Spinner label="Browsing backup contents" />
              </div>
            ) : browseError ? (
              <AlertBanner variant="error" title="Browse failed">{browseError}</AlertBanner>
            ) : browseOrgs.length === 0 ? (
              <p className="py-6 text-center text-muted">
                This backup has no per-organisation contents to browse.
              </p>
            ) : (
              <>
                <Select
                  label="Organisation"
                  placeholder="Select an organisation"
                  value={selectedOrgId}
                  onChange={(e) => onSelectOrg(e.target.value)}
                  options={browseOrgs.map((o) => ({
                    value: o.org_id,
                    label: o.entities && o.entities.length > 0
                      ? `${o.org_name ?? o.org_id} (${o.entities.length} entity types)`
                      : (o.org_name ?? o.org_id),
                  }))}
                />

                {selectedOrg && (
                  <div className="flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                      <span className="text-[12.5px] font-medium text-text">
                        Entity types ({selectedEntities.size} selected)
                      </span>
                      {(selectedOrg.entities ?? []).length === 0 && (
                        <Badge variant="neutral" dot={false}>No org-scoped data</Badge>
                      )}
                    </div>
                    <div className="flex flex-col divide-y divide-border rounded-ctl border border-border">
                      {(selectedOrg.entities ?? []).map((e) => (
                        <label
                          key={e.entity_type}
                          className="flex cursor-pointer items-center justify-between gap-3 px-4 py-2.5"
                        >
                          <span className="flex items-center gap-2.5">
                            <input
                              type="checkbox"
                              checked={selectedEntities.has(e.entity_type)}
                              onChange={() => toggleEntity(e.entity_type)}
                              className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
                            />
                            <span className="text-[13.5px] text-text">{e.entity_type}</span>
                          </span>
                          <span className="text-[12.5px] text-muted">
                            {e.record_count ?? 0} records
                          </span>
                        </label>
                      ))}
                    </div>

                    <Select
                      label="Conflict policy"
                      value={conflictPolicy}
                      onChange={(e) => setConflictPolicy(e.target.value as ConflictPolicy)}
                      options={CONFLICT_OPTIONS}
                    />

                    {conflictPolicy === 'restore_as_new' ? (
                      <AlertBanner variant="warning">
                        {CONFLICT_HELP.restore_as_new}
                      </AlertBanner>
                    ) : (
                      <p className="text-[12.5px] text-muted">
                        {CONFLICT_HELP[conflictPolicy]}
                      </p>
                    )}

                    <label className="flex cursor-pointer items-center gap-2.5">
                      <input
                        type="checkbox"
                        checked={restoreFiles}
                        onChange={(e) => setRestoreFiles(e.target.checked)}
                        className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
                      />
                      <span className="text-[13px] text-text">Also restore stored files</span>
                    </label>

                    {selectedEntities.size === 0 && (
                      <p className="text-[12.5px] text-muted">
                        No entity types selected — the entire organisation will be restored.
                        Tick specific entity types above to restore only those.
                      </p>
                    )}
                  </div>
                )}
              </>
            )}

            {submitError && (
              <AlertBanner variant="error" title="Restore failed">{submitError}</AlertBanner>
            )}
          </CardBody>
        </Card>
      )}

      {/* ---------------- Step: full (Req 10.5-10.7, 12.1) ---------------- */}
      {step === 'full' && (
        <Card>
          <CardHead title="Full platform restore" />
          <CardBody className="flex flex-col gap-4">
            <AlertBanner variant="warning" title="This is a destructive operation">
              A full restore enters maintenance mode, fences any HA standby, takes a
              rollback snapshot, then replaces all platform data. Users are locked out
              until it completes.
            </AlertBanner>

            {dryRunLoading ? (
              <div className="flex justify-center py-8">
                <Spinner label="Running pre-flight dry-run" />
              </div>
            ) : dryRunError ? (
              <AlertBanner variant="error" title="Pre-flight dry-run failed">
                {dryRunError}
              </AlertBanner>
            ) : dryRun ? (
              <DryRunReport result={dryRun} />
            ) : null}

            {dryRun && dryRun.older_schema && (
              <div className="rounded-ctl border border-warn bg-warn-soft px-4 py-3">
                <p className="text-[13px] font-medium text-warn">Older-schema confirmation required</p>
                <p className="mt-1 text-[12.5px] text-text">
                  This backup was taken on an older schema ({dryRun.backup_version ?? 'unknown'})
                  than the current target ({dryRun.target_version ?? 'unknown'}). Restoring it
                  will roll the schema back.
                </p>
                <label className="mt-2 flex cursor-pointer items-center gap-2.5">
                  <input
                    type="checkbox"
                    checked={confirmOlderSchema}
                    onChange={(e) => setConfirmOlderSchema(e.target.checked)}
                    className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
                  />
                  <span className="text-[13px] text-text">
                    I understand and confirm restoring this older-schema backup.
                  </span>
                </label>
              </div>
            )}

            {submitError && (
              <AlertBanner variant="error" title="Restore failed">{submitError}</AlertBanner>
            )}
          </CardBody>
        </Card>
      )}

      {/* ---------------- Step: dry-run (read-only) ---------------- */}
      {step === 'dryrun' && (
        <Card>
          <CardHead title="Dry-run — validation only" />
          <CardBody className="flex flex-col gap-4">
            {dryRunLoading ? (
              <div className="flex justify-center py-8">
                <Spinner label="Running dry-run" />
              </div>
            ) : dryRunError ? (
              <AlertBanner variant="error" title="Dry-run failed">{dryRunError}</AlertBanner>
            ) : dryRun ? (
              <DryRunReport result={dryRun} />
            ) : null}
            <p className="text-[12.5px] text-muted">
              A dry-run writes no data. To apply a restore, choose Full or Per-org mode.
            </p>
          </CardBody>
        </Card>
      )}

      {/* ---------------- Footer navigation ---------------- */}
      <div className="flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={() => {
            if (step === 'key' || step === 'mode') setStep('source')
            else if (step === 'perorg' || step === 'full' || step === 'dryrun') setStep('mode')
          }}
          disabled={step === 'source'}
        >
          Back
        </Button>

        <div className="flex items-center gap-2">
          {step === 'source' && (
            <Button onClick={goToModeStep} disabled={!selectedBackupId || !primaryDestination}>
              Next
            </Button>
          )}
          {step === 'key' && (
            <Button onClick={onBootstrap} loading={bootstrapping} disabled={!recoveryKit || !passphrase}>
              Bootstrap key &amp; continue
            </Button>
          )}
          {step === 'mode' && <Button onClick={startMode}>Continue</Button>}
          {step === 'perorg' && (
            <Button
              onClick={onSubmitPerOrg}
              loading={submitting}
              disabled={!selectedOrgId}
            >
              Start per-org restore
            </Button>
          )}
          {step === 'full' && (
            <Button
              variant="danger"
              onClick={onSubmitFull}
              loading={submitting}
              disabled={
                !dryRun ||
                dryRunLoading ||
                !dryRun.checksum_ok ||
                (dryRun.older_schema && !confirmOlderSchema)
              }
            >
              Start full restore
            </Button>
          )}
        </div>
      </div>

      {/* ---------------- Live progress modal (Req 12.16, 12.17) ---------------- */}
      {jobId && (
        <RestoreProgressModal
          jobId={jobId}
          mode={jobMode ?? 'full'}
          onClose={resetWizard}
        />
      )}
    </div>
  )
}

/* ================================================================== */
/*  Dry-run report                                                     */
/* ================================================================== */

function DryRunReport({ result }: { result: DryRunResult }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={outcomeVariant(result.overall)} dot={false}>
          Overall: {result.overall}
        </Badge>
        <Badge variant={result.checksum_ok ? 'ok' : 'danger'} dot={false}>
          Checksum {result.checksum_ok ? 'OK' : 'failed'}
        </Badge>
        {result.older_schema && (
          <Badge variant="warn" dot={false}>Older schema</Badge>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[12.5px] text-muted">
        <span>Backup schema: {result.backup_version ?? '—'}</span>
        <span>Target schema: {result.target_version ?? '—'}</span>
        <span>Elapsed: {result.elapsed_seconds.toFixed(1)}s</span>
      </div>
      {(result.steps ?? []).length > 0 && (
        <div className="flex flex-col divide-y divide-border rounded-ctl border border-border">
          {(result.steps ?? []).map((s) => (
            <div key={s.name} className="flex items-start justify-between gap-3 px-4 py-2.5">
              <div className="flex flex-col">
                <span className="text-[13px] text-text">{s.name}</span>
                {s.detail && <span className="text-[12px] text-muted">{s.detail}</span>}
              </div>
              <Badge variant={outcomeVariant(s.outcome)} dot={false}>{s.outcome}</Badge>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ================================================================== */
/*  Live progress modal                                                */
/* ================================================================== */

function RestoreProgressModal({
  jobId,
  mode,
  onClose,
}: {
  jobId: string
  mode: RestoreMode
  onClose: () => void
}) {
  const [cancelling, setCancelling] = useState(false)
  const [cancelDisabled, setCancelDisabled] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [variant, setVariant] = useState<'info' | 'success' | 'warning' | 'error'>('info')
  const [status, setStatus] = useState<JobStatus | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)

  const isTerminal =
    status != null &&
    (TERMINAL_RESTORE_STATUSES as readonly string[]).includes(status.status)
  const succeeded = status?.status === 'completed'
  const failed = status?.status === 'failed'
  const cancelledState = status?.status === 'cancelled'

  // Poll the restore job status until it reaches a terminal state (Req 13.3).
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let stopped = false

    const tick = async () => {
      try {
        const next = await getRestoreJobStatus(jobId, controller.signal)
        if (stopped) return
        setStatus(next)
        setPollError(null)
        if ((TERMINAL_RESTORE_STATUSES as readonly string[]).includes(next.status)) {
          return // terminal — stop polling
        }
      } catch (err) {
        if (controller.signal.aborted || stopped) return
        setPollError(errorDetail(err, 'Could not read restore status.'))
      }
      if (!stopped) timer = setTimeout(tick, 2000)
    }

    tick()
    return () => {
      stopped = true
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [jobId])

  const onCancel = useCallback(async () => {
    const controller = new AbortController()
    setCancelling(true)
    setMessage(null)
    try {
      const outcome = await cancelRestoreJob(jobId, controller.signal)
      if (outcome.applyStarted) {
        // 409 — destructive apply already started (Req 12.17). Disable cancel.
        setCancelDisabled(true)
        setVariant('warning')
        setMessage(outcome.detail ?? 'The restore can no longer be cancelled.')
      } else if (outcome.cancelled) {
        setCancelDisabled(true)
        setVariant('success')
        setMessage('Cancellation requested. The restore will stop before applying data.')
      }
    } catch (err) {
      setVariant('error')
      setMessage(errorDetail(err, 'Could not request cancellation.'))
    } finally {
      if (!controller.signal.aborted) setCancelling(false)
    }
  }, [jobId])

  // Cancel applies to the destructive full path AND per-org restores (which
  // cancel cooperatively and roll back). Dry-run has nothing to abort.
  const showCancel =
    (mode === 'full' || mode === 'per_org') && !cancelDisabled && !isTerminal

  const headline =
    mode === 'full'
      ? 'Full platform restore'
      : mode === 'per_org'
        ? 'Per-organisation restore'
        : 'Restore'

  const statusLabel = !status
    ? 'Starting…'
    : succeeded
      ? 'Completed'
      : failed
        ? 'Failed'
        : cancelledState
          ? 'Cancelled'
          : status.status === 'running'
            ? 'Running'
            : 'Queued'

  const pct = Math.max(0, Math.min(100, status?.progress_pct ?? 0))
  const sinceUpdate = status?.seconds_since_last_update ?? 0
  // The backend force-fails a job with no progress/heartbeat for 60s; warn the
  // operator before then so they can choose to abort a seemingly stuck restore.
  const looksStalled = !isTerminal && status?.status === 'running' && sinceUpdate > 25

  return (
    <Modal open onClose={onClose} title="Restore in progress">
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-3">
          {!isTerminal && <Spinner size="sm" label="Restore running" />}
          <div className="flex flex-col">
            <span className="text-[13.5px] font-medium text-text">
              {headline} — {statusLabel}
            </span>
            <span className="text-[12px] text-muted">Job {jobId}</span>
          </div>
        </div>

        {!isTerminal && (
          <div className="flex flex-col gap-1.5">
            {/* Live progress bar */}
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted/20">
              <div
                className="h-full rounded-full bg-accent transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[12px] text-muted">
              <span>{status?.outcome_summary ?? 'Working…'}</span>
              <span>{pct}%</span>
            </div>
          </div>
        )}

        {looksStalled && (
          <AlertBanner variant="warning">
            No update for {Math.round(sinceUpdate)}s. The restore may be slow on a
            large dataset, or stalled. You can cancel it — nothing is applied until
            it finishes, and a cancel rolls back cleanly.
          </AlertBanner>
        )}

        {succeeded && (
          <AlertBanner variant="success">
            {status?.outcome_summary ?? 'Restore completed successfully.'}
          </AlertBanner>
        )}

        {failed && (
          <AlertBanner variant="error">
            {status?.error_message
              ? `Restore failed and was rolled back: ${status.error_message}`
              : 'Restore failed and was rolled back. No data was changed.'}
          </AlertBanner>
        )}

        {cancelledState && (
          <AlertBanner variant="warning">
            {status?.outcome_summary ?? 'Restore was cancelled before applying data.'}
          </AlertBanner>
        )}

        {pollError && !isTerminal && (
          <AlertBanner variant="warning">{pollError}</AlertBanner>
        )}

        {message && <AlertBanner variant={variant}>{message}</AlertBanner>}

        <div className="flex items-center justify-end gap-2">
          {showCancel && (
            <Button variant="ghost" onClick={onCancel} loading={cancelling}>
              Cancel restore
            </Button>
          )}
          <Button onClick={onClose}>Close</Button>
        </div>
      </div>
    </Modal>
  )
}
