/**
 * VehicleProfile — Task 25 port of frontend/src/pages/vehicles/VehicleProfile.tsx.
 *
 * ALL logic is copied VERBATIM from the original: the profile fetch
 * (GET /vehicles/:id), the refresh-from-CarJam action (POST /vehicles/:id/
 * refresh with 429 handling), the WOF/COF + rego expiry indicator badges, the
 * embedded module-gated PpsrCard, the vehicle-details + identification grids,
 * the three tabs (Linked Customers / Odometer History / Service History), the
 * service-history period filter + Print Report (blob → print) + Email-to-
 * Customer modal (with recipient fallback + toasts), and all navigation. NZD /
 * date formatting is preserved.
 *
 * Design: VehicleProfile has no dedicated prototype, so the surface is designed
 * on the fly (FR-2b) in the v2 language — `page page-wide`-style padding, the
 * `.rego`-style mono subtitle, token cards/grids, Tabs primitive, and Badge
 * status pills (the original's `warning`/`error` variants map to v2 `warn`/
 * `danger`). `.mono` is applied to numbers/IDs/dates per FR-2.
 */

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Badge, Spinner, Tabs, Modal, Input, ToastContainer, useToast } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { getInspectionLabel } from '@/utils/vehicleHelpers'
import { PpsrCard } from './components/PpsrCard'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

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
  cof_expiry: ExpiryIndicator
  inspection_type: string | null
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
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(dateStr))
}

/* Original used success/warning/error/info/neutral; v2 Badge uses warn/danger
   for warning/error — mapped here 1:1. */
const INDICATOR_BADGE: Record<string, { label: string; variant: BadgeVariant }> = {
  green: { label: 'OK', variant: 'success' },
  amber: { label: 'Due Soon', variant: 'warn' },
  red: { label: 'Expired / Due', variant: 'danger' },
}

const INVOICE_STATUS_CONFIG: Record<string, { label: string; variant: BadgeVariant }> = {
  draft: { label: 'Draft', variant: 'neutral' },
  issued: { label: 'Issued', variant: 'info' },
  partially_paid: { label: 'Partially Paid', variant: 'warn' },
  paid: { label: 'Paid', variant: 'success' },
  overdue: { label: 'Overdue', variant: 'danger' },
  voided: { label: 'Voided', variant: 'neutral' },
}

