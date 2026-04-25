/**
 * Presentational card wrapper for dashboard widgets.
 *
 * Provides consistent styling, header with icon/title/action link,
 * loading spinner overlay, and error message display.
 *
 * Requirements: 14.1, 14.2, 14.3, 15.5
 */

import { Link } from 'react-router-dom'
import { Spinner } from '@/components/ui/Spinner'
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
    <div className="relative rounded-lg border border-gray-200 bg-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
        <div className="flex items-center gap-2">
          <Icon className="h-5 w-5 text-gray-500" />
          <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        </div>
        {actionLink && (
          <Link
            to={actionLink.to}
            className="text-xs font-medium text-blue-600 hover:text-blue-800"
          >
            {actionLink.label}
          </Link>
        )}
      </div>

      {/* Body */}
      <div className="p-4">
        {error ? (
          <p className="text-sm text-red-600">{error}</p>
        ) : (
          children
        )}
      </div>

      {/* Loading overlay */}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-white/70">
          <Spinner size="sm" label={`Loading ${title}`} />
        </div>
      )}
    </div>
  )
}
