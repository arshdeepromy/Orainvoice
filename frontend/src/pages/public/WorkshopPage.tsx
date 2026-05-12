import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { LandingHeader, LandingFooter, DemoRequestModal } from '@/components/public'
import { usePageMeta } from '@/hooks/usePageMeta'

/* ------------------------------------------------------------------ */
/*  SEO: structured data                                               */
/*                                                                     */
/*  Emits three JSON-LD entities in one <script> tag:                  */
/*                                                                     */
/*    1. SoftwareApplication — identifies OraInvoice as workshop       */
/*       management software, with NZD pricing, NZ audience, and the   */
/*       full feature list that backs up the on-page H3 headings.      */
/*                                                                     */
/*    2. FAQPage — mirrors the FAQ block rendered further down the     */
/*       page. The Q/A text MUST stay in sync with the visible copy    */
/*       or Google will flag a schema/content mismatch in GSC →        */
/*       Enhancements.                                                 */
/*                                                                     */
/*    3. BreadcrumbList — Home → Workshop Software, so Google can      */
/*       render a breadcrumb trail in the SERP result.                 */
/*                                                                     */
/*  We deliberately DO NOT emit AggregateRating with placeholder data  */
/*  (rating: 5 / reviewCount: 3) — that is a spam policy violation.    */
/*  Once we have >= 10 real reviews with customer names, replace the   */
/*  `AGGREGATE_RATING_PLACEHOLDER` constant below with real values.    */
/* ------------------------------------------------------------------ */

// TODO: populate with real numbers once >= 10 verified reviews exist.
//       Until then we leave this OFF the page to avoid Google flagging
//       the structured data as spam.
const AGGREGATE_RATING_PLACEHOLDER = null as null | {
  ratingValue: string
  reviewCount: string
}

/* ------------------------------------------------------------------ */
/*  FAQ content — single source of truth for both the visible         */
/*  accordion and the FAQPage JSON-LD.                                */
/* ------------------------------------------------------------------ */

interface FaqItem {
  q: string
  a: string
}

const FAQS: FaqItem[] = [
  {
    q: 'What is workshop management software?',
    a:
      'Workshop management software is an all-in-one system that replaces paper job cards, spreadsheets, and separate invoicing apps with a single platform. It tracks customers and their vehicles, manages bookings and job cards, handles parts and labour, produces invoices, takes payments, and sends service reminders. OraInvoice adds NZ-specific tools that generic workshop software does not have — CarJam vehicle lookup, WOF and COF expiry tracking, NZ GST, and Xero integration.',
  },
  {
    q: 'How does the CarJam integration work?',
    a:
      'Type a New Zealand registration plate into any vehicle field and OraInvoice fetches the make, model, year, VIN, engine, fuel type, current WOF expiry, registration expiry, and odometer history from CarJam in about two seconds. Workshops that were retyping rego data into three different forms can stop doing that. Your CarJam API key lives in Global Admin → Integrations (encrypted at rest) and each lookup is logged against the vehicle record.',
  },
  {
    q: 'Can I import my customer list from Excel or my current system?',
    a:
      'Yes. OraInvoice has a data import tool that takes CSV files for customers, vehicles, items, and historical invoices. We also have an existing import path from the most common NZ workshop systems. If you are coming from paper job cards, we will help you get the last 12 months of customer and vehicle data into the system during onboarding.',
  },
  {
    q: 'Does it work on mobile and tablet?',
    a:
      'Yes. The full web app is responsive and works on any device with a browser — phone, tablet, or desktop. We also ship a mobile companion app for field staff with camera-based compliance document upload, time tracking, and job management. Mechanics on the workshop floor typically use a tablet mounted on the bay; owners and field staff use the phone app.',
  },
  {
    q: 'Can I send WOF and COF reminders by SMS?',
    a:
      'Yes. OraInvoice tracks WOF expiry (light vehicles, every 6 or 12 months) and COF expiry (heavy vehicles, every 6 months) on every vehicle record. You can schedule automated SMS and email reminders to go out 30, 14, or 7 days before expiry — or on any custom schedule — and we log every reminder sent against the vehicle so you can see who has been contacted and when.',
  },
  {
    q: 'Do you integrate with Xero?',
    a:
      'Yes. OraInvoice has a two-way Xero integration with webhooks — invoices, payments, customers and chart of accounts sync automatically. If you already use Xero you can keep Xero as your single source of truth for accounting, while OraInvoice runs the workshop floor. Setup takes about five minutes: authorise OraInvoice in Xero, map your chart of accounts, and the sync starts.',
  },
  {
    q: 'Is it secure? Where is my data stored?',
    a:
      'OraInvoice is 100% hosted in New Zealand. Your workshop data, customer records, invoices, and vehicle history never leave the country. We use encryption at rest for sensitive fields, Postgres row-level security for multi-tenant isolation, and mandatory multi-factor authentication options (TOTP, SMS, passkeys, backup codes). We run nightly backups to a geographically separate NZ datacentre.',
  },
  {
    q: 'Does it work for a one-person workshop as well as a 10-bay shop?',
    a:
      'Yes — OraInvoice has a single Mech Pro plan at $60 NZD per month (excluding GST) that includes all features with no per-user charges. A one-person workshop uses the same system as a 10-bay multi-branch shop; the larger shop just creates more users and branches. There is no per-seat fee, no per-SMS fee on top of your plan, and no charge for extra features as you grow.',
  },
]

