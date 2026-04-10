import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import 'fake-indexeddb/auto'
import type { ReactNode } from 'react'

/**
 * Validates: Requirements 77.3, 77.4
 * - 77.3: Auto-sync locally saved data when connection restored, notify user
 * - 77.4: Present both versions on sync conflict, user chooses which to keep
 */

// Mock crypto.randomUUID
let uuidCounter = 0
vi.stubGlobal('crypto', {
  ...globalThis.crypto,
  randomUUID: () => `uuid-${++uuidCounter}`,
})

/* ── offlineStorage tests (IndexedDB layer) ── */

describe('offlineStorage — IndexedDB cache read/write', () => {
  // Use clearStore between tests instead of deleting the DB
  // This avoids blocked connection issues with fake-indexeddb
  beforeEach(async () => {
    const { clearStore } = await import('@/utils/offlineStorage')
    await clearStore('invoices')
    await clearStore('customers')
    await clearStore('vehicles')
    await clearStore('pendingSync')
  })

  it('putItem stores and getItem retrieves a record', async () => {
    const { putItem, getItem } = await import('@/utils/offlineStorage')
    const record = { id: 'inv-1', customer_name: 'Test Customer', total: 100 }
    await putItem('invoices', record)
    const result = await getItem<typeof record>('invoices', 'inv-1')
    expect(result).toEqual(record)
  })

  it('getItem returns undefined for a non-existent key', async () => {
    const { getItem } = await import('@/utils/offlineStorage')
    const result = await getItem('invoices', 'non-existent')
    expect(result).toBeUndefined()
  })

  it('getAllItems returns all records in a store', async () => {
    const { putItem, getAllItems } = await import('@/utils/offlineStorage')
    await putItem('customers', { id: 'c-1', name: 'Alice' })
    await putItem('customers', { id: 'c-2', name: 'Bob' })
    const all = await getAllItems<{ id: string; name: string }>('customers')
    expect(all).toHaveLength(2)
    expect(all.map((r) => r.id).sort()).toEqual(['c-1', 'c-2'])
  })

  it('deleteItem removes a record from the store', async () => {
    const { putItem, getItem, deleteItem } = await import('@/utils/offlineStorage')
    await putItem('vehicles', { id: 'v-1', rego: 'ABC123' })
    await deleteItem('vehicles', 'v-1')
    const result = await getItem('vehicles', 'v-1')
    expect(result).toBeUndefined()
  })

  it('clearStore removes all records from a store', async () => {
    const { putItem, getAllItems, clearStore } = await import('@/utils/offlineStorage')
    await putItem('invoices', { id: 'inv-1', total: 50 })
    await putItem('invoices', { id: 'inv-2', total: 75 })
    await clearStore('invoices')
    const all = await getAllItems('invoices')
    expect(all).toHaveLength(0)
  })

  it('cacheRecords stores a batch of records', async () => {
    const { cacheRecords, getAllItems } = await import('@/utils/offlineStorage')
    const records = [
      { id: 'inv-1', total: 100 },
      { id: 'inv-2', total: 200 },
      { id: 'inv-3', total: 300 },
    ]
    await cacheRecords('invoices', records)
    const all = await getAllItems<{ id: string; total: number }>('invoices')
    expect(all).toHaveLength(3)
  })

  it('putItem overwrites an existing record with the same key', async () => {
    const { putItem, getItem } = await import('@/utils/offlineStorage')
    await putItem('invoices', { id: 'inv-1', total: 100 })
    await putItem('invoices', { id: 'inv-1', total: 999 })
    const result = await getItem<{ id: string; total: number }>('invoices', 'inv-1')
    expect(result?.total).toBe(999)
  })
})


/* ── OfflineContext sync logic tests ── */

// Mock apiClient for context tests
vi.mock('@/api/client', () => ({
  default: {
    post: vi.fn(),
    put: vi.fn(),
    get: vi.fn(),
  },
}))

import apiClientModule from '@/api/client'
import { OfflineProvider, useOfflineContext } from '@/contexts/OfflineContext'

const mockedApi = apiClientModule as unknown as {
  post: ReturnType<typeof vi.fn>
  put: ReturnType<typeof vi.fn>
  get: ReturnType<typeof vi.fn>
}

