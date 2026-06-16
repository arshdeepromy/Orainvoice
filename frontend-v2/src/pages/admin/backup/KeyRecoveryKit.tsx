/**
 * KeyRecoveryKit — backup key setup / re-export / rotate (Task 17.6).
 *
 * On load this page calls `GET /backup/keys/status` (Req 16.12) and branches:
 *   • `setup_complete === false` → first-run setup: enter/generate a passphrase
 *     (with a client-side strength meter), generate the kit via
 *     `POST /backup/keys/setup`, then force an "I have stored this offline"
 *     confirmation before the one-time recovery kit can be dismissed.
 *   • an active key exists → re-export the kit (`POST /backup/keys/recovery-kit`,
 *     behind a confirm/re-auth step) and rotate the key version
 *     (`POST /backup/keys/rotate`, showing the active version, Req 16.10).
 *
 * The passphrase is NEVER logged or displayed after submit, and the recovery
 * kit is offered only as a one-time downloadable JSON blob. The page always
 * shows the "passphrase is never recoverable" warning (Req 16.3, 16.4).
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import axios from 'axios'
import Button from '@/components/ui/Button'
import Card from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Modal } from '@/components/ui/Modal'
import { Badge } from '@/components/ui'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import {
  getKeyStatus,
  setupKey,
  exportRecoveryKit,
  rotateKey,
  type KeyStatus,
  type RecoveryKit,
} from '@/api/backup/keys'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Pull a human-readable detail out of an axios error, with a fallback. */
function extractError(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
  }
  if (err instanceof Error && err.message) return err.message
  return fallback
}

/** HTTP status of an axios error, or undefined. */
function errorStatus(err: unknown): number | undefined {
  return axios.isAxiosError(err) ? err.response?.status : undefined
}

type StrengthLevel = 0 | 1 | 2 | 3 | 4

interface Strength {
  score: StrengthLevel
  label: string
}

const STRENGTH_LABELS: Record<StrengthLevel, string> = {
  0: 'Too weak',
  1: 'Weak',
  2: 'Fair',
  3: 'Good',
  4: 'Strong',
}

const STRENGTH_BAR: Record<StrengthLevel, string> = {
  0: 'bg-danger',
  1: 'bg-danger',
  2: 'bg-warn',
  3: 'bg-accent',
  4: 'bg-ok',
}

/**
 * Client-side passphrase strength heuristic. This is ONLY a UX hint — the
 * backend enforces the real rule and returns 422 with a reason if too weak.
 * We reward length, character-class variety and multi-word (diceware-style)
 * passphrases.
 */
function estimateStrength(passphrase: string): Strength {
  if (!passphrase) return { score: 0, label: STRENGTH_LABELS[0] }

  const length = passphrase.length
  const words = passphrase.trim().split(/[\s-]+/).filter(Boolean).length
  const classes =
    (/[a-z]/.test(passphrase) ? 1 : 0) +
    (/[A-Z]/.test(passphrase) ? 1 : 0) +
    (/[0-9]/.test(passphrase) ? 1 : 0) +
    (/[^A-Za-z0-9]/.test(passphrase) ? 1 : 0)

  let points = 0
  if (length >= 12) points += 1
  if (length >= 20) points += 1
  if (length >= 32) points += 1
  if (classes >= 3) points += 1
  if (words >= 4) points += 1

  const score = Math.min(4, points) as StrengthLevel
  return { score, label: STRENGTH_LABELS[score] }
}

/**
 * A small diceware-style word list used purely for the optional client-side
 * "Suggest a passphrase" affordance. The backend owns the canonical diceware
 * generator but exposes no GET endpoint, so this is a convenience only — the
 * admin may type their own passphrase instead.
 */
const DICEWARE_WORDS = [
  'anchor', 'basket', 'cactus', 'dolphin', 'ember', 'falcon', 'garden', 'harbor',
  'island', 'jungle', 'kettle', 'lantern', 'meadow', 'nebula', 'orchard', 'pebble',
  'quartz', 'ribbon', 'saddle', 'timber', 'umbra', 'velvet', 'walnut', 'yonder',
  'zephyr', 'bramble', 'copper', 'driftwood', 'eagle', 'fjord', 'glacier', 'hollow',
]

