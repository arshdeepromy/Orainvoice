/// <reference types="vite/client" />

// Injected at build time from mobile/package.json `version` via vite `define`.
// Semantic version (MAJOR.MINOR.PATCH) surfaced in Settings → About (R19.4).
declare const __APP_VERSION__: string
