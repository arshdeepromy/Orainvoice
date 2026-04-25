import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MobileToast } from '../MobileToast'

describe('MobileToast', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders nothing when isVisible is false', () => {
    render(
      <MobileToast message="Hello" isVisible={false} onDismiss={vi.fn()} />,
    )
    expect(screen.queryByText('Hello')).not.toBeInTheDocument()
  })

  it('renders message when isVisible is true', () => {
    render(
      <MobileToast message="Saved!" isVisible={true} onDismiss={vi.fn()} variant="success" />,
    )
    expect(screen.getByText('Saved!')).toBeInTheDocument()
  })

  it('has role=alert for accessibility', () => {
    render(
      <MobileToast message="Error" isVisible={true} onDismiss={vi.fn()} variant="error" />,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('calls onDismiss when clicked', () => {
    const onDismiss = vi.fn()
    render(
      <MobileToast message="Click me" isVisible={true} onDismiss={onDismiss} />,
    )
    fireEvent.click(screen.getByRole('alert'))
    expect(onDismiss).toHaveBeenCalledOnce()
  })

  it('auto-dismisses after duration', () => {
    const onDismiss = vi.fn()
    render(
      <MobileToast message="Auto" isVisible={true} onDismiss={onDismiss} duration={2000} />,
    )
    expect(onDismiss).not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(onDismiss).toHaveBeenCalledOnce()
  })

  it('does not auto-dismiss when duration is 0', () => {
    const onDismiss = vi.fn()
    render(
      <MobileToast message="Sticky" isVisible={true} onDismiss={onDismiss} duration={0} />,
    )
    act(() => {
      vi.advanceTimersByTime(10000)
    })
    expect(onDismiss).not.toHaveBeenCalled()
  })

  it('applies success variant styles', () => {
    render(
      <MobileToast message="Done" isVisible={true} onDismiss={vi.fn()} variant="success" />,
    )
    const alert = screen.getByRole('alert')
    expect(alert.className).toContain('bg-green-600')
  })

  it('applies error variant styles', () => {
    render(
      <MobileToast message="Fail" isVisible={true} onDismiss={vi.fn()} variant="error" />,
    )
    const alert = screen.getByRole('alert')
    expect(alert.className).toContain('bg-red-600')
  })
})
