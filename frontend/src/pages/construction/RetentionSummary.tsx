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
      <section aria-label="Retention summary">
        <h2>{retentionLabel} Summary</h2>
        <p>Enter a {projectLabel.toLowerCase()} ID to view {retentionLabel.toLowerCase()} details.</p>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <label htmlFor="retention-project-id">{projectLabel} ID</label>
          <input
            id="retention-project-id"
            type="text"
            value={projectInput}
            onChange={(e) => setProjectInput(e.target.value)}
            placeholder={`Enter ${projectLabel.toLowerCase()} ID`}
            style={{ minHeight: 44 }}
          />
          <button
            onClick={() => { if (projectInput.trim()) setProjectId(projectInput.trim()) }}
            style={{ minWidth: 44, minHeight: 44 }}
          >
            Load
          </button>
        </div>
      </section>
    )
  }

  if (loading) {
    return <div role="status" aria-label="Loading retention summary">Loading retention…</div>
  }

  if (!summary) {
    return <p>No {retentionLabel.toLowerCase()} data available.</p>
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
    `$${v.toLocaleString(undefined, { minimumFractionDigits: 2 })}`

  return (
    <section aria-label="Retention summary">
      <h2>{retentionLabel} Summary</h2>

      {projectInfo && (
        <p data-testid="retention-project-name">
          {projectLabel}: <strong>{projectInfo.name}</strong>
        </p>
      )}

      <div role="table" aria-label="Retention breakdown">
        <div role="rowgroup">
          <div role="row">
            <span role="rowheader">Total {retentionLabel} Withheld</span>
            <span role="cell" data-testid="total-withheld">{fmt(withheld)}</span>
          </div>
          <div role="row">
            <span role="rowheader">Total Released</span>
            <span role="cell" data-testid="total-released">{fmt(released)}</span>
          </div>
          <div role="row">
            <span role="rowheader">{retentionLabel} Balance</span>
            <span role="cell" data-testid="retention-balance" style={{ fontWeight: 'bold' }}>
              {fmt(balance)}
            </span>
          </div>
          {contractValue > 0 && (
            <div role="row">
              <span role="rowheader">{retentionLabel} Percentage</span>
              <span role="cell" data-testid="retention-percentage">
                {retPct.toFixed(2)}%
              </span>
            </div>
          )}
        </div>
      </div>

      {balance > 0 && (
        <button
          onClick={() => setShowForm(true)}
          aria-label="Release retention"
          style={{ marginTop: 8, minWidth: 44, minHeight: 44 }}
        >
          Release {retentionLabel}
        </button>
      )}

      {showForm && (
        <form onSubmit={handleRelease} aria-label="Release retention form" style={{ marginTop: 16 }}>
          {error && <div role="alert">{error}</div>}
          {validationError && !error && <div role="alert">{validationError}</div>}
          <div>
            <label htmlFor="release-amount">Amount</label>
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
              style={{ minHeight: 44 }}
            />
          </div>
          <div>
            <label htmlFor="release-date">Release Date</label>
            <input
              id="release-date"
              type="date"
              value={releaseDate}
              onChange={(e) => setReleaseDate(e.target.value)}
              required
              style={{ minHeight: 44 }}
            />
          </div>
          <div>
            <label htmlFor="release-payment-ref">Payment Reference</label>
            <input
              id="release-payment-ref"
              type="text"
              value={paymentRef}
              onChange={(e) => setPaymentRef(e.target.value)}
              placeholder="Optional payment reference"
              style={{ minHeight: 44 }}
            />
          </div>
          <div>
            <label htmlFor="release-notes">Notes</label>
            <textarea
              id="release-notes"
              value={releaseNotes}
              onChange={(e) => setReleaseNotes(e.target.value)}
              style={{ minHeight: 44 }}
            />
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button
              type="submit"
              disabled={submitting || !!validationError}
              aria-label="Confirm release"
              style={{ minWidth: 44, minHeight: 44 }}
            >
              {submitting ? 'Releasing…' : 'Confirm Release'}
            </button>
            <button
              type="button"
              onClick={() => { setShowForm(false); setValidationError(null); setError(null) }}
              style={{ minWidth: 44, minHeight: 44 }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {summary.releases.length > 0 && (
        <>
          <h3>Release History</h3>
          <table role="grid" aria-label="Retention releases list">
            <thead>
              <tr>
                <th>Date</th>
                <th>Amount</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {summary.releases.map((r) => (
                <tr key={r.id}>
                  <td>{new Date(r.release_date).toLocaleDateString()}</td>
                  <td>{fmt(Number(r.amount))}</td>
                  <td>{r.notes || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}
