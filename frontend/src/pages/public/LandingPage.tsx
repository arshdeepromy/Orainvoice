import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { LandingHeader, LandingFooter, DemoRequestModal } from '@/components/public'

/* ------------------------------------------------------------------ */
/*  Feature data — 8 categories with all features from Requirement 4.4 */
/* ------------------------------------------------------------------ */

interface Feature {
  icon: string
  name: string
  description: string
  comingSoon?: boolean
}

interface FeatureCategory {
  title: string
  features: Feature[]
}

const FEATURE_CATEGORIES: FeatureCategory[] = [
  {
    title: 'Core',
    features: [
      {
        icon: '📄',
        name: 'Invoicing',
        description:
          'Create, send, and track professional invoices with automated reminders and online payment links.',
      },
      {
        icon: '👥',
        name: 'Customer Management',
        description:
          'Maintain a complete customer database with contact details, vehicle history, and communication logs.',
      },
      {
        icon: '🔔',
        name: 'Notifications',
        description:
          'Automated email and SMS notifications for invoices, appointments, and overdue payments.',
      },
    ],
  },
  {
    title: 'Automotive-Specific',
    features: [
      {
        icon: '🚗',
        name: 'Vehicle Database (CarJam)',
        description:
          'Integrated vehicle lookup via CarJam — pull registration, make, model, VIN, WOF, and rego expiry instantly.',
      },
      {
        icon: '🔧',
        name: 'Job Cards',
        description:
          'Track every job from check-in to completion with parts, labour, notes, and vehicle linking.',
      },
      {
        icon: '⚙️',
        name: 'Service Types',
        description:
          'Define and manage automotive service types — WOF checks, full services, brake jobs, and more.',
      },
    ],
  },
  {
    title: 'Sales & Quoting',
    features: [
      {
        icon: '💰',
        name: 'Quotes and Estimates',
        description:
          'Build detailed quotes with line items, discounts, and one-click conversion to invoices.',
      },
      {
        icon: '📅',
        name: 'Bookings and Appointments',
        description:
          'Let customers book online and manage your workshop calendar with drag-and-drop scheduling.',
      },
    ],
  },
  {
    title: 'Operations',
    features: [
      {
        icon: '🗓️',
        name: 'Scheduling',
        description:
          'Visual scheduling board for staff and bays — see who is working on what, when.',
      },
      {
        icon: '👷',
        name: 'Staff Management',
        description:
          'Manage staff profiles, roles, permissions, and branch assignments from one place.',
      },
      {
        icon: '⏱️',
        name: 'Time Tracking',
        description:
          'Clock in/out, track hours per job, and generate timesheets for payroll.',
      },
    ],
  },
  {
    title: 'Inventory',
    features: [
      {
        icon: '📦',
        name: 'Inventory and Products',
        description:
          'Track stock levels, set reorder points, and manage products across branches.',
      },
      {
        icon: '🛒',
        name: 'Purchase Orders',
        description:
          'Create and send purchase orders to suppliers, track deliveries, and reconcile stock.',
      },
      {
        icon: '📋',
        name: 'Items Catalogue',
        description:
          'Maintain a master catalogue of parts, fluids, and consumables with pricing and supplier info.',
      },
    ],
  },
  {
    title: 'Finance',
    features: [
      {
        icon: '🔁',
        name: 'Recurring Invoices',
        description:
          'Set up automatic recurring invoices for fleet contracts and regular service agreements.',
      },
      {
        icon: '💱',
        name: 'Multi-Currency',
        description:
          'Support for multiple currencies with automatic exchange rate conversion.',
      },
      {
        icon: '💳',
        name: 'Online Payments',
        description:
          'Accept payments via Stripe — customers pay directly from their invoice link.',
      },
      {
        icon: '📊',
        name: 'Accounting',
        description:
          'Built-in accounting with Xero integration, chart of accounts, and bank reconciliation.',
      },
      {
        icon: '🧾',
        name: 'Expenses',
        description:
          'Track business expenses, attach receipts, and categorise for tax reporting.',
      },
    ],
  },
  {
    title: 'Compliance',
    features: [
      {
        icon: '📑',
        name: 'Compliance Documents',
        description:
          'Store and manage compliance documents — certifications, licences, and safety records.',
      },
      {
        icon: '📈',
        name: 'Reports',
        description:
          'Revenue, expenses, job profitability, staff utilisation, and custom report builder.',
      },
    ],
  },
  {
    title: 'Additional',
    features: [
      {
        icon: '📤',
        name: 'Data Import/Export',
        description:
          'Import existing data from CSV and export anything for backup or migration.',
      },
      {
        icon: '🌐',
        name: 'Customer Portal',
        description:
          'Give customers a self-service portal to view invoices, pay online, and book appointments.',
        comingSoon: true,
      },
      {
        icon: '📱',
        name: 'Mobile App',
        description:
          'Full-featured mobile companion app for field staff — create invoices, track time, and manage jobs on the go.',
        comingSoon: true,
      },
      {
        icon: '🏢',
        name: 'Multi-Branch',
        description:
          'Manage multiple workshop locations from a single account with branch-level reporting.',
      },
      {
        icon: '🔒',
        name: 'MFA Security',
        description:
          'Multi-factor authentication with TOTP, SMS, passkeys, and backup codes to keep your account secure.',
      },
    ],
  },
]

