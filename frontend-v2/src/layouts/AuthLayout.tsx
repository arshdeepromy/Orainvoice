import { Outlet } from 'react-router-dom'

/**
 * AuthLayout — split-screen shell for the auth pages (login, signup, password
 * reset, verify email, MFA). Real implementation (Task 12).
 *
 * Structure + styling mirror OraInvoice_Handoff/app/auth.css `.auth`:
 *
 *   .auth  → grid 1fr 1fr, min-height:100vh                 (root grid)
 *     ├── .auth-brand      ink panel + radial gradient art  (left, decorative)
 *     │     ├── .logo-row  brand lockup
 *     │     ├── .pitch     eyebrow / headline / copy / feats (margin-top:auto)
 *     │     └── .foot      status line
 *     └── .auth-form-wrap  centered, scrollable form column  (right)
 *           ├── .mobile-logo  shown only ≤900px              (this layout owns it)
 *           └── <Outlet />    the ported page form/card
 *
 * Responsive (auth.css `@media (max-width: 900px)`):
 *   • grid collapses 1fr 1fr → single column
 *   • `.auth-brand` is hidden
 *   • `.auth-head .mobile-logo` becomes visible
 * All three flip at exactly 900px via the `max-auth:` custom variant defined in
 * src/styles/tokens.css (`@media (max-width: 900px)`, INCLUSIVE of 900px — same
 * one-pixel-faithful approach as the shell's `max-mobile` 860px variant, so the
 * grid-collapse / brand-hide / mobile-logo-show never disagree by a pixel).
 *
 * Why the layout owns the mobile logo: in the prototype each page repeats the
 * `.mobile-logo` block inside its own `.auth-head`. Hoisting it here means the
 * ported auth pages (Tasks 13–14) render only their heading + form and the
 * single source-of-truth brand lockup lives in one place. It sits at the top of
 * the centered form group and is hidden >900px (where the brand panel covers
 * branding instead).
 *
 * Accessibility:
 *   • The form column is the page's primary region → wrapped in <main>.
 *   • The brand panel is supplementary promo content → <aside>; its purely
 *     decorative SVG art + status pin are marked aria-hidden so screen readers
 *     aren't read redundant iconography before reaching the form.
 *   • Page headings (<h1>) are left to the ported page (kept out of the layout
 *     so each auth page owns its own heading hierarchy).
 *
 * Tokens only — colours/spacing/radii come from the ds.css token layer
 * (bg-sb-bg / bg-accent / text-accent-fg / rounded-* / shadow-*). The two
 * radial-gradient overlays are reproduced inline from auth.css (decorative
 * brand art); their rgba values are the accent (#2F62F0) and purple (#6D5AE6)
 * brand colours at low alpha — no external image assets are referenced.
 */

/** OraInvoice document/brand glyph — shared by both logo lockups (from auth.css). */
const BRAND_MARK_PATH = 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2z'

/** Brand-panel feature bullets — copy + icons verbatim from Login.html. */
const FEATURES: { label: string; icon: string }[] = [
  { label: 'GST-ready invoices & quotes in seconds', icon: BRAND_MARK_PATH },
  {
    label: 'Job cards, time tracking & scheduling',
    icon: 'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.4-9.4a2 2 0 112.8 2.8L11.8 15H9v-2.8z',
  },
  {
    label: 'Bank feeds, reconciliation & Xero sync',
    icon: 'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z',
  },
]

