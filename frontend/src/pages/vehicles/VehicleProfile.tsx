import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import apiClient from '../../api/client'
import { Button, Badge, Spinner, Tabs, Modal, Input, ToastContainer, useToast } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

interface ExpiryIndicator {
  date: string | null
  days_remaining: number | null
  indicator: 'green' | 'amber' | 'red'
}

interface LinkedCustomer {
  id: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
}

interface ServiceHistoryEntry {
  invoice_id: string
  invoice_number: string | null
  status: string
  issue_date: string | null
  total: string
  odometer: number | null
  customer_name: string
  description: string | null
}

interface VehicleProfileData {
  id: string
  rego: string
  make: string | null
  model: string | null
  year: number | null
  colour: string | null
  body_type: string | null
  fuel_type: string | null
  engine_size: string | null
  seats: number | null
  odometer: number | null
  last_pulled_at: string | null
  wof_expiry: ExpiryIndicator
  rego_expiry: ExpiryIndicator
  linked_customers: LinkedCustomer[]
  service_history: ServiceHistoryEntry[]
  // Extended fields
  vin: string | null
  chassis: string | null
  engine_no: string | null
  transmission: string | null
  country_of_origin: string | null
  number_of_owners: number | null
  vehicle_type: string | null
  submodel: string | null
  second_colour: string | null
  lookup_type: string | null
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(amount: string | number): string {
  const num = typeof amount === 'string' ? parseFloat(amount) : amount
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(num)
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(dateStr))
}

const INDICATOR_BADGE: Record<string, { label: string; variant: BadgeVariant }> = {
  green: { label: 'OK', variant: 'success' },
  amber: { label: 'Due Soon', variant: 'warning' },
  red: { label: 'Expired / Due', variant: 'error' },
}

const INVOICE_STATUS_CONFIG: Record<string, { label: string; variant: BadgeVariant }> = {
  draft: { label: 'Draft', variant: 'neutral' },
  issued: { label: 'Issued', variant: 'info' },
  partially_paid: { label: 'Partially Paid', variant: 'warning' },
  paid: { label: 'Paid', variant: 'success' },
  overdue: { label: 'Overdue', variant: 'error' },
  voided: { label: 'Voided', variant: 'neutral' },
}