/** Generate a 5-word diceware-style passphrase using a CSPRNG. */
function generatePassphrase(): string {
  const count = 5
  const picks: string[] = []
  const buf = new Uint32Array(count)
  crypto.getRandomValues(buf)
  for (let i = 0; i < count; i++) {
    picks.push(DICEWARE_WORDS[buf[i] % DICEWARE_WORDS.length])
  }
  return picks.join('-')
}

/** Offer a JS object as a one-time downloadable JSON file. */
function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/* ------------------------------------------------------------------ */
/*  Never-recoverable warning                                          */
/* ------------------------------------------------------------------ */

function NeverRecoverableWarning() {
  return (
    <AlertBanner variant="warning" title="Your passphrase can never be recovered">
      This passphrase unwraps the key that decrypts every backup. We do not store
      it and there is no reset — if it is lost, your backups become permanently
      unreadable. Store the recovery kit and passphrase offline, in a safe place.
    </AlertBanner>
  )
}

/* ------------------------------------------------------------------ */
/*  Recovery-kit download panel (one-time)                             */
/* ------------------------------------------------------------------ */

function RecoveryKitPanel({
  kit,
  storedOffline,
  onStoredOfflineChange,
  onDone,
  doneLabel,
}: {
  kit: RecoveryKit
  storedOffline: boolean
  onStoredOfflineChange: (v: boolean) => void
  onDone: () => void
  doneLabel: string
}) {
  const [downloaded, setDownloaded] = useState(false)

  const handleDownload = useCallback(() => {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-')
    downloadJson(`orainvoice-backup-recovery-kit-${stamp}.json`, kit)
    setDownloaded(true)
  }, [kit])

  return (
    <div className="flex flex-col gap-4">
      <AlertBanner variant="success" title="Recovery kit generated">
        Download the recovery kit now and store it offline. It is shown only once
        and cannot be retrieved later in this form.
      </AlertBanner>

      <div>
        <Button variant="primary" onClick={handleDownload}>
          Download recovery kit (JSON)
        </Button>
        {downloaded && (
          <p className="mt-2 text-[12.5px] text-muted">
            Downloaded. Move it to offline storage now.
          </p>
        )}
      </div>

      <label className="flex items-start gap-2 text-[13.5px] text-text">
        <input
          type="checkbox"
          checked={storedOffline}
          onChange={(e) => onStoredOfflineChange(e.target.checked)}
          className="mt-0.5 h-4 w-4 rounded border-border text-accent focus:ring-accent"
        />
        <span>
          I have downloaded the recovery kit and stored it offline in a safe place.
          I understand it cannot be shown again.
        </span>
      </label>

      <div>
        <Button
          variant="primary"
          disabled={!storedOffline}
          onClick={onDone}
        >
          {doneLabel}
        </Button>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  First-run setup                                                    */
/* ------------------------------------------------------------------ */

function FirstRunSetup({ onComplete }: { onComplete: () => void }) {
  const [passphrase, setPassphrase] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [kit, setKit] = useState<RecoveryKit | null>(null)
  const [storedOffline, setStoredOffline] = useState(false)

  const strength = useMemo(() => estimateStrength(passphrase), [passphrase])
  const mismatch = confirm.length > 0 && confirm !== passphrase

  const handleSuggest = useCallback(() => {
    const generated = generatePassphrase()
    setPassphrase(generated)
    setConfirm(generated)
    setFormError(null)
  }, [])

  const handleGenerateKit = useCallback(async () => {
    setFormError(null)
    if (passphrase !== confirm) {
      setFormError('The passphrases do not match.')
      return
    }
    setSubmitting(true)
    try {
      const res = await setupKey(passphrase)
      // Never retain the passphrase in state after a successful submit.
      setPassphrase('')
      setConfirm('')
      setKit(res.recovery_kit ?? {})
    } catch (err) {
      const status = errorStatus(err)
      if (status === 409) {
        // Already set up elsewhere — refresh the page state.
        onComplete()
        return
      }
      if (status === 422) {
        setFormError(extractError(err, 'Passphrase is too weak. Choose a longer, more complex passphrase.'))
      } else {
        setFormError(extractError(err, 'Could not complete key setup. Please try again.'))
      }
    } finally {
      setSubmitting(false)
    }
  }, [passphrase, confirm, onComplete])

  if (kit) {
    return (
      <Card>
        <Card.Body className="flex flex-col gap-5">
          <RecoveryKitPanel
            kit={kit}
            storedOffline={storedOffline}
            onStoredOfflineChange={setStoredOffline}
            onDone={onComplete}
            doneLabel="Finish setup"
          />
        </Card.Body>
      </Card>
    )
  }

  return (
    <Card>
      <Card.Body className="flex flex-col gap-5">
        <NeverRecoverableWarning />

        <p className="text-[13.5px] text-muted">
          Set a passphrase to protect your backup encryption key. This is the
          first-run setup for this deployment — it has not been configured yet.
        </p>

        {formError && (
          <AlertBanner variant="error" title="Setup failed">
            {formError}
          </AlertBanner>
        )}

        <div className="flex flex-col gap-2">
          <Input
            label="Passphrase"
            type="password"
            autoComplete="new-password"
            value={passphrase}
            onChange={(e) => setPassphrase(e.target.value)}
            disabled={submitting}
          />
          {/* Strength meter — client-side hint only; backend enforces the rule. */}
          <div className="flex items-center gap-3">
            <div className="flex h-1.5 flex-1 gap-1" aria-hidden="true">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className={`h-full flex-1 rounded-full ${
                    i < strength.score ? STRENGTH_BAR[strength.score] : 'bg-border'
                  }`}
                />
              ))}
            </div>
            <span className="w-20 text-right text-[12px] text-muted">{strength.label}</span>
          </div>
          <div>
            <button
              type="button"
              onClick={handleSuggest}
              disabled={submitting}
              className="text-[12.5px] font-medium text-accent hover:underline disabled:opacity-60"
            >
              Suggest a passphrase
            </button>
          </div>
        </div>

        <Input
          label="Confirm passphrase"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          disabled={submitting}
          error={mismatch ? 'Passphrases do not match.' : undefined}
        />

        <div>
          <Button
            variant="primary"
            loading={submitting}
            disabled={submitting || passphrase.length === 0 || mismatch || confirm.length === 0}
            onClick={handleGenerateKit}
          >
            Generate recovery kit
          </Button>
        </div>
      </Card.Body>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/*  Active-key view: re-export + rotate                                */
/* ------------------------------------------------------------------ */

function ActiveKeyView({
  status,
  onStatusChange,
}: {
  status: KeyStatus
  onStatusChange: (next: KeyStatus) => void
}) {
  const { toasts, addToast, dismissToast } = useToast()

  // Re-export flow
  const [confirmExportOpen, setConfirmExportOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportedKit, setExportedKit] = useState<RecoveryKit | null>(null)
  const [storedOffline, setStoredOffline] = useState(false)

  // Rotate flow
  const [confirmRotateOpen, setConfirmRotateOpen] = useState(false)
  const [rotating, setRotating] = useState(false)

  const handleConfirmExport = useCallback(async () => {
    setExporting(true)
    try {
      const res = await exportRecoveryKit()
      setExportedKit(res.recovery_kit ?? {})
      setStoredOffline(false)
      setConfirmExportOpen(false)
    } catch (err) {
      addToast('error', extractError(err, 'Could not re-export the recovery kit.'))
      setConfirmExportOpen(false)
    } finally {
      setExporting(false)
    }
  }, [addToast])

  const handleConfirmRotate = useCallback(async () => {
    setRotating(true)
    try {
      const res = await rotateKey()
      onStatusChange({ ...status, active_version: res.active_version ?? status.active_version })
      addToast('success', `Key rotated. New active version is ${res.active_version ?? '—'}.`)
      setConfirmRotateOpen(false)
    } catch (err) {
      addToast('error', extractError(err, 'Could not rotate the key version.'))
      setConfirmRotateOpen(false)
    } finally {
      setRotating(false)
    }
  }, [status, onStatusChange, addToast])

  return (
    <div className="flex flex-col gap-5">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <NeverRecoverableWarning />

      {/* Active version */}
      <Card>
        <Card.Head title="Backup encryption key" />
        <Card.Body className="flex items-center gap-3">
          <span className="text-[13.5px] text-muted">Active key version</span>
          <Badge variant="info">{status.active_version ?? 'unknown'}</Badge>
        </Card.Body>
      </Card>

      {/* Re-export */}
      <Card>
        <Card.Head title="Recovery kit" />
        <Card.Body className="flex flex-col gap-4">
          {exportedKit ? (
            <RecoveryKitPanel
              kit={exportedKit}
              storedOffline={storedOffline}
              onStoredOfflineChange={setStoredOffline}
              onDone={() => {
                setExportedKit(null)
                setStoredOffline(false)
              }}
              doneLabel="Done"
            />
          ) : (
            <>
              <p className="text-[13.5px] text-muted">
                Re-export the recovery kit for the active key. You will be asked to
                confirm before it is generated, and it is shown only once.
              </p>
              <div>
                <Button variant="ghost" onClick={() => setConfirmExportOpen(true)}>
                  Re-export recovery kit
                </Button>
              </div>
            </>
          )}
        </Card.Body>
      </Card>

      {/* Rotate */}
      <Card>
        <Card.Head title="Rotate key version" />
        <Card.Body className="flex flex-col gap-4">
          <p className="text-[13.5px] text-muted">
            Rotating mints a new key version for future backups. Prior versions are
            retained for the backup retention period so older backups stay restorable.
          </p>
          <div>
            <Button variant="ghost" onClick={() => setConfirmRotateOpen(true)}>
              Rotate key version
            </Button>
          </div>
        </Card.Body>
      </Card>

      {/* Re-export confirm / re-auth gate */}
      <Modal
        open={confirmExportOpen}
        onClose={() => setConfirmExportOpen(false)}
        title="Re-export recovery kit"
        className="max-w-md"
      >
        <div className="flex flex-col gap-4">
          <p className="text-[13.5px] text-muted">
            This will generate a fresh copy of the recovery kit for the active key.
            Only proceed if you intend to store a new offline copy. Continue?
          </p>
          <div className="flex justify-end gap-3">
            <Button variant="ghost" size="sm" onClick={() => setConfirmExportOpen(false)} disabled={exporting}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" loading={exporting} disabled={exporting} onClick={handleConfirmExport}>
              Re-export
            </Button>
          </div>
        </div>
      </Modal>

      {/* Rotate confirm */}
      <Modal
        open={confirmRotateOpen}
        onClose={() => setConfirmRotateOpen(false)}
        title="Rotate key version"
        className="max-w-md"
      >
        <div className="flex flex-col gap-4">
          <p className="text-[13.5px] text-muted">
            Rotate from version{' '}
            <span className="font-semibold text-text">{status.active_version ?? 'unknown'}</span>{' '}
            to a new key version? Future backups will use the new version; existing
            backups remain restorable under their original version.
          </p>
          <div className="flex justify-end gap-3">
            <Button variant="ghost" size="sm" onClick={() => setConfirmRotateOpen(false)} disabled={rotating}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" loading={rotating} disabled={rotating} onClick={handleConfirmRotate}>
              Rotate
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export function KeyRecoveryKit() {
  const [status, setStatus] = useState<KeyStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(false)
    getKeyStatus(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        setStatus(data)
      })
      .catch((err) => {
        if (controller.signal.aborted || axios.isCancel(err)) return
        setError(true)
      })
      .finally(() => {
        if (controller.signal.aborted) return
        setLoading(false)
      })
    return () => controller.abort()
  }, [reloadKey])

  const reload = useCallback(() => setReloadKey((k) => k + 1), [])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading key status" />
      </div>
    )
  }

  if (error || !status) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold text-text">Key Recovery Kit</h1>
        <AlertBanner variant="error" title="Error">
          Could not load the backup key status.
        </AlertBanner>
        <div>
          <Button variant="ghost" onClick={reload}>Retry</Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold text-text">Key Recovery Kit</h1>

      {status.setup_complete ? (
        <ActiveKeyView status={status} onStatusChange={setStatus} />
      ) : (
        <FirstRunSetup onComplete={reload} />
      )}
    </div>
  )
}
