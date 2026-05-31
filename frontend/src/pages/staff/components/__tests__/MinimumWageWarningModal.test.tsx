/**
 * Unit tests for MinimumWageWarningModal.
 *
 * Refs: Staff Management Phase 1 — R4
 */

import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import MinimumWageWarningModal from '../MinimumWageWarningModal'

describe('MinimumWageWarningModal', () => {
  it('renders the threshold and proposed values', () => {
    render(
      <MinimumWageWarningModal
        threshold={23.15}
        proposed={20}
        onCancel={() => {}}
        onConfirm={() => {}}
      />
    )

    // Both values should appear in the body copy
    expect(screen.getByText(/\$20\.00/)).toBeInTheDocument()
    expect(screen.getByText(/\$23\.15/)).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: /below nz minimum wage/i })
    ).toBeInTheDocument()
  })

  it('calls onCancel when Cancel is clicked', () => {
    const onCancel = vi.fn()
    const onConfirm = vi.fn()

    render(
      <MinimumWageWarningModal
        threshold={23.15}
        proposed={20}
        onCancel={onCancel}
        onConfirm={onConfirm}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('calls onConfirm when Continue anyway is clicked', () => {
    const onCancel = vi.fn()
    const onConfirm = vi.fn()

    render(
      <MinimumWageWarningModal
        threshold={23.15}
        proposed={20}
        onCancel={onCancel}
        onConfirm={onConfirm}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /continue anyway/i }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('applies the 44px minimum touch target to both buttons (mobile-app rule)', () => {
    render(
      <MinimumWageWarningModal
        threshold={23.15}
        proposed={20}
        onCancel={() => {}}
        onConfirm={() => {}}
      />
    )

    const cancel = screen.getByRole('button', { name: /cancel/i })
    const confirm = screen.getByRole('button', { name: /continue anyway/i })

    // The Tailwind utility `min-h-[44px]` (and matching min-w) ensures
    // every interactive control meets Apple HIG / WCAG 2.5.8 — assert
    // both classes are present on each button.
    expect(cancel.className).toMatch(/min-h-\[44px\]/)
    expect(cancel.className).toMatch(/min-w-\[44px\]/)
    expect(confirm.className).toMatch(/min-h-\[44px\]/)
    expect(confirm.className).toMatch(/min-w-\[44px\]/)
  })
})
