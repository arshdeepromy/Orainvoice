import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Routes, Route, useLocation } from 'react-router-dom'
import TopBar from './TopBar'
import { ShellProviders, seedSession } from '@/test/providers'
import { setAccessToken } from '@/api/client'

/**
 * TopBar unit tests (Tasks 8, 15).
 *
 * Task 15 replaced the context shims with the REAL providers, so these tests
 * mount TopBar inside the real Auth → Tenant → Module → FeatureFlag → Branch
 * tree (ShellProviders) with a seeded org_admin session, and mock `@/api/client`
 * (test/apiClientMock) so those providers resolve against deterministic backend
 * shapes. TopBar therefore renders its full feature set (search, branch chip,
 * notifications, New menu, avatar menu) against real wired state — no mocking of
 * the contexts themselves.
 */

vi.mock('@/api/client', () => import('@/test/apiClientMock'))

/** Surfaces the current router location so we can assert navigation targets. */
function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="location">{loc.pathname + loc.search}</div>
}

function renderTopBar(props?: Partial<React.ComponentProps<typeof TopBar>>) {
  const onOpenSidebar = props?.onOpenSidebar ?? vi.fn()
  render(
    <ShellProviders initialEntries={['/dashboard']}>
      <TopBar onOpenSidebar={onOpenSidebar} notificationCount={props?.notificationCount} />
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </ShellProviders>,
  )
  return { onOpenSidebar }
}

beforeEach(() => {
  localStorage.clear()
  seedSession()
})

afterEach(() => {
  localStorage.clear()
  setAccessToken(null)
})

describe('TopBar — structure & prototype visuals', () => {
  it('renders the search field with the ⌘K hint', () => {
    renderTopBar()
    expect(screen.getByText('Search customers, invoices, jobs…')).toBeInTheDocument()
    expect(screen.getByText('⌘K')).toBeInTheDocument()
  })

  it('renders the notifications, New and avatar controls', async () => {
    renderTopBar()
    expect(screen.getByRole('button', { name: 'Notifications' })).toBeInTheDocument()
    // "New" appears once the enabled modules resolve from the API.
    expect(await screen.findByRole('button', { name: 'Create new' })).toBeInTheDocument()
    // Avatar shows initials derived from the session user's name ("Preview" → "P").
    expect(screen.getByRole('button', { name: 'Account menu' })).toHaveTextContent('P')
  })
})

describe('TopBar — Task 9 hooks preserved', () => {
  it('keeps the hamburger wired to onOpenSidebar', async () => {
    const user = userEvent.setup()
    const { onOpenSidebar } = renderTopBar()
    await user.click(screen.getByRole('button', { name: 'Open navigation menu' }))
    expect(onOpenSidebar).toHaveBeenCalledTimes(1)
  })
})

describe('TopBar — search ⌘K', () => {
  it('focuses the search field on Cmd/Ctrl+K', async () => {
    const user = userEvent.setup()
    renderTopBar()
    const search = screen.getByRole('button', { name: 'Search customers, invoices, jobs' })
    expect(search).not.toHaveFocus()
    await user.keyboard('{Meta>}k{/Meta}')
    expect(search).toHaveFocus()
  })
})

describe('TopBar — New quick-actions menu', () => {
  it('opens the menu and navigates to the chosen action', async () => {
    const user = userEvent.setup()
    renderTopBar()
    await user.click(await screen.findByRole('button', { name: 'Create new' }))

    // All gated actions visible because every module is enabled in the mock.
    expect(await screen.findByRole('menuitem', { name: 'New Invoice' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'New Quote' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'New Customer' })).toBeInTheDocument()

    await user.click(screen.getByRole('menuitem', { name: 'New Invoice' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/invoices/new')
  })
})

describe('TopBar — notifications', () => {
  it('navigates to the inbox when clicked', async () => {
    const user = userEvent.setup()
    renderTopBar()
    await user.click(screen.getByRole('button', { name: 'Notifications' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/notifications/inbox')
  })

  it('announces the unread count when provided', () => {
    renderTopBar({ notificationCount: 3 })
    expect(screen.getByRole('button', { name: 'Notifications, 3 unread' })).toBeInTheDocument()
  })
})

describe('TopBar — branch chip', () => {
  it('defaults to All Branches and persists a selection to localStorage', async () => {
    const user = userEvent.setup()
    renderTopBar()

    // Chip renders once the branch_management module + branch list resolve.
    const chip = await screen.findByRole('button', { name: 'Select branch' })
    expect(chip).toHaveTextContent('All Branches')

    await user.click(chip)
    await user.click(await screen.findByRole('menuitem', { name: /Kerikeri/ }))

    // Selecting a branch writes the same key the api/client.ts interceptor reads.
    await waitFor(() => {
      expect(localStorage.getItem('selected_branch_id')).toBe('br-01')
    })
    expect(screen.getByRole('button', { name: 'Select branch' })).toHaveTextContent('Kerikeri')
  })

  it('clears the persisted selection when All Branches is chosen', async () => {
    const user = userEvent.setup()
    localStorage.setItem('selected_branch_id', 'br-02')
    renderTopBar()

    await user.click(await screen.findByRole('button', { name: 'Select branch' }))
    await user.click(await screen.findByRole('menuitem', { name: 'All Branches' }))

    await waitFor(() => {
      expect(localStorage.getItem('selected_branch_id')).toBeNull()
    })
  })
})

describe('TopBar — avatar menu', () => {
  it('opens the user menu and signs out to /login', async () => {
    const user = userEvent.setup()
    renderTopBar()

    await user.click(screen.getByRole('button', { name: 'Account menu' }))
    expect(await screen.findByRole('menuitem', { name: 'Profile' })).toBeInTheDocument()
    // org_admin session user sees the admin-only entries.
    expect(screen.getByRole('menuitem', { name: 'Settings' })).toBeInTheDocument()

    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/login')
  })
})
