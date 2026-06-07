import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Spinner, Modal, Badge } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TemplateBlock {
  id: string
  type: 'logo' | 'header' | 'body' | 'text' | 'footer' | 'button' | 'divider' | 'image'
  content: string
  url?: string
}

interface NotificationTemplate {
  id: string
  template_type: string
  subject: string
  channel: 'email' | 'sms'
  body_blocks: TemplateBlock[]
  body?: string
  is_enabled: boolean
  updated_at: string
}

interface TemplatesResponse {
  templates: NotificationTemplate[]
}

const TEMPLATE_VARIABLES_BASE = [
  { variable: '{{customer_first_name}}', description: 'Customer first name' },
  { variable: '{{customer_last_name}}', description: 'Customer last name' },
  { variable: '{{customer_email}}', description: 'Customer email address' },
  { variable: '{{invoice_number}}', description: 'Invoice number' },
  { variable: '{{total_due}}', description: 'Total amount due' },
  { variable: '{{due_date}}', description: 'Invoice due date' },
  { variable: '{{payment_link}}', description: 'Online payment link (Stripe)' },
  { variable: '{{org_name}}', description: 'Organisation name' },
  { variable: '{{org_phone}}', description: 'Organisation phone' },
  { variable: '{{org_email}}', description: 'Organisation email' },
  { variable: '{{user_name}}', description: "User's full name" },
  { variable: '{{reset_link}}', description: 'Password reset link' },
  { variable: '{{signup_link}}', description: 'Invitation signup link' },
]

const TEMPLATE_VARIABLES_VEHICLE = [
  { variable: '{{vehicle_rego}}', description: 'Vehicle registration' },
  { variable: '{{vehicle_make}}', description: 'Vehicle make' },
  { variable: '{{vehicle_model}}', description: 'Vehicle model' },
  { variable: '{{expiry_date}}', description: 'WOF or rego expiry date' },
  { variable: '{{service_due_date}}', description: 'Next service due date' },
]

const TEMPLATE_VARIABLES_BOOKING = [
  { variable: '{{booking_date}}', description: 'Booking date and time' },
  { variable: '{{booking_service}}', description: 'Booked service type' },
]

const TEMPLATE_VARIABLES_QUOTE = [
  { variable: '{{quote_number}}', description: 'Quote reference number' },
  { variable: '{{quote_total}}', description: 'Quote total amount' },
  { variable: '{{quote_valid_until}}', description: 'Quote expiry date' },
]

// Statement and portal-link variables — always shown (invoice_payment_link reuses
// the base invoice variables, so it needs no additional entries here)
const TEMPLATE_VARIABLES_STATEMENT_PORTAL = [
  { variable: '{{statement_period_start}}', description: 'Statement period start date' },
  { variable: '{{statement_period_end}}', description: 'Statement period end date' },
  { variable: '{{total_outstanding}}', description: 'Total outstanding balance' },
  { variable: '{{statement_link}}', description: 'Online customer statement link' },
  { variable: '{{portal_link}}', description: 'Customer portal access link' },
]

const BLOCK_TYPES = [
  { value: 'logo', label: 'Logo' },
  { value: 'header', label: 'Header Text' },
  { value: 'text', label: 'Body Text' },
  { value: 'button', label: 'Button' },
  { value: 'divider', label: 'Divider' },
  { value: 'footer', label: 'Footer' },
]

