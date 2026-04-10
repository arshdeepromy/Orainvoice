import { useState, useCallback } from 'react'

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
    <div className={`overflow-x-auto ${className}`}>
      <table className="min-w-full divide-y divide-gray-200" role="grid">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="bg-gray-50">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={`px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500
                  ${col.sortable ? 'cursor-pointer select-none hover:text-gray-700' : ''}`}
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
                    <span aria-hidden="true" className="text-gray-400">
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
        <tbody className="divide-y divide-gray-200 bg-white">
          {sortedData.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-sm text-gray-500">
                No data available
              </td>
            </tr>
          ) : (
            sortedData.map((row) => (
              <tr key={String((row as Record<string, unknown>)[keyField as string])} className="hover:bg-gray-50">
                {columns.map((col) => (
                  <td key={col.key} className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">
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
