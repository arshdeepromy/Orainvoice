/**
 * Pagination — page-number nav (Task 23 port of frontend/src/components/ui/Pagination).
 *
 * The component's PUBLIC API and ALL page-number logic are copied VERBATIM from
 * the original (the ≤7-pages-vs-ellipsis window builder, Enter/Space keyboard
 * activation, prev/next disabling, aria wiring). Only the markup styling is
 * remapped to the prototype's pagination language from
 * OraInvoice_Handoff/app/ds.css (`.pg-btns button` — 32px square, ctl radii,
 * mono digits, border + card bg; active → accent fill).
 */
interface PaginationProps {
  currentPage: number
  totalPages: number
  onPageChange: (page: number) => void
  className?: string
}

export function Pagination({ currentPage, totalPages, onPageChange, className = '' }: PaginationProps) {
  if (totalPages <= 1) return null

  const getPageNumbers = (): (number | '...')[] => {
    const pages: (number | '...')[] = []
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) pages.push(i)
    } else {
      pages.push(1)
      if (currentPage > 3) pages.push('...')
      for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) {
        pages.push(i)
      }
      if (currentPage < totalPages - 2) pages.push('...')
      pages.push(totalPages)
    }
    return pages
  }

  const handleKeyDown = (e: React.KeyboardEvent, page: number) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onPageChange(page)
    }
  }

  return (
    <nav aria-label="Pagination" className={`flex items-center justify-center gap-1.5 ${className}`}>
      <button
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage <= 1}
        aria-label="Previous page"
        className="mono flex h-8 items-center rounded-ctl border border-border bg-card px-3 text-[12.5px] text-text transition-colors
          hover:border-border-strong disabled:opacity-40 disabled:cursor-not-allowed
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        ‹
      </button>

      {getPageNumbers().map((page, i) =>
        page === '...' ? (
          <span key={`ellipsis-${i}`} className="mono px-1 text-[12.5px] text-muted-2" aria-hidden="true">
            …
          </span>
        ) : (
          <button
            key={page}
            onClick={() => onPageChange(page)}
            onKeyDown={(e) => handleKeyDown(e, page)}
            aria-label={`Page ${page}`}
            aria-current={currentPage === page ? 'page' : undefined}
            className={`mono flex h-8 w-8 items-center justify-center rounded-ctl border text-[12.5px] font-medium transition-colors
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent
              ${
                currentPage === page
                  ? 'border-accent bg-accent text-white'
                  : 'border-border bg-card text-text hover:border-border-strong'
              }`}
          >
            {page}
          </button>
        ),
      )}

      <button
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage >= totalPages}
        aria-label="Next page"
        className="mono flex h-8 items-center rounded-ctl border border-border bg-card px-3 text-[12.5px] text-text transition-colors
          hover:border-border-strong disabled:opacity-40 disabled:cursor-not-allowed
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        ›
      </button>
    </nav>
  )
}

export default Pagination
