/**
 * EmployeePortalLogin — branded login page (Task 14.5).
 *
 * Covers:
 *   • Branding render: org name + logo from a 200 `/e/api/branding/{slug}`.
 *   • Neutral "portal unavailable" page on a 404 — no login form, no
 *     existence leak (R8.3).
 *   • `noindex` robots meta injected on the page (R8.7).
 *
 * The page uses RAW `axios` (not the shared `apiClient`), so we mock the
 * `axios` module's default export with `get`/`post` spies plus a working
 * `isAxiosError` so the component's error branches fire.
 *
 * _Requirements: 8.3, 8.7, 13.2_
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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

import EmployeePortalLogin from '../EmployeePortalLogin'

function renderLogin(slug = 'acme-motors') {
  return render(
    <MemoryRouter initialEntries={[`/e/${slug}`]}>
      <Routes>
        <Route path="/e/:slug" element={<EmployeePortalLogin />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  // Remove any meta tags usePageMeta added so tests stay isolated.
  document.head
    .querySelectorAll('meta[name="robots"], meta[name="googlebot"]')
    .forEach((el) => el.remove())
})

describe('EmployeePortalLogin — branding', () => {
  it('renders the org name and logo from a 200 branding response', async () => {
    axiosGet.mockResolvedValue({
      data: {
        org_name: 'Acme Motors',
        logo_url: 'https://cdn.example.test/acme.png',
        primary_colour: '#0055aa',
        secondary_colour: '#112233',
      },
    })

    renderLogin()

    // Branded heading + logo + footer derived from the org name.
    expect(await screen.findByText('Sign in to Acme Motors')).toBeInTheDocument()
    const logo = screen.getByAltText('Acme Motors logo') as HTMLImageElement
    expect(logo.src).toBe('https://cdn.example.test/acme.png')
    expect(screen.getByText('Acme Motors staff portal')).toBeInTheDocument()

    // The login form is usable.
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })
})

describe('EmployeePortalLogin — neutral unavailable page on 404', () => {
  it('renders the neutral dead-end and NO login form when branding 404s', async () => {
    axiosGet.mockRejectedValue({
      response: { status: 404, data: { code: 'portal_unavailable' } },
    })

    renderLogin('does-not-exist')

    expect(await screen.findByText('This portal is unavailable')).toBeInTheDocument()
    // No existence leak / no form: the email + password inputs are absent.
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument()
  })
})

describe('EmployeePortalLogin — noindex meta (R8.7)', () => {
  it('injects <meta name="robots" content="noindex, nofollow"> on the page', async () => {
    axiosGet.mockResolvedValue({
      data: { org_name: 'Acme Motors', logo_url: null, primary_colour: null, secondary_colour: null },
    })

    renderLogin()
    await screen.findByText('Sign in to Acme Motors')

    await waitFor(() => {
      const robots = document.head.querySelector('meta[name="robots"]')
      expect(robots).not.toBeNull()
      expect(robots?.getAttribute('content')).toBe('noindex, nofollow')
    })
  })

  it('keeps the page noindex even on the neutral unavailable page', async () => {
    axiosGet.mockRejectedValue({ response: { status: 404, data: {} } })

    renderLogin('nope')
    await screen.findByText('This portal is unavailable')

    await waitFor(() => {
      const robots = document.head.querySelector('meta[name="robots"]')
      expect(robots?.getAttribute('content')).toBe('noindex, nofollow')
    })
  })
})
