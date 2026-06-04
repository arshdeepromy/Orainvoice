/**
 * VehicleList — Task 25 port of frontend/src/pages/vehicles/VehicleList.tsx.
 *
 * ALL logic is copied VERBATIM from the original: the paginated fetch
 * (page/page_size/search) with debounced search (400ms), the WOF/COF/rego/
 * service-due traffic-light indicators, the bulk-refresh-expired flow (confirm
 * → POST /vehicles/bulk-refresh with AbortController + result banner), the
 * CarJam onboard-from-search fallback (POST /vehicles/lookup-with-fallback),
 * the full manual-entry modal (core + identification + compliance fields, WOF/
 * COF inspection-type switch, POST /vehicles/manual), and all navigation. Safe-
 * API consumption is preserved (`res.data?.items ?? []`, `?? 0`).
 *
 * Design reference: OraInvoice_Handoff/app/Vehicles.html. The prototype's
 * column set differs from production (Owner / Odometer / Inspection / Last
 * service); FR-1 wins, so production's columns (Rego / Vehicle / Colour /
 * WOF-COF / Rego Expiry / Service Due / Customers) are preserved and styled in
 * the prototype's language (FR-2b): `page page-wide` head + eyebrow, a card-
 * wrapped token table with uppercase `.mono` heads + hover rows, the `.rego`
 * ink chip for plates, and traffic-light pills mapped onto ok/warn/danger
 * tokens. `.mono` is applied to rego/dates per FR-2. The manual-entry modal has
 * no prototype, so it's designed on the fly with the token system (FR-2b).
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Spinner, Modal, Pagination, PageSizeSelect } from '@/components/ui'
import { getInspectionLabel } from '@/utils/vehicleHelpers'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface LinkedCustomer {
  id: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
}

interface VehicleListItem {
  id: string
  rego: string
  make: string | null
  model: string | null
  year: number | null
  colour: string | null
  body_type: string | null
  fuel_type: string | null
  wof_indicator: 'green' | 'amber' | 'red'
  wof_expiry_date: string | null
  cof_expiry: string | null
  inspection_type: string | null
  rego_indicator: 'green' | 'amber' | 'red'
  rego_expiry_date: string | null
  service_due_date: string | null
  linked_customers: LinkedCustomer[]
}

interface VehicleListResponse {
  items: VehicleListItem[]
  total: number
  page: number
  page_size: number
}

interface BulkRefreshResult {
  vehicle_id: string
  rego: string | null
  status: 'success' | 'not_found' | 'rate_limited' | 'error'
  wof_expiry: string | null
  cof_expiry: string | null
  error: string | null
}

interface BulkRefreshResponse {
  results: BulkRefreshResult[]
  total: number
  succeeded: number
  failed: number
}

interface ManualEntryForm {
  rego: string
  make: string
  model: string
  year: string
  colour: string
  body_type: string
  fuel_type: string
  engine_size: string
  num_seats: string
  // Extended fields (matching CarJam data model)
  vin: string
  chassis: string
  engine_no: string
  transmission: string
  country_of_origin: string
  number_of_owners: string
  vehicle_type: string
  submodel: string
  second_colour: string
  wof_expiry: string
  rego_expiry: string
  odometer: string
  inspection_type: string
  cof_expiry: string
}

const EMPTY_MANUAL_FORM: ManualEntryForm = {
  rego: '', make: '', model: '', year: '', colour: '',
  body_type: '', fuel_type: '', engine_size: '', num_seats: '',
  vin: '', chassis: '', engine_no: '', transmission: '',
  country_of_origin: '', number_of_owners: '', vehicle_type: '',
  submodel: '', second_colour: '', wof_expiry: '', rego_expiry: '',
  odometer: '', inspection_type: 'wof', cof_expiry: '',
}

/** Traffic-light pill classes mapped onto the v2 ok/warn/danger tokens. */
const INDICATOR_COLORS: Record<string, string> = {
  green: 'bg-ok-soft text-ok',
  amber: 'bg-warn-soft text-warn',
  red: 'bg-danger-soft text-danger',
}

