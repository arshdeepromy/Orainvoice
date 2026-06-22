import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import OnboardingFormPage from './OnboardingFormPage'

/**
 * OnboardingFormPage — public self-service onboarding form tests (Task 10.6).
 *
 * Covers Requirements 4.2, 6.4, 8.2, 8.3, 9.2, 12.1, 12.2, 12.3:
 *  - R4.2: prefill GET renders read-only first_name / email.
 *  - R6.4: KiwiSaver rate select is hidden until the "enrolled" checkbox.
 *  - R8.2: visa-expiry field appears only for work/student visa.
 *  - R8.3: a past/missing visa-expiry date blocks submission with an error.
 *  - R7.2/R7.3: the document picker rejects files > 10 MB and caps at 3.
 *  - R9.2: a 422 submit maps server errors inline without clearing inputs.
 *  - R12.1: "Save as draft" fires a PUT to /draft.
 *  - R12.2: a debounced autosave-on-blur fires a PUT (~800ms).
 *  - R12.3: resumed masked IRD/bank are NOT re-sent unless retyped.
 *
 * The page uses RAW axios (not the shared apiClient), so we `vi.mock('axios')`
 * and drive get/post/put directly.
 */

vi.mock('axios', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    // The page guards every error branch with axios.isAxiosError(...).
    isAxiosError: (e: unknown): boolean =>
      !!(e && typeof e === 'object' && (e as { isAxiosError?: boolean }).isAxiosError),
  },
}))

import axios from 'axios'

const mockGet = vi.mocked(axios.get)
const mockPost = vi.mocked(axios.post)
const mockPut = vi.mocked(axios.put)

const TOKEN = 'tok-abc-123'
const PREFILL_URL = `/api/v2/public/staff-onboarding/${TOKEN}`
const DRAFT_URL = `${PREFILL_URL}/draft`

interface PrefillOverrides {
  bank_account_required?: boolean
  draft?: Record<string, unknown> | null
  completion_percentage?: number | null
  last_saved_at?: string | null
}

function makePrefill(overrides: PrefillOverrides = {}) {
  return {
    data: {
      first_name: 'Jordan',
      email: 'jordan@example.com',
      org_name: 'Kerikeri Motors',
      tax_code_options: ['M', 'ME', 'S', 'SH', 'ST', 'SB', 'CAE', 'NSW', 'ND'],
      residency_options: [
        'citizen',
        'permanent_resident',
        'work_visa',
        'student_visa',
        'other',
      ],
      kiwisaver_rate_options: [3, 4, 6, 8, 10],
      bank_account_required: overrides.bank_account_required ?? false,
      draft: overrides.draft ?? null,
      completion_percentage: overrides.completion_percentage ?? null,
      last_saved_at: overrides.last_saved_at ?? null,
    },
  }
}

