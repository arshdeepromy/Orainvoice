import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Input } from '@/components/ui/Input'
import { Tabs } from '@/components/ui/Tabs'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import { Modal } from '@/components/ui/Modal'
import apiClient from '@/api/client'

/* ── Types ── */

export interface SubscriptionPlan {
  id: string
  name: string
  monthly_price_nzd: number
  user_seats: number
  storage_quota_gb: number
  carjam_lookups_included: number
  enabled_modules: string[]
  is_public: boolean
  is_archived: boolean
  created_at: string
  updated_at: string
  [key: string]: unknown
}

export interface StoragePricing {
  increment_gb: number
  price_per_gb_nzd: number
}

export interface VehicleDbStats {
  total_records: number
  last_refreshed_at: string | null
}

export interface VehicleRecord {
  id: string
  rego: string
  make: string | null
  model: string | null
  year: number | null
  colour: string | null
  body_type: string | null
  fuel_type: string | null
  engine_size: string | null
  num_seats: number | null
  wof_expiry: string | null
  registration_expiry: string | null
  odometer_last_recorded: number | null
  last_pulled_at: string
  created_at: string
  lookup_type: string | null
  // Extended Carjam fields
  vin: string | null
  chassis: string | null
  engine_no: string | null
  transmission: string | null
  country_of_origin: string | null
  number_of_owners: number | null
  vehicle_type: string | null
  reported_stolen: string | null
  power_kw: number | null
  tare_weight: number | null
  gross_vehicle_mass: number | null
  date_first_registered_nz: string | null
  plate_type: string | null
  submodel: string | null
  second_colour: string | null
}

export interface TermsVersion {
  version: number
  content: string
  updated_at: string
}

export interface PlatformSettings {
  storage_pricing: StoragePricing
  terms_and_conditions: string
  terms_version: number
  terms_history: TermsVersion[]
  announcement_banner: string
  signup_billing?: {
    gst_percentage: number
    stripe_fee_percentage: number
    stripe_fee_fixed_cents: number
    pass_fees_to_customer: boolean
  }
}

/* ── Helpers ── */

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}



/* ── Vehicle DB Tab ── */

