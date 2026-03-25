import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'

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
  { key: 'reference', header: 'Reference', sortable: true },
  { key: 'customer_name', header: 'Customer', sortable: true },
  { key: 'vehicle_rego', header: 'Rego', sortable: true },
  {
    key: 'status',
    header: 'Status',
    render: (row) => <Badge variant="info">{String(row.status)}</Badge>,
  },
]

const invoiceColumns: Column<Row>[] = [
  { key: 'invoice_number', header: 'Invoice #', sortable: true },
  { key: 'customer_name', header: 'Customer', sortable: true },
  { key: 'vehicle_rego', header: 'Rego' },
  {
    key: 'total',
    header: 'Total',
    sortable: true,
    render: (row) => `$${Number(row.total).toFixed(2)}`,
  },
  {
    key: 'status',
    header: 'Status',
    render: (row) => {
      const status = String(row.status)
      const variant =
        status === 'paid'
          ? 'success'
          : status === 'overdue'
            ? 'error'
            : status === 'partially_paid'
              ? 'warning'
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
        const [appointmentsRes, jobCardsRes, invoicesRes, overdueRes] =
          await Promise.all([
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
            Array.isArray(d) ? d : Array.isArray((d as Record<string, unknown>)?.bookings) ? (d as Record<string, unknown>).bookings as unknown[]
            : Array.isArray((d as Record<string, unknown>)?.job_cards) ? (d as Record<string, unknown>).job_cards as unknown[]
            : Array.isArray((d as Record<string, unknown>)?.invoices) ? (d as Record<string, unknown>).invoices as unknown[]
            : Array.isArray((d as Record<string, unknown>)?.items) ? (d as Record<string, unknown>).items as unknown[]
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
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (!data) return null

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">Dashboard</h1>
        <Button onClick={() => navigate('/invoices/new')}>New Invoice</Button>
      </div>

      {data.overdue_invoices.length > 0 && (
        <AlertBanner variant="warning" title="Overdue Invoices">
          You have {data.overdue_invoices.length} overdue invoice
          {data.overdue_invoices.length !== 1 ? 's' : ''} requiring attention.
        </AlertBanner>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard label="Today's Appointments" value={data.appointments.length} />
        <SummaryCard label="Active Job Cards" value={data.active_job_cards.length} />
        <SummaryCard label="Recent Invoices" value={data.recent_invoices.length} />
        <SummaryCard label="Overdue Invoices" value={data.overdue_invoices.length} variant="error" />
      </div>

      {/* Today's appointments */}
      {data.appointments.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-medium text-gray-900">Today's Appointments</h2>
          <div className="space-y-2">
            {data.appointments.map((appt) => (
              <div
                key={appt.id}
                className="flex items-center justify-between rounded-lg border border-gray-200 bg-white p-4"
              >
                <div>
                  <p className="font-medium text-gray-900">{appt.customer_name}</p>
                  <p className="text-sm text-gray-500">
                    {appt.vehicle_rego} · {appt.service_type}
                  </p>
                </div>
                <span className="text-sm font-medium text-gray-700">{appt.time}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Active job cards */}
      <section>
        <h2 className="mb-3 text-lg font-medium text-gray-900">Active Job Cards</h2>
        <DataTable
          columns={jobCardColumns}
          data={data.active_job_cards as unknown as Row[]}
          keyField="id"
          caption="Active job cards"
        />
      </section>

      {/* Recent invoices */}
      <section>
        <h2 className="mb-3 text-lg font-medium text-gray-900">Recent Invoices</h2>
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
          <h2 className="mb-3 text-lg font-medium text-gray-900">Overdue Invoices</h2>
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
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <p className="text-sm font-medium text-gray-500">{label}</p>
      <p
        className={`mt-1 text-2xl font-semibold ${
          variant === 'error' ? 'text-red-600' : 'text-gray-900'
        }`}
      >
        {value}
      </p>
    </div>
  )
}
