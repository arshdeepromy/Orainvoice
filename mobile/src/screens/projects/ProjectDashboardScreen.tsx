import { useNavigate, useParams } from 'react-router-dom'
import {
  Page,
  Card,
  List,
  ListItem,
  Block,
  BlockTitle,
  Preloader,
  Progressbar,
} from 'konsta/react'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import { useApiDetail } from '@/hooks/useApiDetail'
import StatusBadge from '@/components/konsta/StatusBadge'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

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

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/**
 * Project dashboard — tasks, budget breakdown, linked invoices, time entries.
 * Uses KonstaNavbar for back navigation.
 *
 * Requirements: 34.2
 */
export default function ProjectDashboardScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading, error } = useApiDetail<ProjectDashboard>({
    endpoint: `/api/v2/projects/${id}`,
  })

  if (isLoading) {
    return (
      <Page data-testid="project-dashboard-page">
        <KonstaNavbar title="Project" showBack />
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  if (error || !data) {
    return (
      <Page data-testid="project-dashboard-page">
        <KonstaNavbar title="Project" showBack />
        <Block>
          <p className="text-center text-red-600 dark:text-red-400">{error ?? 'Project not found'}</p>
        </Block>
      </Page>
    )
  }

  const tasks: ProjectTask[] = data.tasks ?? []
  const invoices: LinkedInvoice[] = data.linked_invoices ?? []
  const timeEntries: TimeEntry[] = data.time_entries ?? []
  const utilisation = data.budget > 0 ? Math.round((data.spent / data.budget) * 100) : 0

  return (
    <Page data-testid="project-dashboard-page">
      <KonstaNavbar title={data.name ?? 'Project'} showBack />

      <div className="flex flex-col pb-24">
        {/* Budget summary cards */}
        <div className="grid grid-cols-3 gap-2 px-4 pt-4">
          <Card className="text-center" data-testid="budget-card">
            <p className="text-xs text-gray-500 dark:text-gray-400">Budget</p>
            <p className="text-lg font-bold text-gray-900 dark:text-gray-100">{formatNZD(data.budget)}</p>
          </Card>
          <Card className="text-center" data-testid="spent-card">
            <p className="text-xs text-gray-500 dark:text-gray-400">Spent</p>
            <p className="text-lg font-bold text-red-600 dark:text-red-400">{formatNZD(data.spent)}</p>
          </Card>
          <Card className="text-center" data-testid="remaining-card">
            <p className="text-xs text-gray-500 dark:text-gray-400">Remaining</p>
            <p className="text-lg font-bold text-green-600 dark:text-green-400">{formatNZD(data.remaining ?? (data.budget - data.spent))}</p>
          </Card>
        </div>

        {/* Progress bar */}
        <Block>
          <Progressbar progress={Math.min(utilisation, 100) / 100} />
          <p className="mt-1 text-center text-xs text-gray-500 dark:text-gray-400">{utilisation}% utilised</p>
        </Block>

        {/* Tasks */}
        <BlockTitle>Tasks ({tasks.length})</BlockTitle>
        {tasks.length === 0 ? (
          <Block><p className="text-sm text-gray-500 dark:text-gray-400">No tasks</p></Block>
        ) : (
          <List strongIos outlineIos dividersIos data-testid="tasks-list">
            {tasks.map((t) => (
              <ListItem
                key={t.id}
                title={<span className="text-gray-900 dark:text-gray-100">{t.title}</span>}
                subtitle={t.assignee ? <span className="text-xs text-gray-500 dark:text-gray-400">{t.assignee}</span> : undefined}
                after={<StatusBadge status={t.status ?? 'todo'} size="sm" />}
              />
            ))}
          </List>
        )}

        {/* Linked Invoices */}
        <BlockTitle>Linked Invoices ({invoices.length})</BlockTitle>
        {invoices.length === 0 ? (
          <Block><p className="text-sm text-gray-500 dark:text-gray-400">No linked invoices</p></Block>
        ) : (
          <List strongIos outlineIos dividersIos data-testid="linked-invoices-list">
            {invoices.map((inv) => (
              <ListItem
                key={inv.id}
                link
                onClick={() => navigate(`/invoices/${inv.id}`)}
                title={<span className="font-medium text-blue-600 dark:text-blue-400">{inv.invoice_number ?? 'Invoice'}</span>}
                after={<span className="text-sm font-medium text-gray-900 dark:text-gray-100">{formatNZD(inv.amount)}</span>}
              />
            ))}
          </List>
        )}

        {/* Time Entries */}
        <BlockTitle>Time Entries ({timeEntries.length})</BlockTitle>
        {timeEntries.length === 0 ? (
          <Block><p className="text-sm text-gray-500 dark:text-gray-400">No time entries</p></Block>
        ) : (
          <List strongIos outlineIos dividersIos data-testid="time-entries-list">
            {timeEntries.slice(0, 10).map((te) => (
              <ListItem
                key={te.id}
                title={<span className="text-gray-900 dark:text-gray-100">{te.staff_name ?? 'Staff'} — {te.hours ?? 0}h</span>}
                subtitle={te.description ? <span className="text-xs text-gray-500 dark:text-gray-400 line-clamp-1">{te.description}</span> : undefined}
                after={<span className="text-xs text-gray-500 dark:text-gray-400">{te.date}</span>}
              />
            ))}
          </List>
        )}
      </div>
    </Page>
  )
}
