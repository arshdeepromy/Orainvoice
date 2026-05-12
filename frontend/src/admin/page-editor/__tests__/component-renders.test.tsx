/**
 * Unit tests for individual Puck component render functions.
 *
 * Covers:
 *  - FAQAccordion → emits <details>/<summary> + FAQPage JSON-LD
 *  - VideoEmbed   → iframe for YouTube/Vimeo, <video> for MP4
 *  - ImageBlock   → emits srcset from supplied variants
 *  - HeadingComponent → demotes the second H1 to H2 (single H1 rule)
 *
 * The shared headingCounter is reset between tests so each render
 * starts fresh. Uses Testing Library's render to walk the DOM.
 *
 * Validates: Requirements 1.5, 1.6, 7.4, 7.5
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import {
  FAQAccordionComponent,
  VideoEmbedComponent,
  ImageBlockComponent,
  HeadingComponent,
  resetH1Counter,
} from '../components'

beforeEach(() => {
  cleanup()
  resetH1Counter()
})

/* -------------------------------------------------------------------------- */
/*  Helper — invoke a Puck component's render fn with the given props         */
/* -------------------------------------------------------------------------- */

function renderComponent<P extends object>(
  config: { render: (props: P) => JSX.Element | null | false },
  props: P,
) {
  const element = config.render(props)
  // Some renderers return `false` for empty data — wrap so render() works
  return render(<>{element}</>)
}

/* -------------------------------------------------------------------------- */
/*  FAQAccordion                                                              */
/* -------------------------------------------------------------------------- */

describe('FAQAccordionComponent', () => {
  it('emits semantic <details>/<summary> and FAQPage JSON-LD', () => {
    const { container } = renderComponent(FAQAccordionComponent, {
      heading: 'Common questions',
      items: [
        { question: 'What is OraInvoice?', answer: 'Trade invoicing software.' },
        { question: 'Where is data stored?', answer: 'In New Zealand.' },
      ],
    })

    const details = container.querySelectorAll('details')
    const summaries = container.querySelectorAll('summary')
    expect(details.length).toBe(2)
    expect(summaries.length).toBe(2)

    const ldScript = container.querySelector('script[type="application/ld+json"]')
    expect(ldScript).not.toBeNull()
    const ld = JSON.parse(ldScript?.textContent ?? '{}')
    expect(ld['@context']).toBe('https://schema.org')
    expect(ld['@type']).toBe('FAQPage')
    expect(Array.isArray(ld.mainEntity)).toBe(true)
    expect(ld.mainEntity.length).toBe(2)
    expect(ld.mainEntity[0]['@type']).toBe('Question')
    expect(ld.mainEntity[0].acceptedAnswer['@type']).toBe('Answer')
  })

  it('skips items missing question or answer', () => {
    const { container } = renderComponent(FAQAccordionComponent, {
      heading: 'FAQ',
      items: [
        { question: 'Q1', answer: 'A1' },
        { question: '', answer: 'A2' },
        { question: 'Q3', answer: '' },
      ],
    })
    const details = container.querySelectorAll('details')
    expect(details.length).toBe(1)
  })
})

/* -------------------------------------------------------------------------- */
/*  VideoEmbed                                                                */
/* -------------------------------------------------------------------------- */

