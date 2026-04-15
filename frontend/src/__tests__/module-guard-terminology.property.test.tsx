import { render, screen, cleanup } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as fc from 'fast-check'
import React from 'react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Feature: production-readiness-gaps, Property 33: Module guard prevents rendering of disabled modules
// Feature: production-readiness-gaps, Property 34: Terminology substitution with fallback
// **Validates: Requirements 17.1, 17.3, 17.4, 17.6**

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', email: 'test@test.com', name: 'Test', role: 'org_admin', org_id: 'org-1' },
    isAuthenticated: true,
    isLoading: false,
    mfaPending: false,
    mfaSessionToken: null,
    login: vi.fn(),
    loginWithGoogle: vi.fn(),
    loginWithPasskey: vi.fn(),
    logout: vi.fn(),
    completeMfa: vi.fn(),
    isGlobalAdmin: false,
    isOrgAdmin: true,
    isSalesperson: false,
  }),
}))

import apiClient from '@/api/client'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { FeatureFlagProvider } from '@/contexts/FeatureFlagContext'
import { TerminologyProvider, useTerm } from '@/contexts/TerminologyContext'
import { useModuleGuard } from '@/hooks/useModuleGuard'

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/* ------------------------------------------------------------------ */

// Generate valid module slug strings (lowercase alphanumeric with underscores)
const moduleSlugArb = fc.stringMatching(/^[a-z][a-z0-9_]{1,20}$/)

// Generate a list of module info objects from a set of slugs
function makeModuleList(slugs: string[], enabledSlugs: Set<string>) {
  return slugs.map((slug) => ({
    slug,
    display_name: slug,
    description: '',
    category: 'general',
    is_core: false,
    is_enabled: enabledSlugs.has(slug),
  }))
}

// Generate a terminology map: Record<string, string>
const termKeyArb = fc.stringMatching(/^[a-z][a-z0-9_]{0,20}$/)
const termValueArb = fc.string({ minLength: 1, maxLength: 50 }).filter((s) => s.trim().length > 0)

/* ------------------------------------------------------------------ */
/*  Test Components                                                    */
/* ------------------------------------------------------------------ */

function GuardConsumer({ moduleSlug }: { moduleSlug: string }) {
  const { isAllowed, isLoading } = useModuleGuard(moduleSlug)
  if (isLoading) return <div data-testid="guard-loading">Loading</div>
  return <div data-testid="guard-result">{isAllowed ? 'allowed' : 'denied'}</div>
}

function DashboardPage() {
  return <div data-testid="dashboard">Dashboard</div>
}

function TermConsumer({ termKey, fallback }: { termKey: string; fallback: string }) {
  const value = useTerm(termKey, fallback)
  return <div data-testid="term-result">{value}</div>
}

function renderWithModuleProviders(ui: React.ReactElement) {
  return render(
    <MemoryRouter initialEntries={['/test']}>
      <ModuleProvider>
        <FeatureFlagProvider>
          <Routes>
            <Route path="/test" element={ui} />
            <Route path="/dashboard" element={<DashboardPage />} />
          </Routes>
        </FeatureFlagProvider>
      </ModuleProvider>
    </MemoryRouter>,
  )
}

function renderWithTerminologyProvider(
  ui: React.ReactElement,
  termsData: Record<string, string>,
) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: termsData,
  })

  return render(<TerminologyProvider>{ui}</TerminologyProvider>)
}

/* ------------------------------------------------------------------ */
/*  Property 33: Module guard prevents rendering of disabled modules   */
/* ------------------------------------------------------------------ */

