import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import StaffList from './StaffList'

/**
 * StaffList — "Send onboarding link" checkbox + email-blocking tests (Task 10.6).
 *
 * Covers Requirements 1.1, 1.2, 1.3, 3.6:
 *  - R1.1: the Add Staff dialog renders a "Send onboarding link" checkbox.
 *  - R1.2: checking it with an empty email blocks submit with a validation
 *    message and never POSTs.
 *  - R1.3: with an email present, submit proceeds and the create payload
 *    includes `send_onboarding_link: true`.
 *  - R3.6: an `onboarding_email_sent: false` response surfaces an inline
 *    formError (the staff record is still created/preserved).
 *
 * `@/api/client` (apiClient) is mocked so the list fetch + create POST resolve
 * configurable fixtures; the two context hooks and `@/api/staff` helpers are
 * mocked so the page mounts without a provider tree.
 */

const h = vi.hoisted(() => ({
  postResult: { data: {} as Record<string, unknown> },
}))

vi.mock('@/api/client', () => {
  const get = vi.fn(async (url: string) => {
    if (url === '/staff') return { data: { staff: [], total: 0 } }
    if (url === '/staff/check-duplicate') return { data: { duplicate: false } }
    return { data: {} }
  })
  const post = vi.fn(async () => h.postResult)
  return {
    default: {
      get,
      post,
      put: vi.fn(async () => ({ data: {} })),
      delete: vi.fn(async () => ({ data: {} })),
    },
  }
})

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({ branches: [] }),
}))

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: () => true }),
}))

vi.mock('@/api/staff', () => ({
  getPendingLeaveCount: vi.fn(async () => 0),
  getStaffListKpis: vi.fn(async () => null),
}))

import apiClient from '@/api/client'

const mockPost = vi.mocked(apiClient.post)

function renderList() {
  return render(
    <MemoryRouter>
      <StaffList />
    </MemoryRouter>,
  )
}

/** Open the Add Staff modal and return its panel element for scoped queries. */
async function openAddModal(user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> {
  // The toolbar "Add Staff" button (there is a second one in the modal footer
  // once it is open, so query before opening).
  await user.click(screen.getByRole('button', { name: 'Add Staff' }))
  const heading = await screen.findByText('Add Staff Member')
  const panel = heading.closest('.rounded-card') as HTMLElement
  expect(panel).toBeTruthy()
  return panel
}

function firstNameInput(panel: HTMLElement): HTMLInputElement {
  // The first text input inside the modal is "First Name *".
  return panel.querySelector('input[type="text"]') as HTMLInputElement
}

function emailInput(panel: HTMLElement): HTMLInputElement {
  return panel.querySelector('input[type="email"]') as HTMLInputElement
}

beforeEach(() => {
  h.postResult = { data: { onboarding_email_sent: true } }
  mockPost.mockClear()
})

afterEach(() => {
  vi.clearAllTimers()
})

describe('StaffList — Send onboarding link', () => {
  it('renders the "Send onboarding link" checkbox in the Add dialog (R1.1)', async () => {
    const user = userEvent.setup()
    renderList()

    const panel = await openAddModal(user)
    const checkbox = within(panel).getByLabelText(/send onboarding link/i)
    expect(checkbox).toBeInTheDocument()
    expect(checkbox).not.toBeChecked()
  })

  it('blocks submit with a validation message when checked and email is empty (R1.2)', async () => {
    const user = userEvent.setup()
    renderList()

    const panel = await openAddModal(user)

    // First name is required for handleSave to reach the email gate.
    await user.type(firstNameInput(panel), 'Jordan')
    await user.click(within(panel).getByLabelText(/send onboarding link/i))

    await user.click(within(panel).getByRole('button', { name: 'Add Staff' }))

    expect(
      within(panel).getByText(
        /an email address is required to send an onboarding link/i,
      ),
    ).toBeInTheDocument()
    // Submission is blocked — no create POST fired.
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('submits with send_onboarding_link in the payload when an email is present (R1.3)', async () => {
    const user = userEvent.setup()
    renderList()

    const panel = await openAddModal(user)

    await user.type(firstNameInput(panel), 'Jordan')
    await user.type(emailInput(panel), 'jordan@example.com')
    await user.click(within(panel).getByLabelText(/send onboarding link/i))

    await user.click(within(panel).getByRole('button', { name: 'Add Staff' }))

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith(
        '/staff',
        expect.objectContaining({
          send_onboarding_link: true,
          email: 'jordan@example.com',
          first_name: 'Jordan',
        }),
        expect.objectContaining({ baseURL: '/api/v2' }),
      ),
    )
    // On success the modal closes.
    await waitFor(() =>
      expect(screen.queryByText('Add Staff Member')).not.toBeInTheDocument(),
    )
  })

  it('surfaces an inline error when onboarding_email_sent is false (R3.6)', async () => {
    const user = userEvent.setup()
    h.postResult = { data: { onboarding_email_sent: false } }
    renderList()

    const panel = await openAddModal(user)

    await user.type(firstNameInput(panel), 'Jordan')
    await user.type(emailInput(panel), 'jordan@example.com')
    await user.click(within(panel).getByLabelText(/send onboarding link/i))

    await user.click(within(panel).getByRole('button', { name: 'Add Staff' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    // The staff record is preserved; the dialog stays open showing the error.
    expect(
      within(panel).getByText(/the onboarding email could not be sent/i),
    ).toBeInTheDocument()
    expect(screen.getByText('Add Staff Member')).toBeInTheDocument()
  })
})
