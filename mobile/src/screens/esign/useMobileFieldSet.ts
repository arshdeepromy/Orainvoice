/**
 * useMobileFieldSet — Field_Set client state for the Mobile_Field_Placement_Editor.
 *
 * This is the mobile twin of the frontend-v2
 * `components/esign/fieldplacement/hooks/useFieldSet.ts` reducer. It owns the
 * complete collection of fields the Org_Sender has placed across all pages of
 * one document; the set lives entirely in client state for the lifetime of the
 * open editor — it survives in-editor page navigation (R11.1), is discarded on
 * cancel/reopen (R11.3), and is retained after a failed send so the sender can
 * correct and retry (R11.4).
 *
 * Coordinate model
 * ----------------
 * Each field's geometry is stored as a {@link NormalizedRect} (percent 0–100,
 * origin top-left) so it is render-scale independent — a viewport resize never
 * mutates a stored field (R7.2). Geometric clamping is defined in overlay (CSS
 * px) space, so the geometric actions (`add`/`move`/`resize`) carry the target
 * page's {@link PageDims}: the reducer converts the incoming normalized rect to
 * overlay px, runs the **shared** {@link clampToPage}, then converts back to
 * normalized before committing. Because placement and adjustment both flow
 * through the same shared `clampToPage` + mapping as the web editor, the
 * geometry invariants hold identically on both surfaces (R16.4, R16.5, R16.9).
 *
 * _Requirements: 16.4, 16.5, 16.9_
 */

import { useCallback, useMemo, useReducer, type Dispatch } from 'react'
import {
  clampToPage,
  normalizedToOverlay,
  overlayToNormalized,
  type FieldType,
  type NormalizedRect,
  type PageDims,
  type PlacedField,
} from '@/lib/esign'

/**
 * Minimum field size in CSS px, enforced on every geometric action so a resized
 * field stays large enough to display its type label (R3.6). `clampToPage` caps
 * these to the page size, so they never prevent a field fitting on a small page.
 * Identical to the frontend-v2 editor's `MIN_FIELD_*_PX`.
 */
export const MIN_FIELD_WIDTH_PX = 48
export const MIN_FIELD_HEIGHT_PX = 24

/** The Field_Set: a flat array of placed fields. */
export type FieldSetState = PlacedField[]

/**
 * Every mutation of the Field_Set. Geometric actions (`add`/`move`/`resize`)
 * carry the target page's {@link PageDims} so the reducer can clamp in overlay
 * space via the shared `clampToPage`.
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
  | { kind: 'delete'; clientId: string }
  | { kind: 'removeRecipient'; recipientKey: number } // cascade delete (R4.5)
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
 * runs the shared {@link clampToPage}, then converts back to normalized so the
 * stored value remains render-scale independent (R3.5, R3.6, R16.4, R16.5).
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
 * action it always returns the same next state. Byte-for-byte equivalent in
 * behaviour to the frontend-v2 reducer so the two surfaces stay in parity.
 */
export function fieldSetReducer(state: FieldSetState, action: FieldSetAction): FieldSetState {
  switch (action.kind) {
    case 'add': {
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
      return state.map((f) =>
        f.clientId === action.clientId
          ? { ...f, rect: clampNormalizedToPage(action.rect, action.dims) }
          : f,
      )
    }

    case 'assign': {
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
      return state.map((f) =>
        f.clientId === action.clientId
          ? { ...f, label: action.label, placeholder: action.placeholder }
          : f,
      )
    }

    case 'delete': {
      return state.filter((f) => f.clientId !== action.clientId)
    }

    case 'removeRecipient': {
      return state.filter((f) => f.recipientKey !== action.recipientKey)
    }

    case 'reset': {
      return []
    }

    default: {
      return state
    }
  }
}

/** A stable client id for a newly placed field. */
function newClientId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto
  if (c?.randomUUID) return c.randomUUID()
  return `f_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`
}

/** What {@link useMobileFieldSet} returns: the Field_Set plus typed helpers. */
export interface UseMobileFieldSetResult {
  fields: FieldSetState
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
  moveField: (clientId: string, rect: NormalizedRect, dims: PageDims) => void
  resizeField: (clientId: string, rect: NormalizedRect, dims: PageDims) => void
  assignField: (clientId: string, recipientKey: number) => void
  setRequired: (clientId: string, required: boolean) => void
  setTextMeta: (clientId: string, label?: string, placeholder?: string) => void
  deleteField: (clientId: string) => void
  removeRecipient: (recipientKey: number) => void
  reset: () => void
}

/**
 * React hook wrapping the pure {@link fieldSetReducer}. Exposes the current
 * Field_Set and typed action-creator helpers; client ids for new fields are
 * generated here (off the pure reducer).
 */
export function useMobileFieldSet(): UseMobileFieldSetResult {
  const [fields, dispatch] = useReducer(fieldSetReducer, [] as FieldSetState)

  const addField = useCallback<UseMobileFieldSetResult['addField']>((input) => {
    const clientId = newClientId()
    dispatch({ kind: 'add', clientId, ...input })
    return clientId
  }, [])

  const moveField = useCallback<UseMobileFieldSetResult['moveField']>((clientId, rect, dims) => {
    dispatch({ kind: 'move', clientId, rect, dims })
  }, [])

  const resizeField = useCallback<UseMobileFieldSetResult['resizeField']>(
    (clientId, rect, dims) => {
      dispatch({ kind: 'resize', clientId, rect, dims })
    },
    [],
  )

  const assignField = useCallback<UseMobileFieldSetResult['assignField']>(
    (clientId, recipientKey) => {
      dispatch({ kind: 'assign', clientId, recipientKey })
    },
    [],
  )

  const setRequired = useCallback<UseMobileFieldSetResult['setRequired']>((clientId, required) => {
    dispatch({ kind: 'setRequired', clientId, required })
  }, [])

  const setTextMeta = useCallback<UseMobileFieldSetResult['setTextMeta']>(
    (clientId, label, placeholder) => {
      dispatch({ kind: 'setTextMeta', clientId, label, placeholder })
    },
    [],
  )

  const deleteField = useCallback<UseMobileFieldSetResult['deleteField']>((clientId) => {
    dispatch({ kind: 'delete', clientId })
  }, [])

  const removeRecipient = useCallback<UseMobileFieldSetResult['removeRecipient']>(
    (recipientKey) => {
      dispatch({ kind: 'removeRecipient', recipientKey })
    },
    [],
  )

  const reset = useCallback<UseMobileFieldSetResult['reset']>(() => {
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
      deleteField,
      removeRecipient,
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
      deleteField,
      removeRecipient,
      reset,
    ],
  )
}

export default useMobileFieldSet
