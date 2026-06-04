/**
 * ClockInPolicyPage — Settings → People → Clock-in Policy.
 *
 * Renders three editable cards (G1 + G8 + G17):
 *   1. Clock-in policy — default channel, photo + geofence policy,
 *      branch radius default (with the per-branch override note),
 *      late-edit toggle, kiosk lookup rate-limit, plus the
 *      `shift_swap_requires_manager_approval` toggle (G8).
 *   2. Overtime policy (G1) — weekly + daily threshold minutes,
 *      `require_pre_approval` toggle, plus the existing
 *      `overtime_handling` enum from Phase 2.
 *
 * Data flow:
 *   GET /api/v2/org/clock-in-policy → {
 *     clock_in_policy: { ... },
 *     overtime_policy: { ... },
 *     overtime_handling: 'pay_cash' | 'toil' | 'employee_chooses',
 *   }
 *   PUT /api/v2/org/clock-in-policy → same shape (returns updated row).
 *
 * The endpoints follow the project's established settings-PUT pattern
 * (mirrors `app/modules/organisations/router.py::PUT /settings`). When
 * the backend hasn't shipped them yet the page surfaces a clear "load
 * failed" banner and disables the form so admins know the feature isn't
 * live yet rather than silently dropping their input.
 *
 * Refs: Phase 3 R6, R6a, G1, G8, G17. Touch targets ≥ 44×44.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import apiClient from '@/api/client'

/* ─────────────────────────────────────────────── Types ── */

type DefaultChannel = 'kiosk_only' | 'kiosk_and_self_service'
type OvertimeHandling = 'pay_cash' | 'toil' | 'employee_chooses'

interface ClockInPolicy {
  default_channel: DefaultChannel
  self_service_require_photo: boolean
  self_service_require_geofence: boolean
  branch_radius_metres: number
  allow_late_clock_out_edits: boolean
  kiosk_employee_id_rate_limit: number
  shift_swap_requires_manager_approval: boolean
}

interface OvertimePolicy {
  weekly_threshold_minutes: number
  daily_threshold_minutes: number
  require_pre_approval: boolean
}

interface ClockInPolicyResponse {
  clock_in_policy?: Partial<ClockInPolicy> | null
  overtime_policy?: Partial<OvertimePolicy> | null
  overtime_handling?: OvertimeHandling | null
}

const DEFAULT_CLOCK_IN_POLICY: ClockInPolicy = {
  default_channel: 'kiosk_only',
  self_service_require_photo: true,
  self_service_require_geofence: false,
  branch_radius_metres: 200,
  allow_late_clock_out_edits: true,
  kiosk_employee_id_rate_limit: 10,
  shift_swap_requires_manager_approval: false,
}

const DEFAULT_OVERTIME_POLICY: OvertimePolicy = {
  weekly_threshold_minutes: 2400,
  daily_threshold_minutes: 480,
  require_pre_approval: false,
}

const DEFAULT_OVERTIME_HANDLING: OvertimeHandling = 'pay_cash'

/* ─────────────────────────────────────── helpers ── */

function isAbortError(err: unknown): boolean {
  if (axios.isCancel?.(err)) return true
  if (err instanceof DOMException && err.name === 'AbortError') return true
  if (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    (err as { code?: string }).code === 'ERR_CANCELED'
  ) {
    return true
  }
  return false
}

function readErrorDetail(err: unknown): string | null {
  if (axios.isCancel?.(err)) return null
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (
    detail &&
    typeof detail === 'object' &&
    'detail' in detail &&
    typeof (detail as { detail?: unknown }).detail === 'string'
  ) {
    return (detail as { detail: string }).detail
  }
  return null
}

function clamp(n: number, min: number, max: number): number {
  if (!Number.isFinite(n)) return min
  if (n < min) return min
  if (n > max) return max
  return n
}

function parseInteger(value: string, fallback: number): number {
  const n = Number.parseInt(value, 10)
  return Number.isFinite(n) ? n : fallback
}

/* ─────────────────────────────────────── component ── */

