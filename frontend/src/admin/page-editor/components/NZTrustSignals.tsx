/**
 * NZTrustSignals — row of NZ-specific trust badges (NZ hosted, CarJam,
 * WOF/COF, Xero, NZD pricing). Mirrors the badge row used on the
 * existing WorkshopPage hero but usable anywhere on a page.
 */
import type { ComponentConfig } from '@puckeditor/core'

export type NZSignalKey =
  | 'nz-hosted'
  | 'carjam'
  | 'wof-cof'
  | 'xero'
  | 'nzd'
  | 'gst'

export interface NZSignalEntry {
  key: NZSignalKey
}

export interface NZTrustSignalsProps {
  heading: string
  signals: NZSignalEntry[]
  variant: 'dark' | 'light'
}

interface SignalMeta {
  icon: string
  label: string
}

const SIGNALS: Record<NZSignalKey, SignalMeta> = {
  'nz-hosted': { icon: '🇳🇿', label: '100% NZ hosted' },
  carjam: { icon: '🔍', label: 'CarJam integrated' },
  'wof-cof': { icon: '📋', label: 'WOF & COF workflow' },
  xero: { icon: '🔗', label: 'Xero sync' },
  nzd: { icon: '💵', label: 'NZD pricing' },
  gst: { icon: '🧾', label: '15% GST built in' },
}

const SIGNAL_OPTIONS = [
  { label: '100% NZ hosted', value: 'nz-hosted' },
  { label: 'CarJam integrated', value: 'carjam' },
  { label: 'WOF & COF workflow', value: 'wof-cof' },
  { label: 'Xero sync', value: 'xero' },
  { label: 'NZD pricing', value: 'nzd' },
  { label: '15% GST built in', value: 'gst' },
] as const

const VARIANT_BADGE: Record<NZTrustSignalsProps['variant'], string> = {
  dark: 'bg-white/10 text-white backdrop-blur-sm',
  light: 'bg-white text-gray-900 ring-1 ring-gray-200',
}

const VARIANT_SECTION: Record<NZTrustSignalsProps['variant'], string> = {
  dark: 'bg-slate-900 text-white',
  light: 'bg-white text-gray-900',
}

export const NZTrustSignalsComponent: ComponentConfig<NZTrustSignalsProps> = {
  label: 'NZ Trust Signals',
  fields: {
    heading: { type: 'text', label: 'Heading (optional)' },
    signals: {
      type: 'array',
      label: 'Signals to show',
      arrayFields: {
        key: {
          type: 'select',
          label: 'Signal',
          options: SIGNAL_OPTIONS as unknown as Array<{ label: string; value: NZSignalKey }>,
        },
      },
      defaultItemProps: { key: 'nz-hosted' },
      getItemSummary: (item) => SIGNALS[item.key]?.label ?? 'Signal',
    },
    variant: {
      type: 'radio',
      label: 'Background',
      options: [
        { label: 'Light', value: 'light' },
        { label: 'Dark', value: 'dark' },
      ],
    },
  },
  defaultProps: {
    heading: '',
    signals: [
      { key: 'nz-hosted' },
      { key: 'carjam' },
      { key: 'wof-cof' },
      { key: 'xero' },
      { key: 'nzd' },
    ],
    variant: 'light',
  },
  render: ({ heading, signals, variant }) => {
    const badgeClass = VARIANT_BADGE[variant] ?? VARIANT_BADGE.light
    const sectionClass = VARIANT_SECTION[variant] ?? VARIANT_SECTION.light
    const safeSignals = (signals ?? []).filter(
      (entry): entry is NZSignalEntry => entry.key in SIGNALS,
    )
    if (safeSignals.length === 0) return <></>
    return (
      <section className={`${sectionClass} px-4 py-10 sm:px-6 lg:px-8`}>
        <div className="mx-auto max-w-7xl">
          {heading ? (
            <h3 className="mb-6 text-center text-sm font-semibold uppercase tracking-wider">
              {heading}
            </h3>
          ) : null}
          <div className="flex flex-wrap items-center justify-center gap-3 text-sm">
            {safeSignals.map((entry, idx) => {
              const s = SIGNALS[entry.key]
              return (
                <span
                  key={`${entry.key}-${idx}`}
                  className={`inline-flex items-center gap-2 rounded-full px-4 py-2 font-medium ${badgeClass}`}
                >
                  <span aria-hidden="true">{s.icon}</span>
                  <span>{s.label}</span>
                </span>
              )
            })}
          </div>
        </div>
      </section>
    )
  },
}
