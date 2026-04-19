/**
 * Property-based tests for invoice template style resolution.
 *
 * Uses fast-check with Vitest. Each property runs a minimum of 100 iterations.
 */
import { describe, it, expect } from 'vitest'
import fc from 'fast-check'

import {
  resolveTemplateStyles,
  isDarkColour,
  TEMPLATE_STYLES,
} from '../invoiceTemplateStyles'

const NUM_RUNS = 100

/** Arbitrary that produces valid 6-digit hex colour strings (e.g. "#a3f1b2"). */
const hexArb = fc
  .tuple(
    fc.integer({ min: 0, max: 255 }),
    fc.integer({ min: 0, max: 255 }),
    fc.integer({ min: 0, max: 255 }),
  )
  .map(
    ([r, g, b]) =>
      '#' +
      r.toString(16).padStart(2, '0') +
      g.toString(16).padStart(2, '0') +
      b.toString(16).padStart(2, '0'),
  )

const templateIds = Object.keys(TEMPLATE_STYLES)

describe('Invoice Template Style Properties', () => {
  /**
   * Property 2: Colour override precedence
   *
   * For any valid template ID and for any combination of colour overrides
   * (where each of primary_colour, accent_colour, header_bg_colour may be
   * a valid hex string or null/undefined), calling resolveTemplateStyles
   * SHALL return the override value when the override is a non-empty hex
   * string, and the template's default value when the override is null,
   * undefined, or empty.
   *
   * **Validates: Requirements 2.4, 3.5, 7.2**
   */
  it('Property 2: Colour override precedence', () => {
    fc.assert(
      fc.property(
        fc.record({
          templateId: fc.constantFrom(...templateIds),
          overrides: fc.record({
            primary_colour: fc.option(hexArb, { nil: null }),
            accent_colour: fc.option(hexArb, { nil: null }),
            header_bg_colour: fc.option(hexArb, { nil: null }),
          }),
        }),
        ({ templateId, overrides }) => {
          const template = TEMPLATE_STYLES[templateId]
          const result = resolveTemplateStyles(templateId, overrides)

          // Primary colour: override wins when non-empty, template default otherwise
          if (
            overrides.primary_colour !== null &&
            overrides.primary_colour !== undefined &&
            overrides.primary_colour.length > 0
          ) {
            expect(result.primaryColour).toBe(overrides.primary_colour)
          } else {
            expect(result.primaryColour).toBe(template.primaryColour)
          }

          // Accent colour: override wins when non-empty, template default otherwise
          if (
            overrides.accent_colour !== null &&
            overrides.accent_colour !== undefined &&
            overrides.accent_colour.length > 0
          ) {
            expect(result.accentColour).toBe(overrides.accent_colour)
          } else {
            expect(result.accentColour).toBe(template.accentColour)
          }

          // Header BG colour: override wins when non-empty, template default otherwise
          if (
            overrides.header_bg_colour !== null &&
            overrides.header_bg_colour !== undefined &&
            overrides.header_bg_colour.length > 0
          ) {
            expect(result.headerBgColour).toBe(overrides.header_bg_colour)
          } else {
            expect(result.headerBgColour).toBe(template.headerBgColour)
          }

          // Layout and logo position always come from the template (not overridable)
          expect(result.logoPosition).toBe(template.logoPosition)
          expect(result.layoutType).toBe(template.layoutType)
        },
      ),
      { numRuns: NUM_RUNS },
    )
  })

  /**
   * Property 3: Fallback to default for unknown template IDs
   *
   * For any string that is not a key in the TEMPLATE_STYLES map (including
   * empty string and null), calling resolveTemplateStyles SHALL return a
   * style object whose colour values equal the default template's colours
   * (#3b5bdb primary, #3b5bdb accent, #ffffff header background).
   *
   * **Validates: Requirements 2.5, 3.6**
   */
  it('Property 3: Fallback to default for unknown template IDs', () => {
    const defaultStyles = TEMPLATE_STYLES['default']

    const unknownIdArb = fc.oneof(
      fc.string().filter((s) => !templateIds.includes(s)),
      fc.constant(null as string | null | undefined),
      fc.constant(undefined as string | null | undefined),
    )

    fc.assert(
      fc.property(unknownIdArb, (unknownId) => {
        const result = resolveTemplateStyles(unknownId)

        // Colour values must equal the default template
        expect(result.primaryColour).toBe(defaultStyles.primaryColour)
        expect(result.accentColour).toBe(defaultStyles.accentColour)
        expect(result.headerBgColour).toBe(defaultStyles.headerBgColour)

        // Layout properties must also match the default template
        expect(result.logoPosition).toBe(defaultStyles.logoPosition)
        expect(result.layoutType).toBe(defaultStyles.layoutType)

        // Verify the actual default values as specified
        expect(result.primaryColour).toBe('#3b5bdb')
        expect(result.accentColour).toBe('#3b5bdb')
        expect(result.headerBgColour).toBe('#ffffff')
      }),
      { numRuns: NUM_RUNS },
    )
  })

  /**
   * Property 4: Dark colour detection correctness
   *
   * For any valid 6-digit hex colour string, isDarkColour SHALL return true
   * when the sRGB relative luminance is below 0.5, and false when the
   * luminance is 0.5 or above. The luminance is computed as
   * 0.2126 * R_lin + 0.7152 * G_lin + 0.0722 * B_lin where each channel
   * is linearised from sRGB.
   *
   * **Validates: Requirements 6.1, 6.2, 6.3**
   */
  it('Property 4: Dark colour detection correctness', () => {
    /** Independently compute sRGB relative luminance from R, G, B (0–255). */
    function expectedLuminance(r: number, g: number, b: number): number {
      const sr = r / 255
      const sg = g / 255
      const sb = b / 255

      const rLin = sr <= 0.04045 ? sr / 12.92 : Math.pow((sr + 0.055) / 1.055, 2.4)
      const gLin = sg <= 0.04045 ? sg / 12.92 : Math.pow((sg + 0.055) / 1.055, 2.4)
      const bLin = sb <= 0.04045 ? sb / 12.92 : Math.pow((sb + 0.055) / 1.055, 2.4)

      return 0.2126 * rLin + 0.7152 * gLin + 0.0722 * bLin
    }

    fc.assert(
      fc.property(
        fc.tuple(
          fc.integer({ min: 0, max: 255 }),
          fc.integer({ min: 0, max: 255 }),
          fc.integer({ min: 0, max: 255 }),
        ),
        ([r, g, b]) => {
          const hex =
            '#' +
            r.toString(16).padStart(2, '0') +
            g.toString(16).padStart(2, '0') +
            b.toString(16).padStart(2, '0')

          const luminance = expectedLuminance(r, g, b)
          const expectedDark = luminance < 0.5

          expect(isDarkColour(hex)).toBe(expectedDark)
        },
      ),
      { numRuns: NUM_RUNS },
    )
  })
})


