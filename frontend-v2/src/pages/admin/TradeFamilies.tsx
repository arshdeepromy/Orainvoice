import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Button, Spinner, AlertBanner } from '@/components/ui'
import { COUNTRIES } from '@/components/ui/CountrySelect'

interface TradeFamily {
  id: string
  slug: string
  display_name: string
  icon: string | null
  display_order: number
  is_active: boolean
  country_codes: string[]
  gated_features: string[]
  created_at: string
  updated_at: string
}

interface TradeFamilyListResponse {
  families: TradeFamily[]
  total: number
}

// Trade family icons (same as SignupForm)
const FAMILY_ICONS: Record<string, string> = {
  'automotive-transport': '🚗',
  'electrical-mechanical': '⚡',
  'plumbing-gas': '🔧',
  'building-construction': '🏗️',
  'landscaping-outdoor': '🌿',
  'cleaning-facilities': '🧹',
  'it-technology': '💻',
  'creative-professional': '🎨',
  'accounting-legal-financial': '📊',
  'health-wellness': '❤️',
  'food-hospitality': '🍽️',
  'retail': '🛍️',
  'hair-beauty-personal-care': '💇',
  'trades-support-hire': '🔨',
  'freelancing-contracting': '📋',
}

interface FeatureFlag {
  key: string
  display_name: string
  category: string
  is_active: boolean
}

