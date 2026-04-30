import { renderHook } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useCamera } from '../useCamera'

describe('useCamera', () => {
  let originalCapacitor: unknown

  beforeEach(() => {
    originalCapacitor = (window as any).Capacitor
    vi.clearAllMocks()
  })

  afterEach(() => {
    ;(window as any).Capacitor = originalCapacitor
    vi.restoreAllMocks()
  })

  function setNativePlatform(isNative: boolean) {
    ;(window as any).Capacitor = {
      isNativePlatform: () => isNative,
    }
  }

  it('returns takePhoto and pickFromGallery methods', () => {
    const { result } = renderHook(() => useCamera())

    expect(result.current.takePhoto).toBeTypeOf('function')
    expect(result.current.pickFromGallery).toBeTypeOf('function')
    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBeNull()
  })

  describe('on web platform (file input fallback)', () => {
    beforeEach(() => {
      setNativePlatform(false)
    })

    it('hook initializes without error on web', () => {
      const { result } = renderHook(() => useCamera())
      expect(result.current.error).toBeNull()
      expect(result.current.isLoading).toBe(false)
    })
  })

  describe('when Capacitor global is missing', () => {
    beforeEach(() => {
      delete (window as any).Capacitor
    })

    it('falls back to file input without error', () => {
      const { result } = renderHook(() => useCamera())
      expect(result.current.takePhoto).toBeTypeOf('function')
      expect(result.current.pickFromGallery).toBeTypeOf('function')
      expect(result.current.error).toBeNull()
    })
  })
})
