import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import {
  Badge,
  Button,
  Spinner,
  AlertBanner,
  Input,
  ConfirmDialog,
  ToastContainer,
  useToast,
} from '@/components/ui'
import {
  getOrgTaxSettings,
  updateOrgTaxSettings,
  resetOrgTaxField,
  resetAllOrgTaxFields,
  parseFieldErrors,
  SECONDARY_TAX_CODES,
  type OrgTaxSettingsView,
  type OrgOverridesUpdate,
  type SecondaryRates,
  type SecondaryTaxCode,
  type PAYEBracket,
  type IETCParams,
  type FieldError,
} from '@/api/payrollTax'

/**
 * Org-tier payroll tax settings (feature: payroll-tax-settings, design §8).
 *
 * Reached from the Settings control on the Payroll page (task 12.1, route
 * `/payroll/tax-settings`). Mirrors the org-settings pattern of
 * `staff-timesheets/TimesheetSettings.tsx` and reuses the field-rendering
 * conventions of the Global Admin editor `admin/PayrollTaxDefault.tsx`.
 *
 * Fetches `GET /api/v2/payroll-tax-settings` and, for each Tax_Field, shows the
 * effective (resolved) value plus an **Inherited** / **Override** badge sourced
 * from `field_status`. Editing one or more fields and saving issues a sparse
 * `PUT` (only the changed fields). A per-field "Reset to default" issues the
 * field `DELETE`; "Reset all" issues the collection `DELETE`. After any reset
 * the affected field re-renders as Inherited showing the platform value (the
 * returned view drives the re-render). 422 responses render per-field inline
 * errors via `parseFieldErrors`.
 *
 * `tax_year_label` is platform-only: it always renders as **Inherited** with no
 * override / edit / reset control.
 *
 * **Validates: Requirements 4.3, 9.1, 9.2, 9.4**
 */

/* ── Form model ──────────────────────────────────────────────────────────
 * Numeric fields are held as strings so the inputs stay controlled and the
 * user can clear/retype freely; they are parsed to numbers on save. The last
 * bracket row is always the open-ended top band (`isTop`, no upper-limit input).
 */

interface BracketRow {
  upper_limit: string
  rate: string
  isTop: boolean
}

interface TaxForm {
  paye_brackets: BracketRow[]
  secondary_rates: Record<SecondaryTaxCode, string>
  acc_levy_rate: string
  acc_max_liable_earnings: string
  student_loan_rate: string
  student_loan_threshold: string
  ietc_amount: string
  ietc_lower: string
  ietc_abatement_start: string
  ietc_abatement_rate: string
  ietc_upper: string
  default_kiwisaver_employee_rate: string
  default_kiwisaver_employer_rate: string
}

/** The top-level Tax_Field keys an org can override (tax_year_label excluded). */
type OverrideKey =
  | 'paye_brackets'
  | 'secondary_rates'
  | 'acc_levy_rate'
  | 'acc_max_liable_earnings'
  | 'student_loan_rate'
  | 'student_loan_threshold'
  | 'ietc'
  | 'default_kiwisaver_employee_rate'
  | 'default_kiwisaver_employer_rate'

/** Stringify a number for display in a controlled input. */
function n(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return ''
  return String(v)
}

/** Parse a form string back to a number (empty/NaN → 0 so the field is sent). */
function toNum(v: string): number {
  const parsed = parseFloat(v)
  return Number.isFinite(parsed) ? parsed : 0
}

/**
 * Rates are stored as fractions (0.105) but shown to users as percentages
 * (10.5), matching how IRD publishes them. These two helpers convert at the
 * form boundary only — the stored value and the PAYE engine still use the
 * fraction, so nothing downstream changes.
 */

/** Stored fraction (0.105) → percent display string ("10.5"). */
function fracToPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return ''
  // toFixed avoids binary-float drift (0.016 * 100 = 1.6000000000000001).
  return String(Number((v * 100).toFixed(6)))
}

/** Percent form string ("10.5") → stored fraction (0.105). */
function pctToFrac(v: string): number {
  const parsed = parseFloat(v)
  if (!Number.isFinite(parsed)) return 0
  return Number((parsed / 100).toFixed(8))
}

