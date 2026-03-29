/**
 * Tip management pages: TipPrompt dialog, Tip Distribution Rules,
 * Staff Tip Allocation, and Tip Analytics dashboard.
 *
 * Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6
 */

import React, { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Tabs } from '@/components/ui/Tabs'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import { useTerm } from '@/contexts/TerminologyContext'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { distributeTips } from '@/utils/tippingCalcs'

/* ── Types ── */

interface TipPromptProps {
  /** The transaction subtotal to calculate percentages from */
  subtotal: number
  /** Called when user confirms a tip amount (0 for no tip) */
  onConfirm: (tipAmount: number) => void
  /** Called when user skips tipping */
  onSkip: () => void
}

interface DistributionRule {
  id: string
  org_id: string
  method: 'equal_split' | 'percentage' | 'role_based'
  staff_eligibility: string[]
  tip_pooling: boolean
  role_percentages: Record<string, number>
  created_at: string
  updated_at: string
}

interface StaffMember {
  id: string
  name: string
  role: string
  share: number
}

interface TipAllocationRecord {
  staff_member_id: string
  staff_name: string
  total_tips: number
  tip_count: number
  average_tip: number
}

interface TipAnalyticsData {
  total_tips_collected: number
  average_tip_percentage: number
  tips_by_payment_method: { method: string; total: number; count: number }[]
  tips_per_staff: { staff_id: string; name: string; total: number }[]
  daily_totals: { date: string; total: number }[]
  period: 'daily' | 'weekly' | 'monthly'
}

interface TipSummaryInfo {
  tip_amount: number
  payment_method: string
  staff_allocations: { name: string; amount: number }[]
}

/* ── Constants ── */

const PRESET_PERCENTAGES = [10, 15, 20]

/* ── TipPrompt Dialog (original component, enhanced) ── */

