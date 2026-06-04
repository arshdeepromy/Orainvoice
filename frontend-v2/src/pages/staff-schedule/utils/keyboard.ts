/**
 * Pure reducer for the grid's keyboard navigation
 * (Workstream B / task B13).
 *
 * `gridKeyboardReducer(state, key)` mutates only the focused cell;
 * Shift+Arrow extends a `selectionEnd` anchor for multi-cell selection
 * (R10.10).  Always clamps to `[0, R) × [0, C)`.
 *
 * Validates: R10.2-R10.5, R10.10, R14.4 (Property P4).
 */

export interface GridKeyboardState {
  rows: number
  cols: number
  focused: { row: number; col: number }
  /** Anchor for Shift+Arrow multi-cell selection. Mirrors `focused`
   *  when no selection has been started. */
  selectionAnchor: { row: number; col: number }
}

export type GridKeyboardKey =
  | 'ArrowLeft'
  | 'ArrowRight'
  | 'ArrowUp'
  | 'ArrowDown'

export interface GridKeyboardAction {
  key: GridKeyboardKey
  shift: boolean
}

function clamp(n: number, min: number, max: number): number {
  if (n < min) return min
  if (n > max) return max
  return n
}

export function gridKeyboardReducer(
  state: GridKeyboardState,
  action: GridKeyboardAction,
): GridKeyboardState {
  const { rows, cols } = state
  const { row, col } = state.focused
  let nextRow = row
  let nextCol = col
  switch (action.key) {
    case 'ArrowLeft':
      nextCol = clamp(col - 1, 0, cols - 1)
      break
    case 'ArrowRight':
      nextCol = clamp(col + 1, 0, cols - 1)
      break
    case 'ArrowUp':
      nextRow = clamp(row - 1, 0, rows - 1)
      break
    case 'ArrowDown':
      nextRow = clamp(row + 1, 0, rows - 1)
      break
    default:
      return state
  }

  // Clamp again defensively in case rows/cols are 0 (empty grid).
  if (rows <= 0 || cols <= 0) return state

  const nextFocused = { row: nextRow, col: nextCol }
  const nextAnchor = action.shift
    ? state.selectionAnchor
    : { row: nextRow, col: nextCol }
  return {
    rows,
    cols,
    focused: nextFocused,
    selectionAnchor: nextAnchor,
  }
}

/** Bounding rectangle implied by the current selection anchor + focus. */
export interface SelectionRect {
  rowStart: number
  rowEnd: number
  colStart: number
  colEnd: number
}

export function selectionRectFromState(
  state: GridKeyboardState,
): SelectionRect {
  const { focused, selectionAnchor } = state
  return {
    rowStart: Math.min(focused.row, selectionAnchor.row),
    rowEnd: Math.max(focused.row, selectionAnchor.row),
    colStart: Math.min(focused.col, selectionAnchor.col),
    colEnd: Math.max(focused.col, selectionAnchor.col),
  }
}
