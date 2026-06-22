import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync } from 'fs'

// Mirror the build-time version injection (see vite.config.ts) so the version
// surface reads the real mobile/package.json version under test too. (R19.4)
const pkg = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf-8'),
) as { version: string }

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@shared': path.resolve(__dirname, '../shared'),
      '@email-contract': path.resolve(__dirname, '../frontend-v2/src/components/email'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    server: {
      deps: {
        inline: ['konsta'],
      },
    },
  },
})
