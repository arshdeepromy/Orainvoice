import { useState, useEffect, useCallback } from 'react'
import Button from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import {
  getPlatformTaxDefault,
  updatePlatformTaxDefault,
  parseFieldErrors,
  SECONDARY_TAX_CODES,
  type PlatformTaxDefaultView,
  type PlatformTaxDefaultUpdate,
  type SecondaryRates,
  type SecondaryTaxCode,
  type FieldError,
} from '@/api/payrollTax'

/**
 * Global Admin editor for the platform-wide payroll tax default
 * (feature: payroll-tax-settings, design §7).
 *
 * Fetches `GET /api/v2/admin/platform-tax-default` and presents editable
 * controls for every Tax_Field: the PAYE bracket table (add/remove rows; the
 * last row is the open-ended top band with no upper-limit input), the five
 * secondary tax rates, the ACC levy rate + cap, the student-loan rate +
 * threshold, the five IETC parameters, the two KiwiSaver defaults, and the
 * tax-year label. Save issues `PUT`; a 422 renders per-field inline errors
 * keyed by the `field` name returned by the backend.
 *
 * **Validates: Requirements 2.1, 2.2**
 */

/* ── Form model ──────────────────────────────────────────────────────────
 * Numeric fields are held as strings so the inputs stay controlled and the
 * user can clear/retype freely; they are parsed to numbers on save. The last
 * bracket row is always the open-ended top band (`isTop`, no upper-limit input).
 */

interface BracketRow {
  /** Empty string for the open-ended top band (rendered with no input). */
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
  tax_year_label: string
}

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

function viewToForm(view: PlatformTaxDefaultView): TaxForm {
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
    tax_year_label: view.tax_year_label ?? '',
  }
}

function formToPayload(form: TaxForm): PlatformTaxDefaultUpdate {
  return {
    paye_brackets: form.paye_brackets.map((r) => ({
      upper_limit: r.isTop ? null : toNum(r.upper_limit),
      rate: pctToFrac(r.rate),
    })),
    secondary_rates: SECONDARY_TAX_CODES.reduce((acc, code) => {
      acc[code] = pctToFrac(form.secondary_rates[code])
      return acc
    }, {} as SecondaryRates),
    acc_levy_rate: pctToFrac(form.acc_levy_rate),
    acc_max_liable_earnings: toNum(form.acc_max_liable_earnings),
    student_loan_rate: pctToFrac(form.student_loan_rate),
    student_loan_threshold: toNum(form.student_loan_threshold),
    ietc: {
      amount: toNum(form.ietc_amount),
      lower: toNum(form.ietc_lower),
      abatement_start: toNum(form.ietc_abatement_start),
      abatement_rate: pctToFrac(form.ietc_abatement_rate),
      upper: toNum(form.ietc_upper),
    },
    default_kiwisaver_employee_rate: toNum(form.default_kiwisaver_employee_rate),
    default_kiwisaver_employer_rate: toNum(form.default_kiwisaver_employer_rate),
    tax_year_label: form.tax_year_label,
  }
}

/* ── Per-field error helpers ────────────────────────────────────────────── */

/** Exact-match error message for a field key, or undefined. */
function errorFor(errors: FieldError[], field: string): string | undefined {
  return errors.find((e) => e.field === field)?.message
}

/** All error messages whose field starts with the given prefix (grouped fields). */
function errorsByPrefix(errors: FieldError[], prefix: string): FieldError[] {
  return errors.filter((e) => e.field === prefix || e.field.startsWith(`${prefix}.`) || e.field.startsWith(`${prefix}[`))
}

/* ── Section wrapper ────────────────────────────────────────────────────── */

function Section({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-card border border-border bg-card p-5 space-y-4 shadow-card">
      <div>
        <h3 className="text-md font-semibold text-text">{title}</h3>
        {description && <p className="text-xs text-muted mt-0.5">{description}</p>}
      </div>
      {children}
    </div>
  )
}

/* ── Component ──────────────────────────────────────────────────────────── */