function viewToForm(view: OrgTaxSettingsView): TaxForm {
  const brackets = view.paye_brackets ?? []
  const rows: BracketRow[] =
    brackets.length > 0
      ? brackets.map((b) => ({
          upper_limit: b.upper_limit === null ? '' : n(b.upper_limit),
          rate: fracToPct(b.rate),
          isTop: b.upper_limit === null,
        }))
      : [{ upper_limit: '', rate: '', isTop: true }]

  // Guarantee the last row is flagged as the open-ended top band.
  if (rows.length > 0 && !rows[rows.length - 1].isTop) {
    rows[rows.length - 1] = { ...rows[rows.length - 1], upper_limit: '', isTop: true }
  }

  const secondary = view.secondary_rates ?? ({} as SecondaryRates)

  return {
    paye_brackets: rows,
    secondary_rates: SECONDARY_TAX_CODES.reduce(
      (acc, code) => {
        acc[code] = fracToPct(secondary[code])
        return acc
      },
      {} as Record<SecondaryTaxCode, string>,
    ),
    acc_levy_rate: fracToPct(view.acc_levy_rate),
    acc_max_liable_earnings: n(view.acc_max_liable_earnings),
    student_loan_rate: fracToPct(view.student_loan_rate),
    student_loan_threshold: n(view.student_loan_threshold),
    ietc_amount: n(view.ietc?.amount),
    ietc_lower: n(view.ietc?.lower),
    ietc_abatement_start: n(view.ietc?.abatement_start),
    ietc_abatement_rate: fracToPct(view.ietc?.abatement_rate),
    ietc_upper: n(view.ietc?.upper),
    default_kiwisaver_employee_rate: n(view.default_kiwisaver_employee_rate),
    default_kiwisaver_employer_rate: n(view.default_kiwisaver_employer_rate),
  }
}

/* ── Per-group payload builders ─────────────────────────────────────────── */

function bracketsValue(form: TaxForm): PAYEBracket[] {
  return form.paye_brackets.map((r) => ({
    upper_limit: r.isTop ? null : toNum(r.upper_limit),
    rate: pctToFrac(r.rate),
  }))
}

function secondaryValue(form: TaxForm): SecondaryRates {
  return SECONDARY_TAX_CODES.reduce((acc, code) => {
    acc[code] = pctToFrac(form.secondary_rates[code])
    return acc
  }, {} as SecondaryRates)
}

function ietcValue(form: TaxForm): IETCParams {
  return {
    amount: toNum(form.ietc_amount),
    lower: toNum(form.ietc_lower),
    abatement_start: toNum(form.ietc_abatement_start),
    abatement_rate: pctToFrac(form.ietc_abatement_rate),
    upper: toNum(form.ietc_upper),
  }
}

/** The resolved value for a single override key, used for dirty comparison. */
function valueForKey(form: TaxForm, key: OverrideKey): OrgOverridesUpdate[OverrideKey] {
  switch (key) {
    case 'paye_brackets':
      return bracketsValue(form)
    case 'secondary_rates':
      return secondaryValue(form)
    case 'ietc':
      return ietcValue(form)
    case 'acc_levy_rate':
      return pctToFrac(form.acc_levy_rate)
    case 'acc_max_liable_earnings':
      return toNum(form.acc_max_liable_earnings)
    case 'student_loan_rate':
      return pctToFrac(form.student_loan_rate)
    case 'student_loan_threshold':
      return toNum(form.student_loan_threshold)
    case 'default_kiwisaver_employee_rate':
      return toNum(form.default_kiwisaver_employee_rate)
    case 'default_kiwisaver_employer_rate':
      return toNum(form.default_kiwisaver_employer_rate)
  }
}

const OVERRIDE_KEYS: OverrideKey[] = [
  'paye_brackets',
  'secondary_rates',
  'acc_levy_rate',
  'acc_max_liable_earnings',
  'student_loan_rate',
  'student_loan_threshold',
  'ietc',
  'default_kiwisaver_employee_rate',
  'default_kiwisaver_employer_rate',
]

/**
 * Build the sparse PUT payload: include only the top-level Tax_Fields whose
 * current form value differs from the last-loaded baseline. Unchanged fields
 * are omitted so they keep their current inherited/override state.
 */
