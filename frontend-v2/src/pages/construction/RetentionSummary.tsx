/**
 * Retention summary view for a project, showing total withheld, released,
 * outstanding balance, retention percentage, and a release workflow.
 *
 * Integrates TerminologyContext, FeatureFlagContext, and useModuleGuard.
 * Uses pure utility functions from retentionCalcs.ts for calculations.
 *
 * Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
 */

import React, { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { useTerm } from '@/contexts/TerminologyContext'
import { useFlag } from '@/contexts/FeatureFlagContext'
import {
  calculateOutstandingRetention,
  validateReleaseAmount,
  calculateRetentionPercentage,
} from '@/utils/retentionCalcs'
import { Button } from '@/components/ui'

interface RetentionRelease {
  id: string
  project_id: string
  amount: string
  release_date: string
  payment_id: string | null
  notes: string | null
  created_at: string
}

interface RetentionSummaryData {
  project_id: string
  total_retention_withheld: string
  total_retention_released: string
  retention_balance: string
  releases: RetentionRelease[]
}

interface ProjectInfo {
  id: string
  name: string
  contract_value: string | null
  revised_contract_value: string | null
  retention_percentage: string
}

interface Props {
  projectId?: string
}

const inputClass =
  'min-h-[44px] rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent'
const labelClass = 'mb-1 block text-sm font-medium text-text'

export default function RetentionSummary({ projectId: initialProjectId }: Props) {
  const retentionLabel = useTerm('retention', 'Retention')
  const projectLabel = useTerm('project', 'Project')
  // Feature flag integration — primary gating via FlagGatedRoute at route level
  useFlag('construction_retentions')

  const [projectId, setProjectId] = useState(initialProjectId ?? '')
  const [summary, setSummary] = useState<RetentionSummaryData | null>(null)
  const [projectInfo, setProjectInfo] = useState<ProjectInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [releaseAmount, setReleaseAmount] = useState('')
  const [releaseDate, setReleaseDate] = useState('')
  const [releaseNotes, setReleaseNotes] = useState('')
  const [paymentRef, setPaymentRef] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [projectInput, setProjectInput] = useState('')

  const fetchSummary = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const [summaryRes, projectRes] = await Promise.all([
        apiClient.get(`/api/v2/retentions/${projectId}/summary`),
        apiClient.get(`/api/v2/projects/${projectId}`).catch(() => null),
      ])
      setSummary(summaryRes.data)
      if (projectRes) setProjectInfo(projectRes.data)
    } catch {
      setSummary(null)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { fetchSummary() }, [fetchSummary])

  // Real-time validation of release amount
  useEffect(() => {
    if (!summary || !releaseAmount) {
      setValidationError(null)
      return
    }
    const outstanding = calculateOutstandingRetention(
      Number(summary.total_retention_withheld),
      Number(summary.total_retention_released),
    )
    const result = validateReleaseAmount(Number(releaseAmount), outstanding)
    setValidationError(result.valid ? null : result.error ?? null)
  }, [releaseAmount, summary])

  const handleRelease = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!summary) return

    const outstanding = calculateOutstandingRetention(
      Number(summary.total_retention_withheld),
      Number(summary.total_retention_released),
    )
    const result = validateReleaseAmount(Number(releaseAmount), outstanding)
    if (!result.valid) {
      setError(result.error ?? 'Invalid release amount')
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      await apiClient.post(`/api/v2/retentions/${projectId}/release`, {
        amount: Number(releaseAmount),
        release_date: releaseDate,
        notes: releaseNotes || null,
      })
      setShowForm(false)
      setReleaseAmount('')
      setReleaseDate('')
      setReleaseNotes('')
      setPaymentRef('')
      setValidationError(null)
      fetchSummary()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to release retention')
    } finally {
      setSubmitting(false)
    }
  }

  if (!projectId) {
    return (
      <section aria-label="Retention summary" className="space-y-3 px-4 py-6 sm:px-6 lg:px-8">
        <h2 className="text-xl font-semibold text-text">{retentionLabel} Summary</h2>
        <p className="text-sm text-muted">Enter a {projectLabel.toLowerCase()} ID to view {retentionLabel.toLowerCase()} details.</p>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label htmlFor="retention-project-id" className={labelClass}>{projectLabel} ID</label>
            <input
              id="retention-project-id"
              type="text"
              value={projectInput}
              onChange={(e) => setProjectInput(e.target.value)}
              placeholder={`Enter ${projectLabel.toLowerCase()} ID`}
              className={inputClass}
            />
          </div>
          <Button
            onClick={() => { if (projectInput.trim()) setProjectId(projectInput.trim()) }}
          >
            Load
          </Button>
        </div>
      </section>
    )
  }

  if (loading) {
    return <div role="status" aria-label="Loading retention summary" className="py-12 text-center text-sm text-muted">Loading retention…</div>
  }

  if (!summary) {
    return <p className="px-4 py-6 text-sm text-muted">No {retentionLabel.toLowerCase()} data available.</p>
  }

  const withheld = Number(summary.total_retention_withheld)
  const released = Number(summary.total_retention_released)
  const balance = calculateOutstandingRetention(withheld, released)
  const contractValue = projectInfo?.revised_contract_value
    ? Number(projectInfo.revised_contract_value)
    : projectInfo?.contract_value
      ? Number(projectInfo.contract_value)
      : 0
  const retPct = calculateRetentionPercentage(withheld, contractValue)

  const fmt = (v: number) =>
    `${v.toLocaleString(undefined, { minimumFractionDigits: 2 })}`

  return (
    <section aria-label="Retention summary" className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <h2 className="text-xl font-semibold text-text">{retentionLabel} Summary</h2>

      {projectInfo && (
        <p data-testid="retention-project-name" className="text-sm text-muted">
          {projectLabel}: <strong className="text-text">{projectInfo.name}</strong>
        </p>
      )}

      <div role="table" aria-label="Retention breakdown" className="overflow-hidden rounded-card border border-border bg-card shadow-card">
        <div role="rowgroup">
          <div role="row" className="flex items-center justify-between border-b border-border px-4 py-3">
            <span role="rowheader" className="text-sm text-muted">Total {retentionLabel} Withheld</span>
            <span role="cell" data-testid="total-withheld" className="mono text-sm text-text">{fmt(withheld)}</span>
          </div>
          <div role="row" className="flex items-center justify-between border-b border-border px-4 py-3">
            <span role="rowheader" className="text-sm text-muted">Total Released</span>
            <span role="cell" data-testid="total-released" className="mono text-sm text-text">{fmt(released)}</span>
          </div>
          <div role="row" className="flex items-center justify-between border-b border-border px-4 py-3 last:border-b-0">
            <span role="rowheader" className="text-sm text-muted">{retentionLabel} Balance</span>
            <span role="cell" data-testid="retention-balance" className="mono text-sm font-bold text-text">
              {fmt(balance)}
            </span>
          </div>
          {contractValue > 0 && (
            <div role="row" className="flex items-center justify-between px-4 py-3">
              <span role="rowheader" className="text-sm text-muted">{retentionLabel} Percentage</span>
              <span role="cell" data-testid="retention-percentage" className="mono text-sm text-text">
                {retPct.toFixed(2)}%
              </span>
            </div>
          )}
        </div>
      </div>

      {balance > 0 && (
        <Button
          onClick={() => setShowForm(true)}
          aria-label="Release retention"
        >
          Release {retentionLabel}
        </Button>
      )}

      {showForm && (
        <form onSubmit={handleRelease} aria-label="Release retention form" className="space-y-3 rounded-card border border-border bg-card p-4 shadow-card">
          {error && <div role="alert" className="text-sm text-danger">{error}</div>}
          {validationError && !error && <div role="alert" className="text-sm text-danger">{validationError}</div>}
          <div>
            <label htmlFor="release-amount" className={labelClass}>Amount</label>
            <input
              id="release-amount"
              type="number"
              step="0.01"
              min="0.01"
              max={balance}
              inputMode="numeric"
              value={releaseAmount}
              onChange={(e) => setReleaseAmount(e.target.value)}
              required
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="release-date" className={labelClass}>Release Date</label>
            <input
              id="release-date"
              type="date"
              value={releaseDate}
              onChange={(e) => setReleaseDate(e.target.value)}
              required
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="release-payment-ref" className={labelClass}>Payment Reference</label>
            <input
              id="release-payment-ref"
              type="text"
              value={paymentRef}
              onChange={(e) => setPaymentRef(e.target.value)}
              placeholder="Optional payment reference"
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="release-notes" className={labelClass}>Notes</label>
            <textarea
              id="release-notes"
              value={releaseNotes}
              onChange={(e) => setReleaseNotes(e.target.value)}
              className={`${inputClass} w-full`}
            />
          </div>
          <div className="flex gap-2">
            <Button
              type="submit"
              disabled={submitting || !!validationError}
              aria-label="Confirm release"
            >
              {submitting ? 'Releasing…' : 'Confirm Release'}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => { setShowForm(false); setValidationError(null); setError(null) }}
            >
              Cancel
            </Button>
          </div>
        </form>
      )}

      {summary.releases.length > 0 && (
        <>
          <h3 className="text-base font-semibold text-text">Release History</h3>
          <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
            <table role="grid" aria-label="Retention releases list" className="w-full text-sm">
              <thead>
                <tr>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Date</th>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Amount</th>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Notes</th>
                </tr>
              </thead>
              <tbody>
                {(summary.releases ?? []).map((r) => (
                  <tr key={r.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="mono px-4 py-3 text-text">{new Date(r.release_date).toLocaleDateString()}</td>
                    <td className="mono px-4 py-3 text-text">{fmt(Number(r.amount))}</td>
                    <td className="px-4 py-3 text-text">{r.notes || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