describe('VideoEmbedComponent', () => {
  it('renders an iframe for a YouTube URL', () => {
    const { container } = renderComponent(VideoEmbedComponent, {
      url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
      title: 'Demo',
      poster: '',
      aspect: '16/9',
    })
    const iframe = container.querySelector('iframe')
    expect(iframe).not.toBeNull()
    expect(iframe?.getAttribute('src')).toContain('youtube.com/embed/')
    expect(iframe?.getAttribute('loading')).toBe('lazy')
  })

  it('renders an iframe for a Vimeo URL', () => {
    const { container } = renderComponent(VideoEmbedComponent, {
      url: 'https://vimeo.com/123456789',
      title: 'Demo',
      poster: '',
      aspect: '16/9',
    })
    const iframe = container.querySelector('iframe')
    expect(iframe).not.toBeNull()
    expect(iframe?.getAttribute('src')).toContain('player.vimeo.com/video/123456789')
  })

  it('renders a <video> element for direct MP4 URLs', () => {
    const { container } = renderComponent(VideoEmbedComponent, {
      url: 'https://example.com/clip.mp4',
      title: 'Clip',
      poster: 'https://example.com/poster.jpg',
      aspect: '16/9',
    })
    const video = container.querySelector('video')
    expect(video).not.toBeNull()
    // Source should reference the MP4 URL
    const source = video?.querySelector('source')
    expect(source?.getAttribute('src')).toBe('https://example.com/clip.mp4')
    expect(video?.getAttribute('poster')).toBe('https://example.com/poster.jpg')
  })

  it('shows a placeholder for unrecognised URLs', () => {
    const { container } = renderComponent(VideoEmbedComponent, {
      url: 'https://example.com/page.html',
      title: 'X',
      poster: '',
      aspect: '16/9',
    })
    expect(container.querySelector('iframe')).toBeNull()
    expect(container.querySelector('video')).toBeNull()
    expect(container.textContent).toMatch(/Unsupported|empty/i)
  })
})

/* -------------------------------------------------------------------------- */
/*  ImageBlock — srcset emission                                              */
/* -------------------------------------------------------------------------- */

describe('ImageBlockComponent', () => {
  it('emits srcset from variants and lazy-loads', () => {
    const { container } = renderComponent(ImageBlockComponent, {
      src: 'https://cdn/orig.jpg',
      alt: 'Hero photo',
      decorative: false,
      variants: [
        { url: 'https://cdn/640.webp', width: 640 },
        { url: 'https://cdn/1280.webp', width: 1280 },
      ],
      caption: '',
      width: 'wide',
      rounded: true,
    })
    const img = container.querySelector('img')
    expect(img).not.toBeNull()
    expect(img?.getAttribute('loading')).toBe('lazy')
    expect(img?.getAttribute('alt')).toBe('Hero photo')
    const srcset = img?.getAttribute('srcset') ?? ''
    expect(srcset).toContain('https://cdn/640.webp 640w')
    expect(srcset).toContain('https://cdn/1280.webp 1280w')
  })

  it('uses empty alt and presentation role when decorative', () => {
    const { container } = renderComponent(ImageBlockComponent, {
      src: 'https://cdn/orig.jpg',
      alt: 'ignored when decorative',
      decorative: true,
      variants: [],
      caption: '',
      width: 'wide',
      rounded: false,
    })
    const img = container.querySelector('img')
    expect(img?.getAttribute('alt')).toBe('')
    expect(img?.getAttribute('role')).toBe('presentation')
  })
})

/* -------------------------------------------------------------------------- */
/*  HeadingComponent — single-H1 demotion (Requirement 7.4)                   */
/* -------------------------------------------------------------------------- */

describe('HeadingComponent single-H1 enforcement', () => {
  it('renders the first H1 as <h1> and demotes the second to <h2>', () => {
    const first = render(
      <>{HeadingComponent.render({ level: 1, text: 'First', align: 'left' })}</>,
    )
    const second = render(
      <>{HeadingComponent.render({ level: 1, text: 'Second', align: 'left' })}</>,
    )
    expect(first.container.querySelector('h1')?.textContent).toBe('First')
    // The second H1 should have been demoted to H2 by the shared counter
    expect(second.container.querySelector('h1')).toBeNull()
    expect(second.container.querySelector('h2')?.textContent).toBe('Second')
  })

  it('respects level override for non-H1 headings', () => {
    const { container } = render(
      <>{HeadingComponent.render({ level: 3, text: 'Subhead', align: 'left' })}</>,
    )
    expect(container.querySelector('h3')?.textContent).toBe('Subhead')
  })
})
