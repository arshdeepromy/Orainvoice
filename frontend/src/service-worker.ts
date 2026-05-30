/// <reference lib="webworker" />

declare const self: ServiceWorkerGlobalScope

// __APP_VERSION__ is injected by Vite at build time from package.json.
// Embedding the version into the cache name ensures every deploy
// invalidates the previous cache (old workers + cached assets are
// dropped on activate). Falls back to a sentinel for the dev-watcher
// transformation step that runs before the define replacement.
declare const __APP_VERSION__: string
const APP_VERSION = (typeof __APP_VERSION__ !== 'undefined') ? __APP_VERSION__ : 'dev'
const CACHE_NAME = `workshoppro-${APP_VERSION}`

const PRECACHE_ASSETS = [
  '/',
  '/manifest.json',
]

// Install: precache critical assets
self.addEventListener('install', (event: ExtendableEvent) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_ASSETS)),
  )
  // skipWaiting tells the browser to replace any older active worker as soon
  // as this one finishes installing. Combined with clients.claim() in
  // activate, deploy → user-sees-new-bundle is bounded to one tab refresh.
  self.skipWaiting()
})

// Activate: clean up old caches that don't match the current version.
self.addEventListener('activate', (event: ExtendableEvent) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key)),
      ),
    ),
  )
  self.clients.claim()
})

// Fetch: never cache /api or /fleet/api; cache-first for hashed static assets;
// network-first for navigations with a cache fallback when offline.
self.addEventListener('fetch', (event: FetchEvent) => {
  const { request } = event
  const url = new URL(request.url)

  // Skip non-GET requests entirely.
  if (request.method !== 'GET') return

  // Cross-origin requests are passed through untouched.
  if (url.origin !== self.location.origin) return

  // API requests: network only (bypass cache layer).
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/fleet/api')) return

  // Service worker MUST NOT cache itself or the manifest with a stale entry.
  // The browser handles SW cache-busting per the spec; let it through.
  if (url.pathname === '/service-worker.js') return

  // Static assets (JS, CSS, images, fonts): cache-first.
  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(request))
    return
  }

  // Navigation requests: network-first with cache fallback.
  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request))
    return
  }
})

function isStaticAsset(pathname: string): boolean {
  return /\.(js|css|png|jpg|jpeg|svg|gif|woff2?|ttf|eot|ico)$/i.test(pathname)
}

async function cacheFirst(request: Request): Promise<Response> {
  const cached = await caches.match(request)
  if (cached) return cached

  const response = await fetch(request)
  if (response.ok) {
    const cache = await caches.open(CACHE_NAME)
    cache.put(request, response.clone())
  }
  return response
}

async function networkFirst(request: Request): Promise<Response> {
  try {
    const response = await fetch(request)
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME)
      cache.put(request, response.clone())
    }
    return response
  } catch {
    const cached = await caches.match(request)
    return cached || new Response('Offline', { status: 503 })
  }
}

export {}
