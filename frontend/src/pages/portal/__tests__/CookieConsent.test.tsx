import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CookieConsent } from '../CookieConsent'

const CONSENT_KEY = 'portal_cookie_consent'

describe('CookieConsent', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('shows the banner when no consent is stored', () => {
    render(<CookieConsent />)
    expect(screen.getByRole('dialog', { name: /cookie consent/i })).toBeInTheDocument()
    expect(screen.getByText(/this portal uses cookies/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /decline/i })).toBeInTheDocument()
  })

  it('hides the banner when consent is already accepted', () => {
    localStorage.setItem(CONSENT_KEY, 'accepted')
    render(<CookieConsent />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('hides the banner when consent is already declined', () => {
    localStorage.setItem(CONSENT_KEY, 'declined')
    render(<CookieConsent />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('stores "accepted" and dismisses banner on Accept click', () => {
    render(<CookieConsent />)
    fireEvent.click(screen.getByRole('button', { name: /accept/i }))
    expect(localStorage.getItem(CONSENT_KEY)).toBe('accepted')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('stores "declined" and dismisses banner on Decline click', () => {
    render(<CookieConsent />)
    fireEvent.click(screen.getByRole('button', { name: /decline/i }))
    expect(localStorage.getItem(CONSENT_KEY)).toBe('declined')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('does not show banner for invalid stored values', () => {
    localStorage.setItem(CONSENT_KEY, 'accepted')
    const { unmount } = render(<CookieConsent />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    unmount()

    // An unrecognised value should show the banner
    localStorage.setItem(CONSENT_KEY, 'maybe')
    render(<CookieConsent />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
