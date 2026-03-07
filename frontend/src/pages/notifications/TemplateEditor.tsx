import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Spinner, Modal, Badge } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TemplateBlock {
  id: string
  type: 'logo' | 'header' | 'body' | 'footer'
  content: string
}

interface NotificationTemplate {
  id: string
  name: string
  subject: string
  channel: 'email' | 'sms'
  body_blocks: TemplateBlock[]
  body_text?: string
  updated_at: string
}

interface TemplatesResponse {
  templates: NotificationTemplate[]
}

const TEMPLATE_VARIABLES = [
  { variable: '{{customer_first_name}}', description: 'Customer first name' },
  { variable: '{{customer_last_name}}', description: 'Customer last name' },
  { variable: '{{invoice_number}}', description: 'Invoice number' },
  { variable: '{{total_due}}', description: 'Total amount due' },
  { variable: '{{due_date}}', description: 'Invoice due date' },
  { variable: '{{payment_link}}', description: 'Stripe payment link' },
  { variable: '{{vehicle_rego}}', description: 'Vehicle registration' },
  { variable: '{{expiry_type}}', description: 'WOF or Registration' },
  { variable: '{{expiry_date}}', description: 'Expiry date' },
  { variable: '{{workshop_name}}', description: 'Workshop name' },
  { variable: '{{workshop_phone}}', description: 'Workshop phone' },
  { variable: '{{workshop_email}}', description: 'Workshop email' },
]

