/**
 * FeatureGrid — grid of feature cards, each with an icon, title, and
 * description. The column count (2/3/4) is configurable per instance.
 */
import type { ComponentConfig } from '@puckeditor/core'

export interface FeatureCard {
  icon: string
  title: string
  description: string
}

export interface FeatureGridProps {
  heading: string
  subheading: string
  columns: 2 | 3 | 4
  cards: FeatureCard[]
}

const COLUMN_CLASSES: Record<FeatureGridProps['columns'], string> = {
  2: 'grid-cols-1 md:grid-cols-2',
  3: 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3',
  4: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4',
}

export const FeatureGridComponent: ComponentConfig<FeatureGridProps> = {
  label: 'Feature Grid',
  fields: {
    heading: { type: 'text', label: 'Section heading (optional)' },
    subheading: { type: 'textarea', label: 'Section sub-heading (optional)' },
    columns: {
      type: 'select',
      label: 'Columns',
      options: [
        { label: '2 columns', value: 2 },
        { label: '3 columns', value: 3 },
        { label: '4 columns', value: 4 },
      ],
    },
    cards: {
      type: 'array',
      label: 'Cards',
      arrayFields: {
        icon: { type: 'text', label: 'Icon (emoji or SVG)' },
        title: { type: 'text', label: 'Title' },
        description: { type: 'textarea', label: 'Description' },
      },
      defaultItemProps: {
        icon: '✨',
        title: 'Feature title',
        description: 'Describe the feature in one or two sentences.',
      },
      getItemSummary: (item) => item.title || 'Feature',
    },
  },
  defaultProps: {
    heading: '',
    subheading: '',
    columns: 3,
    cards: [
      {
        icon: '🚗',
        title: 'CarJam vehicle lookup',
        description: 'Pull make, model, VIN, WOF and rego expiry in two seconds.',
      },
      {
        icon: '🧾',
        title: 'Invoicing & payments',
        description: 'GST-compliant invoices with Stripe online payments built in.',
      },
      {
        icon: '🗓️',
        title: 'Bookings & scheduling',
        description: 'Online bookings with a drag-and-drop workshop calendar.',
      },
    ],
  },
  render: ({ heading, subheading, columns, cards }) => {
    const safeCards = cards ?? []
    const colClass = COLUMN_CLASSES[columns] ?? COLUMN_CLASSES[3]
    return (
      <section className="bg-white px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl">
          {heading ? (
            <div className="mx-auto mb-10 max-w-3xl text-center">
              <h2 className="text-3xl font-bold text-gray-900">{heading}</h2>
              {subheading ? (
                <p className="mt-3 text-lg text-gray-600">{subheading}</p>
              ) : null}
            </div>
          ) : null}
          <div className={`grid gap-6 ${colClass}`}>
            {safeCards.map((card, idx) => (
              <article
                key={`${card.title}-${idx}`}
                className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md"
              >
                <div className="mb-3 text-3xl" aria-hidden="true">
                  {card.icon}
                </div>
                <h3 className="text-lg font-semibold text-gray-900">{card.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-gray-600">{card.description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>
    )
  },
}
