import { useState, useEffect, useMemo } from 'react'
import { Spinner, AlertBanner } from '@/components/ui'
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
    const controller = new AbortController()
    const fetchModules = async () => {
      setLoading(true)
      setError(false)
      try {
        const res = await apiClient.get('/api/v2/modules', { signal: controller.signal })
        const mods: ModuleInfo[] = res.data?.modules ?? res.data ?? []
        setModules(mods)
      } catch {
        if (!controller.signal.aborted) setError(true)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchModules()
    return () => controller.abort()
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
      <h2 className="text-xl font-semibold text-text">Choose Your Modules</h2>
      <p className="text-sm text-muted">
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
            <legend className="text-sm font-semibold text-text mb-2">
              {category}
            </legend>
            <div className="space-y-1">
              {mods.map((mod) => {
                const checked = isEnabled(mod.slug)
                const isCore = mod.is_core

                return (
                  <label
                    key={mod.slug}
                    className={`flex items-start gap-3 rounded-ctl border px-3 py-2 cursor-pointer transition-colors
                      ${
                        checked
                          ? 'border-accent/40 bg-accent-soft'
                          : 'border-border hover:bg-canvas'
                      }
                      ${isCore ? 'opacity-70 cursor-not-allowed' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => !isCore && toggleModule(mod.slug)}
                      disabled={isCore}
                      className="mt-0.5 rounded border-border text-accent focus:ring-accent"
                    />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium text-text">
                        {mod.display_name}
                        {isCore && (
                          <span className="ml-1 text-xs text-muted">(core)</span>
                        )}
                      </span>
                      <p className="text-xs text-muted mt-0.5">{mod.description}</p>
                      {mod.dependencies.length > 0 && (
                        <p className="text-xs text-muted-2 mt-0.5">
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

      <p className="text-xs text-muted-2">
        {data.enabledModules.length} module{data.enabledModules.length !== 1 ? 's' : ''} selected
      </p>
    </div>
  )
}
