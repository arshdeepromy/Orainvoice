import { useState, useCallback } from 'react'
import { cx } from './cx'

/**
 * DataTable — sortable, accessible table primitive (Task 17 port of
 * frontend/src/components/ui/DataTable).
 *
 * The component's PUBLIC API and ALL sorting/keyboard logic are copied verbatim
 * from the original (column defs, `keyField`, `caption`, the three-state
 * asc→desc→none sort cycle, Enter/Space keyboard activation, the numeric-aware
 * `localeCompare`). Only the markup styling is remapped to the prototype's
 * surface + table language from OraInvoice_Handoff/app/ds.css, matching the
 * recent-invoices table already shipped in MainDashboard (Task 16):
 *   • wrapper           → rounded-card border + card bg + shadow-card
 *   • header cells      → mono, 10.5px, uppercase, muted-2, border-b
 *   • body rows         → 13.5px text, hover:bg-canvas, border-b between rows
 *   • empty state       → centered muted message
 *
 * Numbers/IDs render in the `.mono` (tabular) face so columns line up, matching
 * the prototype's monetary/identifier columns.
 *
 * Safe consumption: callers pass already-guarded arrays (`?? []`); this
 * component never assumes a non-empty list and renders an empty-state row when
 * `data` is empty.
 */

type SortDirection = 'asc' | 'desc' | null

export interface Column<T> {
  key: string
  header: string
  sortable?: boolean
  render?: (row: T) => React.ReactNode
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  keyField: keyof T
  caption?: string
  className?: string
}

export function DataTable<T extends object>({
  columns,
  data,
  keyField,
  caption,
  className = '',
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDirection>(null)

  const handleSort = useCallback(
    (key: string) => {
      if (sortKey === key) {
        setSortDir((prev) => (prev === 'asc' ? 'desc' : prev === 'desc' ? null : 'asc'))
        if (sortDir === 'desc') setSortKey(null)
      } else {
        setSortKey(key)
        setSortDir('asc')
      }
    },
    [sortKey, sortDir],
  )

  const sortedData = (() => {
    if (!sortKey || !sortDir) return data
    return [...data].sort((a, b) => {
      const aVal = (a as Record<string, unknown>)[sortKey]
      const bVal = (b as Record<string, unknown>)[sortKey]
      if (aVal == null && bVal == null) return 0
      if (aVal == null) return 1
      if (bVal == null) return -1
      const cmp = String(aVal).localeCompare(String(bVal), undefined, { numeric: true })
      return sortDir === 'asc' ? cmp : -cmp
    })
  })()

  const handleKeyDown = (e: React.KeyboardEvent, key: string) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleSort(key)
    }
  }

  return (
    <div
      className={cx(
        'overflow-x-auto rounded-card border border-border bg-card shadow-card',
        className,
      )}
    >
      <table className="w-full border-collapse" role="grid">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={cx(
                  'mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2',
                  col.sortable && 'cursor-pointer select-none hover:text-muted',
                )}
                aria-sort={
                  sortKey === col.key && sortDir
                    ? sortDir === 'asc'
                      ? 'ascending'
                      : 'descending'
                    : undefined
                }
                onClick={col.sortable ? () => handleSort(col.key) : undefined}
                onKeyDown={col.sortable ? (e) => handleKeyDown(e, col.key) : undefined}
                tabIndex={col.sortable ? 0 : undefined}
                role={col.sortable ? 'columnheader button' : 'columnheader'}
              >
                <span className="flex items-center gap-1">
                  {col.header}
                  {col.sortable && (
                    <span aria-hidden="true" className="text-muted-2">
                      {sortKey === col.key && sortDir === 'asc'
                        ? '↑'
                        : sortKey === col.key && sortDir === 'desc'
                          ? '↓'
                          : '↕'}
                    </span>
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedData.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-5 py-10 text-center text-[13px] text-muted">
                No data available
              </td>
            </tr>
          ) : (
            sortedData.map((row) => (
              <tr
                key={String((row as Record<string, unknown>)[keyField as string])}
                className="border-b border-border transition-colors last:border-b-0 hover:bg-canvas"
              >
                {columns.map((col) => (
                  <td key={col.key} className="px-5 py-3 text-[13.5px] text-text">
                    {col.render ? col.render(row) : String((row as Record<string, unknown>)[col.key] ?? '')}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

export default DataTable
