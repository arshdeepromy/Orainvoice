import { useCallback } from 'react'
import { Button } from 'konsta/react'
import type { ComponentProps } from 'react'
import { useHaptics } from '@/hooks/useHaptics'

type KonstaButtonProps = ComponentProps<typeof Button>

export type HapticStyle = 'light' | 'medium' | 'heavy' | 'selection'

export interface HapticButtonProps extends KonstaButtonProps {
  /** Which haptic impact to trigger on press. Defaults to 'light'. */
  hapticStyle?: HapticStyle
}

/**
 * Wraps Konsta UI Button and triggers the appropriate haptic impact on press.
 *
 * Requirements: 9.1, 9.2, 9.3
 */
export default function HapticButton({
  hapticStyle = 'light',
  onClick,
  ...rest
}: HapticButtonProps) {
  const haptics = useHaptics()

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>) => {
      // Fire-and-forget — haptics should never block the click handler
      void haptics[hapticStyle]()
      onClick?.(e)
    },
    [haptics, hapticStyle, onClick],
  )

  return <Button onClick={handleClick} {...rest} />
}