const BLOCK_TYPES = [
  { value: 'logo', label: 'Logo' },
  { value: 'header', label: 'Header Text' },
  { value: 'body', label: 'Body Text' },
  { value: 'footer', label: 'Footer' },
]

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
  const [saving, setSaving] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [variablesOpen, setVariablesOpen] = useState(false)
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [channelFilter, setChannelFilter] = useState<'all' | 'email' | 'sms'>('all')

  const fetchTemplates = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<TemplatesResponse>('/notifications/templates')
      setTemplates(res.data.templates)
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
    setEditBlocks(t.body_blocks.map((b) => ({ ...b })))
    setEditSmsText(t.body_text || '')
  }

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    setError('')
    try {
      const body = selected.channel === 'sms'
        ? { subject: editSubject, body_text: editSmsText }
        : { subject: editSubject, body_blocks: editBlocks }
      await apiClient.put(`/notifications/templates/${selected.id}`, body)
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

  /* Preview rendering */
  const renderPreview = () => {
    if (!selected) return null
    if (selected.channel === 'sms') {
      return (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
          <p className="text-sm font-medium text-gray-700 mb-2">SMS Preview</p>
          <div className="rounded-md bg-white p-3 text-sm text-gray-900 whitespace-pre-wrap">
            {editSmsText || '(empty)'}
          </div>
          <p className={`mt-2 text-xs ${editSmsText.length > 160 ? 'text-red-600 font-medium' : 'text-gray-500'}`}>
            {editSmsText.length}/160 characters{editSmsText.length > 160 && ' — exceeds single SMS limit'}
          </p>
        </div>
      )
    }
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
        <p className="text-xs text-gray-500 mb-2">Subject: {editSubject}</p>
        {editBlocks.map((block) => (
          <div key={block.id}>
            {block.type === 'logo' && (
              <div className="h-12 w-32 bg-gray-200 rounded flex items-center justify-center text-xs text-gray-500">
                [Organisation Logo]
              </div>
            )}
            {block.type === 'header' && (
              <h2 className="text-lg font-semibold text-gray-900">{block.content || '(header)'}</h2>
            )}
            {block.type === 'body' && (
              <p className="text-sm text-gray-700 whitespace-pre-wrap">{block.content || '(body text)'}</p>
            )}
            {block.type === 'footer' && (
              <p className="text-xs text-gray-500 border-t border-gray-100 pt-3">{block.content || '(footer)'}</p>
            )}
          </div>
        ))}
      </div>
    )
  }

  const filteredTemplates = templates.filter(
    (t) => channelFilter === 'all' || t.channel === channelFilter,
  )

  if (loading) {
    return <div className="py-16"><Spinner label="Loading templates" /></div>
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-gray-500">
          Customise email and SMS templates with drag-and-drop blocks and template variables.
        </p>
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={() => setVariablesOpen(true)}>
            Variables Reference
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
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
                ? 'bg-blue-100 text-blue-700 border border-blue-300'
                : 'bg-gray-100 text-gray-600 border border-gray-200 hover:bg-gray-200'}`}
          >
            {ch === 'all' ? 'All' : ch.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Template list */}
        <div className="lg:col-span-1">
          <div className="rounded-lg border border-gray-200 bg-white divide-y divide-gray-100">
            {filteredTemplates.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-gray-500">No templates found.</p>
            ) : (
              filteredTemplates.map((t) => (
                <button
                  key={t.id}
                  onClick={() => selectTemplate(t)}
                  className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors
                    ${selected?.id === t.id ? 'bg-blue-50 border-l-2 border-blue-600' : ''}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900">{t.name}</span>
                    <Badge variant={t.channel === 'email' ? 'info' : 'neutral'}>
                      {t.channel.toUpperCase()}
                    </Badge>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
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
            <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-16 text-center text-sm text-gray-500">
              Select a template from the list to edit it.
            </div>
          ) : selected.channel === 'sms' ? (
            /* SMS text editor */
            <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-medium text-gray-900">{selected.name}</h3>
                <Badge variant="neutral">SMS</Badge>
              </div>
              <Input
                label="Subject / Label"
                value={editSubject}
                onChange={(e) => setEditSubject(e.target.value)}
              />
              <div>
                <label htmlFor="sms-body" className="block text-sm font-medium text-gray-700 mb-1">
                  Message body
                </label>
                <textarea
                  id="sms-body"
                  rows={4}
                  value={editSmsText}
                  onChange={(e) => setEditSmsText(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
                <p className={`mt-1 text-xs ${editSmsText.length > 160 ? 'text-red-600 font-medium' : 'text-gray-500'}`}>
                  {editSmsText.length}/160 characters
                  {editSmsText.length > 160 && ' — exceeds single SMS segment'}
                </p>
              </div>
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" onClick={() => setPreviewOpen(true)}>Preview</Button>
                <Button size="sm" onClick={handleSave} loading={saving}>Save Template</Button>
              </div>
            </div>
          ) : (
            /* Email block editor */
            <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-medium text-gray-900">{selected.name}</h3>
                <Badge variant="info">EMAIL</Badge>
              </div>
              <Input
                label="Email subject"
                value={editSubject}
                onChange={(e) => setEditSubject(e.target.value)}
              />

              {/* Blocks */}
              <div>
                <p className="text-sm font-medium text-gray-700 mb-2">Content blocks</p>
                <div className="space-y-2">
                  {editBlocks.map((block, idx) => (
                    <div
                      key={block.id}
                      draggable
                      onDragStart={() => handleDragStart(idx)}
                      onDragOver={(e) => handleDragOver(e, idx)}
                      onDragEnd={handleDragEnd}
                      className={`rounded-md border p-3 transition-colors
                        ${dragIndex === idx ? 'border-blue-400 bg-blue-50' : 'border-gray-200 bg-gray-50'}`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="cursor-grab text-gray-400" aria-label="Drag to reorder">⠿</span>
                          <Badge variant="neutral">{block.type}</Badge>
                        </div>
                        <button
                          onClick={() => removeBlock(idx)}
                          className="text-xs text-red-500 hover:text-red-700"
                          aria-label={`Remove ${block.type} block`}
                        >
                          Remove
                        </button>
                      </div>
                      {block.type === 'logo' ? (
                        <p className="text-xs text-gray-500 italic">Organisation logo will be inserted automatically.</p>
                      ) : (
                        <textarea
                          rows={block.type === 'body' ? 4 : 2}
                          value={block.content}
                          onChange={(e) => updateBlock(idx, e.target.value)}
                          placeholder={`Enter ${block.type} text… Use {{variables}} for dynamic content.`}
                          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        />
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
                      variant="secondary"
                      onClick={() => addBlock(bt.value as TemplateBlock['type'])}
                    >
                      + {bt.label}
                    </Button>
                  ))}
                </div>
              </div>

              <div className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" onClick={() => setPreviewOpen(true)}>Preview</Button>
                <Button size="sm" onClick={handleSave} loading={saving}>Save Template</Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Preview Modal */}
      <Modal open={previewOpen} onClose={() => setPreviewOpen(false)} title="Template Preview">
        {renderPreview()}
        <div className="mt-4 flex justify-end">
          <Button size="sm" variant="secondary" onClick={() => setPreviewOpen(false)}>Close</Button>
        </div>
      </Modal>

      {/* Variables Reference Modal */}
      <Modal open={variablesOpen} onClose={() => setVariablesOpen(false)} title="Template Variables">
        <p className="text-sm text-gray-500 mb-3">
          Insert these variables into your templates. They will be replaced with actual values when sent.
        </p>
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Available template variables</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Variable</th>
                <th scope="col" className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {TEMPLATE_VARIABLES.map((v) => (
                <tr key={v.variable} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-2 text-sm font-mono text-blue-700">{v.variable}</td>
                  <td className="px-4 py-2 text-sm text-gray-700">{v.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-4 flex justify-end">
          <Button size="sm" variant="secondary" onClick={() => setVariablesOpen(false)}>Close</Button>
        </div>
      </Modal>
    </div>
  )
}
