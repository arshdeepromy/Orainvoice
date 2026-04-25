import { useParams, useNavigate } from 'react-router-dom'
import type { JournalEntry } from '@shared/types/accounting'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileCard, MobileButton, MobileSpinner } from '@/components/ui'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

/**
 * Journal entry detail screen — all debit and credit lines for a
 * journal entry.
 *
 * Requirements: 24.2
 */
export default function JournalEntryDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: entry, isLoading, error } = useApiDetail<JournalEntry>({
    endpoint: `/api/v1/ledger/journal-entries/${id}`,
    enabled: !!id,
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !entry) {
    return (
      <div className="flex flex-col items-center gap-4 p-8">
        <p className="text-gray-500 dark:text-gray-400">
          {error ?? 'Journal entry not found'}
        </p>
        <MobileButton variant="secondary" onClick={() => navigate(-1)}>
          Go Back
        </MobileButton>
      </div>
    )
  }

  const lines = entry.lines ?? []
  const totalDebit = lines.reduce((sum, l) => sum + (l.debit ?? 0), 0)
  const totalCredit = lines.reduce((sum, l) => sum + (l.credit ?? 0), 0)

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back button */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
        aria-label="Back"
      >
        <svg
          className="h-5 w-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m15 18-6-6 6-6" />
        </svg>
        Back
      </button>

      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          {entry.description ?? 'Journal Entry'}
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          {formatDate(entry.date)}
          {entry.reference && ` · Ref: ${entry.reference}`}
        </p>
      </div>

      {/* Debit & Credit lines */}
      <MobileCard>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700">
                <th className="pb-2 text-left font-medium text-gray-500 dark:text-gray-400">
                  Account
                </th>
                <th className="pb-2 text-right font-medium text-gray-500 dark:text-gray-400">
                  Debit
                </th>
                <th className="pb-2 text-right font-medium text-gray-500 dark:text-gray-400">
                  Credit
                </th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => (
                <tr
                  key={line.id}
                  className="border-b border-gray-100 last:border-b-0 dark:border-gray-700"
                >
                  <td className="py-3 text-gray-900 dark:text-gray-100">
                    {line.account_name ?? 'Unknown'}
                  </td>
                  <td className="py-3 text-right text-gray-900 dark:text-gray-100">
                    {(line.debit ?? 0) > 0 ? formatCurrency(line.debit) : '—'}
                  </td>
                  <td className="py-3 text-right text-gray-900 dark:text-gray-100">
                    {(line.credit ?? 0) > 0 ? formatCurrency(line.credit) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-gray-300 dark:border-gray-600">
                <td className="pt-3 font-semibold text-gray-900 dark:text-gray-100">
                  Total
                </td>
                <td className="pt-3 text-right font-semibold text-gray-900 dark:text-gray-100">
                  {formatCurrency(totalDebit)}
                </td>
                <td className="pt-3 text-right font-semibold text-gray-900 dark:text-gray-100">
                  {formatCurrency(totalCredit)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </MobileCard>

      {/* Balance check */}
      {Math.abs(totalDebit - totalCredit) > 0.01 && (
        <div
          className="rounded-lg bg-amber-50 p-3 text-sm text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
          role="alert"
        >
          Entry is unbalanced: debits ({formatCurrency(totalDebit)}) ≠ credits ({formatCurrency(totalCredit)})
        </div>
      )}
    </div>
  )
}
