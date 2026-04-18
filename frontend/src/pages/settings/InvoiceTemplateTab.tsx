import { useState, useEffect, useCallback } from 'react'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

/* ── Types ── */

interface TemplateInfo {
  id: string
  display_name: string
  description: string
  thumbnail_path: string
  default_primary_colour: string
  default_accent_colour: string
  default_header_bg_colour: string
  logo_position: string
  layout_type: string
}

interface ColourOverrides {
  primary_colour: string
  accent_colour: string
  header_bg_colour: string
}

/* ── TemplateCard ── */

interface TemplateCardProps {
  template: TemplateInfo
  isSelected: boolean
  isCurrent: boolean
  isDefault: boolean
  onSelect: (id: string) => void
  onPreview: (templateId: string) => void
  previewLoadingId: string | null
}

function TemplateCard({ template, isSelected, isCurrent, isDefault, onSelect, onPreview, previewLoadingId }: TemplateCardProps) {
  const [imgError, setImgError] = useState(false)
  const isLoadingPreview = previewLoadingId === template.id

  return (
    <div
      className={`group relative flex flex-col rounded-lg border-2 bg-white p-3 text-left transition-colors ${
        isSelected
          ? 'border-blue-600 ring-1 ring-blue-600'
          : 'border-gray-200 hover:border-gray-300'
      }`}
    >
      {/* Badges */}
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        {isCurrent && (
          <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
            Current
          </span>
        )}
        {isDefault && !isCurrent && (
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
            Default
          </span>
        )}
      </div>

      {/* Thumbnail with hover overlay */}
      <button
        type="button"
        onClick={() => onSelect(template.id)}
        className="relative mb-3 aspect-[1/1.4] w-full overflow-hidden rounded bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        aria-label={`Select ${template.display_name} template`}
      >
        {imgError ? (
          <div className="flex h-full w-full items-center justify-center p-4 text-center">
            <span className="text-sm font-medium text-gray-500">{template.display_name}</span>
          </div>
        ) : (
          <img
            src={`/${template.thumbnail_path}`}
            alt={`${template.display_name} template preview`}
            loading="lazy"
            className="h-full w-full object-cover"
            onError={() => setImgError(true)}
          />
        )}

        {/* Hover overlay with Preview button */}
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => {
              e.stopPropagation()
              onPreview(template.id)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.stopPropagation()
                e.preventDefault()
                onPreview(template.id)
              }
            }}
            className="rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-900 shadow-lg transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            {isLoadingPreview ? 'Loading…' : '👁 Preview'}
          </span>
        </div>
      </button>

      {/* Info — clicking selects the template */}
      <button
        type="button"
        onClick={() => onSelect(template.id)}
        className="text-left focus-visible:outline-none"
        aria-label={`Select ${template.display_name}`}
      >
        <h3 className="text-sm font-semibold text-gray-900">{template.display_name}</h3>
        <p className="mt-1 text-xs text-gray-500 line-clamp-2">{template.description}</p>
      </button>

      {/* Labels */}
      <div className="mt-2 flex flex-wrap gap-1">
        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] font-medium text-gray-600 capitalize">
          {template.logo_position} logo
        </span>
        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] font-medium text-gray-600 capitalize">
          {template.layout_type}
        </span>
      </div>
    </div>
  )
}

/* ── FilterPill ── */

interface FilterPillProps {
  label: string
  isActive: boolean
  onClick: () => void
}

