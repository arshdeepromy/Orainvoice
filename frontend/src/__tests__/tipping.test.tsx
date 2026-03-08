import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6
 */

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut },
  }
})

vi.mock('@/contexts/TerminologyContext', () => ({
  useTerm: (_key: string, fallback: string) => fallback,
  useTerminology: () => ({ terms: {}, isLoading: false, error: null, refetch: vi.fn() }),
}))

vi.mock('@/contexts/FeatureFlagContext', () => ({
  useFlag: () => true,
  useFeatureFlags: () => ({ flags: {}, isLoading: false, error: null, refetch: vi.fn() }),
  FeatureGate: ({ children }: { children: React.ReactNode }) => children,
}))

import TipPrompt, { TipTransactionSummary } from '../pages/pos/TipPrompt'
import { distributeTips } from '../utils/tippingCalcs'

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
    expect(screen.getByTestId('tip-preset-10')).toHaveTextContent('$10.00')
    expect(screen.getByTestId('tip-preset-15')).toHaveTextContent('$15.00')
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

/* ------------------------------------------------------------------ */
/*  TipTransactionSummary tests (Req 15.5)                            */
/* ------------------------------------------------------------------ */

describe('TipTransactionSummary', () => {
  it('renders tip info when tip amount is positive', () => {
    render(
      <TipTransactionSummary
        tipInfo={{ tip_amount: 15, payment_method: 'card', staff_allocations: [] }}
      />,
    )
    expect(screen.getByTestId('tip-transaction-summary')).toBeInTheDocument()
    expect(screen.getByTestId('tip-summary-amount')).toHaveTextContent('$15.00')
  })

  it('renders nothing when tipInfo is null', () => {
    const { container } = render(<TipTransactionSummary tipInfo={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when tip amount is zero', () => {
    const { container } = render(
      <TipTransactionSummary
        tipInfo={{ tip_amount: 0, payment_method: 'card', staff_allocations: [] }}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('shows staff allocations when present', () => {
    render(
      <TipTransactionSummary
        tipInfo={{
          tip_amount: 20,
          payment_method: 'cash',
          staff_allocations: [
            { name: 'Alice', amount: 10 },
            { name: 'Bob', amount: 10 },
          ],
        }}
      />,
    )
    expect(screen.getByText(/Alice: \$10\.00/)).toBeInTheDocument()
    expect(screen.getByText(/Bob: \$10\.00/)).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  distributeTips utility tests                                       */
/* ------------------------------------------------------------------ */

describe('distributeTips', () => {
  it('distributes equally when shares are equal', () => {
    const result = distributeTips(30, [
      { id: 'a', share: 1 },
      { id: 'b', share: 1 },
      { id: 'c', share: 1 },
    ])
    expect(result).toHaveLength(3)
    expect(result.every((r) => r.amount === 10)).toBe(true)
    expect(result.reduce((s, r) => s + r.amount, 0)).toBe(30)
  })

  it('distributes proportionally by share', () => {
    const result = distributeTips(100, [
      { id: 'a', share: 60 },
      { id: 'b', share: 40 },
    ])
    expect(result.find((r) => r.id === 'a')?.amount).toBe(60)
    expect(result.find((r) => r.id === 'b')?.amount).toBe(40)
  })

  it('handles rounding correctly — total always equals input', () => {
    const result = distributeTips(10, [
      { id: 'a', share: 1 },
      { id: 'b', share: 1 },
      { id: 'c', share: 1 },
    ])
    const total = result.reduce((s, r) => s + r.amount, 0)
    expect(Math.round(total * 100) / 100).toBe(10)
  })

  it('returns empty array for zero total', () => {
    expect(distributeTips(0, [{ id: 'a', share: 1 }])).toEqual([])
  })

  it('returns empty array for empty staff', () => {
    expect(distributeTips(100, [])).toEqual([])
  })
})
