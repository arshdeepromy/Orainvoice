import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import { Tabs } from '@/components/ui/Tabs'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { ToastContainer, useToast } from '@/components/ui/Toast'
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
  last_pulled_at: string
  [key: string]: unknown
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
}

/* ── Available modules for plans ── */

const AVAILABLE_MODULES = [
  'invoices',
  'quotes',
  'job_cards',
  'payments',
  'bookings',
  'inventory',
  'notifications',
  'reports',
  'customer_portal',
  'fleet_accounts',
]

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

function formatCurrency(amount: number): string {
  return `$${amount.toFixed(2)}`
}

/* ── Plan Edit Modal ── */

function PlanModal({
  plan,
  open,
  onClose,
  onSave,
}: {
  plan: SubscriptionPlan | null
  open: boolean
  onClose: () => void
  onSave: (data: Partial<SubscriptionPlan>) => Promise<void>
}) {
  const [name, setName] = useState('')
  const [price, setPrice] = useState('')
  const [seats, setSeats] = useState('')
  const [storage, setStorage] = useState('')
  const [carjam, setCarjam] = useState('')
  const [modules, setModules] = useState<string[]>([])
  const [isPublic, setIsPublic] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (plan) {
      setName(plan.name)
      setPrice(String(plan.monthly_price_nzd))
      setSeats(String(plan.user_seats))
      setStorage(String(plan.storage_quota_gb))
      setCarjam(String(plan.carjam_lookups_included))
      setModules(plan.enabled_modules)
      setIsPublic(plan.is_public)
    } else {
      setName('')
      setPrice('')
      setSeats('')
      setStorage('')
      setCarjam('')
      setModules([])
      setIsPublic(true)
    }
  }, [plan, open])

  const toggleModule = (mod: string) => {
    setModules((prev) =>
      prev.includes(mod) ? prev.filter((m) => m !== mod) : [...prev, mod],
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await onSave({
        name,
        monthly_price_nzd: parseFloat(price),
        user_seats: parseInt(seats, 10),
        storage_quota_gb: parseInt(storage, 10),
        carjam_lookups_included: parseInt(carjam, 10),
        enabled_modules: modules,
        is_public: isPublic,
      })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={plan ? 'Edit Plan' : 'Create Plan'} className="max-w-lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input label="Plan name" value={name} onChange={(e) => setName(e.target.value)} required />
        <div className="grid grid-cols-2 gap-4">
          <Input label="Monthly price (NZD)" type="number" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} required />
          <Input label="User seats" type="number" value={seats} onChange={(e) => setSeats(e.target.value)} required />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Input label="Storage (GB)" type="number" value={storage} onChange={(e) => setStorage(e.target.value)} required />
          <Input label="Carjam lookups" type="number" value={carjam} onChange={(e) => setCarjam(e.target.value)} required />
        </div>

        <fieldset>
          <legend className="text-sm font-medium text-gray-700 mb-2">Enabled modules</legend>
          <div className="flex flex-wrap gap-2">
            {AVAILABLE_MODULES.map((mod) => (
              <label key={mod} className="flex items-center gap-1.5 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={modules.includes(mod)}
                  onChange={() => toggleModule(mod)}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                {mod.replace(/_/g, ' ')}
              </label>
            ))}
          </div>
        </fieldset>

        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={isPublic}
            onChange={(e) => setIsPublic(e.target.checked)}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Publicly visible
        </label>

        <div className="flex gap-3 pt-2">
          <Button type="submit" loading={saving}>
            {plan ? 'Save changes' : 'Create plan'}
          </Button>
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Modal>
  )
}

/* ── Plans Tab ── */

