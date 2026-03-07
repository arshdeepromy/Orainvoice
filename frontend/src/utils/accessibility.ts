/**
 * Accessibility utilities for WorkshopPro NZ.
 * Provides focus management, skip navigation, contrast checking,
 * and screen reader announcement helpers.
 *
 * Validates: Requirements 57.1, 57.2, 57.3, 57.4
 */

// ---------------------------------------------------------------------------
// Focus management
// ---------------------------------------------------------------------------

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

/**
 * Returns all focusable elements within a container.
 */
export function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
}

/**
 * Traps keyboard focus within a container element (e.g. a modal dialog).
 * Returns a cleanup function to remove the event listener.
 */
export function trapFocus(container: HTMLElement): () => void {
  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'Tab') return

    const focusable = getFocusableElements(container)
    if (focusable.length === 0) return

    const first = focusable[0]
    const last = focusable[focusable.length - 1]

    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault()
        last.focus()
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  container.addEventListener('keydown', handleKeyDown)
  return () => container.removeEventListener('keydown', handleKeyDown)
}

/**
 * Saves the currently focused element and returns a function to restore focus.
 * Useful when opening modals or dialogs.
 */
export function saveFocus(): () => void {
  const previousElement = document.activeElement as HTMLElement | null
  return () => previousElement?.focus()
}

// ---------------------------------------------------------------------------
// Skip navigation
// ---------------------------------------------------------------------------

/**
 * Moves focus to the element matching the given selector (typically #main-content).
 * Used by the SkipLink component.
 */
export function skipToContent(targetId: string): void {
  const target = document.getElementById(targetId)
  if (target) {
    target.setAttribute('tabindex', '-1')
    target.focus()
    // Remove tabindex after blur so it doesn't interfere with normal tab order
    target.addEventListener('blur', () => target.removeAttribute('tabindex'), { once: true })
  }
}

// ---------------------------------------------------------------------------
// Contrast ratio checker
// ---------------------------------------------------------------------------

/**
 * Parses a hex colour string (#RGB or #RRGGBB) into [r, g, b] values (0–255).
 */
export function parseHexColour(hex: string): [number, number, number] {
  const cleaned = hex.replace('#', '')
  if (cleaned.length === 3) {
    return [
      parseInt(cleaned[0] + cleaned[0], 16),
      parseInt(cleaned[1] + cleaned[1], 16),
      parseInt(cleaned[2] + cleaned[2], 16),
    ]
  }
  return [
    parseInt(cleaned.slice(0, 2), 16),
    parseInt(cleaned.slice(2, 4), 16),
    parseInt(cleaned.slice(4, 6), 16),
  ]
}

/**
 * Calculates the relative luminance of a colour per WCAG 2.1.
 * https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
 */
export function relativeLuminance(r: number, g: number, b: number): number {
  const [rs, gs, bs] = [r, g, b].map((c) => {
    const sRGB = c / 255
    return sRGB <= 0.03928 ? sRGB / 12.92 : Math.pow((sRGB + 0.055) / 1.055, 2.4)
  })
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs
}

/**
 * Calculates the contrast ratio between two colours.
 * Returns a value between 1 and 21.
 */
export function contrastRatio(hex1: string, hex2: string): number {
  const l1 = relativeLuminance(...parseHexColour(hex1))
  const l2 = relativeLuminance(...parseHexColour(hex2))
  const lighter = Math.max(l1, l2)
  const darker = Math.min(l1, l2)
  return (lighter + 0.05) / (darker + 0.05)
}

/**
 * Checks whether a foreground/background colour pair meets WCAG 2.1 AA.
 * Normal text requires 4.5:1, large text (≥18pt or ≥14pt bold) requires 3:1.
 */
export function meetsContrastAA(
  foreground: string,
  background: string,
  isLargeText = false,
): boolean {
  const ratio = contrastRatio(foreground, background)
  return isLargeText ? ratio >= 3 : ratio >= 4.5
}

// ---------------------------------------------------------------------------
// Screen reader announcements (live region)
// ---------------------------------------------------------------------------

let liveRegion: HTMLElement | null = null

function ensureLiveRegion(): HTMLElement {
  if (liveRegion && document.body.contains(liveRegion)) return liveRegion

  liveRegion = document.createElement('div')
  liveRegion.setAttribute('role', 'status')
  liveRegion.setAttribute('aria-live', 'polite')
  liveRegion.setAttribute('aria-atomic', 'true')
  liveRegion.className = 'sr-only'
  liveRegion.style.cssText =
    'position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0'
  document.body.appendChild(liveRegion)
  return liveRegion
}

/**
 * Announces a message to screen readers via a live region.
 * Uses `aria-live="polite"` by default; pass `assertive` for urgent messages.
 */
export function announce(message: string, priority: 'polite' | 'assertive' = 'polite'): void {
  const region = ensureLiveRegion()
  region.setAttribute('aria-live', priority)
  // Clear then set to ensure the announcement fires even for repeated messages
  region.textContent = ''
  requestAnimationFrame(() => {
    region.textContent = message
  })
}
