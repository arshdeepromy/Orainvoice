/**
 * Currency Settings page — manages enabled currencies, exchange rates,
 * historical rate charts, and rate provider configuration.
 *
 * Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import apiClient from '@/api/client'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useTerm } from '@/contexts/TerminologyContext'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Tabs } from '@/components/ui/Tabs'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import {
  formatCurrencyAmount,
  isMissingExchangeRate,
  ISO_4217_CURRENCIES,
  getCurrencyFormat,
} from '@/utils/currencyCalcs'
import type { ISO4217Currency } from '@/utils/currencyCalcs'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface OrgCurrency {
  id: string
  org_id: string
  currency_code: string
  is_base: boolean
  enabled: boolean
}

interface ExchangeRate {
  id: string
  base_currency: string
  target_currency: string
  rate: string
  source: string
  effective_date: string
  created_at: string
}

interface HistoricalRate {
  date: string
  rate: number
}

interface RateProviderConfig {
  provider: string
  update_frequency: string
  last_sync: string | null
  status: 'active' | 'error' | 'inactive'
}

type ChartRange = '7d' | '30d' | '90d' | '1y'

/* ------------------------------------------------------------------ */
/*  Currency Search & Enable Panel (Req 13.2)                          */
/* ------------------------------------------------------------------ */

