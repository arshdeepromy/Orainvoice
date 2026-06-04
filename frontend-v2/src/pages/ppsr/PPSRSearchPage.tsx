/**
 * PPSRSearchPage — primary surface for the PPSR module.
 *
 * Implements design §6.1 / §6.1a / §6.2 of
 * `.kiro/specs/ppsr-module/design.md`:
 *
 *   1. Page header — "PPSR Vehicle Check" + subtitle.
 *   2. QuotaStrip      — refreshes on mount + after every fresh search.
 *   3. SearchForm      — gated checkboxes per design §6.2.
 *   4. PpsrResultPanel — structured renderer (see D3).
 *   5. PpsrHistoryTable — paginated history (see D4).
 *
 * Module-disabled fallback is handled by `<ModuleRoute moduleSlug="ppsr">`
 * in `App.tsx` (D8) so this component never needs its own gate
 * (G-CODE-3 — earlier draft duplicated the gate which is a maintenance
 * smell).
 *
 * Follows `.kiro/steering/safe-api-consumption.md`:
 *   - Every API consumption uses `?.` + `?? []` / `?? 0`.
 *   - Every `useEffect` issuing an API call uses an `AbortController`.
 *   - Typed API client — no `as any`.
 *
 * **Validates: PPSR module spec task D2 / Requirement R8.**
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { useSearchParams } from 'react-router-dom'
import axios from 'axios'

import {
  ppsrApi,
  type PpsrQuotaResponse,
  type PpsrSearchRequest,
  type PpsrSearchResult,
} from '@/api/ppsr'
import { PpsrResultPanel } from './components/PpsrResultPanel'
import { PpsrHistoryTable } from './components/PpsrHistoryTable'

// ===========================================================================
// CarJam config — Phase 1 fallback (TODO future)
// ===========================================================================
//
// Per design §6.2, "Current owner" / "Ownership history" checkboxes are
// disabled until the org has set both `s241_purpose_default` and
// `ppsr_owner_lookups_enabled=true` in their CarJam admin config.
//
// The existing `/admin/integrations/carjam` endpoint requires global
// admin role, so org users can't read it directly. Until a v2 org-scoped
// read endpoint exists, default both flags to "off" and surface the
// "Configure CarJam in admin" tooltip so the gating is explicit.
//
// TODO(future): when an org-scoped CarJam config endpoint lands, replace
// this constant with a fetch in a useEffect (with AbortController) and
// hydrate from `res.data?.s241_purpose_default ?? null` /
// `res.data?.ppsr_owner_lookups_enabled ?? false`.
const CARJAM_CONFIG_FALLBACK = {
  ppsr_owner_lookups_enabled: false,
  s241_purpose_default: null as string | null,
}
// Retained verbatim from the original for the Phase-1 fallback documentation
// above; not yet wired into a fetch. Referenced here so v2's stricter
// `noUnusedLocals` compiler keeps the declaration intact.
void CARJAM_CONFIG_FALLBACK

// ===========================================================================
// Helpers
// ===========================================================================

const REGO_PATTERN = /^[A-Z0-9]{1,8}$/

function normaliseRego(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8)
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function extractErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)
      ?.detail
    if (typeof detail === 'string' && detail.trim().length > 0) return detail
    if (
      detail &&
      typeof detail === 'object' &&
      'detail' in (detail as Record<string, unknown>) &&
      typeof (detail as Record<string, unknown>).detail === 'string'
    ) {
      return String((detail as Record<string, unknown>).detail)
    }
    if (err.message) return err.message
  }
  if (err instanceof Error) return err.message
  return 'PPSR search failed'
}

// ===========================================================================
// QuotaStrip — top-of-page usage counter
// ===========================================================================

interface QuotaStripProps {
  /** Bumped by the parent after every fresh search to trigger a refresh. */
  refreshKey: number
  /** Callback so the parent can disable the search button when quota=0. */
  onQuotaChange?: (quota: PpsrQuotaResponse | null) => void
}

