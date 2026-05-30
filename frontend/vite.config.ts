import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

// Read version from package.json (single source of truth)
const version = (() => {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'))
    if (pkg.version) return pkg.version
  } catch { /* ignore */ }
  return 'dev'
})()

const isProd = process.env.NODE_ENV === 'production'

/**
 * Strip console.* and debugger statements from production app code.
 *
 * Vite 8 uses rolldown + oxc, which currently ignores esbuild-style
 * `drop: ['console','debugger']` config. This plugin does the same job
 * via a regex pass on .ts/.tsx/.js/.jsx sources during the production
 * build only. Dev keeps console.* intact for debugging.
 *
 * Why: prevents leaking search queries, response bodies, and internal
 * state on public pages (portal, payment, kiosk) to anyone with DevTools
 * open. PERFORMANCE_AUDIT.md §F-H6.
 *
 * Scope: only matches statement-position calls (line-leading or after
 * `;`/`{`/newline) so we don't accidentally rewrite `(console.log)(x)`
 * inside complex expressions. We also skip node_modules to avoid
 * touching third-party code that may rely on console for warnings.
 */
function stripConsoleInProduction(): Plugin {
  const exts = /\.(?:[mc]?[jt]sx?)$/
  // Statement-position console.X(...) — including chained args and
  // multiline calls. Conservative: requires the call to terminate with
  // a closing paren on the same logical statement.
  const consoleStmt = /(^|[\s;{}])console\.(log|debug|info|warn|trace|dir|table|time|timeEnd|timeLog|count|countReset|group|groupEnd|groupCollapsed|profile|profileEnd|assert)\s*\([^;]*?\)\s*;?/gm
  // Bare debugger;
  const debuggerStmt = /(^|[\s;{}])debugger\s*;?/g
  return {
    name: 'orainvoice:strip-console-in-prod',
    apply: 'build',
    enforce: 'pre',
    transform(code, id) {
      if (!isProd) return null
      if (id.includes('node_modules')) return null
      if (!exts.test(id)) return null
      if (!code.includes('console.') && !code.includes('debugger')) return null
      const out = code.replace(consoleStmt, '$1').replace(debuggerStmt, '$1')
      if (out === code) return null
      return { code: out, map: null }
    },
  }
}

/**
 * Manual-chunk classifier — splits heavy / rarely-changing third-party
 * deps into their own chunks so the main app bundle stays small and
 * these deps only download when a route that needs them is loaded.
 *
 * Vite 8 (rolldown/oxc) requires manualChunks to be a function, not an
 * object. PERFORMANCE_AUDIT.md §F-H1, §F-H3.
 */
function classifyChunk(id: string): string | undefined {
  if (!id.includes('node_modules')) return undefined
  if (id.includes('/@puckeditor/')) return 'puck'
  if (id.includes('/@stripe/')) return 'stripe'
  if (id.includes('/recharts/') || id.includes('/d3-') || id.includes('/victory-')) return 'recharts'
  if (id.includes('/@dnd-kit/')) return 'dnd'
  if (id.includes('/firebase/')) return 'firebase-auth'
  if (id.includes('/@headlessui/')) return 'headlessui'
  if (id.includes('/qrcode.react/') || id.includes('/qrcode/')) return 'qrcode'
  if (id.includes('/axios/')) return 'axios'
  if (
    id.includes('/react/') ||
    id.includes('/react-dom/') ||
    id.includes('/react-router/') ||
    id.includes('/react-router-dom/') ||
    id.includes('/scheduler/')
  ) {
    return 'react-vendor'
  }
  return undefined
}

export default defineConfig({
  plugins: [react(), stripConsoleInProduction()],
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@shared': path.resolve(__dirname, '../shared'),
    },
  },
  server: {
    host: '0.0.0.0',
    allowedHosts: true,
    hmr: {
      // When accessed via reverse proxy (e.g. invoice.oraflows.co.nz),
      // the browser must connect to the proxy's host/port, not localhost:5173.
      // Use env var so it works both locally and behind the proxy.
      host: process.env.HMR_HOST || undefined,
      clientPort: process.env.HMR_CLIENT_PORT ? Number(process.env.HMR_CLIENT_PORT) : undefined,
      protocol: process.env.HMR_PROTOCOL || undefined,
    },
    watch: {
      usePolling: true,
      interval: 2000,
    },
  },
  build: {
    target: 'es2020',
    cssCodeSplit: true,
    // Codify sourcemap-off so a future env flip does not silently leak source.
    // PERFORMANCE_AUDIT.md §F-M8.
    sourcemap: false,
    rollupOptions: {
      // Multi-entry: the SPA HTML entry plus the standalone service worker.
      // The SW is built as its own bundle so it can be served at the
      // origin root (`/service-worker.js`) — required by the SW spec to
      // claim the maximum scope (the entire site).
      // PERFORMANCE_AUDIT.md §F-H5 / §1 quick win #5.
      input: {
        main: path.resolve(__dirname, 'index.html'),
        'service-worker': path.resolve(__dirname, 'src/service-worker.ts'),
      },
      output: {
        manualChunks: classifyChunk,
        // Place the SW at /service-worker.js (no hash, no /assets prefix).
        // Hashing would break browser registration which expects a
        // stable URL. Service workers are versioned via CACHE_NAME
        // (which embeds __APP_VERSION__) — see src/service-worker.ts.
        entryFileNames: (chunk) =>
          chunk.name === 'service-worker'
            ? 'service-worker.js'
            : 'assets/[name]-[hash].js',
      },
    },
    // Bump warning threshold — main chunk is expected to drop below 600 KB
    // after the App.tsx lazy-import work; flag anything bigger as a regression.
    chunkSizeWarningLimit: 600,
  },
  optimizeDeps: {
    // Pre-bundle all deps eagerly to avoid waterfall on first load
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      'axios',
      '@headlessui/react',
      '@stripe/react-stripe-js',
      '@stripe/stripe-js',
    ],
  },
})
