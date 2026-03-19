import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
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
