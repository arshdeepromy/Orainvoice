/**
 * Retention summary view for a project, showing total withheld, released,
 * balance, and a list of individual releases with a release form.
 *
 * Validates: Requirement — Retention Module, Task 37.8
 */

import React, { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

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

interface Props {
  projectId: string
}

export default function RetentionSummary({ projectId }: Props) {
  const [summary, setSummary] = useState<RetentionSummaryData | null>(null)
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [releaseAmount, setReleaseAmount] = useState('')
  const [releaseDate, setReleaseDate] = useState('')
  const [releaseNotes, setReleaseNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchSummary = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get(`/api/v2/retentions/${projectId}/summary`)
      setSummary(res.data)
    } catch {
      setSummary(null)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { fetchSummary() }, [fetchSummary])

  const handleRelease = async (e: React.FormEvent) => {
    e.preventDefault()
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
      fetchSummary()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to release retention')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <div role="status" aria-label="Loading retention summary">Loading retention…</div>
  }

  if (!summary) {
    return <p>No retention data available.</p>
  }

  const withheld = Number(summary.total_retention_withheld)
  const released = Number(summary.total_retention_released)
  const balance = Number(summary.retention_balance)

  return (
    <section aria-label="Retention summary">
      <h2>Retention Summary</h2>

      <div role="table" aria-label="Retention breakdown">
        <div role="rowgroup">
          <div role="row">
            <span role="rowheader">Total Retention Withheld</span>
            <span role="cell">${withheld.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
          </div>
          <div role="row">
            <span role="rowheader">Total Released</span>
            <span role="cell">${released.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
          </div>
          <div role="row">
            <span role="rowheader">Retention Balance</span>
            <span role="cell" style={{ fontWeight: 'bold' }}>
              ${balance.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </span>
          </div>
        </div>
      </div>

      {balance > 0 && (
        <button
          onClick={() => setShowForm(true)}
          aria-label="Release retention"
          style={{ marginTop: 8 }}
        >
          Release Retention
        </button>
      )}

      {showForm && (
        <form onSubmit={handleRelease} aria-label="Release retention form" style={{ marginTop: 16 }}>
          {error && <div role="alert">{error}</div>}
          <div>
            <label htmlFor="release-amount">Amount</label>
            <input
              id="release-amount"
              type="number"
              step="0.01"
              min="0.01"
              max={balance}
              value={releaseAmount}
              onChange={(e) => setReleaseAmount(e.target.value)}
              required
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
            />
          </div>
          <div>
            <label htmlFor="release-notes">Notes</label>
            <textarea
              id="release-notes"
              value={releaseNotes}
              onChange={(e) => setReleaseNotes(e.target.value)}
            />
          </div>
          <button type="submit" disabled={submitting} aria-label="Confirm release">
            {submitting ? 'Releasing…' : 'Confirm Release'}
          </button>
          <button type="button" onClick={() => setShowForm(false)}>Cancel</button>
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
                  <td>${Number(r.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
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
