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
      // HMR goes through Cloudflare tunnel → nginx → Vite
      clientPort: 443,
      protocol: 'wss',
      host: 'invoice.oraflows.co.nz',
    },
    watch: {
      usePolling: true,
      interval: 1000,
    },
    // No proxy — nginx handles API routing
  },
})
