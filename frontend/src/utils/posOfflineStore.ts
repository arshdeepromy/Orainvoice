/**
 * IndexedDB storage for offline POS transactions using the idb library.
 * Stores transactions locally when offline and provides retrieval for sync.
 *
 * Validates: Requirement 22.6 — POS offline mode with IndexedDB queue
 */

import type { OfflineTransaction } from '@/pages/pos/types'

const DB_NAME = 'pos-offline-store'
const DB_VERSION = 1
const STORE_NAME = 'transactions'

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'offlineId' })
        store.createIndex('syncStatus', 'syncStatus', { unique: false })
        store.createIndex('timestamp', 'timestamp', { unique: false })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function txStore(db: IDBDatabase, mode: IDBTransactionMode): IDBObjectStore {
  return db.transaction(STORE_NAME, mode).objectStore(STORE_NAME)
}

export async function saveTransaction(tx: OfflineTransaction): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const store = txStore(db, 'readwrite')
    const req = store.put(tx)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error)
  })
}

export async function getPendingTransactions(): Promise<OfflineTransaction[]> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const store = txStore(db, 'readonly')
    const index = store.index('syncStatus')
    const req = index.getAll('pending')
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

export async function getAllTransactions(): Promise<OfflineTransaction[]> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const store = txStore(db, 'readonly')
    const req = store.getAll()
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

export async function markSynced(offlineId: string): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const store = txStore(db, 'readwrite')
    const getReq = store.get(offlineId)
    getReq.onsuccess = () => {
      const tx = getReq.result as OfflineTransaction | undefined
      if (tx) {
        tx.syncStatus = 'synced'
        const putReq = store.put(tx)
        putReq.onsuccess = () => resolve()
        putReq.onerror = () => reject(putReq.error)
      } else {
        resolve()
      }
    }
    getReq.onerror = () => reject(getReq.error)
  })
}

export async function markFailed(offlineId: string, error: string): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const store = txStore(db, 'readwrite')
    const getReq = store.get(offlineId)
    getReq.onsuccess = () => {
      const tx = getReq.result as OfflineTransaction | undefined
      if (tx) {
        tx.syncStatus = 'failed'
        tx.syncError = error
        const putReq = store.put(tx)
        putReq.onsuccess = () => resolve()
        putReq.onerror = () => reject(putReq.error)
      } else {
        resolve()
      }
    }
    getReq.onerror = () => reject(getReq.error)
  })
}

export async function getPendingCount(): Promise<number> {
  const pending = await getPendingTransactions()
  return pending.length
}

export async function clearSyncedTransactions(): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const store = txStore(db, 'readwrite')
    const index = store.index('syncStatus')
    const req = index.openCursor('synced')
    req.onsuccess = () => {
      const cursor = req.result
      if (cursor) {
        cursor.delete()
        cursor.continue()
      } else {
        resolve()
      }
    }
    req.onerror = () => reject(req.error)
  })
}