function CurrencySearchPanel({
  enabledCodes,
  onEnable,
  onClose,
}: {
  enabledCodes: Set<string>
  onEnable: (code: string) => Promise<void>
  onClose: () => void
}) {
  const [search, setSearch] = useState('')
  const [enabling, setEnabling] = useState<string | null>(null)

  const filtered = useMemo(() => {
    if (!search.trim()) return ISO_4217_CURRENCIES
    const q = search.toLowerCase()
    return ISO_4217_CURRENCIES.filter(
      (c) =>
        c.code.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        c.symbol.includes(q),
    )
  }, [search])

  const handleEnable = async (currency: ISO4217Currency) => {
    setEnabling(currency.code)
    try {
      await onEnable(currency.code)
    } finally {
      setEnabling(null)
    }
  }

  return (
    <div
      className="border border-gray-200 rounded-lg p-4 space-y-3"
      data-testid="currency-search-panel"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-900">Enable Currency</h3>
        <Button
          variant="secondary"
          size="sm"
          onClick={onClose}
          style={{ minHeight: 44, minWidth: 44 }}
          data-testid="currency-search-close"
        >
          Cancel
        </Button>
      </div>
      <div>
        <label htmlFor="currency-search" className="text-sm font-medium text-gray-700 block mb-1">
          Search currencies
        </label>
        <input
          id="currency-search"
          type="search"
          placeholder="Search by code, name, or symbol…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          data-testid="currency-search-input"
          style={{ minHeight: 44 }}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
            placeholder:text-gray-400
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
        />
      </div>
      <div className="max-h-64 overflow-y-auto divide-y divide-gray-100">
        {filtered.length === 0 && (
          <p className="text-center text-gray-500 py-4" data-testid="currency-search-empty">
            No currencies match your search.
          </p>
        )}
        {filtered.map((c) => {
          const alreadyEnabled = enabledCodes.has(c.code)
          return (
            <div
              key={c.code}
              className="flex items-center justify-between py-2 px-1"
              data-testid={`currency-option-${c.code}`}
            >
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-900">{c.code}</span>
                <span className="text-gray-500 text-sm">{c.name}</span>
                <span className="text-gray-400 text-sm">{c.symbol}</span>
                <Badge variant="neutral">{c.decimalPlaces} dp</Badge>
              </div>
              {alreadyEnabled ? (
                <Badge variant="success">Enabled</Badge>
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => handleEnable(c)}
                  loading={enabling === c.code}
                  disabled={enabling !== null}
                  style={{ minHeight: 44, minWidth: 44 }}
                  data-testid={`enable-currency-${c.code}`}
                >
                  Enable
                </Button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Historical Rate Chart (Req 13.4)                                   */
/* ------------------------------------------------------------------ */

function HistoricalRateChart({
  baseCurrency,
  targetCurrency,
}: {
  baseCurrency: string
  targetCurrency: string
}) {
  const [range, setRange] = useState<ChartRange>('30d')
  const [history, setHistory] = useState<HistoricalRate[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function fetchHistory() {
      setLoading(true)
      try {
        const res = await apiClient.get(
          `/api/v2/currencies/rates/history?base_currency=${baseCurrency}&target_currency=${targetCurrency}&range=${range}`,
        )
        if (!cancelled) setHistory(res.data ?? [])
      } catch {
        if (!cancelled) setHistory([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchHistory()
    return () => { cancelled = true }
  }, [baseCurrency, targetCurrency, range])

  const rangeOptions: { value: ChartRange; label: string }[] = [
    { value: '7d', label: '7 Days' },
    { value: '30d', label: '30 Days' },
    { value: '90d', label: '90 Days' },
    { value: '1y', label: '1 Year' },
  ]

  const maxRate = history.length > 0 ? Math.max(...history.map((h) => h.rate)) : 1
  const minRate = history.length > 0 ? Math.min(...history.map((h) => h.rate)) : 0
  const rateRange = maxRate - minRate || 1

  return (
    <div
      className="border border-gray-200 rounded-lg p-4 space-y-3"
      data-testid={`rate-chart-${baseCurrency}-${targetCurrency}`}
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h4 className="font-medium text-gray-900">
          {baseCurrency}/{targetCurrency} Rate History
        </h4>
        <div className="flex gap-1" role="group" aria-label="Chart date range">
          {rangeOptions.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setRange(opt.value)}
              style={{ minHeight: 44, minWidth: 44 }}
              data-testid={`chart-range-${opt.value}`}
              className={`px-3 py-1 text-sm rounded-md transition-colors
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
                ${range === opt.value
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <Spinner label="Loading rate history" />
      ) : history.length === 0 ? (
        <p className="text-center text-gray-500 py-4" data-testid="chart-empty">
          No historical data available for this range.
        </p>
      ) : (
        <div className="relative h-40" data-testid="chart-bars" aria-label="Rate history chart">
          <div className="flex items-end h-full gap-px">
            {history.map((h, i) => {
              const height = ((h.rate - minRate) / rateRange) * 100
              return (
                <div
                  key={i}
                  className="flex-1 bg-blue-500 rounded-t-sm hover:bg-blue-600 transition-colors relative group"
                  style={{ height: `${Math.max(height, 2)}%` }}
                  title={`${h.date}: ${h.rate}`}
                  data-testid={`chart-bar-${i}`}
                >
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block
                    bg-gray-900 text-white text-xs rounded px-2 py-1 whitespace-nowrap z-10">
                    {h.date}: {h.rate.toFixed(6)}
                  </div>
                </div>
              )
            })}
          </div>
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>{history[0]?.date}</span>
            <span>{history[history.length - 1]?.date}</span>
          </div>
        </div>
      )}
    </div>
  )
}


/* ------------------------------------------------------------------ */
/*  Rate Provider Configuration (Req 13.5)                             */
/* ------------------------------------------------------------------ */

function RateProviderSection({
  baseCurrency,
  onRefresh,
}: {
  baseCurrency: string
  onRefresh: () => Promise<void>
}) {
  const [config, setConfig] = useState<RateProviderConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function fetchConfig() {
      try {
        const res = await apiClient.get('/api/v2/currencies/provider')
        if (!cancelled) setConfig(res.data)
      } catch {
        // Provider config endpoint may not exist yet — show defaults
        if (!cancelled) {
          setConfig({
            provider: 'Open Exchange Rates',
            update_frequency: 'Daily',
            last_sync: null,
            status: 'inactive',
          })
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchConfig()
    return () => { cancelled = true }
  }, [])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await apiClient.post(`/api/v2/currencies/rates/refresh?base_currency=${baseCurrency}`)
      await onRefresh()
    } finally {
      setRefreshing(false)
    }
  }

  const statusVariant = config?.status === 'active' ? 'success' : config?.status === 'error' ? 'error' : 'neutral'

  if (loading) return <Spinner label="Loading provider config" />

  return (
    <div
      className="border border-gray-200 rounded-lg p-4 space-y-3"
      data-testid="rate-provider-section"
    >
      <h3 className="text-lg font-semibold text-gray-900">Rate Provider</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <span className="text-sm text-gray-500">Provider</span>
          <p className="font-medium text-gray-900" data-testid="provider-name">
            {config?.provider ?? 'Not configured'}
          </p>
        </div>
        <div>
          <span className="text-sm text-gray-500">Update Frequency</span>
          <p className="font-medium text-gray-900" data-testid="provider-frequency">
            {config?.update_frequency ?? '—'}
          </p>
        </div>
        <div>
          <span className="text-sm text-gray-500">Last Sync</span>
          <p className="font-medium text-gray-900" data-testid="provider-last-sync">
            {config?.last_sync ?? 'Never'}
          </p>
        </div>
        <div>
          <span className="text-sm text-gray-500">Status</span>
          <div data-testid="provider-status">
            <Badge variant={statusVariant}>
              {config?.status ?? 'unknown'}
            </Badge>
          </div>
        </div>
      </div>
      <Button
        variant="secondary"
        onClick={handleRefresh}
        loading={refreshing}
        style={{ minHeight: 44, minWidth: 44 }}
        data-testid="refresh-rates-btn"
      >
        Refresh Rates from Provider
      </Button>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Manual Rate Entry Form (Req 13.3)                                  */
/* ------------------------------------------------------------------ */

function ManualRateForm({
  baseCurrency,
  enabledCodes,
  onSave,
  onCancel,
}: {
  baseCurrency: string
  enabledCodes: string[]
  onSave: () => Promise<void>
  onCancel: () => void
}) {
  const [targetCurrency, setTargetCurrency] = useState('')
  const [rate, setRate] = useState('')
  const [effectiveDate, setEffectiveDate] = useState(
    new Date().toISOString().split('T')[0],
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const nonBaseCodes = enabledCodes.filter((c) => c !== baseCurrency)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!targetCurrency || !rate) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post('/api/v2/currencies/rates', {
        base_currency: baseCurrency,
        target_currency: targetCurrency,
        rate: parseFloat(rate),
        effective_date: effectiveDate,
      })
      await onSave()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to set exchange rate')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border border-gray-200 rounded-lg p-4 space-y-3"
      aria-label="Set exchange rate form"
      data-testid="manual-rate-form"
    >
      <h3 className="text-lg font-semibold text-gray-900">Set Manual Rate</h3>
      {error && (
        <AlertBanner variant="error" onDismiss={() => setError(null)}>
          {error}
        </AlertBanner>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label htmlFor="rate-base" className="text-sm font-medium text-gray-700 block mb-1">
            Base Currency
          </label>
          <input
            id="rate-base"
            type="text"
            value={baseCurrency}
            disabled
            style={{ minHeight: 44 }}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-500 bg-gray-50"
            data-testid="rate-base-input"
          />
        </div>
        <div>
          <label htmlFor="rate-target" className="text-sm font-medium text-gray-700 block mb-1">
            Target Currency
          </label>
          <select
            id="rate-target"
            value={targetCurrency}
            onChange={(e) => setTargetCurrency(e.target.value)}
            required
            style={{ minHeight: 44 }}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            data-testid="rate-target-select"
          >
            <option value="">Select currency…</option>
            {nonBaseCodes.map((code) => (
              <option key={code} value={code}>{code}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="rate-value" className="text-sm font-medium text-gray-700 block mb-1">
            Exchange Rate
          </label>
          <input
            id="rate-value"
            type="number"
            inputMode="numeric"
            step="0.00000001"
            min="0.00000001"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            required
            placeholder="e.g. 0.61"
            style={{ minHeight: 44 }}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            data-testid="rate-value-input"
          />
        </div>
        <div>
          <label htmlFor="rate-date" className="text-sm font-medium text-gray-700 block mb-1">
            Effective Date
          </label>
          <input
            id="rate-date"
            type="date"
            value={effectiveDate}
            onChange={(e) => setEffectiveDate(e.target.value)}
            required
            style={{ minHeight: 44 }}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            data-testid="rate-date-input"
          />
        </div>
      </div>
      <div className="flex gap-2">
        <Button
          type="submit"
          loading={saving}
          style={{ minHeight: 44, minWidth: 44 }}
          data-testid="save-rate-btn"
        >
          Save Rate
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={onCancel}
          style={{ minHeight: 44, minWidth: 44 }}
          data-testid="cancel-rate-btn"
        >
          Cancel
        </Button>
      </div>
    </form>
  )
}

/* ------------------------------------------------------------------ */
/*  Exchange Rate Row                                                  */
/* ------------------------------------------------------------------ */

function ExchangeRateRow({
  rate,
  onShowChart,
}: {
  rate: ExchangeRate
  onShowChart: (base: string, target: string) => void
}) {
  const fmt = getCurrencyFormat(rate.target_currency)

  return (
    <tr data-testid={`rate-row-${rate.base_currency}-${rate.target_currency}`}>
      <td className="px-4 py-3 text-sm font-medium text-gray-900">{rate.base_currency}</td>
      <td className="px-4 py-3 text-sm text-gray-900">
        <div className="flex items-center gap-2">
          {rate.target_currency}
          <Badge variant="neutral">{fmt.decimalPlaces} dp</Badge>
        </div>
      </td>
      <td className="px-4 py-3 text-sm text-gray-900 font-mono">{rate.rate}</td>
      <td className="px-4 py-3 text-sm">
        <Badge variant={rate.source === 'manual' ? 'warning' : 'info'}>
          {rate.source}
        </Badge>
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">{rate.effective_date}</td>
      <td className="px-4 py-3 text-sm">
        <button
          type="button"
          onClick={() => onShowChart(rate.base_currency, rate.target_currency)}
          style={{ minHeight: 44, minWidth: 44 }}
          className="text-blue-600 hover:text-blue-800 underline text-sm
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
          data-testid={`show-chart-${rate.target_currency}`}
        >
          History
        </button>
      </td>
    </tr>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function CurrencySettings() {
  // Context integration (Req 13)
  const { isAllowed, isLoading: guardLoading, toasts: guardToasts, dismissToast: dismissGuardToast } = useModuleGuard('multi_currency')
  void useFlag('multi_currency')
  const currencyLabel = useTerm('currency', 'Currency')

  const [currencies, setCurrencies] = useState<OrgCurrency[]>([])
  const [rates, setRates] = useState<ExchangeRate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showSearch, setShowSearch] = useState(false)
  const [showRateForm, setShowRateForm] = useState(false)
  const [chartPair, setChartPair] = useState<{ base: string; target: string } | null>(null)
  const { toasts, addToast, dismissToast } = useToast()

  const baseCurrency = useMemo(
    () => currencies.find((c) => c.is_base)?.currency_code || 'NZD',
    [currencies],
  )

  const enabledCodes = useMemo(
    () => new Set(currencies.filter((c) => c.enabled).map((c) => c.currency_code)),
    [currencies],
  )

  const ratesMap = useMemo(() => {
    const map: Record<string, number> = {}
    for (const r of rates) {
      map[r.target_currency] = parseFloat(r.rate)
    }
    return map
  }, [rates])

  const fetchData = useCallback(async () => {
    try {
      setLoading(true)
      const [currRes, rateRes] = await Promise.all([
        apiClient.get('/api/v2/currencies'),
        apiClient.get('/api/v2/currencies/rates'),
      ])
      setCurrencies(currRes.data)
      setRates(rateRes.data)
    } catch {
      setError('Failed to load currency settings')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isAllowed) fetchData()
  }, [fetchData, isAllowed])

  const handleEnableCurrency = async (code: string) => {
    try {
      await apiClient.post('/api/v2/currencies/enable', {
        currency_code: code,
        is_base: false,
      })
      addToast('success', `${code} enabled`)
      await fetchData()
    } catch (err: any) {
      addToast('error', err?.response?.data?.detail || `Failed to enable ${code}`)
    }
  }

  const handleRateSaved = async () => {
    setShowRateForm(false)
    addToast('success', 'Exchange rate saved')
    await fetchData()
  }

  const handleProviderRefresh = async () => {
    addToast('success', 'Rates refreshed from provider')
    await fetchData()
  }

  // Loading states
  if (guardLoading) {
    return (
      <div className="flex items-center justify-center py-20" data-testid="currency-guard-loading">
        <Spinner label="Loading currency settings" />
        <ToastContainer toasts={guardToasts} onDismiss={dismissGuardToast} />
      </div>
    )
  }

  if (!isAllowed) return <ToastContainer toasts={guardToasts} onDismiss={dismissGuardToast} />

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20" data-testid="currency-settings-loading">
        <Spinner label="Loading currency settings" />
      </div>
    )
  }

  // Currencies with missing rates (Req 13.6)
  const currenciesMissingRates = currencies
    .filter((c) => c.enabled && !c.is_base)
    .filter((c) => isMissingExchangeRate(c.currency_code, ratesMap, baseCurrency))

  // Tabs content
  const currenciesTab = (
    <div className="space-y-4" data-testid="currencies-tab">
      {/* Base currency display (Req 13.1) */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4" data-testid="base-currency-display">
        <span className="text-sm text-blue-700">Base {currencyLabel}</span>
        <p className="text-xl font-bold text-blue-900" data-testid="base-currency-code">
          {baseCurrency}
        </p>
        <p className="text-sm text-blue-600">
          {getCurrencyFormat(baseCurrency).symbol} — All exchange rates are relative to this currency
        </p>
      </div>

      {/* Missing rate warnings (Req 13.6) */}
      {currenciesMissingRates.length > 0 && (
        <div data-testid="missing-rates-warning">
          <AlertBanner variant="warning">
            <strong>Missing exchange rates:</strong>{' '}
            {currenciesMissingRates.map((c) => c.currency_code).join(', ')}.
            Invoice creation is blocked for these currencies until rates are entered.
          </AlertBanner>
        </div>
      )}

      {/* Enabled currencies list */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-900">Enabled Currencies</h3>
        <Button
          variant="primary"
          size="sm"
          onClick={() => setShowSearch(true)}
          style={{ minHeight: 44, minWidth: 44 }}
          data-testid="open-currency-search"
        >
          Enable {currencyLabel}
        </Button>
      </div>

      {showSearch && (
        <CurrencySearchPanel
          enabledCodes={enabledCodes}
          onEnable={handleEnableCurrency}
          onClose={() => setShowSearch(false)}
        />
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200" data-testid="enabled-currencies-table">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{currencyLabel}</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Decimals</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Sample</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {currencies.filter((c) => c.enabled).map((c) => {
              const fmt = getCurrencyFormat(c.currency_code)
              const missing = isMissingExchangeRate(c.currency_code, ratesMap, baseCurrency)
              return (
                <tr key={c.id} data-testid={`currency-row-${c.currency_code}`}>
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{c.currency_code}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{fmt.symbol}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{fmt.decimalPlaces}</td>
                  <td className="px-4 py-3 text-sm">
                    {c.is_base ? (
                      <Badge variant="info">Base</Badge>
                    ) : (
                      <Badge variant="neutral">Additional</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {missing ? (
                      <span data-testid={`missing-rate-${c.currency_code}`}>
                        <Badge variant="warning">⚠ No Rate</Badge>
                      </span>
                    ) : (
                      <Badge variant="success">Active</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm font-mono text-gray-700" data-testid={`sample-format-${c.currency_code}`}>
                    {formatCurrencyAmount(1234.567, c.currency_code)}
                  </td>
                </tr>
              )
            })}
            {currencies.filter((c) => c.enabled).length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  No currencies enabled
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )

  const ratesTab = (
    <div className="space-y-4" data-testid="rates-tab">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-lg font-semibold text-gray-900">Exchange Rates</h3>
        <Button
          variant="primary"
          size="sm"
          onClick={() => setShowRateForm(true)}
          style={{ minHeight: 44, minWidth: 44 }}
          data-testid="open-rate-form"
        >
          Add Manual Rate
        </Button>
      </div>

      {showRateForm && (
        <ManualRateForm
          baseCurrency={baseCurrency}
          enabledCodes={[...enabledCodes]}
          onSave={handleRateSaved}
          onCancel={() => setShowRateForm(false)}
        />
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200" data-testid="exchange-rates-table">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Base</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Target</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Rate</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Chart</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rates.map((r) => (
              <ExchangeRateRow
                key={r.id}
                rate={r}
                onShowChart={(base, target) => setChartPair({ base, target })}
              />
            ))}
            {rates.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  No exchange rates configured
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Historical rate chart (Req 13.4) */}
      {chartPair && (
        <HistoricalRateChart
          baseCurrency={chartPair.base}
          targetCurrency={chartPair.target}
        />
      )}
    </div>
  )

  const providerTab = (
    <RateProviderSection
      baseCurrency={baseCurrency}
      onRefresh={handleProviderRefresh}
    />
  )

  const tabs = [
    { id: 'currencies', label: 'Currencies', content: currenciesTab },
    { id: 'rates', label: 'Exchange Rates', content: ratesTab },
    { id: 'provider', label: 'Rate Provider', content: providerTab },
  ]

  return (
    <div data-testid="currency-settings" className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">{currencyLabel} Settings</h1>
        <Button
          variant="secondary"
          onClick={() => {
            setLoading(true)
            fetchData().finally(() => setLoading(false))
          }}
          style={{ minHeight: 44, minWidth: 44 }}
          data-testid="currency-refresh-btn"
        >
          Refresh
        </Button>
      </div>

      {error && (
        <div data-testid="currency-error">
          <AlertBanner variant="error" onDismiss={() => setError(null)}>
            {error}
          </AlertBanner>
        </div>
      )}

      <Tabs tabs={tabs} />

      <ToastContainer toasts={[...toasts, ...guardToasts]} onDismiss={(id) => { dismissToast(id); dismissGuardToast(id) }} />
    </div>
  )
}
