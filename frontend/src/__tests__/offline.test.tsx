import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useOffline } from '../hooks/useOffline'
import { OfflineProvider } from '../contexts/OfflineContext'
import type { SyncConflict } from '../contexts/OfflineContext'
import { OfflineBanner } from '../components/offline/OfflineBanner'
import { ConflictResolutionModal } from '../components/offline/ConflictResolutionModal'

/**
 * Validates: Requirements 77.1, 77.2, 77.3, 77.4
 * - 77.1: View previously loaded invoices/customers/vehicles from local cache while offline
 * - 77.2: Start creating a new invoice and save it locally while offline
 * - 77.3: Auto-sync locally saved data when connection restored, notify user
 * - 77.4: Present both versions on sync conflict, user chooses which to keep
 */

/* ── Tests ── */

describe('Offline Capability', () => {
  describe('useOffline hook', () => {
    const originalOnLine = navigator.onLine

    afterEach(() => {
      Object.defineProperty(navigator, 'onLine', {
        value: originalOnLine,
        writable: true,
        configurable: true,
      })
    })

    // 77.1: Detects online status
    it('returns current online status from navigator.onLine', () => {
      Object.defineProperty(navigator, 'onLine', {
        value: true,
        writable: true,
        configurable: true,
      })

      const { result } = renderHook(() => useOffline())
      expect(result.current.isOnline).toBe(true)
    })

    // 77.1: Detects offline status
    it('returns offline when navigator.onLine is false', () => {
      Object.defineProperty(navigator, 'onLine', {
        value: false,
        writable: true,
        configurable: true,
      })

      const { result } = renderHook(() => useOffline())
      expect(result.current.isOnline).toBe(false)
    })

    // 77.1: Responds to offline event
    it('updates to offline when offline event fires', () => {
      Object.defineProperty(navigator, 'onLine', {
        value: true,
        writable: true,
        configurable: true,
      })

      const { result } = renderHook(() => useOffline())
      expect(result.current.isOnline).toBe(true)

      act(() => {
        window.dispatchEvent(new Event('offline'))
      })

      expect(result.current.isOnline).toBe(false)
    })

    // 77.3: Detects reconnection
    it('sets justReconnected when online event fires after being offline', () => {
      Object.defineProperty(navigator, 'onLine', {
        value: false,
        writable: true,
        configurable: true,
      })

      const { result } = renderHook(() => useOffline())
      expect(result.current.justReconnected).toBe(false)

      act(() => {
        window.dispatchEvent(new Event('online'))
      })

      expect(result.current.isOnline).toBe(true)
      expect(result.current.justReconnected).toBe(true)
    })

    // 77.3: clearReconnected resets the flag
    it('clears justReconnected flag when clearReconnected is called', () => {
      Object.defineProperty(navigator, 'onLine', {
        value: false,
        writable: true,
        configurable: true,
      })

      const { result } = renderHook(() => useOffline())

      act(() => {
        window.dispatchEvent(new Event('online'))
      })

      expect(result.current.justReconnected).toBe(true)

      act(() => {
        result.current.clearReconnected()
      })

      expect(result.current.justReconnected).toBe(false)
    })
  })

  describe('OfflineBanner component', () => {
    // 77.1: Shows offline banner when offline
    it('displays offline banner when not online', () => {
      Object.defineProperty(navigator, 'onLine', {
        value: false,
        writable: true,
        configurable: true,
      })

      render(
        <OfflineProvider>
          <OfflineBanner />
        </OfflineProvider>,
      )

      expect(screen.getByText("You're offline")).toBeInTheDocument()
      expect(
        screen.getByText(/view cached data and create new invoices/i),
      ).toBeInTheDocument()
    })

    // 77.1: No offline banner when online
    it('does not display offline banner when online', () => {
      Object.defineProperty(navigator, 'onLine', {
        value: true,
        writable: true,
        configurable: true,
      })

      render(
        <OfflineProvider>
          <OfflineBanner />
        </OfflineProvider>,
      )

      expect(screen.queryByText("You're offline")).not.toBeInTheDocument()
    })
  })

  describe('ConflictResolutionModal', () => {
    const mockConflict: SyncConflict = {
      id: 'conflict-1',
      store: 'invoices',
      localVersion: {
        id: 'inv-1',
        customer_name: 'Local Customer',
        total: 150,
        updated_at: '2024-01-15T10:00:00Z',
      },
      serverVersion: {
        id: 'inv-1',
        customer_name: 'Server Customer',
        total: 200,
        updated_at: '2024-01-15T11:00:00Z',
      },
      pendingItemId: 'pending-1',
    }

    // 77.4: Shows both versions
    it('displays both local and server versions for comparison', () => {
      const onResolve = vi.fn()
      const onClose = vi.fn()

      render(
        <ConflictResolutionModal
          conflict={mockConflict}
          onResolve={onResolve}
          onClose={onClose}
        />,
      )

      expect(screen.getByText('Sync Conflict — Invoice')).toBeInTheDocument()
      expect(screen.getByText('Your version (local)')).toBeInTheDocument()
      expect(screen.getByText('Server version')).toBeInTheDocument()
      expect(screen.getByText('Local Customer')).toBeInTheDocument()
      expect(screen.getByText('Server Customer')).toBeInTheDocument()
    })

    // 77.4: User can choose local version
    it('calls onResolve with "local" when user keeps their version', async () => {
      const user = userEvent.setup()
      const onResolve = vi.fn()
      const onClose = vi.fn()

      render(
        <ConflictResolutionModal
          conflict={mockConflict}
          onResolve={onResolve}
          onClose={onClose}
        />,
      )

      await user.click(screen.getByRole('button', { name: /keep my version/i }))
      expect(onResolve).toHaveBeenCalledWith('conflict-1', 'local')
    })

    // 77.4: User can choose server version
    it('calls onResolve with "server" when user keeps server version', async () => {
      const user = userEvent.setup()
      const onResolve = vi.fn()
      const onClose = vi.fn()

      render(
        <ConflictResolutionModal
          conflict={mockConflict}
          onResolve={onResolve}
          onClose={onClose}
        />,
      )

      await user.click(screen.getByRole('button', { name: /keep server version/i }))
      expect(onResolve).toHaveBeenCalledWith('conflict-1', 'server')
    })

    // 77.4: Does not render when no conflict
    it('renders nothing when conflict is null', () => {
      const { container } = render(
        <ConflictResolutionModal
          conflict={null}
          onResolve={vi.fn()}
          onClose={vi.fn()}
        />,
      )

      expect(container.innerHTML).toBe('')
    })
  })
})
