import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ComplianceDocumentResponse, CategoryResponse } from './ComplianceDashboard'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type SortColumn = 'document_type' | 'file_name' | 'expiry_date' | 'created_at'
type SortDir = 'asc' | 'desc'

interface DocumentTableProps {
  documents: ComplianceDocumentResponse[]
  categories: CategoryResponse[]
  loading: boolean
  onDownload: (doc: ComplianceDocumentResponse) => void
  onPreview: (doc: ComplianceDocumentResponse) => void
  onEdit: (doc: ComplianceDocumentResponse) => void
  onDelete: (doc: ComplianceDocumentResponse) => void
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const STATUS_BADGE_STYLES: Record<string, string> = {
  valid: 'bg-ok-soft text-ok',
  expiring_soon: 'bg-warn-soft text-warn',
  expired: 'bg-danger-soft text-danger',
  no_expiry: 'bg-canvas text-muted',
}

function statusLabel(status: string | undefined): string {
  if (!status) return 'Unknown'
  if (status === 'expiring_soon') return 'Expiring Soon'
  if (status === 'no_expiry') return 'No Expiry'
  return status.charAt(0).toUpperCase() + status.slice(1)
}

/** Returns true when the file extension supports inline preview (PDF / images). */
function isPreviewable(doc: ComplianceDocumentResponse): boolean {
  const name = (doc.file_name ?? doc.file_key ?? '').toLowerCase()
  return /\.(pdf|jpe?g|png|gif)$/.test(name)
}

const headerCellClass =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

/** Build a clickable link for the linked entity (invoice or job). */
function LinkedEntityCell({ doc }: { doc: ComplianceDocumentResponse }) {
  const links: React.ReactNode[] = []

  if (doc.invoice_id) {
    links.push(
      <Link
        key="invoice"
        to={`/invoices/${doc.invoice_id}`}
        className="text-accent hover:text-accent-press hover:underline"
      >
        Invoice
      </Link>,
    )
  }

  if (doc.job_id) {
    links.push(
      <Link
        key="job"
        to={`/jobs/${doc.job_id}`}
        className="text-accent hover:text-accent-press hover:underline"
      >
        Job
      </Link>,
    )
  }

  if (links.length === 0) return <span>—</span>

  return (
    <span>
      {links.reduce<React.ReactNode[]>((acc, link, i) => {
        if (i > 0) acc.push(<span key={`sep-${i}`}>, </span>)
        acc.push(link)
        return acc
      }, [])}
    </span>
  )
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function DocumentTable({
  documents,
  categories,
  loading,
  onDownload,
  onPreview,
  onEdit,
  onDelete,
}: DocumentTableProps) {
  /* --- local filter / sort state --- */
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [sortCol, setSortCol] = useState<SortColumn>('created_at')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const hasAnyDocuments = (documents ?? []).length > 0

  /* --- filtering --- */
  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim()
    return (documents ?? []).filter((doc) => {
      // text search
      if (q) {
        const matchesSearch =
          (doc.file_name ?? '').toLowerCase().includes(q) ||
          (doc.document_type ?? '').toLowerCase().includes(q) ||
          (doc.description ?? '').toLowerCase().includes(q)
        if (!matchesSearch) return false
      }
      // status filter
      if (statusFilter !== 'all' && doc.status !== statusFilter) return false
      // category filter
      if (categoryFilter !== 'all' && doc.document_type !== categoryFilter) return false
      return true
    })
  }, [documents, search, statusFilter, categoryFilter])

