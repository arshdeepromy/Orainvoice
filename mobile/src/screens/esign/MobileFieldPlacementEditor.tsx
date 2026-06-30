/**
 * MobileFieldPlacementEditor — the orchestrator for the mobile field-placement
 * editor (R16). It composes the rendered PDF pages, the Field_Palette, the
 * active-recipient picker, the per-field touch overlay, and the selected-field
 * inspector, driving them from the {@link useMobileFieldSet} reducer.
 *
 * Touch_Place flow (R16.4, R16.5):
 *   1. The sender arms a Field_Type from the palette and picks the active
 *      recipient.
 *   2. Tapping a page surface places a field of the armed type at the tap point,
 *      assigned to the active recipient. Placement goes through the shared
 *      `clampToPage` + coordinate mapping (via the reducer) so the field is
 *      always in-bounds and ≥ min-size.
 *   3. Selecting a field shows on-screen nudge / resize / delete controls
 *      (TouchFieldOverlay), each a ≥44×44 px target; adjustments flow through
 *      the same shared clamping, so geometry invariants hold identically to the
 *      web editor (R16.9).
 *
 * The send control is gated by the shared {@link validateFieldSet} (R16.9): it
 * stays disabled while the Field_Set is invalid or any page failed to render
 * (R1.4 / R6.4) and re-enables the moment every failure is corrected (R6.5).
 * The actual network send (createEnvelope + AbortController) lives in the parent
 * EsignSendScreen, which calls back through `onSend`.
 *
 * Supports the 320–430 px viewport (R16.6): the render width is measured from
 * the editor's own content column so pages fit the device.
 *
 * _Requirements: 16.4, 16.5, 16.6, 16.9_
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  FIELD_TYPES,
  normalizedToOverlay,
  overlayToNormalized,
  validateFieldSet,
  type FieldType,
  type PageDims,
  type PlacedField,
  type SigningRole,
} from '@/lib/esign'
import { MobileButton, MobileInput, MobileSelect, MobileSpinner } from '@/components/ui'
import { recipientColor } from './fieldColors'
import { useMobileFieldSet, MIN_FIELD_HEIGHT_PX, MIN_FIELD_WIDTH_PX } from './useMobileFieldSet'
import { usePdfDocument } from './usePdfDocument'
import MobilePdfPage from './MobilePdfPage'
import TouchFieldOverlay from './TouchFieldOverlay'

/** A recipient from step 1, as the editor needs it. */
export interface EditorRecipient {
  /** Stable key referenced by a placed field's `recipientKey`. */
  key: number
  name: string
  email: string
  signing_role: SigningRole
}

export interface MobileFieldPlacementEditorProps {
  /** The PDF selected in step 1. */
  file: File
  /** The recipients added in step 1, in array order. */
  recipients: EditorRecipient[]
  /** Called with the placed Field_Set when the sender confirms a valid send. */
  onSend: (fields: PlacedField[]) => void
  /** Go back to step 1 (the composer). */
  onBack: () => void
  /** True while the parent screen's send request is in flight. */
  isSending: boolean
  /** Humanized send error from the parent, retained for retry (R11.4). */
  sendError: string | null
}

/** Human label for each field type, used in the palette. */
const FIELD_TYPE_LABELS: Record<FieldType, string> = {
  signature: 'Signature',
  initials: 'Initials',
  name: 'Name',
  date: 'Date',
  email: 'Email',
  text: 'Text',
  number: 'Number',
  radio: 'Radio',
  checkbox: 'Checkbox',
  dropdown: 'Dropdown',
}

/** Default placed-field overlay size, as a fraction of the page width / a fixed height. */
const DEFAULT_FIELD_WIDTH_FRACTION = 0.4
const DEFAULT_FIELD_HEIGHT_PX = 44

