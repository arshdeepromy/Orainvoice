import React, { useState, useEffect } from 'react'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import apiClient from '@/api/client'
import type { WizardData, TradeFamily, TradeCategory } from '../types'

const MAX_SELECTIONS = 3

interface TradeStepProps {
  data: WizardData
  onChange: (updates: Partial<WizardData>) => void
}

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

export function TradeStep({ data, onChange }: TradeStepProps) {
  const [families, setFamilies] = useState<TradeFamily[]>([])
  const [categories, setCategories] = useState<TradeCategory[]>([])
  const [expandedFamily, setExpandedFamily] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      setError(false)
      try {
        const [famRes, catRes] = await Promise.all([
          apiClient.get('/v2/trade-families'),
          apiClient.get('/v2/trade-categories'),
        ])
        const famData = famRes.data?.families ?? famRes.data
        const catData = catRes.data?.categories ?? catRes.data
        setFamilies(Array.isArray(famData) ? famData : [])
        setCategories(Array.isArray(catData) ? catData : [])
      } catch {
        setError(true)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  const toggleFamily = (familySlug: string) => {
    setExpandedFamily((prev) => (prev === familySlug ? null : familySlug))
  }

  const toggleCategory = (categorySlug: string) => {
    const current = data.selectedTradeCategories
    if (current.includes(categorySlug)) {
      const updated = current.filter((s) => s !== categorySlug)
      onChange({
        selectedTradeCategories: updated,
        tradeCategorySlug: updated[0] || '',
      })
    } else if (current.length < MAX_SELECTIONS) {
      const updated = [...current, categorySlug]
      onChange({
        selectedTradeCategories: updated,
        tradeCategorySlug: updated[0],
      })
    }
  }

  const familyCategories = (familySlug: string) =>
    categories.filter((c) => c.family_slug === familySlug)

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner label="Loading trade categories" />
      </div>
    )
  }

  if (error) {
    return (
      <AlertBanner variant="error" title="Failed to load trades">
        Could not load trade categories. You can skip this step and configure later.
      </AlertBanner>
    )
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-900">What does your business do?</h2>
      <p className="text-sm text-gray-500">
        Select up to {MAX_SELECTIONS} trade areas. This pre-configures modules, terminology, and default services.
      </p>

      {data.selectedTradeCategories.length > 0 && (
        <p className="text-xs text-blue-600 font-medium">
          {data.selectedTradeCategories.length} of {MAX_SELECTIONS} selected
        </p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {families.map((family) => {
          const icon = FAMILY_ICONS[family.slug] || '📦'
          const isExpanded = expandedFamily === family.slug
          const cats = familyCategories(family.slug)
          const hasSelected = cats.some((c) =>
            data.selectedTradeCategories.includes(c.slug),
          )

          return (
            <div key={family.slug} className={`col-span-1 ${isExpanded ? 'sm:col-span-3 col-span-2' : ''}`}>
              <button
                type="button"
                onClick={() => toggleFamily(family.slug)}
                aria-expanded={isExpanded}
                className={`w-full flex items-center gap-2 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
                  ${
                    hasSelected
                      ? 'border-blue-500 bg-blue-50 text-blue-800'
                      : isExpanded
                        ? 'border-gray-400 bg-gray-50 text-gray-800'
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50 text-gray-700'
                  }`}
              >
                <span className="text-lg" aria-hidden="true">{icon}</span>
                <span className="truncate flex-1">{family.display_name}</span>
                <span className="text-gray-400 text-xs" aria-hidden="true">
                  {isExpanded ? '▲' : '▼'}
                </span>
              </button>

              {isExpanded && cats.length > 0 && (
                <div className="mt-1 ml-2 space-y-1" role="group" aria-label={`${family.display_name} trade types`}>
                  {cats.map((cat) => {
                    const isSelected = data.selectedTradeCategories.includes(cat.slug)
                    const isDisabled = !isSelected && data.selectedTradeCategories.length >= MAX_SELECTIONS

                    return (
                      <button
                        key={cat.slug}
                        type="button"
                        onClick={() => toggleCategory(cat.slug)}
                        disabled={isDisabled}
                        className={`w-full flex items-center gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors
                          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
                          ${
                            isSelected
                              ? 'border-blue-500 bg-blue-100 text-blue-800'
                              : isDisabled
                                ? 'border-gray-100 bg-gray-50 text-gray-400 cursor-not-allowed'
                                : 'border-gray-200 hover:border-blue-300 hover:bg-blue-50 text-gray-700'
                          }`}
                        aria-pressed={isSelected}
                      >
                        <span className="text-base" aria-hidden="true">{cat.icon || '•'}</span>
                        <div className="flex-1 min-w-0">
                          <span className="block truncate">{cat.display_name}</span>
                          {cat.description && (
                            <span className="block text-xs text-gray-500 truncate">{cat.description}</span>
                          )}
                        </div>
                        {isSelected && (
                          <span className="text-blue-600 text-xs font-medium" aria-hidden="true">✓</span>
                        )}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
