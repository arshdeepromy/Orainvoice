import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import type { TimesheetSettingsResponse } from './types'

interface BreakRule {
  after_work_minutes: number
  min_break_minutes: number
  break_type: string
  description: string
}

interface SettingsForm {
  clock_rounding_minutes: number
  clock_rounding_direction: string
  early_grace_minutes: number
  late_grace_minutes: number
  match_policy: string
  auto_approve_threshold_minutes: number
  require_approval_before_lock: boolean
  daily_overtime_threshold_minutes: number
  weekly_overtime_threshold_minutes: number
  overtime_rate_multiplier: number
  public_holiday_rate_multiplier: number
  break_rules: BreakRule[]
}

const DEFAULT_SETTINGS: SettingsForm = {
  clock_rounding_minutes: 1,
  clock_rounding_direction: 'nearest',
  early_grace_minutes: 0,
  late_grace_minutes: 0,
  match_policy: 'pay_actual',
  auto_approve_threshold_minutes: 0,
  require_approval_before_lock: true,
  daily_overtime_threshold_minutes: 480,
  weekly_overtime_threshold_minutes: 2400,
  overtime_rate_multiplier: 1.5,
  public_holiday_rate_multiplier: 1.5,
  break_rules: [],
}

export default function TimesheetSettings() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [data, setData] = useState<TimesheetSettingsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [form, setForm] = useState<SettingsForm>({ ...DEFAULT_SETTINGS })

  // Read-only mode for non-org_admin users
  const readOnly = !!user && user.role !== 'org_admin' && user.role !== 'global_admin'

  // Pay cycles state
  const [payCycles, setPayCycles] = useState<{ id: string; name: string; frequency: string; anchor_date: string; pay_date_offset_days: number; is_default: boolean }[]>([])
  const [showCycleModal, setShowCycleModal] = useState(false)
  const [cycleForm, setCycleForm] = useState({ name: '', frequency: 'fortnightly', anchor_date: '', pay_date_offset_days: 3, is_default: false })
  const [savingCycle, setSavingCycle] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    const fetchSettings = async () => {
      try {
        setLoading(true)
        const [settingsRes, cyclesRes] = await Promise.all([
          apiClient.get<TimesheetSettingsResponse>(
            '/api/v2/timesheet-settings/',
            { signal: controller.signal },
          ),
          apiClient.get<{ items: any[]; total: number }>(
            '/api/v2/pay-cycles/',
            { signal: controller.signal },
          ),
        ])
        setData(settingsRes.data)
        setPayCycles(cyclesRes.data?.items ?? [])
        if (settingsRes.data?.org_default) {
          const d = settingsRes.data.org_default
          setForm({
            clock_rounding_minutes: d.clock_rounding_minutes ?? 1,
            clock_rounding_direction: d.clock_rounding_direction ?? 'nearest',
            early_grace_minutes: d.early_grace_minutes ?? 0,
            late_grace_minutes: d.late_grace_minutes ?? 0,
            match_policy: d.match_policy ?? 'pay_actual',
            auto_approve_threshold_minutes: d.auto_approve_threshold_minutes ?? 0,
            require_approval_before_lock: d.require_approval_before_lock ?? true,
            daily_overtime_threshold_minutes: (d as any).daily_overtime_threshold_minutes ?? 480,
            weekly_overtime_threshold_minutes: (d as any).weekly_overtime_threshold_minutes ?? 2400,
            overtime_rate_multiplier: Number((d as any).overtime_rate_multiplier) || 1.5,
            public_holiday_rate_multiplier: Number((d as any).public_holiday_rate_multiplier) || 1.5,
            break_rules: ((d as any).break_rules ?? []) as BreakRule[],
          })
        }
        setError(null)
      } catch (err: unknown) {
        if (!controller.signal.aborted) setError('Failed to load settings')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchSettings()
    return () => controller.abort()
  }, [])

  const handleSave = async () => {
    try {
      setSaving(true)
      setSuccessMsg(null)
      await apiClient.put('/api/v2/timesheet-settings/', form)
      setSuccessMsg('Settings saved successfully')
      setTimeout(() => setSuccessMsg(null), 3000)
    } catch {
      setError('Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  // Break rules helpers
  const addBreakRule = () => {
    setForm({
      ...form,
      break_rules: [
        ...form.break_rules,
        { after_work_minutes: 240, min_break_minutes: 30, break_type: 'meal_unpaid', description: '' },
      ],
    })
  }

  const updateBreakRule = (index: number, field: keyof BreakRule, value: string | number) => {
    const updated = [...form.break_rules]
    updated[index] = { ...updated[index], [field]: value }
    setForm({ ...form, break_rules: updated })
  }

  const removeBreakRule = (index: number) => {
    setForm({ ...form, break_rules: form.break_rules.filter((_, i) => i !== index) })
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 animate-pulse rounded bg-muted/10" />
        <div className="animate-pulse space-y-4 rounded-card border border-border bg-card p-6 shadow-card">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-12 rounded bg-muted/10" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="page">
    <div className="space-y-6">
      {/* Header */}
      <div className="page-head">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/timesheets')}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border text-muted hover:bg-canvas hover:text-text"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div>
            <div className="eyebrow">Staff</div>
            <h1>Timesheet Settings</h1>
            <p className="sub">Configure clock rounding, matching policies, and overtime rules</p>
          </div>
        </div>
      </div>

      {/* Read-only banner */}
      {readOnly && (
        <div className="rounded-lg border border-warning/20 bg-warning/5 px-4 py-3">
          <p className="text-sm font-medium text-warning">You have read-only access to these settings</p>
        </div>
      )}

      {/* Success / Error messages */}
      {successMsg && (
        <div className="rounded-lg border border-success/20 bg-success/5 px-4 py-3">
          <p className="text-sm font-medium text-success">{successMsg}</p>
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-danger/20 bg-danger/5 px-4 py-3">
          <p className="text-sm font-medium text-danger">{error}</p>
        </div>
      )}

      {/* Clock & Matching Section */}
      <section className="rounded-card border border-border bg-card shadow-card">
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-base font-semibold text-text">Clock & Matching</h2>
          <p className="mt-0.5 text-xs text-muted">Controls how clock-in/out times are rounded and matched to roster shifts</p>
        </div>
        <div className="space-y-5 px-6 py-5">
          {/* Clock Rounding */}
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-text">Clock Rounding Interval</label>
              <select
                value={form.clock_rounding_minutes}
                onChange={(e) => setForm({ ...form, clock_rounding_minutes: Number(e.target.value) })}
                disabled={readOnly}
                className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                <option value={1}>No rounding (1 min)</option>
                <option value={5}>5 minutes</option>
                <option value={10}>10 minutes</option>
                <option value={15}>15 minutes</option>
                <option value={30}>30 minutes</option>
              </select>
              <p className="mt-1 text-xs text-muted">Clock-in/out times will be rounded to this interval</p>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-text">Rounding Direction</label>
              <div className="flex gap-3">
                {(['nearest', 'up', 'down'] as const).map((dir) => (
                  <label key={dir} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="rounding_direction"
                      value={dir}
                      checked={form.clock_rounding_direction === dir}
                      onChange={() => setForm({ ...form, clock_rounding_direction: dir })}
                      disabled={readOnly}
                      className="h-4 w-4 border-border text-accent focus:ring-accent disabled:opacity-60"
                    />
                    <span className="text-sm capitalize text-text">{dir}</span>
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-muted">
                {form.clock_rounding_direction === 'nearest' && 'Standard rounding (≥ half rounds up)'}
                {form.clock_rounding_direction === 'up' && 'Always round to next boundary (employer-favourable for clock-in)'}
                {form.clock_rounding_direction === 'down' && 'Always round to previous boundary (employee-favourable for clock-in)'}
              </p>
            </div>
          </div>

          {/* Grace Windows */}
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-text">Early Grace (minutes)</label>
              <input
                type="number"
                min={0}
                max={60}
                value={form.early_grace_minutes}
                onChange={(e) => setForm({ ...form, early_grace_minutes: Number(e.target.value) })}
                disabled={readOnly}
                className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
              />
              <p className="mt-1 text-xs text-muted">How early a clock-in can be and still match the scheduled shift</p>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-text">Late Grace (minutes)</label>
              <input
                type="number"
                min={0}
                max={60}
                value={form.late_grace_minutes}
                onChange={(e) => setForm({ ...form, late_grace_minutes: Number(e.target.value) })}
                disabled={readOnly}
                className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
              />
              <p className="mt-1 text-xs text-muted">How late a clock-in can be and still match the scheduled shift</p>
            </div>
          </div>

          {/* Match Policy */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-text">Match-to-Roster Policy</label>
            <select
              value={form.match_policy}
              onChange={(e) => setForm({ ...form, match_policy: e.target.value })}
              disabled={readOnly}
              className="h-10 w-full max-w-sm rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <option value="pay_actual">Pay Actual — pay exact clocked hours</option>
              <option value="round_to_roster">Round to Roster — pay scheduled hours if matched</option>
              <option value="actual_rounded">Actual Rounded — pay clocked hours with rounding applied</option>
            </select>
            <p className="mt-1 text-xs text-muted">Determines how matched clock entries are valued for payroll</p>
          </div>
        </div>
      </section>

      {/* Approval & Lock Section */}
      <section className="rounded-card border border-border bg-card shadow-card">
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-base font-semibold text-text">Approval & Locking</h2>
          <p className="mt-0.5 text-xs text-muted">Configure the approval workflow before timesheets can be locked for payroll</p>
        </div>
        <div className="space-y-5 px-6 py-5">
          {/* Require approval before lock */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-text">Require Approval Before Lock</p>
              <p className="text-xs text-muted">Timesheets must be approved before they can be locked into a pay run</p>
            </div>
            <button
              type="button"
              onClick={() => !readOnly && setForm({ ...form, require_approval_before_lock: !form.require_approval_before_lock })}
              disabled={readOnly}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${
                form.require_approval_before_lock ? 'bg-accent' : 'bg-muted/30'
              }`}
            >
              <span className={`inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                form.require_approval_before_lock ? 'translate-x-6' : 'translate-x-1'
              }`} />
            </button>
          </div>

          {/* Auto-approve threshold */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-text">Auto-Approve Variance Threshold (minutes)</label>
            <input
              type="number"
              min={0}
              max={120}
              value={form.auto_approve_threshold_minutes}
              onChange={(e) => setForm({ ...form, auto_approve_threshold_minutes: Number(e.target.value) })}
              disabled={readOnly}
              className="h-10 w-full max-w-[200px] rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
            />
            <p className="mt-1 text-xs text-muted">
              {form.auto_approve_threshold_minutes === 0
                ? 'Disabled — all timesheets require manual approval'
                : `Timesheets with ≤${form.auto_approve_threshold_minutes} min variance will be auto-approved during bulk approve`}
            </p>
          </div>
        </div>
      </section>

      {/* Overtime & Public Holidays Section */}
      <section className="rounded-card border border-border bg-card shadow-card">
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-base font-semibold text-text">Overtime & Public Holidays</h2>
          <p className="mt-0.5 text-xs text-muted">Configure overtime detection thresholds and holiday pay rates</p>
        </div>
        <div className="space-y-5 px-6 py-5">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-text">Daily Overtime Threshold</label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={1440}
                  value={form.daily_overtime_threshold_minutes}
                  onChange={(e) => setForm({ ...form, daily_overtime_threshold_minutes: Number(e.target.value) })}
                  disabled={readOnly}
                  className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
                />
                <span className="text-xs text-muted whitespace-nowrap">min ({(form.daily_overtime_threshold_minutes / 60).toFixed(1)}h)</span>
              </div>
              <p className="mt-1 text-xs text-muted">Minutes per day before overtime kicks in</p>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-text">Weekly Overtime Threshold</label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={10080}
                  value={form.weekly_overtime_threshold_minutes}
                  onChange={(e) => setForm({ ...form, weekly_overtime_threshold_minutes: Number(e.target.value) })}
                  disabled={readOnly}
                  className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
                />
                <span className="text-xs text-muted whitespace-nowrap">min ({(form.weekly_overtime_threshold_minutes / 60).toFixed(1)}h)</span>
              </div>
              <p className="mt-1 text-xs text-muted">Minutes per week before overtime kicks in</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-text">Overtime Rate Multiplier</label>
              <input
                type="number"
                min={1}
                max={5}
                step={0.25}
                value={form.overtime_rate_multiplier}
                onChange={(e) => setForm({ ...form, overtime_rate_multiplier: Number(e.target.value) })}
                disabled={readOnly}
                className="h-10 w-full max-w-[200px] rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
              />
              <p className="mt-1 text-xs text-muted">e.g. 1.5 = time and a half</p>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-text">Public Holiday Rate Multiplier</label>
              <input
                type="number"
                min={1}
                max={5}
                step={0.25}
                value={form.public_holiday_rate_multiplier}
                onChange={(e) => setForm({ ...form, public_holiday_rate_multiplier: Number(e.target.value) })}
                disabled={readOnly}
                className="h-10 w-full max-w-[200px] rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
              />
              <p className="mt-1 text-xs text-muted">e.g. 1.5 = time and a half on public holidays</p>
            </div>
          </div>

          {/* Break Rules */}
          <div className="border-t border-border pt-5">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="text-sm font-medium text-text">Break Rules</p>
                <p className="text-xs text-muted">Define mandatory break requirements based on hours worked</p>
              </div>
              {!readOnly && (
                <button
                  onClick={addBreakRule}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-xs font-medium text-text hover:bg-canvas"
                >
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                  </svg>
                  Add Rule
                </button>
              )}
            </div>

            {form.break_rules.length === 0 ? (
              <p className="text-xs text-muted italic">No break rules configured</p>
            ) : (
              <div className="space-y-3">
                {form.break_rules.map((rule, idx) => (
                  <div key={idx} className="flex flex-wrap items-center gap-3 rounded-lg border border-border p-3 bg-canvas">
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] text-muted">After (min)</label>
                      <input
                        type="number"
                        min={0}
                        value={rule.after_work_minutes}
                        onChange={(e) => updateBreakRule(idx, 'after_work_minutes', Number(e.target.value))}
                        disabled={readOnly}
                        className="h-9 w-20 rounded-lg border border-border bg-card px-2 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] text-muted">Break (min)</label>
                      <input
                        type="number"
                        min={0}
                        value={rule.min_break_minutes}
                        onChange={(e) => updateBreakRule(idx, 'min_break_minutes', Number(e.target.value))}
                        disabled={readOnly}
                        className="h-9 w-20 rounded-lg border border-border bg-card px-2 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] text-muted">Type</label>
                      <select
                        value={rule.break_type}
                        onChange={(e) => updateBreakRule(idx, 'break_type', e.target.value)}
                        disabled={readOnly}
                        className="h-9 rounded-lg border border-border bg-card px-2 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
                      >
                        <option value="rest_paid">Rest (paid)</option>
                        <option value="meal_unpaid">Meal (unpaid)</option>
                        <option value="any">Any</option>
                      </select>
                    </div>
                    <div className="flex flex-1 flex-col gap-1 min-w-[120px]">
                      <label className="text-[11px] text-muted">Description</label>
                      <input
                        type="text"
                        value={rule.description}
                        onChange={(e) => updateBreakRule(idx, 'description', e.target.value)}
                        placeholder="e.g. 30-min meal after 4h"
                        disabled={readOnly}
                        className="h-9 w-full rounded-lg border border-border bg-card px-2 text-sm text-text placeholder:text-muted/50 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60 disabled:cursor-not-allowed"
                      />
                    </div>
                    {!readOnly && (
                      <button
                        onClick={() => removeBreakRule(idx)}
                        className="mt-4 inline-flex h-8 w-8 items-center justify-center rounded-lg text-danger hover:bg-danger/10 transition-colors"
                        title="Remove rule"
                      >
                        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Pay Cycles Section */}
      <section className="rounded-card border border-border bg-card shadow-card">
        <div className="border-b border-border px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-text">Pay Cycles</h2>
              <p className="mt-0.5 text-xs text-muted">Define how often staff get paid. Pay periods auto-generate from cycle settings.</p>
            </div>
            {!readOnly && (
              <button
                onClick={() => setShowCycleModal(true)}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-xs font-medium text-text hover:bg-canvas"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                New Cycle
              </button>
            )}
          </div>
        </div>
        <div className="px-6 py-5">
          {payCycles.length > 0 ? (
            <div className="space-y-3">
              {payCycles.map((cycle) => (
                <div key={cycle.id} className="flex items-center justify-between rounded-lg border border-border p-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/10">
                      <svg className="h-4 w-4 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 12c0-1.232-.046-2.453-.138-3.662a4.006 4.006 0 00-3.7-3.7 48.678 48.678 0 00-7.324 0 4.006 4.006 0 00-3.7 3.7c-.017.22-.032.441-.046.662M19.5 12l3-3m-3 3l-3-3m-12 3c0 1.232.046 2.453.138 3.662a4.006 4.006 0 003.7 3.7 48.656 48.656 0 007.324 0 4.006 4.006 0 003.7-3.7c.017-.22.032-.441.046-.662M4.5 12l3 3m-3-3l-3 3" />
                      </svg>
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-text">{cycle.name}</p>
                        {cycle.is_default && (
                          <span className="rounded bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">Default</span>
                        )}
                      </div>
                      <p className="text-xs text-muted capitalize">
                        {cycle.frequency} • Starts: {cycle.anchor_date} • Pay {cycle.pay_date_offset_days} days after period end
                      </p>
                    </div>
                  </div>
                  {!readOnly && <button className="text-xs text-accent hover:underline">Edit</button>}
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center py-8">
              <div className="rounded-full bg-muted/10 p-3">
                <svg className="h-5 w-5 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 12c0-1.232-.046-2.453-.138-3.662a4.006 4.006 0 00-3.7-3.7 48.678 48.678 0 00-7.324 0 4.006 4.006 0 00-3.7 3.7c-.017.22-.032.441-.046.662M19.5 12l3-3m-3 3l-3-3m-12 3c0 1.232.046 2.453.138 3.662a4.006 4.006 0 003.7 3.7 48.656 48.656 0 007.324 0 4.006 4.006 0 003.7-3.7c.017-.22.032-.441.046-.662M4.5 12l3 3m-3-3l-3 3" />
                </svg>
              </div>
              <p className="mt-2 text-sm text-muted">No pay cycles configured</p>
              <p className="mt-0.5 text-xs text-muted">Create a cycle to define your pay frequency (weekly, fortnightly, or monthly)</p>
            </div>
          )}
        </div>
      </section>

      {/* Branch Overrides Section */}
      <section className="rounded-card border border-border bg-card shadow-card">
        <div className="border-b border-border px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-text">Branch Overrides</h2>
              <p className="mt-0.5 text-xs text-muted">Override org-wide settings for specific branches</p>
            </div>
            {!readOnly && (
              <button className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-xs font-medium text-text hover:bg-canvas">
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                Add Override
              </button>
            )}
          </div>
        </div>
        <div className="px-6 py-5">
          {(data?.branch_overrides ?? []).length > 0 ? (
            <div className="space-y-3">
              {(data?.branch_overrides ?? []).map((override) => (
                <div key={override.id} className="flex items-center justify-between rounded-lg border border-border p-4">
                  <div>
                    <p className="text-sm font-medium text-text">{override.branch_name ?? 'Branch'}</p>
                    <p className="text-xs text-muted">
                      Rounding: {override.clock_rounding_minutes}min ({override.clock_rounding_direction}) •
                      Policy: {override.match_policy?.replace(/_/g, ' ')} •
                      Grace: {override.early_grace_minutes}/{override.late_grace_minutes}min
                    </p>
                  </div>
                  {!readOnly && <button className="text-xs text-accent hover:underline">Edit</button>}
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center py-8">
              <div className="rounded-full bg-muted/10 p-3">
                <svg className="h-5 w-5 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 21h19.5m-18-18v18m10.5-18v18m6-13.5V21M6.75 6.75h.75m-.75 3h.75m-.75 3h.75m3-6h.75m-.75 3h.75m-.75 3h.75M6.75 21v-3.375c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21M3 3h12m-.75 4.5H21m-3.75 3.75h.008v.008h-.008v-.008zm0 3h.008v.008h-.008v-.008zm0 3h.008v.008h-.008v-.008z" />
                </svg>
              </div>
              <p className="mt-2 text-sm text-muted">No branch overrides configured</p>
              <p className="mt-0.5 text-xs text-muted">All branches use the organisation defaults above</p>
            </div>
          )}
        </div>
      </section>

      {/* Save Button — hidden for read-only */}
      {!readOnly && (
        <div className="sticky bottom-0 flex items-center justify-end gap-3 border-t border-border bg-canvas/80 px-4 py-4 backdrop-blur-sm -mx-4 sm:-mx-6">
          <button
            onClick={() => navigate('/timesheets')}
            className="inline-flex h-10 items-center rounded-lg border border-border px-4 text-sm font-medium text-text hover:bg-canvas"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex h-10 items-center rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      )}

      {/* Create Pay Cycle Modal */}
      {showCycleModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50">
          <div className="w-full max-w-md rounded-card bg-card p-6 shadow-pop">
            <h3 className="text-lg font-semibold text-text">New Pay Cycle</h3>
            <p className="mt-1 text-sm text-muted">Define a recurring pay schedule for your staff.</p>

            <div className="mt-4 space-y-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium text-text">Cycle Name</label>
                <input
                  type="text"
                  value={cycleForm.name}
                  onChange={(e) => setCycleForm({ ...cycleForm, name: e.target.value })}
                  placeholder="e.g. Fortnightly - All Staff"
                  className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text placeholder:text-muted/50 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-text">Frequency</label>
                <select
                  value={cycleForm.frequency}
                  onChange={(e) => setCycleForm({ ...cycleForm, frequency: e.target.value })}
                  className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                >
                  <option value="weekly">Weekly (7 days)</option>
                  <option value="fortnightly">Fortnightly (14 days)</option>
                  <option value="monthly">Monthly (calendar month)</option>
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-text">Anchor Date (first period starts here)</label>
                <input
                  type="date"
                  value={cycleForm.anchor_date}
                  onChange={(e) => setCycleForm({ ...cycleForm, anchor_date: e.target.value })}
                  className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                />
                <p className="mt-1 text-xs text-muted">All period boundaries are computed from this date</p>
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-text">Pay Date Offset (days after period end)</label>
                <input
                  type="number"
                  min={0}
                  max={14}
                  value={cycleForm.pay_date_offset_days}
                  onChange={(e) => setCycleForm({ ...cycleForm, pay_date_offset_days: Number(e.target.value) })}
                  className="h-10 w-full max-w-[120px] rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                />
                <p className="mt-1 text-xs text-muted">Staff get paid this many days after the period ends</p>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={cycleForm.is_default}
                  onChange={(e) => setCycleForm({ ...cycleForm, is_default: e.target.checked })}
                  className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
                />
                <span className="text-sm text-text">Set as default cycle for new staff</span>
              </label>
            </div>

            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                onClick={() => setShowCycleModal(false)}
                disabled={savingCycle}
                className="inline-flex h-10 items-center rounded-lg border border-border bg-card px-4 text-sm font-medium text-text hover:bg-canvas transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  if (!cycleForm.name || !cycleForm.anchor_date) return
                  setSavingCycle(true)
                  try {
                    const res = await apiClient.post('/api/v2/pay-cycles/', cycleForm)
                    setPayCycles([...payCycles, res.data as any])
                    setShowCycleModal(false)
                    setCycleForm({ name: '', frequency: 'fortnightly', anchor_date: '', pay_date_offset_days: 3, is_default: false })
                    setSuccessMsg('Pay cycle created')
                    setTimeout(() => setSuccessMsg(null), 3000)
                  } catch {
                    setError('Failed to create pay cycle')
                  } finally {
                    setSavingCycle(false)
                  }
                }}
                disabled={savingCycle || !cycleForm.name || !cycleForm.anchor_date}
                className="inline-flex h-10 items-center rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent/90 transition-colors disabled:opacity-50"
              >
                {savingCycle ? 'Creating...' : 'Create Cycle'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </div>
  )
}
