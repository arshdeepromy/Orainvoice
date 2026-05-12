/**
 * Page templates — starter Puck_Data documents used when creating new
 * Editor_Only_Pages.
 *
 * Per Requirement 8.8, the set of templates lives in this file so new
 * templates can be added without backend changes.
 *
 * Each template's `content` field is a Puck_Data document of shape
 * `{ content: PuckNode[], root: { props: {} } }`. Every PuckNode has
 * a `type` (matching a key in `puckConfig.components`) and `props`
 * that include a unique `id` plus the default field values.
 *
 * The shape mirrors the `@puckeditor/core` `Data` type but is declared
 * as `Record<string, unknown>` here to match the backend
 * `CreatePageRequest.content` field shape (JSON blob, validated
 * server-side against Puck's schema only when persisted).
 */

// Simple counter used only while building the initial template data —
// gives every node in a single page a unique id like "Hero-1",
// "FeatureGrid-2", etc. Puck regenerates ids after the first edit,
// so we just need uniqueness within the starter document.
let _counter = 0
function puckId(type: string): string {
  _counter += 1
  return `${type}-${_counter}`
}

export interface PageTemplate {
  key: string
  name: string
  description: string
  /**
   * Puck_Data shape: `{ content: PuckNode[], root: { props: {} } }`.
   * Declared as a generic record because the templates are passed
   * straight to the backend as JSON and re-hydrated into Puck's `Data`
   * type on the editor side without needing to reference Puck's
   * generated per-component types here.
   */
  content: Record<string, unknown>
}

/* --------------------------------------------------------------------
 * blank
 * -------------------------------------------------------------------- */
const BLANK_CONTENT = {
  content: [],
  root: { props: {} },
}

/* --------------------------------------------------------------------
 * landing — Hero + FeatureGrid (3 cards) + CTABanner
 * Mirrors the generic SaaS marketing layout: big hero, three-column
 * feature cards, closing CTA banner.
 * -------------------------------------------------------------------- */
function buildLandingContent() {
  return {
    content: [
      {
        type: 'Hero',
        props: {
          id: puckId('Hero'),
          eyebrow: '',
          heading: 'Built for NZ Trade Businesses',
          subtext:
            'Invoicing, job management, and business operations — purpose-built for workshops, mechanics, and trade businesses across New Zealand.',
          ctas: [
            { label: 'Get Started', url: '/signup', style: 'primary' },
            { label: 'Request Free Demo', url: '#demo', style: 'secondary' },
          ],
          trustBadges: [
            { icon: '🇳🇿', label: '100% NZ Hosted — Your data never leaves New Zealand' },
          ],
        },
      },
      {
        type: 'FeatureGrid',
        props: {
          id: puckId('FeatureGrid'),
          heading: 'Everything you need to run your business',
          subheading:
            'One platform covering quoting, invoicing, payments and scheduling — no more juggling spreadsheets.',
          columns: 3,
          cards: [
            {
              icon: '🧾',
              title: 'Invoicing & payments',
              description:
                'GST-compliant invoices with Stripe online payments built in.',
            },
            {
              icon: '🗓️',
              title: 'Bookings & scheduling',
              description:
                'Online bookings with a drag-and-drop workshop calendar.',
            },
            {
              icon: '📱',
              title: 'Mobile companion app',
              description:
                'Keep invoicing, job cards and time tracking on the go from your phone.',
            },
          ],
        },
      },
      {
        type: 'CTABanner',
        props: {
          id: puckId('CTABanner'),
          heading: 'Ready to streamline your business?',
          subtext:
            'Join New Zealand trade businesses already using OraInvoice. Start your free trial today — no credit card required.',
          buttons: [
            { label: 'Get Started Free', url: '/signup', style: 'primary' },
          ],
        },
      },
    ],
    root: { props: {} },
  }
}