function QuotaStrip({ refreshKey, onQuotaChange }: QuotaStripProps) {
  const [quota, setQuota] = useState<PpsrQuotaResponse | null>(null)
  const [isLoading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const res = await ppsrApi.getQuota(controller.signal)
        if (cancelled) return
        // ppsrApi.getQuota already guards every field, but apply the
        // safe-api-consumption fallbacks once more defensively.
        const safe: PpsrQuotaResponse = {
          used: res?.used ?? 0,
          included: res?.included ?? 0,
          hidden_plate_used: res?.hidden_plate_used ?? 0,
          hidden_plate_included: res?.hidden_plate_included ?? 0,
          resets_at: res?.resets_at ?? null,
          owner_lookups_enabled: res?.owner_lookups_enabled ?? false,
          s241_purpose_configured: res?.s241_purpose_configured ?? false,
        }
        setQuota(safe)
        onQuotaChange?.(safe)
      } catch (err: unknown) {
        if (controller.signal.aborted || cancelled) return
        setError(extractErrorMessage(err))
        setQuota(null)
        onQuotaChange?.(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [refreshKey, onQuotaChange])

  const used = quota?.used ?? 0
  const included = quota?.included ?? 0
  const remaining = Math.max(0, included - used)
  const pct = included > 0 ? Math.min(100, Math.round((used / included) * 100)) : 0
  const exhausted = included > 0 && used >= included
  const resetsLabel = formatDate(quota?.resets_at ?? null)

  return (
    <section
      aria-label="PPSR quota usage"
      data-testid="ppsr-quota-strip"
      className="rounded-card border border-border bg-card p-4 shadow-card"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-text">
            {isLoading && !quota ? (
              <span className="text-muted-2">
                Loading PPSR quota…
              </span>
            ) : error ? (
              <span className="text-danger">
                Failed to load quota — {error}
              </span>
            ) : (
              <>
                PPSR checks:{' '}
                <span
                  className={`mono ${
                    exhausted ? 'text-danger' : 'text-text'
                  }`}
                  data-testid="ppsr-quota-counter"
                >
                  {used.toLocaleString()} / {included.toLocaleString()}
                </span>{' '}
                <span className="text-muted-2">
                  this month
                  {resetsLabel ? ` — resets ${resetsLabel}` : ''}
                </span>
              </>
            )}
          </p>
          {!isLoading && !error && quota && (
            <p className="mt-0.5 text-xs text-muted-2">
              {remaining.toLocaleString()} remaining
              {(quota?.hidden_plate_included ?? 0) > 0 && (
                <>
                  {' '}
                  · Hidden-plate:{' '}
                  <span className="mono">
                    {(quota?.hidden_plate_used ?? 0).toLocaleString()} /{' '}
                    {(quota?.hidden_plate_included ?? 0).toLocaleString()}
                  </span>
                </>
              )}
            </p>
          )}
        </div>
        {/* Progress bar */}
        <div
          className="h-2 w-full max-w-xs overflow-hidden rounded-full bg-canvas"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
        >
          <div
            className={`h-full transition-all ${
              exhausted
                ? 'bg-danger'
                : pct >= 80
                  ? 'bg-warn'
                  : 'bg-ok'
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    </section>
  )
}

// ===========================================================================
// SearchForm — per design §6.2
// ===========================================================================

interface SearchFormState {
  rego: string
  include_warnings: boolean
  include_fws: boolean
  check_hidden_plates: boolean
  include_current_owner: boolean
  include_ownership_history: boolean
  s241_purpose: string
  force_refresh: boolean
}

interface SearchFormProps {
  initialRego?: string
  loading: boolean
  /** Disabled by the parent when quota.used >= quota.included. */
  quotaExhausted: boolean
  /** From CarJam config — gates the owner-lookup checkboxes. */
  ownerLookupsEnabled: boolean
  /** From CarJam config — pre-populates the s241 input. */
  s241PurposeDefault: string | null
  onSearch: (payload: PpsrSearchRequest) => void
}

function defaultFormState(
  initialRego: string,
  s241Default: string | null,
): SearchFormState {
  return {
    rego: normaliseRego(initialRego ?? ''),
    include_warnings: true,
    include_fws: false,
    check_hidden_plates: false,
    include_current_owner: false,
    include_ownership_history: false,
    s241_purpose: s241Default ?? '',
    force_refresh: false,
  }
}

function SearchForm({
  initialRego = '',
  loading,
  quotaExhausted,
  ownerLookupsEnabled,
  s241PurposeDefault,
  onSearch,
}: SearchFormProps) {
  const [form, setForm] = useState<SearchFormState>(() =>
    defaultFormState(initialRego, s241PurposeDefault),
  )
  const [regoError, setRegoError] = useState<string | null>(null)

  // Re-seed the rego field when the parent changes `?rego=` after mount
  // (e.g. after route navigation) without clobbering user edits.
  useEffect(() => {
    if (initialRego && form.rego.length === 0) {
      setForm((prev) => ({
        ...prev,
        rego: normaliseRego(initialRego),
      }))
    }
    // We deliberately omit `form.rego` from deps to avoid a feedback loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialRego])

  // Re-seed the s241 default when the config arrives after mount.
  useEffect(() => {
    if (s241PurposeDefault && form.s241_purpose.length === 0) {
      setForm((prev) => ({ ...prev, s241_purpose: s241PurposeDefault }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s241PurposeDefault])

  const ownerSectionVisible =
    form.include_current_owner || form.include_ownership_history
  const ownerCheckboxesDisabled =
    !ownerLookupsEnabled || !s241PurposeDefault

  const ownerTooltip = !ownerLookupsEnabled
    ? 'Owner lookups are disabled. Ask your global admin to enable them on the CarJam integration.'
    : !s241PurposeDefault
      ? 'Owner lookups need an s241 purpose code. Ask your global admin to set one on the CarJam integration.'
      : ''
  // Retained verbatim from the original — the owner-lookup checkboxes are
  // hardcoded-disabled in this Phase-1 build, so these gating values aren't
  // wired into the markup yet. Referenced here so v2's stricter
  // `noUnusedLocals` compiler keeps the declarations intact.
  void ownerCheckboxesDisabled
  void ownerTooltip

  const submitDisabled =
    loading ||
    quotaExhausted ||
    !REGO_PATTERN.test(form.rego) ||
    (ownerSectionVisible && form.s241_purpose.trim().length === 0)

  const submitTooltip = quotaExhausted
    ? 'PPSR quota exhausted. Ask your org admin to grant more in your subscription plan.'
    : !REGO_PATTERN.test(form.rego)
      ? 'Enter a valid NZ rego (1-8 letters / digits).'
      : ownerSectionVisible && form.s241_purpose.trim().length === 0
        ? 'Owner lookups require an s241 purpose code.'
        : ''

  const handleSubmit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault()
      const cleanRego = normaliseRego(form.rego)
      if (!REGO_PATTERN.test(cleanRego)) {
        setRegoError('Enter a valid NZ rego (1-8 letters / digits).')
        return
      }
      setRegoError(null)
      const payload: PpsrSearchRequest = {
        rego: cleanRego,
        include_warnings: form.include_warnings,
        include_fws: form.include_fws,
        check_hidden_plates: form.check_hidden_plates,
        include_current_owner: form.include_current_owner,
        include_ownership_history: form.include_ownership_history,
        s241_purpose: ownerSectionVisible
          ? form.s241_purpose.trim() || null
          : null,
        force_refresh: form.force_refresh,
      }
      onSearch(payload)
    },
    [form, ownerSectionVisible, onSearch],
  )

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="rounded-card border border-border bg-card p-6 shadow-card"
      data-testid="ppsr-search-form"
      aria-label="PPSR search form"
    >
      <h2 className="text-base font-medium text-text">
        Search
      </h2>

      <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-[12rem_1fr]">
        {/* Rego ----------------------------------------------------- */}
        <div className="flex flex-col gap-1">
          <label
            htmlFor="ppsr-rego"
            className="text-sm font-medium text-text"
          >
            Rego
          </label>
          <input
            id="ppsr-rego"
            name="rego"
            type="text"
            inputMode="text"
            autoComplete="off"
            spellCheck={false}
            maxLength={8}
            value={form.rego}
            onChange={(e) => {
              setRegoError(null)
              setForm((prev) => ({
                ...prev,
                rego: normaliseRego(e.target.value),
              }))
            }}
            placeholder="ABC123"
            data-testid="ppsr-rego-input"
            className="mono h-10 min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-base uppercase text-text shadow-card placeholder:text-muted-2 focus:outline-none focus:ring-2 focus:ring-accent"
            aria-invalid={regoError ? 'true' : undefined}
            aria-describedby={regoError ? 'ppsr-rego-error' : undefined}
          />
          {regoError && (
            <p
              id="ppsr-rego-error"
              className="text-xs text-danger"
              role="alert"
            >
              {regoError}
            </p>
          )}
        </div>

        {/* Include checkboxes -------------------------------------- */}
        <fieldset
          className="flex flex-col gap-2"
          data-testid="ppsr-include-options"
        >
          <legend className="text-sm font-medium text-text">
            Include
          </legend>

          {/* Money owing — always on, disabled */}
          <label className="inline-flex items-start gap-2 text-sm text-muted">
            <input
              type="checkbox"
              checked
              disabled
              aria-disabled
              className="mt-0.5 h-4 w-4 rounded border-border text-accent focus:ring-accent disabled:opacity-60"
              data-testid="ppsr-include-money-owing"
            />
            <span>
              Money owing{' '}
              <span className="text-xs text-muted-2">
                (always on)
              </span>
            </span>
          </label>

          {/* Warnings & recalls */}
          <label className="inline-flex items-start gap-2 text-sm text-muted">
            <input
              type="checkbox"
              checked={form.include_warnings}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  include_warnings: e.target.checked,
                }))
              }
              className="mt-0.5 h-4 w-4 rounded border-border text-accent focus:ring-accent"
              data-testid="ppsr-include-warnings"
            />
            <span>Warnings &amp; recalls</span>
          </label>

          {/* Fire / water / write-off */}
          <label className="inline-flex items-start gap-2 text-sm text-muted">
            <input
              type="checkbox"
              checked={form.include_fws}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, include_fws: e.target.checked }))
              }
              className="mt-0.5 h-4 w-4 rounded border-border text-accent focus:ring-accent"
              data-testid="ppsr-include-fws"
            />
            <span>Fire / water / write-off</span>
          </label>

          {/* Hidden-plate */}
          <label
            className="inline-flex items-start gap-2 text-sm text-muted"
            title="Searches past plates; CarJam bills this at a higher rate (counts against your separate hidden-plate quota)."
          >
            <input
              type="checkbox"
              checked={form.check_hidden_plates}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  check_hidden_plates: e.target.checked,
                }))
              }
              className="mt-0.5 h-4 w-4 rounded border-border text-accent focus:ring-accent"
              data-testid="ppsr-include-hidden-plate"
            />
            <span>
              Hidden-plate search{' '}
              <span className="text-xs text-muted-2">
                (extra charge)
              </span>{' '}
              <span aria-hidden="true">ⓘ</span>
            </span>
          </label>

          {/* Current owner */}
          <label
            className="inline-flex items-start gap-2 text-sm cursor-not-allowed text-muted-2"
          >
            <input
              type="checkbox"
              checked={false}
              disabled
              className="mt-0.5 h-4 w-4 rounded border-border text-accent focus:ring-accent disabled:opacity-60"
              data-testid="ppsr-include-current-owner"
            />
            <span>
              Current owner
              <span className="ml-1 text-xs text-muted-2">
                — Not available
              </span>
            </span>
          </label>

          {/* Ownership history */}
          <label
            className="inline-flex items-start gap-2 text-sm cursor-not-allowed text-muted-2"
          >
            <input
              type="checkbox"
              checked={false}
              disabled
              className="mt-0.5 h-4 w-4 rounded border-border text-accent focus:ring-accent disabled:opacity-60"
              data-testid="ppsr-include-ownership-history"
            />
            <span>
              Ownership history
              <span className="ml-1 text-xs text-muted-2">
                — Not available
              </span>
            </span>
          </label>
        </fieldset>
      </div>

      {/* s241_purpose — only visible when an owner section is checked */}
      {ownerSectionVisible && (
        <div className="mt-4 max-w-md">
          <label
            htmlFor="ppsr-s241-purpose"
            className="text-sm font-medium text-text"
          >
            s241 purpose
          </label>
          <input
            id="ppsr-s241-purpose"
            type="text"
            value={form.s241_purpose}
            onChange={(e) =>
              setForm((prev) => ({ ...prev, s241_purpose: e.target.value }))
            }
            placeholder={s241PurposeDefault ?? 'e.g. Selling vehicle'}
            data-testid="ppsr-s241-input"
            className="mt-1 h-10 min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text shadow-card focus:outline-none focus:ring-2 focus:ring-accent"
            required
          />
          <p className="mt-1 text-xs text-muted-2">
            Required for owner lookups. Pre-populated from your CarJam config
            when set.
          </p>
        </div>
      )}

      {/* Force refresh toggle ------------------------------------- */}
      <div className="mt-4">
        <label className="inline-flex items-center gap-2 text-sm text-muted">
          <input
            type="checkbox"
            checked={form.force_refresh}
            onChange={(e) =>
              setForm((prev) => ({ ...prev, force_refresh: e.target.checked }))
            }
            className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
            data-testid="ppsr-force-refresh"
          />
          <span>
            Force refresh{' '}
            <span className="text-xs text-muted-2">
              (ignore the 5-minute cache)
            </span>
          </span>
        </label>
      </div>

      {/* Submit --------------------------------------------------- */}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={submitDisabled}
          title={submitTooltip || undefined}
          aria-disabled={submitDisabled || undefined}
          className="inline-flex h-10 min-h-[44px] items-center rounded-ctl bg-accent px-5 text-sm font-medium text-white shadow-card hover:bg-accent-press focus:outline-none focus:ring-2 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          data-testid="ppsr-submit-button"
        >
          {loading ? 'Searching…' : 'Run search'}
        </button>
        {quotaExhausted && (
          <span className="text-xs text-danger">
            PPSR quota exhausted for this month.
          </span>
        )}
      </div>
    </form>
  )
}

// ===========================================================================
// Page component
// ===========================================================================

export function PPSRSearchPage() {
  const [searchParams] = useSearchParams()
  const initialRego = useMemo(
    () => searchParams.get('rego') ?? '',
    [searchParams],
  )

  const [result, setResult] = useState<PpsrSearchResult | null>(null)
  const [isSearching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [quota, setQuota] = useState<PpsrQuotaResponse | null>(null)

  const handleQuotaChange = useCallback((next: PpsrQuotaResponse | null) => {
    setQuota(next)
  }, [])

  const handleSearch = useCallback(async (payload: PpsrSearchRequest) => {
    setSearching(true)
    setError(null)
    try {
      const res = await ppsrApi.search(payload)
      setResult(res ?? null)
      // Bump the refresh key so QuotaStrip + PpsrHistoryTable refetch.
      setRefreshKey((k) => k + 1)
    } catch (err: unknown) {
      setError(extractErrorMessage(err))
      setResult(null)
    } finally {
      setSearching(false)
    }
  }, [])

  const handleNew = useCallback(() => {
    setResult(null)
    setError(null)
  }, [])

  const handleForceRefresh = useCallback(() => {
    if (!result) return
    handleSearch({
      rego: result.rego ?? '',
      force_refresh: true,
    })
  }, [result, handleSearch])

  const quotaExhausted =
    (quota?.included ?? 0) > 0 && (quota?.used ?? 0) >= (quota?.included ?? 0)

  return (
    <div
      className="space-y-6 px-4 py-6 sm:px-6 lg:px-8"
      data-testid="ppsr-search-page"
    >
      {/* 1. Page header --------------------------------------------- */}
      <header>
        <h1 className="text-2xl font-semibold text-text">
          PPSR Vehicle Check
        </h1>
        <p className="mt-1 text-sm text-muted">
          Check money owing, ownership, and warnings on any NZ vehicle.
        </p>
      </header>

      {/* 2. Quota strip --------------------------------------------- */}
      <QuotaStrip
        refreshKey={refreshKey}
        onQuotaChange={handleQuotaChange}
      />

      {/* 3. Search form --------------------------------------------- */}
      <SearchForm
        initialRego={initialRego}
        loading={isSearching}
        quotaExhausted={quotaExhausted}
        ownerLookupsEnabled={quota?.owner_lookups_enabled ?? false}
        s241PurposeDefault={quota?.s241_purpose_configured ? 'Configured' : null}
        onSearch={handleSearch}
      />

      {/* Error banner ----------------------------------------------- */}
      {error && (
        <div
          role="alert"
          className="rounded-ctl border border-danger/40 bg-danger-soft p-3 text-sm text-danger"
          data-testid="ppsr-search-error"
        >
          {error}
        </div>
      )}

      {/* 4. Result panel -------------------------------------------- */}
      {result && (
        <PpsrResultPanel
          result={result}
          onNew={handleNew}
          onForceRefresh={handleForceRefresh}
        />
      )}

      {/* 5. History ------------------------------------------------- */}
      <PpsrHistoryTable refreshKey={refreshKey} />
    </div>
  )
}

export default PPSRSearchPage
