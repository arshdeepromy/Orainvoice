import { renderHook } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useNetworkStatus } from '../useNetworkStatus'

describe('useNetworkStatus', () => {
  let originalCapacitor: unknown

  beforeEach(() => {
    originalCapacitor = (window as any).Capacitor
    vi.clearAllMocks()
  })

  afterEach(() => {
    ;(window as any).Capacitor = originalCapacitor
  })

  it('defaults to online', () => {
    const { result } = renderHook(() => useNetworkStatus())
    expect(result.current.isOnline).toBe(true)
  })

  describe('on web platform', () => {
    beforeEach(() => {
      ;(window as any).Capacitor = {
        isNativePlatform: () => false,
      }
    })

    it('uses navigator.onLine as fallback', () => {
      const { result } = renderHook(() => useNetworkStatus())
      // In jsdom, navigator.onLine is true by default
      expect(result.current.isOnline).toBe(true)
    })
  })
})