function PlansTab({ onToast }: { onToast: (v: 'success' | 'error', msg: string) => void }) {
  const [plans, setPlans] = useState<SubscriptionPlan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [editPlan, setEditPlan] = useState<SubscriptionPlan | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  const fetchPlans = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await apiClient.get<SubscriptionPlan[]>('/admin/plans')
      setPlans(res.data)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchPlans() }, [fetchPlans])

  const handleSave = async (data: Partial<SubscriptionPlan>) => {
    if (editPlan) {
      await apiClient.put(`/admin/plans/${editPlan.id}`, data)
      onToast('success', 'Plan updated')
    } else {
      await apiClient.post('/admin/plans', data)
      onToast('success', 'Plan created')
    }
    fetchPlans()
  }

  const handleArchive = async (plan: SubscriptionPlan) => {
    try {
      await apiClient.put(`/admin/plans/${plan.id}`, { is_archived: !plan.is_archived })
      onToast('success', plan.is_archived ? 'Plan restored' : 'Plan archived')
      fetchPlans()
    } catch {
      onToast('error', 'Failed to update plan')
    }
  }

  const columns: Column<SubscriptionPlan>[] = [
    { key: 'name', header: 'Name', sortable: true },
    { key: 'monthly_price_nzd', header: 'Price/mo', sortable: true, render: (r) => formatCurrency(r.monthly_price_nzd) },
    { key: 'user_seats', header: 'Seats', sortable: true },
    { key: 'storage_quota_gb', header: 'Storage (GB)', sortable: true },
    { key: 'carjam_lookups_included', header: 'Carjam lookups', sortable: true },
    {
      key: 'enabled_modules',
      header: 'Modules',
      render: (r) => (
        <div className="flex flex-wrap gap-1 max-w-xs">
          {r.enabled_modules.slice(0, 3).map((m) => (
            <Badge key={m} variant="neutral">{m.replace(/_/g, ' ')}</Badge>
          ))}
          {r.enabled_modules.length > 3 && (
            <Badge variant="neutral">+{r.enabled_modules.length - 3}</Badge>
          )}
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (r) => (
        <div className="flex gap-1">
          {r.is_archived && <Badge variant="warning">Archived</Badge>}
          {!r.is_archived && r.is_public && <Badge variant="success">Public</Badge>}
          {!r.is_archived && !r.is_public && <Badge variant="neutral">Hidden</Badge>}
        </div>
      ),
    },
    {
      key: 'actions',
      header: '',
      render: (r) => (
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={() => { setEditPlan(r); setModalOpen(true) }}>
            Edit
          </Button>
          <Button variant="secondary" size="sm" onClick={() => handleArchive(r)}>
            {r.is_archived ? 'Restore' : 'Archive'}
          </Button>
        </div>
      ),
    },
  ]

  if (loading) return <div className="flex justify-center py-12"><Spinner label="Loading plans" /></div>
  if (error) return <AlertBanner variant="error" title="Failed to load plans">Could not load subscription plans.</AlertBanner>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500">{plans.length} plan{plans.length !== 1 ? 's' : ''}</p>
        <Button onClick={() => { setEditPlan(null); setModalOpen(true) }}>Create plan</Button>
      </div>
      <DataTable columns={columns} data={plans} keyField="id" caption="Subscription plans" />
      <PlanModal
        plan={editPlan}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSave={handleSave}
      />
    </div>
  )
}

/* ── Storage Tab ── */