function ExpiryBadge({ expiry, label }: { expiry: ExpiryIndicator; label: string }) {
  const cfg = INDICATOR_BADGE[expiry.indicator] ?? INDICATOR_BADGE.red
  // For red indicator, distinguish between expired (past) and expiring soon (future)
  const badgeLabel = expiry.indicator === 'red' && expiry.days_remaining != null && expiry.days_remaining >= 0
    ? 'Expiring Soon'
    : cfg.label
  const dateStr = expiry.date ? formatDate(expiry.date) : 'Unknown'
  const daysText = expiry.days_remaining != null
    ? expiry.days_remaining >= 0
      ? `${expiry.days_remaining}d remaining`
      : `${Math.abs(expiry.days_remaining)}d overdue`
    : ''

  return (
    <div className="rounded-card border border-border p-4">
      <p className="mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">{label}</p>
      <div className="mt-1 flex items-center gap-2">
        <Badge variant={cfg.variant}>{badgeLabel}</Badge>
        <span className="mono text-[13.5px] text-text">{dateStr}</span>
      </div>
      {daysText && <p className="mt-0.5 text-[12px] text-muted">{daysText}</p>}
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
      <div className="page page-wide">
        <div className="rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">
          {error || 'Vehicle not found.'}
        </div>
        <Button variant="ghost" className="mt-4" onClick={() => { window.location.href = '/vehicles' }}>
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

  const TH = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

  /* ---- Tab: Linked Customers ---- */
  const customersTab = (
    <div>
      {vehicle.linked_customers.length === 0 ? (
        <p className="text-[13px] text-muted">No customers linked to this vehicle.</p>
      ) : (
        <div className="overflow-hidden rounded-card border border-border">
          <table className="w-full border-collapse">
            <caption className="sr-only">Linked customers</caption>
            <thead>
              <tr>
                <th scope="col" className={TH}>Name</th>
                <th scope="col" className={TH}>Email</th>
                <th scope="col" className={TH}>Phone</th>
              </tr>
            </thead>
            <tbody>
              {vehicle.linked_customers.map((c) => (
                <tr
                  key={c.id}
                  className="cursor-pointer border-b border-border transition-colors last:border-b-0 hover:bg-canvas"
                  onClick={() => { window.location.href = `/customers/${c.id}` }}
                >
                  <td className="whitespace-nowrap px-4 py-3 text-[13.5px] font-medium text-accent">
                    {c.first_name} {c.last_name}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{c.email || '—'}</td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{c.phone || '—'}</td>
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
        <p className="text-[13px] text-muted">No odometer readings recorded.</p>
      ) : (
        <div className="overflow-hidden rounded-card border border-border">
          <table className="w-full border-collapse">
            <caption className="sr-only">Odometer history</caption>
            <thead>
              <tr>
                <th scope="col" className={TH}>Date</th>
                <th scope="col" className={TH}>Invoice</th>
                <th scope="col" className={`${TH} text-right`}>Odometer</th>
              </tr>
            </thead>
            <tbody>
              {odometerHistory.map((entry, idx) => (
                <tr key={idx} className="border-b border-border transition-colors last:border-b-0 hover:bg-canvas">
                  <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{formatDate(entry.date)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-[13.5px]">
                    <button
                      onClick={() => { window.location.href = `/invoices/${entry.invoice_id}` }}
                      className="mono rounded text-accent hover:text-accent-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      {entry.invoice_number || 'Draft'}
                    </button>
                  </td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-text">
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
        <p className="text-[13px] text-muted">No service history for this vehicle.</p>
      ) : (
        <>
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <label className="text-[13px] text-muted">Period:</label>
              <select value={reportRange} onChange={e => setReportRange(e.target.value as any)}
                className="rounded-ctl border border-border bg-card px-2 py-1 text-[13px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
                <option value="1">Last 1 Year</option>
                <option value="2">Last 2 Years</option>
                <option value="3">Last 3 Years</option>
                <option value="all">All Time</option>
              </select>
              <span className="text-[13px] text-muted-2">{filterByRange(vehicle.service_history, reportRange).length} records</span>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={printServiceReport} loading={printLoading} disabled={printLoading}>Print Report</Button>
              <Button variant="ghost" size="sm" onClick={() => { setEmailRange(reportRange === 'all' ? '1' : reportRange); setEmailMsg(''); setRecipientEmail(''); setEmailModalOpen(true) }}>
                Email to Customer
              </Button>
            </div>
          </div>
          <div className="overflow-hidden rounded-card border border-border">
            <table className="w-full border-collapse">
              <caption className="sr-only">Service history</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Invoice</th>
                  <th scope="col" className={TH}>Status</th>
                  <th scope="col" className={TH}>Date</th>
                  <th scope="col" className={TH}>Customer</th>
                  <th scope="col" className={`${TH} text-right`}>Odometer</th>
                  <th scope="col" className={`${TH} text-right`}>Total</th>
                </tr>
              </thead>
              <tbody>
                {filterByRange(vehicle.service_history, reportRange).map((s) => {
                  const cfg = INVOICE_STATUS_CONFIG[s.status] ?? { label: s.status, variant: 'neutral' as BadgeVariant }
                  return (
                    <tr key={s.invoice_id} className="cursor-pointer border-b border-border transition-colors last:border-b-0 hover:bg-canvas" onClick={() => { window.location.href = `/invoices/${s.invoice_id}` }}>
                      <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] font-medium text-accent">{s.invoice_number || <span className="italic text-muted-2">Draft</span>}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-[13px]"><Badge variant={cfg.variant}>{cfg.label}</Badge></td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{formatDate(s.issue_date)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-text">{s.customer_name}</td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-text">{s.odometer != null ? s.odometer.toLocaleString('en-NZ') + ' km' : '—'}</td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-text">{formatNZD(s.total)}</td>
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
          <p className="text-[13px] text-muted">Send a service history report for {vehicle.rego} to the linked customer.</p>
          {vehicle.linked_customers.length > 0 && vehicle.linked_customers[0].email ? (
            <div className="rounded-ctl border border-border bg-canvas px-3 py-2 text-[13px]">
              <span className="text-muted">To:</span> <span className="font-medium text-text">{vehicle.linked_customers[0].first_name} {vehicle.linked_customers[0].last_name}</span>
              <span className="ml-2 text-muted">{vehicle.linked_customers[0].email}</span>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="rounded-ctl border border-warn/30 bg-warn-soft px-3 py-2 text-[13px] text-warn">No customer email found for this vehicle. Please enter a recipient email below.</div>
              <Input
                label="Recipient Email"
                type="email"
                placeholder="customer@example.com"
                value={recipientEmail}
                onChange={e => setRecipientEmail(e.target.value)}
              />
            </div>
          )}
          <div className="flex flex-col gap-[7px]">
            <label htmlFor="email-range" className="text-[12.5px] font-medium text-text">Date Range</label>
            <select id="email-range" value={emailRange} onChange={e => setEmailRange(e.target.value as any)}
              className="h-[42px] w-full appearance-none rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
              <option value="1">Last 1 Year</option>
              <option value="2">Last 2 Years</option>
              <option value="3">Last 3 Years</option>
              <option value="all">All Time</option>
            </select>
          </div>
          {emailMsg && <p className="text-[13px] text-danger" role="alert">{emailMsg}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setEmailModalOpen(false)}>Cancel</Button>
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
    <div className="page page-wide">
      {/* Header */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => { window.location.href = '/vehicles' }}
            className="rounded p-1 text-muted-2 transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label="Back to vehicles"
          >
            ←
          </button>
          <div>
            <h1 className="text-[22px] font-semibold text-text">{vehicleTitle}</h1>
            <p className="mono text-[13px] text-muted">{vehicle.rego}</p>
          </div>
        </div>
        <Button size="sm" variant="ghost" onClick={handleRefresh} loading={refreshing}>
          ↻ Refresh from Carjam
        </Button>
      </div>

      {/* Refresh message */}
      {refreshMsg && (
        <div
          className={`mb-4 rounded-ctl border px-4 py-2 text-[13px] ${
            refreshMsg.includes('Failed') || refreshMsg.includes('Rate limit')
              ? 'border-danger/30 bg-danger-soft text-danger'
              : 'border-ok/30 bg-ok-soft text-ok'
          }`}
          role="status"
        >
          {refreshMsg}
        </div>
      )}

      {/* WOF/COF & Rego expiry indicators */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <ExpiryBadge expiry={vehicle.inspection_type === 'cof' ? vehicle.cof_expiry : vehicle.wof_expiry} label={getInspectionLabel(vehicle)} />
        <ExpiryBadge expiry={vehicle.rego_expiry} label="Registration Expiry" />
      </div>

      {/* PPSR — module-gated; renders nothing when the module is disabled */}
      <div className="mb-6">
        <PpsrCard rego={vehicle.rego} />
      </div>

      {/* Vehicle details */}
      <section className="mb-6 rounded-card border border-border p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Vehicle Details</h2>
          <div className="flex items-center gap-3">
            {vehicle.lookup_type && (
              <span className="text-[12px] text-muted-2">Source: {vehicle.lookup_type}</span>
            )}
            {vehicle.last_pulled_at && (
              <span className="text-[12px] text-muted-2">Last updated: {formatDate(vehicle.last_pulled_at)}</span>
            )}
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13.5px] sm:grid-cols-3 lg:grid-cols-4">
          <div><dt className="text-muted">Make</dt><dd className="text-text">{vehicle.make || '—'}</dd></div>
          <div><dt className="text-muted">Model</dt><dd className="text-text">{vehicle.model || '—'}</dd></div>
          <div><dt className="text-muted">Submodel</dt><dd className="text-text">{vehicle.submodel || '—'}</dd></div>
          <div><dt className="text-muted">Year</dt><dd className="text-text">{vehicle.year ?? '—'}</dd></div>
          <div><dt className="text-muted">Colour</dt><dd className="text-text">{vehicle.colour || '—'}</dd></div>
          <div><dt className="text-muted">Second Colour</dt><dd className="text-text">{vehicle.second_colour || '—'}</dd></div>
          <div><dt className="text-muted">Body Type</dt><dd className="text-text">{vehicle.body_type || '—'}</dd></div>
          <div><dt className="text-muted">Vehicle Type</dt><dd className="text-text">{vehicle.vehicle_type || '—'}</dd></div>
          <div><dt className="text-muted">Fuel Type</dt><dd className="text-text">{vehicle.fuel_type || '—'}</dd></div>
          <div><dt className="text-muted">Transmission</dt><dd className="text-text">{vehicle.transmission || '—'}</dd></div>
          <div><dt className="text-muted">Engine Size</dt><dd className="text-text">{vehicle.engine_size || '—'}</dd></div>
          <div><dt className="text-muted">Seats</dt><dd className="text-text">{vehicle.seats ?? '—'}</dd></div>
          <div><dt className="text-muted">Odometer</dt><dd className="mono text-text">{vehicle.odometer != null ? vehicle.odometer.toLocaleString('en-NZ') + ' km' : '—'}</dd></div>
          <div><dt className="text-muted">Country of Origin</dt><dd className="text-text">{vehicle.country_of_origin || '—'}</dd></div>
          <div><dt className="text-muted">Number of Owners</dt><dd className="text-text">{vehicle.number_of_owners ?? '—'}</dd></div>
        </dl>
      </section>

      {/* Identification */}
      {(vehicle.vin || vehicle.chassis || vehicle.engine_no) && (
        <section className="mb-6 rounded-card border border-border p-4">
          <h2 className="mono mb-2 text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Identification</h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13.5px] sm:grid-cols-3">
            <div><dt className="text-muted">VIN</dt><dd className="mono text-text">{vehicle.vin || '—'}</dd></div>
            <div><dt className="text-muted">Chassis</dt><dd className="mono text-text">{vehicle.chassis || '—'}</dd></div>
            <div><dt className="text-muted">Engine Number</dt><dd className="mono text-text">{vehicle.engine_no || '—'}</dd></div>
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
