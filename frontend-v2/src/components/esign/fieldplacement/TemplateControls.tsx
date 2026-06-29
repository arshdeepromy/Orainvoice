/**
 * TemplateControls — the saved-field-template surface for the field-placement
 * editor (feature: esignature-field-placement, task 21.5).
 *
 * Two actions over the current send's recipients + Field_Set (R17):
 *
 *   - **Save as template** — names the current Field_Set and persists it via
 *     {@link createFieldTemplate}. The set is serialised by the pure
 *     {@link buildTemplate}, which stores each field against an abstract
 *     **Template_Recipient_Role** slot (derived here from the live recipient
 *     list) and **never** a recipient's name or email (R17.1).
 *   - **Apply a template** — lists the org's templates
 *     ({@link listFieldTemplates}), fetches the chosen one
 *     ({@link getFieldTemplate}), and shows a **role→recipient mapping UI** that
 *     prompts until every Template_Recipient_Role resolves to one of the current
 *     send's recipients. Apply stays disabled while any role is unmapped (R17.6);
 *     on apply the pure {@link applyTemplate} produces the placed Field_Set,
 *     which is handed back to the editor through `onApply` and then flows through
 *     the same `validateFieldSet` as any hand-placed set before send (R17.8).
 *
 * Role derivation: each recipient is assigned a stable abstract slot —
 * `signer 1`, `signer 2`, …, `viewer 1`, … — in recipient order. Saving uses
 * the key→role map; applying offers these same recipients as the targets for
 * each stored role, auto-prefilling a role whose slot matches a current
 * recipient's derived slot.
 *
 * All API consumption is typed and bound to an {@link AbortController} aborted
 * on unmount (R9.5). Interactive controls meet the 44×44 px minimum (R10.1).
 *
 * _Requirements: 17.1, 17.5, 17.6, 17.8_
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertBanner, Button, Input, Select } from '@/components/ui'
import {
  createFieldTemplate as defaultCreateFieldTemplate,
  listFieldTemplates as defaultListFieldTemplates,
  getFieldTemplate as defaultGetFieldTemplate,
} from '@/api/esign'
import type { AgreementType, FieldTemplateOut, SigningRole } from '@/api/esign'

import type { PlacedField } from './hooks/useFieldSet'
import { buildTemplate, type RecipientKeyToRole } from './lib/buildTemplate'
import { applyTemplate, type RoleToRecipientKey } from './lib/applyTemplate'

/**
 * A recipient as these controls need it: a stable `key` (referenced by a placed
 * field's `recipientKey`), optional name/email for display, and the signing
 * role that decides the abstract slot prefix.
 */
export interface TemplateControlsRecipient {
  key: number
  name?: string
  email?: string
  signing_role: SigningRole
}

export interface TemplateControlsProps {
  /** The current Field_Set (saved verbatim, role-mapped). */
  fields: readonly PlacedField[]
  /** The send's recipients (drive role derivation + the apply targets). */
  recipients: readonly TemplateControlsRecipient[]
  /** Optional agreement-type association stored on a saved template (R17.2). */
  agreementType?: AgreementType
  /** Disable both actions (e.g. while the document is loading / non-editable). */
  disabled?: boolean
  /**
   * Feed an applied template's placed Field_Set into the editor (R17.5). The
   * editor seeds its reducer from these (assigning fresh client ids), after
   * which the set is validated like any other before send (R17.8).
   */
  onApply: (fields: PlacedField[]) => void
  /** Injectable client (defaults to the real one) — for testing. */
  createFieldTemplateFn?: typeof defaultCreateFieldTemplate
  /** Injectable client (defaults to the real one) — for testing. */
  listFieldTemplatesFn?: typeof defaultListFieldTemplates
  /** Injectable client (defaults to the real one) — for testing. */
  getFieldTemplateFn?: typeof defaultGetFieldTemplate
  className?: string
}

/** A recipient paired with its derived abstract Template_Recipient_Role slot. */
interface DerivedRole {
  key: number
  role: string
  displayName: string
}

/** Best-effort display name: name → email → "Recipient N". */
function recipientDisplayName(recipient: TemplateControlsRecipient, index: number): string {
  if (recipient.name && recipient.name.trim()) return recipient.name.trim()
  if (recipient.email && recipient.email.trim()) return recipient.email.trim()
  return `Recipient ${index + 1}`
}

/**
 * Assign each recipient a stable abstract role slot (`signer N` / `viewer N`)
 * in recipient order, so saving stores roles (never people) and applying can
 * auto-prefill a role onto the same-slot recipient.
 */
