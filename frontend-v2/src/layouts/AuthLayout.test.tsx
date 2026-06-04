import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import AuthLayout from './AuthLayout'

/**
 * Task 12 — AuthLayout split-screen shell.
 *
 * jsdom does not evaluate CSS media queries, so the *visual* collapse at ≤900px
 * (brand panel hidden, grid → single column, mobile logo shown) lives in the
 * `max-auth:` variants / tokens.css and is verified by the production build, not
 * here. These tests cover the structure that's breakpoint-agnostic: the brand
 * panel + its marketing copy render, the form region is a proper <main>
 * landmark, and the routed page (<Outlet />) renders inside it.
 */
function renderAuth(page = <div>Login form</div>) {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route element={<AuthLayout />}>
          <Route path="/login" element={page} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('AuthLayout', () => {
  it('renders the brand panel with marketing copy', () => {
    renderAuth()
    expect(
      screen.getByRole('heading', { name: /run the whole workshop from one screen/i }),
    ).toBeInTheDocument()
    expect(screen.getByText(/workshop management · nz/i)).toBeInTheDocument()
    expect(screen.getByText(/gst-ready invoices & quotes in seconds/i)).toBeInTheDocument()
  })

  it('renders the routed page inside the <main> form region', () => {
    renderAuth(<div>Login form</div>)
    const main = screen.getByRole('main')
    expect(within(main).getByText('Login form')).toBeInTheDocument()
  })

  it('exposes the brand panel as a complementary <aside> landmark', () => {
    const { container } = renderAuth()
    const aside = container.querySelector('aside')
    expect(aside).not.toBeNull()
    // The brand panel is the supplementary promo region (form lives in <main>).
    expect(within(aside as HTMLElement).getByText(/^Ora/)).toBeInTheDocument()
  })

  it('marks the decorative status pin/SVG art as aria-hidden', () => {
    const { container } = renderAuth()
    // All brand-panel SVGs + the status pin are decorative.
    container.querySelectorAll('aside svg').forEach((svg) => {
      expect(svg).toHaveAttribute('aria-hidden', 'true')
    })
  })
})
