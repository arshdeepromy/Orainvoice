/**
 * CTABanner — full-width gradient banner with a heading, sub-text and
 * one or two CTA buttons. Visually paired with Hero but always rendered
 * at H2 level because it belongs mid-page.
 */
import type { ComponentConfig } from '@puckeditor/core'

export interface CTABannerButton {
  label: string
  url: string
  style: 'primary' | 'secondary'
}

export interface CTABannerProps {
  heading: string
  subtext: string
  buttons: CTABannerButton[]
}

const BUTTON_CLASSES: Record<CTABannerButton['style'], string> = {
  primary:
    'inline-flex items-center rounded-lg bg-blue-600 px-8 py-3 text-lg font-semibold text-white shadow-lg transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
  secondary:
    'inline-flex items-center rounded-lg border-2 border-white/30 px-8 py-3 text-lg font-semibold text-white transition-colors hover:border-white hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
}

export const CTABannerComponent: ComponentConfig<CTABannerProps> = {
  label: 'CTA Banner',
  fields: {
    heading: { type: 'text', label: 'Heading' },
    subtext: { type: 'textarea', label: 'Sub-text' },
    buttons: {
      type: 'array',
      label: 'Buttons',
      max: 2,
      arrayFields: {
        label: { type: 'text', label: 'Button label' },
        url: { type: 'text', label: 'Button URL' },
        style: {
          type: 'select',
          label: 'Style',
          options: [
            { label: 'Primary', value: 'primary' },
            { label: 'Secondary', value: 'secondary' },
          ],
        },
      },
      defaultItemProps: { label: 'Get Started Free', url: '/signup', style: 'primary' },
      getItemSummary: (item) => item.label || 'Button',
    },
  },
  defaultProps: {
    heading: 'Ready to streamline your workshop?',
    subtext:
      'Join New Zealand workshops already using OraInvoice. Start your free trial today — no credit card required.',
    buttons: [{ label: 'Get Started Free', url: '/signup', style: 'primary' }],
  },
  render: ({ heading, subtext, buttons }) => {
    const safeButtons = buttons ?? []
    return (
      <section className="bg-gradient-to-br from-slate-900 to-indigo-900 px-4 py-20 text-white sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <h2 className="text-3xl font-bold sm:text-4xl">{heading}</h2>
          {subtext ? (
            <p className="mx-auto mt-4 max-w-xl text-lg text-gray-300">{subtext}</p>
          ) : null}
          {safeButtons.length > 0 ? (
            <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
              {safeButtons.map((btn, idx) => (
                <a
                  key={`${btn.label}-${idx}`}
                  href={btn.url || '#'}
                  className={BUTTON_CLASSES[btn.style] ?? BUTTON_CLASSES.primary}
                >
                  {btn.label}
                </a>
              ))}
            </div>
          ) : null}
        </div>
      </section>
    )
  },
}
