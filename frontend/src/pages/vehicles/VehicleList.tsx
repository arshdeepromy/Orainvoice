import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Spinner, Badge, Modal } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface VehicleLookupResult {
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
  wof_expiry: string | null
  rego_expiry: string | null
  odometer: number | null
  last_pulled_at: string
  source: string
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
}

const EMPTY_MANUAL_FORM: ManualEntryForm = {
  rego: '',
  make: '',
  model: '',
  year: '',
  colour: '',
  body_type: '',
  fuel_type: '',
  engine_size: '',
  num_seats: '',
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function VehicleList() {
  const [searchRego, setSearchRego] = useState('')
  const [lookupResult, setLookupResult] = useState<VehicleLookupResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notFound, setNotFound] = useState(false)
  const [notFoundRego, setNotFoundRego] = useState('')

  /* Manual entry modal */
  const [manualOpen, setManualOpen] = useState(false)
  const [manualForm, setManualForm] = useState<ManualEntryForm>(EMPTY_MANUAL_FORM)
  const [manualCreating, setManualCreating] = useState(false)
  const [manualError, setManualError] = useState('')

  const debounceRef = useRef<ReturnType<typeof setTimeout>>()
  const abortRef = useRef<AbortController>()

  /* --- Lookup vehicle by rego --- */
  const lookupVehicle = useCallback(async (rego: string) => {
    const cleaned = rego.trim().toUpperCase()
    if (cleaned.length < 2) {
      setLookupResult(null)
      setNotFound(false)
      setError('')
      return
    }

    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError('')
    setNotFound(false)
    setLookupResult(null)

    try {
      const res = await apiClient.get<VehicleLookupResult>(`/vehicles/lookup/${encodeURIComponent(cleaned)}`, {
        signal: controller.signal,
      })
      setLookupResult(res.data)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      const axiosErr = err as { response?: { status?: number; data?: { suggest_manual_entry?: boolean; rego?: string } } }
      if (axiosErr.response?.status === 404 && axiosErr.response.data?.suggest_manual_entry) {
        setNotFound(true)
        setNotFoundRego(axiosErr.response.data.rego || cleaned)
      } else if (axiosErr.response?.status === 429) {
        setError('Rate limit exceeded. Please try again shortly.')
      } else {
        setError('Failed to look up vehicle. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  /* --- Debounced search --- */
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      lookupVehicle(searchRego)
    }, 400)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchRego, lookupVehicle])

  /* --- Open manual entry with pre-filled rego --- */
  const openManualEntry = (rego?: string) => {
    setManualForm({ ...EMPTY_MANUAL_FORM, rego: rego || searchRego.trim().toUpperCase() })
    setManualOpen(true)
    setManualError('')
  }

  /* --- Submit manual entry --- */
  const handleManualCreate = async () => {
    if (!manualForm.rego.trim()) {
      setManualError('Registration number is required.')
      return
    }
    setManualCreating(true)
    setManualError('')
    try {
      const body: Record<string, string | number | undefined> = {
        rego: manualForm.rego.trim().toUpperCase(),
      }
      if (manualForm.make.trim()) body.make = manualForm.make.trim()
      if (manualForm.model.trim()) body.model = manualForm.model.trim()
      if (manualForm.year.trim()) body.year = parseInt(manualForm.year, 10)
      if (manualForm.colour.trim()) body.colour = manualForm.colour.trim()
      if (manualForm.body_type.trim()) body.body_type = manualForm.body_type.trim()
      if (manualForm.fuel_type.trim()) body.fuel_type = manualForm.fuel_type.trim()
      if (manualForm.engine_size.trim()) body.engine_size = manualForm.engine_size.trim()
      if (manualForm.num_seats.trim()) body.num_seats = parseInt(manualForm.num_seats, 10)

      const res = await apiClient.post<{ id: string }>('/vehicles/manual', body)
      setManualOpen(false)
      setManualForm(EMPTY_MANUAL_FORM)
      window.location.href = `/vehicles/${res.data.id}`
    } catch {
      setManualError('Failed to create vehicle. Please try again.')
    } finally {
      setManualCreating(false)
    }
  }

  const updateManualField = (field: keyof ManualEntryForm, value: string) => {
    setManualForm((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Vehicles</h1>
        <Button onClick={() => openManualEntry('')}>+ Manual Entry</Button>
      </div>

      {/* Search by rego */}
      <div className="mb-6">
        <Input
          label="Search by registration number"
          placeholder="Enter rego (e.g. ABC123)…"
          value={searchRego}
          onChange={(e) => setSearchRego(e.target.value)}
          aria-label="Search vehicles by registration number"
        />
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="py-12"><Spinner label="Looking up vehicle" /></div>
      )}

      {/* Not found — suggest manual entry */}
      {!loading && notFound && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-center">
          <p className="text-sm text-amber-800 mb-3">
            No vehicle found for registration <span className="font-mono font-medium">{notFoundRego}</span>.
          </p>
          <Button size="sm" onClick={() => openManualEntry(notFoundRego)}>
            Enter Details Manually
          </Button>
        </div>
      )}

      {/* Lookup result */}
      {!loading && lookupResult && (
        <div className="rounded-lg border border-gray-200 p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between mb-4">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">
                {[lookupResult.year, lookupResult.make, lookupResult.model].filter(Boolean).join(' ') || 'Unknown Vehicle'}
              </h2>
              <p className="text-sm text-gray-500 font-mono">{lookupResult.rego}</p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={lookupResult.source === 'cache' ? 'info' : 'success'}>
                {lookupResult.source === 'cache' ? 'Cached' : 'Carjam'}
              </Badge>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => { window.location.href = `/vehicles/${lookupResult.id}` }}
              >
                View Profile
              </Button>
            </div>
          </div>

          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-4 text-sm">
            <div>
              <dt className="text-gray-500">Colour</dt>
              <dd className="text-gray-900">{lookupResult.colour || '—'}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Body Type</dt>
              <dd className="text-gray-900">{lookupResult.body_type || '—'}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Fuel Type</dt>
              <dd className="text-gray-900">{lookupResult.fuel_type || '—'}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Engine Size</dt>
              <dd className="text-gray-900">{lookupResult.engine_size || '—'}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Seats</dt>
              <dd className="text-gray-900">{lookupResult.seats ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Odometer</dt>
              <dd className="text-gray-900 tabular-nums">{lookupResult.odometer != null ? lookupResult.odometer.toLocaleString('en-NZ') + ' km' : '—'}</dd>
            </div>
          </dl>
        </div>
      )}

      {/* Empty state */}
      {!loading && !lookupResult && !notFound && !error && !searchRego.trim() && (
        <div className="py-16 text-center text-sm text-gray-500">
          Enter a registration number above to look up a vehicle, or add one manually.
        </div>
      )}

      {/* Manual Entry Modal */}
      <Modal open={manualOpen} onClose={() => { setManualOpen(false); setManualError('') }} title="Manual Vehicle Entry">
        <p className="text-sm text-gray-600 mb-3">
          Enter vehicle details manually when Carjam data is unavailable.
        </p>
        <div className="space-y-3">
          <Input
            label="Registration number *"
            value={manualForm.rego}
            onChange={(e) => updateManualField('rego', e.target.value)}
          />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Make" value={manualForm.make} onChange={(e) => updateManualField('make', e.target.value)} />
            <Input label="Model" value={manualForm.model} onChange={(e) => updateManualField('model', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Year" type="number" value={manualForm.year} onChange={(e) => updateManualField('year', e.target.value)} />
            <Input label="Colour" value={manualForm.colour} onChange={(e) => updateManualField('colour', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Body Type" value={manualForm.body_type} onChange={(e) => updateManualField('body_type', e.target.value)} />
            <Input label="Fuel Type" value={manualForm.fuel_type} onChange={(e) => updateManualField('fuel_type', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Engine Size" value={manualForm.engine_size} onChange={(e) => updateManualField('engine_size', e.target.value)} />
            <Input label="Seats" type="number" value={manualForm.num_seats} onChange={(e) => updateManualField('num_seats', e.target.value)} />
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
