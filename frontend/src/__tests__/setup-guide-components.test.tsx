import { render, screen, within } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

/**
 * Validates: Requirements 6.2, 6.3, 6.8, 7.1, 7.2, 9.1
 */

import QuestionCard from '../pages/setup-guide/QuestionCard'
import SummaryScreen from '../pages/setup-guide/SummaryScreen'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function makeQuestion(overrides: Partial<{
  slug: string
  display_name: string
  setup_question: string
  setup_question_description: string | null
  category: string
  dependencies: string[]
}> = {}) {
  return {
    slug: 'quotes',
    display_name: 'Quotes',
    setup_question: 'Will you be sending quotes to your customers?',
    setup_question_description: 'Create professional quotes and convert them into invoices.',
    category: 'Sales',
    dependencies: [],
    ...overrides,
  }
}

/* ------------------------------------------------------------------ */
/*  QuestionCard tests                                                 */
/* ------------------------------------------------------------------ */

describe('QuestionCard', () => {
  const defaultProps = {
    question: makeQuestion(),
    currentIndex: 0,
    totalQuestions: 5,
    selectedAnswer: null,
    onAnswer: vi.fn(),
    onBack: vi.fn(),
    dependencyWarning: null,
  }

  it('renders setup_question text as heading (Req 6.2)', () => {
    render(<QuestionCard {...defaultProps} />)
    expect(
      screen.getByRole('heading', { name: 'Will you be sending quotes to your customers?' }),
    ).toBeInTheDocument()
  })

  it('shows setup_question_description when non-null (Req 6.3)', () => {
    render(<QuestionCard {...defaultProps} />)
    expect(
      screen.getByText('Create professional quotes and convert them into invoices.'),
    ).toBeInTheDocument()
  })

  it('hides description when setup_question_description is null (Req 6.3)', () => {
    const question = makeQuestion({ setup_question_description: null })
    render(<QuestionCard {...defaultProps} question={question} />)
    expect(
      screen.queryByText('Create professional quotes and convert them into invoices.'),
    ).not.toBeInTheDocument()
  })

  it('shows "Question X of Y" with correct values (Req 6.8)', () => {
    render(<QuestionCard {...defaultProps} currentIndex={2} totalQuestions={7} />)
    expect(screen.getByText('Question 3 of 7')).toBeInTheDocument()
  })

  it('shows dependency warning when dependencyWarning is non-null (Req 9.1)', () => {
    render(
      <QuestionCard
        {...defaultProps}
        dependencyWarning="This module requires Jobs, which you chose to skip."
      />,
    )
    expect(
      screen.getByText('This module requires Jobs, which you chose to skip.'),
    ).toBeInTheDocument()
  })

  it('hides dependency warning when dependencyWarning is null (Req 9.1)', () => {
    render(<QuestionCard {...defaultProps} dependencyWarning={null} />)
    // The amber warning container should not be present
    expect(
      screen.queryByText(/This module requires/),
    ).not.toBeInTheDocument()
  })

  it('renders a progressbar with correct aria values (Req 6.8)', () => {
    render(<QuestionCard {...defaultProps} currentIndex={3} totalQuestions={10} />)
    const progressbar = screen.getByRole('progressbar')
    expect(progressbar).toHaveAttribute('aria-valuenow', '4')
    expect(progressbar).toHaveAttribute('aria-valuemax', '10')
  })
})

/* ------------------------------------------------------------------ */
/*  SummaryScreen tests                                                */
/* ------------------------------------------------------------------ */

describe('SummaryScreen', () => {
  const salesQuestions = [
    makeQuestion({ slug: 'quotes', display_name: 'Quotes', category: 'Sales' }),
    makeQuestion({ slug: 'jobs', display_name: 'Jobs', category: 'Operations', setup_question: 'Do you manage jobs?' }),
    makeQuestion({ slug: 'inventory', display_name: 'Inventory', category: 'Operations', setup_question: 'Do you track stock?' }),
    makeQuestion({ slug: 'recurring', display_name: 'Recurring Invoices', category: 'Sales', setup_question: 'Do you send recurring invoices?' }),
  ]

  const answers: Record<string, boolean> = {
    quotes: true,
    jobs: false,
    inventory: true,
    recurring: false,
  }

  const defaultProps = {
    questions: salesQuestions,
    answers,
    autoEnabled: [] as string[],
    onConfirm: vi.fn(),
    onGoBack: vi.fn(),
    isSubmitting: false,
    error: null,
  }

  it('lists every module with correct enabled/skipped status (Req 7.1)', () => {
    render(<SummaryScreen {...defaultProps} />)

    // All module names should appear
    expect(screen.getByText('Quotes')).toBeInTheDocument()
    expect(screen.getByText('Jobs')).toBeInTheDocument()
    expect(screen.getByText('Inventory')).toBeInTheDocument()
    expect(screen.getByText('Recurring Invoices')).toBeInTheDocument()

    // Check sr-only status text for each module
    const listItems = screen.getAllByRole('listitem')
    const quotesItem = listItems.find((li) => within(li).queryByText('Quotes'))!
    expect(within(quotesItem).getByText(/Enabled/)).toBeInTheDocument()

    const jobsItem = listItems.find((li) => within(li).queryByText('Jobs'))!
    expect(within(jobsItem).getByText(/Skipped/)).toBeInTheDocument()

    const inventoryItem = listItems.find((li) => within(li).queryByText('Inventory'))!
    expect(within(inventoryItem).getByText(/Enabled/)).toBeInTheDocument()

    const recurringItem = listItems.find((li) => within(li).queryByText('Recurring Invoices'))!
    expect(within(recurringItem).getByText(/Skipped/)).toBeInTheDocument()
  })

  it('groups modules by category with category headings (Req 7.2)', () => {
    render(<SummaryScreen {...defaultProps} />)

    // Category headings should appear
    expect(screen.getByText('Sales')).toBeInTheDocument()
    expect(screen.getByText('Operations')).toBeInTheDocument()

    // Verify grouping: Sales heading should come before its modules
    const salesHeading = screen.getByText('Sales')
    const operationsHeading = screen.getByText('Operations')
    expect(salesHeading).toBeInTheDocument()
    expect(operationsHeading).toBeInTheDocument()
  })

  it('shows enabled count and skipped count in summary text (Req 7.1)', () => {
    render(<SummaryScreen {...defaultProps} />)
    // 2 enabled (quotes, inventory), 2 skipped (jobs, recurring)
    expect(screen.getByText(/2 modules enabled/)).toBeInTheDocument()
    expect(screen.getByText(/2 skipped/)).toBeInTheDocument()
  })
})
