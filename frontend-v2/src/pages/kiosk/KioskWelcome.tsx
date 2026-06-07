/* ── Types ── */

interface KioskWelcomeProps {
  onCheckIn: () => void
}

/* ── KioskWelcome ──
 * Design: the "WELCOME" screen in OraInvoice_Handoff/app/Kiosk.html. Org
 * branding now lives in the persistent KioskBrand header, so this screen is
 * purely presentational — its only behaviour is the "Check in" action. */

export function KioskWelcome({ onCheckIn }: KioskWelcomeProps) {
  return (
    <div className="k-card">
      <div className="k-ico" style={{ background: 'var(--accent-soft)' }}>
        <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth={1.8}>
          <path d="M5 11l1.5-4.5A2 2 0 018.4 5h7.2a2 2 0 011.9 1.5L19 11m-14 0h14m-14 0a2 2 0 00-2 2v3a1 1 0 001 1h1m12-4a2 2 0 012 2v3a1 1 0 01-1 1h-1M7 17h10M7 17a1 1 0 11-2 0 1 1 0 012 0zm12 0a1 1 0 11-2 0 1 1 0 012 0z" />
        </svg>
      </div>
      <h1>Welcome in</h1>
      <p className="lead">
        Check in for your appointment and we&apos;ll let your technician know you&apos;ve arrived.
      </p>
      <button
        type="button"
        className="btn-kiosk primary"
        style={{ marginTop: '30px' }}
        onClick={onCheckIn}
      >
        Check in
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      </button>
    </div>
  )
}

export default KioskWelcome
