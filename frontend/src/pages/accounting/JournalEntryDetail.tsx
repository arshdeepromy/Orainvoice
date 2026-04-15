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
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          {error || 'Journal entry not found.'}
        </div>
        <div className="mt-4">
          <Button variant="secondary" onClick={() => navigate('/accounting/journal-entries')}>← Back</Button>
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
        <button onClick={() => navigate('/accounting/journal-entries')} className="text-blue-600 hover:underline text-sm">
          ← Back to Journal Entries
        </button>
      </div>

      {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 mb-4">{error}</div>}

      <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">{entry.entry_number}</h1>
            <p className="text-sm text-gray-500 mt-1">{entry.description}</p>
          </div>
          <div className="flex items-center gap-3">
            {entry.is_posted ? (
              <Badge variant="success">Posted</Badge>
            ) : (
              <>
                <Badge variant="warning">Draft</Badge>
                <Button onClick={handlePost} disabled={posting}>
                  {posting ? 'Posting…' : 'Post Entry'}
                </Button>
              </>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-gray-500">Date</span>
            <p className="font-medium">{new Date(entry.entry_date).toLocaleDateString('en-NZ')}</p>
          </div>
          <div>
            <span className="text-gray-500">Source</span>
            <p className="font-medium">{entry.source_type}</p>
          </div>
          <div>
            <span className="text-gray-500">Reference</span>
            <p className="font-medium">{entry.reference ?? '—'}</p>
          </div>
          <div>
            <span className="text-gray-500">Created</span>
            <p className="font-medium">{new Date(entry.created_at).toLocaleDateString('en-NZ')}</p>
          </div>
        </div>
      </div>

      {/* Lines table */}
      <div className="bg-white rounded-lg border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Journal Lines</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Account</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Debit</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Credit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {lines.map(line => (
                <tr key={line.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-900">{accountName(line.account_id)}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{line.description ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-right font-medium tabular-nums">
                    {(Number(line.debit) ?? 0) > 0 ? `$${(Number(line.debit) ?? 0).toFixed(2)}` : '—'}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-right font-medium tabular-nums">
                    {(Number(line.credit) ?? 0) > 0 ? `$${(Number(line.credit) ?? 0).toFixed(2)}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-gray-50">
              <tr>
                <td colSpan={2} className="px-4 py-3 text-sm font-semibold text-gray-900 text-right">Totals</td>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-right font-semibold tabular-nums">
                  ${(totalDebits ?? 0).toFixed(2)}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-right font-semibold tabular-nums">
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
