import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import KonstaFAB from '../KonstaFAB'

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

describe('KonstaFAB', () => {
  it('renders the label text', () => {
    render(<KonstaFAB label="+ New Invoice" onClick={vi.fn()} />)
    expect(screen.getByText('+ New Invoice')).toBeInTheDocument()
  })

  it('renders with the konsta-fab-container test id', () => {
    render(<KonstaFAB label="+ New" onClick={vi.fn()} />)
    expect(screen.getByTestId('konsta-fab-container')).toBeInTheDocument()
  })

  it('calls onClick when tapped', () => {
    const handleClick = vi.fn()
    render(<KonstaFAB label="+ New Invoice" onClick={handleClick} />)
    fireEvent.click(screen.getByTestId('konsta-fab'))
    expect(handleClick).toHaveBeenCalledTimes(1)
  })

  it('triggers light haptic on tap', () => {
    render(<KonstaFAB label="+ New Invoice" onClick={vi.fn()} />)
    fireEvent.click(screen.getByTestId('konsta-fab'))
    expect(mockLight).toHaveBeenCalledTimes(1)
    expect(mockMedium).not.toHaveBeenCalled()
    expect(mockHeavy).not.toHaveBeenCalled()
    expect(mockSelection).not.toHaveBeenCalled()
  })

  it('triggers haptic AND onClick together', () => {
    const handleClick = vi.fn()
    render(<KonstaFAB label="Create" onClick={handleClick} />)
    fireEvent.click(screen.getByTestId('konsta-fab'))
    expect(mockLight).toHaveBeenCalledTimes(1)
    expect(handleClick).toHaveBeenCalledTimes(1)
  })

  it('renders an icon when provided', () => {
    const icon = <span data-testid="fab-icon">+</span>
    render(<KonstaFAB label="Add" onClick={vi.fn()} icon={icon} />)
    expect(screen.getByTestId('fab-icon')).toBeInTheDocument()
  })

  it('is positioned fixed at bottom-right above the tabbar', () => {
    render(<KonstaFAB label="+ New" onClick={vi.fn()} />)
    const container = screen.getByTestId('konsta-fab-container')
    expect(container.className).toContain('fixed')
    expect(container.className).toContain('right-4')
    expect(container.className).toContain('z-50')
    // Bottom offset accounts for tabbar height + safe area
    const bottom = container.style.bottom
    expect(bottom).toContain('calc')
    expect(bottom).toContain('4rem')
    expect(bottom).toContain('safe-area-inset-bottom')
  })

  it('renders without an icon when none is provided', () => {
    render(<KonstaFAB label="+ New" onClick={vi.fn()} />)
    // Should render without error and show the label
    expect(screen.getByText('+ New')).toBeInTheDocument()
  })
})
