/**
 * Hero — full-width hero section with gradient background, H1 heading,
 * sub-text paragraph, up to 2 CTA buttons, and an optional row of
 * trust badges.
 *
 * Implementation notes:
 * - Uses only Tailwind utility classes from the existing config.
 * - Emits a single `<h1>` but does NOT enforce the single-H1 rule on
 *   its own — that job belongs to `Heading` component. A page may
 *   contain more than one Hero only if the page author accepts the
 *   resulting multiple H1 demotion behaviour encoded in Heading.tsx.
 */
import type { ComponentConfig } from '@puckeditor/core'
import { markH1Seen, shouldEmitH1 } from './headingCounter'

export interface HeroCta {
  label: string
  url: string
  style: 'primary' | 'secondary' | 'ghost'
}

export interface HeroTrustBadge {
  label: string
  icon: string
}

export interface HeroProps {
  eyebrow: string
  heading: string
  subtext: string
  ctas: HeroCta[]
  trustBadges: HeroTrustBadge[]
}

const CTA_CLASSES: Record<HeroCta['style'], string> = {
  primary:
    'inline-flex items-center rounded-lg bg-blue-600 px-8 py-3 text-lg font-semibold text-white shadow-lg transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
  secondary:
    'inline-flex items-center rounded-lg border-2 border-white/30 px-8 py-3 text-lg font-semibold text-white transition-colors hover:border-white hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
  ghost:
    'inline-flex items-center rounded-lg px-4 py-3 text-base font-medium text-blue-200 underline-offset-4 transition-colors hover:text-white hover:underline',
}

export const HeroComponent: ComponentConfig<HeroProps> = {
  label: 'Hero',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow (optional)' },
    heading: { type: 'text', label: 'Heading (H1)' },
    subtext: { type: 'textarea', label: 'Sub-text' },
    ctas: {
      type: 'array',
      label: 'CTA Buttons',
      max: 2,
      arrayFields: {
        label: { type: 'text', label: 'Button label' },
        url: { type: 'text', label: 'Button URL' },
        style: {
          type: 'select',
          label: 'Button style',
          options: [
            { label: 'Primary', value: 'primary' },
            { label: 'Secondary', value: 'secondary' },
            { label: 'Ghost', value: 'ghost' },
          ],
        },
      },
      defaultItemProps: { label: 'Get started', url: '/signup', style: 'primary' },
      getItemSummary: (item) => item.label || 'Button',
    },
    trustBadges: {
      type: 'array',
      label: 'Trust badges',
      arrayFields: {
        icon: { type: 'text', label: 'Icon (emoji)' },
        label: { type: 'text', label: 'Badge text' },
      },
      defaultItemProps: { icon: '🇳🇿', label: '100% NZ hosted' },
      getItemSummary: (item) => item.label || 'Badge',
    },
  },
  defaultProps: {
    eyebrow: '',
    heading: 'Built for NZ Trade Businesses',
    subtext:
      'Invoicing, job management, and business operations — purpose-built for workshops, mechanics, and trade businesses across New Zealand.',
    ctas: [
      { label: 'Get Started', url: '/signup', style: 'primary' },
      { label: 'Request Free Demo', url: '#demo', style: 'secondary' },
    ],
    trustBadges: [{ icon: '🇳🇿', label: '100% NZ Hosted — Your data never leaves New Zealand' }],
  },
  render: ({ eyebrow, heading, subtext, ctas, trustBadges }) => {
    const safeCtas = ctas ?? []
    const safeTrust = trustBadges ?? []
    const emitAsH1 = shouldEmitH1()
    if (emitAsH1) markH1Seen()
    return (
      <section className="bg-gradient-to-br from-slate-900 to-indigo-900 px-4 py-20 text-white sm:px-6 lg:px-8 lg:py-32">
        <div className="mx-auto max-w-7xl text-center">
          {eyebrow ? (
            <p className="mb-4 text-sm font-semibold uppercase tracking-wider text-blue-300">
              {eyebrow}
            </p>
          ) : null}
          {emitAsH1 ? (
            <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl lg:text-6xl">
              {heading}
            </h1>
          ) : (
            <h2 className="text-4xl font-extrabold tracking-tight sm:text-5xl lg:text-6xl">
              {heading}
            </h2>
          )}
          {subtext ? (
            <p className="mx-auto mt-6 max-w-2xl text-lg text-gray-300 sm:text-xl">{subtext}</p>
          ) : null}
          {safeCtas.length > 0 ? (
            <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
              {safeCtas.map((cta, idx) => (
                <a
                  key={`${cta.label}-${idx}`}
                  href={cta.url}
                  className={CTA_CLASSES[cta.style] ?? CTA_CLASSES.primary}
                >
                  {cta.label}
                </a>
              ))}
            </div>
          ) : null}
          {safeTrust.length > 0 ? (
            <div className="mt-10 flex flex-wrap items-center justify-center gap-3 text-sm">
              {safeTrust.map((badge, idx) => (
                <span
                  key={`${badge.label}-${idx}`}
                  className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 font-medium text-white backdrop-blur-sm"
                >
                  <span aria-hidden="true">{badge.icon}</span>
                  <span>{badge.label}</span>
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </section>
    )
  },
}
