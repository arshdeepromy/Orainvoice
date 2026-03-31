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

export default function TradeFamilies() {
  const [families, setFamilies] = useState<TradeFamily[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const [editingFamily, setEditingFamily] = useState<TradeFamily | null>(null)
  const [editCountries, setEditCountries] = useState<string[]>([])
  const [editFeatures, setEditFeatures] = useState<string>('')

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
    setEditFeatures((family.gated_features ?? []).join('\n'))
  }

  function closeEditModal() {
    setEditingFamily(null)
    setEditCountries([])
    setEditFeatures('')
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
      const features = editFeatures
        .split('\n')
        .map(f => f.trim())
        .filter(f => f.length > 0)
      await apiClient.put(`/api/v2/admin/trade-families/${editingFamily.slug}`, {
        country_codes: editCountries,
        gated_features: features,
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
          <h1 className="text-2xl font-semibold text-gray-900">Trade Families</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage business types available during signup. Disabled families won't appear in the signup form.
          </p>
        </div>
        <Button variant="secondary" onClick={fetchFamilies}>
          Refresh
        </Button>
      </div>

      {error && (
        <AlertBanner variant="error" onDismiss={() => setError(null)}>
          {error}
        </AlertBanner>
      )}

      <div className="bg-white shadow rounded-lg overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Trade Family
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Status
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Countries
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Gated Features
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {families.map(family => {
              const icon = FAMILY_ICONS[family.slug] || family.icon || '📦'
              const countryCount = (family.country_codes ?? []).length
              const featureCount = (family.gated_features ?? []).length
              return (
                <tr key={family.id} className={!family.is_active ? 'bg-gray-50' : ''}>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">{icon}</span>
                      <div>
                        <div className="text-sm font-medium text-gray-900">
                          {family.display_name}
                        </div>
                        <div className="text-xs text-gray-500">{family.slug}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        family.is_active
                          ? 'bg-green-100 text-green-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}
                    >
                      {family.is_active ? 'Enabled' : 'Disabled'}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {countryCount === 0 ? (
                      <span className="text-green-600">All countries</span>
                    ) : (
                      <span>{countryCount} countries</span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {featureCount === 0 ? (
                      <span className="text-gray-400">None</span>
                    ) : (
                      <span>{featureCount} features</span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium space-x-2">
                    <Button
                      variant="secondary"
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
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={closeEditModal}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-2xl w-full p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                Edit {editingFamily.display_name}
              </h2>

              {/* Country Selection */}
              <div className="mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Available Countries
                </label>
                <p className="text-xs text-gray-500 mb-2">
                  Select which countries can see this trade family during signup.
                  Leave empty to make available to all countries.
                </p>
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 max-h-48 overflow-y-auto border rounded-md p-2">
                  {COUNTRIES.map(country => {
                    const isSelected = editCountries.includes(country.code)
                    return (
                      <button
                        key={country.code}
                        type="button"
                        onClick={() => toggleCountry(country.code)}
                        className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
                          isSelected
                            ? 'bg-blue-100 text-blue-800 border border-blue-300'
                            : 'bg-gray-50 text-gray-700 border border-gray-200 hover:bg-gray-100'
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
                    <span className="text-xs text-gray-500">
                      Selected: {editCountries.join(', ')}
                    </span>
                    <button
                      type="button"
                      onClick={() => setEditCountries([])}
                      className="text-xs text-red-600 hover:underline"
                    >
                      Clear all
                    </button>
                  </div>
                )}
              </div>

              {/* Gated Features */}
              <div className="mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Gated Features
                </label>
                <p className="text-xs text-gray-500 mb-2">
                  List feature slugs that are gated behind this trade family (one per line).
                  These are shown for reference only.
                </p>
                <textarea
                  value={editFeatures}
                  onChange={e => setEditFeatures(e.target.value)}
                  rows={4}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="vehicle-lookup&#10;parts-catalogue&#10;job-cards"
                />
              </div>

              {/* Actions */}
              <div className="flex justify-end gap-3">
                <Button variant="secondary" onClick={closeEditModal}>
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
