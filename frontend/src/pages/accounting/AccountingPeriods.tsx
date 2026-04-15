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
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Accounting Periods</h1>
          <p className="text-sm text-gray-500 mt-1">{(total ?? 0).toLocaleString()} period{total !== 1 ? 's' : ''}</p>
        </div>
        <Button onClick={openCreate}>+ New Period</Button>
      </div>

      {/* Table */}
      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading periods" /></div>
      ) : (periods ?? []).length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          No accounting periods found.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Period</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Start Date</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">End Date</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Closed At</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {(periods ?? []).map(period => (
                <tr key={period.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{period.period_name}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                    {new Date(period.start_date).toLocaleDateString('en-NZ')}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                    {new Date(period.end_date).toLocaleDateString('en-NZ')}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    {period.is_closed ? <Badge variant="neutral">Closed</Badge> : <Badge variant="success">Open</Badge>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                    {period.closed_at ? new Date(period.closed_at).toLocaleDateString('en-NZ') : '—'}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                    {!period.is_closed && (
                      <Button
                        size="sm"
                        variant="secondary"
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
          {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Period Name</label>
            <input
              type="text"
              value={formName}
              onChange={e => setFormName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="e.g. April 2026"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Start Date</label>
              <input
                type="date"
                value={formStart}
                onChange={e => setFormStart(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">End Date</label>
              <input
                type="date"
                value={formEnd}
                onChange={e => setFormEnd(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={saving || !formName || !formStart || !formEnd}>
              {saving ? 'Creating…' : 'Create Period'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
