/**
 * IndexedDB wrapper for offline caching of invoices, customers, and vehicles.
 * Provides typed get/put/getAll/delete/clear operations per store.
 */

const DB_NAME = 'workshoppro-offline'
const DB_VERSION = 1

export type StoreName = 'invoices' | 'customers' | 'vehicles' | 'pendingSync'

export interface PendingSyncItem {
  id: string
  store: 'invoices' | 'customers' | 'vehicles'
  action: 'create' | 'update'
  data: Record<string, unknown>
  createdAt: string
  /** Server version at time of local save (for conflict detection) */
  serverVersion?: number
}

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)

    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains('invoices')) {
        db.createObjectStore('invoices', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('customers')) {
        db.createObjectStore('customers', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('vehicles')) {
        db.createObjectStore('vehicles', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('pendingSync')) {
        db.createObjectStore('pendingSync', { keyPath: 'id' })
      }
    }

    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

export async function getItem<T>(store: StoreName, key: string): Promise<T | undefined> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readonly')
    const req = tx.objectStore(store).get(key)
    req.onsuccess = () => resolve(req.result as T | undefined)
    req.onerror = () => reject(req.error)
  })
}

export async function putItem<T>(store: StoreName, value: T): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite')
    tx.objectStore(store).put(value)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

export async function getAllItems<T>(store: StoreName): Promise<T[]> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readonly')
    const req = tx.objectStore(store).getAll()
    req.onsuccess = () => resolve(req.result as T[])
    req.onerror = () => reject(req.error)
  })
}

export async function deleteItem(store: StoreName, key: string): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite')
    tx.objectStore(store).delete(key)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

export async function clearStore(store: StoreName): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite')
    tx.objectStore(store).clear()
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

/**
 * Cache a batch of records from the server into a local store.
 * Used to pre-populate the offline cache while online.
 */
export async function cacheRecords<T>(store: StoreName, records: T[]): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite')
    const objectStore = tx.objectStore(store)
    for (const record of records) {
      objectStore.put(record)
    }
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}