/* ------------------------------------------------------------------ */
/*  Pricing features checklist                                         */
/* ------------------------------------------------------------------ */

const PRICING_FEATURES: { label: string; comingSoon?: boolean }[] = [
  { label: 'Unlimited invoices & quotes' },
  { label: 'Job cards with vehicle linking' },
  { label: 'CarJam vehicle database' },
  { label: 'Customer management & portal', comingSoon: true },
  { label: 'Bookings & scheduling' },
  { label: 'Staff management & time tracking' },
  { label: 'Inventory & purchase orders' },
  { label: 'Recurring invoices' },
  { label: 'Online payments (Stripe)' },
  { label: 'Xero accounting integration' },
  { label: 'Compliance document storage' },
  { label: 'Reports & analytics' },
  { label: 'Mobile app access', comingSoon: true },
  { label: 'Multi-branch support' },
  { label: 'MFA security' },
  { label: 'Data import/export' },
]

/* ------------------------------------------------------------------ */
/*  Testimonials — placeholder data                                    */
/* ------------------------------------------------------------------ */

// TODO: Replace these placeholder testimonials with real customer testimonials
const TESTIMONIALS = [
  {
    quote:
      'OraInvoice transformed how we run our workshop. Job cards, invoicing, and scheduling all in one place — it just works.',
    name: 'James T.',
    business: 'JT Automotive',
  },
  {
    quote:
      'The CarJam integration alone saves us hours every week. Pull up any vehicle instantly and link it to a job card.',
    name: 'Sarah M.',
    business: 'Kiwi Motors',
  },
  {
    quote:
      'Finally, a system built for NZ workshops. The fact that all our data stays in New Zealand gives us real peace of mind.',
    name: 'Dave R.',
    business: 'Reliable Auto Services',
  },
]

/* ------------------------------------------------------------------ */
/*  LandingPage Component                                              */
/* ------------------------------------------------------------------ */

