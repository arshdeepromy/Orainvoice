import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'

export interface PortalQuote {
  id: string
  quote_number: string
  status: string
  expiry_date: string | null
  terms: string | null
  line_items: { description: string; quantity: number; unit_price: number; total: number | null }[]
  subtotal: number
  tax_amount: number
  total: number
  currency: string | null
  acceptance_token: string | null
  accepted_at: string | null
  created_at: string
}

interface QuoteAcceptanceProps {
  token: string
}

const QUOTE_STATUS: Record<string, { label: string; variant: 'success' | 'warning' | 'error' | 'info' | 'neutral' }> = {
  sent: { label: 'Awaiting Response', variant: 'info' },
  accepted: { label: 'Accepted', variant: 'success' },
  declined: { label: 'Declined', variant: 'error' },
  expired: { label: 'Expired', variant: 'neutral' },
  converted: { label: 'Converted', variant: 'success' },
}

export function QuoteAcceptance({ token }: QuoteAcceptanceProps) {
  const [quotes, setQuotes] = useState<PortalQuote[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [accepting, setAccepting] = useState<string | null>(null)

  const fetchQuotes = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/portal/${token}/quotes`)
      setQuotes(res.data.quotes ?? res.data)
    } catch {
      setError('Failed to load quotes.')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { fetchQuotes() }, [fetchQuotes])

  const handleAccept = async (quoteId: string) => {
    setAccepting(quoteId)
    try {
      await apiClient.post(`/portal/${token}/quotes/${quoteId}/accept`)
      await fetchQuotes()
    } catch {
      setError('Failed to accept quote. It may have expired.')
    } finally {
      setAccepting(null)
    }
  }

  if (loading) return <div className="py-8"><Spinner label="Loading quotes" /></div>
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (quotes.length === 0) return <p className="py-8 text-center text-sm text-gray-500">No quotes found.</p>

  return (
    <div className="space-y-3">
      {quotes.map((q) => {
        const cfg = QUOTE_STATUS[q.status] ?? { label: q.status, variant: 'neutral' as const }
        const canAccept = q.status === 'sent'
        return (
          <div key={q.id} className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{q.quote_number}</span>
                  <Badge variant={cfg.variant}>{cfg.label}</Badge>
                </div>
                {q.line_items.length > 0 && (
                  <p className="mt-1 text-sm text-gray-500 truncate">
                    {q.line_items.map(li => li.description).join(', ')}
                  </p>
                )}
                <p className="mt-1 text-xs text-gray-400">
                  Created {formatDate(q.created_at)}
                  {q.expiry_date && ` · Expires ${formatDate(q.expiry_date)}`}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <p className="text-sm font-semibold text-gray-900 tabular-nums">
                  {formatCurrency(q.total, q.currency)}
                </p>
                {canAccept && (
                  <Button
                    size="sm"
                    onClick={() => handleAccept(q.id)}
                    disabled={accepting === q.id}
                  >
                    {accepting === q.id ? 'Accepting…' : 'Accept Quote'}
                  </Button>
                )}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function formatCurrency(amount: number, currency?: string | null): string {
  return new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: currency || 'NZD',
  }).format(amount)
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-NZ', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}
