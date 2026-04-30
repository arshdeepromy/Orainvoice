import type { ReactNode } from 'react'
import { useCallback } from 'react'
import { Navbar, NavbarBackLink } from 'konsta/react'
import { useNavigate } from 'react-router-dom'
import { useModules } from '@/contexts/ModuleContext'
import { useBranch } from '@/contexts/BranchContext'

/**
 * Props for the KonstaNavbar screen header component.
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
 */
export interface KonstaNavbarProps {
  /** Screen title displayed in the navbar */
  title: string
  /** Optional subtitle text (overrides branch selector when provided) */
  subtitle?: string
  /** Whether to show the back button (detail/nested screens) */
  showBack?: boolean
  /** Custom back handler — defaults to navigate(-1) */
  onBack?: () => void
  /** Screen-specific action buttons rendered in the right slot */
  rightActions?: ReactNode
  /** Callback when the branch selector pill is tapped */
  onBranchPress?: () => void
}

/**
 * KonstaNavbar — screen-level header using Konsta UI Navbar.
 *
 * Behaviour:
 * - Root screens: title centered, no back button
 * - Detail screens: back button on left, title centered
 * - Right slot: screen-specific action buttons (search, filter, overflow menu)
 * - When `branch_management` module is enabled: shows a tappable branch
 *   selector pill as subtitle that calls `onBranchPress`
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
 */
export function KonstaNavbar({
  title,
  subtitle,
  showBack = false,
  onBack,
  rightActions,
  onBranchPress,
}: KonstaNavbarProps) {
  const navigate = useNavigate()
  const { isModuleEnabled } = useModules()
  const { selectedBranchId, branches } = useBranch()

  const branchManagementEnabled = isModuleEnabled('branch_management')

  const handleBack = useCallback(() => {
    if (onBack) {
      onBack()
    } else {
      navigate(-1)
    }
  }, [onBack, navigate])

  // Resolve the branch selector subtitle
  const branchSubtitle = (() => {
    // Explicit subtitle takes priority
    if (subtitle) return null

    // Only show branch selector when branch_management module is enabled
    if (!branchManagementEnabled) return null

    const selectedBranch = branches.find((b) => b.id === selectedBranchId)
    const label = selectedBranch ? selectedBranch.name : 'All Branches'

    return (
      <button
        type="button"
        onClick={onBranchPress}
        data-testid="branch-selector-pill"
        className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary dark:bg-primary/20 dark:text-blue-300"
      >
        <span>{label}</span>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className="h-3 w-3"
        >
          <path
            fillRule="evenodd"
            d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z"
            clipRule="evenodd"
          />
        </svg>
      </button>
    )
  })()

  // Determine the subtitle content
  const subtitleContent = subtitle ?? branchSubtitle

  return (
    <Navbar
      title={title}
      subtitle={subtitleContent}
      centerTitle
      left={
        showBack ? (
          <NavbarBackLink
            onClick={handleBack}
            data-testid="navbar-back-button"
          />
        ) : undefined
      }
      right={rightActions}
      data-testid="konsta-navbar"
    />
  )
}
