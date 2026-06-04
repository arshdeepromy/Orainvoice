import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Modal, Spinner, Badge } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

interface AccountingPeriod {
  id: string
  org_id: string
  period_name: string
  start_date: string
  end_date: string
  is_closed: boolean
  closed_by: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
}

const TH =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_RIGHT =
  'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

const INPUT =
  'h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'
const LABEL = 'mb-1 block text-[12.5px] font-medium text-text'

export default function AccountingPeriods() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const [periods, setPeriods] = useState<AccountingPeriod[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [closing, setClosing] = useState<string | null>(null)
  const [error, setError] = useState('')

  // Form state
  const [formName, setFormName] = useState('')
  const [formStart, setFormStart] = useState('')
  const [formEnd, setFormEnd] = useState('')

  const fetchPeriods = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const res = await apiClient.get<{ items: AccountingPeriod[]; total: number }>('/ledger/periods', { signal })
      setPeriods(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setPeriods([])
        setTotal(0)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchPeriods(controller.signal)
    return () => controller.abort()
  }, [fetchPeriods])

  const openCreate = () => {
    setFormName('')
    setFormStart('')
    setFormEnd('')
    setError('')
    setModalOpen(true)
  }

  const handleCreate = async () => {
    setSaving(true)
    setError('')
    try {
      await apiClient.post('/ledger/periods', {
        period_name: formName,
        start_date: formStart,
        end_date: formEnd,
      })
      setModalOpen(false)
      fetchPeriods()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to create period')
    } finally {
      setSaving(false)
    }
  }

  const handleClose = async (period: AccountingPeriod) => {
    if (!confirm(`Close period "${period.period_name}"? This cannot be undone.`)) return
    setClosing(period.id)
    try {
      await apiClient.post(`/ledger/periods/${period.id}/close`)
      fetchPeriods()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(msg ?? 'Failed to close period')
    } finally {
      setClosing(null)
    }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text">Accounting Periods</h1>
          <p className="mt-1 text-sm text-muted">{(total ?? 0).toLocaleString()} period{total !== 1 ? 's' : ''}</p>
        </div>
        <Button onClick={openCreate}>+ New Period</Button>
      </div>

      {/* Table */}
      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading periods" /></div>
      ) : (periods ?? []).length === 0 ? (
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted">
          No accounting periods found.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full">
            <thead>
              <tr>
                <th className={TH}>Period</th>
                <th className={TH}>Start Date</th>
                <th className={TH}>End Date</th>
                <th className={TH}>Status</th>
                <th className={TH}>Closed At</th>
                <th className={TH_RIGHT}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(periods ?? []).map(period => (
                <tr key={period.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="px-4 py-3 text-sm font-medium text-text">{period.period_name}</td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-text">
                    {new Date(period.start_date).toLocaleDateString('en-NZ')}
                  </td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-text">
                    {new Date(period.end_date).toLocaleDateString('en-NZ')}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    {period.is_closed ? <Badge variant="neutral">Closed</Badge> : <Badge variant="success">Open</Badge>}
                  </td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">
                    {period.closed_at ? new Date(period.closed_at).toLocaleDateString('en-NZ') : '—'}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right text-sm">
                    {!period.is_closed && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleClose(period)}
                        disabled={closing === period.id}
                      >
                        {closing === period.id ? 'Closing…' : 'Close Period'}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="New Accounting Period">
        <div className="space-y-4">
          {error && <div className="rounded-ctl bg-danger-soft p-3 text-sm text-danger">{error}</div>}
          <div>
            <label className={LABEL}>Period Name</label>
            <input
              type="text"
              value={formName}
              onChange={e => setFormName(e.target.value)}
              className={INPUT}
              placeholder="e.g. April 2026"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={LABEL}>Start Date</label>
              <input
                type="date"
                value={formStart}
                onChange={e => setFormStart(e.target.value)}
                className={INPUT}
              />
            </div>
            <div>
              <label className={LABEL}>End Date</label>
              <input
                type="date"
                value={formEnd}
                onChange={e => setFormEnd(e.target.value)}
                className={INPUT}
              />
            </div>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={saving || !formName || !formStart || !formEnd}>
              {saving ? 'Creating…' : 'Create Period'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
