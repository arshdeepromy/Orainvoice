import { useMemo, useCallback } from 'react'
import { Sheet, BlockTitle, List, ListItem } from 'konsta/react'
import { useNavigate } from 'react-router-dom'
import { useModules } from '@/contexts/ModuleContext'
import { useAuth } from '@/contexts/AuthContext'
import type { UserRole } from '@shared/types/auth'
import {
  MORE_MENU_ITEMS,
  filterMoreMenuItems,
  groupByCategory,
} from '@/navigation/MoreMenuConfig'
import type { MoreMenuItem } from '@/navigation/MoreMenuConfig'

// ─── SVG icon component ─────────────────────────────────────────────────────

function MenuIcon({ d }: { d: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
      className="h-6 w-6 text-gray-600 dark:text-gray-300"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  )
}

// ─── Chevron icon ───────────────────────────────────────────────────────────

function ChevronRight() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={2}
      stroke="currentColor"
      className="h-4 w-4 text-gray-400 dark:text-gray-500"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
    </svg>
  )
}

// ─── MoreDrawer props ───────────────────────────────────────────────────────

interface MoreDrawerProps {
  isOpen: boolean
  onClose: () => void
}

/**
 * MoreDrawer — Konsta UI Sheet that displays module-gated navigation items
 * grouped by category. Opens when the More tab is tapped.
 *
 * Filtering uses identical logic to the existing sidebar:
 * module enabled + trade family + user role + adminOnly.
 *
 * Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8
 */
export function MoreDrawer({ isOpen, onClose }: MoreDrawerProps) {
  const navigate = useNavigate()
  const { enabledModules, tradeFamily } = useModules()
  const { user } = useAuth()
  const userRole = (user?.role ?? 'salesperson') as UserRole

  // Filter and group items
  const grouped = useMemo(() => {
    const visible = filterMoreMenuItems(
      MORE_MENU_ITEMS,
      enabledModules,
      tradeFamily,
      userRole,
    )
    return groupByCategory(visible)
  }, [enabledModules, tradeFamily, userRole])

  const handleItemTap = useCallback(
    (item: MoreMenuItem) => {
      navigate(item.path)
      onClose()
    },
    [navigate, onClose],
  )

  return (
    <Sheet
      opened={isOpen}
      onBackdropClick={onClose}
      backdrop
      data-testid="more-drawer"
      className="pb-safe"
      style={{ zIndex: 13500 }}
    >
      <div
        className="max-h-[80vh] overflow-y-auto pb-safe"
        data-testid="more-drawer-content"
      >
        {/* Drag handle indicator */}
        <div className="flex justify-center pb-2 pt-3">
          <div className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" />
        </div>

        {/* Title */}
        <div className="px-4 pb-2">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            More
          </h2>
        </div>

        {/* Grouped navigation items */}
        {grouped.map(([category, items]) => (
          <div key={category} data-testid={`more-category-${category}`}>
            <BlockTitle>{category}</BlockTitle>
            <List strongIos outlineIos>
              {items.map((item) => (
                <ListItem
                  key={item.id}
                  media={<MenuIcon d={item.icon} />}
                  title={item.label}
                  after={
                    <div className="flex items-center gap-2">
                      {item.badge != null && item.badge > 0 && (
                        <span
                          className="inline-flex min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1.5 py-0.5 text-xs font-medium text-white"
                          data-testid={`badge-${item.id}`}
                        >
                          {item.badge}
                        </span>
                      )}
                      <ChevronRight />
                    </div>
                  }
                  link
                  onClick={() => handleItemTap(item)}
                  data-testid={`more-item-${item.id}`}
                />
              ))}
            </List>
          </div>
        ))}
      </div>
    </Sheet>
  )
}
