import { useState, useEffect } from 'react'

const CONSENT_KEY = 'portal_cookie_consent'

type ConsentValue = 'accepted' | 'declined'

export function CookieConsent() {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const stored = localStorage.getItem(CONSENT_KEY)
    if (stored !== 'accepted' && stored !== 'declined') {
      setVisible(true)
    }
  }, [])

  const handleConsent = (value: ConsentValue) => {
    localStorage.setItem(CONSENT_KEY, value)
    setVisible(false)
  }

  if (!visible) return null

  return (
    <div
      role="dialog"
      aria-label="Cookie consent"
      className="fixed inset-x-0 bottom-0 z-50 border-t border-border bg-card px-4 py-4 shadow-pop sm:px-6"
    >
      <div className="mx-auto flex max-w-4xl flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-text">
          This portal uses cookies to maintain your session. We may also use analytics cookies to
          improve the experience. You can accept all cookies or decline non-essential ones.
        </p>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => handleConsent('declined')}
            className="min-h-[44px] rounded-ctl border border-border bg-card px-4 py-2 text-sm font-medium text-text shadow-card hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2"
          >
            Decline
          </button>
          <button
            type="button"
            onClick={() => handleConsent('accepted')}
            className="min-h-[44px] rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white shadow-card hover:bg-accent-press focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2"
          >
            Accept
          </button>
        </div>
      </div>
    </div>
  )
}