function axiosError(status: number, data: unknown) {
  return { isAxiosError: true, response: { status, data } }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/onboard/${TOKEN}`]}>
      <Routes>
        <Route path="/onboard/:token" element={<OnboardingFormPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mockGet.mockReset()
  mockPost.mockReset()
  mockPut.mockReset()
  mockGet.mockResolvedValue(makePrefill())
  mockPost.mockResolvedValue({ data: { ok: true, message: 'Thanks!' } })
  mockPut.mockResolvedValue({
    data: { ok: true, completion_percentage: 40, last_saved_at: '2026-06-15T09:30:00Z' },
  })
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('OnboardingFormPage — prefill and conditional fields', () => {
  it('renders read-only first name and email from the prefill (R4.2)', async () => {
    renderPage()

    const firstName = (await screen.findByLabelText('First name')) as HTMLInputElement
    const email = screen.getByLabelText('Email') as HTMLInputElement

    expect(firstName.value).toBe('Jordan')
    expect(firstName.readOnly).toBe(true)
    expect(email.value).toBe('jordan@example.com')
    expect(email.readOnly).toBe(true)
  })

  it('hides the KiwiSaver rate until the enrolled checkbox is ticked (R6.4)', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByLabelText('First name')
    expect(
      screen.queryByLabelText('KiwiSaver contribution rate'),
    ).not.toBeInTheDocument()

    await user.click(screen.getByLabelText(/enrolled in KiwiSaver/i))

    expect(
      screen.getByLabelText('KiwiSaver contribution rate'),
    ).toBeInTheDocument()
  })

  it('shows the visa-expiry field only for work/student visa (R8.2)', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByLabelText('First name')
    expect(screen.queryByLabelText('Visa expiry date')).not.toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Residency type'), 'work_visa')
    expect(screen.getByLabelText('Visa expiry date')).toBeInTheDocument()

    // Switching to a non-visa type hides it again.
    await user.selectOptions(screen.getByLabelText('Residency type'), 'citizen')
    expect(screen.queryByLabelText('Visa expiry date')).not.toBeInTheDocument()
  })

  it('blocks submission with an error for a past visa-expiry date (R8.3)', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByLabelText('First name')
    await user.selectOptions(screen.getByLabelText('Residency type'), 'work_visa')

    const visa = screen.getByLabelText('Visa expiry date')
    fireEvent.change(visa, { target: { value: '2000-01-01' } })

    // Attempting to submit a past/invalid visa date is a BLOCKING error.
    await user.click(screen.getByRole('button', { name: /^submit$/i }))

    expect(
      await screen.findByText(/valid visa expiry date in the future/i),
    ).toBeInTheDocument()
  })
})

describe('OnboardingFormPage — document picker constraints (R7.2, R7.3)', () => {
  it('rejects a file larger than 10 MB', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByLabelText('First name')

    const input = document.getElementById('documents') as HTMLInputElement
    const big = new File([new ArrayBuffer(11 * 1024 * 1024)], 'passport.pdf', {
      type: 'application/pdf',
    })
    await user.upload(input, big)

    expect(screen.getByText(/larger than 10 MB/i)).toBeInTheDocument()
    // Rejected file is not added to the list.
    expect(screen.queryByText('passport.pdf')).not.toBeInTheDocument()
  })

  it('caps the upload at 3 documents', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByLabelText('First name')

    const input = document.getElementById('documents') as HTMLInputElement
    const files = [1, 2, 3, 4].map(
      (n) => new File(['x'], `doc${n}.png`, { type: 'image/png' }),
    )
    await user.upload(input, files)

    expect(screen.getByText(/you can upload up to 3 documents/i)).toBeInTheDocument()
    expect(screen.getByText('doc1.png')).toBeInTheDocument()
    expect(screen.getByText('doc2.png')).toBeInTheDocument()
    expect(screen.getByText('doc3.png')).toBeInTheDocument()
    expect(screen.queryByText('doc4.png')).not.toBeInTheDocument()
  })
})

describe('OnboardingFormPage — submit error mapping (R9.2)', () => {
  it('maps a 422 response to inline field errors without clearing inputs', async () => {
    const user = userEvent.setup()
    mockPost.mockRejectedValue(
      axiosError(422, {
        ok: false,
        message: 'Please fix the highlighted fields and try again.',
        errors: {
          ird_number: { message: 'IRD number must be 8 or 9 digits.', code: 'validation_failed' },
        },
      }),
    )
    renderPage()
    await screen.findByLabelText('First name')

    const lastName = screen.getByLabelText('Last name') as HTMLInputElement
    await user.type(lastName, 'Smith')

    await user.click(screen.getByRole('button', { name: /^submit$/i }))

    // Inline per-field error + top-level message surface.
    expect(
      await screen.findByText('IRD number must be 8 or 9 digits.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Please fix the highlighted fields and try again.'),
    ).toBeInTheDocument()
    // Entered data is preserved (R9.2).
    expect(lastName.value).toBe('Smith')
  })
})

describe('OnboardingFormPage — draft save (R12.1, R12.2)', () => {
  it('fires a PUT to /draft when "Save as draft" is clicked (R12.1)', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByLabelText('First name')

    await user.type(screen.getByLabelText('Last name'), 'Smith')
    await user.click(screen.getByRole('button', { name: /save as draft/i }))

    await waitFor(() => expect(mockPut).toHaveBeenCalled())
    const [url, payload] = mockPut.mock.calls[mockPut.mock.calls.length - 1]
    expect(url).toBe(DRAFT_URL)
    expect(payload).toEqual(expect.objectContaining({ last_name: 'Smith' }))
  })

  it('fires a debounced autosave PUT on field blur after ~800ms (R12.2)', async () => {
    vi.useFakeTimers()
    renderPage()
    // Flush the mount-time prefill promise (microtask) under fake timers.
    await act(async () => {})

    const lastName = screen.getByLabelText('Last name') as HTMLInputElement
    fireEvent.change(lastName, { target: { value: 'Smith' } })
    fireEvent.blur(lastName)

    // Nothing yet — the autosave is debounced.
    expect(mockPut).not.toHaveBeenCalled()

    await act(async () => {
      vi.advanceTimersByTime(900)
    })

    expect(mockPut).toHaveBeenCalled()
    expect(mockPut.mock.calls[0][0]).toBe(DRAFT_URL)
  })
})

describe('OnboardingFormPage — masked-secret resume (R12.3)', () => {
  it('does not re-send masked IRD/bank, but sends a freshly typed value', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValue(
      makePrefill({
        draft: {
          last_name: 'Smith',
          phone: '021 111 2222',
          emergency_contact_name: null,
          emergency_contact_phone: null,
          tax_code: 'M',
          student_loan: false,
          kiwisaver_enrolled: false,
          kiwisaver_employee_rate: null,
          residency_type: 'citizen',
          visa_expiry_date: null,
          ird_number: '*****789', // masked placeholder (R11.6)
          has_ird: true,
          bank_account_number: '********7890', // masked placeholder
          has_bank: true,
          documents_staged_count: 0,
        },
        completion_percentage: 60,
        last_saved_at: '2026-06-15T09:30:00Z',
      }),
    )
    renderPage()
    await screen.findByLabelText('First name')

    // The masked values rehydrate into the fields.
    const ird = screen.getByLabelText('IRD number') as HTMLInputElement
    const bank = screen.getByLabelText(/NZ bank account number/i) as HTMLInputElement
    expect(ird.value).toBe('*****789')
    expect(bank.value).toBe('********7890')

    // Save with the masked values untouched — neither secret is re-sent.
    await user.click(screen.getByRole('button', { name: /save as draft/i }))
    await waitFor(() => expect(mockPut).toHaveBeenCalled())
    let payload = mockPut.mock.calls[mockPut.mock.calls.length - 1][1] as Record<string, unknown>
    expect(payload).not.toHaveProperty('ird_number')
    expect(payload).not.toHaveProperty('bank_account_number')

    // Retype a fresh IRD — now it IS included in the next save.
    await user.clear(ird)
    await user.type(ird, '123456789')
    await user.click(screen.getByRole('button', { name: /save as draft/i }))

    await waitFor(() => {
      payload = mockPut.mock.calls[mockPut.mock.calls.length - 1][1] as Record<string, unknown>
      expect(payload.ird_number).toBe('123456789')
    })
    // The untouched bank field is still masked, so still not re-sent.
    expect(payload).not.toHaveProperty('bank_account_number')
  })
})
