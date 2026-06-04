import { useState, useEffect, useCallback } from 'react'
import Button from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Input } from '@/components/ui/Input'
import { Tabs } from '@/components/ui/Tabs'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import { Modal } from '@/components/ui/Modal'
import apiClient from '@/api/client'
import axios from 'axios'

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
      setSearchResults(res.data?.results ?? [])
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
          <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); handleRefresh(r.rego); }} loading={refreshing === r.rego}>
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
        <h2 className="text-lg font-semibold text-text">Global Vehicle Database</h2>
        {stats && (
          <div className="mt-2 flex gap-6">
            <div className="rounded-card border border-border p-4">
              <p className="text-sm text-muted">Total records</p>
              <p className="mono text-2xl font-bold text-text">{(stats.total_records ?? 0).toLocaleString()}</p>
            </div>
            <div className="rounded-card border border-border p-4">
              <p className="text-sm text-muted">Last refreshed</p>
              <p className="text-sm font-medium text-text">{formatDate(stats.last_refreshed_at)}</p>
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
        <Button variant="ghost" onClick={() => handleDelete('')}>Purge stale records</Button>
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
              <h3 className="text-sm font-semibold text-text mb-3">Basic Information</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted">Registration</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.rego || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Make</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.make || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Model</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.model || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Submodel</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.submodel || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Year</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.year || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Body Type</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.body_type || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Colour</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.colour || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Second Colour</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.second_colour || '—'}</p>
                </div>
              </div>
            </div>

            {/* Technical Specifications */}
            <div>
              <h3 className="text-sm font-semibold text-text mb-3">Technical Specifications</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted">VIN</p>
                  <p className="mono text-sm font-medium text-text">{selectedVehicle.vin || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Chassis</p>
                  <p className="mono text-sm font-medium text-text">{selectedVehicle.chassis || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Engine Number</p>
                  <p className="mono text-sm font-medium text-text">{selectedVehicle.engine_no || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Engine Size</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.engine_size ? `${selectedVehicle.engine_size} cc` : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Fuel Type</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.fuel_type || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Transmission</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.transmission || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Power</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.power_kw ? `${selectedVehicle.power_kw} kW` : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Seats</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.num_seats || '—'}</p>
                </div>
              </div>
            </div>

            {/* Weight & Dimensions */}
            <div>
              <h3 className="text-sm font-semibold text-text mb-3">Weight & Dimensions</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted">Tare Weight</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.tare_weight ? `${selectedVehicle.tare_weight} kg` : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Gross Vehicle Mass</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.gross_vehicle_mass ? `${selectedVehicle.gross_vehicle_mass} kg` : '—'}</p>
                </div>
              </div>
            </div>

            {/* Registration & Compliance */}
            <div>
              <h3 className="text-sm font-semibold text-text mb-3">Registration & Compliance</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted">Plate Type</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.plate_type || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Vehicle Type</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.vehicle_type || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Country of Origin</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.country_of_origin || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">First Registered NZ</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.date_first_registered_nz ? formatDate(selectedVehicle.date_first_registered_nz) : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Number of Owners</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.number_of_owners || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Reported Stolen</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.reported_stolen === 'Y' ? '⚠️ Yes' : selectedVehicle.reported_stolen === 'N' ? '✓ No' : '—'}</p>
                </div>
              </div>
            </div>

            {/* Inspection & Odometer */}
            <div>
              <h3 className="text-sm font-semibold text-text mb-3">Inspection & Odometer</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted">WOF Expiry</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.wof_expiry ? formatDate(selectedVehicle.wof_expiry) : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Registration Expiry</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.registration_expiry ? formatDate(selectedVehicle.registration_expiry) : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Odometer</p>
                  <p className="text-sm font-medium text-text">{selectedVehicle.odometer_last_recorded ? `${selectedVehicle.odometer_last_recorded.toLocaleString()} km` : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Last Pulled</p>
                  <p className="text-sm font-medium text-text">{formatDate(selectedVehicle.last_pulled_at)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Lookup Type</p>
                  <p className="text-sm font-medium text-text">
                    <span className={selectedVehicle.lookup_type === 'abcd' ? 'text-accent' : 'text-ok'}>
                      {selectedVehicle.lookup_type === 'abcd' ? 'ABCD (Lower Cost)' : 'Basic (Full Data)'}
                    </span>
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-6 flex justify-end gap-3">
            <Button variant="ghost" onClick={() => setSelectedVehicle(null)}>
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
      const tc = res.data?.terms_and_conditions
      if (tc && typeof tc === 'object') {
        setContent(tc.content ?? '')
        setCurrentVersion(tc.version ?? 0)
      } else {
        setContent('')
        setCurrentVersion(0)
      }
      setHistory((res.data?.terms_history ?? []).map((h: any) => ({
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
          <h2 className="text-lg font-semibold text-text">Platform Terms & Conditions</h2>
          <p className="text-sm text-muted">Current version: {currentVersion}</p>
        </div>
        <Button variant="ghost" onClick={() => setShowHistory(!showHistory)}>
          {showHistory ? 'Hide history' : 'Version history'}
        </Button>
      </div>

      {showHistory && history.length > 0 && (
        <div className="rounded-card border border-border p-4 space-y-3" role="region" aria-label="Terms version history">
          <h3 className="text-sm font-medium text-text">Version History</h3>
          {history.map((v) => (
            <div key={v.version} className="flex items-center justify-between border-b border-border pb-2 last:border-0">
              <div>
                <span className="text-sm font-medium text-text">Version {v.version}</span>
                <span className="ml-3 text-sm text-muted">{formatDate(v.updated_at)}</span>
              </div>
              <Button
                variant="ghost"
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
          <label htmlFor="terms-editor" className="text-[12.5px] font-medium text-text">
            Terms content
          </label>
          <textarea
            id="terms-editor"
            className="mono rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text
              focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)] min-h-[300px]"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Enter platform terms and conditions…"
          />
          <p className="text-sm text-muted">
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
      setBanner(res.data?.announcement_banner ?? '')
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
      <h2 className="text-lg font-semibold text-text">Announcement Banner</h2>
      <p className="text-sm text-muted">
        This banner is visible to all organisation users across the platform. Leave empty to hide.
      </p>

      <div className="flex flex-col gap-1">
        <label htmlFor="announcement-text" className="text-[12.5px] font-medium text-text">
          Banner text
        </label>
        <textarea
          id="announcement-text"
          className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text
            focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          rows={3}
          value={banner}
          onChange={(e) => setBanner(e.target.value)}
          placeholder="e.g. Scheduled maintenance on Saturday 10pm–2am NZST"
        />
      </div>

      {banner && (
        <div role="region" aria-label="Banner preview">
          <p className="text-[12.5px] font-medium text-text mb-1">Preview</p>
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
          <Button type="button" variant="ghost" onClick={() => setBanner('')}>
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
      if (data?.signup_billing) setForm(data.signup_billing)
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
      <p className="text-sm text-muted">
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
        <label className="flex items-center gap-2 text-sm cursor-pointer text-text">
          <input
            type="checkbox"
            checked={form.pass_fees_to_customer}
            onChange={e => setForm(f => ({ ...f, pass_fees_to_customer: e.target.checked }))}
          />
          <span>Pass processing fees to customer</span>
        </label>
      </div>

      {/* Preview */}
      <div className="rounded-ctl border border-border bg-canvas p-4 space-y-1 text-sm">
        <p className="font-medium text-text mb-2">Preview (for a ${planPrice} plan):</p>
        <div className="flex justify-between text-text"><span>Plan price</span><span className="mono">${(planCents / 100).toFixed(2)}</span></div>
        <div className="flex justify-between text-text"><span>GST ({form.gst_percentage}%)</span><span className="mono">${(gstCents / 100).toFixed(2)}</span></div>
        {form.pass_fees_to_customer && (
          <div className="flex justify-between text-text"><span>Processing fee</span><span className="mono">${(feeCents / 100).toFixed(2)}</span></div>
        )}
        <div className="flex justify-between font-semibold border-t border-border-strong pt-1 text-text">
          <span>Customer pays</span><span className="mono">${(totalWithFees / 100).toFixed(2)}</span>
        </div>
      </div>

      <Button onClick={handleSave} loading={saving}>Save billing config</Button>
    </div>
  )
}

/* ── Simple Markdown-to-HTML renderer (matches PrivacyPage) ── */

function renderMarkdownToHtml(markdown: string): string {
  let html = markdown
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  html = html.replace(/^### (.+)$/gm, '<h3 class="mt-8 mb-3 text-xl font-semibold text-text">$1</h3>')
  html = html.replace(/^## (.+)$/gm, '<h2 class="mt-10 mb-4 text-2xl font-bold text-text">$1</h2>')
  html = html.replace(/^# (.+)$/gm, '<h1 class="mt-12 mb-6 text-3xl font-bold text-text">$1</h1>')

  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')

  html = html.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" class="text-accent underline hover:text-accent-press" target="_blank" rel="noopener noreferrer">$1</a>',
  )

  html = html.replace(/^- (.+)$/gm, '<li class="ml-6 list-disc text-text">$1</li>')
  html = html.replace(/^\d+\. (.+)$/gm, '<li class="ml-6 list-decimal text-text">$1</li>')

  html = html.replace(
    /(<li class="ml-6 list-disc[^"]*">[\s\S]*?<\/li>\n?)+/g,
    (match) => `<ul class="my-3 space-y-1">${match}</ul>`,
  )
  html = html.replace(
    /(<li class="ml-6 list-decimal[^"]*">[\s\S]*?<\/li>\n?)+/g,
    (match) => `<ol class="my-3 space-y-1">${match}</ol>`,
  )

  html = html
    .split('\n')
    .map((line) => {
      const trimmed = line.trim()
      if (!trimmed) return ''
      if (trimmed.startsWith('<')) return trimmed
      return `<p class="mb-4 leading-relaxed text-text">${trimmed}</p>`
    })
    .join('\n')

  return html
}

/* ── Privacy Policy Tab ── */

function PrivacyPolicyTab({ onToast }: { onToast: (v: 'success' | 'error', msg: string) => void }) {
  const [content, setContent] = useState('')
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [error, setError] = useState(false)
  const [showPreview, setShowPreview] = useState(false)

  const fetchPolicy = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError(false)
    try {
      const res = await axios.get<{ content?: string | null; last_updated?: string | null }>(
        '/api/v1/public/privacy-policy',
        { signal },
      )
      setContent(res.data?.content ?? '')
      setLastUpdated(res.data?.last_updated ?? null)
    } catch (err) {
      if (!(signal?.aborted)) {
        setError(true)
      }
    } finally {
      if (!(signal?.aborted)) {
        setLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchPolicy(controller.signal)
    return () => controller.abort()
  }, [fetchPolicy])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!content.trim()) {
      onToast('error', 'Privacy policy content cannot be empty')
      return
    }
    setSaving(true)
    try {
      const res = await apiClient.put<{ success?: boolean; last_updated?: string | null }>(
        '/admin/privacy-policy',
        { content },
      )
      setLastUpdated(res.data?.last_updated ?? null)
      onToast('success', 'Privacy policy updated')
    } catch {
      onToast('error', 'Failed to update privacy policy')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    setResetting(true)
    try {
      await apiClient.put('/admin/privacy-policy', { content: '' })
      setContent('')
      setLastUpdated(null)
      onToast('success', 'Privacy policy reset to default — the public page will show the built-in NZ Privacy Act policy')
    } catch {
      onToast('error', 'Failed to reset privacy policy')
    } finally {
      setResetting(false)
    }
  }

  if (loading) return <div className="flex justify-center py-12"><Spinner label="Loading privacy policy" /></div>
  if (error) return <AlertBanner variant="error" title="Failed to load privacy policy">Could not load privacy policy content.</AlertBanner>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text">Privacy Policy Editor</h2>
          <p className="text-sm text-muted">
            {lastUpdated
              ? `Last updated: ${formatDate(lastUpdated)}`
              : 'Using default built-in policy'}
          </p>
        </div>
        <div className="flex gap-3">
          <Button variant="ghost" onClick={() => setShowPreview(!showPreview)}>
            {showPreview ? 'Hide preview' : 'Preview'}
          </Button>
          <Button variant="ghost" onClick={handleReset} loading={resetting}>
            Reset to Default
          </Button>
        </div>
      </div>

      {showPreview && content.trim() && (
        <div className="rounded-card border border-border bg-card p-6" role="region" aria-label="Privacy policy preview">
          <h3 className="text-sm font-medium text-text mb-3">Markdown Preview</h3>
          <div
            className="prose prose-gray max-w-none text-base leading-relaxed"
            dangerouslySetInnerHTML={{ __html: renderMarkdownToHtml(content) }}
          />
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="privacy-policy-editor" className="text-[12.5px] font-medium text-text">
            Policy content (Markdown)
          </label>
          <textarea
            id="privacy-policy-editor"
            className="mono rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text
              focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)] min-h-[300px]"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Enter privacy policy content in Markdown format…"
          />
          <p className="text-sm text-muted">
            Supports headings (#, ##, ###), bold (**text**), italic (*text*), links [text](url), and lists (- item, 1. item).
            Leave empty and reset to use the built-in default NZ Privacy Act 2020 policy.
          </p>
        </div>
        <Button type="submit" loading={saving}>Save privacy policy</Button>
      </form>
    </div>
  )
}

export function Settings() {
  const { toasts, addToast, dismissToast } = useToast()

  const tabs = [
    { id: 'vehicle-db', label: 'Vehicle DB', content: <VehicleDbTab onToast={addToast} /> },
    { id: 'terms', label: 'T&C', content: <TermsTab onToast={addToast} /> },
    { id: 'privacy-policy', label: 'Privacy Policy', content: <PrivacyPolicyTab onToast={addToast} /> },
    { id: 'announcements', label: 'Announcements', content: <AnnouncementsTab onToast={addToast} /> },
    { id: 'billing', label: 'Signup Billing', content: <SignupBillingTab onToast={addToast} /> },
  ]

  return (
    <div>
      <h1 className="text-2xl font-semibold text-text mb-6">Platform Settings</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <Tabs tabs={tabs} defaultTab="vehicle-db" urlPersist />
    </div>
  )
}
