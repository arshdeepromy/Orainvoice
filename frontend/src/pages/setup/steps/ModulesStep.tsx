import { useState, useEffect, useMemo } from 'react'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import apiClient from '@/api/client'
import type { WizardData, ModuleInfo } from '../types'

interface ModulesStepProps {
  data: WizardData
  onChange: (updates: Partial<WizardData>) => void
}

export function ModulesStep({ data, onChange }: ModulesStepProps) {
  const [modules, setModules] = useState<ModuleInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [warnings, setWarnings] = useState<string[]>([])

  useEffect(() => {
    const fetchModules = async () => {
      setLoading(true)
      setError(false)
      try {
        const res = await apiClient.get('/api/v2/modules')
        const mods: ModuleInfo[] = res.data?.modules ?? res.data ?? []
        setModules(mods)
      } catch {
        setError(true)
      } finally {
        setLoading(false)
      }
    }
    fetchModules()
  }, [])

  const grouped = useMemo(() => {
    const groups: Record<string, ModuleInfo[]> = {}
    for (const mod of modules) {
      const cat = mod.category || 'Other'
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(mod)
    }
    return groups
  }, [modules])

  const isEnabled = (slug: string) => data.enabledModules.includes(slug)

  const getDependents = (slug: string): string[] =>
    modules
      .filter((m) => m.dependencies.includes(slug) && isEnabled(m.slug))
      .map((m) => m.display_name)

  const toggleModule = (slug: string) => {
    const newWarnings: string[] = []

    if (isEnabled(slug)) {
      // Disabling — check dependents
      const dependents = getDependents(slug)
      if (dependents.length > 0) {
        newWarnings.push(
          `Disabling this will also affect: ${dependents.join(', ')}`,
        )
      }
      onChange({
        enabledModules: data.enabledModules.filter((s) => s !== slug),
      })
    } else {
      // Enabling — auto-enable dependencies
      const mod = modules.find((m) => m.slug === slug)
      const toEnable = new Set(data.enabledModules)
      toEnable.add(slug)
      if (mod) {
        for (const dep of mod.dependencies) {
          if (!toEnable.has(dep)) {
            const depMod = modules.find((m) => m.slug === dep)
            newWarnings.push(
              `Auto-enabled dependency: ${depMod?.display_name || dep}`,
            )
            toEnable.add(dep)
          }
        }
      }
      onChange({ enabledModules: Array.from(toEnable) })
    }

    setWarnings(newWarnings)
    if (newWarnings.length > 0) {
      setTimeout(() => setWarnings([]), 5000)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner label="Loading modules" />
      </div>
    )
  }

  if (error) {
    return (
      <AlertBanner variant="error" title="Failed to load modules">
        Could not load available modules. You can skip this step and configure later.
      </AlertBanner>
    )
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-900">Choose Your Modules</h2>
      <p className="text-sm text-gray-500">
        Select the features you need. Trade-recommended modules are pre-selected.
      </p>

      {warnings.length > 0 && (
        <AlertBanner variant="warning" title="Module dependency">
          {warnings.map((w, i) => (
            <p key={i}>{w}</p>
          ))}
        </AlertBanner>
      )}

      <div className="space-y-6 max-h-96 overflow-y-auto pr-1">
        {Object.entries(grouped).map(([category, mods]) => (
          <fieldset key={category}>
            <legend className="text-sm font-semibold text-gray-800 mb-2">
              {category}
            </legend>
            <div className="space-y-1">
              {mods.map((mod) => {
                const checked = isEnabled(mod.slug)
                const isCore = mod.is_core

                return (
                  <label
                    key={mod.slug}
                    className={`flex items-start gap-3 rounded-md border px-3 py-2 cursor-pointer transition-colors
                      ${
                        checked
                          ? 'border-blue-300 bg-blue-50'
                          : 'border-gray-200 hover:bg-gray-50'
                      }
                      ${isCore ? 'opacity-70 cursor-not-allowed' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => !isCore && toggleModule(mod.slug)}
                      disabled={isCore}
                      className="mt-0.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium text-gray-800">
                        {mod.display_name}
                        {isCore && (
                          <span className="ml-1 text-xs text-gray-500">(core)</span>
                        )}
                      </span>
                      <p className="text-xs text-gray-500 mt-0.5">{mod.description}</p>
                      {mod.dependencies.length > 0 && (
                        <p className="text-xs text-gray-400 mt-0.5">
                          Requires: {mod.dependencies.join(', ')}
                        </p>
                      )}
                    </div>
                  </label>
                )
              })}
            </div>
          </fieldset>
        ))}
      </div>

      <p className="text-xs text-gray-400">
        {data.enabledModules.length} module{data.enabledModules.length !== 1 ? 's' : ''} selected
      </p>
    </div>
  )
}
