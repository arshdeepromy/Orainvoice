import { useState, useEffect } from 'react'
import { Navigate, useParams, useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Spinner, Badge } from '@/components/ui'
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
}

const TH =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_RIGHT =
  'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

export default function JournalEntryDetail() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [entry, setEntry] = useState<JournalEntry | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const fetchData = async () => {
      setLoading(true)
      try {
        const [entryRes, accountsRes] = await Promise.all([
          apiClient.get<JournalEntry>(`/ledger/journal-entries/${id}`, { signal: controller.signal }),
          apiClient.get<{ items: Account[]; total: number }>('/ledger/accounts', { signal: controller.signal }),
        ])
        setEntry(entryRes.data ?? null)
        setAccounts(accountsRes.data?.items ?? [])
      } catch (err: unknown) {
        if (!(err instanceof Error && err.name === 'CanceledError')) {
          setError('Failed to load journal entry')
        }
      } finally {
        setLoading(false)
      }
    }
    fetchData()
    return () => controller.abort()
  }, [id])

  const accountName = (accountId: string) => {
    const acct = (accounts ?? []).find(a => a.id === accountId)
    return acct ? `${acct.code} — ${acct.name}` : accountId
  }

  const handlePost = async () => {
    if (!entry) return
    setPosting(true)
    setError('')
    try {
      const res = await apiClient.post<JournalEntry>(`/ledger/journal-entries/${entry.id}/post`)
      setEntry(res.data ?? null)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to post journal entry')
    } finally {
      setPosting(false)
    }
  }

  if (loading) {
    return (
      <div className="px-4 py-6 sm:px-6 lg:px-8">
        <div className="py-8 text-center"><Spinner label="Loading journal entry" /></div>
      </div>
    )
  }

  if (!entry) {
    return (
      <div className="px-4 py-6 sm:px-6 lg:px-8">
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted">
          {error || 'Journal entry not found.'}
        </div>
        <div className="mt-4">
          <Button variant="ghost" onClick={() => navigate('/accounting/journal-entries')}>← Back</Button>
        </div>
      </div>
    )
  }

  const lines = entry.lines ?? []
  const totalDebits = lines.reduce((sum, l) => sum + (Number(l.debit) ?? 0), 0)
  const totalCredits = lines.reduce((sum, l) => sum + (Number(l.credit) ?? 0), 0)

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-4">
        <button onClick={() => navigate('/accounting/journal-entries')} className="text-sm text-accent hover:underline">
          ← Back to Journal Entries
        </button>
      </div>

      {error && <div className="mb-4 rounded-ctl bg-danger-soft p-3 text-sm text-danger">{error}</div>}

      <div className="mb-6 rounded-card border border-border bg-card p-6 shadow-card">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-text">{entry.entry_number}</h1>
            <p className="mt-1 text-sm text-muted">{entry.description}</p>
          </div>
          <div className="flex items-center gap-3">
            {entry.is_posted ? (
              <Badge variant="success">Posted</Badge>
            ) : (
              <>
                <Badge variant="warn">Draft</Badge>
                <Button onClick={handlePost} disabled={posting}>
                  {posting ? 'Posting…' : 'Post Entry'}
                </Button>
              </>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <span className="text-muted">Date</span>
            <p className="mono font-medium text-text">{new Date(entry.entry_date).toLocaleDateString('en-NZ')}</p>
          </div>
          <div>
            <span className="text-muted">Source</span>
            <p className="font-medium text-text">{entry.source_type}</p>
          </div>
          <div>
            <span className="text-muted">Reference</span>
            <p className="font-medium text-text">{entry.reference ?? '—'}</p>
          </div>
          <div>
            <span className="text-muted">Created</span>
            <p className="mono font-medium text-text">{new Date(entry.created_at).toLocaleDateString('en-NZ')}</p>
          </div>
        </div>
      </div>

      {/* Lines table */}
      <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold text-text">Journal Lines</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead>
              <tr>
                <th className={TH}>Account</th>
                <th className={TH}>Description</th>
                <th className={TH_RIGHT}>Debit</th>
                <th className={TH_RIGHT}>Credit</th>
              </tr>
            </thead>
            <tbody>
              {lines.map(line => (
                <tr key={line.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="px-4 py-3 text-sm text-text">{accountName(line.account_id)}</td>
                  <td className="px-4 py-3 text-sm text-muted">{line.description ?? '—'}</td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-right text-sm font-medium text-text">
                    {(Number(line.debit) ?? 0) > 0 ? `${(Number(line.debit) ?? 0).toFixed(2)}` : '—'}
                  </td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-right text-sm font-medium text-text">
                    {(Number(line.credit) ?? 0) > 0 ? `${(Number(line.credit) ?? 0).toFixed(2)}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-canvas">
              <tr>
                <td colSpan={2} className="px-4 py-3 text-right text-sm font-semibold text-text">Totals</td>
                <td className="mono whitespace-nowrap px-4 py-3 text-right text-sm font-semibold text-text">
                  ${(totalDebits ?? 0).toFixed(2)}
                </td>
                <td className="mono whitespace-nowrap px-4 py-3 text-right text-sm font-semibold text-text">
                  ${(totalCredits ?? 0).toFixed(2)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>
  )
}