/* ------------------------------------------------------------------ */
/*  Feature cards — 11 workshop-focused features                      */
/* ------------------------------------------------------------------ */

interface WorkshopFeature {
  icon: string
  title: string
  description: string
  nzBadge?: boolean
}

const WORKSHOP_FEATURES: WorkshopFeature[] = [
  {
    icon: '🚗',
    title: 'CarJam vehicle lookup',
    description:
      'Type a NZ rego, get make, model, year, VIN, WOF expiry, registration expiry, and odometer history in two seconds. No more manual data entry.',
    nzBadge: true,
  },
  {
    icon: '📅',
    title: 'WOF & COF expiry tracking',
    description:
      'Every vehicle record tracks WOF (light) and COF (heavy) expiry dates. Automated reminders go out by SMS and email before each vehicle comes due.',
    nzBadge: true,
  },
  {
    icon: '🗂️',
    title: 'Job cards & bookings',
    description:
      'Create job cards from bookings with one click. Track parts, labour, notes, photos, and status from check-in to completion.',
  },
  {
    icon: '🧾',
    title: 'Invoicing & online payments',
    description:
      'Generate GST-compliant invoices from completed job cards. Accept Stripe online payments and EFTPOS — customers can pay from a link sent by SMS.',
  },
  {
    icon: '🔩',
    title: 'Parts & labour catalogue',
    description:
      'Maintain a master catalogue of parts, fluids, consumables, and labour codes with pricing and supplier info. Drop items into a job card without retyping.',
  },
  {
    icon: '👥',
    title: 'Customer & vehicle history',
    description:
      'Every customer record shows their full vehicle list and service history — what was done, when, by whom, and how much. Perfect for repeat services.',
  },
  {
    icon: '📲',
    title: 'SMS & email service reminders',
    description:
      'Schedule automatic service reminders for WOF, COF, annual services, or any custom interval. Customers book back in without you lifting a finger.',
  },
  {
    icon: '🖥️',
    title: 'Kiosk check-in',
    description:
      'Put a tablet at reception and let customers self-check-in by rego. The kiosk pre-fills their details and creates a booking — hands-free intake during the Monday morning rush.',
  },
  {
    icon: '📱',
    title: 'Mobile app for field work',
    description:
      'Field staff and mobile mechanics manage bookings, job cards, photos, and time tracking from their phone. Works offline and syncs when you are back on wifi.',
  },
  {
    icon: '🔗',
    title: 'Xero integration',
    description:
      'Two-way sync with Xero for invoices, payments, customers, and chart of accounts. Keep Xero as your accounting source of truth while OraInvoice runs the floor.',
  },
  {
    icon: '🏢',
    title: 'Multi-branch support',
    description:
      'Run multiple workshop locations from one account. Branch-level reporting, stock transfers between bays, and consolidated revenue for the group.',
  },
]