export default function ClockInPolicyPage() {
  const [clockIn, setClockIn] = useState<ClockInPolicy>(DEFAULT_CLOCK_IN_POLICY)
  const [overtime, setOvertime] = useState<OvertimePolicy>(
    DEFAULT_OVERTIME_POLICY,
  )
  const [overtimeHandling, setOvertimeHandling] = useState<OvertimeHandling>(
    DEFAULT_OVERTIME_HANDLING,
  )

  const [loading, setLoading] = useState<boolean>(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState<boolean>(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedAt, setSavedAt] = useState<Date | null>(null)
  const [refreshKey, setRefreshKey] = useState<number>(0)

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      setLoading(true)
      setLoadError(null)
      try {
        const res = await apiClient.get<ClockInPolicyResponse>(
          '/api/v2/org/clock-in-policy',
          { signal: controller.signal },
        )
        if (controller.signal.aborted) return
        const data = res.data ?? {}
        setClockIn({
          ...DEFAULT_CLOCK_IN_POLICY,
          ...(data?.clock_in_policy ?? {}),
        })
        setOvertime({
          ...DEFAULT_OVERTIME_POLICY,
          ...(data?.overtime_policy ?? {}),
        })
        setOvertimeHandling(
          (data?.overtime_handling ?? DEFAULT_OVERTIME_HANDLING) as OvertimeHandling,
        )
      } catch (err) {
        if (controller.signal.aborted || isAbortError(err)) return
        const status = (err as { response?: { status?: number } })?.response
          ?.status
        if (status === 404) {
          setLoadError(
            'Clock-in policy settings are not yet available on this server.',
          )
        } else {
          setLoadError(
            "Couldn't load clock-in policy settings. Please refresh and try again.",
          )
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [refreshKey])

  const handleSave = useCallback(async () => {
    setSaveError(null)
    setSaving(true)
    const controller = new AbortController()
    try {
      const payload = {
        clock_in_policy: clockIn,
        overtime_policy: overtime,
        overtime_handling: overtimeHandling,
      }
      const res = await apiClient.put<ClockInPolicyResponse>(
        '/api/v2/org/clock-in-policy',
        payload,
        { signal: controller.signal },
      )
      if (controller.signal.aborted) return
      const data = res.data ?? {}
      setClockIn({
        ...DEFAULT_CLOCK_IN_POLICY,
        ...(data?.clock_in_policy ?? clockIn),
      })
      setOvertime({
        ...DEFAULT_OVERTIME_POLICY,
        ...(data?.overtime_policy ?? overtime),
      })
      setOvertimeHandling(
        (data?.overtime_handling ?? overtimeHandling) as OvertimeHandling,
      )
      setSavedAt(new Date())
    } catch (err) {
      if (controller.signal.aborted || isAbortError(err)) return
      const detail = readErrorDetail(err)
      const status = (err as { response?: { status?: number } })?.response
        ?.status
      if (status === 403) {
        setSaveError('Only org admins can change clock-in policy.')
      } else if (status === 404) {
        setSaveError(
          'Clock-in policy settings are not yet available on this server.',
        )
      } else if (detail) {
        setSaveError(detail)
      } else {
        setSaveError("Couldn't save changes. Please try again.")
      }
    } finally {
      if (!controller.signal.aborted) setSaving(false)
    }
  }, [clockIn, overtime, overtimeHandling])

  const overtimeWeeklyHours = useMemo(
    () => Math.round(((overtime?.weekly_threshold_minutes ?? 0) / 60) * 10) / 10,
    [overtime],
  )
  const overtimeDailyHours = useMemo(
    () => Math.round(((overtime?.daily_threshold_minutes ?? 0) / 60) * 10) / 10,
    [overtime],
  )

  if (loading) {
    return (
      <div className="p-6 text-sm text-muted">
        Loading clock-in policy…
      </div>
    )
  }

  if (loadError) {
    return (
      <div
        role="alert"
        className="space-y-3 p-6"
        data-testid="clock-in-policy-load-error"
      >
        <div className="rounded-ctl border border-danger bg-danger-soft px-4 py-3 text-sm text-danger">
          {loadError}
        </div>
        <button
          type="button"
          onClick={refresh}
          className="min-h-[44px] rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press"
        >
          Retry
        </button>
      </div>
    )
  }

  const cardCls =
    'rounded-card border border-border bg-card p-6 shadow-card'
  const labelCls =
    'block text-sm font-medium text-text'
  const inputCls =
    'mt-1 w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent'

  return (
    <div className="space-y-6 p-2 md:p-0" data-testid="clock-in-policy-page">
      <div>
        <h1 className="text-xl font-semibold text-text">
          Clock-in Policy
        </h1>
        <p className="text-sm text-muted">
          Configure how staff clock in, overtime thresholds, and shift-swap
          approval. Changes apply to new clock-in events immediately.
        </p>
      </div>

      {/* Clock-in policy card */}
      <section
        aria-labelledby="clock-in-policy-card-title"
        className={cardCls}
        data-testid="clock-in-policy-card"
      >
        <div className="mb-4">
          <h2
            id="clock-in-policy-card-title"
            className="text-base font-semibold text-text"
          >
            Clock-in
          </h2>
          <p className="text-xs text-muted">
            Channels, photo, geofence, late-edit, and rate-limit controls.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label htmlFor="default-channel" className={labelCls}>
              Default channel
            </label>
            <select
              id="default-channel"
              value={clockIn?.default_channel ?? 'kiosk_only'}
              onChange={(e) =>
                setClockIn((p) => ({
                  ...p,
                  default_channel: e.target.value as DefaultChannel,
                }))
              }
              className={inputCls}
              data-testid="default-channel-select"
            >
              <option value="kiosk_only">Kiosk only</option>
              <option value="kiosk_and_self_service">
                Kiosk + self-service
              </option>
            </select>
            <p className="mt-1 text-xs text-muted">
              Applied as the default for newly created staff. Existing staff
              keep their own setting.
            </p>
          </div>

          <div>
            <label htmlFor="branch-radius-metres" className={labelCls}>
              Geofence radius (metres) — default for new branches
            </label>
            <input
              id="branch-radius-metres"
              type="number"
              min={20}
              max={5000}
              step={10}
              value={clockIn?.branch_radius_metres ?? 200}
              onChange={(e) =>
                setClockIn((p) => ({
                  ...p,
                  branch_radius_metres: clamp(
                    parseInteger(e.target.value, p.branch_radius_metres ?? 200),
                    20,
                    5000,
                  ),
                }))
              }
              className={inputCls}
              data-testid="branch-radius-input"
            />
            <p
              className="mt-1 text-xs text-warn"
              data-testid="branch-radius-note"
            >
              The org-level radius is the default applied to new branches;
              existing branches keep their own value unless edited directly
              on the branch page.
            </p>
          </div>

          <div>
            <label htmlFor="kiosk-rate-limit" className={labelCls}>
              Kiosk lookup rate-limit (per minute, per employee code)
            </label>
            <input
              id="kiosk-rate-limit"
              type="number"
              min={1}
              max={100}
              value={clockIn?.kiosk_employee_id_rate_limit ?? 10}
              onChange={(e) =>
                setClockIn((p) => ({
                  ...p,
                  kiosk_employee_id_rate_limit: clamp(
                    parseInteger(
                      e.target.value,
                      p.kiosk_employee_id_rate_limit ?? 10,
                    ),
                    1,
                    100,
                  ),
                }))
              }
              className={inputCls}
              data-testid="kiosk-rate-limit-input"
            />
            <p className="mt-1 text-xs text-muted">
              Rejects more than this many lookups for the same employee code
              within a minute. Default 10.
            </p>
          </div>

          <ToggleRow
            id="self-service-require-photo"
            label="Self-service requires a photo"
            description="When enabled, the staff app/web flow refuses with a clear error when no photo is captured."
            checked={!!clockIn?.self_service_require_photo}
            onChange={(checked) =>
              setClockIn((p) => ({
                ...p,
                self_service_require_photo: checked,
              }))
            }
          />

          <ToggleRow
            id="self-service-require-geofence"
            label="Self-service requires geofence match"
            description="Refuses clock-in/out outside the configured branch radius."
            checked={!!clockIn?.self_service_require_geofence}
            onChange={(checked) =>
              setClockIn((p) => ({
                ...p,
                self_service_require_geofence: checked,
              }))
            }
          />

          <ToggleRow
            id="allow-late-clock-out-edits"
            label="Allow staff to edit late clock-outs"
            description="When off, staff cannot edit a clock-out after the entry is closed."
            checked={!!clockIn?.allow_late_clock_out_edits}
            onChange={(checked) =>
              setClockIn((p) => ({
                ...p,
                allow_late_clock_out_edits: checked,
              }))
            }
          />

          <ToggleRow
            id="shift-swap-requires-manager-approval"
            label="Shift-swap requires manager approval"
            description="When on, accepted swaps wait for a manager to approve before the schedule actually flips."
            checked={!!clockIn?.shift_swap_requires_manager_approval}
            onChange={(checked) =>
              setClockIn((p) => ({
                ...p,
                shift_swap_requires_manager_approval: checked,
              }))
            }
            testId="shift-swap-requires-manager-toggle"
          />
        </div>
      </section>

      {/* Overtime policy card (G1) */}
      <section
        aria-labelledby="overtime-policy-card-title"
        className={cardCls}
        data-testid="overtime-policy-card"
      >
        <div className="mb-4">
          <h2
            id="overtime-policy-card-title"
            className="text-base font-semibold text-text"
          >
            Overtime
          </h2>
          <p className="text-xs text-muted">
            Thresholds + handling. Both daily and weekly thresholds apply to
            split ordinary vs overtime minutes when approving a week.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label htmlFor="weekly-threshold-minutes" className={labelCls}>
              Weekly threshold (minutes)
            </label>
            <input
              id="weekly-threshold-minutes"
              type="number"
              min={0}
              max={10000}
              step={60}
              value={overtime?.weekly_threshold_minutes ?? 2400}
              onChange={(e) =>
                setOvertime((p) => ({
                  ...p,
                  weekly_threshold_minutes: clamp(
                    parseInteger(
                      e.target.value,
                      p.weekly_threshold_minutes ?? 2400,
                    ),
                    0,
                    10000,
                  ),
                }))
              }
              className={inputCls}
              data-testid="weekly-threshold-input"
            />
            <p className="mt-1 text-xs text-muted">
              ≈ {overtimeWeeklyHours}h / week. Default 2400 (40h).
            </p>
          </div>

          <div>
            <label htmlFor="daily-threshold-minutes" className={labelCls}>
              Daily threshold (minutes)
            </label>
            <input
              id="daily-threshold-minutes"
              type="number"
              min={0}
              max={1440}
              step={30}
              value={overtime?.daily_threshold_minutes ?? 480}
              onChange={(e) =>
                setOvertime((p) => ({
                  ...p,
                  daily_threshold_minutes: clamp(
                    parseInteger(
                      e.target.value,
                      p.daily_threshold_minutes ?? 480,
                    ),
                    0,
                    1440,
                  ),
                }))
              }
              className={inputCls}
              data-testid="daily-threshold-input"
            />
            <p className="mt-1 text-xs text-muted">
              ≈ {overtimeDailyHours}h / day. Default 480 (8h).
            </p>
          </div>

          <div>
            <label htmlFor="overtime-handling" className={labelCls}>
              Overtime handling
            </label>
            <select
              id="overtime-handling"
              value={overtimeHandling}
              onChange={(e) =>
                setOvertimeHandling(e.target.value as OvertimeHandling)
              }
              className={inputCls}
              data-testid="overtime-handling-select"
            >
              <option value="pay_cash">Pay cash</option>
              <option value="toil">Bank as TOIL leave</option>
              <option value="employee_chooses">Employee chooses each week</option>
            </select>
            <p className="mt-1 text-xs text-muted">
              Determines how overtime minutes are settled at week-approve
              time.
            </p>
          </div>

          <ToggleRow
            id="require-pre-approval"
            label="Require pre-approved overtime"
            description="When on, overtime minutes without an approved overtime request are flagged 'unapproved' on the timesheet."
            checked={!!overtime?.require_pre_approval}
            onChange={(checked) =>
              setOvertime((p) => ({ ...p, require_pre_approval: checked }))
            }
            testId="require-pre-approval-toggle"
          />
        </div>
      </section>

      {/* Save row */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving}
          className="min-h-[44px] rounded-ctl bg-accent px-5 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="clock-in-policy-save"
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
        {savedAt && !saveError && (
          <p className="text-sm text-ok">
            Saved at {savedAt.toLocaleTimeString()}.
          </p>
        )}
        {saveError && (
          <p
            role="alert"
            className="rounded-ctl bg-danger-soft px-3 py-2 text-sm font-medium text-danger"
            data-testid="clock-in-policy-save-error"
          >
            {saveError}
          </p>
        )}
      </div>
    </div>
  )
}

/* ──────────────────────── Toggle row ── */

interface ToggleRowProps {
  id: string
  label: string
  description?: string
  checked: boolean
  onChange: (checked: boolean) => void
  testId?: string
}

function ToggleRow({
  id,
  label,
  description,
  checked,
  onChange,
  testId,
}: ToggleRowProps) {
  return (
    <label
      htmlFor={id}
      className="flex min-h-[44px] cursor-pointer items-start gap-3 py-2"
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1 h-5 w-5 rounded border-border text-accent focus:ring-2 focus:ring-accent"
        data-testid={testId ?? `${id}-toggle`}
      />
      <span>
        <span className="block text-sm font-medium text-text">
          {label}
        </span>
        {description && (
          <span className="mt-0.5 block text-xs text-muted">
            {description}
          </span>
        )}
      </span>
    </label>
  )
}