function StorageTab({ onToast }: { onToast: (v: 'success' | 'error', msg: string) => void }) {
  const [incrementGb, setIncrementGb] = useState('')
  const [pricePerGb, setPricePerGb] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(false)

  const fetchPricing = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await apiClient.get<PlatformSettings>('/admin/settings')
      setIncrementGb(String(res.data.storage_pricing.increment_gb))
      setPricePerGb(String(res.data.storage_pricing.price_per_gb_nzd))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchPricing() }, [fetchPricing])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await apiClient.put('/admin/settings', {
        storage_pricing: {
          increment_gb: parseInt(incrementGb, 10),
          price_per_gb_nzd: parseFloat(pricePerGb),
        },
      })
      onToast('success', 'Storage pricing updated')
    } catch {
      onToast('error', 'Failed to update storage pricing')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="flex justify-center py-12"><Spinner label="Loading storage pricing" /></div>
  if (error) return <AlertBanner variant="error" title="Failed to load storage pricing">Could not load storage pricing configuration.</AlertBanner>

  return (
    <form onSubmit={handleSave} className="max-w-md space-y-4">
      <h2 className="text-lg font-semibold text-gray-900">Storage Tier Pricing</h2>
      <Input
        label="Storage increment (GB)"
        type="number"
        value={incrementGb}
        onChange={(e) => setIncrementGb(e.target.value)}
        helperText="Size of each storage add-on block organisations can purchase"
        required
      />
      <Input
        label="Price per GB (NZD)"
        type="number"
        step="0.01"
        value={pricePerGb}
        onChange={(e) => setPricePerGb(e.target.value)}
        helperText="Monthly cost per GB of additional storage"
        required
      />
      <Button type="submit" loading={saving}>Save pricing</Button>
    </form>
  )
}

/* ── Vehicle DB Tab ── */

function VehicleDbTab({ onToast }: { onToast: (v: 'success' | 'error', msg: string) => void }) {
  const [stats, setStats] = useState<VehicleDbStats | null>(null)
  const [searchRego, setSearchRego] = useState('')
  const [searchResults, setSearchResults] = useState<VehicleRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [searching, setSearching] = useState(false)
  const [refreshing, setRefreshing] = useState<string | null>(null)
  const [error, setError] = useState(false)

  const fetchStats = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await apiClient.get<VehicleDbStats>('/admin/vehicle-db')
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
      const res = await apiClient.get<VehicleRecord[]>(`/admin/vehicle-db/${encodeURIComponent(searchRego.trim())}`)
      setSearchResults(Array.isArray(res.data) ? res.data : [res.data])
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

  const handleDelete = async (rego: string) => {
    try {
      await apiClient.delete(`/admin/vehicle-db/${encodeURIComponent(rego)}`)
      onToast('success', `Vehicle ${rego} deleted`)
      setSearchResults((prev) => prev.filter((v) => v.rego !== rego))
      fetchStats()
    } catch {
      onToast('error', `Failed to delete ${rego}`)
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
          <Button variant="secondary" size="sm" onClick={() => handleRefresh(r.rego)} loading={refreshing === r.rego}>
            Refresh
          </Button>
          <Button variant="secondary" size="sm" onClick={() => handleDelete(r.rego)}>
            Delete
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

      <form onSubmit={handleSearch} className="flex gap-3 items-end max-w-md" role="search" aria-label="Vehicle search">
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

      {searchResults.length > 0 && (
        <DataTable
          columns={vehicleColumns}
          data={searchResults}
          keyField="id"
          caption="Vehicle search results"
        />
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
      const res = await apiClient.get<PlatformSettings>('/admin/settings')
      setContent(res.data.terms_and_conditions)
      setCurrentVersion(res.data.terms_version)
      setHistory(res.data.terms_history ?? [])
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
      const res = await apiClient.get<PlatformSettings>('/admin/settings')
      setBanner(res.data.announcement_banner)
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

export function Settings() {
  const { toasts, addToast, dismissToast } = useToast()

  const tabs = [
    { id: 'plans', label: 'Plans', content: <PlansTab onToast={addToast} /> },
    { id: 'storage', label: 'Storage', content: <StorageTab onToast={addToast} /> },
    { id: 'vehicle-db', label: 'Vehicle DB', content: <VehicleDbTab onToast={addToast} /> },
    { id: 'terms', label: 'T&C', content: <TermsTab onToast={addToast} /> },
    { id: 'announcements', label: 'Announcements', content: <AnnouncementsTab onToast={addToast} /> },
  ]

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Platform Settings</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <Tabs tabs={tabs} defaultTab="plans" />
    </div>
  )
}