function deriveRoles(recipients: readonly TemplateControlsRecipient[]): DerivedRole[] {
  const counts: Record<string, number> = {}
  return recipients.map((recipient, index) => {
    const base = recipient.signing_role === 'viewer' ? 'viewer' : 'signer'
    counts[base] = (counts[base] ?? 0) + 1
    return {
      key: recipient.key,
      role: `${base} ${counts[base]}`,
      displayName: recipientDisplayName(recipient, index),
    }
  })
}

/** True when the thrown value is an aborted-request signal (ignore it). */
function isAbortError(err: unknown): boolean {
  const name = (err as { name?: string })?.name
  const code = (err as { code?: string })?.code
  return name === 'AbortError' || name === 'CanceledError' || code === 'ERR_CANCELED'
}

/** Coerce a thrown value into a humanized, leak-free message (R12). */
function extractMessage(err: unknown, fallback: string): string {
  const data = (err as { response?: { data?: unknown } })?.response?.data
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>
    if (typeof obj.message === 'string' && obj.message.trim()) return obj.message
    const detail = obj.detail
    if (detail && typeof detail === 'object') {
      const d = detail as Record<string, unknown>
      if (typeof d.message === 'string' && d.message.trim()) return d.message
    }
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return fallback
}

/** Shared 44px-tall control sizing for touch (R10.1). */
const TOUCH = 'min-h-[44px]'

