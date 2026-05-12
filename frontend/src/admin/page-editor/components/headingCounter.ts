/**
 * Single-H1 enforcement helper.
 *
 * Per design doc and Requirement 7.4, a rendered page must have at most
 * one `<h1>` element. Puck components render independently and have no
 * shared state, so we use a module-level counter keyed on a window flag.
 *
 * PageShell (task 8.4) is responsible for resetting `__puckH1Seen` to
 * `false` at the start of each page render. In SSR/test environments
 * where `window` is undefined we fall back to a plain module variable,
 * which is fine for unit tests (each test resets state explicitly).
 */

declare global {
  // eslint-disable-next-line no-var
  var __puckH1Seen: boolean | undefined
}

let moduleH1Seen = false

function canUseWindow(): boolean {
  return typeof window !== 'undefined'
}

/**
 * Returns true if this component should render its heading as `<h1>`.
 * The first caller on a given page render gets `true`; every subsequent
 * caller gets `false` (they should demote to `<h2>`).
 */
export function shouldEmitH1(): boolean {
  if (canUseWindow()) {
    return window.__puckH1Seen !== true
  }
  return !moduleH1Seen
}

/**
 * Marks that an `<h1>` has been emitted on the current page render.
 * Subsequent calls to `shouldEmitH1` will return `false` until
 * `resetH1Counter` is called.
 */
export function markH1Seen(): void {
  if (canUseWindow()) {
    window.__puckH1Seen = true
  } else {
    moduleH1Seen = true
  }
}

/**
 * Resets the single-H1 counter. PageShell calls this at the start of
 * every page render so that each render gets a fresh counter.
 */
export function resetH1Counter(): void {
  if (canUseWindow()) {
    window.__puckH1Seen = false
  }
  moduleH1Seen = false
}