/* --------------------------------------------------------------------
 * workshop-style — matches the existing WorkshopPage layout with NZ
 * trust signals baked into the Hero, workshop-focused feature cards,
 * a testimonial, a pricing card, and a closing CTA.
 * -------------------------------------------------------------------- */
function buildWorkshopContent() {
  return {
    content: [
      {
        type: 'Hero',
        props: {
          id: puckId('Hero'),
          eyebrow: 'For NZ Automotive Workshops',
          heading: 'Run your workshop — not your paperwork',
          subtext:
            'Job cards, WOF/COF reminders, CarJam lookups, invoicing and bookings. Purpose-built for Kiwi mechanics and workshops.',
          ctas: [
            { label: 'Start Free Trial', url: '/signup', style: 'primary' },
            { label: 'See It In Action', url: '#demo', style: 'secondary' },
          ],
          trustBadges: [
            { icon: '🇳🇿', label: '100% NZ hosted' },
            { icon: '🔍', label: 'CarJam integrated' },
            { icon: '📋', label: 'WOF & COF workflow' },
            { icon: '🔗', label: 'Xero sync' },
          ],
        },
      },
      {
        type: 'FeatureGrid',
        props: {
          id: puckId('FeatureGrid'),
          heading: 'Everything a NZ workshop needs',
          subheading:
            'From the first rego lookup to the final paid invoice — all the tools in one place.',
          columns: 3,
          cards: [
            {
              icon: '🚗',
              title: 'CarJam vehicle lookup',
              description:
                'Pull make, model, VIN, WOF and rego expiry in two seconds.',
            },
            {
              icon: '🧰',
              title: 'Job cards & workshop board',
              description:
                'Track every vehicle from arrival to pickup on a drag-and-drop board.',
            },
            {
              icon: '⏰',
              title: 'WOF & COF reminders',
              description:
                'Automatic reminders go out via SMS and email before customers are due.',
            },
            {
              icon: '🧾',
              title: 'Invoicing & payments',
              description:
                'GST-compliant invoices with Stripe online payments and Xero sync.',
            },
            {
              icon: '🗓️',
              title: 'Online bookings',
              description:
                'Your customers book service slots online — no phone tag required.',
            },
            {
              icon: '📱',
              title: 'Field-ready mobile app',
              description:
                'Technicians log time, add parts and update jobs from their phones.',
            },
          ],
        },
      },
      {
        type: 'TestimonialCard',
        props: {
          id: puckId('TestimonialCard'),
          quote:
            'OraInvoice transformed how we run our workshop. Job cards, invoicing, and scheduling all in one place.',
          name: 'James T.',
          business: 'JT Automotive',
        },
      },
      {
        type: 'PricingCard',
        props: {
          id: puckId('PricingCard'),
          planName: 'Mech Pro Plan',
          price: '60',
          currency: '$',
          period: 'month',
          taxNote: 'NZD, excluding GST',
          highlight: true,
          features: [
            { label: 'Unlimited invoices & quotes', comingSoon: false },
            { label: 'CarJam vehicle lookup', comingSoon: false },
            { label: 'WOF & COF reminders', comingSoon: false },
            { label: 'Online payments (Stripe)', comingSoon: false },
            { label: 'Xero accounting sync', comingSoon: false },
            { label: 'Mobile companion app', comingSoon: false },
          ],
          ctaLabel: 'Start Free Trial',
          ctaUrl: '/signup',
        },
      },
      {
        type: 'CTABanner',
        props: {
          id: puckId('CTABanner'),
          heading: 'Ready to streamline your workshop?',
          subtext:
            'Join New Zealand workshops already using OraInvoice. Start your free trial today — no credit card required.',
          buttons: [
            { label: 'Get Started Free', url: '/signup', style: 'primary' },
            { label: 'Request Demo', url: '#demo', style: 'secondary' },
          ],
        },
      },
    ],
    root: { props: {} },
  }
}

