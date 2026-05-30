/**
 * Register the production service worker.
 *
 * Behaviour matches the contract documented in
 * `frontend/src/__tests__/pwa.test.tsx`:
 *
 *   - registers `/service-worker.js` on the window `load` event
 *   - silently no-ops when `navigator.serviceWorker` is unavailable
 *     (older browsers, some webviews, in-memory test envs)
 *   - swallows registration errors so a failure here never crashes
 *     the app shell
 *
 * Why register on `load` rather than at module import time: the install
 * fetch races the initial app fetch on slow links. Deferring to `load`
 * means the user-visible app is fully loaded before the worker starts
 * eating bandwidth.
 *
 * PERFORMANCE_AUDIT.md §F-H5 / §1 quick win #5.
 */
export function registerServiceWorker(): void {
  if (typeof navigator === 'undefined' || !navigator.serviceWorker) {
    // No service worker support — older browser or insecure context.
    return
  }

  // Defer registration until the page has finished loading. Avoids
  // contention with the initial app fetch.
  //
  // In Vite dev, `/service-worker.js` is not emitted; the request
  // 404s and falls through to nginx's SPA fallback returning
  // `index.html` (text/html). The browser logs an "unsupported MIME
  // type" warning per reload but the catch handler below keeps the
  // app shell working. Production builds emit the file at the right
  // path and the registration succeeds silently.
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/service-worker.js')
      .catch((err) => {
        // Non-fatal: log so we can spot regressions in dev tools without
        // breaking the app shell.
        // eslint-disable-next-line no-console
        console.warn('Service worker registration failed:', err)
      })
  })
}
