/**
 * TestimonialCard — quote card with person name and business name.
 *
 * Does NOT emit Review / AggregateRating JSON-LD. Per existing
 * WorkshopPage.tsx guidance, testimonial schema must only be emitted
 * once real verified reviews exist.
 */
import type { ComponentConfig } from '@puckeditor/core'

export interface TestimonialCardProps {
  quote: string
  name: string
  business: string
}

export const TestimonialCardComponent: ComponentConfig<TestimonialCardProps> = {
  label: 'Testimonial Card',
  fields: {
    quote: { type: 'textarea', label: 'Quote' },
    name: { type: 'text', label: 'Person name' },
    business: { type: 'text', label: 'Business name' },
  },
  defaultProps: {
    quote:
      'OraInvoice transformed how we run our workshop. Job cards, invoicing, and scheduling all in one place.',
    name: 'James T.',
    business: 'JT Automotive',
  },
  render: ({ quote, name, business }) => {
    return (
      <figure className="rounded-xl bg-white p-6 shadow-sm">
        <svg
          className="mb-4 h-8 w-8 text-blue-600/30"
          fill="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path d="M14.017 21v-7.391c0-5.704 3.731-9.57 8.983-10.609l.995 2.151c-2.432.917-3.995 3.638-3.995 5.849h4v10H14.017zM0 21v-7.391c0-5.704 3.748-9.57 9-10.609l.996 2.151C7.563 6.068 6 8.789 6 11h4v10H0z" />
        </svg>
        <blockquote className="text-sm leading-relaxed text-gray-700">&ldquo;{quote}&rdquo;</blockquote>
        <figcaption className="mt-4 border-t border-gray-100 pt-4">
          {name ? <p className="text-sm font-semibold text-gray-900">{name}</p> : null}
          {business ? <p className="text-xs text-gray-500">{business}</p> : null}
        </figcaption>
      </figure>
    )
  },
}