/** Format a template_type like "invoice_issued" into "Invoice Issued" */
function formatTemplateType(templateType: string): string {
  return templateType
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

/**
 * Template editor — visual block editor with drag-and-drop, template variables,
 * and preview mode. Supports both email (block editor) and SMS (text editor with
 * 160-char warning).
 *
 * Requirements: 34.1, 34.2, 34.3, 36.3, 36.4, 36.5
 */
export default function TemplateEditor() {
  const [templates, setTemplates] = useState<NotificationTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<NotificationTemplate | null>(null)
  const [editBlocks, setEditBlocks] = useState<TemplateBlock[]>([])
  const [editSubject, setEditSubject] = useState('')
  const [editSmsText, setEditSmsText] = useState('')
  const [editEnabled, setEditEnabled] = useState(false)
  const [saving, setSaving] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [variablesOpen, setVariablesOpen] = useState(false)
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [channelFilter, setChannelFilter] = useState<'all' | 'email' | 'sms'>('all')
  const { isEnabled } = useModules()

  // Build template variables list — vehicle/booking/quote vars shown when their modules are enabled
  const templateVariables = [
    ...TEMPLATE_VARIABLES_BASE,
    ...TEMPLATE_VARIABLES_STATEMENT_PORTAL,
    ...(isEnabled('vehicles') ? TEMPLATE_VARIABLES_VEHICLE : []),
    ...(isEnabled('bookings') ? TEMPLATE_VARIABLES_BOOKING : []),
    ...(isEnabled('quotes') ? TEMPLATE_VARIABLES_QUOTE : []),
  ]

  const fetchTemplates = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [emailRes, smsRes] = await Promise.all([
        apiClient.get<TemplatesResponse>('/notifications/templates'),
        apiClient.get<TemplatesResponse>('/notifications/sms-templates'),
      ])
      const emailTemplates = (emailRes.data.templates || []).map((t) => ({ ...t, channel: 'email' as const }))
      const smsTemplates = (smsRes.data.templates || []).map((t) => ({ ...t, channel: 'sms' as const }))
      setTemplates([...emailTemplates, ...smsTemplates])
    } catch {
      setError('Failed to load templates.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchTemplates() }, [fetchTemplates])

  const selectTemplate = (t: NotificationTemplate) => {
    setSelected(t)
    setEditSubject(t.subject)
    setEditBlocks((t.body_blocks || []).map((b) => ({ ...b })))
    setEditSmsText(t.body || '')
    setEditEnabled(t.is_enabled ?? false)
  }

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    setError('')
    try {
      const payload = selected.channel === 'sms'
        ? { body: editSmsText, is_enabled: editEnabled }
        : { subject: editSubject, body_blocks: editBlocks, is_enabled: editEnabled }
      const endpoint = selected.channel === 'sms'
        ? `/notifications/sms-templates/${selected.template_type}`
        : `/notifications/templates/${selected.template_type}`
      await apiClient.put(endpoint, payload)
      await fetchTemplates()
      setSelected(null)
    } catch {
      setError('Failed to save template.')
    } finally {
      setSaving(false)
    }
  }

  /* Block editor helpers */
  const updateBlock = (index: number, content: string) => {
    setEditBlocks((prev) => prev.map((b, i) => (i === index ? { ...b, content } : b)))
  }

  const addBlock = (type: TemplateBlock['type']) => {
    setEditBlocks((prev) => [
      ...prev,
      { id: `block-${Date.now()}`, type, content: '' },
    ])
  }

  const removeBlock = (index: number) => {
    setEditBlocks((prev) => prev.filter((_, i) => i !== index))
  }

  const moveBlock = (from: number, to: number) => {
    setEditBlocks((prev) => {
      const next = [...prev]
      const [moved] = next.splice(from, 1)
      next.splice(to, 0, moved)
      return next
    })
  }

  /* Drag-and-drop handlers */
  const handleDragStart = (index: number) => setDragIndex(index)
  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault()
    if (dragIndex !== null && dragIndex !== index) {
      moveBlock(dragIndex, index)
      setDragIndex(index)
    }
  }
  const handleDragEnd = () => setDragIndex(null)

  /* Preview rendering — calls backend API for real org data substitution */
  const [previewHtml, setPreviewHtml] = useState<{ subject: string; html_body: string } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  const loadPreview = async () => {
    if (!selected || selected.channel === 'sms') return
    setPreviewLoading(true)
    try {
      const res = await apiClient.get<{ subject: string; html_body: string }>(
        `/notifications/templates/${selected.template_type}/preview`
      )
      setPreviewHtml(res.data ?? null)
    } catch {
      setPreviewHtml(null)
    } finally {
      setPreviewLoading(false)
    }
  }

  const substituteVars = (text: string): string => {
    // Fallback for SMS preview (client-side only since no backend preview for SMS)
    const SAMPLE_VALUES: Record<string, string> = {
      customer_first_name: 'Jane',
      customer_last_name: 'Smith',
      customer_email: 'jane@example.com',
      invoice_number: 'INV-0042',
      total_due: '$150.00',
      due_date: '15/01/2025',
      payment_link: 'https://pay.example.com/inv-0042',
      org_name: 'Your Organisation',
      org_phone: '09 555 1234',
      org_email: 'info@example.co.nz',
      vehicle_rego: 'ABC123',
      vehicle_make: 'Toyota',
      vehicle_model: 'Corolla',
      expiry_date: '28/02/2025',
      service_due_date: '15/03/2025',
      booking_date: 'Monday 10 February 2025 at 09:00 AM',
      booking_service: 'Full Service',
      quote_number: 'QT-0018',
      quote_total: '$420.00',
      quote_valid_until: '28/02/2025',
      user_name: 'John Doe',
      reset_link: 'https://app.example.com/reset/abc123',
      signup_link: 'https://app.example.com/signup/abc123',
    }
    return text.replace(/\{\{(\w+)\}\}/g, (_, varName) => SAMPLE_VALUES[varName] ?? '')
  }

  const renderPreview = () => {
    if (!selected) return null
    if (selected.channel === 'sms') {
      return (
        <div className="rounded-card border border-border bg-canvas p-4">
          <p className="text-sm font-medium text-text mb-2">SMS Preview</p>
          <div className="rounded-ctl bg-card p-3 text-sm text-text whitespace-pre-wrap">
            {substituteVars(editSmsText) || '(empty)'}
          </div>
          <p className={`mt-2 text-xs ${editSmsText.length > 160 ? 'text-danger font-medium' : 'text-muted'}`}>
            {editSmsText.length}/160 characters{editSmsText.length > 160 && ' - exceeds single SMS limit'}
          </p>
        </div>
      )
    }
    if (previewLoading) {
      return <div className="py-8 flex justify-center"><Spinner label="Loading preview" /></div>
    }
    if (previewHtml) {
      return (
        <div className="rounded-card border border-border bg-card p-6 space-y-4">
          <p className="text-xs text-muted mb-2">Subject: <strong>{previewHtml.subject}</strong></p>
          <div
            className="text-sm text-text prose prose-sm max-w-none"
            dangerouslySetInnerHTML={{ __html: previewHtml.html_body }}
          />
        </div>
      )
    }
    return <p className="text-sm text-muted py-4">Preview not available.</p>
  }

  const VEHICLE_TEMPLATE_TYPES = ['wof_expiry_reminder', 'registration_expiry_reminder']

  const filteredTemplates = templates.filter((t) => {
    if (channelFilter !== 'all' && t.channel !== channelFilter) return false
    // Hide vehicle-related templates when vehicles module is disabled
    if (!isEnabled('vehicles') && VEHICLE_TEMPLATE_TYPES.includes(t.template_type)) return false
    return true
  })

  if (loading) {
    return <div className="py-16"><Spinner label="Loading templates" /></div>
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-muted">
          Customise email and SMS templates with drag-and-drop blocks and template variables.
        </p>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => setVariablesOpen(true)}>
            Variables Reference
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {/* Channel filter */}
      <div className="mb-4 flex gap-2">
        {(['all', 'email', 'sms'] as const).map((ch) => (
          <button
            key={ch}
            onClick={() => setChannelFilter(ch)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors
              ${channelFilter === ch
                ? 'bg-accent-soft text-accent border border-accent'
                : 'bg-canvas text-muted border border-border hover:bg-canvas'}`}
          >
            {ch === 'all' ? 'All' : ch.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Template list */}
        <div className="lg:col-span-1">
          <div className="rounded-card border border-border bg-card divide-y divide-border">
            {filteredTemplates.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-muted">No templates found.</p>
            ) : (
              filteredTemplates.map((t) => (
                <button
                  key={t.id}
                  onClick={() => selectTemplate(t)}
                  className={`w-full text-left px-4 py-3 hover:bg-canvas transition-colors
                    ${selected?.id === t.id ? 'bg-accent-soft border-l-2 border-accent' : ''}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-text">{formatTemplateType(t.template_type)}</span>
                    <Badge variant={t.channel === 'email' ? 'info' : 'neutral'}>
                      {t.channel.toUpperCase()}
                    </Badge>
                    {t.is_enabled && (
                      <Badge variant="success">Active</Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted mt-0.5">
                    Updated {new Date(t.updated_at).toLocaleDateString('en-NZ')}
                  </p>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Editor panel */}
        <div className="lg:col-span-2">
          {!selected ? (
            <div className="rounded-card border border-border bg-canvas px-4 py-16 text-center text-sm text-muted">
              Select a template from the list to edit it.
            </div>
          ) : selected.channel === 'sms' ? (
            /* SMS text editor */
            <div className="rounded-card border border-border bg-card p-4 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-medium text-text">{formatTemplateType(selected.template_type)}</h3>
                <Badge variant="neutral">SMS</Badge>
              </div>

              {/* Enable/Disable toggle */}
              <div className="flex items-center justify-between rounded-ctl border border-border bg-canvas px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-text">Use custom template</p>
                  <p className="text-xs text-muted">When enabled, SMS messages use this template instead of the default system content.</p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={editEnabled}
                  onClick={() => setEditEnabled(!editEnabled)}
                  className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 ${editEnabled ? 'bg-accent' : 'bg-border-strong'}`}
                >
                  <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-card shadow ring-0 transition duration-200 ease-in-out ${editEnabled ? 'translate-x-5' : 'translate-x-0'}`} />
                </button>
              </div>

              <Input
                label="Subject / Label"
                value={editSubject}
                onChange={(e) => setEditSubject(e.target.value)}
              />
              <div>
                <label htmlFor="sms-body" className="block text-sm font-medium text-text mb-1">
                  Message body
                </label>
                <textarea
                  id="sms-body"
                  rows={4}
                  value={editSmsText}
                  onChange={(e) => setEditSmsText(e.target.value)}
                  className="w-full rounded-ctl border border-border px-3 py-2 text-sm text-text shadow-sm focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent"
                />
                <p className={`mt-1 text-xs ${editSmsText.length > 160 ? 'text-danger font-medium' : 'text-muted'}`}>
                  {editSmsText.length}/160 characters
                  {editSmsText.length > 160 && ' - exceeds single SMS segment'}
                </p>
                <p className="mt-1 text-xs text-muted-2">
                  Standard text (GSM-7) allows 160 chars per SMS. Special characters or emojis reduce the limit to 70 chars.
                </p>
              </div>
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={() => setPreviewOpen(true)}>Preview</Button>
                <Button size="sm" onClick={handleSave} loading={saving}>Save Template</Button>
              </div>
            </div>
          ) : (
            /* Email block editor */
            <div className="rounded-card border border-border bg-card p-4 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-medium text-text">{formatTemplateType(selected.template_type)}</h3>
                <Badge variant="info">EMAIL</Badge>
              </div>

              {/* Enable/Disable toggle */}
              <div className="flex items-center justify-between rounded-ctl border border-border bg-canvas px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-text">Use custom template</p>
                  <p className="text-xs text-muted">When enabled, emails use this template instead of the default system content.</p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={editEnabled}
                  onClick={() => setEditEnabled(!editEnabled)}
                  className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 ${editEnabled ? 'bg-accent' : 'bg-border-strong'}`}
                >
                  <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-card shadow ring-0 transition duration-200 ease-in-out ${editEnabled ? 'translate-x-5' : 'translate-x-0'}`} />
                </button>
              </div>

              <Input
                label="Email subject"
                value={editSubject}
                onChange={(e) => setEditSubject(e.target.value)}
              />

              {/* Blocks */}
              <div>
                <p className="text-sm font-medium text-text mb-2">Content blocks</p>
                <div className="space-y-2">
                  {editBlocks.map((block, idx) => (
                    <div
                      key={block.id}
                      draggable
                      onDragStart={() => handleDragStart(idx)}
                      onDragOver={(e) => handleDragOver(e, idx)}
                      onDragEnd={handleDragEnd}
                      className={`rounded-ctl border p-3 transition-colors
                        ${dragIndex === idx ? 'border-accent bg-accent-soft' : 'border-border bg-canvas'}`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="cursor-grab text-muted-2" aria-label="Drag to reorder">⠿</span>
                          <Badge variant="neutral">{block.type}</Badge>
                        </div>
                        <button
                          onClick={() => removeBlock(idx)}
                          className="text-xs text-danger hover:brightness-95"
                          aria-label={`Remove ${block.type} block`}
                        >
                          Remove
                        </button>
                      </div>
                      {block.type === 'logo' ? (
                        <p className="text-xs text-muted italic">Organisation logo will be inserted automatically.</p>
                      ) : block.type === 'divider' ? (
                        <p className="text-xs text-muted italic">Horizontal divider line.</p>
                      ) : (
                        <>
                          <textarea
                            rows={block.type === 'body' || block.type === 'text' ? 4 : 2}
                            value={block.content}
                            onChange={(e) => updateBlock(idx, e.target.value)}
                            placeholder={`Enter ${block.type === 'button' ? 'button label' : block.type + ' text'}… Use {{variables}} for dynamic content.`}
                            className="w-full rounded-ctl border border-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent"
                          />
                          {block.type === 'button' && (
                            <input
                              type="text"
                              value={block.url || ''}
                              onChange={(e) => {
                                const updated = [...editBlocks]
                                updated[idx] = { ...updated[idx], url: e.target.value }
                                setEditBlocks(updated)
                              }}
                              placeholder="Button URL… e.g. {{payment_link}}"
                              className="mt-2 w-full rounded-ctl border border-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent"
                            />
                          )}
                        </>
                      )}
                    </div>
                  ))}
                </div>

                {/* Add block */}
                <div className="mt-3 flex flex-wrap gap-2">
                  {BLOCK_TYPES.map((bt) => (
                    <Button
                      key={bt.value}
                      size="sm"
                      variant="ghost"
                      onClick={() => addBlock(bt.value as TemplateBlock['type'])}
                    >
                      + {bt.label}
                    </Button>
                  ))}
                </div>
              </div>

              <div className="flex justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={() => { setPreviewOpen(true); loadPreview() }}>Preview</Button>
                <Button size="sm" onClick={handleSave} loading={saving}>Save Template</Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Preview Modal */}
      <Modal open={previewOpen} onClose={() => { setPreviewOpen(false); setPreviewHtml(null) }} title="Template Preview">
        {renderPreview()}
        <div className="mt-4 flex justify-end">
          <Button size="sm" variant="ghost" onClick={() => setPreviewOpen(false)}>Close</Button>
        </div>
      </Modal>

      {/* Variables Reference Modal */}
      <Modal open={variablesOpen} onClose={() => setVariablesOpen(false)} title="Template Variables">
        <p className="text-sm text-muted mb-3">
          Insert these variables into your templates. They will be replaced with actual values when sent.
        </p>
        <div className="overflow-hidden rounded-card border border-border">
          <table className="min-w-full" role="grid">
            <caption className="sr-only">Available template variables</caption>
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-4 py-2 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Variable</th>
                <th scope="col" className="mono border-b border-border px-4 py-2 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Description</th>
              </tr>
            </thead>
            <tbody>
              {templateVariables.map((v) => (
                <tr key={v.variable} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="mono whitespace-nowrap px-4 py-2 text-sm text-accent">{v.variable}</td>
                  <td className="px-4 py-2 text-sm text-text">{v.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-4 flex justify-end">
          <Button size="sm" variant="ghost" onClick={() => setVariablesOpen(false)}>Close</Button>
        </div>
      </Modal>
    </div>
  )
}
