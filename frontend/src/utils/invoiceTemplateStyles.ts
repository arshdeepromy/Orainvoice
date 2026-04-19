/**
 * Template style map for the in-browser invoice preview.
 *
 * Mirrors the backend `app/modules/invoices/template_registry.py` — every
 * template ID and its default colours / layout must stay in sync with the
 * Python registry.
 */

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

/** Style definition for a single invoice template. */
export interface TemplateStyle {
  primaryColour: string
  accentColour: string
  headerBgColour: string
  logoPosition: 'left' | 'center' | 'side'
  layoutType: 'standard' | 'compact'
}

/** Colour overrides from org settings (snake_case to match backend). */
export interface ColourOverrides {
  primary_colour?: string | null
  accent_colour?: string | null
  header_bg_colour?: string | null
}

/** Resolved styles ready for JSX consumption. */
export interface ResolvedInvoiceStyles {
  primaryColour: string
  accentColour: string
  headerBgColour: string
  logoPosition: 'left' | 'center' | 'side'
  layoutType: 'standard' | 'compact'
  isHeaderDark: boolean
}

// ---------------------------------------------------------------------------
// Template registry — 13 entries matching template_registry.py exactly
// ---------------------------------------------------------------------------

export const TEMPLATE_STYLES: Record<string, TemplateStyle> = {
  default: {
    primaryColour: '#3b5bdb',
    accentColour: '#3b5bdb',
    headerBgColour: '#ffffff',
    logoPosition: 'left',
    layoutType: 'standard',
  },
  classic: {
    primaryColour: '#2563eb',
    accentColour: '#1e40af',
    headerBgColour: '#ffffff',
    logoPosition: 'left',
    layoutType: 'standard',
  },
  'modern-dark': {
    primaryColour: '#6366f1',
    accentColour: '#4f46e5',
    headerBgColour: '#1e1b4b',
    logoPosition: 'left',
    layoutType: 'standard',
  },
  'compact-blue': {
    primaryColour: '#0284c7',
    accentColour: '#0369a1',
    headerBgColour: '#f0f9ff',
    logoPosition: 'left',
    layoutType: 'compact',
  },
  'bold-header': {
    primaryColour: '#dc2626',
    accentColour: '#b91c1c',
    headerBgColour: '#1a1a1a',
    logoPosition: 'center',
    layoutType: 'standard',
  },
  minimal: {
    primaryColour: '#374151',
    accentColour: '#6b7280',
    headerBgColour: '#ffffff',
    logoPosition: 'left',
    layoutType: 'standard',
  },
  'trade-pro': {
    primaryColour: '#059669',
    accentColour: '#047857',
    headerBgColour: '#ecfdf5',
    logoPosition: 'side',
    layoutType: 'standard',
  },
  corporate: {
    primaryColour: '#1e3a5f',
    accentColour: '#2563eb',
    headerBgColour: '#f8fafc',
    logoPosition: 'center',
    layoutType: 'standard',
  },
  'compact-green': {
    primaryColour: '#16a34a',
    accentColour: '#15803d',
    headerBgColour: '#f0fdf4',
    logoPosition: 'left',
    layoutType: 'compact',
  },
  elegant: {
    primaryColour: '#7c3aed',
    accentColour: '#6d28d9',
    headerBgColour: '#faf5ff',
    logoPosition: 'center',
    layoutType: 'standard',
  },
  'compact-mono': {
    primaryColour: '#1a1a1a',
    accentColour: '#525252',
    headerBgColour: '#fafafa',
    logoPosition: 'side',
    layoutType: 'compact',
  },
  sunrise: {
    primaryColour: '#ea580c',
    accentColour: '#c2410c',
    headerBgColour: '#fff7ed',
    logoPosition: 'side',
    layoutType: 'standard',
  },
  ocean: {
    primaryColour: '#0891b2',
    accentColour: '#0e7490',
    headerBgColour: '#ecfeff',
    logoPosition: 'left',
    layoutType: 'standard',
  },
}

// ---------------------------------------------------------------------------
// Utility — sRGB relative luminance
// ---------------------------------------------------------------------------

/**
 * Linearise a single sRGB channel value (0–1) to linear light.
 */
function linearise(c: number): number {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

/**
 * Determine whether a hex colour is "dark" (relative luminance < 0.5).
 *
 * Uses the standard sRGB relative luminance formula:
 *   L = 0.2126·R + 0.7152·G + 0.0722·B
 * where each channel is linearised from sRGB.
 *
 * Returns `false` for invalid hex strings (safe fallback — assumes light).
 */
export function isDarkColour(hex: string): boolean {
  if (typeof hex !== 'string') return false

  const cleaned = hex.startsWith('#') ? hex.slice(1) : hex
  if (!/^[0-9a-fA-F]{6}$/.test(cleaned)) return false

  const r = parseInt(cleaned.slice(0, 2), 16) / 255
  const g = parseInt(cleaned.slice(2, 4), 16) / 255
  const b = parseInt(cleaned.slice(4, 6), 16) / 255

  const luminance =
    0.2126 * linearise(r) + 0.7152 * linearise(g) + 0.0722 * linearise(b)

  return luminance < 0.5
}

// ---------------------------------------------------------------------------
// Resolver
// ---------------------------------------------------------------------------

/**
 * Resolve template styles with optional colour overrides.
 *
 * Precedence: colour override (non-empty string) > template default > 'default' template fallback.
 */
export function resolveTemplateStyles(
  templateId: string | null | undefined,
  colourOverrides?: ColourOverrides | null,
): ResolvedInvoiceStyles {
  const template =
    (templateId ? TEMPLATE_STYLES[templateId] : undefined) ??
    TEMPLATE_STYLES['default']

  const primaryColour =
    colourOverrides?.primary_colour && colourOverrides.primary_colour.length > 0
      ? colourOverrides.primary_colour
      : template.primaryColour

  const accentColour =
    colourOverrides?.accent_colour && colourOverrides.accent_colour.length > 0
      ? colourOverrides.accent_colour
      : template.accentColour

  const headerBgColour =
    colourOverrides?.header_bg_colour &&
    colourOverrides.header_bg_colour.length > 0
      ? colourOverrides.header_bg_colour
      : template.headerBgColour

  return {
    primaryColour,
    accentColour,
    headerBgColour,
    logoPosition: template.logoPosition,
    layoutType: template.layoutType,
    isHeaderDark: isDarkColour(headerBgColour),
  }
}
