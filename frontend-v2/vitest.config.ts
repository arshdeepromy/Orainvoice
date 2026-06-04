import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

/**
 * Vitest config for frontend-v2.
 *
 * Kept separate from vite.config.ts (which carries the production build's
 * base/chunking/strip-console plugins) so the test runner stays minimal:
 * jsdom environment, global describe/it/expect, and the jest-dom matchers
 * loaded via setup.ts. Shares the `@` → src path alias with the app.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
