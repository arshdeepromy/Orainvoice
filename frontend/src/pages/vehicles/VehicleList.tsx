import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Spinner, Modal, Pagination, PageSizeSelect } from '../../components/ui'

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
}

const EMPTY_MANUAL_FORM: ManualEntryForm = {
  rego: '', make: '', model: '', year: '', colour: '',
  body_type: '', fuel_type: '', engine_size: '', num_seats: '',
  vin: '', chassis: '', engine_no: '', transmission: '',
  country_of_origin: '', number_of_owners: '', vehicle_type: '',
  submodel: '', second_colour: '', wof_expiry: '', rego_expiry: '',
  odometer: '',
}

const INDICATOR_COLORS: Record<string, string> = {
  green: 'bg-green-100 text-green-800',
  amber: 'bg-yellow-100 text-yellow-800',
  red: 'bg-red-100 text-red-800',
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

  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  /* --- Fetch vehicle list --- */
  const fetchVehicles = useCallback(async (p: number, q: string) => {
    setLoading(true)
    try {
      const params: Record<string, string | number> = { page: p, page_size: pageSize }
      if (q.trim()) params.search = q.trim()
      const res = await apiClient.get<VehicleListResponse>('/vehicles', { params })
      setVehicles(res.data.items)
      setTotal(res.data.total)
    } catch {
      setVehicles([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [])

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
      if (manualForm.wof_expiry.trim()) body.wof_expiry = manualForm.wof_expiry.trim()
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

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Vehicles</h1>
          <p className="text-sm text-gray-500 mt-1">{total} vehicle{total !== 1 ? 's' : ''} linked to your organisation</p>
        </div>
        <Button onClick={openManualEntry}>+ Manual Entry</Button>
      </div>

      {/* Search */}
      <div className="mb-6">
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
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <caption className="sr-only">Vehicles list</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Rego</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Vehicle</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Colour</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">WOF</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Rego Expiry</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Service Due</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Customers</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {vehicles.map((v) => {
                const wofColor = INDICATOR_COLORS[v.wof_indicator] ?? INDICATOR_COLORS.red
                const regoColor = INDICATOR_COLORS[v.rego_indicator] ?? INDICATOR_COLORS.red
                const vehicleDesc = [v.year, v.make, v.model].filter(Boolean).join(' ') || '—'
                return (
                  <tr
                    key={v.id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() => { window.location.href = `/vehicles/${v.id}` }}
                  >
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-mono font-medium text-blue-600">{v.rego}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{vehicleDesc}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{v.colour || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${wofColor}`}>
                        {formatExpiryDate(v.wof_expiry_date)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${regoColor}`}>
                        {formatExpiryDate(v.rego_expiry_date)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      {v.service_due_date ? (() => {
                        const days = Math.ceil((new Date(v.service_due_date).getTime() - Date.now()) / 86400000)
                        const color = days > 60 ? INDICATOR_COLORS.green : days >= 30 ? INDICATOR_COLORS.amber : INDICATOR_COLORS.red
                        return (
                          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${color}`}>
                            {formatExpiryDate(v.service_due_date)}
                          </span>
                        )
                      })() : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">
                      {v.linked_customers.length === 0
                        ? <span className="text-gray-400">—</span>
                        : v.linked_customers.map((c, i) => (
                            <span key={c.id}>
                              {i > 0 && ', '}
                              <button
                                className="text-blue-600 hover:text-blue-800 hover:underline"
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
      )}

      {/* Empty state */}
      {!loading && vehicles.length === 0 && !search.trim() && (
        <div className="py-16 text-center text-sm text-gray-500">
          No vehicles linked to your organisation yet. Use the search on invoices, bookings, or job cards to look up vehicles, or add one manually.
        </div>
      )}

      {/* No search results — offer to onboard */}
      {!loading && vehicles.length === 0 && search.trim() && (
        <div className="py-12 text-center">
          <p className="text-sm text-gray-500 mb-4">
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
            <Button variant="secondary" onClick={() => {
              setManualForm({ ...EMPTY_MANUAL_FORM, rego: search.trim().toUpperCase() })
              setManualOpen(true)
              setManualError('')
            }}>
              + Manual Entry
            </Button>
            {onboardError && (
              <p className="text-sm text-red-600" role="alert">{onboardError}</p>
            )}
          </div>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between">
          <p className="text-sm text-gray-500">
            Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}
          </p>
          <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
        </div>
      )}
      <div className="mt-3 flex justify-end">
        <PageSizeSelect value={pageSize} onChange={(size) => { setPageSize(size); setPage(1) }} />
      </div>

      <Modal open={manualOpen} onClose={() => { setManualOpen(false); setManualError('') }} title="Manual Vehicle Entry">
        <p className="text-sm text-gray-600 mb-3">Enter vehicle details manually when Carjam data is unavailable.</p>
        <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
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
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider pt-2">Identification</p>
          <div className="grid grid-cols-2 gap-3">
            <Input label="VIN" value={manualForm.vin} onChange={(e) => updateManualField('vin', e.target.value)} />
            <Input label="Chassis Number" value={manualForm.chassis} onChange={(e) => updateManualField('chassis', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Engine Number" value={manualForm.engine_no} onChange={(e) => updateManualField('engine_no', e.target.value)} />
            <Input label="Country of Origin" value={manualForm.country_of_origin} onChange={(e) => updateManualField('country_of_origin', e.target.value)} />
          </div>

          {/* Compliance & History */}
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider pt-2">Compliance & History</p>
          <div className="grid grid-cols-2 gap-3">
            <Input label="WOF Expiry" type="date" value={manualForm.wof_expiry} onChange={(e) => updateManualField('wof_expiry', e.target.value)} />
            <Input label="Rego Expiry" type="date" value={manualForm.rego_expiry} onChange={(e) => updateManualField('rego_expiry', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Odometer (km)" type="number" value={manualForm.odometer} onChange={(e) => updateManualField('odometer', e.target.value)} />
            <Input label="Number of Owners" type="number" value={manualForm.number_of_owners} onChange={(e) => updateManualField('number_of_owners', e.target.value)} />
          </div>
        </div>
        {manualError && <p className="mt-2 text-sm text-red-600" role="alert">{manualError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => { setManualOpen(false); setManualError('') }}>Cancel</Button>
          <Button size="sm" onClick={handleManualCreate} loading={manualCreating}>Create Vehicle</Button>
        </div>
      </Modal>
    </div>
  )
}
