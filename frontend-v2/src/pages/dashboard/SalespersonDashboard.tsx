import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Badge, Spinner, AlertBanner, DataTable, Card, cx, type Column } from '@/components/ui'

/* ============================================================
   SalespersonDashboard (Task 17) — the salesperson dashboard (also the
   default dispatcher branch).
   ------------------------------------------------------------
   Logic source: frontend/src/pages/dashboard/SalespersonDashboard.tsx.
   ALL data logic is copied VERBATIM (FR-1 / FR-2c):
     • Parallel fetch (cancelled guard) of four endpoints:
         GET /bookings?date=<today ISO date>     (today's appointments)
         GET /job-cards?status=active            (active job cards)
         GET /invoices?limit=10&sort=-issue_date (recent invoices)
         GET /invoices?status=overdue            (overdue invoices)
     • The `toArr()` defensive normaliser that accepts a bare array OR a
       wrapped { bookings | job_cards | invoices | items } object — copied
       byte-for-byte (this IS the safe-consumption guard for these legacy
       endpoints that can return either shape).
     • The overdue-invoices warning banner, the four summary counts, and the
       conditional sections (appointments + overdue only when non-empty) —
       all unchanged.
     • The jobCardColumns / invoiceColumns DataTable column defs, including
       the per-status Badge mapping (paid→success / overdue→error /
       partially_paid→warning / else neutral) — preserved; the new Badge
       union maps `error`→`danger` and `warning`→`warn`.

   Design (FR-2): restyled onto the redesign tokens with MainDashboard's
   patterns — `.page` + `.page-head` with a "New Invoice" primary action,
   summary KPI cards, the ported DataTable, and appointment rows as Card
   surfaces. Money/IDs render in `.mono`.
   ============================================================ */

interface Appointment {
  id: string
  time: string
  customer_name: string
  vehicle_rego: string
  service_type: string
}

interface JobCard {
  id: string
  reference: string
  customer_name: string
  vehicle_rego: string
  status: string
  created_at: string
}

interface Invoice {
  id: string
  invoice_number: string
  customer_name: string
  vehicle_rego: string
  total: number
  status: string
  issue_date: string
}

interface SalespersonData {
  appointments: Appointment[]
  active_job_cards: JobCard[]
  recent_invoices: Invoice[]
  overdue_invoices: Invoice[]
}

type Row = Record<string, unknown>

const jobCardColumns: Column<Row>[] = [
  { key: 'reference', header: 'Reference', sortable: true, render: (row) => <span className="mono">{String(row.reference ?? '')}</span> },
  { key: 'customer_name', header: 'Customer', sortable: true },
  { key: 'vehicle_rego', header: 'Rego', sortable: true, render: (row) => <span className="mono">{String(row.vehicle_rego ?? '')}</span> },
  {
    key: 'status',
    header: 'Status',
    render: (row) => <Badge variant="info">{String(row.status)}</Badge>,
  },
]

const invoiceColumns: Column<Row>[] = [
  { key: 'invoice_number', header: 'Invoice #', sortable: true, render: (row) => <span className="mono">{String(row.invoice_number ?? '')}</span> },
  { key: 'customer_name', header: 'Customer', sortable: true },
  { key: 'vehicle_rego', header: 'Rego', render: (row) => <span className="mono">{String(row.vehicle_rego ?? '')}</span> },
  {
    key: 'total',
    header: 'Total',
    sortable: true,
    render: (row) => <span className="mono">${Number(row.total ?? 0).toFixed(2)}</span>,
  },
  {
    key: 'status',
    header: 'Status',
    render: (row) => {
      const status = String(row.status)
      // Original variants paid/overdue/partially_paid/neutral map onto the
      // new Badge union (success / danger / warn / neutral).
      const variant =
        status === 'paid'
          ? 'success'
          : status === 'overdue'
            ? 'danger'
            : status === 'partially_paid'
              ? 'warn'
              : 'neutral'
      return <Badge variant={variant}>{status}</Badge>
    },
  },
]

