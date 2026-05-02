import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// When building for Capacitor (native shell), assets are served from root.
// For web serving behind the reverse proxy, keep the /mobile/ base path.
const isCapacitorBuild = !!process.env.CAPACITOR_BUILD

export default defineConfig({
  base: isCapacitorBuild ? '/' : '/mobile/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@shared': path.resolve(__dirname, '../shared'),
    },
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    allowedHosts: true,
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
