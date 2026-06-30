/**
 * useFieldSet — the Field_Set client state for the Field_Placement_Editor.
 *
 * The Field_Set is the complete collection of fields the Org_Sender has placed
 * across all pages of one document (R-glossary). It lives entirely in client
 * state for the lifetime of the open editor: it survives in-editor page
 * navigation (R11.1), is discarded on cancel/reopen (R11.3), and is retained
 * after a failed send so the sender can correct and retry (R11.4).
 *
 * A **pure reducer** (`fieldSetReducer`) owns every mutation so the client-side
 * rules are directly testable without React. The hook (`useFieldSet`) is a thin
 * `useReducer` wrapper that also exposes typed action-creator helpers (and
 * generates stable client ids) for the editor components.
 *
 * Coordinate model
 * ----------------
 * Each field's geometry is stored as a {@link NormalizedRect} (percent 0–100,
 * origin top-left), so it is **render-scale independent** — a viewport resize or
 * zoom never mutates a stored field (R7.2, R11.1). Geometric clamping, however,
 * is defined in **overlay (CSS px) space** (`clampToPage` enforces min-size and
 * page bounds against the rendered pixel dimensions). So the geometric actions
 * (`add`/`move`/`resize`) carry the target page's {@link PageDims}: the reducer
 * converts the incoming normalized rect to overlay px, clamps it, and converts
 * the clamped result back to normalized before committing. This guarantees the
 * invariant "every committed field is in-bounds and ≥ min-size" after every
 * action (R3.5, R3.6) while page/type/recipient are left unchanged.
 *
 * _Requirements: 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.5, 5.1, 5.2, 11.1, 11.3_
 */

import { useCallback, useMemo, useReducer, type Dispatch } from 'react'
import {
  clampToPage,
  normalizedToOverlay,
  overlayToNormalized,
  type NormalizedRect,
  type PageDims,
} from '../lib/coordinateMapping'

/**
 * The supported field types (R2.1), in palette order. The first six are the
 * original palette; the four advanced types (`number`, `radio`, `checkbox`,
 * `dropdown`) extend it to match Documenso's full palette. `number` behaves
 * like `text` (label/placeholder); `radio` / `dropdown` carry a sender-authored
 * options list; `checkbox` is a single box. All additive — the original six are
 * unchanged.
 */
export const FIELD_TYPES = [
  'signature',
  'initials',
  'name',
  'date',
  'email',
  'text',
  'number',
  'radio',
  'checkbox',
  'dropdown',
] as const

/** The kind of a placed field. Maps 1:1 to a Documenso field type on send (R2.4). */
export type FieldType = (typeof FIELD_TYPES)[number]

/**
 * Minimum field size in CSS px, enforced on every geometric action so a resized
 * field stays large enough to display its type label (R3.6). `clampToPage` caps
 * these to the page size, so they never prevent a field fitting on a small page.
 */
export const MIN_FIELD_WIDTH_PX = 48
export const MIN_FIELD_HEIGHT_PX = 24

/** One placed field in the Field_Set. Geometry is stored normalized (R7). */
export interface PlacedField {
  /** Stable local key (e.g. `crypto.randomUUID()`); never sent to Documenso. */
  clientId: string
  /** The field's type (R2.1). */
  type: FieldType
  /** 1-based page the field sits on. */
  page: number
  /** Position + size in normalized page units (percent 0–100, origin top-left). */
  rect: NormalizedRect
  /** References a SendForSignatureModal recipient row's key (R4.1). */
  recipientKey: number
  /** Required/optional flag; defaults per type on add (R2.3, R5.1). */
  required: boolean
  /** Label for `text` / `number` fields only (R5.2). */
  label?: string
  /** Placeholder for `text` / `number` fields only (R5.2). */
  placeholder?: string
  /** Sender-authored options for `radio` / `dropdown` fields only. */
  options?: string[]
}

/** The Field_Set: a flat array of placed fields. */
export type FieldSetState = PlacedField[]

/**
 * Every mutation of the Field_Set. Geometric actions (`add`/`move`/`resize`)
 * carry the target page's {@link PageDims} so the reducer can clamp in overlay
 * space (see module docs).
 */
export type FieldSetAction =
  | {
      kind: 'add'
      clientId: string
      type: FieldType
      page: number
      rect: NormalizedRect
      recipientKey: number
      dims: PageDims
    }
  | { kind: 'move'; clientId: string; rect: NormalizedRect; dims: PageDims }
  | { kind: 'resize'; clientId: string; rect: NormalizedRect; dims: PageDims }
  | { kind: 'assign'; clientId: string; recipientKey: number }
  | { kind: 'setRequired'; clientId: string; required: boolean }
  | { kind: 'setTextMeta'; clientId: string; label?: string; placeholder?: string }
  | { kind: 'setOptions'; clientId: string; options: string[] }
  | { kind: 'delete'; clientId: string }
  | { kind: 'removeRecipient'; recipientKey: number } // cascade delete (R4.5)
  | { kind: 'seed'; fields: PlacedField[] } // edit-after-send seeding (R13.1)
  | { kind: 'reset' } // cancel / reopen (R11.3)

