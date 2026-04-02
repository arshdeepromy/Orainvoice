import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from 'react'
import type { ReactNode } from 'react'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'

/* ── Types ── */

export interface Branch {
  id: string
  name: string
  address: string | null
  phone: string | null
  is_active: boolean
}

export interface BranchContextValue {
  selectedBranchId: string | null // null = "All Branches"
  branches: Branch[]
  selectBranch: (id: string | null) => void
  isLoading: boolean
}

const STORAGE_KEY = 'selected_branch_id'

const BranchContext = createContext<BranchContextValue | null>(null)

export function useBranch(): BranchContextValue {
  const ctx = useContext(BranchContext)
  if (!ctx) throw new Error('useBranch must be used within BranchProvider')
  return ctx
}

/**
 * Validate a stored branch_id against the user's accessible branch IDs.
 * Returns the id if valid, or null if stale/invalid.
 */
export function validateBranchSelection(
  storedId: string | null,
  userBranchIds: string[],
): string | null {
  if (!storedId || storedId === 'all') return null
  if (userBranchIds.includes(storedId)) return storedId
  return null
}

export function BranchProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth()
  const [branches, setBranches] = useState<Branch[]>([])
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [, setUserBranchIds] = useState<string[]>([])

  // Fetch branches when authenticated with an org
  useEffect(() => {
    if (!isAuthenticated || !user?.org_id || user?.role === 'global_admin') {
      setBranches([])
      setUserBranchIds([])
      setSelectedBranchId(null)
      return
    }

    const controller = new AbortController()

    const fetchBranches = async () => {
      setIsLoading(true)
      try {
        const [branchRes, meRes] = await Promise.all([
          apiClient.get<{ branches: Branch[] }>('/org/branches', {
            signal: controller.signal,
          }),
          apiClient.get<{ branch_ids?: string[] }>('/auth/me', {
            signal: controller.signal,
          }),
        ])

        const branchList = branchRes.data?.branches ?? []
        const activeBranches = branchList.filter((b) => b.is_active)
        setBranches(activeBranches)

        const ids: string[] = meRes.data?.branch_ids ?? []
        setUserBranchIds(ids)

        // Validate stored selection against user's branch_ids
        const stored = localStorage.getItem(STORAGE_KEY)
        const validated = validateBranchSelection(stored, ids)

        if (stored && stored !== 'all' && validated === null) {
          // Stale — remove from localStorage
          localStorage.removeItem(STORAGE_KEY)
        }

        setSelectedBranchId(validated)
      } catch (err: unknown) {
        if (!(err as { name?: string })?.name?.includes('Cancel')) {
          // Silently fail — branches will be empty
        }
      } finally {
        setIsLoading(false)
      }
    }

    fetchBranches()
    return () => controller.abort()
  }, [isAuthenticated, user?.org_id, user?.role])

  // Re-validate on API responses by adding a response interceptor
  useEffect(() => {
    if (!isAuthenticated || !user?.org_id) return

    const interceptorId = apiClient.interceptors.response.use(
      (response) => {
        // Check if the response contains branch_ids (e.g. from /auth/me)
        const data = response.data
        if (data && Array.isArray(data.branch_ids)) {
          const newIds: string[] = data.branch_ids
          setUserBranchIds(newIds)

          // Re-validate current selection
          setSelectedBranchId((prev) => {
            const validated = validateBranchSelection(prev, newIds)
            if (prev !== null && validated === null) {
              localStorage.removeItem(STORAGE_KEY)
            }
            return validated
          })
        }
        return response
      },
      (error) => Promise.reject(error),
    )

    return () => {
      apiClient.interceptors.response.eject(interceptorId)
    }
  }, [isAuthenticated, user?.org_id])

  const selectBranch = useCallback((id: string | null) => {
    if (id === null || id === 'all') {
      localStorage.removeItem(STORAGE_KEY)
      setSelectedBranchId(null)
    } else {
      localStorage.setItem(STORAGE_KEY, id)
      setSelectedBranchId(id)
    }
  }, [])

  const value = useMemo<BranchContextValue>(
    () => ({
      selectedBranchId,
      branches,
      selectBranch,
      isLoading,
    }),
    [selectedBranchId, branches, selectBranch, isLoading],
  )

  return (
    <BranchContext.Provider value={value}>{children}</BranchContext.Provider>
  )
}
