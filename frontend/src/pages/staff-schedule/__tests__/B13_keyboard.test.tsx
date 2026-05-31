/**
 * Tests for the keyboard navigation reducer (B13).
 *
 * Property: for any sequence of arrow keys starting from any cell in
 * the grid, the focused cell stays in `[0, R) × [0, C)`.
 *
 * Validates: R10.2-R10.5, R10.10, R14.4 (Property P4).
 */

import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import {
  gridKeyboardReducer,
  selectionRectFromState,
  type GridKeyboardKey,
} from '../utils/keyboard'

const KEYS: GridKeyboardKey[] = [
  'ArrowLeft',
  'ArrowRight',
  'ArrowUp',
  'ArrowDown',
]

describe('gridKeyboardReducer', () => {
  it('clamps to grid bounds on arrow keys', () => {
    const start = {
      rows: 5,
      cols: 14,
      focused: { row: 0, col: 0 },
      selectionAnchor: { row: 0, col: 0 },
    }
    const next = gridKeyboardReducer(start, { key: 'ArrowLeft', shift: false })
    expect(next.focused).toEqual({ row: 0, col: 0 })
  })

  it('moves the focused cell on arrow keys', () => {
    const start = {
      rows: 5,
      cols: 14,
      focused: { row: 2, col: 3 },
      selectionAnchor: { row: 2, col: 3 },
    }
    expect(
      gridKeyboardReducer(start, { key: 'ArrowRight', shift: false }).focused,
    ).toEqual({ row: 2, col: 4 })
    expect(
      gridKeyboardReducer(start, { key: 'ArrowDown', shift: false }).focused,
    ).toEqual({ row: 3, col: 3 })
  })

  it('keeps selectionAnchor when shift is held', () => {
    const start = {
      rows: 5,
      cols: 14,
      focused: { row: 2, col: 3 },
      selectionAnchor: { row: 2, col: 3 },
    }
    const next = gridKeyboardReducer(start, {
      key: 'ArrowRight',
      shift: true,
    })
    expect(next.focused).toEqual({ row: 2, col: 4 })
    expect(next.selectionAnchor).toEqual({ row: 2, col: 3 })
    const rect = selectionRectFromState(next)
    expect(rect).toEqual({
      rowStart: 2,
      rowEnd: 2,
      colStart: 3,
      colEnd: 4,
    })
  })

  it('property: focused cell always inside [0, R) × [0, C)', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 50 }),
        fc.array(fc.constantFrom(...KEYS), { minLength: 0, maxLength: 100 }),
        fc.integer({ min: 0, max: 49 }),
        fc.integer({ min: 0, max: 13 }),
        (rows, keys, startRow, startCol) => {
          const safeRow = Math.min(startRow, rows - 1)
          let state = {
            rows,
            cols: 14,
            focused: { row: safeRow, col: startCol },
            selectionAnchor: { row: safeRow, col: startCol },
          }
          for (const key of keys) {
            state = gridKeyboardReducer(state, { key, shift: false })
          }
          expect(state.focused.row).toBeGreaterThanOrEqual(0)
          expect(state.focused.row).toBeLessThan(rows)
          expect(state.focused.col).toBeGreaterThanOrEqual(0)
          expect(state.focused.col).toBeLessThan(14)
        },
      ),
      { numRuns: 100 },
    )
  })
})
