import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

// Read version from VERSION file or package.json
const version = (() => {
  try {
    // Check parent directory first (local dev: frontend/../VERSION)
    const parentVersion = path.resolve(__dirname, '..', 'VERSION')
    if (fs.existsSync(parentVersion)) return fs.readFileSync(parentVersion, 'utf-8').trim()
    // Check current directory (Docker: /app/VERSION)
    const localVersion = path.resolve(__dirname, 'VERSION')
    if (fs.existsSync(localVersion)) return fs.readFileSync(localVersion, 'utf-8').trim()
    // Fallback: read from package.json (always available)
    const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'))
    if (pkg.version) return pkg.version
  } catch { /* ignore */ }
  return 'dev'
})()

export default defineConfig({
  plugins: [react()],
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
