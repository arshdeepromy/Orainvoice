/**
 * FAQAccordion — renders semantic `<details>`/`<summary>` elements with
 * an inline FAQPage JSON-LD block for SEO.
 *
 * Per Requirement 1.5 and 6.5, the component emits its own FAQPage
 * JSON-LD script tag. When `usePageMeta` is also emitting JSON-LD at
 * the page level the two are merged server-side (design.md), but each
 * FAQAccordion still ships its own `<script>` so a page without any
 * other SEO metadata still gets FAQ rich-snippet eligibility.
 */
import type { ComponentConfig } from '@puckeditor/core'

export interface FaqItem {
  question: string
  answer: string
}

export interface FAQAccordionProps {
  heading: string
  items: FaqItem[]
}

function buildFaqJsonLd(items: FaqItem[]): string {
  const payload = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: items.map((item) => ({
      '@type': 'Question',
      name: item.question,
      acceptedAnswer: {
        '@type': 'Answer',
        text: item.answer,
      },
    })),
  }
  // Escape `</script` to avoid breaking out of the script tag.
  return JSON.stringify(payload).replace(/<\/script/gi, '<\\/script')
}

export const FAQAccordionComponent: ComponentConfig<FAQAccordionProps> = {
  label: 'FAQ Accordion',
  fields: {
    heading: { type: 'text', label: 'Section heading (optional)' },
    items: {
      type: 'array',
      label: 'Q&A items',
      arrayFields: {
        question: { type: 'text', label: 'Question' },
        answer: { type: 'textarea', label: 'Answer' },
      },
      defaultItemProps: {
        question: 'Question',
        answer: 'Answer',
      },
      getItemSummary: (item) => item.question || 'FAQ',
    },
  },
  defaultProps: {
    heading: 'Frequently asked questions',
    items: [
      { question: 'How much does it cost?', answer: '$60 NZD per month, excluding GST.' },
      {
        question: 'Is my data stored in New Zealand?',
        answer: 'Yes — OraInvoice is 100% NZ hosted.',
      },
    ],
  },
  render: ({ heading, items }) => {
    const safeItems = (items ?? []).filter((item) => item.question && item.answer)
    if (safeItems.length === 0) return <></>
    const jsonLd = buildFaqJsonLd(safeItems)
    return (
      <section className="bg-white px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl">
          {heading ? (
            <h2 className="mb-8 text-center text-3xl font-bold text-gray-900">{heading}</h2>
          ) : null}
          <div className="divide-y divide-gray-200 rounded-xl border border-gray-200 bg-white">
            {safeItems.map((item, idx) => (
              <details
                key={`${item.question}-${idx}`}
                className="group px-5 py-4 [&_summary::-webkit-details-marker]:hidden"
              >
                <summary className="flex cursor-pointer items-start justify-between gap-4 text-left text-base font-semibold text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
                  <span>{item.question}</span>
                  <span
                    aria-hidden="true"
                    className="mt-1 text-gray-500 transition-transform group-open:rotate-45"
                  >
                    +
                  </span>
                </summary>
                <p className="mt-3 text-sm leading-relaxed text-gray-700">{item.answer}</p>
              </details>
            ))}
          </div>
        </div>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd }}
        />
      </section>
    )
  },
}