describe('Property 33: Module guard prevents rendering of disabled modules', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it(
    'returns isAllowed: true iff the slug is in enabledModules',
    async () => {
      await fc.assert(
        fc.asyncProperty(
          // Generate a set of all module slugs (1-6 modules)
          fc.array(moduleSlugArb, { minLength: 1, maxLength: 6 }).chain((allSlugs) => {
            const uniqueSlugs = [...new Set(allSlugs)]
            if (uniqueSlugs.length === 0) return fc.constant({ allSlugs: ['default_mod'] as string[], enabledSlugs: [] as string[], targetSlug: 'default_mod' as string })
            return fc
              // Pick a random subset to be enabled
              .subarray(uniqueSlugs, { minLength: 0 })
              .chain((enabled) =>
                // Pick a target slug — either from the list or a new one
                fc.oneof(
                  fc.constantFrom(...uniqueSlugs),
                  moduleSlugArb,
                ).map((target) => ({
                  allSlugs: uniqueSlugs,
                  enabledSlugs: enabled,
                  targetSlug: target,
                })),
              )
          }),
          async ({ allSlugs, enabledSlugs, targetSlug }: { allSlugs: string[]; enabledSlugs: string[]; targetSlug: string }) => {
            cleanup()
            vi.clearAllMocks()

            const enabledSet = new Set(enabledSlugs)
            const moduleList = makeModuleList(allSlugs, enabledSet)

            ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
              if (url === '/modules') {
                return Promise.resolve({ data: moduleList })
              }
              return Promise.resolve({ data: {} })
            })

            renderWithModuleProviders(<GuardConsumer moduleSlug={targetSlug} />)

            const shouldBeAllowed = enabledSet.has(targetSlug)

            if (shouldBeAllowed) {
              const result = await screen.findByTestId('guard-result')
              expect(result).toHaveTextContent('allowed')
            } else {
              // Should redirect to dashboard
              expect(await screen.findByTestId('dashboard')).toBeInTheDocument()
            }

            cleanup()
          },
        ),
        { numRuns: 100 },
      )
    },
    120_000,
  )
})

/* ------------------------------------------------------------------ */
/*  Property 34: Terminology substitution with fallback                */
/* ------------------------------------------------------------------ */

describe('Property 34: Terminology substitution with fallback', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it(
    'returns terms[K] when key exists, or fallback F when it does not',
    async () => {
      await fc.assert(
        fc.asyncProperty(
          // Generate a terminology map with 0-5 entries
          fc.array(fc.tuple(termKeyArb, termValueArb), { minLength: 0, maxLength: 5 }).chain(
            (entries) => {
              const termsMap: Record<string, string> = {}
              for (const [k, v] of entries) {
                termsMap[k] = v
              }
              // Pick a lookup key — either from the map or a new one
              const existingKeys = Object.keys(termsMap)
              const keyArb =
                existingKeys.length > 0
                  ? fc.oneof(fc.constantFrom(...existingKeys), termKeyArb)
                  : termKeyArb
              return fc.tuple(fc.constant(termsMap), keyArb, termValueArb)
            },
          ),
          async ([termsMap, lookupKey, fallback]) => {
            cleanup()
            vi.clearAllMocks()

            const { unmount } = renderWithTerminologyProvider(
              <TermConsumer termKey={lookupKey} fallback={fallback} />,
              termsMap,
            )

            const result = await screen.findByTestId('term-result')
            const expected = termsMap[lookupKey] || fallback
            // Use exact textContent comparison to avoid whitespace normalization issues
            expect(result.textContent).toBe(expected)

            unmount()
          },
        ),
        { numRuns: 100 },
      )
    },
    120_000,
  )

  it(
    'never throws an error for any missing term key',
    async () => {
      await fc.assert(
        fc.asyncProperty(
          // Generate a terminology map and always look up a key NOT in the map
          fc.array(fc.tuple(termKeyArb, termValueArb), { minLength: 1, maxLength: 5 }).chain(
            (entries) => {
              const termsMap: Record<string, string> = {}
              for (const [k, v] of entries) {
                termsMap[k] = v
              }
              const existingKeys = new Set(Object.keys(termsMap))
              // Generate a key that is NOT in the map
              const missingKeyArb = termKeyArb.filter((k) => !existingKeys.has(k))
              // Use alphanumeric fallback to avoid whitespace normalization issues with toHaveTextContent
              const safeFallbackArb = fc.stringMatching(/^[A-Za-z][A-Za-z0-9 ]{0,20}$/).filter((s) => s.trim().length > 0)
              return fc.tuple(fc.constant(termsMap), missingKeyArb, safeFallbackArb)
            },
          ),
          async ([termsMap, missingKey, fallback]) => {
            cleanup()
            vi.clearAllMocks()

            // Should not throw — should render fallback
            const { unmount } = renderWithTerminologyProvider(
              <TermConsumer termKey={missingKey} fallback={fallback} />,
              termsMap,
            )

            const result = await screen.findByTestId('term-result')
            // Use exact textContent comparison to avoid whitespace normalization issues
            expect(result.textContent).toBe(fallback)

            unmount()
          },
        ),
        { numRuns: 100 },
      )
    },
    120_000,
  )
})
