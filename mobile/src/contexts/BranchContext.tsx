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
import type { Branch } from '@shared/types/branch'

export interface BranchContextValue {
  selectedBranchId: string | null
  branches: Branch[]
  selectBranch: (id: string | null) => void
  isLoading: boolean
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
  branchIds: string[],
): string | null {
  if (!storedId || storedId === 'all') return null
  if (branchIds.includes(storedId)) return storedId
  return null
}

export function BranchProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth()
  const { isModuleEnabled } = useModules()
  const branchModuleEnabled = isModuleEnabled('branch_management')

  const [branches, setBranches] = useState<Branch[]>([])
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(
    () => {
      const stored = localStorage.getItem(STORAGE_KEY)
      return stored && stored !== 'all' ? stored : null
    },
  )
  const [isLoading, setIsLoading] = useState(false)

  const isBranchLocked = user?.role === 'branch_admin' || user?.role === 'manager'

  // When branch module is disabled: reset to no-op state
  useEffect(() => {
    if (!branchModuleEnabled) {
      setBranches([])
      setSelectedBranchId(null)
      setIsLoading(false)
    }
  }, [branchModuleEnabled])

  // For branch_admin: auto-lock to assigned branch
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
  }, [branchModuleEnabled, isAuthenticated, user?.org_id, isBranchLocked, user?.branch_ids])

  // Fetch branches when authenticated with an org (non-branch_admin only)
  useEffect(() => {
    if (!branchModuleEnabled) return
    if (
      !isAuthenticated ||
      !user?.org_id ||
      user?.role === 'global_admin' ||
      isBranchLocked
    ) {
      if (!isBranchLocked) {
        setBranches([])
        setSelectedBranchId(null)
      }
      return
    }

    const controller = new AbortController()

    const fetchBranches = async () => {
      setIsLoading(true)
      try {
        const res = await apiClient.get<{ branches: Branch[] }>(
          '/org/branches',
          { signal: controller.signal },
        )
        const branchList = res.data?.branches ?? []
        const activeBranches = branchList.filter((b) => b.is_active)
        setBranches(activeBranches)

        // Validate stored selection against all accessible branches
        const allBranchIds = activeBranches.map((b) => b.id)
        const stored = localStorage.getItem(STORAGE_KEY)
        const validated = validateBranchSelection(stored, allBranchIds)

        if (stored && stored !== 'all' && validated === null) {
          localStorage.removeItem(STORAGE_KEY)
        }

        setSelectedBranchId(validated)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          // Silently fail — branches will be empty
        }
      } finally {
        setIsLoading(false)
      }
    }

    fetchBranches()
    return () => controller.abort()
  }, [branchModuleEnabled, isAuthenticated, user?.org_id, user?.role, isBranchLocked])

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
