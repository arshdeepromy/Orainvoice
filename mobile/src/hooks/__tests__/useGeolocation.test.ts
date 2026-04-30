import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useGeolocation } from '../useGeolocation'

// Mock @capacitor/geolocation
const mockGetCurrentPosition = vi.fn()

vi.mock('@capacitor/geolocation', () => ({
  Geolocation: {
    getCurrentPosition: (...args: unknown[]) => mockGetCurrentPosition(...args),
  },
}))

describe('useGeolocation', () => {
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
    }
  }

  it('returns getCurrentPosition method', () => {
    const { result } = renderHook(() => useGeolocation())

    expect(result.current.getCurrentPosition).toBeTypeOf('function')
  })

  describe('on native platform', () => {
    beforeEach(() => {
      setNativePlatform(true)
    })

    it('returns { lat, lng } on successful position', async () => {
      mockGetCurrentPosition.mockResolvedValueOnce({
        coords: { latitude: -36.8485, longitude: 174.7633 },
      })

      const { result } = renderHook(() => useGeolocation())

      let position: { lat: number; lng: number } | null = null
      await act(async () => {
        position = await result.current.getCurrentPosition()
      })

      expect(position).toEqual({ lat: -36.8485, lng: 174.7633 })
    })

    it('calls Geolocation.getCurrentPosition with correct options', async () => {
      mockGetCurrentPosition.mockResolvedValueOnce({
        coords: { latitude: 0, longitude: 0 },
      })

      const { result } = renderHook(() => useGeolocation())

      await act(async () => {
        await result.current.getCurrentPosition()
      })

      expect(mockGetCurrentPosition).toHaveBeenCalledOnce()
      expect(mockGetCurrentPosition).toHaveBeenCalledWith({
        enableHighAccuracy: false,
        timeout: 5000,
      })
    })

    it('returns null when permission is denied', async () => {
      mockGetCurrentPosition.mockRejectedValueOnce(
        new Error('Location permission denied')
      )

      const { result } = renderHook(() => useGeolocation())

      let position: { lat: number; lng: number } | null = { lat: 0, lng: 0 }
      await act(async () => {
        position = await result.current.getCurrentPosition()
      })

      expect(position).toBeNull()
    })

    it('returns null when request times out', async () => {
      mockGetCurrentPosition.mockRejectedValueOnce(
        new Error('Location request timed out')
      )

      const { result } = renderHook(() => useGeolocation())

      let position: { lat: number; lng: number } | null = { lat: 0, lng: 0 }
      await act(async () => {
        position = await result.current.getCurrentPosition()
      })

      expect(position).toBeNull()
    })

    it('returns null on any unexpected error', async () => {
      mockGetCurrentPosition.mockRejectedValueOnce(
        new Error('Geolocation not available')
      )

      const { result } = renderHook(() => useGeolocation())

      let position: { lat: number; lng: number } | null = { lat: 0, lng: 0 }
      await act(async () => {
        position = await result.current.getCurrentPosition()
      })

      expect(position).toBeNull()
    })
  })

  describe('on web platform (returns null)', () => {
    beforeEach(() => {
      setNativePlatform(false)
    })

    it('returns null without calling Geolocation', async () => {
      const { result } = renderHook(() => useGeolocation())

      let position: { lat: number; lng: number } | null = { lat: 0, lng: 0 }
      await act(async () => {
        position = await result.current.getCurrentPosition()
      })

      expect(position).toBeNull()
      expect(mockGetCurrentPosition).not.toHaveBeenCalled()
    })
  })

  describe('when Capacitor global is missing', () => {
    beforeEach(() => {
      delete (window as any).Capacitor
    })

    it('returns null silently', async () => {
      const { result } = renderHook(() => useGeolocation())

      let position: { lat: number; lng: number } | null = { lat: 0, lng: 0 }
      await act(async () => {
        position = await result.current.getCurrentPosition()
      })

      expect(position).toBeNull()
      expect(mockGetCurrentPosition).not.toHaveBeenCalled()
    })
  })
})
