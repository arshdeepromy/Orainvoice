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
 * Mirrors the existing `frontend/` build behavior. Vite 8 uses
 * rolldown + oxc, which currently ignores esbuild-style
 * `drop: ['console','debugger']` config, so this plugin does the same
 * job via a regex pass on .ts/.tsx/.js/.jsx sources during the
 * production build only. Dev keeps console.* intact for debugging.
 */
function stripConsoleInProduction(): Plugin {
  const exts = /\.(?:[mc]?[jt]sx?)$/
  const consoleStmt = /(^|[\s;{}])console\.(log|debug|info|warn|trace|dir|table|time|timeEnd|timeLog|count|countReset|group|groupEnd|groupCollapsed|profile|profileEnd|assert)\s*\([^;]*?\)\s*;?/gm
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
 * Targets the < 600 KB main-bundle goal (frontend-redesign NFR-3).
 *
 * Vite 8 (rolldown/oxc) requires manualChunks to be a function.
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
  // Served under the /new/ path prefix for side-by-side testing with the
  // existing frontend (frontend-redesign FR-3 / FR-4).
  base: '/new/',
  plugins: [react(), stripConsoleInProduction()],
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  resolve: {
    alias: {
      // frontend-v2 is fully self-contained — no '@shared' alias into the
      // repo root. All shared code is copied in, not imported (FR-3).
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // Bind on all interfaces so the dev server is reachable inside Docker
    // and via the nginx /new/ reverse proxy.
    host: true,
    port: 5174,
    strictPort: true,
    allowedHosts: true,
    // Proxy API calls to the backend during standalone dev. In the Docker
    // side-by-side setup nginx routes /api/ to the backend, but this keeps
    // `npm run dev` working on its own. Override the target with API_PROXY.
    proxy: {
      '/api': {
        target: process.env.API_PROXY || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    hmr: {
      // When accessed via reverse proxy, the browser must connect to the
      // proxy's host/port, not localhost:5174. Use env vars so it works
      // both locally and behind the proxy.
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
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: classifyChunk,
      },
    },
    // Flag anything bigger than 600 KB as a regression (NFR-3).
    chunkSizeWarningLimit: 600,
  },
  optimizeDeps: {
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
