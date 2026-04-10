import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}))

import apiClient from '../../../api/client'
import { InlineCreateForm, type Category } from '../InlineCreateForm'

beforeEach(() => {
  vi.clearAllMocks()
})

function renderForm(category: Category, overrides?: Partial<React.ComponentProps<typeof InlineCreateForm>>) {
  const props = {
    category,
    onSuccess: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  }
  const result = render(<InlineCreateForm {...props} />)
  return { ...result, props }
}

/* ------------------------------------------------------------------ */
/*  1. Part form fields — Req 2.1                                      */
/* ------------------------------------------------------------------ */

describe('InlineCreateForm — Part fields', () => {
  it('renders name, sell price, GST mode, part number, brand, description fields', () => {
    renderForm('part')

    expect(screen.getByLabelText(/^name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/sell price per unit/i)).toBeInTheDocument()
    expect(screen.getByRole('radiogroup', { name: /gst mode/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/part number/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^brand/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/description/i)).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  2. Tyre form fields — Req 3.1                                      */
/* ------------------------------------------------------------------ */

describe('InlineCreateForm — Tyre fields', () => {
  it('renders name, sell price, GST mode, width, profile, rim dia, brand fields', () => {
    renderForm('tyre')

    expect(screen.getByLabelText(/^name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/sell price per unit/i)).toBeInTheDocument()
    expect(screen.getByRole('radiogroup', { name: /gst mode/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/width/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/profile/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/rim dia/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^brand/i)).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  3. Fluid form fields — Req 4.1                                     */
/* ------------------------------------------------------------------ */

describe('InlineCreateForm — Fluid fields', () => {
  it('renders product name, sell price, GST mode, fluid type, brand fields', () => {
    renderForm('fluid')

    expect(screen.getByLabelText(/product name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/sell price per unit/i)).toBeInTheDocument()
    expect(screen.getByRole('radiogroup', { name: /gst mode/i })).toBeInTheDocument()
    expect(screen.getByRole('radiogroup', { name: /fluid type/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/^brand/i)).toBeInTheDocument()
  })
})


/* ------------------------------------------------------------------ */
/*  4. Service form fields — Req 5.1                                   */
/* ------------------------------------------------------------------ */

describe('InlineCreateForm — Service fields', () => {
  it('renders name, default price, GST mode, description fields', () => {
    renderForm('service')

    expect(screen.getByLabelText(/^name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/default price/i)).toBeInTheDocument()
    expect(screen.getByRole('radiogroup', { name: /gst mode/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/description/i)).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  5. Cancel button — Req 8.3                                         */
/* ------------------------------------------------------------------ */

describe('InlineCreateForm — Cancel', () => {
  it('calls onCancel without making API calls', async () => {
    const user = userEvent.setup()
    const { props } = renderForm('part')

    await user.click(screen.getByRole('button', { name: /cancel/i }))

    expect(props.onCancel).toHaveBeenCalledTimes(1)
    expect(apiClient.post).not.toHaveBeenCalled()
    expect(apiClient.get).not.toHaveBeenCalled()
  })
})

/* ------------------------------------------------------------------ */
/*  6. Loading state — Req 8.4                                         */
/* ------------------------------------------------------------------ */

describe('InlineCreateForm — Loading state', () => {
  it('shows "Creating…" text and disables submit while saving', async () => {
    const user = userEvent.setup()

    // Make the API call hang so we can observe the loading state
    let resolvePost!: (value: unknown) => void
    vi.mocked(apiClient.post).mockImplementation(
      () => new Promise((resolve) => { resolvePost = resolve }),
    )

    renderForm('part')

    // Fill required fields so validation passes
    await user.type(screen.getByLabelText(/^name/i), 'Test Part')
    await user.type(screen.getByLabelText(/sell price per unit/i), '10')

    // Click submit
    const submitBtn = screen.getByRole('button', { name: /create part/i })
    await user.click(submitBtn)

    // Should now show loading state
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /creating…/i })).toBeDisabled()
    })

    // Resolve the API call to clean up
    await waitFor(() => resolvePost({ data: { part: { id: '1', name: 'Test Part' } } }))
  })
})

/* ------------------------------------------------------------------ */
/*  7. Network error — Req 10.1                                        */
/* ------------------------------------------------------------------ */

describe('InlineCreateForm — Network error', () => {
  it('shows generic connection error message for network failures', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockRejectedValue(new Error('Network Error'))

    renderForm('part')

    await user.type(screen.getByLabelText(/^name/i), 'Test Part')
    await user.type(screen.getByLabelText(/sell price per unit/i), '10')
    await user.click(screen.getByRole('button', { name: /create part/i }))

    await waitFor(() => {
      expect(
        screen.getByText('Failed to create part. Please check your connection and try again.'),
      ).toBeInTheDocument()
    })
  })

  it('uses correct category label in network error message for fluid', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockRejectedValue(new Error('Network Error'))

    renderForm('fluid')

    await user.type(screen.getByLabelText(/product name/i), 'Test Fluid')
    await user.type(screen.getByLabelText(/sell price per unit/i), '10')
    await user.click(screen.getByRole('button', { name: /create fluid/i }))

    await waitFor(() => {
      expect(
        screen.getByText('Failed to create fluid/oil. Please check your connection and try again.'),
      ).toBeInTheDocument()
    })
  })
})

/* ------------------------------------------------------------------ */
/*  8. Validation error (400/422) — Req 10.2                           */
/* ------------------------------------------------------------------ */

describe('InlineCreateForm — Validation error', () => {
  it('displays the specific API detail string for 400/422 errors', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockRejectedValue({
      response: { status: 400, data: { detail: 'Part with this name already exists' } },
    })

    renderForm('part')

    await user.type(screen.getByLabelText(/^name/i), 'Duplicate Part')
    await user.type(screen.getByLabelText(/sell price per unit/i), '10')
    await user.click(screen.getByRole('button', { name: /create part/i }))

    await waitFor(() => {
      expect(screen.getByText('Part with this name already exists')).toBeInTheDocument()
    })
  })
})

/* ------------------------------------------------------------------ */
/*  9. Banner text — Req 8.1                                           */
/* ------------------------------------------------------------------ */

describe('InlineCreateForm — Banner text', () => {
  it.each([
    ['part', 'Part'],
    ['tyre', 'Tyre'],
    ['fluid', 'Fluid/Oil'],
    ['service', 'Service'],
  ] as const)('shows "Quick-create a new %s catalogue item" for %s category', (category, label) => {
    renderForm(category)
    expect(
      screen.getByText(`Quick-create a new ${label} catalogue item`),
    ).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  10. Helper text — Req 8.2                                          */
/* ------------------------------------------------------------------ */

describe('InlineCreateForm — Helper text', () => {
  it('shows the catalogue entry helper message', () => {
    renderForm('part')
    expect(
      screen.getByText(/this creates a catalogue entry/i),
    ).toBeInTheDocument()
  })
})