describe('Unit Tests', () => {
  /**
   * Unit tests for resolveTemplateStyles and isDarkColour.
   *
   * **Validates: Requirements 2.4, 2.5, 6.1, 6.2, 6.3**
   */

  // ---------------------------------------------------------------------------
  // resolveTemplateStyles
  // ---------------------------------------------------------------------------

  describe('resolveTemplateStyles', () => {
    it('returns default blue styles when templateId is null', () => {
      const result = resolveTemplateStyles(null)

      expect(result.primaryColour).toBe('#3b5bdb')
      expect(result.accentColour).toBe('#3b5bdb')
      expect(result.headerBgColour).toBe('#ffffff')
      expect(result.logoPosition).toBe('left')
      expect(result.layoutType).toBe('standard')
      expect(result.isHeaderDark).toBe(false)
    })

    it('returns correct indigo colours for modern-dark template', () => {
      const result = resolveTemplateStyles('modern-dark')

      expect(result.primaryColour).toBe('#6366f1')
      expect(result.accentColour).toBe('#4f46e5')
      expect(result.headerBgColour).toBe('#1e1b4b')
      expect(result.logoPosition).toBe('left')
      expect(result.layoutType).toBe('standard')
      expect(result.isHeaderDark).toBe(true)
    })

    it('applies colour override while keeping other template defaults', () => {
      const result = resolveTemplateStyles('modern-dark', {
        primary_colour: '#ff0000',
      })

      expect(result.primaryColour).toBe('#ff0000')
      // accent and header bg should remain template defaults
      expect(result.accentColour).toBe('#4f46e5')
      expect(result.headerBgColour).toBe('#1e1b4b')
    })

    it('falls back to default styles for unknown template ID', () => {
      const result = resolveTemplateStyles('unknown-id')

      expect(result.primaryColour).toBe('#3b5bdb')
      expect(result.accentColour).toBe('#3b5bdb')
      expect(result.headerBgColour).toBe('#ffffff')
      expect(result.logoPosition).toBe('left')
      expect(result.layoutType).toBe('standard')
    })

    it('returns compact layoutType for compact templates', () => {
      expect(resolveTemplateStyles('compact-blue').layoutType).toBe('compact')
      expect(resolveTemplateStyles('compact-green').layoutType).toBe('compact')
      expect(resolveTemplateStyles('compact-mono').layoutType).toBe('compact')
    })

    it('returns correct logoPosition for each variant', () => {
      // left
      expect(resolveTemplateStyles('default').logoPosition).toBe('left')
      expect(resolveTemplateStyles('classic').logoPosition).toBe('left')
      expect(resolveTemplateStyles('ocean').logoPosition).toBe('left')

      // center
      expect(resolveTemplateStyles('bold-header').logoPosition).toBe('center')
      expect(resolveTemplateStyles('corporate').logoPosition).toBe('center')
      expect(resolveTemplateStyles('elegant').logoPosition).toBe('center')

      // side
      expect(resolveTemplateStyles('trade-pro').logoPosition).toBe('side')
      expect(resolveTemplateStyles('compact-mono').logoPosition).toBe('side')
      expect(resolveTemplateStyles('sunrise').logoPosition).toBe('side')
    })
  })

  // ---------------------------------------------------------------------------
  // isDarkColour
  // ---------------------------------------------------------------------------

  describe('isDarkColour', () => {
    it('returns true for dark indigo (#1e1b4b)', () => {
      expect(isDarkColour('#1e1b4b')).toBe(true)
    })

    it('returns false for white (#ffffff)', () => {
      expect(isDarkColour('#ffffff')).toBe(false)
    })

    it('returns true for gray boundary (#808080) — luminance ~0.216', () => {
      expect(isDarkColour('#808080')).toBe(true)
    })

    it('returns false for invalid hex string', () => {
      expect(isDarkColour('invalid')).toBe(false)
    })
  })
})
