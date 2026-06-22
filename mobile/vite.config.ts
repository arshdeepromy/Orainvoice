import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync } from 'fs'

// When building for Capacitor (native shell), assets are served from root.
// For web serving behind the reverse proxy, keep the /mobile/ base path.
const isCapacitorBuild = !!process.env.CAPACITOR_BUILD

// Single source of truth for the displayed app version: mobile/package.json
// `version` (semver MAJOR.MINOR.PATCH). Injected as a compile-time constant so
// the version surface (Settings → About) stays in lockstep with the package
// version that the release/version-bump step (task 18.1) maintains. (R19.4)
const pkg = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf-8'),
) as { version: string }

export default defineConfig({
  base: isCapacitorBuild ? '/' : '/mobile/',
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@shared': path.resolve(__dirname, '../shared'),
      '@email-contract': path.resolve(__dirname, '../frontend-v2/src/components/email'),
    },
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    allowedHosts: true,
    // Allow Vite to serve the shared email contract that lives in frontend-v2/
    // (outside the mobile project root) — the contract is imported via the
    // `@email-contract` alias (R1.10 / R18.2: single source of truth, no dupes).
    fs: {
      allow: [path.resolve(__dirname, '..')],
    },
    hmr: {
      host: process.env.HMR_HOST || undefined,
      clientPort: process.env.HMR_CLIENT_PORT ? Number(process.env.HMR_CLIENT_PORT) : undefined,
      protocol: process.env.HMR_PROTOCOL || undefined,
    },
    watch: {
      usePolling: true,
      interval: 2000,
    },
  },
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      'axios',
      '@headlessui/react',
    ],
  },
})