export default function AuthLayout() {
  return (
    <div
      className="grid h-screen grid-cols-2 overflow-hidden bg-card text-text max-auth:h-auto max-auth:min-h-screen max-auth:grid-cols-1 max-auth:overflow-visible"
      data-testid="auth-layout"
    >
      {/* ── Brand panel (left) — ink bg + radial gradient art; hidden ≤900px ── */}
      <aside
        className="relative flex flex-col overflow-hidden bg-sb-bg px-14 py-12 text-white max-auth:hidden"
        style={{
          // Decorative brand art from auth.css `.auth-brand` (accent + purple
          // glow). aria-hidden imagery — no semantic meaning.
          backgroundImage:
            'radial-gradient(120% 90% at 12% 8%, rgba(47,98,240,.22), transparent 55%),' +
            'radial-gradient(90% 80% at 95% 100%, rgba(109,90,230,.20), transparent 50%)',
        }}
      >
        {/* Brand lockup */}
        <div className="flex items-center gap-3">
          <div className="grid h-[38px] w-[38px] place-items-center rounded-[11px] bg-accent shadow-[0_4px_14px_rgba(47,98,240,.4)]">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.2}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              className="h-[21px] w-[21px] text-white"
            >
              <path d={BRAND_MARK_PATH} />
            </svg>
          </div>
          <div className="text-[18px] font-semibold">
            <b className="font-bold">Ora</b>
            <span className="text-white/50">Invoice</span>
          </div>
        </div>

        {/* Pitch — pushed to the bottom of the panel (margin-top:auto). */}
        <div className="mt-auto">
          <div className="mono text-[11px] font-medium uppercase tracking-[0.12em] text-accent-fg">
            Workshop management · NZ
          </div>
          <h2 className="mt-[14px] max-w-[16ch] text-[34px] font-bold leading-[1.12] tracking-[-0.02em]">
            Run the whole workshop from one screen.
          </h2>
          <p className="mt-4 max-w-[42ch] text-[15px] leading-[1.6] text-white/[0.62]">
            Invoicing, job cards, bookings, inventory and GST — built for Kiwi trades and motor
            workshops.
          </p>

          <div className="mt-[34px] flex flex-col gap-[14px]">
            {FEATURES.map((feature) => (
              <div
                key={feature.label}
                className="flex items-center gap-[13px] text-[14px] text-white/[0.86]"
              >
                <span className="grid h-[30px] w-[30px] flex-shrink-0 place-items-center rounded-lg bg-white/[0.08]">
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                    className="h-4 w-4 text-accent-fg"
                  >
                    <path d={feature.icon} />
                  </svg>
                </span>
                {feature.label}
              </div>
            ))}
          </div>
        </div>

        {/* Status line */}
        <div className="mono mt-10 flex items-center gap-2 text-[11.5px] text-white/40">
          <span
            className="h-[7px] w-[7px] rounded-full bg-[#34D399] shadow-[0_0_0_3px_rgba(52,211,153,.18)]"
            aria-hidden="true"
          />
          All systems operational · node nz-akl-01
        </div>
      </aside>

      {/* ── Form column (right) — vertically centered, independently scrolls ── */}
      <main className="overflow-y-auto bg-card max-auth:overflow-visible">
        {/* `min-h-full` + justify-center keeps the form group centered when it
            fits, and lets it scroll from the top (no clipping) when tall — e.g.
            the signup wizard's `lg` card. This is the flex+overflow-safe
            centering pattern (a plain `m-auto` would clip the top of tall
            content in a scroll container). */}
        <div className="flex min-h-full flex-col items-center justify-center p-10">
          {/* Shrink-to-content group: its width tracks the widest child — the
              ported page's form card (`max-w-[400px]`, or the wider signup
              `lg` card). Centered horizontally by the parent's `items-center`.
              The mobile logo lives inside it (`self-start`) so it aligns to the
              card's LEFT edge for any card width, matching the prototype where
              `.mobile-logo` sits in the card's `.auth-head`. */}
          <div className="flex flex-col">
            {/* Mobile-only brand lockup — shown only ≤900px where the ink brand
                panel is hidden (auth.css `.auth-head .mobile-logo`). */}
            <div className="mb-[22px] hidden items-center gap-[10px] self-start max-auth:flex">
              <div className="grid h-[34px] w-[34px] flex-shrink-0 place-items-center rounded-[9px] bg-accent">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2.2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                  className="h-[18px] w-[18px] text-white"
                >
                  <path d={BRAND_MARK_PATH} />
                </svg>
              </div>
              <div className="text-[18px] font-semibold text-text">
                <b className="font-bold">Ora</b>
                <span className="text-muted-2">Invoice</span>
              </div>
            </div>

            <Outlet />
          </div>
        </div>
      </main>
    </div>
  )
}
