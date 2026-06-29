/**
 * FieldOverlay — one draggable / resizable placed-field box rendered over a PDF
 * page in the Field_Placement_Editor.
 *
 * Responsibilities
 * ----------------
 * A single absolutely-positioned box, drawn in its assigned recipient's colour
 * (R4.4), that lets the Org_Sender move, resize, select, and delete one
 * {@link PlacedField}. Geometry is stored **normalized** (percent 0–100, origin
 * top-left) on the field; this component converts to/from overlay CSS pixels
 * against the page's {@link PageDims} with {@link normalizedToOverlay} /
 * {@link overlayToNormalized} (R7.1). Render scale therefore never leaks into
 * the stored coordinates.
 *
 * Interaction model
 * -----------------
 *   - **Pointer Events** unify mouse + touch so drag/resize work identically on
 *     a desktop and on a ≥320 px touch viewport (R10.5). `touch-action: none`
 *     stops the page scrolling while a field is being dragged.
 *   - **Drag** the box body to move it (R3.2); **drag the resize handle** to
 *     resize it (R3.3). Every commit goes through the parent's `onMove` /
 *     `onResize`, which dispatch into the `useFieldSet` reducer — that reducer
 *     runs `clampToPage` + min-size, so the box always lands in-bounds and at
 *     least minimum size (R3.5, R3.6). This component therefore never has to
 *     clamp itself; it just reports the candidate rect.
 *   - **Keyboard**: when selected the box is movable with the arrow keys
 *     (Shift = larger step, R10.2) and deletable with Delete / Backspace
 *     (R10.3).
 *
 * Accessibility (R10.1, R10.4)
 * ----------------------------
 *   - the box and the resize handle each present at least a 44 × 44 px target;
 *   - the box exposes an accessible name conveying the field's type and the
 *     recipient it is assigned to, e.g. `"Signature field for Alex Tran"`.
 *
 * A visible required / optional indicator is always shown (R5.5).
 *
 * Wiring into the reducer (binding `clientId` + `dims`) happens in the
 * orchestrator (`FieldPlacementEditor`, task 6.4) — this component is purely
 * presentational + interactive over the props it is given.
 *
 * _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.4, 5.5, 10.1, 10.2, 10.3, 10.4, 10.5_
 */

import { useCallback, useRef, type KeyboardEvent, type PointerEvent } from 'react'
import {
  normalizedToOverlay,
  overlayToNormalized,
  type NormalizedRect,
  type OverlayRect,
  type PageDims,
} from './lib/coordinateMapping'
import { recipientColor } from './lib/fieldColors'
import type { FieldType, PlacedField } from './hooks/useFieldSet'

/** The minimum touch-target size for interactive controls, in CSS px (R10.1). */
const MIN_TOUCH_TARGET_PX = 44

/** Arrow-key nudge step (CSS px); Shift multiplies it for a coarser move (R10.2). */
const NUDGE_STEP_PX = 1
const NUDGE_SHIFT_STEP_PX = 10

/** Human-readable label per field type, used in the box and its accessible name. */
const FIELD_TYPE_LABEL: Record<FieldType, string> = {
  signature: 'Signature',
  initials: 'Initials',
  name: 'Name',
  date: 'Date',
  email: 'Email',
  text: 'Text',
}

/**
 * The minimal recipient shape this overlay needs: a 0-based `index` (drives the
 * colour via {@link recipientColor}, R4.4) plus an optional display name/email
 * used to build the accessible name (R10.4).
 */
export interface FieldOverlayRecipient {
  /** 0-based position of the recipient in the Send_Flow recipient list. */
  index: number
  /** Display name, preferred for the accessible name. */
  name?: string
  /** Email, used as a fallback display name. */
  email?: string
}

export interface FieldOverlayProps {
  /** The placed field this overlay renders (geometry stored normalized). */
  field: PlacedField
  /** The rendered dimensions of the page this field sits on (for px ↔ percent). */
  dims: PageDims
  /** Whether this field is the currently-selected one. */
  selected: boolean
  /** The recipient this field is assigned to (colour + accessible name). */
  recipient: FieldOverlayRecipient
  /** Commit a move: the new normalized rect (parent clamps via the reducer). */
  onMove: (rect: NormalizedRect) => void
  /** Commit a resize: the new normalized rect (parent clamps via the reducer). */
  onResize: (rect: NormalizedRect) => void
  /** Select this field (e.g. on pointer-down / focus). */
  onSelect: () => void
  /** Delete this field (keyboard Delete / Backspace). */
  onDelete: () => void
}

