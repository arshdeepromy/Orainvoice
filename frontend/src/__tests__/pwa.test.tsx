import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act as actHook } from '@testing-library/react'
import { useInstallPrompt } from '../hooks/useInstallPrompt'
import { InstallPromptBanner } from '../components/pwa/InstallPromptBanner'
import { registerServiceWorker } from '../registerSW'

/**
 * Validates: Requirements 76.1, 76.2, 76.3
 * - 76.1: Valid PWA manifest enabling installation on mobile and desktop devices
 * - 76.2: Cache critical application assets via service worker for fast loading
 * - 76.3: Display "Install App" prompt on supported devices
 */

describe('PWA Support', () => {
  describe('useInstallPrompt hook', () => {
    let matchMediaMock: ReturnType<typeof vi.fn>

    beforeEach(() => {
      matchMediaMock = vi.fn().mockReturnValue({ matches: false })
      Object.defineProperty(window, 'matchMedia', {
        value: matchMediaMock,
        writable: true,
        configurable: true,
      })
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    // 76.3: Hook detects beforeinstallprompt event
    it('sets isInstallable to true when beforeinstallprompt fires', () => {
      const { result } = renderHook(() => useInstallPrompt())

      expect(result.current.isInstallable).toBe(false)

      act(() => {
        const event = new Event('beforeinstallprompt', { cancelable: true })
        Object.assign(event, {
          prompt: vi.fn().mockResolvedValue(undefined),
          userChoice: Promise.resolve({ outcome: 'accepted' }),
        })
        window.dispatchEvent(event)
      })

      expect(result.current.isInstallable).toBe(true)
    })

    // 76.3: Hook detects already-installed state
    it('sets isInstalled to true when running in standalone mode', () => {
      matchMediaMock.mockReturnValue({ matches: true })

      const { result } = renderHook(() => useInstallPrompt())

      expect(result.current.isInstalled).toBe(true)
      expect(result.current.isInstallable).toBe(false)
    })

    // 76.3: promptInstall triggers the deferred prompt
    it('calls prompt() and returns true when user accepts', async () => {
      const mockPrompt = vi.fn().mockResolvedValue(undefined)
      const { result } = renderHook(() => useInstallPrompt())

      act(() => {
        const event = new Event('beforeinstallprompt', { cancelable: true })
        Object.assign(event, {
          prompt: mockPrompt,
          userChoice: Promise.resolve({ outcome: 'accepted' as const }),
        })
        window.dispatchEvent(event)
      })

      let accepted: boolean | undefined
      await actHook(async () => {
        accepted = await result.current.promptInstall()
      })

      expect(mockPrompt).toHaveBeenCalled()
      expect(accepted).toBe(true)
      expect(result.current.isInstallable).toBe(false)
    })

    // 76.3: promptInstall returns false when user dismisses
    it('returns false when user dismisses the install prompt', async () => {
      const mockPrompt = vi.fn().mockResolvedValue(undefined)
      const { result } = renderHook(() => useInstallPrompt())

      act(() => {
        const event = new Event('beforeinstallprompt', { cancelable: true })
        Object.assign(event, {
          prompt: mockPrompt,
          userChoice: Promise.resolve({ outcome: 'dismissed' as const }),
        })
        window.dispatchEvent(event)
      })

      let accepted: boolean | undefined
      await actHook(async () => {
        accepted = await result.current.promptInstall()
      })

      expect(accepted).toBe(false)
    })

    // 76.3: promptInstall returns false when no deferred prompt
    it('returns false when no deferred prompt is available', async () => {
      const { result } = renderHook(() => useInstallPrompt())

      let accepted: boolean | undefined
      await actHook(async () => {
        accepted = await result.current.promptInstall()
      })

      expect(accepted).toBe(false)
    })

    // 76.3: dismissPrompt clears installable state
    it('clears isInstallable when dismissPrompt is called', () => {
      const { result } = renderHook(() => useInstallPrompt())

      act(() => {
        const event = new Event('beforeinstallprompt', { cancelable: true })
        Object.assign(event, {
          prompt: vi.fn().mockResolvedValue(undefined),
          userChoice: Promise.resolve({ outcome: 'accepted' }),
        })
        window.dispatchEvent(event)
      })

      expect(result.current.isInstallable).toBe(true)

      act(() => {
        result.current.dismissPrompt()
      })

      expect(result.current.isInstallable).toBe(false)
    })

    // 76.3: appinstalled event marks as installed
    it('sets isInstalled when appinstalled event fires', () => {
      const { result } = renderHook(() => useInstallPrompt())

      act(() => {
        window.dispatchEvent(new Event('appinstalled'))
      })

      expect(result.current.isInstalled).toBe(true)
      expect(result.current.isInstallable).toBe(false)
    })
  })

  describe('InstallPromptBanner component', () => {
    beforeEach(() => {
      Object.defineProperty(window, 'matchMedia', {
        value: vi.fn().mockReturnValue({ matches: false }),
        writable: true,
        configurable: true,
      })
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    // 76.3: Banner renders when installable
    it('renders install banner when beforeinstallprompt fires', () => {
      render(<InstallPromptBanner />)

      // Initially not visible
      expect(screen.queryByRole('banner', { name: /install app/i })).not.toBeInTheDocument()

      // Fire the event
      act(() => {
        const event = new Event('beforeinstallprompt', { cancelable: true })
        Object.assign(event, {
          prompt: vi.fn().mockResolvedValue(undefined),
          userChoice: Promise.resolve({ outcome: 'accepted' }),
        })
        window.dispatchEvent(event)
      })

      expect(screen.getByRole('banner', { name: /install app/i })).toBeInTheDocument()
      expect(screen.getByText('Install WorkshopPro')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /install app/i })).toBeInTheDocument()
    })

    // 76.3: Dismiss button hides the banner
    it('hides banner when dismiss button is clicked', async () => {
      const user = userEvent.setup()
      render(<InstallPromptBanner />)

      act(() => {
        const event = new Event('beforeinstallprompt', { cancelable: true })
        Object.assign(event, {
          prompt: vi.fn().mockResolvedValue(undefined),
          userChoice: Promise.resolve({ outcome: 'accepted' }),
        })
        window.dispatchEvent(event)
      })

      expect(screen.getByRole('banner', { name: /install app/i })).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: /dismiss install prompt/i }))

      expect(screen.queryByRole('banner', { name: /install app/i })).not.toBeInTheDocument()
    })

    // 76.3: "Not now" button hides the banner
    it('hides banner when "Not now" is clicked', async () => {
      const user = userEvent.setup()
      render(<InstallPromptBanner />)

      act(() => {
        const event = new Event('beforeinstallprompt', { cancelable: true })
        Object.assign(event, {
          prompt: vi.fn().mockResolvedValue(undefined),
          userChoice: Promise.resolve({ outcome: 'accepted' }),
        })
        window.dispatchEvent(event)
      })

      await user.click(screen.getByRole('button', { name: /not now/i }))

      expect(screen.queryByRole('banner', { name: /install app/i })).not.toBeInTheDocument()
    })

    // 76.3: Install button triggers the prompt
    it('triggers install prompt when Install App button is clicked', async () => {
      const mockPrompt = vi.fn().mockResolvedValue(undefined)
      const user = userEvent.setup()
      render(<InstallPromptBanner />)

      act(() => {
        const event = new Event('beforeinstallprompt', { cancelable: true })
        Object.assign(event, {
          prompt: mockPrompt,
          userChoice: Promise.resolve({ outcome: 'accepted' as const }),
        })
        window.dispatchEvent(event)
      })

      await user.click(screen.getByRole('button', { name: /install app/i }))

      expect(mockPrompt).toHaveBeenCalled()
    })
  })

  describe('registerServiceWorker', () => {
    const originalNavigator = navigator.serviceWorker

    afterEach(() => {
      vi.restoreAllMocks()
      Object.defineProperty(navigator, 'serviceWorker', {
        value: originalNavigator,
        writable: true,
        configurable: true,
      })
    })

    // 76.2: Service worker registration is attempted
    it('registers service worker on window load', async () => {
      const mockRegister = vi.fn().mockResolvedValue({})
      Object.defineProperty(navigator, 'serviceWorker', {
        value: { register: mockRegister },
        writable: true,
        configurable: true,
      })

      registerServiceWorker()

      // Trigger the load event
      window.dispatchEvent(new Event('load'))

      expect(mockRegister).toHaveBeenCalledWith('/service-worker.js')
    })

    // 76.2: Gracefully handles missing service worker support
    it('does nothing when serviceWorker is not supported', () => {
      Object.defineProperty(navigator, 'serviceWorker', {
        value: undefined,
        writable: true,
        configurable: true,
      })

      // Should not throw
      expect(() => registerServiceWorker()).not.toThrow()
    })
  })
})