export function TemplateControls({
  fields,
  recipients,
  agreementType,
  disabled = false,
  onApply,
  createFieldTemplateFn = defaultCreateFieldTemplate,
  listFieldTemplatesFn = defaultListFieldTemplates,
  getFieldTemplateFn = defaultGetFieldTemplate,
  className,
}: TemplateControlsProps) {
  const derivedRoles = useMemo(() => deriveRoles(recipients), [recipients])

  // recipientKey → abstract role slot, for saving (R17.1).
  const recipientKeyToRole = useMemo<RecipientKeyToRole>(() => {
    const map: Record<number, string> = {}
    for (const d of derivedRoles) map[d.key] = d.role
    return map
  }, [derivedRoles])

  // Recipient options (key + label) for the apply role→recipient pickers.
  const recipientOptions = useMemo(
    () => derivedRoles.map((d) => ({ value: String(d.key), label: d.displayName })),
    [derivedRoles],
  )

  // ── Panels (mutually exclusive) ─────────────────────────────────────────
  const [panel, setPanel] = useState<'none' | 'save' | 'apply'>('none')

  // ── Save state ──────────────────────────────────────────────────────────
  const [templateName, setTemplateName] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedName, setSavedName] = useState<string | null>(null)

  // ── Apply state ─────────────────────────────────────────────────────────
  const [templates, setTemplates] = useState<FieldTemplateOut[]>([])
  const [listLoading, setListLoading] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [fetchedTemplate, setFetchedTemplate] = useState<FieldTemplateOut | null>(null)
  const [templateLoading, setTemplateLoading] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  // role slot → chosen recipient key (as a string for the Select; '' = unmapped).
  const [roleMap, setRoleMap] = useState<Record<string, string>>({})

  const abortRef = useRef<AbortController | null>(null)
  useEffect(() => () => abortRef.current?.abort(), [])

  const freshController = useCallback(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    return controller
  }, [])

  const canSave = fields.length > 0 && templateName.trim().length > 0 && !saving && !disabled

  // ── Save the current Field_Set as a template (R17.1) ────────────────────
  const handleSave = useCallback(async () => {
    if (!canSave) return
    setSaveError(null)
    setSavedName(null)
    const controller = freshController()
    setSaving(true)
    try {
      const payload = buildTemplate(fields, recipientKeyToRole, {
        name: templateName.trim(),
        agreementType,
      })
      const created = await createFieldTemplateFn(payload, controller.signal)
      if (controller.signal.aborted) return
      setSavedName(created.name || templateName.trim())
      setTemplateName('')
      setPanel('none')
    } catch (err: unknown) {
      if (controller.signal.aborted || isAbortError(err)) return
      setSaveError(extractMessage(err, 'Couldn’t save this template. Please try again.'))
    } finally {
      if (!controller.signal.aborted) setSaving(false)
    }
  }, [canSave, freshController, fields, recipientKeyToRole, templateName, agreementType, createFieldTemplateFn])

  // ── Load the org's templates when the apply panel opens ──────────────────
  const loadTemplates = useCallback(async () => {
    setListError(null)
    const controller = freshController()
    setListLoading(true)
    try {
      const res = await listFieldTemplatesFn(controller.signal)
      if (controller.signal.aborted) return
      setTemplates(res.items ?? [])
    } catch (err: unknown) {
      if (controller.signal.aborted || isAbortError(err)) return
      setListError(extractMessage(err, 'Couldn’t load your saved templates.'))
    } finally {
      if (!controller.signal.aborted) setListLoading(false)
    }
  }, [freshController, listFieldTemplatesFn])

  // ── Fetch a chosen template + seed the role→recipient mapping ────────────
  const handleSelectTemplate = useCallback(
    async (templateId: string) => {
      setSelectedTemplateId(templateId)
      setFetchedTemplate(null)
      setApplyError(null)
      setRoleMap({})
      if (!templateId) return
      const controller = freshController()
      setTemplateLoading(true)
      try {
        const template = await getFieldTemplateFn(templateId, controller.signal)
        if (controller.signal.aborted) return
        setFetchedTemplate(template)
        // Auto-prefill each role onto a same-slot recipient when one exists, so
        // the common case (template roles line up with current recipients)
        // needs no manual mapping. Roles without a match start unmapped (R17.6).
        const roleToDerived = new Map(derivedRoles.map((d) => [d.role, d.key]))
        const seeded: Record<string, string> = {}
        for (const role of template.roles ?? []) {
          const match = roleToDerived.get(role)
          seeded[role] = match !== undefined ? String(match) : ''
        }
        setRoleMap(seeded)
      } catch (err: unknown) {
        if (controller.signal.aborted || isAbortError(err)) return
        setApplyError(extractMessage(err, 'Couldn’t load that template.'))
      } finally {
        if (!controller.signal.aborted) setTemplateLoading(false)
      }
    },
    [freshController, getFieldTemplateFn, derivedRoles],
  )

  // Distinct roles to map: prefer the template's declared roles, else those its
  // fields reference (defensive against a template missing its `roles[]`).
  const rolesToMap = useMemo<string[]>(() => {
    if (!fetchedTemplate) return []
    if (fetchedTemplate.roles && fetchedTemplate.roles.length > 0) return fetchedTemplate.roles
    const seen = new Set<string>()
    const out: string[] = []
    for (const f of fetchedTemplate.fields ?? []) {
      if (!seen.has(f.template_role)) {
        seen.add(f.template_role)
        out.push(f.template_role)
      }
    }
    return out
  }, [fetchedTemplate])

  // Apply stays disabled until every role resolves to a recipient (R17.6).
  const allRolesMapped = useMemo(
    () => rolesToMap.length > 0 && rolesToMap.every((role) => roleMap[role] !== undefined && roleMap[role] !== ''),
    [rolesToMap, roleMap],
  )

  const handleApply = useCallback(() => {
    if (!fetchedTemplate || !allRolesMapped || disabled) return
    setApplyError(null)
    // Build the pure role→recipientKey map the applier expects.
    const roleToRecipientKey: Record<string, number> = {}
    for (const role of rolesToMap) {
      const key = Number(roleMap[role])
      if (Number.isFinite(key)) roleToRecipientKey[role] = key
    }
    const result = applyTemplate(fetchedTemplate, roleToRecipientKey as RoleToRecipientKey)
    if (!result.ok) {
      // Shouldn't happen once allRolesMapped is true, but surface it rather than
      // silently producing an unassigned set (R17.6).
      setApplyError(
        `Map every role before applying: ${result.unmappedRoles.join(', ')}.`,
      )
      return
    }
    onApply(result.fields)
    // Collapse the panel; the editor now owns the applied set.
    setPanel('none')
    setSelectedTemplateId('')
    setFetchedTemplate(null)
    setRoleMap({})
  }, [fetchedTemplate, allRolesMapped, disabled, rolesToMap, roleMap, onApply])

  const openSave = useCallback(() => {
    setPanel((p) => (p === 'save' ? 'none' : 'save'))
    setSaveError(null)
    setSavedName(null)
  }, [])

  const openApply = useCallback(() => {
    setPanel((p) => {
      const next = p === 'apply' ? 'none' : 'apply'
      if (next === 'apply') void loadTemplates()
      return next
    })
    setApplyError(null)
  }, [loadTemplates])

  const templateOptions = useMemo(
    () =>
      templates.map((t) => ({
        value: t.id,
        label: t.agreement_type ? `${t.name} (${t.agreement_type})` : t.name,
      })),
    [templates],
  )

  return (
    <div
      className={['flex flex-col gap-2', className].filter(Boolean).join(' ')}
      data-testid="template-controls"
    >
      <p className="text-[12.5px] font-medium text-text">Templates</p>

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="ghost"
          className={TOUCH}
          onClick={openSave}
          disabled={disabled || fields.length === 0}
          data-testid="open-save-template"
        >
          Save as template
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className={TOUCH}
          onClick={openApply}
          disabled={disabled}
          data-testid="open-apply-template"
        >
          Apply template
        </Button>
      </div>

      {savedName && panel !== 'save' && (
        <AlertBanner variant="success" onDismiss={() => setSavedName(null)}>
          <span data-testid="template-saved">Saved “{savedName}” as a template.</span>
        </AlertBanner>
      )}

      {/* ── Save panel ──────────────────────────────────────────────────── */}
      {panel === 'save' && (
        <div className="flex flex-col gap-2 rounded-ctl border border-border bg-card p-3" data-testid="save-template-panel">
          <Input
            label="Template name"
            value={templateName}
            onChange={(e) => setTemplateName(e.target.value)}
            placeholder="e.g. Standard sales agreement"
            data-testid="template-name-input"
          />
          {saveError && (
            <AlertBanner variant="error" onDismiss={() => setSaveError(null)}>
              <span data-testid="save-template-error">{saveError}</span>
            </AlertBanner>
          )}
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="quiet" className={TOUCH} onClick={() => setPanel('none')} disabled={saving}>
              Cancel
            </Button>
            <Button
              size="sm"
              className={TOUCH}
              onClick={() => void handleSave()}
              loading={saving}
              disabled={!canSave}
              data-testid="save-template"
            >
              Save template
            </Button>
          </div>
        </div>
      )}

      {/* ── Apply panel ─────────────────────────────────────────────────── */}
      {panel === 'apply' && (
        <div className="flex flex-col gap-3 rounded-ctl border border-border bg-card p-3" data-testid="apply-template-panel">
          {listLoading && (
            <p className="text-[12.5px] text-muted" data-testid="template-list-loading">
              Loading templates…
            </p>
          )}
          {listError && (
            <AlertBanner variant="error" onDismiss={() => setListError(null)}>
              <span data-testid="template-list-error">{listError}</span>
            </AlertBanner>
          )}
          {!listLoading && !listError && templates.length === 0 && (
            <p className="text-[12.5px] text-muted" data-testid="template-list-empty">
              No saved templates yet. Place fields and save one first.
            </p>
          )}

          {templates.length > 0 && (
            <Select
              label="Choose a template"
              className={TOUCH}
              placeholder="Select a template…"
              options={templateOptions}
              value={selectedTemplateId}
              onChange={(e) => void handleSelectTemplate(e.target.value)}
              data-testid="template-picker"
            />
          )}

          {templateLoading && (
            <p className="text-[12.5px] text-muted" data-testid="template-loading">
              Loading template…
            </p>
          )}

          {/* Role → recipient mapping (R17.6) — Apply stays disabled until every
              role resolves to one of the current send's recipients. */}
          {fetchedTemplate && rolesToMap.length > 0 && (
            <div className="flex flex-col gap-2" data-testid="role-mapping">
              <p className="text-[12px] text-muted">
                Map each template role to a recipient on this send.
              </p>
              {rolesToMap.map((role) => (
                <Select
                  key={role}
                  label={role}
                  className={TOUCH}
                  placeholder="Choose a recipient…"
                  options={recipientOptions}
                  value={roleMap[role] ?? ''}
                  onChange={(e) =>
                    setRoleMap((prev) => ({ ...prev, [role]: e.target.value }))
                  }
                  data-testid={`role-map-${role}`}
                />
              ))}
            </div>
          )}

          {applyError && (
            <AlertBanner variant="error" onDismiss={() => setApplyError(null)}>
              <span data-testid="apply-template-error">{applyError}</span>
            </AlertBanner>
          )}

          <div className="flex justify-end gap-2">
            <Button size="sm" variant="quiet" className={TOUCH} onClick={() => setPanel('none')}>
              Cancel
            </Button>
            <Button
              size="sm"
              className={TOUCH}
              onClick={handleApply}
              disabled={!fetchedTemplate || !allRolesMapped || disabled}
              data-testid="apply-template"
            >
              Apply template
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export default TemplateControls