  /* --- sorting --- */
  const sorted = useMemo(() => {
    const list = [...filtered]
    list.sort((a, b) => {
      let aVal: string | null = null
      let bVal: string | null = null

      switch (sortCol) {
        case 'document_type':
          aVal = a.document_type ?? ''
          bVal = b.document_type ?? ''
          break
        case 'file_name':
          aVal = a.file_name ?? ''
          bVal = b.file_name ?? ''
          break
        case 'expiry_date':
          aVal = a.expiry_date ?? ''
          bVal = b.expiry_date ?? ''
          break
        case 'created_at':
          aVal = a.created_at ?? ''
          bVal = b.created_at ?? ''
          break
      }

      const cmp = (aVal ?? '').localeCompare(bVal ?? '')
      return sortDir === 'asc' ? cmp : -cmp
    })
    return list
  }, [filtered, sortCol, sortDir])

  /* --- sort toggle handler --- */
  const handleSort = (col: SortColumn) => {
    if (sortCol === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(col)
      setSortDir('asc')
    }
  }

  const filtersActive = search.trim() !== '' || statusFilter !== 'all' || categoryFilter !== 'all'

  /* --- status filter options --- */
  const statusOptions = [
    { value: 'all', label: 'All' },
    { value: 'valid', label: 'Valid' },
    { value: 'expiring_soon', label: 'Expiring Soon' },
    { value: 'expired', label: 'Expired' },
    { value: 'no_expiry', label: 'No Expiry' },
  ]

  /* --- category filter options --- */
  const categoryOptions = useMemo(() => {
    const opts = [{ value: 'all', label: 'All Categories' }]
    ;(categories ?? []).forEach((cat) => {
      opts.push({ value: cat.name, label: cat.name })
    })
    return opts
  }, [categories])

