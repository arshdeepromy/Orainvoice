import { useState, useEffect } from 'react'
import { Spinner, AlertBanner } from '@/components/ui'
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
    const controller = new AbortController()
    const fetchData = async () => {
      setLoading(true)
      setError(false)
      try {
        const [famRes, catRes] = await Promise.all([
          apiClient.get('/api/v2/trade-families', { signal: controller.signal }),
          apiClient.get('/api/v2/trade-categories', { signal: controller.signal }),
        ])
        const famData = famRes.data?.families ?? famRes.data
        const catData = catRes.data?.categories ?? catRes.data
        setFamilies(Array.isArray(famData) ? famData : [])
        setCategories(Array.isArray(catData) ? catData : [])
      } catch {
        if (!controller.signal.aborted) setError(true)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchData()
    return () => controller.abort()
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
      <h2 className="text-xl font-semibold text-text">What does your business do?</h2>
      <p className="text-sm text-muted">
        Select up to {MAX_SELECTIONS} trade areas. This pre-configures modules, terminology, and default services.
      </p>

      {data.selectedTradeCategories.length > 0 && (
        <p className="text-xs text-accent font-medium">
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
                className={`w-full flex items-center gap-2 rounded-ctl border px-3 py-2.5 text-left text-sm transition-colors
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent
                  ${
                    hasSelected
                      ? 'border-accent bg-accent-soft text-accent'
                      : isExpanded
                        ? 'border-border-strong bg-canvas text-text'
                        : 'border-border hover:border-border-strong hover:bg-canvas text-text'
                  }`}
              >
                <span className="text-lg" aria-hidden="true">{icon}</span>
                <span className="truncate flex-1">{family.display_name}</span>
                <span className="text-muted-2 text-xs" aria-hidden="true">
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
                        className={`w-full flex items-center gap-2 rounded-ctl border px-3 py-2 text-left text-sm transition-colors
                          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent
                          ${
                            isSelected
                              ? 'border-accent bg-accent-soft text-accent'
                              : isDisabled
                                ? 'border-border bg-canvas text-muted-2 cursor-not-allowed'
                                : 'border-border hover:border-accent/40 hover:bg-accent-soft text-text'
                          }`}
                        aria-pressed={isSelected}
                      >
                        <span className="text-base" aria-hidden="true">{cat.icon || '•'}</span>
                        <div className="flex-1 min-w-0">
                          <span className="block truncate">{cat.display_name}</span>
                          {cat.description && (
                            <span className="block text-xs text-muted truncate">{cat.description}</span>
                          )}
                        </div>
                        {isSelected && (
                          <span className="text-accent text-xs font-medium" aria-hidden="true">✓</span>
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
