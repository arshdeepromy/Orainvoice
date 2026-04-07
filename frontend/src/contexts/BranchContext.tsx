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
import { useModules } from '@/contexts/ModuleContext'

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
  /** True when the user is a branch_admin — branch is locked and cannot be switched */
  isBranchLocked: boolean
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
  const { isEnabled } = useModules()
  const branchModuleEnabled = isEnabled('branch_management')

  const [branches, setBranches] = useState<Branch[]>([])
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(() => {
    // Initialize from localStorage so the selection survives page refresh
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored && stored !== 'all' ? stored : null
  })
  const [isLoading, setIsLoading] = useState(false)
  const [, setUserBranchIds] = useState<string[]>([])

  const isBranchLocked = user?.role === 'branch_admin'

  // When branch module is disabled: reset to no-op state
  useEffect(() => {
    if (!branchModuleEnabled) {
      setBranches([])
      setSelectedBranchId(null)
      setUserBranchIds([])
      setIsLoading(false)
    }
  }, [branchModuleEnabled])

  // For branch_admin: auto-lock to assigned branch, skip fetch + validation
  useEffect(() => {
    if (!branchModuleEnabled) return
    if (!isAuthenticated || !user?.org_id || !isBranchLocked) return

    const assignedBranch = user.branch_ids?.[0] ?? null
    if (assignedBranch) {
      localStorage.setItem(STORAGE_KEY, assignedBranch)
      setSelectedBranchId(assignedBranch)
    } else {
      localStorage.removeItem(STORAGE_KEY)
      setSelectedBranchId(null)
    }
    setBranches([])
    setUserBranchIds([])
  }, [branchModuleEnabled, isAuthenticated, user?.org_id, isBranchLocked, user?.branch_ids])

  // Fetch branches when authenticated with an org (non-branch_admin only)
  useEffect(() => {
    if (!branchModuleEnabled) return

    if (!isAuthenticated || !user?.org_id || user?.role === 'global_admin' || isBranchLocked) {
      if (!isBranchLocked) {
        setBranches([])
        setUserBranchIds([])
        setSelectedBranchId(null)
      }
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

        // Validate stored selection against all accessible branches (not just user.branch_ids)
        // org_admin can access all org branches, so validate against the full branch list
        const allBranchIds = activeBranches.map((b) => b.id)
        const stored = localStorage.getItem(STORAGE_KEY)
        const validated = validateBranchSelection(stored, allBranchIds)

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
  }, [branchModuleEnabled, isAuthenticated, user?.org_id, user?.role, isBranchLocked])

  // Re-validate on API responses by adding a response interceptor (skip for branch_admin)
  useEffect(() => {
    if (!branchModuleEnabled) return
    if (!isAuthenticated || !user?.org_id || isBranchLocked) return

    const interceptorId = apiClient.interceptors.response.use(
      (response) => {
        // Check if the response contains branch_ids (e.g. from /auth/me)
        const data = response.data
        if (data && Array.isArray(data.branch_ids)) {
          const newIds: string[] = data.branch_ids
          setUserBranchIds(newIds)

          // Don't re-validate selectedBranchId against user.branch_ids here —
          // org_admin can access all org branches, not just their assigned ones.
          // The initial fetch already validated against the full branch list.
        }
        return response
      },
      (error) => Promise.reject(error),
    )

    return () => {
      apiClient.interceptors.response.eject(interceptorId)
    }
  }, [branchModuleEnabled, isAuthenticated, user?.org_id])

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
      isBranchLocked,
    }),
    [selectedBranchId, branches, selectBranch, isLoading, isBranchLocked],
  )

  return (
    <BranchContext.Provider value={value}>{children}</BranchContext.Provider>
  )
}
