import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 24 — Tipping Module — Task 33.10
 */

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import TipPrompt from '../pages/pos/TipPrompt'

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
})

/* ------------------------------------------------------------------ */
/*  TipPrompt component tests                                         */
/* ------------------------------------------------------------------ */

describe('TipPrompt', () => {
  const defaultProps = {
    subtotal: 100,
    onConfirm: vi.fn(),
    onSkip: vi.fn(),
  }

  it('renders the tip prompt dialog', () => {
    render(<TipPrompt {...defaultProps} />)
    expect(screen.getByRole('dialog', { name: /add a tip/i })).toBeInTheDocument()
  })

  it('displays the transaction subtotal', () => {
    render(<TipPrompt {...defaultProps} />)
    expect(screen.getByTestId('tip-subtotal')).toHaveTextContent('$100.00')
  })

  it('renders preset percentage buttons (10%, 15%, 20%)', () => {
    render(<TipPrompt {...defaultProps} />)
    expect(screen.getByTestId('tip-preset-10')).toHaveTextContent('10%')
    expect(screen.getByTestId('tip-preset-15')).toHaveTextContent('15%')
    expect(screen.getByTestId('tip-preset-20')).toHaveTextContent('20%')
  })

  it('shows calculated tip amount for preset percentages', () => {
    render(<TipPrompt {...defaultProps} />)
    // 10% of $100 = $10.00
    expect(screen.getByTestId('tip-preset-10')).toHaveTextContent('$10.00')
    // 15% of $100 = $15.00
    expect(screen.getByTestId('tip-preset-15')).toHaveTextContent('$15.00')
    // 20% of $100 = $20.00
    expect(screen.getByTestId('tip-preset-20')).toHaveTextContent('$20.00')
  })

  it('selects a preset percentage and shows tip amount', async () => {
    const user = userEvent.setup()
    render(<TipPrompt {...defaultProps} />)
    await user.click(screen.getByTestId('tip-preset-15'))
    expect(screen.getByTestId('tip-amount')).toHaveTextContent('$15.00')
  })

  it('calls onConfirm with correct tip amount when preset selected', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(<TipPrompt {...defaultProps} onConfirm={onConfirm} />)
    await user.click(screen.getByTestId('tip-preset-20'))
    await user.click(screen.getByTestId('tip-confirm'))
    expect(onConfirm).toHaveBeenCalledWith(20)
  })

  it('allows custom tip amount entry', async () => {
    const user = userEvent.setup()
    render(<TipPrompt {...defaultProps} />)
    await user.click(screen.getByTestId('tip-custom-btn'))
    const input = screen.getByTestId('tip-custom-input')
    await user.type(input, '25')
    expect(screen.getByTestId('tip-amount')).toHaveTextContent('$25.00')
  })

  it('calls onConfirm with custom amount', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(<TipPrompt {...defaultProps} onConfirm={onConfirm} />)
    await user.click(screen.getByTestId('tip-custom-btn'))
    await user.type(screen.getByTestId('tip-custom-input'), '7.50')
    await user.click(screen.getByTestId('tip-confirm'))
    expect(onConfirm).toHaveBeenCalledWith(7.5)
  })

  it('calls onSkip when No Tip button is clicked', async () => {
    const user = userEvent.setup()
    const onSkip = vi.fn()
    render(<TipPrompt {...defaultProps} onSkip={onSkip} />)
    await user.click(screen.getByTestId('tip-skip'))
    expect(onSkip).toHaveBeenCalledOnce()
  })

  it('disables confirm button when no tip selected', () => {
    render(<TipPrompt {...defaultProps} />)
    expect(screen.getByTestId('tip-confirm')).toBeDisabled()
  })

  it('handles non-round subtotals correctly', async () => {
    const user = userEvent.setup()
    render(<TipPrompt subtotal={47.83} onConfirm={vi.fn()} onSkip={vi.fn()} />)
    await user.click(screen.getByTestId('tip-preset-15'))
    // 15% of 47.83 = 7.1745 → rounded to 7.17
    expect(screen.getByTestId('tip-amount')).toHaveTextContent('$7.17')
  })
})
