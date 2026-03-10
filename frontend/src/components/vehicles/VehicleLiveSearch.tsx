import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Spinner } from '@/components/ui'

interface Vehicle {
  id: string
  rego: string
  make: string
  model: string
  year: number | null
  colour: string
  body_type: string
  fuel_type: string
  engine_size: string
  wof_expiry: string | null
  registration_expiry: string | null
  odometer?: number | null
}

interface LinkedCustomer {
  id: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
  mobile_phone?: string | null
  display_name?: string | null
  company_name?: string | null
}

interface SearchResult {
  id: string
  rego: string
  make: string | null
  model: string | null
  year: number | null
  colour: string | null
  lookup_type: string | null
  odometer?: number | null
  linked_customers?: LinkedCustomer[]
}

interface VehicleLiveSearchProps {
  vehicle: Vehicle | null
  onVehicleFound: (v: Vehicle | null) => void
  onCustomerAutoSelect?: (c: LinkedCustomer) => void
  error?: string
}

export function VehicleLiveSearch({ vehicle, onVehicleFound, onCustomerAutoSelect, error }: VehicleLiveSearchProps) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [syncError, setSyncError] = useState('')
  const [syncMessage, setSyncMessage] = useState('')
  
  const containerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  // Click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Live search with debounce
  const searchDatabase = useCallback(async (q: string) => {
    if (q.length < 2) {
      setResults([])
      return
    }
    
    console.log('[VehicleLiveSearch] Searching for:', q)
    setSearching(true)
    setSyncError('')
    setSyncMessage('')
    
    try {
      const res = await apiClient.get<{ results: SearchResult[]; total: number }>(
        `/vehicles/search`,
        { params: { q } }
      )
      console.log('[VehicleLiveSearch] Search results:', res.data)
      setResults(res.data.results || [])
    } catch (err) {
      console.error('[VehicleLiveSearch] Search error:', err)
      setResults([])
    } finally {
      setSearching(false)
    }
  }, [])

  useEffect(() => {
    if (query.length < 2) {
      setResults([])
      setShowDropdown(false)
      return
    }
    
    setShowDropdown(true)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => searchDatabase(query), 300)
    
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query, searchDatabase])

  const handleSelectResult = (result: SearchResult) => {
    // Fetch full vehicle details
    const fullVehicle: Vehicle = {
      id: result.id,
      rego: result.rego,
      make: result.make || '',
      model: result.model || '',
      year: result.year,
      colour: result.colour || '',
      body_type: '',
      fuel_type: '',
      engine_size: '',
      wof_expiry: null,
      registration_expiry: null,
      odometer: result.odometer ?? null,
    }
    onVehicleFound(fullVehicle)
    setQuery(result.rego)
    setShowDropdown(false)
    
    // Auto-select first linked customer if available
    if (onCustomerAutoSelect && result.linked_customers && result.linked_customers.length > 0) {
      onCustomerAutoSelect(result.linked_customers[0])
    }
  }

  const syncWithCarjam = async () => {
    const cleaned = query.trim().toUpperCase()
    if (!cleaned) return
    
    setSyncing(true)
    setSyncError('')
    setSyncMessage('Fetching info...')
    
    try {
      const res = await apiClient.post<{
        success: boolean
        vehicle: Vehicle
        source: string
        attempts: number
        cost_estimate_nzd: number
        message: string
      }>('/vehicles/lookup-with-fallback', {
        rego: cleaned
      })
      
      if (res.data.success && res.data.vehicle) {
        onVehicleFound(res.data.vehicle)
        setQuery(res.data.vehicle.rego)
        setShowDropdown(false)
        setSyncMessage(res.data.message)
        
        // Clear success message after 3 seconds
        setTimeout(() => setSyncMessage(''), 3000)
      }
    } catch (err: any) {
      const status = err?.response?.status
      if (status === 404) {
        setSyncError('Vehicle not found. You can enter details manually.')
      } else if (status === 429) {
        setSyncError('Rate limit exceeded. Please try again shortly.')
      } else {
        setSyncError('Sync failed. Please try again.')
      }
      setSyncMessage('')
    } finally {
      setSyncing(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && results.length === 0 && query.length >= 2) {
      e.preventDefault()
      syncWithCarjam()
    }
  }

  const handleClear = () => {
    onVehicleFound(null)
    setQuery('')
    setResults([])
    setSyncError('')
    setSyncMessage('')
  }

  // If vehicle is selected, show summary
  if (vehicle) {
    return (
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Vehicle</label>
        <div className="rounded-md border border-gray-300 bg-gray-50 p-3">
          <div className="flex items-center justify-between">
            <div>
              <span className="font-semibold text-gray-900">{vehicle.rego}</span>
              <span className="ml-2 text-gray-700">
                {vehicle.year} {vehicle.make} {vehicle.model}
              </span>
              {vehicle.colour && <span className="ml-2 text-gray-500">· {vehicle.colour}</span>}
            </div>
            <button
              type="button"
              onClick={handleClear}
              className="rounded p-1 text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              aria-label="Change vehicle"
            >
              ✕
            </button>
          </div>
          {vehicle.body_type && (
            <div className="mt-1 text-sm text-gray-500">
              {vehicle.body_type} · {vehicle.fuel_type} · {vehicle.engine_size}
            </div>
          )}
          {vehicle.odometer != null && vehicle.odometer > 0 && (
            <div className="mt-1 text-sm text-gray-500">
              Odo: {vehicle.odometer.toLocaleString()} Kms
            </div>
          )}
        </div>
      </div>
    )
  }

  // Search input with live results
  return (
    <div ref={containerRef} className="relative flex flex-col gap-1">
      <label className="text-sm font-medium text-gray-700">Vehicle registration</label>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value.toUpperCase())}
        onKeyDown={handleKeyDown}
        onFocus={() => query.length >= 2 && setShowDropdown(true)}
        placeholder="e.g. ABC123"
        className={`rounded-md border px-3 py-2 text-gray-900 shadow-sm transition-colors
          placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
          ${error || syncError ? 'border-red-500' : 'border-gray-300'}`}
        aria-label="Vehicle registration number"
        aria-invalid={!!(error || syncError)}
        autoComplete="off"
      />
      
      {(error || syncError) && (
        <p className="text-sm text-red-600" role="alert">{error || syncError}</p>
      )}
      
      {syncMessage && (
        <p className="text-sm text-green-600">{syncMessage}</p>
      )}

      {showDropdown && query.length >= 2 && (
        <div className="absolute top-full left-0 right-0 z-30 mt-1 max-h-80 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
          {searching && (
            <div className="flex items-center gap-2 px-4 py-3 text-sm text-gray-500">
              <Spinner size="sm" /> Searching database...
            </div>
          )}
          
          {!searching && results && results.length > 0 && (
            <>
              {results.map((result) => (
                <button
                  key={result.id}
                  type="button"
                  onClick={() => handleSelectResult(result)}
                  className="w-full px-4 py-3 text-left hover:bg-gray-50 focus-visible:bg-gray-50 focus-visible:outline-none min-h-[44px] border-b border-gray-50 last:border-b-0"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="font-medium text-gray-900">{result.rego}</span>
                      {result.year && result.make && result.model && (
                        <span className="ml-2 text-sm text-gray-600">
                          {result.year} {result.make} {result.model}
                        </span>
                      )}
                      {result.colour && (
                        <span className="ml-2 text-sm text-gray-500">· {result.colour}</span>
                      )}
                    </div>
                    {result.linked_customers && result.linked_customers.length > 0 && (
                      <span className="text-xs text-green-600 bg-green-50 px-2 py-0.5 rounded">
                        {result.linked_customers.length} owner{result.linked_customers.length > 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                  {result.linked_customers && result.linked_customers.length > 0 && (
                    <div className="mt-1 text-xs text-gray-500">
                      {result.linked_customers.slice(0, 2).map(c => 
                        c.display_name || `${c.first_name} ${c.last_name}`
                      ).join(', ')}
                      {result.linked_customers.length > 2 && ` +${result.linked_customers.length - 2} more`}
                    </div>
                  )}
                </button>
              ))}
            </>
          )}
          
          {!searching && results.length === 0 && (
            <div className="p-4">
              <Button
                onClick={syncWithCarjam}
                loading={syncing}
                size="sm"
                className="w-full"
              >
                {syncing ? 'Fetching info...' : 'Onboard new vehicle'}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