describe('OfflineContext — sync logic', () => {
  beforeEach(async () => {
    uuidCounter = 0

    // Clear IndexedDB stores
    const { clearStore } = await import('@/utils/offlineStorage')
    await clearStore('invoices')
    await clearStore('customers')
    await clearStore('vehicles')
    await clearStore('pendingSync')

    Object.defineProperty(navigator, 'onLine', {
      value: true,
      writable: true,
      configurable: true,
    })

    mockedApi.post.mockReset()
    mockedApi.put.mockReset()
    mockedApi.get.mockReset()
  })

  function wrapper({ children }: { children: ReactNode }) {
    return <OfflineProvider>{children}</OfflineProvider>
  }

  // 77.3: saveOffline queues items for sync
  it('saveOffline adds an item to the pending sync queue', async () => {
    const { result } = renderHook(() => useOfflineContext(), { wrapper })

    await act(async () => {
      await result.current.saveOffline('invoices', 'create', {
        id: 'inv-new',
        customer_name: 'Test',
        total: 150,
      })
    })

    expect(result.current.pendingSyncCount).toBe(1)
  })

  // 77.3: triggerSync sends pending create items to the server
  it('triggerSync posts create items to the correct API endpoint', async () => {
    mockedApi.post.mockResolvedValue({ data: { id: 'inv-new' } })

    const { result } = renderHook(() => useOfflineContext(), { wrapper })

    await act(async () => {
      await result.current.saveOffline('invoices', 'create', {
        id: 'inv-new',
        customer_name: 'Test',
        total: 150,
      })
    })

    expect(result.current.pendingSyncCount).toBe(1)

    await act(async () => {
      await result.current.triggerSync()
    })

    expect(mockedApi.post).toHaveBeenCalledWith(
      '/invoices',
      expect.objectContaining({ id: 'inv-new', customer_name: 'Test' }),
    )
    expect(result.current.pendingSyncCount).toBe(0)
  })

  // 77.3: triggerSync sends update items with PUT
  it('triggerSync puts update items to the correct API endpoint', async () => {
    mockedApi.get.mockResolvedValue({
      data: { id: 'cust-1', name: 'Server Name', version: 1 },
    })
    mockedApi.put.mockResolvedValue({ data: {} })

    const { result } = renderHook(() => useOfflineContext(), { wrapper })

    await act(async () => {
      await result.current.saveOffline(
        'customers',
        'update',
        { id: 'cust-1', name: 'Updated Locally' },
        1,
      )
    })

    await act(async () => {
      await result.current.triggerSync()
    })

    expect(mockedApi.put).toHaveBeenCalledWith(
      '/customers/cust-1',
      expect.objectContaining({ id: 'cust-1', name: 'Updated Locally' }),
    )
    expect(result.current.pendingSyncCount).toBe(0)
  })

  // 77.4: Conflict detection when server version differs
  it('detects a sync conflict when server version has changed', async () => {
    // Server returns a different version than what was saved locally
    mockedApi.get.mockResolvedValue({
      data: { id: 'inv-1', total: 999, version: 3 },
    })

    const { result } = renderHook(() => useOfflineContext(), { wrapper })

    await act(async () => {
      await result.current.saveOffline(
        'invoices',
        'update',
        { id: 'inv-1', total: 150 },
        1, // local saved at serverVersion 1
      )
    })

    await act(async () => {
      await result.current.triggerSync()
    })

    // Should have detected a conflict (server version 3 != local version 1)
    expect(result.current.conflicts).toHaveLength(1)
    expect(result.current.conflicts[0].store).toBe('invoices')
    expect(result.current.conflicts[0].localVersion).toEqual(
      expect.objectContaining({ id: 'inv-1', total: 150 }),
    )
    expect(result.current.conflicts[0].serverVersion).toEqual(
      expect.objectContaining({ id: 'inv-1', total: 999, version: 3 }),
    )
  })

  // 77.4: resolveConflict with 'local' pushes local version to server
  it('resolveConflict with local choice pushes local version to server', async () => {
    mockedApi.get.mockResolvedValue({
      data: { id: 'inv-1', total: 999, version: 3 },
    })
    mockedApi.put.mockResolvedValue({ data: {} })

    const { result } = renderHook(() => useOfflineContext(), { wrapper })

    await act(async () => {
      await result.current.saveOffline(
        'invoices',
        'update',
        { id: 'inv-1', total: 150 },
        1,
      )
    })

    await act(async () => {
      await result.current.triggerSync()
    })

    expect(result.current.conflicts).toHaveLength(1)
    const conflictId = result.current.conflicts[0].id

    await act(async () => {
      await result.current.resolveConflict(conflictId, 'local')
    })

    // Should have pushed local version with force flag
    expect(mockedApi.put).toHaveBeenCalledWith(
      '/invoices/inv-1',
      expect.objectContaining({ id: 'inv-1', total: 150, force: true }),
    )
    expect(result.current.conflicts).toHaveLength(0)
  })

  // 77.4: resolveConflict with 'server' accepts server version
  it('resolveConflict with server choice accepts server version without extra PUT', async () => {
    mockedApi.get.mockResolvedValue({
      data: { id: 'inv-1', total: 999, version: 3 },
    })
    mockedApi.put.mockResolvedValue({ data: {} })

    const { result } = renderHook(() => useOfflineContext(), { wrapper })

    await act(async () => {
      await result.current.saveOffline(
        'invoices',
        'update',
        { id: 'inv-1', total: 150 },
        1,
      )
    })

    await act(async () => {
      await result.current.triggerSync()
    })

    expect(result.current.conflicts).toHaveLength(1)
    const conflictId = result.current.conflicts[0].id

    // Reset put mock to track only resolve calls
    mockedApi.put.mockClear()

    await act(async () => {
      await result.current.resolveConflict(conflictId, 'server')
    })

    // Should NOT have called put (server version accepted as-is)
    expect(mockedApi.put).not.toHaveBeenCalled()
    expect(result.current.conflicts).toHaveLength(0)
  })

  // 77.3: triggerSync does nothing when offline
  it('triggerSync does not sync when offline', async () => {
    Object.defineProperty(navigator, 'onLine', {
      value: false,
      writable: true,
      configurable: true,
    })

    const { result } = renderHook(() => useOfflineContext(), { wrapper })

    await act(async () => {
      await result.current.triggerSync()
    })

    expect(mockedApi.post).not.toHaveBeenCalled()
    expect(mockedApi.put).not.toHaveBeenCalled()
  })
})