/* --------------------------------------------------------------------
 * trades — tradies-focused landing page with a demo request form
 * baked into the flow, rather than a pricing card.
 * -------------------------------------------------------------------- */
function buildTradesContent() {
  return {
    content: [
      {
        type: 'Hero',
        props: {
          id: puckId('Hero'),
          eyebrow: 'For Electricians, Plumbers & Builders',
          heading: 'Quote, invoice and get paid — faster',
          subtext:
            'Job management for NZ tradies. Quotes, invoices, job cards, time tracking and payments in one simple tool.',
          ctas: [
            { label: 'Start Free Trial', url: '/signup', style: 'primary' },
            { label: 'Request Demo', url: '#demo', style: 'secondary' },
          ],
          trustBadges: [
            { icon: '🇳🇿', label: '100% NZ hosted' },
            { icon: '🔗', label: 'Xero sync' },
            { icon: '💵', label: 'NZD pricing' },
          ],
        },
      },
      {
        type: 'FeatureGrid',
        props: {
          id: puckId('FeatureGrid'),
          heading: 'Built for life on the tools',
          subheading:
            'From the first quote to the final paid invoice — designed for NZ trade businesses.',
          columns: 3,
          cards: [
            {
              icon: '📝',
              title: 'Quotes in minutes',
              description:
                'Build professional quotes on-site, email them to the customer, convert to an invoice in one click.',
            },
            {
              icon: '🧰',
              title: 'Job cards & time tracking',
              description:
                'Track labour, parts and materials per job. Technicians log hours from their phones.',
            },
            {
              icon: '📸',
              title: 'On-site photos',
              description:
                'Attach photos, receipts and compliance docs to every job card from the mobile app.',
            },
            {
              icon: '🧾',
              title: 'GST-compliant invoicing',
              description:
                'Invoices with NZ GST calculated correctly. Stripe online payments built in.',
            },
            {
              icon: '🔗',
              title: 'Xero accounting sync',
              description:
                'Invoices, customers and payments flow through to Xero automatically.',
            },
            {
              icon: '📱',
              title: 'Mobile companion app',
              description:
                'Runs on every phone and tablet — iOS, Android and in the browser.',
            },
          ],
        },
      },
      {
        type: 'DemoRequestForm',
        props: {
          id: puckId('DemoRequestForm'),
          heading: 'Request a Free Demo',
          subheading:
            'Our team will set up a dedicated session to walk you through the app.',
          submitLabel: 'Request Demo',
          successMessage:
            'Thank you! Our team will be in touch within 24 hours to schedule your demo.',
          fallbackEmail: 'support@oraflows.co.nz',
        },
      },
      {
        type: 'CTABanner',
        props: {
          id: puckId('CTABanner'),
          heading: 'Ready to stop chasing paperwork?',
          subtext:
            'Join NZ tradies already using OraInvoice. Start your free trial today — no credit card required.',
          buttons: [
            { label: 'Get Started Free', url: '/signup', style: 'primary' },
          ],
        },
      },
    ],
    root: { props: {} },
  }
}

/* --------------------------------------------------------------------
 * privacy — legal-style page: Hero with the page title, followed by a
 * series of Heading + RichText pairs that cover the standard privacy
 * policy sections. Admins can then edit the copy as needed.
 * -------------------------------------------------------------------- */