  /* --- loading state --- */
  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="w-full animate-pulse space-y-3">
          <div className="h-10 rounded bg-border" />
          <div className="h-8 rounded bg-border" />
          <div className="h-8 rounded bg-border" />
          <div className="h-8 rounded bg-border" />
        </div>
      </div>
    )
  }

  return (
    <div>
      {/* Filters row */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        {/* Search */}
        <div className="flex-1">
          <label htmlFor="doc-search" className="text-sm font-medium text-text">
            Search
          </label>
          <input
            id="doc-search"
            type="text"
            placeholder="Search by name, type, or description…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="mt-1 h-[42px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm placeholder:text-muted-2 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          />
        </div>

        {/* Status filter */}
        <div className="w-full sm:w-48">
          <label htmlFor="status-filter" className="text-sm font-medium text-text">
            Status
          </label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="mt-1 h-[42px] w-full appearance-none rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            {statusOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Category filter */}
        <div className="w-full sm:w-48">
          <label htmlFor="category-filter" className="text-sm font-medium text-text">
            Category
          </label>
          <select
            id="category-filter"
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="mt-1 h-[42px] w-full appearance-none rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            {categoryOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Empty states */}
      {sorted.length === 0 ? (
        <div className="py-16 text-center text-sm text-muted">
          {hasAnyDocuments && filtersActive
            ? 'No documents match your filters'
            : 'No compliance documents yet. Upload your first document to get started.'}
        </div>
      ) : (
        /* Table */
        <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table
            className="min-w-full text-sm"
            role="grid"
            aria-label="Compliance documents list"
          >
            <caption className="sr-only">Compliance documents list</caption>
            <thead>
              <tr>
                <SortableHeader
                  label="Document Type"
                  column="document_type"
                  currentCol={sortCol}
                  currentDir={sortDir}
                  onSort={handleSort}
                />
                <SortableHeader
                  label="File Name"
                  column="file_name"
                  currentCol={sortCol}
                  currentDir={sortDir}
                  onSort={handleSort}
                />
                <th
                  scope="col"
                  className={headerCellClass}
                >
                  Description
                </th>
                <SortableHeader
                  label="Expiry Date"
                  column="expiry_date"
                  currentCol={sortCol}
                  currentDir={sortDir}
                  onSort={handleSort}
                />
                <th
                  scope="col"
                  className={headerCellClass}
                >
                  Status
                </th>
                <th
                  scope="col"
                  className={headerCellClass}
                >
                  Linked Entity
                </th>
                <SortableHeader
                  label="Uploaded Date"
                  column="created_at"
                  currentCol={sortCol}
                  currentDir={sortDir}
                  onSort={handleSort}
                />
                <th
                  scope="col"
                  className={headerCellClass}
                >
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {(sorted ?? []).map((doc) => (
                <tr key={doc.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-text">
                    {doc.document_type}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">
                    {doc.file_name}
                  </td>
                  <td className="max-w-xs truncate px-4 py-3 text-sm text-muted">
                    {doc.description ?? '—'}
                  </td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">
                    {doc.expiry_date ?? 'No expiry'}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <StatusBadge status={doc.status} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">
                    <LinkedEntityCell doc={doc} />
                  </td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">
                    {new Date(doc.created_at).toLocaleDateString()}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <ActionButtons
                      doc={doc}
                      onDownload={onDownload}
                      onPreview={onPreview}
                      onEdit={onEdit}
                      onDelete={onDelete}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

/** Sortable column header with asc/desc indicator */
function SortableHeader({
  label,
  column,
  currentCol,
  currentDir,
  onSort,
}: {
  label: string
  column: SortColumn
  currentCol: SortColumn
  currentDir: SortDir
  onSort: (col: SortColumn) => void
}) {
  const isActive = currentCol === column
  const arrow = isActive ? (currentDir === 'asc' ? ' ↑' : ' ↓') : ''

  return (
    <th
      scope="col"
      className="mono cursor-pointer select-none border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2 hover:text-muted"
      onClick={() => onSort(column)}
      aria-sort={isActive ? (currentDir === 'asc' ? 'ascending' : 'descending') : 'none'}
      role="columnheader"
    >
      {label}
      {arrow}
    </th>
  )
}

/** Colour-coded status badge */
function StatusBadge({ status }: { status?: string }) {
  const style = STATUS_BADGE_STYLES[status ?? ''] ?? STATUS_BADGE_STYLES.no_expiry
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${style}`}>
      {statusLabel(status)}
    </span>
  )
}

/** Action buttons: download, preview (PDF/image only), edit, delete */
function ActionButtons({
  doc,
  onDownload,
  onPreview,
  onEdit,
  onDelete,
}: {
  doc: ComplianceDocumentResponse
  onDownload: (doc: ComplianceDocumentResponse) => void
  onPreview: (doc: ComplianceDocumentResponse) => void
  onEdit: (doc: ComplianceDocumentResponse) => void
  onDelete: (doc: ComplianceDocumentResponse) => void
}) {
  const canPreview = isPreviewable(doc)

  return (
    <div className="flex items-center gap-1">
      {/* Download */}
      <button
        type="button"
        onClick={() => onDownload(doc)}
        className="rounded-ctl p-1.5 text-muted-2 hover:bg-canvas hover:text-text"
        aria-label={`Download ${doc.file_name}`}
        title="Download"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5m0 0l5-5m-5 5V3" />
        </svg>
      </button>

      {/* Preview — PDF and images only */}
      {canPreview && (
        <button
          type="button"
          onClick={() => onPreview(doc)}
          className="rounded-ctl p-1.5 text-muted-2 hover:bg-canvas hover:text-text"
          aria-label={`Preview ${doc.file_name}`}
          title="Preview"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
          </svg>
        </button>
      )}

      {/* Edit */}
      <button
        type="button"
        onClick={() => onEdit(doc)}
        className="rounded-ctl p-1.5 text-muted-2 hover:bg-canvas hover:text-text"
        aria-label={`Edit ${doc.file_name}`}
        title="Edit"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
        </svg>
      </button>

      {/* Delete */}
      <button
        type="button"
        onClick={() => onDelete(doc)}
        className="rounded-ctl p-1.5 text-danger/70 hover:bg-danger-soft hover:text-danger"
        aria-label={`Delete ${doc.file_name}`}
        title="Delete"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
      </button>
    </div>
  )
}
