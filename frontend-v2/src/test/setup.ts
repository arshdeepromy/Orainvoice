import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

// jsdom doesn't implement ResizeObserver, which Headless UI v2 (Menu/Popover)
// uses internally for anchor positioning. Provide a no-op polyfill so those
// components mount cleanly under test.
if (!('ResizeObserver' in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}

// jsdom also lacks scrollIntoView (Headless UI scrolls the active item).
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn()
}

// Unmount React trees and reset jsdom between tests so component state and the
// DOM don't leak across cases.
afterEach(() => {
  cleanup()
})
