import { useCallback } from 'react'
import { Fab } from 'konsta/react'
import type { ReactNode } from 'react'
import { useHaptics } from '@/hooks/useHaptics'

export interface KonstaFABProps {
  /** Button text, e.g. "+ New Invoice" */
  label: string
  /** Callback fired on tap (after haptic) */
  onClick: () => void
  /** Optional leading icon (ReactNode) */
  icon?: ReactNode
}

/**
 * Floating Action Button positioned bottom-right, above the Tabbar.
 *
 * Uses the primary brand colour from TenantContext CSS variables and
 * triggers a light haptic on tap via the useHaptics hook.
 *
 * Requirements: 7.1, 7.2, 7.3
 */
export default function KonstaFAB({ label, onClick, icon }: KonstaFABProps) {
  const haptics = useHaptics()

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      void haptics.light()
      onClick()
    },
    [haptics, onClick],
  )

  return (
    <div
      className="fixed right-4 z-50"
      style={{ bottom: 'calc(4rem + env(safe-area-inset-bottom, 0px) + 16px)' }}
      data-testid="konsta-fab-container"
    >
      <Fab
        component="button"
        icon={icon}
        text={label}
        onClick={handleClick}
        colors={{
          bgIos: 'bg-primary',
          bgMaterial: 'bg-primary',
          textIos: 'text-white',
          textMaterial: 'text-white',
          activeBgIos: 'active:bg-primary/80',
          activeBgMaterial: 'active:bg-primary/80',
          touchRipple: 'touch-ripple-white',
        }}
        data-testid="konsta-fab"
      />
    </div>
  )
}