/* ------------------------------------------------------------------ */
/*  Made for NZ — trust signals specific to the NZ market             */
/* ------------------------------------------------------------------ */

interface NzAdvantage {
  icon: string
  title: string
  description: string
}

const NZ_ADVANTAGES: NzAdvantage[] = [
  {
    icon: '🇳🇿',
    title: '100% NZ hosted',
    description:
      'Your workshop data, customer records, and invoices are stored on NZ servers and never leave the country. Data sovereignty is built in, not bolted on.',
  },
  {
    icon: '💰',
    title: 'NZ GST built in',
    description:
      '15% GST applied automatically, GST-compliant invoice templates, and GST period reporting for your IRD return. No accountant reconfig needed.',
  },
  {
    icon: '🔍',
    title: 'CarJam integration',
    description:
      'The only NZ vehicle database that matters. Rego to VIN in seconds, with WOF, rego, and odometer history. Not a generic VIN decoder.',
  },
  {
    icon: '📋',
    title: 'WOF & COF workflow',
    description:
      'Warrant of Fitness and Certificate of Fitness expiry tracking is a first-class feature, not an afterthought. Every vehicle knows when it is next due.',
  },
  {
    icon: '💵',
    title: 'NZD pricing, no FX surprises',
    description:
      'One flat rate in New Zealand dollars. No AUD/USD conversion, no exchange rate drift, and no hidden “extra user” fees creeping up your subscription.',
  },
]

/* ------------------------------------------------------------------ */
/*  Why mechanics switch — pain-points framed without naming names    */
/* ------------------------------------------------------------------ */

interface SwitchReason {
  pain: string
  solution: string
}

const SWITCH_REASONS: SwitchReason[] = [
  {
    pain: 'Sick of retyping rego numbers into three different systems?',
    solution:
      'One CarJam lookup populates the customer, vehicle, and job card at once. Two seconds, not two minutes.',
  },
  {
    pain: 'Losing customers because nobody remembers to send WOF reminders?',
    solution:
      'Automated SMS and email reminders go out on your schedule. Repeat business on autopilot.',
  },
  {
    pain: 'Paying in AUD or USD and watching the bill creep up every month?',
    solution:
      '$60 NZD flat. No per-user fees, no SMS surcharges, no FX drift. Pay in your own currency.',
  },
  {
    pain: 'Your data sitting in a US or AU datacentre with no NZ sovereignty?',
    solution:
      'We run on NZ infrastructure. Your customer list, vehicle history, and invoices stay onshore.',
  },
  {
    pain: 'Stuck with workshop software that ignores COF and heavy vehicles?',
    solution:
      'COF expiry is a first-class field on every vehicle, alongside WOF. Built for NZ workshops that service utes, trucks, and light commercial.',
  },
  {
    pain: 'Accounting mess because your workshop system does not talk to Xero?',
    solution:
      'Two-way Xero sync with webhooks. Invoices, payments, and customers flow both ways without double entry.',
  },
]

/* ------------------------------------------------------------------ */
/*  Pricing feature checklist (dedupes with LandingPage)              */
/* ------------------------------------------------------------------ */

