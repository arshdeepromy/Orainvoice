/**
 * ReminderConsentStep — kiosk reminder-consent capture step.
 *
 * Sits between the customer-details form and the success screen in the kiosk
 * wizard. Captures the customer's opt-in to WOF / COF / registration / service
 * reminders, per vehicle, per channel.
 *
 * Key behaviours:
 *  - Master toggle defaults UNCHECKED; every sub-checkbox + channel resets on
 *    mount with NO localStorage/sessionStorage read (Req 1.2/1.3, CP-4).
 *  - One inspection-type checkbox per vehicle (WOF | COF | none) via
 *    resolveInspectionTypeRow (Req 1.5a–5e).
 *  - Per-checkbox tri-state channel control (SMS / Email / Both), no
 *    preselection (Req 1.6); parent submit is gated while any ticked row
 *    lacks a channel (Req 1.11) via onValidityChange.
 *  - Non-automotive trade families see only Service Due (Req 1.5e, NFR-6).
 *  - Accessibility: 16px+ consent text, ≥44px hit areas, labelled controls
 *    (Req 1.9/1.10, NFR-4).
 */

import { useEffect, useMemo, useState } from 'react'
import type {
  KioskReminderConsentBlock,
  KioskReminderConsentEntry,
  ReminderCategory,
  ReminderChannel,
  ReminderConsentVehicle,
} from './types'
import { inspectionCategory, resolveInspectionTypeRow } from './consentRules'

export interface ReminderConsentStepProps {
  vehicles: ReminderConsentVehicle[]
  consentText: string
  consentTextVersion: string
  isAutomotive: boolean
  onChange: (block: KioskReminderConsentBlock | null) => void
  onValidityChange?: (valid: boolean) => void
  onContinue?: () => void
  onBack?: () => void
}

interface Row {
  key: string
  vehicleId: string
  category: ReminderCategory
  label: string
}

const CATEGORY_LABEL: Record<ReminderCategory, string> = {
  wof_expiry: 'WOF expiry',
  cof_expiry: 'COF expiry',
  registration_expiry: 'Registration expiry',
  service_due: 'Service due',
}

const CHANNELS: { value: ReminderChannel; label: string }[] = [
  { value: 'sms', label: 'SMS' },
  { value: 'email', label: 'Email' },
  { value: 'both', label: 'Both' },
]

/** Build the ordered list of (vehicle, category) rows to render. */
function buildRows(
  vehicles: ReminderConsentVehicle[],
  isAutomotive: boolean,
): Row[] {
  const rows: Row[] = []
  vehicles.forEach((v, i) => {
    const cats: ReminderCategory[] = []
    if (isAutomotive) {
      const insp = inspectionCategory(resolveInspectionTypeRow(v))
      if (insp) cats.push(insp)
    }
    cats.push('service_due')
    cats.forEach((category) => {
      rows.push({
        key: `${i}:${category}`,
        vehicleId: v.global_vehicle_id,
        category,
        label: CATEGORY_LABEL[category],
      })
    })
  })
  return rows
}

