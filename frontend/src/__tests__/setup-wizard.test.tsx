import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 5.1, 5.2, 5.6, 5.8, 5.9
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import { SetupWizard } from '../pages/setup/SetupWizard'
import { StepIndicator, type StepInfo } from '../pages/setup/components/StepIndicator'
import { CountryStep } from '../pages/setup/steps/CountryStep'
import { BusinessStep } from '../pages/setup/steps/BusinessStep'
import { ReadyStep } from '../pages/setup/steps/ReadyStep'
import { INITIAL_WIZARD_DATA, type WizardData } from '../pages/setup/types'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function mockProgressResponse(steps: Record<string, boolean> = {}) {
  return {
    data: {
      org_id: 'test-org',
      steps,
      wizard_completed: false,
      completed_at: null,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    },
  }
}

/* ------------------------------------------------------------------ */
/*  SetupWizard — main container tests                                 */
/* ------------------------------------------------------------------ */

describe('SetupWizard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading spinner while fetching progress', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<SetupWizard />)
    expect(screen.getByRole('status', { name: 'Loading setup wizard' })).toBeInTheDocument()
  })

  it('renders the wizard heading and first step after loading (Req 5.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(mockProgressResponse())
    render(<SetupWizard />)
    expect(await screen.findByText('Set Up Your Business')).toBeInTheDocument()
    expect(screen.getByText(/Where is your business based/)).toBeInTheDocument()
  })

  it('shows Back, Skip, and Next buttons', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(mockProgressResponse())
    render(<SetupWizard />)
    await screen.findByText('Set Up Your Business')
    // On step 1, no Back button
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Skip' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next' })).toBeInTheDocument()
  })

  it('navigates to next step on Skip click (Req 5.6)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('trade-families')) return Promise.resolve({ data: [] })
      if (url.includes('trade-categories')) return Promise.resolve({ data: [] })
      return Promise.resolve(mockProgressResponse())
    })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { step_number: 1, completed: false, skipped: true } })
    render(<SetupWizard />)
    await screen.findByText('Set Up Your Business')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Skip' }))

    // Should now be on step 2 (Trade)
    expect(await screen.findByText(/What does your business do/)).toBeInTheDocument()
  })

  it('shows Back button on step 2+', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('trade-families')) return Promise.resolve({ data: [] })
      if (url.includes('trade-categories')) return Promise.resolve({ data: [] })
      return Promise.resolve(mockProgressResponse())
    })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { step_number: 1, completed: false, skipped: true } })
    render(<SetupWizard />)
    await screen.findByText('Set Up Your Business')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await screen.findByText(/What does your business do/)

    expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument()
  })

  it('navigates back on Back click', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('trade-families')) return Promise.resolve({ data: [] })
      if (url.includes('trade-categories')) return Promise.resolve({ data: [] })
      return Promise.resolve(mockProgressResponse())
    })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { step_number: 1, completed: false, skipped: true } })
    render(<SetupWizard />)
    await screen.findByText('Set Up Your Business')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await screen.findByText(/What does your business do/)

    await user.click(screen.getByRole('button', { name: 'Back' }))
    expect(await screen.findByText(/Where is your business based/)).toBeInTheDocument()
  })

  it('submits step data to API on Next click (Req 5.8)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(mockProgressResponse())
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { step_number: 1, completed: true, skipped: false } })
    render(<SetupWizard />)
    await screen.findByText('Set Up Your Business')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Next' }))

    expect(apiClient.post).toHaveBeenCalledWith(
      '/v2/setup-wizard/step/1',
      expect.objectContaining({ skip: false }),
    )
  })

  it('submits skip=true to API on Skip click', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(mockProgressResponse())
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { step_number: 1, completed: false, skipped: true } })
    render(<SetupWizard />)
    await screen.findByText('Set Up Your Business')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Skip' }))

    expect(apiClient.post).toHaveBeenCalledWith(
      '/v2/setup-wizard/step/1',
      expect.objectContaining({ skip: true }),
    )
  })

  it('shows error message on API failure', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(mockProgressResponse())
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<SetupWizard />)
    await screen.findByText('Set Up Your Business')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Next' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Network error')
  })
})

/* ------------------------------------------------------------------ */
/*  StepIndicator tests                                                */
/* ------------------------------------------------------------------ */

describe('StepIndicator', () => {
  const steps: StepInfo[] = [
    { label: 'Country', completed: true, skipped: false },
    { label: 'Trade', completed: false, skipped: false },
    { label: 'Business', completed: false, skipped: true },
    { label: 'Branding', completed: false, skipped: false },
  ]

  it('renders step count text', () => {
    render(<StepIndicator steps={steps} currentStep={1} />)
    expect(screen.getByText('Step 2 of 4')).toBeInTheDocument()
  })

  it('renders current step label in header', () => {
    render(<StepIndicator steps={steps} currentStep={1} />)
    const allTrade = screen.getAllByText('Trade')
    expect(allTrade.length).toBeGreaterThanOrEqual(1)
  })

  it('has accessible progressbar role', () => {
    render(<StepIndicator steps={steps} currentStep={1} />)
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '2')
    expect(bar).toHaveAttribute('aria-valuemax', '4')
  })
})

/* ------------------------------------------------------------------ */
/*  CountryStep tests                                                  */
/* ------------------------------------------------------------------ */

