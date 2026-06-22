/**
 * EmployeePortalApp — authenticated profile view (Task 14.5).
 *
 * Covers (R7.7):
 *   • Masked-PII rendering: the server returns already-masked IRD / bank
 *     account values and the profile view displays them verbatim (the portal
 *     never receives unmasked PII).
 *   • `not_linked` handling: a `409 not_linked` from `/e/api/profile` renders
 *     the "Account not yet linked" empty state rather than an error or a crash.
 *
 * The shell uses RAW `axios` with cookie auth, so we mock the `axios` module's
 * default export with a URL-dispatching `get` plus a working `isAxiosError`.
 *
 * _Requirements: 7.7_
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const { axiosGet, axiosPost } = vi.hoisted(() => ({
  axiosGet: vi.fn(),
  axiosPost: vi.fn(),
}))

vi.mock('axios', () => {
  const isAxiosError = (e: unknown): boolean =>
    !!(e && typeof e === 'object' && 'response' in (e as Record<string, unknown>))
  const mock = { get: axiosGet, post: axiosPost, isAxiosError }
  return { default: mock, ...mock }
})

import EmployeePortalApp from '../EmployeePortalApp'

const ME = {
  portal_user_id: 'pu-1',
  email: 'staff@acme.test',
  first_name: 'Sam',
  staff_id: 'staff-1',
  org_name: 'Acme Motors',
  branding: null,
}

function renderApp() {
  // A subpath is required so RR v7 matches the splat app route — the bare
  // `/e/:slug` login route outscores `/e/:slug/*` for the exact login path
  // (see App.tsx route ordering).
  return render(
    <MemoryRouter initialEntries={['/e/acme-motors/home']}>
      <Routes>
        <Route path="/e/:slug/*" element={<EmployeePortalApp />} />
        <Route path="/e/:slug" element={<div>branded login</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('EmployeePortalApp — masked PII', () => {
  it('renders the server-masked IRD and bank account values verbatim', async () => {
    axiosGet.mockImplementation((url: string) => {
      if (url.endsWith('/auth/me')) return Promise.resolve({ data: ME })
      if (url.endsWith('/profile'))
        return Promise.resolve({
          data: {
            staff_id: 'staff-1',
            first_name: 'Sam',
            last_name: 'Rivera',
            name: 'Sam Rivera',
            email: 'staff@acme.test',
            phone: '021 555 0100',
            position: 'Technician',
            employee_id: 'EMP-014',
            employment_basis: 'Full-time',
            employment_type: 'Permanent',
            working_arrangement: 'On-site',
            employment_start_date: '2024-02-01',
            tax_code: 'M',
            kiwisaver_enrolled: true,
            ird_number: '••• ••• 789',
            bank_account_number: '••-•••• ••••567-00',
            emergency_contact_name: 'Jordan Rivera',
            emergency_contact_phone: '021 555 0199',
          },
        })
      return Promise.reject(new Error(`unexpected ${url}`))
    })

    renderApp()

    // Identity / employment fields render.
    expect(await screen.findByText('Sam Rivera')).toBeInTheDocument()
    expect(screen.getByText('Technician')).toBeInTheDocument()

    // The masked PII strings are displayed exactly as the server returned them.
    expect(screen.getByText('••• ••• 789')).toBeInTheDocument()
    expect(screen.getByText('••-•••• ••••567-00')).toBeInTheDocument()
  })
})

describe('EmployeePortalApp — not_linked profile', () => {
  it('renders the "Account not yet linked" empty state on a 409 not_linked', async () => {
    axiosGet.mockImplementation((url: string) => {
      if (url.endsWith('/auth/me')) return Promise.resolve({ data: ME })
      if (url.endsWith('/profile'))
        return Promise.reject({ response: { status: 409, data: { code: 'not_linked' } } })
      return Promise.reject(new Error(`unexpected ${url}`))
    })

    renderApp()

    expect(await screen.findByText('Account not yet linked')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Your account is not yet linked to a staff record. Please contact your organisation administrator.',
      ),
    ).toBeInTheDocument()
  })
})