function VehicleDbTab({ onToast }: { onToast: (v: 'success' | 'error', msg: string) => void }) {
  const [stats, setStats] = useState<VehicleDbStats | null>(null)
  const [searchRego, setSearchRego] = useState('')
  const [searchResults, setSearchResults] = useState<VehicleRecord[]>([])
  const [selectedVehicle, setSelectedVehicle] = useState<VehicleRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [searching, setSearching] = useState(false)
  const [refreshing, setRefreshing] = useState<string | null>(null)
  const [error, setError] = useState(false)

  const fetchStats = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await apiClient.get<VehicleDbStats>('/admin/vehicle-db/stats')
      setStats(res.data)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchStats() }, [fetchStats])

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!searchRego.trim()) return
    setSearching(true)
    try {
      const res = await apiClient.get<{ results: VehicleRecord[], total: number }>(`/admin/vehicle-db/search/${encodeURIComponent(searchRego.trim())}`)
      setSearchResults(res.data.results || [])
    } catch {
      onToast('error', 'Vehicle not found')
      setSearchResults([])
    } finally {
      setSearching(false)
    }
  }

  const handleRefresh = async (rego: string) => {
    setRefreshing(rego)
    try {
      await apiClient.post(`/admin/vehicle-db/${encodeURIComponent(rego)}/refresh`)
      onToast('success', `Vehicle ${rego} refreshed from Carjam`)
      handleSearch({ preventDefault: () => {} } as React.FormEvent)
    } catch {
      onToast('error', `Failed to refresh ${rego}`)
    } finally {
      setRefreshing(null)
    }
  }

  const handleDelete = async (_rego: string) => {
    try {
      await apiClient.delete('/admin/vehicle-db/stale', { params: { stale_days: 0 } })
      onToast('success', 'Stale vehicle records purged')
      setSearchResults([])
      fetchStats()
    } catch {
      onToast('error', 'Failed to purge stale records')
    }
  }

  const vehicleColumns: Column<VehicleRecord>[] = [
    { key: 'rego', header: 'Rego', sortable: true },
    { key: 'make', header: 'Make' },
    { key: 'model', header: 'Model' },
    { key: 'year', header: 'Year' },
    { key: 'last_pulled_at', header: 'Last pulled', render: (r) => formatDate(r.last_pulled_at) },
    {
      key: 'actions',
      header: '',
      render: (r) => (
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={(e) => { e.stopPropagation(); handleRefresh(r.rego); }} loading={refreshing === r.rego}>
            Refresh
          </Button>
          <Button variant="primary" size="sm" onClick={(e) => { e.stopPropagation(); setSelectedVehicle(r); }}>
            View Details
          </Button>
        </div>
      ),
    },
  ]

  if (loading) return <div className="flex justify-center py-12"><Spinner label="Loading vehicle database" /></div>
  if (error) return <AlertBanner variant="error" title="Failed to load vehicle database">Could not load vehicle database stats.</AlertBanner>

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Global Vehicle Database</h2>
        {stats && (
          <div className="mt-2 flex gap-6">
            <div className="rounded-lg border border-gray-200 p-4">
              <p className="text-sm text-gray-500">Total records</p>
              <p className="text-2xl font-bold text-gray-900">{stats.total_records.toLocaleString()}</p>
            </div>
            <div className="rounded-lg border border-gray-200 p-4">
              <p className="text-sm text-gray-500">Last refreshed</p>
              <p className="text-sm font-medium text-gray-900">{formatDate(stats.last_refreshed_at)}</p>
            </div>
          </div>
        )}
      </div>

      <div className="flex gap-3 items-end">
        <form onSubmit={handleSearch} className="flex gap-3 items-end max-w-md flex-1" role="search" aria-label="Vehicle search">
          <div className="flex-1">
            <Input
              label="Search by registration"
              placeholder="e.g. ABC123"
              value={searchRego}
              onChange={(e) => setSearchRego(e.target.value)}
            />
          </div>
          <Button type="submit" loading={searching}>Search</Button>
        </form>
        <Button variant="secondary" onClick={() => handleDelete('')}>Purge stale records</Button>
      </div>

      {searchResults.length > 0 && (
        <DataTable
          columns={vehicleColumns}
          data={searchResults}
          keyField="id"
          caption="Vehicle search results"
        />
      )}

      {/* Vehicle Details Modal */}
      {selectedVehicle && (
        <Modal
          open={true}
          onClose={() => setSelectedVehicle(null)}
          title={`Vehicle Details - ${selectedVehicle.rego}`}
          className="max-w-4xl"
        >
          <div className="space-y-6">
            {/* Basic Information */}
            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-3">Basic Information</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-gray-500">Registration</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.rego || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Make</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.make || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Model</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.model || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Submodel</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.submodel || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Year</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.year || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Body Type</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.body_type || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Colour</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.colour || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Second Colour</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.second_colour || '—'}</p>
                </div>
              </div>
            </div>

            {/* Technical Specifications */}
            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-3">Technical Specifications</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-gray-500">VIN</p>
                  <p className="text-sm font-medium text-gray-900 font-mono">{selectedVehicle.vin || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Chassis</p>
                  <p className="text-sm font-medium text-gray-900 font-mono">{selectedVehicle.chassis || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Engine Number</p>
                  <p className="text-sm font-medium text-gray-900 font-mono">{selectedVehicle.engine_no || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Engine Size</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.engine_size ? `${selectedVehicle.engine_size} cc` : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Fuel Type</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.fuel_type || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Transmission</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.transmission || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Power</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.power_kw ? `${selectedVehicle.power_kw} kW` : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Seats</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.num_seats || '—'}</p>
                </div>
              </div>
            </div>

            {/* Weight & Dimensions */}
            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-3">Weight & Dimensions</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-gray-500">Tare Weight</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.tare_weight ? `${selectedVehicle.tare_weight} kg` : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Gross Vehicle Mass</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.gross_vehicle_mass ? `${selectedVehicle.gross_vehicle_mass} kg` : '—'}</p>
                </div>
              </div>
            </div>

            {/* Registration & Compliance */}
            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-3">Registration & Compliance</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-gray-500">Plate Type</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.plate_type || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Vehicle Type</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.vehicle_type || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Country of Origin</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.country_of_origin || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">First Registered NZ</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.date_first_registered_nz ? formatDate(selectedVehicle.date_first_registered_nz) : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Number of Owners</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.number_of_owners || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Reported Stolen</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.reported_stolen === 'Y' ? '⚠️ Yes' : selectedVehicle.reported_stolen === 'N' ? '✓ No' : '—'}</p>
                </div>
              </div>
            </div>

            {/* Inspection & Odometer */}
            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-3">Inspection & Odometer</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-gray-500">WOF Expiry</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.wof_expiry ? formatDate(selectedVehicle.wof_expiry) : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Registration Expiry</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.registration_expiry ? formatDate(selectedVehicle.registration_expiry) : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Odometer</p>
                  <p className="text-sm font-medium text-gray-900">{selectedVehicle.odometer_last_recorded ? `${selectedVehicle.odometer_last_recorded.toLocaleString()} km` : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Last Pulled</p>
                  <p className="text-sm font-medium text-gray-900">{formatDate(selectedVehicle.last_pulled_at)}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Lookup Type</p>
                  <p className="text-sm font-medium text-gray-900">
                    <span className={selectedVehicle.lookup_type === 'abcd' ? 'text-blue-600' : 'text-green-600'}>
                      {selectedVehicle.lookup_type === 'abcd' ? 'ABCD (Lower Cost)' : 'Basic (Full Data)'}
                    </span>
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-6 flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setSelectedVehicle(null)}>
              Close
            </Button>
            <Button 
              variant="primary" 
              onClick={() => {
                handleRefresh(selectedVehicle.rego);
                setSelectedVehicle(null);
              }}
              loading={refreshing === selectedVehicle.rego}
            >
              Refresh from Carjam
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

/* ── Terms & Conditions Tab ── */

function TermsTab({ onToast }: { onToast: (v: 'success' | 'error', msg: string) => void }) {
  const [content, setContent] = useState('')
  const [currentVersion, setCurrentVersion] = useState(0)
  const [history, setHistory] = useState<TermsVersion[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(false)
  const [showHistory, setShowHistory] = useState(false)

  const fetchTerms = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await apiClient.get<Record<string, any>>('/admin/settings')
      const tc = res.data.terms_and_conditions
      if (tc && typeof tc === 'object') {
        setContent(tc.content ?? '')
        setCurrentVersion(tc.version ?? 0)
      } else {
        setContent('')
        setCurrentVersion(0)
      }
      setHistory((res.data.terms_history ?? []).map((h: any) => ({
        version: h.version,
        content: h.content,
        updated_at: h.updated_at,
      })))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchTerms() }, [fetchTerms])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await apiClient.put('/admin/settings', { terms_and_conditions: content })
      onToast('success', 'Terms & Conditions updated — users will be prompted to re-accept')
      fetchTerms()
    } catch {
      onToast('error', 'Failed to update Terms & Conditions')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="flex justify-center py-12"><Spinner label="Loading terms and conditions" /></div>
  if (error) return <AlertBanner variant="error" title="Failed to load terms">Could not load Terms & Conditions.</AlertBanner>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Platform Terms & Conditions</h2>
          <p className="text-sm text-gray-500">Current version: {currentVersion}</p>
        </div>
        <Button variant="secondary" onClick={() => setShowHistory(!showHistory)}>
          {showHistory ? 'Hide history' : 'Version history'}
        </Button>
      </div>

      {showHistory && history.length > 0 && (
        <div className="rounded-lg border border-gray-200 p-4 space-y-3" role="region" aria-label="Terms version history">
          <h3 className="text-sm font-medium text-gray-700">Version History</h3>
          {history.map((v) => (
            <div key={v.version} className="flex items-center justify-between border-b border-gray-100 pb-2 last:border-0">
              <div>
                <span className="text-sm font-medium text-gray-900">Version {v.version}</span>
                <span className="ml-3 text-sm text-gray-500">{formatDate(v.updated_at)}</span>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setContent(v.content)}
              >
                Restore
              </Button>
            </div>
          ))}
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="terms-editor" className="text-sm font-medium text-gray-700">
            Terms content
          </label>
          <textarea
            id="terms-editor"
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm
              focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 min-h-[300px] font-mono"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Enter platform terms and conditions…"
          />
          <p className="text-sm text-gray-500">
            Updating will increment the version and prompt all users to re-accept on next login.
          </p>
        </div>
        <Button type="submit" loading={saving}>Publish new version</Button>
      </form>
    </div>
  )
}

/* ── Announcements Tab ── */

function AnnouncementsTab({ onToast }: { onToast: (v: 'success' | 'error', msg: string) => void }) {
  const [banner, setBanner] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(false)

  const fetchBanner = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await apiClient.get<Record<string, any>>('/admin/settings')
      setBanner(res.data.announcement_banner ?? '')
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchBanner() }, [fetchBanner])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await apiClient.put('/admin/settings', { announcement_banner: banner })
      onToast('success', banner ? 'Announcement banner updated' : 'Announcement banner cleared')
    } catch {
      onToast('error', 'Failed to update announcement banner')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="flex justify-center py-12"><Spinner label="Loading announcement" /></div>
  if (error) return <AlertBanner variant="error" title="Failed to load announcement">Could not load announcement banner.</AlertBanner>

  return (
    <form onSubmit={handleSave} className="max-w-lg space-y-4">
      <h2 className="text-lg font-semibold text-gray-900">Announcement Banner</h2>
      <p className="text-sm text-gray-500">
        This banner is visible to all organisation users across the platform. Leave empty to hide.
      </p>

      <div className="flex flex-col gap-1">
        <label htmlFor="announcement-text" className="text-sm font-medium text-gray-700">
          Banner text
        </label>
        <textarea
          id="announcement-text"
          className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm
            focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          rows={3}
          value={banner}
          onChange={(e) => setBanner(e.target.value)}
          placeholder="e.g. Scheduled maintenance on Saturday 10pm–2am NZST"
        />
      </div>

      {banner && (
        <div role="region" aria-label="Banner preview">
          <p className="text-sm font-medium text-gray-700 mb-1">Preview</p>
          <AlertBanner variant="info" title="Platform Announcement">
            {banner}
          </AlertBanner>
        </div>
      )}

      <div className="flex gap-3">
        <Button type="submit" loading={saving}>
          {banner ? 'Update banner' : 'Clear banner'}
        </Button>
        {banner && (
          <Button type="button" variant="secondary" onClick={() => setBanner('')}>
            Clear
          </Button>
        )}
      </div>
    </form>
  )
}

