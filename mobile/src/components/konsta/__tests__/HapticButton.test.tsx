import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import HapticButton from '../HapticButton'

/* ------------------------------------------------------------------ */
/* Mock useHaptics                                                    */
/* ------------------------------------------------------------------ */

const mockLight = vi.fn().mockResolvedValue(undefined)
const mockMedium = vi.fn().mockResolvedValue(undefined)
const mockHeavy = vi.fn().mockResolvedValue(undefined)
const mockSelection = vi.fn().mockResolvedValue(undefined)

vi.mock('@/hooks/useHaptics', () => ({
  useHaptics: () => ({
    light: mockLight,
    medium: mockMedium,
    heavy: mockHeavy,
    selection: mockSelection,
  }),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('HapticButton', () => {
  it('renders children text', () => {
    render(<HapticButton>Save</HapticButton>)
    expect(screen.getByText('Save')).toBeInTheDocument()
  })

  it('triggers light haptic by default on click', () => {
    render(<HapticButton>Tap me</HapticButton>)
    fireEvent.click(screen.getByText('Tap me'))
    expect(mockLight).toHaveBeenCalledTimes(1)
    expect(mockMedium).not.toHaveBeenCalled()
    expect(mockHeavy).not.toHaveBeenCalled()
    expect(mockSelection).not.toHaveBeenCalled()
  })

  it('triggers medium haptic when hapticStyle="medium"', () => {
    render(<HapticButton hapticStyle="medium">Toggle</HapticButton>)
    fireEvent.click(screen.getByText('Toggle'))
    expect(mockMedium).toHaveBeenCalledTimes(1)
    expect(mockLight).not.toHaveBeenCalled()
  })

  it('triggers heavy haptic when hapticStyle="heavy"', () => {
    render(<HapticButton hapticStyle="heavy">Delete</HapticButton>)
    fireEvent.click(screen.getByText('Delete'))
    expect(mockHeavy).toHaveBeenCalledTimes(1)
    expect(mockLight).not.toHaveBeenCalled()
  })

  it('triggers selection haptic when hapticStyle="selection"', () => {
    render(<HapticButton hapticStyle="selection">Swipe</HapticButton>)
    fireEvent.click(screen.getByText('Swipe'))
    expect(mockSelection).toHaveBeenCalledTimes(1)
    expect(mockLight).not.toHaveBeenCalled()
  })

  it('calls the provided onClick handler', () => {
    const handleClick = vi.fn()
    render(<HapticButton onClick={handleClick}>Press</HapticButton>)
    fireEvent.click(screen.getByText('Press'))
    expect(handleClick).toHaveBeenCalledTimes(1)
  })

  it('triggers haptic AND onClick together', () => {
    const handleClick = vi.fn()
    render(
      <HapticButton hapticStyle="heavy" onClick={handleClick}>
        Confirm
      </HapticButton>,
    )
    fireEvent.click(screen.getByText('Confirm'))
    expect(mockHeavy).toHaveBeenCalledTimes(1)
    expect(handleClick).toHaveBeenCalledTimes(1)
  })

  it('works without an onClick handler (haptic only)', () => {
    render(<HapticButton>No handler</HapticButton>)
    // Should not throw
    fireEvent.click(screen.getByText('No handler'))
    expect(mockLight).toHaveBeenCalledTimes(1)
  })

  it('passes through Konsta Button props like disabled', () => {
    const handleClick = vi.fn()
    render(
      <HapticButton disabled onClick={handleClick}>
        Disabled
      </HapticButton>,
    )
    const btn = screen.getByText('Disabled').closest('button')
    expect(btn).toBeDisabled()
  })
})
