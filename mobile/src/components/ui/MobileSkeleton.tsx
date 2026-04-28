import type { ReactNode } from 'react'

/**
 * Shimmer skeleton placeholders for list and detail screens.
 * Replaces spinners with layout-aware loading states.
 *
 * Requirements: 1.3
 */
export function SkeletonLine({ width = 'full' }: { width?: 'full' | '3/4' | '1/2' | '1/3' }) {
  const widthClass = {
    full: 'w-full',
    '3/4': 'w-3/4',
    '1/2': 'w-1/2',
    '1/3': 'w-1/3',
  }[width]

  return (
    <div
      className={`h-4 animate-pulse rounded bg-gray-200 dark:bg-gray-700 ${widthClass}`}
    />
  )
}

export function SkeletonCard({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  )
}

export function DetailScreenSkeleton() {
  return (
    <div className="flex flex-col gap-4 p-4">
      <SkeletonCard>
        <SkeletonLine width="1/2" />
        <SkeletonLine width="3/4" />
      </SkeletonCard>
      <SkeletonCard>
        <SkeletonLine width="1/3" />
        <SkeletonLine />
        <SkeletonLine />
        <SkeletonLine width="3/4" />
      </SkeletonCard>
      <SkeletonCard>
        <SkeletonLine width="1/2" />
        <SkeletonLine width="3/4" />
        <SkeletonLine width="1/2" />
      </SkeletonCard>
    </div>
  )
}
