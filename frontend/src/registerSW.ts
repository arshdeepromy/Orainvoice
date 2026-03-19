export function registerServiceWorker(): void {
  // Service worker is not yet implemented — skip registration.
  // Attempting to register a non-existent /service-worker.js causes
  // nginx's SPA fallback to return index.html (text/html), which the
  // browser rejects with "unsupported MIME type" and logs a console error.
}