function ExpiryBadge({ expiry, label }: { expiry: ExpiryIndicator; label: string }) {
  const cfg = INDICATOR_BADGE[expiry.indicator] ?? INDICATOR_BADGE.red
  const dateStr = expiry.date ? formatDate(expiry.date) : 'Unknown'
  const daysText = expiry.days_remaining != null
    ? expiry.days_remaining >= 0
      ? `${expiry.days_remaining}d remaining`
      : `${Math.abs(expiry.days_remaining)}d overdue`
    : ''

  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">{label}</p>
      <div className="mt-1 flex items-center gap-2">
        <Badge variant={cfg.variant}>{cfg.label}</Badge>
        <span className="text-sm text-gray-900">{dateStr}</span>
      </div>
      {daysText && <p className="mt-0.5 text-xs text-gray-500">{daysText}</p>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function VehicleProfilePage() {
  const { id } = useParams<{ id: string }>()

  const [vehicle, setVehicle] = useState<VehicleProfileData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState('')

  // Service history report state
  const [reportRange, setReportRange] = useState<'1' | '2' | '3' | 'all'>('1')
  const [printLoading, setPrintLoading] = useState(false)
  const [emailModalOpen, setEmailModalOpen] = useState(false)
  const [emailRange, setEmailRange] = useState<'1' | '2' | '3' | 'all'>('1')
  const [emailSending, setEmailSending] = useState(false)
  const [emailMsg, setEmailMsg] = useState('')
  const [recipientEmail, setRecipientEmail] = useState('')
  const { toasts, addToast, dismissToast } = useToast()

  /* ---- Fetch profile ---- */
  const fetchProfile = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<VehicleProfileData>(`/vehicles/${id}`)
      setVehicle(res.data)
    } catch {
      setError('Failed to load vehicle profile.')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetchProfile() }, [fetchProfile])

  /* ---- Refresh from Carjam ---- */
  const handleRefresh = async () => {
    if (!id) return
    setRefreshing(true)
    setRefreshMsg('')
    try {
      await apiClient.post(`/vehicles/${id}/refresh`)
      setRefreshMsg('Vehicle data refreshed from Carjam.')
      await fetchProfile()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number } }
      if (axiosErr.response?.status === 429) {
        setRefreshMsg('Rate limit exceeded. Please try again shortly.')
      } else {
        setRefreshMsg('Failed to refresh vehicle data.')
      }
    } finally {
      setRefreshing(false)
    }
  }

  /* ---- Loading / Error ---- */
  if (loading) {
    return <div className="py-16"><Spinner label="Loading vehicle" /></div>
  }

  if (error || !vehicle) {
    return (
      <div className="px-4 py-6 sm:px-6 lg:px-8">
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error || 'Vehicle not found.'}
        </div>
        <Button variant="secondary" className="mt-4" onClick={() => { window.location.href = '/vehicles' }}>
          ← Back to Vehicles
        </Button>
      </div>
    )
  }

  const vehicleTitle = [vehicle.year, vehicle.make, vehicle.model].filter(Boolean).join(' ') || 'Unknown Vehicle'

  /* ---- Odometer history from service entries ---- */
  const odometerHistory = vehicle.service_history
    .filter((s) => s.odometer != null)
    .map((s) => ({
      date: s.issue_date,
      odometer: s.odometer as number,
      invoice_number: s.invoice_number,
      invoice_id: s.invoice_id,
    }))

  /* ---- Tab: Linked Customers ---- */
  const customersTab = (
    <div>
      {vehicle.linked_customers.length === 0 ? (
        <p className="text-sm text-gray-500">No customers linked to this vehicle.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <caption className="sr-only">Linked customers</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Email</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Phone</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {vehicle.linked_customers.map((c) => (
                <tr
                  key={c.id}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => { window.location.href = `/customers/${c.id}` }}
                >
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-blue-600">
                    {c.first_name} {c.last_name}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{c.email || '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{c.phone || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )

  /* ---- Tab: Odometer History ---- */
  const odometerTab = (
    <div>
      {odometerHistory.length === 0 ? (
        <p className="text-sm text-gray-500">No odometer readings recorded.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <caption className="sr-only">Odometer history</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Invoice</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Odometer</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {odometerHistory.map((entry, idx) => (
                <tr key={idx} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{formatDate(entry.date)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <button
                      onClick={() => { window.location.href = `/invoices/${entry.invoice_id}` }}
                      className="text-blue-600 hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                    >
                      {entry.invoice_number || 'Draft'}
                    </button>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">
                    {entry.odometer.toLocaleString('en-NZ')} km
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )

  /* ---- Tab: Service History ---- */
  const filterByRange = (entries: ServiceHistoryEntry[], range: string) => {
    if (range === 'all') return entries
    const years = parseInt(range)
    const cutoff = new Date()
    cutoff.setFullYear(cutoff.getFullYear() - years)
    return entries.filter(s => s.issue_date && new Date(s.issue_date) >= cutoff)
  }

  const printServiceReport = async () => {
    if (!vehicle.id) return
    setPrintLoading(true)
    try {
      const rangeYears = reportRange === 'all' ? 0 : parseInt(reportRange)
      const res = await apiClient.post(
        `/vehicles/${vehicle.id}/service-history-report`,
        { range_years: rangeYears },
        { responseType: 'blob' },
      )
      const blob = new Blob([res.data], { type: 'application/pdf' })
      const blobUrl = URL.createObjectURL(blob)
      const printWindow = window.open(blobUrl, '_blank')
      if (printWindow) {
        printWindow.addEventListener('load', () => { printWindow.print() })
      }
    } catch {
      // Silently fail — the user will see the tab didn't open
    } finally {
      setPrintLoading(false)
    }
  }

  const handleEmailServiceHistory = async () => {
    const customer = vehicle.linked_customers[0]
    const emailTo = customer?.email || recipientEmail.trim()
    if (!emailTo) { setEmailMsg('Please enter a recipient email address.'); return }
    setEmailSending(true); setEmailMsg('')
    try {
      await apiClient.post(`/vehicles/${vehicle.id}/service-history-report/email`, {
        range_years: emailRange === 'all' ? 0 : parseInt(emailRange),
        recipient_email: emailTo,
      })
      addToast('success', `Service history report sent to ${emailTo}`)
      setEmailModalOpen(false)
      setEmailMsg('')
      setRecipientEmail('')
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      const detail = axiosErr.response?.data?.detail || 'Failed to send email. Please try again.'
      setEmailMsg(detail)
      addToast('error', detail)
    } finally { setEmailSending(false) }
  }

  const serviceTab = (
    <div>
      {vehicle.service_history.length === 0 ? (
        <p className="text-sm text-gray-500">No service history for this vehicle.</p>
      ) : (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-500">Period:</label>
              <select value={reportRange} onChange={e => setReportRange(e.target.value as any)}
                className="rounded-md border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="1">Last 1 Year</option>
                <option value="2">Last 2 Years</option>
                <option value="3">Last 3 Years</option>
                <option value="all">All Time</option>
              </select>
              <span className="text-sm text-gray-400">{filterByRange(vehicle.service_history, reportRange).length} records</span>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={printServiceReport} loading={printLoading} disabled={printLoading}>Print Report</Button>
              <Button variant="secondary" size="sm" onClick={() => { setEmailRange(reportRange === 'all' ? '1' : reportRange); setEmailMsg(''); setRecipientEmail(''); setEmailModalOpen(true) }}>
                Email to Customer
              </Button>
            </div>
          </div>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <caption className="sr-only">Service history</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Invoice</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Customer</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Odometer</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {filterByRange(vehicle.service_history, reportRange).map((s) => {
                  const cfg = INVOICE_STATUS_CONFIG[s.status] ?? { label: s.status, variant: 'neutral' as BadgeVariant }
                  return (
                    <tr key={s.invoice_id} className="hover:bg-gray-50 cursor-pointer" onClick={() => { window.location.href = `/invoices/${s.invoice_id}` }}>
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-blue-600">{s.invoice_number || <span className="text-gray-400 italic">Draft</span>}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm"><Badge variant={cfg.variant}>{cfg.label}</Badge></td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{formatDate(s.issue_date)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{s.customer_name}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">{s.odometer != null ? s.odometer.toLocaleString('en-NZ') + ' km' : '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">{formatNZD(s.total)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      <Modal open={emailModalOpen} onClose={() => setEmailModalOpen(false)} title="Email Service History">
        <div className="space-y-4">
          <p className="text-sm text-gray-600">Send a service history report for {vehicle.rego} to the linked customer.</p>
          {vehicle.linked_customers.length > 0 && vehicle.linked_customers[0].email ? (
            <div className="rounded-md bg-gray-50 border border-gray-200 px-3 py-2 text-sm">
              <span className="text-gray-500">To:</span> <span className="font-medium text-gray-900">{vehicle.linked_customers[0].first_name} {vehicle.linked_customers[0].last_name}</span>
              <span className="ml-2 text-gray-500">{vehicle.linked_customers[0].email}</span>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-700">No customer email found for this vehicle. Please enter a recipient email below.</div>
              <Input
                label="Recipient Email"
                type="email"
                placeholder="customer@example.com"
                value={recipientEmail}
                onChange={e => setRecipientEmail(e.target.value)}
              />
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Date Range</label>
            <select value={emailRange} onChange={e => setEmailRange(e.target.value as any)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="1">Last 1 Year</option>
              <option value="2">Last 2 Years</option>
              <option value="3">Last 3 Years</option>
              <option value="all">All Time</option>
            </select>
          </div>
          {emailMsg && <p className={`text-sm text-red-600`} role="alert">{emailMsg}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setEmailModalOpen(false)}>Cancel</Button>
            <Button
              onClick={handleEmailServiceHistory}
              loading={emailSending}
              disabled={emailSending || !(vehicle.linked_customers[0]?.email || recipientEmail.trim())}
            >
              {emailSending ? 'Sending…' : 'Send Email'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <div className="flex items-center gap-3">
          <button
            onClick={() => { window.location.href = '/vehicles' }}
            className="rounded p-1 text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Back to vehicles"
          >
            ←
          </button>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">{vehicleTitle}</h1>
            <p className="text-sm text-gray-500 font-mono">{vehicle.rego}</p>
          </div>
        </div>
        <Button size="sm" variant="secondary" onClick={handleRefresh} loading={refreshing}>
          ↻ Refresh from Carjam
        </Button>
      </div>

      {/* Refresh message */}
      {refreshMsg && (
        <div
          className={`mb-4 rounded-md border px-4 py-2 text-sm ${
            refreshMsg.includes('Failed') || refreshMsg.includes('Rate limit')
              ? 'border-red-200 bg-red-50 text-red-700'
              : 'border-green-200 bg-green-50 text-green-700'
          }`}
          role="status"
        >
          {refreshMsg}
        </div>
      )}

      {/* WOF & Rego expiry indicators */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 mb-6">
        <ExpiryBadge expiry={vehicle.wof_expiry} label="WOF Expiry" />
        <ExpiryBadge expiry={vehicle.rego_expiry} label="Registration Expiry" />
      </div>

      {/* Vehicle details */}
      <section className="rounded-lg border border-gray-200 p-4 mb-6">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider">Vehicle Details</h2>
          <div className="flex items-center gap-3">
            {vehicle.lookup_type && (
              <span className="text-xs text-gray-400">Source: {vehicle.lookup_type}</span>
            )}
            {vehicle.last_pulled_at && (
              <span className="text-xs text-gray-400">Last updated: {formatDate(vehicle.last_pulled_at)}</span>
            )}
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-4 text-sm">
          <div>
            <dt className="text-gray-500">Make</dt>
            <dd className="text-gray-900">{vehicle.make || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Model</dt>
            <dd className="text-gray-900">{vehicle.model || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Submodel</dt>
            <dd className="text-gray-900">{vehicle.submodel || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Year</dt>
            <dd className="text-gray-900">{vehicle.year ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Colour</dt>
            <dd className="text-gray-900">{vehicle.colour || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Second Colour</dt>
            <dd className="text-gray-900">{vehicle.second_colour || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Body Type</dt>
            <dd className="text-gray-900">{vehicle.body_type || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Vehicle Type</dt>
            <dd className="text-gray-900">{vehicle.vehicle_type || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Fuel Type</dt>
            <dd className="text-gray-900">{vehicle.fuel_type || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Transmission</dt>
            <dd className="text-gray-900">{vehicle.transmission || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Engine Size</dt>
            <dd className="text-gray-900">{vehicle.engine_size || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Seats</dt>
            <dd className="text-gray-900">{vehicle.seats ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Odometer</dt>
            <dd className="text-gray-900 tabular-nums">
              {vehicle.odometer != null ? vehicle.odometer.toLocaleString('en-NZ') + ' km' : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">Country of Origin</dt>
            <dd className="text-gray-900">{vehicle.country_of_origin || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Number of Owners</dt>
            <dd className="text-gray-900">{vehicle.number_of_owners ?? '—'}</dd>
          </div>
        </dl>
      </section>

      {/* Identification */}
      {(vehicle.vin || vehicle.chassis || vehicle.engine_no) && (
        <section className="rounded-lg border border-gray-200 p-4 mb-6">
          <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-2">Identification</h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 text-sm">
            <div>
              <dt className="text-gray-500">VIN</dt>
              <dd className="text-gray-900 font-mono">{vehicle.vin || '—'}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Chassis</dt>
              <dd className="text-gray-900 font-mono">{vehicle.chassis || '—'}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Engine Number</dt>
              <dd className="text-gray-900 font-mono">{vehicle.engine_no || '—'}</dd>
            </div>
          </dl>
        </section>
      )}

      {/* Tabs: Customers, Odometer History, Service History */}
      <Tabs
        tabs={[
          { id: 'customers', label: `Customers (${vehicle.linked_customers.length})`, content: customersTab },
          { id: 'odometer', label: `Odometer (${odometerHistory.length})`, content: odometerTab },
          { id: 'service', label: `Service History (${vehicle.service_history.length})`, content: serviceTab },
        ]}
        defaultTab="service"
      />

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