const WORKSHOP_PRICING_FEATURES: string[] = [
  'Unlimited invoices, quotes & job cards',
  'CarJam vehicle lookup (NZ only)',
  'WOF & COF expiry tracking with SMS/email reminders',
  'Bookings, scheduling & kiosk check-in',
  'Parts & labour catalogue',
  'Customer & vehicle service history',
  'Stripe online payments & EFTPOS',
  'Xero two-way integration',
  'NZ GST-compliant invoicing',
  'Multi-branch support',
  'Mobile app for field work',
  'All data hosted 100% in New Zealand',
]

/* ------------------------------------------------------------------ */
/*  Placeholder testimonials — replace with real quotes before launch */
/*  NOTE: these do NOT emit Review schema until they are real, to     */
/*        avoid Google spam policy issues.                             */
/* ------------------------------------------------------------------ */

const WORKSHOP_TESTIMONIALS = [
  {
    quote:
      'We used to lose an hour a day just keying in rego numbers. CarJam lookup paid for the subscription in the first week.',
    name: 'Workshop Owner', // TODO: real name
    business: 'Auckland Workshop (placeholder)',
  },
  {
    quote:
      'WOF reminders used to be a sticky note on the fridge. Now they go out automatically and our diary fills itself.',
    name: 'Service Manager', // TODO: real name
    business: 'Wellington Service Centre (placeholder)',
  },
  {
    quote:
      'The Xero sync and NZ GST handling means our accountant stopped charging us for fixing invoices. That alone covers the plan.',
    name: 'Owner-Operator', // TODO: real name
    business: 'Canterbury Auto (placeholder)',
  },
]

/* ------------------------------------------------------------------ */
/*  Build the JSON-LD block                                            */
/* ------------------------------------------------------------------ */

function buildJsonLd(): object[] {
  const softwareApplication: Record<string, unknown> = {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: 'OraInvoice Workshop Software',
    alternateName: 'OraInvoice for NZ Mechanics',
    applicationCategory: 'BusinessApplication',
    applicationSubCategory: 'Workshop Management Software',
    operatingSystem: 'Web, iOS, Android',
    url: 'https://one.oraflows.co.nz/workshop',
    description:
      'Workshop management software for NZ mechanics — CarJam vehicle lookup, WOF and COF expiry tracking, job cards, invoicing, Xero integration, NZ-hosted.',
    inLanguage: 'en-NZ',
    audience: {
      '@type': 'BusinessAudience',
      audienceType: 'Auto workshops, mechanics, and service centres in New Zealand',
      geographicArea: { '@type': 'Country', name: 'New Zealand' },
    },
    provider: {
      '@type': 'Organization',
      name: 'Oraflows Limited',
      url: 'https://one.oraflows.co.nz/',
    },
    offers: {
      '@type': 'Offer',
      name: 'Mech Pro Plan',
      price: '60',
      priceCurrency: 'NZD',
      priceSpecification: {
        '@type': 'UnitPriceSpecification',
        price: '60',
        priceCurrency: 'NZD',
        unitText: 'month',
        valueAddedTaxIncluded: false,
      },
      category: 'Subscription',
      availability: 'https://schema.org/InStock',
    },
    featureList: WORKSHOP_FEATURES.map((f) => f.title),
  }

  if (AGGREGATE_RATING_PLACEHOLDER) {
    softwareApplication['aggregateRating'] = {
      '@type': 'AggregateRating',
      ratingValue: AGGREGATE_RATING_PLACEHOLDER.ratingValue,
      reviewCount: AGGREGATE_RATING_PLACEHOLDER.reviewCount,
      bestRating: '5',
      worstRating: '1',
    }
  }

  const faqPage = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: FAQS.map((f) => ({
      '@type': 'Question',
      name: f.q,
      acceptedAnswer: {
        '@type': 'Answer',
        text: f.a,
      },
    })),
  }

  const breadcrumb = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      {
        '@type': 'ListItem',
        position: 1,
        name: 'Home',
        item: 'https://one.oraflows.co.nz/',
      },
      {
        '@type': 'ListItem',
        position: 2,
        name: 'Workshop Software',
        item: 'https://one.oraflows.co.nz/workshop',
      },
    ],
  }

  return [softwareApplication, faqPage, breadcrumb]
}

