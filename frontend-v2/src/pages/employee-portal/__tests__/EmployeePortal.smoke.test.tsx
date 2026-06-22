/// <reference types="node" />
/**
 * Employee Portal — HTTPS-redirect + noindex SMOKE checks (Task 17.9).
 *
 * Two static guards for Requirement 8:
 *
 *   • R8.6 — HTTP→HTTPS handling at the PROXY TIER for `/e/*`.
 *     In this deployment, TLS is terminated upstream (nginx for local dev,
 *     Cloudflare Tunnel for Pi prod), and the actual HTTP→HTTPS 301 happens at
 *     that edge. nginx's job for `/e/*` is to (a) preserve the upstream HTTPS
 *     scheme via the `map $http_x_forwarded_proto $forwarded_proto` block and
 *     (b) propagate it to the portal backend with
 *     `proxy_set_header X-Forwarded-Proto $forwarded_proto` inside the
 *     `location /e/api/` block, so the portal is served/treated as HTTPS rather
 *     than being silently downgraded. This test is the CONFIG-LEVEL static guard
 *     across all three active gateway configs; the live redirect behaviour is
 *     exercised by the 14.x / 17.10 e2e + curl checks.
 *
 *   • R8.7 — the `noindex` robots meta is present on the branded login page AND
 *     on the authenticated portal pages (`EmployeePortalApp`). Task 14.5 already
 *     covers the branded login + neutral-unavailable page; this adds the missing
 *     authenticated-view coverage and a combined login-vs-authenticated smoke.
 *
 * _Requirements: 8.6, 8.7_
 */
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// ---------------------------------------------------------------------------
// R8.6 — nginx proxy-tier scheme handling for /e/* (config-level static guard)
// ---------------------------------------------------------------------------

// Resolve the repo `nginx/` dir from this test file:
// __tests__ → employee-portal → pages → src → frontend-v2 → <repo root>.
const NGINX_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../../nginx',
)

// Every active gateway config that fronts the platform (and therefore `/e/*`).
const ACTIVE_CONFIGS = [
  'nginx.conf', // canonical prod (legacy frontend) + standby
  'nginx.dev-v2.conf', // local dev gateway (frontend-v2 at /)
  'nginx.pi-v2.conf', // Pi prod gateway (frontend-v2 static build, behind Cloudflare)
] as const

function readConfig(name: string): string {
  return readFileSync(path.join(NGINX_DIR, name), 'utf8')
}

/** Extract the body of the `location /e/api/ { ... }` block (brace-matched). */
function extractEApiBlock(conf: string): string {
  const marker = 'location /e/api/'
  const start = conf.indexOf(marker)
  if (start === -1) return ''
  const braceOpen = conf.indexOf('{', start)
  if (braceOpen === -1) return ''
  let depth = 0
  for (let i = braceOpen; i < conf.length; i++) {
    if (conf[i] === '{') depth++
    else if (conf[i] === '}') {
      depth--
      if (depth === 0) return conf.slice(braceOpen + 1, i)
    }
  }
  return ''
}

describe('R8.6 — nginx proxy-tier HTTPS handling for /e/*', () => {
  it.each(ACTIVE_CONFIGS)(
    '%s preserves the upstream HTTPS scheme via the $forwarded_proto map',
    (name) => {
      const conf = readConfig(name)
      // The proxy tier must not downgrade /e/*: it preserves the upstream
      // (Cloudflare/edge) X-Forwarded-Proto, falling back to $scheme.
      expect(conf).toMatch(/map\s+\$http_x_forwarded_proto\s+\$forwarded_proto\s*\{/)
    },
  )

  it.each(ACTIVE_CONFIGS)(
    '%s routes /e/* through a dedicated /e/api/ proxy block',
    (name) => {
      const conf = readConfig(name)
      // Without this block, /e/api/* would fall through to the SPA `location /`
      // and never reach the backend over the correct scheme.
      expect(conf).toContain('location /e/api/')
    },
  )

  it.each(ACTIVE_CONFIGS)(
    '%s propagates the HTTPS scheme to the portal backend for /e/* (R8.6)',
    (name) => {
      const block = extractEApiBlock(readConfig(name))
      expect(block).not.toBe('')
      // The proxy-tier scheme handling that backs HTTP→HTTPS for /e/*: forward
      // the (preserved) original scheme so the backend serves the portal as HTTPS.
      expect(block).toMatch(
        /proxy_set_header\s+X-Forwarded-Proto\s+\$forwarded_proto\s*;/,
      )
      // The /e/api/ surface must never be cached as plaintext SPA HTML.
      expect(block).toMatch(/add_header\s+X-Robots-Tag\s+"noindex, nofollow"/)
    },
  )
})

// ---------------------------------------------------------------------------
// R8.7 — noindex robots meta on the login + authenticated portal pages
// ---------------------------------------------------------------------------

const { axiosGet, axiosPost } = vi.hoisted(() => ({
  axiosGet: vi.fn(),
  axiosPost: vi.fn(),
}))

vi.mock('axios', () => {
  const isAxiosError = (e: unknown): boolean =>
    !!(e && typeof e === 'object' && 'response' in (e as Record<string, unknown>))
  const mock = { get: axiosGet, post: axiosPost, isAxiosError }
  return { default: mock, ...mock }
})

// Imported AFTER the axios mock is registered.
const { default: EmployeePortalLogin } = await import('../EmployeePortalLogin')
const { default: EmployeePortalApp } = await import('../EmployeePortalApp')

const ME = {
  portal_user_id: 'pu-1',
  email: 'staff@acme.test',
  first_name: 'Sam',
  staff_id: 'staff-1',
  org_name: 'Acme Motors',
  branding: null,
}

function robotsMeta(): HTMLMetaElement | null {
  return document.head.querySelector('meta[name="robots"]')
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  // usePageMeta removes its tags on unmount, but clear any residue so each
  // case asserts against a clean <head>.
  document.head
    .querySelectorAll('meta[name="robots"], meta[name="googlebot"]')
    .forEach((el) => el.remove())
})