function buildPrivacyContent() {
  return {
    content: [
      {
        type: 'Hero',
        props: {
          id: puckId('Hero'),
          eyebrow: 'Legal',
          heading: 'Privacy Policy',
          subtext:
            'How we collect, use and protect information you share with us.',
          ctas: [],
          trustBadges: [],
        },
      },
      {
        type: 'Heading',
        props: {
          id: puckId('Heading'),
          level: 2,
          text: 'Information we collect',
          align: 'left',
        },
      },
      {
        type: 'RichText',
        props: {
          id: puckId('RichText'),
          html: '<p>Describe here what information your business collects — for example account details, billing information and usage data. Replace this placeholder copy with your organisation&rsquo;s policy.</p>',
          align: 'left',
          size: 'base',
        },
      },
      {
        type: 'Heading',
        props: {
          id: puckId('Heading'),
          level: 2,
          text: 'How we use your information',
          align: 'left',
        },
      },
      {
        type: 'RichText',
        props: {
          id: puckId('RichText'),
          html: '<p>Explain the lawful purposes your business uses personal information for — providing the service, billing, communications, security and legal compliance.</p>',
          align: 'left',
          size: 'base',
        },
      },
      {
        type: 'Heading',
        props: {
          id: puckId('Heading'),
          level: 2,
          text: 'How we share your information',
          align: 'left',
        },
      },
      {
        type: 'RichText',
        props: {
          id: puckId('RichText'),
          html: '<p>List any third parties your business shares information with — payment processors, accounting integrations, SMS providers, hosting providers — and the purposes of that sharing.</p>',
          align: 'left',
          size: 'base',
        },
      },
      {
        type: 'Heading',
        props: {
          id: puckId('Heading'),
          level: 2,
          text: 'Data storage and security',
          align: 'left',
        },
      },
      {
        type: 'RichText',
        props: {
          id: puckId('RichText'),
          html: '<p>Describe where data is stored, the security controls in place (encryption at rest, access control, backups), and your approach to incident response.</p>',
          align: 'left',
          size: 'base',
        },
      },
      {
        type: 'Heading',
        props: {
          id: puckId('Heading'),
          level: 2,
          text: 'Your rights',
          align: 'left',
        },
      },
      {
        type: 'RichText',
        props: {
          id: puckId('RichText'),
          html: '<p>Under the Privacy Act 2020, individuals have the right to request access to and correction of personal information held about them. Describe how a user can exercise those rights.</p>',
          align: 'left',
          size: 'base',
        },
      },
      {
        type: 'Heading',
        props: {
          id: puckId('Heading'),
          level: 2,
          text: 'Contact us',
          align: 'left',
        },
      },
      {
        type: 'RichText',
        props: {
          id: puckId('RichText'),
          html: '<p>If you have questions about this privacy policy or how your information is handled, contact us at <a href="mailto:privacy@example.co.nz">privacy@example.co.nz</a>.</p>',
          align: 'left',
          size: 'base',
        },
      },
    ],
    root: { props: {} },
  }
}

/**
 * Public list of templates exposed to the New Page dialog.
 *
 * Order matters — the UI renders these as selectable cards in this
 * order, so `blank` stays first as the safe default.
 */
export const PAGE_TEMPLATES: PageTemplate[] = [
  {
    key: 'blank',
    name: 'Blank Page',
    description: 'Start from scratch with an empty page.',
    content: BLANK_CONTENT,
  },
  {
    key: 'landing',
    name: 'Landing Page',
    description: 'Hero, feature grid and closing CTA — good for generic marketing pages.',
    content: buildLandingContent(),
  },
  {
    key: 'workshop-style',
    name: 'Workshop Style',
    description:
      'Matches the existing workshop landing: NZ trust signals, workshop-focused features, testimonial, pricing and CTA.',
    content: buildWorkshopContent(),
  },
  {
    key: 'trades',
    name: 'Trades',
    description:
      'Trades-focused landing with feature grid and inline demo request form.',
    content: buildTradesContent(),
  },
  {
    key: 'privacy',
    name: 'Privacy Policy',
    description:
      'Legal-page scaffold with headings and rich-text blocks for each standard section.',
    content: buildPrivacyContent(),
  },
]

/**
 * Look up a template by key. Returns the `blank` template as a safe
 * fallback when the key is unknown.
 */
export function getTemplateByKey(key: string): PageTemplate {
  return (
    PAGE_TEMPLATES.find((t) => t.key === key) ??
    PAGE_TEMPLATES.find((t) => t.key === 'blank') ??
    PAGE_TEMPLATES[0]
  )
}