/* ------------------------------------------------------------------ */
/*  WorkshopPage Component                                             */
/* ------------------------------------------------------------------ */

export default function WorkshopPage() {
  const [demoModalOpen, setDemoModalOpen] = useState(false)
  const [openFaqIndex, setOpenFaqIndex] = useState<number | null>(0)

  usePageMeta({
    title: 'Workshop Software for NZ Mechanics | OraInvoice',
    description:
      'Workshop software for NZ mechanics, auto repair shops and service centres. CarJam lookup, WOF/COF reminders, Xero, NZ-hosted. From $60 NZD/month. 30-day free trial.',
    canonical: 'https://one.oraflows.co.nz/workshop',
    jsonLd: buildJsonLd(),
    openGraph: {
      type: 'website',
      image: 'https://one.oraflows.co.nz/icons/icon-512x512.png',
    },
  })

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
        {/*  HERO                                                         */}
        {/* ============================================================ */}
        <section
          aria-labelledby="workshop-hero-heading"
          className="bg-gradient-to-br from-slate-900 to-indigo-900 px-4 py-20 text-white sm:px-6 lg:px-8 lg:py-28"
        >
          <div className="mx-auto max-w-5xl text-center">
            {/* Eyebrow */}
            <p className="mb-4 text-sm font-semibold uppercase tracking-wider text-blue-300">
              Built for NZ mechanics
            </p>

            <h1
              id="workshop-hero-heading"
              className="text-4xl font-extrabold tracking-tight sm:text-5xl lg:text-6xl"
            >
              Workshop Software for NZ Mechanics, Auto Repair &amp; Service Centres
            </h1>

            <p className="mx-auto mt-6 max-w-3xl text-lg text-gray-300 sm:text-xl">
              CarJam vehicle lookup, WOF &amp; COF expiry tracking, job cards, invoicing, Xero
              integration — all in one NZ-hosted platform, priced in New Zealand dollars.
            </p>

            {/* CTA row */}
            <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <Link
                to="/signup"
                className="inline-flex items-center rounded-lg bg-blue-600 px-8 py-3 text-lg font-semibold text-white shadow-lg transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900"
              >
                Start 30-Day Free Trial
              </Link>
              <button
                type="button"
                onClick={() => setDemoModalOpen(true)}
                className="inline-flex items-center rounded-lg border-2 border-white/30 px-8 py-3 text-lg font-semibold text-white transition-colors hover:border-white hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900"
              >
                Book a Demo
              </button>
              <a
                href="#workshop-pricing"
                className="inline-flex items-center rounded-lg px-4 py-3 text-base font-medium text-blue-200 underline-offset-4 transition-colors hover:text-white hover:underline"
              >
                See pricing →
              </a>
            </div>

            {/* Trust badges row */}
            <div className="mt-10 flex flex-wrap items-center justify-center gap-3 text-sm">
              <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 font-medium text-white backdrop-blur-sm">
                <span aria-hidden="true">🇳🇿</span>
                <span>100% NZ hosted</span>
              </span>
              <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 font-medium text-white backdrop-blur-sm">
                <span aria-hidden="true">🔍</span>
                <span>CarJam integrated</span>
              </span>
              <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 font-medium text-white backdrop-blur-sm">
                <span aria-hidden="true">📋</span>
                <span>WOF &amp; COF workflow</span>
              </span>
              <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 font-medium text-white backdrop-blur-sm">
                <span aria-hidden="true">🔗</span>
                <span>Xero sync</span>
              </span>
            </div>

            {/* CSS hero illustration — emoji + ring, no stock photos */}
            <div
              className="mx-auto mt-14 flex max-w-xl items-center justify-center"
              aria-hidden="true"
            >
              <div className="relative flex h-40 w-40 items-center justify-center rounded-full border border-white/20 bg-white/5 backdrop-blur-sm sm:h-48 sm:w-48">
                <span className="text-6xl sm:text-7xl" role="presentation">
                  🔧
                </span>
                <span className="absolute -right-4 -top-4 rounded-full bg-blue-600 p-3 text-2xl shadow-lg sm:-right-6 sm:-top-6">
                  🚗
                </span>
                <span className="absolute -bottom-4 -left-4 rounded-full bg-emerald-500 p-3 text-2xl shadow-lg sm:-bottom-6 sm:-left-6">
                  📅
                </span>
              </div>
            </div>
            <p className="sr-only">
              Illustration of a workshop wrench with a car and a calendar — representing the
              OraInvoice workshop management platform.
            </p>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  KEY FEATURES                                                 */}
        {/* ============================================================ */}
        <section
          id="workshop-features"
          aria-labelledby="workshop-features-heading"
          className="bg-white px-4 py-20 sm:px-6 lg:px-8"
        >
          <div className="mx-auto max-w-7xl">
            <div className="mx-auto max-w-3xl text-center">
              <h2
                id="workshop-features-heading"
                className="text-3xl font-bold text-gray-900 sm:text-4xl"
              >
                Everything a NZ workshop needs in one platform
              </h2>
              <p className="mt-4 text-lg text-gray-600">
                Features that replace paper job cards, spreadsheets, and three separate apps —
                plus NZ-specific tools that generic workshop software does not have.
              </p>
            </div>

            <div className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {WORKSHOP_FEATURES.map((feature) => (
                <article
                  key={feature.title}
                  className="relative rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md"
                >
                  {feature.nzBadge && (
                    <span className="absolute right-4 top-4 inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
                      NZ exclusive
                    </span>
                  )}
                  <div className="mb-3 text-3xl" aria-hidden="true">
                    {feature.icon}
                  </div>
                  <h3 className="text-lg font-semibold text-gray-900">{feature.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-gray-600">
                    {feature.description}
                  </p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  MADE FOR NZ                                                  */}
        {/* ============================================================ */}
        <section
          aria-labelledby="workshop-nz-heading"
          className="bg-gradient-to-b from-gray-50 to-white px-4 py-20 sm:px-6 lg:px-8"
        >
          <div className="mx-auto max-w-7xl">
            <div className="mx-auto max-w-3xl text-center">
              <p className="mb-3 inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-xs font-semibold uppercase tracking-wider text-emerald-700 ring-1 ring-emerald-200">
                <span aria-hidden="true">🇳🇿</span>
                <span>Made for New Zealand</span>
              </p>
              <h2
                id="workshop-nz-heading"
                className="text-3xl font-bold text-gray-900 sm:text-4xl"
              >
                Built in NZ, for NZ workshops
              </h2>
              <p className="mt-4 text-lg text-gray-600">
                The competitors in this space are good global products. We are the NZ-first one.
                WOF and COF, CarJam, NZ GST, and NZ data sovereignty are not add-ons — they are
                the core.
              </p>
            </div>

            <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-5">
              {NZ_ADVANTAGES.map((adv) => (
                <article
                  key={adv.title}
                  className="rounded-xl border border-gray-200 bg-white p-6 text-center shadow-sm"
                >
                  <div className="mb-3 text-4xl" aria-hidden="true">
                    {adv.icon}
                  </div>
                  <h3 className="text-base font-semibold text-gray-900">{adv.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-gray-600">{adv.description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  WHY MECHANICS SWITCH                                         */}
        {/* ============================================================ */}
        <section
          aria-labelledby="workshop-switch-heading"
          className="bg-white px-4 py-20 sm:px-6 lg:px-8"
        >
          <div className="mx-auto max-w-5xl">
            <div className="text-center">
              <h2
                id="workshop-switch-heading"
                className="text-3xl font-bold text-gray-900 sm:text-4xl"
              >
                Why mechanics switch to OraInvoice
              </h2>
              <p className="mx-auto mt-4 max-w-2xl text-lg text-gray-600">
                The workshop floor has enough going on without fighting your software. Here is
                what our customers stopped putting up with.
              </p>
            </div>

            <ul className="mt-12 space-y-5">
              {SWITCH_REASONS.map((reason) => (
                <li
                  key={reason.pain}
                  className="flex items-start gap-4 rounded-xl border border-gray-200 bg-gray-50 p-5"
                >
                  <svg
                    className="mt-1 h-6 w-6 flex-shrink-0 text-blue-600"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    aria-hidden="true"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                  <div>
                    <p className="font-semibold text-gray-900">{reason.pain}</p>
                    <p className="mt-1 text-sm leading-relaxed text-gray-700">{reason.solution}</p>
                  </div>
                </li>
              ))}
            </ul>

            <div className="mt-10 text-center">
              <p className="text-sm text-gray-600">
                Running multiple trades? See all the trade families we support on our{' '}
                <Link
                  to="/trades"
                  className="font-semibold text-blue-700 underline-offset-4 hover:underline"
                >
                  trades page
                </Link>
                .
              </p>
            </div>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  PRICING                                                      */}
        {/* ============================================================ */}
        <section
          id="workshop-pricing"
          aria-labelledby="workshop-pricing-heading"
          className="bg-gray-50 px-4 py-20 sm:px-6 lg:px-8"
        >
          <div className="mx-auto max-w-7xl text-center">
            <h2
              id="workshop-pricing-heading"
              className="text-3xl font-bold text-gray-900 sm:text-4xl"
            >
              One plan. All features. NZ dollars.
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-gray-600">
              Everything your workshop needs in one plan. No per-user fees. No SMS surcharges on
              top of your plan. No exchange-rate surprises.
            </p>

            <div className="mx-auto mt-12 max-w-md rounded-2xl border-2 border-blue-600 bg-white p-8 shadow-xl">
              <h3 className="text-2xl font-bold text-gray-900">Mech Pro Plan</h3>
              <div className="mt-4">
                <span className="text-5xl font-extrabold text-gray-900">$60</span>
                <span className="text-lg text-gray-500">/month</span>
              </div>
              <p className="mt-2 text-sm text-gray-500">NZD, excluding GST</p>
              <p className="mt-1 text-xs font-medium text-emerald-700">
                30-day free trial — no credit card required
              </p>

              <ul className="mt-8 space-y-3 text-left">
                {WORKSHOP_PRICING_FEATURES.map((label) => (
                  <li key={label} className="flex items-start gap-3">
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
                    <span className="text-sm text-gray-700">{label}</span>
                  </li>
                ))}
              </ul>

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
                  Book a Demo
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  FAQ (also backs FAQPage JSON-LD)                             */}
        {/* ============================================================ */}
        <section
          aria-labelledby="workshop-faq-heading"
          className="bg-white px-4 py-20 sm:px-6 lg:px-8"
        >
          <div className="mx-auto max-w-3xl">
            <div className="text-center">
              <h2
                id="workshop-faq-heading"
                className="text-3xl font-bold text-gray-900 sm:text-4xl"
              >
                Workshop software FAQ
              </h2>
              <p className="mt-4 text-lg text-gray-600">
                Answers to the most common questions from NZ workshops evaluating OraInvoice.
              </p>
            </div>

            <dl className="mt-12 space-y-3">
              {FAQS.map((faq, index) => {
                const isOpen = openFaqIndex === index
                return (
                  <div
                    key={faq.q}
                    className="rounded-xl border border-gray-200 bg-white shadow-sm"
                  >
                    <dt>
                      <button
                        type="button"
                        className="flex w-full items-start justify-between gap-4 px-6 py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                        aria-expanded={isOpen}
                        aria-controls={`workshop-faq-panel-${index}`}
                        onClick={() => setOpenFaqIndex(isOpen ? null : index)}
                      >
                        <span className="text-base font-semibold text-gray-900">{faq.q}</span>
                        <svg
                          className={`mt-1 h-5 w-5 flex-shrink-0 text-gray-400 transition-transform ${
                            isOpen ? 'rotate-180' : ''
                          }`}
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          aria-hidden="true"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 9l-7 7-7-7"
                          />
                        </svg>
                      </button>
                    </dt>
                    <dd
                      id={`workshop-faq-panel-${index}`}
                      className={`overflow-hidden px-6 pb-5 text-sm leading-relaxed text-gray-700 ${
                        isOpen ? 'block' : 'hidden'
                      }`}
                    >
                      {faq.a}
                    </dd>
                  </div>
                )
              })}
            </dl>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  TESTIMONIALS                                                 */}
        {/* ============================================================ */}
        {/* TODO: Replace placeholder testimonials with real customer quotes */}
        <section
          aria-labelledby="workshop-testimonials-heading"
          className="bg-gray-50 px-4 py-20 sm:px-6 lg:px-8"
        >
          <div className="mx-auto max-w-7xl">
            <h2
              id="workshop-testimonials-heading"
              className="mb-12 text-center text-3xl font-bold text-gray-900 sm:text-4xl"
            >
              NZ workshops who switched
            </h2>
            <div className="grid grid-cols-1 gap-8 md:grid-cols-3">
              {WORKSHOP_TESTIMONIALS.map((t) => (
                <article
                  key={t.business}
                  className="rounded-xl bg-white p-6 shadow-sm"
                >
                  <svg
                    className="mb-4 h-8 w-8 text-blue-600/30"
                    fill="currentColor"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path d="M14.017 21v-7.391c0-5.704 3.731-9.57 8.983-10.609l.995 2.151c-2.432.917-3.995 3.638-3.995 5.849h4v10H14.017zM0 21v-7.391c0-5.704 3.748-9.57 9-10.609l.996 2.151C7.563 6.068 6 8.789 6 11h4v10H0z" />
                  </svg>
                  <blockquote className="text-sm leading-relaxed text-gray-700">
                    &ldquo;{t.quote}&rdquo;
                  </blockquote>
                  <footer className="mt-4 border-t border-gray-100 pt-4">
                    <p className="text-sm font-semibold text-gray-900">{t.name}</p>
                    <p className="text-xs text-gray-500">{t.business}</p>
                  </footer>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ============================================================ */}
        {/*  FINAL CTA                                                    */}
        {/* ============================================================ */}
        <section
          aria-labelledby="workshop-final-cta-heading"
          className="bg-gradient-to-br from-slate-900 to-indigo-900 px-4 py-20 text-white sm:px-6 lg:px-8"
        >
          <div className="mx-auto max-w-3xl text-center">
            <h2
              id="workshop-final-cta-heading"
              className="text-3xl font-bold sm:text-4xl"
            >
              Try OraInvoice free for 30 days
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-lg text-gray-300">
              No credit card required. Your data stays in NZ from day one. Cancel any time —
              export everything with one click.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <Link
                to="/signup"
                className="inline-flex items-center rounded-lg bg-blue-600 px-8 py-3 text-lg font-semibold text-white shadow-lg transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900"
              >
                Start Free Trial
              </Link>
              <button
                type="button"
                onClick={() => setDemoModalOpen(true)}
                className="inline-flex items-center rounded-lg border-2 border-white/30 px-8 py-3 text-lg font-semibold text-white transition-colors hover:border-white hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900"
              >
                Book a Demo
              </button>
            </div>
          </div>
        </section>
      </main>

      <LandingFooter />

      <DemoRequestModal open={demoModalOpen} onClose={() => setDemoModalOpen(false)} />
    </>
  )
}
