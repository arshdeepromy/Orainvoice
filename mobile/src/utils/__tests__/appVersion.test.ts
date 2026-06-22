import { describe, it, expect } from 'vitest'
import { APP_VERSION } from '@/utils/appVersion'

/**
 * Verifies the app version surface (Settings → About) exposes a semantic
 * version of the form MAJOR.MINOR.PATCH that is >= the release introducing the
 * Portal_Type_Selector (a MINOR above 1.13.0). (R19.4)
 */

const SEMVER_RE = /^\d+\.\d+\.\d+$/

// The release that introduced the Portal_Type_Selector is a MINOR above
// 1.13.0; the displayed version must be >= that floor.
const PORTAL_RELEASE_FLOOR: [number, number, number] = [1, 14, 0]

function parseSemver(v: string): [number, number, number] {
  const [major, minor, patch] = v.split('.').map((n) => Number(n))
  return [major, minor, patch]
}

function gte(a: [number, number, number], b: [number, number, number]): boolean {
  for (let i = 0; i < 3; i++) {
    if (a[i] > b[i]) return true
    if (a[i] < b[i]) return false
  }
  return true
}

describe('APP_VERSION', () => {
  it('is a well-formed MAJOR.MINOR.PATCH semantic version', () => {
    expect(APP_VERSION).toMatch(SEMVER_RE)
  })

  it('is >= the Portal_Type_Selector release floor (1.14.0)', () => {
    expect(gte(parseSemver(APP_VERSION), PORTAL_RELEASE_FLOOR)).toBe(true)
  })
})