export default function TipPrompt({ subtotal, onConfirm, onSkip }: TipPromptProps) {
  const [selectedPreset, setSelectedPreset] = useState<number | null>(null)
  const [customAmount, setCustomAmount] = useState<string>('')
  const [isCustom, setIsCustom] = useState(false)

  const tipLabel = useTerm('tip', 'Tip')

  const tipAmount = isCustom
    ? parseFloat(customAmount) || 0
    : selectedPreset !== null
      ? Math.round(subtotal * (selectedPreset / 100) * 100) / 100
      : 0

  const handlePresetClick = (pct: number) => {
    setIsCustom(false)
    setSelectedPreset(pct)
  }

  const handleCustomClick = () => {
    setIsCustom(true)
    setSelectedPreset(null)
  }

  const handleConfirm = () => {
    onConfirm(tipAmount)
  }

  const hasSelection = tipAmount > 0

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      role="dialog"
      aria-label={`Add a ${tipLabel}`}
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-center">Add a {tipLabel}</h2>
        </div>

        <div className="px-6 py-6">
          {/* Subtotal display */}
          <div className="text-center mb-6">
            <p className="text-sm text-gray-500">Transaction Total</p>
            <p className="text-2xl font-bold text-gray-900" data-testid="tip-subtotal">
              ${subtotal.toFixed(2)}
            </p>
          </div>

          {/* Preset percentage buttons */}
          <div className="flex gap-3 mb-4" role="group" aria-label="Tip percentage presets">
            {PRESET_PERCENTAGES.map((pct) => {
              const amount = Math.round(subtotal * (pct / 100) * 100) / 100
              const isSelected = !isCustom && selectedPreset === pct
              return (
                <button
                  key={pct}
                  type="button"
                  onClick={() => handlePresetClick(pct)}
                  className={`flex-1 py-3 rounded-lg text-center border-2 transition-colors ${
                    isSelected
                      ? 'border-blue-600 bg-blue-50 text-blue-700'
                      : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300'
                  }`}
                  style={{ minHeight: 44, minWidth: 44 }}
                  aria-pressed={isSelected}
                  data-testid={`tip-preset-${pct}`}
                >
                  <span className="block text-lg font-semibold">{pct}%</span>
                  <span className="block text-sm text-gray-500">${amount.toFixed(2)}</span>
                </button>
              )
            })}
          </div>

          {/* Custom amount */}
          <div className="mb-4">
            <button
              type="button"
              onClick={handleCustomClick}
              className={`w-full py-2 rounded-lg text-sm font-medium border-2 transition-colors ${
                isCustom
                  ? 'border-blue-600 bg-blue-50 text-blue-700'
                  : 'border-gray-200 text-gray-600 hover:border-gray-300'
              }`}
              style={{ minHeight: 44 }}
              data-testid="tip-custom-btn"
            >
              Custom Amount
            </button>
            {isCustom && (
              <div className="mt-3">
                <label htmlFor="custom-tip" className="sr-only">Custom tip amount</label>
                <input
                  id="custom-tip"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  step={0.01}
                  value={customAmount}
                  onChange={(e) => setCustomAmount(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-lg text-center"
                  style={{ minHeight: 44 }}
                  placeholder="0.00"
                  autoFocus
                  data-testid="tip-custom-input"
                />
              </div>
            )}
          </div>

          {/* Tip amount display */}
          {hasSelection && (
            <div className="text-center py-3 bg-green-50 rounded-lg mb-4">
              <p className="text-sm text-gray-600">{tipLabel} Amount</p>
              <p className="text-2xl font-bold text-green-600" data-testid="tip-amount">
                ${tipAmount.toFixed(2)}
              </p>
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="px-6 py-4 border-t border-gray-200 flex gap-3">
          <button
            onClick={onSkip}
            className="flex-1 py-2.5 rounded-md border border-gray-300 text-gray-700 font-medium hover:bg-gray-50"
            style={{ minHeight: 44, minWidth: 44 }}
            data-testid="tip-skip"
          >
            No {tipLabel}
          </button>
          <button
            onClick={handleConfirm}
            disabled={!hasSelection}
            className="flex-1 py-2.5 rounded-md bg-blue-600 text-white font-semibold hover:bg-blue-700 disabled:opacity-50"
            style={{ minHeight: 44, minWidth: 44 }}
            data-testid="tip-confirm"
          >
            Add {tipLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── Tip Distribution Rules Page (Req 15.2) ── */

function DistributionRulesSection({
  rule,
  staff,
  onSave,
  error,
}: {
  rule: DistributionRule | null
  staff: StaffMember[]
  onSave: (method: string, pooling: boolean, rolePercentages: Record<string, number>) => void
  error: string | null
}) {
  const tipLabel = useTerm('tip', 'Tip')
  const [method, setMethod] = useState<string>(rule?.method || 'equal_split')
  const [pooling, setPooling] = useState(rule?.tip_pooling ?? true)
  const [rolePercentages, setRolePercentages] = useState<Record<string, number>>(
    rule?.role_percentages || {},
  )

  useEffect(() => {
    if (rule) {
      setMethod(rule.method)
      setPooling(rule.tip_pooling)
      setRolePercentages(rule.role_percentages || {})
    }
  }, [rule])

  const uniqueRoles = [...new Set(staff.map((s) => s.role))].filter(Boolean)
  const totalPct = Object.values(rolePercentages).reduce((s, v) => s + v, 0)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSave(method, pooling, rolePercentages)
  }

  return (
    <div data-testid="distribution-rules-section">
      <h3>{tipLabel} Distribution Rules</h3>
      {error && (
        <div role="alert" style={{ color: '#ef4444', marginBottom: 8 }}>{error}</div>
      )}
      <form onSubmit={handleSubmit} aria-label="Tip distribution rules form">
        <div style={{ marginBottom: 12 }}>
          <label htmlFor="dist-method">Distribution Method</label>
          <select
            id="dist-method"
            value={method}
            onChange={(e) => setMethod(e.target.value)}
            style={{ minHeight: 44, width: '100%' }}
            data-testid="dist-method-select"
          >
            <option value="equal_split">Equal Split</option>
            <option value="percentage">Percentage-Based</option>
            <option value="role_based">Role-Based</option>
          </select>
        </div>

        {method === 'percentage' && (
          <div style={{ marginBottom: 12 }} data-testid="percentage-config">
            <p className="text-sm text-gray-600 mb-2">
              Assign percentage shares to each staff member. Total must equal 100%.
            </p>
            {staff.map((s) => (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ flex: 1 }}>{s.name}</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={100}
                  step={1}
                  value={rolePercentages[s.id] ?? 0}
                  onChange={(e) =>
                    setRolePercentages((prev) => ({
                      ...prev,
                      [s.id]: parseFloat(e.target.value) || 0,
                    }))
                  }
                  style={{ minHeight: 44, width: 80 }}
                  data-testid={`pct-input-${s.id}`}
                />
                <span>%</span>
              </div>
            ))}
            {totalPct !== 100 && (
              <p style={{ color: '#ef4444', fontSize: 14 }} role="alert">
                Total: {totalPct}% (must equal 100%)
              </p>
            )}
          </div>
        )}

        {method === 'role_based' && (
          <div style={{ marginBottom: 12 }} data-testid="role-based-config">
            <p className="text-sm text-gray-600 mb-2">
              Assign percentage shares per role. Total must equal 100%.
            </p>
            {uniqueRoles.map((role) => (
              <div key={role} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ flex: 1 }}>{role}</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={100}
                  step={1}
                  value={rolePercentages[role] ?? 0}
                  onChange={(e) =>
                    setRolePercentages((prev) => ({
                      ...prev,
                      [role]: parseFloat(e.target.value) || 0,
                    }))
                  }
                  style={{ minHeight: 44, width: 80 }}
                  data-testid={`role-pct-input-${role}`}
                />
                <span>%</span>
              </div>
            ))}
          </div>
        )}

        <div style={{ marginBottom: 12 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="checkbox"
              checked={pooling}
              onChange={(e) => setPooling(e.target.checked)}
              style={{ minWidth: 44, minHeight: 44 }}
              data-testid="tip-pooling-toggle"
            />
            Enable {tipLabel} Pooling
          </label>
        </div>

        <button
          type="submit"
          style={{ minHeight: 44, minWidth: 44 }}
          aria-label="Save distribution rules"
          data-testid="save-distribution-rules"
        >
          Save Rules
        </button>
      </form>
    </div>
  )
}

/* ── Staff Tip Allocation Page (Req 15.3) ── */

function StaffAllocationSection({
  allocations,
  staff,
  rule,
  dateRange,
  setDateRange,
  onRefresh,
}: {
  allocations: TipAllocationRecord[]
  staff: StaffMember[]
  rule: DistributionRule | null
  dateRange: { start: string; end: string }
  setDateRange: React.Dispatch<React.SetStateAction<{ start: string; end: string }>>
  onRefresh: () => void
}) {
  const tipLabel = useTerm('tip', 'Tip')

  // Distribution preview using pure utility
  const previewTotal = allocations.reduce((s, a) => s + a.total_tips, 0)
  const staffShares = staff.map((s) => ({ id: s.id, share: s.share || 1 }))
  const preview = distributeTips(previewTotal, staffShares)

  return (
    <div data-testid="staff-allocation-section">
      <h3>Staff {tipLabel} Allocation</h3>

      {/* Date range filter */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <div>
          <label htmlFor="alloc-start">From</label>
          <input
            id="alloc-start"
            type="date"
            value={dateRange.start}
            onChange={(e) => setDateRange((d) => ({ ...d, start: e.target.value }))}
            style={{ minHeight: 44 }}
            data-testid="alloc-date-start"
          />
        </div>
        <div>
          <label htmlFor="alloc-end">To</label>
          <input
            id="alloc-end"
            type="date"
            value={dateRange.end}
            onChange={(e) => setDateRange((d) => ({ ...d, end: e.target.value }))}
            style={{ minHeight: 44 }}
            data-testid="alloc-date-end"
          />
        </div>
        <button
          onClick={onRefresh}
          style={{ minHeight: 44, minWidth: 44, alignSelf: 'flex-end' }}
          data-testid="alloc-refresh"
        >
          Refresh
        </button>
      </div>

      {/* Allocation table */}
      <table role="grid" aria-label="Staff tip allocations">
        <thead>
          <tr>
            <th>Staff Member</th>
            <th>Total Tips</th>
            <th>Tip Count</th>
            <th>Average</th>
          </tr>
        </thead>
        <tbody>
          {allocations.map((a) => (
            <tr key={a.staff_member_id} data-testid={`alloc-row-${a.staff_member_id}`}>
              <td>{a.staff_name}</td>
              <td>${(a.total_tips ?? 0).toFixed(2)}</td>
              <td>{a.tip_count}</td>
              <td>${(a.average_tip ?? 0).toFixed(2)}</td>
            </tr>
          ))}
          {allocations.length === 0 && (
            <tr><td colSpan={4}>No allocations for this period</td></tr>
          )}
        </tbody>
      </table>

      {/* Distribution preview */}
      {preview.length > 0 && (
        <div style={{ marginTop: 16 }} data-testid="distribution-preview">
          <h4>Distribution Preview ({rule?.method || 'equal_split'})</h4>
          <p className="text-sm text-gray-600 mb-2">
            Total pool: ${previewTotal.toFixed(2)}
          </p>
          <table role="grid" aria-label="Distribution preview">
            <thead>
              <tr><th>Staff</th><th>Allocated</th></tr>
            </thead>
            <tbody>
              {preview.map((p) => {
                const staffName = staff.find((s) => s.id === p.id)?.name || p.id
                return (
                  <tr key={p.id} data-testid={`preview-row-${p.id}`}>
                    <td>{staffName}</td>
                    <td>${(p.amount ?? 0).toFixed(2)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ── Tip Analytics Dashboard (Req 15.4) ── */

function TipAnalyticsSection({ analytics }: { analytics: TipAnalyticsData | null }) {
  const tipLabel = useTerm('tip', 'Tip')

  if (!analytics) {
    return <p>No analytics data available.</p>
  }

  return (
    <div data-testid="tip-analytics" aria-label="Tip analytics dashboard">
      <h3>{tipLabel} Analytics</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
        <div data-testid="analytics-total-collected">
          <strong>Total {tipLabel}s Collected</strong>
          <p>${(analytics.total_tips_collected ?? 0).toFixed(2)}</p>
        </div>
        <div data-testid="analytics-avg-pct">
          <strong>Average {tipLabel} %</strong>
          <p>{(analytics.average_tip_percentage ?? 0).toFixed(1)}%</p>
        </div>
      </div>

      {/* Tips by payment method */}
      {analytics.tips_by_payment_method.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h4>{tipLabel}s by Payment Method</h4>
          <table role="grid" aria-label="Tips by payment method">
            <thead><tr><th>Method</th><th>Total</th><th>Count</th></tr></thead>
            <tbody>
              {analytics.tips_by_payment_method.map((m) => (
                <tr key={m.method} data-testid={`method-row-${m.method}`}>
                  <td>{m.method}</td>
                  <td>${(m.total ?? 0).toFixed(2)}</td>
                  <td>{m.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Tips per staff */}
      {analytics.tips_per_staff.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h4>{tipLabel}s per Staff Member</h4>
          <table role="grid" aria-label="Tips per staff member">
            <thead><tr><th>Name</th><th>Total</th></tr></thead>
            <tbody>
              {analytics.tips_per_staff.map((s) => (
                <tr key={s.staff_id} data-testid={`staff-tip-row-${s.staff_id}`}>
                  <td>{s.name}</td>
                  <td>${(s.total ?? 0).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Daily trend */}
      {analytics.daily_totals.length > 0 && (
        <div style={{ marginTop: 16 }} data-testid="tip-trend">
          <h4>{tipLabel} Trend ({analytics.period})</h4>
          <table role="grid" aria-label="Tip trend data">
            <thead><tr><th>Date</th><th>Total</th></tr></thead>
            <tbody>
              {analytics.daily_totals.map((d) => (
                <tr key={d.date}>
                  <td>{d.date}</td>
                  <td>${(d.total ?? 0).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ── POS Transaction Tip Summary (Req 15.5) ── */

export function TipTransactionSummary({ tipInfo }: { tipInfo: TipSummaryInfo | null }) {
  const tipLabel = useTerm('tip', 'Tip')

  if (!tipInfo || tipInfo.tip_amount <= 0) return null

  return (
    <div data-testid="tip-transaction-summary" aria-label="Tip summary" style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0' }}>
        <span className="text-sm text-gray-600">{tipLabel}</span>
        <span className="text-sm font-medium" data-testid="tip-summary-amount">
          ${(tipInfo.tip_amount ?? 0).toFixed(2)}
        </span>
      </div>
      <div style={{ fontSize: 12, color: '#6b7280' }}>
        via {tipInfo.payment_method}
      </div>
      {tipInfo.staff_allocations.length > 0 && (
        <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>
          {tipInfo.staff_allocations.map((a) => (
            <span key={a.name} style={{ marginRight: 8 }}>
              {a.name}: ${(a.amount ?? 0).toFixed(2)}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Main Tip Management Page ── */

export function TipManagement() {
  const tipLabel = useTerm('tip', 'Tip')
  void useFlag('tipping')

  const [rule, setRule] = useState<DistributionRule | null>(null)
  const [staff, setStaff] = useState<StaffMember[]>([])
  const [allocations, setAllocations] = useState<TipAllocationRecord[]>([])
  const [analytics, setAnalytics] = useState<TipAnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [ruleError, setRuleError] = useState<string | null>(null)
  const [analyticsPeriod, setAnalyticsPeriod] = useState<'daily' | 'weekly' | 'monthly'>('daily')
  const [dateRange, setDateRange] = useState({
    start: new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10),
    end: new Date().toISOString().slice(0, 10),
  })
  const { addToast, toasts, dismissToast } = useToast()

  const fetchData = useCallback(async () => {
    try {
      setLoading(true)
      const [ruleRes, staffRes, allocRes, analyticsRes] = await Promise.all([
        apiClient.get('/api/v2/tips/distribution-rules').catch(() => ({ data: null })),
        apiClient.get('/api/v2/staff'),
        apiClient.get('/api/v2/tips/allocations', {
          params: { start_date: dateRange.start, end_date: dateRange.end },
        }).catch(() => ({ data: [] })),
        apiClient.get('/api/v2/tips/analytics', {
          params: { period: analyticsPeriod },
        }).catch(() => ({ data: null })),
      ])
      if (ruleRes.data) setRule(ruleRes.data)
      setStaff(
        (staffRes.data || []).map((s: any) => ({
          id: s.id,
          name: s.name || `${s.first_name || ''} ${s.last_name || ''}`.trim(),
          role: s.role || '',
          share: s.tip_share || 1,
        })),
      )
      setAllocations(allocRes.data || [])
      if (analyticsRes.data && typeof analyticsRes.data === 'object') {
        setAnalytics(analyticsRes.data)
      }
    } catch {
      setError('Failed to load tip management data')
    } finally {
      setLoading(false)
    }
  }, [dateRange.start, dateRange.end, analyticsPeriod])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleSaveRules = async (
    method: string,
    pooling: boolean,
    rolePercentages: Record<string, number>,
  ) => {
    setRuleError(null)
    try {
      const res = await apiClient.put('/api/v2/tips/distribution-rules', {
        method,
        tip_pooling: pooling,
        role_percentages: rolePercentages,
      })
      setRule(res.data)
      addToast('success', 'Distribution rules saved')
    } catch (err: any) {
      setRuleError(err?.response?.data?.detail || 'Failed to save rules')
    }
  }

  const handleRefreshAllocations = async () => {
    try {
      const res = await apiClient.get('/api/v2/tips/allocations', {
        params: { start_date: dateRange.start, end_date: dateRange.end },
      })
      setAllocations(res.data || [])
    } catch {
      setError('Failed to refresh allocations')
    }
  }

  if (loading) {
    return <Spinner label="Loading tip management" aria-label="Loading tip management" />
  }

  return (
    <section aria-label="Tip Management" data-testid="tip-management-page">
      <h2>{tipLabel} Management</h2>
      {error && (
        <AlertBanner variant="error" onDismiss={() => setError(null)}>
          {error}
        </AlertBanner>
      )}

      {/* Analytics period selector */}
      <div style={{ marginBottom: 12 }}>
        <label htmlFor="analytics-period">Analytics Period: </label>
        <select
          id="analytics-period"
          value={analyticsPeriod}
          onChange={(e) => setAnalyticsPeriod(e.target.value as 'daily' | 'weekly' | 'monthly')}
          style={{ minHeight: 44 }}
          data-testid="analytics-period-select"
        >
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
        </select>
      </div>

      <Tabs
        tabs={[
          {
            id: 'rules',
            label: 'Distribution Rules',
            content: (
              <DistributionRulesSection
                rule={rule}
                staff={staff}
                onSave={handleSaveRules}
                error={ruleError}
              />
            ),
          },
          {
            id: 'allocations',
            label: 'Staff Allocations',
            content: (
              <StaffAllocationSection
                allocations={allocations}
                staff={staff}
                rule={rule}
                dateRange={dateRange}
                setDateRange={setDateRange}
                onRefresh={handleRefreshAllocations}
              />
            ),
          },
          {
            id: 'analytics',
            label: 'Analytics',
            content: <TipAnalyticsSection analytics={analytics} />,
          },
        ]}
      />

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </section>
  )
}