export default function TradeFamilies() {
  const [families, setFamilies] = useState<TradeFamily[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const [editingFamily, setEditingFamily] = useState<TradeFamily | null>(null)
  const [editCountries, setEditCountries] = useState<string[]>([])
  const [editFeatures, setEditFeatures] = useState<string[]>([])
  const [availableFeatures, setAvailableFeatures] = useState<FeatureFlag[]>([])
  const [featuresLoading, setFeaturesLoading] = useState(false)

  useEffect(() => {
    fetchFamilies()
  }, [])

  async function fetchFamilies() {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<TradeFamilyListResponse>('/api/v2/admin/trade-families')
      setFamilies(res.data?.families ?? [])
    } catch {
      setError('Failed to load trade families')
    } finally {
      setLoading(false)
    }
  }


  async function toggleActive(family: TradeFamily) {
    setSaving(family.slug)
    try {
      await apiClient.put(`/api/v2/admin/trade-families/${family.slug}`, {
        is_active: !family.is_active,
      })
      await fetchFamilies()
    } catch {
      setError(`Failed to update ${family.display_name}`)
    } finally {
      setSaving(null)
    }
  }

  function openEditModal(family: TradeFamily) {
    setEditingFamily(family)
    setEditCountries(family.country_codes ?? [])
    setEditFeatures(family.gated_features ?? [])
    fetchAvailableFeatures()
  }

  async function fetchAvailableFeatures() {
    setFeaturesLoading(true)
    try {
      const res = await apiClient.get<{ flags: FeatureFlag[]; total: number }>('/api/v2/admin/flags')
      setAvailableFeatures(res.data?.flags ?? [])
    } catch {
      setAvailableFeatures([])
    } finally {
      setFeaturesLoading(false)
    }
  }

  function closeEditModal() {
    setEditingFamily(null)
    setEditCountries([])
    setEditFeatures([])
    setAvailableFeatures([])
  }

  function toggleCountry(code: string) {
    setEditCountries(prev =>
      prev.includes(code) ? prev.filter(c => c !== code) : [...prev, code]
    )
  }

  async function saveFamily() {
    if (!editingFamily) return
    setSaving(editingFamily.slug)
    try {
      await apiClient.put(`/api/v2/admin/trade-families/${editingFamily.slug}`, {
        country_codes: editCountries,
        gated_features: editFeatures,
      })
      closeEditModal()
      await fetchFamilies()
    } catch {
      setError(`Failed to save ${editingFamily.display_name}`)
    } finally {
      setSaving(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner label="Loading trade families..." />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text">Trade Families</h1>
          <p className="mt-1 text-sm text-muted">
            Manage business types available during signup. Disabled families won't appear in the signup form.
          </p>
        </div>
        <Button variant="ghost" onClick={fetchFamilies}>
          Refresh
        </Button>
      </div>

      {error && (
        <AlertBanner variant="error" onDismiss={() => setError(null)}>
          {error}
        </AlertBanner>
      )}

      <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
        <table className="min-w-full border-collapse">
          <thead>
            <tr>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                Trade Family
              </th>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                Status
              </th>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                Countries
              </th>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                Gated Features
              </th>
              <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {families.map(family => {
              const icon = FAMILY_ICONS[family.slug] || family.icon || '📦'
              const countryCount = (family.country_codes ?? []).length
              const featureCount = (family.gated_features ?? []).length
              return (
                <tr key={family.id} className={`border-b border-border last:border-b-0 hover:bg-canvas ${!family.is_active ? 'bg-canvas' : ''}`}>
                  <td className="px-4 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">{icon}</span>
                      <div>
                        <div className="text-sm font-medium text-text">
                          {family.display_name}
                        </div>
                        <div className="text-xs text-muted">{family.slug}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap">
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        family.is_active
                          ? 'bg-ok-soft text-ok'
                          : 'bg-[#EEF0F4] text-muted'
                      }`}
                    >
                      {family.is_active ? 'Enabled' : 'Disabled'}
                    </span>
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-sm text-muted">
                    {countryCount === 0 ? (
                      <span className="text-ok">All countries</span>
                    ) : (
                      <span>{countryCount} countries</span>
                    )}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-sm text-muted">
                    {featureCount === 0 ? (
                      <span className="text-muted-2">None</span>
                    ) : (
                      <span>{featureCount} features</span>
                    )}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-right text-sm font-medium space-x-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEditModal(family)}
                    >
                      Edit
                    </Button>
                    <Button
                      variant={family.is_active ? 'danger' : 'primary'}
                      size="sm"
                      loading={saving === family.slug}
                      onClick={() => toggleActive(family)}
                    >
                      {family.is_active ? 'Disable' : 'Enable'}
                    </Button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>


      {/* Edit Modal */}
      {editingFamily && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-ink/50 transition-opacity"
              onClick={closeEditModal}
            />
            <div className="relative bg-card rounded-card shadow-pop max-w-2xl w-full p-6">
              <h2 className="text-lg font-semibold text-text mb-4">
                Edit {editingFamily.display_name}
              </h2>

              {/* Country Selection */}
              <div className="mb-6">
                <label className="block text-sm font-medium text-text mb-2">
                  Available Countries
                </label>
                <p className="text-xs text-muted mb-2">
                  Select which countries can see this trade family during signup.
                  Leave empty to make available to all countries.
                </p>
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 max-h-48 overflow-y-auto border border-border rounded-ctl p-2">
                  {COUNTRIES.map(country => {
                    const isSelected = editCountries.includes(country.code)
                    return (
                      <button
                        key={country.code}
                        type="button"
                        onClick={() => toggleCountry(country.code)}
                        className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
                          isSelected
                            ? 'bg-accent-soft text-accent border border-accent'
                            : 'bg-canvas text-text border border-border hover:bg-card'
                        }`}
                      >
                        <span>{country.flag}</span>
                        <span className="truncate">{country.code}</span>
                      </button>
                    )
                  })}
                </div>
                {editCountries.length > 0 && (
                  <div className="mt-2 flex items-center gap-2">
                    <span className="text-xs text-muted">
                      Selected: {editCountries.join(', ')}
                    </span>
                    <button
                      type="button"
                      onClick={() => setEditCountries([])}
                      className="text-xs text-danger hover:underline"
                    >
                      Clear all
                    </button>
                  </div>
                )}
              </div>

              {/* Gated Features */}
              <div className="mb-6">
                <label className="block text-sm font-medium text-text mb-2">
                  Gated Features
                </label>
                <p className="text-xs text-muted mb-2">
                  Select which features are gated behind this trade family.
                  Only orgs in this trade family will have access to these features.
                </p>
                {featuresLoading ? (
                  <div className="flex items-center gap-2 py-4 text-sm text-muted">
                    <Spinner /> Loading features...
                  </div>
                ) : availableFeatures.length === 0 ? (
                  <p className="text-sm text-muted-2 py-2">No feature flags registered yet.</p>
                ) : (
                  <div className="max-h-56 overflow-y-auto border border-border rounded-ctl p-2 space-y-1">
                    {/* Group by category */}
                    {Object.entries(
                      availableFeatures.reduce<Record<string, FeatureFlag[]>>((acc, f) => {
                        const cat = f.category || 'Uncategorised'
                        ;(acc[cat] ??= []).push(f)
                        return acc
                      }, {})
                    )
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([category, flags]) => (
                        <div key={category}>
                          <div className="text-xs font-semibold text-muted uppercase tracking-wider px-1 pt-2 pb-1">
                            {category}
                          </div>
                          {flags.map(flag => {
                            const isSelected = editFeatures.includes(flag.key)
                            return (
                              <label
                                key={flag.key}
                                className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors ${
                                  isSelected
                                    ? 'bg-accent-soft text-accent'
                                    : 'hover:bg-canvas text-text'
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  onChange={() =>
                                    setEditFeatures(prev =>
                                      isSelected
                                        ? prev.filter(k => k !== flag.key)
                                        : [...prev, flag.key]
                                    )
                                  }
                                  className="rounded border-border text-accent focus:ring-accent"
                                />
                                <span className="text-sm">{flag.display_name}</span>
                                <span className="text-xs text-muted-2 ml-auto">{flag.key}</span>
                              </label>
                            )
                          })}
                        </div>
                      ))}
                  </div>
                )}
                {editFeatures.length > 0 && (
                  <div className="mt-2 flex items-center gap-2">
                    <span className="text-xs text-muted">
                      {editFeatures.length} feature{editFeatures.length !== 1 ? 's' : ''} selected
                    </span>
                    <button
                      type="button"
                      onClick={() => setEditFeatures([])}
                      className="text-xs text-danger hover:underline"
                    >
                      Clear all
                    </button>
                  </div>
                )}
              </div>

              {/* Actions */}
              <div className="flex justify-end gap-3">
                <Button variant="ghost" onClick={closeEditModal}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  loading={saving === editingFamily.slug}
                  onClick={saveFamily}
                >
                  Save Changes
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
