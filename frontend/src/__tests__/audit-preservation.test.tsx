/// <reference types="node" />
/**
 * Preservation property tests for platform audit fixes — frontend.
 *
 * These tests capture the BASELINE behavior of the UNFIXED frontend code
 * for all non-buggy pages and components. They must PASS on the current
 * unfixed code and continue to PASS after fixes are applied.
 *
 * **Validates: Requirements 3.14**
 *
 * Property 2: Preservation — Non-notification frontend pages function correctly
 */

import { describe, it, expect } from 'vitest'
import * as fs from 'fs'
import * as path from 'path'

// Helper to read source files for static analysis
function readSource(relativePath: string): string {
  const fullPath = path.resolve(__dirname, '..', '..', '..', relativePath)
  return fs.readFileSync(fullPath, 'utf-8')
}

function fileExists(relativePath: string): boolean {
  const fullPath = path.resolve(__dirname, '..', '..', '..', relativePath)
  return fs.existsSync(fullPath)
}

// ===================================================================
// NON-NOTIFICATION PAGES PRESERVATION (Req 3.14)
// ===================================================================

describe('Non-notification frontend pages — Preservation', () => {
  /**
   * Verify that all core non-notification page files exist and have
   * expected structure. These pages must not be affected by the audit fixes.
   *
   * **Validates: Requirements 3.14**
   */

  const NON_NOTIFICATION_PAGES = [
    'frontend/src/pages/invoices',
    'frontend/src/pages/inventory',
    'frontend/src/pages/pos',
    'frontend/src/pages/jobs',
    'frontend/src/pages/quotes',
    'frontend/src/pages/bookings',
    'frontend/src/pages/projects',
    'frontend/src/pages/expenses',
    'frontend/src/pages/staff',
    'frontend/src/pages/reports',
  ] as const

  it('all non-notification page directories exist', () => {
    for (const dir of NON_NOTIFICATION_PAGES) {
      const fullPath = path.resolve(__dirname, '..', '..', '..', dir)
      expect(fs.existsSync(fullPath)).toBe(true)
    }
  })

  it('App.tsx has routes for core modules', () => {
    const source = readSource('frontend/src/App.tsx')
    const coreRoutes = [
      '/invoices',
      '/inventory',
      '/jobs',
      '/quotes',
    ]
    for (const route of coreRoutes) {
      expect(source).toContain(route)
    }
  })

  it('API client has base configuration preserved', () => {
    const source = readSource('frontend/src/api/client.ts')
    // The API client must have withCredentials and base URL config
    expect(source).toContain('withCredentials')
    expect(source).toContain('api/v')
  })
})

describe('AdminLayout — Preservation', () => {
  /**
   * AdminLayout must continue to render navigation for all modules.
   *
   * **Validates: Requirements 3.14**
   */
  it('AdminLayout file exists and has navigation structure', () => {
    expect(fileExists('frontend/src/layouts/AdminLayout.tsx')).toBe(true)
    const source = readSource('frontend/src/layouts/AdminLayout.tsx')
    // Must have navigation/sidebar structure
    expect(source).toContain('nav')
  })
})

describe('Settings page — non-notification sections preserved', () => {
  /**
   * The Settings page must preserve all existing non-notification sections.
   *
   * **Validates: Requirements 3.14**
   */
  it('Settings page file exists', () => {
    expect(fileExists('frontend/src/pages/settings/Settings.tsx')).toBe(true)
  })

  it('Settings page has NAV_ITEMS structure', () => {
    const source = readSource('frontend/src/pages/settings/Settings.tsx')
    expect(source).toContain('NAV_ITEMS')
  })
})

describe('Frontend API client — Preservation', () => {
  /**
   * The API client must preserve its core configuration and interceptors.
   *
   * **Validates: Requirements 3.14**
   */
  it('client.ts exists and exports apiClient', () => {
    const source = readSource('frontend/src/api/client.ts')
    expect(source).toContain('apiClient')
    expect(source).toContain('axios')
  })

  it('client.ts has request/response interceptors', () => {
    const source = readSource('frontend/src/api/client.ts')
    expect(source).toContain('interceptors')
  })

  it('client.ts has token refresh logic', () => {
    const source = readSource('frontend/src/api/client.ts')
    // Must have refresh token logic (regardless of storage mechanism)
    expect(source).toContain('refresh')
  })
})

describe('POS pages — Preservation', () => {
  /**
   * POS pages must continue functioning identically.
   *
   * **Validates: Requirements 3.14**
   */
  it('POSScreen exists and has expected structure', () => {
    expect(fileExists('frontend/src/pages/pos/POSScreen.tsx')).toBe(true)
    const source = readSource('frontend/src/pages/pos/POSScreen.tsx')
    expect(source).toContain('export')
  })

  it('POS offline sync manager exists', () => {
    expect(fileExists('frontend/src/utils/posSyncManager.ts')).toBe(true)
  })
})

describe('Inventory pages — Preservation', () => {
  /**
   * Inventory pages must continue functioning identically.
   *
   * **Validates: Requirements 3.14**
   */
  it('ProductList exists', () => {
    expect(fileExists('frontend/src/pages/inventory/ProductList.tsx')).toBe(true)
  })

  it('ProductDetail exists', () => {
    expect(fileExists('frontend/src/pages/inventory/ProductDetail.tsx')).toBe(true)
  })

  it('StockMovements exists', () => {
    expect(fileExists('frontend/src/pages/inventory/StockMovements.tsx')).toBe(true)
  })
})

describe('Job pages — Preservation', () => {
  /**
   * Job pages must continue functioning identically.
   *
   * **Validates: Requirements 3.14**
   */
  it('JobList exists and exports component', () => {
    expect(fileExists('frontend/src/pages/jobs/JobList.tsx')).toBe(true)
    const source = readSource('frontend/src/pages/jobs/JobList.tsx')
    expect(source).toContain('export')
  })

  it('JobDetail exists', () => {
    expect(fileExists('frontend/src/pages/jobs/JobDetail.tsx')).toBe(true)
  })

  it('JobBoard exists', () => {
    expect(fileExists('frontend/src/pages/jobs/JobBoard.tsx')).toBe(true)
  })
})
