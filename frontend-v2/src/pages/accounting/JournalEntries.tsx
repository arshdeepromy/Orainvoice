import { useState, useEffect, useCallback } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Modal, Spinner, Badge } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

interface JournalLine {
  id: string
  journal_entry_id: string
  org_id: string
  account_id: string
  debit: number
  credit: number
  description: string | null
}

interface JournalEntry {
  id: string
  org_id: string
  entry_number: string
  entry_date: string
  description: string
  reference: string | null
  source_type: string
  source_id: string | null
  period_id: string | null
  is_posted: boolean
  created_by: string
  created_at: string
  updated_at: string
  lines: JournalLine[]
}

interface Account {
  id: string
  code: string
  name: string
  account_type: string
  is_active: boolean
}

interface FormLine {
  account_id: string
  debit: string
  credit: string
  description: string
}

const emptyLine = (): FormLine => ({ account_id: '', debit: '', credit: '', description: '' })

const TH =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_RIGHT =
  'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

const FILTER =
  'h-[42px] rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'
const INPUT =
  'w-full rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'
const LABEL = 'mb-1 block text-[12.5px] font-medium text-text'
const LINE_INPUT =
  'rounded-ctl border border-border bg-card px-2 py-1.5 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'

export default function JournalEntries() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const navigate = useNavigate()
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // Filters
  const [filterSource, setFilterSource] = useState('')
  const [filterDateFrom, setFilterDateFrom] = useState('')
  const [filterDateTo, setFilterDateTo] = useState('')

  // Form state
  const [formDate, setFormDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [formDescription, setFormDescription] = useState('')
  const [formReference, setFormReference] = useState('')
  const [formLines, setFormLines] = useState<FormLine[]>([emptyLine(), emptyLine()])

  const fetchEntries = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (filterSource) params.source_type = filterSource
      if (filterDateFrom) params.date_from = filterDateFrom
      if (filterDateTo) params.date_to = filterDateTo
      const res = await apiClient.get<{ items: JournalEntry[]; total: number }>('/ledger/journal-entries', { params, signal })
      setEntries(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setEntries([])
        setTotal(0)
      }
    } finally {
      setLoading(false)
    }
  }, [filterSource, filterDateFrom, filterDateTo])

  const fetchAccounts = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await apiClient.get<{ items: Account[]; total: number }>('/ledger/accounts', { params: { is_active: 'true' }, signal })
      setAccounts(res.data?.items ?? [])
    } catch {
      setAccounts([])
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchEntries(controller.signal)
    return () => controller.abort()
  }, [fetchEntries])

  useEffect(() => {
    const controller = new AbortController()
    fetchAccounts(controller.signal)
    return () => controller.abort()
  }, [fetchAccounts])

  const openCreate = () => {
    setFormDate(new Date().toISOString().slice(0, 10))
    setFormDescription('')
    setFormReference('')
    setFormLines([emptyLine(), emptyLine()])
    setError('')
    setModalOpen(true)
  }

  const updateLine = (idx: number, field: keyof FormLine, value: string) => {
    setFormLines(prev => prev.map((l, i) => i === idx ? { ...l, [field]: value } : l))
  }

  const addLine = () => setFormLines(prev => [...prev, emptyLine()])

  const removeLine = (idx: number) => {
    if (formLines.length <= 2) return
    setFormLines(prev => prev.filter((_, i) => i !== idx))
  }

  const totalDebits = formLines.reduce((sum, l) => sum + (parseFloat(l.debit) || 0), 0)
  const totalCredits = formLines.reduce((sum, l) => sum + (parseFloat(l.credit) || 0), 0)
  const isBalanced = Math.abs(totalDebits - totalCredits) < 0.01 && totalDebits > 0

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const lines = formLines
        .filter(l => l.account_id && (parseFloat(l.debit) > 0 || parseFloat(l.credit) > 0))
        .map(l => ({
          account_id: l.account_id,
          debit: parseFloat(l.debit) || 0,
          credit: parseFloat(l.credit) || 0,
          description: l.description || undefined,
        }))
      await apiClient.post('/ledger/journal-entries', {
        entry_date: formDate,
        description: formDescription,
        reference: formReference || undefined,
        source_type: 'manual',
        lines,
      })
      setModalOpen(false)
      fetchEntries()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to create journal entry')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text">Journal Entries</h1>
          <p className="mt-1 text-sm text-muted">{(total ?? 0).toLocaleString()} entr{total !== 1 ? 'ies' : 'y'}</p>
        </div>
        <Button onClick={openCreate}>+ New Entry</Button>
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap gap-3">
        <select
          value={filterSource}
          onChange={e => setFilterSource(e.target.value)}
          className={FILTER}
        >
          <option value="">All Sources</option>
          <option value="manual">Manual</option>
          <option value="invoice">Invoice</option>
          <option value="payment">Payment</option>
          <option value="expense">Expense</option>
          <option value="credit_note">Credit Note</option>
        </select>
        <input
          type="date"
          value={filterDateFrom}
          onChange={e => setFilterDateFrom(e.target.value)}
          className={FILTER}
          placeholder="From"
        />
        <input
          type="date"
          value={filterDateTo}
          onChange={e => setFilterDateTo(e.target.value)}
          className={FILTER}
          placeholder="To"
        />
      </div>

      {/* Table */}
      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading journal entries" /></div>
      ) : (entries ?? []).length === 0 ? (
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted">
          No journal entries found.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full">
            <thead>
              <tr>
                <th className={TH}>Entry #</th>
                <th className={TH}>Date</th>
                <th className={TH}>Description</th>
                <th className={TH}>Source</th>
                <th className={TH}>Status</th>
                <th className={TH_RIGHT}>Lines</th>
              </tr>
            </thead>
            <tbody>
              {(entries ?? []).map(entry => (
                <tr
                  key={entry.id}
                  className="cursor-pointer border-b border-border last:border-b-0 hover:bg-canvas"
                  onClick={() => navigate(`/accounting/journal-entries/${entry.id}`)}
                >
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-accent">{entry.entry_number}</td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-text">
                    {new Date(entry.entry_date).toLocaleDateString('en-NZ')}
                  </td>
                  <td className="max-w-xs truncate px-4 py-3 text-sm text-text">{entry.description}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <Badge variant="neutral">{entry.source_type}</Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    {entry.is_posted ? <Badge variant="success">Posted</Badge> : <Badge variant="warn">Draft</Badge>}
                  </td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-right text-sm text-muted">
                    {(entry.lines ?? []).length}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="New Manual Journal Entry" className="max-w-2xl">
        <div className="space-y-4">
          {error && <div className="rounded-ctl bg-danger-soft p-3 text-sm text-danger">{error}</div>}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={LABEL}>Date</label>
              <input
                type="date"
                value={formDate}
                onChange={e => setFormDate(e.target.value)}
                className={INPUT}
              />
            </div>
            <div>
              <label className={LABEL}>Reference</label>
              <input
                type="text"
                value={formReference}
                onChange={e => setFormReference(e.target.value)}
                className={INPUT}
                placeholder="Optional reference"
              />
            </div>
          </div>
          <div>
            <label className={LABEL}>Description</label>
            <input
              type="text"
              value={formDescription}
              onChange={e => setFormDescription(e.target.value)}
              className={INPUT}
              placeholder="Journal entry description"
            />
          </div>

          {/* Lines */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="block text-[12.5px] font-medium text-text">Lines</label>
              <button onClick={addLine} className="text-xs text-accent hover:underline">+ Add Line</button>
            </div>
            <div className="space-y-2">
              {formLines.map((line, idx) => (
                <div key={idx} className="grid grid-cols-12 items-center gap-2">
                  <select
                    value={line.account_id}
                    onChange={e => updateLine(idx, 'account_id', e.target.value)}
                    className={`col-span-4 ${LINE_INPUT}`}
                  >
                    <option value="">Select account</option>
                    {(accounts ?? []).map(a => (
                      <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
                    ))}
                  </select>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={line.debit}
                    onChange={e => updateLine(idx, 'debit', e.target.value)}
                    placeholder="Debit"
                    className={`col-span-2 text-right ${LINE_INPUT}`}
                  />
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={line.credit}
                    onChange={e => updateLine(idx, 'credit', e.target.value)}
                    placeholder="Credit"
                    className={`col-span-2 text-right ${LINE_INPUT}`}
                  />
                  <input
                    type="text"
                    value={line.description}
                    onChange={e => updateLine(idx, 'description', e.target.value)}
                    placeholder="Note"
                    className={`col-span-3 ${LINE_INPUT}`}
                  />
                  <button
                    onClick={() => removeLine(idx)}
                    disabled={formLines.length <= 2}
                    className="col-span-1 text-sm text-danger hover:brightness-90 disabled:text-muted-2"
                    aria-label="Remove line"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
            <div className="mt-2 flex justify-between text-sm">
              <span className={isBalanced ? 'text-ok' : 'text-danger'}>
                Debits: ${totalDebits.toFixed(2)} | Credits: ${totalCredits.toFixed(2)}
                {isBalanced ? ' ✓ Balanced' : ' ✗ Unbalanced'}
              </span>
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving || !formDescription || !isBalanced}>
              {saving ? 'Creating…' : 'Create Entry'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
