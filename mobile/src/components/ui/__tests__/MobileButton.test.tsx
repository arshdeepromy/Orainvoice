import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MobileButton } from '../MobileButton'

describe('MobileButton', () => {
  it('renders children text', () => {
    render(<MobileButton>Click me</MobileButton>)
    expect(screen.getByRole('button', { name: 'Click me' })).toBeInTheDocument()
  })

  it('has min-h-[44px] for touch target', () => {
    render(<MobileButton>Tap</MobileButton>)
    const btn = screen.getByRole('button')
    expect(btn.className).toContain('min-h-[44px]')
  })

  it('applies primary variant styles by default', () => {
    render(<MobileButton>Primary</MobileButton>)
    const btn = screen.getByRole('button')
    expect(btn.className).toContain('bg-blue-600')
  })

  it('applies danger variant styles', () => {
    render(<MobileButton variant="danger">Delete</MobileButton>)
    const btn = screen.getByRole('button')
    expect(btn.className).toContain('bg-red-600')
  })

  it('applies ghost variant styles', () => {
    render(<MobileButton variant="ghost">Ghost</MobileButton>)
    const btn = screen.getByRole('button')
    expect(btn.className).toContain('bg-transparent')
  })

  it('shows loading spinner and disables button when isLoading', () => {
    render(<MobileButton isLoading>Loading</MobileButton>)
    const btn = screen.getByRole('button')
    expect(btn).toBeDisabled()
    expect(btn.getAttribute('aria-busy')).toBe('true')
    // Should have the spinner SVG
    expect(btn.querySelector('svg.animate-spin')).toBeTruthy()
  })

  it('is disabled when disabled prop is true', () => {
    render(<MobileButton disabled>Disabled</MobileButton>)
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('calls onClick handler', () => {
    const onClick = vi.fn()
    render(<MobileButton onClick={onClick}>Click</MobileButton>)
    fireEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('applies fullWidth class', () => {
    render(<MobileButton fullWidth>Full</MobileButton>)
    expect(screen.getByRole('button').className).toContain('w-full')
  })
})
