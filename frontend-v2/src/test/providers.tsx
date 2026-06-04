import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '@/contexts/AuthContext'
import { TenantProvider } from '@/contexts/TenantContext'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { FeatureFlagProvider } from '@/contexts/FeatureFlagContext'
import { BranchProvider } from '@/contexts/BranchContext'
import { setAccessToken } from '@/api/client'

/**
 * Test harness mounting the shell's REAL context providers (the same nesting
 * order App.tsx uses for Auth → Tenant → Module → FeatureFlag → Branch). Used
 * by the shell unit tests so TopBar / OrgSwitcher / OrgLayout exercise the real
 * wiring. Pair with `vi.mock('@/api/client', ...)` → test/apiClientMock so the
 * providers resolve against deterministic backend shapes.
 *
 * Locale/PlatformBranding/Theme providers are omitted — the shell components
 * don't consume them, so they're unnecessary noise for these unit tests.
 */

/** Base64url-encode a JSON object for a JWT segment (browser btoa). */
function b64url(obj: Record<string, unknown>): string {
  return btoa(JSON.stringify(obj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/**
 * Build a syntactically valid (unsigned) JWT whose payload AuthContext decodes.
 * Defaults to an org_admin session for Kerikeri Motors so admin-gated shell
 * affordances render, matching the original shim's preview user.
 */
export function makeToken(overrides: Record<string, unknown> = {}): string {
  const payload = {
    user_id: 'preview',
    email: 'preview@orainvoice.app',
    role: 'org_admin',
    org_id: 'preview-org',
    exp: Math.floor(Date.now() / 1000) + 3600,
    ...overrides,
  }
  return `${b64url({ alg: 'none', typ: 'JWT' })}.${b64url(payload)}.sig`
}

/** Seed the api/client access token so AuthProvider restores a session on mount. */
export function seedSession(token: string = makeToken()): void {
  setAccessToken(token)
}

export function ShellProviders({
  children,
  initialEntries = ['/dashboard'],
}: {
  children: ReactNode
  initialEntries?: string[]
}) {
  return (
    <MemoryRouter initialEntries={initialEntries}>
      <AuthProvider>
        <TenantProvider>
          <ModuleProvider>
            <FeatureFlagProvider>
              <BranchProvider>{children}</BranchProvider>
            </FeatureFlagProvider>
          </ModuleProvider>
        </TenantProvider>
      </AuthProvider>
    </MemoryRouter>
  )
}