export function SalespersonDashboard() {
  const navigate = useNavigate()
  const [data, setData] = useState<SalespersonData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function fetchDashboard() {
      try {
        const [appointmentsRes, jobCardsRes, invoicesRes, overdueRes] = await Promise.all([
          apiClient.get('/bookings', {
            params: { date: new Date().toISOString().split('T')[0] },
          }),
          apiClient.get('/job-cards', {
            params: { status: 'active' },
          }),
          apiClient.get('/invoices', {
            params: { limit: 10, sort: '-issue_date' },
          }),
          apiClient.get('/invoices', {
            params: { status: 'overdue' },
          }),
        ])
        if (!cancelled) {
          const toArr = (d: unknown): unknown[] =>
            Array.isArray(d)
              ? d
              : Array.isArray((d as Record<string, unknown>)?.bookings)
                ? ((d as Record<string, unknown>).bookings as unknown[])
                : Array.isArray((d as Record<string, unknown>)?.job_cards)
                  ? ((d as Record<string, unknown>).job_cards as unknown[])
                  : Array.isArray((d as Record<string, unknown>)?.invoices)
                    ? ((d as Record<string, unknown>).invoices as unknown[])
                    : Array.isArray((d as Record<string, unknown>)?.items)
                      ? ((d as Record<string, unknown>).items as unknown[])
                      : []
          setData({
            appointments: toArr(appointmentsRes.data) as Appointment[],
            active_job_cards: toArr(jobCardsRes.data) as JobCard[],
            recent_invoices: toArr(invoicesRes.data) as Invoice[],
            overdue_invoices: toArr(overdueRes.data) as Invoice[],
          })
        }
      } catch {
        if (!cancelled) setError('Failed to load dashboard data')
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    fetchDashboard()
    return () => {
      cancelled = true
    }
  }, [])

  if (isLoading) return <Spinner size="lg" label="Loading dashboard" className="py-20" />
  if (error) {
    return (
      <div className="page">
        <AlertBanner variant="error">{error}</AlertBanner>
      </div>
    )
  }
  if (!data) return null

  return (
    <div className="page space-y-6">
      <div className="page-head">
        <div>
          <div className="eyebrow">Overview</div>
          <h1>Dashboard</h1>
        </div>
        <div className="head-actions">
          <Button onClick={() => navigate('/invoices/new')}>New Invoice</Button>
        </div>
      </div>

      {data.overdue_invoices.length > 0 && (
        <AlertBanner variant="warning" title="Overdue Invoices">
          You have {data.overdue_invoices.length} overdue invoice
          {data.overdue_invoices.length !== 1 ? 's' : ''} requiring attention.
        </AlertBanner>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-gap sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard label="Today's Appointments" value={data.appointments.length} />
        <SummaryCard label="Active Job Cards" value={data.active_job_cards.length} />
        <SummaryCard label="Recent Invoices" value={data.recent_invoices.length} />
        <SummaryCard label="Overdue Invoices" value={data.overdue_invoices.length} variant="error" />
      </div>

      {/* Today's appointments */}
      {data.appointments.length > 0 && (
        <section>
          <h2 className="mb-3 text-[15px] font-semibold text-text">Today's Appointments</h2>
          <div className="space-y-2">
            {data.appointments.map((appt) => (
              <Card key={appt.id} className="flex items-center justify-between p-4">
                <div>
                  <p className="text-[13.5px] font-semibold text-text">{appt.customer_name}</p>
                  <p className="text-[12.5px] text-muted">
                    <span className="mono">{appt.vehicle_rego}</span> · {appt.service_type}
                  </p>
                </div>
                <span className="mono text-[13.5px] font-semibold text-text">{appt.time}</span>
              </Card>
            ))}
          </div>
        </section>
      )}

      {/* Active job cards */}
      <section>
        <h2 className="mb-3 text-[15px] font-semibold text-text">Active Job Cards</h2>
        <DataTable
          columns={jobCardColumns}
          data={data.active_job_cards as unknown as Row[]}
          keyField="id"
          caption="Active job cards"
        />
      </section>

      {/* Recent invoices */}
      <section>
        <h2 className="mb-3 text-[15px] font-semibold text-text">Recent Invoices</h2>
        <DataTable
          columns={invoiceColumns}
          data={data.recent_invoices as unknown as Row[]}
          keyField="id"
          caption="Recent invoices"
        />
      </section>

      {/* Overdue invoices */}
      {data.overdue_invoices.length > 0 && (
        <section>
          <h2 className="mb-3 text-[15px] font-semibold text-text">Overdue Invoices</h2>
          <DataTable
            columns={invoiceColumns}
            data={data.overdue_invoices as unknown as Row[]}
            keyField="id"
            caption="Overdue invoices"
          />
        </section>
      )}
    </div>
  )
}

/* ── Summary card — label + big mono count ── */

function SummaryCard({
  label,
  value,
  variant,
}: {
  label: string
  value: number | string
  variant?: 'error'
}) {
  return (
    <div className="rounded-card border border-border bg-card p-5 shadow-card">
      <p className="text-[12.5px] font-medium text-muted">{label}</p>
      <p
        className={cx(
          'mono mt-1.5 text-[27px] font-semibold leading-none tracking-[-0.02em]',
          variant === 'error' ? 'text-danger' : 'text-text',
        )}
      >
        {value}
      </p>
    </div>
  )
}

export default SalespersonDashboard