function FilterPill({ label, isActive, onClick }: FilterPillProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
        isActive
          ? 'bg-blue-600 text-white'
          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
      }`}
    >
      {label}
    </button>
  )
}

/* ── InvoiceTemplateTab ── */

const LAYOUT_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'standard', label: 'Standard' },
  { value: 'compact', label: 'Compact' },
] as const

const LOGO_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'left', label: 'Left' },
  { value: 'center', label: 'Center' },
  { value: 'side', label: 'Side' },
] as const

/** Extract default colours from a template. Returns fallback greys if template is missing. */
function getDefaultColours(template: TemplateInfo | undefined): ColourOverrides {
  return {
    primary_colour: template?.default_primary_colour ?? '#000000',
    accent_colour: template?.default_accent_colour ?? '#000000',
    header_bg_colour: template?.default_header_bg_colour ?? '#ffffff',
  }
}

export function InvoiceTemplateTab() {
  const [templates, setTemplates] = useState<TemplateInfo[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [savedTemplateId, setSavedTemplateId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [layoutFilter, setLayoutFilter] = useState('all')
  const [logoFilter, setLogoFilter] = useState('all')
  const [colourOverrides, setColourOverrides] = useState<ColourOverrides>({
    primary_colour: '#000000',
    accent_colour: '#000000',
    header_bg_colour: '#ffffff',
  })
  const [previewHtml, setPreviewHtml] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewLoadingId, setPreviewLoadingId] = useState<string | null>(null)
  const [previewTemplateName, setPreviewTemplateName] = useState<string>('')
  const [previewTemplateId, setPreviewTemplateId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [savingFromPreview, setSavingFromPreview] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  // The first template in the registry is the default when nothing is saved
  const defaultTemplateId = (templates ?? [])[0]?.id ?? null

  // The currently selected template object (if any)
  const selectedTemplate = (templates ?? []).find((t) => t?.id === selectedId)

  // Filter templates based on selected filter values
  const filteredTemplates = (templates ?? []).filter((t) => {
    const matchesLayout = layoutFilter === 'all' || t?.layout_type === layoutFilter
    const matchesLogo = logoFilter === 'all' || t?.logo_position === logoFilter
    return matchesLayout && matchesLogo
  })

  // When selectedId changes, reset colour overrides to the new template's defaults
  useEffect(() => {
    if (selectedId) {
      const tpl = (templates ?? []).find((t) => t?.id === selectedId)
      setColourOverrides(getDefaultColours(tpl))
    }
  }, [selectedId, templates])

  const handleResetColours = useCallback(() => {
    setColourOverrides(getDefaultColours(selectedTemplate))
  }, [selectedTemplate])

  const handleColourChange = useCallback(
    (field: keyof ColourOverrides, value: string) => {
      setColourOverrides((prev) => ({ ...prev, [field]: value }))
    },
    [],
  )

  const handlePreview = useCallback(async () => {
    if (!selectedId) return
    setPreviewLoading(true)
    try {
      const res = await apiClient.post<{ html: string }>('/invoices/invoice-templates/preview', {
        template_id: selectedId,
        primary_colour: colourOverrides.primary_colour,
        accent_colour: colourOverrides.accent_colour,
        header_bg_colour: colourOverrides.header_bg_colour,
      })
      const html = res.data?.html ?? ''
      setPreviewHtml(html)
      setPreviewTemplateName(selectedTemplate?.display_name ?? 'Unknown')
      setPreviewTemplateId(selectedId)
    } catch {
      addToast('error', 'Failed to generate preview')
    } finally {
      setPreviewLoading(false)
    }
  }, [selectedId, colourOverrides, addToast])

  const handleCardPreview = useCallback(async (templateId: string) => {
    const tpl = (templates ?? []).find((t) => t?.id === templateId)
    if (!tpl) return
    setPreviewLoadingId(templateId)
    try {
      const res = await apiClient.post<{ html: string }>('/invoices/invoice-templates/preview', {
        template_id: templateId,
        primary_colour: tpl.default_primary_colour,
        accent_colour: tpl.default_accent_colour,
        header_bg_colour: tpl.default_header_bg_colour,
      })
      const html = res.data?.html ?? ''
      setPreviewHtml(html)
      setPreviewTemplateName(tpl.display_name)
      setPreviewTemplateId(templateId)
    } catch {
      addToast('error', 'Failed to generate preview')
    } finally {
      setPreviewLoadingId(null)
    }
  }, [templates, addToast])

  const handleSave = useCallback(async () => {
    if (!selectedId) return
    setSaving(true)
    try {
      await apiClient.put('/org/settings', {
        invoice_template_id: selectedId,
        invoice_template_colours: colourOverrides,
      })
      setSavedTemplateId(selectedId)
      addToast('success', 'Invoice template saved')
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } }
      if (axiosErr?.response?.status === 422) {
        const detail = axiosErr.response?.data?.detail ?? 'Invalid template settings'
        addToast('error', String(detail))
      } else {
        addToast('error', 'Failed to save template settings')
      }
    } finally {
      setSaving(false)
    }
  }, [selectedId, colourOverrides, addToast])

  const handleSetDefaultFromPreview = useCallback(async () => {
    if (!previewTemplateId) return
    setSavingFromPreview(true)
    const tpl = (templates ?? []).find((t) => t?.id === previewTemplateId)
    const defaultColours = tpl
      ? { primary_colour: tpl.default_primary_colour, accent_colour: tpl.default_accent_colour, header_bg_colour: tpl.default_header_bg_colour }
      : colourOverrides
    try {
      await apiClient.put('/org/settings', {
        invoice_template_id: previewTemplateId,
        invoice_template_colours: defaultColours,
      })
      setSavedTemplateId(previewTemplateId)
      setSelectedId(previewTemplateId)
      setColourOverrides(defaultColours as ColourOverrides)
      addToast('success', `${tpl?.display_name ?? 'Template'} set as default`)
      setPreviewHtml(null)
    } catch {
      addToast('error', 'Failed to set default template')
    } finally {
      setSavingFromPreview(false)
    }
  }, [previewTemplateId, templates, colourOverrides, addToast])

  useEffect(() => {
    const controller = new AbortController()

    const fetchData = async () => {
      try {
        const [templatesRes, settingsRes] = await Promise.all([
          apiClient.get<{ templates: TemplateInfo[] }>('/invoices/invoice-templates', {
            signal: controller.signal,
          }),
          apiClient.get('/org/settings', { signal: controller.signal }),
        ])

        const templateList = templatesRes.data?.templates ?? []
        setTemplates(templateList)

        const currentId = settingsRes.data?.invoice_template_id ?? null
        setSavedTemplateId(currentId)

        // Pre-select the saved template, or the first template if none saved
        const initialId = currentId ?? templateList[0]?.id ?? null
        setSelectedId(initialId)

        // Initialize colour overrides from the saved settings or template defaults
        const savedColours = settingsRes.data?.invoice_template_colours
        const initialTemplate = templateList.find((t: TemplateInfo) => t?.id === initialId)
        if (savedColours && currentId) {
          setColourOverrides({
            primary_colour: savedColours?.primary_colour ?? initialTemplate?.default_primary_colour ?? '#000000',
            accent_colour: savedColours?.accent_colour ?? initialTemplate?.default_accent_colour ?? '#000000',
            header_bg_colour: savedColours?.header_bg_colour ?? initialTemplate?.default_header_bg_colour ?? '#ffffff',
          })
        } else {
          setColourOverrides(getDefaultColours(initialTemplate))
        }
      } catch {
        if (!controller.signal.aborted) {
          addToast('error', 'Failed to load templates')
        }
      } finally {
        setLoading(false)
      }
    }

    fetchData()
    return () => controller.abort()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return <p className="text-sm text-gray-500">Loading templates…</p>
  }

  return (
    <div className="space-y-6">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div>
        <h2 className="text-lg font-medium text-gray-900">Invoice Template</h2>
        <p className="mt-1 text-sm text-gray-500">
          Choose a template for your invoice PDFs. Each template has a unique layout and colour scheme.
        </p>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-500">Layout:</span>
          {LAYOUT_FILTERS.map((f) => (
            <FilterPill
              key={f.value}
              label={f.label}
              isActive={layoutFilter === f.value}
              onClick={() => setLayoutFilter(f.value)}
            />
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-500">Logo:</span>
          {LOGO_FILTERS.map((f) => (
            <FilterPill
              key={f.value}
              label={f.label}
              isActive={logoFilter === f.value}
              onClick={() => setLogoFilter(f.value)}
            />
          ))}
        </div>
      </div>

      {/* Template Grid */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {filteredTemplates.map((template) => (
          <TemplateCard
            key={template.id}
            template={template}
            isSelected={selectedId === template.id}
            isCurrent={savedTemplateId != null && savedTemplateId === template.id}
            isDefault={savedTemplateId == null && template.id === defaultTemplateId}
            onSelect={setSelectedId}
            onPreview={handleCardPreview}
            previewLoadingId={previewLoadingId}
          />
        ))}
      </div>

      {filteredTemplates.length === 0 && (
        <p className="text-sm text-gray-500">No templates match the selected filters.</p>
      )}

      {/* Colour Customisation */}
      {selectedId && selectedTemplate && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Colour Customisation</h3>
              <p className="mt-0.5 text-xs text-gray-500">
                Adjust the colour scheme for {selectedTemplate.display_name}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handlePreview}
                disabled={previewLoading}
                className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                {previewLoading ? 'Loading…' : 'Preview'}
              </button>
              <button
                type="button"
                onClick={handleResetColours}
                className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                Reset to Defaults
              </button>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-6">
            <label className="flex items-center gap-2">
              <input
                type="color"
                value={colourOverrides.primary_colour}
                onChange={(e) => handleColourChange('primary_colour', e.target.value)}
                className="h-8 w-8 cursor-pointer rounded border border-gray-300"
              />
              <span className="text-sm text-gray-700">Primary Colour</span>
            </label>

            <label className="flex items-center gap-2">
              <input
                type="color"
                value={colourOverrides.accent_colour}
                onChange={(e) => handleColourChange('accent_colour', e.target.value)}
                className="h-8 w-8 cursor-pointer rounded border border-gray-300"
              />
              <span className="text-sm text-gray-700">Accent Colour</span>
            </label>

            <label className="flex items-center gap-2">
              <input
                type="color"
                value={colourOverrides.header_bg_colour}
                onChange={(e) => handleColourChange('header_bg_colour', e.target.value)}
                className="h-8 w-8 cursor-pointer rounded border border-gray-300"
              />
              <span className="text-sm text-gray-700">Header Background</span>
            </label>
          </div>
        </div>
      )}

      {/* Save Button */}
      {selectedId && (
        <div>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}

      {/* Preview Modal */}
      {previewHtml !== null && (
        <div
          className="fixed inset-0 z-50 overflow-y-auto bg-black/50"
          onClick={() => { setPreviewHtml(null); setPreviewTemplateId(null) }}
          role="dialog"
          aria-modal="true"
          aria-label="Invoice template preview"
        >
          <div className="flex min-h-full items-start justify-center p-4 sm:p-8">
            <div
              className="relative w-full max-w-4xl rounded-lg bg-white shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="sticky top-0 z-10 flex items-center justify-between rounded-t-lg border-b border-gray-200 bg-white px-5 py-3">
                <h3 className="text-sm font-semibold text-gray-900">
                  Template Preview — {previewTemplateName || 'Unknown'}
                </h3>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleSetDefaultFromPreview}
                    disabled={savingFromPreview || savedTemplateId === previewTemplateId}
                    className={`rounded-md px-3 py-1.5 text-xs font-medium shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                      savedTemplateId === previewTemplateId
                        ? 'bg-green-100 text-green-700 cursor-default'
                        : 'bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50'
                    }`}
                  >
                    {savingFromPreview
                      ? 'Saving…'
                      : savedTemplateId === previewTemplateId
                        ? '✓ Current Default'
                        : 'Set as Default'}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setPreviewHtml(null); setPreviewTemplateId(null) }}
                    className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                    aria-label="Close preview"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                    </svg>
                  </button>
                </div>
              </div>
              <div className="p-4">
                <iframe
                  srcDoc={previewHtml}
                  title="Invoice template preview"
                  className="w-full rounded border border-gray-200"
                  sandbox="allow-same-origin"
                  style={{ height: '1200px', maxHeight: 'none' }}
                  scrolling="no"
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