export function PayrollTaxDefault() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [form, setForm] = useState<TaxForm | null>(null)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([])
  const { toasts, addToast, dismissToast } = useToast()

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setLoadError(false)
    try {
      const view = await getPlatformTaxDefault(signal)
      setForm(viewToForm(view))
      setUpdatedAt(view.updated_at)
    } catch (err) {
      if (!signal?.aborted) setLoadError(true)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

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
      // Insert a new finite band immediately before the open-ended top band.
      const insertAt = Math.max(0, rows.length - 1)
      rows.splice(insertAt, 0, { upper_limit: '', rate: '', isTop: false })
      return { ...prev, paye_brackets: rows }
    })
  }

  const removeBracketRow = (index: number) => {
    setForm((prev) => {
      if (!prev) return prev
      // The open-ended top band cannot be removed.
      if (prev.paye_brackets[index]?.isTop) return prev
      const rows = prev.paye_brackets.filter((_, i) => i !== index)
      return { ...prev, paye_brackets: rows }
    })
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form) return
    setSaving(true)
    setFieldErrors([])
    try {
      const view = await updatePlatformTaxDefault(formToPayload(form))
      setForm(viewToForm(view))
      setUpdatedAt(view.updated_at)
      addToast('success', 'Platform tax default saved')
    } catch (err: unknown) {
      const detail =
        typeof err === 'object' && err !== null && 'response' in err
          ? (err as { response?: { status?: number; data?: { detail?: unknown } } }).response
          : undefined
      if (detail?.status === 422) {
        const parsed = parseFieldErrors(detail?.data?.detail)
        setFieldErrors(parsed)
        addToast('error', 'Please fix the highlighted fields')
      } else {
        addToast('error', 'Failed to save platform tax default')
      }
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner label="Loading platform tax default" />
      </div>
    )
  }

  if (loadError || !form) {
    return (
      <AlertBanner variant="error" title="Failed to load">
        Could not load the platform tax default. Please try again.
      </AlertBanner>
    )
  }

  const bracketErrors = errorsByPrefix(fieldErrors, 'paye_brackets')
  const secondaryErrors = errorsByPrefix(fieldErrors, 'secondary_rates')
  const ietcErrors = errorsByPrefix(fieldErrors, 'ietc')

  return (
    <div className="max-w-2xl space-y-5">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="rounded-card border-l-4 border-accent bg-accent-soft p-4">
        <h2 className="text-lg font-semibold text-accent">Platform Payroll Tax Default</h2>
        <p className="text-sm text-accent mt-1">
          The platform-wide NZ payroll tax baseline. Organisations inherit these values
          unless they set their own override. Editing here applies IRD rate changes to
          every organisation that has not overridden the field — no deploy required.
        </p>
        <p className="text-xs text-accent mt-2">
          Tax rates are entered as <strong>percentages</strong> — type <span className="mono">10.5</span> for
          10.5%, exactly as IRD publishes them. Income thresholds and dollar amounts are
          entered in <strong>dollars</strong> (e.g. <span className="mono">15600</span>). See{' '}
          <a
            href="https://www.ird.govt.nz/employing-staff/payday-filing/calculating-deductions/paye-and-tax-codes"
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            IRD PAYE rates and thresholds
          </a>
          .
        </p>
        {updatedAt && (
          <p className="text-xs text-accent mt-2">
            Last updated:{' '}
            <span className="mono">
              {new Date(updatedAt).toLocaleString('en-NZ', {
                day: 'numeric',
                month: 'short',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
          </p>
        )}
      </div>

      {fieldErrors.length > 0 && (
        <AlertBanner variant="error" title="Validation failed">
          The submitted configuration was rejected. Fix the field-level errors below and
          save again.
        </AlertBanner>
      )}

      <form onSubmit={handleSave} className="space-y-5">
        {/* ── Tax year label ── */}
        <Section title="Tax year" description="Display label only — does not affect calculations.">
          <Input
            label="Tax year label"
            value={form.tax_year_label}
            onChange={(e) => setField('tax_year_label', e.target.value)}
            placeholder="2024/25"
            error={errorFor(fieldErrors, 'tax_year_label')}
          />
        </Section>

        {/* ── PAYE brackets ── */}
        <Section
          title="PAYE income-tax brackets"
          description="Progressive bands. Each band's rate (%) is the marginal tax on income up to that limit; the last row is the open-ended top band (no upper limit)."
        >
          <div className="space-y-2">
            <div className="grid grid-cols-[1fr_1fr_auto] gap-3 items-end text-[12.5px] font-medium text-muted">
              <span>Upper limit (annual $)</span>
              <span>Rate (%)</span>
              <span className="w-[34px]" aria-hidden="true" />
            </div>
            {form.paye_brackets.map((row, index) => (
              <div
                key={index}
                className="grid grid-cols-[1fr_1fr_auto] gap-3 items-end"
              >
                {row.isTop ? (
                  <div className="flex flex-col gap-[7px]">
                    <span className="h-[42px] flex items-center rounded-ctl border border-dashed border-border bg-canvas px-[13px] text-[13px] text-muted">
                      No upper limit (top band)
                    </span>
                  </div>
                ) : (
                  <Input
                    label=""
                    type="number"
                    step="1"
                    value={row.upper_limit}
                    onChange={(e) => updateBracket(index, { upper_limit: e.target.value })}
                    placeholder="15600"
                  />
                )}
                <Input
                  label=""
                  type="number"
                  step="0.01"
                  value={row.rate}
                  onChange={(e) => updateBracket(index, { rate: e.target.value })}
                  placeholder="10.5"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  iconOnly
                  aria-label={`Remove bracket row ${index + 1}`}
                  disabled={row.isTop}
                  onClick={() => removeBracketRow(index)}
                >
                  ✕
                </Button>
              </div>
            ))}
          </div>

          <Button type="button" variant="ghost" size="sm" onClick={addBracketRow}>
            + Add bracket
          </Button>

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
        >
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {SECONDARY_TAX_CODES.map((code) => (
              <Input
                key={code}
                label={code}
                type="number"
                step="0.01"
                value={form.secondary_rates[code] ?? ''}
                onChange={(e) => setSecondary(code, e.target.value)}
                placeholder="17.5"
                error={errorFor(fieldErrors, `secondary_rates.${code}`)}
              />
            ))}
          </div>
          {secondaryErrors.length > 0 && (
            <ul className="space-y-1" role="alert">
              {secondaryErrors
                .filter((e) => !SECONDARY_TAX_CODES.some((c) => e.field === `secondary_rates.${c}`))
                .map((e, i) => (
                  <li key={`${e.field}-${i}`} className="text-[12.5px] text-danger">
                    {e.field}: {e.message}
                  </li>
                ))}
            </ul>
          )}
        </Section>

        {/* ── ACC ── */}
        <Section title="ACC earner levy">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Input
              label="ACC levy rate (%)"
              type="number"
              step="0.01"
              value={form.acc_levy_rate}
              onChange={(e) => setField('acc_levy_rate', e.target.value)}
              placeholder="1.6"
              helperText="e.g. 1.6 means 1.6%"
              error={errorFor(fieldErrors, 'acc_levy_rate')}
            />
            <Input
              label="ACC max liable earnings ($)"
              type="number"
              step="1"
              value={form.acc_max_liable_earnings}
              onChange={(e) => setField('acc_max_liable_earnings', e.target.value)}
              placeholder="142283"
              error={errorFor(fieldErrors, 'acc_max_liable_earnings')}
            />
          </div>
        </Section>

        {/* ── Student loan ── */}
        <Section title="Student loan">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Input
              label="Student loan rate (%)"
              type="number"
              step="0.01"
              value={form.student_loan_rate}
              onChange={(e) => setField('student_loan_rate', e.target.value)}
              placeholder="12"
              helperText="e.g. 12 means 12%"
              error={errorFor(fieldErrors, 'student_loan_rate')}
            />
            <Input
              label="Student loan threshold ($)"
              type="number"
              step="1"
              value={form.student_loan_threshold}
              onChange={(e) => setField('student_loan_threshold', e.target.value)}
              placeholder="24128"
              error={errorFor(fieldErrors, 'student_loan_threshold')}
            />
          </div>
        </Section>

        {/* ── IETC ── */}
        <Section
          title="Independent Earner Tax Credit (IETC)"
          description="Parameters for the ME tax code."
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Input
              label="Amount ($)"
              type="number"
              step="1"
              value={form.ietc_amount}
              onChange={(e) => setField('ietc_amount', e.target.value)}
              placeholder="520"
              error={errorFor(fieldErrors, 'ietc.amount')}
            />
            <Input
              label="Lower bound ($)"
              type="number"
              step="1"
              value={form.ietc_lower}
              onChange={(e) => setField('ietc_lower', e.target.value)}
              placeholder="24000"
              error={errorFor(fieldErrors, 'ietc.lower')}
            />
            <Input
              label="Abatement start ($)"
              type="number"
              step="1"
              value={form.ietc_abatement_start}
              onChange={(e) => setField('ietc_abatement_start', e.target.value)}
              placeholder="44000"
              error={errorFor(fieldErrors, 'ietc.abatement_start')}
            />
            <Input
              label="Abatement rate (%)"
              type="number"
              step="0.01"
              value={form.ietc_abatement_rate}
              onChange={(e) => setField('ietc_abatement_rate', e.target.value)}
              placeholder="13"
              helperText="e.g. 13 means 13%"
              error={errorFor(fieldErrors, 'ietc.abatement_rate')}
            />
            <Input
              label="Upper bound ($)"
              type="number"
              step="1"
              value={form.ietc_upper}
              onChange={(e) => setField('ietc_upper', e.target.value)}
              placeholder="48000"
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

        {/* ── KiwiSaver defaults ── */}
        <Section
          title="KiwiSaver defaults"
          description="Applied when a staff profile does not specify a rate (percent, 0–100)."
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Input
              label="Employee default rate (%)"
              type="number"
              step="0.01"
              value={form.default_kiwisaver_employee_rate}
              onChange={(e) => setField('default_kiwisaver_employee_rate', e.target.value)}
              placeholder="3.00"
              error={errorFor(fieldErrors, 'default_kiwisaver_employee_rate')}
            />
            <Input
              label="Employer default rate (%)"
              type="number"
              step="0.01"
              value={form.default_kiwisaver_employer_rate}
              onChange={(e) => setField('default_kiwisaver_employer_rate', e.target.value)}
              placeholder="3.00"
              error={errorFor(fieldErrors, 'default_kiwisaver_employer_rate')}
            />
          </div>
        </Section>

        <div className="flex gap-3 pt-1">
          <Button type="submit" loading={saving}>
            Save tax default
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={saving}
            onClick={() => load()}
          >
            Reset changes
          </Button>
        </div>
      </form>
    </div>
  )
}

export default PayrollTaxDefault