/* ── Main Settings Page ── */

function SignupBillingTab({ onToast }: { onToast: (v: 'success' | 'error', msg: string) => void }) {
  const [form, setForm] = useState({
    gst_percentage: 15.0,
    stripe_fee_percentage: 2.9,
    stripe_fee_fixed_cents: 30,
    pass_fees_to_customer: true,
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    apiClient.get('/admin/settings').then(({ data }) => {
      if (data.signup_billing) setForm(data.signup_billing)
    }).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      await apiClient.put('/admin/settings', { signup_billing: form })
      onToast('success', 'Signup billing config saved')
    } catch {
      onToast('error', 'Failed to save billing config')
    } finally {
      setSaving(false)
    }
  }

  // Preview calculation
  const planPrice = 60
  const planCents = planPrice * 100
  const gstCents = Math.round(planCents * form.gst_percentage / 100)
  const subtotal = planCents + gstCents
  const totalWithFees = form.pass_fees_to_customer
    ? Math.round((subtotal + form.stripe_fee_fixed_cents) / (1 - form.stripe_fee_percentage / 100))
    : subtotal
  const feeCents = totalWithFees - subtotal

  if (loading) return <Spinner label="Loading billing config..." />

  return (
    <div className="space-y-6 max-w-lg">
      <p className="text-sm text-gray-600">
        Configure GST and payment processing fees for signup charges. These are applied on top of the plan price.
      </p>

      <div className="space-y-4">
        <Input
          label="GST Percentage"
          type="number"
          step="0.5"
          min="0"
          max="100"
          value={String(form.gst_percentage)}
          onChange={e => setForm(f => ({ ...f, gst_percentage: parseFloat(e.target.value) || 0 }))}
          helperText="Applied on top of plan price (NZ default: 15%)"
        />
        <Input
          label="Stripe Fee Percentage"
          type="number"
          step="0.1"
          min="0"
          max="20"
          value={String(form.stripe_fee_percentage)}
          onChange={e => setForm(f => ({ ...f, stripe_fee_percentage: parseFloat(e.target.value) || 0 }))}
          helperText="Stripe's percentage fee per transaction (NZ default: 2.9%)"
        />
        <Input
          label="Stripe Fixed Fee (cents)"
          type="number"
          min="0"
          value={String(form.stripe_fee_fixed_cents)}
          onChange={e => setForm(f => ({ ...f, stripe_fee_fixed_cents: parseInt(e.target.value) || 0 }))}
          helperText="Stripe's fixed fee per transaction in cents (NZ default: 30c)"
        />
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={form.pass_fees_to_customer}
            onChange={e => setForm(f => ({ ...f, pass_fees_to_customer: e.target.checked }))}
          />
          <span>Pass processing fees to customer</span>
        </label>
      </div>

      {/* Preview */}
      <div className="rounded-md border border-gray-200 bg-gray-50 p-4 space-y-1 text-sm">
        <p className="font-medium text-gray-700 mb-2">Preview (for a ${planPrice} plan):</p>
        <div className="flex justify-between"><span>Plan price</span><span>${(planCents / 100).toFixed(2)}</span></div>
        <div className="flex justify-between"><span>GST ({form.gst_percentage}%)</span><span>${(gstCents / 100).toFixed(2)}</span></div>
        {form.pass_fees_to_customer && (
          <div className="flex justify-between"><span>Processing fee</span><span>${(feeCents / 100).toFixed(2)}</span></div>
        )}
        <div className="flex justify-between font-semibold border-t border-gray-300 pt-1">
          <span>Customer pays</span><span>${(totalWithFees / 100).toFixed(2)}</span>
        </div>
      </div>

      <Button onClick={handleSave} loading={saving}>Save billing config</Button>
    </div>
  )
}

export function Settings() {
  const { toasts, addToast, dismissToast } = useToast()

  const tabs = [
    { id: 'vehicle-db', label: 'Vehicle DB', content: <VehicleDbTab onToast={addToast} /> },
    { id: 'terms', label: 'T&C', content: <TermsTab onToast={addToast} /> },
    { id: 'announcements', label: 'Announcements', content: <AnnouncementsTab onToast={addToast} /> },
    { id: 'billing', label: 'Signup Billing', content: <SignupBillingTab onToast={addToast} /> },
  ]

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Platform Settings</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <Tabs tabs={tabs} defaultTab="vehicle-db" urlPersist />
    </div>
  )
}