/**
 * The per-type default required flag (R2.3): every type defaults to required
 * except `text`, which defaults to optional.
 */
export function defaultRequiredFor(type: FieldType): boolean {
  return type !== 'text'
}

/**
 * Clamp a normalized rect to its page, in overlay space, enforcing page bounds
 * and the minimum field size. Converts normalized → overlay px against `dims`,
 * runs {@link clampToPage}, then converts the clamped overlay rect back to
 * normalized so the stored value remains render-scale independent (R3.5, R3.6).
 *
 * If the page dims are degenerate (non-positive), the rect is returned
 * unchanged — there is no meaningful overlay space to clamp against.
 */
function clampNormalizedToPage(rect: NormalizedRect, dims: PageDims): NormalizedRect {
  if (!(dims.cssWidth > 0) || !(dims.cssHeight > 0)) return rect
  const overlay = normalizedToOverlay(rect, dims)
  const clamped = clampToPage(overlay, dims, MIN_FIELD_WIDTH_PX, MIN_FIELD_HEIGHT_PX)
  return overlayToNormalized(clamped, dims)
}

/**
 * The pure Field_Set reducer. No I/O, no randomness — given the same state and
 * action it always returns the same next state, so the client-side rules are
 * directly property-testable.
 */
export function fieldSetReducer(state: FieldSetState, action: FieldSetAction): FieldSetState {
  switch (action.kind) {
    case 'add': {
      // Grows the set by exactly one field carrying the chosen type/page,
      // assigned to the active recipient, with the per-type default required
      // flag, geometry clamped in-bounds and to ≥ min-size (R2.2, R2.3, R3.1).
      const field: PlacedField = {
        clientId: action.clientId,
        type: action.type,
        page: action.page,
        rect: clampNormalizedToPage(action.rect, action.dims),
        recipientKey: action.recipientKey,
        required: defaultRequiredFor(action.type),
      }
      return [...state, field]
    }

    case 'move':
    case 'resize': {
      // Move/resize change only the target field's geometry; the new rect is
      // clamped so the field stays in-bounds and ≥ min-size while page, type,
      // and recipient are unchanged (R3.2, R3.3, R3.5, R3.6).
      return state.map((f) =>
        f.clientId === action.clientId
          ? { ...f, rect: clampNormalizedToPage(action.rect, action.dims) }
          : f,
      )
    }

    case 'assign': {
      // Re-assign changes only this field's recipient (R4.3).
      return state.map((f) =>
        f.clientId === action.clientId ? { ...f, recipientKey: action.recipientKey } : f,
      )
    }

    case 'setRequired': {
      return state.map((f) =>
        f.clientId === action.clientId ? { ...f, required: action.required } : f,
      )
    }

    case 'setTextMeta': {
      // Label/placeholder are meaningful for `text` / `number` fields only (R5.2).
      return state.map((f) =>
        f.clientId === action.clientId
          ? { ...f, label: action.label, placeholder: action.placeholder }
          : f,
      )
    }

    case 'setOptions': {
      // Options are meaningful for `radio` / `dropdown` fields only.
      return state.map((f) =>
        f.clientId === action.clientId ? { ...f, options: action.options } : f,
      )
    }

    case 'delete': {
      // Remove the field from the set; the editor stops rendering it (R3.4).
      return state.filter((f) => f.clientId !== action.clientId)
    }

    case 'removeRecipient': {
      // Cascade-delete: dropping a recipient drops exactly that recipient's
      // fields and leaves every other field unchanged (R4.5).
      return state.filter((f) => f.recipientKey !== action.recipientKey)
    }

    case 'seed': {
      // Replace the whole Field_Set with a pre-built set. Used by edit-after-send
      // to seed the editor from an envelope's current Documenso fields (R13.1).
      // The fields are already valid (server-supplied normalized coords) and
      // carry fresh client ids, so no clamping is applied here.
      return action.fields
    }

    case 'reset': {
      // Cancel / reopen starts from an empty Field_Set (R11.3).
      return []
    }

    default: {
      // Exhaustiveness guard: unreachable for a well-typed action.
      return state
    }
  }
}

/** A stable client id for a newly placed field. */
function newClientId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto
  if (c?.randomUUID) return c.randomUUID()
  // Fallback for environments without crypto.randomUUID (kept off the reducer
  // so the reducer itself stays pure/deterministic).
  return `f_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`
}