export default function LandingPage() {
  const [demoModalOpen, setDemoModalOpen] = useState(false)

  // Enable smooth scrolling and allow document scroll on public pages
  useEffect(() => {
    document.documentElement.classList.add('public-page')
    document.documentElement.style.scrollBehavior = 'smooth'
    return () => {
      document.documentElement.classList.remove('public-page')
      document.documentElement.style.scrollBehavior = ''
    }
  }, [])

  return (
    <>
      <LandingHeader />

      {/* pt-16 accounts for the fixed header height */}
      <main className="pt-16">
        {/* ============================================================ */}
        {/*  HERO SECTION                                                 */}
        {/* ============================================================ */}
        <section className="bg-gradient-to-br from-slate-900 to-indigo-900 px-4 py-20 text-white sm:px-6 lg:px-8 lg:py-32">
          <div className="mx-auto max-w-7xl text-center">
            <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl lg:text-6xl">
              Built for Automotive Businesses
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg text-gray-300 sm:text-xl">
              Invoicing, job management, and business operations — purpose-built for workshops,
              mechanics, and trade businesses across New Zealand.
            </p>

            {/* CTA buttons */}
            <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <Link
                to="/signup"
                className="inline-flex items-center rounded-lg bg-blue-600 px-8 py-3 text-lg font-semibold text-white shadow-lg transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900"
              >
                Get Started
              </Link>
              <button
                type="button"
                onClick={() => setDemoModalOpen(true)}
                className="inline-flex items-center rounded-lg border-2 border-white/30 px-8 py-3 text-lg font-semibold text-white transition-colors hover:border-white hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900"
              >
                Request Free Demo
              </button>
            </div>

            {/* 100% NZ Hosted badge */}
            <div className="mt-8 inline-flex items-center gap-2 rounded-full bg-white/10 px-5 py-2 text-sm font-medium text-white backdrop-blur-sm">
              <span aria-hidden="true">🇳🇿</span>
              <span>100% NZ Hosted — Your data never leaves New Zealand</span>
            </div>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  FEATURE SECTIONS                                             */}
        {/* ============================================================ */}
        <div id="features">
          {FEATURE_CATEGORIES.map((category, categoryIndex) => (
            <section
              key={category.title}
              className={`px-4 py-16 sm:px-6 lg:px-8 ${
                categoryIndex % 2 === 0 ? 'bg-white' : 'bg-gray-50'
              }`}
            >
              <div className="mx-auto max-w-7xl">
                <h2 className="mb-10 text-center text-3xl font-bold text-gray-900">
                  {category.title}
                </h2>
                <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
                  {category.features.map((feature) => (
                    <div
                      key={feature.name}
                      className="relative rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md"
                    >
                      {feature.comingSoon && (
                        <span className="absolute right-4 top-4 inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">
                          Coming Soon
                        </span>
                      )}
                      <div className="mb-3 text-3xl" aria-hidden="true">
                        {feature.icon}
                      </div>
                      <h3 className="text-lg font-semibold text-gray-900">{feature.name}</h3>
                      <p className="mt-2 text-sm leading-relaxed text-gray-600">
                        {feature.description}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          ))}
        </div>

        {/* ============================================================ */}
        {/*  PRICING SECTION                                              */}
        {/* ============================================================ */}
        <section id="pricing" className="bg-white px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl text-center">
            <h2 className="text-3xl font-bold text-gray-900 sm:text-4xl">
              Simple, Transparent Pricing
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-gray-600">
              Everything your workshop needs in one plan. No hidden fees, no per-user charges.
            </p>

            {/* Pricing card */}
            <div className="mx-auto mt-12 max-w-md rounded-2xl border-2 border-blue-600 bg-white p-8 shadow-xl">
              <h3 className="text-2xl font-bold text-gray-900">Mech Pro Plan</h3>
              <div className="mt-4">
                {/* Price: $60 NZD/month excl. GST — matches the Mech Pro Plan in subscription_plans */}
                <span className="text-5xl font-extrabold text-gray-900">$60</span>
                <span className="text-lg text-gray-500">/month</span>
              </div>
              <p className="mt-2 text-sm text-gray-500">NZD, excluding GST</p>

              {/* Feature checklist */}
              <ul className="mt-8 space-y-3 text-left">
                {PRICING_FEATURES.map((feature) => (
                  <li key={feature.label} className="flex items-start gap-3">
                    <svg
                      className="mt-0.5 h-5 w-5 flex-shrink-0 text-blue-600"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      aria-hidden="true"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                    <span className="text-sm text-gray-700">{feature.label}</span>
                    {feature.comingSoon && (
                      <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                        Coming Soon
                      </span>
                    )}
                  </li>
                ))}
              </ul>

              {/* CTA buttons */}
              <div className="mt-8 flex flex-col gap-3">
                <Link
                  to="/signup"
                  className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-6 py-3 text-base font-semibold text-white shadow transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                >
                  Start Free Trial
                </Link>
                <button
                  type="button"
                  onClick={() => setDemoModalOpen(true)}
                  className="inline-flex items-center justify-center rounded-lg border border-gray-300 px-6 py-3 text-base font-semibold text-gray-700 transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                >
                  Request Free Demo
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  TESTIMONIALS SECTION                                         */}
        {/* ============================================================ */}
        {/* TODO: Replace placeholder testimonials with real customer testimonials */}
        <section className="bg-gray-50 px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <h2 className="mb-12 text-center text-3xl font-bold text-gray-900">
              Trusted by NZ Workshops
            </h2>
            <div className="grid grid-cols-1 gap-8 md:grid-cols-3">
              {TESTIMONIALS.map((testimonial) => (
                <div
                  key={testimonial.name}
                  className="rounded-xl bg-white p-6 shadow-sm"
                >
                  {/* Quotation mark */}
                  <svg
                    className="mb-4 h-8 w-8 text-blue-600/30"
                    fill="currentColor"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path d="M14.017 21v-7.391c0-5.704 3.731-9.57 8.983-10.609l.995 2.151c-2.432.917-3.995 3.638-3.995 5.849h4v10H14.017zM0 21v-7.391c0-5.704 3.748-9.57 9-10.609l.996 2.151C7.563 6.068 6 8.789 6 11h4v10H0z" />
                  </svg>
                  <blockquote className="text-sm leading-relaxed text-gray-700">
                    &ldquo;{testimonial.quote}&rdquo;
                  </blockquote>
                  <div className="mt-4 border-t border-gray-100 pt-4">
                    <p className="text-sm font-semibold text-gray-900">{testimonial.name}</p>
                    <p className="text-xs text-gray-500">{testimonial.business}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  CTA SECTION                                                  */}
        {/* ============================================================ */}
        <section className="bg-gradient-to-br from-slate-900 to-indigo-900 px-4 py-20 text-white sm:px-6 lg:px-8">
          <div className="mx-auto max-w-3xl text-center">
            <h2 className="text-3xl font-bold sm:text-4xl">
              Ready to streamline your workshop?
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-lg text-gray-300">
              Join New Zealand workshops already using OraInvoice to manage their business. Start
              your free trial today — no credit card required.
            </p>
            <div className="mt-8">
              <Link
                to="/signup"
                className="inline-flex items-center rounded-lg bg-blue-600 px-8 py-3 text-lg font-semibold text-white shadow-lg transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900"
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