export default function MobileFieldPlacementEditor({
  file,
  recipients,
  onSend,
  onBack,
  isSending,
  sendError,
}: MobileFieldPlacementEditorProps) {
  const contentRef = useRef<HTMLDivElement | null>(null)
  const [availableWidth, setAvailableWidth] = useState<number>(320)

  // Measure the content column so pages fit the 320–430 px viewport (R16.6).
  useEffect(() => {
    const el = contentRef.current
    if (!el) return
    const measure = () => setAvailableWidth(el.clientWidth || 320)
    measure()
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(measure)
      ro.observe(el)
      return () => ro.disconnect()
    }
    return undefined
  }, [])

  const { pdf, pages, loading, error, hasRenderError, setPageStatus } = usePdfDocument(file, {
    availableWidth,
  })

  const {
    fields,
    addField,
    moveField,
    resizeField,
    assignField,
    setRequired,
    setTextMeta,
    deleteField,
  } = useMobileFieldSet()

  const [armedType, setArmedType] = useState<FieldType>('signature')
  const [activeRecipientKey, setActiveRecipientKey] = useState<number | null>(
    recipients[0]?.key ?? null,
  )
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null)

  // Keep the active recipient valid if the list changes.
  useEffect(() => {
    if (recipients.length === 0) {
      setActiveRecipientKey(null)
      return
    }
    if (activeRecipientKey === null || !recipients.some((r) => r.key === activeRecipientKey)) {
      setActiveRecipientKey(recipients[0].key)
    }
  }, [recipients, activeRecipientKey])

  // Per-page dimensions, keyed by 1-based page number.
  const dimsByPage = useMemo(() => {
    const map = new Map<number, PageDims>()
    for (const p of pages) {
      map.set(p.pageNumber, { cssWidth: p.cssWidth, cssHeight: p.cssHeight })
    }
    return map
  }, [pages])

  const selectedField = useMemo(
    () => fields.find((f) => f.clientId === selectedClientId) ?? null,
    [fields, selectedClientId],
  )

  // Touch_Place: place the armed field type at a tap point on a page (R16.4).
  const handlePlaceAt = useCallback(
    (pageNumber: number, xPx: number, yPx: number) => {
      if (activeRecipientKey === null) return
      const dims = dimsByPage.get(pageNumber)
      if (!dims) return

      const wPx = Math.max(
        MIN_FIELD_WIDTH_PX,
        Math.min(dims.cssWidth * DEFAULT_FIELD_WIDTH_FRACTION, dims.cssWidth),
      )
      const hPx = Math.max(MIN_FIELD_HEIGHT_PX, DEFAULT_FIELD_HEIGHT_PX)
      // Centre the field on the tap point; the reducer clamps it in-bounds.
      const rect = overlayToNormalized(
        { xPx: xPx - wPx / 2, yPx: yPx - hPx / 2, wPx, hPx },
        dims,
      )
      const clientId = addField({
        type: armedType,
        page: pageNumber,
        rect,
        recipientKey: activeRecipientKey,
        dims,
      })
      setSelectedClientId(clientId)
    },
    [activeRecipientKey, armedType, addField, dimsByPage],
  )

  // Nudge the selected field by an overlay-px delta, through shared clamping.
  const handleNudge = useCallback(
    (clientId: string, dxPx: number, dyPx: number) => {
      const field = fields.find((f) => f.clientId === clientId)
      if (!field) return
      const dims = dimsByPage.get(field.page)
      if (!dims) return
      const overlay = normalizedToOverlay(field.rect, dims)
      const next = overlayToNormalized(
        { ...overlay, xPx: overlay.xPx + dxPx, yPx: overlay.yPx + dyPx },
        dims,
      )
      moveField(clientId, next, dims)
    },
    [fields, dimsByPage, moveField],
  )

  // Resize the selected field by an overlay-px width/height delta.
  const handleResize = useCallback(
    (clientId: string, dwPx: number, dhPx: number) => {
      const field = fields.find((f) => f.clientId === clientId)
      if (!field) return
      const dims = dimsByPage.get(field.page)
      if (!dims) return
      const overlay = normalizedToOverlay(field.rect, dims)
      const next = overlayToNormalized(
        { ...overlay, wPx: overlay.wPx + dwPx, hPx: overlay.hPx + dhPx },
        dims,
      )
      resizeField(clientId, next, dims)
    },
    [fields, dimsByPage, resizeField],
  )

  const handleDelete = useCallback(
    (clientId: string) => {
      deleteField(clientId)
      setSelectedClientId((prev) => (prev === clientId ? null : prev))
    },
    [deleteField],
  )

  // Shared validation gates the send control (R16.9 / R6.4 / R6.5).
  const validation = useMemo(
    () =>
      validateFieldSet(
        fields,
        recipients.map((r) => ({
          key: r.key,
          signing_role: r.signing_role,
          name: r.name,
          email: r.email,
        })),
      ),
    [fields, recipients],
  )

  const overlayRecipients = useMemo(
    () => recipients.map((r) => ({ key: r.key, name: r.name || r.email || 'recipient' })),
    [recipients],
  )

  const canSend = validation.ok && !hasRenderError && !loading && !isSending && fields.length > 0

  const handleSend = () => {
    if (!canSend) return
    onSend(fields)
  }

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-4 pb-1 pt-4">
        <button
          type="button"
          onClick={onBack}
          className="flex min-h-[44px] items-center gap-1 text-blue-600 dark:text-blue-400"
          aria-label="Back to recipients"
        >
          <svg
            className="h-5 w-5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="m15 18-6-6 6-6" />
          </svg>
          Back
        </button>
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Place fields</h1>
        <div className="w-12" aria-hidden="true" />
      </div>

      {/* Field palette (tap to arm) — all six types (R2.1), each ≥44px. */}
      <div className="px-4 pb-2">
        <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">Field type</p>
        <div className="grid grid-cols-3 gap-2" role="group" aria-label="Field type palette">
          {FIELD_TYPES.map((type) => {
            const active = type === armedType
            return (
              <button
                key={type}
                type="button"
                aria-pressed={active}
                onClick={() => setArmedType(type)}
                className={`min-h-[44px] rounded-lg px-2 text-sm font-medium transition-colors ${
                  active
                    ? 'bg-blue-600 text-white dark:bg-blue-500'
                    : 'bg-gray-100 text-gray-800 active:bg-gray-200 dark:bg-gray-700 dark:text-gray-100'
                }`}
              >
                {FIELD_TYPE_LABELS[type]}
              </button>
            )
          })}
        </div>
      </div>

      {/* Active recipient picker (drives assignment of newly placed fields, R4.2). */}
      <div className="px-4 pb-2">
        <MobileSelect
          label="Assign new fields to"
          value={activeRecipientKey === null ? '' : String(activeRecipientKey)}
          onChange={(e) => setActiveRecipientKey(Number(e.target.value))}
          options={recipients.map((r, i) => ({
            value: String(r.key),
            label: `${r.name || r.email || `Recipient ${i + 1}`} (${r.signing_role})`,
          }))}
        />
        {/* Recipient colour legend (R4.4). */}
        <div className="mt-2 flex flex-wrap gap-2">
          {recipients.map((r, i) => (
            <span
              key={r.key}
              className="inline-flex items-center gap-1 text-xs text-gray-600 dark:text-gray-300"
            >
              <span
                className="inline-block h-3 w-3 rounded-sm"
                style={{ backgroundColor: recipientColor(i).solid }}
                aria-hidden="true"
              />
              {r.name || r.email || `Recipient ${i + 1}`}
            </span>
          ))}
        </div>
      </div>

      {/* Pages */}
      <div ref={contentRef} className="flex flex-col items-center gap-4 px-2 py-2">
        {loading && (
          <div className="flex flex-col items-center gap-2 py-8">
            <MobileSpinner size="md" />
            <span className="text-sm text-gray-500 dark:text-gray-400">Loading document…</span>
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="w-full rounded-lg bg-red-50 p-4 text-center text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300"
          >
            This document couldn’t be displayed for field placement. Go back and choose a
            different PDF.
          </div>
        )}

        {!loading &&
          !error &&
          pdf &&
          pages.map((page) => {
            const dims: PageDims = { cssWidth: page.cssWidth, cssHeight: page.cssHeight }
            const pageFields = fields.filter((f) => f.page === page.pageNumber)
            return (
              <MobilePdfPage
                key={page.pageNumber}
                pdf={pdf}
                page={page}
                setPageStatus={setPageStatus}
                onPlaceAt={handlePlaceAt}
              >
                <TouchFieldOverlay
                  fields={pageFields}
                  recipients={overlayRecipients}
                  dims={dims}
                  selectedClientId={selectedClientId}
                  onSelect={(id) => setSelectedClientId((prev) => (prev === id ? null : id))}
                  onNudge={handleNudge}
                  onResize={handleResize}
                  onDelete={handleDelete}
                />
              </MobilePdfPage>
            )
          })}
      </div>

      {/* Selected-field inspector */}
      {selectedField && (
        <div className="mx-4 mb-2 flex flex-col gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800">
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            {FIELD_TYPE_LABELS[selectedField.type]} field
          </p>

          <MobileSelect
            label="Recipient"
            value={String(selectedField.recipientKey)}
            onChange={(e) => assignField(selectedField.clientId, Number(e.target.value))}
            options={recipients.map((r, i) => ({
              value: String(r.key),
              label: `${r.name || r.email || `Recipient ${i + 1}`} (${r.signing_role})`,
            }))}
          />

          <label className="flex min-h-[44px] items-center justify-between gap-2 text-sm text-gray-800 dark:text-gray-100">
            <span>Required</span>
            <input
              type="checkbox"
              className="h-6 w-6"
              checked={selectedField.required}
              onChange={(e) => setRequired(selectedField.clientId, e.target.checked)}
            />
          </label>

          {selectedField.type === 'text' && (
            <>
              <MobileInput
                label="Label"
                value={selectedField.label ?? ''}
                onChange={(e) =>
                  setTextMeta(selectedField.clientId, e.target.value, selectedField.placeholder)
                }
                placeholder="e.g. Job reference"
              />
              <MobileInput
                label="Placeholder"
                value={selectedField.placeholder ?? ''}
                onChange={(e) =>
                  setTextMeta(selectedField.clientId, selectedField.label, e.target.value)
                }
                placeholder="e.g. Enter reference number"
              />
            </>
          )}

          <MobileButton
            variant="danger"
            size="sm"
            onClick={() => handleDelete(selectedField.clientId)}
          >
            Delete field
          </MobileButton>
        </div>
      )}

      {/* Validation messages + send control */}
      <div
        className="sticky bottom-0 flex flex-col gap-2 border-t border-gray-200 bg-white px-4 pt-3 dark:border-gray-700 dark:bg-gray-900"
        style={{ paddingBottom: 'max(0.75rem, env(safe-area-inset-bottom))' }}
      >
        {!validation.ok && fields.length > 0 && (
          <ul className="text-xs text-amber-700 dark:text-amber-400">
            {validation.issues.map((issue, i) => (
              <li key={`${issue.code}-${i}`}>{issue.message}</li>
            ))}
          </ul>
        )}

        {fields.length === 0 && (
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Tap the document to place a {FIELD_TYPE_LABELS[armedType].toLowerCase()} field.
          </p>
        )}

        {hasRenderError && !error && (
          <p className="text-xs text-red-600 dark:text-red-400" role="alert">
            A page couldn’t be displayed. Sending is blocked until the document renders.
          </p>
        )}

        {sendError && (
          <p className="text-sm text-red-600 dark:text-red-400" role="alert">
            {sendError}
          </p>
        )}

        <MobileButton
          variant="primary"
          fullWidth
          onClick={handleSend}
          disabled={!canSend}
          isLoading={isSending}
        >
          Send for signature
        </MobileButton>
      </div>
    </div>
  )
}