/** What {@link useFieldSet} returns: the Field_Set plus typed action helpers. */
export interface UseFieldSetResult {
  /** The current Field_Set. */
  fields: FieldSetState
  /** Raw dispatch for callers that prefer to build actions directly. */
  dispatch: Dispatch<FieldSetAction>
  /**
   * Place a new field at `rect` on `page` for `recipientKey`. Generates a stable
   * client id and returns it so the caller can immediately select the field.
   */
  addField: (input: {
    type: FieldType
    page: number
    rect: NormalizedRect
    recipientKey: number
    dims: PageDims
  }) => string
  /** Move an existing field to a new (clamped) position. */
  moveField: (clientId: string, rect: NormalizedRect, dims: PageDims) => void
  /** Resize an existing field to a new (clamped) size/position. */
  resizeField: (clientId: string, rect: NormalizedRect, dims: PageDims) => void
  /** Re-assign a field to a different recipient. */
  assignField: (clientId: string, recipientKey: number) => void
  /** Toggle a field required/optional. */
  setRequired: (clientId: string, required: boolean) => void
  /** Set a `text` / `number` field's label/placeholder. */
  setTextMeta: (clientId: string, label?: string, placeholder?: string) => void
  /** Set a `radio` / `dropdown` field's sender-authored options. */
  setOptions: (clientId: string, options: string[]) => void
  /** Delete a field from the set. */
  deleteField: (clientId: string) => void
  /** Cascade-delete every field assigned to a recipient. */
  removeRecipient: (recipientKey: number) => void
  /**
   * Replace the whole Field_Set with a pre-built set (edit-after-send seeding,
   * R13.1). Client ids are generated here (off the pure reducer) so callers
   * pass field inputs without one.
   */
  seedFields: (fields: ReadonlyArray<Omit<PlacedField, 'clientId'>>) => void
  /** Empty the Field_Set (cancel / reopen). */
  reset: () => void
}

/**
 * React hook wrapping the pure {@link fieldSetReducer}. Exposes the current
 * Field_Set and a set of typed action-creator helpers; client ids for new
 * fields are generated here (off the pure reducer).
 */
export function useFieldSet(): UseFieldSetResult {
  const [fields, dispatch] = useReducer(fieldSetReducer, [] as FieldSetState)

  const addField = useCallback<UseFieldSetResult['addField']>((input) => {
    const clientId = newClientId()
    dispatch({ kind: 'add', clientId, ...input })
    return clientId
  }, [])

  const moveField = useCallback<UseFieldSetResult['moveField']>((clientId, rect, dims) => {
    dispatch({ kind: 'move', clientId, rect, dims })
  }, [])

  const resizeField = useCallback<UseFieldSetResult['resizeField']>((clientId, rect, dims) => {
    dispatch({ kind: 'resize', clientId, rect, dims })
  }, [])

  const assignField = useCallback<UseFieldSetResult['assignField']>((clientId, recipientKey) => {
    dispatch({ kind: 'assign', clientId, recipientKey })
  }, [])

  const setRequired = useCallback<UseFieldSetResult['setRequired']>((clientId, required) => {
    dispatch({ kind: 'setRequired', clientId, required })
  }, [])

  const setTextMeta = useCallback<UseFieldSetResult['setTextMeta']>(
    (clientId, label, placeholder) => {
      dispatch({ kind: 'setTextMeta', clientId, label, placeholder })
    },
    [],
  )

  const setOptions = useCallback<UseFieldSetResult['setOptions']>((clientId, options) => {
    dispatch({ kind: 'setOptions', clientId, options })
  }, [])

  const deleteField = useCallback<UseFieldSetResult['deleteField']>((clientId) => {
    dispatch({ kind: 'delete', clientId })
  }, [])

  const removeRecipient = useCallback<UseFieldSetResult['removeRecipient']>((recipientKey) => {
    dispatch({ kind: 'removeRecipient', recipientKey })
  }, [])

  const seedFields = useCallback<UseFieldSetResult['seedFields']>((inputs) => {
    const seeded: PlacedField[] = inputs.map((input) => ({ ...input, clientId: newClientId() }))
    dispatch({ kind: 'seed', fields: seeded })
  }, [])

  const reset = useCallback<UseFieldSetResult['reset']>(() => {
    dispatch({ kind: 'reset' })
  }, [])

  return useMemo(
    () => ({
      fields,
      dispatch,
      addField,
      moveField,
      resizeField,
      assignField,
      setRequired,
      setTextMeta,
      setOptions,
      deleteField,
      removeRecipient,
      seedFields,
      reset,
    }),
    [
      fields,
      addField,
      moveField,
      resizeField,
      assignField,
      setRequired,
      setTextMeta,
      setOptions,
      deleteField,
      removeRecipient,
      seedFields,
      reset,
    ],
  )
}

export default useFieldSet
