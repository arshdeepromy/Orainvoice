import { Link } from 'react-router-dom'
import { Page, Block, Card, Button } from 'konsta/react'

/**
 * LandingScreen — Mobile-optimized marketing landing page.
 *
 * Displays a hero gradient with headline and CTA buttons (Sign Up, Login),
 * feature cards in a vertical stack layout, a pricing card, and a footer.
 *
 * This is a public page rendered without the app shell (no navbar, no tabbar).
 *
 * Requirements: 15.1, 15.2, 15.3
 */

// ---------------------------------------------------------------------------
// Feature data
// ---------------------------------------------------------------------------

interface Feature {
  icon: React.ReactNode
  title: string
  description: string
}

const FEATURES: Feature[] = [
  {
    icon: <InvoiceIcon />,
    title: 'Professional Invoicing',
    description:
      'Create and send polished invoices in seconds. Track payments, send reminders, and get paid faster.',
  },
  {
    icon: <JobIcon />,
    title: 'Job Management',
    description:
      'Manage job cards, track time with live timers, and convert completed jobs to invoices automatically.',
  },
  {
    icon: <CustomerIcon />,
    title: 'Customer Management',
    description:
      'Keep all your customer details, invoices, and vehicle history in one place.',
  },
  {
    icon: <QuoteIcon />,
    title: 'Quotes & Estimates',
    description:
      'Send professional quotes and convert accepted ones to invoices with a single tap.',
  },
  {
    icon: <InventoryIcon />,
    title: 'Inventory Tracking',
    description:
      'Track stock levels, set reorder alerts, and add parts directly to invoices and job cards.',
  },
  {
    icon: <ReportIcon />,
    title: 'Reports & Insights',
    description:
      'Monitor revenue, outstanding receivables, and business performance with real-time dashboards.',
  },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function LandingScreen() {
  return (
    <Page className="bg-white dark:bg-gray-900">
      {/* Hero gradient section */}
      <div className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-14 pt-16 text-center">
        <div className="mx-auto mb-4 flex h-20 w-20 items-center justify-center rounded-2xl bg-white/10 backdrop-blur-sm">
          <OraInvoiceLogo />
        </div>
        <h1 className="text-3xl font-bold text-white">OraInvoice</h1>
        <p className="mx-auto mt-3 max-w-xs text-base text-indigo-200">
          The all-in-one invoicing and business management platform built for
          trade businesses.
        </p>

        {/* CTA buttons */}
        <div className="mt-8 flex flex-col gap-3 px-2">
          <Link to="/signup" className="block">
            <Button large className="w-full">
              Sign Up Free
            </Button>
          </Link>
          <Link to="/login" className="block">
            <Button large outline className="w-full !border-white/30 !text-white">
              Login
            </Button>
          </Link>
        </div>
      </div>

      {/* Feature cards section */}
      <Block className="-mt-6 rounded-t-2xl bg-white pt-8 dark:bg-gray-900">
        <h2 className="mb-6 text-center text-xl font-bold text-gray-900 dark:text-white">
          Everything you need to run your trade business
        </h2>

        <div className="space-y-4">
          {FEATURES.map((feature) => (
            <Card key={feature.title} className="!m-0">
              <div className="flex gap-4 p-4">
                <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-xl bg-indigo-50 dark:bg-indigo-900/30">
                  {feature.icon}
                </div>
                <div className="flex-1">
                  <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                    {feature.title}
                  </h3>
                  <p className="mt-1 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
                    {feature.description}
                  </p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </Block>

      {/* Pricing card */}
      <Block className="bg-white dark:bg-gray-900">
        <h2 className="mb-4 text-center text-xl font-bold text-gray-900 dark:text-white">
          Simple, transparent pricing
        </h2>

        <Card className="!m-0 overflow-hidden">
          <div className="bg-gradient-to-br from-indigo-600 to-blue-600 p-6 text-center text-white">
            <p className="text-sm font-medium uppercase tracking-wide text-indigo-200">
              Mech Pro Plan
            </p>
            <div className="mt-2 flex items-baseline justify-center gap-1">
              <span className="text-4xl font-bold">$60</span>
              <span className="text-lg text-indigo-200">NZD/mo</span>
            </div>
            <p className="mt-1 text-sm text-indigo-200">excl. GST</p>
          </div>

          <div className="p-5">
            <ul className="space-y-3">
              <PricingFeature text="Unlimited invoices and quotes" />
              <PricingFeature text="Job cards with live timers" />
              <PricingFeature text="Customer and vehicle management" />
              <PricingFeature text="Inventory and stock tracking" />
              <PricingFeature text="Stripe payment integration" />
              <PricingFeature text="Multi-branch support" />
              <PricingFeature text="Staff roles and permissions" />
              <PricingFeature text="Reports and dashboards" />
            </ul>

            <div className="mt-6">
              <Link to="/signup" className="block">
                <Button large className="w-full">
                  Get Started
                </Button>
              </Link>
            </div>
          </div>
        </Card>
      </Block>

      {/* Footer */}
      <Block className="bg-white pb-12 dark:bg-gray-900">
        <div className="border-t border-gray-200 pt-6 text-center dark:border-gray-700">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 dark:bg-indigo-900/30">
            <OraInvoiceLogoSmall />
          </div>
          <p className="text-sm font-medium text-gray-900 dark:text-white">
            OraInvoice
          </p>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            Built for trade businesses in New Zealand
          </p>
          <div className="mt-4 flex justify-center gap-6">
            <Link
              to="/login"
              className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400"
            >
              Login
            </Link>
            <Link
              to="/signup"
              className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400"
            >
              Sign Up
            </Link>
          </div>
          <p className="mt-6 text-xs text-gray-400 dark:text-gray-500">
            © {new Date().getFullYear()} OraInvoice. All rights reserved.
          </p>
        </div>
      </Block>
    </Page>
  )
}

// ---------------------------------------------------------------------------
// Pricing feature list item
// ---------------------------------------------------------------------------

function PricingFeature({ text }: { text: string }) {
  return (
    <li className="flex items-start gap-3">
      <svg
        className="mt-0.5 h-5 w-5 flex-shrink-0 text-green-500"
        viewBox="0 0 20 20"
        fill="currentColor"
        aria-hidden="true"
      >
        <path
          fillRule="evenodd"
          d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
          clipRule="evenodd"
        />
      </svg>
      <span className="text-sm text-gray-700 dark:text-gray-300">{text}</span>
    </li>
  )
}

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------

function OraInvoiceLogo() {
  return (
    <svg
      className="h-10 w-10 text-white"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  )
}

function OraInvoiceLogoSmall() {
  return (
    <svg
      className="h-5 w-5 text-indigo-600 dark:text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  )
}

function InvoiceIcon() {
  return (
    <svg
      className="h-6 w-6 text-indigo-600 dark:text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  )
}

function JobIcon() {
  return (
    <svg
      className="h-6 w-6 text-indigo-600 dark:text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
      <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
    </svg>
  )
}

function CustomerIcon() {
  return (
    <svg
      className="h-6 w-6 text-indigo-600 dark:text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  )
}

function QuoteIcon() {
  return (
    <svg
      className="h-6 w-6 text-indigo-600 dark:text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
    </svg>
  )
}

function InventoryIcon() {
  return (
    <svg
      className="h-6 w-6 text-indigo-600 dark:text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
      <line x1="12" y1="22.08" x2="12" y2="12" />
    </svg>
  )
}

function ReportIcon() {
  return (
    <svg
      className="h-6 w-6 text-indigo-600 dark:text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  )
}
