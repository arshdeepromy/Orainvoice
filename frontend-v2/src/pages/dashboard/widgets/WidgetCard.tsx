/**
 * Presentational card wrapper for dashboard widgets.
 *
 * Provides consistent styling, header with icon/title/action link,
 * loading spinner overlay, and error message display.
 *
 * Ported from frontend/src/pages/dashboard/widgets/WidgetCard.tsx (Task 18).
 * The prop contract (`WidgetCardProps`: title / icon / actionLink / children /
 * isLoading / error) and behaviour (header row, action link, body, loading
 * overlay, error message) are preserved verbatim (FR-1). The presentation is
 * remapped onto the redesign tokens / prototype card language (FR-2): the
 * `.card` surface (rounded-card, border-border, bg-card, shadow-card), the
 * `.card-head` row (bottom border, px-5 py-[17px], 15px/600 heading, accent
 * `.link` action), and the `.card-body` padding (p-5) from
 * OraInvoice_Handoff/app/ds.css — the same patterns the ported MainDashboard /
 * OrgAdminDashboard cards use.
 *
 * Requirements: 14.1, 14.2, 14.3, 15.5
 */

import { Link } from 'react-router-dom'
import { Spinner } from '@/components/ui'
import type { WidgetCardProps } from './types'

export function WidgetCard({
  title,
  icon: Icon,
  actionLink,
  children,
  isLoading = false,
  error = null,
}: WidgetCardProps) {
  return (
    <div className="relative rounded-card border border-border bg-card shadow-card">
      {/* Header — mirrors the prototype `.card-head` */}
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-[17px]">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="h-[18px] w-[18px] shrink-0 text-muted" />
          <h3 className="truncate text-[15px] font-semibold text-text">{title}</h3>
        </div>
        {actionLink && (
          <Link
            to={actionLink.to}
            className="shrink-0 text-[12.5px] font-medium text-accent hover:text-accent-press"
          >
            {actionLink.label}
          </Link>
        )}
      </div>

      {/* Body — `.card-body` */}
      <div className="p-5">
        {error ? (
          <p className="text-[13px] text-danger">{error}</p>
        ) : (
          children
        )}
      </div>

      {/* Loading overlay */}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center rounded-card bg-card/70">
          <Spinner size="sm" label={`Loading ${title}`} />
        </div>
      )}
    </div>
  )
}