describe('R8.7 — noindex on the branded login page', () => {
  it('injects noindex on the branded login', async () => {
    axiosGet.mockResolvedValue({
      data: { org_name: 'Acme Motors', logo_url: null, primary_colour: null, secondary_colour: null },
    })

    render(
      <MemoryRouter initialEntries={['/e/acme-motors']}>
        <Routes>
          <Route path="/e/:slug" element={<EmployeePortalLogin />} />
        </Routes>
      </MemoryRouter>,
    )

    await screen.findByText('Sign in to Acme Motors')
    await waitFor(() => {
      expect(robotsMeta()?.getAttribute('content')).toBe('noindex, nofollow')
      expect(
        document.head.querySelector('meta[name="googlebot"]')?.getAttribute('content'),
      ).toBe('noindex, nofollow')
    })
  })
})

describe('R8.7 — noindex on the authenticated portal pages (EmployeePortalApp)', () => {
  it('injects noindex while the session is being verified', async () => {
    // Never resolve /auth/me so the app stays in its "checking" state — the
    // noindex meta must already be present (the hook runs unconditionally).
    axiosGet.mockReturnValue(new Promise(() => {}))

    render(
      <MemoryRouter initialEntries={['/e/acme-motors/home']}>
        <Routes>
          <Route path="/e/:slug/*" element={<EmployeePortalApp />} />
          <Route path="/e/:slug" element={<div>branded login</div>} />
        </Routes>
      </MemoryRouter>,
    )

    // Loading skeleton is on screen…
    expect(screen.getByLabelText('Loading portal')).toBeInTheDocument()
    // …and the page is already marked noindex.
    await waitFor(() => {
      expect(robotsMeta()?.getAttribute('content')).toBe('noindex, nofollow')
    })
  })

  it('keeps noindex on the authenticated profile view once the session is ready', async () => {
    axiosGet.mockImplementation((url: string) => {
      if (url.endsWith('/auth/me')) return Promise.resolve({ data: ME })
      if (url.endsWith('/profile'))
        return Promise.resolve({
          data: {
            staff_id: 'staff-1',
            first_name: 'Sam',
            last_name: 'Rivera',
            name: 'Sam Rivera',
            email: 'staff@acme.test',
            phone: null,
            position: 'Technician',
            employee_id: 'EMP-014',
            employment_basis: null,
            employment_type: null,
            working_arrangement: null,
            employment_start_date: null,
            tax_code: null,
            kiwisaver_enrolled: null,
            ird_number: null,
            bank_account_number: null,
            emergency_contact_name: null,
            emergency_contact_phone: null,
          },
        })
      return Promise.reject(new Error(`unexpected ${url}`))
    })

    render(
      <MemoryRouter initialEntries={['/e/acme-motors/home']}>
        <Routes>
          <Route path="/e/:slug/*" element={<EmployeePortalApp />} />
          <Route path="/e/:slug" element={<div>branded login</div>} />
        </Routes>
      </MemoryRouter>,
    )

    // Authenticated content renders…
    expect(await screen.findByText('Sam Rivera')).toBeInTheDocument()
    // …and the authenticated page remains noindex (R8.7).
    await waitFor(() => {
      expect(robotsMeta()?.getAttribute('content')).toBe('noindex, nofollow')
    })
  })
})