function buildSparsePayload(form: TaxForm, baseline: TaxForm): OrgOverridesUpdate {
  const payload: OrgOverridesUpdate = {}
  for (const key of OVERRIDE_KEYS) {
    const current = valueForKey(form, key)
    const prior = valueForKey(baseline, key)
    if (JSON.stringify(current) !== JSON.stringify(prior)) {
      // Each branch assigns the correctly-typed value for `key`.
      ;(payload as Record<string, unknown>)[key] = current
    }
  }
  return payload
}

/* ── Per-field error helpers ────────────────────────────────────────────── */

function errorFor(errors: FieldError[], field: string): string | undefined {
  return errors.find((e) => e.field === field)?.message
}

function errorsByPrefix(errors: FieldError[], prefix: string): FieldError[] {
  return errors.filter(
    (e) =>
      e.field === prefix ||
      e.field.startsWith(`${prefix}.`) ||
      e.field.startsWith(`${prefix}[`),
  )
}

/* ── Inherited / Override badge ─────────────────────────────────────────── */

function StatusBadge({ override }: { override: boolean }) {
  return override ? (
    <Badge variant="info">Override</Badge>
  ) : (
    <Badge variant="neutral">Inherited</Badge>
  )
}

/* ── Section wrapper with badge + reset control ─────────────────────────── */

function Section({
  title,
  description,
  override,
  onReset,
  resetting,
  readOnly,
  showReset = true,
  children,
}: {
  title: string
  description?: string
  override: boolean
  onReset?: () => void
  resetting?: boolean
  readOnly?: boolean
  showReset?: boolean
  children: React.ReactNode
}) {
  return (
    <section className="rounded-card border border-border bg-card shadow-card">
      <div className="border-b border-border px-6 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-text">{title}</h2>
              <StatusBadge override={override} />
            </div>
            {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
          </div>
          {showReset && !readOnly && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={!override || resetting}
              loading={resetting}
              onClick={onReset}
              title={
                override
                  ? 'Remove this override so the field inherits the platform default'
                  : 'Already inheriting the platform default'
              }
            >
              Reset to default
            </Button>
          )}
        </div>
      </div>
      <div className="space-y-5 px-6 py-5">{children}</div>
    </section>
  )
}

/* ── Component ──────────────────────────────────────────────────────────── */