/** Best-effort display name for a recipient, falling back to email then index. */
function recipientDisplayName(recipient: FieldOverlayRecipient): string {
  if (recipient.name && recipient.name.trim()) return recipient.name.trim()
  if (recipient.email && recipient.email.trim()) return recipient.email.trim()
  return `recipient ${recipient.index + 1}`
}

/** Tracks an in-flight pointer drag / resize gesture. */
interface Gesture {
  pointerId: number
  /** Pointer position when the gesture began (client px). */
  startClientX: number
  startClientY: number
  /** The field's overlay rect when the gesture began (CSS px). */
  startRect: OverlayRect
}

/**
 * One draggable / resizable placed-field box. Presentational + interactive over
 * its props; all clamping lives in the parent reducer (see module docs).
 */
export default function FieldOverlay({
  field,
  dims,
  selected,
  recipient,
  onMove,
  onResize,
  onSelect,
  onDelete,
}: FieldOverlayProps) {
  const color = recipientColor(recipient.index)
  const overlay = normalizedToOverlay(field.rect, dims)
  const typeLabel = FIELD_TYPE_LABEL[field.type]
  const displayName = recipientDisplayName(recipient)
  const accessibleName = `${typeLabel} field for ${displayName}`

  // Live gesture state is kept in refs so pointer-move handling never depends on
  // a re-render landing first (the committed rect flows back through props).
  const dragRef = useRef<Gesture | null>(null)
  const resizeRef = useRef<Gesture | null>(null)

  // ----- Drag (move) -------------------------------------------------------
  const onBoxPointerDown = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      // Selecting here (rather than on click) means a drag that begins on an
      // unselected field both selects and moves it in one gesture.
      onSelect()
      // Keep the gesture local to this box so the page background doesn't also
      // react (e.g. deselect) to the same pointer-down.
      e.stopPropagation()
      e.currentTarget.setPointerCapture(e.pointerId)
      dragRef.current = {
        pointerId: e.pointerId,
        startClientX: e.clientX,
        startClientY: e.clientY,
        startRect: normalizedToOverlay(field.rect, dims),
      }
    },
    [onSelect, field.rect, dims],
  )

  const onBoxPointerMove = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      const g = dragRef.current
      if (!g || g.pointerId !== e.pointerId) return
      const dx = e.clientX - g.startClientX
      const dy = e.clientY - g.startClientY
      const next: OverlayRect = {
        xPx: g.startRect.xPx + dx,
        yPx: g.startRect.yPx + dy,
        wPx: g.startRect.wPx,
        hPx: g.startRect.hPx,
      }
      onMove(overlayToNormalized(next, dims))
    },
    [onMove, dims],
  )

  const endDrag = useCallback((e: PointerEvent<HTMLDivElement>) => {
    const g = dragRef.current
    if (!g || g.pointerId !== e.pointerId) return
    dragRef.current = null
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      // Releasing a capture that was never set (or already released) is a no-op.
    }
  }, [])

  // ----- Resize ------------------------------------------------------------
  const onHandlePointerDown = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      onSelect()
      // Resizing must not also start a drag of the box body.
      e.stopPropagation()
      e.currentTarget.setPointerCapture(e.pointerId)
      resizeRef.current = {
        pointerId: e.pointerId,
        startClientX: e.clientX,
        startClientY: e.clientY,
        startRect: normalizedToOverlay(field.rect, dims),
      }
    },
    [onSelect, field.rect, dims],
  )

  const onHandlePointerMove = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      const g = resizeRef.current
      if (!g || g.pointerId !== e.pointerId) return
      const dw = e.clientX - g.startClientX
      const dh = e.clientY - g.startClientY
      const next: OverlayRect = {
        xPx: g.startRect.xPx,
        yPx: g.startRect.yPx,
        wPx: g.startRect.wPx + dw,
        hPx: g.startRect.hPx + dh,
      }
      // The reducer enforces min-size + page bounds; we just report the
      // candidate size (R3.6).
      onResize(overlayToNormalized(next, dims))
    },
    [onResize, dims],
  )

  const endResize = useCallback((e: PointerEvent<HTMLDivElement>) => {
    const g = resizeRef.current
    if (!g || g.pointerId !== e.pointerId) return
    resizeRef.current = null
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      // No-op if the capture is already gone.
    }
  }, [])

  // ----- Keyboard ----------------------------------------------------------
  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      // Delete / Backspace removes the selected field (R10.3).
      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault()
        onDelete()
        return
      }

      // Arrow keys nudge the field; Shift takes a larger step (R10.2).
      const step = e.shiftKey ? NUDGE_SHIFT_STEP_PX : NUDGE_STEP_PX
      let dx = 0
      let dy = 0
      switch (e.key) {
        case 'ArrowLeft':
          dx = -step
          break
        case 'ArrowRight':
          dx = step
          break
        case 'ArrowUp':
          dy = -step
          break
        case 'ArrowDown':
          dy = step
          break
        default:
          return
      }
      e.preventDefault()
      const current = normalizedToOverlay(field.rect, dims)
      const next: OverlayRect = {
        xPx: current.xPx + dx,
        yPx: current.yPx + dy,
        wPx: current.wPx,
        hPx: current.hPx,
      }
      onMove(overlayToNormalized(next, dims))
    },
    [onDelete, onMove, field.rect, dims],
  )

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={accessibleName}
      aria-pressed={selected}
      data-testid={`field-overlay-${field.clientId}`}
      data-field-type={field.type}
      data-selected={selected ? 'true' : 'false'}
      onPointerDown={onBoxPointerDown}
      onPointerMove={onBoxPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
      onFocus={onSelect}
      className="absolute box-border flex cursor-move select-none items-center justify-center rounded-sm text-center focus:outline-none"
      style={{
        left: overlay.xPx,
        top: overlay.yPx,
        width: overlay.wPx,
        height: overlay.hPx,
        // Guarantee a 44 × 44 px touch target for the interactive box (R10.1)
        // without disturbing its top-left placement, which stays exact.
        minWidth: MIN_TOUCH_TARGET_PX,
        minHeight: MIN_TOUCH_TARGET_PX,
        backgroundColor: color.fill,
        border: `2px solid ${color.solid}`,
        boxShadow: selected ? `0 0 0 2px ${color.solid}` : undefined,
        // Let pointer drags work on touch without the page scrolling (R10.5).
        touchAction: 'none',
      }}
    >
      {/* Field type label + required/optional indicator (R5.5). */}
      <span
        className="pointer-events-none flex items-center gap-1 px-1 text-[11px] font-medium leading-tight"
        style={{ color: color.solid }}
      >
        <span className="truncate">{field.type === 'text' && field.label ? field.label : typeLabel}</span>
        {field.required ? (
          <span
            aria-hidden="true"
            title="Required"
            data-testid={`field-required-${field.clientId}`}
            className="font-bold"
          >
            *
          </span>
        ) : (
          <span
            aria-hidden="true"
            title="Optional"
            data-testid={`field-optional-${field.clientId}`}
            className="opacity-70"
          >
            (optional)
          </span>
        )}
      </span>

      {/* Bottom-right resize handle — a 44 × 44 px touch target (R10.1) with a
          small visible nub at the corner (R3.3). */}
      <div
        role="slider"
        aria-label={`Resize ${accessibleName}`}
        aria-hidden={selected ? undefined : 'true'}
        tabIndex={-1}
        data-testid={`field-resize-${field.clientId}`}
        onPointerDown={onHandlePointerDown}
        onPointerMove={onHandlePointerMove}
        onPointerUp={endResize}
        onPointerCancel={endResize}
        className="absolute flex cursor-se-resize items-end justify-end"
        style={{
          right: -MIN_TOUCH_TARGET_PX / 2,
          bottom: -MIN_TOUCH_TARGET_PX / 2,
          width: MIN_TOUCH_TARGET_PX,
          height: MIN_TOUCH_TARGET_PX,
          touchAction: 'none',
        }}
      >
        <span
          aria-hidden="true"
          className="m-1 block h-3 w-3 rounded-sm border border-white"
          style={{ backgroundColor: color.solid }}
        />
      </div>
    </div>
  )
}