function formatExpiryDate(dateStr: string | null): string {
  if (!dateStr) return 'Unknown'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(dateStr))
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function VehicleList() {
  /* Vehicle list state */
  const [vehicles, setVehicles] = useState<VehicleListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

  /* Manual entry modal */
  const [manualOpen, setManualOpen] = useState(false)
  const [manualForm, setManualForm] = useState<ManualEntryForm>(EMPTY_MANUAL_FORM)
  const [manualCreating, setManualCreating] = useState(false)
  const [manualError, setManualError] = useState('')

  /* CarJam onboard from search */
  const [onboardLoading, setOnboardLoading] = useState(false)
  const [onboardError, setOnboardError] = useState('')

  /* Bulk refresh state */
  const [bulkRefreshing, setBulkRefreshing] = useState(false)
  const [bulkRefreshProgress, setBulkRefreshProgress] = useState('')
  const [bulkRefreshBanner, setBulkRefreshBanner] = useState<{ message: string; type: 'success' | 'warning' | 'error' } | null>(null)

  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const bulkRefreshAbortRef = useRef<AbortController | null>(null)

  /* --- Fetch vehicle list --- */
  const fetchVehicles = useCallback(async (p: number, q: string) => {
    setLoading(true)
    try {
      const params: Record<string, string | number> = { page: p, page_size: pageSize }
      if (q.trim()) params.search = q.trim()
      const res = await apiClient.get<VehicleListResponse>('/vehicles', { params })
      setVehicles(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
    } catch {
      setVehicles([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [pageSize])

  useEffect(() => { fetchVehicles(page, search) }, [page, pageSize, fetchVehicles]) // eslint-disable-line react-hooks/exhaustive-deps

  /* Debounced search */
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(1)
      fetchVehicles(1, search)
    }, 400)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [search, fetchVehicles])

  /* --- Manual entry --- */
  const openManualEntry = () => {
    setManualForm(EMPTY_MANUAL_FORM)
    setManualOpen(true)
    setManualError('')
  }

  const handleManualCreate = async () => {
    if (!manualForm.rego.trim()) { setManualError('Registration number is required.'); return }
    setManualCreating(true)
    setManualError('')
    try {
      const body: Record<string, string | number | undefined> = { rego: manualForm.rego.trim().toUpperCase() }
      if (manualForm.make.trim()) body.make = manualForm.make.trim()
      if (manualForm.model.trim()) body.model = manualForm.model.trim()
      if (manualForm.year.trim()) body.year = parseInt(manualForm.year, 10)
      if (manualForm.colour.trim()) body.colour = manualForm.colour.trim()
      if (manualForm.body_type.trim()) body.body_type = manualForm.body_type.trim()
      if (manualForm.fuel_type.trim()) body.fuel_type = manualForm.fuel_type.trim()
      if (manualForm.engine_size.trim()) body.engine_size = manualForm.engine_size.trim()
      if (manualForm.num_seats.trim()) body.num_seats = parseInt(manualForm.num_seats, 10)
      // Extended fields
      if (manualForm.vin.trim()) body.vin = manualForm.vin.trim()
      if (manualForm.chassis.trim()) body.chassis = manualForm.chassis.trim()
      if (manualForm.engine_no.trim()) body.engine_no = manualForm.engine_no.trim()
      if (manualForm.transmission.trim()) body.transmission = manualForm.transmission.trim()
      if (manualForm.country_of_origin.trim()) body.country_of_origin = manualForm.country_of_origin.trim()
      if (manualForm.number_of_owners.trim()) body.number_of_owners = parseInt(manualForm.number_of_owners, 10)
      if (manualForm.vehicle_type.trim()) body.vehicle_type = manualForm.vehicle_type.trim()
      if (manualForm.submodel.trim()) body.submodel = manualForm.submodel.trim()
      if (manualForm.second_colour.trim()) body.second_colour = manualForm.second_colour.trim()
      if (manualForm.inspection_type === 'cof' && manualForm.cof_expiry.trim()) {
        body.cof_expiry = manualForm.cof_expiry.trim()
        body.inspection_type = 'cof'
      } else {
        if (manualForm.wof_expiry.trim()) body.wof_expiry = manualForm.wof_expiry.trim()
        body.inspection_type = 'wof'
      }
      if (manualForm.rego_expiry.trim()) body.rego_expiry = manualForm.rego_expiry.trim()
      if (manualForm.odometer.trim()) body.odometer = parseInt(manualForm.odometer, 10)
      const res = await apiClient.post<{ id: string }>('/vehicles/manual', body)
      setManualOpen(false)
      window.location.href = `/vehicles/${res.data.id}`
    } catch { setManualError('Failed to create vehicle. Please try again.') }
    finally { setManualCreating(false) }
  }

  const updateManualField = (field: keyof ManualEntryForm, value: string) => {
    setManualForm((prev) => ({ ...prev, [field]: value }))
  }

  /* --- Bulk refresh expired vehicles --- */
  const expiredVehicles = vehicles.filter((v) => v.wof_indicator === 'red')
  const expiredCount = expiredVehicles.length

  const handleBulkRefresh = async () => {
    if (expiredCount === 0) return
    const confirmed = window.confirm(
      `Refresh ${expiredCount} expired vehicle${expiredCount !== 1 ? 's' : ''} via CarJam? This will use ${expiredCount} CarJam lookup${expiredCount !== 1 ? 's' : ''}.`
    )
    if (!confirmed) return

    setBulkRefreshing(true)
    setBulkRefreshBanner(null)
    setBulkRefreshProgress(`Refreshing... 0/${expiredCount} complete`)

    const controller = new AbortController()
    bulkRefreshAbortRef.current = controller

    try {
      const vehicleIds = expiredVehicles.map((v) => v.id)
      const res = await apiClient.post<BulkRefreshResponse>(
        '/vehicles/bulk-refresh',
        { vehicle_ids: vehicleIds },
        { signal: controller.signal }
      )

      const data = res.data
      const succeeded = data?.succeeded ?? 0
      const total = data?.total ?? 0
      const failed = data?.failed ?? 0

      if (failed === 0) {
        setBulkRefreshBanner({
          message: `Refreshed ${succeeded}/${total} vehicles successfully.`,
          type: 'success',
        })
      } else {
        const rateLimited = (data?.results ?? []).some((r) => r.status === 'rate_limited')
        setBulkRefreshBanner({
          message: `Refreshed ${succeeded}/${total} vehicles. ${failed} failed.${rateLimited ? ' Rate limited — try again later.' : ''}`,
          type: failed === total ? 'error' : 'warning',
        })
      }

      // Reload the vehicle list
      await fetchVehicles(page, search)
    } catch {
      if (controller.signal.aborted) return
      setBulkRefreshBanner({
        message: 'Bulk refresh failed. Please try again.',
        type: 'error',
      })
    } finally {
      setBulkRefreshing(false)
      setBulkRefreshProgress('')
      bulkRefreshAbortRef.current = null
    }
  }

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => { bulkRefreshAbortRef.current?.abort() }
  }, [])

  const totalPages = Math.ceil(total / pageSize)

  const TH = 'mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

  return (
    <div className="page page-wide">
      {/* Header */}
      <div className="page-head">
        <div>
          <div className="eyebrow">Automotive</div>
          <h1>Vehicles</h1>
          <p className="sub"><span className="mono">{total}</span> vehicle{total !== 1 ? 's' : ''} linked to your organisation</p>
        </div>
        <div className="head-actions flex items-center gap-2">
          {expiredCount > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleBulkRefresh}
              loading={bulkRefreshing}
              disabled={bulkRefreshing}
            >
              {bulkRefreshing
                ? (bulkRefreshProgress || 'Refreshing...')
                : `↻ Refresh Expired (${expiredCount})`
              }
            </Button>
          )}
          <Button
            size="sm"
            leftIcon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" />
              </svg>
            }
            onClick={openManualEntry}
          >
            Manual Entry
          </Button>
        </div>
      </div>

      {/* Bulk refresh result banner */}
      {bulkRefreshBanner && (
        <div
          className={`mb-4 flex items-center justify-between rounded-ctl border px-4 py-3 text-[13px] ${
            bulkRefreshBanner.type === 'success'
              ? 'border-ok/30 bg-ok-soft text-ok'
              : bulkRefreshBanner.type === 'warning'
              ? 'border-warn/30 bg-warn-soft text-warn'
              : 'border-danger/30 bg-danger-soft text-danger'
          }`}
          role="status"
        >
          <span>{bulkRefreshBanner.message}</span>
          <button
            onClick={() => setBulkRefreshBanner(null)}
            className="ml-3 text-lg leading-none opacity-60 hover:opacity-100"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      {/* Search */}
      <div className="mb-6 max-w-[340px]">
        <Input
          label="Search vehicles"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search vehicles by rego, make, or model"
        />
      </div>

      {/* Loading */}
      {loading && <div className="py-12"><Spinner label="Loading vehicles" /></div>}

      {/* Vehicle table */}
      {!loading && vehicles.length > 0 && (
        <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <caption className="sr-only">Vehicles list</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Rego</th>
                  <th scope="col" className={TH}>Vehicle</th>
                  <th scope="col" className={TH}>Colour</th>
                  <th scope="col" className={TH}>WOF/COF</th>
                  <th scope="col" className={TH}>Rego Expiry</th>
                  <th scope="col" className={TH}>Service Due</th>
                  <th scope="col" className={TH}>Customers</th>
                </tr>
              </thead>
              <tbody>
                {vehicles.map((v) => {
                  const wofColor = INDICATOR_COLORS[v.wof_indicator] ?? INDICATOR_COLORS.red
                  const regoColor = INDICATOR_COLORS[v.rego_indicator] ?? INDICATOR_COLORS.red
                  const vehicleDesc = [v.year, v.make, v.model].filter(Boolean).join(' ') || '—'
                  return (
                    <tr
                      key={v.id}
                      className="cursor-pointer border-b border-border transition-colors last:border-b-0 hover:bg-canvas"
                      onClick={() => { window.location.href = `/vehicles/${v.id}` }}
                    >
                      <td className="whitespace-nowrap px-5 py-3">
                        <span className="mono inline-block rounded-md bg-ink px-2.5 py-[3px] text-[12px] font-semibold tracking-[0.04em] text-white">{v.rego}</span>
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-[13.5px] text-text">{vehicleDesc}</td>
                      <td className="whitespace-nowrap px-5 py-3 text-[13.5px] text-muted">{v.colour || '—'}</td>
                      <td className="whitespace-nowrap px-5 py-3 text-[13px]">
                        <span className={`mono inline-flex items-center rounded-full px-2.5 py-0.5 text-[12px] font-medium ${wofColor}`}>
                          {getInspectionLabel(v)}: {formatExpiryDate(v.inspection_type === 'cof' ? (v.cof_expiry ?? null) : (v.wof_expiry_date ?? null))}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-[13px]">
                        <span className={`mono inline-flex items-center rounded-full px-2.5 py-0.5 text-[12px] font-medium ${regoColor}`}>
                          {formatExpiryDate(v.rego_expiry_date)}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-[13px]">
                        {v.service_due_date ? (() => {
                          const days = Math.ceil((new Date(v.service_due_date).getTime() - Date.now()) / 86400000)
                          const color = days > 60 ? INDICATOR_COLORS.green : days >= 30 ? INDICATOR_COLORS.amber : INDICATOR_COLORS.red
                          return (
                            <span className={`mono inline-flex items-center rounded-full px-2.5 py-0.5 text-[12px] font-medium ${color}`}>
                              {formatExpiryDate(v.service_due_date)}
                            </span>
                          )
                        })() : <span className="text-muted-2">—</span>}
                      </td>
                      <td className="px-5 py-3 text-[13.5px] text-muted">
                        {v.linked_customers.length === 0
                          ? <span className="text-muted-2">—</span>
                          : v.linked_customers.map((c, i) => (
                              <span key={c.id}>
                                {i > 0 && ', '}
                                <button
                                  className="text-accent hover:text-accent-press hover:underline"
                                  onClick={(e) => { e.stopPropagation(); window.location.href = `/customers/${c.id}` }}
                                >
                                  {c.first_name} {c.last_name}
                                </button>
                              </span>
                            ))
                        }
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Empty state */}
      {!loading && vehicles.length === 0 && !search.trim() && (
        <div className="py-16 text-center text-[13px] text-muted">
          No vehicles linked to your organisation yet. Use the search on invoices, bookings, or job cards to look up vehicles, or add one manually.
        </div>
      )}

      {/* No search results — offer to onboard */}
      {!loading && vehicles.length === 0 && search.trim() && (
        <div className="py-12 text-center">
          <p className="mb-4 text-[13px] text-muted">
            No vehicles found matching "{search}".
          </p>
          <div className="flex flex-col items-center gap-3">
            <Button
              onClick={async () => {
                const cleaned = search.trim().toUpperCase()
                if (!cleaned) return
                setOnboardLoading(true)
                setOnboardError('')
                try {
                  const res = await apiClient.post<{
                    success: boolean
                    vehicle: { id: string }
                    message: string
                  }>('/vehicles/lookup-with-fallback', { rego: cleaned })
                  if (res.data.success && res.data.vehicle) {
                    window.location.href = `/vehicles/${res.data.vehicle.id}`
                  }
                } catch (err: any) {
                  const status = err?.response?.status
                  if (status === 404) {
                    setOnboardError('Vehicle not found in CarJam. Try manual entry instead.')
                  } else if (status === 429) {
                    setOnboardError('Rate limit exceeded. Please try again shortly.')
                  } else {
                    setOnboardError('Lookup failed. Please try again or use manual entry.')
                  }
                } finally {
                  setOnboardLoading(false)
                }
              }}
              loading={onboardLoading}
            >
              🔍 Look up "{search.trim().toUpperCase()}" via CarJam
            </Button>
            <Button variant="ghost" onClick={() => {
              setManualForm({ ...EMPTY_MANUAL_FORM, rego: search.trim().toUpperCase() })
              setManualOpen(true)
              setManualError('')
            }}>
              + Manual Entry
            </Button>
            {onboardError && (
              <p className="text-[13px] text-danger" role="alert">{onboardError}</p>
            )}
          </div>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between">
          <p className="text-[12.5px] text-muted">
            Showing <span className="mono text-text">{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)}</span> of <span className="mono text-text">{total}</span>
          </p>
          <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
        </div>
      )}
      <div className="mt-3 flex justify-end">
        <PageSizeSelect value={pageSize} onChange={(size) => { setPageSize(size); setPage(1) }} />
      </div>

      <Modal open={manualOpen} onClose={() => { setManualOpen(false); setManualError('') }} title="Manual Vehicle Entry">
        <p className="mb-3 text-[13px] text-muted">Enter vehicle details manually when Carjam data is unavailable.</p>
        <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
          {/* Core fields */}
          <Input label="Registration number *" value={manualForm.rego} onChange={(e) => updateManualField('rego', e.target.value)} />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Make" value={manualForm.make} onChange={(e) => updateManualField('make', e.target.value)} />
            <Input label="Model" value={manualForm.model} onChange={(e) => updateManualField('model', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Submodel / Variant" value={manualForm.submodel} onChange={(e) => updateManualField('submodel', e.target.value)} />
            <Input label="Year" type="number" value={manualForm.year} onChange={(e) => updateManualField('year', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Colour" value={manualForm.colour} onChange={(e) => updateManualField('colour', e.target.value)} />
            <Input label="Second Colour" value={manualForm.second_colour} onChange={(e) => updateManualField('second_colour', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Body Type" value={manualForm.body_type} onChange={(e) => updateManualField('body_type', e.target.value)} />
            <Input label="Vehicle Type" value={manualForm.vehicle_type} onChange={(e) => updateManualField('vehicle_type', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Fuel Type" value={manualForm.fuel_type} onChange={(e) => updateManualField('fuel_type', e.target.value)} />
            <Input label="Transmission" value={manualForm.transmission} onChange={(e) => updateManualField('transmission', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Engine Size" value={manualForm.engine_size} onChange={(e) => updateManualField('engine_size', e.target.value)} />
            <Input label="Seats" type="number" value={manualForm.num_seats} onChange={(e) => updateManualField('num_seats', e.target.value)} />
          </div>

          {/* Identification */}
          <p className="mono pt-2 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-2">Identification</p>
          <div className="grid grid-cols-2 gap-3">
            <Input label="VIN" value={manualForm.vin} onChange={(e) => updateManualField('vin', e.target.value)} />
            <Input label="Chassis Number" value={manualForm.chassis} onChange={(e) => updateManualField('chassis', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Engine Number" value={manualForm.engine_no} onChange={(e) => updateManualField('engine_no', e.target.value)} />
            <Input label="Country of Origin" value={manualForm.country_of_origin} onChange={(e) => updateManualField('country_of_origin', e.target.value)} />
          </div>

          {/* Compliance & History */}
          <p className="mono pt-2 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-2">Compliance & History</p>
          <div className="flex flex-col gap-[7px]">
            <label htmlFor="manual-inspection-type" className="text-[12.5px] font-medium text-text">Inspection Type</label>
            <select
              id="manual-inspection-type"
              value={manualForm.inspection_type}
              onChange={(e) => updateManualField('inspection_type', e.target.value)}
              className="h-[42px] w-full appearance-none rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            >
              <option value="wof">WOF (Warrant of Fitness)</option>
              <option value="cof">COF (Certificate of Fitness)</option>
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {manualForm.inspection_type === 'cof' ? (
              <Input label="COF Expiry" type="date" value={manualForm.cof_expiry} onChange={(e) => updateManualField('cof_expiry', e.target.value)} />
            ) : (
              <Input label="WOF Expiry" type="date" value={manualForm.wof_expiry} onChange={(e) => updateManualField('wof_expiry', e.target.value)} />
            )}
            <Input label="Rego Expiry" type="date" value={manualForm.rego_expiry} onChange={(e) => updateManualField('rego_expiry', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Odometer (km)" type="number" value={manualForm.odometer} onChange={(e) => updateManualField('odometer', e.target.value)} />
            <Input label="Number of Owners" type="number" value={manualForm.number_of_owners} onChange={(e) => updateManualField('number_of_owners', e.target.value)} />
          </div>
        </div>
        {manualError && <p className="mt-2 text-[12.5px] text-danger" role="alert">{manualError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => { setManualOpen(false); setManualError('') }}>Cancel</Button>
          <Button size="sm" onClick={handleManualCreate} loading={manualCreating}>Create Vehicle</Button>
        </div>
      </Modal>
    </div>
  )
}