export function ReminderConsentStep({
  vehicles,
  consentText,
  consentTextVersion,
  isAutomotive,
  onChange,
  onValidityChange,
  onContinue,
  onBack,
}: ReminderConsentStepProps) {
  const rows = useMemo(
    () => buildRows(vehicles ?? [], isAutomotive),
    [vehicles, isAutomotive],
  )

  // Master toggle — defaults UNCHECKED, no persisted state (CP-4).
  const [master, setMaster] = useState(false)
  // Per-row checked state and chosen channel ('' = none chosen yet).
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [channels, setChannels] = useState<Record<string, ReminderChannel | ''>>(
    {},
  )

  function toggleMaster(next: boolean) {
    setMaster(next)
    if (next) {
      // Pre-select every sub-checkbox; channels stay empty (no preselection).
      const allChecked: Record<string, boolean> = {}
      rows.forEach((r) => {
        allChecked[r.key] = true
      })
      setChecked(allChecked)
    } else {
      setChecked({})
      setChannels({})
    }
  }

  function toggleRow(key: string, next: boolean) {
    setChecked((prev) => ({ ...prev, [key]: next }))
    if (!next) {
      setChannels((prev) => {
        const copy = { ...prev }
        delete copy[key]
        return copy
      })
    }
  }

  function setChannel(key: string, value: ReminderChannel) {
    setChannels((prev) => ({ ...prev, [key]: value }))
  }

  // Derive the consent block + validity and notify the parent on every change.
  const { block, valid } = useMemo(() => {
    if (!master) {
      return { block: null as KioskReminderConsentBlock | null, valid: true }
    }
    const tickedRows = rows.filter((r) => checked[r.key])
    const anyMissingChannel = tickedRows.some((r) => !channels[r.key])
    const entries: KioskReminderConsentEntry[] = tickedRows
      .filter((r) => channels[r.key])
      .map((r) => ({
        vehicle_id: r.vehicleId,
        category: r.category,
        channel: channels[r.key] as ReminderChannel,
      }))
    const nextBlock: KioskReminderConsentBlock | null =
      entries.length > 0
        ? { consent_text_version: consentTextVersion, entries }
        : null
    return { block: nextBlock, valid: !anyMissingChannel }
  }, [master, rows, checked, channels, consentTextVersion])

  useEffect(() => {
    onChange(block)
  }, [block, onChange])

  useEffect(() => {
    onValidityChange?.(valid)
  }, [valid, onValidityChange])

  return (
    <div className="mx-auto max-w-2xl p-4">
      <h2 className="text-xl font-semibold text-text">Stay reminded</h2>

      {/* Primary consent text — 16px+ for kiosk legibility (Req 1.9). */}
      <p className="mt-2 text-base leading-relaxed text-text">{consentText}</p>

      {/* Master opt-in toggle. */}
      <label
        htmlFor="reminder-consent-master"
        className="mt-4 flex min-h-[44px] cursor-pointer items-center gap-3 rounded-ctl border border-border p-3"
      >
        <input
          id="reminder-consent-master"
          type="checkbox"
          checked={master}
          onChange={(e) => toggleMaster(e.target.checked)}
          className="h-6 w-6"
        />
        <span className="text-base font-medium text-text">
          Yes, send me reminders
        </span>
      </label>

      {master && (
        <div className="mt-4 space-y-5">
          {vehicles.map((v, i) => {
            const vehicleRows = rows.filter((r) => r.key.startsWith(`${i}:`))
            if (vehicleRows.length === 0) return null
            const heading = [v.rego, v.make, v.model]
              .filter(Boolean)
              .join(' · ')
            return (
              <fieldset
                key={v.global_vehicle_id || i}
                className="rounded-card border border-border p-3"
              >
                <legend className="px-1 text-sm font-semibold text-text">
                  {heading || 'Vehicle'}
                </legend>
                <div className="space-y-3">
                  {vehicleRows.map((r) => {
                    const isChecked = !!checked[r.key]
                    const chan = channels[r.key] ?? ''
                    const channelMissing = isChecked && !chan
                    return (
                      <div key={r.key}>
                        <label
                          htmlFor={`cb-${r.key}`}
                          className="flex min-h-[44px] cursor-pointer items-center gap-3"
                        >
                          <input
                            id={`cb-${r.key}`}
                            type="checkbox"
                            checked={isChecked}
                            onChange={(e) => toggleRow(r.key, e.target.checked)}
                            className="h-6 w-6"
                          />
                          <span className="text-base text-text">{r.label}</span>
                        </label>
                        {isChecked && (
                          <div
                            role="group"
                            aria-label={`${r.label} reminder channel`}
                            className="ml-9 mt-1 flex flex-wrap gap-2"
                          >
                            {CHANNELS.map((c) => (
                              <button
                                key={c.value}
                                type="button"
                                aria-pressed={chan === c.value}
                                onClick={() => setChannel(r.key, c.value)}
                                className={`min-h-[44px] min-w-[44px] rounded-ctl border px-3 text-sm font-medium transition-colors ${
                                  chan === c.value
                                    ? 'border-accent bg-accent-soft text-accent'
                                    : 'border-border text-muted hover:text-text'
                                }`}
                              >
                                {c.label}
                              </button>
                            ))}
                            {channelMissing && (
                              <span className="self-center text-xs text-warn">
                                Choose a channel
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </fieldset>
            )
          })}
        </div>
      )}

      {/* Secondary supporting note — 12px+ (Req 1.10). */}
      <p className="mt-4 text-xs text-muted-2">
        You can change or withdraw consent at any time by phoning the workshop,
        without penalty. Consent version {consentTextVersion}.
      </p>

      {(onContinue || onBack) && (
        <div className="mt-6 flex items-center justify-between gap-3">
          {onBack ? (
            <button
              type="button"
              onClick={onBack}
              className="min-h-[44px] rounded-ctl border border-border px-6 text-base font-medium text-muted hover:text-text"
            >
              Back
            </button>
          ) : (
            <span />
          )}
          {onContinue && (
            <button
              type="button"
              onClick={onContinue}
              disabled={!valid}
              className="min-h-[44px] min-w-[44px] rounded-ctl bg-accent px-6 text-base font-medium text-white disabled:opacity-50"
            >
              Continue
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export default ReminderConsentStep
