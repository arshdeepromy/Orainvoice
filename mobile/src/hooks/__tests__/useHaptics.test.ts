import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useHaptics } from '../useHaptics'

// Mock @capacitor/haptics
const mockImpact = vi.fn().mockResolvedValue(undefined)
const mockSelectionStart = vi.fn().mockResolvedValue(undefined)
const mockSelectionChanged = vi.fn().mockResolvedValue(undefined)
const mockSelectionEnd = vi.fn().mockResolvedValue(undefined)

vi.mock('@capacitor/haptics', () => ({
  Haptics: {
    impact: (...args: unknown[]) => mockImpact(...args),
    selectionStart: () => mockSelectionStart(),
    selectionChanged: () => mockSelectionChanged(),
    selectionEnd: () => mockSelectionEnd(),
  },
  ImpactStyle: {
    Light: 'LIGHT',
    Medium: 'MEDIUM',
    Heavy: 'HEAVY',
  },
}))

describe('useHaptics', () => {
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

  it('returns all four haptic methods', () => {
    const { result } = renderHook(() => useHaptics())

    expect(result.current.light).toBeTypeOf('function')
    expect(result.current.medium).toBeTypeOf('function')
    expect(result.current.heavy).toBeTypeOf('function')
    expect(result.current.selection).toBeTypeOf('function')
  })

  describe('on native platform', () => {
    beforeEach(() => {
      setNativePlatform(true)
    })

    it('light() triggers Haptics.impact with Light style', async () => {
      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.light()
      })

      expect(mockImpact).toHaveBeenCalledOnce()
      expect(mockImpact).toHaveBeenCalledWith({ style: 'LIGHT' })
    })

    it('medium() triggers Haptics.impact with Medium style', async () => {
      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.medium()
      })

      expect(mockImpact).toHaveBeenCalledOnce()
      expect(mockImpact).toHaveBeenCalledWith({ style: 'MEDIUM' })
    })

    it('heavy() triggers Haptics.impact with Heavy style', async () => {
      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.heavy()
      })

      expect(mockImpact).toHaveBeenCalledOnce()
      expect(mockImpact).toHaveBeenCalledWith({ style: 'HEAVY' })
    })

    it('selection() triggers the selection haptic sequence', async () => {
      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.selection()
      })

      expect(mockSelectionStart).toHaveBeenCalledOnce()
      expect(mockSelectionChanged).toHaveBeenCalledOnce()
      expect(mockSelectionEnd).toHaveBeenCalledOnce()
    })
  })

  describe('on web platform (no-op)', () => {
    beforeEach(() => {
      setNativePlatform(false)
    })

    it('light() does not call Haptics', async () => {
      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.light()
      })

      expect(mockImpact).not.toHaveBeenCalled()
    })

    it('medium() does not call Haptics', async () => {
      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.medium()
      })

      expect(mockImpact).not.toHaveBeenCalled()
    })

    it('heavy() does not call Haptics', async () => {
      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.heavy()
      })

      expect(mockImpact).not.toHaveBeenCalled()
    })

    it('selection() does not call Haptics', async () => {
      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.selection()
      })

      expect(mockSelectionStart).not.toHaveBeenCalled()
      expect(mockSelectionChanged).not.toHaveBeenCalled()
      expect(mockSelectionEnd).not.toHaveBeenCalled()
    })
  })

  describe('when Capacitor global is missing', () => {
    beforeEach(() => {
      delete (window as any).Capacitor
    })

    it('light() is a silent no-op', async () => {
      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.light()
      })

      expect(mockImpact).not.toHaveBeenCalled()
    })

    it('selection() is a silent no-op', async () => {
      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.selection()
      })

      expect(mockSelectionStart).not.toHaveBeenCalled()
    })
  })

  describe('error handling on unsupported devices', () => {
    beforeEach(() => {
      setNativePlatform(true)
    })

    it('light() swallows errors silently', async () => {
      mockImpact.mockRejectedValueOnce(new Error('Haptics not available'))

      const { result } = renderHook(() => useHaptics())

      // Should not throw
      await act(async () => {
        await result.current.light()
      })
    })

    it('medium() swallows errors silently', async () => {
      mockImpact.mockRejectedValueOnce(new Error('Haptics not available'))

      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.medium()
      })
    })

    it('heavy() swallows errors silently', async () => {
      mockImpact.mockRejectedValueOnce(new Error('Haptics not available'))

      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.heavy()
      })
    })

    it('selection() swallows errors silently', async () => {
      mockSelectionStart.mockRejectedValueOnce(new Error('Haptics not available'))

      const { result } = renderHook(() => useHaptics())

      await act(async () => {
        await result.current.selection()
      })
    })
  })
})
