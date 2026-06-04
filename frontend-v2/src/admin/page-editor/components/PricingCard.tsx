/**
 * PricingCard — single plan pricing card with a feature checklist and
 * one CTA button.
 */
import type { ComponentConfig } from '@puckeditor/core'

export interface PricingFeature {
  label: string
  comingSoon: boolean
}

export interface PricingCardProps {
  planName: string
  price: string
  currency: string
  period: string
  taxNote: string
  highlight: boolean
  features: PricingFeature[]
  ctaLabel: string
  ctaUrl: string
}

export const PricingCardComponent: ComponentConfig<PricingCardProps> = {
  label: 'Pricing Card',
  fields: {
    planName: { type: 'text', label: 'Plan name' },
    price: { type: 'text', label: 'Price (numeric)' },
    currency: { type: 'text', label: 'Currency (e.g. NZD, $)' },
    period: { type: 'text', label: 'Billing period (e.g. month, year)' },
    taxNote: { type: 'text', label: 'Tax note (e.g. excl. GST)' },
    highlight: {
      type: 'radio',
      label: 'Highlight this card?',
      options: [
        { label: 'No', value: false },
        { label: 'Yes', value: true },
      ],
    },
    features: {
      type: 'array',
      label: 'Features',
      arrayFields: {
        label: { type: 'text', label: 'Feature label' },
        comingSoon: {
          type: 'radio',
          label: 'Coming soon?',
          options: [
            { label: 'No', value: false },
            { label: 'Yes', value: true },
          ],
        },
      },
      defaultItemProps: { label: 'Feature', comingSoon: false },
      getItemSummary: (item) => item.label || 'Feature',
    },
    ctaLabel: { type: 'text', label: 'CTA label' },
    ctaUrl: { type: 'text', label: 'CTA URL' },
  },
  defaultProps: {
    planName: 'Mech Pro Plan',
    price: '60',
    currency: '$',
    period: 'month',
    taxNote: 'NZD, excluding GST',
    highlight: true,
    features: [
      { label: 'Unlimited invoices & quotes', comingSoon: false },
      { label: 'CarJam vehicle lookup', comingSoon: false },
      { label: 'Online payments (Stripe)', comingSoon: false },
    ],
    ctaLabel: 'Start Free Trial',
    ctaUrl: '/signup',
  },
  render: ({
    planName,
    price,
    currency,
    period,
    taxNote,
    highlight,
    features,
    ctaLabel,
    ctaUrl,
  }) => {
    const safeFeatures = features ?? []
    const borderClass = highlight
      ? 'border-2 border-blue-600 shadow-xl'
      : 'border border-gray-200 shadow-sm'
    return (
      <div className={`mx-auto max-w-md rounded-2xl bg-white p-8 ${borderClass}`}>
        <h3 className="text-2xl font-bold text-gray-900">{planName}</h3>
        <div className="mt-4">
          <span className="text-5xl font-extrabold text-gray-900">
            {currency}
            {price}
          </span>
          {period ? <span className="text-lg text-gray-500">/{period}</span> : null}
        </div>
        {taxNote ? <p className="mt-2 text-sm text-gray-500">{taxNote}</p> : null}
        <ul className="mt-8 space-y-3 text-left">
          {safeFeatures.map((feature, idx) => (
            <li key={`${feature.label}-${idx}`} className="flex items-start gap-3">
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
              {feature.comingSoon ? (
                <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                  Coming soon
                </span>
              ) : null}
            </li>
          ))}
        </ul>
        {ctaLabel ? (
          <a
            href={ctaUrl || '#'}
            className="mt-8 inline-flex w-full items-center justify-center rounded-lg bg-blue-600 px-6 py-3 text-base font-semibold text-white shadow transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
          >
            {ctaLabel}
          </a>
        ) : null}
      </div>
    )
  },
}
