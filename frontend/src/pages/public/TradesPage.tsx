import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { LandingHeader, LandingFooter, DemoRequestModal } from '@/components/public'

/* ------------------------------------------------------------------ */
/*  Trade data                                                         */
/* ------------------------------------------------------------------ */

interface Trade {
  icon: string
  name: string
  status: 'available' | 'coming_soon'
  description: string
}

const TRADES: Trade[] = [
  {
    icon: '🚗',
    name: 'Automotive & Transport',
    status: 'available',
    description:
      'Full trade-specific features including vehicle database with CarJam integration, WOF and registration expiry tracking, odometer history, job cards with vehicle linking, automotive service types, and a parts and fluids catalogue. Everything a workshop, mechanic, or fleet operator needs to manage vehicles end-to-end.',
  },
  {
    icon: '📄',
    name: 'General Invoicing',
    status: 'available',
    description:
      'Core invoicing, quoting, customer management, online payments, accounting, reports, and all non-trade-specific modules are available for any business type regardless of trade. Perfect for businesses that need professional invoicing without trade-specific tools.',
  },
  {
    icon: '🔧',
    name: 'Plumbing & Gas',
    status: 'coming_soon',
    description:
      'Trade-specific features for plumbers, gasfitters, and drainlayers including compliance tracking, gas certification management, and plumbing-specific service types. Designed to meet NZ regulatory requirements for the plumbing and gasfitting trades.',
  },
  {
    icon: '⚡',
    name: 'Electrical & Mechanical',
    status: 'coming_soon',
    description:
      'Trade-specific features for electricians, solar installers, and mechanical engineers including electrical certification tracking and trade-specific service types. Built to support the compliance and documentation needs of the electrical trade.',
  },
]

/* ------------------------------------------------------------------ */
/*  TradesPage Component                                               */
/* ------------------------------------------------------------------ */

export default function TradesPage() {
  const [demoModalOpen, setDemoModalOpen] = useState(false)

  // Allow document scroll on public pages
  useEffect(() => {
    document.documentElement.classList.add('public-page')
    return () => { document.documentElement.classList.remove('public-page') }
  }, [])

  return (
    <>
      <LandingHeader />

      {/* pt-16 accounts for the fixed header height */}
      <main className="pt-16">
        {/* ============================================================ */}
        {/*  HERO SECTION                                                 */}
        {/* ============================================================ */}
        <section className="bg-gradient-to-br from-slate-900 to-indigo-900 px-4 py-20 text-white sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl text-center">
            <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl lg:text-6xl">
              Built for Every Trade
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg text-gray-300 sm:text-xl">
              OraInvoice supports multiple trade industries with specialised tools on top of a
              powerful core platform. See what's available today and what's coming next.
            </p>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  TRADE CARDS GRID                                             */}
        {/* ============================================================ */}
        <section className="bg-white px-4 py-16 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
              {TRADES.map((trade) => (
                <article
                  key={trade.name}
                  className="flex flex-col rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md"
                >
                  {/* Icon and header */}
                  <div className="mb-4 flex items-start justify-between">
                    <span className="text-4xl" aria-hidden="true">
                      {trade.icon}
                    </span>
                    {trade.status === 'available' ? (
                      <span className="inline-flex items-center rounded-full bg-green-100 px-3 py-1 text-xs font-semibold text-green-800">
                        Available
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">
                        Coming Soon
                      </span>
                    )}
                  </div>

                  {/* Trade name */}
                  <h2 className="text-xl font-bold text-gray-900">{trade.name}</h2>

                  {/* Description */}
                  <p className="mt-3 flex-1 text-sm leading-relaxed text-gray-600">
                    {trade.description}
                  </p>

                  {/* CTA button */}
                  <div className="mt-6">
                    {trade.status === 'available' ? (
                      <Link
                        to="/signup"
                        className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                      >
                        Get Started
                      </Link>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setDemoModalOpen(true)}
                        className="inline-flex items-center justify-center rounded-lg border border-gray-300 px-6 py-3 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                      >
                        Request Free Demo
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  EXPLANATORY SECTION                                          */}
        {/* ============================================================ */}
        <section className="bg-gray-50 px-4 py-16 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-3xl text-center">
            <h2 className="text-2xl font-bold text-gray-900 sm:text-3xl">
              One Platform, Every Trade
            </h2>
            <p className="mt-6 text-base leading-relaxed text-gray-600 sm:text-lg">
              OraInvoice's core invoicing, quoting, customer management, and accounting features
              work for any business type — trade-specific features add specialised tools on top.
            </p>
            <p className="mt-4 text-base leading-relaxed text-gray-600 sm:text-lg">
              Whether you run an automotive workshop, a plumbing business, or any other trade,
              OraInvoice gives you everything you need to manage your operations, get paid faster,
              and stay compliant — all from one place, 100% hosted in New Zealand.
            </p>
            <div className="mt-8">
              <Link
                to="/signup"
                className="inline-flex items-center rounded-lg bg-blue-600 px-8 py-3 text-lg font-semibold text-white shadow-lg transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2"
              >
                Get Started Free
              </Link>
            </div>
          </div>
        </section>
      </main>

      <LandingFooter />

      {/* Demo request modal */}
      <DemoRequestModal open={demoModalOpen} onClose={() => setDemoModalOpen(false)} />
    </>
  )
}