describe('CountryStep', () => {
  it('renders searchable country list', () => {
    const onChange = vi.fn()
    render(<CountryStep data={{ ...INITIAL_WIZARD_DATA }} onChange={onChange} />)
    expect(screen.getByLabelText('Search countries')).toBeInTheDocument()
    expect(screen.getByText('New Zealand')).toBeInTheDocument()
    expect(screen.getByText('Australia')).toBeInTheDocument()
  })

  it('filters countries by search text', async () => {
    const onChange = vi.fn()
    render(<CountryStep data={{ ...INITIAL_WIZARD_DATA }} onChange={onChange} />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Search countries'), 'united')
    expect(screen.getByText('United Kingdom')).toBeInTheDocument()
    expect(screen.getByText('United States')).toBeInTheDocument()
    expect(screen.queryByText('New Zealand')).not.toBeInTheDocument()
  })

  it('auto-fills currency/tax/date on country select (Req 5.2)', async () => {
    const onChange = vi.fn()
    render(<CountryStep data={{ ...INITIAL_WIZARD_DATA }} onChange={onChange} />)
    const user = userEvent.setup()
    await user.click(screen.getByText('New Zealand'))
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        countryCode: 'NZ',
        currency: 'NZD',
        taxLabel: 'GST',
        taxRate: 15,
        dateFormat: 'dd/MM/yyyy',
      }),
    )
  })

  it('shows auto-configured preview after selection', async () => {
    const data = { ...INITIAL_WIZARD_DATA, countryCode: 'NZ' }
    render(<CountryStep data={data} onChange={vi.fn()} />)
    expect(screen.getByText(/Auto-configured for New Zealand/)).toBeInTheDocument()
    expect(screen.getByText('Currency: NZD')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  BusinessStep validation tests                                      */
/* ------------------------------------------------------------------ */

describe('BusinessStep', () => {
  it('renders all form fields', () => {
    render(
      <BusinessStep
        data={{ ...INITIAL_WIZARD_DATA }}
        onChange={vi.fn()}
        errors={{}}
      />,
    )
    expect(screen.getByLabelText('Business name *')).toBeInTheDocument()
    expect(screen.getByLabelText('Trading name')).toBeInTheDocument()
    expect(screen.getByLabelText('Registration number')).toBeInTheDocument()
    expect(screen.getByLabelText('Phone')).toBeInTheDocument()
    expect(screen.getByLabelText('Website')).toBeInTheDocument()
  })

  it('shows validation error for business name (Req 5.9)', () => {
    render(
      <BusinessStep
        data={{ ...INITIAL_WIZARD_DATA }}
        onChange={vi.fn()}
        errors={{ businessName: 'Business name is required' }}
      />,
    )
    expect(screen.getByText('Business name is required')).toBeInTheDocument()
  })

  it('shows country-specific tax number label', () => {
    const data = { ...INITIAL_WIZARD_DATA, countryCode: 'AU', taxNumberLabel: 'ABN' }
    render(<BusinessStep data={data} onChange={vi.fn()} errors={{}} />)
    expect(screen.getByLabelText('ABN')).toBeInTheDocument()
  })

  it('validates tax number format for NZ (Req 5.10)', async () => {
    const data = {
      ...INITIAL_WIZARD_DATA,
      countryCode: 'NZ',
      taxNumberLabel: 'GST Number',
      taxNumberRegex: '^\\d{8,9}$',
      taxNumber: 'invalid',
    }
    render(<BusinessStep data={data} onChange={vi.fn()} errors={{}} />)
    expect(screen.getByText('Invalid GST Number format')).toBeInTheDocument()
  })

  it('does not show error for valid NZ tax number', () => {
    const data = {
      ...INITIAL_WIZARD_DATA,
      countryCode: 'NZ',
      taxNumberLabel: 'GST Number',
      taxNumberRegex: '^\\d{8,9}$',
      taxNumber: '123456789',
    }
    render(<BusinessStep data={data} onChange={vi.fn()} errors={{}} />)
    expect(screen.queryByText('Invalid GST Number format')).not.toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  ReadyStep tests                                                    */
/* ------------------------------------------------------------------ */

describe('ReadyStep', () => {
  it('renders summary sections with edit links', () => {
    const data = {
      ...INITIAL_WIZARD_DATA,
      countryCode: 'NZ',
      businessName: 'Test Co',
      enabledModules: ['invoicing', 'inventory'],
    }
    const onGoToStep = vi.fn()
    render(<ReadyStep data={data} onGoToStep={onGoToStep} />)

    expect(screen.getByText("You're All Set!")).toBeInTheDocument()
    expect(screen.getByText('Country & Region')).toBeInTheDocument()
    expect(screen.getByText('Business Details')).toBeInTheDocument()
    expect(screen.getByText('Test Co')).toBeInTheDocument()

    // Edit links
    const editButtons = screen.getAllByText('Edit')
    expect(editButtons.length).toBeGreaterThanOrEqual(6)
  })

  it('calls onGoToStep when edit link is clicked', async () => {
    const data = { ...INITIAL_WIZARD_DATA, countryCode: 'NZ' }
    const onGoToStep = vi.fn()
    render(<ReadyStep data={data} onGoToStep={onGoToStep} />)

    const user = userEvent.setup()
    const editButtons = screen.getAllByText('Edit')
    await user.click(editButtons[0]) // First edit link = Country (step 0)
    expect(onGoToStep).toHaveBeenCalledWith(0)
  })
})
