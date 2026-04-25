import { useNavigate, useParams } from 'react-router-dom'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileCard, MobileBadge, MobileSpinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'

interface ProjectDashboard {
  id: string
  name: string
  status: string
  budget: number
  spent: number
  remaining: number
  tasks: ProjectTask[]
  linked_invoices: LinkedInvoice[]
  time_entries: TimeEntry[]
}

interface ProjectTask {
  id: string
  title: string
  status: string
  assignee: string | null
}

interface LinkedInvoice {
  id: string
  invoice_number: string
  amount: number
  status: string
}

interface TimeEntry {
  id: string
  staff_name: string | null
  hours: number
  date: string
  description: string | null
}

const taskStatusVariant: Record<string, BadgeVariant> = {
  todo: 'draft',
  in_progress: 'sent',
  done: 'paid',
  blocked: 'overdue',
}

function formatCurrency(n: number) {
  return `$${Number(n ?? 0).toFixed(2)}`
}

/**
 * Project dashboard — tasks, budget breakdown, linked invoices, time entries.
 *
 * Requirements: 36.2
 */
export default function ProjectDashboardScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading, error } = useApiDetail<ProjectDashboard>({
    endpoint: `/api/v2/projects/${id}`,
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="p-4 text-center text-red-600 dark:text-red-400">
        {error ?? 'Project not found'}
      </div>
    )
  }

  const tasks: ProjectTask[] = data.tasks ?? []
  const invoices: LinkedInvoice[] = data.linked_invoices ?? []
  const timeEntries: TimeEntry[] = data.time_entries ?? []
  const utilisation = data.budget > 0 ? Math.round((data.spent / data.budget) * 100) : 0

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
        aria-label="Back"
      >
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="m15 18-6-6 6-6" />
        </svg>
        Back
      </button>

      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        {data.name ?? 'Project'}
      </h1>

      {/* Budget breakdown */}
      <div className="grid grid-cols-3 gap-2">
        <MobileCard>
          <p className="text-xs text-gray-500 dark:text-gray-400">Budget</p>
          <p className="text-lg font-bold text-gray-900 dark:text-gray-100">
            {formatCurrency(data.budget)}
          </p>
        </MobileCard>
        <MobileCard>
          <p className="text-xs text-gray-500 dark:text-gray-400">Spent</p>
          <p className="text-lg font-bold text-red-600 dark:text-red-400">
            {formatCurrency(data.spent)}
          </p>
        </MobileCard>
        <MobileCard>
          <p className="text-xs text-gray-500 dark:text-gray-400">Remaining</p>
          <p className="text-lg font-bold text-green-600 dark:text-green-400">
            {formatCurrency(data.remaining ?? (data.budget - data.spent))}
          </p>
        </MobileCard>
      </div>

      {/* Budget bar */}
      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
        <div
          className={`h-full rounded-full transition-all ${utilisation > 90 ? 'bg-red-500' : utilisation > 70 ? 'bg-amber-500' : 'bg-green-500'}`}
          style={{ width: `${Math.min(utilisation, 100)}%` }}
        />
      </div>
      <p className="text-center text-xs text-gray-500 dark:text-gray-400">{utilisation}% utilised</p>

      {/* Tasks */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Tasks ({tasks.length})
        </h2>
        {tasks.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">No tasks</p>
        ) : (
          tasks.map((t) => (
            <div
              key={t.id}
              className="flex items-center justify-between border-b border-gray-100 py-2 last:border-b-0 dark:border-gray-700"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm text-gray-900 dark:text-gray-100">{t.title}</p>
                {t.assignee && (
                  <p className="text-xs text-gray-500 dark:text-gray-400">{t.assignee}</p>
                )}
              </div>
              <MobileBadge
                label={(t.status ?? 'todo').replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                variant={taskStatusVariant[t.status] ?? 'info'}
              />
            </div>
          ))
        )}
      </MobileCard>

      {/* Linked invoices */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Linked Invoices ({invoices.length})
        </h2>
        {invoices.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">No linked invoices</p>
        ) : (
          invoices.map((inv) => (
            <div
              key={inv.id}
              onClick={() => navigate(`/invoices/${inv.id}`)}
              className="flex cursor-pointer items-center justify-between border-b border-gray-100 py-2 last:border-b-0 dark:border-gray-700"
            >
              <p className="text-sm font-medium text-blue-600 dark:text-blue-400">
                {inv.invoice_number ?? 'Invoice'}
              </p>
              <span className="text-sm text-gray-900 dark:text-gray-100">
                {formatCurrency(inv.amount)}
              </span>
            </div>
          ))
        )}
      </MobileCard>

      {/* Time entries */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Time Entries ({timeEntries.length})
        </h2>
        {timeEntries.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">No time entries</p>
        ) : (
          timeEntries.slice(0, 10).map((te) => (
            <div
              key={te.id}
              className="flex items-center justify-between border-b border-gray-100 py-2 last:border-b-0 dark:border-gray-700"
            >
              <div>
                <p className="text-sm text-gray-900 dark:text-gray-100">
                  {te.staff_name ?? 'Staff'} — {te.hours ?? 0}h
                </p>
                {te.description && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-1">
                    {te.description}
                  </p>
                )}
              </div>
              <span className="text-xs text-gray-500 dark:text-gray-400">{te.date}</span>
            </div>
          ))
        )}
      </MobileCard>
    </div>
  )
}