export default function PayrollTaxSettings() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { toasts, addToast, dismissToast } = useToast()

  const [view, setView] = useState<OrgTaxSettingsView | null>(null)
  const [form, setForm] = useState<TaxForm | null>(null)
  const [baseline, setBaseline] = useState<TaxForm | null>(null)
  const [taxYearLabel, setTaxYearLabel] = useState('')

  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [resettingKey, setResettingKey] = useState<OverrideKey | null>(null)
  const [resettingAll, setResettingAll] = useState(false)
  const [confirmResetAll, setConfirmResetAll] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([])

  // Only org admins may edit; mirror the read-only treatment of TimesheetSettings.
  const readOnly = !!user && user.role !== 'org_admin'

  const applyView = useCallback((v: OrgTaxSettingsView) => {
    const f = viewToForm(v)
    setView(v)
    setForm(f)
    setBaseline(f)
    setTaxYearLabel(v.tax_year_label ?? '')
  }, [])

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true)
      setLoadError(false)
      try {
        const v = await getOrgTaxSettings(signal)
        applyView(v)
      } catch (err) {
        if (!signal?.aborted) setLoadError(true)
      } finally {
        if (!signal?.aborted) setLoading(false)
      }
    },
    [applyView],
  )

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

  /** Whether a top-level field is an org override (else inherited). */
  const isOverride = useCallback(
    (key: OverrideKey): boolean => !!view?.field_status?.[key]?.override,
    [view],
  )

  /* ── field update helpers ── */

  const setField = <K extends keyof TaxForm>(key: K, value: TaxForm[K]) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const setSecondary = (code: SecondaryTaxCode, value: string) => {
    setForm((prev) =>
      prev
        ? { ...prev, secondary_rates: { ...prev.secondary_rates, [code]: value } }
        : prev,
    )
  }

  const updateBracket = (index: number, patch: Partial<BracketRow>) => {
    setForm((prev) => {
      if (!prev) return prev
      const next = prev.paye_brackets.map((row, i) =>
        i === index ? { ...row, ...patch } : row,
      )
      return { ...prev, paye_brackets: next }
    })
  }

  const addBracketRow = () => {
    setForm((prev) => {
      if (!prev) return prev
      const rows = [...prev.paye_brackets]
      const insertAt = Math.max(0, rows.length - 1)
      rows.splice(insertAt, 0, { upper_limit: '', rate: '', isTop: false })
      return { ...prev, paye_brackets: rows }
    })
  }

  const removeBracketRow = (index: number) => {
    setForm((prev) => {
      if (!prev) return prev
      if (prev.paye_brackets[index]?.isTop) return prev
      const rows = prev.paye_brackets.filter((_, i) => i !== index)
      return { ...prev, paye_brackets: rows }
    })
  }

  /* ── dirty tracking ── */

  const dirtyPayload = useMemo<OrgOverridesUpdate>(() => {
    if (!form || !baseline) return {}
    return buildSparsePayload(form, baseline)
  }, [form, baseline])

  const isDirty = Object.keys(dirtyPayload).length > 0

  /* ── save / reset handlers ── */

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form || !baseline || readOnly) return
    const payload = buildSparsePayload(form, baseline)
    if (Object.keys(payload).length === 0) {
      addToast('info', 'No changes to save')
      return
    }
    setSaving(true)
    setFieldErrors([])
    try {
      const v = await updateOrgTaxSettings(payload)
      applyView(v)
      addToast('success', 'Tax settings saved')
    } catch (err: unknown) {
      const response =
        typeof err === 'object' && err !== null && 'response' in err
          ? (err as { response?: { status?: number; data?: { detail?: unknown } } }).response
          : undefined
      if (response?.status === 422) {
        setFieldErrors(parseFieldErrors(response?.data?.detail))
        addToast('error', 'Please fix the highlighted fields')
      } else {
        addToast('error', 'Failed to save tax settings')
      }
    } finally {
      setSaving(false)
    }
  }

  const handleResetField = async (key: OverrideKey) => {
    if (readOnly) return
    setResettingKey(key)
    setFieldErrors([])
    try {
      const v = await resetOrgTaxField(key)
      applyView(v)
      addToast('success', 'Field reset to platform default')
    } catch {
      addToast('error', 'Failed to reset field')
    } finally {
      setResettingKey(null)
    }
  }

  const handleResetAll = async () => {
    if (readOnly) return
    setResettingAll(true)
    setFieldErrors([])
    try {
      const v = await resetAllOrgTaxFields()
      applyView(v)
      addToast('success', 'All fields reset to platform defaults')
    } catch {
      addToast('error', 'Failed to reset all fields')
    } finally {
      setResettingAll(false)
      setConfirmResetAll(false)
    }
  }

  const hasAnyOverride = useMemo(
    () => OVERRIDE_KEYS.some((k) => !!view?.field_status?.[k]?.override),
    [view],
  )

  /* ── render ── */

  if (loading) {
    return (
      <div className="page">
        <div className="flex items-center justify-center py-16">
          <Spinner label="Loading tax settings" />
        </div>
      </div>
    )
  }

  if (loadError || !form || !view) {
    return (
      <div className="page">
        <div className="space-y-6">
          <AlertBanner variant="error" title="Failed to load">
            Could not load your organisation's tax settings. Please try again.
          </AlertBanner>
          <Button variant="ghost" onClick={() => load()}>
            Retry
          </Button>
        </div>
      </div>
    )
  }

  const bracketErrors = errorsByPrefix(fieldErrors, 'paye_brackets')
  const secondaryErrors = errorsByPrefix(fieldErrors, 'secondary_rates')
  const ietcErrors = errorsByPrefix(fieldErrors, 'ietc')

  return (
    <div className="page">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="space-y-6">
        {/* Header */}
        <div className="page-head">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/payroll/run')}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border text-muted hover:bg-canvas hover:text-text"
              aria-label="Back to payroll"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <div>
              <div className="eyebrow">Payroll</div>
              <h1>Tax Settings</h1>
              <p className="sub">
                NZ payroll tax values for your organisation. Each field either inherits
                the platform default or uses your override. Rates are entered as
                percentages (e.g. 10.5 for 10.5%); dollar thresholds are entered in dollars.
              </p>
            </div>
          </div>
          {!readOnly && (
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                disabled={!hasAnyOverride || resettingAll}
                onClick={() => setConfirmResetAll(true)}
              >
                Reset all
              </Button>
            </div>
          )}
        </div>

        {/* Read-only banner */}
        {readOnly && (
          <div className="rounded-lg border border-warning/20 bg-warning/5 px-4 py-3">
            <p className="text-sm font-medium text-warning">
              You have read-only access to these settings
            </p>
          </div>
        )}

        {fieldErrors.length > 0 && (
          <AlertBanner variant="error" title="Validation failed">
            The submitted configuration was rejected. Fix the field-level errors below
            and save again.
          </AlertBanner>
        )}

        <form onSubmit={handleSave} className="space-y-6">
          {/* ── Tax year (platform-only, always Inherited) ── */}
          <Section
            title="Tax year"
            description="Display label only — set on the platform default and not overridable."
            override={false}
            showReset={false}
            readOnly={readOnly}
          >
            <div>
              <label className="mb-1.5 block text-sm font-medium text-text">Tax year label</label>
              <span className="inline-flex h-10 items-center rounded-lg border border-dashed border-border bg-canvas px-3 text-sm text-muted">
                {taxYearLabel || '—'}
              </span>
            </div>
          </Section>

          {/* ── PAYE brackets ── */}
          <Section
            title="PAYE income-tax brackets"
            description="Progressive bands. Each band's rate (%) is the marginal tax on income up to that limit; the last row is the open-ended top band (no upper limit)."
            override={isOverride('paye_brackets')}
            onReset={() => handleResetField('paye_brackets')}
            resetting={resettingKey === 'paye_brackets'}
            readOnly={readOnly}
          >
            <div className="space-y-2">
              <div className="grid grid-cols-[1fr_1fr_auto] gap-3 items-end text-[12.5px] font-medium text-muted">
                <span>Upper limit (annual $)</span>
                <span>Rate (%)</span>
                <span className="w-[34px]" aria-hidden="true" />
              </div>
              {form.paye_brackets.map((row, index) => (
                <div key={index} className="grid grid-cols-[1fr_1fr_auto] gap-3 items-end">
                  {row.isTop ? (
                    <span className="flex h-[42px] items-center rounded-ctl border border-dashed border-border bg-canvas px-[13px] text-[13px] text-muted">
                      No upper limit (top band)
                    </span>
                  ) : (
                    <Input
                      label=""
                      type="number"
                      step="1"
                      value={row.upper_limit}
                      onChange={(e) => updateBracket(index, { upper_limit: e.target.value })}
                      placeholder="15600"
                      disabled={readOnly}
                    />
                  )}
                  <Input
                    label=""
                    type="number"
                    step="0.01"
                    value={row.rate}
                    onChange={(e) => updateBracket(index, { rate: e.target.value })}
                    placeholder="10.5"
                    disabled={readOnly}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    iconOnly
                    aria-label={`Remove bracket row ${index + 1}`}
                    disabled={row.isTop || readOnly}
                    onClick={() => removeBracketRow(index)}
                  >
                    ✕
                  </Button>
                </div>
              ))}
            </div>

            {!readOnly && (
              <Button type="button" variant="ghost" size="sm" onClick={addBracketRow}>
                + Add bracket
              </Button>
            )}

            {bracketErrors.length > 0 && (
              <ul className="space-y-1" role="alert">
                {bracketErrors.map((e, i) => (
                  <li key={`${e.field}-${i}`} className="text-[12.5px] text-danger">
                    {e.field}: {e.message}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {/* ── Secondary tax rates ── */}
          <Section
            title="Secondary tax rates"
            description="Flat tax rate (%) for each secondary tax code — e.g. type 17.5 for 17.5%."
            override={isOverride('secondary_rates')}
            onReset={() => handleResetField('secondary_rates')}
            resetting={resettingKey === 'secondary_rates'}
            readOnly={readOnly}
          >
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              {SECONDARY_TAX_CODES.map((code) => (
                <Input
                  key={code}
                  label={code}
                  type="number"
                  step="0.01"
                  value={form.secondary_rates[code] ?? ''}
                  onChange={(e) => setSecondary(code, e.target.value)}
                  placeholder="17.5"
                  disabled={readOnly}
                  error={errorFor(fieldErrors, `secondary_rates.${code}`)}
                />
              ))}
            </div>
            {secondaryErrors.length > 0 && (
              <ul className="space-y-1" role="alert">
                {secondaryErrors
                  .filter(
                    (e) => !SECONDARY_TAX_CODES.some((c) => e.field === `secondary_rates.${c}`),
                  )
                  .map((e, i) => (
                    <li key={`${e.field}-${i}`} className="text-[12.5px] text-danger">
                      {e.field}: {e.message}
                    </li>
                  ))}
              </ul>
            )}
          </Section>

          {/* ── ACC levy rate ── */}
          <Section
            title="ACC levy rate"
            description="ACC earner levy rate (%) applied to liable earnings — e.g. 1.6 for 1.6%."
            override={isOverride('acc_levy_rate')}
            onReset={() => handleResetField('acc_levy_rate')}
            resetting={resettingKey === 'acc_levy_rate'}
            readOnly={readOnly}
          >
            <div className="max-w-xs">
              <Input
                label="ACC levy rate (%)"
                type="number"
                step="0.01"
                value={form.acc_levy_rate}
                onChange={(e) => setField('acc_levy_rate', e.target.value)}
                placeholder="1.6"
                disabled={readOnly}
                error={errorFor(fieldErrors, 'acc_levy_rate')}
              />
            </div>
          </Section>

          {/* ── ACC max liable earnings ── */}
          <Section
            title="ACC max liable earnings"
            description="The annual ACC earnings cap."
            override={isOverride('acc_max_liable_earnings')}
            onReset={() => handleResetField('acc_max_liable_earnings')}
            resetting={resettingKey === 'acc_max_liable_earnings'}
            readOnly={readOnly}
          >
            <div className="max-w-xs">
              <Input
                label="ACC max liable earnings ($)"
                type="number"
                step="1"
                value={form.acc_max_liable_earnings}
                onChange={(e) => setField('acc_max_liable_earnings', e.target.value)}
                placeholder="142283"
                disabled={readOnly}
                error={errorFor(fieldErrors, 'acc_max_liable_earnings')}
              />
            </div>
          </Section>

          {/* ── Student loan rate ── */}
          <Section
            title="Student loan rate"
            description="Repayment rate (%) applied above the threshold — e.g. 12 for 12%."
            override={isOverride('student_loan_rate')}
            onReset={() => handleResetField('student_loan_rate')}
            resetting={resettingKey === 'student_loan_rate'}
            readOnly={readOnly}
          >
            <div className="max-w-xs">
              <Input
                label="Student loan rate (%)"
                type="number"
                step="0.01"
                value={form.student_loan_rate}
                onChange={(e) => setField('student_loan_rate', e.target.value)}
                placeholder="12"
                disabled={readOnly}
                error={errorFor(fieldErrors, 'student_loan_rate')}
              />
            </div>
          </Section>

          {/* ── Student loan threshold ── */}
          <Section
            title="Student loan threshold"
            description="Annual income threshold above which repayments apply."
            override={isOverride('student_loan_threshold')}
            onReset={() => handleResetField('student_loan_threshold')}
            resetting={resettingKey === 'student_loan_threshold'}
            readOnly={readOnly}
          >
            <div className="max-w-xs">
              <Input
                label="Student loan threshold ($)"
                type="number"
                step="1"
                value={form.student_loan_threshold}
                onChange={(e) => setField('student_loan_threshold', e.target.value)}
                placeholder="24128"
                disabled={readOnly}
                error={errorFor(fieldErrors, 'student_loan_threshold')}
              />
            </div>
          </Section>

          {/* ── IETC ── */}
          <Section
            title="Independent Earner Tax Credit (IETC)"
            description="Parameters for the ME tax code."
            override={isOverride('ietc')}
            onReset={() => handleResetField('ietc')}
            resetting={resettingKey === 'ietc'}
            readOnly={readOnly}
          >
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Input
                label="Amount ($)"
                type="number"
                step="1"
                value={form.ietc_amount}
                onChange={(e) => setField('ietc_amount', e.target.value)}
                placeholder="520"
                disabled={readOnly}
                error={errorFor(fieldErrors, 'ietc.amount')}
              />
              <Input
                label="Lower bound ($)"
                type="number"
                step="1"
                value={form.ietc_lower}
                onChange={(e) => setField('ietc_lower', e.target.value)}
                placeholder="24000"
                disabled={readOnly}
                error={errorFor(fieldErrors, 'ietc.lower')}
              />
              <Input
                label="Abatement start ($)"
                type="number"
                step="1"
                value={form.ietc_abatement_start}
                onChange={(e) => setField('ietc_abatement_start', e.target.value)}
                placeholder="44000"
                disabled={readOnly}
                error={errorFor(fieldErrors, 'ietc.abatement_start')}
              />
              <Input
                label="Abatement rate (%)"
                type="number"
                step="0.01"
                value={form.ietc_abatement_rate}
                onChange={(e) => setField('ietc_abatement_rate', e.target.value)}
                placeholder="13"
                disabled={readOnly}
                error={errorFor(fieldErrors, 'ietc.abatement_rate')}
              />
              <Input
                label="Upper bound ($)"
                type="number"
                step="1"
                value={form.ietc_upper}
                onChange={(e) => setField('ietc_upper', e.target.value)}
                placeholder="48000"
                disabled={readOnly}
                error={errorFor(fieldErrors, 'ietc.upper')}
              />
            </div>
            {ietcErrors
              .filter(
                (e) =>
                  !['amount', 'lower', 'abatement_start', 'abatement_rate', 'upper'].some(
                    (k) => e.field === `ietc.${k}`,
                  ),
              )
              .map((e, i) => (
                <p key={`${e.field}-${i}`} className="text-[12.5px] text-danger" role="alert">
                  {e.field}: {e.message}
                </p>
              ))}
          </Section>

          {/* ── KiwiSaver employee default ── */}
          <Section
            title="KiwiSaver employee default rate"
            description="Applied when a staff profile does not specify a rate (percent, 0–100)."
            override={isOverride('default_kiwisaver_employee_rate')}
            onReset={() => handleResetField('default_kiwisaver_employee_rate')}
            resetting={resettingKey === 'default_kiwisaver_employee_rate'}
            readOnly={readOnly}
          >
            <div className="max-w-xs">
              <Input
                label="Employee default rate (%)"
                type="number"
                step="0.01"
                value={form.default_kiwisaver_employee_rate}
                onChange={(e) => setField('default_kiwisaver_employee_rate', e.target.value)}
                placeholder="3.00"
                disabled={readOnly}
                error={errorFor(fieldErrors, 'default_kiwisaver_employee_rate')}
              />
            </div>
          </Section>

          {/* ── KiwiSaver employer default ── */}
          <Section
            title="KiwiSaver employer default rate"
            description="Applied when a staff profile does not specify a rate (percent, 0–100)."
            override={isOverride('default_kiwisaver_employer_rate')}
            onReset={() => handleResetField('default_kiwisaver_employer_rate')}
            resetting={resettingKey === 'default_kiwisaver_employer_rate'}
            readOnly={readOnly}
          >
            <div className="max-w-xs">
              <Input
                label="Employer default rate (%)"
                type="number"
                step="0.01"
                value={form.default_kiwisaver_employer_rate}
                onChange={(e) => setField('default_kiwisaver_employer_rate', e.target.value)}
                placeholder="3.00"
                disabled={readOnly}
                error={errorFor(fieldErrors, 'default_kiwisaver_employer_rate')}
              />
            </div>
          </Section>

          {!readOnly && (
            <div className="flex gap-3 pt-1">
              <Button type="submit" loading={saving} disabled={!isDirty || saving}>
                Save overrides
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={!isDirty || saving}
                onClick={() => baseline && setForm(baseline)}
              >
                Discard changes
              </Button>
            </div>
          )}
        </form>
      </div>

      <ConfirmDialog
        open={confirmResetAll}
        title="Reset all tax settings?"
        message="This removes every override for your organisation so all fields inherit the platform default. This cannot be undone."
        confirmLabel="Reset all"
        variant="danger"
        loading={resettingAll}
        onConfirm={handleResetAll}
        onCancel={() => setConfirmResetAll(false)}
      />
    </div>
  )
}
