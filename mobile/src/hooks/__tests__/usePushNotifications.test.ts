import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { usePushNotifications } from '../usePushNotifications'

// Mock API client
vi.mock('@/api/client', () => ({
  default: {
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

describe('usePushNotifications', () => {
  let originalCapacitor: unknown

  beforeEach(() => {
    originalCapacitor = (window as any).Capacitor
    vi.clearAllMocks()
  })

  afterEach(() => {
    ;(window as any).Capacitor = originalCapacitor
  })

  function setNativePlatform(isNative: boolean) {
    ;(window as any).Capacitor = {
      isNativePlatform: () => isNative,
      getPlatform: () => (isNative ? 'ios' : 'web'),
    }
  }

  it('returns expected interface', () => {
    const { result } = renderHook(() => usePushNotifications())

    expect(result.current.isPermissionGranted).toBe(false)
    expect(result.current.token).toBeNull()
    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBeNull()
    expect(result.current.register).toBeTypeOf('function')
  })

  describe('on web platform', () => {
    beforeEach(() => {
      setNativePlatform(false)
    })

    it('register sets error when not on native', async () => {
      const { result } = renderHook(() => usePushNotifications())

      await act(async () => {
        await result.current.register()
      })

      expect(result.current.error).toBe('Push notifications not available on this device')
    })
  })

  describe('when Capacitor global is missing', () => {
    beforeEach(() => {
      delete (window as any).Capacitor
    })

    it('register sets error gracefully', async () => {
      const { result } = renderHook(() => usePushNotifications())

      await act(async () => {
        await result.current.register()
      })

      expect(result.current.error).toBe('Push notifications not available on this device')
    })
  })
})
