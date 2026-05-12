/**
 * MediaField — custom Puck field that lets editors pick an image from
 * the media library or paste a raw URL.
 *
 * Used by component configs (e.g. `ImageBlock`, OG image in settings)
 * as `{ type: 'custom', render: MediaFieldRender }` — see Puck's
 * `CustomField` contract: the render function receives
 * `{ field, name, id, value, onChange, readOnly }` and must return a
 * React element that updates `value` via `onChange`.
 *
 * Design (see `.kiro/specs/visual-page-editor/design.md` §Gap E):
 *   - Preview of the currently-selected asset (image thumbnail)
 *   - Raw URL/asset-ID text input (fallback for admins who prefer typing)
 *   - "Browse Library" button opens `MediaLibraryModal`
 *   - On select inside the modal → onChange(assetId), close modal
 *
 * Task 7.8 adds the real `MediaLibraryModal.tsx` — until then this
 * field shows a lightweight placeholder modal with a URL input so
 * editors can still wire up images via direct URL. When the real
 * modal lands, swap the placeholder in `getMediaLibraryModal()` for
 * a direct import of `MediaLibraryModal` and all call-sites (e.g.
 * `ImageBlock.src`, page-settings OG image) get it automatically.
 *
 * Requirements: 12.2
 */
import { useState } from 'react'
import type { ReactElement } from 'react'
import type { CustomField, CustomFieldRender } from '@puckeditor/core'

// ---------------------------------------------------------------------------
// MediaLibraryModal wiring (replaced by Task 7.8)
// ---------------------------------------------------------------------------

/**
 * Contract expected from `MediaLibraryModal` when Task 7.8 ships.
 * Kept in a single place so the real modal and the placeholder stay
 * in sync.
 */
export interface MediaLibraryModalProps {
  /** Called with an asset identifier (asset UUID or URL). */
  onSelect: (assetRef: string) => void
  onClose: () => void
}
type MediaLibraryModalComponent = (
  props: MediaLibraryModalProps,
) => ReactElement

/**
 * Registered modal component. Task 7.8 replaces this default via
 * `registerMediaLibraryModal(RealModal)` at the top of the admin
 * page-editor entry, or equivalently by changing the default below
 * to an import of the real component.
 */
let registeredModal: MediaLibraryModalComponent = PlaceholderMediaLibraryModal

/**
 * Hook Task 7.8 calls once (e.g. from the page-editor entry point)
 * to plug the real modal in. Exposed as a side-effect registration
 * rather than a prop on every field instance so that any consumer
 * of `mediaField()` just works without each field config re-wiring
 * the modal.
 */
export function registerMediaLibraryModal(
  component: MediaLibraryModalComponent,
): void {
  registeredModal = component
}

function PlaceholderMediaLibraryModal({
  onSelect,
  onClose,
}: MediaLibraryModalProps): ReactElement {
  const [url, setUrl] = useState('')
  const handleInsert = () => {
    const trimmed = url.trim()
    if (trimmed) onSelect(trimmed)
  }
  return (
    <ModalShell onClose={onClose}>
      <h2 className="text-base font-semibold text-gray-900">
        Media library
      </h2>
      <p className="mt-2 text-sm text-gray-600">
        Full media library is coming soon. For now, paste an image URL
        to insert.
      </p>
      <input
        type="text"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://…"
        autoFocus
        className="mt-4 w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      />
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleInsert}
          disabled={url.trim().length === 0}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-500 disabled:opacity-50"
        >
          Insert
        </button>
      </div>
    </ModalShell>
  )
}

// ---------------------------------------------------------------------------
// Public field-renderer component
// ---------------------------------------------------------------------------

export interface MediaFieldRendererProps {
  /** Current value — either a raw URL or an asset UUID. */
  value: string
  onChange: (value: string) => void
  /** Label to display above the input (Puck passes the field name). */
  label?: string
  /** Unique DOM id for the input element. */
  id?: string
  readOnly?: boolean
}

/**
 * Standalone, testable renderer. Consumed by `mediaField` below
 * (which plugs it into Puck) and directly in unit tests.
 */
export function MediaFieldRenderer({
  value,
  onChange,
  label,
  id,
  readOnly,
}: MediaFieldRendererProps): ReactElement {
  const [showLibrary, setShowLibrary] = useState(false)
  const safeValue = value ?? ''
  const inputId = id ?? 'media-field-input'

  const openLibrary = () => {
    if (!readOnly) setShowLibrary(true)
  }
  const closeLibrary = () => setShowLibrary(false)
  const handleSelect = (assetRef: string) => {
    onChange(assetRef)
    setShowLibrary(false)
  }

  const LibraryModal = registeredModal

  return (
    <div className="space-y-2">
      {label ? (
        <label
          htmlFor={inputId}
          className="block text-sm font-medium text-gray-700"
        >
          {label}
        </label>
      ) : null}

      <div className="flex items-stretch gap-2">
        <input
          id={inputId}
          type="text"
          value={safeValue}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Asset ID or image URL"
          readOnly={readOnly}
          className="min-h-[36px] flex-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-500"
        />
        <button
          type="button"
          onClick={openLibrary}
          disabled={readOnly}
          className="inline-flex min-h-[36px] items-center rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Browse Library
        </button>
      </div>

      {/*
        Preview: if `value` looks like a URL we can render it directly;
        asset UUIDs would need a resolver, which the full
        MediaLibraryModal hands back as a URL — so for now we only
        preview URL-like values. Preview errors (broken URL, CORS)
        fall back silently.
      */}
      {safeValue && isLikelyUrl(safeValue) ? (
        <div className="mt-2 overflow-hidden rounded-md border border-gray-200 bg-gray-50">
          <img
            src={safeValue}
            alt=""
            className="block h-32 w-full object-contain"
            onError={(e) => {
              // Hide the preview if the URL fails to load; a broken
              // thumbnail would just confuse the editor.
              ;(e.target as HTMLImageElement).style.display = 'none'
            }}
          />
        </div>
      ) : null}

      {showLibrary ? (
        <LibraryModal onSelect={handleSelect} onClose={closeLibrary} />
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Puck CustomField adapter
// ---------------------------------------------------------------------------

/**
 * Puck-compatible render function. Plugged into a component's field
 * definition as:
 *
 * ```ts
 * fields: {
 *   src: mediaField({ label: 'Image' })
 * }
 * ```
 */
export const mediaFieldRender: CustomFieldRender<string> = ({
  field,
  name,
  id,
  value,
  onChange,
  readOnly,
}) => (
  <MediaFieldRenderer
    value={value}
    onChange={onChange}
    label={field.label ?? name}
    id={id}
    readOnly={readOnly}
  />
)

/**
 * Factory that returns a Puck `CustomField<string>` — use this in
 * component configs when you want a media picker for a string-valued
 * prop.
 */
export function mediaField(
  opts: { label?: string } = {},
): CustomField<string> {
  return {
    type: 'custom',
    label: opts.label,
    render: mediaFieldRender,
  }
}

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

function isLikelyUrl(value: string): boolean {
  const trimmed = value.trim()
  return (
    trimmed.startsWith('http://') ||
    trimmed.startsWith('https://') ||
    trimmed.startsWith('/')
  )
}

function ModalShell({
  onClose,
  children,
}: {
  onClose: () => void
  children: React.ReactNode
}): ReactElement {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  )
}
