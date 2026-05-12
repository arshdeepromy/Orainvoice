/**
 * Property 6: Single H1 Enforcement
 *
 * Generate random Puck_Data with varying H1 counts and verify the
 * rendered output contains at most one `<h1>` element.
 *
 * The enforcement is implemented in `Heading.tsx` and `Hero.tsx` via
 * the shared `headingCounter` module (`shouldEmitH1()` +
 * `markH1Seen()`). This test validates the contract by generating
 * random heading sequences — including mixes of Heading + Hero — and
 * asserting the rendered DOM never has more than one `<h1>`.
 *
 * Validates: Requirements 7.4
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import fc from 'fast-check'
import {
  HeadingComponent,
  HeroComponent,
  resetH1Counter,
  type HeadingProps,
  type HeroProps,
} from '../components'

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

const headingPropsArb: fc.Arbitrary<HeadingProps> = fc.record({
  level: fc.integer({ min: 1, max: 6 }) as fc.Arbitrary<HeadingProps['level']>,
  text: fc.string({ minLength: 1, maxLength: 20 }).filter((s) => s.trim().length > 0),
  align: fc.constantFrom<HeadingProps['align']>('left', 'center', 'right'),
})

// Generator biased toward H1 so the "enforcement" branch is exercised
// more often. Without this bias most random draws would land on H2-H6
// and the H1-cap logic would rarely fire.
const h1HeavyHeadingPropsArb: fc.Arbitrary<HeadingProps> = fc.record({
  level: fc.oneof(
    { weight: 3, arbitrary: fc.constant(1 as const) },
    { weight: 1, arbitrary: fc.constantFrom(2, 3, 4, 5, 6) as fc.Arbitrary<HeadingProps['level']> },
  ),
  text: fc.string({ minLength: 1, maxLength: 20 }).filter((s) => s.trim().length > 0),
  align: fc.constantFrom<HeadingProps['align']>('left', 'center', 'right'),
})

const heroPropsArb: fc.Arbitrary<HeroProps> = fc.record({
  eyebrow: fc.string({ maxLength: 20 }),
  heading: fc.string({ minLength: 1, maxLength: 40 }).filter((s) => s.trim().length > 0),
  subtext: fc.string({ maxLength: 80 }),
  ctas: fc.constant([]),
  trustBadges: fc.constant([]),
})

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/**
 * Puck component render functions are typed as `PuckComponent<Props>`
 * which includes Puck-injected props (`puck`, `id`). In a non-editor
 * context we only provide the user-authored props; the components in
 * this codebase never read `puck.*` or `id`, so an unchecked cast is
 * safe for testing.
 */
function renderHeading(props: HeadingProps) {
  const Component = HeadingComponent.render as (p: unknown) => JSX.Element
  return Component(props)
}

function renderHero(props: HeroProps) {
  const Component = HeroComponent.render as (p: unknown) => JSX.Element
  return Component(props)
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('Single H1 enforcement (Property 6)', () => {
  beforeEach(() => {
    resetH1Counter()
    cleanup()
  })

  it('never emits more than one h1 across random Heading sequences', () => {
    fc.assert(
      fc.property(fc.array(headingPropsArb, { maxLength: 20 }), (headings) => {
        resetH1Counter()
        const { container } = render(
          <div>
            {headings.map((h, i) => (
              <div key={i}>{renderHeading(h)}</div>
            ))}
          </div>,
        )
        const h1s = container.querySelectorAll('h1')
        return h1s.length <= 1
      }),
      { numRuns: 100 },
    )
  })

  it('never emits more than one h1 for H1-heavy Heading sequences', () => {
    // H1-heavy generator ensures we exercise the demotion branch in
    // most runs, not just the "no H1 requested" branch.
    fc.assert(
      fc.property(
        fc.array(h1HeavyHeadingPropsArb, { minLength: 1, maxLength: 20 }),
        (headings) => {
          resetH1Counter()
          const { container } = render(
            <div>
              {headings.map((h, i) => (
                <div key={i}>{renderHeading(h)}</div>
              ))}
            </div>,
          )
          const h1s = container.querySelectorAll('h1')
          return h1s.length <= 1
        },
      ),
      { numRuns: 100 },
    )
  })

  it('emits exactly one h1 when at least one Heading requests level=1', () => {
    // Stronger property: if any heading in the list requests H1, the
    // output should have exactly one h1 (the first one wins, the rest
    // are demoted to h2).
    fc.assert(
      fc.property(
        fc.array(h1HeavyHeadingPropsArb, { minLength: 1, maxLength: 20 }),
        (headings) => {
          const hasH1Request = headings.some((h) => h.level === 1)
          fc.pre(hasH1Request)
          resetH1Counter()
          const { container } = render(
            <div>
              {headings.map((h, i) => (
                <div key={i}>{renderHeading(h)}</div>
              ))}
            </div>,
          )
          const h1s = container.querySelectorAll('h1')
          return h1s.length === 1
        },
      ),
      { numRuns: 100 },
    )
  })

  it('never emits more than one h1 when mixing Hero and Heading components', () => {
    // Hero also emits an h1 via the shared headingCounter. When a page
    // contains a Hero plus multiple H1-requesting Headings, total h1
    // count must still be ≤ 1.
    fc.assert(
      fc.property(
        fc.array(heroPropsArb, { minLength: 1, maxLength: 3 }),
        fc.array(h1HeavyHeadingPropsArb, { maxLength: 10 }),
        (heroes, headings) => {
          resetH1Counter()
          const { container } = render(
            <div>
              {heroes.map((hero, i) => (
                <div key={`hero-${i}`}>{renderHero(hero)}</div>
              ))}
              {headings.map((h, i) => (
                <div key={`heading-${i}`}>{renderHeading(h)}</div>
              ))}
            </div>,
          )
          const h1s = container.querySelectorAll('h1')
          return h1s.length <= 1
        },
      ),
      { numRuns: 100 },
    )
  })

  it('emits zero h1 elements when no Heading requests level=1 and no Hero is present', () => {
    // Negative property: without any H1 source, output has zero h1s.
    const nonH1HeadingArb: fc.Arbitrary<HeadingProps> = fc.record({
      level: fc.constantFrom(2, 3, 4, 5, 6) as fc.Arbitrary<HeadingProps['level']>,
      text: fc.string({ minLength: 1, maxLength: 20 }).filter((s) => s.trim().length > 0),
      align: fc.constantFrom<HeadingProps['align']>('left', 'center', 'right'),
    })
    fc.assert(
      fc.property(fc.array(nonH1HeadingArb, { maxLength: 20 }), (headings) => {
        resetH1Counter()
        const { container } = render(
          <div>
            {headings.map((h, i) => (
              <div key={i}>{renderHeading(h)}</div>
            ))}
          </div>,
        )
        const h1s = container.querySelectorAll('h1')
        return h1s.length === 0
      }),
      { numRuns: 100 },
    )
  })
})
